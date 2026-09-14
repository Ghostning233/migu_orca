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
    page.goto(f"{live_server_url}/app/add")
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
    page.goto(f"{live_server_url}/app/add")
    page.wait_for_selector(".app-title")
    expect(page.locator(".pending-badge")).to_have_text("2")
    assert "2" in page.locator(".workspace-status").inner_text()
