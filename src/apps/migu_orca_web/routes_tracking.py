from __future__ import annotations

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

from ab_engine.controllers.ab_config import build_ab_config
from apps.migu_orca_web.blueprints import api_blueprint
from apps.migu_orca_web.schemas import (
    TrackingDetailQuery,
    TrackingListQuery,
    TrackingRecoverPayload,
    TrackingRevalidatePayload,
    TrackingSubmitPayload,
)
from apps.migu_orca_web.services import _storage_dir
from apps.migu_orca_web.tracking_read_service import (
    build_tracking_detail,
    list_tracking_items,
)
from apps.migu_orca_web.tracking_recovery_service import run_tracking_recover
from apps.migu_orca_web.tracking_revalidate_service import run_tracking_revalidate
from apps.migu_orca_web.tracking_submission_service import (
    run_tracking_retry,
    run_tracking_submit,
)
from extensions.flask_api import class_route
from extensions.flask_api.views import GetView, PostView
from storage_engine.controllers.storage_config import load_storage_config


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
    profile) — never ``ab_config`` or connection/capability settings.  A
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

    ``confirm`` must be strictly true and ``ab_config`` lives only in this
    request's memory.  The service re-reads the latest local Request and runs
    the complete local revalidation before any Auto Bangumi call; a persisted
    business outcome (``NEEDS_RECONFIRM``/``SUBMIT_FAILED``/
    ``VERIFYING_EXTERNAL``/``RECOVERY_REQUIRED``/``ACTIVE``) is HTTP 200.  Only
    preconditions (missing record, stale revision, non-submittable state,
    idempotency conflict, in-flight operation) raise.
    """

    request_validator_model = TrackingSubmitPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, TrackingSubmitPayload)
        payload = self.request_validator_model
        config = load_storage_config(_storage_dir(payload.storage_dir))
        ab_config = build_ab_config(payload.ab_config.model_dump(exclude_none=True))
        return run_tracking_submit(
            config,
            tracking_id=payload.tracking_id,
            expected_revision=payload.expected_revision,
            idempotency_key=payload.idempotency_key,
            confirm=payload.confirm,
            ab_config=ab_config,
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
    request-scoped ``ab_config``, an opaque idempotency key); the unified
    service re-reads the latest Request and revalidates before creating a fresh
    operation and calling Auto Bangumi once.  A persisted business outcome is
    HTTP 200; only preconditions (missing record, stale revision,
    non-retryable state, idempotency conflict, in-flight operation) raise.
    """

    request_validator_model = TrackingSubmitPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, TrackingSubmitPayload)
        payload = self.request_validator_model
        config = load_storage_config(_storage_dir(payload.storage_dir))
        ab_config = build_ab_config(payload.ab_config.model_dump(exclude_none=True))
        return run_tracking_retry(
            config,
            tracking_id=payload.tracking_id,
            expected_revision=payload.expected_revision,
            idempotency_key=payload.idempotency_key,
            confirm=payload.confirm,
            ab_config=ab_config,
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
        config = load_storage_config(_storage_dir(payload.storage_dir))
        return run_tracking_recover(
            config,
            tracking_id=payload.tracking_id,
            expected_revision=payload.expected_revision,
            action=payload.action,
            confirm=payload.confirm,
        )


__all__ = [
    "TrackingItemDetailView",
    "TrackingItemListView",
    "TrackingItemRecoverView",
    "TrackingItemRetryView",
    "TrackingItemRevalidateView",
    "TrackingItemSubmitView",
]
