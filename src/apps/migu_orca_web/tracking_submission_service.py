"""Unified reliable tracking submit orchestration (US-225).

``POST /api/v1/tracking/items/{tracking_id}/submit`` runs the Stage 29 §13
reliable submit sequence for one tracking record:

1. re-run the historical-backfill coordinator (every tracking API access does);
2. load the TrackingRecord and require ``confirm`` strictly true;
3. re-read the *fresh* local Request and run the complete pure-local
   revalidation (``classify_revalidation``) — the server never trusts a
   browser-supplied fingerprint;
4. on a pure plan change the user's ``confirm=true`` adopts the latest Request
   (stored fingerprint/revision/audit updated in the same SUBMITTING write);
   on any other blocking issue the record moves to ``NEEDS_RECONFIRM`` (a
   persisted business result, HTTP 200) and Auto Bangumi is never touched;
5. bind the idempotency-keyed operation ``PREPARED``, persist the record as
   ``SUBMITTING``, then switch the operation to ``IN_PROGRESS`` — the durable
   boundary after which an external call may have happened (§13.2);
6. call the existing Auto Bangumi create seam once and classify the normalized
   result (``classify_external_submit_result``) as
   ``ACTIVE``/``SUBMIT_FAILED``/``VERIFYING_EXTERNAL``/``RECOVERY_REQUIRED``;
7. persist the safe AB result first, then the TrackingRecord final status and
   the operation terminal state (§13.3).

Idempotency / concurrency
-------------------------
- A same-key/same-binding request whose operation already reached a terminal
  state replays the same public outcome without a second external call.
- A same-key replay whose operation is still ``PREPARED`` (external never
  called) resumes the normal submit path on the same operation.
- Only the operation's ``PREPARED -> IN_PROGRESS`` compare-and-swap may touch
  Auto Bangumi, so concurrent same-key submits produce at most one external
  call; losers surface ``tracking_operation_in_progress`` (409).
- ``ab_config`` exists only in this request's memory — it is never persisted,
  logged or returned.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace
from typing import Any

from apps.migu_orca_web.save_confirm_service import compute_request_fingerprint
from apps.migu_orca_web.serializers import (
    _sanitize_ab_submit_result,
    serialize_request_safe_info,
)
from apps.migu_orca_web.tracking_migration_service import run_tracking_migration
from apps.migu_orca_web.tracking_queue_compat import sync_queue_projection_for_tracking
from apps.migu_orca_web.tracking_serializers import (
    tracking_available_actions,
    tracking_summary_fields,
)
from batch_engine.controllers.batch_submit_controller import compose_ab_submit_one
from shared.errors import Stage1Error
from storage_engine.controllers.ab_result_repository import save_ab_submit_result
from storage_engine.controllers.operation_repository import (
    bind_tracking_operation,
    compare_and_swap_tracking_operation,
    load_tracking_operation,
)
from storage_engine.controllers.request_repository import (
    load_request_snapshot,
    save_request_snapshot,
)
from storage_engine.controllers.storage_config import StorageConfig
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
    SUBMIT_ADOPTED_MESSAGE,
    SUBMIT_FAILED_MESSAGE,
    SUBMIT_FROM_STATUSES,
    SUBMIT_OUTCOME_UNKNOWN_MESSAGE,
    SUBMIT_PERSIST_FAILED_MESSAGE,
    SUBMIT_STARTED_MESSAGE,
    SUBMIT_SUCCEEDED_MESSAGE,
    classify_external_submit_result,
    external_submit_error_type,
    external_submit_result_id,
    tracking_status_for_operation_state,
)
from tracking_engine.models.operation import (
    TRACKING_OPERATION_KIND_SUBMIT,
    TRACKING_OPERATION_STATE_FAILED,
    TRACKING_OPERATION_STATE_IN_PROGRESS,
    TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
    TRACKING_OPERATION_STATE_PREPARED,
    TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
    TRACKING_OPERATION_STATE_SUCCEEDED,
    TRACKING_OPERATION_TERMINAL_STATES,
    TrackingOperation,
    tracking_operation_id_for_idempotency_key,
    transition_tracking_operation,
)
from tracking_engine.models.tracking import (
    TRACKING_AUDIT_ACTOR_SYSTEM,
    TRACKING_AUDIT_PLAN_CHANGE_DETECTED,
    TRACKING_AUDIT_RESULT_PERSIST_FAILED,
    TRACKING_AUDIT_REVALIDATION_FAILED,
    TRACKING_AUDIT_SUBMIT_FAILED,
    TRACKING_AUDIT_SUBMIT_OUTCOME_UNKNOWN,
    TRACKING_AUDIT_SUBMIT_STARTED,
    TRACKING_AUDIT_SUBMIT_SUCCEEDED,
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_NEEDS_RECONFIRM,
    TRACKING_STATUS_PENDING_SUBMIT,
    TRACKING_STATUS_RECOVERY_REQUIRED,
    TRACKING_STATUS_SUBMIT_FAILED,
    TRACKING_STATUS_SUBMITTING,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
    TrackingRecord,
    transition_record,
    utc_now,
)

#: The external create seam shape (request, ab_config) -> normalized result.
SubmitOne = Callable[[dict[str, Any], Any], dict[str, Any]]
#: Persists one Request's sanitized AB result into the snapshot + ab_results.
PersistAbResult = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]

#: Audit action used to reconcile a record on a same-key terminal replay.
_REPLAY_AUDIT_ACTION: dict[str, str] = {
    TRACKING_OPERATION_STATE_SUCCEEDED: TRACKING_AUDIT_SUBMIT_SUCCEEDED,
    TRACKING_OPERATION_STATE_FAILED: TRACKING_AUDIT_SUBMIT_FAILED,
    TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN: TRACKING_AUDIT_SUBMIT_OUTCOME_UNKNOWN,
    TRACKING_OPERATION_STATE_RECOVERY_REQUIRED: TRACKING_AUDIT_RESULT_PERSIST_FAILED,
}
_REPLAY_SAFE_MESSAGE: dict[str, str] = {
    TRACKING_OPERATION_STATE_SUCCEEDED: SUBMIT_SUCCEEDED_MESSAGE,
    TRACKING_OPERATION_STATE_FAILED: SUBMIT_FAILED_MESSAGE,
    TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN: SUBMIT_OUTCOME_UNKNOWN_MESSAGE,
    TRACKING_OPERATION_STATE_RECOVERY_REQUIRED: SUBMIT_PERSIST_FAILED_MESSAGE,
}


def run_tracking_submit(
    config: StorageConfig,
    *,
    tracking_id: str,
    expected_revision: int,
    idempotency_key: str,
    confirm: bool,
    ab_config: Any,
    start_statuses: frozenset[str] | None = None,
    submit_one: SubmitOne | None = None,
    persist_ab_result: PersistAbResult | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Run the unified reliable submit for one tracking item (US-225).

    ``confirm`` must be strictly true.  ``ab_config`` is request-scoped memory
    only.  A persisted business result (``NEEDS_RECONFIRM``/``SUBMIT_FAILED``/
    ``VERIFYING_EXTERNAL``/``RECOVERY_REQUIRED``/``ACTIVE``) is returned as an
    HTTP-200-safe result dict; only preconditions (missing record, stale
    revision, non-submittable state, idempotency conflict, in-flight operation)
    raise.

    ``start_statuses`` restricts the fresh-key submit to a subset of
    ``SUBMIT_FROM_STATUSES``.  The unified ``retry`` entry point (US-226) passes
    ``{SUBMIT_FAILED}`` so a retry is only accepted from a definitely-failed
    submission; a same-key terminal replay is still resolved before this guard
    (an idempotent replay of a previous attempt is never re-run externally).
    """
    allowed_start = start_statuses or SUBMIT_FROM_STATUSES
    if not allowed_start.issubset(SUBMIT_FROM_STATUSES):
        raise ValueError("start_statuses must be a subset of SUBMIT_FROM_STATUSES")

    run_tracking_migration(config=config)

    timestamp = now or utc_now()
    record = load_tracking_record(config, tracking_id)
    _guard_confirm(confirm)

    request = _tolerant_load_request(config, record)
    fingerprint = compute_request_fingerprint(request) if isinstance(request, dict) else None

    existing_operation = _find_operation(config, idempotency_key)
    if existing_operation is not None:
        _guard_replay_binding(
            existing_operation,
            record=record,
            expected_revision=expected_revision,
            fingerprint=fingerprint,
        )
        return _resolve_existing_operation(
            config,
            record=record,
            request=request,
            operation=existing_operation,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            ab_config=ab_config,
            submit_one=submit_one,
            persist_ab_result=persist_ab_result,
            timestamp=timestamp,
        )

    # A fresh idempotency key: an in-flight operation (any key) must be resolved
    # through recover before a new external attempt may start.
    _guard_no_inflight_operation(config, record)
    if record.status not in allowed_start:
        _raise_state_conflict(record)
    _guard_expected_revision(expected_revision, record)

    issues = classify_revalidation(
        record,
        RevalidationEvidence(
            request=request,
            request_fingerprint=fingerprint,
            operation_in_progress=False,
        ),
    )
    changed_only = bool(issues) and all(
        issue.code == REVALIDATE_ISSUE_REQUEST_CHANGED for issue in issues
    )
    if issues and not changed_only:
        # A blocking business issue: never touch Auto Bangumi.  The record moves
        # to NEEDS_RECONFIRM (or stays there) as a persisted HTTP-200 outcome.
        return _blocked_needs_reconfirm(
            config,
            record=record,
            issues=issues,
            expected_revision=expected_revision,
            request=request,
            timestamp=timestamp,
        )

    # issues empty, or only REQUEST_CHANGED with confirm=true (adopt latest).
    return _submit_through_external(
        config,
        record=record,
        request=request,
        fingerprint=fingerprint,
        expected_revision=expected_revision,
        idempotency_key=idempotency_key,
        ab_config=ab_config,
        operation=None,
        submit_one=submit_one,
        persist_ab_result=persist_ab_result,
        timestamp=timestamp,
    )


