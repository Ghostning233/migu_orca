from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.migu_orca_web.api_contract import TrackingAvailableActionDTO, TrackingManagementResultDTO
from apps.migu_orca_web.schemas import TrackingModifyPayload, TrackingRefreshRssPayload, TrackingSetEnabledPayload
from apps.migu_orca_web.tracking_contract import MANAGEMENT_ACTION_CONTRACTS, MANAGEMENT_ERROR_SEMANTICS


def test_management_contract_freezes_actions_and_guards() -> None:
    assert set(MANAGEMENT_ACTION_CONTRACTS) == {"MODIFY", "SET_ENABLED", "DELETE_EXTERNAL", "REFRESH_RSS"}
    assert MANAGEMENT_ACTION_CONTRACTS["REFRESH_RSS"].scopes == ("ASSOCIATED_RSS",)
    assert all(item.requires_confirmation and item.requires_capability_probe and item.read_before_write
               for item in MANAGEMENT_ACTION_CONTRACTS.values())


def test_management_error_semantics_freeze_boundaries() -> None:
    assert MANAGEMENT_ERROR_SEMANTICS["tracking_management_confirmation_required"] == (400, "validation")
    assert MANAGEMENT_ERROR_SEMANTICS["tracking_revision_conflict"] == (409, "conflict")
    assert MANAGEMENT_ERROR_SEMANTICS["tracking_management_outcome_unknown"] == (200, "unknown")


def test_management_payloads_are_strict_and_revision_is_not_coerced() -> None:
    base = {
        "tracking_id": "trk_1", "target_scope": "SUBSCRIPTION", "expected_revision": 1,
        "idempotency_key": "key-1", "confirm": True,
        "ab_config": {"auth_mode": "password", "base_url": "https://ab.invalid",
                      "username": "u", "password": "p", "fallback_enabled": False},
    }
    assert TrackingSetEnabledPayload.model_validate({**base, "enabled": False})
    with pytest.raises(ValidationError):
        TrackingSetEnabledPayload.model_validate({**base, "expected_revision": True, "enabled": False})
    with pytest.raises(ValidationError):
        TrackingModifyPayload.model_validate({**base, "patch": {"title": "x"}, "unexpected": 1})
    with pytest.raises(ValidationError):
        TrackingRefreshRssPayload.model_validate({**base, "target_scope": "SUBSCRIPTION"})


def test_public_action_and_management_status_are_enumerated() -> None:
    assert TrackingAvailableActionDTO(code="DELETE_EXTERNAL", label="删除外部订阅", style="DANGER",
                                      requires_confirmation=True).code == "DELETE_EXTERNAL"
    with pytest.raises(ValidationError):
        TrackingAvailableActionDTO(code="NOT_AN_ACTION", label="x", style="PRIMARY", requires_confirmation=True)
    with pytest.raises(ValidationError):
        TrackingManagementResultDTO(action="MODIFY", management_status="NOT_A_STATUS",
                                    needs_manual=False, safe_message="x",
                                    tracking={"tracking_id": "trk", "status": "ACTIVE",
                                              "status_label": "正在追番", "status_group": "ACTIVE", "revision": 1})
