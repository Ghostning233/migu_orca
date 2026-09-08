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
    BATCH_OUTCOME_CONFIRMED,
    BATCH_OUTCOME_FAILED,
    BATCH_OUTCOME_SKIPPED,
    STATE_CONFIRMED,
    STATE_IN_PROGRESS,
    STATE_SAVED_CONFIRM_FAILED,
    BatchSaveConfirmItemResult,
    ProcessOne,
    SaveConfirmOutcome,
    build_batch_process_one,
    compute_request_fingerprint,
    resolve_in_progress_retry,
    run_batch_save_confirm,
    run_save_confirm,
    serialize_batch_save_confirm_result,
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


def test_terminal_record_with_different_live_draft_conflicts(tmp_path: Path) -> None:
    """US-213 fix: a terminal record must not replay for a *different* live draft.

    ``key-A`` confirmed draft-1; a second, still-present draft-2 reuses key-A.
    The terminal replay path must compare fingerprints via ``peek_draft`` and
    return a 409 ``idempotency_conflict`` (details only field/reason), leaving
    draft-2 usable and not reserved/consumed.
    """
    config = _config(tmp_path)
    first = _draft_request("芙莉莲")
    first_id = first["request_id"]
    save_request_snapshot(config, accept_request(first))
    record = create_idempotency_record(
        idempotency_key="key-reuse",
        operation="SAVE_CONFIRM",
        request_fingerprint=compute_request_fingerprint(first),
        request_id=first_id,
        state=STATE_CONFIRMED,
        now=NOW,
    )
    save_idempotency_record(config, record)

    # A different, still-present draft reuses the key.
    second = _draft_request("咒术回战")
    harness = _SaveConfirmHarness(config, second)

    with pytest.raises(Stage1Error) as error:
        run_save_confirm(
            config=config,
            idempotency_key="key-reuse",
            reserve_draft=harness.reserve_draft,
            persist_pending=harness.persist_pending,
            confirm_saved=harness.confirm_saved,
            commit_draft=harness.commit_draft,
            release_draft=harness.release_draft,
            peek_draft=lambda: second,
            now=NOW,
        )

    assert error.value.error_type == "idempotency_conflict"
    assert error.value.details == {
        "field": "idempotency_key",
        "reason": "payload_mismatch",
    }
    # The second draft is untouched: never reserved/committed/released/persisted.
    assert harness.reservations == []
    assert harness.commits == 0
    assert harness.releases == 0
    # No second Request exists; only the first confirmed Request remains.
    assert sorted(path.name for path in config.requests_dir.glob("*.json")) == [
        f"{first_id}.json"
    ]


def test_terminal_record_with_matching_live_draft_replays(tmp_path: Path) -> None:
    """US-213 fix: a matching live draft under a terminal key replays safely.

    ``peek_draft`` returns a draft whose fingerprint matches the record, so the
    terminal outcome is replayed *without* consuming/reserving the live draft.
    """
    config = _config(tmp_path)
    draft = _draft_request()
    request_id = draft["request_id"]
    save_request_snapshot(config, accept_request(draft))
    record = create_idempotency_record(
        idempotency_key="key-match",
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
        idempotency_key="key-match",
        reserve_draft=harness.reserve_draft,
        persist_pending=harness.persist_pending,
        confirm_saved=harness.confirm_saved,
        commit_draft=harness.commit_draft,
        release_draft=harness.release_draft,
        peek_draft=lambda: draft,
        now=NOW,
    )

    assert outcome.outcome == STATE_CONFIRMED
    assert outcome.request_id == request_id
    assert outcome.replayed is True
    assert harness.reservations == []
    assert harness.commits == 0
    assert harness.releases == 0


def test_terminal_record_with_missing_draft_replays(tmp_path: Path) -> None:
    """US-213 fix: a missing draft (process restart) still replays the terminal
    record — ``peek_draft`` returns None and the replay is allowed."""
    config = _config(tmp_path)
    draft = _draft_request()
    request_id = draft["request_id"]
    save_request_snapshot(config, accept_request(draft))
    record = create_idempotency_record(
        idempotency_key="key-restart",
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
        idempotency_key="key-restart",
        reserve_draft=harness.reserve_draft,
        persist_pending=harness.persist_pending,
        confirm_saved=harness.confirm_saved,
        commit_draft=harness.commit_draft,
        release_draft=harness.release_draft,
        peek_draft=lambda: None,  # draft gone after restart
        now=NOW,
    )

    assert outcome.outcome == STATE_CONFIRMED
    assert outcome.request_id == request_id
    assert outcome.replayed is True
    assert harness.reservations == []


