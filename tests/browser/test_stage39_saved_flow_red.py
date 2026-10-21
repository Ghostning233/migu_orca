"""Stage 39 browser red tests for the retired credential boundary."""

import time

import pytest
from playwright.sync_api import expect

from tests.browser.saved_tracking_fixtures import (
    _detail_payload,
    _item,
    _management_actions,
    _modify_actions,
    _probe_capabilities,
    _recovery_item,
    _status_groups,
    _status_groups_for,
    _summary,
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
def test_settings_draft_test_save_locks_and_tracking_summary_is_non_sensitive(page, live_server_url):
    """Real Chromium journey: current draft test precedes save; secrets never leak."""
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
                        "configured": False,
                        "credential_present": False,
                        "connection_ref": None,
                        "configuration_revision": 0,
                        "connection_status": "UNCONFIGURED",
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
        if request.method == "POST" and path.startswith("/settings/autobangumi/test"):
            captured.append(("test", request.post_data_json))
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "success": True, "summary": {"reachable": True}, "error": None,
                    },
                }
            )
            return
        route.continue_()

    page.route("**/api/v1/**", api)
    page.goto(f"{live_server_url}/app/settings")
    page.wait_for_selector("#settings-heading")
    page.locator("#settings-ab-endpoint").fill("ab.example.invalid")
    page.locator("#settings-ab-username").fill("browser-user")
    page.locator("#settings-ab-password").fill(secret)
    page.locator("#settings-ab-test").click()
    expect(page.locator("#settings-ab-save")).to_be_enabled()
    page.locator("#settings-ab-save").click()
    expect(page.locator("#settings-ab-save-form .status-alert")).to_contain_text("已保存")
    assert captured[0][0] == "test"
    assert captured[1][0] == "save"
    assert "fallback_enabled" not in captured[0][1]["config"]
    assert secret not in page.locator("body").inner_text()
    assert secret not in page.url
    stored = page.evaluate(
        "() => ({local: JSON.stringify(localStorage), session: JSON.stringify(sessionStorage), history: location.href})"
    )
    assert secret not in str(stored)

    # A new page retires the probe entry but keeps the read-only capability
    # current automatically; it never triggers a business action.
    page.goto(f"{live_server_url}/app/tracking")
    page.wait_for_selector("#tracking-overview")
    expect(page.locator("#tracking-probe-saved")).to_have_count(0)
    expect(page.locator("#tracking-overview")).to_be_visible()
    assert secret not in page.locator("body").inner_text()


@pytest.mark.browser
@pytest.mark.parametrize(
    ("action", "selector", "setup"),
    [
        ("MODIFY", "#tracking-modify-subscription-submit", "modify"),
        ("SET_ENABLED", "#tracking-set-enabled-submit", "enabled"),
        ("REFRESH_RSS", "#tracking-refresh-rss-submit", "refresh"),
    ],
)
def test_saved_management_actions_send_only_bound_connection_fields(page, live_server_url, action, selector, setup):
    """Each management action is reached from the saved connection with no credential snapshot."""
    ref = "11111111-1111-4111-8111-111111111111"
    captured: list[dict] = []
    actions = _modify_actions() + _management_actions("ACTIVE")
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
                            "inactive": 0, "needs_attention": 0,
                            "unreadable": 0,
                        },
                        "status_groups": _status_groups(active=1),
                        "warnings": [],
                    },
                }
            )
            return
        if request.method == "POST" and path == "/tracking/sync":
            # #229 F1: the page entry runs one read-only sync; answer it locally
            # so this case stays hermetic. A partial result keeps the case's own
            # list and detail exactly as they were.
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "sync_status": "PARTIAL",
                        "checked_at": "2026-10-21T00:00:00Z",
                        "capabilities": _probe_capabilities(),
                        "summary": {"checked": 0, "created": 0, "updated": 0, "unchanged": 0,
                                    "ignored": 0, "failed": 1, "unreadable": 0},
                        "warnings": [],
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
    # #229 retires the manual sync entry; the action itself only renders once the
    # saved connection summary is adopted.
    page.wait_for_selector(selector)
    page.locator(selector).scroll_into_view_if_needed()
    if setup == "modify":
        page.locator("#tracking-modify-title-enabled").check()
        page.locator("#tracking-modify-title").fill("新标题")
    elif setup == "enabled":
        # Issue #89: enable/disable always addresses the controlled external
        # anime subscription, so there is no scope choice to make.
        assert page.locator("#tracking-set-enabled-scope-SUBSCRIPTION").count() == 0
    page.locator(selector).click()
    page.wait_for_selector(".confirm-dialog", timeout=10_000)
    # Cancelling the impact confirmation sends zero requests.
    page.locator(".confirm-dialog .cancel-button, .confirm-dialog .secondary-button").first.click(timeout=2000)
    page.wait_for_timeout(50)
    assert captured == []
    page.locator(selector).click()
    page.wait_for_selector(".confirm-dialog", timeout=10_000)
    page.locator(".confirm-dialog .danger-button, .confirm-dialog .primary-button").last.click(timeout=2000)
    page.wait_for_timeout(500)
    assert captured, action
    body = captured[-1]
    assert body["connection_ref"] == ref
    assert body["configuration_revision"] == 3
    assert "ab_config" not in body and "password" not in str(body)


