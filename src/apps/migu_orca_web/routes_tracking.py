from __future__ import annotations

from typing import Any

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
    SavedTrackingBatchDeleteExternalInput,
    SavedTrackingBatchDeleteInput,
    SavedTrackingBatchSubmitInput,
    SavedTrackingManagementInput,
    SavedTrackingPlanDeleteInput,
    SavedTrackingRecoveryInput,
    SavedTrackingSubmitInput,
    SavedTrackingSyncInput,
    TrackingBatchDeleteStatusQuery,
    TrackingCheckPayload,
    TrackingDetailQuery,
    TrackingListQuery,
    TrackingModifyPayload,
    TrackingRecoverPayload,
    TrackingRefreshRssPayload,
    TrackingResubmitPayload,
    TrackingRevalidatePayload,
    TrackingSetEnabledPayload,
    TrackingSyncPayload,
)
from apps.migu_orca_web.services import _storage_dir
from apps.migu_orca_web.tracking_batch_delete_service import (
    ensure_no_racing_single_writes,
    get_saved_tracking_batch_delete,
    run_saved_tracking_batch_delete,
)
from apps.migu_orca_web.tracking_check_service import run_saved_tracking_check
from apps.migu_orca_web.tracking_management_service import management_writer
from apps.migu_orca_web.tracking_plan_delete_service import run_saved_tracking_plan_delete
from apps.migu_orca_web.tracking_read_service import (
    build_tracking_detail,
    list_tracking_items,
)
from apps.migu_orca_web.tracking_resubmit_service import run_saved_tracking_resubmit
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
from extensions.flask_api.api import failed_response
from extensions.flask_api.views import GetView, PostView
from shared.errors import Stage1Error
from storage_engine.controllers.operation_repository import load_tracking_operation
from storage_engine.controllers.storage_config import load_storage_config
from storage_engine.controllers.tracking_repository import (
    batch_conflicts_with,
    load_tracking_record,
    note_request_storage_dirs,
    tracking_batch_lease,
    tracking_batch_scope,
)
from tracking_engine.models.operation import TRACKING_OPERATION_STATE_SUCCEEDED

#: Issue #248: only a route that may start an **external** write on a record can
#: collide with the batch's external-write resource.  Read-only verifications
#: (``check``/``revalidate``/``recover``) and pure-local record writes are never
#: refused here — the batch owns the external write, not the record file.
_BATCH_EXCLUDED_SINGLE_WRITES: frozenset[tuple[str, str]] = frozenset({
    ("POST", "/api/v1/tracking/items/<path:tracking_id>/submit"),
    ("POST", "/api/v1/tracking/items/<path:tracking_id>/retry"),
    ("POST", "/api/v1/tracking/items/<path:tracking_id>/delete-plan"),
    ("POST", "/api/v1/tracking/items/<path:tracking_id>/resubmit"),
    ("POST", "/api/v1/tracking/items/<path:tracking_id>/modify"),
    ("POST", "/api/v1/tracking/items/<path:tracking_id>/set-enabled"),
    ("POST", "/api/v1/tracking/items/<path:tracking_id>/refresh"),
})

#: Issue #248 (connection resource): replacing or deleting the saved Auto Bangumi
#: connection changes the generation a running batch pinned, so a batch that
#: names a connection excludes those two writes.  A local-only batch has no
#: connection and does not block a settings change.
_BATCH_EXCLUDED_CONNECTION_WRITES: frozenset[tuple[str, str]] = frozenset({
    ("PUT", "/api/v1/settings/autobangumi"),
    ("DELETE", "/api/v1/settings/autobangumi"),
})


def _request_storage_profiles() -> frozenset[str] | None:
    """Every storage profile this request could resolve to, or ``None``.

    Views disagree about the ``storage_dir`` source: the manual tracking views
    read the body, while ``extensions.flask_api.views`` lets a query string
    override it.  The guard therefore records **both** candidates and the
    conflict predicate fails closed on any match, so an attacker cannot pick the
    source the guard ignores (issue #248 B3).

    ``None`` means a parse failure (malformed JSON body / invalid profile): the
    view must answer 400, never this guard a 409.
    """
    body = request.get_json(silent=True)
    if request.data and body is None:
        return None
    raw_body = body.get("storage_dir") if isinstance(body, dict) else None
    raw_query = request.args.get("storage_dir")
    if raw_body is not None and not isinstance(raw_body, str):
        return None
    if raw_query is not None and not isinstance(raw_query, str):
        return None
    try:
        candidates = {str(_storage_dir(raw_body))}
        candidates.add(str(_storage_dir(raw_query)))
    except Stage1Error:
        return None
    return frozenset(candidates)


