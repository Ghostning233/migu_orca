"""Durable coordinator for Auto Bangumi management writes (US-241).

This module is the only layer that joins request-scoped AB credentials, the
read adapter, and the tracking repositories.  Action-specific response and
readback semantics are deliberately left to the later management stories.
"""
from __future__ import annotations

import contextlib
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import replace
from typing import Any, Protocol
from uuid import UUID

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
from tracking_engine.controllers.management_state import (
    management_action_allowed,
    management_baseline_verified,
    management_capability_allowed,
)
from tracking_engine.controllers.management_target import (
    ManagementBinding,
    ResolvedManagementTarget,
    build_complete_rss_update,
    build_complete_subscription_update,
    build_management_binding,
    build_management_patch,
    resolve_management_target,
    validate_management_mapping,
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
    TRACKING_AUDIT_RECOVERY_AUTO_SUCCEEDED,
    TRACKING_AUDIT_RECOVERY_EXTERNAL_VERIFIED,
    TRACKING_AUDIT_RECOVERY_MANUAL_SUCCEEDED,
    TRACKING_AUDIT_SUBMIT_SUCCEEDED,
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


def management_writer(client: Any, action: str) -> ManagementWriter:
    """Build the fixed-route adapter closure for one request-scoped action."""
    def write(target: ResolvedManagementTarget, payload: object) -> dict[str, object]:
        calls: list[dict[str, object]] = []
        if target.scope == "SUBSCRIPTION":
            item = target.subscription
            assert item is not None
            if action == "MODIFY":
                calls.append(client.update_subscription(item.external_id, payload))
            elif action == "SET_ENABLED":
                calls.append(client.set_subscription_enabled(item.external_id, payload["enabled"]))
            elif action == "DELETE_EXTERNAL":
                calls.append(client.delete_subscription(item.external_id))
            else:
                raise ValueError("invalid management action")
        else:
            rss_payloads = payload.get("items", []) if isinstance(payload, dict) else []
            for index, item in enumerate(target.rss):
                if action == "MODIFY":
                    body = rss_payloads[index] if index < len(rss_payloads) else payload
                    calls.append(client.update_rss(item.external_id, body, item.url))
                elif action == "SET_ENABLED":
                    calls.append(client.enable_rss([rss.external_id for rss in target.rss]) if payload["enabled"] else client.disable_rss(item.external_id))
                    if payload["enabled"]:
                        break
                elif action == "DELETE_EXTERNAL":
                    calls.append(client.delete_rss(item.external_id))
                elif action == "REFRESH_RSS":
                    calls.append(client.refresh_rss(item.external_id))
        statuses = [(200 if result.get("status") is True else 400 if result.get("status") is False else result.get("status_code")) for result in calls if isinstance(result, dict)]
        if statuses and all(isinstance(status, int) and 200 <= status < 300 for status in statuses):
            return {"status_code": 200}
        if any(isinstance(status, int) and 200 <= status < 300 for status in statuses) and any(not isinstance(status, int) or not 200 <= status < 300 for status in statuses):
            return {"transport_error": "unknown"}
        return {"status_code": next((status for status in statuses if isinstance(status, int)), 502)}
    return write

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
    connection_ref: str | None = None,
    capabilities: AutoBangumiCapabilities | None = None,
    patch: Mapping[str, Any] | None = None,
    enabled: bool | None = None,
    #: Local plan values to raise once the external write is confirmed.
    local_plan: Mapping[str, Any] | None = None,
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
    if isinstance(connection_ref, UUID):
        connection_ref = str(connection_ref)
    if confirm is not True:
        raise Stage1Error("tracking_management_confirmation_required", "请确认后再执行管理操作", "tracking_management")
    resolved_config = config or load_storage_config()
    record = load_tracking_record(resolved_config, tracking_id)
    if operation not in {TRACKING_OPERATION_KIND_MODIFY, TRACKING_OPERATION_KIND_SET_ENABLED, TRACKING_OPERATION_KIND_DELETE_EXTERNAL, TRACKING_OPERATION_KIND_REFRESH_RSS}:
        raise Stage1Error("tracking_management_patch_invalid", "管理操作类型无效", "tracking_management")
    if operation == TRACKING_OPERATION_KIND_REFRESH_RSS and target_scope != "ASSOCIATED_RSS":
        raise Stage1Error("tracking_management_patch_invalid", "刷新操作目标无效", "tracking_management")
    safe_patch = _safe_patch(operation, target_scope, patch, enabled)
    binding = build_management_binding(action=operation, scope=target_scope, patch=safe_patch if operation == "MODIFY" else None, enabled=enabled if operation == "SET_ENABLED" else None, connection_ref=connection_ref)
    existing = _load_operation_if_present(resolved_config, idempotency_key)
    if existing is not None:
        same_binding = (existing.tracking_id, existing.operation, existing.target_scope,
                        existing.request_fingerprint, existing.connection_ref) == (
                            record.tracking_id, operation, target_scope,
                            binding.action_fingerprint, connection_ref)
        # Terminal replay remains bound to the original revision.  The caller
        # may safely replay with that stale-but-recorded revision; a different
        # revision is a different request and must conflict.
        if not same_binding or existing.expected_revision != expected_revision:
            raise Stage1Error("tracking_idempotency_conflict", "同一幂等键已绑定不同的管理操作", "tracking_management")
        if existing.state in TRACKING_OPERATION_TERMINAL_STATES:
            # A later operation may have replaced the record pointer.  Never
            # compensate an old terminal operation in that case: doing so
            # would mutate historical bytes belonging to an unrelated op.
            if record.current_operation_id != existing.operation_id:
                raise Stage1Error("tracking_management_state_conflict", "已有管理操作已被后续操作取代", "tracking_management")
            if not _record_matches_management_terminal(record, existing):
                # Do not claim success for an operation whose paired tracking
                # result was lost in the operation-first crash window.
                _persist_management_storage_failure(resolved_config, record.tracking_id, existing, utc_now())
                raise Stage1Error("tracking_management_state_conflict", "已有管理操作尚未完成本地落盘，请先恢复", "tracking_management")
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
    if not management_action_allowed(record.status, operation, enabled=enabled):
        raise Stage1Error("tracking_management_state_conflict", "当前追番状态不允许该管理操作", "tracking_management")
    if expected_revision != record.revision:
        raise Stage1Error("tracking_revision_conflict", "追番记录版本已变化，请刷新后重试", "tracking_management", {"expected_revision": expected_revision, "current_revision": record.revision})
    _guard_current_operation(resolved_config, record)
    if connection_ref is not None:
        validate_management_mapping(record, connection_ref)
    if management_client is None:
        raise Stage1Error("tracking_management_capability_unknown", "管理能力尚未验证", "tracking_management")
    caps, subscriptions, rss_items = management_client.read_snapshot()
    effective_caps = caps if connection_ref is not None else (capabilities or caps)
    if not management_capability_allowed(effective_caps, operation, target_scope, enabled=enabled):
        raise Stage1Error("tracking_management_capability_unknown", "当前 Auto Bangumi 管理能力未验证", "tracking_management")
    target = resolve_management_target(
        record, target_scope, subscriptions, rss_items,
        include_deleted_subscription=(
            operation in {TRACKING_OPERATION_KIND_SET_ENABLED, TRACKING_OPERATION_KIND_DELETE_EXTERNAL}
            and target_scope == "SUBSCRIPTION"
        ),
        connection_ref=connection_ref,
    )
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
        connection_ref=connection_ref,
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
    try:
        in_progress = compare_and_swap_tracking_operation(
            resolved_config, operation_record.operation_id, TRACKING_OPERATION_STATE_PREPARED,
            transition_tracking_operation(operation_record, state=TRACKING_OPERATION_STATE_IN_PROGRESS, now=now),
        )
    except Stage1Error:
        raise
    except Exception:
        # The external boundary was never crossed.  Compensate the durable
        # PREPARED binding and its record pointer before surfacing the failure.
        _compensate_prepared_start(resolved_config, started, operation_record, now or utc_now())
        raise
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
            status_code=(response.get("status_code") if isinstance(response, Mapping)
                         and isinstance(response.get("status_code"), int) else None),
            transport_error=response.get("transport_error") if isinstance(response, Mapping) and isinstance(response.get("transport_error"), str) else None,
            response_valid=(
                isinstance(response, Mapping)
                and response.get("response_valid") is not False
                and (isinstance(response.get("status_code"), int)
                     or isinstance(response.get("transport_error"), str))
            ),
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
                operation_id=in_progress.operation_id, reason="management_verified", now=now,
                enabled=enabled, patch=safe_patch, local_plan=local_plan)
        try:
            actual = readback(operation, target_scope, target) if readback is not None else _readback_target(management_client, record, target_scope, operation, connection_ref=connection_ref)
            readback_outcome = _classify_target_readback(operation, target_scope, actual, binding.expected_external_fingerprint)
        except Exception:
            readback_outcome = MANAGEMENT_OUTCOME_UNKNOWN
        return _finish_management(config=resolved_config, record=started,
            operation=in_progress, outcome=readback_outcome, target=target,
            operation_id=in_progress.operation_id, reason="management_readback_failed" if readback_outcome != MANAGEMENT_OUTCOME_SUCCESS else "management_verified", now=now,
            actual=actual if 'actual' in locals() else None, enabled=enabled, patch=safe_patch,
            local_plan=local_plan)
    return {"operation_id": in_progress.operation_id, "management_status": "IN_PROGRESS", "created": True}


