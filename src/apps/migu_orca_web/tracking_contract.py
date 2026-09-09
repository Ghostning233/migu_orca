"""Frozen public tracking-management vocabulary and action semantics."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

MANAGEMENT_ACTIONS: Final = ("MODIFY", "SET_ENABLED", "DELETE_EXTERNAL", "REFRESH_RSS")
MANAGEMENT_SCOPES: Final = ("SUBSCRIPTION", "ASSOCIATED_RSS")
MANAGEMENT_ERROR_SEMANTICS: Final = {
    "tracking_management_confirmation_required": (400, "validation"),
    "tracking_management_patch_invalid": (400, "validation"),
    "tracking_management_capability_unknown": (409, "capability"),
    "tracking_revision_conflict": (409, "conflict"),
    "tracking_idempotency_conflict": (409, "conflict"),
    "tracking_management_state_conflict": (409, "conflict"),
    "tracking_management_external_failure": (200, "definite_failure"),
    "tracking_management_outcome_unknown": (200, "unknown"),
}

@dataclass(frozen=True)
class ManagementActionContract:
    action: str
    endpoint_suffix: str
    scopes: tuple[str, ...]
    requires_confirmation: bool = True
    requires_capability_probe: bool = True
    read_before_write: bool = True

MANAGEMENT_ACTION_CONTRACTS: Final = {
    item.action: item for item in (
        ManagementActionContract("MODIFY", "modify", MANAGEMENT_SCOPES),
        ManagementActionContract("SET_ENABLED", "set-enabled", MANAGEMENT_SCOPES),
        ManagementActionContract("DELETE_EXTERNAL", "delete-external", MANAGEMENT_SCOPES),
        ManagementActionContract("REFRESH_RSS", "refresh", ("ASSOCIATED_RSS",)),
    )
}