@pytest.mark.browser
def test_page_entry_runs_one_read_only_sync_with_the_saved_connection(page, live_server_url):
    """#229 F1: entering the page is the trigger — one read-only sync bound to
    the saved connection, with no probe, no confirmation dialog and no manual
    entry left behind."""
    ref = "11111111-1111-4111-8111-111111111111"
    calls: list[dict] = []
    item = {**_item("tracking-a", "测试番"), "available_actions": [], "revision": 1}

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
                            "inactive": 0, "needs_attention": 0,
                            "unreadable": 0,
                        },
                        "status_groups": _status_groups_for([item]),
                        "warnings": [],
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
                        "checked_at": "2026-10-21T00:00:00Z",
                        "capabilities": _probe_capabilities(),
                        "summary": {"checked": 1, "created": 0, "updated": 0, "unchanged": 1, "ignored": 2},
                        "items": [item],
                    },
                }
            )
            return
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/tracking")
    page.wait_for_selector("#tracking-overview")
    # A degraded result that ignored strangers is reported in the bounded area.
    expect(page.locator("#tracking-sync-status")).to_contain_text("忽略 2 条不属于 MiGuOrca 管理的外部订阅")

    # One entry, one read-only sync bound to the saved connection.
    assert calls == [{"connection_ref": ref, "configuration_revision": 3, "confirm": True}]
    expect(page.locator("#tracking-sync")).to_have_count(0)
    expect(page.locator("#tracking-probe-saved")).to_have_count(0)
    assert page.locator(".confirm-dialog").count() == 0


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
                        "connection_status": "VERIFIED",
                        # Stage 39: loading never probes; the saved summary is the
                        # only capability source (here: last proven generation).
                        "capabilities": _probe_capabilities(),
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
                            "inactive": 0, "needs_attention": 1,
                            "unreadable": 0,
                        },
                        "status_groups": _status_groups(attention=1),
                        "warnings": [],
                    },
                }
            )
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
    page.wait_for_selector("#tracking-recover-verify")
    page.locator("#tracking-recover-verify").click()
    expect(page.locator(".confirm-dialog-message")).to_contain_text("只读核对")
    page.locator(".confirm-dialog-actions button").filter(has_text="确认只读核验").click()
    page.wait_for_selector("#tracking-recovery-result")
    assert calls == [
        {
            "expected_revision": 4,
            "action": "VERIFY_EXTERNAL",
            "connection_ref": ref,
            "configuration_revision": 3,
        }
    ]
    expect(page.locator("#tracking-recovery-result")).to_contain_text("独立核对")
    expect(page.locator("#tracking-recovery-result")).not_to_contain_text("RECOVERY_REQUIRED")
    assert not any(
        endpoint in path
        for path in writes
        for endpoint in ("/submit", "/retry", "/modify", "/set-enabled", "/refresh")
    )
    assert secret not in page.locator("body").inner_text()
    assert secret not in page.url
    assert secret not in page.evaluate(
        "() => location.href + JSON.stringify(history.state) + JSON.stringify(localStorage) + JSON.stringify(sessionStorage)"
    )
    assert secret not in " ".join(console_messages)


@pytest.mark.browser
def test_settings_cas_conflict_rereads_summary_without_resubmitting(page, live_server_url):
    gets = 0
    puts = 0

    def route_api(route, request):
        nonlocal gets, puts
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
            gets += 1
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "configured": False,
                        "credential_present": False,
                        "connection_ref": None,
                        "configuration_revision": gets - 1,
                        "connection_status": "UNCONFIGURED",
                    },
                }
            )
            return
        if request.method == "POST" and path == "/settings/autobangumi/test":
            route.fulfill(json={"ok": True, "result": {"success": True, "summary": {"reachable": True}, "error": None}})
            return
        if request.method == "PUT" and path == "/settings/autobangumi":
            puts += 1
            route.fulfill(status=409, json={"ok": False, "error_type": "configuration_conflict"})
            return
        route.continue_()

    page.route("**/api/v1/**", route_api)
    page.goto(f"{live_server_url}/app/settings")
    page.wait_for_selector("#settings-ab-save-form")
    page.locator("#settings-ab-endpoint").fill("192.168.1.20")
    page.locator("#settings-ab-port").fill("7890")
    page.locator("#settings-ab-username").fill("user")
    page.locator("#settings-ab-password").fill("cas-canary")
    page.locator("#settings-ab-test").click()
    page.locator("#settings-ab-save").click()
    expect(page.locator("#settings-ab-save-form [role=alert]")).to_contain_text("配置已变化")
    assert puts == 1
    assert gets >= 2
    assert page.locator("#settings-ab-password").input_value() == "cas-canary"


