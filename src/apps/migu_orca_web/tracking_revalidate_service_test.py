from __future__ import annotations

"""US-224: web revalidate service tests (pure-local orchestration).

These exercise ``run_tracking_revalidate`` against a tmp storage root and never
touch an external system.  The accepted Requests come from the static fixture;
records are seeded through the handoff/repositories.
"""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from apps.migu_orca_web.save_confirm_service import compute_request_fingerprint
from apps.migu_orca_web.tracking_handoff import ensure_confirmed_request_tracking
from apps.migu_orca_web.tracking_revalidate_service import run_tracking_revalidate
from plan_engine.controllers.data_sources import StaticFixtureDataSource
from plan_engine.controllers.plan_generation import build_plan
from request_engine.controllers.request_controller import accept_request
from shared.errors import Stage1Error
from shared.models import EntryRequest
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
from tracking_engine.controllers.revalidate import (
    REVALIDATE_ISSUE_REQUEST_CHANGED,
    REVALIDATE_ISSUE_REQUEST_MISSING,
    REVALIDATE_ISSUE_REQUEST_NOT_ACCEPTED,
)
from tracking_engine.models.tracking import (
    TRACKING_AUDIT_ACTOR_SYSTEM,
    TRACKING_AUDIT_PLAN_CHANGE_DETECTED,
    TRACKING_AUDIT_REVALIDATION_PASSED,
    TRACKING_AUDIT_TRACKING_CREATED,
    TRACKING_ORIGIN_SAVE_CONFIRM,
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_NEEDS_RECONFIRM,
    TRACKING_STATUS_PENDING_SUBMIT,
    TRACKING_STATUS_SUBMIT_FAILED,
    TrackingRecord,
    transition_record,
)

NOW = "2026-09-08T00:00:00+00:00"


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


def _save_modified_request(tmp_path: Path, request_id: str, **changes: Any) -> None:
    config = _config(tmp_path)
    request = load_request_snapshot(config, request_id)
    confirmable = request.get("confirmable_config")
    assert isinstance(confirmable, dict)
    for key, value in changes.items():
        confirmable[key] = value
    save_request_snapshot(config, request)


def _error_type(exc: Stage1Error) -> str:
    return exc.error_type


# ---------------------------------------------------------------------------
# Passing / failing outcomes
# ---------------------------------------------------------------------------


def test_healthy_pending_submit_is_ready_and_unchanged(tmp_path: Path) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)

    result = run_tracking_revalidate(
        _config(tmp_path),
        tracking_id=record.tracking_id,
        expected_revision=record.revision,
        now=NOW,
    )

    assert result["ready"] is True
    assert result["next_status"] == TRACKING_STATUS_PENDING_SUBMIT
    assert result["checked_revision"] == record.revision
    assert result["next_revision"] == record.revision
    assert result["issues"] == []
    assert result["tracking"]["status"] == TRACKING_STATUS_PENDING_SUBMIT
    # No-op recheck: no revision bump and no duplicated audit event.
    after = load_tracking_record(_config(tmp_path), record.tracking_id)
    assert after.revision == record.revision
    assert [event["action"] for event in after.audit_events] == [
        TRACKING_AUDIT_TRACKING_CREATED
    ]


def test_changed_plan_moves_to_needs_reconfirm_with_audit(tmp_path: Path) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    _save_modified_request(tmp_path, "request-1", selected_subtitle_group="Loli")

    result = run_tracking_revalidate(
        _config(tmp_path),
        tracking_id=record.tracking_id,
        expected_revision=record.revision,
        now=NOW,
    )

    assert result["ready"] is False
    assert result["next_status"] == TRACKING_STATUS_NEEDS_RECONFIRM
    assert result["checked_revision"] == record.revision
    assert result["next_revision"] == record.revision + 1
    codes = [issue["code"] for issue in result["issues"]]
    assert codes == [REVALIDATE_ISSUE_REQUEST_CHANGED]
    issue = result["issues"][0]
    assert issue["message"] == "订阅方案已发生修改，请确认最新方案后再提交"
    assert issue["recovery_action"] == "SUBMIT"

    after = load_tracking_record(_config(tmp_path), record.tracking_id)
    assert after.status == TRACKING_STATUS_NEEDS_RECONFIRM
    assert after.revision == record.revision + 1
    assert [event["action"] for event in after.audit_events] == [
        TRACKING_AUDIT_TRACKING_CREATED,
        TRACKING_AUDIT_PLAN_CHANGE_DETECTED,
    ]


