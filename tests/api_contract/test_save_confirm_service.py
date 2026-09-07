from __future__ import annotations

"""US-213: save-confirm idempotency protocol tests.

These drive ``save_confirm_service.run_save_confirm`` with injected seams
(reserve/persist/confirm/commit/release) against a ``tmp_path`` storage
profile. They prove the durable idempotency guarantees US-214 will build on:

- a terminal outcome is replayed for the same key and never touches the draft;
- an ``IN_PROGRESS`` retry first reconciles against the on-disk Request;
- after the process-level DraftStore is cleared (crash/restart), retrying the
  same key neither reserves a lost draft nor creates a second Request;
- the same key bound to a different plan is a 409 ``idempotency_conflict`` and
  the error never echoes the raw payload;
- persistence and confirmation failures keep the record/outcome consistent.
"""

from pathlib import Path
from threading import Barrier, Thread
from typing import Any

import pytest

from apps.migu_orca_entry.controllers.entry_controller import generate_request
from apps.migu_orca_web.save_confirm_service import (
    STATE_CONFIRMED,
    STATE_IN_PROGRESS,
    STATE_SAVED_CONFIRM_FAILED,
    compute_request_fingerprint,
    resolve_in_progress_retry,
    run_save_confirm,
)
from request_engine.controllers.request_controller import accept_request
from shared.errors import Stage1Error
from shared.models import EntryRequest
from storage_engine.controllers.idempotency_repository import (
    create_idempotency_record,
    load_idempotency_record,
    save_idempotency_record,
)
from storage_engine.controllers.request_repository import (
    load_request_snapshot,
    save_request_snapshot,
)
from storage_engine.controllers.storage_config import load_storage_config

NOW = "2026-09-08T00:00:00+00:00"


def _config(tmp_path: Path):
    return load_storage_config(tmp_path / "migu-state")


def _draft_request(title: str = "芙莉莲") -> dict[str, Any]:
    """Return a generated PENDING_CONFIRM draft-like Request dict."""
    return generate_request(EntryRequest(raw_title=title))["request"]


class _SaveConfirmHarness:
    """Wires real-ish seams over a tmp storage profile.

    ``fail_persist`` / ``fail_confirm`` simulate the disk/acceptance failures
    US-212/US-214 must survive; ``reserved`` records every draft reservation so
    tests can assert the draft was (or was not) touched on a replay.
    """

    def __init__(self, config, draft: dict[str, Any]) -> None:
        self.config = config
        self.draft = draft
        self.fail_persist: bool = False
        self.fail_confirm: bool = False
        self.reservations: list[str] = []
        self.commits: int = 0
        self.releases: int = 0

    def reserve_draft(self) -> dict[str, Any]:
        self.reservations.append(str(self.draft.get("request_id")))
        return self.draft

    def persist_pending(self, request: dict[str, Any]) -> dict[str, Any]:
        if self.fail_persist:
            raise Stage1Error(
                "storage_error",
                "保存订阅方案 JSON 失败",
                "save_request_snapshot",
                {"request_id": request["request_id"], "directory": "requests"},
            )
        return save_request_snapshot(self.config, request)

    def confirm_saved(self, request_id: str) -> dict[str, Any]:
        if self.fail_confirm:
            raise Stage1Error(
                "invalid_request_status",
                "只有待确认订阅方案可以执行确认操作",
                "confirm_request",
                {"status": "PENDING_CONFIRM"},
            )
        request = load_request_snapshot(self.config, request_id)
        accepted = accept_request(request)
        save_request_snapshot(self.config, accepted)
        return accepted

    def commit_draft(self) -> None:
        self.commits += 1

    def release_draft(self) -> None:
        self.releases += 1


def _saved_pending(config, request: dict[str, Any]) -> dict[str, Any]:
    save_request_snapshot(config, request)
    return request


def _seed_record(config, record: dict[str, Any]) -> None:
    save_idempotency_record(config, record)


# ---------------------------------------------------------------------------
# Terminal replay
# ---------------------------------------------------------------------------


