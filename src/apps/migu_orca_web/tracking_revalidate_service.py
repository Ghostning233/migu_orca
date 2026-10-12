from __future__ import annotations

"""Pure-local pre-submit revalidation orchestration (US-224).

``POST /api/v1/tracking/items/{tracking_id}/revalidate`` is a revision-aware,
pure-local check: it never accepts ``ab_config``, never probes connections and
never contacts an external system.  This module is the Web-service layer that

1. re-runs the historical-backfill coordinator (every tracking API access does);
2. loads the TrackingRecord and guards ``expected_revision`` (409
   ``tracking_revision_conflict``) and the current tracking status (409
   ``tracking_state_conflict``);
3. loads the *fresh* local Request (missing/damaged degrades to a
   ``REQUEST_MISSING`` business issue, never a path/raw leak) plus the current
   operation's non-terminal state;
4. runs the pure ``classify_revalidation`` checklist against the re-read
   Request — the server never trusts a browser-supplied fingerprint;
5. persists the resulting state transition atomically (status + audit +
   revision through one CAS) and returns the safe §11.5 payload.

State semantics (Stage 29 PRD §7.2/§8.3/§11.5): a business failure moves
``PENDING_SUBMIT``/``SUBMIT_FAILED`` to ``NEEDS_RECONFIRM`` (+1 revision +
audit); a passing check moves ``NEEDS_RECONFIRM`` back to ``PENDING_SUBMIT``.
Passing checks on ``PENDING_SUBMIT``/``SUBMIT_FAILED`` and failing checks that
are already on ``NEEDS_RECONFIRM`` are *unchanged* re-checks, so they neither
bump the revision nor duplicate an audit event (§9: 不记录无变化复核).  The
stored ``request_fingerprint`` is deliberately **not** updated here — adopting a
changed plan is the user's ``confirm=true`` submit decision (US-225), so a
changed plan keeps reporting ``REQUEST_CHANGED`` until it is confirmed.
"""

from typing import Any

from apps.migu_orca_web.save_confirm_service import compute_request_fingerprint
from apps.migu_orca_web.tracking_migration_service import run_tracking_migration
from apps.migu_orca_web.tracking_serializers import (
    safe_valid_resource_count,
    tracking_available_actions,
    tracking_summary_fields,
)
from shared.errors import Stage1Error
from storage_engine.controllers.operation_repository import load_tracking_operation
from storage_engine.controllers.request_repository import load_request_snapshot
from storage_engine.controllers.storage_config import StorageConfig
from storage_engine.controllers.tracking_repository import (
    compare_and_swap_tracking_record,
    load_tracking_record,
)
from tracking_engine.controllers.revalidate import (
    REVALIDATABLE_STATUSES,
    REVALIDATE_ISSUE_REQUEST_CHANGED,
    RevalidationEvidence,
    RevalidationIssue,
    classify_revalidation,
)
from tracking_engine.models.operation import TRACKING_OPERATION_TERMINAL_STATES
from tracking_engine.models.tracking import (
    TRACKING_AUDIT_ACTOR_SYSTEM,
    TRACKING_AUDIT_PLAN_CHANGE_DETECTED,
    TRACKING_AUDIT_REVALIDATION_FAILED,
    TRACKING_AUDIT_REVALIDATION_PASSED,
    TRACKING_STATUS_NEEDS_RECONFIRM,
    TRACKING_STATUS_PENDING_SUBMIT,
    TrackingRecord,
    transition_record,
    utc_now,
)

#: Fixed safe message written when a passing revalidate re-arms a
#: ``NEEDS_RECONFIRM`` record for submission.
_REVALIDATION_PASSED_MESSAGE = "本地方案复核通过，可以提交追番"


