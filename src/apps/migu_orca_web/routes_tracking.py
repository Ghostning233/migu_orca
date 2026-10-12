from __future__ import annotations

from flask import request

"""Tracking-items family API routes (US-223).

Provides the read-only unified tracking list and detail endpoints:

- ``GET /api/v1/tracking/items`` — safe local list with optional ``q`` /
  ``status_group`` / ``sort`` filters and summary counts;
- ``GET /api/v1/tracking/items/{tracking_id}`` — safe detail reusing the
  Request safe-info whitelist plus operation/audit summaries.

Both run the historical-backfill coordinator before reading, so a first access
converges migrated records onto the same deterministic tracking list.  Only
local storage is read — no external system is ever contacted.
"""

from apps.migu_orca_web.blueprints import api_blueprint
from apps.migu_orca_web.schemas import (
    SavedTrackingBatchSubmitInput,
    SavedTrackingManagementInput,
    SavedTrackingPlanDeleteInput,
    SavedTrackingRecoveryInput,
    SavedTrackingSubmitInput,
    SavedTrackingSyncInput,
    TrackingCheckPayload,
    TrackingDeleteExternalPayload,
    TrackingDetailQuery,
    TrackingListQuery,
    TrackingModifyPayload,
    TrackingRecoverPayload,
    TrackingRefreshRssPayload,
    TrackingRevalidatePayload,
    TrackingSetEnabledPayload,
    TrackingSyncPayload,
)
from apps.migu_orca_web.services import _storage_dir
from apps.migu_orca_web.tracking_check_service import run_saved_tracking_check
from apps.migu_orca_web.tracking_management_service import management_writer
from apps.migu_orca_web.tracking_plan_delete_service import run_saved_tracking_plan_delete
from apps.migu_orca_web.tracking_read_service import (
    build_tracking_detail,
    list_tracking_items,
)
from apps.migu_orca_web.tracking_revalidate_service import run_tracking_revalidate
from apps.migu_orca_web.tracking_saved_management_service import run_saved_tracking_management
from apps.migu_orca_web.tracking_saved_recovery_service import run_saved_tracking_recovery
from apps.migu_orca_web.tracking_saved_sync_service import run_saved_tracking_sync
from apps.migu_orca_web.tracking_serializers import serialize_tracking_operation_summary, tracking_summary_fields
from apps.migu_orca_web.tracking_submission_service import (
    run_saved_tracking_batch_submit,
    run_saved_tracking_retry,
    run_saved_tracking_submit,
)
from extensions.flask_api import class_route
from extensions.flask_api.views import GetView, PostView
from storage_engine.controllers.operation_repository import load_tracking_operation
from storage_engine.controllers.storage_config import load_storage_config
from storage_engine.controllers.tracking_repository import load_tracking_record
from tracking_engine.models.operation import TRACKING_OPERATION_STATE_SUCCEEDED


@class_route(api_blueprint, "/api/v1/tracking/items", methods=["GET"])
class TrackingItemListView(GetView):
    """Return the safe unified tracking list (Stage 29 PRD §11.2)."""

    request_validator_model = TrackingListQuery

    def get_object(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, TrackingListQuery)
        query = self.request_validator_model
        config = load_storage_config(_storage_dir(query.storage_dir))
        return list_tracking_items(
            config,
            q=query.q,
            status_group=query.status_group,
            sort=query.sort,
        )


@class_route(api_blueprint, "/api/v1/tracking/sync", methods=["POST"])
class TrackingSyncView(PostView):
    """Run a read-only sync through the saved connection generation."""

    request_validator_model = TrackingSyncPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, TrackingSyncPayload)
        payload = self.request_validator_model
        config = load_storage_config(_storage_dir(payload.storage_dir))
        result = run_saved_tracking_sync(SavedTrackingSyncInput.model_validate({
            "connection_ref": str(payload.connection_ref),
            "configuration_revision": payload.configuration_revision,
            "confirm": payload.confirm,
            "storage_dir": payload.storage_dir,
        }))
        listing = list_tracking_items(config)
        warnings = list(result.warnings)
        for warning in listing["warnings"]:
            if warning not in warnings:
                warnings.append(warning)
        return {
            "sync_status": result.sync_status,
            "checked_at": result.checked_at,
            "capabilities": result.capabilities.to_public_dict(),
            "summary": result.summary.__dict__,
            "warnings": warnings,
            "items": listing["items"],
        }