def test_recheck_while_needs_reconfirm_does_not_bump_revision(tmp_path: Path) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    _save_modified_request(tmp_path, "request-1", selected_subtitle_group="Loli")
    config = _config(tmp_path)
    run_tracking_revalidate(
        config,
        tracking_id=record.tracking_id,
        expected_revision=record.revision,
        now=NOW,
    )
    changed = load_tracking_record(config, record.tracking_id)
    assert changed.status == TRACKING_STATUS_NEEDS_RECONFIRM
    audit_before = list(changed.audit_events)

    # A second revalidate still sees the same (unconfirmed) changed plan.
    second = run_tracking_revalidate(
        config,
        tracking_id=record.tracking_id,
        expected_revision=changed.revision,
        now=NOW,
    )
    assert second["ready"] is False
    assert second["next_status"] == TRACKING_STATUS_NEEDS_RECONFIRM
    assert second["next_revision"] == changed.revision
    after = load_tracking_record(config, record.tracking_id)
    assert after.revision == changed.revision
    assert after.audit_events == audit_before


def test_confirm_latest_plan_then_revalidate_returns_to_pending(tmp_path: Path) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    config = _config(tmp_path)
    _save_modified_request(tmp_path, "request-1", selected_subtitle_group="Loli")

    # US-224 deliberately does NOT adopt the new fingerprint here; US-225's
    # confirm=true submit does. Simulate that confirmation so the revalidate
    # can re-arm the record.
    fresh = load_request_snapshot(config, "request-1")
    new_fingerprint = compute_request_fingerprint(fresh)
    needs = load_tracking_record(config, record.tracking_id)
    confirmed = replace(
        transition_record(
            needs,
            status=TRACKING_STATUS_PENDING_SUBMIT,
            audit_action=TRACKING_AUDIT_PLAN_CHANGE_DETECTED,
            audit_actor=TRACKING_AUDIT_ACTOR_SYSTEM,
            now=NOW,
        ),
        request_fingerprint=new_fingerprint,
    )
    compare_and_swap_tracking_record(
        config,
        record.tracking_id,
        base_revision=needs.revision,
        record=confirmed,
    )

    result = run_tracking_revalidate(
        config,
        tracking_id=record.tracking_id,
        expected_revision=confirmed.revision,
        now=NOW,
    )
    assert result["ready"] is True
    assert result["next_status"] == TRACKING_STATUS_PENDING_SUBMIT
    after = load_tracking_record(config, record.tracking_id)
    assert after.status == TRACKING_STATUS_PENDING_SUBMIT
    assert after.revision == confirmed.revision
    assert [event["action"] for event in after.audit_events][-1] in {
        TRACKING_AUDIT_PLAN_CHANGE_DETECTED,
        TRACKING_AUDIT_REVALIDATION_PASSED,
    }


