"""Test-only writer for constructing historical queue JSON fixtures."""

import json
from dataclasses import asdict
from typing import Any

from batch_engine.models import BatchSubmissionQueue
from shared.errors import Stage1Error
from storage_engine.controllers.storage_config import StorageConfig, ensure_storage_layout


def write_legacy_queue_fixture(config: StorageConfig, queue: BatchSubmissionQueue) -> dict[str, Any]:
    if not queue.batch_id.strip() or "/" in queue.batch_id or "\\" in queue.batch_id:
        raise Stage1Error("invalid_batch_id", "批次标识无效", "write_legacy_queue_fixture", {"field": "batch_id"})
    ensure_storage_layout(config)
    path = config.queue_dir / f"{queue.batch_id}.json"
    path.write_text(json.dumps(asdict(queue), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"batch_id": queue.batch_id, "storage": "local_json", "directory": config.queue_dir.name, "filename": path.name}