@pytest.mark.browser
def test_saved_summary_survives_refresh_and_navigation_without_settings_probe(page, live_server_url):
    """Settings no longer probes saved refs; the safe summary remains non-sensitive."""
    ref = "11111111-1111-4111-8111-111111111111"
    secret = "probe-failure-canary"
    def handler(route, request):
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
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
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/settings")
    # 已保存连接摘要是异步读取的：用自动重试断言等待按钮真正可用，
    # 而不是在摘要返回前读一次 is_enabled()。
    expect(page.locator("#settings-ab-delete")).to_be_enabled()
    page.reload()
    expect(page.locator("#settings-ab-delete")).to_be_enabled()
    page.goto(f"{live_server_url}/app/tracking")
    page.wait_for_selector("#tracking-overview")
    # B1: no probe entry on the tracking page any more; only the safe saved
    # connection summary (and its read-only capability) is loaded.
    expect(page.locator("#tracking-probe-saved")).to_have_count(0)
    expect(page.locator("#tracking-overview")).to_be_visible()
    assert secret not in page.locator("body").inner_text()
    assert secret not in page.evaluate(
        "() => location.href + JSON.stringify(history.state) + JSON.stringify(localStorage) + JSON.stringify(sessionStorage)"
    )


@pytest.mark.browser
def test_tracking_page_load_syncs_once_without_probing_or_writing(page, live_server_url):
    """#229 F1 + Stage 39 + B1: each entry reads the summary and runs exactly one
    read-only sync; it never probes and never starts a business write."""
    ref = "11111111-1111-4111-8111-111111111111"
    posts: list[str] = []

    def handler(route, request):
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
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
        if request.method == "GET" and path == "/tracking/items":
            route.fulfill(json={"ok": True, "result": {"items": [], "summary": {"total": 0}, "status_groups": _status_groups_for([]), "warnings": []}})
            return
        if request.method == "POST" and path == "/tracking/sync":
            posts.append(path)
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "sync_status": "COMPLETE",
                        "checked_at": "2026-10-21T00:00:00Z",
                        "capabilities": _probe_capabilities(),
                        "summary": {"checked": 0, "created": 0, "updated": 0, "unchanged": 0, "ignored": 0},
                        "items": [],
                    },
                }
            )
            return
        if request.method == "POST":
            posts.append(path)
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/tracking")
    page.wait_for_selector("#tracking-overview")
    expect(page.locator(".global-notification")).to_contain_text("同步完成")
    page.reload()
    page.wait_for_selector("#tracking-overview")
    expect(page.locator(".global-notification")).to_contain_text("同步完成")

    # One entry, one read-only sync; no probe and no business write at all.
    assert posts == ["/tracking/sync", "/tracking/sync"], posts
    expect(page.locator("#tracking-probe-saved")).to_have_count(0)
    expect(page.locator("#tracking-sync")).to_have_count(0)
    assert page.locator(".confirm-dialog").count() == 0


@pytest.mark.browser
def test_tracking_capability_degrade_does_not_hide_management_actions(page, live_server_url):
    """Issue #89: a diagnostic probe never gates a server-projected action."""
    ref = "11111111-1111-4111-8111-111111111111"
    item = {**_item("tracking-a", "降级番"), "available_actions": _management_actions("ACTIVE"), "revision": 1}
    detail = {
        "ok": True,
        "result": {
            **item,
            "origin": "single",
            "batch_id": None,
            "created_at": "2026-09-01T00:00:00Z",
            "updated_at": "2026-09-01T00:00:00Z",
            "last_synced_at": None,
            "safe_info": None,
            "current_operation": None,
            "revalidation_issues": [],
            "external_mapping": None,
            "audit_events": [],
            "warnings": [],
        },
    }
    writes: list[str] = []

    def handler(route, request):
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
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
        if request.method == "GET" and path == "/tracking/items":
            route.fulfill(json={"ok": True, "result": {"items": [item], "summary": _summary(1), "status_groups": _status_groups_for([item]), "warnings": []}})
            return
        if request.method == "GET" and path == "/tracking/items/tracking-a":
            route.fulfill(json=detail)
            return
        if request.method == "POST" and path == "/settings/autobangumi/probe":
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        **_probe_capabilities(),
                        "subscription_modify": "UNSUPPORTED",
                        "subscription_enable": "UNSUPPORTED",
                        "rss_refresh": "UNSUPPORTED",
                    },
                }
            )
            return
        if request.method == "POST" and path == "/tracking/sync":
            # #229 F1: the page entry runs one read-only sync; answer it locally
            # so this case stays hermetic. A partial result keeps the case's own
            # list and detail exactly as they were.
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "sync_status": "PARTIAL",
                        "checked_at": "2026-10-21T00:00:00Z",
                        "capabilities": _probe_capabilities(),
                        "summary": {"checked": 0, "created": 0, "updated": 0, "unchanged": 0,
                                    "ignored": 0, "failed": 1, "unreadable": 0},
                        "warnings": [],
                    },
                }
            )
            return
        if request.method == "POST" and "/tracking/items/" in path:
            writes.append(path)
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
    page.wait_for_selector("#tracking-overview")
    page.wait_for_selector(".tracking-inspector-content")

    # No probe was clicked: the saved connection already offers every action the
    # server projected for this record.
    expect(page.locator("#tracking-set-enabled-submit")).to_be_enabled()
    expect(page.locator("#tracking-refresh-rss-submit")).to_be_enabled()
    # Merely looking at the page writes nothing.
    assert writes == []

    # A diagnostic "unsupported" probe does not hide them either.
    page.wait_for_timeout(150)
    expect(page.locator("#tracking-set-enabled-submit")).to_be_enabled()
    expect(page.locator("#tracking-refresh-rss-submit")).to_be_enabled()
    assert writes == []


