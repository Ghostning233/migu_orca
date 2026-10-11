from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shared.errors import Stage1Error
from storage_engine.controllers.storage_config import (
    StorageConfig,
    ensure_storage_layout,
)
from storage_engine.controllers.storage_primitives import is_relative_to


@dataclass(frozen=True)
class RequestListResult:
    """Healthy Request snapshots plus the opaque ids of damaged files.

    Used by the migration runner (US-221) so one damaged snapshot never blocks
    migrating the healthy requests; the damaged ids are only counted/reported,
    never exposed as file paths or raw content.
    """

    requests: tuple[dict[str, Any], ...]
    damaged_request_ids: tuple[str, ...]

    @property
    def unreadable_count(self) -> int:
        return len(self.damaged_request_ids)


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
            "保存订阅方案 JSON 失败",
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
            "未找到已保存的订阅方案",
            "load_request_snapshot",
            {"request_id": request_id},
        )

    try:
        loaded = json.loads(request_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise Stage1Error(
            "storage_json_error",
            "读取订阅方案 JSON 失败",
            "load_request_snapshot",
            {"request_id": request_id, "reason": exc.msg},
        ) from exc
    except OSError as exc:
        raise Stage1Error(
            "storage_error",
            "读取订阅方案 JSON 失败",
            "load_request_snapshot",
            {"request_id": request_id, "directory": config.requests_dir.name},
        ) from exc

    if not isinstance(loaded, dict):
        raise Stage1Error(
            "storage_json_error",
            "订阅方案 JSON 必须是对象",
            "load_request_snapshot",
            {"request_id": request_id},
        )

    return deepcopy(loaded)


def delete_request_snapshot(
    config: StorageConfig,
    request_id: str,
) -> dict[str, Any]:
    request_path = _request_path(config, request_id, "delete_request_snapshot")
    if not request_path.exists():
        raise Stage1Error(
            "request_not_found",
            "未找到已保存的订阅方案",
            "delete_request_snapshot",
            {"request_id": request_id.strip()},
        )

    try:
        request_path.unlink()
    except OSError as exc:
        raise Stage1Error(
            "storage_error",
            "删除订阅方案 JSON 失败",
            "delete_request_snapshot",
            {
                "request_id": request_id.strip(),
                "directory": config.requests_dir.name,
            },
        ) from exc

    return {
        "request_id": request_id.strip(),
        "storage": "local_json",
        "directory": config.requests_dir.name,
        "filename": request_path.name,
        "deleted": True,
    }


def list_request_snapshots(config: StorageConfig) -> list[dict[str, Any]]:
    if not config.requests_dir.exists():
        return []
    if not config.requests_dir.is_dir():
        raise Stage1Error(
            "storage_error",
            "本地 Request 存储路径不是目录",
            "list_request_snapshots",
            {"directory": config.requests_dir.name},
        )

    snapshots: list[dict[str, Any]] = []
    try:
        request_files = sorted(config.requests_dir.glob("*.json"))
    except OSError as exc:
        raise Stage1Error(
            "storage_error",
            "列出已保存订阅方案失败",
            "list_request_snapshots",
            {"directory": config.requests_dir.name},
        ) from exc

    for request_file in request_files:
        snapshots.append(load_request_snapshot(config, request_file.stem))
    return snapshots


def list_request_snapshots_tolerant(config: StorageConfig) -> RequestListResult:
    """Return healthy snapshots plus ids of damaged files (US-221).

    A damaged single snapshot is never deleted and never blocks the healthy
    list; the opaque damaged ids let the migration runner count/report safely.
    A file whose inner ``request_id`` does not match its file name is treated as
    damaged (the file name is the legacy key).
    """
    if not config.requests_dir.exists():
        return RequestListResult(requests=(), damaged_request_ids=())
    if not config.requests_dir.is_dir():
        raise Stage1Error(
            "storage_error",
            "本地 Request 存储路径不是目录",
            "list_request_snapshots_tolerant",
            {"directory": config.requests_dir.name},
        )

    requests: list[dict[str, Any]] = []
    damaged: list[str] = []
    try:
        request_files = sorted(config.requests_dir.glob("*.json"))
    except OSError as exc:
        raise Stage1Error(
            "storage_error",
            "列出已保存订阅方案失败",
            "list_request_snapshots_tolerant",
            {"directory": config.requests_dir.name},
        ) from exc

    for request_file in request_files:
        candidate_id = request_file.stem
        try:
            loaded = load_request_snapshot(config, candidate_id)
        except Stage1Error:
            damaged.append(candidate_id)
            continue
        inner_id = loaded.get("request_id")
        if not isinstance(inner_id, str) or not inner_id.strip() or inner_id != candidate_id:
            damaged.append(candidate_id)
            continue
        requests.append(loaded)
    return RequestListResult(
        requests=tuple(requests),
        damaged_request_ids=tuple(damaged),
    )


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
    if not is_relative_to(candidate, requests_root):
        raise Stage1Error(
            "invalid_request_id",
            "request_id 不能包含路径片段",
            failed_step,
            {"field": "request_id"},
        )
    return candidate


