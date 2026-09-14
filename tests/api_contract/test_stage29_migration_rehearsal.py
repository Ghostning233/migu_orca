from __future__ import annotations

"""US-227: end-to-end migration & recovery rehearsal on sanitized fixtures.

This module is the Stage 29 PRD §US-227 "rehearsal" evidence.  It drives the
real web service layer against a tmp storage profile seeded only with sanitized
fixture data (static-catalog Requests, hand-written queue/AB-result records) so
the workspace ``.migu_orca/storage`` and every external system are never
touched.  Four contract scenarios are rehearsed:

1. **Full migration** over a mixed Request / legacy-queue / AB-result fixture
   set, plus an idempotent re-run that adds nothing;
2. **Partial migration** (one damaged source file) followed by retry after
   repair -> COMPLETE without duplicates;
3. **Crash window**: a durable ``VERIFYING_EXTERNAL`` record left behind by an
   interrupted submit is resolved by pure-local ``AUTO`` recovery (no external
   call), while an unresolved ``RECOVERY_REQUIRED`` record cannot be blindly
   retried;
4. **Legacy-entry compatibility & rollback**: old queue/AB outcomes project
   into tracking, a durable ``ACTIVE`` is never downgraded by a stale queue
   item, and a same-key terminal replay returns the original outcome without a
   second external call.
"""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from apps.migu_orca_entry.controllers.entry_controller import generate_request
from apps.migu_orca_web.tracking_handoff import ensure_confirmed_request_tracking
from apps.migu_orca_web.tracking_migration_service import (
    MIGRATION_PARTIAL_WARNING,
    run_tracking_migration,
)
from apps.migu_orca_web.tracking_recovery_service import run_tracking_recover
from apps.migu_orca_web.tracking_submission_service import run_tracking_submit
from batch_engine.models import (
    BATCH_QUEUE_STATUS_FAILED,
    BATCH_QUEUE_STATUS_READY_TO_SUBMIT,
    BATCH_QUEUE_STATUS_SUCCEEDED,
    BatchQueueItem,
    BatchSubmissionQueue,
)
from request_engine.controllers.request_controller import accept_request
from shared.errors import Stage1Error
from shared.models import EntryRequest
from storage_engine.controllers.ab_result_repository import save_ab_submit_result
from storage_engine.controllers.operation_repository import (
    bind_tracking_operation,
    compare_and_swap_tracking_operation,
    load_tracking_operation,
)
from storage_engine.controllers.request_repository import (
    load_request_snapshot,
    save_request_snapshot,
)
from storage_engine.controllers.storage_config import (
    StorageConfig,
    load_storage_config,
)
from storage_engine.controllers.tracking_repository import (
    compare_and_swap_tracking_record,
    list_tracking_records,
    load_tracking_record,
)
from tests.legacy_queue_fixture import write_legacy_queue_fixture
from tracking_engine.models.operation import (
    TRACKING_OPERATION_KIND_SUBMIT,
    TRACKING_OPERATION_STATE_IN_PROGRESS,
    TRACKING_OPERATION_STATE_PREPARED,
    TRACKING_OPERATION_STATE_SUCCEEDED,
    transition_tracking_operation,
)
from tracking_engine.models.tracking import (
    TRACKING_ORIGIN_MIGRATED_QUEUE,
    TRACKING_ORIGIN_SAVE_CONFIRM,
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_PENDING_SUBMIT,
    TRACKING_STATUS_RECOVERY_REQUIRED,
    TRACKING_STATUS_SUBMIT_FAILED,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
    TrackingRecord,
    tracking_id_for_request,
    transition_record,
)

NOW = "2026-09-08T00:00:00+00:00"


# ---------------------------------------------------------------------------
# Sanitized-fixture helpers
# ---------------------------------------------------------------------------


def _config(tmp_path: Path, name: str = "storage") -> StorageConfig:
    return load_storage_config(tmp_path / name)


def _accepted_request(tmp_path: Path, request_id: str, *, root: str = "storage") -> dict[str, Any]:
    """Persist one sanitized ACCEPTED Request from the static fixture catalog."""
    config = _config(tmp_path, root)
    request = accept_request(
        {
            **generate_request(EntryRequest(raw_title="芙莉莲"))["request"],
            "request_id": request_id,
        }
    )
    save_request_snapshot(config, request)
    return request