def recover_tracking_management(
    config: StorageConfig,
    *,
    record: TrackingRecord,
    operation: TrackingOperation,
    management_client: ManagementSnapshotClient,
    now: str | None = None,
    connection_ref: str | None = None,
) -> dict[str, Any]:
    """Verify one uncertain management operation without issuing a write.

    The operation binding is the sole source of action, scope and expected
    projection.  In particular, this function does not accept an idempotency
    key or construct a replacement operation.
    """
    if (operation.tracking_id != record.tracking_id
        or (connection_ref is not None and operation.connection_ref != connection_ref)
        or operation.operation not in {
        TRACKING_OPERATION_KIND_MODIFY,
        TRACKING_OPERATION_KIND_SET_ENABLED,
        TRACKING_OPERATION_KIND_DELETE_EXTERNAL,
        TRACKING_OPERATION_KIND_REFRESH_RSS,
    } or operation.target_scope is None):
        return _management_recovery_result(record, operation, "RECOVERY_REQUIRED", True)
    if connection_ref is not None:
        try:
            validate_management_mapping(record, connection_ref)
        except Exception:
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
        if not management_baseline_verified(capabilities) or getattr(capabilities, required, "UNKNOWN") != "SUPPORTED":
            return _persist_management_recovery(
                config, record, operation, "RECOVERY_REQUIRED", "management_capability_unknown", now,
                successful=False,
            )
        target = _readback_target(
            management_client, record, operation.target_scope, operation.operation,
            connection_ref=connection_ref,
        )
        outcome = _classify_target_readback(
            operation.operation, operation.target_scope, target,
            operation.expected_external_fingerprint or "",
        )
    except Stage1Error:
        raise
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
                else operation.previous_tracking_status or record.status
            )
        elif operation.operation == TRACKING_OPERATION_KIND_SET_ENABLED:
            status = TRACKING_STATUS_ACTIVE if _target_enabled(target) else TRACKING_STATUS_DISABLED
        else:
            status = operation.previous_tracking_status or record.status
        return _persist_management_recovery(config, record, operation, status, "management_recovered", now, target, successful=True)
    if outcome == MANAGEMENT_OUTCOME_DEFINITE_FAILURE:
        status = operation.previous_tracking_status or record.status
        return _persist_management_recovery(config, record, operation, status, "management_not_applied", now, successful=False)
    return _persist_management_recovery(config, record, operation, "RECOVERY_REQUIRED", "management_recovery_required", now, successful=False)


