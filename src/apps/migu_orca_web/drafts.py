from __future__ import annotations

"""Server-authoritative draft store for unsaved preview requests (US-194).

The old preview flow trusted the client to send back the *complete* preview
Request for every ``preview-modify`` and ``preview-save`` call. US-194 makes
the server the authority for unsaved drafts:

- generation endpoints (``POST /api/v1/requests`` with ``save_request=false``)
  store the authoritative PENDING_CONFIRM draft in this bounded store and
  return an opaque ``draft_id`` plus its initial ``draft_revision`` (US-211);
- ``preview-modify`` accepts ``draft_id`` + ``base_revision`` + an allowed patch
  (never a client full Request), performs a compare-and-swap, and returns the
  updated in-memory draft with the bumped ``draft_revision``;
- ``preview-save`` consumes a *valid* ``draft_id`` once and persists the
  server-held draft, with replay protection.

US-210 adds a monotonic ``revision`` to every server-authoritative draft so the
server can reject out-of-order stale writes:

- ``issue`` returns a ``DraftHandle`` whose ``revision`` starts at 1;
- ``get`` returns a ``DraftRead`` carrying the authoritative draft *and* its
  current revision;
- ``compare_and_swap`` replaces the draft atomically only when ``base_revision``
  matches the current revision (bumping the revision by 1); a mismatch leaves
  both payload and revision untouched and returns ``REASON_REVISION_CONFLICT``.

Security/robustness properties
------------------------------
- Draft contents are request-scoped and ephemeral: they are never written to
  browser storage, URL state, history, logs or screenshots, and never appear
  in API responses (only the opaque ``draft_id`` leaves the server).
- The store is bounded (``max_entries``), time-limited (``ttl_seconds``),
  self-cleaning on every access, and one-shot for saves.
- Every failure mode maps to a stable 409 ``draft_*`` error type
  (``draft_expired`` / ``draft_evicted`` / ``draft_replayed`` /
  ``draft_revision_conflict`` / ``draft_mismatch``), which
  ``extensions/flask_api/api.py`` classifies as HTTP 409; the UI offers a
  "重新生成" (re-generate) hint instead of leaking draft content.
- Like ``CandidateSelectionContextStore``, the store is a process-level
  singleton whose capacity is intentionally small: drafts are short-lived
  working state, not durable storage.
"""

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from secrets import token_urlsafe
from time import monotonic
from typing import Any

#: Reason codes returned by the store so routes can pick a stable error type.
REASON_OK = "ok"
REASON_EXPIRED = "expired"
REASON_EVICTED = "evicted"
REASON_REPLAYED = "replayed"
REASON_REVISION_CONFLICT = "revision_conflict"
REASON_UNKNOWN = "unknown"


@dataclass(frozen=True)
class DraftHandle:
    """Public handle returned by ``issue``.

    Carries the opaque ``draft_id`` and the draft's initial ``revision`` (=1).
    Only the opaque id is ever sent to the client; the revision stays in the
    current response/request body and component memory (US-211).
    """

    draft_id: str
    revision: int


@dataclass(frozen=True)
class DraftRead:
    """Authoritative draft snapshot plus its current revision (``get``).

    ``get`` never consumes the draft; it returns the payload and the revision
    the caller must send back as ``base_revision`` for the next atomic update.
    """

    request: dict[str, Any]
    revision: int


@dataclass(frozen=True)
class _DraftEntry:
    request: dict[str, Any]
    revision: int
    created_at: float
    used_at: float


