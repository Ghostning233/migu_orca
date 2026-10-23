"""Batch occupation scope and resource-level exclusion (issue #248).

#223 excluded *every* single tracking write while a batch ran.  #248 narrows the
exclusion to the resources the batch actually occupies:

* an **external write** on a record the batch owns queues behind the batch (and
  is refused with ``connection_in_use`` when the wait budget is exhausted);
* an external write on an unrelated record, or in another storage profile, is
  not blocked at all;
* pure-local record writes (revalidate/check/handoff) never wait for the batch —
  the per-record lock plus CAS keeps them honest.

These pin the repository half of that contract; the HTTP guard is covered by
``tests/api_contract/test_tracking_batch_exclusion_narrowing.py``.
"""
from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

import storage_engine.controllers.tracking_repository as tracking_repository
from shared.errors import Stage1Error
from storage_engine.controllers.storage_config import StorageConfig, load_storage_config
from storage_engine.controllers.tracking_repository import (
    compare_and_swap_tracking_record,
    ensure_tracking_record,
    lock_tracking_record,
    note_request_storage_dir,
    tracking_batch_lease,
    tracking_batch_scope,
)
from tracking_engine.models.tracking import (
    TRACKING_STATUS_ACTIVE,
    TrackingRecord,
    create_external_tracking_record,
)

REF = "11111111-1111-4111-8111-111111111111"


@pytest.fixture(autouse=True)
def _fast_batch_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracking_repository, "_BATCH_WAIT_SECONDS", 0.05)


@pytest.fixture()
def config(tmp_path: Path) -> StorageConfig:
    return load_storage_config(tmp_path / "storage")


def _seed(config: StorageConfig, index: int) -> TrackingRecord:
    record = create_external_tracking_record(
        adapter="legacy_3_1",
        object_kind="subscription",
        external_id=f"sub-{index}",
        subscription_id=f"sub-{index}",
        title=f"Show {index}",
        season=1,
        connection_ref=REF,
    )
    seeded, _created = ensure_tracking_record(config, replace(record, status=TRACKING_STATUS_ACTIVE))
    return seeded


def _hold_scope(
    *,
    tracking_ids: set[str],
    storage_dir: str | None,
    connection_ref: str | None = REF,
) -> tuple[threading.Event, threading.Event, threading.Thread]:
    entered = threading.Event()
    release = threading.Event()

    def run() -> None:
        with tracking_batch_lease(
            batch_key="scope-batch",
            tracking_ids=tracking_ids,
            connection_ref=connection_ref,
            storage_dir=storage_dir,
        ):
            entered.set()
            assert release.wait(timeout=10)

    thread = threading.Thread(target=run)
    thread.start()
    assert entered.wait(timeout=10)
    return entered, release, thread


def test_scope_is_published_only_while_the_batch_runs(config: StorageConfig) -> None:
    assert tracking_batch_scope() is None

    _entered, release, thread = _hold_scope(
        tracking_ids={"trk_a", "trk_b"}, storage_dir=str(config.storage_dir)
    )
    try:
        scope = tracking_batch_scope()
        assert scope is not None
        assert scope.tracking_ids == frozenset({"trk_a", "trk_b"})
        assert scope.connection_ref == REF
        assert scope.storage_dir == str(config.storage_dir)
    finally:
        release.set()
        thread.join(timeout=10)

    assert tracking_batch_scope() is None


def test_scope_is_released_after_a_failed_batch(config: StorageConfig) -> None:
    with pytest.raises(RuntimeError), tracking_batch_lease(
        batch_key="failing-batch", tracking_ids={"trk_a"}, storage_dir=str(config.storage_dir)
    ):
        raise RuntimeError("boom")

    assert tracking_batch_scope() is None
    # The store is usable again.
    with tracking_batch_lease(batch_key="after-failure"):
        pass