def _target_enabled(target: Any) -> bool:
    if isinstance(target, ResolvedManagementTarget):
        if target.subscription is not None:
            return not target.subscription.deleted
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
    terminal = TRACKING_OPERATION_STATE_SUCCEEDED if success else (
        "RECOVERY_REQUIRED" if status == TRACKING_STATUS_RECOVERY_REQUIRED else "FAILED"
    )
    try:
        if operation.state in {"OUTCOME_UNKNOWN", "RECOVERY_REQUIRED"}:
            recover_tracking_operation(
                config, operation.operation_id, operation.state,
                target_state=terminal, error_type=None if success else reason, now=timestamp,
            )
        else:
            compare_and_swap_tracking_operation(
                config, operation.operation_id, operation.state,
                transition_tracking_operation(operation, state=terminal, error_type=None if success else reason, now=timestamp),
            )
        final = compare_and_swap_tracking_record(config, record.tracking_id, record.revision, next_record)
    except Exception:
        _persist_management_storage_failure(config, record.tracking_id, operation, timestamp)
        return {
            "operation_id": operation.operation_id,
            "management_status": "RECOVERY_REQUIRED",
            "outcome": "OUTCOME_UNKNOWN",
            "needs_manual": True,
            "created": False,
        }
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
    if not isinstance(exc, Stage1Error):
        return False
    status_code = exc.details.get("status_code")
    return (
        exc.error_type in {
            "ab_management_failed", "invalid_ab_response", "ab_timeout", "ab_connection_failed",
        }
        or (isinstance(status_code, int) and not isinstance(status_code, bool) and status_code >= 500)
    )


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


