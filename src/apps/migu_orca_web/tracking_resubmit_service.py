"""Risk-confirmed single manual resubmission of a pending submission (issue #184).

``POST /api/v1/tracking/items/{tracking_id}/resubmit`` answers the second
question a user has about a 结果待确认 persistent submission: *the subscription
still cannot be proven — may I send this plan to Auto Bangumi again?*

The endpoint has exactly two phases and one endpoint purpose:

1. ``confirm=false`` runs the **same bounded read-only check** as issue #183
   (:func:`run_saved_tracking_check_locked`), through the Auto Bangumi instance
   the original operation was bound to.  When the exact subscription is proven,
   the record converges and **no external write happens**.  When it still cannot
   be proven, a resubmit is *offered* — with the proven reason class and the exact
   binding (record revision + original operation + bound connection generation) —
   and **nothing else is written externally**.
2. ``confirm=true`` is the user's explicit acceptance of the duplicate/resource
   risk (ADR-0002).  The server

   * refuses a stale confirmation: a changed revision, a different pending
     operation or a replaced/deleted saved connection raises before any read or
     write (409 ``tracking_resubmit_binding_conflict``);
   * re-runs the read-only check once more and converges with **zero external
     writes** if the subscription is now provable;
   * refuses to resubmit while an external write may still be running
     (``IN_PROGRESS``), while the bound connection is proven unusable
     (authentication/version/capability/connection) or while the local plan does
     not satisfy the submit preconditions — each with a proven, published reason;
   * otherwise records the user's verdict as a ``USER`` audit event and creates
     exactly **one** new operation whose ``previous_operation_id`` points at the
     operation the user confirmed against, then runs the existing
     ``_submit_through_external`` sequence exactly once.

Idempotency is server-owned: the new operation's idempotency key is derived from
the confirmed binding (tracking id + previous operation + confirmed revision +
connection generation), so a replay or a concurrent duplicate of the same
confirmation converges onto the very same operation and can never create a second
external call or subscription.  The pending original operation, its record
history and the audit trail are never rewritten or deleted.

The pending statuses this endpoint serves are the persistent-submit ones
(``VERIFYING_EXTERNAL``/``RECOVERY_REQUIRED``/``UNKNOWN``); a definite one-time
"download existing resources" failure keeps its own retry semantics (ADR-0001 is
unchanged).
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Any

from apps.migu_orca_web.save_confirm_service import compute_request_fingerprint
from apps.migu_orca_web.schemas import TrackingCheckPayload, TrackingResubmitPayload
from apps.migu_orca_web.services import _storage_dir
from apps.migu_orca_web.tracking_check_service import run_saved_tracking_check_locked
from apps.migu_orca_web.tracking_external_check import CheckPolicy, single_flight_check
from apps.migu_orca_web.tracking_serializers import (
    safe_valid_resource_count,
    tracking_summary_fields,
)
from apps.migu_orca_web.tracking_submission_service import (
    _find_operation,
    compose_tracking_readback_external,
    run_tracking_resubmit_after_risk_confirmation,
)
from shared.errors import Stage1Error
from storage_engine.controllers.autobangumi_config_repository import (
    AutoBangumiConfigRepository,
)
from storage_engine.controllers.operation_repository import load_tracking_operation
from storage_engine.controllers.request_repository import load_request_snapshot
from storage_engine.controllers.storage_config import StorageConfig, load_storage_config
from storage_engine.controllers.tracking_repository import (
    compare_and_swap_tracking_record,
    load_tracking_record,
)
from tracking_engine.controllers.revalidate import (
    REVALIDATE_ISSUE_REQUEST_CHANGED,
    RevalidationEvidence,
    RevalidationIssue,
    classify_revalidation,
)
from tracking_engine.controllers.submit import (
    CONFIRM_REASON_AMBIGUOUS,
    CONFIRM_REASON_AUTHENTICATION,
    CONFIRM_REASON_CAPABILITY,
    CONFIRM_REASON_CONNECTION,
    CONFIRM_REASON_CONNECTION_CHANGED,
    CONFIRM_REASON_NOT_FOUND,
    CONFIRM_REASON_UNREADABLE,
    CONFIRM_REASON_VERSION,
)
from tracking_engine.models.operation import (
    TRACKING_OPERATION_KIND_SUBMIT,
    TRACKING_OPERATION_STATE_IN_PROGRESS,
    TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
    TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
    TRACKING_OPERATION_TERMINAL_STATES,
    TRACKING_SUBMISSION_MODE_CONTINUE,
    TrackingOperation,
)
from tracking_engine.models.tracking import (
    TRACKING_AUDIT_ACTOR_USER,
    TRACKING_AUDIT_RESUBMIT_CONFIRMED,
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_DISABLED,
    TRACKING_STATUS_PENDING_SUBMIT,
    TrackingRecord,
    transition_record,
    utc_now,
)

_RESUBMIT_FAILED_STEP = "tracking_resubmit"

#: The check wording for a resubmit the user asked for but the server refused.
_RESUBMIT_AUDIT_MESSAGE = "用户已确认重复与资源处理风险，重新提交本地方案"

# -- published machine codes --------------------------------------------------
#: ``check_status`` of one resubmit response.
RESUBMIT_STATUS_CONFIRMED = "CONFIRMED"
RESUBMIT_STATUS_UNRESOLVED = "UNRESOLVED"
RESUBMIT_STATUS_BLOCKED = "BLOCKED"

#: The proven check reasons an explicit risk confirmation may override: the
#: subscription was not found, several objects are ambiguous, or the snapshot
#: could not be read at all. None of these authorize an *automatic* resubmit.
RESUBMIT_ALLOWED_REASONS = frozenset(
    {
        CONFIRM_REASON_NOT_FOUND,
        CONFIRM_REASON_AMBIGUOUS,
        CONFIRM_REASON_UNREADABLE,
    }
)

#: The proven reasons that forbid a resubmit outright: the bound connection or
#: its capabilities are proven unusable, so resubmitting cannot be the user's
#: next step (AC 6). ``CONNECTION_CHANGED`` means the bound generation is gone.
RESUBMIT_BLOCKED_REASONS = frozenset(
    {
        CONFIRM_REASON_CONNECTION_CHANGED,
        CONFIRM_REASON_AUTHENTICATION,
        CONFIRM_REASON_VERSION,
        CONFIRM_REASON_CAPABILITY,
        CONFIRM_REASON_CONNECTION,
    }
)

#: A resubmit refused because the durable external boundary was crossed and the
#: write may still be executing right now; only recovery may settle it first.
RESUBMIT_BLOCKED_EXTERNAL_WRITE_IN_PROGRESS = "EXTERNAL_WRITE_IN_PROGRESS"
#: A resubmit refused because the local plan fails the submit preconditions.
RESUBMIT_BLOCKED_PLAN_NOT_SUBMITTABLE = "PLAN_NOT_SUBMITTABLE"
#: A resubmit refused because the saved connection generation is gone/unusable.
RESUBMIT_BLOCKED_CONNECTION_CHANGED = "CONNECTION_CHANGED"
#: A resubmit refused because the saved connection cannot be resolved at all.
RESUBMIT_BLOCKED_CONFIG_ERROR = "CONFIG_ERROR"
#: A resubmit refused because the pending operation was a one-time
#: "download existing resources" request.  Issue #184 covers persistent
#: submissions only (ADR-0001/ADR-0002), so the feature never re-runs a one-time
#: collection under a risk confirmation.
RESUBMIT_BLOCKED_ONE_TIME_SUBMISSION = "ONE_TIME_SUBMISSION"
#: A resubmit refused because the unresolved check published no proven cause we
#: may act on; a fail-closed code that never doubles as an offerable reason.
RESUBMIT_BLOCKED_RESULT_UNPROVEN = "RESULT_UNPROVEN"


def resubmit_idempotency_key(
    *,
    tracking_id: str,
    previous_operation_id: str,
    expected_revision: int,
    connection_ref: str,
) -> str:
    """Derive the one operation key of a confirmation from its exact binding.

    The binding is the server-visible confirmation identity, so a replay or a
    concurrent duplicate of the same confirmation converges onto the same
    operation instead of minting a second one.  The namespace is versioned and
    the value stays a printable token (never a path, URL or credential).
    """
    digest = hashlib.sha256(
        "migu-orca/tracking-resubmit/v1\x00"
        f"{tracking_id}\x00{previous_operation_id}\x00{expected_revision}\x00{connection_ref}".encode()
    ).hexdigest()
    return f"resubmit-{digest[:32]}"


def run_saved_tracking_resubmit(
    payload: TrackingResubmitPayload,
    *,
    config_root: Any | None = None,
    repository: AutoBangumiConfigRepository | None = None,
    management_client: object | None = None,
    submit_one: Any | None = None,
    persist_ab_result: Any | None = None,
    readback_external: Any | None = None,
    read_policy: CheckPolicy | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Run the two-phase risk-confirmed resubmission for one tracking item."""
    config = load_storage_config(_storage_dir(payload.storage_dir))
    repository = repository or AutoBangumiConfigRepository(config_root)
    # One effective interaction per record: the read-only phase and the possible
    # write phase share one in-process guard, so a replay/second tab can neither
    # read twice nor start two submits for the same pending record.
    with single_flight_check(payload.tracking_id):
        if payload.confirm:
            return _confirmed_resubmit(
                config,
                payload,
                config_root=config_root,
                repository=repository,
                management_client=management_client,
                submit_one=submit_one,
                persist_ab_result=persist_ab_result,
                readback_external=readback_external,
                read_policy=read_policy,
                now=now,
            )
        return _check_only_resubmit(
            config,
            payload,
            config_root=config_root,
            management_client=management_client,
            read_policy=read_policy,
            now=now,
        )


