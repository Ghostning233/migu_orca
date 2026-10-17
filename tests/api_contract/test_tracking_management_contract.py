from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

import pytest
from pydantic import ValidationError

from ab_engine.controllers.ab_config import AutoBangumiConfig
from ab_engine.controllers.ab_http_client import UrlopenAutoBangumiHttpTransport
from ab_engine.controllers.ab_management_client import create_legacy_31_management_client
from apps.migu_orca_web.api_contract import TrackingAvailableActionDTO, TrackingManagementResultDTO
from apps.migu_orca_web.openapi_gen import generate_openapi
from apps.migu_orca_web.schemas import (
    TrackingDeleteExternalPayload,
    TrackingModifyPayload,
    TrackingRefreshRssPayload,
    TrackingSetEnabledPayload,
)
from apps.migu_orca_web.tracking_contract import MANAGEMENT_ACTION_CONTRACTS, MANAGEMENT_ERROR_SEMANTICS
from extensions.flask_api.api import _error_http_status
from shared.errors import Stage1Error
from tests.api_contract.ab_write_envelopes import (
    RECORDED_MISSING_ID_ENVELOPE,
    RECORDED_MISSING_ID_STATUS,
    RECORDED_REFRESH_RSS_ENVELOPE,
    RECORDED_REFRESH_RSS_STATUS,
    RECORDED_RSS_DELETE_ENVELOPE,
    RECORDED_RSS_DELETE_STATUS,
)


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
        "connection_ref": "11111111-1111-4111-1111-111111111111", "configuration_revision": 1,
    }
    assert TrackingSetEnabledPayload.model_validate({**base, "enabled": False})
    with pytest.raises(ValidationError):
        TrackingSetEnabledPayload.model_validate({**base, "expected_revision": True, "enabled": False})
    with pytest.raises(ValidationError):
        TrackingModifyPayload.model_validate({**base, "patch": {"title": "x"}, "unexpected": 1})
    with pytest.raises(ValidationError):
        TrackingRefreshRssPayload.model_validate({**base, "target_scope": "SUBSCRIPTION"})


@pytest.mark.parametrize("payload_model, extra", [
    (TrackingModifyPayload, {"target_scope": "SUBSCRIPTION", "patch": {"title": "x"}}),
    (TrackingSetEnabledPayload, {"target_scope": "SUBSCRIPTION", "enabled": False}),
    (TrackingDeleteExternalPayload, {"target_scope": "SUBSCRIPTION"}),
    (TrackingRefreshRssPayload, {"target_scope": "ASSOCIATED_RSS"}),
])
def test_management_success_requests_use_saved_connection_reference(monkeypatch, payload_model, extra) -> None:
    """Stage 39 migration red test: successful writes carry only saved binding."""
    payload = {
        "tracking_id": "trk_1", "expected_revision": 1,
        "idempotency_key": "key-1", "confirm": True,
        "connection_ref": "11111111-1111-1111-1111-111111111111",
        "configuration_revision": 3,
        **extra,
    }
    # This must be accepted once the request-scoped credential contract is retired.
    parsed = payload_model.model_validate(payload)
    dumped = parsed.model_dump(exclude_none=True)
    assert str(dumped["connection_ref"]) == payload["connection_ref"]
    assert dumped["configuration_revision"] == 3
    assert "ab_config" not in dumped


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
        "connection_ref": "11111111-1111-4111-1111-111111111111", "configuration_revision": 1,
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


