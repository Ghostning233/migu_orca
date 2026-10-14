from __future__ import annotations

"""US-224 route/contract tests for the pure-local revalidate endpoint.

These run against the real Flask app through the ``client`` fixture and never
touch an external system.  Accepted Requests come from the static fixture and
tracking records are seeded through the handoff/repositories; the autouse
``_web_storage_root`` fixture maps the relative ``storage`` profile onto
``tmp_path`` so absolute tmp paths never leak into payloads or URLs.
"""

from pathlib import Path
from typing import Any

from flask.testing import FlaskClient

from apps.migu_orca_web.api_contract import TrackingRevalidateResultDTO
from apps.migu_orca_web.tracking_handoff import ensure_confirmed_request_tracking
from plan_engine.controllers.data_sources import StaticFixtureDataSource
from plan_engine.controllers.plan_generation import build_plan
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
    TRACKING_AUDIT_PLAN_CHANGE_DETECTED,
    TRACKING_AUDIT_TRACKING_CREATED,
    TRACKING_ORIGIN_SAVE_CONFIRM,
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_NEEDS_RECONFIRM,
    TRACKING_STATUS_PENDING_SUBMIT,
    TrackingRecord,
    transition_record,
)


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


def _save_modified_request(tmp_path: Path, request_id: str, **changes: Any) -> None:
    config = _config(tmp_path)
    request = load_request_snapshot(config, request_id)
    confirmable = request.get("confirmable_config")
    assert isinstance(confirmable, dict)
    for key, value in changes.items():
        confirmable[key] = value
    save_request_snapshot(config, request)


def _activate_record(config: StorageConfig, record: TrackingRecord) -> TrackingRecord:
    active = transition_record(
        record,
        status=TRACKING_STATUS_ACTIVE,
        audit_action="SUBMIT_SUCCEEDED",
        now="2026-09-08T00:00:00+00:00",
    )
    return compare_and_swap_tracking_record(
        config,
        record.tracking_id,
        base_revision=record.revision,
        record=active,
    )


# ---------------------------------------------------------------------------
# Success / business-failure flows
# ---------------------------------------------------------------------------


