from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shared.errors import Stage1Error
from storage_engine.controllers.request_repository import _extract_request_id
from storage_engine.controllers.storage_config import (
    StorageConfig,
    ensure_storage_layout,
)
from storage_engine.controllers.storage_primitives import is_relative_to


def append_status_history(
    config: StorageConfig,
    event: dict[str, Any],
) -> dict[str, Any]:
    request_id = _extract_request_id(event, "append_status_history")
    history_path = _history_path(config, request_id, "append_status_history")
    ensure_storage_layout(config)

    history = _load_existing_history(history_path, request_id)
    history.append(event)

    try:
        history_path.write_text(
            json.dumps(history, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise Stage1Error(
            "storage_error",
            "保存订阅方案状态历史失败",
            "append_status_history",
            {"request_id": request_id, "directory": config.history_dir.name},
        ) from exc

    return {
        "request_id": request_id,
        "storage": "local_json",
        "directory": config.history_dir.name,
        "filename": history_path.name,
        "event_count": len(history),
    }


def load_status_history(config: StorageConfig, request_id: str) -> list[dict[str, Any]]:
    history_path = _history_path(config, request_id, "load_status_history")
    return _load_history_file(history_path, request_id, "load_status_history")


def _load_existing_history(history_path: Path, request_id: str) -> list[dict[str, Any]]:
    return _load_history_file(history_path, request_id, "append_status_history")


def _load_history_file(
    history_path: Path,
    request_id: str,
    failed_step: str,
) -> list[dict[str, Any]]:
    if not history_path.exists():
        return []

    try:
        loaded = json.loads(history_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise Stage1Error(
            "storage_json_error",
            "读取订阅方案状态历史失败",
            failed_step,
            {"request_id": request_id, "reason": exc.msg},
        ) from exc
    except OSError as exc:
        raise Stage1Error(
            "storage_error",
            "读取订阅方案状态历史失败",
            failed_step,
            {"request_id": request_id, "directory": "history"},
        ) from exc

    if not isinstance(loaded, list) or not all(
        isinstance(item, dict) for item in loaded
    ):
        raise Stage1Error(
            "storage_json_error",
            "订阅方案状态历史 JSON 必须是对象数组",
            failed_step,
            {"request_id": request_id},
        )
    return loaded


def _history_path(
    config: StorageConfig,
    request_id: str,
    failed_step: str,
) -> Path:
    if not isinstance(request_id, str) or not request_id.strip():
        raise Stage1Error(
            "invalid_request_id",
            "request_id 不能为空",
            failed_step,
            {"field": "request_id"},
        )

    clean_request_id = request_id.strip()
    if Path(clean_request_id).name != clean_request_id or "\\" in clean_request_id:
        raise Stage1Error(
            "invalid_request_id",
            "request_id 不能包含路径片段",
            failed_step,
            {"field": "request_id"},
        )

    history_root = config.history_dir.resolve(strict=False)
    candidate = (config.history_dir / f"{clean_request_id}.json").resolve(
        strict=False
    )
    if not is_relative_to(candidate, history_root):
        raise Stage1Error(
            "invalid_request_id",
            "request_id 不能包含路径片段",
            failed_step,
            {"field": "request_id"},
        )
    return candidate