def test_missing_request_reports_request_missing_and_moves_to_reconfirm(
    tmp_path: Path,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    # Remove the backing Request from storage.
    request_path = _config(tmp_path).requests_dir / "request-1.json"
    request_path.unlink()

    result = run_tracking_revalidate(
        _config(tmp_path),
        tracking_id=record.tracking_id,
        expected_revision=record.revision,
        now=NOW,
    )
    assert result["ready"] is False
    assert [issue["code"] for issue in result["issues"]] == [
        REVALIDATE_ISSUE_REQUEST_MISSING
    ]
    assert result["next_status"] == TRACKING_STATUS_NEEDS_RECONFIRM


def test_not_accepted_request_reports_request_not_accepted(tmp_path: Path) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    config = _config(tmp_path)
    saved = load_request_snapshot(config, "request-1")
    saved["status"] = "PENDING_CONFIRM"
    save_request_snapshot(config, saved)

    result = run_tracking_revalidate(
        config,
        tracking_id=record.tracking_id,
        expected_revision=record.revision,
        now=NOW,
    )
    assert result["ready"] is False
    assert [issue["code"] for issue in result["issues"]] == [
        REVALIDATE_ISSUE_REQUEST_NOT_ACCEPTED
    ]


def test_failed_submission_plan_still_valid_keeps_submit_failed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    failed = transition_record(
        record,
        status=TRACKING_STATUS_SUBMIT_FAILED,
        audit_action="SUBMIT_FAILED",
        now=NOW,
    )
    compare_and_swap_tracking_record(
        config,
        record.tracking_id,
        base_revision=record.revision,
        record=failed,
    )

    result = run_tracking_revalidate(
        config,
        tracking_id=record.tracking_id,
        expected_revision=failed.revision,
        now=NOW,
    )
    assert result["ready"] is True
    assert result["next_status"] == TRACKING_STATUS_SUBMIT_FAILED
    assert result["next_revision"] == failed.revision
    after = load_tracking_record(config, record.tracking_id)
    assert after.status == TRACKING_STATUS_SUBMIT_FAILED


def test_failed_submission_changed_plan_moves_to_needs_reconfirm(tmp_path: Path) -> None:
    config = _config(tmp_path)
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    failed = transition_record(
        record,
        status=TRACKING_STATUS_SUBMIT_FAILED,
        audit_action="SUBMIT_FAILED",
        now=NOW,
    )
    compare_and_swap_tracking_record(
        config,
        record.tracking_id,
        base_revision=record.revision,
        record=failed,
    )
    _save_modified_request(tmp_path, "request-1", selected_subtitle_group="Loli")

    result = run_tracking_revalidate(
        config,
        tracking_id=record.tracking_id,
        expected_revision=failed.revision,
        now=NOW,
    )
    assert result["ready"] is False
    assert result["next_status"] == TRACKING_STATUS_NEEDS_RECONFIRM
    assert result["next_revision"] == failed.revision + 1
    assert [issue["code"] for issue in result["issues"]] == [
        REVALIDATE_ISSUE_REQUEST_CHANGED
    ]


def test_revision_conflict_raises(tmp_path: Path) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    with pytest.raises(Stage1Error) as excinfo:
        run_tracking_revalidate(
            _config(tmp_path),
            tracking_id=record.tracking_id,
            expected_revision=record.revision + 1,
            now=NOW,
        )
    assert _error_type(excinfo.value) == "tracking_revision_conflict"


def test_state_conflict_raises_for_active_record(tmp_path: Path) -> None:
    config = _config(tmp_path)
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    active = transition_record(
        record,
        status=TRACKING_STATUS_ACTIVE,
        audit_action="SUBMIT_SUCCEEDED",
        now=NOW,
    )
    compare_and_swap_tracking_record(
        config,
        record.tracking_id,
        base_revision=record.revision,
        record=active,
    )
    with pytest.raises(Stage1Error) as excinfo:
        run_tracking_revalidate(
            config,
            tracking_id=record.tracking_id,
            expected_revision=active.revision,
            now=NOW,
        )
    assert _error_type(excinfo.value) == "tracking_state_conflict"


def test_needs_reconfirm_passing_moves_back_to_pending_submit(tmp_path: Path) -> None:
    config = _config(tmp_path)
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    # Seed a NEEDS_RECONFIRM record whose plan actually still matches.
    needs = transition_record(
        record,
        status=TRACKING_STATUS_NEEDS_RECONFIRM,
        audit_action=TRACKING_AUDIT_PLAN_CHANGE_DETECTED,
        now=NOW,
    )
    compare_and_swap_tracking_record(
        config,
        record.tracking_id,
        base_revision=record.revision,
        record=needs,
    )

    result = run_tracking_revalidate(
        config,
        tracking_id=record.tracking_id,
        expected_revision=needs.revision,
        now=NOW,
    )
    assert result["ready"] is True
    assert result["next_status"] == TRACKING_STATUS_PENDING_SUBMIT
    assert result["next_revision"] == needs.revision + 1
    after = load_tracking_record(config, record.tracking_id)
    assert after.status == TRACKING_STATUS_PENDING_SUBMIT
    assert after.revision == needs.revision + 1
    assert after.audit_events[-1]["action"] == TRACKING_AUDIT_REVALIDATION_PASSED


def test_missing_request_safe_error_never_leaks_path(tmp_path: Path) -> None:
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    request_path = _config(tmp_path).requests_dir / "request-1.json"
    request_path.unlink()
    result = run_tracking_revalidate(
        _config(tmp_path),
        tracking_id=record.tracking_id,
        expected_revision=record.revision,
        now=NOW,
    )
    body = repr(result)
    assert str(tmp_path) not in body
    assert "request-1.json" not in body
