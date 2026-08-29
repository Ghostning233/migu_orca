from __future__ import annotations

"""US-189 golden contracts for every /api/v1 endpoint family.

These tests freeze the *current* behavior (success envelope, validation-failure
envelope, business-failure envelope, sanitized-error envelope) so later Stage 26
work (US-190 DTO/OpenAPI, US-191 route split, US-192 HTTP status) cannot
silently change what old pages depend on. Every test uses only fakes and
``tmp_path`` storage — no real MiKan, AutoBangumi or qBittorrent access.
"""

from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient

from ab_engine.controllers.ab_client import FakeAutoBangumiClient
from apps.migu_orca_entry.controllers.entry_controller import generate_request
from batch_engine.models import (
    BATCH_ITEM_STATUS_EMPTY,
    BATCH_ITEM_STATUS_FAILED,
    BATCH_ITEM_STATUS_FOUND,
)
from mikan_engine.controllers.mikan_client import create_mikan_client
from mikan_engine.controllers.mikan_config import MikanConfig
from request_engine.controllers.request_controller import summarize_request
from shared.errors import Stage1Error
from shared.models import EntryRequest
from tests.api_contract.conftest import saved_request


def _generated_request(title: str) -> dict[str, Any]:
    return generate_request(EntryRequest(raw_title=title))["request"]


class _FakeMikanTransport:
    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self.responses = responses or {}
        self.requests: list[str] = []

    def get_text(self, url: str, *, timeout: float) -> str:
        self.requests.append(url)
        return self.responses[url]


def _fake_mikan_search(monkeypatch: pytest.MonkeyPatch) -> _FakeMikanTransport:
    transport = _FakeMikanTransport(
        {
            "https://mikan.example/Home/Search?searchstr=%E8%8A%99%E8%8E%89%E8%8E%B2": (
                '<section class="related-recommendations">'
                '<div class="bangumi-item">'
                '<a class="an-text" href="/Home/Bangumi/2353">葬送的芙莉莲</a>'
                "</div>"
                "</section>"
            )
        }
    )

    def fake_create(config: MikanConfig) -> Any:
        return create_mikan_client(config, transport=transport)

    monkeypatch.setattr(
        "apps.migu_orca_web.services.mikan_client_module.create_mikan_client",
        fake_create,
    )
    return transport


# ---------------------------------------------------------------------------
# Requests family
# ---------------------------------------------------------------------------


