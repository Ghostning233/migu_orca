from __future__ import annotations

from typing import Any

import pytest

import apps.migu_orca_web.routes_tracking as routes_tracking
from apps.base import create_app
from tracking_engine.models.tracking import create_external_tracking_record


def _payload(scope: str = "SUBSCRIPTION", **extra: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "tracking_id": "trk_route_test", "target_scope": scope,
        "expected_revision": 1, "idempotency_key": "route-key",
        "confirm": True,
        "ab_config": {"auth_mode": "password", "base_url": "https://ab.invalid",
                      "username": "user", "password": "secret", "fallback_enabled": False},
    }
    value.update(extra)
    return value


@pytest.mark.parametrize(
    ("path", "scope", "extra", "action"),
    [
        ("modify", "SUBSCRIPTION", {"patch": {"title": "新标题"}}, "MODIFY"),
        ("set-enabled", "SUBSCRIPTION", {"enabled": False}, "SET_ENABLED"),
        ("delete-external", "SUBSCRIPTION", {}, "DELETE_EXTERNAL"),
        ("refresh", "ASSOCIATED_RSS", {}, "REFRESH_RSS"),
    ],
)
def test_management_flask_routes_dispatch_all_four_actions(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    scope: str,
    extra: dict[str, Any],
    action: str,
) -> None:
    calls: list[tuple[str, dict[str, Any], Any, Any]] = []

    def fake_run(payload: Any, selected_action: str, **kwargs: Any) -> dict[str, Any]:
        calls.append((selected_action, kwargs, payload.tracking_id, payload.target_scope))
        return {"management_status": "SUCCEEDED", "needs_manual": False, "action": selected_action}

    monkeypatch.setattr(routes_tracking, "_run_management_route", fake_run)
    response = create_app("testing").test_client().post(
        f"/api/v1/tracking/items/trk_route_test/{path}",
        json=_payload(scope, **extra),
    )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "result": {
        "management_status": "SUCCEEDED", "needs_manual": False, "action": action,
    }}
    assert calls == [(action, ({"patch": extra["patch"]} if action == "MODIFY" else
                                {"enabled": False} if action == "SET_ENABLED" else {}),
                      "trk_route_test", scope)]


def test_management_result_distinguishes_explicit_failure_from_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    record = create_external_tracking_record(
        adapter="legacy_3_1", object_kind="subscription", external_id="sub-1",
        subscription_id="sub-1", title="Test", season=1,
    )
    monkeypatch.setattr(routes_tracking, "load_tracking_record", lambda _config, _tracking_id: record)
    result = routes_tracking._management_result(
        object(), tracking_id=record.tracking_id, action="MODIFY",
        result={"operation_id": "op_test", "management_status": "FAILED",
                "outcome": "DEFINITE_FAILURE", "needs_manual": False},
    )
    assert result["needs_manual"] is False
    assert result["safe_message"] == "管理操作明确失败，外部系统未确认应用"
    assert result["outcome"] == "DEFINITE_FAILURE"
