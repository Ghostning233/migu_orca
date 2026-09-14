from __future__ import annotations

"""Server-authoritative draft store for unsaved preview requests (US-194).

The old preview flow trusted the client to send back the *complete* preview
Request for every draft modification call. US-194 makes
the server the authority for unsaved drafts:

- generation endpoint (``POST /api/v1/requests``) issues a server draft
  store the authoritative PENDING_CONFIRM draft in this bounded store and
  return an opaque ``draft_id`` plus its initial ``draft_revision`` (US-211);
- ``preview-modify`` accepts ``draft_id`` + ``base_revision`` + an allowed patch
  (never a client full Request), performs a compare-and-swap, and returns the
  updated in-memory draft with the bumped ``draft_revision``;
- ``save-confirm`` reserves a *valid* ``draft_id`` for persistence, commits the
  replay tombstone only after the Request is written, and releases the draft on
  a failed persist so the same draft/revision can be retried (US-212).

US-210 adds a monotonic ``revision`` to every server-authoritative draft so the
server can reject out-of-order stale writes:

- ``issue`` returns a ``DraftHandle`` whose ``revision`` starts at 1;
- ``get`` returns a ``DraftRead`` carrying the authoritative draft *and* its
  current revision;
- ``compare_and_swap`` replaces the draft atomically only when ``base_revision``
  matches the current revision (bumping the revision by 1); a mismatch leaves
  both payload and revision untouched and returns ``REASON_REVISION_CONFLICT``.

US-212 fixes "consume before persist" so a failed disk write never destroys a
draft the user must re-search for:

- ``reserve_for_save`` validates ``draft_id`` + ``base_revision`` and pins the
  draft while it is being persisted; during the reservation the draft cannot be
  modified, consumed, or reserved again by a different save operation;
- ``commit_save`` records the replay tombstone (the draft is now consumed) after
  the caller persisted the authoritative snapshot;
- ``release_save`` returns a reserved draft to the usable pool with its payload
  and revision untouched after a persistence failure.

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
from copy import deepcopy
from dataclasses import dataclass
from secrets import token_urlsafe
from threading import RLock
from time import monotonic
from typing import Any

#: Reason codes returned by the store so routes can pick a stable error type.
REASON_OK = "ok"
REASON_EXPIRED = "expired"
REASON_EVICTED = "evicted"
REASON_REPLAYED = "replayed"
REASON_REVISION_CONFLICT = "revision_conflict"
REASON_RESERVED = "reserved"
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
    #: When truthy the draft is reserved by a save-in-progress (US-212). A
    #: reserved entry is skipped by purge/eviction and rejected by
    #: get/compare_and_swap/update/consume so a persistence attempt owns the
    #: exact payload/revision it is about to write.
    reserved: bool = False


class DraftStore:
    """Bounded, expiring, save-lifecycle store for unsaved preview drafts.

    ``issue`` stores a generated draft and returns a ``DraftHandle`` carrying
    the opaque ``draft_id`` and ``revision=1``. ``get`` reads a draft for
    dry-run modification without consuming it, returning both the payload and
    its current revision. ``consume_for_save`` atomically removes and returns a
    draft, so a saved draft can never be saved twice (replay protection).

    Updates go through ``compare_and_swap``: the caller supplies the
    ``base_revision`` it last observed, and the store replaces the payload
    atomically (bumping the revision by 1) only when the base matches the
    current revision. A stale base leaves the payload and revision untouched.

    Saving uses the US-212 reservation lifecycle so a failed disk write never
    destroys the draft:

    - ``reserve_for_save`` validates ``draft_id`` + ``base_revision`` and pins
      the draft; while reserved the draft cannot be modified, consumed, purged,
      evicted, or reserved again, so the exact payload/revision being persisted
      stays stable;
    - ``commit_save`` turns the reservation into the replay tombstone (the
      caller has persisted the Request — a later save of the same id is
      ``replayed``);
    - ``release_save`` drops the reservation and keeps the draft usable with
      its payload and revision untouched (the persistence failed).

    Lookups return a ``(value_or_None, reason)`` tuple so the routes can map
    the failure to a stable 409 ``draft_*`` error type:

    - ``expired``            — the draft lived past its TTL (or was purged);
    - ``evicted``            — the draft was evicted because the store was full;
    - ``replayed``           — the draft id was consumed by a previous save;
    - ``revision_conflict``  — the caller's ``base_revision`` is stale;
    - ``reserved``           — a save-in-progress owns the draft (US-212);
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
        # Flask may serve multiple requests concurrently.  Every lifecycle
        # transition must therefore share one lock; otherwise two writers can
        # both observe the same revision and both report a successful CAS.
        self._lock = RLock()
        self._entries: OrderedDict[str, _DraftEntry] = OrderedDict()
        #: Tombstones for ids that disappeared: draft_id -> (reason, at).
        #: ``replayed`` for a consumed save, ``expired``/``evicted`` for a
        #: purge/eviction. Bounded by the same TTL; purged on access.
        self._tombstones: dict[str, tuple[str, float]] = {}

    # -- lifecycle ----------------------------------------------------------

    def issue(self, request: dict[str, Any]) -> DraftHandle:
        """Store ``request`` and return a handle with an opaque id, revision 1.

        Evicts expired entries first, then the oldest **unreserved** entry when
        at capacity (a reserved draft is never evicted mid-save).
        """
        with self._lock:
            self._purge()
            while len(self._entries) >= self._max_entries:
                # Evict the oldest *unreserved* entry. A reserved draft is
                # pinned mid-save and must never disappear under the caller;
                # when every entry is reserved the store allows a transient
                # over-capacity entry until one reservation resolves.
                evictable = next(
                    (
                        candidate_id
                        for candidate_id, entry in self._entries.items()
                        if not entry.reserved
                    ),
                    None,
                )
                if evictable is None:
                    break
                del self._entries[evictable]
                self._tombstones[evictable] = (REASON_EVICTED, self._now())
            draft_id = token_urlsafe(24)
            now = self._now()
            self._entries[draft_id] = _DraftEntry(
                request=deepcopy(request),
                revision=1,
                created_at=now,
                used_at=now,
            )
            return DraftHandle(draft_id=draft_id, revision=1)

    def peek(self, draft_id: str | None) -> tuple[dict[str, Any] | None, str]:
        """Observe a draft with **no side effect** (US-213 fix).

        Unlike ``get`` this never refreshes ``used_at``, never moves the entry
        within the LRU order, and never touches tombstones — it is a pure
        observation used to compare a *terminal* idempotency record's
        fingerprint against a still-present draft without consuming, reserving
        or pinning it. A reserved draft is reported ``reserved`` (a
        save-in-progress owns it); a missing id reports the tombstone reason
        (``replayed`` after a successful save, ``expired``/``evicted`` when
        purged/evicted, otherwise ``unknown``). The caller maps every
        non-``ok`` reason to "no live draft to verify".
        """
        with self._lock:
            self._purge()
            if not draft_id:
                return None, REASON_UNKNOWN
            entry = self._entries.get(draft_id)
            if entry is None:
                return None, self._missing_reason(draft_id)
            if entry.reserved:
                return None, REASON_RESERVED
            return deepcopy(entry.request), REASON_OK

    def get(self, draft_id: str | None) -> tuple[DraftRead | None, str]:
        """Return ``(DraftRead, reason)`` for a dry-run modify (never consumes).

        Reading refreshes ``used_at`` (recently-modified drafts stay alive),
        but does not invalidate the entry. A missing id is reported as
        ``replayed`` when it was consumed by an earlier save, ``expired``/
        ``evicted`` when it was purged/evicted, otherwise ``unknown``.
        """
        with self._lock:
            self._purge()
            if not draft_id:
                return None, REASON_UNKNOWN
            entry = self._entries.get(draft_id)
            if entry is None:
                return None, self._missing_reason(draft_id)
            if entry.reserved:
                # A save-in-progress owns the exact payload/revision it is
                # persisting; a concurrent dry-run modify must not read against
                # it (US-212).
                return None, REASON_RESERVED
            self._entries.move_to_end(draft_id)
            self._entries[draft_id] = _DraftEntry(
                request=entry.request,
                revision=entry.revision,
                created_at=entry.created_at,
                used_at=self._now(),
            )
            return (
                DraftRead(request=deepcopy(entry.request), revision=entry.revision),
                REASON_OK,
            )

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
        with self._lock:
            self._purge()
            if not draft_id:
                return None, REASON_UNKNOWN
            entry = self._entries.get(draft_id)
            if entry is None:
                return None, self._missing_reason(draft_id)
            if entry.reserved:
                # The save-in-progress pins the payload/revision; a concurrent
                # modify must not move the revision out from under it (US-212).
                return None, REASON_RESERVED
            if entry.revision != base_revision:
                return None, REASON_REVISION_CONFLICT
            new_revision = entry.revision + 1
            now = self._now()
            self._entries[draft_id] = _DraftEntry(
                request=deepcopy(request),
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
        with self._lock:
            self._purge()
            if not draft_id:
                return None, REASON_UNKNOWN
            entry = self._entries.pop(draft_id, None)
            if entry is None:
                return None, self._missing_reason(draft_id)
            if entry.reserved:
                # Never consume a draft a save-in-progress owns (US-212): the
                # reserved entry must be committed/released by its reservation,
                # not double-saved by a concurrent consumer.
                self._entries[draft_id] = entry
                return None, REASON_RESERVED
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
        with self._lock:
            self._purge()
            if not draft_id:
                return False
            entry = self._entries.get(draft_id)
            if entry is None:
                return False
            if entry.reserved:
                return False
            new_revision = entry.revision + 1
            now = self._now()
            self._entries[draft_id] = _DraftEntry(
                request=deepcopy(request),
                revision=new_revision,
                created_at=entry.created_at,
                used_at=now,
            )
            self._entries.move_to_end(draft_id)
            return True

    # -- US-212 reservation lifecycle --------------------------------------

    def reserve_for_save(
        self,
        draft_id: str | None,
        base_revision: int,
    ) -> tuple[dict[str, Any] | None, str]:
        """Pin a draft for persistence iff ``base_revision`` is still current.

        Returns the authoritative ``(request, REASON_OK)`` the caller must
        persist. A stale revision returns ``revision_conflict`` (nothing is
        changed); an expired/evicted/replayed/unknown id returns the matching
        ``draft_*`` reason. While reserved the entry is invisible to
        get/compare_and_swap/update/consume and is skipped by purge/eviction so
        the caller persists a stable payload/revision. The reservation is
        resolved by ``commit_save`` (success) or ``release_save`` (failure).
        """
        with self._lock:
            self._purge()
            if not draft_id:
                return None, REASON_UNKNOWN
            entry = self._entries.get(draft_id)
            if entry is None:
                return None, self._missing_reason(draft_id)
            if entry.reserved:
                return None, REASON_RESERVED
            if entry.revision != base_revision:
                return None, REASON_REVISION_CONFLICT
            self._entries[draft_id] = _DraftEntry(
                request=entry.request,
                revision=entry.revision,
                created_at=entry.created_at,
                used_at=self._now(),
                reserved=True,
            )
            self._entries.move_to_end(draft_id)
            return deepcopy(entry.request), REASON_OK

    def commit_save(self, draft_id: str | None) -> None:
        """Record the replay tombstone for a reservation whose Request persisted.

        After commit the draft is consumed: a later save of the same id is
        reported ``replayed``. A draft that is no longer reserved (already
        committed/released/cleared) is a no-op so an interrupted save can never
        poison another save's outcome.
        """
        with self._lock:
            if not draft_id:
                return
            entry = self._entries.get(draft_id)
            if entry is None or not entry.reserved:
                return
            del self._entries[draft_id]
            self._tombstones[draft_id] = (REASON_REPLAYED, self._now())

    def release_save(self, draft_id: str | None) -> None:
        """Unpin a reservation after a persistence failure, keeping the draft.

        The draft's payload and revision are untouched, so the same
        ``draft_id``/``base_revision`` can be retried and the user never loses
        their edit. A draft that is no longer reserved is a no-op.
        """
        with self._lock:
            if not draft_id:
                return
            entry = self._entries.get(draft_id)
            if entry is None or not entry.reserved:
                return
            self._entries[draft_id] = _DraftEntry(
                request=entry.request,
                revision=entry.revision,
                created_at=entry.created_at,
                used_at=self._now(),
            )
            self._entries.move_to_end(draft_id)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._tombstones.clear()

    def __len__(self) -> int:
        with self._lock:
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
            if entry.reserved:
                # A save-in-progress pins the draft even past its TTL; the TTL
                # resumes after commit/release. This prevents a long persist
                # from having its draft purged mid-write.
                continue
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
