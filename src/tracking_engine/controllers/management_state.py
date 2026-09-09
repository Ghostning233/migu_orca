"""Frozen Stage 31 management-action state matrix.

This module is intentionally pure so the coordinator and safe API projection
use the exact same policy without depending on one another.
"""
from __future__ import annotations

from collections.abc import Collection

from tracking_engine.models.tracking import (
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_DISABLED,
    TRACKING_STATUS_EXTERNAL_ONLY,
)

MANAGEMENT_ACTIONS = frozenset({"MODIFY", "SET_ENABLED", "DELETE_EXTERNAL", "REFRESH_RSS"})

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


__all__ = ["MANAGEMENT_ACTIONS", "management_action_allowed", "management_actions_for_status"]