def _readback_target(client: ManagementSnapshotClient | None, record: TrackingRecord, scope: str, operation: str, *, connection_ref: str | None = None) -> Any:
    if client is None:
        raise Stage1Error("tracking_management_readback_missing", "管理操作缺少外部回查", "tracking_management")
    if connection_ref is not None:
        validate_management_mapping(record, connection_ref)
    _caps, subscriptions, rss_items = client.read_snapshot()
    mapping = record.external_mapping or {}
    if operation == TRACKING_OPERATION_KIND_DELETE_EXTERNAL:
        if scope == "SUBSCRIPTION":
            external_id = mapping.get("subscription_id")
            match = next((item for item in subscriptions if item.external_id == external_id), None)
            if match is None:
                return None
            # A disabled 3.1.18 Bangumi remains present in the list with
            # deleted=true.  DELETE_EXTERNAL succeeds only after it vanishes.
            return ResolvedManagementTarget(scope="SUBSCRIPTION", subscription=match)
        else:
            wanted = tuple(mapping.get("rss_ids", ()))
            remaining = tuple(item for item in rss_items if item.external_id in wanted)
            return ResolvedManagementTarget(scope="ASSOCIATED_RSS", rss=tuple(sorted(remaining, key=lambda item: item.external_id)))
    return resolve_management_target(
        record, scope, subscriptions, rss_items,
        include_deleted_subscription=(
            operation in {TRACKING_OPERATION_KIND_SET_ENABLED, TRACKING_OPERATION_KIND_DELETE_EXTERNAL}
            and scope == "SUBSCRIPTION"
        ),
        connection_ref=connection_ref,
    )


def _projection_digest(value: Any, action: str, scope: str) -> str:
    return canonical_management_fingerprint(action=action, target_scope=scope, expected_projection=value)


def _classify_target_readback(operation: str, scope: str, actual: Any, expected: str) -> str:
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
                projection = {
                    "official_title": item.title, "season": item.season,
                    "group_name": item.subtitle_group, "deleted": item.deleted,
                }
        else:
            projection = {"enabled": not item.deleted}
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
                       enabled: bool | None = None, patch: Mapping[str, Any] | None = None,
                       local_plan: Mapping[str, Any] | None = None) -> dict[str, Any]:
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
            # Issue #91: the local plan is raised only after the external write was
            # confirmed by read-back, so the two never diverge on a failure.
            if local_plan:
                promoted_fingerprint = _promote_local_plan(
                    config=config, record=next_record, local_plan=local_plan, now=timestamp
                )
                if promoted_fingerprint is not None:
                    next_record = replace(next_record, request_fingerprint=promoted_fingerprint)
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
        compare_and_swap_tracking_operation(config, operation_id, TRACKING_OPERATION_STATE_IN_PROGRESS,
            transition_tracking_operation(operation, state=target_state, error_type=None if outcome == MANAGEMENT_OUTCOME_SUCCESS else reason, now=timestamp))
        compare_and_swap_tracking_record(config, record.tracking_id, record.revision, next_record)
    except Exception:
        persistence_failed = True
        _persist_management_storage_failure(config, record.tracking_id, operation, timestamp)
    persisted_state = "RECOVERY_REQUIRED" if persistence_failed else target_state
    if target_state == "RECOVERY_REQUIRED" and outcome != MANAGEMENT_OUTCOME_UNKNOWN:
        persisted_state = "RECOVERY_REQUIRED"
    return {"operation_id": operation_id, "management_status": persisted_state,
            "outcome": outcome if not persistence_failed else MANAGEMENT_OUTCOME_UNKNOWN,
            "needs_manual": persisted_state == "RECOVERY_REQUIRED" or outcome == MANAGEMENT_OUTCOME_UNKNOWN,
            "created": True}


