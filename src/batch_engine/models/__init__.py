from __future__ import annotations

from dataclasses import dataclass, field


BATCH_ITEM_STATUS_RAW = "RAW"
BATCH_ITEM_STATUS_PARSED = "PARSED"
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
    "BATCH_ITEM_STATUS_PARSED",
    "BATCH_ITEM_STATUS_RAW",
    "BatchDraft",
    "BatchDraftItem",
]
