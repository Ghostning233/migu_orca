from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shared.errors import Stage1Error
from storage_engine.controllers.storage_config import (
    StorageConfig,
    ensure_storage_layout,
)
from storage_engine.controllers.storage_primitives import is_relative_to


@dataclass(frozen=True)
class AbResultListResult:
    """Healthy saved AB-result records plus opaque damaged request ids (US-221)."""

    records: tuple[dict[str, Any], ...]
    damaged_request_ids: tuple[str, ...]

    @property
    def unreadable_count(self) -> int:
        return len(self.damaged_request_ids)


def save_ab_submit_result(
    config: StorageConfig,
    request: dict[str, Any],
) -> dict[str, Any]:
    request_id = _extract_request_id(request, "save_ab_submit_result")
    ab_submit_result = request.get("ab_submit_result")
    if not isinstance(ab_submit_result, dict):
        raise Stage1Error(
            "invalid_ab_submit_result",
            "订阅方案缺少有效 Auto Bangumi 提交结果",
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


def list_ab_submit_results_tolerant(config: StorageConfig) -> AbResultListResult:
    """Return healthy saved AB-result records plus damaged request ids (US-221)."""
    if not config.ab_results_dir.exists():
        return AbResultListResult(records=(), damaged_request_ids=())
    if not config.ab_results_dir.is_dir():
        raise Stage1Error(
            "storage_error",
            "本地 Auto Bangumi 结果存储路径不是目录",
            "list_ab_submit_results_tolerant",
            {"directory": config.ab_results_dir.name},
        )

    records: list[dict[str, Any]] = []
    damaged: list[str] = []
    try:
        result_files = sorted(config.ab_results_dir.glob("*.json"))
    except OSError as exc:
        raise Stage1Error(
            "storage_error",
            "列出 Auto Bangumi 提交结果失败",
            "list_ab_submit_results_tolerant",
            {"directory": config.ab_results_dir.name},
        ) from exc

    for result_file in result_files:
        candidate_id = result_file.stem
        try:
            record = load_ab_submit_result(config, candidate_id)
        except Stage1Error:
            damaged.append(candidate_id)
            continue
        inner_id = record.get("request_id")
        if not isinstance(inner_id, str) or not inner_id.strip() or inner_id != candidate_id:
            damaged.append(candidate_id)
            continue
        records.append(record)
    return AbResultListResult(records=tuple(records), damaged_request_ids=tuple(damaged))


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
    if not is_relative_to(candidate, results_root):
        raise Stage1Error(
            "invalid_request_id",
            "request_id 不能包含路径片段",
            failed_step,
            {"field": "request_id"},
        )
    return candidate


