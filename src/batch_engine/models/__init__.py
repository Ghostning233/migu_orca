from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Iterable

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
ANIME_TITLE_PARSE_SOURCE_CORRECTION = "correction"
ANIME_TITLE_PARSE_SOURCE_RULE = "rule"
ANIME_TITLE_PARSE_SOURCE_ALIAS = "alias"
ANIME_TITLE_PARSE_SOURCE_FALLBACK = "fallback"
ANIME_TITLE_PARSE_SOURCE_FAKE = "fake"

MAX_ANIME_TITLE_LENGTH = 256
MAX_ANIME_TITLE_QUERY_COUNT = 8
MAX_ANIME_TITLE_QUERY_LENGTH = 256
MAX_ANIME_TITLE_REVIEW_HINT_COUNT = 8
MAX_ANIME_TITLE_REVIEW_HINT_LENGTH = 160


class AnimeTitleParseSource(StrEnum):
    """Whitelisted origins that may be exposed by title parsing APIs."""

    CORRECTION = ANIME_TITLE_PARSE_SOURCE_CORRECTION
    RULE = ANIME_TITLE_PARSE_SOURCE_RULE
    ALIAS = ANIME_TITLE_PARSE_SOURCE_ALIAS
    FALLBACK = ANIME_TITLE_PARSE_SOURCE_FALLBACK
    FAKE = ANIME_TITLE_PARSE_SOURCE_FAKE


class AnimeTitleSeasonSource(StrEnum):
    """Whitelisted origin for the public, reviewable season contract."""

    TITLE_MARKER = "title_marker"
    NONE = "none"


@dataclass(frozen=True)
class AnimeTitleSeason:
    """Immutable JSON-safe season evidence owned by the title parser.

    ``number`` is absent whenever the parser cannot prove a one-to-ninety-nine
    season.  Legacy ``season_hint`` is derived from this object only.
    """

    number: int | None
    raw: str | None = None
    normalized: str | None = None
    source: AnimeTitleSeasonSource | str = AnimeTitleSeasonSource.NONE

    def __post_init__(self) -> None:
        source = AnimeTitleSeasonSource(self.source)
        if self.number is None:
            if self.raw is not None or self.normalized is not None or source is not AnimeTitleSeasonSource.NONE:
                raise ValueError("unproven season must use the none source without values")
        else:
            if not isinstance(self.number, int) or isinstance(self.number, bool) or not 1 <= self.number <= 99:
                raise ValueError("season number must be between 1 and 99")
            if not isinstance(self.raw, str) or not self.raw.strip() or not isinstance(self.normalized, str) or not self.normalized.strip():
                raise ValueError("proven season requires raw and normalized public values")
            if source is AnimeTitleSeasonSource.NONE:
                raise ValueError("proven season requires a non-none source")
            object.__setattr__(self, "raw", self.raw.strip())
            object.__setattr__(self, "normalized", self.normalized.strip())
        object.__setattr__(self, "source", source)

    def to_dict(self) -> dict[str, int | str | None]:
        return {"number": self.number, "raw": self.raw, "normalized": self.normalized, "source": self.source.value}


ANIME_TITLE_PARSE_SOURCE_LABELS = {
    AnimeTitleParseSource.CORRECTION: "用户修正",
    AnimeTitleParseSource.RULE: "规则识别",
    AnimeTitleParseSource.ALIAS: "别名匹配",
    AnimeTitleParseSource.FALLBACK: "原始标题回退",
    AnimeTitleParseSource.FAKE: "测试解析",
}


def coerce_anime_title_parse_source(value: AnimeTitleParseSource | str) -> AnimeTitleParseSource:
    """Return a public-safe source without reflecting provider-owned strings."""

    try:
        return AnimeTitleParseSource(value)
    except (TypeError, ValueError):
        return AnimeTitleParseSource.FALLBACK


