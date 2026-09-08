from __future__ import annotations

"""US-225: web unified submit service tests.

These exercise ``run_tracking_submit`` against a tmp storage root with injected
submit/persist seams — no external system is ever contacted.  Accepted Requests
come from the static fixture; records are seeded through the handoff.
"""

import threading
from pathlib import Path
from typing import Any

import pytest

from apps.migu_orca_entry.controllers.entry_controller import generate_request
from apps.migu_orca_web.tracking_handoff import ensure_confirmed_request_tracking
from apps.migu_orca_web.tracking_submission_service import run_tracking_submit
from request_engine.controllers.request_controller import accept_request
from shared.errors import Stage1Error
from shared.models import EntryRequest
from storage_engine.controllers.operation_repository import load_tracking_operation
from storage_engine.controllers.request_repository import (
    load_request_snapshot,
    save_request_snapshot,
)
from storage_engine.controllers.storage_config import (
    StorageConfig,
    load_storage_config,
)
from storage_engine.controllers.tracking_repository import (
    load_tracking_record,
)
from tracking_engine.models.operation import (
    TRACKING_OPERATION_STATE_FAILED,
    TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
    TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
    TRACKING_OPERATION_STATE_SUCCEEDED,
)
from tracking_engine.models.tracking import (
    TRACKING_AUDIT_RESULT_PERSIST_FAILED,
    TRACKING_AUDIT_SUBMIT_FAILED,
    TRACKING_AUDIT_SUBMIT_OUTCOME_UNKNOWN,
    TRACKING_AUDIT_SUBMIT_STARTED,
    TRACKING_AUDIT_SUBMIT_SUCCEEDED,
    TRACKING_ORIGIN_SAVE_CONFIRM,
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_NEEDS_RECONFIRM,
    TRACKING_STATUS_RECOVERY_REQUIRED,
    TRACKING_STATUS_SUBMIT_FAILED,
    TRACKING_STATUS_SUBMITTING,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
    TrackingRecord,
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
            **generate_request(EntryRequest(raw_title="芙莉莲"))["request"],
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


def _save_modified_request(tmp_path: Path, request_id: str, **changes: Any) -> None:
    config = _config(tmp_path)
    request = load_request_snapshot(config, request_id)
    confirmable = request.get("confirmable_config")
    assert isinstance(confirmable, dict)
    for key, value in changes.items():
        confirmable[key] = value
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


def _ab_unknown() -> dict[str, Any]:
    return {
        "success": False,
        "ab_subscription_id": None,
        "ab_response": None,
        "fallback_config": None,
        "error": {
            "error_type": "ab_timeout",
            "error_message": "Auto Bangumi HTTP 请求超时",
            "failed_step": "create_ab_subscription",
            "details": {"category": "timeout"},
        },
    }


def _counting_submit_one(calls: list[int], result: dict[str, Any] | None = None):
    """Return a submit_one that records calls and returns ``result``."""
    lock = threading.Lock()

    def submit_one(request: dict[str, Any], ab_config: Any) -> dict[str, Any]:
        with lock:
            calls.append(1)
        return result if result is not None else _ab_success()

    return submit_one


def _submit_kwargs(
    config: StorageConfig,
    record: TrackingRecord,
    *,
    key: str = "key-1",
    expected_revision: int | None = None,
    confirm: bool = True,
):
    return {
        "config": config,
        "tracking_id": record.tracking_id,
        "expected_revision": expected_revision or record.revision,
        "idempotency_key": key,
        "confirm": confirm,
        "ab_config": _FakeAbConfig(),
        "now": NOW,
    }


def _error_type(exc: Stage1Error) -> str:
    return exc.error_type


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


def test_successful_submit_persists_active_and_operation_succeeded(
    tmp_path: Path,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    config = _config(tmp_path)
    calls: list[int] = []

    result = run_tracking_submit(
        **_submit_kwargs(config, record),
        submit_one=_counting_submit_one(calls),
    )

    assert result["outcome"] == TRACKING_STATUS_ACTIVE
    assert result["next_revision"] == record.revision + 2
    assert result["issues"] == []
    assert result["operation_id"] is not None
    assert result["tracking"]["status"] == TRACKING_STATUS_ACTIVE
    assert len(calls) == 1

    after = load_tracking_record(config, record.tracking_id)
    assert after.status == TRACKING_STATUS_ACTIVE
    assert after.current_operation_id == result["operation_id"]
    assert after.request_fingerprint is not None
    assert after.audit_events[-1]["action"] == TRACKING_AUDIT_SUBMIT_SUCCEEDED
    operation = load_tracking_operation(config, result["operation_id"])
    assert operation.state == TRACKING_OPERATION_STATE_SUCCEEDED
    assert operation.external_result_id == "ab-subscription-1"

    saved = load_request_snapshot(config, "request-1")
    assert saved["ab_submit_result"]["success"] is True
    assert "secret-token" not in repr(result)
    assert "auto-bangumi.local" not in repr(result)


def test_changed_plan_confirm_adopts_latest_and_submits(tmp_path: Path) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    config = _config(tmp_path)
    # A different-but-valid subtitle group changes the fingerprint only.
    _save_modified_request(tmp_path, "request-1", selected_subtitle_group="Loli")
    calls: list[int] = []

    result = run_tracking_submit(
        **_submit_kwargs(config, record),
        submit_one=_counting_submit_one(calls),
    )

    assert result["outcome"] == TRACKING_STATUS_ACTIVE
    assert len(calls) == 1
    after = load_tracking_record(config, record.tracking_id)
    assert after.status == TRACKING_STATUS_ACTIVE
    # The new plan's fingerprint was adopted in the SUBMITTING write.
    fresh = load_request_snapshot(config, "request-1")
    from apps.migu_orca_web.save_confirm_service import compute_request_fingerprint

    assert after.request_fingerprint == compute_request_fingerprint(fresh)
    actions = [event["action"] for event in after.audit_events]
    assert TRACKING_AUDIT_SUBMIT_STARTED in actions
    assert TRACKING_AUDIT_SUBMIT_SUCCEEDED in actions


# ---------------------------------------------------------------------------
# Blocking / pre-external business outcomes
# ---------------------------------------------------------------------------


def test_blocking_issue_moves_to_needs_reconfirm_without_external_call(
    tmp_path: Path,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    config = _config(tmp_path)
    # Empty the selected subtitle group => SUBTITLE_GROUP_MISSING/NO_VALID_RESOURCES.
    _save_modified_request(tmp_path, "request-1", selected_subtitle_group="")
    calls: list[int] = []

    result = run_tracking_submit(
        **_submit_kwargs(config, record),
        submit_one=_counting_submit_one(calls),
    )

    assert result["outcome"] == TRACKING_STATUS_NEEDS_RECONFIRM
    assert len(calls) == 0
    assert result["issues"]  # non-empty fixed issue list
    after = load_tracking_record(config, record.tracking_id)
    assert after.status == TRACKING_STATUS_NEEDS_RECONFIRM


def test_confirm_false_raises_confirmation_required(tmp_path: Path) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    with pytest.raises(Stage1Error) as excinfo:
        run_tracking_submit(
            **_submit_kwargs(config=_config(tmp_path), record=record, confirm=False)
        )
    assert _error_type(excinfo.value) == "tracking_confirmation_required"


def test_revision_conflict_raises(tmp_path: Path) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    with pytest.raises(Stage1Error) as excinfo:
        run_tracking_submit(
            **_submit_kwargs(
                _config(tmp_path),
                record,
                expected_revision=record.revision + 99,
            )
        )
    assert _error_type(excinfo.value) == "tracking_revision_conflict"


def test_active_record_submit_raises_state_conflict(tmp_path: Path) -> None:
    config = _config(tmp_path)
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    from storage_engine.controllers.tracking_repository import (
        compare_and_swap_tracking_record,
    )
    from tracking_engine.models.tracking import transition_record

    active = transition_record(
        record,
        status=TRACKING_STATUS_ACTIVE,
        audit_action=TRACKING_AUDIT_SUBMIT_SUCCEEDED,
        now=NOW,
    )
    compare_and_swap_tracking_record(
        config,
        record.tracking_id,
        base_revision=record.revision,
        record=active,
    )
    with pytest.raises(Stage1Error) as excinfo:
        run_tracking_submit(**_submit_kwargs(config, active))
    assert _error_type(excinfo.value) == "tracking_state_conflict"


# ---------------------------------------------------------------------------
# External outcome classification
# ---------------------------------------------------------------------------


def test_definite_external_failure_moves_to_submit_failed(tmp_path: Path) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    config = _config(tmp_path)
    calls: list[int] = []

    result = run_tracking_submit(
        **_submit_kwargs(config, record),
        submit_one=_counting_submit_one(calls, _ab_definite_failure()),
    )

    assert result["outcome"] == TRACKING_STATUS_SUBMIT_FAILED
    assert len(calls) == 1
    after = load_tracking_record(config, record.tracking_id)
    assert after.status == TRACKING_STATUS_SUBMIT_FAILED
    assert after.audit_events[-1]["action"] == TRACKING_AUDIT_SUBMIT_FAILED
    operation = load_tracking_operation(config, result["operation_id"])
    assert operation.state == TRACKING_OPERATION_STATE_FAILED
    assert operation.error_type == "ab_auth_failed"


def test_unknown_external_outcome_moves_to_verifying_external(tmp_path: Path) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    config = _config(tmp_path)
    calls: list[int] = []

    result = run_tracking_submit(
        **_submit_kwargs(config, record),
        submit_one=_counting_submit_one(calls, _ab_unknown()),
    )

    assert result["outcome"] == TRACKING_STATUS_VERIFYING_EXTERNAL
    assert len(calls) == 1
    after = load_tracking_record(config, record.tracking_id)
    assert after.status == TRACKING_STATUS_VERIFYING_EXTERNAL
    assert after.audit_events[-1]["action"] == TRACKING_AUDIT_SUBMIT_OUTCOME_UNKNOWN
    operation = load_tracking_operation(config, result["operation_id"])
    assert operation.state == TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN
    assert operation.error_type == "ab_timeout"


def test_ab_result_persist_failure_moves_to_recovery_required(tmp_path: Path) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    config = _config(tmp_path)
    calls: list[int] = []

    def failing_persist(request: dict[str, Any], ab_result: dict[str, Any]) -> dict[str, Any]:
        raise Stage1Error(
            "storage_error",
            "保存 Auto Bangumi 提交结果失败",
            "persist_tracking_submit_result",
            {"request_id": "request-1"},
        )

    result = run_tracking_submit(
        **_submit_kwargs(config, record),
        submit_one=_counting_submit_one(calls, _ab_success()),
        persist_ab_result=failing_persist,
    )

    assert result["outcome"] == TRACKING_STATUS_RECOVERY_REQUIRED
    assert len(calls) == 1
    after = load_tracking_record(config, record.tracking_id)
    assert after.status == TRACKING_STATUS_RECOVERY_REQUIRED
    assert after.audit_events[-1]["action"] == TRACKING_AUDIT_RESULT_PERSIST_FAILED
    operation = load_tracking_operation(config, result["operation_id"])
    assert operation.state == TRACKING_OPERATION_STATE_RECOVERY_REQUIRED


# ---------------------------------------------------------------------------
# Idempotent replay & concurrency
# ---------------------------------------------------------------------------


def test_same_key_terminal_replay_reuses_original_outcome_without_external(
    tmp_path: Path,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    config = _config(tmp_path)
    calls: list[int] = []

    first = run_tracking_submit(
        **_submit_kwargs(config, record),
        submit_one=_counting_submit_one(calls),
    )
    assert first["outcome"] == TRACKING_STATUS_ACTIVE
    assert len(calls) == 1

    replayed = run_tracking_submit(
        **_submit_kwargs(
            config,
            load_tracking_record(config, record.tracking_id),
            expected_revision=record.revision,
        ),
        submit_one=_counting_submit_one(calls),
    )
    assert replayed["outcome"] == TRACKING_STATUS_ACTIVE
    assert len(calls) == 1  # no second external call
    assert replayed["operation_id"] == first["operation_id"]


def test_same_key_different_binding_raises_idempotency_conflict(
    tmp_path: Path,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    config = _config(tmp_path)
    calls: list[int] = []

    first = run_tracking_submit(
        **_submit_kwargs(config, record),
        submit_one=_counting_submit_one(calls),
    )
    assert first["outcome"] == TRACKING_STATUS_ACTIVE

    # Change the plan before replaying the same key -> different fingerprint.
    _save_modified_request(tmp_path, "request-1", selected_subtitle_group="Loli")
    with pytest.raises(Stage1Error) as excinfo:
        run_tracking_submit(
            **_submit_kwargs(
                config,
                load_tracking_record(config, record.tracking_id),
                expected_revision=record.revision,
            ),
            submit_one=_counting_submit_one(calls),
        )
    assert _error_type(excinfo.value) == "tracking_idempotency_conflict"
    assert len(calls) == 1  # never a second external call


def test_concurrent_same_key_submits_produce_single_external_call(
    tmp_path: Path,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    config = _config(tmp_path)
    calls: list[int] = []
    barrier = threading.Barrier(2)
    errors: list[Stage1Error] = []
    outcomes: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            barrier.wait(timeout=10)
            result = run_tracking_submit(
                **_submit_kwargs(config, record),
                submit_one=_counting_submit_one(calls),
            )
            with lock:
                outcomes.append(result["outcome"])
        except Stage1Error as exc:  # noqa: BLE001 - expected conflict loser
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert len(calls) == 1
    assert outcomes.count(TRACKING_STATUS_ACTIVE) == 1
    assert len(errors) == 1
    assert errors[0].error_type == "tracking_operation_in_progress"
    after = load_tracking_record(config, record.tracking_id)
    assert after.status == TRACKING_STATUS_ACTIVE
    operation = load_tracking_operation(config, after.current_operation_id)
    assert operation.state == TRACKING_OPERATION_STATE_SUCCEEDED


def test_replay_resumes_prepared_operation_after_submitting_write(
    tmp_path: Path,
) -> None:
    """A same-key replay after a SUBMITTING-only crash resumes once."""
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    config = _config(tmp_path)

    # Simulate the crashed attempt: bind PREPARED and persist the record as
    # SUBMITTING, but never switch the operation to IN_PROGRESS.
    from storage_engine.controllers.operation_repository import (
        bind_tracking_operation,
    )
    from tracking_engine.models.operation import (
        TRACKING_OPERATION_KIND_SUBMIT,
    )
    from tracking_engine.models.tracking import (
        transition_record,
    )

    fingerprint = record.request_fingerprint
    bound, created = bind_tracking_operation(
        config,
        tracking_id=record.tracking_id,
        operation=TRACKING_OPERATION_KIND_SUBMIT,
        idempotency_key="key-1",
        expected_revision=record.revision,
        request_fingerprint=fingerprint or "fingerprint",
        now=NOW,
    )
    assert created is True
    submitting = transition_record(
        record,
        status=TRACKING_STATUS_SUBMITTING,
        audit_action=TRACKING_AUDIT_SUBMIT_STARTED,
        now=NOW,
    )
    from dataclasses import replace as _replace

    submitting = _replace(submitting, current_operation_id=bound.operation_id)
    from storage_engine.controllers.tracking_repository import (
        compare_and_swap_tracking_record,
    )

    compare_and_swap_tracking_record(
        config,
        record.tracking_id,
        base_revision=record.revision,
        record=submitting,
    )

    calls: list[int] = []
    result = run_tracking_submit(
        **_submit_kwargs(
            config,
            load_tracking_record(config, record.tracking_id),
            expected_revision=record.revision,
        ),
        submit_one=_counting_submit_one(calls, _ab_success()),
    )
    assert result["outcome"] == TRACKING_STATUS_ACTIVE
    assert len(calls) == 1
    assert result["operation_id"] == bound.operation_id
    after = load_tracking_record(config, record.tracking_id)
    assert after.status == TRACKING_STATUS_ACTIVE
    operation = load_tracking_operation(config, bound.operation_id)
    assert operation.state == TRACKING_OPERATION_STATE_SUCCEEDED
