"""Stage 20 batch pre-submission queue data contract.

The queue tracks accepted batch items that are waiting to be submitted to Auto
Bangumi, so a batch can be accepted together and submitted explicitly later.
Each queue item stores only non-sensitive public metadata (ids, public title,
status, attempt count, sanitized summaries, timestamps). Auto Bangumi secrets
(endpoint, token, cookie, Authorization header), raw response bodies, full RSS
URLs, and magnets must never appear on a queue item or in its serialization.
"""

from __future__ import annotations

from dataclasses import dataclass, field

BATCH_QUEUE_STATUS_READY_TO_SUBMIT = "READY_TO_SUBMIT"
BATCH_QUEUE_STATUS_SUBMITTING = "SUBMITTING"
BATCH_QUEUE_STATUS_SUCCEEDED = "SUCCEEDED"
BATCH_QUEUE_STATUS_FAILED = "FAILED"
BATCH_QUEUE_STATUS_RETRYABLE = "RETRYABLE"
BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED = "RESULT_PERSIST_FAILED"

#: Chinese display labels for the supported queue statuses.
BATCH_QUEUE_STATUS_LABELS: dict[str, str] = {
    BATCH_QUEUE_STATUS_READY_TO_SUBMIT: "待提交",
    BATCH_QUEUE_STATUS_SUBMITTING: "提交中",
    BATCH_QUEUE_STATUS_SUCCEEDED: "提交成功",
    BATCH_QUEUE_STATUS_FAILED: "提交失败",
    BATCH_QUEUE_STATUS_RETRYABLE: "可重试",
    BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED: "结果保存失败",
}

#: Allowed status transitions. SUCCEEDED is terminal; FAILED/RETRYABLE can be
#: retried (back to SUBMITTING); a READY item can be marked FAILED/RETRYABLE
#: directly when pre-submit validation rejects it before any submit attempt.
#: RESULT_PERSIST_FAILED is the ambiguous state after an Auto Bangumi call whose
#: local result persistence failed — it is never retried automatically and can
#: only be resolved through explicit recovery (to SUCCEEDED after manual
#: verification that the subscription was created, or to FAILED when it was
#: not). SUBMITTING can likewise be recovered to SUCCEEDED/FAILED/RETRYABLE
#: after an interruption.
BATCH_QUEUE_TRANSITIONS: dict[str, frozenset[str]] = {
    BATCH_QUEUE_STATUS_READY_TO_SUBMIT: frozenset(
        {
            BATCH_QUEUE_STATUS_SUBMITTING,
            BATCH_QUEUE_STATUS_FAILED,
            BATCH_QUEUE_STATUS_RETRYABLE,
        }
    ),
    BATCH_QUEUE_STATUS_SUBMITTING: frozenset(
        {
            BATCH_QUEUE_STATUS_SUCCEEDED,
            BATCH_QUEUE_STATUS_FAILED,
            BATCH_QUEUE_STATUS_RETRYABLE,
            BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED,
        }
    ),
    BATCH_QUEUE_STATUS_FAILED: frozenset({BATCH_QUEUE_STATUS_SUBMITTING}),
    BATCH_QUEUE_STATUS_RETRYABLE: frozenset({BATCH_QUEUE_STATUS_SUBMITTING}),
    BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED: frozenset(
        {
            BATCH_QUEUE_STATUS_SUCCEEDED,
            BATCH_QUEUE_STATUS_FAILED,
        }
    ),
    BATCH_QUEUE_STATUS_SUCCEEDED: frozenset(),
}


@dataclass(frozen=True)
class BatchQueueItem:
    """One accepted batch item waiting in the pre-submission queue.

    ``last_error`` and ``ab_result_summary`` are sanitized one-line summaries
    produced by the queue controller; they never carry Auto Bangumi secrets,
    raw response bodies, full RSS URLs, magnets, or local paths.
    """

    queue_id: str
    batch_id: str
    item_id: str
    request_id: str
    title: str
    status: str = BATCH_QUEUE_STATUS_READY_TO_SUBMIT
    attempts: int = 0
    last_error: str | None = None
    ab_result_summary: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class BatchSubmissionQueue:
    """An ordered pre-submission queue for one accepted batch."""

    queue_id: str
    batch_id: str
    items: list[BatchQueueItem] = field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None


__all__ = [
    "BATCH_QUEUE_STATUS_FAILED",
    "BATCH_QUEUE_STATUS_LABELS",
    "BATCH_QUEUE_STATUS_READY_TO_SUBMIT",
    "BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED",
    "BATCH_QUEUE_STATUS_RETRYABLE",
    "BATCH_QUEUE_STATUS_SUBMITTING",
    "BATCH_QUEUE_STATUS_SUCCEEDED",
    "BATCH_QUEUE_TRANSITIONS",
    "BatchQueueItem",
    "BatchSubmissionQueue",
]