@pytest.mark.browser
@pytest.mark.parametrize(
    ("status", "code", "selector"),
    [("PENDING_SUBMIT", "SUBMIT", "#tracking-submit"), ("SUBMIT_FAILED", "RETRY", "#tracking-retry")],
)
def test_saved_submit_and_retry_use_one_explicit_generation(page, live_server_url, status, code, selector):
    ref = "11111111-1111-4111-8111-111111111111"
    body_item = {
        **_item("tracking-a", "提交番", status),
        "status": status,
        "available_actions": [
            {"code": code, "label": code, "style": "PRIMARY", "requires_confirmation": True, "target_scopes": []}
        ],
    }
    detail = {"ok": True, "result": {**_detail_payload(body_item), "revision": 4}}
    calls: list[dict] = []

    def handler(route, request):
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
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
        if request.method == "GET" and path == "/tracking/items":
            route.fulfill(json={"ok": True, "result": {"items": [body_item], "summary": {"total": 1}, "status_groups": _status_groups_for([body_item]), "warnings": []}})
            return
        if request.method == "GET" and path == "/tracking/items/tracking-a":
            route.fulfill(json=detail)
            return
        if request.method == "POST" and path == "/settings/autobangumi/probe":
            route.fulfill(json={"ok": True, "result": _probe_capabilities()})
            return
        if (
            request.method == "POST"
            and path.endswith("/submit")
            or request.method == "POST"
            and path.endswith("/retry")
        ):
            calls.append(request.post_data_json or {})
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "tracking_id": "tracking-a",
                        "action": code,
                        "outcome": "OUTCOME_UNKNOWN",
                        "needs_manual": True,
                        "tracking": body_item,
                    },
                }
            )
            return
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
    page.wait_for_selector("#tracking-overview")
    page.wait_for_selector(selector)
    page.locator(selector).click()
    expect(page.locator(".confirm-dialog")).to_be_visible()
    page.locator(".confirm-dialog .cancel-button, .confirm-dialog .secondary-button").first.click()
    assert calls == []
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
def test_recovery_entry_is_the_read_only_verification_only(page, live_server_url):
    """Issue #228: the retired local recovery entries are gone from the page.

    Without a saved connection the panel still explains why the read-only
    verification is unavailable and offers no action at all; the removed
    standalone revalidation is not rendered anywhere either.
    """
    item = _recovery_item("tracking-a", "本地恢复", revision=4)
    detail = {"ok": True, "result": _detail_payload(item)}
    calls: list[tuple[str, dict]] = []

    def handler(route, request):
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "configured": False,
                        "credential_present": False,
                        "connection_ref": None,
                        "configuration_revision": 0,
                        "connection_status": "UNCONFIGURED",
                    },
                }
            )
            return
        if request.method == "GET" and path == "/tracking/items":
            route.fulfill(json={"ok": True, "result": {"items": [item], "summary": _summary(1), "status_groups": _status_groups_for([item]), "warnings": []}})
            return
        if request.method == "GET" and path == "/tracking/items/tracking-a":
            route.fulfill(json=detail)
            return
        if request.method == "POST":
            calls.append((path, request.post_data_json or {}))
            route.fulfill(json={"ok": True, "result": {}})
            return
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
    page.wait_for_selector("#tracking-recovery-heading")
    expect(page.locator("#tracking-recovery-heading")).to_have_text("结果待确认")
    # No local recovery entry survives, and the read-only verification needs the
    # saved connection this page does not have.
    for retired in ("#tracking-recover-auto", "#tracking-recover-succeeded", "#tracking-recover-failed"):
        assert page.locator(retired).count() == 0
    assert page.locator("#tracking-recover-verify").count() == 0
    expect(page.locator("#tracking-recovery-heading").locator("..")).to_contain_text(
        "只读外部核验需要先在页面连接 Auto Bangumi"
    )
    # The removed standalone revalidation is not rendered anywhere.
    assert page.locator("#tracking-revalidate").count() == 0
    assert calls == []


