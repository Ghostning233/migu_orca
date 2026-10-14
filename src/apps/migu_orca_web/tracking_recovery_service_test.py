from __future__ import annotations

"""US-226: web unified retry/recovery service tests.

These exercise ``run_tracking_retry`` / ``run_tracking_recover`` against a tmp
storage root with an injected submit seam — no external system is ever
contacted.  Accepted Requests come from the static fixture; records are seeded
through the handoff and then moved into the desired recoverable state.
"""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from apps.migu_orca_web.tracking_handoff import ensure_confirmed_request_tracking
from apps.migu_orca_web.tracking_recovery_service import run_tracking_recover
from apps.migu_orca_web.tracking_submission_service import run_tracking_retry
from plan_engine.controllers.data_sources import StaticFixtureDataSource
from plan_engine.controllers.plan_generation import build_plan
from request_engine.controllers.request_controller import accept_request
from shared.errors import Stage1Error
from shared.models import EntryRequest
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
    load_tracking_record,
)
from tracking_engine.models.operation import (
    TRACKING_OPERATION_KIND_SUBMIT,
    TRACKING_OPERATION_STATE_IN_PROGRESS,
    TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
    TRACKING_OPERATION_STATE_PREPARED,
    TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
    TRACKING_OPERATION_STATE_SUCCEEDED,
    TrackingOperation,
    transition_tracking_operation,
)
from tracking_engine.models.tracking import (
    TRACKING_AUDIT_ACTOR_USER,
    TRACKING_AUDIT_RECOVERY_AUTO_FAILED,
    TRACKING_AUDIT_RECOVERY_AUTO_SUCCEEDED,
    TRACKING_AUDIT_RECOVERY_MANUAL_FAILED,
    TRACKING_AUDIT_RECOVERY_MANUAL_SUCCEEDED,
    TRACKING_AUDIT_RECOVERY_NEEDS_MANUAL,
    TRACKING_AUDIT_SUBMIT_OUTCOME_UNKNOWN,
    TRACKING_AUDIT_SUBMIT_STARTED,
    TRACKING_AUDIT_SUBMIT_SUCCEEDED,
    TRACKING_ORIGIN_SAVE_CONFIRM,
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_PENDING_SUBMIT,
    TRACKING_STATUS_RECOVERY_REQUIRED,
    TRACKING_STATUS_SUBMIT_FAILED,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
    TrackingRecord,
    transition_record,
)

NOW = "2026-09-08T00:00:00+00:00"


class _FakeAbConfig:
    """Minimal request-scoped config object for tests."""


def _config(tmp_path: Path) -> StorageConfig:
    return load_storage_config(tmp_path / "storage")


def _accepted_request(
    tmp_path: Path,
    request_id: str = "request-1",
) -> dict[str, Any]:
    config = _config(tmp_path)
    request = accept_request(
        {
            **build_plan(EntryRequest(raw_title="芙莉莲"), data_source=StaticFixtureDataSource())["request"],
            "request_id": request_id,
        }
    )
    save_request_snapshot(config, request)
    return request


def _seeded_tracking(tmp_path: Path, request: dict[str, Any]) -> TrackingRecord:
    config = _config(tmp_path)
    handoff = ensure_confirmed_request_tracking(
        config=config,
        request=request,
        origin=TRACKING_ORIGIN_SAVE_CONFIRM,
        now=NOW,
    )
    assert handoff.tracking_ready is True
    assert handoff.tracking_id is not None
    return load_tracking_record(config, handoff.tracking_id)


def _move_record(
    tmp_path: Path,
    record: TrackingRecord,
    status: str,
    *,
    audit_action: str = TRACKING_AUDIT_SUBMIT_OUTCOME_UNKNOWN,
    current_operation_id: str | None = None,
    now: str = NOW,
) -> TrackingRecord:
    """Persist the record in ``status`` (optionally bound to an operation)."""
    config = _config(tmp_path)
    next_record = transition_record(
        record,
        status=status,
        audit_action=audit_action,
        operation_id=current_operation_id,
        now=now,
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
    tmp_path: Path,
    record: TrackingRecord,
    *,
    key: str = "op-key-1",
) -> TrackingOperation:
    """Bind a PREPARED operation and advance it to IN_PROGRESS."""
    config = _config(tmp_path)
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


