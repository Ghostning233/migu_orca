"""Stage 39 browser red tests for the retired credential boundary."""

import pytest
from playwright.sync_api import expect

from tests.browser.test_app_tracking import (
    _delete_detail,
    _detail_payload,
    _item,
    _management_actions,
    _modify_actions,
    _probe_capabilities,
    _recovery_item,
)


@pytest.mark.browser
def test_retired_capabilities_endpoint_is_not_reachable(page, live_server_url):
    response = page.request.post(f"{live_server_url}/api/v1/autobangumi/capabilities", data="{}")
    assert response.status == 404


@pytest.mark.browser
def test_tracking_page_has_no_legacy_credential_dialog(page, live_server_url):
    page.goto(f"{live_server_url}/app/tracking")
    page.wait_for_load_state("networkidle")
    assert page.locator("#tracking-connect").count() == 0
    assert page.locator("text=连接 Auto Bangumi").count() == 0


@pytest.mark.browser
def test_saved_settings_probe_and_tracking_summary_are_explicit_and_non_sensitive(page, live_server_url):
    """Real Chromium journey: save is the only secret-bearing request; probe/actions use ref+revision."""
    secret = "browser-only-canary"
    ref = "11111111-1111-4111-8111-111111111111"
    captured: list[tuple[str, dict]] = []

    def api(route, request):
        path = request.url.split("/api/v1", 1)[-1]
        if request.method == "GET" and path.startswith("/settings/autobangumi"):
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "configured": True,
                        "credential_present": True,
                        "connection_ref": ref,
                        "configuration_revision": 3,
                        "connection_status": "CONFIGURED",
                    },
                }
            )
            return
        if request.method == "PUT" and path.startswith("/settings/autobangumi"):
            captured.append(("save", request.post_data_json))
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "configured": True,
                        "credential_present": True,
                        "connection_ref": ref,
                        "configuration_revision": 3,
                        "connection_status": "CONFIGURED",
                    },
                }
            )
            return
        if request.method == "POST" and path.startswith("/settings/autobangumi/probe"):
            captured.append(("probe", request.post_data_json))
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "probe_status": "VERIFIED",
                        "version": "3.1.18",
                        "adapter": "legacy_3_1",
                        "subscription_list": "SUPPORTED",
                        "subscription_detail": "SUPPORTED",
                        "subscription_submit": "SUPPORTED",
                        "subscription_modify": "SUPPORTED",
                        "subscription_enable": "SUPPORTED",
                        "subscription_disable": "SUPPORTED",
                        "subscription_delete": "SUPPORTED",
                        "rss_list": "SUPPORTED",
                        "rss_modify": "SUPPORTED",
                        "rss_enable": "SUPPORTED",
                        "rss_disable": "SUPPORTED",
                        "rss_delete": "SUPPORTED",
                        "rss_refresh": "SUPPORTED",
                        "external_verify": "SUPPORTED",
                        "checked_at": None,
                        "safe_message": "已完成安全探测",
                    },
                }
            )
            return
        route.continue_()

    page.route("**/api/v1/**", api)
    page.goto(f"{live_server_url}/app/settings")
    page.wait_for_selector("#settings-heading")
    page.locator("#settings-ab-endpoint").fill("https://ab.example.invalid")
    page.locator("#settings-ab-username").fill("browser-user")
    page.locator("#settings-ab-password").fill(secret)
    page.locator("#settings-ab-save").click()
    expect(page.locator("#settings-ab-save-form .status-alert")).to_contain_text("已保存")
    page.locator("#settings-ab-probe").click()
    expect(page.locator("#settings-ab-save-form .status-alert")).to_contain_text("VERIFIED")
    assert captured[0][0] == "save"
    assert captured[1] == ("probe", {"connection_ref": ref, "configuration_revision": 3})
    assert secret not in page.locator("body").inner_text()
    assert secret not in page.url
    stored = page.evaluate(
        "() => ({local: JSON.stringify(localStorage), session: JSON.stringify(sessionStorage), history: location.href})"
    )
    assert secret not in str(stored)

    # A new page reads only the safe summary. It does not automatically probe or act.
    page.goto(f"{live_server_url}/app/tracking")
    page.wait_for_selector("#tracking-overview")
    expect(page.locator("#tracking-probe-saved")).to_be_visible()
    assert len([kind for kind, _ in captured if kind == "probe"]) == 1
    assert secret not in page.locator("body").inner_text()


