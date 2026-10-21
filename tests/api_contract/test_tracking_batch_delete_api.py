"""Batch delete API contract tests (issue #223, ADR-0007).

These exercise the real Flask app with isolated temporary storage and a stubbed
external boundary, so the published contract (request shape, per-entry result,
skip reasons, idempotent replay, batch exclusion, status query) is verified
without any Auto Bangumi instance.
"""
from __future__ import annotations

import json
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient

from apps.migu_orca_web.api_contract import TrackingBatchDeleteResultDTO
from shared.errors import Stage1Error
from storage_engine.controllers.operation_repository import bind_tracking_operation
from storage_engine.controllers.storage_config import StorageConfig, load_storage_config
from storage_engine.controllers.tracking_repository import (
    compare_and_swap_tracking_record,
    ensure_tracking_record,
    list_tracking_records,
    load_tracking_record,
)
from tracking_engine.models.tracking import (
    TRACKING_STATUS_ACTIVE,
    TrackingRecord,
    create_external_tracking_record,
)

REF = "11111111-1111-4111-8111-111111111111"
LOCAL_URL = "/api/v1/tracking/batch-delete-plan"
EXTERNAL_URL = "/api/v1/tracking/batch-delete-plan-external"
STATUS_URL = "/api/v1/tracking/batch-deletions/{}"


@pytest.fixture(autouse=True)
def _fast_batch_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the ADR-0007 bounded wait short so refusals stay fast in tests."""
    import storage_engine.controllers.tracking_repository as tracking_repository

    monkeypatch.setattr(tracking_repository, "_BATCH_WAIT_SECONDS", 0.05)


def _config(tmp_path: Path) -> StorageConfig:
    return load_storage_config(tmp_path / "storage")


def _seed(tmp_path: Path, index: int, *, connection_ref: str | None = REF) -> TrackingRecord:
    config = _config(tmp_path)
    record = create_external_tracking_record(
        adapter="legacy_3_1",
        object_kind="subscription",
        external_id=f"sub-{index}",
        subscription_id=f"sub-{index}",
        title=f"Show {index}",
        season=1,
        connection_ref=connection_ref,
    )
    record, _created = ensure_tracking_record(
        config, replace(record, status=TRACKING_STATUS_ACTIVE)
    )
    return record


def _items(records: list[TrackingRecord]) -> list[dict[str, Any]]:
    return [
        {"tracking_id": record.tracking_id, "expected_revision": record.revision}
        for record in records
    ]


def _local_body(records: list[TrackingRecord], **overrides: Any) -> dict[str, Any]:
    return {
        "confirm": True,
        "idempotency_key": "batch-local-1",
        "items": _items(records),
        "storage_dir": "storage",
        **overrides,
    }


def _external_body(records: list[TrackingRecord], **overrides: Any) -> dict[str, Any]:
    return {
        **_local_body(records, idempotency_key="batch-external-1"),
        "connection_ref": REF,
        "configuration_revision": 3,
        **overrides,
    }


def _stub_management(
    monkeypatch: pytest.MonkeyPatch,
    statuses: dict[str, str] | None = None,
    *,
    gate: threading.Event | None = None,
    entered: threading.Event | None = None,
) -> list[dict[str, Any]]:
    """Stub the reliable management chain (the only external boundary here)."""
    calls: list[dict[str, Any]] = []

    def fake(payload: Any, **_kwargs: Any) -> dict[str, Any]:
        calls.append(
            {
                "tracking_id": payload.tracking_id,
                "operation": payload.operation,
                "scope": payload.target_scope,
            }
        )
        if gate is not None:
            assert entered is not None
            entered.set()
            assert gate.wait(timeout=10), "batch gate was never released"
        status = (statuses or {}).get(payload.tracking_id, "SUCCEEDED")
        return {"management_status": status, "outcome": status}

    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_plan_delete_service.run_saved_tracking_management",
        fake,
    )
    return calls


def test_local_batch_deletes_plans_with_zero_external_calls(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC1/AC3/AC7: local-only batch is a pure local delete."""
    calls = _stub_management(monkeypatch)
    records = [_seed(tmp_path, index) for index in (1, 2, 3)]

    response = client.post(LOCAL_URL, json=_local_body(records))

    assert response.status_code == 200, response.get_json()
    result = response.get_json()["result"]
    TrackingBatchDeleteResultDTO.model_validate(result)
    assert result["kind"] == "LOCAL_ONLY"
    assert result["state"] == "COMPLETED"
    assert [item["outcome"] for item in result["items"]] == ["DELETED"] * 3
    assert [item["external_deleted"] for item in result["items"]] == [False] * 3
    assert result["summary"] == {
        "total": 3, "deleted": 3, "external_deleted": 0, "skipped": 0, "failed": 0, "unknown": 0,
    }
    assert calls == [], "a local-only batch must never reach the external boundary"
    assert list_tracking_records(_config(tmp_path)).records == []


