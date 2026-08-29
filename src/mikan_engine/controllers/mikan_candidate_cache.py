"""Safe in-process cache for MiKan candidate search results.

Only sanitized public candidate metadata is cached: the query, candidate title,
bangumi id, normalized mikan URL, optional poster URL, aliases, and a timestamp.
Cache keys are derived from a SHA-256 digest of the normalized search endpoint
(the MiKan host/config identity) plus the normalized query, so keys never contain
tokens, cookies, or the full sensitive endpoint. Entries expire after a TTL, the
cache is bounded, and it can be cleared for tests or debugging.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass

from mikan_engine.controllers.mikan_client import MikanCandidate
from mikan_engine.controllers.mikan_config import MikanConfig

DEFAULT_CANDIDATE_CACHE_TTL_SECONDS = 300.0
DEFAULT_CANDIDATE_CACHE_MAX_ENTRIES = 128


def candidate_cache_key(query: str, config: MikanConfig) -> str:
    """Build a safe cache key from a normalized query and MiKan identity.

    The MiKan host/config identity (the configured search endpoint) is stored only
    as a truncated SHA-256 digest, so the key never contains the raw endpoint,
    tokens, cookies, or other sensitive values. The query is whitespace-normalized
    so ``" 芙莉莲 "`` and ``"芙莉莲"`` resolve to the same cache entry.
    """
    normalized_query = " ".join(query.split())
    endpoint_identity = config.search_endpoint.strip()
    identity_digest = hashlib.sha256(endpoint_identity.encode("utf-8")).hexdigest()[:32]
    return f"mikan-candidates:{identity_digest}:{normalized_query}"


def _query_from_key(key: str) -> str:
    # key format: mikan-candidates:<identity digest>:<normalized query>
    parts = key.split(":", 2)
    return parts[2] if len(parts) == 3 else ""


@dataclass(frozen=True)
class _CandidateCacheEntry:
    candidates: tuple[MikanCandidate, ...]
    timestamp: float


def _copy_candidates(candidates: list[MikanCandidate]) -> list[MikanCandidate]:
    """Deep-ish copy candidate public metadata so cache entries are immutable.

    ``MikanCandidate`` is frozen, but its ``aliases`` field is a mutable list; a
    fresh candidate with a copied aliases list is stored/returned so callers can
    never mutate cached metadata.
    """
    return [
        MikanCandidate(
            bangumi_id=candidate.bangumi_id,
            title=candidate.title,
            mikan_url=candidate.mikan_url,
            poster_url=candidate.poster_url,
            total_episodes=candidate.total_episodes,
            source_query=candidate.source_query,
            aliases=list(candidate.aliases),
        )
        for candidate in candidates
    ]


class CandidateSearchCache:
    """Bounded in-process cache for sanitized MiKan candidate metadata.

    Entries expire after ``ttl_seconds`` (measured with an injectable monotonic
    clock for tests), the cache is bounded to ``max_entries`` (oldest evicted),
    and ``clear()`` provides a safe way to drop the current contents.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_CANDIDATE_CACHE_TTL_SECONDS,
        max_entries: int = DEFAULT_CANDIDATE_CACHE_MAX_ENTRIES,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._now = now or time.monotonic
        self._entries: dict[str, _CandidateCacheEntry] = {}

    @property
    def ttl_seconds(self) -> float:
        return self._ttl_seconds

    @property
    def max_entries(self) -> int:
        return self._max_entries

    def get(self, key: str) -> list[MikanCandidate] | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if self._now() - entry.timestamp >= self._ttl_seconds:
            del self._entries[key]
            return None
        return _copy_candidates(list(entry.candidates))

    def set(self, key: str, candidates: list[MikanCandidate]) -> None:
        if len(self._entries) >= self._max_entries and key not in self._entries:
            oldest_key = min(
                self._entries,
                key=lambda entry: self._entries[entry].timestamp,
            )
            del self._entries[oldest_key]
        self._entries[key] = _CandidateCacheEntry(
            candidates=tuple(_copy_candidates(candidates)),
            timestamp=self._now(),
        )

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)

    def snapshot(self) -> list[dict[str, object]]:
        """Return sanitized cache contents for tests or debugging.

        Only public candidate fields, the normalized query, and the stored
        timestamp are exposed; the raw key digest is included so tests can verify
        cache isolation without leaking any sensitive endpoint.
        """
        return [
            {
                "key": key,
                "query": _query_from_key(key),
                "timestamp": entry.timestamp,
                "candidates": [
                    {
                        "bangumi_id": candidate.bangumi_id,
                        "title": candidate.title,
                        "mikan_url": candidate.mikan_url,
                        "poster_url": candidate.poster_url,
                        "source_query": candidate.source_query,
                        "aliases": list(candidate.aliases),
                    }
                    for candidate in entry.candidates
                ],
            }
            for key, entry in self._entries.items()
        ]


candidate_search_cache = CandidateSearchCache()