def test_revalidate_healthy_pending_submit_is_ready(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/revalidate",
        json={"expected_revision": record.revision, "storage_dir": "storage"},
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["ready"] is True
    assert result["checked_revision"] == record.revision
    assert result["next_revision"] == record.revision
    assert result["next_status"] == TRACKING_STATUS_PENDING_SUBMIT
    assert result["issues"] == []
    assert result["tracking"]["tracking_id"] == record.tracking_id
    TrackingRevalidateResultDTO.model_validate(result)


def test_revalidate_changed_plan_returns_needs_reconfirm(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    _save_modified_request(tmp_path, "request-1", selected_subtitle_group="Loli")

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/revalidate",
        json={"expected_revision": record.revision, "storage_dir": "storage"},
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["ready"] is False
    assert result["next_status"] == TRACKING_STATUS_NEEDS_RECONFIRM
    assert result["next_revision"] == record.revision + 1
    codes = [issue["code"] for issue in result["issues"]]
    assert codes == ["REQUEST_CHANGED"]
    assert result["issues"][0]["recovery_action"] == "SUBMIT"
    assert result["tracking"]["status"] == TRACKING_STATUS_NEEDS_RECONFIRM
    TrackingRevalidateResultDTO.model_validate(result)

    after = load_tracking_record(_config(tmp_path), record.tracking_id)
    assert after.status == TRACKING_STATUS_NEEDS_RECONFIRM
    assert after.revision == record.revision + 1
    assert [event["action"] for event in after.audit_events] == [
        TRACKING_AUDIT_TRACKING_CREATED,
        TRACKING_AUDIT_PLAN_CHANGE_DETECTED,
    ]

    body_text = response.get_data(as_text=True)
    assert str(tmp_path) not in body_text
    assert "request-1.json" not in body_text


def test_revalidate_result_matches_strict_dto_after_revision_conflict(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/revalidate",
        json={"expected_revision": record.revision + 99, "storage_dir": "storage"},
    )

    assert response.status_code == 409
    payload = response.get_json()
    assert payload["error_type"] == "tracking_revision_conflict"
    assert payload["error_data"]["details"]["current_revision"] == record.revision
    assert payload["error_data"]["failed_step"] == "tracking_revalidate"


def test_revalidate_non_revalidatable_state_conflict(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    _activate_record(_config(tmp_path), record)

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/revalidate",
        json={"expected_revision": record.revision + 1, "storage_dir": "storage"},
    )

    assert response.status_code == 409
    assert response.get_json()["error_type"] == "tracking_state_conflict"
    body_text = response.get_data(as_text=True)
    assert str(tmp_path) not in body_text


def test_revalidate_missing_record_is_404(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    response = client.post(
        "/api/v1/tracking/items/trk_nonexistent0000000000000000000000/revalidate",
        json={"expected_revision": 1, "storage_dir": "storage"},
    )
    assert response.status_code == 404
    assert response.get_json()["error_type"] == "tracking_not_found"


def test_revalidate_rejects_path_fragment_tracking_id(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    response = client.post(
        "/api/v1/tracking/items/trk_a/b/revalidate",
        json={"expected_revision": 1, "storage_dir": "storage"},
    )
    assert response.status_code == 400
    assert response.get_json()["error_type"] == "invalid_tracking_id"


# ---------------------------------------------------------------------------
# Pure-local / strict request-body guards
# ---------------------------------------------------------------------------


def test_revalidate_rejects_ab_config_and_unknown_fields(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/revalidate",
        json={
            "expected_revision": record.revision,
            "storage_dir": "storage",
            "ab_config": {"base_url": "https://example.invalid", "fallback_enabled": False},
        },
    )
    assert response.status_code == 400
    assert response.get_json()["error_type"] == "data_validation_errors"

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/revalidate",
        json={"expected_revision": record.revision, "mystery_field": 1},
    )
    assert response.status_code == 400
    assert response.get_json()["error_type"] == "data_validation_errors"


def test_revalidate_requires_expected_revision(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/revalidate",
        json={"storage_dir": "storage"},
    )
    assert response.status_code == 400
    assert response.get_json()["error_type"] == "data_validation_errors"


def test_revalidate_missing_request_is_business_issue_http_200(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    request_file = _config(tmp_path).requests_dir / "request-1.json"
    request_file.unlink()

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/revalidate",
        json={"expected_revision": record.revision, "storage_dir": "storage"},
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["ready"] is False
    assert [issue["code"] for issue in result["issues"]] == ["REQUEST_MISSING"]
    body_text = response.get_data(as_text=True)
    assert str(tmp_path) not in body_text
    assert "request-1.json" not in body_text


def test_revalidate_no_storage_dir_defaults_to_server_root(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    # Seed the record under the *server root* (the empty storage profile), so
    # the endpoint's storage fallback is exercised end to end.
    config = load_storage_config(tmp_path)
    request = accept_request(
        {
            **build_plan(EntryRequest(raw_title="芙莉莲"), data_source=StaticFixtureDataSource())["request"],
            "request_id": "request-root",
        }
    )
    save_request_snapshot(config, request)
    handoff = ensure_confirmed_request_tracking(
        config=config,
        request=request,
        origin=TRACKING_ORIGIN_SAVE_CONFIRM,
        now="2026-09-08T00:00:00+00:00",
    )
    assert handoff.tracking_id is not None
    record = load_tracking_record(config, handoff.tracking_id)

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/revalidate",
        json={"expected_revision": record.revision},
    )

    # The autouse _web_storage_root maps the empty storage profile to tmp_path.
    assert response.status_code == 200
    assert response.get_json()["result"]["ready"] is True