def _save_ab_result(tmp_path: Path, request_id: str, ab_result: dict[str, Any]) -> None:
    config = _config(tmp_path)
    request = load_request_snapshot(config, request_id)
    request["ab_submit_result"] = ab_result
    save_request_snapshot(config, request)


def _ab_success() -> dict[str, Any]:
    return {
        "success": True,
        "ab_subscription_id": "ab-subscription-1",
        "ab_response": {"id": "ab-subscription-1", "status": "created"},
        "fallback_config": None,
        "error": None,
    }


def _ab_definite_failure() -> dict[str, Any]:
    return {
        "success": False,
        "ab_subscription_id": None,
        "ab_response": None,
        "fallback_config": None,
        "error": {
            "error_type": "ab_auth_failed",
            "error_message": "Auto Bangumi 认证失败",
            "failed_step": "create_ab_subscription",
            "details": {"status_code": 401},
        },
    }


def _recover_kwargs(
    config: StorageConfig,
    record: TrackingRecord,
    *,
    action: str = "AUTO",
    expected_revision: int | None = None,
    confirm: bool = False,
):
    return {
        "config": config,
        "tracking_id": record.tracking_id,
        "expected_revision": expected_revision or record.revision,
        "action": action,
        "confirm": confirm,
        "now": NOW,
    }


def _error_type(exc: Stage1Error) -> str:
    return exc.error_type


# ---------------------------------------------------------------------------
# AUTO recovery
# ---------------------------------------------------------------------------


