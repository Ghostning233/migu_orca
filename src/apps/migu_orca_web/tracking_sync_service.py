"""Request-scoped, read-only Auto Bangumi tracking synchronisation.

The service is deliberately the only layer that combines the management
adapter, the pure reconciliation controller and durable tracking storage.
Upstream objects never leave the request-scoped adapter/reconciliation path.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from ab_engine.controllers.ab_management_client import (
    AutoBangumiManagementClient,
    Legacy31ManagementClient,
)
from ab_engine.controllers.reconcile import (
    RECONCILE_WARNING_CONFLICT,
    RECONCILE_WARNING_UNPROVEN,
    LocalTrackingEvidence,
    classify_missing_mapping,
    reconcile_subscriptions,
)
from ab_engine.models.management import AutoBangumiCapabilities
from shared.errors import Stage1Error
from storage_engine.controllers.operation_repository import load_tracking_operation
from storage_engine.controllers.request_repository import load_request_snapshot
from storage_engine.controllers.storage_config import StorageConfig, load_storage_config
from storage_engine.controllers.tracking_repository import (
    compare_and_swap_tracking_record,
    ensure_tracking_record,
    list_tracking_records,
)
from tracking_engine.models.operation import (
    TRACKING_OPERATION_STATE_IN_PROGRESS,
    TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
    TRACKING_OPERATION_STATE_PREPARED,
    TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
)
from tracking_engine.models.tracking import (
    TRACKING_AUDIT_PLAN_CHANGE_DETECTED,
    TrackingRecord,
    build_audit_event,
    create_external_tracking_record,
    tracking_to_storage_dict,
    transition_record,
    utc_now,
)

SYNC_WARNING_CAPABILITY_FAILED = "EXTERNAL_CAPABILITY_FAILED"
SYNC_WARNING_PARTIAL = "EXTERNAL_SYNC_PARTIAL"
SYNC_WARNING_UNREADABLE = "UNREADABLE_TRACKING_RECORDS"
SYNC_WARNING_EXTERNAL_DELETED = "EXTERNAL_SUBSCRIPTION_MISSING"


@dataclass(frozen=True)
class TrackingSyncSummary:
    checked: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    external_only: int = 0
    failed: int = 0
    unreadable: int = 0


@dataclass(frozen=True)
class TrackingSyncResult:
    sync_status: str
    checked_at: str
    capabilities: AutoBangumiCapabilities
    summary: TrackingSyncSummary
    warnings: tuple[str, ...] = ()


def run_tracking_sync(
    *,
    ab_config=None,
    storage_dir: Path | str | None = None,
    config: StorageConfig | None = None,
    management_client: AutoBangumiManagementClient | None = None,
    now: str | None = None,
    connection_ref=None,
) -> TrackingSyncResult:
    """Read AB once and converge local records, returning only safe counts.

    ``management_client`` is an injection seam for offline tests.  Production
    callers provide ``ab_config`` and the service creates the read-only 3.1.18
    client.  No error from an external read is interpreted as an empty list.
    """
    resolved_config = config if config is not None else load_storage_config(storage_dir)
    checked_at = now or utc_now()
    if management_client is None:
        if ab_config is None:
            raise Stage1Error("config_error", "缺少 Auto Bangumi 配置", "tracking_sync")
        from ab_engine.controllers.ab_http_client import UrlopenAutoBangumiHttpTransport
        from ab_engine.controllers.ab_management_client import create_legacy_31_management_client

        management_client = create_legacy_31_management_client(
            ab_config, transport=UrlopenAutoBangumiHttpTransport()
        )

    try:
        capabilities, externals, _rss = management_client.read_snapshot()
    except Stage1Error:
        return TrackingSyncResult(
            "FAILED", checked_at, _failed_capabilities(management_client),
            TrackingSyncSummary(), (SYNC_WARNING_CAPABILITY_FAILED,)
        )
    except Exception:
        return TrackingSyncResult(
            "FAILED", checked_at, _failed_capabilities(management_client),
            TrackingSyncSummary(), (SYNC_WARNING_CAPABILITY_FAILED,)
        )

    if capabilities.subscription_list != "SUPPORTED" or (
        connection_ref is not None and capabilities.probe_status != "VERIFIED"
    ):
        return TrackingSyncResult(
            "FAILED", checked_at, capabilities, TrackingSyncSummary(),
            (SYNC_WARNING_CAPABILITY_FAILED,)
        )

    local_result = list_tracking_records(resolved_config)
    locals_by_id = {record.tracking_id: record for record in local_result.records}
    evidence = tuple(
        LocalTrackingEvidence(
            tracking_id=record.tracking_id,
            status=record.status,
            origin=record.origin,
            plan_summary=record.plan_summary,
            external_mapping=record.external_mapping,
            rss_urls=(_request_rss_urls(resolved_config, record) if connection_ref is not None else ()),
        )
        for record in local_result.records
    )
    decisions = reconcile_subscriptions(externals, evidence, connection_ref=connection_ref)
    protected_ids = {
        record.tracking_id for record in local_result.records
        if connection_ref is not None and _has_pending_operation(resolved_config, record)
    }
    for decision in decisions:
        protected_ids.update(decision.protected_tracking_ids)
    if protected_ids:
        warnings: list[str] = [RECONCILE_WARNING_UNPROVEN]
    else:
        warnings = []
    counts = TrackingSyncSummary(unreadable=local_result.unreadable_count)
    if local_result.unreadable_count:
        warnings.append(SYNC_WARNING_UNREADABLE)

    observed_ids = {item.external_id for item in externals}
    for decision in decisions:
        if decision.warning and decision.warning not in warnings:
            warnings.append(decision.warning)
        if decision.tracking_id is None:
            if decision.warning == RECONCILE_WARNING_CONFLICT or decision.protected_tracking_ids:
                counts = replace(counts, checked=counts.checked + 1, unchanged=counts.unchanged + 1)
                continue
            if connection_ref is not None:
                existing_external = locals_by_id.get(
                    _external_tracking_id(decision.external_id, connection_ref)
                )
                if existing_external is not None and existing_external.tracking_id in protected_ids:
                    counts = replace(counts, checked=counts.checked + 1, unchanged=counts.unchanged + 1)
                    continue
            record, created, failed = _ensure_external(
                resolved_config, decision, externals, checked_at, connection_ref
            )
            counts = replace(
                counts,
                checked=counts.checked + 1,
                created=counts.created + int(created),
                external_only=counts.external_only + 1,
                unchanged=counts.unchanged + int(not created and not failed),
                failed=counts.failed + int(failed),
            )
            continue
        local = locals_by_id.get(decision.tracking_id)
        if local is None:
            counts = replace(counts, checked=counts.checked + 1, failed=counts.failed + 1)
            continue
        if local.tracking_id in protected_ids:
            counts = replace(counts, checked=counts.checked + 1, unchanged=counts.unchanged + 1)
            continue
        updated, failed = _apply_decision(resolved_config, local, decision, checked_at, connection_ref)
        counts = replace(
            counts,
            checked=counts.checked + 1,
            updated=counts.updated + int(updated and not failed),
            unchanged=counts.unchanged + int(not updated and not failed),
            failed=counts.failed + int(failed),
        )
        orphan_id = _external_tracking_id(decision.external_id, connection_ref)
        orphan = locals_by_id.get(orphan_id)
        if (orphan is not None and orphan.tracking_id != local.tracking_id
                and local.request_id is not None and _same_ref(orphan, connection_ref)
                and orphan.tracking_id not in protected_ids):
            merged, merge_failed = _merge_orphan(resolved_config, orphan, local.tracking_id, checked_at)
            counts = replace(
                counts, updated=counts.updated + int(merged and not merge_failed),
                failed=counts.failed + int(merge_failed),
            )
        if updated and decision.warning and decision.warning not in warnings:
            warnings.append(decision.warning)

    # A complete successful list is the only evidence allowed to mark mapped
    # locals deleted.  In-progress records are protected by reconcile itself.
    for local in local_result.records:
        if local.tracking_id in {d.tracking_id for d in decisions if d.tracking_id}:
            continue
        if local.tracking_id in protected_ids:
            continue
        missing = classify_missing_mapping(local, complete_subscription_list=True, connection_ref=connection_ref)
        if missing is None or _mapping_subscription_id(local) in observed_ids:
            continue
        if SYNC_WARNING_EXTERNAL_DELETED not in warnings:
            warnings.append(SYNC_WARNING_EXTERNAL_DELETED)
        updated, failed = _apply_missing(resolved_config, local, missing, checked_at, connection_ref)
        counts = replace(
            counts, updated=counts.updated + int(updated and not failed),
            unchanged=counts.unchanged + int(not updated and not failed),
            failed=counts.failed + int(failed),
        )

    status = (("PARTIAL" if counts.checked or counts.updated else "FAILED")
              if counts.failed or warnings else "COMPLETE")
    return TrackingSyncResult(status, checked_at, capabilities, counts, tuple(warnings))


def _apply_decision(config, record: TrackingRecord, decision, timestamp: str, connection_ref=None) -> tuple[bool, bool]:
    desired_status = decision.status
    mapping = decision.safe_mapping(connection_ref=connection_ref)
    current_mapping = record.external_mapping or {}
    mapping_changed = _mapping_without_verified_at(current_mapping) != _mapping_without_verified_at(mapping)
    status_changed = desired_status != record.status
    if not mapping_changed and not status_changed:
        return False, False

    mapping["last_verified_at"] = timestamp
    desired = replace(record, external_mapping=mapping, last_synced_at=timestamp)
    if status_changed:
        desired = transition_record(
            desired, status=desired_status,
            audit_action=TRACKING_AUDIT_PLAN_CHANGE_DETECTED,
            reason_code=decision.match_reason,
            safe_message="外部同步已更新追番状态", now=timestamp,
        )
    elif _semantic_record(record) != _semantic_record(desired):
        desired = replace(
            desired, revision=record.revision + 1, updated_at=timestamp,
            audit_events=[*record.audit_events, build_audit_event(
                action=TRACKING_AUDIT_PLAN_CHANGE_DETECTED,
                actor="SYSTEM", from_status=record.status, to_status=record.status,
                tracking_revision=record.revision + 1, reason_code=decision.match_reason,
                safe_message="外部同步已更新追番映射", created_at=timestamp,
            )],
        )
    try:
        compare_and_swap_tracking_record(config, record.tracking_id, record.revision, desired)
        return True, False
    except Stage1Error:
        return False, True


def _apply_missing(config, record, decision, timestamp, connection_ref=None):
    previous_mapping = record.external_mapping or {}
    missing_count = int(previous_mapping.get("missing_sync_count", 0))
    if record.status != decision.status:
        missing_count += 1
    mapping = {**previous_mapping, **decision.safe_mapping(connection_ref=connection_ref), "missing_sync_count": missing_count}
    status_changed = decision.status != record.status
    mapping_changed = _mapping_without_verified_at(previous_mapping) != _mapping_without_verified_at(mapping)
    if not mapping_changed and not status_changed:
        return False, False

    mapping["last_verified_at"] = timestamp
    desired = replace(record, external_mapping=mapping, last_synced_at=timestamp)
    if status_changed:
        desired = transition_record(desired, status=decision.status,
            audit_action=TRACKING_AUDIT_PLAN_CHANGE_DETECTED,
            reason_code="EXTERNAL_SUBSCRIPTION_MISSING", safe_message="外部追番暂未找到", now=timestamp)
    elif _semantic_record(record) != _semantic_record(desired):
        desired = replace(desired, revision=record.revision + 1, updated_at=timestamp)
    try:
        compare_and_swap_tracking_record(config, record.tracking_id, record.revision, desired)
        return True, False
    except Stage1Error:
        return False, True


def _ensure_external(config, decision, externals, timestamp, connection_ref=None):
    external = next(item for item in externals if item.external_id == decision.external_id)
    record = create_external_tracking_record(
        adapter="legacy_3_1", object_kind="subscription", external_id=external.external_id,
        title=external.title, season=external.season, subtitle_group=external.subtitle_group,
        subscription_id=decision.subscription_id, rss_ids=decision.rss_ids,
        match_reason=decision.match_reason, external_deleted=decision.external_deleted,
        connection_ref=connection_ref,
        enabled=not decision.external_deleted, last_verified_at=timestamp, now=timestamp,
    )
    try:
        existing, created = ensure_tracking_record(config, record)
        if created:
            return existing, True, False
        updated, failed = _apply_decision(config, existing, decision, timestamp, connection_ref)
        return existing, False, failed
    except Stage1Error:
        return record, False, True


def _merge_orphan(config, orphan: TrackingRecord, target_id: str, timestamp: str) -> tuple[bool, bool]:
    """Mark an old external-only record as an alias of the local authority."""
    if (orphan.recovery or {}).get("merged_into_tracking_id") == target_id:
        return False, False
    desired = replace(
        orphan,
        recovery={"merged_into_tracking_id": target_id},
        revision=orphan.revision + 1,
        updated_at=timestamp,
        audit_events=[*orphan.audit_events, build_audit_event(
            action=TRACKING_AUDIT_PLAN_CHANGE_DETECTED, actor="SYSTEM",
            from_status=orphan.status, to_status=orphan.status,
            tracking_revision=orphan.revision + 1, reason_code="MERGED_INTO_LOCAL",
            safe_message="外部孤立记录已合并到本地追番", created_at=timestamp,
        )],
    )
    try:
        compare_and_swap_tracking_record(config, orphan.tracking_id, orphan.revision, desired)
        return True, False
    except Stage1Error:
        return False, True


def _semantic_record(record: TrackingRecord) -> dict:
    value = tracking_to_storage_dict(record)
    value.pop("revision", None)
    value.pop("updated_at", None)
    return value


def _mapping_without_verified_at(mapping: dict | None) -> dict:
    """Compare only external projection evidence, not check timestamps."""
    return {key: value for key, value in (mapping or {}).items() if key != "last_verified_at"}


def _mapping_subscription_id(record):
    mapping = record.external_mapping or {}
    value = mapping.get("subscription_id")
    return value if isinstance(value, str) else None


def _external_tracking_id(external_id: str, connection_ref=None) -> str:
    from tracking_engine.models.tracking import tracking_id_for_external

    return tracking_id_for_external("legacy_3_1", "subscription", external_id, connection_ref)


def _same_ref(record: TrackingRecord, connection_ref) -> bool:
    return connection_ref is None or (record.external_mapping or {}).get("connection_ref") == str(connection_ref)


def _has_pending_operation(config: StorageConfig, record: TrackingRecord) -> bool:
    if record.status in {"UNKNOWN", "VERIFYING_EXTERNAL", "RECOVERY_REQUIRED"}:
        return True
    if not record.current_operation_id:
        return False
    try:
        operation = load_tracking_operation(config, record.current_operation_id)
    except Stage1Error:
        return True
    return operation.state in {
        TRACKING_OPERATION_STATE_PREPARED, TRACKING_OPERATION_STATE_IN_PROGRESS,
        TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN, TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
    }


def _request_rss_urls(config: StorageConfig, record: TrackingRecord) -> tuple[str, ...]:
    if not record.request_id:
        return ()
    try:
        request = load_request_snapshot(config, record.request_id)
    except Stage1Error:
        return ()
    confirmable = request.get("confirmable_config")
    selected_url = confirmable.get("selected_rss_url") if isinstance(confirmable, dict) else None
    return (selected_url,) if isinstance(selected_url, str) and selected_url else ()


def _failed_capabilities(client) -> AutoBangumiCapabilities:
    adapter = "legacy_3_1" if isinstance(client, Legacy31ManagementClient) else None
    return AutoBangumiCapabilities(
        probe_status="FAILED", version=None, adapter=adapter,
        subscription_list="UNKNOWN", subscription_detail="UNKNOWN", rss_list="UNKNOWN",
        external_verify="UNKNOWN", safe_message="Auto Bangumi 外部同步失败，能力保持未知",
    )


__all__ = ["TrackingSyncResult", "TrackingSyncSummary", "run_tracking_sync"]