def _ensure_tracking(tmp_path: Path, request: dict[str, Any], *, root: str = "storage") -> TrackingRecord:
    config = _config(tmp_path, root)
    handoff = ensure_confirmed_request_tracking(
        config=config,
        request=request,
        origin=TRACKING_ORIGIN_SAVE_CONFIRM,
        now=NOW,
    )
    assert handoff.tracking_ready is True
    assert handoff.tracking_id is not None
    return load_tracking_record(config, handoff.tracking_id)


def _save_queue(
    config: StorageConfig,
    batch_id: str,
    entries: list[tuple[str, str]],
) -> None:
    """Persist a legacy batch queue whose items only carry safe metadata."""
    items = [
        BatchQueueItem(
            queue_id=f"queue-{batch_id}",
            batch_id=batch_id,
            item_id=f"item-{index}",
            request_id=request_id,
            title="占位标题",
            status=status,
            created_at=NOW,
            updated_at=NOW,
        )
        for index, (request_id, status) in enumerate(entries)
    ]
    write_legacy_queue_fixture(
        config,
        BatchSubmissionQueue(
            queue_id=f"queue-{batch_id}",
            batch_id=batch_id,
            items=items,
            created_at=NOW,
            updated_at=NOW,
        ),
    )


def _save_ab_result(config: StorageConfig, request_id: str, *, success: bool) -> None:
    save_ab_submit_result(
        config,
        {
            "request_id": request_id,
            "ab_submit_result": {
                "success": success,
                "ab_subscription_id": "ab-123" if success else None,
                "error": None if success else {"error_type": "ab_rejected"},
            },
        },
    )


def _record_by_request(
    config: StorageConfig,
    records: list[TrackingRecord],
    request_id: str,
) -> TrackingRecord:
    (match,) = [record for record in records if record.request_id == request_id]
    return match


def _move_record(
    config: StorageConfig,
    record: TrackingRecord,
    status: str,
    *,
    current_operation_id: str | None = None,
) -> TrackingRecord:
    next_record = transition_record(
        record,
        status=status,
        audit_action="SUBMIT_OUTCOME_UNKNOWN",
        operation_id=current_operation_id,
        now=NOW,
    )
    if current_operation_id is not None:
        next_record = replace(next_record, current_operation_id=current_operation_id)
    return compare_and_swap_tracking_record(
        config,
        record.tracking_id,
        base_revision=record.revision,
        record=next_record,
    )


def _bind_in_flight_operation(
    config: StorageConfig,
    record: TrackingRecord,
    *,
    key: str = "crash-key",
):
    bound, created = bind_tracking_operation(
        config,
        tracking_id=record.tracking_id,
        operation=TRACKING_OPERATION_KIND_SUBMIT,
        idempotency_key=key,
        expected_revision=record.revision,
        request_fingerprint=record.request_fingerprint or "fingerprint",
        now=NOW,
    )
    assert created is True
    return compare_and_swap_tracking_operation(
        config,
        bound.operation_id,
        expected_state=TRACKING_OPERATION_STATE_PREPARED,
        record=transition_tracking_operation(
            bound,
            state=TRACKING_OPERATION_STATE_IN_PROGRESS,
            now=NOW,
        ),
    )


def _ab_success() -> dict[str, Any]:
    return {
        "success": True,
        "ab_subscription_id": "ab-subscription-1",
        "ab_response": {"id": "ab-subscription-1", "status": "created"},
        "fallback_config": None,
        "error": None,
    }


def _save_request_ab_result(tmp_path: Path, request_id: str, *, root: str = "storage") -> None:
    """Persist a sanitized AB result *inside* the Request snapshot (US-226 evidence)."""
    config = _config(tmp_path, root)
    request = load_request_snapshot(config, request_id)
    request["ab_submit_result"] = _ab_success()
    save_request_snapshot(config, request)


def _counting_submit_one(calls: list[int]):
    def submit_one(request: dict[str, Any], ab_config: Any) -> dict[str, Any]:
        calls.append(1)
        return _ab_success()

    return submit_one


class _FakeAbConfig:
    """Minimal request-scoped config object."""


# ---------------------------------------------------------------------------
# Rehearsal 1: full historical migration + idempotent re-run
# ---------------------------------------------------------------------------


