from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from batch_engine.controllers.batch_queue_controller import (
    queue_from_storage_dict,
    queue_to_storage_dict,
)
from batch_engine.models import BatchSubmissionQueue
from shared.errors import Stage1Error
from storage_engine.controllers.storage_config import (
    StorageConfig,
    ensure_storage_layout,
)


def save_submission_queue(
    config: StorageConfig,
    queue: BatchSubmissionQueue,
) -> dict[str, Any]:
    """Persist a batch pre-submission queue as JSON keyed by ``batch_id``.

    The queue only holds non-sensitive public fields (summaries were already
    sanitized on write), so storing the full queue never persists Auto Bangumi
    secrets, raw response bodies, full RSS URLs, magnets, or local paths.
    """
    batch_id = _extract_batch_id(queue, "save_submission_queue")
    queue_path = _queue_path(config, batch_id, "save_submission_queue")
    ensure_storage_layout(config)

    try:
        queue_path.write_text(
            json.dumps(queue_to_storage_dict(queue), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise Stage1Error(
            "storage_error",
            "保存提交队列 JSON 失败",
            "save_submission_queue",
            {"batch_id": batch_id, "directory": config.queue_dir.name},
        ) from exc

    return {
        "batch_id": batch_id,
        "storage": "local_json",
        "directory": config.queue_dir.name,
        "filename": queue_path.name,
    }


def load_submission_queue(
    config: StorageConfig,
    batch_id: str,
) -> BatchSubmissionQueue:
    """Load a batch pre-submission queue, raising ``queue_not_found`` when absent."""
    queue_path = _queue_path(config, batch_id, "load_submission_queue")
    if not queue_path.exists():
        raise Stage1Error(
            "queue_not_found",
            "未找到该批次的提交队列",
            "load_submission_queue",
            {"batch_id": batch_id.strip()},
        )

    try:
        loaded = json.loads(queue_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise Stage1Error(
            "storage_json_error",
            "读取提交队列 JSON 失败",
            "load_submission_queue",
            {"batch_id": batch_id.strip(), "reason": exc.msg},
        ) from exc
    except OSError as exc:
        raise Stage1Error(
            "storage_error",
            "读取提交队列 JSON 失败",
            "load_submission_queue",
            {"batch_id": batch_id.strip(), "directory": config.queue_dir.name},
        ) from exc

    try:
        queue = queue_from_storage_dict(loaded)
    except ValueError as exc:
        raise Stage1Error(
            "storage_json_error",
            "提交队列 JSON 格式无效",
            "load_submission_queue",
            {"batch_id": batch_id.strip(), "reason": str(exc)},
        ) from exc
    return deepcopy(queue)


def _extract_batch_id(queue: BatchSubmissionQueue, failed_step: str) -> str:
    batch_id = queue.batch_id
    if not isinstance(batch_id, str) or not batch_id.strip():
        raise Stage1Error(
            "invalid_batch_id",
            "提交队列缺少有效 batch_id",
            failed_step,
            {"field": "batch_id"},
        )
    return batch_id.strip()


def _queue_path(
    config: StorageConfig,
    batch_id: str,
    failed_step: str,
) -> Path:
    if not isinstance(batch_id, str) or not batch_id.strip():
        raise Stage1Error(
            "invalid_batch_id",
            "batch_id 不能为空",
            failed_step,
            {"field": "batch_id"},
        )

    clean_batch_id = batch_id.strip()
    if Path(clean_batch_id).name != clean_batch_id or "\\" in clean_batch_id:
        raise Stage1Error(
            "invalid_batch_id",
            "batch_id 不能包含路径片段",
            failed_step,
            {"field": "batch_id"},
        )

    queue_root = config.queue_dir.resolve(strict=False)
    candidate = (config.queue_dir / f"{clean_batch_id}.json").resolve(strict=False)
    if not _is_relative_to(candidate, queue_root):
        raise Stage1Error(
            "invalid_batch_id",
            "batch_id 不能包含路径片段",
            failed_step,
            {"field": "batch_id"},
        )
    return candidate


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


__all__ = [
    "load_submission_queue",
    "save_submission_queue",
]
