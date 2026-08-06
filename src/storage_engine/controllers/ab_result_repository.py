from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from shared.errors import Stage1Error
from storage_engine.controllers.storage_config import (
    StorageConfig,
    ensure_storage_layout,
)


def save_ab_submit_result(
    config: StorageConfig,
    request: dict[str, Any],
) -> dict[str, Any]:
    request_id = _extract_request_id(request, "save_ab_submit_result")
    ab_submit_result = request.get("ab_submit_result")
    if not isinstance(ab_submit_result, dict):
        raise Stage1Error(
            "invalid_ab_submit_result",
            "Request 缺少有效 Auto Bangumi 提交结果",
            "save_ab_submit_result",
            {"request_id": request_id, "field": "ab_submit_result"},
        )

    result_path = _ab_result_path(config, request_id, "save_ab_submit_result")
    ensure_storage_layout(config)
    record = {
        "request_id": request_id,
        "recorded_at": datetime.now(UTC).isoformat(),
        "ab_submit_result": deepcopy(ab_submit_result),
    }

    try:
        result_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise Stage1Error(
            "storage_error",
            "保存 Auto Bangumi 提交结果失败",
            "save_ab_submit_result",
            {"request_id": request_id, "directory": config.ab_results_dir.name},
        ) from exc

    return {
        "request_id": request_id,
        "storage": "local_json",
        "directory": config.ab_results_dir.name,
        "filename": result_path.name,
    }


def load_ab_submit_result(
    config: StorageConfig,
    request_id: str,
) -> dict[str, Any]:
    result_path = _ab_result_path(config, request_id, "load_ab_submit_result")
    if not result_path.exists():
        raise Stage1Error(
            "ab_result_not_found",
            "未找到已保存的 Auto Bangumi 提交结果",
            "load_ab_submit_result",
            {"request_id": request_id},
        )

    try:
        loaded = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise Stage1Error(
            "storage_json_error",
            "读取 Auto Bangumi 提交结果 JSON 失败",
            "load_ab_submit_result",
            {"request_id": request_id, "reason": exc.msg},
        ) from exc
    except OSError as exc:
        raise Stage1Error(
            "storage_error",
            "读取 Auto Bangumi 提交结果 JSON 失败",
            "load_ab_submit_result",
            {"request_id": request_id, "directory": config.ab_results_dir.name},
        ) from exc

    if not isinstance(loaded, dict):
        raise Stage1Error(
            "storage_json_error",
            "Auto Bangumi 提交结果 JSON 必须是对象",
            "load_ab_submit_result",
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


def _ab_result_path(
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

    results_root = config.ab_results_dir.resolve(strict=False)
    candidate = (config.ab_results_dir / f"{clean_request_id}.json").resolve(
        strict=False
    )
    if not _is_relative_to(candidate, results_root):
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