@pytest.mark.browser
@pytest.mark.parametrize(
    ("action", "selector", "setup"),
    [
        ("MODIFY", "#tracking-modify-subscription-submit", "modify"),
        ("SET_ENABLED", "#tracking-set-enabled-submit", "enabled"),
        ("REFRESH_RSS", "#tracking-refresh-rss-submit", "refresh"),
        ("DELETE_EXTERNAL", "#tracking-delete-external-submit", "delete"),
    ],
)
def test_saved_management_actions_send_only_bound_connection_fields(page, live_server_url, action, selector, setup):
    """Each external management action is reached via explicit saved probe and has no credential/config snapshot."""
    ref = "11111111-1111-4111-8111-111111111111"
    captured: list[dict] = []
    actions = (
        _modify_actions()
        + _management_actions("ACTIVE")
        + [
            {
                "code": "DELETE_EXTERNAL",
                "label": "删除外部订阅",
                "style": "DANGER",
                "requires_confirmation": True,
                "target_scopes": ["ASSOCIATED_RSS"],
            }
        ]
    )
    detail = {
        "ok": True,
        "result": {
            **_item("tracking-a", "测试番"),
            "available_actions": actions,
            "revision": 1,
            "origin": "single",
            "batch_id": None,
            "created_at": "2026-09-01T00:00:00Z",
            "updated_at": "2026-09-01T00:00:00Z",
            "last_synced_at": None,
            "safe_info": None,
            "current_operation": None,
            "revalidation_issues": [],
            "external_mapping": {"match_reason": "标题", "enabled": True, "external_deleted": False},
            "audit_events": [],
            "warnings": [],
        },
    }
    if action == "DELETE_EXTERNAL":
        detail = _delete_detail(1)

    def handler(route, request):
        path = request.url.split("/api/v1", 1)[-1]
        if request.method == "GET" and path.startswith("/settings/autobangumi"):
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "configured": True,
                        "credential_present": True,
                        "connection_ref": ref,
                        "configuration_revision": 3,
                        "connection_status": "CONFIGURED",
                    },
                }
            )
            return
        if request.method == "GET" and path.startswith("/tracking/items/tracking-a"):
            route.fulfill(json=detail)
            return
        if request.method == "GET" and path.startswith("/tracking/items"):
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "items": [{**detail["result"], "safe_info": None}],
                        "summary": {
                            "total": 1,
                            "pending": 1,
                            "processing": 0,
                            "active": 0,
                            "needs_attention": 0,
                            "unreadable": 0,
                        },
                        "warnings": [],
                    },
                }
            )
            return
        if request.method == "POST" and path.startswith("/settings/autobangumi/probe"):
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "probe_status": "VERIFIED",
                        "version": "3.1.18",
                        "adapter": "legacy_3_1",
                        "subscription_list": "SUPPORTED",
                        "subscription_detail": "SUPPORTED",
                        "subscription_submit": "SUPPORTED",
                        "subscription_modify": "SUPPORTED",
                        "subscription_enable": "SUPPORTED",
                        "subscription_disable": "SUPPORTED",
                        "subscription_delete": "SUPPORTED",
                        "rss_list": "SUPPORTED",
                        "rss_modify": "SUPPORTED",
                        "rss_enable": "SUPPORTED",
                        "rss_disable": "SUPPORTED",
                        "rss_delete": "SUPPORTED",
                        "rss_refresh": "SUPPORTED",
                        "external_verify": "SUPPORTED",
                        "checked_at": None,
                        "safe_message": "ok",
                    },
                }
            )
            return
        if request.method == "POST" and "/tracking/items/tracking-a/" in path:
            captured.append(request.post_data_json or {})
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "action": action,
                        "management_status": "SUCCEEDED",
                        "needs_manual": False,
                        "safe_message": "已完成",
                        "operation_id": "op-1",
                        "operation": None,
                        "tracking": {**_item("tracking-a", "测试番"), "revision": 2},
                    },
                }
            )
            return
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
    page.wait_for_selector("#tracking-overview")
    page.locator("#tracking-probe-saved").click()
    page.wait_for_timeout(50)
    page.locator(selector).scroll_into_view_if_needed()
    if setup == "modify":
        page.locator("#tracking-modify-title-enabled").check()
        page.locator("#tracking-modify-title").fill("新标题")
    elif setup == "enabled":
        page.locator("#tracking-set-enabled-scope-SUBSCRIPTION").check()
    elif setup == "delete":
        page.locator("#tracking-delete-external-scope-ASSOCIATED_RSS").check()
    page.locator(selector).click()
    if page.locator(".confirm-dialog").count():
        page.locator(".confirm-dialog .danger-button, .confirm-dialog .primary-button").last.click(timeout=2000)
    page.wait_for_timeout(500)
    assert captured, action
    body = captured[-1]
    assert body["connection_ref"] == ref
    assert body["configuration_revision"] == 3
    assert "ab_config" not in body and "password" not in str(body)
    if action == "DELETE_EXTERNAL":
        assert body["confirm"] is True
        assert body["expected_revision"] == 1
        assert body["idempotency_key"]
        assert "file" not in body
        expect(page.locator("#tracking-delete-external-result")).to_be_visible()


