"""Read-only parser for historical batch queue JSON."""

from typing import Any

from batch_engine.models.queue import (
    BATCH_QUEUE_STATUS_FAILED,
    BATCH_QUEUE_STATUS_READY_TO_SUBMIT,
    BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED,
    BATCH_QUEUE_STATUS_RETRYABLE,
    BATCH_QUEUE_STATUS_SUBMITTING,
    BATCH_QUEUE_STATUS_SUCCEEDED,
    BatchQueueItem,
    BatchSubmissionQueue,
)

_KNOWN_QUEUE_STATUSES = frozenset(
    {
        BATCH_QUEUE_STATUS_READY_TO_SUBMIT,
        BATCH_QUEUE_STATUS_SUBMITTING,
        BATCH_QUEUE_STATUS_SUCCEEDED,
        BATCH_QUEUE_STATUS_FAILED,
        BATCH_QUEUE_STATUS_RETRYABLE,
        BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED,
    }
)


def queue_from_storage_dict(data: Any) -> BatchSubmissionQueue:
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError("queue storage JSON must be an object with items")
    return BatchSubmissionQueue(
        queue_id=str(data.get("queue_id") or ""),
        batch_id=str(data.get("batch_id") or ""),
        items=[queue_item_from_storage_dict(item) for item in data["items"]],
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
    )


def queue_item_from_storage_dict(data: Any) -> BatchQueueItem:
    if not isinstance(data, dict):
        raise ValueError("queue item storage JSON must be an object")
    status = str(data.get("status") or BATCH_QUEUE_STATUS_READY_TO_SUBMIT)
    if status not in _KNOWN_QUEUE_STATUSES:
        raise ValueError(f"invalid queue item status: {status}")
    return BatchQueueItem(
        queue_id=str(data.get("queue_id") or ""),
        batch_id=str(data.get("batch_id") or ""),
        item_id=str(data.get("item_id") or ""),
        request_id=str(data.get("request_id") or ""),
        title=str(data.get("title") or ""),
        status=status,
        attempts=int(data.get("attempts") or 0),
        last_error=data.get("last_error"),
        ab_result_summary=data.get("ab_result_summary"),
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
    )