@pytest.mark.browser
def test_settings_bare_endpoint_is_normalized_and_navigation_cancels_save(page, live_server_url):
    ref = "11111111-1111-4111-8111-111111111111"
    puts: list[dict] = []

    def handler(route, request):
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "configured": False,
                        "credential_present": False,
                        "connection_ref": None,
                        "configuration_revision": 0,
                        "connection_status": "UNCONFIGURED",
                    },
                }
            )
            return
        if request.method == "POST" and path == "/settings/autobangumi/test":
            route.fulfill(json={"ok": True, "result": {"success": True, "summary": {"reachable": True}, "error": None}})
            return
        if request.method == "PUT" and path == "/settings/autobangumi":
            puts.append(request.post_data_json or {})
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "configured": True,
                        "credential_present": True,
                        "connection_ref": ref,
                        "configuration_revision": 1,
                        "connection_status": "CONFIGURED",
                    },
                }
            )
            return
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/settings")
    page.wait_for_selector("#settings-heading")
    page.wait_for_selector("#settings-ab-save")
    page.locator("#settings-ab-endpoint").fill("192.168.1.20")
    page.locator("#settings-ab-port").fill("7890")
    page.locator("#settings-ab-username").fill("user")
    page.locator("#settings-ab-password").fill("cancel-canary")
    page.goto(f"{live_server_url}/app/tracking")
    assert puts == []
    page.goto(f"{live_server_url}/app/settings")
    page.wait_for_selector("#settings-ab-save")
    page.locator("#settings-ab-endpoint").fill("192.168.1.20")
    page.locator("#settings-ab-port").fill("7890")
    page.locator("#settings-ab-username").fill("user")
    page.locator("#settings-ab-password").fill("save-canary")
    page.locator("#settings-ab-test").click()
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
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "configured": False,
                        "credential_present": False,
                        "connection_ref": None,
                        "configuration_revision": 0,
                        "connection_status": "UNCONFIGURED",
                    },
                }
            )
            return
        if request.method == "GET" and path == "/tracking/items":
            route.fulfill(json={"ok": True, "result": {"items": [item], "summary": {"total": 1}, "status_groups": _status_groups_for([item]), "warnings": []}})
            return
        if request.method == "GET" and path == "/tracking/items/tracking-a":
            route.fulfill(json=detail)
            return
        if request.method == "POST":
            external_calls.append(path)
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
    page.wait_for_selector("#tracking-recovery-heading")
    assert page.locator("#tracking-recover-auto").count() == 0
    assert page.locator("#tracking-recover-verify").count() == 0
    assert external_calls == []
    secret = "unbound-canary"
    assert secret not in page.locator("body").inner_text()
    assert secret not in page.evaluate(
        "() => location.href + JSON.stringify(history.state) + JSON.stringify(localStorage) + JSON.stringify(sessionStorage)"
    )


@pytest.mark.browser
def test_settings_delete_requires_confirmation_and_then_tracking_degrades(page, live_server_url):
    ref = "11111111-1111-4111-8111-111111111111"
    deletes = 0
    posts: list[str] = []

    def handler(route, request):
        nonlocal deletes
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "POST":
            posts.append(path)
        if request.method == "GET" and path == "/settings/autobangumi":
            configured = deletes == 0
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "configured": configured,
                        "credential_present": configured,
                        "connection_ref": ref if configured else None,
                        "configuration_revision": 3 if configured else 0,
                        "connection_status": "CONFIGURED" if configured else "UNCONFIGURED",
                    },
                }
            )
            return
        if request.method == "DELETE" and path == "/settings/autobangumi":
            deletes += 1
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "configured": False,
                        "credential_present": False,
                        "connection_ref": None,
                        "configuration_revision": 0,
                        "connection_status": "UNCONFIGURED",
                    },
                }
            )
            return
        if request.method == "GET" and path == "/tracking/items":
            route.fulfill(json={"ok": True, "result": {"items": [], "summary": {"total": 0}, "status_groups": _status_groups_for([]), "warnings": []}})
            return
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
    page.wait_for_selector("#tracking-overview")
    # Unconfigured: no probe entry, no manual sync entry and no automatic POST
    # (there is no saved connection to bind a read-only sync to).
    assert page.locator("#tracking-probe-saved").count() == 0
    assert page.locator("#tracking-sync").count() == 0
    assert posts == [], posts
    assert deletes == 1