# ---------------------------------------------------------------------------
# Phase 1: the read-only check that may offer (never perform) a resubmit
# ---------------------------------------------------------------------------


def _check_only_resubmit(
    config: StorageConfig,
    payload: TrackingResubmitPayload,
    *,
    config_root: Any | None,
    management_client: object | None,
    read_policy: CheckPolicy | None,
    now: str | None,
) -> dict[str, Any]:
    timestamp = now or utc_now()
    # Issue #184 review: the feature is scoped to persistent submissions, and the
    # server (not the page) enforces it — a one-time "download existing
    # resources" operation is refused before any read, so it can never converge
    # into a subscription nor re-run a collection.
    current = load_tracking_record(config, payload.tracking_id)
    _guard_expected_revision(payload.expected_revision, current)
    current_operation = _current_operation(config, current)
    if _is_one_time_submission(current_operation):
        return _resubmit_response(
            current,
            confirm=False,
            check_status=RESUBMIT_STATUS_BLOCKED,
            checked_revision=payload.expected_revision,
            timestamp=timestamp,
            blocked_reason=RESUBMIT_BLOCKED_ONE_TIME_SUBMISSION,
            operation_id=current_operation.operation_id if current_operation is not None else None,
        )
    check, plan_identity_changed = _run_identity_safe_check(
        payload,
        config_root=config_root,
        management_client=management_client,
        read_policy=read_policy,
        timestamp=timestamp,
    )
    record = load_tracking_record(config, payload.tracking_id)
    if plan_identity_changed:
        return _plan_identity_blocked_response(
            config, record, payload, confirm=False, timestamp=timestamp
        )
    assert check is not None
    if _check_confirmed(check):
        return _resubmit_response(
            record,
            confirm=False,
            check_status=RESUBMIT_STATUS_CONFIRMED,
            checked_revision=payload.expected_revision,
            timestamp=timestamp,
            check=check,
            operation_id=_check_operation_id(check),
        )
    operation = _current_operation(config, record)
    blocked = _blocked_reason_for_unresolved(check, operation)
    if blocked is not None:
        return _resubmit_response(
            record,
            confirm=False,
            check_status=RESUBMIT_STATUS_BLOCKED,
            checked_revision=payload.expected_revision,
            timestamp=timestamp,
            check=check,
            blocked_reason=blocked,
            operation_id=operation.operation_id if operation is not None else None,
        )
    assert operation is not None
    if not isinstance(operation.connection_ref, str) or not operation.connection_ref:
        # Defensive: a pending operation without a bound generation can never be
        # confirmed against an instance, so it is refused rather than rebound.
        return _resubmit_response(
            record,
            confirm=False,
            check_status=RESUBMIT_STATUS_BLOCKED,
            checked_revision=payload.expected_revision,
            timestamp=timestamp,
            check=check,
            blocked_reason=RESUBMIT_BLOCKED_CONNECTION_CHANGED,
            operation_id=operation.operation_id,
        )
    return _resubmit_response(
        record,
        confirm=False,
        check_status=RESUBMIT_STATUS_UNRESOLVED,
        checked_revision=payload.expected_revision,
        timestamp=timestamp,
        check=check,
        requires_risk_confirmation=True,
        binding=_binding(record, operation),
        operation_id=operation.operation_id,
    )