@class_route(
    api_blueprint,
    "/api/v1/tracking/items/<path:tracking_id>",
    methods=["GET"],
)
class TrackingItemDetailView(GetView):
    """Return the safe unified tracking detail (Stage 29 PRD §11.3)."""

    request_validator_model = TrackingDetailQuery

    def get_object(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, TrackingDetailQuery)
        query = self.request_validator_model
        config = load_storage_config(_storage_dir(query.storage_dir))
        return build_tracking_detail(config, query.tracking_id)


@class_route(
    api_blueprint,
    "/api/v1/tracking/items/<path:tracking_id>/revalidate",
    methods=["POST"],
)
class TrackingItemRevalidateView(PostView):
    """Run the pure-local pre-submit revalidation for one tracking item (US-224).

    The request carries only ``expected_revision`` (plus an optional storage
    profile) — never accepts client credentials or connection settings.  A
    business revalidation failure is still HTTP 200 (``ready=false`` +
    ``next_status=NEEDS_RECONFIRM`` + the fixed §11.5 issue list); only a stale
    revision (409) or a non-revalidatable tracking state (409) raise.
    """

    request_validator_model = TrackingRevalidatePayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, TrackingRevalidatePayload)
        payload = self.request_validator_model
        config = load_storage_config(_storage_dir(payload.storage_dir))
        return run_tracking_revalidate(
            config,
            tracking_id=payload.tracking_id,
            expected_revision=payload.expected_revision,
        )


@class_route(
    api_blueprint,
    "/api/v1/tracking/items/<path:tracking_id>/submit",
    methods=["POST"],
)
class TrackingItemSubmitView(PostView):
    """Run the unified reliable submit for one tracking item (US-225).

    ``confirm`` must be strictly true; the saved connection lease and immutable
    snapshot are resolved for the submitted generation. The service re-reads the latest local Request and runs
    the complete local revalidation before any Auto Bangumi call; a persisted
    business outcome (``NEEDS_RECONFIRM``/``SUBMIT_FAILED``/
    ``VERIFYING_EXTERNAL``/``RECOVERY_REQUIRED``/``ACTIVE``) is HTTP 200.  Only
    preconditions (missing record, stale revision, non-submittable state,
    idempotency conflict, in-flight operation) raise.
    """

    request_validator_model = None

    def save(self) -> dict[str, object]:
        body = request.get_json(silent=True) or {}
        payload = SavedTrackingSubmitInput.model_validate({**body, "tracking_id": request.view_args["tracking_id"]})
        return run_saved_tracking_submit(load_storage_config(_storage_dir(payload.storage_dir)), payload=payload)


@class_route(
    api_blueprint,
    "/api/v1/tracking/batch-submit",
    methods=["POST"],
)
class TrackingBatchSubmitView(PostView):
    """Run an explicit batch of independent reliable submissions (issue #87).

    ``items`` holds 1..36 distinct tracking records, each with its own expected
    revision and opaque idempotency key.  The service resolves every entry
    through the single reliable submit sequence, so each one succeeds or fails on
    its own: there is no whole-batch transaction and a success is never rolled
    back by a later failure.  Every entry returns its own business result (or a
    stable pre-boundary ``error_type``); the batch request itself is HTTP 200
    whenever it was accepted.
    """

    request_validator_model = SavedTrackingBatchSubmitInput

    def save(self) -> dict[str, object]:
        payload = self.request_validator_model
        assert isinstance(payload, SavedTrackingBatchSubmitInput)
        return run_saved_tracking_batch_submit(
            load_storage_config(_storage_dir(payload.storage_dir)), payload=payload
        )


