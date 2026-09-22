from __future__ import annotations

import json

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import preview_result_json
from tests.browser.test_app_workbench import (
    _candidate,
    _candidate_result_json,
    _preview_request,
    _register_generation_capture,
)

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
    expect(page.locator(".pending-badge")).to_have_count(0)
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
    expect(page.locator(".pending-badge")).to_have_count(0)



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


def test_profile_change_while_app_is_mounted_invalidates_held_old_list(page: Page, live_server_url: str) -> None:
    held_old = []
    a_calls = 0
    requests: list[str] = []

    def handle(route, request):
        if request.url.endswith("/settings/autobangumi"):
            route.fulfill(status=200, content_type="application/json", body=_envelope({
                "configured": True, "credential_present": True, "connection_ref": "ref-a",
                "configuration_revision": 1, "connection_status": "CONFIGURED",
            }))
        elif "/tracking/items" in request.url:
            requests.append(request.url)
            if "profile-b" in request.url:
                route.fulfill(status=200, content_type="application/json", body=_envelope({
                    "items": [{"status": "PENDING_SUBMIT"}],
                }))
            else:
                nonlocal a_calls
                if "profile-a" not in request.url:
                    route.fulfill(status=200, content_type="application/json", body=_envelope({"items": []}))
                elif a_calls == 0:
                    a_calls += 1
                    route.fulfill(status=200, content_type="application/json", body=_envelope({
                        "items": [{"status": "PENDING_SUBMIT"}, {"status": "SUBMIT_FAILED"}],
                    }))
                else:
                    held_old.append(route)
        elif request.url.endswith("/preferences") and request.method == "POST":
            route.fulfill(status=200, content_type="application/json", body=_envelope({}))
        else:
            route.continue_()

    page.route("**/api/v1/settings/autobangumi", handle)
    page.route("**/api/v1/tracking/items**", handle)
    page.route("**/api/v1/preferences", handle)
    # Seed the profile *before* the shell boots: the /app/add route issues no
    # tracking-list request of its own, so the first profile-a response
    # unambiguously belongs to the global badge, and the 100 ms profile poll in
    # the shell cannot race a reload by firing an extra profile-a request first
    # (which used to consume the first-response window and hang the held request).
    page.add_init_script(
        "window.localStorage.setItem('miguOrca.web.storageDir', 'profile-a')"
    )
    with page.expect_response(
        lambda response: (
            response.request.method == "GET"
            and "storage_dir=profile-a" in response.url
            and "/api/v1/tracking/items" in response.url
            and response.ok
        )
    ) as profile_a_response:
        page.goto(f"{live_server_url}/app/add")
    payload = profile_a_response.value.json()
    assert payload["ok"] is True
    assert len(payload["result"]["items"]) == 2
    expect(page.locator(".pending-badge")).to_have_text("2")
    with page.expect_request(
        lambda request: (
            request.method == "GET"
            and "storage_dir=profile-a" in request.url
            and "/api/v1/tracking/items" in request.url
        )
    ):
        page.goto(f"{live_server_url}/app/tracking")
    assert len(held_old) == 1

    # Change the profile through the real Settings form while keeping the SPA alive.
    page.locator(".workspace-status").press("Enter")
    page.wait_for_url("**/app/settings")
    page.locator("#settings-storage-dir").fill("profile-b")
    page.locator("#storage-preferences-save").click()
    page.locator(".brand-block").press("Enter")
    page.wait_for_url("**/app/add")
    expect(page.locator(".pending-badge")).to_have_text("1")
    assert any("storage_dir=profile-a" in url for url in requests)
    assert any("storage_dir=profile-b" in url for url in requests)
    held_old[0].fulfill(status=200, content_type="application/json", body=_envelope({
        "items": [{"status": "PENDING_SUBMIT"}, {"status": "SUBMIT_FAILED"}],
    }))
    expect(page.locator(".pending-badge")).to_have_text("1")