def test_rehearsal_full_migration_on_sanitized_fixtures_and_repeat_is_idempotent(
    tmp_path: Path,
) -> None:
    root = "full"
    # One ACCEPTED Request with each historical evidence shape (§10.2).
    _accepted_request(tmp_path, "r-request-only", root=root)
    _accepted_request(tmp_path, "r-queue-ready", root=root)
    _accepted_request(tmp_path, "r-queue-failed", root=root)
    _accepted_request(tmp_path, "r-queue-succ-noab", root=root)
    _accepted_request(tmp_path, "r-ab-active", root=root)
    config = _config(tmp_path, root)
    _save_queue(
        config,
        "batch-ready",
        [("r-queue-ready", BATCH_QUEUE_STATUS_READY_TO_SUBMIT)],
    )
    _save_queue(
        config,
        "batch-failed",
        [("r-queue-failed", BATCH_QUEUE_STATUS_FAILED)],
    )
    _save_queue(
        config,
        "batch-succ",
        [("r-queue-succ-noab", BATCH_QUEUE_STATUS_SUCCEEDED)],
    )
    _save_ab_result(config, "r-ab-active", success=True)

    first = run_tracking_migration(config=config, now=NOW)

    assert first.complete
    assert first.warning() is None
    assert first.manifest.counts.created == 5
    assert first.manifest.counts.existing == 0
    assert first.manifest.counts.recovery_required == 1
    records = list_tracking_records(config).records
    assert len(records) == 5
    assert _record_by_request(config, records, "r-request-only").status == TRACKING_STATUS_PENDING_SUBMIT
    assert (
        _record_by_request(config, records, "r-queue-ready").status
        == TRACKING_STATUS_PENDING_SUBMIT
    )
    assert (
        _record_by_request(config, records, "r-queue-ready").origin
        == TRACKING_ORIGIN_MIGRATED_QUEUE
    )
    assert (
        _record_by_request(config, records, "r-queue-failed").status
        == TRACKING_STATUS_SUBMIT_FAILED
    )
    assert (
        _record_by_request(config, records, "r-queue-succ-noab").status
        == TRACKING_STATUS_RECOVERY_REQUIRED
    )
    assert _record_by_request(config, records, "r-ab-active").status == TRACKING_STATUS_ACTIVE

    # Deterministic tracking ids: same Request always maps to the same record.
    for record in records:
        assert record.tracking_id == tracking_id_for_request(record.request_id)

    # Re-run: the manifest is COMPLETE so no full scan happens and nothing is
    # added or re-audited.
    second = run_tracking_migration(config=config, now=NOW)
    assert second.replayed is True
    assert second.manifest.counts.created == 5
    assert len(list_tracking_records(config).records) == 5


# ---------------------------------------------------------------------------
# Rehearsal 2: partial migration then retry after repair
# ---------------------------------------------------------------------------


def test_rehearsal_partial_migration_then_retry_after_repair_completes(
    tmp_path: Path,
) -> None:
    root = "partial"
    _accepted_request(tmp_path, "req-healthy", root=root)
    config = _config(tmp_path, root)
    config.requests_dir.mkdir(parents=True, exist_ok=True)
    (config.requests_dir / "req-broken.json").write_text("{bad json", encoding="utf-8")

    first = run_tracking_migration(config=config, now=NOW)

    assert first.partial
    assert first.warning() == MIGRATION_PARTIAL_WARNING
    assert first.manifest.counts.unreadable == 1
    assert first.manifest.counts.created == 1
    records = list_tracking_records(config).records
    assert len(records) == 1
    assert records[0].request_id == "req-healthy"
    # The damaged file is never copied back to any API surface.
    manifest_text = (config.tracking_migrations_dir / "schema-v1.json").read_text(encoding="utf-8")
    assert "req-broken" not in manifest_text
    assert "bad json" not in manifest_text

    # "Repair": replace the broken source with a real ACCEPTED Request and retry.
    (config.requests_dir / "req-broken.json").unlink()
    _accepted_request(tmp_path, "req-broken", root=root)

    second = run_tracking_migration(config=config, now=NOW)

    assert second.complete
    assert second.manifest.counts.created == 1  # only the repaired request is new
    assert second.manifest.counts.existing == 1
    assert second.manifest.counts.unreadable == 0
    records = list_tracking_records(config).records
    assert len(records) == 2
    assert _record_by_request(config, records, "req-healthy").status == TRACKING_STATUS_PENDING_SUBMIT
    assert _record_by_request(config, records, "req-broken").status == TRACKING_STATUS_PENDING_SUBMIT


