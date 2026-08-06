from __future__ import annotations

from pathlib import Path
from typing import Any

from flask.testing import FlaskClient

from apps.base import create_app
from apps.migu_orca_entry.controllers.entry_controller import generate_request
from request_engine.controllers.request_controller import summarize_request
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
