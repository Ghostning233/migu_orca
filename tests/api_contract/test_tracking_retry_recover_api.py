from __future__ import annotations

"""US-226 route/contract tests for the retry + recover tracking endpoints.

These run against the real Flask app through the ``client`` fixture and never
touch an external system.  Accepted Requests come from the static fixture and
tracking records are seeded through the handoff; Auto Bangumi is faked by
monkeypatching the AB HTTP client factory the compose seam resolves at call
time.  The autouse ``_web_storage_root`` fixture maps the relative ``storage``
profile onto ``tmp_path`` so absolute tmp paths never leak into payloads or
URLs.
"""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient

from ab_engine.controllers.ab_client import FakeAutoBangumiClient
from apps.migu_orca_entry.controllers.entry_controller import generate_request
from apps.migu_orca_web.api_contract import (
    TrackingRecoverResultDTO,
    TrackingSubmitResultDTO,
)
from apps.migu_orca_web.tracking_handoff import ensure_confirmed_request_tracking
from request_engine.controllers.request_controller import accept_request
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
from tracking_engine.models.tracking import (
    TRACKING_AUDIT_SUBMIT_OUTCOME_UNKNOWN,
    TRACKING_AUDIT_SUBMIT_STARTED,
    TRACKING_AUDIT_SUBMIT_SUCCEEDED,
    TRACKING_ORIGIN_SAVE_CONFIRM,
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_RECOVERY_REQUIRED,
    TRACKING_STATUS_SUBMIT_FAILED,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
    TrackingRecord,
    transition_record,
)

AB_CONFIG = {
    "auth_mode": "api_token",
    "base_url": "http://auto-bangumi.local",
    "token": "secret-token",
    "fallback_enabled": False,
}


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


def _seed_tracking(tmp_path: Path, request: dict[str, Any]) -> TrackingRecord:
    config = _config(tmp_path)
    handoff = ensure_confirmed_request_tracking(
        config=config,
        request=request,
        origin=TRACKING_ORIGIN_SAVE_CONFIRM,
        now="2026-09-08T00:00:00+00:00",
    )
    assert handoff.tracking_id is not None
    return load_tracking_record(config, handoff.tracking_id)


def _move_record(
    tmp_path: Path,
    record: TrackingRecord,
    status: str,
    *,
    audit_action: str = TRACKING_AUDIT_SUBMIT_OUTCOME_UNKNOWN,
    current_operation_id: str | None = None,
) -> TrackingRecord:
    config = _config(tmp_path)
    next_record = transition_record(
        record,
        status=status,
        audit_action=audit_action,
        operation_id=current_operation_id,
        now="2026-09-08T00:00:00+00:00",
    )
    if current_operation_id is not None:
        next_record = replace(next_record, current_operation_id=current_operation_id)
    return compare_and_swap_tracking_record(
        config,
        record.tracking_id,
        base_revision=record.revision,
        record=next_record,
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
        "error": None,
    }


def _retry_body(record: TrackingRecord, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "expected_revision": record.revision,
        "storage_dir": "storage",
        "confirm": True,
        "idempotency_key": "retry-key-1",
        "ab_config": AB_CONFIG,
    }
    body.update(overrides)
    return body


def _recover_body(record: TrackingRecord, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "expected_revision": record.revision,
        "storage_dir": "storage",
        "action": "AUTO",
        "confirm": False,
    }
    body.update(overrides)
    return body


def _patch_ab_factory(monkeypatch: pytest.MonkeyPatch, client: FakeAutoBangumiClient):
    monkeypatch.setattr(
        "ab_engine.controllers.ab_http_client.create_auto_bangumi_http_client",
        lambda _config: client,
    )
    return client


# ---------------------------------------------------------------------------
# Retry endpoint
# ---------------------------------------------------------------------------


