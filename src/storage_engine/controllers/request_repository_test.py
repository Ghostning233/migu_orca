from __future__ import annotations

from pathlib import Path

import pytest

from apps.migu_orca_entry.controllers.entry_controller import generate_request
from shared.errors import Stage1Error
from shared.models import EntryRequest
from storage_engine.controllers.request_repository import (
    list_request_snapshots,
    load_request_snapshot,
    save_request_snapshot,
)
from storage_engine.controllers.storage_config import load_storage_config


def test_save_and_load_request_snapshot_preserves_request_fields(
    tmp_path: Path,
) -> None:
    config = load_storage_config(tmp_path / "migu-state")
    request = generate_request(EntryRequest(raw_title="芙莉莲"))["request"]

    saved = save_request_snapshot(config, request)
    loaded = load_request_snapshot(config, request["request_id"])

    assert saved == {
        "request_id": request["request_id"],
        "storage": "local_json",
        "directory": "requests",
        "filename": f"{request['request_id']}.json",
    }
    assert loaded == request
    assert loaded is not request
    assert set(loaded) == set(request)


def test_list_request_snapshots_returns_saved_requests_in_filename_order(
    tmp_path: Path,
) -> None:
    config = load_storage_config(tmp_path / "migu-state")
    request_a = {
        **generate_request(EntryRequest(raw_title="芙莉莲"))["request"],
        "request_id": "request-b",
    }
    request_b = {
        **generate_request(EntryRequest(raw_title="咒术回战第三季"))["request"],
        "request_id": "request-a",
    }
    save_request_snapshot(config, request_a)
    save_request_snapshot(config, request_b)

    snapshots = list_request_snapshots(config)

    assert [request["request_id"] for request in snapshots] == [
        "request-a",
        "request-b",
    ]
    assert snapshots[0] == request_b
    assert snapshots[1] == request_a
    assert snapshots[0] is not request_b


def test_list_request_snapshots_returns_empty_for_missing_storage_dir(
    tmp_path: Path,
) -> None:
    config = load_storage_config(tmp_path / "migu-state")

    assert list_request_snapshots(config) == []


def test_save_request_snapshot_rejects_path_traversal_request_id(
    tmp_path: Path,
) -> None:
    config = load_storage_config(tmp_path / "migu-state")
    request = {
        "request_id": "../outside",
        "status": "PENDING_CONFIRM",
    }

    with pytest.raises(Stage1Error) as error:
        save_request_snapshot(config, request)

    assert error.value.as_dict() == {
        "error_type": "invalid_request_id",
        "error_message": "request_id 不能包含路径片段",
        "failed_step": "save_request_snapshot",
        "details": {"field": "request_id"},
    }
    assert not (tmp_path / "outside.json").exists()


def test_load_request_snapshot_rejects_nested_request_id(
    tmp_path: Path,
) -> None:
    config = load_storage_config(tmp_path / "migu-state")

    with pytest.raises(Stage1Error) as error:
        load_request_snapshot(config, "nested/request")

    assert error.value.error_type == "invalid_request_id"
    assert error.value.failed_step == "load_request_snapshot"


def test_load_request_snapshot_returns_stable_error_for_missing_request(
    tmp_path: Path,
) -> None:
    config = load_storage_config(tmp_path / "migu-state")

    with pytest.raises(Stage1Error) as error:
        load_request_snapshot(config, "missing-request")

    assert error.value.as_dict() == {
        "error_type": "request_not_found",
        "error_message": "未找到已保存的 Request",
        "failed_step": "load_request_snapshot",
        "details": {"request_id": "missing-request"},
    }


def test_load_request_snapshot_returns_stable_error_for_invalid_json(
    tmp_path: Path,
) -> None:
    config = load_storage_config(tmp_path / "migu-state")
    config.requests_dir.mkdir(parents=True)
    (config.requests_dir / "broken.json").write_text("{", encoding="utf-8")

    with pytest.raises(Stage1Error) as error:
        load_request_snapshot(config, "broken")

    error_dict = error.value.as_dict()
    assert error_dict["error_type"] == "storage_json_error"
    assert error_dict["failed_step"] == "load_request_snapshot"
    assert error_dict["details"]["request_id"] == "broken"
    assert str(tmp_path) not in str(error_dict)


def test_load_request_snapshot_rejects_non_object_json(tmp_path: Path) -> None:
    config = load_storage_config(tmp_path / "migu-state")
    config.requests_dir.mkdir(parents=True)
    (config.requests_dir / "array.json").write_text("[]", encoding="utf-8")

    with pytest.raises(Stage1Error) as error:
        load_request_snapshot(config, "array")

    assert error.value.as_dict() == {
        "error_type": "storage_json_error",
        "error_message": "Request JSON 必须是对象",
        "failed_step": "load_request_snapshot",
        "details": {"request_id": "array"},
    }


def test_save_request_snapshot_returns_stable_error_for_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_storage_config(tmp_path / "migu-state")
    request = generate_request(EntryRequest(raw_title="芙莉莲"))["request"]

    def fail_write_text(
        self: Path,
        data: str,
        *,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        raise OSError("permission denied: /sensitive/path")

    monkeypatch.setattr(Path, "write_text", fail_write_text)

    with pytest.raises(Stage1Error) as error:
        save_request_snapshot(config, request)

    assert error.value.as_dict() == {
        "error_type": "storage_error",
        "error_message": "保存 Request JSON 失败",
        "failed_step": "save_request_snapshot",
        "details": {
            "request_id": request["request_id"],
            "directory": "requests",
        },
    }
    assert str(tmp_path) not in str(error.value.as_dict())
