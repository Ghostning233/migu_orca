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

#: Publicly advertised management actions per status.  The API projection and
#: the normal management writes both read this table.  Issue #228 (T5a) retired
#: the standalone "删除 Auto Bangumi 外部对象" entry, so ``DELETE_EXTERNAL`` is
#: advertised for no status at all; it survives only in
#: :data:`_INTERNAL_ONLY_ACTIONS` for the composite plan-delete leg.
_ACTIONS_BY_STATUS: dict[str, frozenset[str]] = {
    TRACKING_STATUS_ACTIVE: frozenset({"MODIFY", "SET_ENABLED", "REFRESH_RSS"}),
    # Issue #224 A4 / ADR-0005: ``EXTERNAL_ONLY`` is retired read-only history.
    # MiGuOrca never adopted that external object, so it offers no management
    # action — this table is the one policy the read projection and the write
    # path share, which keeps the UI and the API from disagreeing.
    # Disabled subscriptions may only be re-enabled.
    TRACKING_STATUS_DISABLED: frozenset({"SET_ENABLED"}),
}

#: Internal-only capability that is never advertised, but that the plan-delete
#: chain still needs.  Issue #218 exception (a) lets "删除追番方案 + 同时删除受控
#: 外部订阅" remove the mapped Auto Bangumi object for any mapped status; #228
#: retires only the *public* entry, so this leg keeps exactly
#: ``DELETE_EXTERNAL`` and nothing else.  The public projection, the public
#: management endpoints and the other actions remain refused, and A4 must not
#: turn the retired state into an orphan this product can never clean up.
_INTERNAL_ONLY_ACTIONS: dict[str, frozenset[str]] = {
    TRACKING_STATUS_ACTIVE: frozenset({"DELETE_EXTERNAL"}),
    TRACKING_STATUS_DISABLED: frozenset({"DELETE_EXTERNAL"}),
    TRACKING_STATUS_EXTERNAL_ONLY: frozenset({"DELETE_EXTERNAL"}),
}


def management_actions_for_status(
    status: str,
    *,
    include_internal: bool = False,
) -> frozenset[str]:
    """Return the management actions permitted for ``status``.

    ``include_internal`` is only for the internal plan-delete external leg; it
    adds :data:`_INTERNAL_ONLY_ACTIONS` and never widens the public projection
    (the serializer calls this without the flag).
    """
    actions = _ACTIONS_BY_STATUS.get(status, frozenset())
    if include_internal:
        return actions | _INTERNAL_ONLY_ACTIONS.get(status, frozenset())
    return actions


def management_action_allowed(
    status: str,
    action: str,
    *,
    enabled: bool | None = None,
    include_internal: bool = False,
) -> bool:
    """Return whether the local state permits this action and direction.

    The action projection intentionally omits a direction because it is shown
    before a request exists.  The write coordinator supplies ``enabled`` and
    therefore enforces the stricter DISABLED re-enable-only rule.
    """
    if action not in management_actions_for_status(status, include_internal=include_internal):
        return False
    if status == TRACKING_STATUS_DISABLED and action == "SET_ENABLED" and enabled is not None:
        return enabled is True
    return True


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
