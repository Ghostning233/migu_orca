"""Batch delete service tests (issue #223, ADR-0007).

These pin the parts a contract test cannot see: sequential execution, the
batch-level exclusion, per-entry execution-time revalidation, the "external
failure keeps that entry's local data" rule, replay/resume idempotency and the
status query.
"""
from __future__ import annotations

import contextlib
import json
import threading
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import apps.migu_orca_web.services as web_services
import apps.migu_orca_web.tracking_batch_delete_service as batch_delete
import apps.migu_orca_web.tracking_management_service as management_service
import apps.migu_orca_web.tracking_saved_management_service as saved_management
import storage_engine.controllers.tracking_repository as tracking_repository
from ab_engine.models.management import AutoBangumiCapabilities, ExternalSubscription
from apps.migu_orca_web.schemas import (
    SavedTrackingBatchDeleteExternalInput,
    SavedTrackingBatchDeleteInput,
    SavedTrackingBatchDeleteItem,
    SavedTrackingPlanDeleteInput,
)
from apps.migu_orca_web.tracking_plan_delete_service import _IN_FLIGHT_OPERATION_STATES, run_saved_tracking_plan_delete
from shared.errors import Stage1Error
from storage_engine.controllers.autobangumi_config_repository import (
    AutoBangumiConfigRepository,
    build_stored_autobangumi_config,
)
from storage_engine.controllers.operation_repository import (
    bind_tracking_operation,
    compare_and_swap_tracking_operation,
    load_tracking_operation,
)
from storage_engine.controllers.storage_config import StorageConfig, load_storage_config
from storage_engine.controllers.tracking_repository import (
    compare_and_swap_tracking_record,
    ensure_tracking_record,
    load_tracking_record,
    tracking_batch_lease,
)
from tracking_engine.models.operation import (
    tracking_operation_id_for_idempotency_key,
    transition_tracking_operation,
)
from tracking_engine.models.tracking import (
    TRACKING_STATUS_ACTIVE,
    TrackingRecord,
    create_external_tracking_record,
)

REF = "11111111-1111-4111-8111-111111111111"


class _FakeAb:
    """Offline 3.1.18 management surface with an explicit call log."""

    def __init__(self, *, fail_on: set[str] | None = None, unknown_on: set[str] | None = None) -> None:
        self.deleted: list[str] = []
        self.calls: list[str] = []
        self.fail_on = fail_on or set()
        self.unknown_on = unknown_on or set()
        self._unknown_seen: set[str] = set()
        self._in_flight = 0
        self.max_in_flight = 0
        self.gate: threading.Event | None = None
        self.entered = threading.Event()
        self.subscriptions = [ExternalSubscription(f"sub-{index}", f"Show {index}", 1, "Group") for index in range(1, 6)]
        self.capabilities = AutoBangumiCapabilities(
            probe_status="VERIFIED", version="3.1.18", adapter="legacy_3_1",
            subscription_list="SUPPORTED", subscription_detail="SUPPORTED",
            subscription_modify="SUPPORTED", subscription_enable="SUPPORTED",
            subscription_disable="SUPPORTED", subscription_delete="SUPPORTED",
            rss_list="SUPPORTED", rss_modify="SUPPORTED", rss_enable="SUPPORTED",
            rss_disable="SUPPORTED", rss_delete="SUPPORTED", rss_refresh="SUPPORTED",
        )

    def read_snapshot(self, *, deadline: float | None = None) -> Any:
        self.calls.append("read")
        # Simulate an unreadable readback: the previous delete succeeded but the
        # confirming snapshot is gone, which is exactly an unknown outcome.
        if self.unknown_on and self._unknown_seen & self.unknown_on:
            raise Stage1Error("ab_timeout", "外部读取失败", "read_snapshot")
        return self.capabilities, list(self.subscriptions), []

    def delete_subscription(self, ident: str) -> dict[str, int]:
        self.calls.append(f"delete:{ident}")
        self._in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            if self.gate is not None:
                self.entered.set()
                assert self.gate.wait(timeout=10), "batch gate was never released"
            if ident in self.fail_on:
                raise Stage1Error("ab_http_failed", "外部删除失败", "delete_subscription")
            if ident in self.unknown_on:
                self._unknown_seen.add(ident)
            self.deleted.append(ident)
            self.subscriptions = [item for item in self.subscriptions if item.external_id != ident]
            return {"status_code": 200}
        finally:
            self._in_flight -= 1


