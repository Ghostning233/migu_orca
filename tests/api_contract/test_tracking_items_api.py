from __future__ import annotations

"""US-223 route/service tests for the unified tracking list/detail APIs.

These tests run against the real Flask app through the ``client`` fixture but
never touch an external system: accepted Requests are generated from the
static fixture and tracking records/operations are seeded directly through the
repositories.  The autouse ``_web_storage_root`` fixture maps the relative
``storage`` profile onto ``tmp_path``, so absolute tmp paths never leak into
payloads or URLs.
"""

from dataclasses import replace
from pathlib import Path
from typing import Any

from flask.testing import FlaskClient

from apps.migu_orca_entry.controllers.entry_controller import generate_request
from apps.migu_orca_web.api_contract import (
    TrackingDetailResultDTO,
    TrackingItemListResultDTO,
)
from request_engine.controllers.request_controller import accept_request
from shared.models import EntryRequest
from storage_engine.controllers.operation_repository import bind_tracking_operation
from storage_engine.controllers.request_repository import save_request_snapshot
from storage_engine.controllers.storage_config import (
    StorageConfig,
    load_storage_config,
)
from storage_engine.controllers.tracking_repository import (
    compare_and_swap_tracking_record,
    ensure_tracking_record,
)
from tracking_engine.models.tracking import (
    TRACKING_AUDIT_ACTOR_USER,
    TRACKING_AUDIT_SUBMIT_FAILED,
    TRACKING_AUDIT_SUBMIT_SUCCEEDED,
    TRACKING_AUDIT_TRACKING_CREATED,
    TRACKING_ORIGIN_SAVE_CONFIRM,
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_PENDING_SUBMIT,
    TRACKING_STATUS_SUBMIT_FAILED,
    TrackingRecord,
    create_tracking_record,
    tracking_id_for_request,
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
            **generate_request(EntryRequest(raw_title="芙莉莲"))["request"],
            "request_id": request_id,
        }
    )
    save_request_snapshot(config, request)
    return request


def _seed_record(
    tmp_path: Path,
    request_id: str,
    *,
    status: str,
    title: str,
    subtitle_group: str = "喵萌",
    now: str = "2026-01-01T00:00:00+00:00",
) -> TrackingRecord:
    config = _config(tmp_path)
    audit_action = (
        TRACKING_AUDIT_SUBMIT_SUCCEEDED
        if status == TRACKING_STATUS_ACTIVE
        else TRACKING_AUDIT_SUBMIT_FAILED
        if status == TRACKING_STATUS_SUBMIT_FAILED
        else TRACKING_AUDIT_TRACKING_CREATED
    )
    record = create_tracking_record(
        request_id=request_id,
        status=status,
        plan_summary={
            "title": title,
            "season": 1,
            "subtitle_group": subtitle_group,
        },
        origin=TRACKING_ORIGIN_SAVE_CONFIRM,
        audit_action=audit_action,
        audit_actor=TRACKING_AUDIT_ACTOR_USER,
        now=now,
    )
    ensured, _created = ensure_tracking_record(config, record)
    return ensured


def _all_json_leaves(value: Any) -> Any:
    """Yield every scalar and key recursively (leak check helper)."""
    if isinstance(value, dict):
        yield from value.keys()
        for child in value.values():
            yield from _all_json_leaves(child)
    elif isinstance(value, list):
        for child in value:
            yield from _all_json_leaves(child)
    else:
        yield value


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


def test_tracking_list_empty(tmp_path: Path, client: FlaskClient) -> None:
    response = client.get("/api/v1/tracking/items", query_string={"storage_dir": "storage"})

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"] == {
        "items": [],
        "summary": {
            "total": 0,
            "pending": 0,
            "processing": 0,
            "active": 0,
            "needs_attention": 0,
            "unreadable": 0,
        },
        "warnings": [],
    }