def _promote_local_plan(
    *,
    config: StorageConfig,
    record: TrackingRecord,
    local_plan: Mapping[str, Any],
    now: str,
) -> str | None:
    """Raise the local Request to the values the external write just confirmed.

    Returns the new request fingerprint so the record can be persisted in the
    same write, or ``None`` when there is no local plan to raise. The stored
    snapshot stays the authority: only whitelisted plan fields change.
    """
    request_id = record.request_id
    if not request_id:
        return None
    # Imported lazily: the save-confirm module owns the fingerprint rule and must
    # not be pulled in at module import time (cycle through the web adapters).
    from apps.migu_orca_web.save_confirm_service import compute_request_fingerprint
    from storage_engine.controllers.request_repository import (
        load_request_snapshot,
        save_request_snapshot,
    )

    request = load_request_snapshot(config, request_id)
    if not isinstance(request, dict):
        return None
    confirmable = request.get("confirmable_config")
    if not isinstance(confirmable, dict):
        return None

    updated = deepcopy(request)
    target_config = updated["confirmable_config"]
    filter_rule = local_plan.get("filter_rule")
    if isinstance(filter_rule, dict):
        current_rule = target_config.get("filter_rule")
        merged_rule = dict(current_rule) if isinstance(current_rule, dict) else {}
        merged_rule.update(filter_rule)
        target_config["filter_rule"] = merged_rule
    folder = local_plan.get("expected_folder_name")
    if isinstance(folder, str):
        target_config["expected_folder_name"] = folder
    updated["updated_at"] = now
    save_request_snapshot(config, updated)
    return compute_request_fingerprint(updated)


def _persist_management_storage_failure(
    config: StorageConfig, tracking_id: str, operation: TrackingOperation, timestamp: str,
) -> None:
    """Converge both durable records to recovery without reviving stale data.

    We cannot make two independent atomic files transactional.  Therefore any
    failure between them is never reported as success, and compensation always
    reloads the current tracking record before a CAS.  A concurrent update is
    left intact rather than being overwritten from the pre-write snapshot.
    """
    with contextlib.suppress(Exception):
        current = load_tracking_record(config, tracking_id)
        if current.current_operation_id == operation.operation_id:
            recovery = transition_record(
                current, status=TRACKING_STATUS_RECOVERY_REQUIRED,
                audit_action=TRACKING_AUDIT_MANAGEMENT_UNKNOWN,
                operation_id=operation.operation_id,
                reason_code="management_result_persist_failed",
                safe_message="管理结果未能安全保存，请人工恢复",
                now=timestamp,
            )
            compare_and_swap_tracking_record(config, tracking_id, current.revision, recovery)
    with contextlib.suppress(Exception):
        current_operation = load_tracking_operation(config, operation.operation_id)
        if current_operation.state == TRACKING_OPERATION_STATE_IN_PROGRESS:
            compare_and_swap_tracking_operation(
                config, operation.operation_id, TRACKING_OPERATION_STATE_IN_PROGRESS,
                transition_tracking_operation(
                    current_operation, state="RECOVERY_REQUIRED",
                    error_type="management_result_persist_failed", now=timestamp,
                ),
            )
        elif current_operation.state in {"SUCCEEDED", "FAILED", "OUTCOME_UNKNOWN", "RECOVERY_REQUIRED"}:
            recover_tracking_operation(
                config, operation.operation_id, current_operation.state,
                target_state="RECOVERY_REQUIRED",
                error_type="management_result_persist_failed", now=timestamp,
            )


