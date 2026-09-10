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

MANAGEMENT_ERROR_MESSAGES: Final = {
    "tracking_management_confirmation_required": "管理操作必须显式确认",
    "tracking_management_patch_invalid": "管理操作参数无效",
    "tracking_management_capability_unknown": "当前 Auto Bangumi 管理能力未验证",
    "tracking_revision_conflict": "追番记录版本已变化，请刷新后重试",
    "tracking_idempotency_conflict": "同一幂等键已绑定不同的管理操作",
    "tracking_management_state_conflict": "已有管理操作正在执行，请先恢复",
}


def management_error_names_for_status(status: int) -> tuple[str, ...]:
    """Return registered management errors for one public HTTP status."""
    return tuple(
        name for name, (error_status, _semantic) in MANAGEMENT_ERROR_SEMANTICS.items()
        if error_status == status and name in MANAGEMENT_ERROR_MESSAGES
    )

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