@class_route(
    api_blueprint,
    "/api/v1/tracking/items/<path:tracking_id>/delete-plan",
    methods=["POST"],
)
class TrackingItemDeletePlanView(PostView):
    """Delete one tracking plan, optionally with its controlled external object.

    ``delete_external`` defaults to false, so the external subscription keeps
    running unless the user explicitly ticked the option. A requested external
    delete runs first through the reliable management sequence and only a
    confirmed success is followed by the local plan/record delete; a failure or
    an unknown outcome removes nothing local.
    """

    request_validator_model = None

    def save(self) -> dict[str, object]:
        body = request.get_json(silent=True) or {}
        payload = SavedTrackingPlanDeleteInput.model_validate(
            {**body, "tracking_id": request.view_args["tracking_id"]}
        )
        return run_saved_tracking_plan_delete(
            load_storage_config(_storage_dir(payload.storage_dir)), payload=payload
        )


@class_route(
    api_blueprint,
    "/api/v1/tracking/items/<path:tracking_id>/retry",
    methods=["POST"],
)
class TrackingItemRetryView(PostView):
    """Retry a definitely-failed unified submission (US-226).

    Only ``SUBMIT_FAILED`` records are retryable — an unknown/incomplete outcome
    (``VERIFYING_EXTERNAL``/``RECOVERY_REQUIRED``) must be recovered first.  The
    request shape is identical to ``submit`` (``confirm`` strictly true,
    saved connection generation and opaque idempotency key); the unified
    service re-reads the latest Request and revalidates before creating a fresh
    operation and calling Auto Bangumi once.  A persisted business outcome is
    HTTP 200; only preconditions (missing record, stale revision,
    non-retryable state, idempotency conflict, in-flight operation) raise.
    """

    request_validator_model = None

    def save(self) -> dict[str, object]:
        body = request.get_json(silent=True) or {}
        payload = SavedTrackingSubmitInput.model_validate({**body, "tracking_id": request.view_args["tracking_id"]})
        return run_saved_tracking_retry(load_storage_config(_storage_dir(payload.storage_dir)), payload=payload)


@class_route(
    api_blueprint,
    "/api/v1/tracking/items/<path:tracking_id>/check",
    methods=["POST"],
)
class TrackingItemCheckView(PostView):
    """Run one bounded, read-only confirmation of a pending submission (#183).

    The request carries only ``expected_revision``: the Auto Bangumi instance is
    the one the original submit operation was bound to, resolved server-side, so
    the browser never supplies a connection and a replaced saved connection is
    reported instead of rebinding the old operation.  The check only reads; it
    never creates, modifies, deletes or resubmits a subscription.  A stale
    revision (409) or a record with no checkable pending submission (409) raise;
    every read-only business outcome is HTTP 200.
    """

    request_validator_model = TrackingCheckPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, TrackingCheckPayload)
        payload = self.request_validator_model
        return run_saved_tracking_check(
            TrackingCheckPayload.model_validate({
                **payload.model_dump(mode="json", exclude_none=True),
                "tracking_id": payload.tracking_id,
            })
        )


@class_route(
    api_blueprint,
    "/api/v1/tracking/items/<path:tracking_id>/recover",
    methods=["POST"],
)
class TrackingItemRecoverView(PostView):
    """Resolve an unknown/incomplete unified tracking outcome (US-226).

    ``action=AUTO`` reads only local operation / Request safe AB-result evidence
    and never contacts an external system; ``MARK_SUCCEEDED``/``MARK_FAILED``
    require ``confirm=true`` and write a USER audit.  The endpoint never accepts
    an external id/URL/raw result.  A persisted recovery outcome
    (``ACTIVE``/``SUBMIT_FAILED``/``RECOVERY_REQUIRED``) is HTTP 200; only
    preconditions (missing record, stale revision, non-recoverable state,
    missing manual confirmation) raise.
    """

    request_validator_model = TrackingRecoverPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, TrackingRecoverPayload)
        payload = self.request_validator_model
        return run_saved_tracking_recovery(SavedTrackingRecoveryInput.model_validate({
            **payload.model_dump(mode="json", exclude_none=True), "tracking_id": payload.tracking_id,
        }))