# ---------------------------------------------------------------------------
# Phase 2: the explicitly confirmed resubmission
# ---------------------------------------------------------------------------


def _confirmed_resubmit(
    config: StorageConfig,
    payload: TrackingResubmitPayload,
    *,
    config_root: Any | None,
    repository: AutoBangumiConfigRepository,
    management_client: object | None,
    submit_one: Any | None,
    persist_ab_result: Any | None,
    readback_external: Any | None,
    read_policy: CheckPolicy | None,
    now: str | None,
) -> dict[str, Any]:
    timestamp = now or utc_now()
    connection_ref = str(payload.connection_ref)
    assert payload.previous_operation_id is not None
    key = resubmit_idempotency_key(
        tracking_id=payload.tracking_id,
        previous_operation_id=payload.previous_operation_id,
        expected_revision=payload.expected_revision,
        connection_ref=connection_ref,
    )
    existing = _find_operation(config, key)
    if existing is not None:
        # The very same confirmation was already accepted (a transport replay, a
        # double click or a concurrent duplicate): resolve that one operation and
        # never create a second one, re-audit, re-check or call Auto Bangumi twice.
        return _replay_confirmed_resubmit(
            config,
            payload,
            existing,
            repository=repository,
            submit_one=submit_one,
            persist_ab_result=persist_ab_result,
            readback_external=readback_external,
            timestamp=timestamp,
        )

    record = load_tracking_record(config, payload.tracking_id)
    _guard_expected_revision(payload.expected_revision, record)
    operation = _guard_confirmation_binding(config, record, payload)
    if _is_one_time_submission(operation):
        return _resubmit_response(
            record,
            confirm=True,
            check_status=RESUBMIT_STATUS_BLOCKED,
            checked_revision=payload.expected_revision,
            timestamp=timestamp,
            blocked_reason=RESUBMIT_BLOCKED_ONE_TIME_SUBMISSION,
            operation_id=operation.operation_id,
        )
    # The success path first: a changed snapshot that now proves the subscription
    # must converge with zero external writes, exactly like the plain check.
    check, plan_identity_changed = _run_identity_safe_check(
        payload,
        config_root=config_root,
        management_client=management_client,
        read_policy=read_policy,
        timestamp=timestamp,
    )
    record = load_tracking_record(config, payload.tracking_id)
    if plan_identity_changed:
        return _plan_identity_blocked_response(
            config, record, payload, confirm=True, timestamp=timestamp
        )
    assert check is not None
    if _check_confirmed(check):
        return _resubmit_response(
            record,
            confirm=True,
            check_status=RESUBMIT_STATUS_CONFIRMED,
            checked_revision=payload.expected_revision,
            timestamp=timestamp,
            check=check,
            operation_id=_check_operation_id(check),
        )
    operation = _guard_confirmation_binding(config, record, payload, expected=operation)
    blocked = _blocked_reason_for_unresolved(check, operation)
    if blocked is not None:
        return _resubmit_response(
            record,
            confirm=True,
            check_status=RESUBMIT_STATUS_BLOCKED,
            checked_revision=payload.expected_revision,
            timestamp=timestamp,
            check=check,
            blocked_reason=blocked,
            operation_id=operation.operation_id if operation is not None else None,
        )
    assert operation is not None
    request, fingerprint, issues = _plan_preconditions(config, record)
    if issues:
        return _resubmit_response(
            record,
            confirm=True,
            check_status=RESUBMIT_STATUS_BLOCKED,
            checked_revision=payload.expected_revision,
            timestamp=timestamp,
            check=check,
            blocked_reason=RESUBMIT_BLOCKED_PLAN_NOT_SUBMITTABLE,
            issues=issues,
            operation_id=operation.operation_id,
            request=request,
        )
    return _submit_through_bound_connection(
        config,
        payload,
        repository=repository,
        record=record,
        request=request,
        fingerprint=fingerprint,
        expected_revision=record.revision,
        idempotency_key=key,
        previous_operation_id=operation.operation_id,
        submission_mode=operation.submission_mode,
        submit_one=submit_one,
        persist_ab_result=persist_ab_result,
        readback_external=readback_external,
        timestamp=timestamp,
        operation_id=operation.operation_id,
        submit_record=record,
        risk_operation=operation,
        check=check,
    )


