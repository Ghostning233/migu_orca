from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.migu_orca_web.api_contract import TrackingAvailableActionDTO, TrackingManagementResultDTO
from apps.migu_orca_web.openapi_gen import generate_openapi
from apps.migu_orca_web.schemas import TrackingModifyPayload, TrackingRefreshRssPayload, TrackingSetEnabledPayload
from apps.migu_orca_web.tracking_contract import MANAGEMENT_ACTION_CONTRACTS, MANAGEMENT_ERROR_SEMANTICS
from extensions.flask_api.api import _error_http_status


def test_management_contract_freezes_actions_and_guards() -> None:
    assert set(MANAGEMENT_ACTION_CONTRACTS) == {"MODIFY", "SET_ENABLED", "DELETE_EXTERNAL", "REFRESH_RSS"}
    assert MANAGEMENT_ACTION_CONTRACTS["REFRESH_RSS"].scopes == ("ASSOCIATED_RSS",)
    assert all(item.requires_confirmation and item.requires_capability_probe and item.read_before_write
               for item in MANAGEMENT_ACTION_CONTRACTS.values())


def test_management_error_semantics_freeze_boundaries() -> None:
    assert MANAGEMENT_ERROR_SEMANTICS["tracking_management_confirmation_required"] == (400, "validation")
    assert MANAGEMENT_ERROR_SEMANTICS["tracking_revision_conflict"] == (409, "conflict")
    assert MANAGEMENT_ERROR_SEMANTICS["tracking_management_outcome_unknown"] == (200, "unknown")
    assert _error_http_status("tracking_management_capability_unknown") == 409
    assert MANAGEMENT_ERROR_SEMANTICS["tracking_management_capability_unknown"] == (409, "capability")
    documented = {
        error_type
        for path in generate_openapi()["paths"].values()
        for operation in path.values()
        if isinstance(operation, dict)
        for error_type in MANAGEMENT_ERROR_SEMANTICS
        if error_type in operation.get("responses", {}).get("409", {}).get("description", "")
    }
    assert "tracking_management_capability_unknown" in documented


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


def test_modify_patch_is_strictly_discriminated_by_scope() -> None:
    base = {
        "expected_revision": 1, "idempotency_key": "key-1", "confirm": True,
        "ab_config": {"auth_mode": "password", "base_url": "https://ab.invalid",
                      "username": "u", "password": "p", "fallback_enabled": False},
    }
    subscription = TrackingModifyPayload.model_validate({
        **base, "tracking_id": "trk_1", "target_scope": "SUBSCRIPTION",
        "patch": {"season": 2, "filter_rule": {"must_contain": "1080p"}},
    })
    assert subscription.patch.model_dump(exclude_unset=True) == {
        "season": 2, "filter_rule": {"must_contain": "1080p"}
    }
    rss = TrackingModifyPayload.model_validate({
        **base, "tracking_id": "trk_1", "target_scope": "ASSOCIATED_RSS",
        "patch": {"aggregate": True},
    })
    assert rss.patch.model_dump(exclude_unset=True) == {"aggregate": True}
    with pytest.raises(ValidationError):
        TrackingModifyPayload.model_validate({
            **base, "tracking_id": "trk_1", "target_scope": "SUBSCRIPTION",
            "patch": {"name": "rss"},
        })
    with pytest.raises(ValidationError):
        TrackingModifyPayload.model_validate({
            **base, "tracking_id": "trk_1", "target_scope": "ASSOCIATED_RSS",
            "patch": {"title": "show"},
        })
    with pytest.raises(ValidationError):
        TrackingModifyPayload.model_validate({
            **base, "tracking_id": "trk_1", "target_scope": "SUBSCRIPTION",
            "patch": {"title": "show", "rss_url": "https://ab.invalid/rss"},
        })


def test_management_action_scopes_are_server_computed_per_action_without_mapping_values() -> None:
    from apps.migu_orca_web.tracking_serializers import tracking_available_actions

    actions = tracking_available_actions(
        "ACTIVE", {"subscription_id": "opaque-sub", "rss_ids": ["opaque-rss"]}
    )
    by_code = {item["code"]: item["target_scopes"] for item in actions}
    assert by_code["MODIFY"] == ["SUBSCRIPTION", "ASSOCIATED_RSS"]
    assert by_code["SET_ENABLED"] == ["SUBSCRIPTION", "ASSOCIATED_RSS"]
    assert by_code["DELETE_EXTERNAL"] == ["SUBSCRIPTION", "ASSOCIATED_RSS"]
    assert by_code["REFRESH_RSS"] == ["ASSOCIATED_RSS"]
    assert all("opaque" not in str(item) for item in actions)
    subscription_only = tracking_available_actions("ACTIVE", {"subscription_id": "opaque-sub", "rss_ids": []})
    assert "REFRESH_RSS" not in {item["code"] for item in subscription_only}
    assert tracking_available_actions("ACTIVE", None) == []