@pytest.mark.browser
def test_submit_is_available_from_the_saved_connection_without_a_probe(page, live_server_url):
    """Issue #86: submission needs the saved connection, never a probe click."""
    ref = "11111111-1111-4111-8111-111111111111"
    probes: list[str] = []
    item = {
        **_item("tracking-a", "已保存连接"),
        "available_actions": [
            {"code": "SUBMIT", "label": "提交", "style": "PRIMARY", "requires_confirmation": True, "target_scopes": []}
        ],
    }

    def handler(route, request):
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "POST" and path.endswith("/probe"):
            probes.append(path)
            route.fulfill(json={"ok": True, "result": _probe_capabilities()})
            return
        if request.method == "GET" and path == "/settings/autobangumi":
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
        if request.method == "GET" and path == "/tracking/items":
            route.fulfill(json={"ok": True, "result": {"items": [item], "summary": _summary(1), "status_groups": _status_groups_for([item]), "warnings": []}})
            return
        if request.method == "GET" and path == "/tracking/items/tracking-a":
            route.fulfill(json={"ok": True, "result": _detail_payload(item)})
            return
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
    page.wait_for_selector("#tracking-submit")
    expect(page.locator("#tracking-submit")).to_be_visible()
    expect(page.locator("#tracking-submit")).to_be_enabled()
    # Nothing is probed: submission needs only the saved connection, never a
    # probe click (issue #86), and capability discovery is not a submission gate.
    assert probes == []


@pytest.mark.browser
def test_management_unknown_keeps_lock_and_does_not_resend(page, live_server_url):
    ref = "11111111-1111-4111-8111-111111111111"
    ref_b = "22222222-2222-4222-8222-222222222222"
    summary_reads = 0
    item = {**_item("tracking-a", "未知管理"), "available_actions": _modify_actions()}
    detail = {
        "ok": True,
        "result": {
            **_detail_payload(item),
            "external_mapping": {"match_reason": "标题", "enabled": True, "external_deleted": False},
        },
    }
    calls: list[dict] = []

    def handler(route, request):
        nonlocal summary_reads
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
            summary_reads += 1
            current_ref = ref if summary_reads <= 2 else ref_b
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "configured": True,
                        "credential_present": True,
                        "connection_ref": current_ref,
                        "configuration_revision": summary_reads + 2,
                        "connection_status": "CONFIGURED",
                    },
                }
            )
            return
        if request.method == "GET" and path == "/tracking/items":
            route.fulfill(json={"ok": True, "result": {"items": [item], "summary": {"total": 1}, "status_groups": _status_groups_for([item]), "warnings": []}})
            return
        if request.method == "GET" and path == "/tracking/items/tracking-a":
            route.fulfill(json=detail)
            return
        if request.method == "POST" and path == "/settings/autobangumi/probe":
            route.fulfill(json={"ok": True, "result": _probe_capabilities()})
            return
        if request.method == "POST" and "/tracking/items/tracking-a/" in path:
            calls.append(request.post_data_json or {})
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "action": "MODIFY",
                        "management_status": "UNKNOWN",
                        "needs_manual": True,
                        "safe_message": "结果待确认，请人工恢复",
                        "operation_id": "op-unknown",
                        "tracking": item,
                    },
                }
            )
            return
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
    page.wait_for_selector("#tracking-overview")
    page.wait_for_selector("#tracking-modify-subscription-submit")
    page.locator("#tracking-modify-title-enabled").check()
    page.locator("#tracking-modify-title").fill("未知管理更新")
    page.locator("#tracking-modify-subscription-submit").click()
    if page.locator(".confirm-dialog").count():
        page.locator(".confirm-dialog .danger-button, .confirm-dialog .primary-button").last.click()
    page.wait_for_timeout(150)
    assert len(calls) == 1 and calls[0]["connection_ref"] == ref and "password" not in str(calls[0])
    expect(page.locator("#tracking-modify-subscription-submit")).to_be_disabled()
    page.reload()
    page.wait_for_selector("#tracking-overview")
    assert len(calls) == 1


@pytest.mark.browser
def test_generation_switch_does_not_reuse_old_management_intent(page, live_server_url):
    refs = ["11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"]
    reads = 0
    writes: list[dict] = []
    item = {**_item("tracking-a", "换代映射"), "available_actions": _modify_actions()}

    def handler(route, request):
        nonlocal reads
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
            ref = refs[min(reads, 1)]
            reads += 1
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "configured": True,
                        "credential_present": True,
                        "connection_ref": ref,
                        "configuration_revision": reads,
                        "connection_status": "CONFIGURED",
                    },
                }
            )
            return
        if request.method == "GET" and path == "/tracking/items":
            route.fulfill(json={"ok": True, "result": {"items": [item], "summary": {"total": 1}, "status_groups": _status_groups_for([item]), "warnings": []}})
            return
        if request.method == "GET" and path == "/tracking/items/tracking-a":
            route.fulfill(json={"ok": True, "result": _detail_payload(item)})
            return
        if request.method == "POST" and "/tracking/items/tracking-a/" in path:
            writes.append(request.post_data_json or {})
            route.continue_()
            return
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
    page.wait_for_selector("#tracking-overview")
    page.reload()
    page.wait_for_selector("#tracking-overview")
    page.reload()
    page.wait_for_selector("#tracking-overview")
    assert (
        page.locator("#tracking-modify-subscription-submit").count() == 0
        or page.locator("#tracking-modify-subscription-submit").is_disabled()
    )
    assert writes == []