@pytest.fixture(autouse=True)
def _fast_batch_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the bounded "later side waits" seam short inside the test suite."""
    monkeypatch.setattr(tracking_repository, "_BATCH_WAIT_SECONDS", 0.05)


@pytest.fixture()
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[StorageConfig, Any]]:
    """Isolated business storage + AB config roots for the external leg."""
    storage_root = tmp_path / "storage"
    config_root = tmp_path / "config"
    saved = AutoBangumiConfigRepository(config_root).save(
        build_stored_autobangumi_config({
            "auth_mode": "password", "base_url": "http://ab.invalid",
            "username": "operator", "password": "secret-password",
        }),
        expected_configuration_revision=0,
    )
    monkeypatch.setenv("MIGU_ORCA_WEB_CONFIG_ROOT", str(config_root))
    web_services.set_web_storage_root(storage_root)
    try:
        yield load_storage_config(storage_root), saved
    finally:
        web_services.set_web_storage_root(None)


def _seed_record(
    config: StorageConfig, index: int, *, connection_ref: str | None = None
) -> TrackingRecord:
    record = create_external_tracking_record(
        adapter="legacy_3_1",
        object_kind="subscription",
        external_id=f"sub-{index}",
        subscription_id=f"sub-{index}",
        title=f"Show {index}",
        season=1,
        connection_ref=connection_ref,
    )
    record, _created = ensure_tracking_record(config, replace(record, status=TRACKING_STATUS_ACTIVE))
    return record


def _install_fake(monkeypatch: pytest.MonkeyPatch, fake: _FakeAb) -> None:
    monkeypatch.setattr(saved_management, "create_management_client", lambda _runtime: fake)


def _local_payload(records: list[TrackingRecord], key: str = "batch-delete-1") -> SavedTrackingBatchDeleteInput:
    return SavedTrackingBatchDeleteInput(
        items=[
            SavedTrackingBatchDeleteItem(tracking_id=record.tracking_id, expected_revision=record.revision)
            for record in records
        ],
        confirm=True,
        idempotency_key=key,
    )


def _external_payload(
    records: list[TrackingRecord], saved: Any, key: str = "batch-delete-external-1"
) -> SavedTrackingBatchDeleteExternalInput:
    return SavedTrackingBatchDeleteExternalInput(
        items=[
            SavedTrackingBatchDeleteItem(tracking_id=record.tracking_id, expected_revision=record.revision)
            for record in records
        ],
        confirm=True,
        idempotency_key=key,
        connection_ref=str(saved.connection_ref),
        configuration_revision=saved.configuration_revision,
    )


def test_local_only_batch_deletes_plans_without_any_external_write(
    roots: tuple[StorageConfig, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC3/AC7: the local-only batch never reaches Auto Bangumi."""
    config, saved = roots
    fake = _FakeAb()
    _install_fake(monkeypatch, fake)
    records = [_seed_record(config, index, connection_ref=str(saved.connection_ref)) for index in (1, 2, 3)]

    result = batch_delete.run_saved_tracking_batch_delete(
        config, payload=_local_payload(records), delete_external=False
    )

    assert result["kind"] == batch_delete.KIND_LOCAL_ONLY
    assert result["state"] == batch_delete.STATE_COMPLETED
    assert [item["outcome"] for item in result["items"]] == ["DELETED", "DELETED", "DELETED"]
    assert result["summary"] == {
        "total": 3, "deleted": 3, "external_deleted": 0, "skipped": 0, "failed": 0, "unknown": 0,
    }
    assert fake.calls == [], "a local-only delete must never contact Auto Bangumi"
    # AC7: the mapped subscriptions keep running in Auto Bangumi (MiGuOrca only
    # stops managing them), so the external surface is byte-identical.
    assert {item.external_id for item in fake.subscriptions} >= {"sub-1", "sub-2", "sub-3"}
    for record in records:
        with pytest.raises(Stage1Error) as failure:
            load_tracking_record(config, record.tracking_id)
        assert failure.value.error_type == "tracking_not_found"


