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

import pytest
from flask.testing import FlaskClient

from apps.migu_orca_web import tracking_poster
from apps.migu_orca_web.api_contract import (
    TrackingDetailResultDTO,
    TrackingItemListResultDTO,
)
from apps.migu_orca_web.tracking_handoff import ensure_confirmed_request_tracking
from mikan_engine.controllers.mikan_poster_cache import (
    MikanPosterCacheConfig,
    poster_cache_key,
)
from mikan_engine.controllers.mikan_poster_service import MikanPosterService
from plan_engine.controllers.data_sources import StaticFixtureDataSource
from plan_engine.controllers.plan_generation import build_plan
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
    TRACKING_STATUS_ADDED_TO_DOWNLOAD,
    TRACKING_STATUS_DISABLED,
    TRACKING_STATUS_EXTERNAL_DELETED,
    TRACKING_STATUS_EXTERNAL_ONLY,
    TRACKING_STATUS_PENDING_SUBMIT,
    TRACKING_STATUS_SUBMIT_FAILED,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
    TrackingRecord,
    create_external_tracking_record,
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
            **build_plan(EntryRequest(raw_title="芙莉莲"), data_source=StaticFixtureDataSource())["request"],
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


def _seed_external_only(
    tmp_path: Path,
    *,
    external_id: str = "sub-history-1",
    title: str = "历史外部订阅",
) -> TrackingRecord:
    """Seed a read-only ``EXTERNAL_ONLY`` archive record (issue #224 A4).

    It is built through the external-record constructor so it carries a real
    external mapping and no local Request — exactly the historical shape.
    """
    config = _config(tmp_path)
    record = create_external_tracking_record(
        adapter="legacy_3_1",
        object_kind="subscription",
        external_id=external_id,
        subscription_id=external_id,
        title=title,
        season=1,
        subtitle_group="喵萌",
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


def test_tracking_sync_rejects_retired_request_scoped_credentials(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """US-233: sync output is a safe projection, never an upstream echo."""
    response = client.post("/api/v1/tracking/sync", json={
        "confirm": True,
        "storage_dir": "storage",
        "connection_ref": "11111111-1111-4111-8111-111111111111",
        "configuration_revision": 1,
        "ab_config": {
            "auth_mode": "password", "fallback_enabled": False,
            "base_url": "https://private.example", "username": "operator",
            "password": "password-secret",
        },
    })

    assert response.status_code == 400
    assert response.get_json()["error_type"] == "data_validation_errors"
    rendered = " ".join(str(item) for item in _all_json_leaves(response.get_json()))
    for forbidden in ("private.example", "operator", "password-secret"):
        assert forbidden not in rendered

    invalid = client.post("/api/v1/tracking/sync", json={"confirm": False, "ab_config": {"fallback_enabled": False}})
    assert invalid.status_code == 400


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


def test_tracking_list_empty(tmp_path: Path, client: FlaskClient) -> None:
    response = client.get("/api/v1/tracking/items", query_string={"storage_dir": "storage"})

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    # Issue #224 A7: the group metadata is published even for an empty list, so
    # the client keeps no label table and still renders zero-count cards.
    assert payload["result"] == {
        "items": [],
        "summary": {
            "total": 0,
            "pending": 0,
            "processing": 0,
            "active": 0,
            "added_to_download": 0,
            "inactive": 0,
            "needs_attention": 0,
            "unreadable": 0,
        },
        "status_groups": [
            {"group": "PENDING", "label": "待处理", "count": 0, "has_overview_card": True},
            {"group": "PROCESSING", "label": "处理中", "count": 0, "has_overview_card": False},
            {"group": "ACTIVE", "label": "追番中", "count": 0, "has_overview_card": True},
            {"group": "ATTENTION", "label": "需处理", "count": 0, "has_overview_card": True},
            {"group": "INACTIVE", "label": "已停用", "count": 0, "has_overview_card": True},
        ],
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
        "added_to_download": 0,
        "inactive": 0,
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
    # #228 E1: the standalone 重新复核 entry is retired; the submit path
    # revalidates internally, so only the submit decision is projected.
    assert [action["code"] for action in pending["available_actions"]] == [
        "SUBMIT",
    ]

    active = result["items"][1]
    assert active["status"] == "ACTIVE"
    # No local external mapping means all management targets fail closed.
    assert active["available_actions"] == []

    failed = result["items"][0]
    assert failed["status"] == "SUBMIT_FAILED"
    assert [action["code"] for action in failed["available_actions"]] == [
        "RETRY",
    ]


def test_tracking_summary_counts_the_disabled_group(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    """Issue #85: "已停用" is an overview category backed by server counts."""
    _seed_record(
        tmp_path,
        "request-disabled",
        status=TRACKING_STATUS_DISABLED,
        title="已停用番剧",
    )

    response = client.get("/api/v1/tracking/items", query_string={"storage_dir": "storage"})

    payload = response.get_json()
    assert response.status_code == 200
    item = payload["result"]["items"][0]
    assert item["status_label"] == "已停用"
    assert item["status_group"] == "INACTIVE"
    assert payload["result"]["summary"]["inactive"] == 1


def test_tracking_list_publishes_four_card_metadata_with_whole_library_counts(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    """#224 A2/A3/A5/A7: four server-owned cards over authoritative counts."""
    _seed_record(tmp_path, "request-pending", status=TRACKING_STATUS_PENDING_SUBMIT, title="待提交番")
    _seed_record(tmp_path, "request-active", status=TRACKING_STATUS_ACTIVE, title="追番中番")
    _seed_record(
        tmp_path, "request-added", status=TRACKING_STATUS_ADDED_TO_DOWNLOAD, title="已加入下载番"
    )
    _seed_record(tmp_path, "request-failed", status=TRACKING_STATUS_SUBMIT_FAILED, title="提交失败番")
    _seed_record(
        tmp_path, "request-deleted", status=TRACKING_STATUS_EXTERNAL_DELETED, title="外部已删除番"
    )
    _seed_record(tmp_path, "request-disabled", status=TRACKING_STATUS_DISABLED, title="已停用番")
    _seed_record(
        tmp_path, "request-verifying", status=TRACKING_STATUS_VERIFYING_EXTERNAL, title="核验中番"
    )
    _seed_external_only(tmp_path)

    response = client.get("/api/v1/tracking/items", query_string={"storage_dir": "storage"})
    assert response.status_code == 200
    result = response.get_json()["result"]

    assert result["status_groups"] == [
        {"group": "PENDING", "label": "待处理", "count": 1, "has_overview_card": True},
        {"group": "PROCESSING", "label": "处理中", "count": 1, "has_overview_card": False},
        # 追番中 + 已加入下载 are one card.
        {"group": "ACTIVE", "label": "追番中", "count": 2, "has_overview_card": True},
        # 提交失败 + 需要恢复 + 状态未知 + 外部已删除 are one card.
        {"group": "ATTENTION", "label": "需处理", "count": 2, "has_overview_card": True},
        # 仅外部 is read-only history: never counted in the 已停用 card.
        {"group": "INACTIVE", "label": "已停用", "count": 1, "has_overview_card": True},
    ]
    cards = [entry for entry in result["status_groups"] if entry["has_overview_card"]]
    assert [entry["group"] for entry in cards] == ["PENDING", "ACTIVE", "ATTENTION", "INACTIVE"]

    summary = result["summary"]
    # 全部 still contains the retired read-only archive record.
    assert summary["total"] == 8
    assert summary["inactive"] == 1
    assert summary["needs_attention"] == 2
    assert summary["active"] + summary["added_to_download"] == 2

    # A5: the published counts are the whole-library projection, not the query's
    # result count.  A search or a group filter must not move them.
    searched = client.get(
        "/api/v1/tracking/items",
        query_string={"storage_dir": "storage", "q": "追番中番"},
    ).get_json()["result"]
    assert searched["status_groups"] == result["status_groups"]
    assert len(searched["items"]) == 1
    filtered = client.get(
        "/api/v1/tracking/items",
        query_string={"storage_dir": "storage", "status_group": "ACTIVE"},
    ).get_json()["result"]
    assert filtered["status_groups"] == result["status_groups"]
    assert len(filtered["items"]) == 2


def test_external_only_history_is_read_only_and_only_visible_in_all(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    """#224 A4: real label, no card count/filter, no management actions."""
    record = _seed_external_only(tmp_path)

    all_result = client.get(
        "/api/v1/tracking/items", query_string={"storage_dir": "storage"}
    ).get_json()["result"]
    item = next(
        entry for entry in all_result["items"] if entry["tracking_id"] == record.tracking_id
    )
    assert item["status"] == TRACKING_STATUS_EXTERNAL_ONLY
    assert item["status_label"] == "仅外部"
    assert item["status_group"] == "INACTIVE"
    # Only 删除追番方案 / 复制并重新添加 remain page-level; no management action.
    assert item["available_actions"] == []
    assert all_result["summary"]["inactive"] == 0
    assert all_result["summary"]["total"] == 1
    inactive = next(
        entry for entry in all_result["status_groups"] if entry["group"] == "INACTIVE"
    )
    assert inactive["count"] == 0

    # A4: it stays visible only in 全部 — no group filter may return it.
    for group in ("PENDING", "PROCESSING", "ACTIVE", "ATTENTION", "INACTIVE"):
        filtered = client.get(
            "/api/v1/tracking/items",
            query_string={"storage_dir": "storage", "status_group": group},
        ).get_json()["result"]
        assert filtered["items"] == []
    # A plain search still runs over 全部, so the archive record stays findable.
    searched = client.get(
        "/api/v1/tracking/items",
        query_string={"storage_dir": "storage", "q": "历史外部订阅"},
    ).get_json()["result"]
    assert [entry["tracking_id"] for entry in searched["items"]] == [record.tracking_id]

    # The archive is loadable through the detail route too (AC3) with its real
    # label and no management action; the opaque external id never leaves.
    detail_response = client.get(
        f"/api/v1/tracking/items/{record.tracking_id}",
        query_string={"storage_dir": "storage"},
    )
    assert detail_response.status_code == 200
    detail = detail_response.get_json()["result"]
    assert detail["status"] == TRACKING_STATUS_EXTERNAL_ONLY
    assert detail["status_label"] == "仅外部"
    assert detail["status_group"] == "INACTIVE"
    assert detail["available_actions"] == []
    assert detail["safe_info"] is None
    detail_text = detail_response.get_data(as_text=True)
    for forbidden in ("sub-history-1", "legacy_3_1", str(tmp_path)):
        assert forbidden not in detail_text
    list_text = client.get(
        "/api/v1/tracking/items", query_string={"storage_dir": "storage"}
    ).get_data(as_text=True)
    assert "sub-history-1" not in list_text


def test_published_group_enum_matches_the_engine_order() -> None:
    """Issue #224 A7: the DTO can never quietly drift from the engine order."""
    from typing import get_args

    from apps.migu_orca_web.api_contract import TrackingStatusGroupDTO
    from tracking_engine.models.tracking import TRACKING_STATUS_GROUP_ORDER

    annotation = TrackingStatusGroupDTO.model_fields["group"].annotation
    assert get_args(annotation) == TRACKING_STATUS_GROUP_ORDER



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


# ---------------------------------------------------------------------------
# Cover references (issue #84)
# ---------------------------------------------------------------------------


def _poster_service(tmp_path: Path) -> MikanPosterService:
    return MikanPosterService(MikanPosterCacheConfig(cache_dir=tmp_path / "posters"))


def _accepted_request_with_cover(
    tmp_path: Path, request_id: str, poster_url: str | None
) -> dict[str, Any]:
    config = _config(tmp_path)
    request = accept_request(
        {
            **build_plan(EntryRequest(raw_title="芙莉莲"), data_source=StaticFixtureDataSource())["request"],
            "request_id": request_id,
        }
    )
    request["source_info"]["matched_bangumi"]["poster_url"] = poster_url
    save_request_snapshot(config, request)
    return request


def test_confirmed_plan_persists_a_same_origin_cover_across_restart(
    tmp_path: Path,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tracking_poster, "poster_service", _poster_service(tmp_path)
    )
    config = _config(tmp_path)
    upstream = "https://mikan.example/assets/cover.jpg?token=secret"
    request = _accepted_request_with_cover(tmp_path, "request-cover", upstream)

    handoff = ensure_confirmed_request_tracking(
        config=config,
        request=request,
        origin=TRACKING_ORIGIN_SAVE_CONFIRM,
    )
    assert handoff.tracking_ready is True

    # A restart re-reads only durable state; the same cover reference must come
    # back from the tracking summary and never the upstream address.
    response = client.get(
        f"/api/v1/tracking/items/{handoff.tracking_id}",
        query_string={"storage_dir": "storage"},
    )
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["result"]["poster_path"] == (
        f"/api/v1/mikan/posters/{poster_cache_key(upstream)}"
    )
    body_text = response.get_data(as_text=True)
    assert "mikan.example" not in body_text
    assert "token=secret" not in body_text


def test_confirmed_plan_without_a_cover_still_lists(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    config = _config(tmp_path)
    request = _accepted_request_with_cover(tmp_path, "request-no-cover", None)

    handoff = ensure_confirmed_request_tracking(
        config=config,
        request=request,
        origin=TRACKING_ORIGIN_SAVE_CONFIRM,
    )

    response = client.get("/api/v1/tracking/items", query_string={"storage_dir": "storage"})
    payload = response.get_json()
    assert response.status_code == 200
    item = payload["result"]["items"][0]
    assert item["tracking_id"] == handoff.tracking_id
    assert item["poster_path"] is None


@pytest.mark.parametrize(
    ("unsafe", "request_id"),
    [
        ("https://mikan.example/assets/cover.jpg", "request-unsafe-url"),
        ("/etc/passwd", "request-unsafe-path"),
        ("/api/v1/mikan/posters/../escape", "request-unsafe-traversal"),
    ],
)
def test_tracking_summary_drops_an_unsafe_cover_reference(
    tmp_path: Path,
    client: FlaskClient,
    unsafe: str,
    request_id: str,
) -> None:
    config = _config(tmp_path)
    record = create_tracking_record(
        request_id=request_id,
        status=TRACKING_STATUS_PENDING_SUBMIT,
        plan_summary={"title": "葬送的芙莉莲", "poster_path": unsafe},
        origin=TRACKING_ORIGIN_SAVE_CONFIRM,
        audit_action=TRACKING_AUDIT_TRACKING_CREATED,
        audit_actor=TRACKING_AUDIT_ACTOR_USER,
    )
    ensure_tracking_record(config, record)

    response = client.get("/api/v1/tracking/items", query_string={"storage_dir": "storage"})
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["result"]["items"][0]["poster_path"] is None
    assert unsafe not in response.get_data(as_text=True)
