from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page

from tests.browser.conftest import create_saved_request, set_storage_preferences
from request_engine.controllers.request_controller import accept_request
from storage_engine.controllers.request_repository import save_request_snapshot
from storage_engine.controllers.storage_config import load_storage_config


pytestmark = pytest.mark.browser


def _open_request_detail(
    page: Page, live_server_url: str, storage_dir: Path, request_id: str
) -> None:
    """Navigate to index, set storage_dir, refresh list, and click a request item."""
    set_storage_preferences(page, storage_dir)
    page.goto(f"{live_server_url}/index")
    page.click("#request-list-refresh")
    page.wait_for_timeout(800)
    item = page.locator(f"[data-request-id='{request_id}']")
    item.click()
    page.wait_for_timeout(500)


# ── scoped action-button helpers (avoid strict-mode clashes with modify-form) ──

def _click_confirm(page: Page) -> None:
    """Click the confirm button scoped to the actions container."""
    page.locator(".detail-actions button:has-text('确认')").click()


def _click_cancel(page: Page) -> None:
    """Click the cancel button scoped to the actions container."""
    page.locator(".detail-actions button:has-text('取消')").click()


def _click_modify(page: Page) -> None:
    """Click the modify toggle button scoped to the actions container."""
    page.locator(".detail-actions button:has-text('修改')").click()


def _click_ab_submit_entry(page: Page) -> None:
    page.locator(".detail-actions a:has-text('去 Settings 提交 Auto Bangumi')").click()