def test_settings_test_save_delete_refreshes_global_state(page: Page, live_server_url: str) -> None:
    state = {"configured": False, "status": "UNCONFIGURED", "ref": None, "revision": 0}
    console_messages: list[str] = []
    page.on("console", lambda message: console_messages.append(message.text))

    def handle(route, request):
        if request.url.endswith("/settings/autobangumi") and request.method == "GET":
            route.fulfill(status=200, content_type="application/json", body=_envelope({
                "configured": state["configured"], "credential_present": state["configured"],
                "connection_ref": state["ref"], "configuration_revision": state["revision"],
                "connection_status": state["status"],
                "raw_endpoint": "https://secret.invalid", "raw_token": "token-canary",
            }))
        elif request.url.endswith("/settings/autobangumi") and request.method == "PUT":
            state.update(configured=True, status="CONFIGURED", ref="new-ref", revision=1)
            route.fulfill(status=200, content_type="application/json", body=_envelope({
                "configured": True, "credential_present": True, "connection_ref": "new-ref",
                "configuration_revision": 1, "connection_status": "CONFIGURED",
                "raw_endpoint": "https://secret.invalid", "raw_token": "token-canary",
            }))
        elif request.url.endswith("/settings/autobangumi") and request.method == "DELETE":
            state.update(configured=False, status="UNCONFIGURED", ref=None, revision=2)
            route.fulfill(status=200, content_type="application/json", body=_envelope({
                "configured": False, "credential_present": False, "connection_ref": None,
                "configuration_revision": 2, "connection_status": "UNCONFIGURED",
                "raw_endpoint": "https://secret.invalid", "raw_token": "token-canary",
            }))
        elif request.url.endswith("/settings/autobangumi/test"):
            route.fulfill(status=200, content_type="application/json", body=_envelope({
                "success": True, "summary": {"reachable": True}, "error": None,
            }))
        elif "/tracking/items" in request.url:
            route.fulfill(status=200, content_type="application/json", body=_envelope({"items": []}))
        else:
            route.continue_()

    page.route("**/api/v1/settings/autobangumi**", handle)
    page.route("**/api/v1/tracking/items**", handle)
    page.goto(f"{live_server_url}/app/settings")
    page.locator("#settings-ab-endpoint").fill("safe.invalid")
    page.locator("#settings-ab-username").fill("user")
    page.locator("#settings-ab-password").fill("safe-password")
    page.locator("#settings-ab-test").click()
    page.locator("#settings-ab-save").click()
    expect(page.locator(".workspace-status")).to_contain_text("已配置")
    expect(page.locator("#settings-ab-delete")).to_be_enabled()
    page.locator("#settings-ab-delete").click()
    page.locator(".confirm-dialog .danger-button").click()
    expect(page.locator(".workspace-status")).to_contain_text("未配置")
    evidence = page.evaluate("""() => ({
      href: location.href,
      history: history.length + ':' + (history.state ? JSON.stringify(history.state) : ''),
      body: document.body.innerText,
      local: JSON.stringify(localStorage),
      session: JSON.stringify(sessionStorage),
    })""")
    assert all(secret not in json.dumps(evidence) for secret in ("https://secret.invalid", "token-canary"))
    assert all(secret not in "\n".join(console_messages) for secret in ("https://secret.invalid", "token-canary"))


def test_badge_failure_then_successful_zero_hides(page: Page, live_server_url: str) -> None:
    failed = True

    def handle(route, request):
        nonlocal failed
        if "/tracking/items" in request.url:
            if failed:
                failed = False
                route.fulfill(status=503, content_type="application/json", body=_envelope({"items": []}))
            else:
                route.fulfill(status=200, content_type="application/json", body=_envelope({"items": []}))
        else:
            route.continue_()

    page.route("**/api/v1/tracking/items**", handle)
    page.goto(f"{live_server_url}/app/add")
    expect(page.locator(".pending-badge")).to_have_count(0)
    page.goto(f"{live_server_url}/app/settings")
    page.locator("#storage-preferences-save").click()
    page.goto(f"{live_server_url}/app/add")
    expect(page.locator(".pending-badge")).to_have_count(0)


