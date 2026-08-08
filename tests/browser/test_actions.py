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
    page.wait_for_timeout(800)
    item = page.locator(f"[data-request-id='{request_id}']")
    item.click()
    page.wait_for_timeout(500)


# ── scoped action-button helpers (avoid strict-mode clashes with modify-form) ──

def _click_confirm(page: Page) -> None:
    """Click the confirm button scoped to the actions container."""
    page.locator(".detail-actions button:not(.secondary-button)").click()


def _click_cancel(page: Page) -> None:
    """Click the cancel button scoped to the actions container."""
    page.locator(".detail-actions button:has-text('取消')").click()


def _click_modify(page: Page) -> None:
    """Click the modify toggle button scoped to the actions container."""
    page.locator(".detail-actions button:has-text('修改')").click()


class TestActionButtons:
    """AC: PENDING_CONFIRM Request 详情展示确认/取消/修改按钮，非 PENDING 状态隐藏."""

    def test_buttons_present_for_pending_confirm(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-act-1")
        _open_request_detail(page, live_server_url, storage_dir, "req-act-1")

        container = page.locator("#request-detail-container")
        assert container.locator("button:has-text('确认')").count() >= 1
        assert container.locator("button:has-text('取消')").count() >= 1
        assert container.locator("button:has-text('修改')").count() >= 1

    def test_buttons_hidden_after_confirm(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-act-2")
        _open_request_detail(page, live_server_url, storage_dir, "req-act-2")

        page.on("dialog", lambda dialog: dialog.accept())
        _click_confirm(page)
        page.wait_for_timeout(1500)

        # Reload detail — buttons should be gone
        _open_request_detail(page, live_server_url, storage_dir, "req-act-2")
        container = page.locator("#request-detail-container")
        assert container.locator("button:has-text('确认')").count() == 0
        assert "不可操作" in container.inner_text()

    def test_modify_button_toggles_form(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-act-3")
        _open_request_detail(page, live_server_url, storage_dir, "req-act-3")

        _click_modify(page)
        page.wait_for_timeout(300)
        assert page.locator("#detail-modify-form").is_visible()

        # Toggle off via form's own cancel button
        page.locator("#detail-modify-form button:has-text('取消')").click()
        page.wait_for_timeout(300)
        assert page.locator("#detail-modify-form").is_hidden()


class TestConfirmFlow:
    """AC: 确认操作 → 通知 + 状态更新 + 列表刷新."""

    def test_confirm_shows_success_notification(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-act-4")
        _open_request_detail(page, live_server_url, storage_dir, "req-act-4")

        page.on("dialog", lambda dialog: dialog.accept())
        _click_confirm(page)
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        notif = page.locator("#page-notification")
        assert "确认成功" in notif.inner_text()

    def test_confirm_updates_detail_status(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-act-5")
        _open_request_detail(page, live_server_url, storage_dir, "req-act-5")

        page.on("dialog", lambda dialog: dialog.accept())
        _click_confirm(page)
        page.wait_for_timeout(1500)

        detail_text = page.locator("#request-detail-container").inner_text()
        assert "ACCEPTED" in detail_text
        # Buttons should be gone after refresh
        assert page.locator("button:has-text('确认')").count() == 0

    def test_confirm_updates_list_count(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-act-6")
        create_saved_request(storage_dir, "咒术回战第三季", "req-act-7")
        _open_request_detail(page, live_server_url, storage_dir, "req-act-6")

        before = page.locator("#request-list-count").inner_text()
        assert "2" in before

        page.on("dialog", lambda dialog: dialog.accept())
        _click_confirm(page)
        page.wait_for_timeout(1500)

        after = page.locator("#request-list-count").inner_text()
        assert "2" in after


class TestCancelFlow:
    """AC: 取消操作 → 通知 + cause + history."""

    def test_cancel_shows_success_notification(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-act-8")
        _open_request_detail(page, live_server_url, storage_dir, "req-act-8")

        page.on("dialog", lambda dialog: dialog.accept("不需要这个番剧"))
        _click_cancel(page)
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        notif = page.locator("#page-notification")
        assert "取消成功" in notif.inner_text()

    def test_cancel_updates_detail_status(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-act-9")
        _open_request_detail(page, live_server_url, storage_dir, "req-act-9")

        page.on("dialog", lambda dialog: dialog.accept("不想追了"))
        _click_cancel(page)
        page.wait_for_timeout(1500)

        detail_text = page.locator("#request-detail-container").inner_text()
        assert "CANCELLED" in detail_text


class TestModifyFlow:
    """AC: 修改操作 → 表单可填充可提交."""

    def test_modify_form_has_all_fields(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-act-10")
        _open_request_detail(page, live_server_url, storage_dir, "req-act-10")

        _click_modify(page)
        page.wait_for_timeout(300)

        form = page.locator("#detail-modify-form")
        assert form.is_visible()
        assert page.locator("#modify-subtitle-group").count() >= 1
        assert page.locator("#modify-must-contain").count() >= 1
        assert page.locator("#modify-must-not-contain").count() >= 1
        assert page.locator("#modify-folder-name").count() >= 1

    def test_modify_folder_name_succeeds(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-act-11")
        _open_request_detail(page, live_server_url, storage_dir, "req-act-11")

        _click_modify(page)
        page.wait_for_timeout(300)

        page.locator("#modify-folder-name").fill("自定义目录名")
        page.locator("button:has-text('提交修改')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        notif = page.locator("#page-notification")
        assert "修改成功" in notif.inner_text()

        # Detail should still show PENDING_CONFIRM (modify keeps status)
        detail_text = page.locator("#request-detail-container").inner_text()
        assert "PENDING_CONFIRM" in detail_text

    def test_modify_form_hidden_initially(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-act-12")
        _open_request_detail(page, live_server_url, storage_dir, "req-act-12")

        form = page.locator("#detail-modify-form")
        assert form.get_attribute("hidden") is not None


class TestErrorRecovery:
    """AC: 操作失败时通知展示错误消息，现有数据不丢失."""

    def test_notification_has_close_button_after_action(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-act-13")
        _open_request_detail(page, live_server_url, storage_dir, "req-act-13")

        page.on("dialog", lambda dialog: dialog.accept())
        _click_confirm(page)
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        close_btn = page.locator(".notification-close").first
        assert close_btn.count() >= 1
        assert "关闭" in close_btn.inner_text()

    def test_other_sections_remain_after_action(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-act-14")
        _open_request_detail(page, live_server_url, storage_dir, "req-act-14")

        page.on("dialog", lambda dialog: dialog.accept())
        _click_confirm(page)
        page.wait_for_timeout(1500)

        # Detail should still show Overview / Source / Filter / Seeds / Audit
        detail_text = page.locator("#request-detail-container").inner_text()
        for section in ("Overview", "Source", "Filter", "Seeds", "Audit"):
            assert section in detail_text, f"Missing section: {section}"
