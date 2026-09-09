"""Durable coordinator for Auto Bangumi management writes (US-241).

This module is the only layer that joins request-scoped AB credentials, the
read adapter, and the tracking repositories.  Action-specific response and
readback semantics are deliberately left to the later management stories.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any, Protocol

from ab_engine.models.management import AutoBangumiCapabilities
from shared.errors import Stage1Error
from storage_engine.controllers.operation_repository import (
    bind_tracking_operation,
    compare_and_swap_tracking_operation,
    load_tracking_operation,
)
from storage_engine.controllers.storage_config import StorageConfig, load_storage_config
from storage_engine.controllers.tracking_repository import (
    compare_and_swap_tracking_record,
    load_tracking_record,
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
    TRACKING_OPERATION_TERMINAL_STATES,
    TrackingOperation,
    tracking_operation_id_for_idempotency_key,
    transition_tracking_operation,
)
from tracking_engine.models.tracking import (
    TRACKING_AUDIT_ACTOR_USER,
    TRACKING_AUDIT_MANAGEMENT_STARTED,
    TrackingRecord,
    append_audit_event,
    build_audit_event,
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
    if expected_revision != record.revision:
        raise Stage1Error("tracking_revision_conflict", "追番记录版本已变化，请刷新后重试", "tracking_management", {"expected_revision": expected_revision, "current_revision": record.revision})
    if operation not in {TRACKING_OPERATION_KIND_MODIFY, TRACKING_OPERATION_KIND_SET_ENABLED, TRACKING_OPERATION_KIND_DELETE_EXTERNAL, TRACKING_OPERATION_KIND_REFRESH_RSS}:
        raise Stage1Error("tracking_management_patch_invalid", "管理操作类型无效", "tracking_management")
    if operation == TRACKING_OPERATION_KIND_REFRESH_RSS and target_scope != "ASSOCIATED_RSS":
        raise Stage1Error("tracking_management_patch_invalid", "刷新操作目标无效", "tracking_management")

    _guard_current_operation(resolved_config, record)
    safe_patch = _safe_patch(operation, target_scope, patch, enabled)
    binding = build_management_binding(action=operation, scope=target_scope, patch=safe_patch if operation == "MODIFY" else None, enabled=enabled if operation == "SET_ENABLED" else None)
    existing = _load_operation_if_present(resolved_config, idempotency_key)
    if existing is not None:
        if (existing.tracking_id, existing.operation, existing.expected_revision,
                existing.target_scope, existing.request_fingerprint,
                existing.expected_external_fingerprint) != (
                    record.tracking_id, operation, expected_revision, target_scope,
                    binding.action_fingerprint, binding.expected_external_fingerprint):
            raise Stage1Error("tracking_idempotency_conflict", "同一幂等键已绑定不同的管理操作", "tracking_management")
        if existing.state in TRACKING_OPERATION_TERMINAL_STATES:
            return {"operation_id": existing.operation_id, "management_status": existing.state, "created": False}
        raise Stage1Error("tracking_management_state_conflict", "已有管理操作正在执行，请先恢复", "tracking_management")
    if management_client is None:
        raise Stage1Error("tracking_management_capability_unknown", "管理能力尚未验证", "tracking_management")
    caps, subscriptions, rss_items = management_client.read_snapshot()
    effective_caps = capabilities or caps
    field = _CAPABILITY_FIELDS.get((operation, target_scope))
    if field is None or getattr(effective_caps, field, "UNKNOWN") != "SUPPORTED":
        raise Stage1Error("tracking_management_capability_unknown", "当前 Auto Bangumi 管理能力未验证", "tracking_management")
    target = resolve_management_target(record, target_scope, subscriptions, rss_items)
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
            write(target, _write_payload(operation, target, safe_patch, enabled))
        except Exception:
            # IN_PROGRESS is durable evidence that the call may have happened.
            raise
    return {"operation_id": in_progress.operation_id, "management_status": "IN_PROGRESS", "created": True}


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
    if operation.state in {TRACKING_OPERATION_STATE_PREPARED, TRACKING_OPERATION_STATE_IN_PROGRESS}:
        raise Stage1Error("tracking_management_state_conflict", "已有管理操作正在执行，请先恢复", "tracking_management")


def _load_operation_if_present(config: StorageConfig, idempotency_key: str) -> TrackingOperation | None:
    operation_id = tracking_operation_id_for_idempotency_key(idempotency_key)
    try:
        return load_tracking_operation(config, operation_id)
    except Stage1Error as exc:
        if exc.error_type == "tracking_operation_not_found":
            return None
        raise


__all__ = ["ManagementBinding", "ManagementSnapshotClient", "ManagementWriter", "run_tracking_management"]
