from __future__ import annotations

"""US-225 route/contract tests for the unified reliable submit endpoint.

These run against the real Flask app through the ``client`` fixture and never
touch an external system.  Accepted Requests come from the static fixture and
tracking records are seeded through the handoff; Auto Bangumi is faked by
monkeypatching the AB HTTP client factory that the compose seam resolves at
call time.  The autouse ``_web_storage_root`` fixture maps the relative
``storage`` profile onto ``tmp_path`` so absolute tmp paths never leak into
payloads or URLs.
"""

from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient

from ab_engine.controllers.ab_client import FakeAutoBangumiClient
from apps.migu_orca_entry.controllers.entry_controller import generate_request
from apps.migu_orca_web.api_contract import TrackingSubmitResultDTO
from apps.migu_orca_web.tracking_handoff import ensure_confirmed_request_tracking
from request_engine.controllers.request_controller import accept_request
from shared.errors import Stage1Error
from shared.models import EntryRequest
from storage_engine.controllers.autobangumi_config_repository import (
    AutoBangumiConfigRepository,
    build_stored_autobangumi_config,
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
from tracking_engine.models.tracking import (
    TRACKING_AUDIT_SUBMIT_STARTED,
    TRACKING_AUDIT_SUBMIT_SUCCEEDED,
    TRACKING_AUDIT_TRACKING_CREATED,
    TRACKING_ORIGIN_SAVE_CONFIRM,
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_NEEDS_RECONFIRM,
    TRACKING_STATUS_SUBMIT_FAILED,
    TRACKING_STATUS_SUBMITTING,
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

SAVED_GENERATION: tuple[str, int] = ("", 0)


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
    global SAVED_GENERATION
    saved = AutoBangumiConfigRepository(tmp_path / "config").save(
        build_stored_autobangumi_config({"auth_mode": "password", "base_url": "http://ab.invalid", "username": "u", "password": "p"}),
        expected_configuration_revision=0,
    )
    SAVED_GENERATION = (str(saved.connection_ref), saved.configuration_revision)
    config = _config(tmp_path)
    handoff = ensure_confirmed_request_tracking(
        config=config,
        request=request,
        origin=TRACKING_ORIGIN_SAVE_CONFIRM,
        now="2026-09-08T00:00:00+00:00",
    )
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


def _submit_body(record: TrackingRecord, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "expected_revision": record.revision,
        "storage_dir": "storage",
        "confirm": True,
        "idempotency_key": "key-1",
        "connection_ref": SAVED_GENERATION[0],
        "configuration_revision": SAVED_GENERATION[1],
    }
    body.update(overrides)
    return body


def _patch_ab_factory(monkeypatch: pytest.MonkeyPatch, client: FakeAutoBangumiClient):
    def submit_one(_request: dict[str, Any], _config: Any) -> dict[str, Any]:
        client.create_subscription({"fixture": True})
        return {"success": True, "ab_subscription_id": "fake-ab-subscription", "error": None}
    monkeypatch.setattr("apps.migu_orca_web.tracking_submission_service.compose_tracking_submit_one", lambda: submit_one)
    return client


# ---------------------------------------------------------------------------
# Success / business outcomes
# ---------------------------------------------------------------------------


def test_submit_success_persists_active_and_dto(
    tmp_path: Path,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    fake = FakeAutoBangumiClient()
    _patch_ab_factory(monkeypatch, fake)

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json=_submit_body(record),
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["outcome"] == TRACKING_STATUS_ACTIVE
    assert result["issues"] == []
    assert result["failure_category"] is None
    assert result["operation_id"] is not None
    assert result["tracking"]["status"] == TRACKING_STATUS_ACTIVE
    TrackingSubmitResultDTO.model_validate(result)

    after = load_tracking_record(_config(tmp_path), record.tracking_id)
    assert after.status == TRACKING_STATUS_ACTIVE
    assert [event["action"] for event in after.audit_events] == [
        TRACKING_AUDIT_TRACKING_CREATED,
        TRACKING_AUDIT_SUBMIT_STARTED,
        TRACKING_AUDIT_SUBMIT_SUCCEEDED,
    ]
    assert fake.calls

    body_text = response.get_data(as_text=True)
    assert "secret-token" not in body_text
    assert "auto-bangumi.local" not in body_text
    assert str(tmp_path) not in body_text


def test_submit_changed_plan_confirm_adopts_latest_and_submits(
    tmp_path: Path,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    _save_modified_request(tmp_path, "request-1", selected_subtitle_group="Loli")
    _patch_ab_factory(monkeypatch, FakeAutoBangumiClient())

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json=_submit_body(record),
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["outcome"] == TRACKING_STATUS_ACTIVE
    after = load_tracking_record(_config(tmp_path), record.tracking_id)
    assert after.status == TRACKING_STATUS_ACTIVE


def test_submit_confirm_false_returns_400_confirmation_required(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json=_submit_body(record, confirm=False),
    )
    assert response.status_code == 400
    assert response.get_json()["error_type"] == "data_validation_errors"


def test_submit_blocking_issue_returns_needs_reconfirm_without_ab_call(
    tmp_path: Path,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    _save_modified_request(tmp_path, "request-1", selected_subtitle_group="")
    fake = FakeAutoBangumiClient()
    _patch_ab_factory(monkeypatch, fake)

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json=_submit_body(record),
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["outcome"] == TRACKING_STATUS_NEEDS_RECONFIRM
    assert result["issues"]
    assert fake.calls == []
    after = load_tracking_record(_config(tmp_path), record.tracking_id)
    assert after.status == TRACKING_STATUS_NEEDS_RECONFIRM


def test_submit_definite_external_failure_returns_submit_failed(
    tmp_path: Path,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    fake = FakeAutoBangumiClient(
        error=Stage1Error(
            "ab_auth_failed",
            "Auto Bangumi 认证失败",
            "create_ab_subscription",
            {"status_code": 401},
        )
    )
    _patch_ab_factory(monkeypatch, fake)

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json=_submit_body(record),
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["outcome"] == TRACKING_STATUS_SUBMIT_FAILED
    assert result["failure_category"] == "AUTHENTICATION"
    assert fake.calls
    body_text = response.get_data(as_text=True)
    assert "secret-token" not in body_text
    assert "auto-bangumi.local" not in body_text


def test_submit_unknown_external_outcome_returns_verifying_external(
    tmp_path: Path,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    fake = FakeAutoBangumiClient(
        error=Stage1Error(
            "ab_timeout",
            "Auto Bangumi HTTP 请求超时",
            "create_ab_subscription",
            {"category": "timeout"},
        )
    )
    _patch_ab_factory(monkeypatch, fake)

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json=_submit_body(record),
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["outcome"] == TRACKING_STATUS_VERIFYING_EXTERNAL
    assert result["failure_category"] == "OUTCOME_UNKNOWN"


@pytest.mark.parametrize(
    ("error_type", "expected_category"),
    [
        ("ab_connection_failed_pre_write", "CONNECTION"),
        ("ab_timeout_pre_write", "CONNECTION"),
        ("ab_connection_failed", "OUTCOME_UNKNOWN"),
        ("ab_timeout", "OUTCOME_UNKNOWN"),
        ("ab_auth_failed", "AUTHENTICATION"),
        ("ab_unsupported_version", "VERSION"),
        ("ab_duplicate_subscription", "DUPLICATE_SUBSCRIPTION"),
        ("invalid_ab_payload", "VALIDATION"),
        ("ab_submit_failed", "REJECTED"),
    ],
)
def test_submit_publishes_a_stable_failure_category(
    tmp_path: Path,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
    error_type: str,
    expected_category: str,
) -> None:
    """Issue #86: every external failure publishes one safe, actionable class."""
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    fake = FakeAutoBangumiClient(
        error=Stage1Error(error_type, "Auto Bangumi 提交失败", "create_ab_subscription")
    )
    _patch_ab_factory(monkeypatch, fake)

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json=_submit_body(record),
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["failure_category"] == expected_category
    TrackingSubmitResultDTO.model_validate(result)
    body_text = response.get_data(as_text=True)
    for forbidden in ("secret-token", "auto-bangumi.local", str(tmp_path)):
        assert forbidden not in body_text


# ---------------------------------------------------------------------------
# Precondition guards / strict payload
# ---------------------------------------------------------------------------


def test_submit_missing_record_is_404(tmp_path: Path, client: FlaskClient) -> None:
    saved = AutoBangumiConfigRepository(tmp_path / "config").save(
        build_stored_autobangumi_config({"auth_mode": "password", "base_url": "http://ab.invalid", "username": "u", "password": "p"}),
        expected_configuration_revision=0,
    )
    response = client.post(
        "/api/v1/tracking/items/trk_nonexistent0000000000000000000000/submit",
            json=_submit_body(TrackingRecord(tracking_id="trk_nonexistent0000000000000000000000", revision=1),
                              connection_ref=str(saved.connection_ref), configuration_revision=saved.configuration_revision),
    )
    assert response.status_code == 404
    assert response.get_json()["error_type"] == "tracking_not_found"


def test_submit_revision_conflict_is_409(tmp_path: Path, client: FlaskClient) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json=_submit_body(record, expected_revision=record.revision + 99),
    )
    assert response.status_code == 409
    assert response.get_json()["error_type"] == "tracking_revision_conflict"


def test_submit_active_record_raises_state_conflict(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    active = transition_record(
        record,
        status=TRACKING_STATUS_ACTIVE,
        audit_action=TRACKING_AUDIT_SUBMIT_SUCCEEDED,
        now="2026-09-08T00:00:00+00:00",
    )
    compare_and_swap_tracking_record(
        _config(tmp_path),
        record.tracking_id,
        base_revision=record.revision,
        record=active,
    )
    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json=_submit_body(active),
    )
    assert response.status_code == 409
    assert response.get_json()["error_type"] == "tracking_state_conflict"


def test_submit_in_flight_operation_raises_operation_in_progress(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    """A new key submit against a record with an in-flight operation is 409."""
    from dataclasses import replace as _replace

    from storage_engine.controllers.operation_repository import (
        bind_tracking_operation,
        compare_and_swap_tracking_operation,
    )
    from tracking_engine.models.operation import (
        TRACKING_OPERATION_KIND_SUBMIT,
        TRACKING_OPERATION_STATE_IN_PROGRESS,
        TRACKING_OPERATION_STATE_PREPARED,
        transition_tracking_operation,
    )

    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    config = _config(tmp_path)
    bound, created = bind_tracking_operation(
        config,
        tracking_id=record.tracking_id,
        operation=TRACKING_OPERATION_KIND_SUBMIT,
        idempotency_key="old-key",
        expected_revision=record.revision,
        request_fingerprint=record.request_fingerprint or "fingerprint",
        now="2026-09-08T00:00:00+00:00",
    )
    assert created is True
    in_flight = compare_and_swap_tracking_operation(
        config,
        bound.operation_id,
        expected_state=TRACKING_OPERATION_STATE_PREPARED,
        record=transition_tracking_operation(
            bound,
            state=TRACKING_OPERATION_STATE_IN_PROGRESS,
            now="2026-09-08T00:00:00+00:00",
        ),
    )
    assert in_flight.state == TRACKING_OPERATION_STATE_IN_PROGRESS

    submitting = _replace(
        transition_record(
            record,
            status=TRACKING_STATUS_SUBMITTING,
            audit_action=TRACKING_AUDIT_SUBMIT_STARTED,
            now="2026-09-08T00:00:00+00:00",
        ),
        current_operation_id=bound.operation_id,
    )
    compare_and_swap_tracking_record(
        config,
        record.tracking_id,
        base_revision=record.revision,
        record=submitting,
    )
    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json=_submit_body(submitting, idempotency_key="new-key"),
    )
    assert response.status_code == 409
    assert response.get_json()["error_type"] == "tracking_operation_in_progress"


def test_submit_rejects_unknown_field(tmp_path: Path, client: FlaskClient) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json={**_submit_body(record), "mystery": 1},
    )
    assert response.status_code == 400
    assert response.get_json()["error_type"] == "data_validation_errors"


def test_submit_rejects_missing_idempotency_key(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    body = _submit_body(record)
    body.pop("idempotency_key")
    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json=body,
    )
    assert response.status_code == 400
    assert response.get_json()["error_type"] == "data_validation_errors"


def test_submit_same_key_replay_reuses_operation_without_second_external_call(
    tmp_path: Path,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    fake = FakeAutoBangumiClient()
    _patch_ab_factory(monkeypatch, fake)

    url = f"/api/v1/tracking/items/{record.tracking_id}/submit"
    first = client.post(url, json=_submit_body(record))
    assert first.status_code == 200
    assert first.get_json()["result"]["outcome"] == TRACKING_STATUS_ACTIVE
    assert len(fake.calls) == 1

    replay = client.post(url, json=_submit_body(record))
    assert replay.status_code == 200
    replay_result = replay.get_json()["result"]
    assert replay_result["outcome"] == TRACKING_STATUS_ACTIVE
    assert replay_result["operation_id"] == first.get_json()["result"]["operation_id"]
    assert len(fake.calls) == 1
