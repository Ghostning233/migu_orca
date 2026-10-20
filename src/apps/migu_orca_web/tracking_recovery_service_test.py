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
    TRACKING_OPERATION_STATE_PREPARED,
    TrackingOperation,
    transition_tracking_operation,
)
from tracking_engine.models.tracking import (
    TRACKING_AUDIT_SUBMIT_OUTCOME_UNKNOWN,
    TRACKING_AUDIT_SUBMIT_STARTED,
    TRACKING_AUDIT_SUBMIT_SUCCEEDED,
    TRACKING_ORIGIN_SAVE_CONFIRM,
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_PENDING_SUBMIT,
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
# The recovery family converges on the read-only external verification (#228)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("action", ["AUTO", "MARK_SUCCEEDED", "MARK_FAILED"])
def test_retired_recovery_actions_are_rejected_without_any_write(
    tmp_path: Path, action: str
) -> None:
    """#228 E2/E3/E5: 自动恢复/标记成功/标记失败 are retired user actions.

    The request is rejected before any state is touched: the record keeps its
    status, revision and audit trail, the bound operation stays in flight, and
    no new operation is created.  The read-only external verification is the
    only recovery the executable set still accepts.
    """
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    _save_ab_result(tmp_path, "request-1", _ab_success())
    op = _bind_in_flight_operation(tmp_path, record)
    verifying = _move_record(
        tmp_path,
        record,
        TRACKING_STATUS_VERIFYING_EXTERNAL,
        current_operation_id=op.operation_id,
    )
    config = _config(tmp_path)
    before = load_tracking_record(config, record.tracking_id)

    for confirm in (False, True):
        with pytest.raises(Stage1Error) as excinfo:
            run_tracking_recover(
                **_recover_kwargs(config, verifying, action=action, confirm=confirm)
            )
        assert _error_type(excinfo.value) == "validation_error"
        # The rejection names the retired action, not some unrelated field.
        assert excinfo.value.details.get("field") == "action"

    after = load_tracking_record(config, record.tracking_id)
    assert after.status == TRACKING_STATUS_VERIFYING_EXTERNAL
    assert after.revision == before.revision
    assert after.audit_events == before.audit_events
    assert after.current_operation_id == before.current_operation_id
    assert (
        load_tracking_operation(config, op.operation_id).state
        == TRACKING_OPERATION_STATE_IN_PROGRESS
    )


def test_read_only_external_verification_is_the_only_accepted_recovery_action(
    tmp_path: Path,
) -> None:
    """#228 E5: VERIFY_EXTERNAL still passes the executable-action gate.

    Without a connection the verification stops on its own configuration guard
    (``field=ab_config``), which proves the action itself is accepted — unlike a
    retired action, which is refused on ``field=action``.
    """
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    verifying = _move_record(
        tmp_path, record, TRACKING_STATUS_VERIFYING_EXTERNAL
    )
    with pytest.raises(Stage1Error) as excinfo:
        run_tracking_recover(
            **_recover_kwargs(_config(tmp_path), verifying, action="VERIFY_EXTERNAL")
        )
    assert _error_type(excinfo.value) == "validation_error"
    assert excinfo.value.details.get("field") == "ab_config"


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
