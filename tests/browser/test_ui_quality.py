from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import create_saved_request, set_storage_preferences


pytestmark = pytest.mark.browser


def _open_detail(
    page: Page, live_server_url: str, storage_dir: Path, request_id: str
) -> None:
    create_saved_request(storage_dir, "葬送的芙莉莲", request_id)
    set_storage_preferences(page, storage_dir)
    page.goto(f"{live_server_url}/index?request_id={request_id}")
    page.wait_for_selector("#request-detail-container .overview-section", timeout=5000)


def test_index_uses_stage13_visual_hierarchy_and_button_semantics(
    page: Page, live_server_url: str
) -> None:
    page.goto(f"{live_server_url}/index")

    expect(page.locator("#generate-panel")).to_be_visible()
    expect(page.locator("#request-list-panel")).to_be_visible()
    expect(page.locator("#request-detail-panel")).to_be_visible()
    expect(page.locator("#acceptance-panel")).to_have_count(0)
    expect(page.locator("#request-generate-submit.primary-button")).to_be_visible()
    expect(page.locator("#request-list-refresh.secondary-button")).to_be_visible()
    expect(page.locator("#request-list-container.empty-state")).to_be_visible()
    expect(page.locator("#request-detail-container.empty-state")).to_be_visible()


def test_settings_sections_use_boundaries_disclosure_and_button_semantics(
    page: Page, live_server_url: str
) -> None:
    page.goto(f"{live_server_url}/settings")

    for panel_id in (
        "storage-settings-panel",
        "data-source-settings-panel",
        "qbittorrent-settings-panel",
        "auto-bangumi-settings-panel",
    ):
        expect(page.locator(f"#{panel_id}.settings-panel")).to_be_visible()

    expect(page.locator("#qbittorrent-settings-details.settings-disclosure")).to_be_visible()
    expect(page.locator("#settings-qbittorrent-endpoint")).to_be_hidden()
    expect(page.locator("#storage-preferences-save.primary-button")).to_be_visible()
    expect(page.locator("#storage-preferences-clear.danger-button")).to_be_visible()
    expect(page.locator("#settings-qbittorrent-test-submit.primary-button")).to_be_hidden()


def test_request_detail_sections_are_grouped_and_actions_are_near_heading(
    page: Page, live_server_url: str, storage_dir: Path
) -> None:
    _open_detail(page, live_server_url, storage_dir, "req-ui-detail")

    detail = page.locator("#request-detail-container")
    for section_class in (
        "overview-section",
        "source-section",
        "filter-section",
        "seeds-section",
        "audit-group-section",
    ):
        expect(detail.locator(f".detail-section.{section_class}")).to_be_visible()

    expect(detail.locator(".detail-actions .primary-button:has-text('确认')")).to_be_visible()
    expect(detail.locator(".detail-actions .secondary-button:has-text('修改')")).to_be_visible()
    expect(detail.locator(".detail-actions .danger-button:has-text('取消')")).to_be_visible()

    heading_box = detail.locator("h3").bounding_box()
    actions_box = detail.locator(".detail-actions").bounding_box()
    assert heading_box is not None
    assert actions_box is not None
    assert actions_box["y"] > heading_box["y"]
    assert actions_box["y"] - heading_box["y"] < 80


def test_stage13_pages_remain_readable_on_narrow_viewports(
    page: Page, live_server_url: str, storage_dir: Path
) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    _open_detail(page, live_server_url, storage_dir, "req-ui-mobile")

    expect(page.locator(".app-layout")).to_have_css("grid-template-columns", "366px")
    expect(page.locator("#generate-panel")).to_be_visible()
    expect(page.locator("#request-detail-panel")).to_be_visible()
    assert page.locator("#request-detail-panel").bounding_box()["width"] <= 390

    page.goto(f"{live_server_url}/settings")
    expect(page.locator(".settings-layout")).to_have_css("grid-template-columns", "366px")
    assert page.locator("#storage-settings-panel").bounding_box()["width"] <= 390


def test_notifications_and_state_feedback_do_not_expose_sensitive_values(
    page: Page, live_server_url: str
) -> None:
    page.goto(f"{live_server_url}/index")
    page.fill("#request-title", " ")
    page.click("#request-generate-submit")

    notification = page.locator("#page-notification")
    expect(notification).to_be_visible()
    assert "notification-error" in (notification.get_attribute("class") or "")
    text = notification.inner_text().lower()
    for forbidden in (
        "http://",
        "https://",
        "token",
        "password",
        "cookie",
        "sid",
        "<rss",
    ):
        assert forbidden not in text
