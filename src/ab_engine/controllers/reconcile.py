"""Pure reconciliation of local tracking projections with AB read results.

This module intentionally has no storage or web dependencies.  RSS URLs are
accepted only as request-scoped evidence and are never copied into a decision,
mapping, warning, or representation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from ab_engine.models.management import ExternalSubscription
from tracking_engine.models.tracking import (
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_DISABLED,
    TRACKING_STATUS_EXTERNAL_DELETED,
    TRACKING_STATUS_EXTERNAL_ONLY,
    TRACKING_STATUS_REVALIDATING,
    TRACKING_STATUS_SUBMITTING,
)

RECONCILE_WARNING_AMBIGUOUS = "AMBIGUOUS_EXTERNAL_MATCH"
RECONCILE_WARNING_CONFLICT = "EXTERNAL_MATCH_CONFLICT"
RECONCILE_WARNING_EXTERNAL_DELETED = "EXTERNAL_SUBSCRIPTION_MISSING"

_IN_PROGRESS = frozenset({TRACKING_STATUS_SUBMITTING, TRACKING_STATUS_REVALIDATING})


@dataclass(frozen=True, repr=False)
class LocalTrackingEvidence:
    """The safe local fields needed for matching one tracking record."""

    tracking_id: str
    status: str
    origin: str | None = None
    plan_summary: dict[str, Any] = field(default_factory=dict)
    external_mapping: dict[str, Any] | None = None
    # This is deliberately excluded from repr and every output decision.
    rss_urls: tuple[str, ...] = field(default_factory=tuple, repr=False)


@dataclass(frozen=True)
class ReconcileDecision:
    """Safe result for one external subscription."""

    external_id: str
    tracking_id: str | None
    status: str
    match_reason: str
    warning: str | None = None
    external_deleted: bool = False
    subscription_id: str | None = None
    rss_ids: tuple[str, ...] = ()

    def safe_mapping(self, *, connection_ref: str | UUID | None = None) -> dict[str, Any]:
        """Return a v1 legacy or v2 connection-bound safe mapping."""
        if connection_ref is not None:
            if isinstance(connection_ref, UUID):
                connection_ref = str(connection_ref)
            elif not isinstance(connection_ref, str):
                raise ValueError("connection_ref must be a canonical UUID")
            try:
                parsed_ref = UUID(connection_ref)
            except (ValueError, AttributeError):
                raise ValueError("connection_ref must be a canonical UUID") from None
            if str(parsed_ref) != connection_ref:
                raise ValueError("connection_ref must be a canonical UUID")
        mapping = {
            "schema_version": 2 if connection_ref is not None else 1,
            "adapter": "legacy_3_1",
            "subscription_id": self.subscription_id,
            "rss_ids": list(self.rss_ids),
            "match_reason": self.match_reason,
            "external_deleted": self.external_deleted,
            "enabled": not self.external_deleted,
            "missing_sync_count": 0,
            "last_verified_at": None,
        }
        if connection_ref is not None:
            mapping["connection_ref"] = connection_ref
        return mapping


def normalize_match_text(value: str | None) -> str | None:
    """Normalize only harmless presentation differences for exact matching."""
    if value is None:
        return None
    return " ".join(value.split()).casefold()


def reconcile_subscription(
    external: ExternalSubscription,
    locals: tuple[LocalTrackingEvidence, ...] | list[LocalTrackingEvidence],
) -> ReconcileDecision:
    """Classify one external subscription using deterministic strict evidence."""
    # External-only records are projections of this same snapshot, not local
    # evidence.  Including them would turn a stable EXTERNAL_ONLY result into
    # an EXACT_FIELDS self-match on the next sync.
    candidates = tuple(local for local in locals if local.origin != "EXTERNAL_SYNC")
    external_id_matches = tuple(
        local
        for local in candidates
        if local.origin != "EXTERNAL_SYNC" and _mapped_subscription_id(local) == external.external_id
    )
    if len(external_id_matches) == 1:
        local = external_id_matches[0]
        return _decision(external, local, "EXTERNAL_ID")
    if len(external_id_matches) > 1:
        return _ambiguous(external, RECONCILE_WARNING_AMBIGUOUS)

    field_matches = tuple(local for local in candidates if _fields_match(local, external))
    if len(field_matches) == 1:
        return _decision(external, field_matches[0], "EXACT_FIELDS")
    if len(field_matches) > 1:
        return _ambiguous(external, RECONCILE_WARNING_AMBIGUOUS)
    return ReconcileDecision(
        external_id=external.external_id,
        tracking_id=None,
        status=TRACKING_STATUS_EXTERNAL_DELETED if external.deleted else TRACKING_STATUS_EXTERNAL_ONLY,
        match_reason="EXTERNAL_ONLY",
        external_deleted=external.deleted,
        subscription_id=external.external_id,
        rss_ids=_rss_ids(external),
    )


def reconcile_subscriptions(
    externals: tuple[ExternalSubscription, ...] | list[ExternalSubscription],
    locals: tuple[LocalTrackingEvidence, ...] | list[LocalTrackingEvidence],
) -> tuple[ReconcileDecision, ...]:
    """Reconcile a snapshot in input order; repeated input is deterministic."""
    return tuple(reconcile_subscription(item, locals) for item in externals)


def classify_missing_mapping(
    local: LocalTrackingEvidence,
    *,
    complete_subscription_list: bool,
) -> ReconcileDecision | None:
    """Classify a mapped local record absent from a verified complete list."""
    mapping = local.external_mapping or {}
    external_id = mapping.get("subscription_id")
    if not complete_subscription_list or not isinstance(external_id, str) or not external_id:
        return None
    if local.status in _IN_PROGRESS:
        return ReconcileDecision(
            external_id=external_id, tracking_id=local.tracking_id, status=local.status,
            match_reason="EXTERNAL_ID", warning=None, subscription_id=external_id,
        )
    return ReconcileDecision(
        external_id=external_id,
        tracking_id=local.tracking_id,
        status=TRACKING_STATUS_EXTERNAL_DELETED,
        match_reason="EXTERNAL_ID",
        warning=RECONCILE_WARNING_EXTERNAL_DELETED,
        external_deleted=True,
        subscription_id=external_id,
    )


def _fields_match(local: LocalTrackingEvidence, external: ExternalSubscription) -> bool:
    summary = local.plan_summary
    if normalize_match_text(summary.get("title")) != normalize_match_text(external.title):
        return False
    if summary.get("season") != external.season:
        return False
    if normalize_match_text(summary.get("subtitle_group")) != normalize_match_text(external.subtitle_group):
        return False
    local_rss = tuple(local.rss_urls)
    external_rss = tuple(external.rss_urls)
    return not local_rss or not external_rss or set(local_rss) == set(external_rss)


def _mapped_subscription_id(local: LocalTrackingEvidence) -> str | None:
    mapping = local.external_mapping
    value = mapping.get("subscription_id") if isinstance(mapping, dict) else None
    return value if isinstance(value, str) and value else None


def _decision(external: ExternalSubscription, local: LocalTrackingEvidence, reason: str) -> ReconcileDecision:
    status = local.status if local.status in _IN_PROGRESS else (
        TRACKING_STATUS_DISABLED if external.deleted else (
            TRACKING_STATUS_EXTERNAL_ONLY if local.status == TRACKING_STATUS_EXTERNAL_ONLY else TRACKING_STATUS_ACTIVE
        )
    )
    return ReconcileDecision(
        external_id=external.external_id,
        tracking_id=local.tracking_id,
        status=status,
        match_reason=reason,
        external_deleted=external.deleted,
        subscription_id=external.external_id,
        rss_ids=_rss_ids(external),
    )


def _ambiguous(external: ExternalSubscription, warning: str) -> ReconcileDecision:
    return ReconcileDecision(
        external_id=external.external_id, tracking_id=None,
        status=TRACKING_STATUS_EXTERNAL_DELETED if external.deleted else TRACKING_STATUS_EXTERNAL_ONLY,
        match_reason="EXTERNAL_ONLY", warning=warning,
        external_deleted=external.deleted, subscription_id=external.external_id,
        rss_ids=_rss_ids(external),
    )


def _rss_ids(external: ExternalSubscription) -> tuple[str, ...]:
    return tuple(dict.fromkeys(external.rss_ids))


__all__ = [
    "LocalTrackingEvidence", "ReconcileDecision", "RECONCILE_WARNING_AMBIGUOUS",
    "RECONCILE_WARNING_CONFLICT", "RECONCILE_WARNING_EXTERNAL_DELETED",
    "classify_missing_mapping", "normalize_match_text", "reconcile_subscription",
    "reconcile_subscriptions",
]
