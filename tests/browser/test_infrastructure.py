from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page


pytestmark = pytest.mark.browser


def _check_no_sensitive_content(text: str) -> None:
    """Verify that rendered content does not expose tokens, URLs, or raw data."""
    lowered = text.lower()
    assert "http://" not in lowered
    assert "https://" not in lowered
    assert "<rss" not in lowered
    assert "token" not in lowered


def test_server_reachable(page: Page, live_server_url: str) -> None:
    """The browser can reach the Flask test server via health check."""
    page.goto(f"{live_server_url}/healthz")
    body = page.locator("body").inner_text()
    assert "ok" in body


def test_root_redirects_to_index(page: Page, live_server_url: str) -> None:
    """GET / returns a 302 redirect to /index then loads the page."""
    page.goto(f"{live_server_url}/")
    # After following redirect, we should land on /index
    page.wait_for_url("**/index")
    assert page.title().startswith("MiGuOrca")


def test_index_loads_stage13_request_workbench(page: Page, live_server_url: str) -> None:
    """The /index page loads the Stage 13 Request workbench shell."""
    page.goto(f"{live_server_url}/index")

    assert page.title().startswith("MiGuOrca")
    assert page.locator("text=MiGuOrca").count() >= 1
    assert page.locator("text=Stage 13 Request 工作台").count() >= 1

    # Top navigation anchors
    nav = page.locator(".top-nav")
    assert nav.count() >= 1
    assert nav.locator("a[href='/index']").count() >= 1
    assert nav.locator("a[href='/settings']").count() >= 1
    assert nav.locator("text=Request 工作台").count() >= 1
    assert nav.locator("text=Settings").count() >= 1

    # Mode hint
    hint = page.locator("text=运行模式：本地 JSON storage").first
    assert hint.count() >= 1

    # Main panels are present
    for panel_id in (
        "generate-panel",
        "request-list-panel",
        "request-detail-panel",
    ):
        assert page.locator(f"#{panel_id}").count() >= 1, f"Missing panel: #{panel_id}"
    assert page.locator("#qbittorrent-panel").count() == 0
    assert page.locator("#acceptance-panel").count() == 0

    _check_no_sensitive_content(page.content())


def test_settings_loads_placeholder_shell(page: Page, live_server_url: str) -> None:
    """The /settings page loads the Stage 13 Settings shell."""
    page.goto(f"{live_server_url}/settings")

    assert page.title() == "MiGuOrca Settings"
    assert page.locator("text=MiGuOrca Settings").count() >= 1
    assert page.locator(".top-nav a[href='/index']").count() >= 1
    assert page.locator(".top-nav a[href='/settings']").count() >= 1
    for panel_id in (
        "storage-settings-panel",
        "data-source-settings-panel",
        "qbittorrent-settings-panel",
        "auto-bangumi-settings-panel",
    ):
        assert page.locator(f"#{panel_id}.panel").count() >= 1


def test_static_assets_load_without_critical_errors(
    page: Page, live_server_url: str
) -> None:
    """Static CSS and JS assets load without console errors."""
    console_errors: list[str] = []

    def _on_console(msg: object) -> None:
        # playwright console message
        mtype = getattr(msg, "type", "")
        if mtype == "error":
            console_errors.append(str(getattr(msg, "text", "")))

    page.on("console", _on_console)
    page.goto(f"{live_server_url}/index")
    page.wait_for_timeout(800)

    critical = [e for e in console_errors if "favicon" not in e.lower()]
    assert not critical, f"Unexpected console errors: {critical}"

    # Verify key static assets are loaded
    assert page.locator('link[href*="style.css"]').count() >= 1
    assert page.locator('script[src*="app.js"]').count() >= 1


def test_empty_list_state(page: Page, live_server_url: str) -> None:
    """When no Requests are saved, the list displays '显示 0 / 0'."""
    page.goto(f"{live_server_url}/index")
    list_count = page.locator("#request-list-count")
    assert list_count.count() >= 1
    assert "显示 0 / 0" in list_count.inner_text()


def test_no_default_storage_pollution(
    page: Page, live_server_url: str, storage_dir: Path
) -> None:
    """Browser tests never touch the repo's `.migu_orca/storage`."""
    default = Path(".migu_orca/storage")
    assert not default.exists(), (
        ".migu_orca/storage was created — browser test must use temp storage"
    )


def test_generation_form_present(page: Page, live_server_url: str) -> None:
    """The Request generation form is rendered with all expected controls."""
    page.goto(f"{live_server_url}/index")

    assert page.locator("#request-generate-form").count() >= 1
    assert page.locator('input[name="title"]').count() >= 1
    assert page.locator('select[name="source"]').count() == 0
    assert page.locator('input[name="mikan_search_endpoint"]').count() == 0
    assert page.locator('input[name="mikan_timeout_seconds"]').count() == 0
    assert page.locator('input[name="storage_dir"]').count() == 0
    assert page.locator('input[name="save_request"]').count() == 0
    assert page.locator("#storage-preference-summary").count() >= 1
    assert page.locator("#storage-preference-summary a[href*='/settings']").count() >= 1
    assert page.locator("#request-generate-submit").count() >= 1
    assert page.locator("#request-form-error").count() >= 1

    # Default label on submit button
    submit = page.locator("#request-generate-submit")
    assert submit.get_attribute("data-default-label") == "生成"


def test_notification_area_present(page: Page, live_server_url: str) -> None:
    """The unified notification area is rendered with correct aria attributes."""
    page.goto(f"{live_server_url}/index")

    notif = page.locator("#page-notification")
    assert notif.count() >= 1
    assert notif.get_attribute("aria-live") == "polite"
    assert notif.get_attribute("role") == "status"
    # Should be hidden initially
    assert notif.get_attribute("hidden") is not None


def test_accessibility_landmarks(page: Page, live_server_url: str) -> None:
    """The page has basic semantic landmarks for accessibility."""
    page.goto(f"{live_server_url}/index")

    # Form error area is an alert region
    assert page.locator('#request-form-error[role="alert"]').count() >= 1

    # Refresh button has an aria-label
    refresh = page.locator("#request-list-refresh")
    assert refresh.count() >= 1
    label = refresh.get_attribute("aria-label")
    assert label and "刷新" in label