def _replay_confirmed_resubmit(
    config: StorageConfig,
    payload: TrackingResubmitPayload,
    existing: TrackingOperation,
    *,
    repository: AutoBangumiConfigRepository,
    submit_one: Any | None,
    persist_ab_result: Any | None,
    readback_external: Any | None,
    timestamp: str,
) -> dict[str, Any]:
    """Resolve the operation a repeated identical confirmation already created."""
    connection_ref = str(payload.connection_ref)
    if (
        existing.tracking_id != payload.tracking_id
        or existing.operation != TRACKING_OPERATION_KIND_SUBMIT
        or existing.previous_operation_id != payload.previous_operation_id
        or existing.connection_ref != connection_ref
    ):
        raise Stage1Error(
            "tracking_resubmit_binding_conflict",
            "本次重新提交绑定的操作或连接已变化，请重新检查后再确认",
            _RESUBMIT_FAILED_STEP,
            {"field": "previous_operation_id"},
        )
    # Defensive only: every operation this endpoint creates already passed the
    # gate above, so this is reachable only for a hand-written/stale operation
    # file that names a one-time submission under a resubmit key.
    if _is_one_time_submission(existing):
        return _resubmit_response(
            load_tracking_record(config, payload.tracking_id),
            confirm=True,
            check_status=RESUBMIT_STATUS_BLOCKED,
            checked_revision=payload.expected_revision,
            timestamp=timestamp,
            blocked_reason=RESUBMIT_BLOCKED_ONE_TIME_SUBMISSION,
            operation_id=existing.operation_id,
        )
    record = load_tracking_record(config, payload.tracking_id)
    request, fingerprint, _issues = _plan_preconditions(config, record)
    if existing.state in {*TRACKING_OPERATION_TERMINAL_STATES, TRACKING_OPERATION_STATE_IN_PROGRESS}:
        # A settled or in-flight operation is resolved from local evidence only;
        # a deleted credential must not turn a replay into a new external call.
        write = run_tracking_resubmit_after_risk_confirmation(
            config,
            tracking_id=payload.tracking_id,
            record=record,
            request=request,
            fingerprint=fingerprint,
            expected_revision=existing.expected_revision,
            idempotency_key=existing.idempotency_key,
            previous_operation_id=str(payload.previous_operation_id),
            ab_config=None,
            connection_ref=connection_ref,
            submission_mode=existing.submission_mode,
            submit_one=submit_one,
            persist_ab_result=persist_ab_result,
            now=timestamp,
        )
        return _write_response(write, previous_operation_id=str(payload.previous_operation_id))
    # PREPARED: the external system was provably never called, so the same
    # confirmation may resume the sequence through the bound generation.
    return _submit_through_bound_connection(
        config,
        payload,
        repository=repository,
        record=record,
        request=request,
        fingerprint=fingerprint,
        expected_revision=existing.expected_revision,
        idempotency_key=existing.idempotency_key,
        previous_operation_id=str(payload.previous_operation_id),
        submission_mode=existing.submission_mode,
        submit_one=submit_one,
        persist_ab_result=persist_ab_result,
        readback_external=readback_external,
        timestamp=timestamp,
        operation_id=existing.operation_id,
        submit_record=record,
    )


