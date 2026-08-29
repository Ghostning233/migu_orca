from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

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
        assert page.locator("#settings-ab-auth-mode").input_value() == "password"
        assert page.locator("#settings-ab-username").is_visible()
        assert page.locator("#settings-ab-password").get_attribute("type") == "password"
        assert page.locator("#settings-ab-token-fields").is_hidden()

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
        page.locator("#settings-ab-endpoint").fill("http://ab.example.invalid")
        page.locator("#settings-ab-username").fill("browser-user")
        page.locator("#settings-ab-password").fill("browser-secret-password")

        seen_dialogs = []
        page.on(
            "dialog",
            lambda dialog: (seen_dialogs.append(dialog.message), dialog.accept()),
        )
        page.locator("#settings-ab-submit").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert seen_dialogs == ["确认提交此订阅方案到 Auto Bangumi？"]
        assert "/api/v1/requests/req-ab-submit/submit-ab" in captured["url"]
        assert "browser-secret-token" not in captured["url"]
        assert "ab-endpoint-value" not in captured["url"]
        assert captured["payload"] == {
            "storage_dir": storage_dir.name,
            "ab_config": {
                "auth_mode": "password",
                "base_url": "http://ab.example.invalid",
                "username": "browser-user",
                "password": "browser-secret-password",
                "fallback_enabled": False,
            },
        }
        storage_keys = page.evaluate("Object.keys(window.localStorage)")
        session_keys = page.evaluate("Object.keys(window.sessionStorage)")
        assert all("ab" not in key.lower() for key in storage_keys)
        assert session_keys == []
        assert page.locator("#settings-ab-endpoint").input_value() == ""
        assert page.locator("#settings-ab-username").input_value() == ""
        assert page.locator("#settings-ab-password").input_value() == ""

    def test_connection_uses_password_mode_and_clears_credentials(
        self, page: Page, live_server_url: str
    ) -> None:
        captured: dict[str, object] = {}

        def _connection(route: object) -> None:
            request = getattr(route, "request")
            captured["body"] = request.post_data_json
            getattr(route, "fulfill")(
                status=200,
                content_type="application/json",
                body=(
                    '{"ok": true, "result": {"reachable": true, '
                    '"authenticated": true, "version": "3.1.18", '
                    '"auth_mode": "账号密码", "adapter": "legacy_3_1", '
                    '"submit_supported": true}}'
                ),
            )

        page.route("**/api/v1/autobangumi/test-connection", _connection)
        page.goto(f"{live_server_url}/settings#auto-bangumi")
        assert page.locator("#settings-ab-submit-form").is_visible()
        assert page.locator("#settings-ab-submit").is_hidden()
        page.fill("#settings-ab-endpoint", "http://ab.example.invalid")
        page.fill("#settings-ab-username", "browser-user")
        page.fill("#settings-ab-password", "browser-secret-password")
        page.click("#settings-ab-test-submit")
        expect(page.locator("#settings-ab-result")).to_contain_text("连接成功")
        assert captured["body"] == {
            "ab_config": {
                "auth_mode": "password",
                "base_url": "http://ab.example.invalid",
                "username": "browser-user",
                "password": "browser-secret-password",
                "fallback_enabled": False,
            }
        }
        for selector in ("#settings-ab-endpoint", "#settings-ab-username", "#settings-ab-password"):
            expect(page.locator(selector)).to_have_value("")
        state = page.evaluate("() => JSON.stringify({url: location.href, localStorage, sessionStorage, body: document.body.innerText})")
        assert "browser-secret-password" not in state
        assert "browser-user" not in state
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
        assert "已确认" in detail_text
        # Confirm action button should be gone after refresh (list items now show
        # the Chinese status label "已确认", so scope to the detail action area).
        assert (
            page.locator("#request-detail-container .detail-actions button:has-text('确认')").count()
            == 0
        )

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

        assert dialogs == ["确认取消此订阅方案？"]
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
        assert "已取消" in detail_text


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
        assert "包含规则" in form.inner_text()
        assert "排除规则" in form.inner_text()
        regex_box = page.locator("#modify-filter-use-regex")
        case_box = page.locator("#modify-filter-case-sensitive")
        assert regex_box.count() >= 1
        assert case_box.count() >= 1
        assert regex_box.is_checked() is False
        assert case_box.is_checked() is False
        assert "默认按字面文本匹配" in form.inner_text()
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

        # Detail should still show 待确认 (modify keeps status)
        detail_text = page.locator("#request-detail-container").inner_text()
        assert "待确认" in detail_text

    def test_modify_literal_v2_exclude_shows_removed_seed_feedback(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "咒术回战第三季", "req-act-v2-literal")
        _open_request_detail(page, live_server_url, storage_dir, "req-act-v2-literal")

        _click_modify(page)
        page.locator("#modify-must-not-contain").fill("V2")
        page.locator("#detail-modify-form button:has-text('提交修改')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        detail = page.locator("#request-detail-container")
        detail_text = detail.inner_text()
        assert "修改成功" in page.locator("#page-notification").inner_text()
        assert "排除规则" in detail_text
        assert "V2" in detail_text
        assert "有效种子数" in detail_text
        assert "排除种子数" in detail_text

        detail.locator(".excluded-seed-details").evaluate("element => element.open = true")
        valid_group = detail.locator(".effective-seed-group")
        excluded_group = detail.locator(".excluded-seed-details .seed-group")
        assert "V2" not in valid_group.inner_text()
        assert "V2" in excluded_group.inner_text()
        assert "命中排除规则" in excluded_group.inner_text()

    def test_modify_regex_v2_exclude_updates_seed_lists(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "咒术回战第三季", "req-act-v2-regex")
        _open_request_detail(page, live_server_url, storage_dir, "req-act-v2-regex")

        _click_modify(page)
        page.locator("#modify-must-not-contain").fill("V2")
        page.locator("#modify-filter-use-regex").check()
        page.locator("#detail-modify-form button:has-text('提交修改')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        detail = page.locator("#request-detail-container")
        detail.locator(".excluded-seed-details").evaluate("element => element.open = true")
        detail_text = detail.inner_text()
        assert "V2" in detail.locator(".excluded-seed-details").inner_text()
        assert "V2" not in detail.locator(".effective-seed-group").inner_text()
        assert "有效种子（当前选中字幕组：Loli）(1)" in detail_text
        assert "完整种子（按字幕组分组）(3)" in detail_text
        assert "排除种子 (1)" in detail_text

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
            "filter_rule": {
                "must_contain": "",
                "must_not_contain": "",
                "use_regex": False,
                "case_sensitive": False,
            },
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
        assert "待确认" in page.locator("#request-detail-container").inner_text()


class TestModifyFilterOptions:
    """US-107: 修改表单默认字面匹配，勾选使用正则/大小写敏感时 payload 携带对应布尔值."""

    def _capture_modify(
        self, page: Page, request_id: str
    ) -> dict:
        captured: dict = {}

        def handle_modify(route: object) -> None:
            if getattr(route, "request").method == "POST":
                captured["payload"] = getattr(route, "request").post_data_json
                getattr(route, "fulfill")(
                    json={
                        "ok": True,
                        "result": {
                            "request": {
                                "request_id": request_id,
                                "status": "PENDING_CONFIRM",
                            },
                            "summary": {
                                "request_id": request_id,
                                "status": "PENDING_CONFIRM",
                            },
                        },
                    }
                )
            else:
                getattr(route, "continue_")()

        page.route(f"**/api/v1/requests/{request_id}/modify**", handle_modify)
        return captured

    def test_default_filter_submit_sends_false_flags(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-filter-default")
        captured = self._capture_modify(page, "req-filter-default")
        _open_request_detail(page, live_server_url, storage_dir, "req-filter-default")

        _click_modify(page)
        assert page.locator("#modify-filter-use-regex").is_checked() is False
        assert page.locator("#modify-filter-case-sensitive").is_checked() is False
        page.locator("#modify-must-contain").fill("1080p")
        page.locator("#detail-modify-form button:has-text('提交修改')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        filter_rule = captured["payload"]["patch"]["filter_rule"]
        assert filter_rule["must_contain"] == "1080p"
        assert filter_rule["use_regex"] is False
        assert filter_rule["case_sensitive"] is False

    def test_regex_checked_payload_sends_use_regex_true(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-filter-regex")
        captured = self._capture_modify(page, "req-filter-regex")
        _open_request_detail(page, live_server_url, storage_dir, "req-filter-regex")

        _click_modify(page)
        page.locator("#modify-must-not-contain").fill("^01")
        page.locator("#modify-filter-use-regex").check()
        assert page.locator("#modify-filter-use-regex").is_checked() is True
        page.locator("#detail-modify-form button:has-text('提交修改')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        filter_rule = captured["payload"]["patch"]["filter_rule"]
        assert filter_rule["must_not_contain"] == "^01"
        assert filter_rule["use_regex"] is True
        assert filter_rule["case_sensitive"] is False

    def test_case_sensitive_checked_payload_sends_case_sensitive_true(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-filter-case")
        captured = self._capture_modify(page, "req-filter-case")
        _open_request_detail(page, live_server_url, storage_dir, "req-filter-case")

        _click_modify(page)
        page.locator("#modify-must-contain").fill("V2")
        page.locator("#modify-filter-case-sensitive").check()
        assert page.locator("#modify-filter-case-sensitive").is_checked() is True
        page.locator("#detail-modify-form button:has-text('提交修改')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        filter_rule = captured["payload"]["patch"]["filter_rule"]
        assert filter_rule["must_contain"] == "V2"
        assert filter_rule["use_regex"] is False
        assert filter_rule["case_sensitive"] is True

    def test_invalid_regex_error_recovery_preserves_form(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "咒术回战第三季", "req-filter-regex-fail")

        def handle_modify(route: object) -> None:
            getattr(route, "fulfill")(
                status=500,
                json={
                    "ok": False,
                    "error_type": "invalid_modify_patch",
                    "error_message": "filter_rule.must_not_contain 不是合法正则",
                },
            )

        page.route("**/api/v1/requests/req-filter-regex-fail/modify**", handle_modify)
        _open_request_detail(page, live_server_url, storage_dir, "req-filter-regex-fail")

        _click_modify(page)
        page.locator("#modify-must-not-contain").fill("[")
        page.locator("#modify-filter-use-regex").check()
        page.locator("#detail-modify-form button:has-text('提交修改')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert "不是合法正则" in page.locator("#page-notification").inner_text()
        assert page.locator("#detail-modify-form").is_visible()
        assert page.locator("#modify-must-not-contain").input_value() == "["
        assert page.locator("#modify-filter-use-regex").is_checked() is True


class TestFilterDetailDisplay:
    """US-108: 详情 Filter 分区展示规则、匹配模式与大小写状态；Seeds 排除原因可读."""

    def _save_request_with_seed_names(
        self, storage_dir: Path, title: str, request_id: str, seed_names: list[str]
    ) -> None:
        request = create_saved_request(storage_dir, title, request_id)
        source = request["source_info"]["rss_sources"][0]
        source["seed_names"] = list(seed_names)
        source["valid_seed_names"] = list(seed_names)
        source["valid_seed_count"] = len(seed_names)
        source["excluded_seed_names"] = []
        source["invalid_seed_count"] = 0
        source["total_seed_count"] = len(seed_names)
        request["confirmable_config"]["effective_seed_names"] = list(seed_names)
        save_request_snapshot(load_storage_config(storage_dir), request)

    def test_filter_section_shows_rules_mode_and_case_status(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "咒术回战第三季", "req-filter-display-1")
        _open_request_detail(page, live_server_url, storage_dir, "req-filter-display-1")

        detail = page.locator("#request-detail-container")
        filter_text = detail.locator(".filter-section").inner_text()
        assert "包含规则" in filter_text
        assert "排除规则" in filter_text
        assert "匹配模式" in filter_text
        assert "普通字符" in filter_text
        assert "大小写" in filter_text
        assert "不区分大小写" in filter_text

        # Switch to regex + case-sensitive via the modify form and verify refresh.
        _click_modify(page)
        page.locator("#modify-must-contain").fill("1080p")
        page.locator("#modify-filter-use-regex").check()
        page.locator("#modify-filter-case-sensitive").check()
        page.locator("#detail-modify-form button:has-text('提交修改')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        refreshed = detail.locator(".filter-section").inner_text()
        assert "匹配模式" in refreshed
        assert "正则" in refreshed
        assert "区分大小写" in refreshed
        assert "普通字符" not in refreshed

    def test_literal_v2_exclude_and_reason_display(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        self._save_request_with_seed_names(
            storage_dir,
            "咒术回战第三季",
            "req-filter-v2-literal",
            [
                "[Loli] 咒术回战 第三季 - 01 [1080p][CHS].mkv",
                "[Loli] 咒术回战 第三季 - 01 [v2][1080p][CHS].mkv",
            ],
        )
        _open_request_detail(page, live_server_url, storage_dir, "req-filter-v2-literal")

        _click_modify(page)
        page.locator("#modify-must-not-contain").fill("[v2]")
        page.locator("#detail-modify-form button:has-text('提交修改')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        detail = page.locator("#request-detail-container")
        filter_text = detail.locator(".filter-section").inner_text()
        assert "排除规则" in filter_text
        assert "[v2]" in filter_text
        assert "普通字符" in filter_text
        assert "不区分大小写" in filter_text

        detail.locator(".excluded-seed-details").evaluate("element => element.open = true")
        excluded_text = detail.locator(".excluded-seed-details .seed-group").inner_text()
        valid_text = detail.locator(".effective-seed-group").inner_text()
        assert "[v2]" in excluded_text
        assert "命中排除规则：[v2]" in excluded_text
        assert "[v2]" not in valid_text

    def test_case_insensitive_v2_matches_uppercase_V2(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "咒术回战第三季", "req-filter-ci-v2")
        _open_request_detail(page, live_server_url, storage_dir, "req-filter-ci-v2")

        _click_modify(page)
        page.locator("#modify-must-contain").fill("v2")
        page.locator("#detail-modify-form button:has-text('提交修改')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        detail = page.locator("#request-detail-container")
        filter_text = detail.locator(".filter-section").inner_text()
        assert "包含规则" in filter_text
        assert "v2" in filter_text
        assert "不区分大小写" in filter_text

        detail.locator(".excluded-seed-details").evaluate("element => element.open = true")
        valid_text = detail.locator(".effective-seed-group").inner_text()
        excluded_text = detail.locator(".excluded-seed-details .seed-group").inner_text()
        # Seed 2 contains "V2"; case-insensitive "v2" must match it.
        assert "V2" in valid_text
        assert "未命中包含规则：v2" in excluded_text

    def test_case_sensitive_v2_does_not_match_uppercase_V2(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "咒术回战第三季", "req-filter-cs-v2")
        _open_request_detail(page, live_server_url, storage_dir, "req-filter-cs-v2")

        _click_modify(page)
        page.locator("#modify-must-contain").fill("v2")
        page.locator("#modify-filter-case-sensitive").check()
        page.locator("#detail-modify-form button:has-text('提交修改')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        detail = page.locator("#request-detail-container")
        filter_text = detail.locator(".filter-section").inner_text()
        assert "区分大小写" in filter_text

        detail.locator(".excluded-seed-details").evaluate("element => element.open = true")
        valid_text = detail.locator(".effective-seed-group").inner_text()
        excluded_text = detail.locator(".excluded-seed-details .seed-group").inner_text()
        # Case-sensitive "v2" must NOT match the uppercase "V2" seed.
        assert "V2" not in valid_text
        assert "V2" in excluded_text
        assert "未命中包含规则：v2" in excluded_text

    def test_regex_mode_shows_regex_and_applies_pattern(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "咒术回战第三季", "req-filter-regex-detail")
        _open_request_detail(page, live_server_url, storage_dir, "req-filter-regex-detail")

        _click_modify(page)
        page.locator("#modify-must-not-contain").fill("V2 \\[1080p\\]")
        page.locator("#modify-filter-use-regex").check()
        page.locator("#detail-modify-form button:has-text('提交修改')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        detail = page.locator("#request-detail-container")
        filter_text = detail.locator(".filter-section").inner_text()
        assert "匹配模式" in filter_text
        assert "正则" in filter_text
        # Raw user text is shown as-is, never auto-transformed into a different pattern.
        assert "V2 \\[1080p\\]" in filter_text

        detail.locator(".excluded-seed-details").evaluate("element => element.open = true")
        excluded_text = detail.locator(".excluded-seed-details .seed-group").inner_text()
        valid_text = detail.locator(".effective-seed-group").inner_text()
        assert "命中排除规则：V2 \\[1080p\\]" in excluded_text
        assert "V2 \\[1080p\\]" not in valid_text


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


class TestAcceptedRequestManagement:
    """US-105: ACCEPTED Request 详情展示修改/删除/去 Settings 提交 Auto Bangumi 动作."""

    def test_accepted_request_shows_modify_delete_and_ab_submit(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_accepted_request(storage_dir, "葬送的芙莉莲", "req-accepted-actions")
        _open_request_detail(page, live_server_url, storage_dir, "req-accepted-actions")

        actions = page.locator(".detail-actions")
        assert actions.locator("button:has-text('修改')").count() >= 1
        assert actions.locator("button:has-text('删除')").count() >= 1
        assert (
            actions.locator("a:has-text('去 Settings 提交 Auto Bangumi')").count() >= 1
        )

    def test_accepted_modify_keeps_status_and_refreshes_detail(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_accepted_request(storage_dir, "葬送的芙莉莲", "req-accepted-modify")
        _open_request_detail(page, live_server_url, storage_dir, "req-accepted-modify")

        page.locator(".detail-actions button:has-text('修改')").click()
        page.wait_for_timeout(300)
        assert page.locator("#detail-modify-form").is_visible()
        page.locator("#modify-folder-name").fill("ACCEPTED 修改目录")
        page.locator("#detail-modify-form button:has-text('提交修改')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert "修改成功" in page.locator("#page-notification").inner_text()
        detail_text = page.locator("#request-detail-container").inner_text()
        assert "已确认" in detail_text
        assert "ACCEPTED 修改目录" in detail_text
        assert (
            "ACCEPTED"
            in page.locator("[data-request-id='req-accepted-modify']").inner_text()
        )

    def test_accepted_delete_success_refreshes_list_and_clears_detail(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_accepted_request(storage_dir, "葬送的芙莉莲", "req-accepted-delete")
        _open_request_detail(page, live_server_url, storage_dir, "req-accepted-delete")

        seen_dialogs: list[str] = []
        page.on(
            "dialog",
            lambda dialog: (seen_dialogs.append(dialog.message), dialog.accept()),
        )
        page.locator(".detail-actions button:has-text('删除')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert seen_dialogs
        assert "确认删除此订阅方案" in seen_dialogs[0]
        assert "删除成功" in page.locator("#page-notification").inner_text()
        assert page.locator("[data-request-id='req-accepted-delete']").count() == 0
        detail_text = page.locator("#request-detail-container").inner_text()
        assert "订阅方案已删除" in detail_text
        assert "request_id=" not in page.url
        assert not (storage_dir / "requests" / "req-accepted-delete.json").exists()

    def test_accepted_delete_cancel_does_not_call_api(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_accepted_request(
            storage_dir, "葬送的芙莉莲", "req-accepted-delete-cancel"
        )
        calls: list[str] = []

        def handle_delete(route: object) -> None:
            calls.append(str(getattr(route, "request").url))
            getattr(route, "continue_")()

        page.route(
            "**/api/v1/requests/req-accepted-delete-cancel/delete**", handle_delete
        )
        _open_request_detail(
            page, live_server_url, storage_dir, "req-accepted-delete-cancel"
        )

        page.on("dialog", lambda dialog: dialog.dismiss())
        page.locator(".detail-actions button:has-text('删除')").click()
        page.wait_for_timeout(600)

        assert calls == []
        assert page.locator("[data-request-id='req-accepted-delete-cancel']").count() >= 1
        assert (
            "req-accepted-delete-cancel"
            in page.locator("#request-detail-container").inner_text()
        )
        assert "request_id=req-accepted-delete-cancel" in page.url

    def test_delete_failure_keeps_detail_and_shows_error(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_accepted_request(
            storage_dir, "葬送的芙莉莲", "req-accepted-delete-fail"
        )

        def handle_delete(route: object) -> None:
            getattr(route, "fulfill")(
                status=500,
                json={
                    "ok": False,
                    "error_type": "storage_error",
                    "error_message": "删除订阅方案 JSON 失败",
                },
            )

        page.route(
            "**/api/v1/requests/req-accepted-delete-fail/delete**", handle_delete
        )
        _open_request_detail(
            page, live_server_url, storage_dir, "req-accepted-delete-fail"
        )

        page.on("dialog", lambda dialog: dialog.accept())
        page.locator(".detail-actions button:has-text('删除')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert "删除失败" in page.locator("#page-notification").inner_text()
        assert page.locator("[data-request-id='req-accepted-delete-fail']").count() >= 1
        assert (
            "req-accepted-delete-fail"
            in page.locator("#request-detail-container").inner_text()
        )
        assert "request_id=req-accepted-delete-fail" in page.url

    def test_accepted_modify_failure_keeps_form_and_detail(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_accepted_request(
            storage_dir, "葬送的芙莉莲", "req-accepted-modify-fail"
        )

        def handle_modify(route: object) -> None:
            getattr(route, "fulfill")(
                status=500,
                json={
                    "ok": False,
                    "error_type": "invalid_modify_patch",
                    "error_message": "修改失败",
                },
            )

        page.route(
            "**/api/v1/requests/req-accepted-modify-fail/modify**", handle_modify
        )
        _open_request_detail(
            page, live_server_url, storage_dir, "req-accepted-modify-fail"
        )

        page.locator(".detail-actions button:has-text('修改')").click()
        page.wait_for_timeout(300)
        page.locator("#modify-folder-name").fill("失败后仍保留")
        page.locator("#detail-modify-form button:has-text('提交修改')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert "修改失败" in page.locator("#page-notification").inner_text()
        assert page.locator("#detail-modify-form").is_visible()
        assert page.locator("#modify-folder-name").input_value() == "失败后仍保留"
        detail_text = page.locator("#request-detail-container").inner_text()
        assert "已确认" in detail_text
        assert page.locator("[data-request-id='req-accepted-modify-fail']").count() >= 1


class TestHttpStatusErrorHandling:
    """US-192: 非 2xx JSON 与网络失败显示中文安全反馈，且不泄露敏感值."""

    def test_non_2xx_json_error_shows_chinese_safe_message(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-status-409")

        def handle_accept(route: object) -> None:
            getattr(route, "fulfill")(
                status=409,
                content_type="application/json",
                body=(
                    '{"ok": false, "error_type": "invalid_request_status", '
                    '"error_message": "订阅方案状态已变更，请刷新后重试", '
                    '"error_data": {"failed_step": "confirm"}}'
                ),
            )

        page.route(
            "**/api/v1/requests/req-status-409/accept**", handle_accept
        )
        _open_request_detail(page, live_server_url, storage_dir, "req-status-409")

        page.on("dialog", lambda dialog: dialog.accept())
        _click_confirm(page)
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        # The envelope's Chinese error_message is shown, not a raw status page.
        notification = page.locator("#page-notification").inner_text()
        assert "订阅方案状态已变更，请刷新后重试" in notification
        assert "request_id=req-status-409" in page.url

    def test_non_json_error_body_falls_back_to_generic_message(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-status-html")

        def handle_cancel(route: object) -> None:
            getattr(route, "fulfill")(
                status=502,
                content_type="text/html",
                body="<html><body>Bad Gateway</body></html>",
            )

        page.route(
            "**/api/v1/requests/req-status-html/cancel**", handle_cancel
        )
        _open_request_detail(page, live_server_url, storage_dir, "req-status-html")

        _click_cancel(page)
        assert page.locator("#detail-cancel-form").is_visible()
        page.on("dialog", lambda dialog: dialog.accept())
        page.locator("#detail-cancel-form button:has-text('提交取消')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        # A non-JSON error body must not crash fetchJson or render raw HTML;
        # the user sees the safe generic fallback message.
        notification = page.locator("#page-notification").inner_text()
        assert "请求失败，请稍后重试" in notification
        assert "Bad Gateway" not in notification

    def test_network_failure_shows_retryable_message(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-status-net")

        def handle_network(route: object) -> None:
            route.abort("connectionfailed")

        page.route(
            "**/api/v1/requests/req-status-net/accept**", handle_network
        )
        _open_request_detail(page, live_server_url, storage_dir, "req-status-net")

        page.on("dialog", lambda dialog: dialog.accept())
        _click_confirm(page)
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        notification = page.locator("#page-notification").inner_text()
        assert "网络请求失败" in notification
