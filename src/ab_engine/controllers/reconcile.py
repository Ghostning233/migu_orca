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
RECONCILE_WARNING_UNPROVEN = "EXTERNAL_MATCH_UNPROVEN"

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
    # Local records involved in an ambiguous/conflicting snapshot.  This is
    # request-local control data and is never serialized into safe output.
    protected_tracking_ids: tuple[str, ...] = ()

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
    *,
    connection_ref: str | UUID | None = None,
) -> ReconcileDecision:
    """Classify one external subscription using deterministic strict evidence."""
    # External-only records are projections of this same snapshot, not local
    # evidence.  Including them would turn a stable EXTERNAL_ONLY result into
    # an EXACT_FIELDS self-match on the next sync.
    candidates = tuple(local for local in locals if local.origin != "EXTERNAL_SYNC")
    current_ref = str(connection_ref) if isinstance(connection_ref, UUID) else connection_ref
    external_id_matches = tuple(
        local
        for local in candidates
        if local.origin != "EXTERNAL_SYNC"
        and _mapped_subscription_id(local) == external.external_id
        and (connection_ref is None or _mapping_ref(local) == current_ref)
    )
    if len(external_id_matches) == 1:
        local = external_id_matches[0]
        return _decision(external, local, "EXTERNAL_ID")
    if len(external_id_matches) > 1:
        return _ambiguous(external, RECONCILE_WARNING_AMBIGUOUS,
                          protected_tracking_ids=(
                              tuple(item.tracking_id for item in external_id_matches)
                              if connection_ref is not None else ()
                          ))

    field_matches = tuple(
        local for local in candidates
        if _fields_match(
            local, external,
            require_rss=connection_ref is not None,
        )
    )
    if len(field_matches) == 1:
        return _decision(external, field_matches[0], "EXACT_FIELDS")
    if len(field_matches) > 1:
        return _ambiguous(external, RECONCILE_WARNING_AMBIGUOUS,
                          protected_tracking_ids=(
                              tuple(item.tracking_id for item in field_matches)
                              if connection_ref is not None else ()
                          ))
    return ReconcileDecision(
        external_id=external.external_id,
        tracking_id=None,
        status=TRACKING_STATUS_EXTERNAL_DELETED if external.deleted else TRACKING_STATUS_EXTERNAL_ONLY,
        match_reason="EXTERNAL_ONLY",
        external_deleted=external.deleted,
        subscription_id=external.external_id,
        rss_ids=_rss_ids(external),
        warning=RECONCILE_WARNING_UNPROVEN if connection_ref is not None and candidates else None,
    )


def reconcile_subscriptions(
    externals: tuple[ExternalSubscription, ...] | list[ExternalSubscription],
    locals: tuple[LocalTrackingEvidence, ...] | list[LocalTrackingEvidence],
    *,
    connection_ref: str | UUID | None = None,
) -> tuple[ReconcileDecision, ...]:
    """Reconcile a snapshot in input order; repeated input is deterministic."""
    decisions = tuple(
        reconcile_subscription(item, locals, connection_ref=connection_ref)
        for item in externals
    )
    original_decisions = decisions
    candidates = tuple(local for local in locals if local.origin != "EXTERNAL_SYNC")
    external_id_counts: dict[str, int] = {}
    for item in externals:
        external_id_counts[item.external_id] = external_id_counts.get(item.external_id, 0) + 1
    if any(count > 1 for count in external_id_counts.values()):
        decisions = tuple(
            ReconcileDecision(
                external_id=decision.external_id, tracking_id=None,
                status=(TRACKING_STATUS_EXTERNAL_DELETED if decision.external_deleted
                        else TRACKING_STATUS_EXTERNAL_ONLY), match_reason="EXTERNAL_ONLY",
                warning=RECONCILE_WARNING_CONFLICT,
                external_deleted=decision.external_deleted,
                subscription_id=decision.subscription_id, rss_ids=decision.rss_ids,
                protected_tracking_ids=tuple(dict.fromkeys(
                    [
                        item.tracking_id for item in candidates
                        if _mapped_subscription_id(item) == decision.external_id
                        and (connection_ref is None or _mapping_ref(item) == str(connection_ref))
                    ]
                    + [
                        original.tracking_id for original in original_decisions
                        if original.external_id == decision.external_id
                        and original.tracking_id is not None
                    ]
                )),
            ) if external_id_counts.get(decision.external_id, 0) > 1 else decision
            for decision in decisions
        )
    if connection_ref is not None:
        counts: dict[str, int] = {}
        for decision in decisions:
            if decision.tracking_id is not None:
                counts[decision.tracking_id] = counts.get(decision.tracking_id, 0) + 1
        result: list[ReconcileDecision] = []
        for decision in decisions:
            if decision.tracking_id is not None and counts.get(decision.tracking_id, 0) > 1:
                affected = (decision.tracking_id,)
                result.append(ReconcileDecision(
                    external_id=decision.external_id, tracking_id=None,
                    status=(TRACKING_STATUS_EXTERNAL_DELETED if decision.external_deleted
                            else TRACKING_STATUS_EXTERNAL_ONLY), match_reason="EXTERNAL_ONLY",
                    warning=RECONCILE_WARNING_UNPROVEN,
                    external_deleted=decision.external_deleted,
                    subscription_id=decision.subscription_id, rss_ids=decision.rss_ids,
                    protected_tracking_ids=affected,
                ))
            else:
                result.append(decision)
        return tuple(result)
    return decisions