@pytest.mark.browser
def test_management_generation_refresh_keeps_external_id_unbound(page, live_server_url):
    """A changed saved generation is never silently rebound to an old mapping."""
    ref = "33333333-3333-4333-8333-333333333333"
    calls: list[str] = []

    def handler(route, request):
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "configured": True,
                        "credential_present": True,
                        "connection_ref": ref,
                        "configuration_revision": 9,
                        "connection_status": "CONFIGURED",
                    },
                }
            )
            return
        if request.method == "GET" and path == "/tracking/items":
            route.fulfill(json={"ok": True, "result": {"items": [], "summary": {"total": 0}, "status_groups": _status_groups_for([]), "warnings": []}})
            return
        if request.method == "POST":
            calls.append(path)
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/tracking")
    page.wait_for_selector("#tracking-overview")
    page.reload()
    page.wait_for_selector("#tracking-overview")
    # #229 F1: each entry runs exactly one automatic read-only sync; no probe,
    # recovery, submit or management write runs on load.
    assert [call for call in calls if call != "/tracking/sync"] == [], calls
    assert calls.count("/tracking/sync") == 2, calls


@pytest.mark.browser
@pytest.mark.parametrize("status_code", [("PENDING_SUBMIT", "SUBMIT"), ("SUBMIT_FAILED", "RETRY")])
def test_submit_retry_singleflight_holds_unknown_lock_across_generation(page, live_server_url, status_code):
    status, code = status_code
    ref_a = "11111111-1111-4111-8111-111111111111"
    ref_b = "22222222-2222-4222-8222-222222222222"
    settings_reads = 0
    posts: list[dict] = []
    item = {
        **_item("tracking-a", "单飞提交", status),
        "status": status,
        "available_actions": [
            {"code": code, "label": code, "style": "PRIMARY", "requires_confirmation": True, "target_scopes": []}
        ],
    }

    def handler(route, request):
        nonlocal settings_reads
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
            settings_reads += 1
            ref = ref_a if settings_reads <= 2 else ref_b
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "configured": True,
                        "credential_present": True,
                        "connection_ref": ref,
                            "configuration_revision": 1 if settings_reads <= 2 else settings_reads,
                        "connection_status": "CONFIGURED",
                    },
                }
            )
            return
        if request.method == "GET" and path == "/tracking/items":
            route.fulfill(json={"ok": True, "result": {"items": [item], "summary": {"total": 1}, "status_groups": _status_groups_for([item]), "warnings": []}})
            return
        if request.method == "GET" and path == "/tracking/items/tracking-a":
            route.fulfill(json={"ok": True, "result": _detail_payload(item)})
            return
        if request.method == "POST" and (path.endswith("/submit") or path.endswith("/retry")):
            posts.append(request.post_data_json or {})
            time.sleep(0.35)
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "tracking_id": "tracking-a",
                        "action": code,
                        "outcome": "RECOVERY_REQUIRED",
                        "needs_manual": True,
                        "tracking": item,
                    },
                }
            )
            return
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
    page.wait_for_selector("#tracking-overview")
    selector = "#tracking-submit" if code == "SUBMIT" else "#tracking-retry"
    page.wait_for_selector(selector)
    page.locator(selector).click()
    page.wait_for_selector("#tracking-mode-continue", timeout=10_000)
    page.locator("#tracking-mode-continue").click()
    page.locator(selector).dblclick(force=True)
    page.wait_for_timeout(500)
    assert len(posts) == 1
    assert posts[0]["connection_ref"] == ref_a and posts[0]["configuration_revision"] == 1
    assert "ab_config" not in posts[0] and "password" not in str(posts[0])
    page.reload()
    page.wait_for_selector("#tracking-overview")
    assert len(posts) == 1