_management_writer = management_writer


def _management_result(config, *, tracking_id: str, action: str, result: dict[str, object]) -> dict[str, object]:
    record = load_tracking_record(config, tracking_id)
    operation = None
    if record.current_operation_id:
        operation = load_tracking_operation(config, record.current_operation_id)
    management_status = result.get("management_status")
    safe_message = (
        "管理操作已完成"
        if management_status == TRACKING_OPERATION_STATE_SUCCEEDED
        else "管理操作明确失败，外部系统未确认应用"
        if management_status == "FAILED" and result.get("needs_manual") is not True
        else "外部管理结果未知，请人工恢复；不会自动重试"
    )
    return {
        "action": action,
        "management_status": management_status or "RECOVERY_REQUIRED",
        "outcome": result.get("outcome"),
        "needs_manual": result.get("needs_manual") is True,
        "safe_message": safe_message,
        "operation_id": result.get("operation_id"),
        "tracking": tracking_summary_fields(record),
        "operation": serialize_tracking_operation_summary(operation) if operation else None,
    }


def _run_management_route(payload, action: str, patch: dict[str, object] | None = None, enabled: bool | None = None) -> dict[str, object]:
    saved = SavedTrackingManagementInput.model_validate({
        **payload.model_dump(mode="json"), "operation": action, "patch": patch, "enabled": enabled,
    })
    config = load_storage_config(_storage_dir(payload.storage_dir))
    result = run_saved_tracking_management(saved)
    return _management_result(config, tracking_id=payload.tracking_id, action=action, result=result)


@class_route(api_blueprint, "/api/v1/tracking/items/<path:tracking_id>/modify", methods=["POST"])
class TrackingItemModifyView(PostView):
    request_validator_model = TrackingModifyPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, TrackingModifyPayload)
        payload = self.request_validator_model
        return _run_management_route(
            payload, "MODIFY", patch=payload.patch.model_dump(exclude_unset=True)
        )


@class_route(api_blueprint, "/api/v1/tracking/items/<path:tracking_id>/set-enabled", methods=["POST"])
class TrackingItemSetEnabledView(PostView):
    request_validator_model = TrackingSetEnabledPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, TrackingSetEnabledPayload)
        payload = self.request_validator_model
        return _run_management_route(payload, "SET_ENABLED", enabled=payload.enabled)


@class_route(api_blueprint, "/api/v1/tracking/items/<path:tracking_id>/delete-external", methods=["POST"])
class TrackingItemDeleteExternalView(PostView):
    request_validator_model = TrackingDeleteExternalPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, TrackingDeleteExternalPayload)
        return _run_management_route(self.request_validator_model, "DELETE_EXTERNAL")


@class_route(api_blueprint, "/api/v1/tracking/items/<path:tracking_id>/refresh", methods=["POST"])
class TrackingItemRefreshView(PostView):
    request_validator_model = TrackingRefreshRssPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, TrackingRefreshRssPayload)
        return _run_management_route(self.request_validator_model, "REFRESH_RSS")


__all__ = [
    "TrackingItemCheckView",
    "TrackingItemDetailView",
    "TrackingItemDeleteExternalView",
    "TrackingItemListView",
    "TrackingItemModifyView",
    "TrackingItemRefreshView",
    "TrackingItemRecoverView",
    "TrackingItemRetryView",
    "TrackingItemRevalidateView",
    "TrackingItemSubmitView",
    "TrackingItemSetEnabledView",
    "TrackingSyncView",
]
