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

from apps.migu_orca_web.blueprints import api_blueprint
from apps.migu_orca_web.schemas import (
    TrackingDetailQuery,
    TrackingListQuery,
    TrackingRevalidatePayload,
)
from apps.migu_orca_web.services import _storage_dir
from apps.migu_orca_web.tracking_read_service import (
    build_tracking_detail,
    list_tracking_items,
)
from apps.migu_orca_web.tracking_revalidate_service import run_tracking_revalidate
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


__all__ = [
    "TrackingItemDetailView",
    "TrackingItemListView",
    "TrackingItemRevalidateView",
]