@api_blueprint.before_request
def _refuse_single_tracking_write_during_batch() -> Any | None:
    """Early refusal for a single external write the running batch owns.

    The batch publishes its occupied resources (records + profile + connection)
    with its lease; this guard refuses only an external write on one of those
    records in one of the profiles this request may resolve to.  It runs before
    any service persists an intent, so the published ``connection_in_use`` (409)
    cannot leave an orphan operation; the repository's ``lock_tracking_record``
    is the final, shared check for the race window between this guard and the
    batch.
    """
    note_request_storage_dirs(())
    scope = tracking_batch_scope()
    if scope is None:
        return None
    rule = request.url_rule
    if rule is None:
        return None
    key = (request.method.upper(), rule.rule)
    if key not in _BATCH_EXCLUDED_SINGLE_WRITES and key not in _BATCH_EXCLUDED_CONNECTION_WRITES:
        return None
    profiles = _request_storage_profiles()
    # Publish the candidates for the repository's final gate: it must apply the
    # same predicate as this guard (issue #248 I2/I3/B3).
    note_request_storage_dirs(profiles)
    if profiles is None:
        # A malformed body/profile must reach the view for its 400.
        return None
    if key in _BATCH_EXCLUDED_CONNECTION_WRITES:
        if scope.connection_ref is None:
            return None
        return failed_response(
            "connection_in_use",
            "批量操作进行中：请等待批次结束后再修改 Auto Bangumi 连接",
            {"failed_step": "tracking_batch_connection_exclusion"},
        )
    tracking_id = (request.view_args or {}).get("tracking_id")
    if not isinstance(tracking_id, str) or not tracking_id.strip():
        return None
    # A parseable but schema-invalid body still gets this 409 while the record is
    # owned: the batch is the stronger, fail-closed answer, and the alternative
    # would require duplicating each view's validator here.
    if not batch_conflicts_with(tracking_id, storage_dirs=profiles):
        return None
    return failed_response(
        "connection_in_use",
        "批量操作进行中：请等待批次结束后再操作该记录",
        {"failed_step": "tracking_batch_exclusion"},
    )


@api_blueprint.teardown_request
def _clear_request_storage_profile(_exception: BaseException | None) -> None:
    """Do not let one request's profiles leak into the next on this thread."""
    note_request_storage_dirs(())


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
        config = load_storage_config(_storage_dir(payload.storage_dir))
        tracking_ids = {entry.tracking_id for entry in payload.items}
        # ADR-0007 decision 3 applies to every batch: refuse while another
        # record already owns an external write, then hold the batch lease so a
        # later batch or single write cannot overlap this one.
        ensure_no_racing_single_writes(config, tracking_ids)
        # Issue #248: publish the occupied resources so the boundary guard and
        # the repository gate exclude exactly these records.
        with tracking_batch_lease(
            batch_key=f"submit:{payload.items[0].idempotency_key}",
            tracking_ids=tracking_ids,
            connection_ref=str(payload.connection_ref),
            storage_dir=str(config.storage_dir),
        ):
            return run_saved_tracking_batch_submit(config, payload=payload)


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

    Issue #230 (T5b, ADR-0006): an unresolved operation
    (``OUTCOME_UNKNOWN``/``RECOVERY_REQUIRED``) can only be removed through a
    **risk-confirmed abandon** — the same request with ``delete_external=false``
    plus ``expected_revision`` + ``expected_operation_id``.  The server re-reads
    both right before the delete, so a stale confirmation removes nothing.  A
    write that may still run (``PREPARED``/``IN_PROGRESS``), an unreadable or
    unknown operation state, and any abandon carrying ``delete_external=true``
    are refused.
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


def _run_batch_delete(
    config: Any,
    *,
    payload: Any,
    delete_external: bool,
    tracking_ids: set[str],
    connection_ref: str | None = None,
) -> dict[str, object]:
    """Run one batch delete under the route-published resource scope.

    A replay of an already completed batch is a pure read, so another running
    batch must not turn it into a 409: fall back to the stored result.
    """
    try:
        with tracking_batch_lease(
            batch_key=payload.idempotency_key,
            tracking_ids=tracking_ids,
            connection_ref=connection_ref,
            storage_dir=str(config.storage_dir),
        ):
            return run_saved_tracking_batch_delete(
                config,
                payload=payload,
                delete_external=delete_external,
            )
    except Stage1Error as exc:
        if exc.error_type != "connection_in_use":
            raise
        try:
            stored = get_saved_tracking_batch_delete(config, batch_key=payload.idempotency_key)
        except Stage1Error:
            raise exc from None
        if stored.get("state") == "COMPLETED":
            return stored
        raise


@class_route(
    api_blueprint,
    "/api/v1/tracking/batch-delete-plan",
    methods=["POST"],
)
class TrackingBatchDeletePlanView(PostView):
    """Delete 1..36 local plans/records, never touching Auto Bangumi (#223).

    The body carries no connection fields at all, so this route physically
    cannot start an external write: the controlled external subscription keeps
    running and MiGuOrca simply stops managing it.  Entries whose current
    operation is unresolved are skipped with a reason (never abandoned), the
    batch holds the batch-level lease, and the client's ``idempotency_key``
    makes a replay return the stored per-entry result.
    """

    request_validator_model = SavedTrackingBatchDeleteInput

    def save(self) -> dict[str, object]:
        payload = self.request_validator_model
        assert isinstance(payload, SavedTrackingBatchDeleteInput)
        config = load_storage_config(_storage_dir(payload.storage_dir))
        # Issue #248: publish the occupied resources; the service's own lease
        # nests inside this one and keeps the same scope.
        return _run_batch_delete(
            config,
            payload=payload,
            delete_external=False,
            tracking_ids={entry.tracking_id for entry in payload.items},
        )