@dataclass(frozen=True)
class AnimeTitleQuery:
    """One bounded, ordered query in an anime-title search plan."""

    query: str
    source: AnimeTitleParseSource | str
    priority: int

    def __post_init__(self) -> None:
        query = self.query.strip()
        if not query or len(query) > MAX_ANIME_TITLE_QUERY_LENGTH:
            raise ValueError("query must be non-empty and within the maximum length")
        if not 1 <= self.priority <= MAX_ANIME_TITLE_QUERY_COUNT:
            raise ValueError("priority must be between 1 and the query-plan limit")
        object.__setattr__(self, "query", query)
        object.__setattr__(self, "source", coerce_anime_title_parse_source(self.source))

    def to_dict(self) -> dict[str, str | int]:
        return {"query": self.query, "source": self.source.value, "priority": self.priority}


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
    canonical_title_candidates: tuple[str, ...]
    season_hint: str | None
    search_queries: tuple[str, ...]
    confidence: float
    needs_user_review: bool
    source: AnimeTitleParseSource | str
    normalized_title: str | None = None
    base_title: str | None = None
    season: AnimeTitleSeason | int | None = None
    query_plan: tuple[AnimeTitleQuery, ...] = ()
    review_hints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        raw_title = self.raw_title
        if not raw_title.strip() or len(raw_title) > MAX_ANIME_TITLE_LENGTH:
            raise ValueError("raw_title must be non-empty and within the maximum length")
        candidates = _immutable_texts(self.canonical_title_candidates, MAX_ANIME_TITLE_LENGTH)
        queries = _immutable_texts(self.search_queries, MAX_ANIME_TITLE_QUERY_LENGTH)
        if not candidates or not queries:
            raise ValueError("canonical_title_candidates and search_queries must not be empty")
        if len(queries) > MAX_ANIME_TITLE_QUERY_COUNT:
            raise ValueError("search_queries exceeds the query-plan limit")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        season = _coerce_anime_title_season(self.season)
        derived_hint = f"S{season.number}" if season.number is not None else None
        # Provider/legacy input may carry an arbitrary hint.  Never preserve it:
        # the public compatibility field is derived from the structured object.
        normalized_title = (self.normalized_title or raw_title).strip()
        base_title = (self.base_title or normalized_title).strip()
        if not normalized_title or not base_title:
            raise ValueError("normalized_title and base_title must not be empty")
        plan = tuple(self.query_plan) or tuple(
            AnimeTitleQuery(query=query, source=self.source, priority=index)
            for index, query in enumerate(queries, start=1)
        )
        if len(plan) > MAX_ANIME_TITLE_QUERY_COUNT:
            raise ValueError("query_plan exceeds the query-plan limit")
        if tuple(entry.query for entry in plan) != queries:
            raise ValueError("search_queries must be derived from query_plan")
        if tuple(entry.priority for entry in plan) != tuple(range(1, len(plan) + 1)):
            raise ValueError("query_plan priorities must be consecutive and start at 1")
        hints = _immutable_texts(
            self.review_hints, MAX_ANIME_TITLE_REVIEW_HINT_LENGTH, MAX_ANIME_TITLE_REVIEW_HINT_COUNT
        )
        object.__setattr__(self, "raw_title", raw_title)
        object.__setattr__(self, "canonical_title_candidates", candidates)
        object.__setattr__(self, "search_queries", queries)
        object.__setattr__(self, "confidence", float(self.confidence))
        object.__setattr__(self, "source", coerce_anime_title_parse_source(self.source))
        object.__setattr__(self, "normalized_title", normalized_title)
        object.__setattr__(self, "base_title", base_title)
        object.__setattr__(self, "season", season)
        object.__setattr__(self, "season_hint", derived_hint)
        object.__setattr__(self, "query_plan", plan)
        object.__setattr__(self, "review_hints", hints)

    def to_dict(self) -> dict[str, object]:
        """Return the stable JSON-safe contract used at API boundaries."""

        return {
            "raw_title": self.raw_title,
            "normalized_title": self.normalized_title,
            "base_title": self.base_title,
            "canonical_title_candidates": list(self.canonical_title_candidates),
            "season": self.season.to_dict(),
            # Transitional scalar for older clients. It is derived exclusively
            # from the structured public season object above.
            "season_number": self.season.number,
            "season_hint": self.season_hint,
            "query_plan": [entry.to_dict() for entry in self.query_plan],
            # Kept for existing callers; this is always derived from query_plan.
            "search_queries": list(self.search_queries),
            "source": self.source.value,
            "confidence": self.confidence,
            "needs_user_review": self.needs_user_review,
            "review_hints": list(self.review_hints),
        }


def _immutable_texts(
    values: Iterable[str], maximum_length: int, maximum_count: int | None = None
) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        text = value.strip()
        if not text or len(text) > maximum_length:
            raise ValueError("text values must be non-empty and within the maximum length")
        if text not in normalized:
            normalized.append(text)
    if maximum_count is not None and len(normalized) > maximum_count:
        raise ValueError("too many text values")
    return tuple(normalized)


def _coerce_anime_title_season(value: AnimeTitleSeason | int | None) -> AnimeTitleSeason:
    if isinstance(value, AnimeTitleSeason):
        return value
    if value is None:
        return AnimeTitleSeason(None)
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 99:
        raise ValueError("season must be between 1 and 99")
    return AnimeTitleSeason(value, f"S{value}", f"第{value}季", AnimeTitleSeasonSource.TITLE_MARKER)


__all__ = [
    "ANIME_TITLE_PARSE_SOURCE_FAKE",
    "ANIME_TITLE_PARSE_SOURCE_ALIAS",
    "ANIME_TITLE_PARSE_SOURCE_CORRECTION",
    "ANIME_TITLE_PARSE_SOURCE_FALLBACK",
    "ANIME_TITLE_PARSE_SOURCE_LABELS",
    "ANIME_TITLE_PARSE_SOURCE_RULE",
    "AnimeTitleParseSource",
    "AnimeTitleSeason",
    "AnimeTitleSeasonSource",
    "AnimeTitleQuery",
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
    "MAX_ANIME_TITLE_LENGTH",
    "MAX_ANIME_TITLE_QUERY_COUNT",
    "MAX_ANIME_TITLE_QUERY_LENGTH",
    "coerce_anime_title_parse_source",
]