# ---------------------------------------------------------------------------
# Rehearsal 3: crash window -> pure-local AUTO recovery, never a blind retry
# ---------------------------------------------------------------------------


def test_rehearsal_crash_window_auto_recovery_resolves_without_external_call(
    tmp_path: Path,
) -> None:
    root = "crash"
    request = _accepted_request(tmp_path, "request-1", root=root)
    record = _ensure_tracking(tmp_path, request, root=root)
    config = _config(tmp_path, root)
    op = _bind_in_flight_operation(config, record)
    verifying = _move_record(
        config,
        record,
        TRACKING_STATUS_VERIFYING_EXTERNAL,
        current_operation_id=op.operation_id,
    )
    # The external call happened and its sanitized result was persisted before
    # the process died; only the record finalization was lost.
    _save_request_ab_result(tmp_path, "request-1", root=root)

    result = run_tracking_recover(
        config=config,
        tracking_id=record.tracking_id,
        expected_revision=verifying.revision,
        action="AUTO",
        confirm=False,
        now=NOW,
    )

    assert result["outcome"] == TRACKING_STATUS_ACTIVE
    assert result["needs_manual"] is False
    after = load_tracking_record(config, record.tracking_id)
    assert after.status == TRACKING_STATUS_ACTIVE
    operation = load_tracking_operation(config, op.operation_id)
    assert operation.state == TRACKING_OPERATION_STATE_SUCCEEDED


def test_rehearsal_unresolved_recovery_required_cannot_be_blindly_retried(
    tmp_path: Path,
) -> None:
    root = "crash-unresolved"
    request = _accepted_request(tmp_path, "request-2", root=root)
    record = _ensure_tracking(tmp_path, request, root=root)
    config = _config(tmp_path, root)
    op = _bind_in_flight_operation(config, record, key="crash-key-2")
    _move_record(
        config,
        record,
        TRACKING_STATUS_VERIFYING_EXTERNAL,
        current_operation_id=op.operation_id,
    )
    # No local AB evidence: AUTO recovery must move it to RECOVERY_REQUIRED and
    # ask for manual resolution — it must never auto-call the external system.
    resolved = run_tracking_recover(
        config=config,
        tracking_id=record.tracking_id,
        expected_revision=record.revision + 1,
        action="AUTO",
        confirm=False,
        now=NOW,
    )
    assert resolved["outcome"] == TRACKING_STATUS_RECOVERY_REQUIRED
    assert resolved["needs_manual"] is True

    # A retry from RECOVERY_REQUIRED is rejected before any external call.
    with pytest.raises(Stage1Error) as excinfo:
        run_tracking_submit(
            config=config,
            tracking_id=record.tracking_id,
            expected_revision=resolved["next_revision"],
            idempotency_key="new-retry-key",
            confirm=True,
            ab_config=_FakeAbConfig(),
            submit_one=_counting_submit_one([]),
            now=NOW,
        )
    assert excinfo.value.error_type == "tracking_state_conflict"


# ---------------------------------------------------------------------------
# Rehearsal 4: legacy-entry compatibility & rollback safety
# ---------------------------------------------------------------------------






def test_rehearsal_same_key_terminal_replay_returns_same_outcome_no_second_call(
    tmp_path: Path,
) -> None:
    root = "replay"
    request = _accepted_request(tmp_path, "req-replay", root=root)
    record = _ensure_tracking(tmp_path, request, root=root)
    config = _config(tmp_path, root)
    calls: list[int] = []

    def kwargs(expected_revision: int, key: str) -> dict[str, Any]:
        return {
            "config": config,
            "tracking_id": record.tracking_id,
            "expected_revision": expected_revision,
            "idempotency_key": key,
            "confirm": True,
            "ab_config": _FakeAbConfig(),
            "submit_one": _counting_submit_one(calls),
            "now": NOW,
        }

    first = run_tracking_submit(**kwargs(record.revision, "replay-key"))
    assert first["outcome"] == TRACKING_STATUS_ACTIVE
    assert len(calls) == 1

    replayed = run_tracking_submit(**kwargs(record.revision, "replay-key"))
    assert replayed["outcome"] == TRACKING_STATUS_ACTIVE
    assert replayed["operation_id"] == first["operation_id"]
    assert len(calls) == 1  # replay never calls the external system again