def test_external_batch_deletes_each_subscription_before_its_local_record(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC1/AC2/AC3: the external leg runs per entry, in payload order."""
    calls = _stub_management(monkeypatch)
    records = [_seed(tmp_path, index) for index in (1, 2, 3)]

    response = client.post(EXTERNAL_URL, json=_external_body(records))

    assert response.status_code == 200, response.get_json()
    result = response.get_json()["result"]
    TrackingBatchDeleteResultDTO.model_validate(result)
    assert result["kind"] == "LOCAL_AND_EXTERNAL"
    assert [item["outcome"] for item in result["items"]] == ["DELETED"] * 3
    assert [item["external_deleted"] for item in result["items"]] == [True] * 3
    assert [call["tracking_id"] for call in calls] == [record.tracking_id for record in records]
    assert {call["operation"] for call in calls} == {"DELETE_EXTERNAL"}
    assert list_tracking_records(_config(tmp_path)).records == []


@pytest.mark.parametrize(
    ("status", "outcome"),
    [("FAILED", "EXTERNAL_FAILED"), ("OUTCOME_UNKNOWN", "EXTERNAL_UNKNOWN")],
)
def test_unconfirmed_external_delete_keeps_that_entry_local(
    tmp_path: Path,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    outcome: str,
) -> None:
    """AC3: nothing local is removed for an entry whose external delete is not confirmed."""
    records = [_seed(tmp_path, index) for index in (1, 2, 3)]
    calls = _stub_management(monkeypatch, {records[1].tracking_id: status})

    response = client.post(EXTERNAL_URL, json=_external_body(records))

    assert response.status_code == 200, response.get_json()
    items = response.get_json()["result"]["items"]
    by_id = {item["tracking_id"]: item for item in items}
    assert by_id[records[1].tracking_id]["outcome"] == outcome
    assert by_id[records[1].tracking_id]["external_deleted"] is False
    # The failed entry keeps its record and mapping; the others are gone.
    kept = load_tracking_record(_config(tmp_path), records[1].tracking_id)
    assert kept.external_mapping is not None
    remaining = {record.tracking_id for record in list_tracking_records(_config(tmp_path)).records}
    assert remaining == {records[1].tracking_id}
    assert len(calls) == 3, "the remaining entries still ran"


def test_unresolved_entry_is_skipped_with_a_reason_and_kept(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC4/AC8: an unresolved entry never enters the batch, and is explained."""
    calls = _stub_management(monkeypatch)
    record = _seed(tmp_path, 1)
    operation, _created = bind_tracking_operation(
        _config(tmp_path),
        tracking_id=record.tracking_id,
        operation="SUBMIT",
        idempotency_key="pending-submit-key",
        expected_revision=record.revision,
        request_fingerprint="fingerprint",
    )
    guarded = compare_and_swap_tracking_record(
        _config(tmp_path),
        record.tracking_id,
        record.revision,
        replace(
            record,
            current_operation_id=operation.operation_id,
            revision=record.revision + 1,
        ),
    )

    response = client.post(LOCAL_URL, json=_local_body([guarded], idempotency_key="batch-unresolved"))

    assert response.status_code == 200, response.get_json()
    item = response.get_json()["result"]["items"][0]
    assert item["outcome"] == "SKIPPED"
    assert item["skip_reason"] == "UNRESOLVED"
    assert calls == []
    assert load_tracking_record(_config(tmp_path), record.tracking_id).current_operation_id == operation.operation_id


def test_same_key_replay_returns_the_stored_result_without_second_external_write(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC9: a timed-out client can replay the same key safely."""
    records = [_seed(tmp_path, index) for index in (1, 2)]
    calls = _stub_management(monkeypatch)
    body = _external_body(records, idempotency_key="batch-replay")

    first = client.post(EXTERNAL_URL, json=body)
    after_first = len(calls)
    second = client.post(EXTERNAL_URL, json=body)

    assert first.status_code == 200, first.get_json()
    assert second.status_code == 200, second.get_json()
    assert second.get_json()["result"] == first.get_json()["result"]
    assert len(calls) == after_first == 2


def test_status_endpoint_reports_the_completed_batch_and_404_for_unknown_keys(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC9: the batch is queryable by its idempotency key."""
    _stub_management(monkeypatch)
    records = [_seed(tmp_path, index) for index in (1, 2)]
    body = _local_body(records, idempotency_key="batch-status")
    client.post(LOCAL_URL, json=body)

    response = client.get(STATUS_URL.format("batch-status"), query_string={"storage_dir": "storage"})

    assert response.status_code == 200, response.get_json()
    result = response.get_json()["result"]
    TrackingBatchDeleteResultDTO.model_validate(result)
    assert result["state"] == "COMPLETED"
    assert [item["outcome"] for item in result["items"]] == ["DELETED", "DELETED"]

    unknown = client.get(STATUS_URL.format("batch-never-existed"), query_string={"storage_dir": "storage"})
    assert unknown.status_code == 404
    assert unknown.get_json()["error_type"] == "tracking_not_found"


def test_same_key_bound_to_different_entries_is_a_conflict(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_management(monkeypatch)
    first = _seed(tmp_path, 1)
    second = _seed(tmp_path, 2)
    client.post(EXTERNAL_URL, json=_external_body([first], idempotency_key="batch-conflict"))

    response = client.post(EXTERNAL_URL, json=_external_body([second], idempotency_key="batch-conflict"))

    assert response.status_code == 409, response.get_json()
    assert response.get_json()["error_type"] == "idempotency_conflict"


def test_a_second_batch_is_refused_while_one_runs(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC9: two batches are mutually exclusive at the HTTP boundary."""
    gate = threading.Event()
    entered = threading.Event()
    _stub_management(monkeypatch, gate=gate, entered=entered)
    first = _seed(tmp_path, 1)
    second = _seed(tmp_path, 2)
    outcome: dict[str, Any] = {}

    def run_first() -> None:
        from apps.base import create_app

        local = create_app("testing").test_client()
        outcome["first"] = local.post(
            EXTERNAL_URL, json=_external_body([first], idempotency_key="batch-running")
        )

    thread = threading.Thread(target=run_first)
    thread.start()
    assert entered.wait(timeout=10), "the first batch never reached the external boundary"

    refused = client.post(EXTERNAL_URL, json=_external_body([second], idempotency_key="batch-refused"))

    gate.set()
    thread.join(timeout=20)
    assert "first" in outcome, outcome
    assert outcome["first"].status_code == 200, outcome["first"].get_json()
    assert refused.status_code == 409, refused.get_json()
    assert refused.get_json()["error_type"] == "connection_in_use"
    # The refused batch wrote nothing.
    load_tracking_record(_config(tmp_path), second.tracking_id)


def test_batch_submit_is_refused_while_a_batch_owns_the_store(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0007: batches exclude each other across both batch families."""
    from storage_engine.controllers.tracking_repository import tracking_batch_lease

    _stub_management(monkeypatch)
    record = _seed(tmp_path, 1)
    held = threading.Event()
    release = threading.Event()

    def hold_batch() -> None:
        with tracking_batch_lease(batch_key="held-batch"):
            held.set()
            assert release.wait(timeout=10)

    holder = threading.Thread(target=hold_batch)
    holder.start()
    assert held.wait(timeout=10)

    try:
        response = client.post(
            "/api/v1/tracking/batch-submit",
            json={
                "confirm": True,
                "submission_mode": "CONTINUE_TRACKING",
                "connection_ref": REF,
                "configuration_revision": 3,
                "storage_dir": "storage",
                "items": [{
                    "tracking_id": record.tracking_id,
                    "expected_revision": record.revision,
                    "idempotency_key": "submit-during-batch",
                }],
            },
        )
    finally:
        release.set()
        holder.join(timeout=10)

    assert response.status_code == 409, response.get_json()
    assert response.get_json()["error_type"] == "connection_in_use"
    # The refused batch persisted nothing for its entry.
    load_tracking_record(_config(tmp_path), record.tracking_id)


@pytest.mark.parametrize(
    ("url", "body", "error_type"),
    [
        (LOCAL_URL, {"items": [{"tracking_id": "trk_a", "expected_revision": 1}], "confirm": False, "idempotency_key": "k"}, "data_validation_errors"),
        (LOCAL_URL, {"items": [], "confirm": True, "idempotency_key": "k"}, "data_validation_errors"),
        (LOCAL_URL, {"confirm": True, "idempotency_key": "k"}, "data_validation_errors"),
        (LOCAL_URL, {"items": [{"tracking_id": "trk_a", "expected_revision": 1}], "confirm": True}, "data_validation_errors"),
        (
            LOCAL_URL,
            {
                "items": [
                    {"tracking_id": "trk_a", "expected_revision": 1},
                    {"tracking_id": "trk_a", "expected_revision": 2},
                ],
                "confirm": True,
                "idempotency_key": "k",
            },
            "data_validation_errors",
        ),
        (
            LOCAL_URL,
            {
                "items": [{"tracking_id": f"trk_{index}", "expected_revision": 1} for index in range(37)],
                "confirm": True,
                "idempotency_key": "k",
            },
            "data_validation_errors",
        ),
        (
            LOCAL_URL,
            {
                "items": [{"tracking_id": "trk_a", "expected_revision": 1}],
                "confirm": True,
                "idempotency_key": "k",
                "connection_ref": REF,
            },
            "data_validation_errors",
        ),
        (
            LOCAL_URL,
            {
                "items": [{"tracking_id": "trk_a", "expected_revision": 1}],
                "confirm": True,
                "idempotency_key": "k",
                "storage_dir": "/absolute",
            },
            "invalid_storage_dir",
        ),
        (
            EXTERNAL_URL,
            {"items": [{"tracking_id": "trk_a", "expected_revision": 1}], "confirm": True, "idempotency_key": "k"},
            "data_validation_errors",
        ),
    ],
)
def test_batch_delete_rejects_invalid_requests(
    client: FlaskClient, url: str, body: dict[str, Any], error_type: str
) -> None:
    response = client.post(url, json=body)

    assert response.status_code == 400, response.get_json()
    assert response.get_json()["error_type"] == error_type


def test_batch_delete_response_carries_no_private_or_upstream_values(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Security: only opaque ids, outcomes and fixed reasons leave the server."""
    _stub_management(monkeypatch)
    record = _seed(tmp_path, 1)
    body = _external_body([record], idempotency_key="batch-safe")

    raw = json.dumps(client.post(EXTERNAL_URL, json=body).get_json(), ensure_ascii=False)

    assert "Show 1" not in raw
    assert REF not in raw
    assert "secret" not in raw
    assert "sub-1" not in raw


def test_local_batch_reports_missing_and_stale_entries_with_reasons(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC8: execution-time eligibility is re-verified per entry."""
    _stub_management(monkeypatch)
    record = _seed(tmp_path, 1)
    body = _local_body(
        [record],
        idempotency_key="batch-stale",
        items=[
            {"tracking_id": record.tracking_id, "expected_revision": record.revision + 9},
            {"tracking_id": "trk_missing", "expected_revision": 1},
        ],
    )

    response = client.post(LOCAL_URL, json=body)

    assert response.status_code == 200, response.get_json()
    items = response.get_json()["result"]["items"]
    assert [item["skip_reason"] for item in items] == ["REVISION_CHANGED", "NOT_FOUND"]
    assert response.get_json()["result"]["summary"]["skipped"] == 2
    assert load_tracking_record(_config(tmp_path), record.tracking_id).revision == record.revision


def test_batch_delete_requires_confirm_true_for_the_external_kind(
    tmp_path: Path, client: FlaskClient
) -> None:
    record = _seed(tmp_path, 1)

    response = client.post(EXTERNAL_URL, json=_external_body([record], confirm=False))

    assert response.status_code == 400, response.get_json()
    assert response.get_json()["error_type"] == "data_validation_errors"


def test_unknown_errors_are_not_leaked_into_the_batch_result(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A per-entry refusal becomes a stable code, never raw upstream text."""
    def explode(_payload: Any, **_kwargs: Any) -> dict[str, Any]:
        raise Stage1Error("ab_http_failed", "upstream body with secret-password", "management")

    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_plan_delete_service.run_saved_tracking_management",
        explode,
    )
    record = _seed(tmp_path, 1)

    response = client.post(EXTERNAL_URL, json=_external_body([record], idempotency_key="batch-explode"))

    assert response.status_code == 200, response.get_json()
    item = response.get_json()["result"]["items"][0]
    assert item["outcome"] == "SKIPPED"
    assert item["error_type"] == "ab_http_failed"
    assert "secret-password" not in json.dumps(item, ensure_ascii=False)
    load_tracking_record(_config(tmp_path), record.tracking_id)
