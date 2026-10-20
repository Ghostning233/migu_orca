from __future__ import annotations

from typing import Any

import pytest

import apps.migu_orca_web.routes_tracking as routes_tracking
from ab_engine.models.management import ExternalRss
from apps.base import create_app
from tracking_engine.controllers.management_target import ResolvedManagementTarget
from tracking_engine.models.tracking import create_external_tracking_record


def _payload(scope: str = "SUBSCRIPTION", **extra: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "tracking_id": "trk_route_test", "target_scope": scope,
        "expected_revision": 1, "idempotency_key": "route-key",
        "confirm": True,
        "connection_ref": "11111111-1111-4111-8111-111111111111",
        "configuration_revision": 1,
    }
    value.update(extra)
    return value


@pytest.mark.parametrize(
    ("path", "scope", "extra", "action"),
    [
        ("modify", "SUBSCRIPTION", {"patch": {"title": "新标题"}}, "MODIFY"),
        ("set-enabled", "SUBSCRIPTION", {"enabled": False}, "SET_ENABLED"),
        # Issue #228 retired the standalone /delete-external route; the
        # operation survives only inside the composite plan-delete leg.
        ("refresh", "ASSOCIATED_RSS", {}, "REFRESH_RSS"),
    ],
)
def test_management_flask_routes_dispatch_the_public_actions(
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
    # #204: ``outcome`` is not part of the public safe result any more.
    assert "outcome" not in result

    # Issue #169: an indeterminate management write is 结果待确认, not a failure.
    unknown = routes_tracking._management_result(
        object(), tracking_id=record.tracking_id, action="MODIFY",
        result={"operation_id": "op_test", "management_status": "OUTCOME_UNKNOWN",
                "outcome": "OUTCOME_UNKNOWN", "needs_manual": True},
    )
    assert unknown["needs_manual"] is True
    assert unknown["management_status"] == "OUTCOME_UNKNOWN"
    assert unknown["safe_message"] == "外部管理结果待确认，请人工恢复；不会自动重试"


def test_management_writer_never_reads_a_body_status_as_success() -> None:
    """Issue #216: a body ``status`` is no longer accepted-action evidence.

    The real 3.1.18 adapter answers with an exact HTTP status and never with a
    ``status`` field, so a writer that fed one must not reach the success branch:
    without an exact status code the result stays the fail-closed 502.
    """
    class Client:
        def delete_rss(self, external_id: str) -> dict[str, object]:
            del external_id
            return {"status": True}

    result = routes_tracking._management_writer(Client(), "DELETE_EXTERNAL")(
        ResolvedManagementTarget(
            scope="ASSOCIATED_RSS", rss=(ExternalRss("1", "one", "https://rss.invalid/1"),)
        ),
        None,
    )

    assert result == {"status_code": 502}


def test_rss_mixed_write_statuses_are_not_reduced_to_the_first_failure() -> None:
    """Issue #216: the mixed-result rule reads the adapter's exact status code.

    The real 3.1.18 adapter never returns a body ``status`` field, so a fake that
    still fed one could only prove a criterion production no longer uses.
    """
    class Client:
        def delete_rss(self, external_id: str) -> dict[str, object]:
            return {"status_code": 200 if external_id == "2" else 502}

    result = routes_tracking._management_writer(Client(), "DELETE_EXTERNAL")(
        ResolvedManagementTarget(
            scope="ASSOCIATED_RSS",
            rss=(ExternalRss("1", "one", "https://rss.invalid/1"), ExternalRss("2", "two", "https://rss.invalid/2")),
        ),
        None,
    )
    assert result == {"transport_error": "unknown"}
