"""Stage 39 browser red tests for the retired credential boundary."""

import pytest
from playwright.sync_api import expect

from tests.browser.saved_tracking_fixtures import (
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
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
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
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
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
    page.locator(".confirm-dialog .danger-button, .confirm-dialog .primary-button").last.click()
    page.wait_for_timeout(100)
    assert calls == [{"connection_ref": ref, "configuration_revision": 3, "confirm": True}]


@pytest.mark.browser
def test_saved_verify_external_preserves_unknown_source_lock(page, live_server_url):
    ref = "11111111-1111-4111-8111-111111111111"
    calls: list[dict] = []
    writes: list[str] = []
    console_messages: list[str] = []
    secret = "verify-secret-canary"
    page.on("console", lambda message: console_messages.append(message.text))
    unknown = _detail_payload(_recovery_item("tracking-a", "未知结果", revision=4))

    def handler(route, request):
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
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
            route.fulfill(json={"ok": True, "result": unknown})
            return
        if request.method == "GET" and path == "/tracking/items":
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
        if request.method == "POST" and path.startswith("/tracking/items/tracking-a/"):
            writes.append(path)
            route.continue_()
            return
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
    page.wait_for_selector("#tracking-overview")
    page.wait_for_selector(".tracking-inspector-detail")
    page.locator("#tracking-probe-saved").click()
    page.wait_for_selector("#tracking-recover-verify")
    page.locator("#tracking-recover-verify").click()
    expect(page.locator(".confirm-dialog-message")).to_contain_text("只读核对")
    page.locator(".confirm-dialog-actions button").filter(has_text="确认只读核验").click()
    page.wait_for_selector("#tracking-recovery-result")
    assert calls == [{
        "expected_revision": 4,
        "action": "VERIFY_EXTERNAL",
        "connection_ref": ref,
        "configuration_revision": 3,
    }]
    expect(page.locator("#tracking-recovery-result")).to_contain_text("独立核对")
    expect(page.locator("#tracking-recovery-result")).not_to_contain_text("RECOVERY_REQUIRED")
    assert not any(endpoint in path for path in writes for endpoint in ("/submit", "/retry", "/modify", "/set-enabled", "/refresh", "/delete-external"))
    assert secret not in page.locator("body").inner_text()
    assert secret not in page.url
    assert secret not in page.evaluate("() => location.href + JSON.stringify(history.state) + JSON.stringify(localStorage) + JSON.stringify(sessionStorage)")
    assert secret not in " ".join(console_messages)


@pytest.mark.browser
def test_settings_cas_conflict_rereads_summary_without_resubmitting(page, live_server_url):
    ref = "11111111-1111-4111-8111-111111111111"
    gets = 0
    puts = 0

    def route_api(route, request):
        nonlocal gets, puts
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
            gets += 1
            route.fulfill(json={"ok": True, "result": {
                "configured": True, "credential_present": True,
                "connection_ref": ref, "configuration_revision": gets,
                "connection_status": "CONFIGURED",
            }})
            return
        if request.method == "PUT" and path == "/settings/autobangumi":
            puts += 1
            route.fulfill(status=409, json={"ok": False, "error_type": "configuration_conflict"})
            return
        route.continue_()

    page.route("**/api/v1/**", route_api)
    page.goto(f"{live_server_url}/app/settings")
    page.wait_for_selector("#settings-ab-save-form")
    page.locator("#settings-ab-endpoint").fill("192.168.1.20:7890")
    page.locator("#settings-ab-username").fill("user")
    page.locator("#settings-ab-password").fill("cas-canary")
    page.locator("#settings-ab-save").click()
    expect(page.locator("#settings-ab-save-form [role=alert]")).to_contain_text("配置已变化")
    assert puts == 1
    assert gets >= 2
    assert page.locator("#settings-ab-password").input_value() == "cas-canary"


@pytest.mark.browser
def test_saved_probe_failure_keeps_summary_across_refresh_and_navigation(page, live_server_url):
    """A failed explicit probe never deletes the saved generation or leaks input."""
    ref = "11111111-1111-4111-8111-111111111111"
    secret = "probe-failure-canary"
    probe_calls = 0

    def handler(route, request):
        nonlocal probe_calls
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
            route.fulfill(json={"ok": True, "result": {"configured": True, "credential_present": True,
                "connection_ref": ref, "configuration_revision": 3, "connection_status": "CONFIGURED"}})
            return
        if request.method == "POST" and path == "/settings/autobangumi/probe":
            probe_calls += 1
            route.fulfill(status=503, json={"ok": False, "error_type": "upstream_unavailable", "error_message": secret})
            return
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/settings")
    page.wait_for_selector("#settings-ab-probe")
    page.locator("#settings-ab-probe").click()
    expect(page.locator("#settings-ab-save-form .status-alert")).to_contain_text("探测失败")
    assert probe_calls == 1
    assert page.locator("#settings-ab-delete").is_enabled()
    page.reload()
    page.wait_for_selector("#settings-ab-probe")
    assert page.locator("#settings-ab-delete").is_enabled()
    page.goto(f"{live_server_url}/app/tracking")
    page.wait_for_selector("#tracking-probe-saved")
    assert page.locator("#tracking-probe-saved").is_enabled()
    assert secret not in page.locator("body").inner_text()
    assert secret not in page.evaluate("() => location.href + JSON.stringify(history.state) + JSON.stringify(localStorage) + JSON.stringify(sessionStorage)")


@pytest.mark.browser
def test_tracking_refresh_does_not_probe_or_sync_saved_connection(page, live_server_url):
    """Loading and refreshing tracking remains read-only until the explicit probe."""
    ref = "11111111-1111-4111-8111-111111111111"
    calls: list[str] = []

    def handler(route, request):
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
            route.fulfill(json={"ok": True, "result": {"configured": True, "credential_present": True,
                "connection_ref": ref, "configuration_revision": 3, "connection_status": "CONFIGURED"}})
            return
        if request.method == "GET" and path == "/tracking/items":
            route.fulfill(json={"ok": True, "result": {"items": [], "summary": {"total": 0}, "warnings": []}})
            return
        if request.method == "POST":
            calls.append(path)
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/tracking")
    page.wait_for_selector("#tracking-probe-saved")
    page.reload()
    page.wait_for_selector("#tracking-probe-saved")
    assert calls == []
    expect(page.locator("#tracking-sync")).to_have_count(0)


@pytest.mark.browser
def test_tracking_saved_capability_degrade_hides_management_actions(page, live_server_url):
    """Unsupported capabilities fail closed and cannot produce a management write."""
    ref = "11111111-1111-4111-8111-111111111111"
    item = {**_item("tracking-a", "降级番"), "available_actions": _management_actions("ACTIVE"), "revision": 1}
    detail = {"ok": True, "result": {**item, "origin": "single", "batch_id": None,
        "created_at": "2026-09-01T00:00:00Z", "updated_at": "2026-09-01T00:00:00Z",
        "last_synced_at": None, "safe_info": None, "current_operation": None,
        "revalidation_issues": [], "external_mapping": None, "audit_events": [], "warnings": []}}
    writes: list[str] = []

    def handler(route, request):
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
            route.fulfill(json={"ok": True, "result": {"configured": True, "credential_present": True,
                "connection_ref": ref, "configuration_revision": 3, "connection_status": "CONFIGURED"}}); return
        if request.method == "GET" and path == "/tracking/items":
            route.fulfill(json={"ok": True, "result": {"items": [item], "summary": {"total": 1}, "warnings": []}}); return
        if request.method == "GET" and path == "/tracking/items/tracking-a":
            route.fulfill(json=detail); return
        if request.method == "POST" and path == "/settings/autobangumi/probe":
            route.fulfill(json={"ok": True, "result": {**_probe_capabilities(), "subscription_modify": "UNSUPPORTED",
                "subscription_enable": "UNSUPPORTED", "rss_refresh": "UNSUPPORTED"}}); return
        if request.method == "POST" and "/tracking/items/" in path:
            writes.append(path)
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
    page.wait_for_selector("#tracking-probe-saved")
    page.locator("#tracking-probe-saved").click()
    page.wait_for_timeout(150)
    assert page.locator("#tracking-modify-subscription-submit").count() == 0
    if page.locator("#tracking-set-enabled-submit").count():
        expect(page.locator("#tracking-set-enabled-submit")).to_be_disabled()
    if page.locator("#tracking-refresh-rss-submit").count():
        expect(page.locator("#tracking-refresh-rss-submit")).to_be_disabled()
    assert writes == []


@pytest.mark.browser
@pytest.mark.parametrize(("status", "code", "selector"), [("PENDING_SUBMIT", "SUBMIT", "#tracking-submit"), ("SUBMIT_FAILED", "RETRY", "#tracking-retry")])
def test_saved_submit_and_retry_use_one_explicit_generation(page, live_server_url, status, code, selector):
    ref = "11111111-1111-4111-8111-111111111111"
    body_item = {**_item("tracking-a", "提交番", status), "status": status,
        "available_actions": [{"code": code, "label": code, "style": "PRIMARY", "requires_confirmation": True, "target_scopes": []}]}
    detail = {"ok": True, "result": {**_detail_payload(body_item), "revision": 4}}
    calls: list[dict] = []

    def handler(route, request):
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
            route.fulfill(json={"ok": True, "result": {"configured": True, "credential_present": True, "connection_ref": ref, "configuration_revision": 3, "connection_status": "CONFIGURED"}}); return
        if request.method == "GET" and path == "/tracking/items":
            route.fulfill(json={"ok": True, "result": {"items": [body_item], "summary": {"total": 1}, "warnings": []}}); return
        if request.method == "GET" and path == "/tracking/items/tracking-a":
            route.fulfill(json=detail); return
        if request.method == "POST" and path == "/settings/autobangumi/probe":
            route.fulfill(json={"ok": True, "result": _probe_capabilities()}); return
        if request.method == "POST" and path.endswith("/submit") or request.method == "POST" and path.endswith("/retry"):
            calls.append(request.post_data_json or {})
            route.fulfill(json={"ok": True, "result": {"tracking_id": "tracking-a", "action": code, "outcome": "OUTCOME_UNKNOWN", "needs_manual": True, "tracking": body_item}}); return
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
    page.wait_for_selector("#tracking-probe-saved")
    page.locator("#tracking-probe-saved").click()
    page.wait_for_selector(selector)
    page.locator(selector).click()
    expect(page.locator(".confirm-dialog")).to_be_visible()
    page.locator(".confirm-dialog .danger-button, .confirm-dialog .primary-button").last.click()
    page.wait_for_timeout(150)
    assert len(calls) == 1
    sent = calls[0]
    assert sent["connection_ref"] == ref and sent["configuration_revision"] == 3
    assert sent["confirm"] is True and sent["expected_revision"] == 4
    assert sent["idempotency_key"] and "ab_config" not in sent and "password" not in str(sent)


@pytest.mark.browser
def test_local_recovery_needs_no_saved_probe_and_revalidate_is_local(page, live_server_url):
    item = _recovery_item("tracking-a", "本地恢复", revision=4)
    item["available_actions"] = [
        {"code": "RECOVER_AUTO", "label": "自动恢复", "style": "SECONDARY", "requires_confirmation": False, "target_scopes": []},
        {"code": "MARK_SUCCEEDED", "label": "标记成功", "style": "PRIMARY", "requires_confirmation": True, "target_scopes": []},
        {"code": "MARK_FAILED", "label": "标记失败", "style": "DANGER", "requires_confirmation": True, "target_scopes": []},
        {"code": "REVALIDATE", "label": "本地复核", "style": "SECONDARY", "requires_confirmation": False, "target_scopes": []},
    ]
    detail = {"ok": True, "result": _detail_payload(item)}
    calls: list[tuple[str, dict]] = []

    def handler(route, request):
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
            route.fulfill(json={"ok": True, "result": {"configured": False, "credential_present": False, "connection_ref": None, "configuration_revision": 0, "connection_status": "UNCONFIGURED"}}); return
        if request.method == "GET" and path == "/tracking/items":
            route.fulfill(json={"ok": True, "result": {"items": [item], "summary": {"total": 1}, "warnings": []}}); return
        if request.method == "GET" and path == "/tracking/items/tracking-a":
            route.fulfill(json=detail); return
        if request.method == "POST" and path.endswith("/recover"):
            calls.append(("recover", request.post_data_json or {}))
            route.fulfill(json={"ok": True, "result": {"tracking_id": "tracking-a", "action": "RECOVER_AUTO", "outcome": "SUCCEEDED", "checked_revision": 4, "next_revision": 5, "needs_manual": False, "tracking": item}}); return
        if request.method == "POST" and path.endswith("/revalidate"):
            calls.append(("revalidate", request.post_data_json or {}))
            route.fulfill(json={"ok": True, "result": {"ready": False, "next_status": "NEEDS_RECONFIRM", "issues": []}}); return
        if request.method == "POST":
            raise AssertionError(f"unexpected external call: {path}")
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
    page.wait_for_selector("#tracking-recover-auto")
    page.locator("#tracking-revalidate").click()
    page.wait_for_timeout(100)
    assert any(kind == "revalidate" and payload == {"expected_revision": 4} for kind, payload in calls)


@pytest.mark.browser
def test_settings_bare_endpoint_is_normalized_and_navigation_cancels_save(page, live_server_url):
    ref = "11111111-1111-4111-8111-111111111111"
    puts: list[dict] = []

    def handler(route, request):
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
            route.fulfill(json={"ok": True, "result": {"configured": False, "credential_present": False, "connection_ref": None, "configuration_revision": 0, "connection_status": "UNCONFIGURED"}}); return
        if request.method == "PUT" and path == "/settings/autobangumi":
            puts.append(request.post_data_json or {})
            route.fulfill(json={"ok": True, "result": {"configured": True, "credential_present": True, "connection_ref": ref, "configuration_revision": 1, "connection_status": "CONFIGURED"}}); return
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/settings")
    page.wait_for_selector("#settings-ab-save")
    page.locator("#settings-ab-endpoint").fill("192.168.1.20:7890")
    page.locator("#settings-ab-username").fill("user")
    page.locator("#settings-ab-password").fill("cancel-canary")
    page.goto(f"{live_server_url}/app/tracking")
    assert puts == []
    page.goto(f"{live_server_url}/app/settings")
    page.wait_for_selector("#settings-ab-save")
    page.locator("#settings-ab-endpoint").fill("192.168.1.20:7890")
    page.locator("#settings-ab-username").fill("user")
    page.locator("#settings-ab-password").fill("save-canary")
    page.locator("#settings-ab-save").click()
    page.wait_for_timeout(150)
    assert len(puts) == 1
    assert puts[0]["config"]["base_url"] == "http://192.168.1.20:7890"
    assert "save-canary" not in page.locator("body").inner_text()


@pytest.mark.browser
def test_unconfigured_recovery_has_no_external_verify_or_probe(page, live_server_url):
    item = _recovery_item("tracking-a", "未绑定恢复", revision=4)
    detail = {"ok": True, "result": _detail_payload(item)}
    external_calls: list[str] = []

    def handler(route, request):
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
            route.fulfill(json={"ok": True, "result": {"configured": False, "credential_present": False, "connection_ref": None, "configuration_revision": 0, "connection_status": "UNCONFIGURED"}}); return
        if request.method == "GET" and path == "/tracking/items":
            route.fulfill(json={"ok": True, "result": {"items": [item], "summary": {"total": 1}, "warnings": []}}); return
        if request.method == "GET" and path == "/tracking/items/tracking-a":
            route.fulfill(json=detail); return
        if request.method == "POST":
            external_calls.append(path)
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
    page.wait_for_selector("#tracking-recover-auto")
    assert page.locator("#tracking-recover-verify").count() == 0
    assert external_calls == []
    secret = "unbound-canary"
    assert secret not in page.locator("body").inner_text()
    assert secret not in page.evaluate("() => location.href + JSON.stringify(history.state) + JSON.stringify(localStorage) + JSON.stringify(sessionStorage)")


@pytest.mark.browser
def test_settings_delete_requires_confirmation_and_then_tracking_degrades(page, live_server_url):
    ref = "11111111-1111-4111-8111-111111111111"
    deletes = 0

    def handler(route, request):
        nonlocal deletes
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
            configured = deletes == 0
            route.fulfill(json={"ok": True, "result": {"configured": configured, "credential_present": configured, "connection_ref": ref if configured else None, "configuration_revision": 3 if configured else 0, "connection_status": "CONFIGURED" if configured else "UNCONFIGURED"}}); return
        if request.method == "DELETE" and path == "/settings/autobangumi":
            deletes += 1
            route.fulfill(json={"ok": True, "result": {"configured": False, "credential_present": False, "connection_ref": None, "configuration_revision": 0, "connection_status": "UNCONFIGURED"}}); return
        if request.method == "GET" and path == "/tracking/items":
            route.fulfill(json={"ok": True, "result": {"items": [], "summary": {"total": 0}, "warnings": []}}); return
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/settings")
    page.wait_for_selector("#settings-ab-delete")
    page.locator("#settings-ab-delete").click()
    expect(page.locator(".confirm-dialog")).to_be_visible()
    page.locator(".confirm-dialog .secondary-button, .confirm-dialog .cancel-button").first.click()
    assert deletes == 0
    page.locator("#settings-ab-delete").click()
    page.locator(".confirm-dialog .danger-button").click()
    page.wait_for_timeout(100)
    assert deletes == 1
    page.goto(f"{live_server_url}/app/tracking")
    page.wait_for_selector("#tracking-probe-saved")
    assert page.locator("#tracking-probe-saved").is_disabled()


@pytest.mark.browser
@pytest.mark.parametrize("action", ["MARK_SUCCEEDED", "MARK_FAILED"])
def test_manual_recovery_is_local_and_confirmed(page, live_server_url, action):
    item = _recovery_item("tracking-a", "人工恢复", revision=4)
    item["available_actions"] = [{"code": action, "label": action, "style": "PRIMARY", "requires_confirmation": True, "target_scopes": []}]
    calls: list[dict] = []

    def handler(route, request):
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
            route.fulfill(json={"ok": True, "result": {"configured": False, "credential_present": False, "connection_ref": None, "configuration_revision": 0, "connection_status": "UNCONFIGURED"}}); return
        if request.method == "GET" and path == "/tracking/items":
            route.fulfill(json={"ok": True, "result": {"items": [item], "summary": {"total": 1}, "warnings": []}}); return
        if request.method == "GET" and path == "/tracking/items/tracking-a":
            route.fulfill(json={"ok": True, "result": _detail_payload(item)}); return
        if request.method == "POST" and path.endswith("/recover"):
            calls.append(request.post_data_json or {})
            route.fulfill(json={"ok": True, "result": {"tracking_id": "tracking-a", "action": action, "outcome": "SUCCEEDED", "checked_revision": 4, "next_revision": 5, "needs_manual": False, "tracking": item}}); return
        if request.method == "POST":
            raise AssertionError(path)
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
    selector = f"#tracking-recover-{'succeeded' if action == 'MARK_SUCCEEDED' else 'failed'}"
    page.wait_for_selector(selector)
    page.locator(selector).click()
    expect(page.locator(".confirm-dialog")).to_be_visible()
    page.locator(".confirm-dialog .danger-button, .confirm-dialog .primary-button").last.click()
    page.wait_for_timeout(100)
    assert calls == [{"expected_revision": 4, "action": action, "confirm": True}]
