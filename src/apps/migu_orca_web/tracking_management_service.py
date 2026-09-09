"""Durable coordinator for Auto Bangumi management writes (US-241).

This module is the only layer that joins request-scoped AB credentials, the
read adapter, and the tracking repositories.  Action-specific response and
readback semantics are deliberately left to the later management stories.
"""
from __future__ import annotations

import contextlib
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any, Protocol

from ab_engine.models.management import AutoBangumiCapabilities
from shared.errors import Stage1Error
from storage_engine.controllers.operation_repository import (
    bind_tracking_operation,
    compare_and_swap_tracking_operation,
    load_tracking_operation,
    recover_tracking_operation,
)
from storage_engine.controllers.storage_config import StorageConfig, load_storage_config
from storage_engine.controllers.tracking_repository import (
    compare_and_swap_tracking_record,
    load_tracking_record,
)
from tracking_engine.controllers.management_operation import (
    MANAGEMENT_OUTCOME_DEFINITE_FAILURE,
    MANAGEMENT_OUTCOME_SUCCESS,
    MANAGEMENT_OUTCOME_UNKNOWN,
    canonical_management_fingerprint,
    classify_management_action,
    classify_management_readback,
)
from tracking_engine.controllers.management_target import (
    ManagementBinding,
    ResolvedManagementTarget,
    build_complete_rss_update,
    build_complete_subscription_update,
    build_management_binding,
    build_management_patch,
    resolve_management_target,
)
from tracking_engine.models.operation import (
    TRACKING_OPERATION_KIND_DELETE_EXTERNAL,
    TRACKING_OPERATION_KIND_MODIFY,
    TRACKING_OPERATION_KIND_REFRESH_RSS,
    TRACKING_OPERATION_KIND_SET_ENABLED,
    TRACKING_OPERATION_STATE_IN_PROGRESS,
    TRACKING_OPERATION_STATE_PREPARED,
    TRACKING_OPERATION_STATE_SUCCEEDED,
    TRACKING_OPERATION_TERMINAL_STATES,
    TrackingOperation,
    tracking_operation_id_for_idempotency_key,
    transition_tracking_operation,
)
from tracking_engine.models.tracking import (
    TRACKING_AUDIT_ACTOR_USER,
    TRACKING_AUDIT_MANAGEMENT_FAILED,
    TRACKING_AUDIT_MANAGEMENT_STARTED,
    TRACKING_AUDIT_MANAGEMENT_SUCCEEDED,
    TRACKING_AUDIT_MANAGEMENT_UNKNOWN,
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_DISABLED,
    TRACKING_STATUS_EXTERNAL_DELETED,
    TRACKING_STATUS_RECOVERY_REQUIRED,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
    TrackingRecord,
    append_audit_event,
    build_audit_event,
    transition_record,
    utc_now,
)


class ManagementSnapshotClient(Protocol):
    def read_snapshot(self) -> tuple[AutoBangumiCapabilities, list[Any], list[Any]]: ...


ManagementWriter = Callable[[ResolvedManagementTarget, Mapping[str, Any] | None], Any]

_CAPABILITY_FIELDS = {
    (TRACKING_OPERATION_KIND_MODIFY, "SUBSCRIPTION"): "subscription_modify",
    (TRACKING_OPERATION_KIND_MODIFY, "ASSOCIATED_RSS"): "rss_modify",
    (TRACKING_OPERATION_KIND_SET_ENABLED, "SUBSCRIPTION"): "subscription_enable",
    (TRACKING_OPERATION_KIND_SET_ENABLED, "ASSOCIATED_RSS"): "rss_enable",
    (TRACKING_OPERATION_KIND_DELETE_EXTERNAL, "SUBSCRIPTION"): "subscription_delete",
    (TRACKING_OPERATION_KIND_DELETE_EXTERNAL, "ASSOCIATED_RSS"): "rss_delete",
    (TRACKING_OPERATION_KIND_REFRESH_RSS, "ASSOCIATED_RSS"): "rss_refresh",
}