def _compensate_prepared_start(
    config: StorageConfig, record: TrackingRecord, operation: TrackingOperation, timestamp: str,
) -> None:
    """Close a pre-write CAS failure without leaving a stale operation gate."""
    with contextlib.suppress(Exception):
        current_operation = load_tracking_operation(config, operation.operation_id)
        if current_operation.state == TRACKING_OPERATION_STATE_PREPARED:
            compare_and_swap_tracking_operation(
                config, operation.operation_id, TRACKING_OPERATION_STATE_PREPARED,
                transition_tracking_operation(
                    current_operation, state="FAILED", error_type="management_start_persist_failed", now=timestamp,
                ),
            )
    with contextlib.suppress(Exception):
        current = load_tracking_record(config, record.tracking_id)
        if current.current_operation_id == operation.operation_id:
            reverted = transition_record(
                current, status=operation.previous_tracking_status or current.status,
                audit_action=TRACKING_AUDIT_MANAGEMENT_FAILED,
                operation_id=operation.operation_id,
                reason_code="management_start_persist_failed",
                safe_message="管理操作启动未完成，未执行外部写入",
                now=timestamp,
            )
            compare_and_swap_tracking_record(
                config, current.tracking_id, current.revision,
                replace(reverted, current_operation_id=None),
            )


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
    management_kinds = {
        TRACKING_OPERATION_KIND_MODIFY,
        TRACKING_OPERATION_KIND_SET_ENABLED,
        TRACKING_OPERATION_KIND_DELETE_EXTERNAL,
        TRACKING_OPERATION_KIND_REFRESH_RSS,
    }
    if operation.operation not in management_kinds:
        if operation.operation == "SUBMIT" and operation.state == TRACKING_OPERATION_STATE_SUCCEEDED and any(
                isinstance(event, Mapping)
                and event.get("operation_id") == operation.operation_id
                and event.get("action") in {
                    TRACKING_AUDIT_SUBMIT_SUCCEEDED,
                    TRACKING_AUDIT_RECOVERY_AUTO_SUCCEEDED,
                    TRACKING_AUDIT_RECOVERY_MANUAL_SUCCEEDED,
                    TRACKING_AUDIT_RECOVERY_EXTERNAL_VERIFIED,
                }
                for event in record.audit_events
            ):
                return
        raise Stage1Error("tracking_management_state_conflict", "已有操作尚未完成，请先恢复", "tracking_management")
    if operation.state in TRACKING_OPERATION_TERMINAL_STATES and not _record_matches_management_terminal(record, operation):
        # A crash may land the operation result before its paired TrackingRecord
        # CAS.  Turn that orphaned terminal state into the normal recovery gate
        # before rejecting any fresh idempotency key.
        _persist_management_storage_failure(config, record.tracking_id, operation, utc_now())
        raise Stage1Error("tracking_management_state_conflict", "已有管理操作尚未完成本地落盘，请先恢复", "tracking_management")


def _record_matches_management_terminal(record: TrackingRecord, operation: TrackingOperation) -> bool:
    """Prove the record persisted the precise terminal operation outcome."""
    if record.current_operation_id != operation.operation_id:
        return False
    expected_audit = {
        TRACKING_OPERATION_STATE_SUCCEEDED: TRACKING_AUDIT_MANAGEMENT_SUCCEEDED,
        "FAILED": TRACKING_AUDIT_MANAGEMENT_FAILED,
        "OUTCOME_UNKNOWN": TRACKING_AUDIT_MANAGEMENT_UNKNOWN,
        "RECOVERY_REQUIRED": TRACKING_AUDIT_MANAGEMENT_UNKNOWN,
    }.get(operation.state)
    expected_status = {
        TRACKING_OPERATION_STATE_SUCCEEDED: None,
        "FAILED": None,
        "OUTCOME_UNKNOWN": TRACKING_STATUS_VERIFYING_EXTERNAL,
        "RECOVERY_REQUIRED": TRACKING_STATUS_RECOVERY_REQUIRED,
    }.get(operation.state)
    if expected_audit is None:
        return False
    relevant = [
        event for event in record.audit_events
        if isinstance(event, Mapping) and event.get("operation_id") == operation.operation_id
        and event.get("action") in {
            TRACKING_AUDIT_MANAGEMENT_SUCCEEDED,
            TRACKING_AUDIT_MANAGEMENT_FAILED,
            TRACKING_AUDIT_MANAGEMENT_UNKNOWN,
        }
    ]
    if not relevant or relevant[-1].get("action") != expected_audit:
        return False
    if expected_status is not None:
        return record.status == expected_status
    return record.status not in {TRACKING_STATUS_VERIFYING_EXTERNAL, TRACKING_STATUS_RECOVERY_REQUIRED}


def _load_operation_if_present(config: StorageConfig, idempotency_key: str) -> TrackingOperation | None:
    operation_id = tracking_operation_id_for_idempotency_key(idempotency_key)
    try:
        return load_tracking_operation(config, operation_id)
    except Stage1Error as exc:
        if exc.error_type == "tracking_operation_not_found":
            return None
        raise


__all__ = ["ManagementBinding", "ManagementSnapshotClient", "ManagementWriter", "recover_tracking_management", "run_tracking_management"]