def run_tracking_retry(
    config: StorageConfig,
    *,
    tracking_id: str,
    expected_revision: int,
    idempotency_key: str,
    confirm: bool,
    ab_config: Any,
    submit_one: SubmitOne | None = None,
    persist_ab_result: PersistAbResult | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Run the unified retry for one definitely-failed tracking item (US-226).

    ``POST .../retry`` shares the entire reliable submit sequence with
    ``run_tracking_submit`` — the fresh Request re-read + revalidation, the
    PREPARED operation bind, the SUBMITTING pre-write, the single external call
    and the result classification — but only starts from ``SUBMIT_FAILED``.
    ``VERIFYING_EXTERNAL``/``RECOVERY_REQUIRED`` must be recovered first (they
    are never blindly retried, D29-07); a request against those states raises
    ``tracking_state_conflict`` (409).
    """
    return run_tracking_submit(
        config,
        tracking_id=tracking_id,
        expected_revision=expected_revision,
        idempotency_key=idempotency_key,
        confirm=confirm,
        ab_config=ab_config,
        start_statuses=frozenset({TRACKING_STATUS_SUBMIT_FAILED}),
        submit_one=submit_one,
        persist_ab_result=persist_ab_result,
        now=now,
    )


# ---------------------------------------------------------------------------
# Existing-operation handling (replay / resume)
# ---------------------------------------------------------------------------


def _resolve_existing_operation(
    config: StorageConfig,
    *,
    record: TrackingRecord,
    request: dict[str, Any] | None,
    operation: TrackingOperation,
    expected_revision: int,
    idempotency_key: str,
    fingerprint: str | None,
    ab_config: Any,
    submit_one: SubmitOne | None,
    persist_ab_result: PersistAbResult | None,
    timestamp: str,
) -> dict[str, Any]:
    """Decide how a same-key request proceeds from the stored operation state."""
    if operation.state in TRACKING_OPERATION_TERMINAL_STATES:
        return _replay_terminal_outcome(
            config,
            record=record,
            operation=operation,
            expected_revision=expected_revision,
            timestamp=timestamp,
        )
    if operation.state == TRACKING_OPERATION_STATE_IN_PROGRESS:
        # The durable external boundary was crossed by an earlier attempt; only
        # recovery may resolve the ambiguous outcome.  Never call again.
        _raise_operation_in_progress(record)

    # operation.state == PREPARED: the external system was provably never
    # called, so the same-key request may resume the normal submit path.
    if record.status == TRACKING_STATUS_SUBMITTING and (
        record.current_operation_id == operation.operation_id
    ):
        # The earlier attempt already persisted SUBMITTING before crashing;
        # resume from the durable operation gate.
        if not isinstance(request, dict):
            return _resume_missing_request(config, record, operation, timestamp)
        return _submit_through_external(
            config,
            record=record,
            request=request,
            fingerprint=fingerprint,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            ab_config=ab_config,
            operation=operation,
            submit_one=submit_one,
            persist_ab_result=persist_ab_result,
            timestamp=timestamp,
        )
    if record.status in SUBMIT_FROM_STATUSES:
        if not isinstance(request, dict):
            return _resume_missing_request(config, record, operation, timestamp)
        return _submit_through_external(
            config,
            record=record,
            request=request,
            fingerprint=fingerprint,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            ab_config=ab_config,
            operation=operation,
            submit_one=submit_one,
            persist_ab_result=persist_ab_result,
            timestamp=timestamp,
        )
    # The record no longer allows submission; the prepared operation cannot
    # safely continue.
    _raise_operation_in_progress(record)


def _resume_missing_request(
    config: StorageConfig,
    record: TrackingRecord,
    operation: TrackingOperation,
    timestamp: str,
) -> dict[str, Any]:
    """Resolve a resumed PREPARED operation whose Request has since vanished.

    The external system was never called (still PREPARED), so it is safe to
    fail the operation and move the record to NEEDS_RECONFIRM for the user to
    restore the plan — never a blind retry of an ambiguous external state.
    """
    failed_operation = compare_and_swap_tracking_operation(
        config,
        operation.operation_id,
        expected_state=TRACKING_OPERATION_STATE_PREPARED,
        record=transition_tracking_operation(
            operation,
            state=TRACKING_OPERATION_STATE_FAILED,
            error_type="request_missing",
            now=timestamp,
        ),
    )
    next_record = transition_record(
        record,
        status=TRACKING_STATUS_NEEDS_RECONFIRM,
        audit_action=TRACKING_AUDIT_REVALIDATION_FAILED,
        audit_actor=TRACKING_AUDIT_ACTOR_SYSTEM,
        operation_id=operation.operation_id,
        reason_code="request_missing",
        safe_message="本地方案不存在或暂时不可读，无法提交追番",
        now=timestamp,
    )
    next_record = replace(next_record, current_operation_id=failed_operation.operation_id)
    record_final = compare_and_swap_tracking_record(
        config,
        record.tracking_id,
        base_revision=record.revision,
        record=next_record,
    )
    return _submit_result_payload(
        record=record_final,
        outcome=TRACKING_STATUS_NEEDS_RECONFIRM,
        checked_revision=record_final.revision,
        operation_id=operation.operation_id,
        issues=(
            RevalidationIssue(
                code="REQUEST_MISSING",
                message="本地方案不存在或暂时不可读，无法提交追番",
            ),
        ),
        request=None,
        timestamp=timestamp,
    )


def _replay_terminal_outcome(
    config: StorageConfig,
    *,
    record: TrackingRecord,
    operation: TrackingOperation,
    expected_revision: int,
    timestamp: str,
) -> dict[str, Any]:
    """Replay a same-key terminal operation's public outcome (no external call)."""
    outcome = tracking_status_for_operation_state(operation.state)
    reconciled = record
    if record.status == TRACKING_STATUS_SUBMITTING and record.status != outcome:
        # A crash between the record-final write and the operation-terminal
        # write left the record mid-flight; reconcile it to the terminal state.
        next_record = transition_record(
            record,
            status=outcome,
            audit_action=_REPLAY_AUDIT_ACTION[operation.state],
            audit_actor=TRACKING_AUDIT_ACTOR_SYSTEM,
            operation_id=operation.operation_id,
            safe_message=_REPLAY_SAFE_MESSAGE[operation.state],
            now=timestamp,
        )
        try:
            reconciled = compare_and_swap_tracking_record(
                config,
                record.tracking_id,
                base_revision=record.revision,
                record=next_record,
            )
        except Stage1Error as exc:
            if exc.error_type == "tracking_revision_conflict":
                # A concurrent actor already moved the record; report it.
                reconciled = load_tracking_record(config, record.tracking_id)
            else:
                raise
    return _submit_result_payload(
        record=reconciled,
        outcome=outcome,
        checked_revision=expected_revision,
        operation_id=operation.operation_id,
        issues=(),
        request=None,
        timestamp=timestamp,
    )


# ---------------------------------------------------------------------------
# Reliable external submit sequence (§13.2)
# ---------------------------------------------------------------------------


def _submit_through_external(
    config: StorageConfig,
    *,
    record: TrackingRecord,
    request: dict[str, Any] | None,
    fingerprint: str | None,
    expected_revision: int,
    idempotency_key: str,
    ab_config: Any,
    operation: TrackingOperation | None,
    submit_one: SubmitOne | None,
    persist_ab_result: PersistAbResult | None,
    timestamp: str,
) -> dict[str, Any]:
    """Persist the SUBMITTING boundary, gate the external call and finalize."""
    if operation is None:
        operation, created = bind_tracking_operation(
            config,
            tracking_id=record.tracking_id,
            operation=TRACKING_OPERATION_KIND_SUBMIT,
            idempotency_key=idempotency_key,
            expected_revision=expected_revision,
            request_fingerprint=fingerprint or "",
            now=timestamp,
        )
        if not created:
            # A concurrent same-key bind won the race; resolve by its state.
            return _resolve_existing_operation(
                config,
                record=record,
                request=request,
                operation=operation,
                expected_revision=expected_revision,
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
                ab_config=ab_config,
                submit_one=submit_one,
                persist_ab_result=persist_ab_result,
                timestamp=timestamp,
            )

    if record.status != TRACKING_STATUS_SUBMITTING:
        adopted = fingerprint is not None and record.request_fingerprint != fingerprint
        next_record = transition_record(
            record,
            status=TRACKING_STATUS_SUBMITTING,
            audit_action=TRACKING_AUDIT_SUBMIT_STARTED,
            audit_actor=TRACKING_AUDIT_ACTOR_SYSTEM,
            operation_id=operation.operation_id,
            safe_message=SUBMIT_ADOPTED_MESSAGE if adopted else SUBMIT_STARTED_MESSAGE,
            now=timestamp,
        )
        next_record = replace(
            next_record,
            current_operation_id=operation.operation_id,
            request_fingerprint=fingerprint,
        )
        try:
            record = compare_and_swap_tracking_record(
                config,
                record.tracking_id,
                base_revision=record.revision,
                record=next_record,
            )
        except Stage1Error as exc:
            if exc.error_type == "tracking_revision_conflict":
                # A competing submit already moved the record into SUBMITTING.
                _raise_operation_in_progress(record)
            raise
    elif record.current_operation_id != operation.operation_id:
        _raise_operation_in_progress(record)

    # §13.2: when a legacy batch queue still holds this Request, mirror the
    # SUBMITTING boundary into it before the external call (best-effort; a
    # damaged/unwritable queue never blocks the authoritative submit).
    _sync_queue_projection(config, record, TRACKING_STATUS_SUBMITTING)

    # Durable external boundary: only the caller that wins the PREPARED ->
    # IN_PROGRESS compare-and-swap may touch Auto Bangumi.
    try:
        in_flight = compare_and_swap_tracking_operation(
            config,
            operation.operation_id,
            expected_state=TRACKING_OPERATION_STATE_PREPARED,
            record=transition_tracking_operation(
                operation,
                state=TRACKING_OPERATION_STATE_IN_PROGRESS,
                now=timestamp,
            ),
        )
    except Stage1Error as exc:
        if exc.error_type == "tracking_operation_state_conflict":
            _raise_operation_in_progress(record)
        raise
    operation = in_flight

    ab_result = _run_submit_one(submit_one, request, ab_config)

    persist = persist_ab_result or _default_persist_ab_result(config)
    try:
        persist(request, ab_result)
    except Stage1Error as exc:
        return _persist_failure_recovery(
            config,
            record=record,
            operation=operation,
            error_type=exc.error_type,
            expected_revision=expected_revision,
            timestamp=timestamp,
        )
    except Exception:  # pragma: no cover - safety boundary
        return _persist_failure_recovery(
            config,
            record=record,
            operation=operation,
            error_type="result_persist_failed",
            expected_revision=expected_revision,
            timestamp=timestamp,
        )

    classification = classify_external_submit_result(ab_result)
    return _finalize_external_outcome(
        config,
        record=record,
        operation=operation,
        classification=classification,
        ab_result=ab_result,
        expected_revision=expected_revision,
        request=request,
        timestamp=timestamp,
    )


def _finalize_external_outcome(
    config: StorageConfig,
    *,
    record: TrackingRecord,
    operation: TrackingOperation,
    classification: str,
    ab_result: dict[str, Any],
    expected_revision: int,
    request: dict[str, Any] | None,
    timestamp: str,
) -> dict[str, Any]:
    """Persist the TrackingRecord final status then the operation terminal state."""
    if classification == TRACKING_OPERATION_STATE_SUCCEEDED:
        outcome = TRACKING_STATUS_ACTIVE
        audit_action = TRACKING_AUDIT_SUBMIT_SUCCEEDED
        safe_message = SUBMIT_SUCCEEDED_MESSAGE
        external_id = external_submit_result_id(ab_result)
        op_error_type = None
        reason_code = None
        op_state = TRACKING_OPERATION_STATE_SUCCEEDED
    elif classification == TRACKING_OPERATION_STATE_FAILED:
        outcome = TRACKING_STATUS_SUBMIT_FAILED
        audit_action = TRACKING_AUDIT_SUBMIT_FAILED
        safe_message = SUBMIT_FAILED_MESSAGE
        external_id = None
        op_error_type = external_submit_error_type(ab_result) or "ab_submit_failed"
        reason_code = op_error_type
        op_state = TRACKING_OPERATION_STATE_FAILED
    else:  # OUTCOME_UNKNOWN
        outcome = TRACKING_STATUS_VERIFYING_EXTERNAL
        audit_action = TRACKING_AUDIT_SUBMIT_OUTCOME_UNKNOWN
        safe_message = SUBMIT_OUTCOME_UNKNOWN_MESSAGE
        external_id = None
        op_error_type = external_submit_error_type(ab_result) or "outcome_unknown"
        reason_code = op_error_type
        op_state = TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN

    next_record = transition_record(
        record,
        status=outcome,
        audit_action=audit_action,
        audit_actor=TRACKING_AUDIT_ACTOR_SYSTEM,
        operation_id=operation.operation_id,
        reason_code=reason_code,
        safe_message=safe_message,
        now=timestamp,
    )
    if reason_code is not None:
        next_record = replace(
            next_record,
            last_error={
                "error_type": reason_code,
                "reason_code": reason_code,
                "safe_message": safe_message,
            },
        )
    record_final = compare_and_swap_tracking_record(
        config,
        record.tracking_id,
        base_revision=record.revision,
        record=next_record,
    )
    compare_and_swap_tracking_operation(
        config,
        operation.operation_id,
        expected_state=TRACKING_OPERATION_STATE_IN_PROGRESS,
        record=transition_tracking_operation(
            operation,
            state=op_state,
            external_result_id=external_id,
            error_type=op_error_type,
            now=timestamp,
        ),
    )
    # §13.3: mirror the final tracking state into any legacy queue projection
    # (best-effort; a post-call queue write failure never overwrites a durable
    # success and never rolls back the authoritative record).
    _sync_queue_projection(config, record_final, outcome)
    return _submit_result_payload(
        record=record_final,
        outcome=outcome,
        checked_revision=expected_revision,
        operation_id=operation.operation_id,
        issues=(),
        request=request,
        timestamp=timestamp,
    )


def _persist_failure_recovery(
    config: StorageConfig,
    *,
    record: TrackingRecord,
    operation: TrackingOperation,
    error_type: str,
    expected_revision: int,
    timestamp: str,
) -> dict[str, Any]:
    """Persist RECOVERY_REQUIRED after the safe AB result could not be stored.

    The external call happened but its local evidence could not be persisted,
    so the record/operation enter RECOVERY_REQUIRED (never a blindly retried
    FAILED) and only recovery may resolve them (§8.3/§13.3).
    """
    reason_code = error_type or "result_persist_failed"
    next_record = transition_record(
        record,
        status=TRACKING_STATUS_RECOVERY_REQUIRED,
        audit_action=TRACKING_AUDIT_RESULT_PERSIST_FAILED,
        audit_actor=TRACKING_AUDIT_ACTOR_SYSTEM,
        operation_id=operation.operation_id,
        reason_code=reason_code,
        safe_message=SUBMIT_PERSIST_FAILED_MESSAGE,
        now=timestamp,
    )
    next_record = replace(
        next_record,
        last_error={
            "error_type": "result_persist_failed",
            "reason_code": reason_code,
            "safe_message": SUBMIT_PERSIST_FAILED_MESSAGE,
        },
    )
    record_final = compare_and_swap_tracking_record(
        config,
        record.tracking_id,
        base_revision=record.revision,
        record=next_record,
    )
    compare_and_swap_tracking_operation(
        config,
        operation.operation_id,
        expected_state=TRACKING_OPERATION_STATE_IN_PROGRESS,
        record=transition_tracking_operation(
            operation,
            state=TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
            error_type="result_persist_failed",
            now=timestamp,
        ),
    )
    _sync_queue_projection(config, record_final, TRACKING_STATUS_RECOVERY_REQUIRED)
    return _submit_result_payload(
        record=record_final,
        outcome=TRACKING_STATUS_RECOVERY_REQUIRED,
        checked_revision=expected_revision,
        operation_id=operation.operation_id,
        issues=(),
        request=None,
        timestamp=timestamp,
    )


# ---------------------------------------------------------------------------
# Blocking business outcome (NEEDS_RECONFIRM)
# ---------------------------------------------------------------------------


def _blocked_needs_reconfirm(
    config: StorageConfig,
    *,
    record: TrackingRecord,
    issues: tuple[RevalidationIssue, ...],
    expected_revision: int,
    request: dict[str, Any] | None,
    timestamp: str,
) -> dict[str, Any]:
    """Persist a blocking submit outcome as NEEDS_RECONFIRM (no external call)."""
    next_record = record
    if record.status in {TRACKING_STATUS_PENDING_SUBMIT, TRACKING_STATUS_SUBMIT_FAILED}:
        primary = issues[0] if issues else None
        audit_action = (
            TRACKING_AUDIT_PLAN_CHANGE_DETECTED
            if any(issue.code == REVALIDATE_ISSUE_REQUEST_CHANGED for issue in issues)
            else TRACKING_AUDIT_REVALIDATION_FAILED
        )
        next_record = transition_record(
            record,
            status=TRACKING_STATUS_NEEDS_RECONFIRM,
            audit_action=audit_action,
            audit_actor=TRACKING_AUDIT_ACTOR_SYSTEM,
            reason_code=primary.code if primary else None,
            safe_message=primary.message if primary else None,
            now=timestamp,
        )
        try:
            next_record = compare_and_swap_tracking_record(
                config,
                record.tracking_id,
                base_revision=record.revision,
                record=next_record,
            )
        except Stage1Error as exc:
            if exc.error_type == "tracking_revision_conflict":
                next_record = load_tracking_record(config, record.tracking_id)
            else:
                raise
    return _submit_result_payload(
        record=next_record,
        outcome=TRACKING_STATUS_NEEDS_RECONFIRM,
        checked_revision=expected_revision,
        operation_id=None,
        issues=issues,
        request=request,
        timestamp=timestamp,
    )


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _guard_confirm(confirm: bool) -> None:
    if confirm is not True:
        raise Stage1Error(
            "tracking_confirmation_required",
            "提交 Auto Bangumi 必须显式确认最新方案",
            "tracking_submit",
            {"field": "confirm"},
        )


def _guard_expected_revision(expected_revision: int, record: TrackingRecord) -> None:
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
        raise Stage1Error(
            "tracking_revision_conflict",
            "expected_revision 必须是正整数",
            "tracking_submit",
            {"field": "expected_revision", "current_revision": record.revision},
        )
    if expected_revision != record.revision:
        raise Stage1Error(
            "tracking_revision_conflict",
            "追番记录版本已变化，请刷新后重试",
            "tracking_submit",
            {
                "field": "expected_revision",
                "expected_revision": expected_revision,
                "current_revision": record.revision,
            },
        )


def _guard_replay_binding(
    operation: TrackingOperation,
    *,
    record: TrackingRecord,
    expected_revision: int,
    fingerprint: str | None,
) -> None:
    """Raise ``tracking_idempotency_conflict`` when a same-key binding differs."""
    if (
        operation.tracking_id != record.tracking_id
        or operation.operation != TRACKING_OPERATION_KIND_SUBMIT
        or operation.expected_revision != expected_revision
    ):
        raise Stage1Error(
            "tracking_idempotency_conflict",
            "同一幂等键已绑定不同的提交内容，不能复用",
            "tracking_submit",
            {"field": "idempotency_key"},
        )
    if fingerprint is not None and operation.request_fingerprint != fingerprint:
        raise Stage1Error(
            "tracking_idempotency_conflict",
            "同一幂等键已绑定不同的提交内容，不能复用",
            "tracking_submit",
            {"field": "idempotency_key"},
        )


def _guard_no_inflight_operation(config: StorageConfig, record: TrackingRecord) -> None:
    operation_id = record.current_operation_id
    if not operation_id:
        return
    try:
        operation = load_tracking_operation(config, operation_id)
    except Stage1Error:
        # An unreadable current operation is treated as in-flight (conservative):
        # a new submit must not mask an operation whose outcome is unknown.
        _raise_operation_in_progress(record)
    if operation.state not in TRACKING_OPERATION_TERMINAL_STATES:
        _raise_operation_in_progress(record)


def _raise_operation_in_progress(record: TrackingRecord) -> None:
    raise Stage1Error(
        "tracking_operation_in_progress",
        "存在尚未完成的提交操作，请先恢复后再提交",
        "tracking_submit",
        {"field": "status", "current_status": record.status},
    )


def _raise_state_conflict(
    record: TrackingRecord,
    *,
    message: str = "当前追番记录状态不允许提交",
    failed_step: str = "tracking_submit",
) -> None:
    action_codes = [
        action.get("code")
        for action in tracking_available_actions(record.status)
        if isinstance(action.get("code"), str)
    ]
    raise Stage1Error(
        "tracking_state_conflict",
        message,
        failed_step,
        {
            "field": "status",
            "current_status": record.status,
            "available_actions": action_codes,
        },
    )


def _find_operation(
    config: StorageConfig,
    idempotency_key: str,
) -> TrackingOperation | None:
    """Load the operation bound to ``idempotency_key``, or None when absent."""
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        return None
    operation_id = tracking_operation_id_for_idempotency_key(idempotency_key)
    try:
        return load_tracking_operation(config, operation_id)
    except Stage1Error as exc:
        if exc.error_type == "tracking_operation_not_found":
            return None
        raise


def _tolerant_load_request(
    config: StorageConfig,
    record: TrackingRecord,
) -> dict[str, Any] | None:
    if not record.request_id:
        return None
    try:
        loaded = load_request_snapshot(config, record.request_id)
        return loaded if isinstance(loaded, dict) else None
    except Stage1Error:
        return None


def _sync_queue_projection(
    config: StorageConfig,
    record: TrackingRecord,
    tracking_status: str,
) -> None:
    """Best-effort mirror of a tracking state into any legacy queue item.

    Used at the §13.2 SUBMITTING boundary and after §13.3 terminal outcomes so
    the old batch queue stays a faithful compat projection of the authoritative
    TrackingRecord.  Never raises and never overwrites a durable queue success.
    """
    if not record.request_id:
        return
    sync_queue_projection_for_tracking(
        config,
        request_id=record.request_id,
        tracking_status=tracking_status,
    )


def _run_submit_one(
    submit_one: SubmitOne | None,
    request: dict[str, Any],
    ab_config: Any,
) -> dict[str, Any]:
    """Invoke the AB create seam, folding a raised error into a result dict."""
    seam = submit_one or compose_ab_submit_one()
    try:
        result = seam(request, ab_config)
        return result if isinstance(result, dict) else {"success": False, "error": None}
    except Stage1Error as exc:
        return {"success": False, "error": exc.as_dict()}
    except Exception:  # pragma: no cover - safety boundary
        return {
            "success": False,
            "error": {
                "error_type": "unexpected_error",
                "error_message": "Auto Bangumi 提交发生未预期错误",
                "failed_step": "submit_tracking_item",
                "details": {},
            },
        }


def _default_persist_ab_result(config: StorageConfig) -> PersistAbResult:
    """Build the default AB-result persister (sanitize + request + ab_results)."""

    def persist(
        request: dict[str, Any],
        ab_submit_result: dict[str, Any],
    ) -> dict[str, Any]:
        sanitized = _sanitize_ab_submit_result(ab_submit_result)
        updated = deepcopy(request)
        updated["ab_submit_result"] = sanitized
        updated["updated_at"] = utc_now()
        save_request_snapshot(config, updated)
        save_ab_submit_result(config, updated)
        return updated

    return persist


def _submit_result_payload(
    *,
    record: TrackingRecord,
    outcome: str,
    checked_revision: int,
    operation_id: str | None,
    issues: tuple[RevalidationIssue, ...],
    request: dict[str, Any] | None,
    timestamp: str,
) -> dict[str, Any]:
    """Build the safe US-225 submit result (HTTP 200 business result)."""
    valid_count = 0
    if isinstance(request, dict):
        resources = serialize_request_safe_info(request, storage_profile=None).get("resources")
        if isinstance(resources, dict):
            count = resources.get("valid_resource_count")
            valid_count = count if isinstance(count, int) and count >= 0 else 0
    return {
        "tracking_id": record.tracking_id,
        "outcome": outcome,
        "checked_revision": checked_revision,
        "next_revision": record.revision,
        "checked_at": timestamp,
        "operation_id": operation_id,
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


__all__ = ["PersistAbResult", "SubmitOne", "run_tracking_retry", "run_tracking_submit"]