def test_golden_request_list_success(client: FlaskClient, tmp_path: Path) -> None:
    saved_request(tmp_path, "芙莉莲", "request-1")

    response = client.get(
        "/api/v1/requests", query_string={"storage_dir": str(tmp_path / "storage")}
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["requests"][0]["request_id"] == "request-1"
    # The summary is the frozen public shape.
    assert set(payload["result"]["requests"][0]) == {
        "request_id",
        "status",
        "bangumi_title",
        "candidate_subtitle_groups",
        "selected_subtitle_group",
        "effective_seed_count",
        "expected_folder_name",
        "warnings",
    }


def test_golden_request_detail_success(client: FlaskClient, tmp_path: Path) -> None:
    saved_request(tmp_path, "芙莉莲", "request-1")

    response = client.get(
        "/api/v1/requests/request-1",
        query_string={"storage_dir": str(tmp_path / "storage")},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert set(payload["result"]) == {"request", "history", "ab_result"}
    assert set(payload["result"]["history"]) == {"available", "events", "error"}
    assert set(payload["result"]["ab_result"]) == {"available", "record", "error"}


def test_golden_request_create_success(client: FlaskClient, tmp_path: Path) -> None:
    response = client.post(
        "/api/v1/requests",
        json={
            "title": "芙莉莲",
            "storage_dir": str(tmp_path / "storage"),
            "save_request": False,
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert set(payload["result"]) == {"request", "summary"}
    assert payload["result"]["request"]["input"]["raw_title"] == "芙莉莲"
    assert payload["result"]["request"]["status"] == "PENDING_CONFIRM"
    assert payload["result"]["summary"] == summarize_request(
        payload["result"]["request"]
    )
    # Preview generation never writes storage unless save_request=true.
    assert not (tmp_path / "storage").exists()


def test_golden_request_create_validation_failure(client: FlaskClient) -> None:
    response = client.post("/api/v1/requests", json={})

    payload = response.get_json()
    assert response.status_code == 200
    assert payload == {
        "ok": False,
        "error_type": "data_validation_errors",
        "error_message": "Data has validation errors",
        "error_data": {
            "errors": [
                {
                    "error_type": "validation_error",
                    "field": "title",
                    "message": "Field required",
                }
            ]
        },
    }


def test_golden_request_detail_business_failure(client: FlaskClient) -> None:
    response = client.get("/api/v1/requests/missing-request")

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "request_not_found"
    assert payload["error_message"] == "未找到已保存的订阅方案"
    assert payload["error_data"]["failed_step"] == "load_request_snapshot"
    assert payload["error_data"]["details"] == {"request_id": "missing-request"}


def test_golden_preview_modify_rejects_illegal_patch(client: FlaskClient) -> None:
    response = client.post(
        "/api/v1/requests/preview-modify",
        json={
            "request": {"status": "PENDING_CONFIRM", "input": {"raw_title": "x"}},
            "patch": {"bogus_field": 1},
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "invalid_modify_patch_field"
    assert payload["error_data"]["details"]["illegal_fields"] == ["bogus_field"]
    assert payload["error_data"]["details"]["allowed_fields"] == [
        "expected_folder_name",
        "filter_rule",
        "selected_subtitle_group",
    ]


def test_golden_preview_save_rejects_non_pending(client: FlaskClient) -> None:
    response = client.post(
        "/api/v1/requests/preview-save",
        json={"request": {"status": "ACCEPTED"}},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "invalid_request_status"
    assert payload["error_message"] == "只有待确认的订阅草案可以保存"
    assert payload["error_data"]["details"] == {"status": "ACCEPTED"}


def test_golden_request_actions_error_sanitized(
    client: FlaskClient, tmp_path: Path
) -> None:
    """A failed storage write must never leak absolute paths or tokens."""
    response = client.post(
        "/api/v1/requests/request-1/accept",
        json={"storage_dir": str(tmp_path / "storage")},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "request_not_found"
    serialized = str(payload)
    assert str(tmp_path) not in serialized


def test_golden_delete_success_shape(client: FlaskClient, tmp_path: Path) -> None:
    saved_request(tmp_path, "芙莉莲", "request-1")

    response = client.post(
        "/api/v1/requests/request-1/delete",
        json={"storage_dir": str(tmp_path / "storage")},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload == {
        "ok": True,
        "result": {
            "request_id": "request-1",
            "storage": "local_json",
            "directory": "requests",
            "filename": "request-1.json",
            "deleted": True,
        },
    }


def test_golden_request_create_does_not_trust_client_aliases(
    client: FlaskClient,
) -> None:
    """candidate_context must be a one-time server-issued token (US-185).

    A forged client-supplied context token must never be treated as season
    evidence. Static-fixture generation is used so no external transport is
    touched: the view consumes the token against the (empty) server-side store
    and rejects it because it was never issued by a candidate search.
    """
    response = client.post(
        "/api/v1/requests",
        json={
            "title": "芙莉莲",
            "candidate_context": "forged-client-token",
            "season_confirmation": 1,
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "candidate_context_invalid"
    assert payload["error_message"] == "候选上下文已失效，请重新搜索并选择合集"
    assert payload["error_data"]["details"] == {"field": "candidate_context"}


# ---------------------------------------------------------------------------
# MiKan family
# ---------------------------------------------------------------------------


def test_golden_mikan_candidates_success(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_mikan_search(monkeypatch)

    response = client.post(
        "/api/v1/mikan/candidates",
        json={
            "query": "芙莉莲",
            "mikan_config": {
                "search_endpoint": "https://mikan.example/Home/Search",
                "timeout_seconds": 5,
            },
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    result = payload["result"]
    assert set(result) >= {"query", "status", "parse_result", "attempted_queries", "candidates"}
    assert result["status"] == BATCH_ITEM_STATUS_FOUND
    assert result["candidates"][0]["bangumi_id"] == "2353"
    # Only the public candidate whitelist is exposed.
    assert set(result["candidates"][0]) <= {
        "bangumi_id",
        "title",
        "mikan_url",
        "poster_url",
        "source_query",
        "aliases",
        "recommendation",
        "total_episodes",
        "season_evidence",
        "candidate_context",
    }


def test_golden_mikan_candidates_validation_failure(client: FlaskClient) -> None:
    response = client.post("/api/v1/mikan/candidates", json={"query": "   "})

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert any(e["field"] == "query" for e in payload["error_data"]["errors"])


def test_golden_mikan_candidates_business_failure_sanitized(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_search(query: str, mikan_config: MikanConfig) -> list[dict[str, Any]]:
        raise Stage1Error(
            "mikan_http_failed",
            "MiKan HTTP 请求失败",
            "mikan_search",
            {"url": "https://private.example/search?token=secret"},
        )

    monkeypatch.setattr(
        "apps.migu_orca_web.routes_mikan._search_candidates_from_parse_result",
        fail_search,
    )

    response = client.post(
        "/api/v1/mikan/candidates",
        json={"query": "芙莉莲"},
    )

    payload = response.get_json()
    serialized = str(payload)
    assert "private.example" not in serialized
    assert "secret" not in serialized
    assert "https://" not in serialized


# ---------------------------------------------------------------------------
# Batches family
# ---------------------------------------------------------------------------


def test_golden_batch_parse_success(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches._search_batch_item_candidates",
        lambda queries, config: [],
    )

    response = client.post(
        "/api/v1/batches/parse",
        json={"raw_input": "萌王S4\n路哥S4"},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    result = payload["result"]
    assert set(result) == {"batch_id", "raw_input", "items"}
    assert result["batch_id"].startswith("batch-")
    assert [item["raw_title"] for item in result["items"]] == ["萌王S4", "路哥S4"]
    assert all(item["item_id"].startswith("item-") for item in result["items"])
    assert all(item["status"] == BATCH_ITEM_STATUS_EMPTY for item in result["items"])


def test_golden_batch_parse_validation_failure(client: FlaskClient) -> None:
    response = client.post("/api/v1/batches/parse", json={"raw_input": "\n \t\n"})

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_message"] == "请至少输入一个番剧名称"
    assert payload["error_data"]["details"] == {"field": "raw_input"}


def test_golden_batch_parse_failed_item_error_sanitized(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_search(queries: list[str], config: Any) -> list[dict[str, Any]]:
        raise Stage1Error(
            "mikan_http_failed",
            "MiKan HTTP 请求失败",
            "mikan_search",
            {"url": "https://private.example/search?token=secret"},
        )

    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches._search_batch_item_candidates",
        fail_search,
    )

    response = client.post(
        "/api/v1/batches/parse",
        json={"raw_input": "萌王S4"},
    )

    payload = response.get_json()
    serialized = str(payload)
    assert "private.example" not in serialized
    assert "secret" not in serialized
    item = payload["result"]["items"][0]
    assert item["status"] == BATCH_ITEM_STATUS_FAILED
    assert item["error"]["error_type"] == "mikan_http_failed"


def test_golden_batch_queue_read_success(client: FlaskClient, tmp_path: Path) -> None:
    response = client.get(
        "/api/v1/batches/nonexistent/queue",
        query_string={"storage_dir": str(tmp_path / "storage")},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload == {
        "ok": True,
        "result": {"batch_id": "nonexistent", "queue": None},
    }


def test_golden_batch_accept_reports_unacceptable_item(
    client: FlaskClient, tmp_path: Path
) -> None:
    response = client.post(
        "/api/v1/batches/batch-1/accept",
        json={
            "batch_id": "batch-1",
            "items": [
                {
                    "item_id": "item-1",
                    "request_id": "missing-request",
                    "title": "示例标题",
                }
            ],
            "storage_dir": str(tmp_path / "storage"),
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    item = payload["result"]["items"][0]
    assert item["status"] == "unacceptable"
    assert item["queued"] is False
    assert item["reason"] == "订阅方案不存在或已删除"
    # The queue is persisted with non-sensitive fields only.
    assert payload["result"]["queue"]["items"] == []


def test_golden_batch_submit_requires_ab_config(client: FlaskClient) -> None:
    response = client.post(
        "/api/v1/batches/batch-1/submit",
        json={"batch_id": "batch-1"},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_message"] == "请提供 Auto Bangumi 配置"
    assert payload["error_data"]["details"] == {"field": "ab_config"}


def test_golden_batch_submit_requires_confirmation(client: FlaskClient) -> None:
    response = client.post(
        "/api/v1/batches/batch-1/submit",
        json={
            "batch_id": "batch-1",
            "ab_config": {
                "auth_mode": "api_token",
                "base_url": "http://ab.example",
                "token": "secret-token",
                "fallback_enabled": False,
            },
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_message"] == "请确认提交到 Auto Bangumi"
    assert "secret-token" not in str(payload)


def test_golden_batch_recover_rejects_bad_action(client: FlaskClient) -> None:
    response = client.post(
        "/api/v1/batches/batch-1/recover",
        json={"batch_id": "batch-1", "request_id": "request-1", "action": "bogus"},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_message"] == "恢复动作必须是 auto、succeeded 或 failed"


def test_golden_batch_retry_unknown_item(client: FlaskClient) -> None:
    response = client.post(
        "/api/v1/batches/batch-1/retry",
        json={
            "batch_id": "batch-1",
            "request_id": "missing-request",
            "ab_config": {
                "auth_mode": "api_token",
                "base_url": "http://ab.example",
                "token": "secret-token",
                "fallback_enabled": False,
            },
            "confirm": True,
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "queue_not_found"
    assert payload["error_message"] == "未找到该批次的提交队列"
    assert payload["error_data"]["details"] == {"batch_id": "batch-1"}
    assert "secret-token" not in str(payload)


# ---------------------------------------------------------------------------
# Preferences / Corrections family
# ---------------------------------------------------------------------------


def test_golden_preferences_read_defaults(client: FlaskClient, tmp_path: Path) -> None:
    response = client.get(
        "/api/v1/preferences",
        query_string={"storage_dir": str(tmp_path / "storage")},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"] == {
        "version": 1,
        "subtitle_groups": {
            "preferred": [],
            "excluded": [],
            "fallback": "next_preferred",
        },
        "filter_defaults": {
            "must_contain": "",
            "must_not_contain": "",
            "use_regex": False,
            "case_sensitive": False,
        },
        "naming": {"strategy": "official_title_season", "template": "{title}"},
        "search": {"reuse_explicit_corrections": True},
    }


def test_golden_preferences_save_missing(client: FlaskClient) -> None:
    response = client.post("/api/v1/preferences", json={})

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_message"] == "请提供偏好配置"
    assert payload["error_data"]["details"] == {"field": "preferences"}


def test_golden_preferences_save_rejects_sensitive_value(
    client: FlaskClient, tmp_path: Path
) -> None:
    response = client.post(
        "/api/v1/preferences",
        json={
            "storage_dir": str(tmp_path / "storage"),
            "preferences": {
                "subtitle_groups": {"preferred": ["https://secret.example"]}
            },
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert "https://" not in str(payload)
    assert "secret.example" not in str(payload)


def test_golden_corrections_read_empty(client: FlaskClient, tmp_path: Path) -> None:
    response = client.get(
        "/api/v1/corrections",
        query_string={"storage_dir": str(tmp_path / "storage")},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload == {"ok": True, "result": {"corrections": []}}


def test_golden_corrections_save_missing(client: FlaskClient) -> None:
    response = client.post("/api/v1/corrections", json={})

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_message"] == "请提供修正内容"
    assert payload["error_data"]["details"] == {"field": "correction"}


# ---------------------------------------------------------------------------
# Connection tests family
# ---------------------------------------------------------------------------


def test_golden_qbittorrent_connection_success_whitelist(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_test(*, qbittorrent_config: Any) -> dict[str, Any]:
        return {
            "success": True,
            "summary": {
                "status": "connected",
                "reachable": True,
                "version": "v4.6.7",
                "endpoint": "http://private.example:8080",
                "username": "private-user",
                "password": "private-password",
                "cookie": "SID=secret-session",
            },
            "error": None,
        }

    monkeypatch.setattr(
        "apps.migu_orca_web.routes_connections.test_qbittorrent_connection", fake_test
    )
    response = client.post(
        "/api/v1/qbittorrent/test-connection",
        json={
            "qbittorrent_config": {
                "endpoint": "http://private.example:8080",
                "username": "private-user",
                "password": "private-password",
                "timeout_seconds": 7,
                "verify_tls": False,
            }
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    # Only the whitelist survives; credentials never appear.
    assert payload == {
        "ok": True,
        "result": {"status": "connected", "reachable": True, "version": "v4.6.7"},
    }
    serialized = str(payload)
    assert "private" not in serialized
    assert "secret" not in serialized


def test_golden_qbittorrent_connection_validation_failure(
    client: FlaskClient,
) -> None:
    response = client.post("/api/v1/qbittorrent/test-connection", json={})

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert any(
        e["field"] == "qbittorrent_config"
        for e in payload["error_data"]["errors"]
    )


def test_golden_ab_connection_success_whitelist(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_test(*, ab_config: Any) -> dict[str, Any]:
        return {
            "success": True,
            "summary": {
                "reachable": True,
                "authenticated": True,
                "version": "3.1.18",
                "auth_mode": "账号密码",
                "adapter": "legacy_3_1",
                "submit_supported": True,
                "base_url": "http://private-ab.example",
                "token": "secret-token",
            },
            "error": None,
        }

    monkeypatch.setattr("apps.migu_orca_web.routes_connections.test_ab_connection", fake_test)
    response = client.post(
        "/api/v1/autobangumi/test-connection",
        json={
            "ab_config": {
                "auth_mode": "password",
                "base_url": "http://private-ab.example",
                "username": "private-user",
                "password": "private-password",
                "fallback_enabled": False,
            }
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload == {
        "ok": True,
        "result": {
            "reachable": True,
            "authenticated": True,
            "version": "3.1.18",
            "auth_mode": "账号密码",
            "adapter": "legacy_3_1",
            "submit_supported": True,
        },
    }
    serialized = str(payload)
    assert "private" not in serialized
    assert "secret" not in serialized


def test_golden_ab_connection_validation_failure(client: FlaskClient) -> None:
    response = client.post("/api/v1/autobangumi/test-connection", json={})

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert any(e["field"] == "ab_config" for e in payload["error_data"]["errors"])


# ---------------------------------------------------------------------------
# submit-ab family
# ---------------------------------------------------------------------------


def test_golden_submit_ab_rejects_non_accepted(
    client: FlaskClient, tmp_path: Path
) -> None:
    saved_request(tmp_path, "芙莉莲", "request-1")

    response = client.post(
        "/api/v1/requests/request-1/submit-ab",
        json={
            "storage_dir": str(tmp_path / "storage"),
            "ab_config": {
                "auth_mode": "api_token",
                "base_url": "http://private-ab.example",
                "token": "secret-token",
                "fallback_enabled": False,
            },
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "invalid_request_status"
    assert payload["error_message"] == "只有已确认订阅方案可以提交到 Auto Bangumi"
    serialized = str(payload)
    assert "secret-token" not in serialized
    assert "private-ab.example" not in serialized


def test_golden_submit_ab_success_sanitizes_ab_result(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from request_engine.controllers.request_controller import accept_request
    from storage_engine.controllers.request_repository import save_request_snapshot
    from storage_engine.controllers.storage_config import load_storage_config

    request = accept_request(
        {
            **_generated_request("芙莉莲"),
            "request_id": "request-1",
        }
    )
    save_request_snapshot(load_storage_config(tmp_path / "storage"), request)

    fake_client = FakeAutoBangumiClient(
        response={
            "id": "fake-ab-subscription",
            "status": "created",
            "token": "leaked-internal",
            "cookie": "SID=leaked",
        }
    )

    def build_client(ab_config: Any) -> FakeAutoBangumiClient:
        return fake_client

    monkeypatch.setattr(
        "apps.migu_orca_entry.controllers.entry_controller.ab_http_client.create_auto_bangumi_http_client",
        build_client,
    )

    response = client.post(
        "/api/v1/requests/request-1/submit-ab",
        json={
            "storage_dir": str(tmp_path / "storage"),
            "ab_config": {
                "auth_mode": "api_token",
                "base_url": "http://private-ab.example",
                "token": "secret-token",
                "fallback_enabled": False,
            },
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    result = payload["result"]
    assert result["request"]["status"] == "ACCEPTED"
    assert result["ab_submit_result"]["success"] is True
    serialized = str(payload)
    assert "leaked-internal" not in serialized
    assert "SID=leaked" not in serialized
    assert "secret-token" not in serialized
    assert "private-ab.example" not in serialized