def test_openapi_modify_patch_allows_multiple_fields_but_requires_one() -> None:
    """The inner patch alternatives are ``anyOf``: multi-field writes remain valid."""
    schema = generate_openapi()["paths"]["/api/v1/tracking/items/{tracking_id}/modify"]["post"]
    body = schema["requestBody"]["content"]["application/json"]["schema"]
    assert len(body["oneOf"]) == 2  # scope remains the discriminator
    subscription_patch = body["oneOf"][0]["properties"]["patch"]
    rss_patch = body["oneOf"][1]["properties"]["patch"]
    subscription_any_of = subscription_patch["allOf"][1]["anyOf"]
    rss_any_of = rss_patch["allOf"][1]["anyOf"]
    assert "oneOf" not in subscription_patch
    assert "oneOf" not in rss_patch
    assert {tuple(branch["required"]) for branch in subscription_any_of} == {
        ("title",), ("season",), ("subtitle_group",), ("filter_rule",),
        ("offset",), ("expected_folder_name",),
    }
    assert {tuple(branch["required"]) for branch in rss_any_of} == {
        ("name",), ("aggregate",), ("parser",),
    }
    filter_schema = subscription_patch["allOf"][0]["properties"]["filter_rule"]
    filter_object = next(branch for branch in filter_schema["anyOf"] if "allOf" in branch)
    assert "oneOf" not in filter_object
    assert len(filter_object["allOf"][1]["anyOf"]) == 4

    base = {
        "tracking_id": "trk_1", "expected_revision": 1,
        "idempotency_key": "key-1", "confirm": True,
        "connection_ref": "11111111-1111-1111-1111-111111111111", "configuration_revision": 1,
    }
    assert TrackingModifyPayload.model_validate({
        **base, "target_scope": "SUBSCRIPTION",
        "patch": {"title": "show", "season": 2,
                   "filter_rule": {"must_contain": "1080p", "use_regex": False}},
    })
    assert TrackingModifyPayload.model_validate({
        **base, "target_scope": "ASSOCIATED_RSS",
        "patch": {"name": "rss", "aggregate": True},
    })
    for scope, patch in (("SUBSCRIPTION", {}), ("ASSOCIATED_RSS", {}),
                         ("SUBSCRIPTION", {"filter_rule": {}})):
        with pytest.raises(ValidationError):
            TrackingModifyPayload.model_validate({**base, "target_scope": scope, "patch": patch})


def test_modify_local_plan_is_subscription_only_and_never_empty() -> None:
    """Issue #202: the restored field keeps #91's scope rule and strictness."""
    base = {
        "tracking_id": "trk_1", "expected_revision": 1, "idempotency_key": "key-1",
        "confirm": True, "connection_ref": "11111111-1111-4111-1111-111111111111",
        "configuration_revision": 1,
    }
    subscription = TrackingModifyPayload.model_validate({
        **base, "target_scope": "SUBSCRIPTION", "patch": {"title": "show"},
        "local_plan": {"expected_folder_name": "New"},
    })
    assert subscription.local_plan is not None
    assert subscription.local_plan.model_dump(exclude_none=True) == {
        "expected_folder_name": "New"
    }
    # ``local_plan`` is optional and independent from ``patch``.
    assert TrackingModifyPayload.model_validate({
        **base, "target_scope": "SUBSCRIPTION", "patch": {"title": "show"},
    }).local_plan is None
    # Only a subscription modify has a local plan to raise.
    with pytest.raises(ValidationError, match="local_plan"):
        TrackingModifyPayload.model_validate({
            **base, "target_scope": "ASSOCIATED_RSS", "patch": {"name": "rss"},
            "local_plan": {"expected_folder_name": "New"},
        })
    for empty in ({}, {"filter_rule": {}}, {"expected_folder_name": ""},
                  {"expected_folder_name": "a/b"}):
        with pytest.raises(ValidationError):
            TrackingModifyPayload.model_validate({
                **base, "target_scope": "SUBSCRIPTION", "patch": {"title": "show"},
                "local_plan": empty,
            })
    # The unknown-field guard is untouched.
    with pytest.raises(ValidationError):
        TrackingModifyPayload.model_validate({
            **base, "target_scope": "SUBSCRIPTION", "patch": {"title": "show"},
            "local_plan": {"expected_folder_name": "New"}, "local_plan_v2": {},
        })


