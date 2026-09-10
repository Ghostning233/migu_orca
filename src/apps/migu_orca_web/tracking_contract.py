"""Compatibility exports for the Web tracking-management contract."""

from shared.management_contract import (
    MANAGEMENT_ACTION_CONTRACTS,
    MANAGEMENT_ACTIONS,
    MANAGEMENT_ERROR_MESSAGES,
    MANAGEMENT_ERROR_SEMANTICS,
    MANAGEMENT_SCOPES,
    ManagementActionContract,
    management_error_names_for_status,
)

__all__ = [
    "MANAGEMENT_ACTION_CONTRACTS",
    "MANAGEMENT_ACTIONS",
    "MANAGEMENT_ERROR_MESSAGES",
    "MANAGEMENT_ERROR_SEMANTICS",
    "MANAGEMENT_SCOPES",
    "ManagementActionContract",
    "management_error_names_for_status",
]
