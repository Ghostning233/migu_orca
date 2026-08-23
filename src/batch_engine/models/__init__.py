from __future__ import annotations

from dataclasses import dataclass, field

from batch_engine.models.queue import (
    BATCH_QUEUE_STATUS_FAILED,
    BATCH_QUEUE_STATUS_LABELS,
    BATCH_QUEUE_STATUS_READY_TO_SUBMIT,
    BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED,
    BATCH_QUEUE_STATUS_RETRYABLE,
    BATCH_QUEUE_STATUS_SUBMITTING,
    BATCH_QUEUE_STATUS_SUCCEEDED,
    BATCH_QUEUE_TRANSITIONS,
    BatchQueueItem,
    BatchSubmissionQueue,
)

BATCH_ITEM_STATUS_RAW = "RAW"
BATCH_ITEM_STATUS_PARSED = "PARSED"
BATCH_ITEM_STATUS_FOUND = "FOUND"
BATCH_ITEM_STATUS_EMPTY = "EMPTY"
BATCH_ITEM_STATUS_FAILED = "FAILED"
ANIME_TITLE_PARSE_SOURCE_FAKE = "fake"


@dataclass(frozen=True)
class BatchDraftItem:
    item_id: str
    raw_title: str
    status: str = BATCH_ITEM_STATUS_RAW


@dataclass(frozen=True)
class BatchDraft:
    batch_id: str
    raw_input: str
    items: list[BatchDraftItem] = field(default_factory=list)


@dataclass(frozen=True)
class AnimeTitleParseResult:
    raw_title: str
    canonical_title_candidates: list[str]
    season_hint: str | None
    search_queries: list[str]
    confidence: float
    needs_user_review: bool
    source: str


__all__ = [
    "ANIME_TITLE_PARSE_SOURCE_FAKE",
    "AnimeTitleParseResult",
    "BATCH_ITEM_STATUS_FAILED",
    "BATCH_ITEM_STATUS_EMPTY",
    "BATCH_ITEM_STATUS_FOUND",
    "BATCH_ITEM_STATUS_PARSED",
    "BATCH_ITEM_STATUS_RAW",
    "BATCH_QUEUE_STATUS_FAILED",
    "BATCH_QUEUE_STATUS_LABELS",
    "BATCH_QUEUE_STATUS_READY_TO_SUBMIT",
    "BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED",
    "BATCH_QUEUE_STATUS_RETRYABLE",
    "BATCH_QUEUE_STATUS_SUBMITTING",
    "BATCH_QUEUE_STATUS_SUCCEEDED",
    "BATCH_QUEUE_TRANSITIONS",
    "BatchDraft",
    "BatchDraftItem",
    "BatchQueueItem",
    "BatchSubmissionQueue",
]
