from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
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


@dataclass(frozen=True)
class QueueListResult:
    """Healthy batch queues plus the opaque batch ids of damaged files (US-221)."""

    queues: tuple[BatchSubmissionQueue, ...]
    damaged_batch_ids: tuple[str, ...]

    @property
    def unreadable_count(self) -> int:
        return len(self.damaged_batch_ids)


def write_legacy_queue_fixture(
    config: StorageConfig,
    queue: BatchSubmissionQueue,
) -> dict[str, Any]:
    """Persist a batch pre-submission queue as JSON keyed by ``batch_id``.

    The queue only holds non-sensitive public fields (summaries were already
    sanitized on write), so storing the full queue never persists Auto Bangumi
    secrets, raw response bodies, full RSS URLs, magnets, or local paths.
    """
    batch_id = _extract_batch_id(queue, "write_legacy_queue_fixture")
    queue_path = _queue_path(config, batch_id, "write_legacy_queue_fixture")
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
            "write_legacy_queue_fixture",
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


def list_submission_queues_tolerant(config: StorageConfig) -> QueueListResult:
    """Return healthy queues plus opaque batch ids of damaged files (US-221)."""
    if not config.queue_dir.exists():
        return QueueListResult(queues=(), damaged_batch_ids=())
    if not config.queue_dir.is_dir():
        raise Stage1Error(
            "storage_error",
            "本地提交队列存储路径不是目录",
            "list_submission_queues_tolerant",
            {"directory": config.queue_dir.name},
        )

    queues: list[BatchSubmissionQueue] = []
    damaged: list[str] = []
    try:
        queue_files = sorted(config.queue_dir.glob("*.json"))
    except OSError as exc:
        raise Stage1Error(
            "storage_error",
            "列出提交队列失败",
            "list_submission_queues_tolerant",
            {"directory": config.queue_dir.name},
        ) from exc

    for queue_file in queue_files:
        candidate_id = queue_file.stem
        try:
            queues.append(load_submission_queue(config, candidate_id))
        except Stage1Error:
            damaged.append(candidate_id)
    return QueueListResult(queues=tuple(queues), damaged_batch_ids=tuple(damaged))


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
    "QueueListResult",
    "list_submission_queues_tolerant",
    "load_submission_queue",
    "write_legacy_queue_fixture",
]