def test_external_batch_deletes_each_subscription_then_its_local_record_sequentially(
    roots: tuple[StorageConfig, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC1/AC5: entries run one after another, never concurrently."""
    config, saved = roots
    fake = _FakeAb()
    _install_fake(monkeypatch, fake)
    records = [_seed_record(config, index, connection_ref=str(saved.connection_ref)) for index in (1, 2, 3)]

    result = batch_delete.run_saved_tracking_batch_delete(
        config, payload=_external_payload(records, saved), delete_external=True
    )

    assert result["kind"] == batch_delete.KIND_LOCAL_AND_EXTERNAL
    assert [item["outcome"] for item in result["items"]] == ["DELETED", "DELETED", "DELETED"]
    assert [item["external_deleted"] for item in result["items"]] == [True, True, True]
    # Payload order is the execution order and no two writes overlapped.
    assert [call for call in fake.calls if call.startswith("delete:")] == [
        "delete:sub-1", "delete:sub-2", "delete:sub-3",
    ]
    assert fake.max_in_flight == 1, "batch external deletes must be sequential"
    assert result["summary"]["external_deleted"] == 3
    for record in records:
        with pytest.raises(Stage1Error):
            load_tracking_record(config, record.tracking_id)


def test_external_failure_keeps_that_entry_local_and_continues_the_batch(
    roots: tuple[StorageConfig, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC3: a failed external delete removes nothing local for that entry."""
    config, saved = roots
    fake = _FakeAb(fail_on={"sub-2"})
    _install_fake(monkeypatch, fake)
    records = [_seed_record(config, index, connection_ref=str(saved.connection_ref)) for index in (1, 2, 3)]

    result = batch_delete.run_saved_tracking_batch_delete(
        config, payload=_external_payload(records, saved), delete_external=True
    )

    by_id = {item["tracking_id"]: item for item in result["items"]}
    failed = by_id[records[1].tracking_id]
    assert failed["outcome"] == "EXTERNAL_FAILED"
    assert failed["external_deleted"] is False
    # The failed entry keeps its plan, record and mapping.
    kept = load_tracking_record(config, records[1].tracking_id)
    assert kept.external_mapping is not None
    # The other entries finished normally.
    assert by_id[records[0].tracking_id]["outcome"] == "DELETED"
    assert by_id[records[2].tracking_id]["outcome"] == "DELETED"
    assert result["summary"]["failed"] == 1
    assert result["summary"]["deleted"] == 2


def test_unknown_external_outcome_keeps_that_entry_and_reports_unknown(
    roots: tuple[StorageConfig, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC3: an unknown external result is never reported as a delete."""
    config, saved = roots
    fake = _FakeAb(unknown_on={"sub-2"})
    _install_fake(monkeypatch, fake)
    records = [_seed_record(config, index, connection_ref=str(saved.connection_ref)) for index in (1, 2)]

    result = batch_delete.run_saved_tracking_batch_delete(
        config, payload=_external_payload(records, saved), delete_external=True
    )

    by_id = {item["tracking_id"]: item for item in result["items"]}
    unknown = by_id[records[1].tracking_id]
    assert unknown["outcome"] == "EXTERNAL_UNKNOWN"
    assert unknown["external_deleted"] is False
    load_tracking_record(config, records[1].tracking_id)
    assert result["summary"]["unknown"] == 1


def test_unresolved_entry_is_skipped_with_a_reason_never_abandoned(
    roots: tuple[StorageConfig, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC4/AC8: an unresolved entry is excluded and explained, not deleted."""
    config, saved = roots
    fake = _FakeAb()
    _install_fake(monkeypatch, fake)
    record = _seed_record(config, 1, connection_ref=str(saved.connection_ref))
    operation, _created = bind_tracking_operation(
        config,
        tracking_id=record.tracking_id,
        operation="SUBMIT",
        idempotency_key="pending-submit-key",
        expected_revision=record.revision,
        request_fingerprint="fingerprint",
    )
    guarded = compare_and_swap_tracking_record(
        config,
        record.tracking_id,
        record.revision,
        replace(
            record,
            current_operation_id=operation.operation_id,
            revision=record.revision + 1,
        ),
    )

    result = batch_delete.run_saved_tracking_batch_delete(
        config,
        payload=_local_payload([guarded], key="batch-unresolved"),
        delete_external=False,
    )

    item = result["items"][0]
    assert item["outcome"] == "SKIPPED"
    assert item["skip_reason"] == batch_delete.SKIP_UNRESOLVED
    assert result["summary"]["skipped"] == 1
    # Nothing was deleted and no abandon was attempted.
    kept = load_tracking_record(config, record.tracking_id)
    assert kept.current_operation_id == operation.operation_id
    assert fake.calls == []


def test_changed_revision_and_missing_records_are_skipped_with_reasons(
    roots: tuple[StorageConfig, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC8: eligibility is re-verified at execution time, per entry."""
    config, saved = roots
    _install_fake(monkeypatch, _FakeAb())
    record = _seed_record(config, 1, connection_ref=str(saved.connection_ref))
    stale = SavedTrackingBatchDeleteItem(tracking_id=record.tracking_id, expected_revision=record.revision + 5)
    missing = SavedTrackingBatchDeleteItem(tracking_id="trk_missing", expected_revision=1)
    payload = SavedTrackingBatchDeleteInput(
        items=[stale, missing], confirm=True, idempotency_key="batch-stale"
    )

    result = batch_delete.run_saved_tracking_batch_delete(
        config, payload=payload, delete_external=False
    )

    assert [item["skip_reason"] for item in result["items"]] == [
        batch_delete.SKIP_REVISION_CHANGED,
        batch_delete.SKIP_NOT_FOUND,
    ]
    assert result["summary"]["deleted"] == 0
    assert result["summary"]["skipped"] == 2
    assert load_tracking_record(config, record.tracking_id).revision == record.revision


def test_replay_of_the_same_key_returns_the_stored_result_without_new_writes(
    roots: tuple[StorageConfig, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC9: a same-key replay never repeats an external write."""
    config, saved = roots
    fake = _FakeAb()
    _install_fake(monkeypatch, fake)
    records = [_seed_record(config, index, connection_ref=str(saved.connection_ref)) for index in (1, 2)]
    payload = _external_payload(records, saved, key="batch-replay")

    first = batch_delete.run_saved_tracking_batch_delete(config, payload=payload, delete_external=True)
    writes_after_first = list(fake.calls)
    second = batch_delete.run_saved_tracking_batch_delete(config, payload=payload, delete_external=True)

    assert second == first
    assert fake.calls == writes_after_first, "a replay must not call Auto Bangumi again"


def test_same_key_bound_to_different_entries_is_a_conflict(
    roots: tuple[StorageConfig, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    config, saved = roots
    _install_fake(monkeypatch, _FakeAb())
    records = [_seed_record(config, index, connection_ref=str(saved.connection_ref)) for index in (1, 2)]
    batch_delete.run_saved_tracking_batch_delete(
        config, payload=_external_payload([records[0]], saved, key="batch-conflict"), delete_external=True
    )

    with pytest.raises(Stage1Error) as failure:
        batch_delete.run_saved_tracking_batch_delete(
            config, payload=_external_payload([records[1]], saved, key="batch-conflict"), delete_external=True
        )
    assert failure.value.error_type == "idempotency_conflict"


def test_a_second_batch_is_refused_while_one_runs(
    roots: tuple[StorageConfig, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC9: two batches never run at the same time."""
    config, saved = roots
    fake = _FakeAb()
    fake.gate = threading.Event()
    _install_fake(monkeypatch, fake)
    first_records = [_seed_record(config, 1, connection_ref=str(saved.connection_ref))]
    second_records = [_seed_record(config, 2, connection_ref=str(saved.connection_ref))]
    outcome: dict[str, Any] = {}

    def run_first() -> None:
        try:
            outcome["first"] = batch_delete.run_saved_tracking_batch_delete(
                config,
                payload=_external_payload(first_records, saved, key="batch-first"),
                delete_external=True,
            )
        except BaseException as exc:  # pragma: no cover - surfaced by the assert
            outcome["error"] = exc

    thread = threading.Thread(target=run_first)
    thread.start()
    assert fake.entered.wait(timeout=10), "the first batch never reached Auto Bangumi"

    with pytest.raises(Stage1Error) as failure:
        batch_delete.run_saved_tracking_batch_delete(
            config,
            payload=_external_payload(second_records, saved, key="batch-second"),
            delete_external=True,
        )
    assert failure.value.error_type == "connection_in_use"

    fake.gate.set()
    thread.join(timeout=20)
    assert "error" not in outcome, outcome
    assert outcome["first"]["items"][0]["outcome"] == "DELETED"
    # The refused batch wrote nothing: its record is still there.
    load_tracking_record(config, second_records[0].tracking_id)


def test_a_single_write_queues_behind_a_batch_and_leaves_no_orphan_intent(
    roots: tuple[StorageConfig, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0007 + B1 + #247: the single write waits for the batch instead of failing.

    A refusal after the intent was persisted would leave a resumable operation
    that no record points at (permanent same-key conflict).  The single write is
    therefore queued: it starts no external call while the batch runs, completes
    afterwards, and its intent ends as normal history — not an orphan.  Since
    #247 the queue gate is the store lock taken *before* the binding, so a queued
    write persists nothing (not even an intent) until the batch releases the
    store.
    """
    # The product bound (10s) is intentional; this test only needs an assertion
    # window that does not depend on CI speed, so widen it for this test alone.
    monkeypatch.setattr(tracking_repository, "_BATCH_WAIT_SECONDS", 120)
    config, saved = roots
    fake = _FakeAb()
    fake.gate = threading.Event()
    _install_fake(monkeypatch, fake)
    batch_record = _seed_record(config, 1, connection_ref=str(saved.connection_ref))
    other = _seed_record(config, 2, connection_ref=str(saved.connection_ref))
    batch_outcome: dict[str, Any] = {}
    single_outcome: dict[str, Any] = {}
    single_key = "single-during-batch"

    def run_batch() -> None:
        batch_outcome["result"] = batch_delete.run_saved_tracking_batch_delete(
            config,
            payload=_external_payload([batch_record], saved, key="batch-queue"),
            delete_external=True,
        )

    batch_thread = threading.Thread(target=run_batch)
    batch_thread.start()
    assert fake.entered.wait(timeout=10), "the batch never reached Auto Bangumi"

    single_done = threading.Event()

    def run_single() -> None:
        try:
            single_outcome["result"] = run_saved_tracking_plan_delete(
                config,
                payload=SavedTrackingPlanDeleteInput(
                    tracking_id=other.tracking_id,
                    confirm=True,
                    delete_external=True,
                    idempotency_key=single_key,
                    connection_ref=str(saved.connection_ref),
                    configuration_revision=saved.configuration_revision,
                ),
            )
        except BaseException as exc:  # pragma: no cover - surfaced below
            single_outcome["error"] = exc
        single_done.set()

    # Deterministic signal: the single write reached the store gate and is
    # waiting there, before it persisted anything and before any external call.
    reached_gate = threading.Event()
    real_lock = management_service.lock_tracking_record

    @contextlib.contextmanager
    def signalling_lock(tracking_id: str):
        reached_gate.set()
        with real_lock(tracking_id):
            yield

    monkeypatch.setattr(management_service, "lock_tracking_record", signalling_lock)
    single_thread = threading.Thread(target=run_single)
    single_thread.start()
    assert reached_gate.wait(timeout=10), "the single write never reached the store gate"
    operation_id = tracking_operation_id_for_idempotency_key(single_key)
    # Nothing was persisted while queued: no intent, no orphan.
    assert not (config.tracking_operations_dir / f"{operation_id}.json").exists()
    assert not single_done.is_set(), "the single write was not serialized"
    assert single_thread.is_alive(), "the single write finished while the batch ran"
    assert "delete:sub-2" not in fake.calls

    fake.gate.set()
    batch_thread.join(timeout=20)
    assert single_done.wait(timeout=20), "the single write never completed"
    single_thread.join(timeout=20)
    assert "error" not in single_outcome, single_outcome
    assert single_outcome["result"]["outcome"] == "DELETED"
    assert batch_outcome["result"]["items"][0]["outcome"] == "DELETED"
    assert [call for call in fake.calls if call.startswith("delete:")][-1] == "delete:sub-2"

    # No orphan intent: the operation the single write persisted is finished
    # history, and the record it deleted is gone.
    operation = load_tracking_operation(
        config, tracking_operation_id_for_idempotency_key(single_key)
    )
    assert operation.state not in _IN_FLIGHT_OPERATION_STATES
    with pytest.raises(Stage1Error):
        load_tracking_record(config, other.tracking_id)


def test_status_query_returns_partial_progress_and_unknown_keys_are_not_found(
    roots: tuple[StorageConfig, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC9: a timed-out client can query the batch instead of guessing."""
    config, saved = roots
    fake = _FakeAb()
    fake.gate = threading.Event()
    _install_fake(monkeypatch, fake)
    records = [_seed_record(config, index, connection_ref=str(saved.connection_ref)) for index in (1, 2)]
    payload = _external_payload(records, saved, key="batch-query")

    thread = threading.Thread(
        target=lambda: batch_delete.run_saved_tracking_batch_delete(
            config, payload=payload, delete_external=True
        )
    )
    thread.start()
    assert fake.entered.wait(timeout=10)

    partial = batch_delete.get_saved_tracking_batch_delete(config, batch_key="batch-query")
    assert partial["state"] == batch_delete.STATE_IN_PROGRESS
    assert partial["summary"]["total"] == 2
    assert partial["items"] == []

    fake.gate.set()
    thread.join(timeout=20)
    completed = batch_delete.get_saved_tracking_batch_delete(config, batch_key="batch-query")
    assert completed["state"] == batch_delete.STATE_COMPLETED
    assert [item["outcome"] for item in completed["items"]] == ["DELETED", "DELETED"]

    with pytest.raises(Stage1Error) as failure:
        batch_delete.get_saved_tracking_batch_delete(config, batch_key="batch-unknown")
    assert failure.value.error_type == "tracking_not_found"


def test_resume_after_an_interruption_only_runs_the_unfinished_entries(
    roots: tuple[StorageConfig, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC9: a crashed batch resumes without repeating a finished external delete."""
    config, saved = roots
    fake = _FakeAb()
    _install_fake(monkeypatch, fake)
    records = [_seed_record(config, index, connection_ref=str(saved.connection_ref)) for index in (1, 2)]
    payload = _external_payload(records, saved, key="batch-resume")
    fingerprint = batch_delete._fingerprint(batch_delete.KIND_LOCAL_AND_EXTERNAL, payload.items)
    # Simulate a process that finished entry 1 and died before entry 2.
    record = {
        "version": 1,
        "batch_key": "batch-resume",
        "kind": batch_delete.KIND_LOCAL_AND_EXTERNAL,
        "fingerprint": fingerprint,
        "total": 2,
        "state": batch_delete.STATE_IN_PROGRESS,
        "items": [{
            "tracking_id": records[0].tracking_id,
            "outcome": "DELETED",
            "external_deleted": True,
            "skip_reason": None,
        }],
        "created_at": "2026-10-22T00:00:00+00:00",
        "updated_at": "2026-10-22T00:00:00+00:00",
    }
    config.idempotency_dir.mkdir(parents=True, exist_ok=True)
    (config.idempotency_dir / "tracking_batch_delete_batch-resume.json").write_text(
        json.dumps(record), encoding="utf-8"
    )

    result = batch_delete.run_saved_tracking_batch_delete(config, payload=payload, delete_external=True)

    assert [item["outcome"] for item in result["items"]] == ["DELETED", "DELETED"]
    assert [call for call in fake.calls if call.startswith("delete:")] == ["delete:sub-2"]
    assert result["state"] == batch_delete.STATE_COMPLETED


def test_batch_record_never_contains_titles_connections_or_error_text(
    roots: tuple[StorageConfig, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Security: the persisted batch record is a minimal, non-sensitive log."""
    config, saved = roots
    _install_fake(monkeypatch, _FakeAb())
    records = [_seed_record(config, 1, connection_ref=str(saved.connection_ref))]
    batch_delete.run_saved_tracking_batch_delete(
        config, payload=_external_payload(records, saved, key="batch-safe"), delete_external=True
    )

    raw = (config.idempotency_dir / "tracking_batch_delete_batch-safe.json").read_text(encoding="utf-8")
    for forbidden in ("secret-password", "http://ab.invalid", "Show 1", str(saved.connection_ref)):
        assert forbidden not in raw, forbidden


def test_lease_is_released_after_a_failed_batch(
    roots: tuple[StorageConfig, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refused/failed batch must not leave the store locked."""
    config, saved = roots
    _install_fake(monkeypatch, _FakeAb())
    record = _seed_record(config, 1, connection_ref=str(saved.connection_ref))

    with pytest.raises(Stage1Error):
        batch_delete.run_saved_tracking_batch_delete(
            config,
            payload=SavedTrackingBatchDeleteInput(
                items=[SavedTrackingBatchDeleteItem(tracking_id=record.tracking_id, expected_revision=record.revision)],
                confirm=True,
                idempotency_key="batch-invalid",  # external kind without the connection
            ),
            delete_external=True,
        )

    with tracking_batch_lease(batch_key="after-failure"):
        pass


def _operation_in_state(
    config: StorageConfig,
    record: TrackingRecord,
    state: str,
    *,
    key: str = "pending-op",
) -> Any:
    """Bind one operation for ``record`` and move it to ``state``."""
    operation, _created = bind_tracking_operation(
        config,
        tracking_id=record.tracking_id,
        operation="SUBMIT",
        idempotency_key=key,
        expected_revision=record.revision,
        request_fingerprint="fingerprint",
    )
    # Walk the legal state machine: PREPARED -> IN_PROGRESS -> outcome.
    path = {
        "PREPARED": [],
        "FAILED": ["FAILED"],
    }.get(state, ["IN_PROGRESS"] if state == "IN_PROGRESS" else ["IN_PROGRESS", state])
    for step in path:
        operation = compare_and_swap_tracking_operation(
            config,
            operation.operation_id,
            operation.state,
            transition_tracking_operation(operation, state=step),
        )
    return operation


def _point_record_at(config: StorageConfig, record: TrackingRecord, operation: Any) -> TrackingRecord:
    return compare_and_swap_tracking_record(
        config,
        record.tracking_id,
        record.revision,
        replace(
            record,
            current_operation_id=operation.operation_id,
            revision=record.revision + 1,
        ),
    )


@pytest.mark.parametrize(
    "state",
    ["PREPARED", "IN_PROGRESS", "OUTCOME_UNKNOWN", "RECOVERY_REQUIRED"],
)
def test_every_unresolved_operation_state_is_skipped_never_abandoned(
    roots: tuple[StorageConfig, Any],
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    """AC4/AC8: all four unresolved states skip with a reason and write nothing."""
    config, _saved = roots
    fake = _FakeAb()
    _install_fake(monkeypatch, fake)
    record = _seed_record(config, 1, connection_ref=REF)
    operation = _operation_in_state(config, record, state, key=f"pending-{state.lower()}")
    guarded = _point_record_at(config, record, operation)

    result = batch_delete.run_saved_tracking_batch_delete(
        config,
        payload=_local_payload([guarded], key=f"batch-{state.lower()}"),
        delete_external=False,
    )

    item = result["items"][0]
    assert item["outcome"] == "SKIPPED"
    assert item["skip_reason"] == batch_delete.SKIP_UNRESOLVED
    assert fake.calls == []
    kept = load_tracking_record(config, record.tracking_id)
    assert kept.current_operation_id == operation.operation_id


def test_a_settled_operation_does_not_block_the_delete(
    roots: tuple[StorageConfig, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finished history is not a delete lock (issue #96 semantics stay intact)."""
    config, _saved = roots
    _install_fake(monkeypatch, _FakeAb())
    record = _seed_record(config, 1, connection_ref=REF)
    operation = _operation_in_state(config, record, "SUCCEEDED", key="settled-op")
    guarded = _point_record_at(config, record, operation)

    result = batch_delete.run_saved_tracking_batch_delete(
        config, payload=_local_payload([guarded], key="batch-settled"), delete_external=False
    )

    assert result["items"][0]["outcome"] == "DELETED"
    with pytest.raises(Stage1Error):
        load_tracking_record(config, record.tracking_id)


def test_an_operation_of_another_record_is_skipped(
    roots: tuple[StorageConfig, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pointer naming another record's operation proves nothing (fail closed)."""
    config, _saved = roots
    _install_fake(monkeypatch, _FakeAb())
    record = _seed_record(config, 1, connection_ref=REF)
    other = _seed_record(config, 2, connection_ref=REF)
    foreign = _operation_in_state(config, other, "SUCCEEDED", key="foreign-op")
    # Point record 1 at record 2's operation.
    guarded = compare_and_swap_tracking_record(
        config,
        record.tracking_id,
        record.revision,
        replace(
            record,
            current_operation_id=foreign.operation_id,
            revision=record.revision + 1,
        ),
    )

    result = batch_delete.run_saved_tracking_batch_delete(
        config, payload=_local_payload([guarded], key="batch-foreign"), delete_external=False
    )

    assert result["items"][0]["skip_reason"] == batch_delete.SKIP_UNRESOLVED
    load_tracking_record(config, record.tracking_id)


def test_a_batch_is_refused_while_another_records_write_is_in_flight(
    roots: tuple[StorageConfig, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0007 decision 3, batch-as-later-side: a running single write wins."""
    config, _saved = roots
    fake = _FakeAb()
    _install_fake(monkeypatch, fake)
    busy_other = _seed_record(config, 1, connection_ref=REF)
    target = _seed_record(config, 2, connection_ref=REF)
    # A live record points at the running operation: it really can still write.
    operation = _operation_in_state(config, busy_other, "IN_PROGRESS", key="single-in-flight")
    _point_record_at(config, busy_other, operation)

    with pytest.raises(Stage1Error) as failure:
        batch_delete.run_saved_tracking_batch_delete(
            config, payload=_local_payload([target], key="batch-refused"), delete_external=False
        )

    assert failure.value.error_type == "connection_in_use"
    assert fake.calls == []
    load_tracking_record(config, target.tracking_id)


def test_inert_operation_evidence_never_blocks_a_batch(
    roots: tuple[StorageConfig, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """B1: an orphan or damaged operation file is inert, not a running write.

    Resume/execution only ever starts from ``TrackingRecord.current_operation_id``,
    so an operation nobody points at (a historical crashed bind) or an unreadable
    file cannot reach Auto Bangumi.  Treating either as "a write is running"
    would disable every batch forever with no user recovery path.
    """
    config, _saved = roots
    fake = _FakeAb()
    _install_fake(monkeypatch, fake)
    orphan_owner = _seed_record(config, 1, connection_ref=REF)
    target = _seed_record(config, 2, connection_ref=REF)
    # Orphan intents: IN_PROGRESS and PREPARED operations with no record pointer.
    _operation_in_state(config, orphan_owner, "IN_PROGRESS", key="orphan-in-flight")
    _operation_in_state(config, orphan_owner, "PREPARED", key="orphan-prepared")
    # And a damaged operation file in the same directory.
    config.tracking_operations_dir.mkdir(parents=True, exist_ok=True)
    (config.tracking_operations_dir / "damaged-operation.json").write_text(
        "{not json", encoding="utf-8"
    )

    result = batch_delete.run_saved_tracking_batch_delete(
        config, payload=_local_payload([target], key="batch-inert"), delete_external=False
    )

    assert result["items"][0]["outcome"] == "DELETED"
    with pytest.raises(Stage1Error):
        load_tracking_record(config, target.tracking_id)


def test_lease_is_released_when_the_batch_fails_inside_it(
    roots: tuple[StorageConfig, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash in the middle of a batch must not leave the store locked."""
    config, _saved = roots
    _install_fake(monkeypatch, _FakeAb())
    records = [_seed_record(config, index, connection_ref=REF) for index in (1, 2)]
    calls: list[str] = []

    def explode(config_arg: Any, *, payload: Any) -> dict[str, Any]:
        calls.append(payload.tracking_id)
        raise RuntimeError("simulated crash inside the batch")

    monkeypatch.setattr(batch_delete, "run_saved_tracking_plan_delete", explode)

    with pytest.raises(RuntimeError):
        batch_delete.run_saved_tracking_batch_delete(
            config, payload=_local_payload(records, key="batch-crash"), delete_external=False
        )

    assert calls, "the crash must happen inside the batch"
    # The store is free again: a new lease and a normal write both work.
    with tracking_batch_lease(batch_key="after-crash"):
        ensure_tracking_record(
            config,
            replace(
                create_external_tracking_record(
                    adapter="legacy_3_1", object_kind="subscription",
                    external_id="sub-9", subscription_id="sub-9", title="After", season=1,
                    connection_ref=REF,
                ),
                status=TRACKING_STATUS_ACTIVE,
            ),
        )


def test_derived_item_keys_stay_bounded_and_distinct() -> None:
    """A long batch key or tracking id can never collide or break validation."""
    first = batch_delete._item_key("k" * 200, "trk_" + "a" * 500)
    second = batch_delete._item_key("k" * 200, "trk_" + "b" * 500)
    assert first != second
    assert len(first) <= 200
    # The single delete contract accepts the derived key unchanged.
    SavedTrackingPlanDeleteInput(
        tracking_id="trk_a", confirm=True, delete_external=False, idempotency_key=first
    )
