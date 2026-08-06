from __future__ import annotations

from pathlib import Path
from typing import Any

from flask.testing import FlaskClient
import pytest

from apps.base import create_app
from apps.migu_orca_entry.controllers.entry_controller import generate_request
from request_engine.controllers.request_controller import summarize_request
from shared.errors import Stage1Error
from shared.models import EntryRequest
from storage_engine.controllers.request_repository import save_request_snapshot
from storage_engine.controllers.storage_config import load_storage_config


def _client() -> FlaskClient:
    return create_app("testing").test_client()


def _saved_request(tmp_path: Path, title: str, request_id: str) -> dict[str, Any]:
    request = {
        **generate_request(EntryRequest(raw_title=title))["request"],
        "request_id": request_id,
    }
    save_request_snapshot(load_storage_config(tmp_path / "storage"), request)
    return request


def test_root_redirects_to_index() -> None:
    response = _client().get("/")

    assert response.status_code == 302
    assert response.headers["Location"] == "/index"


def test_index_serves_web_ui_shell() -> None:
    response = _client().get("/index")

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "text/html" in response.content_type
    assert "MiGuOrca" in html
    assert "Stage 7 Web UI MVP" in html
    assert "Request 生成" in html
    assert "Request 列表" in html
    assert "Request 详情" in html
    assert 'id="request-generate-form"' in html
    assert 'name="title"' in html
    assert 'name="storage_dir"' in html
    assert 'name="save_request"' in html
    assert 'id="request-list-container"' in html
    assert 'id="request-detail-container"' in html
    assert "token" not in html.lower()
    assert "http://" not in html
    assert "https://" not in html
    assert "<rss" not in html.lower()


def test_list_requests_returns_empty_list_for_missing_storage_dir(
    tmp_path: Path,
) -> None:
    response = _client().get(
        "/api/v1/requests",
        query_string={"storage_dir": str(tmp_path / "missing-storage")},
    )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "result": {"requests": []}}


def test_list_requests_returns_saved_request_summaries(tmp_path: Path) -> None:
    request_b = _saved_request(tmp_path, "芙莉莲", "request-b")
    request_a = _saved_request(tmp_path, "咒术回战第三季", "request-a")

    response = _client().get(
        "/api/v1/requests",
        query_string={"storage_dir": str(tmp_path / "storage")},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "result": {
            "requests": [
                summarize_request(request_a),
                summarize_request(request_b),
            ]
        },
    }


def test_get_request_detail_returns_complete_saved_snapshot(tmp_path: Path) -> None:
    request = _saved_request(tmp_path, "芙莉莲", "request-1")

    response = _client().get(
        "/api/v1/requests/request-1",
        query_string={"storage_dir": str(tmp_path / "storage")},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "result": {"request": request},
    }


def test_get_request_detail_returns_unified_error_for_missing_request(
    tmp_path: Path,
) -> None:
    response = _client().get(
        "/api/v1/requests/missing-request",
        query_string={"storage_dir": str(tmp_path / "storage")},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload == {
        "ok": False,
        "error_type": "request_not_found",
        "error_message": "未找到已保存的 Request",
        "error_data": {
            "failed_step": "load_request_snapshot",
            "details": {"request_id": "missing-request"},
        },
    }
    assert str(tmp_path) not in str(payload)


def test_get_request_detail_rejects_path_fragments_without_leaking_storage_path(
    tmp_path: Path,
) -> None:
    response = _client().get(
        "/api/v1/requests/nested%2Frequest",
        query_string={"storage_dir": str(tmp_path / "storage")},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload == {
        "ok": False,
        "error_type": "invalid_request_id",
        "error_message": "request_id 不能包含路径片段",
        "error_data": {
            "failed_step": "load_request_snapshot",
            "details": {"field": "request_id"},
        },
    }
    assert str(tmp_path) not in str(payload)


def test_list_requests_returns_unified_error_for_damaged_snapshot(
    tmp_path: Path,
) -> None:
    config = load_storage_config(tmp_path / "storage")
    config.requests_dir.mkdir(parents=True)
    (config.requests_dir / "broken.json").write_text("{", encoding="utf-8")

    response = _client().get(
        "/api/v1/requests",
        query_string={"storage_dir": str(tmp_path / "storage")},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "storage_json_error"
    assert payload["error_data"]["failed_step"] == "load_request_snapshot"
    assert payload["error_data"]["details"]["request_id"] == "broken"
    assert str(tmp_path) not in str(payload)


def test_create_request_generates_without_writing_storage(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/requests",
        json={
            "title": "芙莉莲",
            "storage_dir": str(storage_dir),
            "save_request": False,
        },
    )

    payload = response.get_json()
    request = payload["result"]["request"]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert request["input"]["raw_title"] == "芙莉莲"
    assert payload["result"]["summary"] == summarize_request(request)
    assert "saved_request" not in payload["result"]
    assert not storage_dir.exists()


def test_create_request_saves_when_explicitly_requested(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/requests",
        json={
            "title": "芙莉莲",
            "storage_dir": str(storage_dir),
            "save_request": True,
        },
    )

    payload = response.get_json()
    saved_request = payload["result"]["saved_request"]
    saved_path = storage_dir / "requests" / saved_request["filename"]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert saved_request == {
        "request_id": payload["result"]["request"]["request_id"],
        "storage": "local_json",
        "directory": "requests",
        "filename": f"{payload['result']['request']['request_id']}.json",
    }
    assert saved_path.exists()


def test_create_request_returns_validation_error_for_missing_title() -> None:
    response = _client().post(
        "/api/v1/requests",
        json={"save_request": False},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert payload["error_data"]["errors"][0]["field"] == "title"


def test_create_request_returns_validation_error_for_blank_title() -> None:
    response = _client().post(
        "/api/v1/requests",
        json={"title": "   "},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert payload["error_data"]["errors"][0]["field"] == "title"


def test_create_request_returns_validation_error_for_invalid_storage_dir_type() -> None:
    response = _client().post(
        "/api/v1/requests",
        json={"title": "芙莉莲", "storage_dir": 123},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert payload["error_data"]["errors"][0]["field"] == "storage_dir"


def test_create_request_returns_unified_error_for_save_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_save(*args: object, **kwargs: object) -> dict[str, Any]:
        return {
            "success": False,
            "request": None,
            "error": Stage1Error(
                "storage_error",
                "保存 Request JSON 失败",
                "save_request_snapshot",
                {
                    "reason": f"cannot write {tmp_path}/private-token at https://example.test/api",
                    "directory": "requests",
                },
            ).as_dict(),
        }

    monkeypatch.setattr(
        "apps.migu_orca_web.views.apply_request_save_action",
        fail_save,
    )

    response = _client().post(
        "/api/v1/requests",
        json={
            "title": "芙莉莲",
            "storage_dir": str(tmp_path / "storage"),
            "save_request": True,
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "storage_error"
    assert payload["error_message"] == "保存 Request JSON 失败"
    assert payload["error_data"]["failed_step"] == "save_request_snapshot"
    assert payload["error_data"]["details"]["directory"] == "requests"
    assert str(tmp_path) not in str(payload)
    assert "https://example.test/api" not in str(payload)
    assert "token" not in str(payload).lower()
