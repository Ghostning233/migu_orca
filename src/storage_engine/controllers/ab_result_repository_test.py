from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.errors import Stage1Error
from storage_engine.controllers.ab_result_repository import (
    load_ab_submit_result,
    save_ab_submit_result,
)
from storage_engine.controllers.storage_config import load_storage_config


def test_save_and_load_ab_submit_result_by_request_id(tmp_path: Path) -> None:
    config = load_storage_config(tmp_path / "migu-state")
    request = {
        "request_id": "request-123",
        "ab_submit_result": {
            "success": True,
            "ab_subscription_id": "sub-123",
            "ab_response": {"id": "sub-123", "status": "created"},
            "fallback_config": None,
            "error": None,
        },
    }

    saved = save_ab_submit_result(config, request)
    loaded = load_ab_submit_result(config, "request-123")

    assert saved == {
        "request_id": "request-123",
        "storage": "local_json",
        "directory": "ab_results",
        "filename": "request-123.json",
    }
    assert loaded["request_id"] == "request-123"
    assert loaded["ab_submit_result"] == request["ab_submit_result"]
    assert (config.ab_results_dir / "request-123.json").exists()


def test_save_ab_submit_result_rejects_path_fragments(tmp_path: Path) -> None:
    config = load_storage_config(tmp_path / "migu-state")

    with pytest.raises(Stage1Error) as error:
        save_ab_submit_result(
            config,
            {"request_id": "../escape", "ab_submit_result": {"success": True}},
        )

    assert error.value.error_type == "invalid_request_id"
    assert error.value.failed_step == "save_ab_submit_result"
    assert not (tmp_path / "escape.json").exists()


def test_save_ab_submit_result_requires_result_object(tmp_path: Path) -> None:
    config = load_storage_config(tmp_path / "migu-state")

    with pytest.raises(Stage1Error) as error:
        save_ab_submit_result(config, {"request_id": "request-123"})

    assert error.value.as_dict() == {
        "error_type": "invalid_ab_submit_result",
        "error_message": "Request 缺少有效 Auto Bangumi 提交结果",
        "failed_step": "save_ab_submit_result",
        "details": {"request_id": "request-123", "field": "ab_submit_result"},
    }


def test_load_ab_submit_result_returns_stable_missing_error(tmp_path: Path) -> None:
    config = load_storage_config(tmp_path / "migu-state")

    with pytest.raises(Stage1Error) as error:
        load_ab_submit_result(config, "missing-request")

    assert error.value.as_dict() == {
        "error_type": "ab_result_not_found",
        "error_message": "未找到已保存的 Auto Bangumi 提交结果",
        "failed_step": "load_ab_submit_result",
        "details": {"request_id": "missing-request"},
    }
    assert str(tmp_path) not in str(error.value.as_dict())


def test_load_ab_submit_result_returns_stable_json_error(tmp_path: Path) -> None:
    config = load_storage_config(tmp_path / "migu-state")
    config.ab_results_dir.mkdir(parents=True)
    (config.ab_results_dir / "broken.json").write_text("{", encoding="utf-8")

    with pytest.raises(Stage1Error) as error:
        load_ab_submit_result(config, "broken")

    assert error.value.error_type == "storage_json_error"
    assert error.value.failed_step == "load_ab_submit_result"
    assert error.value.details["request_id"] == "broken"
    assert str(tmp_path) not in str(error.value.as_dict())


def test_saved_ab_submit_result_is_defensively_copied(tmp_path: Path) -> None:
    config = load_storage_config(tmp_path / "migu-state")
    request = {
        "request_id": "request-123",
        "ab_submit_result": {"success": False, "fallback_config": {"title": "番剧"}},
    }

    save_ab_submit_result(config, request)
    request["ab_submit_result"]["fallback_config"]["title"] = "changed"

    saved_json = json.loads(
        (config.ab_results_dir / "request-123.json").read_text(encoding="utf-8")
    )
    assert saved_json["ab_submit_result"]["fallback_config"]["title"] == "番剧"
