"""Recovery orchestration for unknown/incomplete tracking outcomes (US-226).

``POST /api/v1/tracking/items/{tracking_id}/recover`` resolves a tracking
record whose external outcome is unknown (``VERIFYING_EXTERNAL``), whose local
result could not be made durable (``RECOVERY_REQUIRED``), or whose state is
``UNKNOWN``.  Stage 29 PRD §8.3/§11.8 — a record in one of these states must
never be blindly retried (D29-07); only an explicit recovery may move it to
``ACTIVE`` / ``SUBMIT_FAILED`` / ``RECOVERY_REQUIRED``.

This module is the Web-service layer that

1. re-runs the historical-backfill coordinator (every tracking API access does);
2. loads the TrackingRecord and guards ``expected_revision`` (409
   ``tracking_revision_conflict``) and the recoverable tracking status (409
   ``tracking_state_conflict``);
3. guards the manual actions (``MARK_SUCCEEDED``/``MARK_FAILED`` require
   ``confirm=true`` → 400 ``tracking_confirmation_required``);
4. gathers **local-only** evidence (the current operation's state + the
   Request's persisted safe AB result — never an external call) and runs the
   pure :func:`classify_auto_recovery` decision for ``AUTO``, or maps a manual
   action to its outcome;
5. persists the resulting TrackingRecord transition (status + audit + revision
   through one CAS) and advances an in-flight operation to its matching
   terminal state, then returns the safe §11.8 payload.

Security: recovery never contacts Auto Bangumi, never accepts an external
id/URL/raw result, and manual actions write ``USER`` audit events.  No file
name, path, credential, URL, magnet or raw upstream text is ever returned.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ab_engine.controllers.ab_config import AutoBangumiConfig
from ab_engine.controllers.ab_http_client import UrlopenAutoBangumiHttpTransport
from ab_engine.controllers.ab_management_client import Legacy31ManagementClient
from ab_engine.controllers.reconcile import ReconcileDecision, normalize_match_text
from ab_engine.models.management import ExternalSubscription
from apps.migu_orca_web.save_confirm_service import compute_request_fingerprint
from apps.migu_orca_web.serializers import serialize_request_safe_info
from apps.migu_orca_web.tracking_external_check import (
    DEFAULT_CHECK_POLICY,
    CheckPolicy,
    attempt_timeout_seconds,
    read_snapshot_bounded,
)
from apps.migu_orca_web.tracking_management_service import recover_tracking_management
from apps.migu_orca_web.tracking_migration_service import run_tracking_migration
from apps.migu_orca_web.tracking_serializers import (
    tracking_available_actions,
    tracking_summary_fields,
)
from shared.errors import Stage1Error
from storage_engine.controllers.operation_repository import (
    compare_and_swap_tracking_operation,
    load_tracking_operation,
    recover_tracking_operation,
)
from storage_engine.controllers.request_repository import load_request_snapshot
from storage_engine.controllers.storage_config import StorageConfig
from storage_engine.controllers.tracking_repository import (
    compare_and_swap_tracking_record,
    load_tracking_record,
)
from tracking_engine.controllers.recover import (
    RECOVERABLE_STATUSES,
    RECOVERY_ACTION_AUTO,
    RECOVERY_ACTION_MARK_FAILED,
    RECOVERY_ACTION_MARK_SUCCEEDED,
    RECOVERY_ACTION_VERIFY_EXTERNAL,
    RECOVERY_ACTIONS,
    RECOVERY_AUTO_FAILED_MESSAGE,
    RECOVERY_AUTO_SUCCEEDED_MESSAGE,
    RECOVERY_MANUAL_FAILED_MESSAGE,
    RECOVERY_MANUAL_SUCCEEDED_MESSAGE,
    RECOVERY_NEEDS_MANUAL_MESSAGE,
    AutoRecoveryDecision,
    RecoveryEvidence,
    classify_auto_recovery,
    recovery_outcome_for_manual,
)
from tracking_engine.controllers.submit import (
    CONFIRM_REASON_AMBIGUOUS,
    CONFIRM_REASON_CAPABILITY,
    CONFIRM_REASON_CONFIRMED,
    CONFIRM_REASON_NOT_FOUND,
    CONFIRM_REASON_UNREADABLE,
    confirm_reason_for_error,
    match_subscription_by_exact_rss,
)
from tracking_engine.models.operation import (
    TRACKING_OPERATION_STATE_FAILED,
    TRACKING_OPERATION_STATE_IN_PROGRESS,
    TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
    TRACKING_OPERATION_STATE_SUCCEEDED,
    TrackingOperation,
    transition_tracking_operation,
)
from tracking_engine.models.tracking import (
    TRACKING_AUDIT_ACTOR_SYSTEM,
    TRACKING_AUDIT_ACTOR_USER,
    TRACKING_AUDIT_RECOVERY_AUTO_FAILED,
    TRACKING_AUDIT_RECOVERY_AUTO_SUCCEEDED,
    TRACKING_AUDIT_RECOVERY_EXTERNAL_VERIFIED,
    TRACKING_AUDIT_RECOVERY_MANUAL_FAILED,
    TRACKING_AUDIT_RECOVERY_MANUAL_SUCCEEDED,
    TRACKING_AUDIT_RECOVERY_NEEDS_MANUAL,
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_DISABLED,
    TRACKING_STATUS_RECOVERY_REQUIRED,
    TrackingRecord,
    transition_record,
    utc_now,
)

_RECOVER_FAILED_STEP = "tracking_recover"


def _verify_external(
    config: StorageConfig,
    *,
    record: TrackingRecord,
    request: dict[str, Any] | None,
    checked_revision: int,
    timestamp: str,
    ab_config: AutoBangumiConfig,
    management_client: Any | None,
    connection_ref: str | None = None,
    expected_operation: TrackingOperation | None = None,
    expected_record_revision: int | None = None,
    read_policy: CheckPolicy | None = None,
) -> dict[str, Any]:
    """Read-only recovery against one verified management snapshot."""
    try:
        policy = read_policy or DEFAULT_CHECK_POLICY
        client = management_client or _management_client(
            ab_config, timeout=attempt_timeout_seconds(policy)
        )
    except Stage1Error as exc:
        # A saved connection this build cannot read through is a proven,
        # non-retriable capability failure, never an unknown object state.
        return _verification_needs_manual(config, record=record, request=request,
            checked_revision=checked_revision, timestamp=timestamp,
            reason=confirm_reason_for_error(exc.error_type))
    read = read_snapshot_bounded(
        lambda deadline: client.read_snapshot(deadline=deadline), policy=policy
    )
    if read.snapshot is None:
        # A read that never succeeded proves nothing about the object; only the
        # proven failure class is reported (issue #183).
        return _verification_needs_manual(config, record=record, request=request,
            checked_revision=checked_revision, timestamp=timestamp,
            reason=read.reason or CONFIRM_REASON_UNREADABLE)
    try:
        capabilities, subscriptions, rss_items = read.snapshot
        operation_kind = _load_current_operation(config, record)
        capability_ok = (capabilities.probe_status == "VERIFIED"
                         and capabilities.subscription_list == "SUPPORTED"
                         and capabilities.external_verify == "SUPPORTED")
        if not capability_ok:
            matches, match_reason = [], None
        else:
            matches, match_reason = _external_matches(
                record, subscriptions, request=request, connection_ref=connection_ref,
                is_submit=operation_kind is not None and operation_kind.operation == "SUBMIT",
                rss_items=rss_items,
            )
    except Stage1Error:
        raise
    except (TimeoutError, ConnectionError, OSError, TypeError, ValueError):
        return _verification_needs_manual(config, record=record, request=request,
            checked_revision=checked_revision, timestamp=timestamp,
            reason=CONFIRM_REASON_UNREADABLE)
    if not capability_ok:
        return _verification_needs_manual(config, record=record, request=request,
            checked_revision=checked_revision, timestamp=timestamp,
            reason=CONFIRM_REASON_CAPABILITY)
    if len(matches) != 1:
        # Issue #183 review: the matcher's own proven reason survives, so several
        # identical objects are reported as ambiguous instead of "not found".
        reason = match_reason or (
            CONFIRM_REASON_AMBIGUOUS if matches else CONFIRM_REASON_NOT_FOUND
        )
        return _verification_needs_manual(config, record=record, request=request,
            checked_revision=checked_revision, timestamp=timestamp, reason=reason)
    external = matches[0]
    if expected_operation is not None:
        current_record = load_tracking_record(config, record.tracking_id)
        current_operation = _load_current_operation(config, current_record)
        current_request = _tolerant_load_request(config, current_record)
        if (current_record.revision != expected_record_revision
                or current_record.current_operation_id != expected_operation.operation_id
                or current_operation is None
                or current_operation.operation_id != expected_operation.operation_id
                or current_operation.tracking_id != expected_operation.tracking_id
                or current_operation.operation != expected_operation.operation
                or current_operation.state != expected_operation.state
                or current_operation.connection_ref != expected_operation.connection_ref
                or current_operation.request_fingerprint != expected_operation.request_fingerprint
                or not isinstance(current_request, dict)
                or current_request.get("request_id") != (request or {}).get("request_id")
                or compute_request_fingerprint(current_request) != expected_operation.request_fingerprint):
            raise Stage1Error("tracking_connection_mismatch", "外部核验期间历史操作已变化", _RECOVER_FAILED_STEP)
    if connection_ref is not None and operation_kind is not None and operation_kind.operation == "SUBMIT":
        decision = ReconcileDecision(external_id=external.external_id, tracking_id=record.tracking_id,
            status=TRACKING_STATUS_ACTIVE, match_reason="EXTERNAL_ID",
            subscription_id=external.external_id, rss_ids=external.rss_ids)
        mapping = decision.safe_mapping(connection_ref=connection_ref)
        mapping["last_verified_at"] = timestamp
        record = replace(record, external_mapping=mapping)
    return _persist_recovery_outcome(
        config, action=RECOVERY_ACTION_VERIFY_EXTERNAL, record=record,
        operation=operation_kind, target_status=TRACKING_STATUS_DISABLED if external.deleted else TRACKING_STATUS_ACTIVE,
        audit_action=TRACKING_AUDIT_RECOVERY_EXTERNAL_VERIFIED, audit_actor=TRACKING_AUDIT_ACTOR_SYSTEM,
        reason_code="external_verified_disabled" if external.deleted else "external_verified_active",
        safe_message="已只读核验 Auto Bangumi 状态并恢复追番记录", target_operation_state=TRACKING_OPERATION_STATE_SUCCEEDED,
        request=request, checked_revision=checked_revision, needs_manual=False, timestamp=timestamp)


def _management_client(
    config: AutoBangumiConfig, *, timeout: float = 30
) -> Legacy31ManagementClient:
    if config.auth_mode != "password":
        raise Stage1Error("ab_management_unsupported", "当前认证模式不支持外部核验", _RECOVER_FAILED_STEP)
    return Legacy31ManagementClient(config, transport=UrlopenAutoBangumiHttpTransport(), timeout=timeout)


def _external_matches(
    record: TrackingRecord, subscriptions: list[ExternalSubscription], *, request: dict[str, Any] | None = None,
    connection_ref: str | None = None, is_submit: bool = False,
    rss_items: list[Any] | None = None,
) -> tuple[list[ExternalSubscription], str | None]:
    """Return the matched objects plus the proven reason when nothing matched.

    The reason is carried out of the matcher (issue #183 review) instead of being
    collapsed into "no match": an ambiguous snapshot must never be reported as
    "not found", because the two lead to different user actions.
    """
    mapping = record.external_mapping if isinstance(record.external_mapping, dict) else {}
    if connection_ref is not None and not is_submit and (mapping.get("schema_version") != 2 or mapping.get("connection_ref") != connection_ref):
        return [], CONFIRM_REASON_NOT_FOUND
    external_id = mapping.get("subscription_id")
    if connection_ref is not None and is_submit:
        # Issue #182: the later read-only check uses exactly the same confirmation
        # rule as the post-submit read-back — the server-private exact RSS
        # identity and its unique owning subscription — so the two can never
        # reach different conclusions about the same snapshot.
        match = match_subscription_by_exact_rss(
            _request_selected_rss_url(request),
            (None, subscriptions, list(rss_items or ())),
        )
        if match.status == CONFIRM_REASON_CONFIRMED and match.subscription is not None:
            matched = match.subscription
            return [item for item in subscriptions if item.external_id == matched.external_id], None
        return [], match.status
    if connection_ref is not None:
        if not isinstance(request, dict):
            return [], CONFIRM_REASON_UNREADABLE
        confirmable = request.get("confirmable_config")
        selected_url = confirmable.get("selected_rss_url") if isinstance(confirmable, dict) else None
        summary = record.plan_summary
        title, season, group = summary.get("title"), summary.get("season"), summary.get("subtitle_group")
        if (not isinstance(selected_url, str) or not selected_url.strip()
                or not isinstance(title, str) or not title.strip()
                or not isinstance(season, int) or isinstance(season, bool) or season < 1
                or not isinstance(group, str) or not group.strip()):
            return [], CONFIRM_REASON_UNREADABLE
        return [item for item in subscriptions if item.season == season and item.subtitle_group is not None
                and isinstance(item.title, str) and item.title.strip()
                and normalize_match_text(item.title) == normalize_match_text(title)
                and normalize_match_text(item.subtitle_group) == normalize_match_text(group)
                and selected_url in item.rss_urls], None
    if isinstance(external_id, str) and external_id:
        return [item for item in subscriptions if item.external_id == external_id], None
    if connection_ref is not None:
        return [], CONFIRM_REASON_NOT_FOUND
    summary = record.plan_summary
    title = summary.get("title")
    season = summary.get("season")
    group = summary.get("subtitle_group")
    if not isinstance(title, str) or not title.strip() or not isinstance(season, int) or isinstance(season, bool):
        return [], CONFIRM_REASON_UNREADABLE
    if not isinstance(group, str) or not group.strip():
        return [], CONFIRM_REASON_UNREADABLE
    return [
        item for item in subscriptions
        if item.season == season
        and item.subtitle_group is not None
        and " ".join(item.title.split()).casefold() == " ".join(title.split()).casefold()
        and " ".join(item.subtitle_group.split()).casefold() == " ".join(group.split()).casefold()
    ], None


def _request_selected_rss_url(request: dict[str, Any] | None) -> str | None:
    """The server-private exact RSS identity of the saved plan, if any."""
    confirmable = request.get("confirmable_config") if isinstance(request, dict) else None
    if not isinstance(confirmable, dict):
        return None
    value = confirmable.get("selected_rss_url")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _verification_needs_manual(
    config: StorageConfig,
    *,
    record: TrackingRecord,
    request: dict[str, Any] | None,
    checked_revision: int,
    timestamp: str,
    reason: str,
) -> dict[str, Any]:
    stored_reason = None
    if isinstance(record.last_error, dict):
        stored_reason = record.last_error.get("reason_code")
    if record.status == TRACKING_STATUS_RECOVERY_REQUIRED and stored_reason == reason:
        next_record = record
    else:
        next_record = transition_record(
            record,
            status=TRACKING_STATUS_RECOVERY_REQUIRED,
            audit_action=TRACKING_AUDIT_RECOVERY_NEEDS_MANUAL,
            audit_actor=TRACKING_AUDIT_ACTOR_SYSTEM,
            reason_code=reason,
            safe_message=RECOVERY_NEEDS_MANUAL_MESSAGE,
            now=timestamp,
        )
        next_record = replace(
            next_record,
            last_error={
                "error_type": reason,
                "reason_code": reason,
                "safe_message": RECOVERY_NEEDS_MANUAL_MESSAGE,
            },
        )
        next_record = compare_and_swap_tracking_record(
            config, record.tracking_id, base_revision=record.revision, record=next_record
        )
    _sync_queue_projection(config, next_record, TRACKING_STATUS_RECOVERY_REQUIRED)
    return _recover_result_payload(
        record=next_record, action=RECOVERY_ACTION_VERIFY_EXTERNAL,
        outcome=TRACKING_STATUS_RECOVERY_REQUIRED, checked_revision=checked_revision,
        operation_id=record.current_operation_id, needs_manual=True, request=request,
        timestamp=timestamp, verification_reason=reason,
    )


def run_tracking_recover(
    config: StorageConfig,
    *,
    tracking_id: str,
    expected_revision: int,
    action: str,
    confirm: bool,
    now: str | None = None,
    ab_config: AutoBangumiConfig | None = None,
    management_client: Any | None = None,
    connection_ref: str | None = None,
    expected_operation_id: str | None = None,
    expected_operation_kind: str | None = None,
    read_policy: CheckPolicy | None = None,
) -> dict[str, Any]:
    """Run one explicit recovery for a tracking item.

    ``AUTO`` is a pure-local reconciliation that never touches Auto Bangumi;
    ``MARK_SUCCEEDED``/``MARK_FAILED`` require ``confirm=true`` and write a
    ``USER`` audit.  A persisted recovery outcome (``ACTIVE``/``SUBMIT_FAILED``/
    ``RECOVERY_REQUIRED``) is returned as an HTTP-200-safe result dict; only
    preconditions (missing record, stale revision, non-recoverable state,
    missing manual confirmation) raise.
    """
    run_tracking_migration(config=config)

    timestamp = now or utc_now()
    record = load_tracking_record(config, tracking_id)
    checked_revision = record.revision
    _guard_expected_revision(expected_revision, record)

    if record.status not in RECOVERABLE_STATUSES:
        _raise_state_conflict(record)

    if action not in RECOVERY_ACTIONS:
        raise Stage1Error(
            "validation_error",
            "恢复动作必须是 AUTO、MARK_SUCCEEDED、MARK_FAILED 或 VERIFY_EXTERNAL",
            _RECOVER_FAILED_STEP,
            {"field": "action"},
        )

    manual = action in {RECOVERY_ACTION_MARK_SUCCEEDED, RECOVERY_ACTION_MARK_FAILED}
    if manual and confirm is not True:
        raise Stage1Error(
            "tracking_confirmation_required",
            "人工恢复必须显式确认核验结果",
            _RECOVER_FAILED_STEP,
            {"field": "confirm"},
        )

    operation = _load_current_operation(config, record)
    if expected_operation_id is not None:
        if (operation is None or operation.operation_id != expected_operation_id
                or operation.tracking_id != record.tracking_id
                or (expected_operation_kind is not None and operation.operation != expected_operation_kind)
                or (connection_ref is not None and operation.connection_ref != connection_ref)
                or operation.state not in {"IN_PROGRESS", "OUTCOME_UNKNOWN", "RECOVERY_REQUIRED"}):
            raise Stage1Error("tracking_connection_mismatch", "历史操作绑定已变化，不能进行外部核验", _RECOVER_FAILED_STEP)
        if operation.operation == "SUBMIT":
            request = load_request_snapshot(config, record.request_id) if record.request_id else None
            if not isinstance(request, dict) or compute_request_fingerprint(request) != operation.request_fingerprint:
                raise Stage1Error("tracking_connection_mismatch", "历史请求已变化，不能进行外部核验", _RECOVER_FAILED_STEP)
            mapping = record.external_mapping
            if mapping is not None and (not isinstance(mapping, dict) or mapping.get("schema_version") != 2
                                        or mapping.get("connection_ref") != connection_ref):
                raise Stage1Error("tracking_connection_mismatch", "历史映射未绑定当前连接", _RECOVER_FAILED_STEP)
        elif connection_ref is not None:
            mapping = record.external_mapping
            if (not isinstance(mapping, dict) or mapping.get("schema_version") != 2
                    or mapping.get("connection_ref") != connection_ref):
                raise Stage1Error("tracking_connection_mismatch", "历史映射未绑定当前连接", _RECOVER_FAILED_STEP)
    if action == RECOVERY_ACTION_VERIFY_EXTERNAL and operation is not None and operation.operation in {
        "MODIFY", "SET_ENABLED", "DELETE_EXTERNAL", "REFRESH_RSS"
    }:
        if ab_config is None:
            raise Stage1Error(
                "validation_error", "外部核验需要连接配置", _RECOVER_FAILED_STEP, {"field": "ab_config"}
            )
        try:
            client = management_client or _management_client(ab_config)
        except Exception:
            return _verification_needs_manual(
                config, record=record, request=None, checked_revision=checked_revision,
                timestamp=timestamp, reason="management_capability_unknown",
            )
        result = recover_tracking_management(
            config, record=record, operation=operation, management_client=client, now=timestamp,
            connection_ref=connection_ref,
        )
        resolved_record = load_tracking_record(config, tracking_id)
        result.update(
            {
                "tracking_id": resolved_record.tracking_id,
                "action": RECOVERY_ACTION_VERIFY_EXTERNAL,
                "checked_revision": checked_revision,
                "next_revision": resolved_record.revision,
                "checked_at": timestamp,
                "tracking": tracking_summary_fields(resolved_record, valid_resource_count=0),
            }
        )
        return result
    request = _tolerant_load_request(config, record)
    ab_result = _ab_result_of(request)

    if action == RECOVERY_ACTION_VERIFY_EXTERNAL:
        if ab_config is None:
            raise Stage1Error(
                "validation_error", "外部核验需要连接配置", _RECOVER_FAILED_STEP, {"field": "ab_config"}
            )
        return _verify_external(
            config,
            record=record,
            request=request,
            checked_revision=checked_revision,
            timestamp=timestamp,
            ab_config=ab_config,
            management_client=management_client,
            connection_ref=connection_ref,
            expected_operation=operation,
            expected_record_revision=checked_revision,
            read_policy=read_policy,
        )

    if action == RECOVERY_ACTION_AUTO:
        decision = classify_auto_recovery(
            RecoveryEvidence(
                operation_state=operation.state if operation is not None else None,
                ab_result=ab_result,
            )
        )
        return _apply_auto_recovery(
            config,
            record=record,
            operation=operation,
            request=request,
            decision=decision,
            checked_revision=checked_revision,
            timestamp=timestamp,
        )

    outcome = recovery_outcome_for_manual(action)
    audit_action = (
        TRACKING_AUDIT_RECOVERY_MANUAL_SUCCEEDED
        if outcome == TRACKING_STATUS_ACTIVE
        else TRACKING_AUDIT_RECOVERY_MANUAL_FAILED
    )
    safe_message = (
        RECOVERY_MANUAL_SUCCEEDED_MESSAGE
        if outcome == TRACKING_STATUS_ACTIVE
        else RECOVERY_MANUAL_FAILED_MESSAGE
    )
    reason_code = (
        "manual_recovery_succeeded" if outcome == TRACKING_STATUS_ACTIVE else "manual_recovery_failed"
    )
    return _persist_recovery_outcome(
        config,
        action=action,
        record=record,
        operation=operation,
        target_status=outcome,
        audit_action=audit_action,
        audit_actor=TRACKING_AUDIT_ACTOR_USER,
        reason_code=reason_code,
        safe_message=safe_message,
        target_operation_state=(
            TRACKING_OPERATION_STATE_SUCCEEDED
            if outcome == TRACKING_STATUS_ACTIVE
            else TRACKING_OPERATION_STATE_FAILED
        ),
        request=request,
        checked_revision=checked_revision,
        needs_manual=False,
        timestamp=timestamp,
    )


# ---------------------------------------------------------------------------
# AUTO decision application
# ---------------------------------------------------------------------------


def _apply_auto_recovery(
    config: StorageConfig,
    *,
    record: TrackingRecord,
    operation: TrackingOperation | None,
    request: dict[str, Any] | None,
    decision: AutoRecoveryDecision,
    checked_revision: int,
    timestamp: str,
) -> dict[str, Any]:
    """Persist the AUTO recovery outcome from the pure classifier."""
    if not decision.resolved:
        # No clear local evidence: the record must be resolved manually.  A
        # VERIFYING_EXTERNAL/UNKNOWN record moves to RECOVERY_REQUIRED; one that
        # is already RECOVERY_REQUIRED stays (an unchanged state is reported
        # without a revision bump/audit).  An in-flight operation is finalised
        # to RECOVERY_REQUIRED as durable evidence that only recovery applies.
        if record.status == TRACKING_STATUS_RECOVERY_REQUIRED:
            next_record = record
            needs_manual = True
            _terminalize_in_flight_operation(
                config,
                operation,
                target_operation_state=TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
                error_type="requires_manual_recovery",
                timestamp=timestamp,
            )
        else:
            next_record = transition_record(
                record,
                status=TRACKING_STATUS_RECOVERY_REQUIRED,
                audit_action=TRACKING_AUDIT_RECOVERY_NEEDS_MANUAL,
                audit_actor=TRACKING_AUDIT_ACTOR_SYSTEM,
                operation_id=operation.operation_id if operation is not None else None,
                reason_code="requires_manual_recovery",
                safe_message=RECOVERY_NEEDS_MANUAL_MESSAGE,
                now=timestamp,
            )
            next_record = compare_and_swap_tracking_record(
                config,
                record.tracking_id,
                base_revision=record.revision,
                record=next_record,
            )
            needs_manual = True
            _terminalize_in_flight_operation(
                config,
                operation,
                target_operation_state=TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
                error_type="requires_manual_recovery",
                timestamp=timestamp,
            )
        _sync_queue_projection(
            config,
            next_record,
            TRACKING_STATUS_RECOVERY_REQUIRED,
        )
        return _recover_result_payload(
            record=next_record,
            action=RECOVERY_ACTION_AUTO,
            outcome=TRACKING_STATUS_RECOVERY_REQUIRED,
            checked_revision=checked_revision,
            operation_id=operation.operation_id if operation is not None else None,
            needs_manual=needs_manual,
            request=request,
            timestamp=timestamp,
        )

    if decision.outcome == TRACKING_STATUS_ACTIVE:
        audit_action = TRACKING_AUDIT_RECOVERY_AUTO_SUCCEEDED
        safe_message = RECOVERY_AUTO_SUCCEEDED_MESSAGE
        reason_code = "auto_recovery_succeeded"
        target_operation_state = TRACKING_OPERATION_STATE_SUCCEEDED
    else:
        audit_action = TRACKING_AUDIT_RECOVERY_AUTO_FAILED
        safe_message = RECOVERY_AUTO_FAILED_MESSAGE
        reason_code = "auto_recovery_failed"
        target_operation_state = TRACKING_OPERATION_STATE_FAILED

    return _persist_recovery_outcome(
        config,
        action=RECOVERY_ACTION_AUTO,
        record=record,
        operation=operation,
        target_status=decision.outcome,
        audit_action=audit_action,
        audit_actor=TRACKING_AUDIT_ACTOR_SYSTEM,
        reason_code=reason_code,
        safe_message=safe_message,
        target_operation_state=target_operation_state,
        request=request,
        checked_revision=checked_revision,
        needs_manual=False,
        timestamp=timestamp,
    )


# ---------------------------------------------------------------------------
# Persisting a resolved recovery
# ---------------------------------------------------------------------------


def _persist_recovery_outcome(
    config: StorageConfig,
    *,
    action: str,
    record: TrackingRecord,
    operation: TrackingOperation | None,
    target_status: str,
    audit_action: str,
    audit_actor: str,
    reason_code: str,
    safe_message: str,
    request: dict[str, Any] | None,
    checked_revision: int,
    needs_manual: bool,
    timestamp: str,
    target_operation_state: str | None = None,
) -> dict[str, Any]:
    """Transition the record (and its in-flight operation) to a resolved state."""
    operation_id = operation.operation_id if operation is not None else None
    next_record = transition_record(
        record,
        status=target_status,
        audit_action=audit_action,
        audit_actor=audit_actor,
        operation_id=operation_id,
        reason_code=reason_code,
        safe_message=safe_message,
        now=timestamp,
    )
    record_final = compare_and_swap_tracking_record(
        config,
        record.tracking_id,
        base_revision=record.revision,
        record=next_record,
    )

    if target_operation_state is not None:
        _terminalize_in_flight_operation(
            config,
            operation,
            target_operation_state=target_operation_state,
            error_type=reason_code,
            timestamp=timestamp,
        )
    _sync_queue_projection(config, record_final, target_status)
    return _recover_result_payload(
        record=record_final,
        action=action,
        outcome=target_status,
        checked_revision=checked_revision,
        operation_id=operation_id,
        needs_manual=needs_manual,
        request=request,
        timestamp=timestamp,
    )


def _terminalize_in_flight_operation(
    config: StorageConfig,
    operation: TrackingOperation | None,
    *,
    target_operation_state: str,
    error_type: str | None,
    timestamp: str,
) -> None:
    """Advance an ``IN_PROGRESS`` operation to its matching terminal state.

    A PREPARED operation proves the external was never called and is left for a
    same-key submit to resume; a terminal operation is already final.  Only the
    ``IN_PROGRESS`` boundary (an external call may have happened) is advanced to
    the terminal recovery verdict so the durable operation record matches the
    recovered tracking state.
    """
    if operation is None or operation.state not in {
        TRACKING_OPERATION_STATE_IN_PROGRESS, "OUTCOME_UNKNOWN", TRACKING_OPERATION_STATE_RECOVERY_REQUIRED
    }:
        return
    terminal_state = _operation_terminal_for(target_operation_state)
    try:
        if operation.state in {"OUTCOME_UNKNOWN", TRACKING_OPERATION_STATE_RECOVERY_REQUIRED}:
            recover_tracking_operation(config, operation.operation_id, operation.state,
                                       target_state=terminal_state, error_type=error_type, now=timestamp)
        else:
            compare_and_swap_tracking_operation(
                config, operation.operation_id,
                expected_state=TRACKING_OPERATION_STATE_IN_PROGRESS,
                record=transition_tracking_operation(
                    operation, state=terminal_state, error_type=error_type, now=timestamp))
    except Stage1Error:
        # A concurrent actor may have advanced the operation; surface storage
        # failures so callers cannot claim the old snapshot was durably settled.
        raise


def _operation_terminal_for(target_operation_state: str) -> str:
    """Map a recovery target operation state to an allowed terminal state.

    ``SUCCEEDED``/``FAILED``/``RECOVERY_REQUIRED`` are all valid operation
    terminal states (IN_PROGRESS has an edge to each of them).
    """
    if target_operation_state not in {
        TRACKING_OPERATION_STATE_SUCCEEDED,
        TRACKING_OPERATION_STATE_FAILED,
        TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
    }:
        raise ValueError(f"invalid recovery operation target: {target_operation_state}")
    return target_operation_state


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _guard_expected_revision(expected_revision: int, record: TrackingRecord) -> None:
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
        raise Stage1Error(
            "tracking_revision_conflict",
            "expected_revision 必须是正整数",
            _RECOVER_FAILED_STEP,
            {"field": "expected_revision", "current_revision": record.revision},
        )
    if expected_revision != record.revision:
        raise Stage1Error(
            "tracking_revision_conflict",
            "追番记录版本已变化，请刷新后重试",
            _RECOVER_FAILED_STEP,
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
        "当前追番记录状态不允许恢复",
        _RECOVER_FAILED_STEP,
        {
            "field": "status",
            "current_status": record.status,
            "available_actions": action_codes,
        },
    )


def _load_current_operation(
    config: StorageConfig,
    record: TrackingRecord,
) -> TrackingOperation | None:
    """Load the record's current operation, tolerating an unreadable reference."""
    operation_id = record.current_operation_id
    if not operation_id:
        return None
    try:
        operation = load_tracking_operation(config, operation_id)
        return operation if isinstance(operation, TrackingOperation) else None
    except Stage1Error:
        return None


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


def _ab_result_of(request: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the Request's persisted safe AB result, or None when absent."""
    if not isinstance(request, dict):
        return None
    ab_result = request.get("ab_submit_result")
    return ab_result if isinstance(ab_result, dict) else None


def _sync_queue_projection(
    config: StorageConfig,
    record: TrackingRecord,
    tracking_status: str,
) -> None:
    """Best-effort mirror of a recovery outcome into any legacy queue item."""
    # Retired US-336: recovery never writes a legacy queue projection.
    return


def _recover_result_payload(
    *,
    record: TrackingRecord,
    action: str,
    outcome: str,
    checked_revision: int,
    operation_id: str | None,
    needs_manual: bool,
    request: dict[str, Any] | None,
    timestamp: str,
    verification_reason: str | None = None,
) -> dict[str, Any]:
    """Build the safe §11.8 recover result (HTTP 200 business result)."""
    valid_count = 0
    if isinstance(request, dict):
        resources = serialize_request_safe_info(request, storage_profile=None).get("resources")
        if isinstance(resources, dict):
            count = resources.get("valid_resource_count")
            valid_count = count if isinstance(count, int) and count >= 0 else 0
    return {
        "tracking_id": record.tracking_id,
        "action": action,
        "outcome": outcome,
        "checked_revision": checked_revision,
        "next_revision": record.revision,
        "checked_at": timestamp,
        "operation_id": operation_id,
        "needs_manual": needs_manual,
        # Issue #183: the proven reason class of a read-only verification, so the
        # page explains 待确认 from evidence instead of guessing a cause.
        "verification_reason": verification_reason,
        "tracking": tracking_summary_fields(record, valid_resource_count=valid_count),
    }


__all__ = ["run_tracking_recover"]
