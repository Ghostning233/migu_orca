from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from shared.errors import Stage1Error
from storage_engine.controllers.storage_config import (
    StorageConfig,
    ensure_storage_layout,
)


def save_request_snapshot(
    config: StorageConfig,
    request: dict[str, Any],
) -> dict[str, Any]:
    request_id = _extract_request_id(request, "save_request_snapshot")
    request_path = _request_path(config, request_id, "save_request_snapshot")
    ensure_storage_layout(config)

    try:
        request_path.write_text(
            json.dumps(request, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise Stage1Error(
            "storage_error",
            "保存 Request JSON 失败",
            "save_request_snapshot",
            {"request_id": request_id, "directory": config.requests_dir.name},
        ) from exc

    return {
        "request_id": request_id,
        "storage": "local_json",
        "directory": config.requests_dir.name,
        "filename": request_path.name,
    }


def load_request_snapshot(
    config: StorageConfig,
    request_id: str,
) -> dict[str, Any]:
    request_path = _request_path(config, request_id, "load_request_snapshot")
    if not request_path.exists():
        raise Stage1Error(
            "request_not_found",
            "未找到已保存的 Request",
            "load_request_snapshot",
            {"request_id": request_id},
        )

    try:
        loaded = json.loads(request_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise Stage1Error(
            "storage_json_error",
            "读取 Request JSON 失败",
            "load_request_snapshot",
            {"request_id": request_id, "reason": exc.msg},
        ) from exc
    except OSError as exc:
        raise Stage1Error(
            "storage_error",
            "读取 Request JSON 失败",
            "load_request_snapshot",
            {"request_id": request_id, "directory": config.requests_dir.name},
        ) from exc

    if not isinstance(loaded, dict):
        raise Stage1Error(
            "storage_json_error",
            "Request JSON 必须是对象",
            "load_request_snapshot",
            {"request_id": request_id},
        )

    return deepcopy(loaded)


def _extract_request_id(request: dict[str, Any], failed_step: str) -> str:
    request_id = request.get("request_id")
    if not isinstance(request_id, str) or not request_id.strip():
        raise Stage1Error(
            "invalid_request_id",
            "Request 缺少有效 request_id",
            failed_step,
            {"field": "request_id"},
        )
    return request_id.strip()


def _request_path(
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

    requests_root = config.requests_dir.resolve(strict=False)
    candidate = (config.requests_dir / f"{clean_request_id}.json").resolve(
        strict=False
    )
    if not _is_relative_to(candidate, requests_root):
        raise Stage1Error(
            "invalid_request_id",
            "request_id 不能包含路径片段",
            failed_step,
            {"field": "request_id"},
        )
    return candidate


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