def classify_missing_mapping(
    local: LocalTrackingEvidence,
    *,
    complete_subscription_list: bool,
    connection_ref: str | UUID | None = None,
) -> ReconcileDecision | None:
    """Classify a mapped local record absent from a verified complete list."""
    mapping = local.external_mapping or {}
    external_id = mapping.get("subscription_id")
    if not complete_subscription_list or not isinstance(external_id, str) or not external_id:
        return None
    if connection_ref is not None and _mapping_ref(local) != str(connection_ref):
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


def _fields_match(
    local: LocalTrackingEvidence,
    external: ExternalSubscription,
    *,
    require_rss: bool = False,
) -> bool:
    summary = local.plan_summary
    if require_rss and (
        not normalize_match_text(summary.get("title"))
        or not isinstance(summary.get("season"), int)
        or isinstance(summary.get("season"), bool)
        or summary.get("season") < 1
        or not normalize_match_text(summary.get("subtitle_group"))
        or not normalize_match_text(external.title)
        or not isinstance(external.season, int)
        or isinstance(external.season, bool)
        or external.season < 1
        or not normalize_match_text(external.subtitle_group)
    ):
        return False
    if normalize_match_text(summary.get("title")) != normalize_match_text(external.title):
        return False
    if summary.get("season") != external.season:
        return False
    if normalize_match_text(summary.get("subtitle_group")) != normalize_match_text(external.subtitle_group):
        return False
    local_rss = tuple(local.rss_urls)
    external_rss = tuple(external.rss_urls)
    return bool(local_rss and external_rss and set(local_rss) == set(external_rss)) if require_rss else (
        not local_rss or not external_rss or set(local_rss) == set(external_rss)
    )


def _mapped_subscription_id(local: LocalTrackingEvidence) -> str | None:
    mapping = local.external_mapping
    value = mapping.get("subscription_id") if isinstance(mapping, dict) else None
    return value if isinstance(value, str) and value else None


def _mapping_ref(local: LocalTrackingEvidence) -> str | None:
    mapping = local.external_mapping
    value = mapping.get("connection_ref") if isinstance(mapping, dict) else None
    return value if isinstance(value, str) else None


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


def _ambiguous(
    external: ExternalSubscription,
    warning: str,
    *,
    protected_tracking_ids: tuple[str, ...] = (),
) -> ReconcileDecision:
    return ReconcileDecision(
        external_id=external.external_id, tracking_id=None,
        status=TRACKING_STATUS_EXTERNAL_DELETED if external.deleted else TRACKING_STATUS_EXTERNAL_ONLY,
        match_reason="EXTERNAL_ONLY", warning=warning,
        external_deleted=external.deleted, subscription_id=external.external_id,
        rss_ids=_rss_ids(external),
        protected_tracking_ids=protected_tracking_ids,
    )


def _rss_ids(external: ExternalSubscription) -> tuple[str, ...]:
    return tuple(dict.fromkeys(external.rss_ids))


__all__ = [
    "LocalTrackingEvidence", "ReconcileDecision", "RECONCILE_WARNING_AMBIGUOUS",
    "RECONCILE_WARNING_CONFLICT", "RECONCILE_WARNING_EXTERNAL_DELETED",
    "RECONCILE_WARNING_UNPROVEN",
    "classify_missing_mapping", "normalize_match_text", "reconcile_subscription",
    "reconcile_subscriptions",
]
