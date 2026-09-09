"""Frozen Stage 31 management-action state matrix.

This module is intentionally pure so the coordinator and safe API projection
use the exact same policy without depending on one another.
"""
from __future__ import annotations

from collections.abc import Collection

from ab_engine.models.management import AutoBangumiCapabilities
from tracking_engine.models.tracking import (
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_DISABLED,
    TRACKING_STATUS_EXTERNAL_ONLY,
)

MANAGEMENT_ACTIONS = frozenset({"MODIFY", "SET_ENABLED", "DELETE_EXTERNAL", "REFRESH_RSS"})

# Management writes are deliberately narrower than submit/read capability.
# Keep this table as the one server-side policy used by both the write and
# recovery paths; a public capability projection is never sufficient by itself.
_CAPABILITY_FIELDS = {
    ("MODIFY", "SUBSCRIPTION"): "subscription_modify",
    ("MODIFY", "ASSOCIATED_RSS"): "rss_modify",
    ("DELETE_EXTERNAL", "SUBSCRIPTION"): "subscription_delete",
    ("DELETE_EXTERNAL", "ASSOCIATED_RSS"): "rss_delete",
    ("REFRESH_RSS", "ASSOCIATED_RSS"): "rss_refresh",
}

_ACTIONS_BY_STATUS: dict[str, frozenset[str]] = {
    TRACKING_STATUS_ACTIVE: MANAGEMENT_ACTIONS,
    # A synced external-only record has a durable mapping and can use the same
    # bounded management endpoints as an active local record.
    TRACKING_STATUS_EXTERNAL_ONLY: MANAGEMENT_ACTIONS,
    # Disabled subscriptions may only be re-enabled or permanently removed.
    TRACKING_STATUS_DISABLED: frozenset({"SET_ENABLED", "DELETE_EXTERNAL"}),
}


def management_actions_for_status(status: str) -> frozenset[str]:
    """Return the exact Stage 31 management actions permitted for ``status``."""
    return _ACTIONS_BY_STATUS.get(status, frozenset())


def management_action_allowed(status: str, action: str) -> bool:
    return action in management_actions_for_status(status)


def is_management_action(action: str, actions: Collection[str] = MANAGEMENT_ACTIONS) -> bool:
    """Small validation helper that keeps caller input bounded."""
    return action in actions


def management_capability_field(action: str, scope: str, enabled: bool | None = None) -> str | None:
    """Return the exact capability required by one action direction."""
    if scope not in {"SUBSCRIPTION", "ASSOCIATED_RSS"}:
        return None
    if action == "SET_ENABLED":
        if type(enabled) is not bool:
            return None
        prefix = "subscription" if scope == "SUBSCRIPTION" else "rss"
        return f"{prefix}_{'enable' if enabled else 'disable'}"
    return _CAPABILITY_FIELDS.get((action, scope))


def management_capability_allowed(
    capabilities: AutoBangumiCapabilities,
    action: str,
    scope: str,
    *,
    enabled: bool | None = None,
) -> bool:
    """Fail closed unless the proven adapter/version supports this action."""
    field = management_capability_field(action, scope, enabled)
    return (
        management_baseline_verified(capabilities)
        and field is not None
        and getattr(capabilities, field, "UNKNOWN") == "SUPPORTED"
    )


def management_baseline_verified(capabilities: AutoBangumiCapabilities) -> bool:
    """Return whether the exact write/readback adapter baseline was proven."""
    return (
        capabilities.probe_status == "VERIFIED"
        and capabilities.version == "3.1.18"
        and capabilities.adapter == "legacy_3_1"
    )


__all__ = [
    "MANAGEMENT_ACTIONS",
    "management_action_allowed",
    "management_actions_for_status",
    "management_capability_allowed",
    "management_capability_field",
    "management_baseline_verified",
]