# ---------------------------------------------------------------------------
# Guards and small helpers
# ---------------------------------------------------------------------------


def _check_payload(payload: TrackingResubmitPayload) -> TrackingCheckPayload:
    return TrackingCheckPayload(
        tracking_id=payload.tracking_id,
        expected_revision=payload.expected_revision,
        storage_dir=payload.storage_dir,
    )


def _run_identity_safe_check(
    payload: TrackingResubmitPayload,
    *,
    config_root: Any | None,
    management_client: object | None,
    read_policy: CheckPolicy | None,
    timestamp: str,
) -> tuple[dict[str, Any] | None, bool]:
    """Run the read-only check, translating a changed plan identity honestly.

    The read-only verification is only meaningful for the exact Request the
    pending operation was bound to; when the local plan changed since then the
    verification refuses with ``tracking_connection_mismatch`` *before* reading
    anything.  A resubmit reports that as its own published plan reason (HTTP 200)
    instead of leaking the check's binding error, and nothing is written.
    """
    try:
        return (
            run_saved_tracking_check_locked(
                _check_payload(payload),
                config_root=config_root,
                management_client=management_client,
                now=timestamp,
                read_policy=read_policy,
            ),
            False,
        )
    except Stage1Error as exc:
        if exc.error_type == "tracking_connection_mismatch":
            return None, True
        raise


def _request_changed_issue() -> RevalidationIssue:
    return RevalidationIssue(
        code=REVALIDATE_ISSUE_REQUEST_CHANGED,
        message="订阅方案已发生修改，请确认最新方案后再提交",
        recovery_action="SUBMIT",
    )