def test_auto_resolves_verifying_external_to_active_from_ab_result(
    tmp_path: Path,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    _save_ab_result(tmp_path, "request-1", _ab_success())
    verifying = _move_record(
        tmp_path, record, TRACKING_STATUS_VERIFYING_EXTERNAL
    )
    config = _config(tmp_path)

    result = run_tracking_recover(
        **_recover_kwargs(config, verifying, action="AUTO")
    )

    assert result["outcome"] == TRACKING_STATUS_ACTIVE
    assert result["needs_manual"] is False
    assert result["next_revision"] == verifying.revision + 1
    after = load_tracking_record(config, record.tracking_id)
    assert after.status == TRACKING_STATUS_ACTIVE
    assert after.audit_events[-1]["action"] == TRACKING_AUDIT_RECOVERY_AUTO_SUCCEEDED
    assert after.audit_events[-1]["actor"] == "SYSTEM"


def test_auto_resolves_recovery_required_to_submit_failed_from_definite_failure(
    tmp_path: Path,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    _save_ab_result(tmp_path, "request-1", _ab_definite_failure())
    recovery = _move_record(
        tmp_path, record, TRACKING_STATUS_RECOVERY_REQUIRED
    )
    config = _config(tmp_path)

    result = run_tracking_recover(
        **_recover_kwargs(config, recovery, action="AUTO")
    )

    assert result["outcome"] == TRACKING_STATUS_SUBMIT_FAILED
    after = load_tracking_record(config, record.tracking_id)
    assert after.status == TRACKING_STATUS_SUBMIT_FAILED
    assert after.audit_events[-1]["action"] == TRACKING_AUDIT_RECOVERY_AUTO_FAILED


def test_auto_without_evidence_moves_verifying_external_to_recovery_required(
    tmp_path: Path,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    verifying = _move_record(
        tmp_path, record, TRACKING_STATUS_VERIFYING_EXTERNAL
    )
    config = _config(tmp_path)

    result = run_tracking_recover(
        **_recover_kwargs(config, verifying, action="AUTO")
    )

    assert result["outcome"] == TRACKING_STATUS_RECOVERY_REQUIRED
    assert result["needs_manual"] is True
    after = load_tracking_record(config, record.tracking_id)
    assert after.status == TRACKING_STATUS_RECOVERY_REQUIRED
    assert after.audit_events[-1]["action"] == TRACKING_AUDIT_RECOVERY_NEEDS_MANUAL


def test_auto_without_evidence_keeps_recovery_required_without_revision_bump(
    tmp_path: Path,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    recovery = _move_record(
        tmp_path, record, TRACKING_STATUS_RECOVERY_REQUIRED
    )
    config = _config(tmp_path)

    result = run_tracking_recover(
        **_recover_kwargs(config, recovery, action="AUTO")
    )

    assert result["outcome"] == TRACKING_STATUS_RECOVERY_REQUIRED
    assert result["needs_manual"] is True
    assert result["next_revision"] == recovery.revision  # unchanged no-op
    after = load_tracking_record(config, record.tracking_id)
    assert after.status == TRACKING_STATUS_RECOVERY_REQUIRED
    assert after.revision == recovery.revision
    assert after.audit_events[-1]["action"] != TRACKING_AUDIT_RECOVERY_NEEDS_MANUAL


def test_auto_resolves_in_flight_operation_and_terminalizes_succeeded(
    tmp_path: Path,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    op = _bind_in_flight_operation(tmp_path, record)
    _save_ab_result(tmp_path, "request-1", _ab_success())
    verifying = _move_record(
        tmp_path,
        record,
        TRACKING_STATUS_VERIFYING_EXTERNAL,
        current_operation_id=op.operation_id,
    )
    config = _config(tmp_path)

    result = run_tracking_recover(
        **_recover_kwargs(config, verifying, action="AUTO")
    )

    assert result["outcome"] == TRACKING_STATUS_ACTIVE
    operation = load_tracking_operation(config, op.operation_id)
    assert operation.state == TRACKING_OPERATION_STATE_SUCCEEDED


def test_auto_needs_manual_terminalizes_in_flight_operation_to_recovery_required(
    tmp_path: Path,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    op = _bind_in_flight_operation(tmp_path, record)
    verifying = _move_record(
        tmp_path,
        record,
        TRACKING_STATUS_VERIFYING_EXTERNAL,
        current_operation_id=op.operation_id,
    )
    config = _config(tmp_path)

    result = run_tracking_recover(
        **_recover_kwargs(config, verifying, action="AUTO")
    )

    assert result["outcome"] == TRACKING_STATUS_RECOVERY_REQUIRED
    assert result["needs_manual"] is True
    operation = load_tracking_operation(config, op.operation_id)
    assert operation.state == TRACKING_OPERATION_STATE_RECOVERY_REQUIRED


def test_auto_terminal_outcome_unknown_operation_uses_ab_result(tmp_path: Path) -> None:
    """A terminal OUTCOME_UNKNOWN op plus a persisted success resolves ACTIVE."""
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    op = _bind_in_flight_operation(tmp_path, record, key="op-key-2")
    config = _config(tmp_path)
    # Advance the operation to terminal OUTCOME_UNKNOWN.
    compare_and_swap_tracking_operation(
        config,
        op.operation_id,
        expected_state=TRACKING_OPERATION_STATE_IN_PROGRESS,
        record=transition_tracking_operation(
            op,
            state=TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
            error_type="ab_timeout",
            now=NOW,
        ),
    )
    _save_ab_result(tmp_path, "request-1", _ab_success())
    verifying = _move_record(
        tmp_path,
        record,
        TRACKING_STATUS_VERIFYING_EXTERNAL,
        current_operation_id=op.operation_id,
    )

    result = run_tracking_recover(
        **_recover_kwargs(config, verifying, action="AUTO")
    )

    assert result["outcome"] == TRACKING_STATUS_ACTIVE


# ---------------------------------------------------------------------------
# Manual recovery
# ---------------------------------------------------------------------------


def test_manual_mark_succeeded_requires_confirm(tmp_path: Path) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    verifying = _move_record(
        tmp_path, record, TRACKING_STATUS_VERIFYING_EXTERNAL
    )
    with pytest.raises(Stage1Error) as excinfo:
        run_tracking_recover(
            **_recover_kwargs(
                _config(tmp_path),
                verifying,
                action="MARK_SUCCEEDED",
                confirm=False,
            )
        )
    assert _error_type(excinfo.value) == "tracking_confirmation_required"


def test_manual_mark_succeeded_writes_user_audit_and_active(tmp_path: Path) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    verifying = _move_record(
        tmp_path, record, TRACKING_STATUS_VERIFYING_EXTERNAL
    )
    config = _config(tmp_path)

    result = run_tracking_recover(
        **_recover_kwargs(
            config,
            verifying,
            action="MARK_SUCCEEDED",
            confirm=True,
        )
    )

    assert result["outcome"] == TRACKING_STATUS_ACTIVE
    after = load_tracking_record(config, record.tracking_id)
    assert after.status == TRACKING_STATUS_ACTIVE
    assert after.audit_events[-1]["action"] == TRACKING_AUDIT_RECOVERY_MANUAL_SUCCEEDED
    assert after.audit_events[-1]["actor"] == TRACKING_AUDIT_ACTOR_USER


def test_manual_mark_failed_resolves_recovery_required_to_submit_failed(
    tmp_path: Path,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    recovery = _move_record(
        tmp_path, record, TRACKING_STATUS_RECOVERY_REQUIRED
    )
    config = _config(tmp_path)

    result = run_tracking_recover(
        **_recover_kwargs(
            config,
            recovery,
            action="MARK_FAILED",
            confirm=True,
        )
    )

    assert result["outcome"] == TRACKING_STATUS_SUBMIT_FAILED
    after = load_tracking_record(config, record.tracking_id)
    assert after.status == TRACKING_STATUS_SUBMIT_FAILED
    assert after.audit_events[-1]["action"] == TRACKING_AUDIT_RECOVERY_MANUAL_FAILED
    assert after.audit_events[-1]["actor"] == TRACKING_AUDIT_ACTOR_USER


def test_manual_mark_succeeded_terminalizes_in_flight_operation(
    tmp_path: Path,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    op = _bind_in_flight_operation(tmp_path, record)
    verifying = _move_record(
        tmp_path,
        record,
        TRACKING_STATUS_VERIFYING_EXTERNAL,
        current_operation_id=op.operation_id,
    )
    config = _config(tmp_path)

    result = run_tracking_recover(
        **_recover_kwargs(
            config,
            verifying,
            action="MARK_SUCCEEDED",
            confirm=True,
        )
    )

    assert result["outcome"] == TRACKING_STATUS_ACTIVE
    operation = load_tracking_operation(config, op.operation_id)
    assert operation.state == TRACKING_OPERATION_STATE_SUCCEEDED


def test_manual_mark_failed_without_confirm_raises(tmp_path: Path) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    recovery = _move_record(
        tmp_path, record, TRACKING_STATUS_RECOVERY_REQUIRED
    )
    with pytest.raises(Stage1Error) as excinfo:
        run_tracking_recover(
            **_recover_kwargs(
                _config(tmp_path),
                recovery,
                action="MARK_FAILED",
                confirm=False,
            )
        )
    assert _error_type(excinfo.value) == "tracking_confirmation_required"


# ---------------------------------------------------------------------------
# Precondition guards
# ---------------------------------------------------------------------------


def test_recover_rejects_pending_submit_state(tmp_path: Path) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    assert record.status == TRACKING_STATUS_PENDING_SUBMIT
    with pytest.raises(Stage1Error) as excinfo:
        run_tracking_recover(
            **_recover_kwargs(_config(tmp_path), record, action="AUTO")
        )
    assert _error_type(excinfo.value) == "tracking_state_conflict"


def test_recover_rejects_stale_revision(tmp_path: Path) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    verifying = _move_record(
        tmp_path, record, TRACKING_STATUS_VERIFYING_EXTERNAL
    )
    with pytest.raises(Stage1Error) as excinfo:
        run_tracking_recover(
            **_recover_kwargs(
                _config(tmp_path),
                verifying,
                action="AUTO",
                expected_revision=verifying.revision + 99,
            )
        )
    assert _error_type(excinfo.value) == "tracking_revision_conflict"


def test_recover_rejects_unknown_action(tmp_path: Path) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    verifying = _move_record(
        tmp_path, record, TRACKING_STATUS_VERIFYING_EXTERNAL
    )
    with pytest.raises(Stage1Error) as excinfo:
        run_tracking_recover(
            **_recover_kwargs(
                _config(tmp_path), verifying, action="VERIFY_EXTERNAL"
            )
        )
    assert _error_type(excinfo.value) == "validation_error"


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------


def _counting_submit_one(calls: list[int], result: dict[str, Any] | None = None):
    def submit_one(request: dict[str, Any], ab_config: Any) -> dict[str, Any]:
        calls.append(1)
        return result if result is not None else _ab_success()

    return submit_one


def test_retry_only_allowed_from_submit_failed_and_submits(tmp_path: Path) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    failed = _move_record(
        tmp_path,
        record,
        TRACKING_STATUS_SUBMIT_FAILED,
        audit_action="SUBMIT_FAILED",
    )
    config = _config(tmp_path)
    calls: list[int] = []

    result = run_tracking_retry(
        config,
        tracking_id=record.tracking_id,
        expected_revision=failed.revision,
        idempotency_key="retry-key-1",
        confirm=True,
        ab_config=_FakeAbConfig(),
        submit_one=_counting_submit_one(calls),
        now=NOW,
    )

    assert result["outcome"] == TRACKING_STATUS_ACTIVE
    assert len(calls) == 1
    after = load_tracking_record(config, record.tracking_id)
    assert after.status == TRACKING_STATUS_ACTIVE
    actions = [event["action"] for event in after.audit_events]
    assert TRACKING_AUDIT_SUBMIT_STARTED in actions
    assert TRACKING_AUDIT_SUBMIT_SUCCEEDED in actions


def test_retry_rejects_pending_submit_record(tmp_path: Path) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    assert record.status == TRACKING_STATUS_PENDING_SUBMIT
    with pytest.raises(Stage1Error) as excinfo:
        run_tracking_retry(
            _config(tmp_path),
            tracking_id=record.tracking_id,
            expected_revision=record.revision,
            idempotency_key="retry-key-2",
            confirm=True,
            ab_config=_FakeAbConfig(),
            now=NOW,
        )
    assert _error_type(excinfo.value) == "tracking_state_conflict"


def test_retry_rejects_verifying_external_record(tmp_path: Path) -> None:
    """VERIFYING_EXTERNAL must be recovered, never blindly retried (D29-07)."""
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    verifying = _move_record(
        tmp_path, record, TRACKING_STATUS_VERIFYING_EXTERNAL
    )
    with pytest.raises(Stage1Error) as excinfo:
        run_tracking_retry(
            _config(tmp_path),
            tracking_id=record.tracking_id,
            expected_revision=verifying.revision,
            idempotency_key="retry-key-3",
            confirm=True,
            ab_config=_FakeAbConfig(),
            now=NOW,
        )
    assert _error_type(excinfo.value) == "tracking_state_conflict"


def test_retry_requires_confirm(tmp_path: Path) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    failed = _move_record(
        tmp_path,
        record,
        TRACKING_STATUS_SUBMIT_FAILED,
        audit_action="SUBMIT_FAILED",
    )
    with pytest.raises(Stage1Error) as excinfo:
        run_tracking_retry(
            _config(tmp_path),
            tracking_id=record.tracking_id,
            expected_revision=failed.revision,
            idempotency_key="retry-key-4",
            confirm=False,
            ab_config=_FakeAbConfig(),
            now=NOW,
        )
    assert _error_type(excinfo.value) == "tracking_confirmation_required"
