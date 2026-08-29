"""Shared bounded title-plan to MiKan-candidate search orchestration."""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass
from typing import Generic, TypeVar

from batch_engine.models import (
    BATCH_ITEM_STATUS_EMPTY,
    BATCH_ITEM_STATUS_FAILED,
    BATCH_ITEM_STATUS_FOUND,
    AnimeTitleParseResult,
)
from shared.errors import Stage1Error

Candidate = TypeVar("Candidate")


@dataclass(frozen=True)
class CandidateSearchOutcome(Generic[Candidate]):
    """The auditable result of running one bounded parsed query plan.

    The caller owns candidate serialization; this module deliberately only
    coordinates public-safe values supplied by that caller.
    """

    status: str
    candidates: tuple[Candidate, ...]
    attempted_queries: tuple[str, ...]
    error: Stage1Error | None = None


def search_parsed_candidates(
    parse_result: AnimeTitleParseResult,
    search: Callable[[str], list[Candidate]],
    identity: Callable[[Candidate], Hashable],
) -> CandidateSearchOutcome[Candidate]:
    """Run a parsed plan in priority order with bounded, tolerant fallback.

    A successful non-empty priority stops weaker fallbacks. Individual search
    errors are retained only when every query fails, while later queries still
    run. Candidates are stably deduplicated by their public identity.
    """

    attempted: list[str] = []
    last_error: Stage1Error | None = None
    successful_query = False
    for entry in parse_result.query_plan:
        attempted.append(entry.query)
        try:
            results = search(entry.query)
        except Stage1Error as exc:
            last_error = exc
            continue
        successful_query = True
        if not results:
            continue
        seen: set[Hashable] = set()
        candidates: list[Candidate] = []
        for candidate in results:
            key = identity(candidate)
            if key not in seen:
                seen.add(key)
                candidates.append(candidate)
        return CandidateSearchOutcome(
            status=BATCH_ITEM_STATUS_FOUND,
            candidates=tuple(candidates),
            attempted_queries=tuple(attempted),
        )

    return CandidateSearchOutcome(
        status=BATCH_ITEM_STATUS_EMPTY if successful_query else BATCH_ITEM_STATUS_FAILED,
        candidates=(),
        attempted_queries=tuple(attempted),
        error=None if successful_query else last_error,
    )


__all__ = ["CandidateSearchOutcome", "search_parsed_candidates"]
