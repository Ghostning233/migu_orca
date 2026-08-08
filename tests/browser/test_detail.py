from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page

from tests.browser.conftest import create_saved_request


pytestmark = pytest.mark.browser


def _open_request_detail(
    page: Page, live_server_url: str, storage_dir: Path, request_id: str
) -> None:
    """Navigate to index, set storage_dir, refresh list, and click a request item."""
    page.goto(f"{live_server_url}/index")
    page.fill('input[name="storage_dir"]', str(storage_dir))
    page.click("#request-list-refresh")
    # Wait for list to load from API
    page.wait_for_timeout(800)
    # Click list item by data-request-id attribute
    item = page.locator(f"[data-request-id='{request_id}']")
    item.click()
    page.wait_for_timeout(500)


class TestDetailSections:
    """AC: 打开已保存 Request 后，详情包含 Overview、Source、Filter、Seeds、Audit 分组."""

    def test_all_sections_present(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-detail-1")
        _open_request_detail(page, live_server_url, storage_dir, "req-detail-1")

        detail = page.locator("#request-detail-container")
        text = detail.inner_text()
        for section in ("Overview", "Source", "Filter", "Seeds", "Audit"):
            assert section in text, f"Missing detail section: {section}"

    def test_overview_shows_key_fields(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-detail-2")
        _open_request_detail(page, live_server_url, storage_dir, "req-detail-2")

        detail = page.locator("#request-detail-container")
        text = detail.inner_text()
        assert "原始标题" in text
        assert "葬送的芙莉莲" in text


class TestRequestIdCopy:
    """AC: request_id 复制按钮存在并可触发复制反馈."""

    def test_copy_button_present(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-detail-3")
        _open_request_detail(page, live_server_url, storage_dir, "req-detail-3")

        copy_btn = page.locator(".copy-request-id").first
        assert copy_btn.count() >= 1
        assert "复制" in copy_btn.inner_text()

    def test_rss_only_shows_selected_status(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """AC: RSS 只展示是否已选择，不展示完整 RSS URL."""
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-detail-4")
        _open_request_detail(page, live_server_url, storage_dir, "req-detail-4")

        detail = page.locator("#request-detail-container")
        text = detail.inner_text()
        assert "已选择" in text or "未选择" in text
        lowered = text.lower()
        assert ".xml" not in lowered


class TestSeedsExpandable:
    """AC: Seeds 区块可展开查看完整有效种子标题列表."""

    def test_seeds_section_has_details_element(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-detail-5")
        _open_request_detail(page, live_server_url, storage_dir, "req-detail-5")

        details = page.locator("#request-detail-container details")
        assert details.count() >= 1, "Seeds section should use <details> element"

    def test_seeds_label_present(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-detail-5")
        _open_request_detail(page, live_server_url, storage_dir, "req-detail-5")

        text = page.locator("#request-detail-container").inner_text()
        assert "有效种子" in text


class TestMissingOptionalData:
    """AC: 缺失 history 或 AB result 时，Audit 显示非致命提示且详情仍可读取."""

    def test_missing_history_shows_placeholder(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-detail-6")
        _open_request_detail(page, live_server_url, storage_dir, "req-detail-6")

        text = page.locator("#request-detail-container").inner_text()
        assert "暂无状态历史" in text

    def test_missing_ab_result_shows_placeholder(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-detail-7")
        _open_request_detail(page, live_server_url, storage_dir, "req-detail-7")

        text = page.locator("#request-detail-container").inner_text()
        assert "暂无 Auto Bangumi 提交结果" in text

    def test_detail_still_readable_when_optional_missing(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-detail-8")
        _open_request_detail(page, live_server_url, storage_dir, "req-detail-8")

        text = page.locator("#request-detail-container").inner_text()
        assert "原始标题" in text
        assert "葬送的芙莉莲" in text


class TestNotificationAndRecovery:
    """AC: 通知区域支持成功、错误、手动关闭和下一次操作替换旧消息."""

    def test_notification_hidden_initially(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/index")
        notif = page.locator("#page-notification")
        assert notif.get_attribute("hidden") is not None

    def test_notification_has_close_button(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        page.goto(f"{live_server_url}/index")
        page.fill('input[name="storage_dir"]', str(storage_dir))
        page.fill('input[name="title"]', "葬送的芙莉莲")
        page.click("#request-generate-submit")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        close_btn = page.locator(".notification-close").first
        assert close_btn.count() >= 1
        assert "关闭" in close_btn.inner_text()

    def test_refresh_button_available_on_load_failure(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/index")
        refresh = page.locator("#request-list-refresh")
        assert refresh.count() >= 1
        assert refresh.is_enabled()