def test_tracking_list_returns_safe_summaries_and_actions(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    _seed_record(
        tmp_path, "request-1", status=TRACKING_STATUS_PENDING_SUBMIT, title="葬送的芙莉莲"
    )
    _seed_record(
        tmp_path,
        "request-2",
        status=TRACKING_STATUS_ACTIVE,
        title="咒术回战",
        now="2026-02-01T00:00:00+00:00",
    )
    _seed_record(
        tmp_path,
        "request-3",
        status=TRACKING_STATUS_SUBMIT_FAILED,
        title="葬送的芙莉莲 第二季",
        subtitle_group="Loli",
        now="2026-03-01T00:00:00+00:00",
    )

    response = client.get("/api/v1/tracking/items", query_string={"storage_dir": "storage"})

    payload = response.get_json()
    assert response.status_code == 200
    result = payload["result"]
    assert result["summary"] == {
        "total": 3,
        "pending": 1,
        "processing": 0,
        "active": 1,
        "needs_attention": 1,
        "unreadable": 0,
    }
    # Default sort is newest updated_at first.
    assert [item["request_id"] for item in result["items"]] == [
        "request-3",
        "request-2",
        "request-1",
    ]
    pending = result["items"][2]
    assert pending["tracking_id"] == tracking_id_for_request("request-1")
    assert pending["title"] == "葬送的芙莉莲"
    assert pending["subtitle_group"] == "喵萌"
    assert pending["season"] == 1
    assert pending["poster_path"] is None
    assert pending["status"] == "PENDING_SUBMIT"
    assert pending["status_label"] == "待提交"
    assert pending["status_group"] == "PENDING"
    assert pending["updated_episode"] is None
    assert pending["updated_episode_status"] == "NOT_IMPLEMENTED"
    assert pending["total_episodes"] is None
    assert pending["revision"] == 1
    assert [action["code"] for action in pending["available_actions"]] == [
        "REVALIDATE",
        "SUBMIT",
    ]

    active = result["items"][1]
    assert active["status"] == "ACTIVE"
    assert active["available_actions"] == []

    failed = result["items"][0]
    assert failed["status"] == "SUBMIT_FAILED"
    assert [action["code"] for action in failed["available_actions"]] == [
        "REVALIDATE",
        "RETRY",
    ]


def test_tracking_list_q_and_status_group_and_sort(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    _seed_record(
        tmp_path, "request-1", status=TRACKING_STATUS_PENDING_SUBMIT, title="葬送的芙莉莲"
    )
    _seed_record(
        tmp_path,
        "request-2",
        status=TRACKING_STATUS_ACTIVE,
        title="咒术回战",
        now="2026-02-01T00:00:00+00:00",
    )
    _seed_record(
        tmp_path,
        "request-3",
        status=TRACKING_STATUS_PENDING_SUBMIT,
        title="芙莉莲 外传",
        subtitle_group="Loli",
        now="2026-03-01T00:00:00+00:00",
    )

    # q matches title (case-insensitive on latin, exact on CJK substring).
    response = client.get(
        "/api/v1/tracking/items",
        query_string={"storage_dir": "storage", "q": "芙莉莲"},
    )
    assert [item["request_id"] for item in response.get_json()["result"]["items"]] == [
        "request-3",
        "request-1",
    ]

    # q also matches subtitle_group.
    response = client.get(
        "/api/v1/tracking/items",
        query_string={"storage_dir": "storage", "q": "Loli"},
    )
    assert [item["request_id"] for item in response.get_json()["result"]["items"]] == [
        "request-3"
    ]

    # status_group filter.
    response = client.get(
        "/api/v1/tracking/items",
        query_string={"storage_dir": "storage", "status_group": "ACTIVE"},
    )
    assert [item["request_id"] for item in response.get_json()["result"]["items"]] == [
        "request-2"
    ]

    # Summary is stable across the status_group filter.
    response = client.get(
        "/api/v1/tracking/items",
        query_string={"storage_dir": "storage", "status_group": "ACTIVE"},
    )
    assert response.get_json()["result"]["summary"]["total"] == 3

    # sort=title ascending.
    response = client.get(
        "/api/v1/tracking/items",
        query_string={"storage_dir": "storage", "sort": "title"},
    )
    titles = [item["title"] for item in response.get_json()["result"]["items"]]
    assert titles == sorted(titles)

    # sort=status ascending.
    response = client.get(
        "/api/v1/tracking/items",
        query_string={"storage_dir": "storage", "sort": "status"},
    )
    statuses = [item["status"] for item in response.get_json()["result"]["items"]]
    assert statuses == sorted(statuses)


def test_tracking_list_valid_resource_count_uses_request_safe_info(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    request = _accepted_request(tmp_path, "request-1")
    _seed_record(
        tmp_path,
        "request-1",
        status=TRACKING_STATUS_PENDING_SUBMIT,
        title="葬送的芙莉莲",
    )

    response = client.get("/api/v1/tracking/items", query_string={"storage_dir": "storage"})

    item = response.get_json()["result"]["items"][0]
    # The fixture Request carries one valid seed for its selected group.
    assert item["valid_resource_count"] == 1
    assert request["request_id"] == "request-1"


def test_tracking_list_damaged_record_never_blocks_healthy_list(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    _seed_record(
        tmp_path, "request-1", status=TRACKING_STATUS_PENDING_SUBMIT, title="葬送的芙莉莲"
    )
    config = _config(tmp_path)
    config.tracking_dir.mkdir(parents=True, exist_ok=True)
    (config.tracking_dir / "trk_damaged.json").write_text("{not json", encoding="utf-8")

    response = client.get("/api/v1/tracking/items", query_string={"storage_dir": "storage"})

    payload = response.get_json()
    assert response.status_code == 200
    result = payload["result"]
    assert [item["request_id"] for item in result["items"]] == ["request-1"]
    assert result["summary"]["total"] == 1
    assert result["summary"]["unreadable"] == 1
    assert any("暂时无法读取" in warning for warning in result["warnings"])
    body_text = response.get_data(as_text=True)
    assert str(tmp_path) not in body_text
    assert "trk_damaged" not in body_text


def test_tracking_list_rejects_invalid_enum_queries(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    response = client.get(
        "/api/v1/tracking/items",
        query_string={"storage_dir": "storage", "status_group": "BOGUS"},
    )
    assert response.status_code == 400
    assert response.get_json()["error_type"] == "data_validation_errors"

    response = client.get(
        "/api/v1/tracking/items",
        query_string={"storage_dir": "storage", "sort": "bogus"},
    )
    assert response.status_code == 400
    assert response.get_json()["error_type"] == "data_validation_errors"


def test_tracking_list_result_matches_strict_dto(tmp_path: Path, client: FlaskClient) -> None:
    _seed_record(
        tmp_path, "request-1", status=TRACKING_STATUS_PENDING_SUBMIT, title="葬送的芙莉莲"
    )
    response = client.get("/api/v1/tracking/items", query_string={"storage_dir": "storage"})
    result = response.get_json()["result"]
    validated = TrackingItemListResultDTO.model_validate(result)
    assert validated.summary.total == 1


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------


def test_tracking_detail_returns_safe_info_and_audit(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    _accepted_request(tmp_path, "request-1")
    record = _seed_record(
        tmp_path,
        "request-1",
        status=TRACKING_STATUS_PENDING_SUBMIT,
        title="葬送的芙莉莲",
    )

    response = client.get(
        f"/api/v1/tracking/items/{record.tracking_id}",
        query_string={"storage_dir": "storage"},
    )

    payload = response.get_json()
    assert response.status_code == 200
    result = payload["result"]
    assert result["tracking_id"] == record.tracking_id
    assert result["request_id"] == "request-1"
    assert result["status"] == "PENDING_SUBMIT"
    assert result["status_label"] == "待提交"
    assert result["status_group"] == "PENDING"
    assert result["origin"] == TRACKING_ORIGIN_SAVE_CONFIRM
    assert result["revision"] == 1
    assert result["safe_info"]["request_id"] == "request-1"
    assert result["safe_info"]["status"] == "ACCEPTED"
    assert result["safe_info"]["updated_episode_status"] == "NOT_IMPLEMENTED"
    assert result["current_operation"] is None
    assert result["revalidation_issues"] == []
    assert result["external_mapping"] is None
    assert len(result["audit_events"]) == 1
    assert result["audit_events"][0]["action"] == "TRACKING_CREATED"
    assert result["warnings"] == []
    # Detail DTO strictness: no extra top-level keys.
    TrackingDetailResultDTO.model_validate(result)

    body_text = response.get_data(as_text=True)
    assert str(tmp_path) not in body_text
    assert "http://" not in body_text
    assert "magnet:" not in body_text.lower()


def test_tracking_detail_returns_operation_summary_without_key(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    record = _seed_record(
        tmp_path,
        "request-1",
        status=TRACKING_STATUS_PENDING_SUBMIT,
        title="葬送的芙莉莲",
    )
    config = _config(tmp_path)
    operation, _created = bind_tracking_operation(
        config,
        tracking_id=record.tracking_id,
        operation="SUBMIT",
        idempotency_key="opaque-key-abc123",
        expected_revision=record.revision,
        request_fingerprint="fp",
    )
    advanced = transition_record(
        record,
        status=TRACKING_STATUS_SUBMIT_FAILED,
        audit_action=TRACKING_AUDIT_SUBMIT_FAILED,
        operation_id=operation.operation_id,
    )
    advanced = replace(advanced, current_operation_id=operation.operation_id)
    compare_and_swap_tracking_record(
        config,
        record.tracking_id,
        base_revision=record.revision,
        record=advanced,
    )

    response = client.get(
        f"/api/v1/tracking/items/{record.tracking_id}",
        query_string={"storage_dir": "storage"},
    )

    payload = response.get_json()
    assert response.status_code == 200
    result = payload["result"]
    current = result["current_operation"]
    assert current is not None
    assert current["operation_id"] == operation.operation_id
    assert current["operation"] == "SUBMIT"
    assert current["state"] == "PREPARED"
    assert current["attempt"] == 1
    assert result["status"] == "SUBMIT_FAILED"
    body_text = response.get_data(as_text=True)
    assert "opaque-key-abc123" not in body_text


def test_tracking_detail_missing_record_is_404(tmp_path: Path, client: FlaskClient) -> None:
    response = client.get(
        "/api/v1/tracking/items/trk_nonexistent0000000000000000000000",
        query_string={"storage_dir": "storage"},
    )
    assert response.status_code == 404
    assert response.get_json()["error_type"] == "tracking_not_found"


def test_tracking_detail_rejects_path_fragment(tmp_path: Path, client: FlaskClient) -> None:
    response = client.get(
        "/api/v1/tracking/items/trk_a/b",
        query_string={"storage_dir": "storage"},
    )
    assert response.status_code == 400
    assert response.get_json()["error_type"] == "invalid_tracking_id"


def test_tracking_detail_degrades_when_request_missing(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    record = _seed_record(
        tmp_path,
        "request-1",
        status=TRACKING_STATUS_PENDING_SUBMIT,
        title="葬送的芙莉莲",
    )
    response = client.get(
        f"/api/v1/tracking/items/{record.tracking_id}",
        query_string={"storage_dir": "storage"},
    )
    payload = response.get_json()
    assert response.status_code == 200
    result = payload["result"]
    assert result["safe_info"] is None
    assert result["valid_resource_count"] == 0
    assert any("不存在或暂时不可读" in warning for warning in result["warnings"])


def test_tracking_list_poisoned_plan_label_is_redacted(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    config = _config(tmp_path)
    record = create_tracking_record(
        request_id="request-poisoned",
        status=TRACKING_STATUS_PENDING_SUBMIT,
        plan_summary={"title": "https://private.example/leak", "subtitle_group": "喵萌"},
        origin=TRACKING_ORIGIN_SAVE_CONFIRM,
        audit_action=TRACKING_AUDIT_TRACKING_CREATED,
        audit_actor=TRACKING_AUDIT_ACTOR_USER,
    )
    ensure_tracking_record(config, record)

    response = client.get("/api/v1/tracking/items", query_string={"storage_dir": "storage"})
    payload = response.get_json()
    assert response.status_code == 200
    item = payload["result"]["items"][0]
    assert item["title"] == "[redacted]"
    body_text = response.get_data(as_text=True)
    assert "private.example" not in body_text