def test_retry_success_from_submit_failed(
    tmp_path: Path,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    failed = _move_record(
        tmp_path,
        record,
        TRACKING_STATUS_SUBMIT_FAILED,
        audit_action="SUBMIT_FAILED",
    )
    fake = FakeAutoBangumiClient()
    _patch_ab_factory(monkeypatch, fake)

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/retry",
        json=_retry_body(failed),
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["outcome"] == TRACKING_STATUS_ACTIVE
    assert result["operation_id"] is not None
    assert result["issues"] == []
    TrackingSubmitResultDTO.model_validate(result)
    assert fake.calls
    after = load_tracking_record(_config(tmp_path), record.tracking_id)
    assert after.status == TRACKING_STATUS_ACTIVE
    assert [event["action"] for event in after.audit_events][-2:] == [
        TRACKING_AUDIT_SUBMIT_STARTED,
        TRACKING_AUDIT_SUBMIT_SUCCEEDED,
    ]
    body_text = response.get_data(as_text=True)
    assert "secret-token" not in body_text
    assert "auto-bangumi.local" not in body_text
    assert str(tmp_path) not in body_text


def test_retry_rejects_pending_submit_record(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/retry",
        json=_retry_body(record),
    )
    assert response.status_code == 409
    assert response.get_json()["error_type"] == "tracking_state_conflict"


def test_retry_rejects_verifying_external_record(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    verifying = _move_record(
        tmp_path, record, TRACKING_STATUS_VERIFYING_EXTERNAL
    )
    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/retry",
        json=_retry_body(verifying),
    )
    assert response.status_code == 409
    assert response.get_json()["error_type"] == "tracking_state_conflict"


def test_retry_rejects_recovery_required_record(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    recovery = _move_record(
        tmp_path, record, TRACKING_STATUS_RECOVERY_REQUIRED
    )
    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/retry",
        json=_retry_body(recovery),
    )
    assert response.status_code == 409
    assert response.get_json()["error_type"] == "tracking_state_conflict"


def test_retry_requires_confirm(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    failed = _move_record(
        tmp_path,
        record,
        TRACKING_STATUS_SUBMIT_FAILED,
        audit_action="SUBMIT_FAILED",
    )
    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/retry",
        json=_retry_body(failed, confirm=False),
    )
    assert response.status_code == 400
    assert response.get_json()["error_type"] == "tracking_confirmation_required"


def test_retry_rejects_unknown_field(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    failed = _move_record(
        tmp_path,
        record,
        TRACKING_STATUS_SUBMIT_FAILED,
        audit_action="SUBMIT_FAILED",
    )
    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/retry",
        json={**_retry_body(failed), "mystery": 1},
    )
    assert response.status_code == 400
    assert response.get_json()["error_type"] == "data_validation_errors"


# ---------------------------------------------------------------------------
# Recover endpoint
# ---------------------------------------------------------------------------


def test_recover_auto_resolves_active_from_persisted_result(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    _save_ab_result(tmp_path, "request-1", _ab_success())
    verifying = _move_record(
        tmp_path, record, TRACKING_STATUS_VERIFYING_EXTERNAL
    )

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/recover",
        json=_recover_body(verifying, action="AUTO"),
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["action"] == "AUTO"
    assert result["outcome"] == TRACKING_STATUS_ACTIVE
    assert result["needs_manual"] is False
    TrackingRecoverResultDTO.model_validate(result)
    after = load_tracking_record(_config(tmp_path), record.tracking_id)
    assert after.status == TRACKING_STATUS_ACTIVE
    body_text = response.get_data(as_text=True)
    assert str(tmp_path) not in body_text


def test_recover_auto_without_evidence_needs_manual(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    verifying = _move_record(
        tmp_path, record, TRACKING_STATUS_VERIFYING_EXTERNAL
    )

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/recover",
        json=_recover_body(verifying, action="AUTO"),
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["outcome"] == TRACKING_STATUS_RECOVERY_REQUIRED
    assert result["needs_manual"] is True
    after = load_tracking_record(_config(tmp_path), record.tracking_id)
    assert after.status == TRACKING_STATUS_RECOVERY_REQUIRED


def test_recover_manual_succeeded_requires_confirm(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    verifying = _move_record(
        tmp_path, record, TRACKING_STATUS_VERIFYING_EXTERNAL
    )
    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/recover",
        json=_recover_body(verifying, action="MARK_SUCCEEDED", confirm=False),
    )
    assert response.status_code == 400
    assert response.get_json()["error_type"] == "tracking_confirmation_required"


def test_recover_manual_succeeded_confirmed_writes_user_audit(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    verifying = _move_record(
        tmp_path, record, TRACKING_STATUS_VERIFYING_EXTERNAL
    )
    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/recover",
        json=_recover_body(verifying, action="MARK_SUCCEEDED", confirm=True),
    )
    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["outcome"] == TRACKING_STATUS_ACTIVE
    after = load_tracking_record(_config(tmp_path), record.tracking_id)
    assert after.status == TRACKING_STATUS_ACTIVE
    assert after.audit_events[-1]["actor"] == "USER"


def test_recover_manual_failed_confirmed_resolves_recovery_required(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    recovery = _move_record(
        tmp_path, record, TRACKING_STATUS_RECOVERY_REQUIRED
    )
    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/recover",
        json=_recover_body(recovery, action="MARK_FAILED", confirm=True),
    )
    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["outcome"] == TRACKING_STATUS_SUBMIT_FAILED
    after = load_tracking_record(_config(tmp_path), record.tracking_id)
    assert after.status == TRACKING_STATUS_SUBMIT_FAILED
    assert after.audit_events[-1]["actor"] == "USER"


def test_recover_rejects_active_state(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    active = _move_record(
        tmp_path,
        record,
        TRACKING_STATUS_ACTIVE,
        audit_action="SUBMIT_SUCCEEDED",
    )
    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/recover",
        json=_recover_body(active, action="AUTO"),
    )
    assert response.status_code == 409
    assert response.get_json()["error_type"] == "tracking_state_conflict"


def test_recover_rejects_invalid_action(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    verifying = _move_record(
        tmp_path, record, TRACKING_STATUS_VERIFYING_EXTERNAL
    )
    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/recover",
        json=_recover_body(verifying, action="VERIFY_EXTERNAL"),
    )
    assert response.status_code == 400
    assert response.get_json()["error_type"] == "data_validation_errors"


def test_recover_rejects_stale_revision(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    verifying = _move_record(
        tmp_path, record, TRACKING_STATUS_VERIFYING_EXTERNAL
    )
    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/recover",
        json=_recover_body(verifying, expected_revision=verifying.revision + 99),
    )
    assert response.status_code == 409
    assert response.get_json()["error_type"] == "tracking_revision_conflict"


def test_recover_rejects_unknown_field(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    verifying = _move_record(
        tmp_path, record, TRACKING_STATUS_VERIFYING_EXTERNAL
    )
    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/recover",
        json={**_recover_body(verifying), "mystery": 1},
    )
    assert response.status_code == 400
    assert response.get_json()["error_type"] == "data_validation_errors"


def test_recover_does_not_accept_external_id_or_url(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    """MARK_SUCCEEDED never accepts an external ID/URL/raw result (§11.8)."""
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    verifying = _move_record(
        tmp_path, record, TRACKING_STATUS_VERIFYING_EXTERNAL
    )
    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/recover",
        json={
            **_recover_body(verifying, action="MARK_SUCCEEDED", confirm=True),
            "external_id": "ab-123",
            "external_url": "http://auto-bangumi.local/sub/1",
        },
    )
    assert response.status_code == 400
    assert response.get_json()["error_type"] == "data_validation_errors"