@pytest.mark.browser
def test_saved_sync_requires_explicit_probe_and_sends_ref_revision(page, live_server_url):
    ref = "11111111-1111-4111-8111-111111111111"
    calls: list[dict] = []
    item = {**_item("tracking-a", "测试番"), "available_actions": [], "revision": 1}

    def handler(route, request):
        path = request.url.split("/api/v1", 1)[-1]
        if request.method == "GET" and path.startswith("/settings/autobangumi"):
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "configured": True,
                        "credential_present": True,
                        "connection_ref": ref,
                        "configuration_revision": 3,
                        "connection_status": "CONFIGURED",
                    },
                }
            )
            return
        if request.method == "GET" and path.startswith("/tracking/items"):
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "items": [item],
                        "summary": {
                            "total": 1,
                            "pending": 1,
                            "processing": 0,
                            "active": 0,
                            "needs_attention": 0,
                            "unreadable": 0,
                        },
                        "warnings": [],
                    },
                }
            )
            return
        if request.method == "POST" and path.startswith("/settings/autobangumi/probe"):
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "probe_status": "VERIFIED",
                        "version": "3.1.18",
                        "adapter": "legacy_3_1",
                        **{
                            name: "SUPPORTED"
                            for name in (
                                "subscription_list",
                                "subscription_detail",
                                "subscription_submit",
                                "subscription_modify",
                                "subscription_enable",
                                "subscription_disable",
                                "subscription_delete",
                                "rss_list",
                                "rss_modify",
                                "rss_enable",
                                "rss_disable",
                                "rss_delete",
                                "rss_refresh",
                                "external_verify",
                            )
                        },
                        "checked_at": None,
                        "safe_message": "ok",
                    },
                }
            )
            return
        if request.method == "POST" and path.startswith("/tracking/sync"):
            calls.append(request.post_data_json or {})
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "sync_status": "COMPLETE",
                        "capabilities": {
                            "probe_status": "VERIFIED",
                            **{
                                name: "SUPPORTED"
                                for name in (
                                    "subscription_list",
                                    "subscription_detail",
                                    "subscription_submit",
                                    "subscription_modify",
                                    "subscription_enable",
                                    "subscription_disable",
                                    "subscription_delete",
                                    "rss_list",
                                    "rss_modify",
                                    "rss_enable",
                                    "rss_disable",
                                    "rss_delete",
                                    "rss_refresh",
                                    "external_verify",
                                )
                            },
                        },
                        "summary": {"checked": 1, "created": 0, "updated": 0, "unchanged": 1},
                        "items": [item],
                    },
                }
            )
            return
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/tracking")
    page.wait_for_selector("#tracking-overview")
    expect(page.locator("#tracking-sync")).to_have_count(0)
    page.locator("#tracking-probe-saved").click()
    expect(page.locator("#tracking-sync")).to_be_enabled()
    page.locator("#tracking-sync").click()
    page.locator(".confirm-dialog .primary-button").click()
    page.wait_for_timeout(100)
    assert calls == [{"connection_ref": ref, "configuration_revision": 3, "confirm": True}]


@pytest.mark.browser
def test_saved_verify_external_is_unknown_safe_when_unavailable(page, live_server_url):
    ref = "11111111-1111-4111-8111-111111111111"
    calls: list[dict] = []
    unknown = _detail_payload(_recovery_item("tracking-a", "未知结果", revision=4))

    def handler(route, request):
        path = request.url.split("/api/v1", 1)[-1]
        if request.method == "GET" and path.startswith("/settings/autobangumi"):
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "configured": True,
                        "credential_present": True,
                        "connection_ref": ref,
                        "configuration_revision": 3,
                        "connection_status": "CONFIGURED",
                    },
                }
            )
            return
        if request.method == "GET" and path.startswith("/tracking/items"):
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "items": [unknown],
                        "summary": {
                            "total": 1,
                            "pending": 0,
                            "processing": 0,
                            "active": 0,
                            "needs_attention": 1,
                            "unreadable": 0,
                        },
                        "warnings": [],
                    },
                }
            )
            return
        if request.method == "POST" and path.startswith("/settings/autobangumi/probe"):
            route.fulfill(json={"ok": True, "result": _probe_capabilities()})
            return
        if request.method == "POST" and path.endswith("/recover"):
            calls.append(request.post_data_json or {})
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "tracking_id": "tracking-a",
                        "action": "VERIFY_EXTERNAL",
                        "outcome": "RECOVERY_REQUIRED",
                        "checked_revision": 4,
                        "next_revision": 4,
                        "checked_at": "2026-09-14T00:00:00Z",
                        "operation_id": "op-unknown",
                        "needs_manual": True,
                        "tracking": unknown,
                    },
                }
            )
            return
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
    page.wait_for_selector("#tracking-overview")
    expect(page.locator("#tracking-recover-verify")).to_have_count(0)
    page.locator("#tracking-probe-saved").click()
    page.wait_for_timeout(300)
    assert page.locator("#tracking-recover-verify").count() == 0
    assert calls == []