def _capability_field(operation: str, target_scope: str, enabled: bool | None) -> str | None:
    """Select the exact verified capability required by this action direction."""
    if operation == TRACKING_OPERATION_KIND_SET_ENABLED:
        if enabled is not True and enabled is not False:
            return None
        suffix = "enable" if enabled else "disable"
        return f"subscription_{suffix}" if target_scope == "SUBSCRIPTION" else f"rss_{suffix}"
    return _CAPABILITY_FIELDS.get((operation, target_scope))


def run_tracking_management(
    config: StorageConfig | None = None,
    *,
    tracking_id: str,
    expected_revision: int,
    idempotency_key: str,
    confirm: bool,
    operation: str,
    target_scope: str,
    ab_config: Any = None,
    management_client: ManagementSnapshotClient | None = None,
    capabilities: AutoBangumiCapabilities | None = None,
    patch: Mapping[str, Any] | None = None,
    enabled: bool | None = None,
    write: ManagementWriter | None = None,
    readback: Callable[[str, str, ResolvedManagementTarget], Any] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Prepare and start one management operation, with an at-most-once gate.

    ``ab_config`` is intentionally accepted only as a request-scoped value and
    is never passed to a repository or included in a returned dictionary.
    ``write`` is an offline/test seam; production callers provide the
    action-specific adapter closure in a later service layer.
    """
    del ab_config
    if confirm is not True:
        raise Stage1Error("tracking_management_confirmation_required", "请确认后再执行管理操作", "tracking_management")
    resolved_config = config or load_storage_config()
    record = load_tracking_record(resolved_config, tracking_id)
    if operation not in {TRACKING_OPERATION_KIND_MODIFY, TRACKING_OPERATION_KIND_SET_ENABLED, TRACKING_OPERATION_KIND_DELETE_EXTERNAL, TRACKING_OPERATION_KIND_REFRESH_RSS}:
        raise Stage1Error("tracking_management_patch_invalid", "管理操作类型无效", "tracking_management")
    if operation == TRACKING_OPERATION_KIND_REFRESH_RSS and target_scope != "ASSOCIATED_RSS":
        raise Stage1Error("tracking_management_patch_invalid", "刷新操作目标无效", "tracking_management")

    safe_patch = _safe_patch(operation, target_scope, patch, enabled)
    binding = build_management_binding(action=operation, scope=target_scope, patch=safe_patch if operation == "MODIFY" else None, enabled=enabled if operation == "SET_ENABLED" else None)
    existing = _load_operation_if_present(resolved_config, idempotency_key)
    if existing is not None:
        same_binding = (existing.tracking_id, existing.operation, existing.target_scope,
                        existing.request_fingerprint) == (
                            record.tracking_id, operation, target_scope,
                            binding.action_fingerprint)
        # A terminal operation is replayable after its first call advanced the
        # tracking revision.  The original expected revision remains durable
        # binding evidence; requiring the caller to resend it makes replay
        # impossible in the normal API flow.
        if not same_binding or (existing.state not in TRACKING_OPERATION_TERMINAL_STATES
                                and existing.expected_revision != expected_revision):
            raise Stage1Error("tracking_idempotency_conflict", "同一幂等键已绑定不同的管理操作", "tracking_management")
        if existing.state in TRACKING_OPERATION_TERMINAL_STATES:
            outcome = {
                TRACKING_OPERATION_STATE_SUCCEEDED: MANAGEMENT_OUTCOME_SUCCESS,
                "FAILED": MANAGEMENT_OUTCOME_DEFINITE_FAILURE,
                MANAGEMENT_OUTCOME_UNKNOWN: MANAGEMENT_OUTCOME_UNKNOWN,
                "RECOVERY_REQUIRED": MANAGEMENT_OUTCOME_UNKNOWN,
            }.get(existing.state, MANAGEMENT_OUTCOME_UNKNOWN)
            return {
                "operation_id": existing.operation_id,
                "management_status": existing.state,
                "outcome": outcome,
                "needs_manual": existing.state in {MANAGEMENT_OUTCOME_UNKNOWN, "RECOVERY_REQUIRED"},
                "created": False,
            }
        raise Stage1Error("tracking_management_state_conflict", "已有管理操作正在执行，请先恢复", "tracking_management")
    if expected_revision != record.revision:
        raise Stage1Error("tracking_revision_conflict", "追番记录版本已变化，请刷新后重试", "tracking_management", {"expected_revision": expected_revision, "current_revision": record.revision})
    _guard_current_operation(resolved_config, record)
    if management_client is None:
        raise Stage1Error("tracking_management_capability_unknown", "管理能力尚未验证", "tracking_management")
    caps, subscriptions, rss_items = management_client.read_snapshot()
    effective_caps = capabilities or caps
    field = _capability_field(operation, target_scope, enabled)
    if field is None or getattr(effective_caps, field, "UNKNOWN") != "SUPPORTED":
        raise Stage1Error("tracking_management_capability_unknown", "当前 Auto Bangumi 管理能力未验证", "tracking_management")
    target = resolve_management_target(record, target_scope, subscriptions, rss_items)
    # The operation binds the projection expected after the write, not merely
    # the sparse browser patch.  The fresh snapshot is still request-scoped.
    if operation == TRACKING_OPERATION_KIND_MODIFY:
        expected_projection = (
            build_complete_subscription_update(target, safe_patch)
            if target_scope == "SUBSCRIPTION"
            else list(build_complete_rss_update(target, safe_patch))
        )
    elif operation == TRACKING_OPERATION_KIND_SET_ENABLED:
        expected_projection = (
            {"enabled": enabled}
            if target_scope == "SUBSCRIPTION"
            else [{"enabled": enabled} for _item in target.rss]
        )
    else:
        expected_projection = None
    if expected_projection is not None:
        binding = replace(binding, expected_external_fingerprint=_projection_digest(expected_projection, operation, target_scope))
    operation_record, created = bind_tracking_operation(
        resolved_config, tracking_id=record.tracking_id, operation=operation,
        idempotency_key=idempotency_key, expected_revision=expected_revision,
        request_fingerprint=binding.action_fingerprint, target_scope=target_scope,
        previous_tracking_status=record.status,
        expected_external_fingerprint=binding.expected_external_fingerprint, now=now,
    )
    if not created:
        if operation_record.state == TRACKING_OPERATION_STATE_IN_PROGRESS:
            raise Stage1Error("tracking_management_state_conflict", "已有管理操作正在核验或恢复", "tracking_management")
        raise Stage1Error("tracking_management_state_conflict", "该幂等键已绑定已有管理操作", "tracking_management")

    started = replace(record, current_operation_id=operation_record.operation_id)
    started = append_audit_event(started, build_audit_event(
        action=TRACKING_AUDIT_MANAGEMENT_STARTED, actor=TRACKING_AUDIT_ACTOR_USER,
        from_status=record.status, to_status=record.status,
        tracking_revision=record.revision + 1, operation_id=operation_record.operation_id,
        reason_code=operation, safe_message="已准备执行 Auto Bangumi 管理操作", created_at=now or utc_now(),
    ))
    started = replace(started, revision=record.revision + 1, updated_at=now or utc_now())
    compare_and_swap_tracking_record(resolved_config, record.tracking_id, record.revision, started)
    in_progress = compare_and_swap_tracking_operation(
        resolved_config, operation_record.operation_id, TRACKING_OPERATION_STATE_PREPARED,
        transition_tracking_operation(operation_record, state=TRACKING_OPERATION_STATE_IN_PROGRESS, now=now),
    )
    if write is not None:
        try:
            response = _run_management_write(
                write, operation, target, _write_payload(operation, target, safe_patch, enabled)
            )
        except Exception as exc:
            outcome = classify_management_action(
                transport_error="unknown" if _unknown_write_error(exc) else None,
                response_valid=not _unknown_write_error(exc),
            )
            return _finish_management(config=resolved_config, record=started,
                operation=in_progress, outcome=outcome, target=target,
                operation_id=in_progress.operation_id, reason="management_write_unknown" if outcome == MANAGEMENT_OUTCOME_UNKNOWN else "management_write_failed", now=now)

        # The original coordinator's test seam used a side-effect-only writer.
        # Preserve that contract; real writers return a bounded response and
        # therefore continue through mandatory readback below.
        if response is None and readback is None:
            return {"operation_id": in_progress.operation_id, "management_status": "IN_PROGRESS", "created": True}

        action_outcome = classify_management_action(
            status_code=response.get("status_code") if isinstance(response, Mapping) and isinstance(response.get("status_code"), int) else 200,
            transport_error=response.get("transport_error") if isinstance(response, Mapping) and isinstance(response.get("transport_error"), str) else None,
            response_valid=not (isinstance(response, Mapping) and response.get("response_valid") is False),
        )
        if action_outcome != MANAGEMENT_OUTCOME_SUCCESS:
            return _finish_management(config=resolved_config, record=started,
                operation=in_progress, outcome=action_outcome, target=target,
                operation_id=in_progress.operation_id, reason="management_write_failed", now=now)
        # Refresh has no post-write projection for readback.  A bounded,
        # successful upstream response is therefore its terminal evidence;
        # only a lost or malformed response remains recovery-required.
        if operation == TRACKING_OPERATION_KIND_REFRESH_RSS:
            return _finish_management(config=resolved_config, record=started,
                operation=in_progress, outcome=MANAGEMENT_OUTCOME_SUCCESS, target=target,
                operation_id=in_progress.operation_id, reason="management_verified", now=now)
        try:
            actual = readback(operation, target_scope, target) if readback is not None else _readback_target(management_client, record, target_scope, operation)
            readback_outcome = _classify_target_readback(operation, target_scope, target, actual, binding.expected_external_fingerprint)
        except Exception:
            readback_outcome = MANAGEMENT_OUTCOME_UNKNOWN
        return _finish_management(config=resolved_config, record=started,
            operation=in_progress, outcome=readback_outcome, target=target,
            operation_id=in_progress.operation_id, reason="management_readback_failed" if readback_outcome != MANAGEMENT_OUTCOME_SUCCESS else "management_verified", now=now,
            actual=actual if 'actual' in locals() else None, enabled=enabled, patch=safe_patch)
    return {"operation_id": in_progress.operation_id, "management_status": "IN_PROGRESS", "created": True}


def recover_tracking_management(
    config: StorageConfig,
    *,
    record: TrackingRecord,
    operation: TrackingOperation,
    management_client: ManagementSnapshotClient,
    now: str | None = None,
) -> dict[str, Any]:
    """Verify one uncertain management operation without issuing a write.

    The operation binding is the sole source of action, scope and expected
    projection.  In particular, this function does not accept an idempotency
    key or construct a replacement operation.
    """
    if operation.tracking_id != record.tracking_id or operation.operation not in {
        TRACKING_OPERATION_KIND_MODIFY,
        TRACKING_OPERATION_KIND_SET_ENABLED,
        TRACKING_OPERATION_KIND_DELETE_EXTERNAL,
        TRACKING_OPERATION_KIND_REFRESH_RSS,
    } or operation.target_scope is None:
        return _management_recovery_result(record, operation, "RECOVERY_REQUIRED", True)
    if operation.state not in {
        TRACKING_OPERATION_STATE_IN_PROGRESS,
        "OUTCOME_UNKNOWN",
        "RECOVERY_REQUIRED",
    }:
        return _management_recovery_result(record, operation, "RECOVERY_REQUIRED", True)

    try:
        capabilities, subscriptions, rss_items = management_client.read_snapshot()
        required = "subscription_list" if operation.target_scope == "SUBSCRIPTION" else "rss_list"
        if (
            capabilities.probe_status != "VERIFIED"
            or capabilities.version != "3.1.18"
            or getattr(capabilities, required, "UNKNOWN") != "SUPPORTED"
        ):
            return _persist_management_recovery(
                config, record, operation, "RECOVERY_REQUIRED", "management_capability_unknown", now,
                successful=False,
            )
        target = _readback_target(
            management_client, record, operation.target_scope, operation.operation
        )
        outcome = _classify_target_readback(
            operation.operation, operation.target_scope, target, target,
            operation.expected_external_fingerprint or "",
        )
    except Exception:
        return _persist_management_recovery(
            config, record, operation, "RECOVERY_REQUIRED", "management_readback_failed", now,
            successful=False,
        )

    if outcome == MANAGEMENT_OUTCOME_SUCCESS:
        if operation.operation == TRACKING_OPERATION_KIND_DELETE_EXTERNAL:
            status = (
                TRACKING_STATUS_EXTERNAL_DELETED
                if operation.target_scope == "SUBSCRIPTION"
                else record.status
            )
        elif operation.operation == TRACKING_OPERATION_KIND_SET_ENABLED:
            status = TRACKING_STATUS_ACTIVE if _target_enabled(target) else TRACKING_STATUS_DISABLED
        else:
            status = TRACKING_STATUS_ACTIVE if record.status != TRACKING_STATUS_DISABLED else record.status
        return _persist_management_recovery(config, record, operation, status, "management_recovered", now, target, successful=True)
    if outcome == MANAGEMENT_OUTCOME_DEFINITE_FAILURE:
        status = operation.previous_tracking_status or record.status
        return _persist_management_recovery(config, record, operation, status, "management_not_applied", now, successful=False)
    return _persist_management_recovery(config, record, operation, "RECOVERY_REQUIRED", "management_recovery_required", now, successful=False)


def _target_enabled(target: Any) -> bool:
    if isinstance(target, ResolvedManagementTarget):
        if target.subscription is not None:
            return target.subscription.enabled
        return bool(target.rss) and all(item.enabled for item in target.rss)
    return False


def _management_recovery_result(
    record: TrackingRecord, operation: TrackingOperation, status: str, needs_manual: bool
) -> dict[str, Any]:
    return {
        "operation_id": operation.operation_id,
        "management_status": "RECOVERY_REQUIRED" if needs_manual else status,
        "outcome": status,
        "needs_manual": needs_manual,
        "created": False,
    }


def _persist_management_recovery(
    config: StorageConfig,
    record: TrackingRecord,
    operation: TrackingOperation,
    status: str,
    reason: str,
    now: str | None,
    target: Any = None,
    successful: bool | None = None,
) -> dict[str, Any]:
    timestamp = now or utc_now()
    success = successful if successful is not None else status not in {TRACKING_STATUS_RECOVERY_REQUIRED, TRACKING_STATUS_VERIFYING_EXTERNAL}
    definite_failure = not success and status not in {TRACKING_STATUS_RECOVERY_REQUIRED, TRACKING_STATUS_VERIFYING_EXTERNAL}
    audit = (
        TRACKING_AUDIT_MANAGEMENT_SUCCEEDED if success
        else TRACKING_AUDIT_MANAGEMENT_FAILED if definite_failure
        else TRACKING_AUDIT_MANAGEMENT_UNKNOWN
    )
    message = (
        "Auto Bangumi 管理结果已通过只读回查确认"
        if success or definite_failure
        else "外部管理结果仍未知，请人工恢复；不会自动重试"
    )
    next_record = transition_record(
        record, status=status, audit_action=audit, operation_id=operation.operation_id,
        reason_code=reason, safe_message=message, now=timestamp,
    )
    if success and operation.operation == TRACKING_OPERATION_KIND_DELETE_EXTERNAL:
        mapping = dict(next_record.external_mapping or {})
        if operation.target_scope == "SUBSCRIPTION":
            mapping["external_deleted"] = True
        elif isinstance(target, ResolvedManagementTarget):
            mapping["rss_ids"] = [item.external_id for item in target.rss]
        next_record = replace(next_record, external_mapping=mapping)
    final = compare_and_swap_tracking_record(config, record.tracking_id, record.revision, next_record)
    terminal = TRACKING_OPERATION_STATE_SUCCEEDED if success else (
        "RECOVERY_REQUIRED" if status == TRACKING_STATUS_RECOVERY_REQUIRED else "FAILED"
    )
    if operation.state in {"OUTCOME_UNKNOWN", "RECOVERY_REQUIRED"}:
        recover_tracking_operation(
            config, operation.operation_id, operation.state,
            target_state=("SUCCEEDED" if success else
                          ("RECOVERY_REQUIRED" if status == TRACKING_STATUS_RECOVERY_REQUIRED else "FAILED")),
            error_type=None if success else reason, now=timestamp,
        )
    else:
        compare_and_swap_tracking_operation(
            config, operation.operation_id, operation.state,
            transition_tracking_operation(operation, state=terminal, error_type=None if success else reason, now=timestamp),
        )
    return {
        "operation_id": operation.operation_id,
        "management_status": terminal,
        "outcome": "SUCCESS" if success else (
            "OUTCOME_UNKNOWN" if status == TRACKING_STATUS_RECOVERY_REQUIRED else "DEFINITE_FAILURE"
        ),
        "needs_manual": not success and not definite_failure,
        "created": False,
        "tracking": final.tracking_id,
    }


def _unknown_write_error(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True
    return isinstance(exc, Stage1Error) and exc.error_type in {"ab_management_failed", "invalid_ab_response"}


def _run_management_write(
    write: ManagementWriter,
    operation: str,
    target: ResolvedManagementTarget,
    payload: Mapping[str, Any] | None,
) -> Any:
    """Invoke RSS destructive actions one mapped item at a time.

    The adapter owns the fixed routes and ``file=false`` safeguard.  This
    service only supplies the request-scoped target, and aggregates bounded
    status codes without retaining upstream response bodies.
    """
    if operation != TRACKING_OPERATION_KIND_DELETE_EXTERNAL or target.scope != "ASSOCIATED_RSS":
        return write(target, payload)
    responses: list[Mapping[str, Any]] = []
    saw_side_effect_only = False
    for item in target.rss:
        single = ResolvedManagementTarget(scope="ASSOCIATED_RSS", rss=(item,))
        response = write(single, payload)
        if response is None:
            saw_side_effect_only = True
            continue
        if not isinstance(response, Mapping):
            return {"status_code": 502, "response_valid": False}
        responses.append(response)
    if saw_side_effect_only:
        return None
    if not responses:
        return {"status_code": 200}
    statuses = [
        (200 if item.get("status") is True else 400 if item.get("status") is False else item.get("status_code"))
        for item in responses
    ]
    if all(isinstance(status, int) and 200 <= status < 300 for status in statuses):
        return {"status_code": 200}
    if any(not isinstance(status, int) or status < 200 or status >= 300 for status in statuses):
        # Mixed or partial results are deliberately treated as unknown: at
        # least one upstream item may have been deleted already.
        if any(isinstance(status, int) and 200 <= status < 300 for status in statuses):
            return {"transport_error": "partial_external_result"}
        return {"status_code": next((status for status in statuses if isinstance(status, int)), 502)}
    return {"transport_error": "partial_external_result"}


def _readback_target(client: ManagementSnapshotClient | None, record: TrackingRecord, scope: str, operation: str) -> Any:
    if client is None:
        raise Stage1Error("tracking_management_readback_missing", "管理操作缺少外部回查", "tracking_management")
    _caps, subscriptions, rss_items = client.read_snapshot()
    mapping = record.external_mapping or {}
    if operation == TRACKING_OPERATION_KIND_DELETE_EXTERNAL:
        if scope == "SUBSCRIPTION":
            external_id = mapping.get("subscription_id")
            match = next((item for item in subscriptions if item.external_id == external_id), None)
            if match is None or match.deleted:
                return None
        else:
            wanted = tuple(mapping.get("rss_ids", ()))
            remaining = tuple(item for item in rss_items if item.external_id in wanted)
            return ResolvedManagementTarget(scope="ASSOCIATED_RSS", rss=tuple(sorted(remaining, key=lambda item: item.external_id)))
    return resolve_management_target(record, scope, subscriptions, rss_items)


def _projection_digest(value: Any, action: str, scope: str) -> str:
    return canonical_management_fingerprint(action=action, target_scope=scope, expected_projection=value)


def _classify_target_readback(operation: str, scope: str, target: ResolvedManagementTarget, actual: Any, expected: str) -> str:
    if operation == TRACKING_OPERATION_KIND_REFRESH_RSS:
        return MANAGEMENT_OUTCOME_UNKNOWN
    if operation == TRACKING_OPERATION_KIND_DELETE_EXTERNAL:
        if scope == "SUBSCRIPTION":
            return MANAGEMENT_OUTCOME_SUCCESS if actual is None else MANAGEMENT_OUTCOME_DEFINITE_FAILURE
        if not isinstance(actual, ResolvedManagementTarget):
            return MANAGEMENT_OUTCOME_UNKNOWN
        if not actual.rss:
            return MANAGEMENT_OUTCOME_SUCCESS
        # A partial delete cannot distinguish an unprocessed item from an
        # externally-unknown result, so it must be recovered manually.
        return MANAGEMENT_OUTCOME_UNKNOWN
    if not isinstance(actual, ResolvedManagementTarget):
        return MANAGEMENT_OUTCOME_UNKNOWN
    if scope == "SUBSCRIPTION":
        item = actual.subscription
        if item is None:
            return MANAGEMENT_OUTCOME_UNKNOWN
        if operation == "MODIFY":
            if item.upstream_fields:
                projection = dict(item.upstream_fields)
            else:
                projection = {"title": item.title, "season": item.season, "subtitle_group": item.subtitle_group}
        else:
            projection = {"enabled": item.enabled}
        digest = _projection_digest(projection, operation, scope)
    else:
        items = actual.rss
        if not items:
            return MANAGEMENT_OUTCOME_UNKNOWN
        if operation == "MODIFY":
            projection = [dict(item.upstream_fields) if item.upstream_fields else {
                "name": item.name, "aggregate": item.aggregate, "parser": item.parser
            } for item in items]
        else:
            projection = [{"enabled": item.enabled} for item in items]
        digest = _projection_digest(projection, operation, scope)
    return classify_management_readback(expected_fingerprint=expected, actual_fingerprint=digest, read_succeeded=True)


def _finish_management(*, config: StorageConfig, record: TrackingRecord, operation: TrackingOperation,
                       outcome: str, target: ResolvedManagementTarget, operation_id: str,
                       reason: str, now: str | None, actual: Any = None,
                       enabled: bool | None = None, patch: Mapping[str, Any] | None = None) -> dict[str, Any]:
    timestamp = now or utc_now()
    if outcome == MANAGEMENT_OUTCOME_SUCCESS:
        status = record.status
        if operation.operation == TRACKING_OPERATION_KIND_DELETE_EXTERNAL and operation.target_scope == "SUBSCRIPTION":
            status = TRACKING_STATUS_EXTERNAL_DELETED
        elif operation.operation == TRACKING_OPERATION_KIND_SET_ENABLED:
            status = TRACKING_STATUS_ACTIVE if enabled else TRACKING_STATUS_DISABLED
        elif record.status != TRACKING_STATUS_DISABLED:
            status = TRACKING_STATUS_ACTIVE
        action = TRACKING_AUDIT_MANAGEMENT_SUCCEEDED
        target_state = "SUCCEEDED"
        message = "Auto Bangumi 管理操作已完成并通过回查"
    elif outcome == MANAGEMENT_OUTCOME_DEFINITE_FAILURE:
        status = record.status
        action = TRACKING_AUDIT_MANAGEMENT_FAILED
        target_state = "FAILED"
        message = "Auto Bangumi 未应用管理操作"
    else:
        status = TRACKING_STATUS_VERIFYING_EXTERNAL if outcome == MANAGEMENT_OUTCOME_UNKNOWN else TRACKING_STATUS_RECOVERY_REQUIRED
        action = TRACKING_AUDIT_MANAGEMENT_UNKNOWN
        target_state = "OUTCOME_UNKNOWN" if outcome == MANAGEMENT_OUTCOME_UNKNOWN else "RECOVERY_REQUIRED"
        message = "外部管理结果未知，请人工恢复；不会自动重试"
        if operation.operation in {TRACKING_OPERATION_KIND_DELETE_EXTERNAL, TRACKING_OPERATION_KIND_REFRESH_RSS}:
            status = TRACKING_STATUS_RECOVERY_REQUIRED
            target_state = "RECOVERY_REQUIRED"
    next_record = transition_record(record, status=status, audit_action=action,
        operation_id=operation_id, reason_code=reason, safe_message=message, now=timestamp)
    mapping = dict(next_record.external_mapping or {})
    if outcome == MANAGEMENT_OUTCOME_SUCCESS and operation.target_scope == "SUBSCRIPTION" and isinstance(actual, ResolvedManagementTarget) and actual.subscription:
        item = actual.subscription
        mapping.update({"enabled": item.enabled, "external_deleted": item.deleted})
        if operation.operation == TRACKING_OPERATION_KIND_MODIFY:
            next_record = replace(next_record, plan_summary={**next_record.plan_summary, "title": item.title, "season": item.season, "subtitle_group": item.subtitle_group})
    if outcome == MANAGEMENT_OUTCOME_SUCCESS and operation.operation == TRACKING_OPERATION_KIND_DELETE_EXTERNAL:
        if operation.target_scope == "SUBSCRIPTION":
            mapping["external_deleted"] = True
        else:
            mapping["rss_ids"] = [
                item.external_id
                for item in (actual.rss if isinstance(actual, ResolvedManagementTarget) else ())
            ]
    next_record = replace(next_record, external_mapping=mapping)
    persistence_failed = False
    try:
        final = compare_and_swap_tracking_record(config, record.tracking_id, record.revision, next_record)
        compare_and_swap_tracking_operation(config, operation_id, TRACKING_OPERATION_STATE_IN_PROGRESS,
            transition_tracking_operation(operation, state=target_state, error_type=None if outcome == MANAGEMENT_OUTCOME_SUCCESS else reason, now=timestamp))
    except Exception:
        persistence_failed = True
        final = transition_record(record, status=TRACKING_STATUS_RECOVERY_REQUIRED,
            audit_action=TRACKING_AUDIT_MANAGEMENT_UNKNOWN, operation_id=operation_id,
            reason_code="management_result_persist_failed", safe_message="管理结果未能安全保存，请人工恢复", now=timestamp)
        with contextlib.suppress(Exception):
            current = load_tracking_record(config, record.tracking_id)
            compare_and_swap_tracking_record(
                config, record.tracking_id, current.revision,
                replace(final, revision=current.revision + 1),
            )
        with contextlib.suppress(Exception):
            compare_and_swap_tracking_operation(config, operation_id, TRACKING_OPERATION_STATE_IN_PROGRESS,
                transition_tracking_operation(operation, state="RECOVERY_REQUIRED", error_type="management_result_persist_failed", now=timestamp))
    persisted_state = "RECOVERY_REQUIRED" if persistence_failed else target_state
    if target_state == "RECOVERY_REQUIRED" and outcome != MANAGEMENT_OUTCOME_UNKNOWN:
        persisted_state = "RECOVERY_REQUIRED"
    return {"operation_id": operation_id, "management_status": persisted_state,
            "outcome": outcome if not persistence_failed else MANAGEMENT_OUTCOME_UNKNOWN,
            "needs_manual": persisted_state == "RECOVERY_REQUIRED" or outcome == MANAGEMENT_OUTCOME_UNKNOWN,
            "created": True}


def _safe_patch(operation: str, scope: str, patch: Mapping[str, Any] | None, enabled: bool | None) -> dict[str, Any] | None:
    if operation == "MODIFY":
        return build_management_patch(scope, patch)
    if operation == "SET_ENABLED" and type(enabled) is not bool:
        raise Stage1Error("tracking_management_patch_invalid", "启用状态必须是布尔值", "tracking_management")
    return None


def _write_payload(operation: str, target: ResolvedManagementTarget, patch: Mapping[str, Any] | None, enabled: bool | None) -> Mapping[str, Any] | None:
    if operation == "MODIFY":
        return build_complete_subscription_update(target, patch) if target.scope == "SUBSCRIPTION" else {"items": build_complete_rss_update(target, patch)}
    return {"enabled": enabled} if operation == "SET_ENABLED" else None


def _guard_current_operation(config: StorageConfig, record: TrackingRecord) -> None:
    if not record.current_operation_id:
        return
    operation = load_tracking_operation(config, record.current_operation_id)
    if operation.state in {
        TRACKING_OPERATION_STATE_PREPARED,
        TRACKING_OPERATION_STATE_IN_PROGRESS,
        "OUTCOME_UNKNOWN",
        "RECOVERY_REQUIRED",
    }:
        raise Stage1Error("tracking_management_state_conflict", "已有管理操作正在执行，请先恢复", "tracking_management")


def _load_operation_if_present(config: StorageConfig, idempotency_key: str) -> TrackingOperation | None:
    operation_id = tracking_operation_id_for_idempotency_key(idempotency_key)
    try:
        return load_tracking_operation(config, operation_id)
    except Stage1Error as exc:
        if exc.error_type == "tracking_operation_not_found":
            return None
        raise


__all__ = ["ManagementBinding", "ManagementSnapshotClient", "ManagementWriter", "recover_tracking_management", "run_tracking_management"]