def create_saved_accepted_request(
    storage_root: Path, title: str, request_id: str
) -> dict:
    request = accept_request(create_saved_request(storage_root, title, request_id))
    save_request_snapshot(load_storage_config(storage_root), request)
    return request


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
        assert container.locator("a:has-text('去 Settings 提交 Auto Bangumi')").count() >= 1

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

    def test_ab_submit_button_hidden_for_pending_request(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-act-ab-hidden")
        _open_request_detail(page, live_server_url, storage_dir, "req-act-ab-hidden")

        container = page.locator("#request-detail-container")
        assert (
            container.locator(".detail-actions a:has-text('去 Settings 提交 Auto Bangumi')").count()
            == 0
        )


class TestAutoBangumiSubmitFlow:
    """AC: ACCEPTED Request links to Settings for temporary AB config."""

    def test_ab_submit_entry_links_to_settings_context(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_accepted_request(storage_dir, "葬送的芙莉莲", "req-ab-form")
        _open_request_detail(page, live_server_url, storage_dir, "req-ab-form")

        entry = page.locator(".detail-actions a:has-text('去 Settings 提交 Auto Bangumi')")
        assert entry.count() >= 1
        assert entry.get_attribute("href") == "/settings?request_id=req-ab-form#auto-bangumi"
        assert page.locator("#detail-ab-submit-form").count() == 0
        _click_ab_submit_entry(page)
        page.wait_for_url("**/settings?request_id=req-ab-form#auto-bangumi")
        assert page.locator("#settings-ab-submit-form").is_visible()
        assert page.locator("#settings-ab-request-id").inner_text() == "req-ab-form"
        assert page.locator("#settings-ab-token").get_attribute("type") == "password"
        assert page.locator("#settings-ab-fallback-enabled").get_attribute("type") == "checkbox"

    def test_ab_submit_requires_confirmation_and_sends_request_scoped_config(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_accepted_request(storage_dir, "葬送的芙莉莲", "req-ab-submit")
        captured = {}

        def handle_submit(route):
            if route.request.method == "POST":
                captured["url"] = route.request.url
                captured["payload"] = route.request.post_data_json
                route.fulfill(
                    json={
                        "ok": True,
                        "result": {
                            "request": {"request_id": "req-ab-submit", "status": "ACCEPTED"},
                            "ab_submit_result": {
                                "success": True,
                                "ab_subscription_id": "sub-browser",
                                "ab_response": {"id": "sub-browser"},
                                "fallback_config": None,
                                "error": None,
                            },
                        },
                    }
                )
            else:
                route.continue_()

        page.route("**/api/v1/requests/req-ab-submit/submit-ab**", handle_submit)
        set_storage_preferences(page, storage_dir)
        page.goto(f"{live_server_url}/settings?request_id=req-ab-submit#auto-bangumi")
        page.locator("#settings-ab-endpoint").fill("ab-endpoint-value")
        page.locator("#settings-ab-token").fill("browser-secret-token")
        page.locator("#settings-ab-fallback-enabled").check()

        seen_dialogs = []
        page.on(
            "dialog",
            lambda dialog: (seen_dialogs.append(dialog.message), dialog.accept()),
        )
        page.locator("#settings-ab-submit").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert seen_dialogs == ["确认提交此 Request 到 Auto Bangumi？"]
        assert "/api/v1/requests/req-ab-submit/submit-ab" in captured["url"]
        assert "browser-secret-token" not in captured["url"]
        assert "ab-endpoint-value" not in captured["url"]
        assert captured["payload"] == {
            "storage_dir": str(storage_dir),
            "ab_config": {
                "endpoint": "ab-endpoint-value",
                "token": "browser-secret-token",
                "fallback_enabled": True,
            },
        }
        storage_keys = page.evaluate("Object.keys(window.localStorage)")
        session_keys = page.evaluate("Object.keys(window.sessionStorage)")
        assert all("ab" not in key.lower() for key in storage_keys)
        assert session_keys == []
        assert page.locator("#settings-ab-endpoint").input_value() == ""
        assert page.locator("#settings-ab-token").input_value() == ""


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

        _click_cancel(page)
        assert page.locator("#detail-cancel-form").is_visible()
        page.locator("#cancel-reason").fill("不需要这个番剧")
        page.on("dialog", lambda dialog: dialog.accept())
        page.locator("#detail-cancel-form button:has-text('提交取消')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        notif = page.locator("#page-notification")
        assert "取消成功" in notif.inner_text()

    def test_cancel_uses_visible_form_and_confirmation(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-act-cancel-form")
        captured = {}
        dialogs = []

        def handle_cancel(route):
            if route.request.method == "POST":
                captured["payload"] = route.request.post_data_json
            route.continue_()

        page.route("**/api/v1/requests/req-act-cancel-form/cancel**", handle_cancel)
        _open_request_detail(page, live_server_url, storage_dir, "req-act-cancel-form")

        _click_cancel(page)
        form = page.locator("#detail-cancel-form")
        assert form.is_visible()
        assert page.locator("#cancel-reason").is_visible()
        page.locator("#cancel-reason").fill("表单取消原因")
        page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.accept()))
        page.locator("#detail-cancel-form button:has-text('提交取消')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert dialogs == ["确认取消此 Request？"]
        assert captured["payload"]["cancel_reason"] == "表单取消原因"

    def test_cancel_updates_detail_status(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-act-9")
        _open_request_detail(page, live_server_url, storage_dir, "req-act-9")

        _click_cancel(page)
        page.locator("#cancel-reason").fill("不想追了")
        page.on("dialog", lambda dialog: dialog.accept())
        page.locator("#detail-cancel-form button:has-text('提交取消')").click()
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
        assert page.locator("#modify-must-not-contain-literal").count() >= 1
        assert "默认按正则匹配" in form.inner_text()
        assert page.locator("#modify-folder-name").count() >= 1
        assert page.locator("#modify-clear-must-contain").count() >= 1
        assert page.locator("#modify-clear-must-not-contain").count() >= 1
        assert page.locator("#modify-clear-folder-name").count() >= 1

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

    def test_modify_literal_v2_exclude_shows_removed_seed_feedback(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "咒术回战第三季", "req-act-v2-literal")
        _open_request_detail(page, live_server_url, storage_dir, "req-act-v2-literal")

        _click_modify(page)
        page.locator("#modify-must-not-contain").fill("[v2]")
        page.locator("#modify-must-not-contain-literal").check()
        page.locator("#detail-modify-form button:has-text('提交修改')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        detail = page.locator("#request-detail-container")
        detail_text = detail.inner_text()
        assert "修改成功" in page.locator("#page-notification").inner_text()
        assert "must_not_contain" in detail_text
        assert "(?i:\\[?v2\\]?)" in detail_text
        assert "有效种子数" in detail_text
        assert "排除种子数" in detail_text

        detail.locator(".seed-details").evaluate("element => element.open = true")
        valid_group = detail.locator(".seed-group:has-text('有效种子')")
        excluded_group = detail.locator(".seed-group:has-text('排除种子')")
        assert "V2" not in valid_group.inner_text()
        assert "V2" in excluded_group.inner_text()
        assert "命中必须不含规则" in excluded_group.inner_text()

    def test_modify_regex_v2_exclude_updates_seed_lists(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "咒术回战第三季", "req-act-v2-regex")
        _open_request_detail(page, live_server_url, storage_dir, "req-act-v2-regex")

        _click_modify(page)
        page.locator("#modify-must-not-contain").fill("V2")
        page.locator("#detail-modify-form button:has-text('提交修改')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        detail = page.locator("#request-detail-container")
        detail.locator(".seed-details").evaluate("element => element.open = true")
        detail_text = detail.inner_text()
        assert "V2" in detail.locator(".seed-group:has-text('排除种子')").inner_text()
        assert "V2" not in detail.locator(".seed-group:has-text('有效种子')").inner_text()
        assert "查看筛选种子列表 (完整 2 / 有效 1 / 排除 1)" in detail_text

    def test_modify_form_hidden_initially(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-act-12")
        _open_request_detail(page, live_server_url, storage_dir, "req-act-12")

        form = page.locator("#detail-modify-form")
        assert form.get_attribute("hidden") is not None

    def test_modify_empty_patch_is_blocked_in_browser(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-act-empty-modify")
        calls = []

        def handle_modify(route):
            calls.append(route.request.post_data_json)
            route.continue_()

        page.route("**/api/v1/requests/req-act-empty-modify/modify**", handle_modify)
        _open_request_detail(page, live_server_url, storage_dir, "req-act-empty-modify")

        _click_modify(page)
        page.locator("button:has-text('提交修改')").click()
        page.wait_for_timeout(500)

        assert calls == []
        assert "请至少修改或清空一个字段" in page.locator("#detail-modify-error").inner_text()

    def test_modify_clear_fields_sends_explicit_empty_values(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-act-clear-modify")
        captured = {}

        def handle_modify(route):
            if route.request.method == "POST":
                captured["payload"] = route.request.post_data_json
                route.fulfill(
                    json={
                        "ok": True,
                        "result": {
                            "request": {
                                "request_id": "req-act-clear-modify",
                                "status": "PENDING_CONFIRM",
                            },
                            "summary": {
                                "request_id": "req-act-clear-modify",
                                "status": "PENDING_CONFIRM",
                            },
                        },
                    }
                )
            else:
                route.continue_()

        page.route("**/api/v1/requests/req-act-clear-modify/modify**", handle_modify)
        _open_request_detail(page, live_server_url, storage_dir, "req-act-clear-modify")

        _click_modify(page)
        page.locator("#modify-clear-must-contain").check()
        page.locator("#modify-clear-must-not-contain").check()
        page.locator("#modify-clear-folder-name").check()
        page.locator("button:has-text('提交修改')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert captured["payload"]["patch"] == {
            "filter_rule": {"must_contain": "", "must_not_contain": ""},
            "expected_folder_name": "",
        }

    def test_modify_failure_preserves_form_state(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-act-modify-failure")

        def handle_modify(route):
            route.fulfill(
                status=500,
                json={
                    "ok": False,
                    "error_type": "invalid_modify_patch",
                    "error_message": "修改失败",
                },
            )

        page.route("**/api/v1/requests/req-act-modify-failure/modify**", handle_modify)
        _open_request_detail(page, live_server_url, storage_dir, "req-act-modify-failure")

        _click_modify(page)
        page.locator("#modify-must-not-contain").fill("V2")
        page.locator("#modify-folder-name").fill("失败后仍保留")
        page.locator("button:has-text('提交修改')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert page.locator("#detail-modify-form").is_visible()
        assert page.locator("#modify-must-not-contain").input_value() == "V2"
        assert page.locator("#modify-folder-name").input_value() == "失败后仍保留"
        assert "PENDING_CONFIRM" in page.locator("#request-detail-container").inner_text()


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