def test_terminal_record_with_reserved_draft_raises_draft_reserved(
    tmp_path: Path,
) -> None:
    """Stage 28 boundary fix: a reserved draft must never replay a terminal record.

    ``peek_draft`` raising the 409 ``draft_reserved`` (as the route layer does
    for a reserved DraftStore entry) must propagate — never be folded into
    "gone" and replayed as an unrelated Request.
    """
    config = _config(tmp_path)
    first = _draft_request("芙莉莲")
    first_id = first["request_id"]
    save_request_snapshot(config, accept_request(first))
    record = create_idempotency_record(
        idempotency_key="key-reserved",
        operation="SAVE_CONFIRM",
        request_fingerprint=compute_request_fingerprint(first),
        request_id=first_id,
        state=STATE_CONFIRMED,
        now=NOW,
    )
    save_idempotency_record(config, record)

    def peek_reserved() -> dict[str, Any]:
        raise Stage1Error(
            "draft_reserved",
            "订阅草案正在保存中，请稍后重试",
            "reserve_preview_draft",
            {"field": "draft_id"},
        )

    harness = _SaveConfirmHarness(config, first)

    with pytest.raises(Stage1Error) as error:
        run_save_confirm(
            config=config,
            idempotency_key="key-reserved",
            reserve_draft=harness.reserve_draft,
            persist_pending=harness.persist_pending,
            confirm_saved=harness.confirm_saved,
            commit_draft=harness.commit_draft,
            release_draft=harness.release_draft,
            peek_draft=peek_reserved,
            now=NOW,
        )

    # The reserved error propagates; the old Request is NOT returned.
    assert error.value.error_type == "draft_reserved"
    assert error.value.details == {"field": "draft_id"}
    # The second draft's harness was never reserved/committed/released.
    assert harness.reservations == []
    assert harness.commits == 0
    assert harness.releases == 0


