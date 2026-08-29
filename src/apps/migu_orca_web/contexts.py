from __future__ import annotations

"""Bounded, expiring, one-time candidate-selection contexts (US-191 split).

The candidate selection context is short-lived server state that lets a parser
season hint reach a selected Request without ever trusting browser-displayed
fields. It was previously defined in ``views.py``; it now lives here so the
route modules and tests can import it without the page/registration module.
"""

from collections import OrderedDict
from dataclasses import dataclass
from secrets import token_urlsafe
from time import monotonic
from typing import Callable


@dataclass(frozen=True)
class _CandidateSelectionContext:
    mikan_url: str
    season: int | None
    created_at: float


class CandidateSelectionContextStore:
    """Bounded, expiring, one-time capability for a reviewed candidate choice."""

    def __init__(self, *, ttl_seconds: float = 300.0, max_entries: int = 128, now: Callable[[], float] | None = None) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._now = now or monotonic
        self._entries: OrderedDict[str, _CandidateSelectionContext] = OrderedDict()

    def issue(self, mikan_url: str, season: int | None) -> str:
        self._purge()
        while len(self._entries) >= self._max_entries:
            self._entries.popitem(last=False)
        token = token_urlsafe(24)
        self._entries[token] = _CandidateSelectionContext(mikan_url, season, self._now())
        return token

    def consume(self, token: str | None, mikan_url: str) -> tuple[bool, int | None]:
        self._purge()
        if not token:
            return False, None
        context = self._entries.pop(token, None)
        if context is None or context.mikan_url != mikan_url:
            return False, None
        return True, context.season

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        self._purge()
        return len(self._entries)

    def _purge(self) -> None:
        threshold = self._now() - self._ttl_seconds
        for token, context in list(self._entries.items()):
            if context.created_at <= threshold:
                del self._entries[token]


candidate_selection_contexts = CandidateSelectionContextStore()