def _plan_identity_blocked_response(
    config: StorageConfig,
    record: TrackingRecord,
    payload: TrackingResubmitPayload,
    *,
    confirm: bool,
    timestamp: str,
) -> dict[str, Any]:
    _request, _fingerprint, issues = _plan_preconditions(config, record)
    if not any(issue.code == REVALIDATE_ISSUE_REQUEST_CHANGED for issue in issues):
        # The verification refused because the historical operation/mapping
        # binding changed, not because the plan changed: that is a stale
        # confirmation, never a plan problem (issue #184 review).
        raise Stage1Error(
            "tracking_resubmit_binding_conflict",
            "历史操作绑定已变化，请重新检查后再确认",
            _RESUBMIT_FAILED_STEP,
            {"field": "previous_operation_id"},
        )
    return _resubmit_response(
        record,
        confirm=confirm,
        check_status=RESUBMIT_STATUS_BLOCKED,
        checked_revision=payload.expected_revision,
        timestamp=timestamp,
        blocked_reason=RESUBMIT_BLOCKED_PLAN_NOT_SUBMITTABLE,
        issues=issues or (_request_changed_issue(),),
    )


def _check_confirmed(check: dict[str, Any]) -> bool:
    """True only when the read-only check proved the external object exists."""
    return check.get("needs_manual") is False and check.get("outcome") in {
        TRACKING_STATUS_ACTIVE,
        TRACKING_STATUS_DISABLED,
    }


def _check_operation_id(check: dict[str, Any]) -> str | None:
    value = check.get("operation_id")
    return value if isinstance(value, str) and value else None


def _is_one_time_submission(operation: TrackingOperation | None) -> bool:
    """True when the pending operation was a one-time collection (AC 1/#184 scope)."""
    return (
        operation is not None
        and operation.operation == TRACKING_OPERATION_KIND_SUBMIT
        and operation.submission_mode != TRACKING_SUBMISSION_MODE_CONTINUE
    )


def _current_operation(
    config: StorageConfig, record: TrackingRecord
) -> TrackingOperation | None:
    if not record.current_operation_id:
        return None
    try:
        return load_tracking_operation(config, record.current_operation_id)
    except Stage1Error:
        return None


def _blocked_reason_for_unresolved(
    check: dict[str, Any], operation: TrackingOperation | None
) -> str | None:
    """Return the proven reason a resubmit is refused, or None when it may be offered."""
    if operation is None or operation.state == TRACKING_OPERATION_STATE_IN_PROGRESS:
        # The durable boundary was crossed and no terminal result is stored: the
        # external write may still be running, so only recovery may settle it.
        return RESUBMIT_BLOCKED_EXTERNAL_WRITE_IN_PROGRESS
    if operation.state not in {
        TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
        TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
    }:
        return RESUBMIT_BLOCKED_EXTERNAL_WRITE_IN_PROGRESS
    reason = check.get("verification_reason")
    if isinstance(reason, str) and reason in RESUBMIT_BLOCKED_REASONS:
        return reason
    if isinstance(reason, str) and reason in RESUBMIT_ALLOWED_REASONS:
        return None
    # An unresolved outcome without a recognized proven reason is not an
    # authorization: fail closed with its own refusal code — never the offerable
    # ``UNREADABLE`` reason class, which would read as "risk confirmation".
    return RESUBMIT_BLOCKED_RESULT_UNPROVEN


def _guard_expected_revision(expected_revision: Any, record: TrackingRecord) -> None:
    if (
        not isinstance(expected_revision, int)
        or isinstance(expected_revision, bool)
        or expected_revision != record.revision
    ):
        raise Stage1Error(
            "tracking_revision_conflict",
            "追番记录版本已变化，请刷新后重新检查",
            _RESUBMIT_FAILED_STEP,
            {"field": "expected_revision", "current_revision": record.revision},
        )


def _guard_confirmation_binding(
    config: StorageConfig,
    record: TrackingRecord,
    payload: TrackingResubmitPayload,
    *,
    expected: TrackingOperation | None = None,
) -> TrackingOperation:
    """Refuse a confirmation that no longer matches the record's own binding."""
    connection_ref = str(payload.connection_ref)
    operation = _current_operation(config, record)
    if expected is not None and operation is not None and (
        operation.operation_id != expected.operation_id
        or operation.connection_ref != expected.connection_ref
    ):
        raise Stage1Error(
            "tracking_resubmit_binding_conflict",
            "本次重新提交绑定的操作已变化，请重新检查后再确认",
            _RESUBMIT_FAILED_STEP,
            {"field": "previous_operation_id"},
        )
    if (
        operation is None
        or operation.operation_id != payload.previous_operation_id
        or operation.operation != TRACKING_OPERATION_KIND_SUBMIT
        or operation.tracking_id != record.tracking_id
        or operation.connection_ref != connection_ref
    ):
        raise Stage1Error(
            "tracking_resubmit_binding_conflict",
            "本次重新提交绑定的操作或连接已变化，请重新检查后再确认",
            _RESUBMIT_FAILED_STEP,
            {"field": "previous_operation_id"},
        )
    return operation