def test_terminal_confirmed_record_is_replayed_without_reserving_draft(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    draft = _draft_request()
    request_id = draft["request_id"]
    accepted = accept_request(draft)
    save_request_snapshot(config, accepted)
    record = create_idempotency_record(
        idempotency_key="key-1",
        operation="SAVE_CONFIRM",
        request_fingerprint=compute_request_fingerprint(draft),
        request_id=request_id,
        state=STATE_CONFIRMED,
        now=NOW,
    )
    save_idempotency_record(config, record)
    harness = _SaveConfirmHarness(config, draft)

    outcome = run_save_confirm(
        config=config,
        idempotency_key="key-1",
        reserve_draft=harness.reserve_draft,
        persist_pending=harness.persist_pending,
        confirm_saved=harness.confirm_saved,
        commit_draft=harness.commit_draft,
        release_draft=harness.release_draft,
        now=NOW,
    )

    assert outcome.outcome == STATE_CONFIRMED
    assert outcome.request_id == request_id
    assert outcome.replayed is True
    assert outcome.request["status"] == "ACCEPTED"
    assert harness.reservations == []
    assert harness.commits == 0
    assert harness.releases == 0


def test_terminal_saved_confirm_failed_record_is_replayed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    draft = _draft_request()
    request_id = draft["request_id"]
    save_request_snapshot(config, draft)
    record = create_idempotency_record(
        idempotency_key="key-fail",
        operation="SAVE_CONFIRM",
        request_fingerprint=compute_request_fingerprint(draft),
        request_id=request_id,
        state=STATE_SAVED_CONFIRM_FAILED,
        now=NOW,
    )
    save_idempotency_record(config, record)
    harness = _SaveConfirmHarness(config, draft)

    outcome = run_save_confirm(
        config=config,
        idempotency_key="key-fail",
        reserve_draft=harness.reserve_draft,
        persist_pending=harness.persist_pending,
        confirm_saved=harness.confirm_saved,
        commit_draft=harness.commit_draft,
        release_draft=harness.release_draft,
        now=NOW,
    )

    assert outcome.outcome == STATE_SAVED_CONFIRM_FAILED
    assert outcome.request_id == request_id
    assert outcome.replayed is True
    assert outcome.request["status"] == "PENDING_CONFIRM"
    assert harness.reservations == []


# ---------------------------------------------------------------------------
# Full success + same-key replay after a process-level store loss
# ---------------------------------------------------------------------------


def test_fresh_save_confirm_succeeds_and_binds_record(tmp_path: Path) -> None:
    config = _config(tmp_path)
    draft = _draft_request()
    harness = _SaveConfirmHarness(config, draft)

    outcome = run_save_confirm(
        config=config,
        idempotency_key="key-success",
        reserve_draft=harness.reserve_draft,
        persist_pending=harness.persist_pending,
        confirm_saved=harness.confirm_saved,
        commit_draft=harness.commit_draft,
        release_draft=harness.release_draft,
        now=NOW,
    )

    assert outcome.outcome == STATE_CONFIRMED
    assert outcome.request_id == draft["request_id"]
    assert outcome.request["status"] == "ACCEPTED"
    assert outcome.replayed is False
    assert harness.reservations == [draft["request_id"]]
    assert harness.commits == 1
    assert harness.releases == 0
    record = load_idempotency_record(config, "key-success")
    assert record is not None
    assert record["state"] == STATE_CONFIRMED
    assert record["request_id"] == draft["request_id"]
    assert record["request_fingerprint"] == compute_request_fingerprint(draft)
    # The record never stores a title, draft or URL.
    written = (config.idempotency_dir / "key-success.json").read_text(encoding="utf-8")
    assert "芙莉莲" not in written
    assert "mikan" not in written


def test_retry_after_draft_store_loss_does_not_reserve_or_duplicate(
    tmp_path: Path,
) -> None:
    """US-213 core: after a crash the in-process draft is gone, but the durable
    CONFIRMED record lets the retry return the same Request without reserving a
    lost draft or creating a duplicate."""
    config = _config(tmp_path)
    draft = _draft_request()
    request_id = draft["request_id"]
    # First attempt fully succeeds and writes the ACCEPTED request + record.
    first = _SaveConfirmHarness(config, draft)
    run_save_confirm(
        config=config,
        idempotency_key="key-crash",
        reserve_draft=first.reserve_draft,
        persist_pending=first.persist_pending,
        confirm_saved=first.confirm_saved,
        commit_draft=first.commit_draft,
        release_draft=first.release_draft,
        now=NOW,
    )

    # Process restart: the in-memory draft store is empty (draft gone) but the
    # durable storage still has the accepted Request + record.
    harness = _SaveConfirmHarness(config, draft)
    outcome = run_save_confirm(
        config=config,
        idempotency_key="key-crash",
        reserve_draft=harness.reserve_draft,
        persist_pending=harness.persist_pending,
        confirm_saved=harness.confirm_saved,
        commit_draft=harness.commit_draft,
        release_draft=harness.release_draft,
        now=NOW,
    )

    assert outcome.outcome == STATE_CONFIRMED
    assert outcome.request_id == request_id
    assert outcome.replayed is True
    assert harness.reservations == []
    assert harness.commits == 0
    # Exactly one Request exists on disk.
    assert sorted(path.name for path in config.requests_dir.glob("*.json")) == [
        f"{request_id}.json"
    ]
    assert load_request_snapshot(config, request_id)["status"] == "ACCEPTED"


# ---------------------------------------------------------------------------
# IN_PROGRESS reconciliation (rule 3)
# ---------------------------------------------------------------------------


def test_in_progress_retry_with_request_on_disk_continues_confirm(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    draft = _draft_request()
    request_id = draft["request_id"]
    save_request_snapshot(config, draft)
    record = create_idempotency_record(
        idempotency_key="key-mid",
        operation="SAVE_CONFIRM",
        request_fingerprint=compute_request_fingerprint(draft),
        request_id=request_id,
        state=STATE_IN_PROGRESS,
        now=NOW,
    )
    save_idempotency_record(config, record)
    harness = _SaveConfirmHarness(config, draft)

    outcome = run_save_confirm(
        config=config,
        idempotency_key="key-mid",
        reserve_draft=harness.reserve_draft,
        persist_pending=harness.persist_pending,
        confirm_saved=harness.confirm_saved,
        commit_draft=harness.commit_draft,
        release_draft=harness.release_draft,
        now=NOW,
    )

    # The on-disk Request was found; the save was NOT redone; the draft was not
    # reserved; confirmation completed.
    assert outcome.outcome == STATE_CONFIRMED
    assert outcome.request_id == request_id
    assert outcome.replayed is True
    assert harness.reservations == []
    assert harness.commits == 0
    assert load_request_snapshot(config, request_id)["status"] == "ACCEPTED"
    record = load_idempotency_record(config, "key-mid")
    assert record["state"] == STATE_CONFIRMED


def test_in_progress_retry_without_request_redoes_save_once(tmp_path: Path) -> None:
    config = _config(tmp_path)
    draft = _draft_request()
    request_id = draft["request_id"]
    record = create_idempotency_record(
        idempotency_key="key-inprogress",
        operation="SAVE_CONFIRM",
        request_fingerprint=compute_request_fingerprint(draft),
        request_id=None,
        state=STATE_IN_PROGRESS,
        now=NOW,
    )
    save_idempotency_record(config, record)
    harness = _SaveConfirmHarness(config, draft)

    outcome = run_save_confirm(
        config=config,
        idempotency_key="key-inprogress",
        reserve_draft=harness.reserve_draft,
        persist_pending=harness.persist_pending,
        confirm_saved=harness.confirm_saved,
        commit_draft=harness.commit_draft,
        release_draft=harness.release_draft,
        now=NOW,
    )

    assert outcome.outcome == STATE_CONFIRMED
    assert outcome.request_id == request_id
    assert harness.reservations == [request_id]
    assert harness.commits == 1
    assert sorted(path.name for path in config.requests_dir.glob("*.json")) == [
        f"{request_id}.json"
    ]


def test_in_progress_crash_window_before_persist_redoes_save_once(
    tmp_path: Path,
) -> None:
    """Crash between binding request_id and the atomic Request write.

    The record points at a request_id whose snapshot never landed on disk. A
    retry must resolve to retry_save (rule 3) and produce exactly one Request,
    never skip the save (which would leave the user without a Request) and
    never create a duplicate.
    """
    config = _config(tmp_path)
    draft = _draft_request()
    request_id = draft["request_id"]
    record = create_idempotency_record(
        idempotency_key="key-crash-window",
        operation="SAVE_CONFIRM",
        request_fingerprint=compute_request_fingerprint(draft),
        request_id=request_id,
        state=STATE_IN_PROGRESS,
        now=NOW,
    )
    save_idempotency_record(config, record)
    harness = _SaveConfirmHarness(config, draft)

    outcome = run_save_confirm(
        config=config,
        idempotency_key="key-crash-window",
        reserve_draft=harness.reserve_draft,
        persist_pending=harness.persist_pending,
        confirm_saved=harness.confirm_saved,
        commit_draft=harness.commit_draft,
        release_draft=harness.release_draft,
        now=NOW,
    )

    assert outcome.outcome == STATE_CONFIRMED
    assert outcome.request_id == request_id
    assert harness.reservations == [request_id]
    assert harness.commits == 1
    assert sorted(path.name for path in config.requests_dir.glob("*.json")) == [
        f"{request_id}.json"
    ]
    record = load_idempotency_record(config, "key-crash-window")
    assert record["state"] == STATE_CONFIRMED


def test_in_progress_retry_same_key_different_plan_conflicts(tmp_path: Path) -> None:
    """A key bound IN_PROGRESS to a plan must reject a different plan."""
    config = _config(tmp_path)
    original = _draft_request("芙莉莲")
    record = create_idempotency_record(
        idempotency_key="key-plan",
        operation="SAVE_CONFIRM",
        request_fingerprint=compute_request_fingerprint(original),
        request_id=original["request_id"],
        state=STATE_IN_PROGRESS,
        now=NOW,
    )
    save_idempotency_record(config, record)
    # A retry now holds a genuinely different plan (different bangumi).
    changed = _draft_request("咒术回战")
    harness = _SaveConfirmHarness(config, changed)

    with pytest.raises(Stage1Error) as error:
        run_save_confirm(
            config=config,
            idempotency_key="key-plan",
            reserve_draft=harness.reserve_draft,
            persist_pending=harness.persist_pending,
            confirm_saved=harness.confirm_saved,
            commit_draft=harness.commit_draft,
            release_draft=harness.release_draft,
            now=NOW,
        )

    assert error.value.error_type == "idempotency_conflict"
    assert error.value.details == {
        "field": "idempotency_key",
        "reason": "payload_mismatch",
    }
    assert "芙莉莲" not in str(error.value.as_dict())
    assert "咒术回战" not in str(error.value.as_dict())
    assert harness.releases == 1
    record = load_idempotency_record(config, "key-plan")
    assert record["state"] == STATE_IN_PROGRESS


def test_reused_key_with_different_operation_conflicts(tmp_path: Path) -> None:
    """A key bound to SAVE_CONFIRM may never be reused for another operation."""
    config = _config(tmp_path)
    draft = _draft_request()
    record = create_idempotency_record(
        idempotency_key="key-op",
        operation="SOME_OTHER_OPERATION",
        request_fingerprint=compute_request_fingerprint(draft),
        request_id=draft["request_id"],
        state=STATE_CONFIRMED,
        now=NOW,
    )
    save_idempotency_record(config, record)
    harness = _SaveConfirmHarness(config, draft)

    with pytest.raises(Stage1Error) as error:
        run_save_confirm(
            config=config,
            idempotency_key="key-op",
            reserve_draft=harness.reserve_draft,
            persist_pending=harness.persist_pending,
            confirm_saved=harness.confirm_saved,
            commit_draft=harness.commit_draft,
            release_draft=harness.release_draft,
            now=NOW,
        )

    assert error.value.error_type == "idempotency_conflict"
    assert error.value.details["reason"] == "operation_mismatch"
    # The operation/fingerprint are not the raw payload; nothing sensitive leaks.
    assert "SOME_OTHER_OPERATION" not in str(error.value.as_dict())
    assert harness.reservations == []


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


def test_persist_failure_releases_draft_and_leaves_recoverable_record(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    draft = _draft_request()
    harness = _SaveConfirmHarness(config, draft)
    harness.fail_persist = True

    with pytest.raises(Stage1Error) as error:
        run_save_confirm(
            config=config,
            idempotency_key="key-persist-fail",
            reserve_draft=harness.reserve_draft,
            persist_pending=harness.persist_pending,
            confirm_saved=harness.confirm_saved,
            commit_draft=harness.commit_draft,
            release_draft=harness.release_draft,
            now=NOW,
        )

    assert error.value.error_type == "storage_error"
    assert harness.releases == 1
    assert harness.commits == 0
    # The draft was released (retryable) and no Request was written. The key is
    # durably bound to an IN_PROGRESS record; because the on-disk Request does
    # not exist, a retry resolves to retry_save (never blindly re-creates while
    # a Request might already exist).
    record = load_idempotency_record(config, "key-persist-fail")
    assert record is not None
    assert record["state"] == STATE_IN_PROGRESS
    assert list(config.requests_dir.glob("*.json")) == []

    # A retry now succeeds and produces exactly one Request.
    harness.fail_persist = False
    outcome = run_save_confirm(
        config=config,
        idempotency_key="key-persist-fail",
        reserve_draft=harness.reserve_draft,
        persist_pending=harness.persist_pending,
        confirm_saved=harness.confirm_saved,
        commit_draft=harness.commit_draft,
        release_draft=harness.release_draft,
        now=NOW,
    )
    assert outcome.outcome == STATE_CONFIRMED
    assert outcome.request_id == draft["request_id"]
    assert sorted(path.name for path in config.requests_dir.glob("*.json")) == [
        f"{draft['request_id']}.json"
    ]


def test_confirm_failure_returns_saved_confirm_failed_and_commits_draft(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    draft = _draft_request()
    harness = _SaveConfirmHarness(config, draft)
    harness.fail_confirm = True

    outcome = run_save_confirm(
        config=config,
        idempotency_key="key-confirm-fail",
        reserve_draft=harness.reserve_draft,
        persist_pending=harness.persist_pending,
        confirm_saved=harness.confirm_saved,
        commit_draft=harness.commit_draft,
        release_draft=harness.release_draft,
        now=NOW,
    )

    # The Request is durable and PENDING_CONFIRM; the draft is consumed (never
    # released back) so a retry cannot create a second Request.
    assert outcome.outcome == STATE_SAVED_CONFIRM_FAILED
    assert outcome.request_id == draft["request_id"]
    assert outcome.request["status"] == "PENDING_CONFIRM"
    assert harness.commits == 1
    assert harness.releases == 0
    record = load_idempotency_record(config, "key-confirm-fail")
    assert record["state"] == STATE_SAVED_CONFIRM_FAILED
    assert record["request_id"] == draft["request_id"]
    assert load_request_snapshot(config, draft["request_id"])["status"] == "PENDING_CONFIRM"


def test_confirm_failure_retry_replays_saved_confirm_failed_without_new_request(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    draft = _draft_request()
    request_id = draft["request_id"]

    first = _SaveConfirmHarness(config, draft)
    first.fail_confirm = True
    run_save_confirm(
        config=config,
        idempotency_key="key-cf-retry",
        reserve_draft=first.reserve_draft,
        persist_pending=first.persist_pending,
        confirm_saved=first.confirm_saved,
        commit_draft=first.commit_draft,
        release_draft=first.release_draft,
        now=NOW,
    )

    # Retry: the SAVED_CONFIRM_FAILED record is terminal; nothing is touched.
    second = _SaveConfirmHarness(config, draft)
    outcome = run_save_confirm(
        config=config,
        idempotency_key="key-cf-retry",
        reserve_draft=second.reserve_draft,
        persist_pending=second.persist_pending,
        confirm_saved=second.confirm_saved,
        commit_draft=second.commit_draft,
        release_draft=second.release_draft,
        now=NOW,
    )

    assert outcome.outcome == STATE_SAVED_CONFIRM_FAILED
    assert outcome.request_id == request_id
    assert outcome.replayed is True
    assert second.reservations == []
    assert second.commits == 0
    assert sorted(path.name for path in config.requests_dir.glob("*.json")) == [
        f"{request_id}.json"
    ]


def test_concurrent_same_key_attempts_produce_one_request(tmp_path: Path) -> None:
    """US-213 concurrent conflict: two threads retry the same key with the same
    plan. The in-process per-key lock serializes them; exactly one Request is
    created and the terminal record is consistent."""
    config = _config(tmp_path)
    draft = _draft_request()
    request_id = draft["request_id"]
    harness = _SaveConfirmHarness(config, draft)
    # The shared harness makes persist/confirm naturally thread-safe through the
    # per-key lock; count reservations to prove only one attempt ran the save.
    barrier = Barrier(2)
    outcomes: list = []
    errors: list[BaseException] = []

    def attempt() -> None:
        try:
            barrier.wait()
            outcome = run_save_confirm(
                config=config,
                idempotency_key="key-concurrent",
                reserve_draft=harness.reserve_draft,
                persist_pending=harness.persist_pending,
                confirm_saved=harness.confirm_saved,
                commit_draft=harness.commit_draft,
                release_draft=harness.release_draft,
                now=NOW,
            )
            outcomes.append(outcome)
        except BaseException as exc:  # pragma: no cover - failure surfaced below
            errors.append(exc)

    threads = [Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(outcomes) == 2
    # One thread performed the real save; the other replayed the terminal record.
    assert {outcome.outcome for outcome in outcomes} == {STATE_CONFIRMED}
    assert all(outcome.request_id == request_id for outcome in outcomes)
    assert harness.commits == 1
    assert sorted(path.name for path in config.requests_dir.glob("*.json")) == [
        f"{request_id}.json"
    ]
    record = load_idempotency_record(config, "key-concurrent")
    assert record["state"] == STATE_CONFIRMED
    assert record["request_id"] == request_id


# ---------------------------------------------------------------------------
# Fingerprint stability / gate helpers
# ---------------------------------------------------------------------------


def test_fingerprint_is_stable_across_request_id_and_sensitive_fields() -> None:
    draft_a = _draft_request("芙莉莲")
    draft_b = {**draft_a, "request_id": "a-different-regenerated-id"}
    # Add sensitive fields that must never influence the digest.
    draft_b["source_info"]["rss_sources"][0]["rss_url"] = "https://example.invalid/secret"
    draft_b["source_info"]["rss_sources"][0]["seed_names"] = ["private-seed"]

    assert compute_request_fingerprint(draft_a) == compute_request_fingerprint(draft_b)
    assert len(compute_request_fingerprint(draft_a)) == 64


def test_fingerprint_differs_for_different_plan() -> None:
    draft_a = _draft_request("芙莉莲")
    draft_b = _draft_request("咒术回战")
    assert compute_request_fingerprint(draft_a) != compute_request_fingerprint(draft_b)


def test_resolve_in_progress_retry_checks_on_disk_request(tmp_path: Path) -> None:
    config = _config(tmp_path)
    draft = _draft_request()
    request_id = draft["request_id"]
    base_record = {
        "idempotency_key": "k",
        "operation": "SAVE_CONFIRM",
        "request_fingerprint": "f",
        "state": STATE_IN_PROGRESS,
        "created_at": NOW,
        "updated_at": NOW,
    }

    without_id = resolve_in_progress_retry(
        config=config, record={**base_record, "request_id": None}
    )
    assert without_id == {"action": "retry_save", "request_id": None}

    # Request on disk → continue confirm.
    save_request_snapshot(config, draft)
    on_disk = resolve_in_progress_retry(
        config=config, record={**base_record, "request_id": request_id}
    )
    assert on_disk == {"action": "continue_confirm", "request_id": request_id}

    # Request not on disk → retry save.
    missing = resolve_in_progress_retry(
        config=config, record={**base_record, "request_id": "never-saved"}
    )
    assert missing == {"action": "retry_save", "request_id": "never-saved"}
