from __future__ import annotations

"""Live accept/save-confirm -> TrackingRecord handoff (US-222).

Stage 29 unifies the pre-submit entry points: the moment a Request becomes
``ACCEPTED`` through the single request accept entry, the single save-confirm
endpoint, a batch save-confirm item or a save-confirm terminal replay, this
module calls ``ensure_tracking_record`` so the same Request always converges to
the same deterministic ``tracking_id`` whether it was created live, by a
replayed terminal outcome, or by the historical migration.

Contract (Stage 29 PRD §12)
---------------------------
- ``ensure_confirmed_request_tracking`` returns a ``TrackingHandoff`` and never
  raises for a *tracking* persistence failure: a confirmed Request must never
  be rolled back because its tracking record could not be written, and a
  tracking state is never faked — ``tracking_ready=False`` with a fixed safe
  message tells the client the record will be recovered on the next access.
- A fresh record starts at ``PENDING_SUBMIT`` (the plan is confirmed but has
  never been submitted); an existing record (from an earlier entry point or the
  migration) is returned unchanged by ``ensure`` — first writer wins, and
  re-running never adds records, changes ids/revisions or duplicates audits.
- The record stores only whitelisted non-sensitive fields; ``plan_summary`` is
  built by the same safe extraction the migration uses, and ``tracking_id`` is
  always the deterministic id derived from the public ``request_id``.
"""

from dataclasses import dataclass
from typing import Any

from apps.migu_orca_web.save_confirm_service import compute_request_fingerprint
from request_engine.controllers.request_controller import ACCEPTED
from shared.errors import Stage1Error
from storage_engine.controllers.storage_config import StorageConfig
from storage_engine.controllers.tracking_repository import ensure_tracking_record
from tracking_engine.controllers.migration import plan_summary_from_request
from tracking_engine.models.tracking import (
    TRACKING_AUDIT_ACTOR_USER,
    TRACKING_AUDIT_TRACKING_CREATED,
    TRACKING_STATUS_PENDING_SUBMIT,
    create_tracking_record,
    tracking_id_for_request,
)

#: Fixed safe message returned when a confirmed Request's tracking record could
#: not be written (Stage 29 PRD §12).  It never exposes a path/file/request id
#: and promises the record will be recovered on a later tracking access.
TRACKING_HANDOFF_RETRY_MESSAGE = "方案已保存，追番列表将在打开时自动恢复"


@dataclass(frozen=True)
class TrackingHandoff:
    """Public tracking handoff for a confirmed Request (US-222).

    ``tracking_id`` is always the deterministic id derived from the Request id,
    so even a failed write still hands the client a stable identity to address
    later accesses.  ``tracking_status`` is ``None`` (never faked) when the
    record could not be read/written; ``tracking_ready`` distinguishes a usable
    record from one that must be recovered.
    """

    tracking_id: str
    tracking_status: str | None
    tracking_ready: bool
    safe_message: str | None


def ensure_confirmed_request_tracking(
    *,
    config: StorageConfig,
    request: dict[str, Any],
    origin: str,
    now: str | None = None,
) -> TrackingHandoff:
    """Ensure a deterministic TrackingRecord exists for an ACCEPTED Request.

    The caller must already have durably confirmed the Request (ACCEPTED);
    this function never rolls that confirmation back.  A fresh record is
    created with ``origin`` and ``PENDING_SUBMIT``; an existing record is left
    untouched.  A tracking persistence failure (damaged/absent storage) returns
    a not-ready handoff instead of raising, so the confirmed Request still
    succeeds.
    """
    request_id = request.get("request_id")
    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("cannot track a Request without a non-empty request_id")
    if request.get("status") != ACCEPTED:
        raise ValueError("only an ACCEPTED Request may enter the tracking handoff")

    fingerprint = compute_request_fingerprint(request)
    record = create_tracking_record(
        request_id=request_id.strip(),
        status=TRACKING_STATUS_PENDING_SUBMIT,
        plan_summary=plan_summary_from_request(request),
        origin=origin,
        request_fingerprint=fingerprint,
        audit_action=TRACKING_AUDIT_TRACKING_CREATED,
        audit_actor=TRACKING_AUDIT_ACTOR_USER,
        now=now,
    )
    try:
        ensured, _created = ensure_tracking_record(config, record)
    except Stage1Error:
        # The confirmed Request stays confirmed.  Do not fake a tracking state:
        # report not-ready with the fixed recovery message; a later tracking
        # access re-runs ensure and heals the record.
        return unavailable_tracking_handoff(request_id)

    return TrackingHandoff(
        tracking_id=ensured.tracking_id,
        tracking_status=ensured.status,
        tracking_ready=True,
        safe_message=None,
    )


def unavailable_tracking_handoff(request_id: str) -> TrackingHandoff:
    """Return the not-ready handoff for a Request whose record cannot be written.

    The tracking_id is still the deterministic id derived from ``request_id``
    (a stable identity, not a faked status); ``tracking_status`` stays None and
    ``safe_message`` carries the fixed recovery copy.
    """
    tracking_id = tracking_id_for_request(request_id)
    return TrackingHandoff(
        tracking_id=tracking_id,
        tracking_status=None,
        tracking_ready=False,
        safe_message=TRACKING_HANDOFF_RETRY_MESSAGE,
    )


__all__ = [
    "TRACKING_HANDOFF_RETRY_MESSAGE",
    "TrackingHandoff",
    "ensure_confirmed_request_tracking",
    "unavailable_tracking_handoff",
]