def test_held_old_summary_cannot_overwrite_new_configuration(page: Page, live_server_url: str) -> None:
    held = []
    calls = 0

    def handle(route, request):
        nonlocal calls
        if request.url.endswith("/settings/autobangumi"):
            calls += 1
            if calls == 1:
                held.append(route)
            else:
                route.fulfill(status=200, content_type="application/json", body=_envelope({
                    "configured": True, "credential_present": True, "connection_ref": "new-ref",
                    "configuration_revision": 2, "connection_status": "VERIFIED",
                }))
        elif "/tracking/items" in request.url:
            route.fulfill(status=200, content_type="application/json", body=_envelope({"items": []}))
        else:
            route.continue_()

    page.route("**/api/v1/settings/autobangumi", handle)
    page.route("**/api/v1/tracking/items**", handle)
    page.goto(f"{live_server_url}/app/add")
    page.locator(".workspace-status").click()
    page.wait_for_url("**/app/settings")
    page.locator("#storage-preferences-save").click()
    expect(page.locator(".workspace-status")).to_contain_text("连接可用")
    held[0].fulfill(status=200, content_type="application/json", body=_envelope({
        "configured": True, "credential_present": True, "connection_ref": "old-ref",
        "configuration_revision": 1, "connection_status": "CONFIGURED",
    }))
    expect(page.locator(".workspace-status")).to_contain_text("连接可用")


def test_brand_leave_guard_cancel_then_confirm(page: Page, live_server_url: str) -> None:
    page.route(
        "**/api/v1/mikan/candidates",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=_candidate_result_json(
                "芙莉莲",
                [_candidate(
                    bangumi_id="2353",
                    title="葬送的芙莉莲",
                    mikan_url="https://mikan.example/Home/Bangumi/2353",
                )],
            ),
        ),
    )
    preview = _preview_request("葬送的芙莉莲", "req-global-guard")
    _register_generation_capture(page, [], body=preview_result_json(preview))
    page.goto(f"{live_server_url}/app/add")
    page.locator("#mikan-candidate-query").fill("芙莉莲")
    page.locator("#mikan-candidate-search-submit").click()
    expect(page.locator(".candidate-card")).to_have_count(1)
    page.locator(".candidate-card button:has-text('选择此合集')").click()
    page.wait_for_selector("#detail-preview-edit-form")
    page.locator("#preview-must-contain").fill("1080p")
    page.locator(".brand-block").click()
    expect(page.locator(".confirm-dialog")).to_be_visible()
    page.locator(".confirm-dialog .secondary-button").click()
    expect(page).to_have_url(f"{live_server_url}/app/add")
    expect(page.locator("#single-anime-review-step")).to_be_visible()
    page.locator(".brand-block").click()
    page.locator(".confirm-dialog .danger-button").click()
    expect(page).to_have_url(f"{live_server_url}/app/add")
    expect(page.locator("#mikan-candidate-search-form")).to_be_visible()


def test_summary_loading_never_starts_probe(page: Page, live_server_url: str) -> None:
    probe_calls: list[str] = []

    def handle(route, request):
        if request.url.endswith("/settings/autobangumi"):
            route.fulfill(status=200, content_type="application/json", body=_envelope({
                "configured": True, "credential_present": True, "connection_ref": "safe-ref",
                "configuration_revision": 1, "connection_status": "CONFIGURED",
            }))
        elif request.url.endswith("/settings/autobangumi/probe"):
            probe_calls.append(request.method)
            route.fulfill(status=200, content_type="application/json", body=_envelope({"probe_status": "VERIFIED"}))
        else:
            route.continue_()

    page.route("**/api/v1/settings/autobangumi**", handle)
    page.goto(f"{live_server_url}/app/add")
    expect(page.locator(".workspace-status")).to_contain_text("已配置")
    assert probe_calls == []


def test_zoom_keyboard_and_sensitive_canary(page: Page, live_server_url: str) -> None:
    page.on("console", lambda message: (_ for _ in ()).throw(AssertionError(message.text)) if "secret.invalid" in message.text else None)
    page.goto(f"{live_server_url}/app/add")
    page.set_viewport_size({"width": 1280, "height": 800})
    page.evaluate("document.body.style.zoom='200%'")
    page.locator(".workspace-status").focus()
    page.locator(".workspace-status").press("Enter")
    page.wait_for_url("**/app/settings")
    expect(page.locator("#settings-heading")).to_be_visible()
    assert page.evaluate("location.href + document.body.innerText + Object.keys(localStorage).join(',') + Object.keys(sessionStorage).join(',')").find("secret.invalid") == -1