@pytest.mark.browser
def test_submit_unknown_lock_survives_new_generation_refresh(page, live_server_url):
    ref_a = "11111111-1111-4111-8111-111111111111"
    ref_b = "22222222-2222-4222-8222-222222222222"
    generation = 0
    posts: list[dict] = []
    item = {
        **_item("tracking-a", "代际提交"),
        "available_actions": [
            {"code": "SUBMIT", "label": "提交", "style": "PRIMARY", "requires_confirmation": True, "target_scopes": []}
        ],
    }

    def handler(route, request):
        nonlocal generation
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
            generation += 1
            ref = ref_a if generation <= 2 else ref_b
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "configured": True,
                        "credential_present": True,
                        "connection_ref": ref,
                        "configuration_revision": generation,
                        "connection_status": "CONFIGURED",
                    },
                }
            )
            return
        if request.method == "GET" and path == "/tracking/items":
            route.fulfill(json={"ok": True, "result": {"items": [item], "summary": _summary(1), "status_groups": _status_groups_for([item]), "warnings": []}})
            return
        if request.method == "GET" and path == "/tracking/items/tracking-a":
            route.fulfill(json={"ok": True, "result": _detail_payload(item)})
            return
        if request.method == "POST" and path.endswith("/submit"):
            posts.append(request.post_data_json or {})
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "tracking_id": "tracking-a",
                        "outcome": "VERIFYING_EXTERNAL",
                        "checked_revision": 1,
                        "next_revision": 2,
                        "checked_at": "2026-09-14T00:00:00Z",
                        "operation_id": "op-unknown",
                        "failure_category": "OUTCOME_UNKNOWN",
                        "issues": [],
                        "tracking": item,
                    },
                }
            )
            return
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
    # Issue #86: the saved connection offers submit without any probe click.
    page.wait_for_selector("#tracking-submit")
    expect(page.locator("#tracking-submit")).to_be_enabled()
    page.locator("#tracking-submit").click()
    page.wait_for_selector("#tracking-mode-continue", timeout=10_000)
    page.locator("#tracking-mode-continue").click()
    page.wait_for_timeout(200)
    assert len(posts) == 1 and posts[0]["connection_ref"] == ref_a
    # Issue #169: an indeterminate submit shows its 结果待确认 recovery copy in
    # place. The presentation's title is dialog-channel only, so the sentence
    # that must render here is the recovery message; the page must never claim
    # the submission succeeded.
    inspector = page.locator(".tracking-inspector")
    expect(inspector).to_contain_text("无法确认 Auto Bangumi 是否已创建订阅")
    expect(inspector).to_contain_text("请先使用恢复核验")
    expect(inspector).not_to_contain_text("已在 Auto Bangumi 创建外部订阅")

    # The indeterminate result is never resent on its own, even after the saved
    # generation changes and the page re-reads everything.
    page.reload()
    page.wait_for_selector("#tracking-submit")
    page.wait_for_timeout(300)
    assert len(posts) == 1


@pytest.mark.browser
def test_unknown_operation_after_configuration_change_cannot_verify(page, live_server_url):
    ref_a = "11111111-1111-4111-8111-111111111111"
    ref_b = "22222222-2222-4222-8222-222222222222"
    reads = 0
    calls: list[str] = []
    item = _recovery_item("tracking-a", "换绑未知", revision=4)

    def handler(route, request):
        nonlocal reads
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
            reads += 1
            changed = reads > 2
            ref = ref_b if changed else ref_a
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "configured": True,
                        "credential_present": True,
                        "connection_ref": ref,
                        "configuration_revision": reads,
                        "connection_status": "CONFIGURED",
                        # Only the original generation has an already-proven
                        # capability; the replacement has a cold cache.
                        "capabilities": None if changed else _probe_capabilities(),
                    },
                }
            )
            return
        if request.method == "GET" and path == "/tracking/items":
            route.fulfill(json={"ok": True, "result": {"items": [item], "summary": {"total": 1}, "status_groups": _status_groups_for([item]), "warnings": []}})
            return
        if request.method == "GET" and path == "/tracking/items/tracking-a":
            route.fulfill(json={"ok": True, "result": _detail_payload(item)})
            return
        if request.method == "POST" and path.endswith("/recover"):
            calls.append(path)
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
    page.wait_for_selector("#tracking-overview")
    page.wait_for_selector("#tracking-recover-verify")
    page.reload()
    page.wait_for_selector("#tracking-overview")
    # The replacement generation has no proven capability, so the page does not
    # offer the read-only verification again after the connection changed, and
    # it never verifies by itself.  (The server additionally rejects a rebind
    # request: tracking_saved_recovery_service_test owns that guard.)
    assert page.locator("#tracking-recover-verify").count() == 0
    assert calls == []

@pytest.mark.browser
def test_settings_states_the_saved_connection_capability_in_one_sentence(page, live_server_url):
    """#229 F3/AC6: the settings page carries exactly one plain capability
    sentence and never the technical capability field table."""
    page.goto(f"{live_server_url}/app/settings")
    note = page.locator("#settings-ab-capability-note")
    expect(note).to_have_count(1)
    expect(note).to_have_text("已保存连接可读取并管理受控外部订阅；提交前仍需逐次确认。")
    body = page.locator("body").inner_text()
    for field in ("探测状态", "subscription_list", "external_verify", "rss_refresh"):
        assert field not in body, field
