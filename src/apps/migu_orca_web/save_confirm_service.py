from __future__ import annotations

"""Save-confirm idempotency protocol (US-213).

Stage 28's single/batch save-confirm composition (US-214/US-216) must be safe
to retry when the response is lost or the process restarts. The in-process
``DraftStore`` replay tombstone only protects *one process lifetime*; after a
restart the draft is gone and an unguarded retried save would create a
duplicate Request. This module implements the durable idempotency protocol on
top of ``storage_engine.controllers.idempotency_repository``:

- ``compute_request_fingerprint`` reduces a Request to a one-way digest over a
  canonical whitelist of *business* fields (status, raw title, matched title,
  selected subtitle group, filter rule, expected folder name). RSS/magnet URLs,
  seed names, credentials, raw responses and absolute paths never participate,
  and the digest is what the record stores — never the payload.
- ``run_save_confirm`` is the durable coordinator. Given injected seams for
  draft reservation, PENDING persistence and acceptance confirmation, it:
  1. replays a terminal record (``CONFIRMED`` / ``SAVED_CONFIRM_FAILED``) so a
     retry returns the same public outcome and never touches the draft;
  2. resolves an ``IN_PROGRESS`` retry against the on-disk Request first
     (rule 3 of the Stage 28 PRD §7) — never unconditionally creating a new
     Request;
  3. reserves the draft, binds the key to the operation + fingerprint (a reused
     key bound to a different operation/payload is a 409
     ``idempotency_conflict``), persists the Request, then confirms and records
     ``CONFIRMED``. The durable record stays ``IN_PROGRESS`` (with the public
     ``request_id`` bound) from the first durable write until the confirmation
     lands, so a crash mid-way is reconciled against the on-disk Request on the
     next retry; a confirmation failure transitions the record to
     ``SAVED_CONFIRM_FAILED`` and the client retries with the accept action.

Concurrency
-----------
The storage profile is served by a single process (no DB / multi-user /
remote — Stage 28 non-goals), so same-key save-confirm attempts are serialized
by an in-process key lock while cross-restart safety comes from the durable
record + ``resolve_in_progress_retry``.
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import Any

from request_engine.controllers.request_controller import summarize_request
from shared.errors import Stage1Error
from storage_engine.controllers.idempotency_repository import (
    IDEMPOTENCY_OPERATION_SAVE_CONFIRM,
    IDEMPOTENCY_STATE_CONFIRMED,
    IDEMPOTENCY_STATE_IN_PROGRESS,
    IDEMPOTENCY_STATE_SAVED_CONFIRM_FAILED,
    create_idempotency_record,
    load_idempotency_record,
    save_idempotency_record,
)
from storage_engine.controllers.request_repository import load_request_snapshot
from storage_engine.controllers.storage_config import StorageConfig

OPERATION_SAVE_CONFIRM = IDEMPOTENCY_OPERATION_SAVE_CONFIRM

STATE_IN_PROGRESS = IDEMPOTENCY_STATE_IN_PROGRESS
STATE_SAVED_CONFIRM_FAILED = IDEMPOTENCY_STATE_SAVED_CONFIRM_FAILED
STATE_CONFIRMED = IDEMPOTENCY_STATE_CONFIRMED

#: Stable public strings for the save-confirm HTTP contract (US-214). The
#: frontend branches on these; they are frozen by golden/DTO tests.
HANDOFF_STATUS_ACCEPTED = "ACCEPTED"
HANDOFF_NEXT_ACTION_OPEN_TRACKING = "OPEN_TRACKING"
RETRY_ACTION_ACCEPT_SAVED_REQUEST = "ACCEPT_SAVED_REQUEST"
ERROR_TYPE_SAVE_CONFIRM_FAILED = "save_confirm_failed"

_TERMINAL_STATES = frozenset({STATE_SAVED_CONFIRM_FAILED, STATE_CONFIRMED})


@dataclass(frozen=True)
class SaveConfirmOutcome:
    """Public outcome of one save-confirm attempt.

    ``outcome`` is ``CONFIRMED`` or ``SAVED_CONFIRM_FAILED``; ``request_id`` is
    always the public saved Request id once one exists. ``request`` /
    ``summary`` carry the final saved Request (``ACCEPTED`` on CONFIRMED, the
    persisted ``PENDING_CONFIRM`` when confirmation is still failing).
    ``replayed`` is True when the outcome came from an earlier durable record
    (no new work was done), so the HTTP layer can reuse it verbatim.
    """

    outcome: str
    request_id: str | None
    request: dict[str, Any] | None
    summary: dict[str, Any] | None
    replayed: bool = False


#: In-process per-key locks. The storage profile is single-process, so this
#: serializes concurrent same-key attempts (a different-payload concurrent
#: reuse is the ``idempotency_conflict`` case) while cross-restart safety comes
#: from the durable record.
_KEY_LOCK_GUARD: RLock = RLock()
_KEY_LOCKS: dict[str, RLock] = {}


def compute_request_fingerprint(request: dict[str, Any]) -> str:
    """Return a one-way digest over a Request's canonical business identity.

    The same re-generated plan (same raw title + matched title + chosen group /
    filter / folder) produces the same digest, while a genuinely different plan
    produces a different one. The digest intentionally excludes ``request_id``
    (a regenerated draft is the same user operation) and every sensitive field
    (RSS/magnet URLs, seed names, credentials, raw responses, absolute paths).
    """
    source_info = request.get("source_info") or {}
    matched = source_info.get("matched_bangumi") or {}
    confirmable = request.get("confirmable_config") or {}
    filter_rule = confirmable.get("filter_rule") or {}

    canonical = {
        "status": request.get("status"),
        "raw_title": (request.get("input") or {}).get("raw_title"),
        "bangumi_title": matched.get("title"),
        "selected_subtitle_group": confirmable.get("selected_subtitle_group"),
        "filter_rule": {
            "must_contain": filter_rule.get("must_contain"),
            "must_not_contain": filter_rule.get("must_not_contain"),
            "use_regex": filter_rule.get("use_regex"),
            "case_sensitive": filter_rule.get("case_sensitive"),
        },
        "expected_folder_name": confirmable.get("expected_folder_name"),
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def resolve_in_progress_retry(
    *,
    config: StorageConfig,
    record: dict[str, Any],
) -> dict[str, Any]:
    """Decide how an ``IN_PROGRESS`` save-confirm retry must proceed.

    Rule 3 of the Stage 28 PRD §7: never unconditionally create a new Request.
    When the record already references a Request that is on disk the save has
    landed and the caller should continue the confirmation; otherwise the
    caller may retry the save only while it still holds a valid draft
    reservation.

    Returns ``{"action": "continue_confirm", "request_id": id}`` or
    ``{"action": "retry_save", "request_id": id-or-None}``. Storage/JSON
    failures propagate (a damaged record is never silently treated as missing).
    """
    request_id = (record.get("request_id") or "").strip() or None
    if request_id is None:
        return {"action": "retry_save", "request_id": None}
    try:
        load_request_snapshot(config, request_id)
    except Stage1Error as exc:
        if exc.error_type == "request_not_found":
            return {"action": "retry_save", "request_id": request_id}
        raise
    return {"action": "continue_confirm", "request_id": request_id}


def run_save_confirm(
    *,
    config: StorageConfig,
    idempotency_key: str,
    reserve_draft: Callable[[], dict[str, Any]],
    persist_pending: Callable[[dict[str, Any]], dict[str, Any]],
    confirm_saved: Callable[[str], dict[str, Any]],
    commit_draft: Callable[[], None],
    release_draft: Callable[[], None],
    now: str | None = None,
) -> SaveConfirmOutcome:
    """Run one durable save-confirm attempt under ``idempotency_key``.

    Injected seams (US-214 wires the real DraftStore/entry-controller flow):
    - ``reserve_draft`` returns the authoritative PENDING_CONFIRM draft and
      raises a ``Stage1Error`` when the draft is stale/expired/replayed/
      reserved (the caller maps DraftStore reasons);
    - ``persist_pending(request)`` writes the PENDING_CONFIRM snapshot and
      returns a dict that carries the saved Request (its ``request_id`` must
      equal the draft's ``request_id``);
    - ``confirm_saved(request_id)`` idempotently accepts the saved Request and
      returns the updated ACCEPTED Request (an already-ACCEPTED request is a
      success, not a failure);
    - ``commit_draft`` / ``release_draft`` resolve the reservation.

    Terminal outcomes are replayed without touching the draft, so retrying a
    key after a process restart (when the in-memory DraftStore is empty) never
    creates a duplicate Request.
    """
    with _key_lock(idempotency_key):
        existing = load_idempotency_record(config, idempotency_key)

        # A bound key may never switch operations — even after a terminal state,
        # reusing the same key for a different operation is a 409 conflict.
        if existing is not None and existing.get("operation") != OPERATION_SAVE_CONFIRM:
            raise _idempotency_conflict(existing, "operation_mismatch")

        # 1. A bound key that already reached a terminal state is replayed.
        if existing is not None and existing.get("state") in _TERMINAL_STATES:
            return _terminal_outcome(config, existing, replayed=True)

        # 2. An IN_PROGRESS retry first checks the on-disk Request.
        if existing is not None and existing.get("state") == STATE_IN_PROGRESS:
            decision = resolve_in_progress_retry(config=config, record=existing)
            if decision["action"] == "continue_confirm":
                request_id = decision["request_id"]
                assert request_id is not None
                try:
                    accepted = confirm_saved(request_id)
                except Exception:
                    _update_state(
                        config, existing, STATE_SAVED_CONFIRM_FAILED, request_id, now
                    )
                    return _saved_confirm_failed_outcome(config, request_id)
                _update_state(config, existing, STATE_CONFIRMED, request_id, now)
                return _confirmed_outcome(accepted, request_id, replayed=True)
            # action == retry_save: the save never landed; fall through.

        # 3. Fresh attempt or a safe retry-save: reserve the draft to obtain the
        #    authoritative Request, bind the key, persist, then confirm.
        request = reserve_draft()
        request_id = _draft_request_id(request, "run_save_confirm")
        fingerprint = compute_request_fingerprint(request)

        if existing is not None:
            # IN_PROGRESS retry-save: same operation is mandatory and the plan
            # must be identical; a changed plan under one key is a conflict.
            if existing.get("request_fingerprint") != fingerprint:
                release_draft()
                raise _idempotency_conflict(existing, "payload_mismatch")
            # Re-arm the IN_PROGRESS record and bind the public request_id
            # *before* persisting. If the process crashes after the atomic
            # Request write but before the next durable update, the retry sees
            # request_id + IN_PROGRESS and resolves against the on-disk Request
            # (rule 3) instead of blindly re-saving a duplicate.
            record = _update_state(config, existing, STATE_IN_PROGRESS, request_id, now)
        else:
            record = create_idempotency_record(
                idempotency_key=idempotency_key,
                operation=OPERATION_SAVE_CONFIRM,
                request_fingerprint=fingerprint,
                request_id=request_id,
                state=STATE_IN_PROGRESS,
                now=now,
            )
            save_idempotency_record(config, record)

        try:
            persist_pending(request)
        except Exception:
            release_draft()
            raise

        try:
            accepted = confirm_saved(request_id)
        except Exception:
            # Never release the draft back: the Request is on disk, so a second
            # save of the same draft would duplicate it. The durable record
            # tells the client to ACCEPT the saved Request.
            commit_draft()
            record = _update_state(
                config, record, STATE_SAVED_CONFIRM_FAILED, request_id, now
            )
            return _saved_confirm_failed_outcome(config, request_id)

        commit_draft()
        _update_state(config, record, STATE_CONFIRMED, request_id, now)
        return _confirmed_outcome(accepted, request_id, replayed=False)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _key_lock(idempotency_key: str) -> RLock:
    with _KEY_LOCK_GUARD:
        lock = _KEY_LOCKS.get(idempotency_key)
        if lock is None:
            lock = _KEY_LOCKS[idempotency_key] = RLock()
        return lock


def _update_state(
    config: StorageConfig,
    record: dict[str, Any],
    state: str,
    request_id: str | None,
    now: str | None,
) -> dict[str, Any]:
    timestamp = now or datetime.now(UTC).isoformat()
    updated = {
        **record,
        "state": state,
        "request_id": request_id if request_id is not None else record.get("request_id"),
        "updated_at": timestamp,
    }
    save_idempotency_record(config, updated)
    return updated


def _terminal_outcome(
    config: StorageConfig,
    record: dict[str, Any],
    *,
    replayed: bool,
) -> SaveConfirmOutcome:
    request_id = (record.get("request_id") or "").strip() or None
    if record.get("state") == STATE_CONFIRMED:
        saved = _load_or_none(config, request_id)
        summary = summarize_request(saved) if saved is not None else None
        return SaveConfirmOutcome(
            outcome=STATE_CONFIRMED,
            request_id=request_id,
            request=saved,
            summary=summary,
            replayed=replayed,
        )
    return _saved_confirm_failed_outcome(config, request_id, replayed=replayed)


def _confirmed_outcome(
    accepted_request: dict[str, Any],
    request_id: str,
    *,
    replayed: bool,
) -> SaveConfirmOutcome:
    return SaveConfirmOutcome(
        outcome=STATE_CONFIRMED,
        request_id=request_id,
        request=accepted_request,
        summary=summarize_request(accepted_request),
        replayed=replayed,
    )


def _saved_confirm_failed_outcome(
    config: StorageConfig,
    request_id: str | None,
    *,
    replayed: bool = False,
) -> SaveConfirmOutcome:
    saved = _load_or_none(config, request_id)
    summary = summarize_request(saved) if saved is not None else None
    return SaveConfirmOutcome(
        outcome=STATE_SAVED_CONFIRM_FAILED,
        request_id=request_id,
        request=saved,
        summary=summary,
        replayed=replayed,
    )


def _load_or_none(
    config: StorageConfig,
    request_id: str | None,
) -> dict[str, Any] | None:
    if not request_id:
        return None
    try:
        return load_request_snapshot(config, request_id)
    except Stage1Error:
        return None


def _draft_request_id(request: dict[str, Any], failed_step: str) -> str:
    request_id = request.get("request_id")
    if not isinstance(request_id, str) or not request_id.strip():
        raise Stage1Error(
            "invalid_request_id",
            "订阅草案缺少有效 request_id",
            failed_step,
            {"field": "request_id"},
        )
    return request_id.strip()


def _idempotency_conflict(record: dict[str, Any], reason: str) -> Stage1Error:
    return Stage1Error(
        "idempotency_conflict",
        "相同的幂等键不能用于不同的保存确认操作",
        "save_confirm_idempotency",
        {"field": "idempotency_key", "reason": reason},
    )


def build_saved_confirm_failed_error(
    request_id: str,
    *,
    failed_step: str = "save_confirm",
) -> Stage1Error:
    """Build the SAVED_CONFIRM_FAILED failure envelope (US-214).

    The Request is already durable (PENDING_CONFIRM on disk) and only the
    acceptance/confirmation step failed. The error surfaces through the normal
    envelope with the PRD §6.3 ``error_data.details`` whitelist:
    ``{outcome, request_id, retry_action}`` — never the consumed draft_id or
    any draft content. The client retries confirmation through the existing
    Request accept endpoint (``ACCEPT_SAVED_REQUEST``).
    """
    return Stage1Error(
        ERROR_TYPE_SAVE_CONFIRM_FAILED,
        "订阅方案已保存但确认失败，请对已保存的方案重试确认",
        failed_step,
        {
            "outcome": STATE_SAVED_CONFIRM_FAILED,
            "request_id": request_id,
            "retry_action": RETRY_ACTION_ACCEPT_SAVED_REQUEST,
        },
    )


__all__ = [
    "OPERATION_SAVE_CONFIRM",
    "STATE_CONFIRMED",
    "STATE_IN_PROGRESS",
    "STATE_SAVED_CONFIRM_FAILED",
    "HANDOFF_STATUS_ACCEPTED",
    "HANDOFF_NEXT_ACTION_OPEN_TRACKING",
    "RETRY_ACTION_ACCEPT_SAVED_REQUEST",
    "ERROR_TYPE_SAVE_CONFIRM_FAILED",
    "SaveConfirmOutcome",
    "build_saved_confirm_failed_error",
    "compute_request_fingerprint",
    "resolve_in_progress_retry",
    "run_save_confirm",
]