def test_external_write_on_an_owned_record_queues_behind_the_batch(
    config: StorageConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A real queue (not a refusal) needs a wait budget longer than the assertion.
    monkeypatch.setattr(tracking_repository, "_BATCH_WAIT_SECONDS", 5.0)
    seeded = _seed(config, 1)
    _entered, release, thread = _hold_scope(
        tracking_ids={seeded.tracking_id}, storage_dir=str(config.storage_dir)
    )
    done = threading.Event()
    started = threading.Event()

    def attempt() -> None:
        started.set()
        with lock_tracking_record(seeded.tracking_id):
            done.set()

    worker = threading.Thread(target=attempt)
    worker.start()
    assert started.wait(timeout=5), "the external write never started"
    try:
        # Queued: the batch owns that record's external-write resource.
        assert not done.wait(timeout=0.3), "the external write did not wait for the batch"
    finally:
        release.set()
        thread.join(timeout=10)
    assert done.wait(timeout=10)
    worker.join(timeout=10)


def test_external_write_on_an_unowned_record_is_not_blocked(config: StorageConfig) -> None:
    owned = _seed(config, 1)
    other = _seed(config, 2)
    _entered, release, thread = _hold_scope(
        tracking_ids={owned.tracking_id}, storage_dir=str(config.storage_dir)
    )
    try:
        entered = threading.Event()

        def attempt() -> None:
            with lock_tracking_record(other.tracking_id):
                entered.set()

        worker = threading.Thread(target=attempt)
        worker.start()
        assert entered.wait(timeout=2), "an unrelated record must not wait for the batch"
        # The batch is still running while the unrelated write completed.
        assert tracking_batch_scope() is not None
        worker.join(timeout=5)
    finally:
        release.set()
        thread.join(timeout=10)


def test_pure_local_record_write_does_not_wait_for_the_batch(config: StorageConfig) -> None:
    owned = _seed(config, 1)
    _entered, release, thread = _hold_scope(
        tracking_ids={owned.tracking_id}, storage_dir=str(config.storage_dir)
    )
    try:
        started = time.monotonic()
        compare_and_swap_tracking_record(
            config,
            owned.tracking_id,
            owned.revision,
            replace(owned, revision=owned.revision + 1),
        )
        elapsed = time.monotonic() - started
        assert elapsed < 1.0, "a pure-local record write must not wait for the batch"
    finally:
        release.set()
        thread.join(timeout=10)


def test_external_write_is_refused_when_the_wait_budget_is_exhausted(config: StorageConfig) -> None:
    seeded = _seed(config, 1)
    _entered, release, thread = _hold_scope(
        tracking_ids={seeded.tracking_id}, storage_dir=str(config.storage_dir)
    )
    try:
        with pytest.raises(Stage1Error) as failure, lock_tracking_record(seeded.tracking_id):
            pass
        assert failure.value.error_type == "connection_in_use"
    finally:
        release.set()
        thread.join(timeout=10)


def test_unknown_scope_keeps_the_fail_safe_exclusion(config: StorageConfig) -> None:
    """A batch that publishes no resources keeps #223's blanket exclusion."""
    seeded = _seed(config, 1)
    _entered, release, thread = _hold_scope(tracking_ids=set(), storage_dir=None)
    try:
        with pytest.raises(Stage1Error) as failure, lock_tracking_record(seeded.tracking_id):
            pass
        assert failure.value.error_type == "connection_in_use"
    finally:
        release.set()
        thread.join(timeout=10)


def test_a_local_write_never_waits_even_when_the_batch_owns_its_record(
    config: StorageConfig,
) -> None:
    owned = _seed(config, 1)
    _entered, release, thread = _hold_scope(
        tracking_ids={owned.tracking_id}, storage_dir=str(config.storage_dir)
    )
    try:
        done = threading.Event()

        def attempt() -> None:
            compare_and_swap_tracking_record(
                config,
                owned.tracking_id,
                owned.revision,
                replace(owned, revision=owned.revision + 1),
            )
            done.set()

        worker = threading.Thread(target=attempt)
        worker.start()
        assert done.wait(timeout=2), "a pure-local write must not wait for the batch"
        worker.join(timeout=5)
    finally:
        release.set()
        thread.join(timeout=10)


def test_a_batch_cannot_start_inside_an_external_write_critical_section(
    config: StorageConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B1 (#248): the #247 lock order and pre-intent refusal must hold.

    A single external write holds the store lock for its bind+pointer critical
    section even when no batch is active, so a batch starting at that moment
    waits; the nested record write must never try to re-take the store lock while
    holding the record lock (that would reverse the order and refuse a write
    whose intent is already persisted).
    """
    seeded = _seed(config, 1)
    monkeypatch.setattr(tracking_repository, "_BATCH_WAIT_SECONDS", 5.0)
    inside = threading.Event()
    finish = threading.Event()
    batch_acquired = threading.Event()

    def single_write() -> None:
        with lock_tracking_record(seeded.tracking_id):
            inside.set()
            assert finish.wait(timeout=10)
            # A nested record write inside the critical section (the bind ->
            # pointer CAS the #247 services perform) must succeed.
            compare_and_swap_tracking_record(
                config,
                seeded.tracking_id,
                seeded.revision,
                replace(seeded, revision=seeded.revision + 1),
            )

    worker = threading.Thread(target=single_write)
    worker.start()
    assert inside.wait(timeout=10)

    def start_batch() -> None:
        with tracking_batch_lease(
            batch_key="late-batch",
            tracking_ids={seeded.tracking_id},
            storage_dir=str(config.storage_dir),
        ):
            batch_acquired.set()

    batch_thread = threading.Thread(target=start_batch)
    batch_thread.start()
    try:
        # The batch must wait for the single write's critical section.
        assert not batch_acquired.wait(timeout=0.3), "the batch entered mid critical section"
    finally:
        finish.set()
        worker.join(timeout=10)
    assert batch_acquired.wait(timeout=10)
    batch_thread.join(timeout=10)


def test_a_same_id_record_in_another_profile_is_not_blocked(
    config: StorageConfig, tmp_path: Path
) -> None:
    """I2 (#248): the final gate must use the request's profile, not just the id."""
    owned = _seed(config, 1)
    other_profile = load_storage_config(tmp_path / "other")
    # Same deterministic tracking id in two profiles.
    other_record = create_external_tracking_record(
        adapter="legacy_3_1",
        object_kind="subscription",
        external_id="sub-other",
        subscription_id="sub-other",
        title="Other profile",
        season=1,
        connection_ref=REF,
    )
    other, _created = ensure_tracking_record(
        other_profile,
        replace(
            other_record,
            tracking_id=owned.tracking_id,
            status=TRACKING_STATUS_ACTIVE,
        ),
    )
    _entered, release, thread = _hold_scope(
        tracking_ids={owned.tracking_id}, storage_dir=str(config.storage_dir)
    )
    try:
        entered = threading.Event()

        def attempt() -> None:
            # A request thread publishes its own profile; the worker plays that
            # role here.
            note_request_storage_dir(str(other_profile.storage_dir))
            with lock_tracking_record(other.tracking_id):
                entered.set()

        worker = threading.Thread(target=attempt)
        worker.start()
        assert entered.wait(timeout=2), "another profile must not be blocked by the batch"
        worker.join(timeout=5)
    finally:
        release.set()
        thread.join(timeout=10)


def test_a_queued_write_proceeds_when_the_batch_crashes_inside_the_gate(
    config: StorageConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#248: a batch that raises inside its lease must release the waiter."""
    monkeypatch.setattr(tracking_repository, "_BATCH_WAIT_SECONDS", 5.0)
    seeded = _seed(config, 1)
    entered = threading.Event()
    crashed = threading.Event()

    def failing_batch() -> None:
        try:
            with tracking_batch_lease(
                batch_key="crashing-batch",
                tracking_ids={seeded.tracking_id},
                storage_dir=str(config.storage_dir),
            ):
                entered.set()
                raise RuntimeError("batch crashed")
        except RuntimeError:
            crashed.set()

    batch_thread = threading.Thread(target=failing_batch)
    batch_thread.start()
    assert entered.wait(timeout=10)
    batch_thread.join(timeout=10)
    assert crashed.is_set()
    assert tracking_batch_scope() is None

    # The queued write now proceeds instead of failing closed.
    done = threading.Event()

    def attempt() -> None:
        with lock_tracking_record(seeded.tracking_id):
            done.set()

    worker = threading.Thread(target=attempt)
    worker.start()
    assert done.wait(timeout=5), "the waiter must proceed after the batch crashed"
    worker.join(timeout=5)