def test_record_creation_failure_releases_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """US-213 fix: a first-record write failure releases the reservation.

    ``save_idempotency_record`` raising before ``persist_pending`` must not leave
    the draft permanently reserved — the same draft/revision can reserve again
    and the failed attempt must not leave a Request on disk.
    """
    from apps.migu_orca_web import save_confirm_service as scs

    config = _config(tmp_path)
    draft = _draft_request()
    harness = _SaveConfirmHarness(config, draft)

    def fail_record(conf, record):
        raise Stage1Error(
            "storage_error", "幂等记录写入失败", "save_idempotency_record",
            {"reason": "disk full"},
        )

    monkeypatch.setattr(scs, "save_idempotency_record", fail_record)

    with pytest.raises(Stage1Error) as error:
        run_save_confirm(
            config=config,
            idempotency_key="key-record-fail",
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
    assert list(config.requests_dir.glob("*.json")) == []

    # The draft was released: a clean retry (record write restored) succeeds
    # and produces exactly one Request.
    monkeypatch.setattr(
        scs, "save_idempotency_record", save_idempotency_record
    )
    outcome = run_save_confirm(
        config=config,
        idempotency_key="key-record-fail",
        reserve_draft=harness.reserve_draft,
        persist_pending=harness.persist_pending,
        confirm_saved=harness.confirm_saved,
        commit_draft=harness.commit_draft,
        release_draft=harness.release_draft,
        now=NOW,
    )
    assert outcome.outcome == STATE_CONFIRMED
    assert sorted(path.name for path in config.requests_dir.glob("*.json")) == [
        f"{draft['request_id']}.json"
    ]


def test_in_progress_update_failure_releases_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """US-213 fix: re-arming an IN_PROGRESS record failure releases the draft.

    ``_update_state`` (which calls ``save_idempotency_record``) failing before
    ``persist_pending`` must release the reservation, leaving the same
    draft/revision usable and no Request on disk.
    """
    from apps.migu_orca_web import save_confirm_service as scs

    config = _config(tmp_path)
    draft = _draft_request()
    request_id = draft["request_id"]
    # Pre-bind the key IN_PROGRESS with no on-disk Request (retry_save path).
    record = create_idempotency_record(
        idempotency_key="key-inprogress-fail",
        operation="SAVE_CONFIRM",
        request_fingerprint=compute_request_fingerprint(draft),
        request_id=None,
        state=STATE_IN_PROGRESS,
        now=NOW,
    )
    save_idempotency_record(config, record)
    harness = _SaveConfirmHarness(config, draft)

    calls = {"n": 0}

    def flaky_record(conf, record_to_save):
        # First write after the pre-seed is the _update_state re-arm: fail it.
        calls["n"] += 1
        if calls["n"] == 1:
            raise Stage1Error(
                "storage_error", "幂等记录更新失败", "save_idempotency_record",
                {"reason": "disk full"},
            )
        return save_idempotency_record(conf, record_to_save)

    monkeypatch.setattr(scs, "save_idempotency_record", flaky_record)

    with pytest.raises(Stage1Error) as error:
        run_save_confirm(
            config=config,
            idempotency_key="key-inprogress-fail",
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
    assert list(config.requests_dir.glob("*.json")) == []

    # Restore the write path and retry the same draft/revision: it succeeds once.
    monkeypatch.setattr(scs, "save_idempotency_record", save_idempotency_record)
    outcome = run_save_confirm(
        config=config,
        idempotency_key="key-inprogress-fail",
        reserve_draft=harness.reserve_draft,
        persist_pending=harness.persist_pending,
        confirm_saved=harness.confirm_saved,
        commit_draft=harness.commit_draft,
        release_draft=harness.release_draft,
        now=NOW,
    )
    assert outcome.outcome == STATE_CONFIRMED
    assert outcome.request_id == request_id
    assert sorted(path.name for path in config.requests_dir.glob("*.json")) == [
        f"{request_id}.json"
    ]


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


# ---------------------------------------------------------------------------
# Batch save-confirm coordinator (US-216)
# ---------------------------------------------------------------------------


def _fake_batch_process_one(
    outcomes: dict[str, SaveConfirmOutcome],
    error: str | None = None,
) -> ProcessOne:
    """Return a per-item runner backed by canned outcomes for unit tests."""

    def process_one_item(
        item_id: str,
        draft_id: str,
        base_revision: int,
        idempotency_key: str,
    ) -> SaveConfirmOutcome:
        if error is not None:
            raise Stage1Error(error, "失败", "batch_save_confirm")
        return outcomes[item_id]

    return build_batch_process_one(process_one_item, map_error=lambda item_id, exc: BatchSaveConfirmItemResult(
        item_id=item_id,
        outcome=BATCH_OUTCOME_FAILED,
        error_type=exc.error_type,
        error_message=exc.message,
    ))


def test_batch_save_confirm_coordinator_preserves_order_and_counts() -> None:
    """US-216: results keep input order and summary counts requested/confirmed."""
    confirmed = SaveConfirmOutcome(
        outcome=STATE_CONFIRMED,
        request_id="request-1",
        request=accept_request(_draft_request("芙莉莲")),
        summary=None,
    )
    process_one = _fake_batch_process_one({"item-1": confirmed})

    result = run_batch_save_confirm(
        batch_id="batch-1",
        items=[
            ("item-1", "draft-1", 1, "key-1"),
            ("item-2", "draft-2", 1, "key-2"),
        ],
        item_ids=None,
        process_one=process_one,
    )
    # item-2 is not in outcomes → unexpected error folded to a per-item failure.
    assert [r.item_id for r in result.results] == ["item-1", "item-2"]
    assert result.results[0].outcome == BATCH_OUTCOME_CONFIRMED
    assert result.results[0].request_id == "request-1"
    assert result.results[1].outcome == BATCH_OUTCOME_FAILED
    assert result.summary() == {"requested": 2, "confirmed": 1, "failed": 1}
    serialized = serialize_batch_save_confirm_result(result)
    assert serialized["batch_id"] == "batch-1"
    assert serialized["summary"] == {"requested": 2, "confirmed": 1, "failed": 1}


def test_batch_save_confirm_coordinator_item_ids_selects_subset() -> None:
    """US-216: item_ids filters items while preserving the input order."""
    confirmed = SaveConfirmOutcome(
        outcome=STATE_CONFIRMED,
        request_id="request-1",
        request=accept_request(_draft_request("芙莉莲")),
        summary=None,
    )
    process_one = _fake_batch_process_one(
        {"item-a": confirmed, "item-b": confirmed, "item-c": confirmed}
    )
    result = run_batch_save_confirm(
        batch_id="batch-1",
        items=[
            ("item-a", "d-a", 1, "k-a"),
            ("item-b", "d-b", 1, "k-b"),
            ("item-c", "d-c", 1, "k-c"),
        ],
        item_ids=["item-c", "item-a"],
        process_one=process_one,
    )
    assert [r.item_id for r in result.results] == ["item-a", "item-c"]
    assert result.summary()["requested"] == 2


def test_batch_save_confirm_coordinator_duplicate_item_is_skipped() -> None:
    """US-216: a duplicate item_id is skipped and never re-touched."""
    confirmed = SaveConfirmOutcome(
        outcome=STATE_CONFIRMED,
        request_id="request-1",
        request=accept_request(_draft_request("芙莉莲")),
        summary=None,
    )
    process_one = _fake_batch_process_one({"item-1": confirmed})
    result = run_batch_save_confirm(
        batch_id="batch-1",
        items=[
            ("item-1", "draft-1", 1, "key-1"),
            ("item-1", "draft-1", 1, "key-2"),
        ],
        item_ids=None,
        process_one=process_one,
    )
    assert result.results[0].outcome == BATCH_OUTCOME_CONFIRMED
    assert result.results[1].outcome == BATCH_OUTCOME_SKIPPED
    assert result.results[1].error_type == "duplicate_item"
    # process_one was only ever invoked for the first (non-skipped) occurrence;
    # the second key never reached the single save-confirm use case.
    # US-213 fix: a skipped item is not a confirmation, so it is counted as a
    # failure to keep requested == confirmed + failed closed.
    assert result.summary() == {"requested": 2, "confirmed": 1, "failed": 1}


def test_batch_save_confirm_coordinator_rejects_shared_key_for_two_items() -> None:
    """US-216: one key may drive only one item per request.

    Reusing the same key for two different drafts would replay the first item's
    terminal record and falsely claim the second item confirmed — the second
    occurrence is a deterministic per-item idempotency_conflict instead.
    """
    confirmed = SaveConfirmOutcome(
        outcome=STATE_CONFIRMED,
        request_id="request-1",
        request=accept_request(_draft_request("芙莉莲")),
        summary=None,
    )

    def process_one_item(
        item_id: str,
        draft_id: str,
        base_revision: int,
        idempotency_key: str,
    ) -> SaveConfirmOutcome:
        return confirmed

    process_one = build_batch_process_one(
        process_one_item,
        map_error=lambda item_id, exc: BatchSaveConfirmItemResult(
            item_id=item_id,
            outcome=BATCH_OUTCOME_FAILED,
            error_type=exc.error_type,
            error_message=exc.message,
        ),
    )
    result = run_batch_save_confirm(
        batch_id="batch-1",
        items=[
            ("item-1", "draft-1", 1, "shared-key"),
            ("item-2", "draft-2", 1, "shared-key"),
        ],
        item_ids=None,
        process_one=process_one,
    )
    assert result.results[0].outcome == BATCH_OUTCOME_CONFIRMED
    second = result.results[1]
    assert second.outcome == BATCH_OUTCOME_FAILED
    assert second.error_type == "idempotency_conflict"
    assert second.error_message == "同一请求中幂等键不能重复用于不同条目"
    assert second.request_id is None
    # process_one ran exactly once (only for item-1).
    assert result.summary() == {"requested": 2, "confirmed": 1, "failed": 1}


def test_batch_save_confirm_coordinator_maps_expected_error_to_failed() -> None:
    """US-216: a Stage1Error from one item is folded into a per-item failure."""
    confirmed = SaveConfirmOutcome(
        outcome=STATE_CONFIRMED,
        request_id="request-ok",
        request=accept_request(_draft_request("芙莉莲")),
        summary=None,
    )

    def process_one_item(
        item_id: str,
        draft_id: str,
        base_revision: int,
        idempotency_key: str,
    ) -> SaveConfirmOutcome:
        if item_id == "item-bad":
            raise Stage1Error(
                "idempotency_conflict",
                "相同的幂等键不能用于不同的保存确认操作",
                "save_confirm_idempotency",
                {"field": "idempotency_key", "reason": "payload_mismatch"},
            )
        return confirmed

    process_one = build_batch_process_one(
        process_one_item,
        map_error=lambda item_id, exc: BatchSaveConfirmItemResult(
            item_id=item_id,
            outcome=BATCH_OUTCOME_FAILED,
            error_type=exc.error_type,
            error_message=exc.message,
        ),
    )
    result = run_batch_save_confirm(
        batch_id="batch-1",
        items=[
            ("item-ok", "d-ok", 1, "k-ok"),
            ("item-bad", "d-bad", 1, "k-bad"),
        ],
        item_ids=None,
        process_one=process_one,
    )
    assert result.results[0].outcome == BATCH_OUTCOME_CONFIRMED
    bad = result.results[1]
    assert bad.outcome == BATCH_OUTCOME_FAILED
    assert bad.error_type == "idempotency_conflict"
    assert bad.request_id is None
    assert result.summary() == {"requested": 2, "confirmed": 1, "failed": 1}
    # The error details (fingerprint/key) never enter the serialized result.
    serialized = str(serialize_batch_save_confirm_result(result))
    assert "payload_mismatch" not in serialized