#: Lease refusals that prove the bound generation is gone or unusable, so the
#: resubmit is refused with a published reason and zero external calls.
_BOUND_CONNECTION_REFUSALS = frozenset(
    {"connection_ref_conflict", "config_error", "connection_in_use"}
)


def _blocked_reason_for_lease_error(error_type: str) -> str:
    return (
        RESUBMIT_BLOCKED_CONNECTION_CHANGED
        if error_type == "connection_ref_conflict"
        else RESUBMIT_BLOCKED_CONFIG_ERROR
    )


def _submit_through_bound_connection(
    config: StorageConfig,
    payload: TrackingResubmitPayload,
    *,
    repository: AutoBangumiConfigRepository,
    record: TrackingRecord,
    request: dict[str, Any] | None,
    fingerprint: str | None,
    expected_revision: int,
    idempotency_key: str,
    previous_operation_id: str,
    submission_mode: str | None,
    submit_one: Any | None,
    persist_ab_result: Any | None,
    readback_external: Any | None,
    timestamp: str,
    operation_id: str,
    submit_record: TrackingRecord,
    risk_operation: TrackingOperation | None = None,
    check: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the one new operation through the *bound* saved generation.

    The generation is resolved from the reference the confirmation echoed (never
    from the browser) and its lease is held across the whole write. A replaced,
    deleted or in-use generation is a proven refusal with zero external calls;
    the write itself is the ordinary reliable submit sequence. The user's risk
    verdict is made durable only once that generation is proven usable, so a
    refused resubmit never leaves a confirmation behind.
    """
    connection_ref = str(payload.connection_ref)
    try:
        lease = repository.acquire_lease(connection_ref=connection_ref)
    except Stage1Error as exc:
        if exc.error_type not in _BOUND_CONNECTION_REFUSALS:
            raise
        return _resubmit_response(
            record,
            confirm=True,
            check_status=RESUBMIT_STATUS_BLOCKED,
            checked_revision=payload.expected_revision,
            timestamp=timestamp,
            check=check,
            blocked_reason=_blocked_reason_for_lease_error(exc.error_type),
            operation_id=operation_id,
        )
    with lease:
        if (
            lease.record.config is None
            or lease.record.connection_ref is None
            or str(lease.record.connection_ref) != connection_ref
        ):
            return _resubmit_response(
                record,
                confirm=True,
                check_status=RESUBMIT_STATUS_BLOCKED,
                checked_revision=payload.expected_revision,
                timestamp=timestamp,
                check=check,
                blocked_reason=RESUBMIT_BLOCKED_CONNECTION_CHANGED,
                operation_id=operation_id,
            )
        if risk_operation is not None:
            submit_record = _record_risk_confirmation(
                config, record=submit_record, operation=risk_operation, timestamp=timestamp
            )
            expected_revision = submit_record.revision
        readback = readback_external or compose_tracking_readback_external(
            lease.record.config.to_runtime_config()
        )
        write = run_tracking_resubmit_after_risk_confirmation(
            config,
            tracking_id=payload.tracking_id,
            record=submit_record,
            request=request,
            fingerprint=fingerprint,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            previous_operation_id=previous_operation_id,
            ab_config=lease.record.config.to_runtime_config(),
            connection_ref=connection_ref,
            submission_mode=submission_mode,
            submit_one=submit_one,
            persist_ab_result=persist_ab_result,
            readback_external=readback,
            now=timestamp,
        )
    return _write_response(write, previous_operation_id=previous_operation_id)


def _plan_preconditions(
    config: StorageConfig, record: TrackingRecord
) -> tuple[dict[str, Any] | None, str | None, tuple[RevalidationIssue, ...]]:
    """Re-run the complete pure-local submit preconditions (no external access).

    A resubmit repeats the *pending* plan; it never adopts a changed plan under a
    confirmation that was given for another one, so every revalidation issue —
    including a plan change — refuses the resubmit instead of being folded into a
    fresh submit.

    ``classify_revalidation`` gates on the record being in a pre-submit status,
    which a pending (``VERIFYING_EXTERNAL``/``RECOVERY_REQUIRED``) record is not;
    that gate answers "may this record start a submit now?", which is exactly the
    question this endpoint has already answered.  The check is therefore re-run
    against the same plan content with the gate satisfied, so every real plan
    precondition still blocks and nothing is persisted.
    """
    request = _tolerant_load_request(config, record)
    fingerprint = compute_request_fingerprint(request) if isinstance(request, dict) else None
    issues = classify_revalidation(
        replace(record, status=TRACKING_STATUS_PENDING_SUBMIT),
        RevalidationEvidence(
            request=request,
            request_fingerprint=fingerprint,
            operation_in_progress=False,
        ),
    )
    return request, fingerprint, issues


def _tolerant_load_request(
    config: StorageConfig, record: TrackingRecord
) -> dict[str, Any] | None:
    if not record.request_id:
        return None
    try:
        loaded = load_request_snapshot(config, record.request_id)
        return loaded if isinstance(loaded, dict) else None
    except Stage1Error:
        return None


def _record_risk_confirmation(
    config: StorageConfig,
    *,
    record: TrackingRecord,
    operation: TrackingOperation,
    timestamp: str,
) -> TrackingRecord:
    """Durably record the user's explicit risk verdict before any new write.

    The status is unchanged (the pending outcome is still unproven); this write
    only appends the ``USER`` audit event and advances the revision, so the
    confirmation the new operation is created under is auditable even if the
    process dies before the external call.
    """
    next_record = transition_record(
        record,
        status=record.status,
        audit_action=TRACKING_AUDIT_RESUBMIT_CONFIRMED,
        audit_actor=TRACKING_AUDIT_ACTOR_USER,
        operation_id=operation.operation_id,
        reason_code="risk_confirmed",
        safe_message=_RESUBMIT_AUDIT_MESSAGE,
        now=timestamp,
    )
    return compare_and_swap_tracking_record(
        config, record.tracking_id, base_revision=record.revision, record=next_record
    )


def _binding(record: TrackingRecord, operation: TrackingOperation) -> dict[str, Any]:
    return {
        "expected_revision": record.revision,
        "previous_operation_id": operation.operation_id,
        "connection_ref": operation.connection_ref,
    }


def _resubmit_response(
    record: TrackingRecord,
    *,
    confirm: bool,
    check_status: str,
    checked_revision: int,
    timestamp: str,
    check: dict[str, Any] | None = None,
    requires_risk_confirmation: bool = False,
    blocked_reason: str | None = None,
    binding: dict[str, Any] | None = None,
    issues: tuple[RevalidationIssue, ...] = (),
    operation_id: str | None = None,
    request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one safe two-phase resubmit result (HTTP 200 business result)."""
    valid_count = safe_valid_resource_count(request)
    reason = check.get("verification_reason") if isinstance(check, dict) else None
    return {
        "tracking_id": record.tracking_id,
        "confirm": confirm,
        "check_status": check_status,
        "outcome": record.status,
        "requires_risk_confirmation": requires_risk_confirmation,
        "blocked_reason": blocked_reason,
        "verification_reason": reason if isinstance(reason, str) else None,
        "binding": binding,
        "checked_revision": checked_revision,
        "next_revision": record.revision,
        "checked_at": timestamp,
        "operation_id": operation_id,
        "previous_operation_id": None,
        "failure_category": None,
        "diagnostics": {},
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


def _write_response(write: dict[str, Any], *, previous_operation_id: str) -> dict[str, Any]:
    """Project the standard submit result as the write phase of a resubmit."""
    return {
        **write,
        "confirm": True,
        "check_status": RESUBMIT_STATUS_UNRESOLVED,
        "requires_risk_confirmation": False,
        "blocked_reason": None,
        "binding": None,
        "previous_operation_id": previous_operation_id,
    }


__all__ = [
    "RESUBMIT_ALLOWED_REASONS",
    "RESUBMIT_BLOCKED_CONFIG_ERROR",
    "RESUBMIT_BLOCKED_CONNECTION_CHANGED",
    "RESUBMIT_BLOCKED_EXTERNAL_WRITE_IN_PROGRESS",
    "RESUBMIT_BLOCKED_ONE_TIME_SUBMISSION",
    "RESUBMIT_BLOCKED_PLAN_NOT_SUBMITTABLE",
    "RESUBMIT_BLOCKED_RESULT_UNPROVEN",
    "RESUBMIT_BLOCKED_REASONS",
    "RESUBMIT_STATUS_BLOCKED",
    "RESUBMIT_STATUS_CONFIRMED",
    "RESUBMIT_STATUS_UNRESOLVED",
    "resubmit_idempotency_key",
    "run_saved_tracking_resubmit",
]