def test_openapi_modify_local_plan_is_subscription_only() -> None:
    """Issue #202: the contract publishes ``local_plan`` on one branch only."""
    schema = generate_openapi()["paths"]["/api/v1/tracking/items/{tracking_id}/modify"]["post"]
    body = schema["requestBody"]["content"]["application/json"]["schema"]
    subscription, rss = body["oneOf"]
    assert subscription["properties"]["target_scope"] == {"const": "SUBSCRIPTION"}
    assert rss["properties"]["target_scope"] == {"const": "ASSOCIATED_RSS"}

    local_plan = subscription["properties"]["local_plan"]
    assert local_plan["type"] == ["object", "null"]
    assert local_plan["additionalProperties"] is False
    # The "provide at least one field" rule comes from the model projection.
    assert local_plan["minProperties"] == 1
    assert set(local_plan["properties"]) == {"filter_rule", "expected_folder_name"}
    assert local_plan["description"] == (
        "issue #91：外部修改确认成功后同时提升的本地方案字段（身份字段不可编辑）。"
        "与 patch 独立，缺省表示只改外部对象。"
    )
    # ``filter_rule`` mirrors the patch branch's reviewed anyOf encoding.
    filter_rule = local_plan["properties"]["filter_rule"]
    assert any(branch == {"type": "null"} for branch in filter_rule["anyOf"])
    assert any("allOf" in branch for branch in filter_rule["anyOf"])
    # The RSS branch stays strict: an unknown local_plan there is rejected.
    assert "local_plan" not in rss["properties"]
    assert rss["additionalProperties"] is False


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


# ---------------------------------------------------------------------------
# The verified 3.1.18 write contract (issue #216)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("action", "path", "status", "envelope", "expected_error", "expected_details"),
    [
        ("refresh_rss", "/api/v1/rss/refresh/7", RECORDED_REFRESH_RSS_STATUS, RECORDED_REFRESH_RSS_ENVELOPE, None, {"status_code": 200}),
        ("delete_rss", "/api/v1/rss/delete/7", RECORDED_RSS_DELETE_STATUS, RECORDED_RSS_DELETE_ENVELOPE, None, {"status_code": 200}),
        (
            "delete_rss", "/api/v1/rss/delete/7", RECORDED_MISSING_ID_STATUS, RECORDED_MISSING_ID_ENVELOPE,
            "ab_submit_failed",
            {
                "status_code": 406, "http_status": 406,
                "message_zh": RECORDED_MISSING_ID_ENVELOPE["msg_zh"],
                "message_en": RECORDED_MISSING_ID_ENVELOPE["msg_en"],
            },
        ),
        ("delete_rss", "/api/v1/rss/delete/7", 500, None, "ab_submit_failed", {"status_code": 500, "http_status": 500}),
    ],
)
def test_recorded_management_write_envelopes_decide_by_their_exact_status(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    path: str,
    status: int,
    envelope: dict[str, Any] | None,
    expected_error: str | None,
    expected_details: dict[str, Any],
) -> None:
    """Issue #216 AC2/AC4: the exact status plus the recorded envelope decide.

    The real transport, the real JSON decoder and the real management adapter
    run; only the HTTP exchange is replaced, and the recorded 3.1.18 envelopes
    are served verbatim.  A body-only judgement (the deleted ``else -> 502``
    branch) turned every accepted action into a failure and could not tell a
    proven 200 from a 406/500.
    """

    def exchange(
        method: str, endpoint: str, headers: Any, body: Any, *,
        timeout: float, step: str, inspect_error_body: bool = False, monotonic: Any = None,
    ) -> tuple[int, dict[str, str], bytes]:
        request_path = urlsplit(endpoint).path
        if request_path == "/api/v1/auth/login":
            return 200, {}, b'{"access_token": "ab-session"}'
        if request_path == "/api/v1/status":
            return 200, {}, b'{"version": "3.1.18"}'
        assert request_path == path, request_path
        raw = b"" if envelope is None else json.dumps(envelope).encode("utf-8")
        return status, {}, raw

    monkeypatch.setattr("ab_engine.controllers.ab_http_client._exchange", exchange)
    client = create_legacy_31_management_client(
        AutoBangumiConfig(
            base_url="https://ab.invalid", auth_mode="password", fallback_enabled=False,
            username="user", password="secret",
        ),
        transport=UrlopenAutoBangumiHttpTransport(),
    )

    if expected_error is None:
        assert getattr(client, action)("7") == expected_details
    else:
        with pytest.raises(Stage1Error) as error:
            getattr(client, action)("7")
        assert error.value.error_type == expected_error
        assert error.value.details == expected_details
        assert "ab-session" not in repr(error.value.as_dict())
