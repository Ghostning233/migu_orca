from __future__ import annotations

import json

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser


def _envelope(result: object) -> str:
    return json.dumps({"ok": True, "result": result})


def test_global_status_unconfigured_and_settings_route(page: Page, live_server_url: str) -> None:
    def handle(route, request):
        if request.url.endswith("/settings/autobangumi"):
            route.fulfill(status=200, content_type="application/json", body=_envelope({
                "configured": False, "credential_present": False, "connection_ref": None,
                "configuration_revision": 0, "connection_status": "UNCONFIGURED",
            }))
        else:
            route.continue_()

    page.route("**/api/v1/settings/autobangumi", handle)
    page.goto(f"{live_server_url}/app/add?batch_id=profile-test")
    page.wait_for_selector(".app-title")
    expect(page.locator(".workspace-status")).to_contain_text("未配置")
    page.locator(".workspace-status").press("Enter")
    page.wait_for_url("**/app/settings")
    expect(page.locator("#settings-heading")).to_be_visible()


def test_badge_counts_items_only_and_hides_zero(page: Page, live_server_url: str) -> None:
    def handle(route, request):
        if request.url.endswith("/settings/autobangumi"):
            route.fulfill(status=200, content_type="application/json", body=_envelope({
                "configured": True, "credential_present": True, "connection_ref": "ref",
                "configuration_revision": 1, "connection_status": "CONFIGURED",
            }))
        elif "/tracking/items" in request.url:
            route.fulfill(status=200, content_type="application/json", body=_envelope({
                "items": [{"status": "PENDING_SUBMIT"}, {"status": "SUBMIT_FAILED"}, {"status": "DONE"}],
                "summary": {"pending": 0}, "warnings": [],
            }))
        else:
            route.continue_()

    page.route("**/api/v1/settings/autobangumi", handle)
    page.route("**/api/v1/tracking/items**", handle)
    page.goto(f"{live_server_url}/app/add?batch_id=failure-test")
    page.wait_for_selector(".app-title")
    expect(page.locator(".pending-badge")).to_have_text("2")
    assert "2" in page.locator(".workspace-status").inner_text()


@pytest.mark.parametrize(("connection_status", "label"), [
    ("CONFIGURED", "已配置"),
    ("VERIFIED", "连接可用"),
    ("ERROR", "需检查"),
])
def test_global_status_state_matrix(page: Page, live_server_url: str, connection_status: str, label: str) -> None:
    def handle(route, request):
        if request.url.endswith("/settings/autobangumi"):
            route.fulfill(status=200, content_type="application/json", body=_envelope({
                "configured": True, "credential_present": True, "connection_ref": "safe-ref",
                "configuration_revision": 3, "connection_status": connection_status,
            }))
        elif "/tracking/items" in request.url:
            route.fulfill(status=200, content_type="application/json", body=_envelope({"items": []}))
        else:
            route.continue_()

    page.route("**/api/v1/settings/autobangumi", handle)
    page.route("**/api/v1/tracking/items**", handle)
    page.goto(f"{live_server_url}/app/add")
    expect(page.locator(".workspace-status")).to_contain_text(label)


def test_profile_switch_uses_new_query_and_failure_never_fabricates_zero(page: Page, live_server_url: str) -> None:
    calls: list[str] = []

    def handle(route, request):
        if request.url.endswith("/settings/autobangumi"):
            route.fulfill(status=200, content_type="application/json", body=_envelope({
                "configured": True, "credential_present": True, "connection_ref": "safe-ref",
                "configuration_revision": 3, "connection_status": "VERIFIED",
            }))
        elif "/tracking/items" in request.url:
            calls.append(request.url)
            if "profile-b" in request.url:
                route.fulfill(status=200, content_type="application/json", body=_envelope({
                    "items": [{"status": "PENDING_SUBMIT"}, {"status": "SUBMIT_FAILED"}],
                }))
            else:
                route.fulfill(status=200, content_type="application/json", body=_envelope({"items": []}))
        else:
            route.continue_()

    page.route("**/api/v1/settings/autobangumi", handle)
    page.route("**/api/v1/tracking/items**", handle)
    page.goto(f"{live_server_url}/app/add")
    page.evaluate("localStorage.clear()")
    page.evaluate("localStorage.setItem('miguOrca.web.storageDir', 'profile-a')")
    page.reload()
    # The old profile is invalidated before the new profile's count is shown;
    # any later non-zero value must come from the current profile response.
    expect(page.locator(".pending-badge")).not_to_have_text("2")
    page.evaluate("localStorage.setItem('miguOrca.web.storageDir', 'profile-b')")
    page.reload()
    expect(page.locator(".pending-badge")).to_have_text("2")
    assert any("storage_dir=profile-b" in url for url in calls)


def test_list_failure_keeps_badge_unknown(page: Page, live_server_url: str) -> None:
    def handle(route, request):
        if "/tracking/items" in request.url:
            route.fulfill(status=503, content_type="application/json", body=_envelope({"items": []}))
        else:
            route.continue_()

    page.route("**/api/v1/tracking/items**", handle)
    page.goto(f"{live_server_url}/app/add")
    page.evaluate("localStorage.clear()")
    page.reload()
    expect(page.locator(".pending-badge")).not_to_have_text("2")



def test_status_entry_keyboard_brand_and_zoom_canary(page: Page, live_server_url: str) -> None:
    page.goto(f"{live_server_url}/app/add")
    page.locator(".workspace-status").focus()
    expect(page.locator(".workspace-status")).to_be_focused()
    page.locator(".workspace-status").press("Enter")
    page.wait_for_url("**/app/settings")
    page.locator(".brand-block").press("Enter")
    page.wait_for_url("**/app/add")
    page.set_viewport_size({"width": 1280, "height": 800})
    page.evaluate("document.body.style.zoom='200%'")
    expect(page.locator(".app-title")).to_be_visible()
    assert page.evaluate("location.pathname") == "/app/add"
    assert page.evaluate("Object.keys(localStorage).join(',')") == ""
    assert page.evaluate("Object.keys(sessionStorage).join(',')") == ""
