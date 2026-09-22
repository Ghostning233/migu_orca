"""Unified "delete the tracking plan" use case (issue #92).

One business action removes the local tracking plan **and** its tracking record
together, and optionally the controlled external subscription as well:

* without the external checkbox the external object keeps running and MiGuOrca
  simply stops managing it (the mapping disappears with the record, so later
  syncs can never re-import or adopt it);
* with the checkbox the exact mapped external object is removed first through
  the reliable management sequence (confirm, expected revision, idempotency,
  read-back, unknown-outcome recovery, adapter-fixed ``file=false``), and only a
  confirmed success is followed by the local delete.

An external failure or an unknown outcome removes nothing: the plan, the record,
the mapping and the recovery evidence all stay, so the user never loses control
of the external object. No path here deletes downloaded media.
"""
from __future__ import annotations

import contextlib
from typing import Any

from apps.migu_orca_web.schemas import (
    SavedTrackingManagementInput,
    SavedTrackingPlanDeleteInput,
)
from apps.migu_orca_web.tracking_saved_management_service import run_saved_tracking_management
from shared.errors import Stage1Error
from storage_engine.controllers.request_repository import delete_request_snapshot
from storage_engine.controllers.storage_config import StorageConfig
from storage_engine.controllers.tracking_repository import (
    delete_tracking_record,
    load_tracking_record,
)
from tracking_engine.models.tracking import (
    TRACKING_STATUS_RECOVERY_REQUIRED,
    TRACKING_STATUS_REVALIDATING,
    TRACKING_STATUS_SUBMITTING,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
    TrackingRecord,
)

#: Statuses where an external action is still in flight or unresolved: deleting
#: then would race the pending write, so the delete is refused.
_UNDELETABLE_STATUSES = frozenset(
    {
        TRACKING_STATUS_SUBMITTING,
        TRACKING_STATUS_REVALIDATING,
        TRACKING_STATUS_VERIFYING_EXTERNAL,
        TRACKING_STATUS_RECOVERY_REQUIRED,
    }
)

_MANAGEMENT_SUCCEEDED = "SUCCEEDED"
_MANAGEMENT_FAILED = "FAILED"


def run_saved_tracking_plan_delete(
    config: StorageConfig,
    *,
    payload: SavedTrackingPlanDeleteInput,
    repository: Any = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Delete one tracking plan, optionally removing its external subscription."""
    record = load_tracking_record(config, payload.tracking_id)
    _guard_deletable(config, record)

    mapping = record.external_mapping if isinstance(record.external_mapping, dict) else {}
    has_controlled_external = isinstance(mapping.get("subscription_id"), str) and bool(
        mapping.get("subscription_id")
    )

    external_deleted = False
    if payload.delete_external and has_controlled_external:
        outcome = _delete_external(payload=payload, record=record)
        if outcome != _MANAGEMENT_SUCCEEDED:
            # Nothing local is removed: the plan, record, mapping and recovery
            # evidence stay so the user can retry or recover deliberately.
            return {
                "tracking_id": record.tracking_id,
                "outcome": "EXTERNAL_FAILED" if outcome == _MANAGEMENT_FAILED else "EXTERNAL_UNKNOWN",
                "external_deleted": False,
            }
        external_deleted = True

    _delete_local(config, record)
    return {
        "tracking_id": record.tracking_id,
        "outcome": "DELETED",
        "external_deleted": external_deleted,
    }


def _guard_deletable(config: StorageConfig, record: TrackingRecord) -> None:
    """Refuse a delete while an external action is in flight or unresolved."""
    if record.status in _UNDELETABLE_STATUSES or record.current_operation_id:
        raise Stage1Error(
            "tracking_state_conflict",
            "当前追番正在进行外部操作或存在未决结果，请先恢复后再删除",
            "run_saved_tracking_plan_delete",
        )


def _delete_external(
    *,
    payload: SavedTrackingPlanDeleteInput,
    record: TrackingRecord,
) -> str:
    """Run the reliable external delete; return its management status."""
    management = SavedTrackingManagementInput(
        tracking_id=payload.tracking_id,
        target_scope="SUBSCRIPTION",
        operation="DELETE_EXTERNAL",
        expected_revision=record.revision,
        idempotency_key=payload.idempotency_key,
        confirm=True,
        # The management contract takes the canonical string form.
        connection_ref=str(payload.connection_ref),
        configuration_revision=payload.configuration_revision,
        storage_dir=payload.storage_dir,
    )
    result = run_saved_tracking_management(management)
    status = result.get("management_status")
    return status if isinstance(status, str) else "OUTCOME_UNKNOWN"


def _delete_local(config: StorageConfig, record: TrackingRecord) -> None:
    """Remove the local plan and its tracking record; media is never touched."""
    if record.request_id:
        # A plan that cannot be read anymore must not block the delete: removing
        # the tracking record is still the user's explicit request.
        with contextlib.suppress(Stage1Error):
            delete_request_snapshot(config, record.request_id)
    delete_tracking_record(config, record.tracking_id)


__all__ = ["run_saved_tracking_plan_delete"]