class DraftStore:
    """Bounded, expiring, one-time-save store for unsaved preview drafts.

    ``issue`` stores a generated draft and returns a ``DraftHandle`` carrying
    the opaque ``draft_id`` and ``revision=1``. ``get`` reads a draft for
    dry-run modification without consuming it, returning both the payload and
    its current revision. ``consume_for_save`` atomically removes and returns a
    draft, so a saved draft can never be saved twice (replay protection).

    Updates go through ``compare_and_swap``: the caller supplies the
    ``base_revision`` it last observed, and the store replaces the payload
    atomically (bumping the revision by 1) only when the base matches the
    current revision. A stale base leaves the payload and revision untouched.

    Lookups return a ``(value_or_None, reason)`` tuple so the routes can map
    the failure to a stable 409 ``draft_*`` error type:

    - ``expired``            — the draft lived past its TTL (or was purged);
    - ``evicted``            — the draft was evicted because the store was full;
    - ``replayed``           — the draft id was consumed by a previous save;
    - ``revision_conflict``  — the caller's ``base_revision`` is stale;
    - ``unknown``            — the id was never issued (or long forgotten).
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = 1800.0,
        max_entries: int = 128,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._now = now or monotonic
        self._entries: OrderedDict[str, _DraftEntry] = OrderedDict()
        #: Tombstones for ids that disappeared: draft_id -> (reason, at).
        #: ``replayed`` for a consumed save, ``expired``/``evicted`` for a
        #: purge/eviction. Bounded by the same TTL; purged on access.
        self._tombstones: dict[str, tuple[str, float]] = {}

    # -- lifecycle ----------------------------------------------------------

    def issue(self, request: dict[str, Any]) -> DraftHandle:
        """Store ``request`` and return a handle with an opaque id, revision 1.

        Evicts expired entries first, then the oldest entry when at capacity.
        """
        self._purge()
        while len(self._entries) >= self._max_entries:
            evicted_id, _ = self._entries.popitem(last=False)
            self._tombstones[evicted_id] = (REASON_EVICTED, self._now())
        draft_id = token_urlsafe(24)
        now = self._now()
        self._entries[draft_id] = _DraftEntry(
            request=request,
            revision=1,
            created_at=now,
            used_at=now,
        )
        return DraftHandle(draft_id=draft_id, revision=1)

    def get(self, draft_id: str | None) -> tuple[DraftRead | None, str]:
        """Return ``(DraftRead, reason)`` for a dry-run modify (never consumes).

        Reading refreshes ``used_at`` (recently-modified drafts stay alive),
        but does not invalidate the entry. A missing id is reported as
        ``replayed`` when it was consumed by an earlier save, ``expired``/
        ``evicted`` when it was purged/evicted, otherwise ``unknown``.
        """
        self._purge()
        if not draft_id:
            return None, REASON_UNKNOWN
        entry = self._entries.get(draft_id)
        if entry is None:
            return None, self._missing_reason(draft_id)
        self._entries.move_to_end(draft_id)
        self._entries[draft_id] = _DraftEntry(
            request=entry.request,
            revision=entry.revision,
            created_at=entry.created_at,
            used_at=self._now(),
        )
        return DraftRead(request=entry.request, revision=entry.revision), REASON_OK

    def compare_and_swap(
        self,
        draft_id: str | None,
        base_revision: int,
        request: dict[str, Any],
    ) -> tuple[int | None, str]:
        """Atomically replace ``request`` iff ``base_revision`` is current.

        On success the revision is bumped by 1 and ``(new_revision,
        REASON_OK)`` is returned. When ``base_revision`` is stale the payload
        and revision are left untouched and ``(None,
        REASON_REVISION_CONFLICT)`` is returned. An expired/evicted/consumed/
        unknown id returns ``(None, draft_* reason)``; the caller maps it to a
        stable 409 error.
        """
        self._purge()
        if not draft_id:
            return None, REASON_UNKNOWN
        entry = self._entries.get(draft_id)
        if entry is None:
            return None, self._missing_reason(draft_id)
        if entry.revision != base_revision:
            return None, REASON_REVISION_CONFLICT
        new_revision = entry.revision + 1
        now = self._now()
        self._entries[draft_id] = _DraftEntry(
            request=request,
            revision=new_revision,
            created_at=entry.created_at,
            used_at=now,
        )
        self._entries.move_to_end(draft_id)
        return new_revision, REASON_OK

    def consume_for_save(self, draft_id: str | None) -> tuple[dict[str, Any] | None, str]:
        """Atomically remove and return a draft if it is still usable.

        On success the id is recorded as consumed (tombstone) so a second save
        is detected as ``replayed``. An expired/evicted/unknown id returns a
        ``draft_*`` reason; the caller maps it to a stable 409 error.
        """
        self._purge()
        if not draft_id:
            return None, REASON_UNKNOWN
        entry = self._entries.pop(draft_id, None)
        if entry is None:
            return None, self._missing_reason(draft_id)
        self._tombstones[draft_id] = (REASON_REPLAYED, self._now())
        return entry.request, REASON_OK

    def update(self, draft_id: str, request: dict[str, Any]) -> bool:
        """Replace the stored payload for an existing draft (legacy helper).

        Bumps the revision exactly like a successful CAS against the current
        revision, but performs **no base check** (callers that must reject
        out-of-order writes use ``compare_and_swap`` instead — US-211 routes
        no longer call this). Retained for US-210 unit coverage and as the
        internal primitive ``compare_and_swap`` builds on. Returns False when
        the draft is no longer present (expired/evicted/consumed).
        """
        if not draft_id:
            return False
        entry = self._entries.get(draft_id)
        if entry is None:
            return False
        new_revision = entry.revision + 1
        now = self._now()
        self._entries[draft_id] = _DraftEntry(
            request=request,
            revision=new_revision,
            created_at=entry.created_at,
            used_at=now,
        )
        self._entries.move_to_end(draft_id)
        return True

    def clear(self) -> None:
        self._entries.clear()
        self._tombstones.clear()

    def __len__(self) -> int:
        self._purge()
        return len(self._entries)

    # -- internals ----------------------------------------------------------

    def _missing_reason(self, draft_id: str) -> str:
        tombstone = self._tombstones.get(draft_id)
        if tombstone is None:
            return REASON_UNKNOWN
        return tombstone[0]

    def _purge(self) -> None:
        threshold = self._now() - self._ttl_seconds
        for draft_id, entry in list(self._entries.items()):
            if entry.created_at <= threshold or entry.used_at <= threshold:
                del self._entries[draft_id]
                self._tombstones.setdefault(draft_id, (REASON_EXPIRED, self._now()))
        for draft_id, (_, at) in list(self._tombstones.items()):
            # Forget tombstones older than the TTL so a long-gone id is
            # reported as ``unknown`` rather than a stale reason forever.
            if at <= threshold:
                del self._tombstones[draft_id]


#: Process-level singleton. Like ``candidate_selection_contexts``, tests reset
#: it between cases; capacity is deliberately small because drafts are
#: ephemeral working state.
draft_store = DraftStore()
