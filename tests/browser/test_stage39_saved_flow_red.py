"""Stage 39 browser red tests for the retired credential boundary."""

import pytest
from playwright.sync_api import expect


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
            route.fulfill(json={"ok": True, "result": {
                "configured": True, "credential_present": True, "connection_ref": ref,
                "configuration_revision": 3, "connection_status": "CONFIGURED",
            }})
            return
        if request.method == "PUT" and path.startswith("/settings/autobangumi"):
            captured.append(("save", request.post_data_json))
            route.fulfill(json={"ok": True, "result": {
                "configured": True, "credential_present": True, "connection_ref": ref,
                "configuration_revision": 3, "connection_status": "CONFIGURED",
            }})
            return
        if request.method == "POST" and path.startswith("/settings/autobangumi/probe"):
            captured.append(("probe", request.post_data_json))
            route.fulfill(json={"ok": True, "result": {
                "probe_status": "VERIFIED", "version": "3.1.18", "adapter": "legacy_3_1",
                "subscription_list": "SUPPORTED", "subscription_detail": "SUPPORTED",
                "subscription_submit": "SUPPORTED", "subscription_modify": "SUPPORTED",
                "subscription_enable": "SUPPORTED", "subscription_disable": "SUPPORTED",
                "subscription_delete": "SUPPORTED", "rss_list": "SUPPORTED", "rss_modify": "SUPPORTED",
                "rss_enable": "SUPPORTED", "rss_disable": "SUPPORTED", "rss_delete": "SUPPORTED",
                "rss_refresh": "SUPPORTED", "external_verify": "SUPPORTED",
                "checked_at": None, "safe_message": "已完成安全探测",
            }})
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
    stored = page.evaluate("() => ({local: JSON.stringify(localStorage), session: JSON.stringify(sessionStorage), history: location.href})")
    assert secret not in str(stored)

    # A new page reads only the safe summary. It does not automatically probe or act.
    page.goto(f"{live_server_url}/app/tracking")
    page.wait_for_selector("#tracking-overview")
    expect(page.locator("#tracking-probe-saved")).to_be_visible()
    assert len([kind for kind, _ in captured if kind == "probe"]) == 1
    assert secret not in page.locator("body").inner_text()
