from __future__ import annotations

"""Issue #92: unified "delete the tracking plan" contract tests.

The endpoint deletes the local plan **and** its tracking record together, and
optionally the controlled external subscription as well. These tests run against
the real Flask app with an isolated temporary storage root and a stubbed
management sequence, so the coordination rules (nothing local is removed on an
external failure or unknown outcome; the external path is only taken when the
user ticked the option) are verified without any external system.
"""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient

from apps.migu_orca_entry.controllers.entry_controller import generate_request
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
from storage_engine.controllers.storage_config import StorageConfig, load_storage_config
from storage_engine.controllers.tracking_repository import (
    compare_and_swap_tracking_record,
    list_tracking_records,
    load_tracking_record,
)
from tracking_engine.models.tracking import (
    TRACKING_ORIGIN_SAVE_CONFIRM,
    TRACKING_STATUS_SUBMITTING,
    TrackingRecord,
)

REF = "11111111-1111-4111-8111-111111111111"


def _config(tmp_path: Path) -> StorageConfig:
    return load_storage_config(tmp_path / "storage")


def _seed(tmp_path: Path, *, mapped: bool) -> tuple[TrackingRecord, dict[str, Any]]:
    AutoBangumiConfigRepository(tmp_path / "config").save(
        build_stored_autobangumi_config({
            "auth_mode": "password", "base_url": "http://ab.invalid",
            "username": "operator", "password": "secret-password",
        }),
        expected_configuration_revision=0,
    )
    config = _config(tmp_path)
    request = accept_request({
        **generate_request(EntryRequest(raw_title="芙莉莲"))["request"],
        "request_id": "request-plan",
    })
    save_request_snapshot(config, request)
    handoff = ensure_confirmed_request_tracking(
        config=config, request=request, origin=TRACKING_ORIGIN_SAVE_CONFIRM,
        now="2026-09-08T00:00:00+00:00",
    )
    record = load_tracking_record(config, handoff.tracking_id)
    if mapped:
        record = compare_and_swap_tracking_record(
            config, record.tracking_id, record.revision,
            replace(
                record,
                external_mapping={"subscription_id": "sub-1", "connection_ref": REF},
                revision=record.revision + 1,
                updated_at="2026-09-08T00:00:00+00:00",
            ),
        )
    return record, request


def _body(record: TrackingRecord, **overrides: Any) -> dict[str, Any]:
    return {
        "confirm": True,
        "delete_external": False,
        "idempotency_key": "delete-key-1",
        "connection_ref": REF,
        "configuration_revision": 1,
        "storage_dir": "storage",
        **overrides,
    }


def _post(client: FlaskClient, record: TrackingRecord, **overrides: Any) -> Any:
    return client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/delete-plan",
        json=_body(record, **overrides),
    )


def _stub_management(monkeypatch: pytest.MonkeyPatch, status: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake(payload: Any, **_kwargs: Any) -> dict[str, Any]:
        calls.append({"operation": payload.operation, "scope": payload.target_scope})
        return {"management_status": status, "outcome": status}

    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_plan_delete_service.run_saved_tracking_management",
        fake,
    )
    return calls


def test_delete_plan_without_external_object_removes_local_data(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    record, request = _seed(tmp_path, mapped=False)
    calls = _stub_management(monkeypatch, "SUCCEEDED")

    response = _post(client, record)

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["result"] == {
        "tracking_id": record.tracking_id, "outcome": "DELETED", "external_deleted": False,
    }
    # Nothing external was contacted, and both local objects are gone.
    assert calls == []
    assert list_tracking_records(_config(tmp_path)).records == []
    with pytest.raises(Stage1Error):
        load_request_snapshot(_config(tmp_path), request["request_id"])


def test_delete_plan_keeps_the_external_subscription_unless_ticked(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    record, _request = _seed(tmp_path, mapped=True)
    calls = _stub_management(monkeypatch, "SUCCEEDED")

    response = _post(client, record, delete_external=False)

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["result"]["outcome"] == "DELETED"
    assert payload["result"]["external_deleted"] is False
    # The external object is untouched: no management call was made at all.
    assert calls == []
    assert list_tracking_records(_config(tmp_path)).records == []


def test_delete_plan_removes_the_external_subscription_first_when_ticked(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    record, _request = _seed(tmp_path, mapped=True)
    calls = _stub_management(monkeypatch, "SUCCEEDED")

    response = _post(client, record, delete_external=True)

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["result"] == {
        "tracking_id": record.tracking_id, "outcome": "DELETED", "external_deleted": True,
    }
    assert calls == [{"operation": "DELETE_EXTERNAL", "scope": "SUBSCRIPTION"}]
    assert list_tracking_records(_config(tmp_path)).records == []


@pytest.mark.parametrize(
    ("status", "expected"),
    [("FAILED", "EXTERNAL_FAILED"), ("OUTCOME_UNKNOWN", "EXTERNAL_UNKNOWN"), ("RECOVERY_REQUIRED", "EXTERNAL_UNKNOWN")],
)
def test_delete_plan_keeps_everything_local_when_the_external_delete_is_not_confirmed(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch, status: str, expected: str
) -> None:
    record, request = _seed(tmp_path, mapped=True)
    _stub_management(monkeypatch, status)

    response = _post(client, record, delete_external=True)

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["result"]["outcome"] == expected
    assert payload["result"]["external_deleted"] is False
    # The plan, record, mapping and recovery evidence all stay.
    stored = load_tracking_record(_config(tmp_path), record.tracking_id)
    assert stored.external_mapping == record.external_mapping
    assert load_request_snapshot(_config(tmp_path), request["request_id"])["request_id"] == "request-plan"


def test_delete_plan_refuses_while_an_external_action_is_unresolved(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    record, _request = _seed(tmp_path, mapped=True)
    config = _config(tmp_path)
    in_flight = compare_and_swap_tracking_record(
        config, record.tracking_id, record.revision,
        replace(
            record,
            status=TRACKING_STATUS_SUBMITTING,
            current_operation_id="op-pending",
            revision=record.revision + 1,
            updated_at="2026-09-08T00:00:00+00:00",
        ),
    )
    calls = _stub_management(monkeypatch, "SUCCEEDED")

    response = _post(client, in_flight, delete_external=True)

    assert response.status_code == 409
    assert response.get_json()["error_type"] == "tracking_state_conflict"
    assert calls == []
    assert load_tracking_record(config, record.tracking_id).status == TRACKING_STATUS_SUBMITTING


def test_delete_plan_requires_an_explicit_confirmation(
    tmp_path: Path, client: FlaskClient
) -> None:
    record, _request = _seed(tmp_path, mapped=False)

    response = _post(client, record, confirm=False)

    assert response.status_code == 400
    assert response.get_json()["error_type"] == "data_validation_errors"
    assert [item.tracking_id for item in list_tracking_records(_config(tmp_path)).records] == [
        record.tracking_id
    ]


def test_delete_plan_never_sends_a_media_flag(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    record, _request = _seed(tmp_path, mapped=True)
    _stub_management(monkeypatch, "SUCCEEDED")

    response = _post(client, record, delete_external=True, file=True, delete_files=True)

    # Unknown transport flags are rejected outright: no path can ask to delete
    # downloaded media.
    assert response.status_code == 400
    assert response.get_json()["error_type"] == "data_validation_errors"