@class_route(
    api_blueprint,
    "/api/v1/tracking/batch-delete-plan-external",
    methods=["POST"],
)
class TrackingBatchDeletePlanExternalView(PostView):
    """The same batch, removing each controlled external subscription first (#223).

    A separate route (not a flag on the local one) keeps the external write
    explicit.  Each entry runs the single composite delete: only a confirmed
    external success is followed by that entry's local delete, while an external
    failure or unknown outcome leaves the plan, record and mapping untouched and
    the remaining entries still run.  Sequential; the batch-level lease excludes
    other batches and single tracking writes.
    """

    request_validator_model = SavedTrackingBatchDeleteExternalInput

    def save(self) -> dict[str, object]:
        payload = self.request_validator_model
        assert isinstance(payload, SavedTrackingBatchDeleteExternalInput)
        config = load_storage_config(_storage_dir(payload.storage_dir))
        return _run_batch_delete(
            config,
            payload=payload,
            delete_external=True,
            tracking_ids={entry.tracking_id for entry in payload.items},
            connection_ref=str(payload.connection_ref),
        )


@class_route(
    api_blueprint,
    "/api/v1/tracking/batch-deletions/<path:batch_key>",
    methods=["GET"],
)
class TrackingBatchDeleteStatusView(GetView):
    """Read one batch's stored status by its client idempotency key (#223).

    A client timeout is answerable: the per-entry outcome is persisted after
    every entry, so this returns ``IN_PROGRESS`` with the entries finished so far
    or ``COMPLETED`` with the final result.  Reading never starts a write.
    """

    request_validator_model = TrackingBatchDeleteStatusQuery

    def get_object(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, TrackingBatchDeleteStatusQuery)
        query = self.request_validator_model
        return get_saved_tracking_batch_delete(
            load_storage_config(_storage_dir(query.storage_dir)),
            batch_key=query.batch_key,
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
    "/api/v1/tracking/items/<path:tracking_id>/resubmit",
    methods=["POST"],
)
class TrackingItemResubmitView(PostView):
    """Offer (read-only) or perform one risk-confirmed manual resubmit (#184).

    ``confirm=false`` runs the same bounded read-only confirmation as ``check``
    through the Auto Bangumi instance the pending operation was bound to. A
    proven subscription converges the record with **zero external writes**; an
    unresolved one publishes its proven reason, the duplicate/resource risk and
    the exact binding (revision + pending operation + connection generation).

    ``confirm=true`` is the user's explicit acceptance of that risk. A stale or
    rebound confirmation is refused with 409 before anything is read or written;
    the server re-checks once, converges if the subscription became provable, and
    otherwise creates exactly one new operation traceable to the pending one and
    runs the existing reliable submit sequence once. Every pre-boundary refusal
    and persisted business outcome is HTTP 200.
    """

    request_validator_model = None

    def save(self) -> dict[str, object]:
        body = request.get_json(silent=True) or {}
        payload = TrackingResubmitPayload.model_validate(
            {**body, "tracking_id": request.view_args["tracking_id"]}
        )
        return run_saved_tracking_resubmit(payload)


@class_route(
    api_blueprint,
    "/api/v1/tracking/items/<path:tracking_id>/recover",
    methods=["POST"],
)
class TrackingItemRecoverView(PostView):
    """Resolve an unknown/incomplete unified tracking outcome (US-226 / #228).

    The only accepted ``action`` is ``VERIFY_EXTERNAL``: one bounded read of the
    bound Auto Bangumi connection that never creates, modifies or deletes an
    object.  ``AUTO``/``MARK_SUCCEEDED``/``MARK_FAILED`` are retired and rejected
    by the request enum.  The endpoint never accepts an external id/URL/raw
    result.  A persisted verification result
    (``ACTIVE``/``DISABLED``/``EXTERNAL_DELETED``/``RECOVERY_REQUIRED``) is
    HTTP 200; only preconditions (missing record, stale revision or binding,
    insufficient capability) raise.
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
        else "外部管理结果待确认，请人工恢复；不会自动重试"
    )
    return {
        "action": action,
        "management_status": management_status or "RECOVERY_REQUIRED",
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


@class_route(api_blueprint, "/api/v1/tracking/items/<path:tracking_id>/refresh", methods=["POST"])
class TrackingItemRefreshView(PostView):
    request_validator_model = TrackingRefreshRssPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, TrackingRefreshRssPayload)
        return _run_management_route(self.request_validator_model, "REFRESH_RSS")


__all__ = [
    "TrackingItemCheckView",
    "TrackingItemDetailView",
    "TrackingItemListView",
    "TrackingItemModifyView",
    "TrackingItemRefreshView",
    "TrackingItemRecoverView",
    "TrackingItemResubmitView",
    "TrackingItemRetryView",
    "TrackingItemRevalidateView",
    "TrackingItemSubmitView",
    "TrackingItemSetEnabledView",
    "TrackingSyncView",
]