def run_tracking_revalidate(
    config: StorageConfig,
    *,
    tracking_id: str,
    expected_revision: int,
    now: str | None = None,
) -> dict[str, Any]:
    """Run the pure-local revalidation for one tracking item.

    ``expected_revision`` must equal the current record revision (revision-aware
    compare, US-224).  A business failure is *not* an HTTP failure: it returns
    ``ready=False`` with the fixed §11.5 issue list and the record moved to
    ``NEEDS_RECONFIRM``.  Only revision/state conflicts raise.
    """
    run_tracking_migration(config=config)

    timestamp = now or utc_now()
    record = load_tracking_record(config, tracking_id)
    checked_revision = record.revision
    _guard_expected_revision(expected_revision, record)

    if record.status not in REVALIDATABLE_STATUSES:
        _raise_state_conflict(record)

    request = _tolerant_load_request(config, record)
    current_fingerprint = (
        compute_request_fingerprint(request) if isinstance(request, dict) else None
    )
    evidence = RevalidationEvidence(
        request=request,
        request_fingerprint=current_fingerprint,
        operation_in_progress=_operation_in_progress(config, record),
    )
    issues = classify_revalidation(record, evidence)
    ready = not issues

    next_record, transitioned = _apply_outcome(record, issues, timestamp)
    if transitioned:
        next_record = compare_and_swap_tracking_record(
            config,
            next_record.tracking_id,
            base_revision=checked_revision,
            record=next_record,
        )

    return _result_payload(
        record=next_record,
        checked_revision=checked_revision,
        ready=ready,
        issues=issues,
        request=request,
        checked_at=timestamp,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _guard_expected_revision(expected_revision: int, record: TrackingRecord) -> None:
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
        raise Stage1Error(
            "tracking_revision_conflict",
            "expected_revision 必须是正整数",
            "tracking_revalidate",
            {"field": "expected_revision", "current_revision": record.revision},
        )
    if expected_revision != record.revision:
        raise Stage1Error(
            "tracking_revision_conflict",
            "追番记录版本已变化，请刷新后重试",
            "tracking_revalidate",
            {
                "field": "expected_revision",
                "expected_revision": expected_revision,
                "current_revision": record.revision,
            },
        )


def _raise_state_conflict(record: TrackingRecord) -> None:
    action_codes = [
        action.get("code")
        for action in tracking_available_actions(record.status)
        if isinstance(action.get("code"), str)
    ]
    raise Stage1Error(
        "tracking_state_conflict",
        "当前追番记录状态不允许复核",
        "tracking_revalidate",
        {
            "field": "status",
            "current_status": record.status,
            "available_actions": action_codes,
        },
    )


def _tolerant_load_request(
    config: StorageConfig,
    record: TrackingRecord,
) -> dict[str, Any] | None:
    """Load the fresh Request, or None when it is missing/damaged.

    A missing/damaged Request is a legitimate ``REQUEST_MISSING`` business issue
    for revalidation (never a path/raw-JSON leak), so storage failures are
    folded into ``None`` here.
    """
    if not record.request_id:
        return None
    try:
        loaded = load_request_snapshot(config, record.request_id)
        return loaded if isinstance(loaded, dict) else None
    except Stage1Error:
        return None


def _operation_in_progress(config: StorageConfig, record: TrackingRecord) -> bool:
    """Return whether the record's current operation is still in flight.

    A referenced operation that cannot be read is treated as in flight
    (conservative): revalidation must not mask an operation whose outcome is
    unknown — the plan must be resolved through submit/retry/recover instead.
    """
    operation_id = record.current_operation_id
    if not operation_id:
        return False
    try:
        operation = load_tracking_operation(config, operation_id)
    except Stage1Error:
        return True
    return operation.state not in TRACKING_OPERATION_TERMINAL_STATES


def _apply_outcome(
    record: TrackingRecord,
    issues: tuple[RevalidationIssue, ...],
    timestamp: str,
) -> tuple[TrackingRecord, bool]:
    """Return ``(record_to_persist, needs_cas)`` for one revalidate outcome.

    - Passing + ``NEEDS_RECONFIRM`` → ``PENDING_SUBMIT`` (+1, audit).
    - Failing + not already ``NEEDS_RECONFIRM`` → ``NEEDS_RECONFIRM`` (+1,
      audit).  ``REQUEST_CHANGED`` uses the ``PLAN_CHANGE_DETECTED`` audit
      action; other business failures use ``REVALIDATION_FAILED``.
    - Any other combination is an unchanged re-check (no state change, no
      revision bump, no audit).
    """
    if not issues:
        if record.status == TRACKING_STATUS_NEEDS_RECONFIRM:
            return (
                transition_record(
                    record,
                    status=TRACKING_STATUS_PENDING_SUBMIT,
                    audit_action=TRACKING_AUDIT_REVALIDATION_PASSED,
                    audit_actor=TRACKING_AUDIT_ACTOR_SYSTEM,
                    safe_message=_REVALIDATION_PASSED_MESSAGE,
                    now=timestamp,
                ),
                True,
            )
        return record, False

    if record.status == TRACKING_STATUS_NEEDS_RECONFIRM:
        # Already needs re-confirmation: this is an unchanged re-check.
        return record, False

    primary = issues[0]
    audit_action = (
        TRACKING_AUDIT_PLAN_CHANGE_DETECTED
        if any(issue.code == REVALIDATE_ISSUE_REQUEST_CHANGED for issue in issues)
        else TRACKING_AUDIT_REVALIDATION_FAILED
    )
    return (
        transition_record(
            record,
            status=TRACKING_STATUS_NEEDS_RECONFIRM,
            audit_action=audit_action,
            audit_actor=TRACKING_AUDIT_ACTOR_SYSTEM,
            reason_code=primary.code,
            safe_message=primary.message,
            now=timestamp,
        ),
        True,
    )


def _result_payload(
    *,
    record: TrackingRecord,
    checked_revision: int,
    ready: bool,
    issues: tuple[RevalidationIssue, ...],
    request: dict[str, Any] | None,
    checked_at: str,
) -> dict[str, Any]:
    """Build the safe §11.5 revalidate result (HTTP 200 for business results)."""
    valid_count = safe_valid_resource_count(request)
    return {
        "tracking_id": record.tracking_id,
        "ready": ready,
        "checked_revision": checked_revision,
        "next_revision": record.revision,
        "checked_at": checked_at,
        "next_status": record.status,
        "issues": [
            {
                "code": issue.code,
                "field": issue.field,
                "message": issue.message,
                "recovery_action": issue.recovery_action,
            }
            for issue in issues
        ],
        "tracking": tracking_summary_fields(record, valid_resource_count=valid_count),
    }


__all__ = ["run_tracking_revalidate"]
