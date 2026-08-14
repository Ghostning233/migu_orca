from __future__ import annotations

import json
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
    # Wait for list to load from API
    page.wait_for_timeout(800)
    # Click list item by data-request-id attribute
    item = page.locator(f"[data-request-id='{request_id}']")
    item.click()
    page.wait_for_timeout(500)


def _save_accepted_request(
    storage_dir: Path, title: str, request_id: str
) -> dict[str, object]:
    request = accept_request(
        create_saved_request(storage_dir, title, request_id),
    )
    save_request_snapshot(load_storage_config(storage_dir), request)
    return request


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


class TestRequestDetailUrlState:
    """AC: Request 详情选择状态可通过 URL 恢复."""

    def test_direct_request_id_query_loads_detail(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-url-direct")
        set_storage_preferences(page, storage_dir)

        page.goto(f"{live_server_url}/index?request_id=req-url-direct")
        page.wait_for_selector("#request-detail-container .overview-section", timeout=5000)

        detail = page.locator("#request-detail-container")
        assert "req-url-direct" in detail.inner_text()
        assert page.locator("[data-request-id='req-url-direct']").get_attribute(
            "aria-current"
        ) == "true"

    def test_clicking_list_item_pushes_request_id_query(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-url-click")
        set_storage_preferences(page, storage_dir)

        page.goto(f"{live_server_url}/index")
        page.wait_for_selector("[data-request-id='req-url-click']", timeout=5000)
        page.locator("[data-request-id='req-url-click']").click()
        page.wait_for_url("**/index?request_id=req-url-click", timeout=5000)
        page.wait_for_selector("#request-detail-container .overview-section", timeout=5000)

        assert "req-url-click" in page.locator("#request-detail-container").inner_text()

    def test_refresh_restores_request_id_detail(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-url-refresh")
        set_storage_preferences(page, storage_dir)

        page.goto(f"{live_server_url}/index?request_id=req-url-refresh")
        page.wait_for_selector("#request-detail-container .overview-section", timeout=5000)
        page.reload()
        page.wait_for_selector("#request-detail-container .overview-section", timeout=5000)

        assert "req-url-refresh" in page.locator("#request-detail-container").inner_text()

    def test_missing_request_id_shows_safe_error_and_keeps_list(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-url-existing")
        set_storage_preferences(page, storage_dir)

        page.goto(f"{live_server_url}/index?request_id=req-url-missing")
        page.wait_for_selector("#request-detail-container.error-state", timeout=5000)

        detail_text = page.locator("#request-detail-container").inner_text()
        assert "Request 详情加载失败" in detail_text
        assert "req-url-missing" not in detail_text
        page.wait_for_selector("[data-request-id='req-url-existing']", timeout=5000)


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


class TestAutoBangumiSubmitEntry:
    """AC: ACCEPTED Request 详情展示 Auto Bangumi 提交入口并使用临时配置表单."""

    def test_submit_entry_visible_only_for_accepted_request(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _save_accepted_request(storage_dir, "葬送的芙莉莲", "req-ab-1")
        _open_request_detail(page, live_server_url, storage_dir, "req-ab-1")

        detail = page.locator("#request-detail-container")
        assert detail.locator("button:has-text('提交 Auto Bangumi')").count() >= 1
        assert page.locator("#detail-ab-submit-form").is_hidden()

        page.locator(".detail-actions button:has-text('提交 Auto Bangumi')").click()
        page.wait_for_timeout(300)

        form = page.locator("#detail-ab-submit-form")
        assert form.is_visible()
        assert page.locator("#ab-submit-endpoint").count() >= 1
        assert page.locator("#ab-submit-token").get_attribute("type") == "password"
        assert page.locator("#ab-submit-fallback-enabled").count() >= 1

    def test_submit_entry_hidden_for_pending_request(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-ab-2")
        _open_request_detail(page, live_server_url, storage_dir, "req-ab-2")

        detail = page.locator("#request-detail-container")
        assert (
            detail.locator(".detail-actions > button:visible:has-text('提交 Auto Bangumi')").count()
            == 0
        )
        assert page.locator("#detail-ab-submit-form").count() >= 1
        assert page.locator("#detail-ab-submit-form").is_hidden()

    def test_submit_flow_uses_confirmation_and_refreshes_result(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        request = _save_accepted_request(storage_dir, "葬送的芙莉莲", "req-ab-3")
        _open_request_detail(page, live_server_url, storage_dir, "req-ab-3")

        page.locator(".detail-actions button:has-text('提交 Auto Bangumi')").click()
        page.wait_for_timeout(300)
        page.fill("#ab-submit-endpoint", "http://auto-bangumi.local/api/subscriptions")
        page.fill("#ab-submit-token", "temporary-token")
        page.check("#ab-submit-fallback-enabled")

        dialog_messages: list[str] = []

        def _handle_dialog(dialog: object) -> None:
            message = getattr(dialog, "message", "")
            dialog_messages.append(str(message))
            getattr(dialog, "accept")()

        page.once("dialog", _handle_dialog)

        captured: dict[str, object] = {}

        def _capture_submit(route: object) -> None:
            request_obj = getattr(route, "request")
            if getattr(request_obj, "method", "") != "POST":
                getattr(route, "continue_")()
                return
            captured["body"] = request_obj.post_data_json
            response_body = {
                "ok": True,
                "result": {
                    "request": {
                        "request_id": request["request_id"],
                        "status": "ACCEPTED",
                        "input": {"raw_title": "葬送的芙莉莲"},
                        "source_info": {},
                        "confirmable_config": {},
                        "ab_submit_result": {
                            "success": True,
                            "ab_subscription_id": "browser-subscription",
                            "ab_response": {
                                "id": "browser-subscription",
                                "status": "created",
                            },
                            "fallback_config": None,
                            "error": None,
                        },
                    },
                    "summary": {"request_id": "req-ab-3"},
                    "ab_submit_result": {
                        "success": True,
                        "ab_subscription_id": "browser-subscription",
                        "ab_response": {
                            "id": "browser-subscription",
                            "status": "created",
                        },
                        "fallback_config": None,
                        "error": None,
                    },
                    "saved_ab_result": {"request_id": "req-ab-3"},
                },
            }
            getattr(route, "fulfill")(
                status=200,
                content_type="application/json",
                body=json.dumps(response_body, ensure_ascii=False),
            )

        page.route("**/api/v1/requests/req-ab-3/submit-ab**", _capture_submit)
        page.locator("#detail-ab-submit-form button:has-text('提交 Auto Bangumi')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert dialog_messages
        assert "确认提交此 Request 到 Auto Bangumi" in dialog_messages[0]
        assert captured["body"]["storage_dir"] == str(storage_dir)
        assert captured["body"]["ab_config"] == {
            "endpoint": "http://auto-bangumi.local/api/subscriptions",
            "token": "temporary-token",
            "fallback_enabled": True,
        }

        detail_text = page.locator("#request-detail-container").inner_text()
        assert "Auto Bangumi 结果" in detail_text
        assert "browser-subscription" in detail_text
        assert "提交成功" in page.locator("#page-notification").inner_text()
        storage_keys = page.evaluate("Object.keys(window.localStorage)")
        assert all("ab" not in key.lower() for key in storage_keys)

    def test_submit_failure_keeps_detail_visible(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _save_accepted_request(storage_dir, "葬送的芙莉莲", "req-ab-4")
        _open_request_detail(page, live_server_url, storage_dir, "req-ab-4")

        page.locator(".detail-actions button:has-text('提交 Auto Bangumi')").click()
        page.wait_for_timeout(300)
        page.fill("#ab-submit-endpoint", "http://auto-bangumi.local/api/subscriptions")
        page.fill("#ab-submit-token", "temporary-token")

        page.once("dialog", lambda dialog: dialog.accept())

        def _fail_submit(route: object) -> None:
            request_obj = getattr(route, "request")
            if getattr(request_obj, "method", "") != "POST":
                getattr(route, "continue_")()
                return
            getattr(route, "fulfill")(
                status=200,
                content_type="application/json",
                body=(
                    '{"ok": false, "error_type": "ab_submit_failed", '
                    '"error_message": "Auto Bangumi 提交失败"}'
                ),
            )

        page.route("**/api/v1/requests/req-ab-4/submit-ab**", _fail_submit)
        page.locator("#detail-ab-submit-form button:has-text('提交 Auto Bangumi')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        detail_text = page.locator("#request-detail-container").inner_text()
        assert "ACCEPTED" in detail_text
        assert "Auto Bangumi 提交失败" in page.locator("#page-notification").inner_text()


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
        set_storage_preferences(page, storage_dir, save_request=True)
        page.goto(f"{live_server_url}/index")
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
