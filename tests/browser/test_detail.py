from __future__ import annotations

import json
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import (
    create_saved_request,
    open_dev_fixture_panel,
    set_storage_preferences,
)
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
        assert "订阅方案详情加载失败" in detail_text
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
    """AC: ACCEPTED Request 详情展示 Settings Auto Bangumi 提交入口."""

    def test_submit_entry_visible_only_for_accepted_request(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _save_accepted_request(storage_dir, "葬送的芙莉莲", "req-ab-1")
        _open_request_detail(page, live_server_url, storage_dir, "req-ab-1")

        detail = page.locator("#request-detail-container")
        entry = detail.locator("a:has-text('去 Settings 提交 Auto Bangumi')")
        assert entry.count() >= 1
        assert entry.get_attribute("href") == "/settings?request_id=req-ab-1#auto-bangumi"
        assert page.locator("#detail-ab-submit-form").count() == 0

    def test_submit_entry_hidden_for_pending_request(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-ab-2")
        _open_request_detail(page, live_server_url, storage_dir, "req-ab-2")

        detail = page.locator("#request-detail-container")
        assert (
            detail.locator(
                ".detail-actions > a:visible:has-text('去 Settings 提交 Auto Bangumi')"
            ).count()
            == 0
        )
        assert page.locator("#detail-ab-submit-form").count() == 0

    def test_submit_flow_uses_confirmation_and_refreshes_result(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        request = _save_accepted_request(storage_dir, "葬送的芙莉莲", "req-ab-3")
        set_storage_preferences(page, storage_dir)
        page.goto(f"{live_server_url}/settings?request_id=req-ab-3#auto-bangumi")
        page.select_option("#settings-ab-auth-mode", "api_token")
        page.fill("#settings-ab-endpoint", "http://auto-bangumi.local/api/subscriptions")
        page.fill("#settings-ab-token", "temporary-token")
        page.check("#settings-ab-fallback-enabled")

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
        page.locator("#settings-ab-submit").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert dialog_messages
        assert "确认提交此订阅方案到 Auto Bangumi" in dialog_messages[0]
        assert captured["body"]["storage_dir"] == storage_dir.name
        assert captured["body"]["ab_config"] == {
            "auth_mode": "api_token",
            "base_url": "http://auto-bangumi.local/api/subscriptions",
            "token": "temporary-token",
            "fallback_enabled": True,
        }

        settings_text = page.locator("#auto-bangumi-settings-panel").inner_text()
        assert "Auto Bangumi 提交成功" in settings_text
        assert "browser-subscription" in settings_text
        assert page.locator("#settings-ab-endpoint").input_value() == ""
        assert page.locator("#settings-ab-token").input_value() == ""
        assert page.locator("#settings-ab-return-link").get_attribute("href") == (
            "/index?request_id=req-ab-3"
        )
        assert "提交成功" in page.locator("#page-notification").inner_text()
        storage_keys = page.evaluate("Object.keys(window.localStorage)")
        assert all("ab" not in key.lower() for key in storage_keys)

    def test_submit_failure_keeps_detail_visible(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _save_accepted_request(storage_dir, "葬送的芙莉莲", "req-ab-4")
        set_storage_preferences(page, storage_dir)
        page.goto(f"{live_server_url}/settings?request_id=req-ab-4#auto-bangumi")
        page.select_option("#settings-ab-auth-mode", "api_token")
        page.fill("#settings-ab-endpoint", "http://auto-bangumi.local/api/subscriptions")
        page.fill("#settings-ab-token", "temporary-token")

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
        page.locator("#settings-ab-submit").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        settings_text = page.locator("#auto-bangumi-settings-panel").inner_text()
        assert "req-ab-4" in settings_text
        assert "Auto Bangumi 提交失败" in page.locator("#page-notification").inner_text()


class TestSeedsExpandable:
    """AC: Seeds 区块按 有效种子 -> 完整种子（按字幕组分组）-> 排除种子 展示."""

    def test_seeds_section_has_details_element(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-detail-5")
        _open_request_detail(page, live_server_url, storage_dir, "req-detail-5")

        detail = page.locator("#request-detail-container")
        assert detail.locator(".effective-seed-group").count() == 1
        assert detail.locator(".complete-seed-details").count() == 1
        assert detail.locator(".excluded-seed-details").count() == 1

    def test_seeds_label_present(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-detail-5")
        _open_request_detail(page, live_server_url, storage_dir, "req-detail-5")

        detail = page.locator("#request-detail-container")
        text = detail.inner_text()
        assert "有效种子" in text
        assert "完整种子" in text
        assert "排除种子" in text
        assert "当前选中字幕组" in text

    def test_seeds_section_shows_three_title_lists_and_counts(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "咒术回战第三季", "req-detail-seeds")
        _open_request_detail(page, live_server_url, storage_dir, "req-detail-seeds")

        detail = page.locator("#request-detail-container")
        # Effective seeds are always visible and name the current subtitle group.
        effective_text = detail.locator(".effective-seed-group").inner_text()
        assert "有效种子（当前选中字幕组：Loli）(2)" in effective_text
        assert "[Loli] 咒术回战 第三季 - 01 [1080p][CHS].mkv" in effective_text
        assert "[Loli] 咒术回战 第三季 - 01 V2 [1080p][CHS].mkv" in effective_text
        # Complete seeds are grouped by subtitle group with per-group counts.
        assert "完整种子（按字幕组分组）(3)" in detail.inner_text()
        detail.locator(".complete-seed-details").evaluate("element => element.open = true")
        complete_text = detail.locator(".complete-seed-groups").inner_text()
        assert "Loli (2)" in complete_text
        assert "喵萌 (1)" in complete_text
        # Expanding a subgroup reveals its seed list.
        detail.locator(".subgroup-seed-group").first.evaluate("element => element.open = true")
        detail.locator(".subgroup-seed-group").last.evaluate("element => element.open = true")
        complete_text = detail.locator(".complete-seed-groups").inner_text()
        assert "[Loli] 咒术回战 第三季 - 01 [1080p][CHS].mkv" in complete_text
        assert "[喵萌] 咒术回战 第三季 - 01 [1080p][CHS].mkv" in complete_text
        # Excluded seeds render last as a collapsed area.
        assert "排除种子 (0)" in detail.inner_text()
        detail.locator(".excluded-seed-details").evaluate("element => element.open = true")
        assert "无排除种子标题。" in detail.locator(".excluded-seed-details").inner_text()

    def test_seeds_section_empty_states_are_consistent(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        request = create_saved_request(storage_dir, "葬送的芙莉莲", "req-detail-empty-seeds")
        source = request["source_info"]["rss_sources"][0]
        source["seed_names"] = []
        source["total_seed_count"] = 0
        source["valid_seed_names"] = []
        source["valid_seed_count"] = 0
        source["excluded_seed_names"] = []
        source["invalid_seed_count"] = 0
        request["confirmable_config"]["effective_seed_names"] = []
        save_request_snapshot(load_storage_config(storage_dir), request)

        _open_request_detail(page, live_server_url, storage_dir, "req-detail-empty-seeds")

        detail = page.locator("#request-detail-container")
        # Effective seeds area is always visible and empty.
        assert "有效种子（当前选中字幕组：喵萌）(0)" in detail.inner_text()
        assert "无有效种子标题。" in detail.locator(".effective-seed-group").inner_text()
        # Complete seed area collapses and shows per-group empty states.
        assert "完整种子（按字幕组分组）(0)" in detail.inner_text()
        detail.locator(".complete-seed-details").evaluate("element => element.open = true")
        detail.locator(".complete-seed-details .subgroup-seed-group").first.evaluate(
            "element => element.open = true"
        )
        assert "无种子标题。" in detail.locator(".complete-seed-groups").inner_text()
        # Excluded seed area is last and empty.
        detail.locator(".excluded-seed-details").evaluate("element => element.open = true")
        assert "无排除种子标题。" in detail.locator(".excluded-seed-details").inner_text()

    def test_seeds_section_does_not_expose_raw_source_values(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        request = create_saved_request(storage_dir, "葬送的芙莉莲", "req-detail-seed-safe")
        selected_source = request["source_info"]["rss_sources"][0]
        selected_source["rss_url"] = "https://secret.example.invalid/rss.xml?token=hidden-token"
        selected_source["raw_response_body"] = "<rss><channel>hidden-token</channel></rss>"
        save_request_snapshot(load_storage_config(storage_dir), request)

        _open_request_detail(page, live_server_url, storage_dir, "req-detail-seed-safe")

        detail_text = page.locator("#request-detail-container").inner_text()
        assert "hidden-token" not in detail_text
        assert "<rss" not in detail_text
        assert "https://secret.example.invalid" not in detail_text


class TestSeedsGroupedBySubtitleGroup:
    """US-129: Seeds 区展示顺序 有效 -> 完整（按字幕组分组）-> 排除，默认折叠行为正确."""

    def test_seeds_display_order_effective_then_complete_then_excluded(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "咒术回战第三季", "req-seeds-order")
        _open_request_detail(page, live_server_url, storage_dir, "req-seeds-order")

        seeds_text = page.locator("#request-detail-container .seeds-section").inner_text()
        assert seeds_text.index("有效种子") < seeds_text.index("完整种子")
        assert seeds_text.index("完整种子") < seeds_text.index("排除种子")

    def test_complete_seeds_grouped_by_subtitle_group(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "咒术回战第三季", "req-seeds-groups")
        _open_request_detail(page, live_server_url, storage_dir, "req-seeds-groups")

        detail = page.locator("#request-detail-container")
        detail.locator(".complete-seed-details").evaluate("element => element.open = true")
        groups = detail.locator(".subgroup-seed-group")
        assert groups.count() == 2
        assert "Loli (2)" in groups.nth(0).locator("summary").inner_text()
        assert "喵萌 (1)" in groups.nth(1).locator("summary").inner_text()
        # Each group's list is expandable.
        groups.nth(0).evaluate("element => element.open = true")
        groups.nth(1).evaluate("element => element.open = true")
        group_text = detail.locator(".complete-seed-groups").inner_text()
        assert "[Loli] 咒术回战 第三季 - 01 V2 [1080p][CHS].mkv" in group_text
        assert "[喵萌] 咒术回战 第三季 - 01 [1080p][CHS].mkv" in group_text

    def test_effective_seeds_visible_by_default_and_complete_excluded_collapsed(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "咒术回战第三季", "req-seeds-collapse")
        _open_request_detail(page, live_server_url, storage_dir, "req-seeds-collapse")

        detail = page.locator("#request-detail-container")
        # Effective seeds are not wrapped in <details> and their list is visible
        # without any expansion.
        effective = detail.locator(".effective-seed-group")
        expect(effective).to_be_visible()
        assert "[Loli] 咒术回战 第三季 - 01 V2 [1080p][CHS].mkv" in effective.inner_text()
        # Complete and excluded seeds are collapsed by default.
        assert detail.locator(".complete-seed-details").get_attribute("open") is None
        assert detail.locator(".excluded-seed-details").get_attribute("open") is None

    def test_modify_filter_updates_grouped_seeds_display(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "咒术回战第三季", "req-seeds-filter-update")
        _open_request_detail(page, live_server_url, storage_dir, "req-seeds-filter-update")

        page.locator("#detail-modify-form").evaluate("element => element.hidden = false")
        page.locator("#modify-must-not-contain").fill("V2")
        page.locator("#detail-modify-form button:has-text('提交修改')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        detail = page.locator("#request-detail-container")
        # The always-visible effective area reflects the recomputed valid seeds.
        effective_text = detail.locator(".effective-seed-group").inner_text()
        assert "有效种子（当前选中字幕组：Loli）(1)" in effective_text
        assert "V2" not in effective_text
        # The excluded area shows the Chinese exclusion reason.
        detail.locator(".excluded-seed-details").evaluate("element => element.open = true")
        excluded_text = detail.locator(".excluded-seed-details").inner_text()
        assert "命中排除规则：V2" in excluded_text

    def test_grouped_seeds_do_not_render_sensitive_values(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        request = create_saved_request(storage_dir, "咒术回战第三季", "req-seeds-sec")
        for source in request["source_info"]["rss_sources"]:
            source["rss_url"] = "https://secret.example.invalid/rss.xml?token=hidden-token"
            source["raw_response_body"] = "<rss><channel>hidden-token</channel></rss>"
        save_request_snapshot(load_storage_config(storage_dir), request)

        _open_request_detail(page, live_server_url, storage_dir, "req-seeds-sec")

        detail = page.locator("#request-detail-container")
        detail.locator(".complete-seed-details").evaluate("element => element.open = true")
        detail.locator(".excluded-seed-details").evaluate("element => element.open = true")
        text = detail.inner_text()
        assert "hidden-token" not in text
        assert "<rss" not in text
        assert "token=" not in text
        assert "https://secret.example.invalid" not in text


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
        open_dev_fixture_panel(page)
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


class TestChineseStatusLabels:
    """US-128: 状态展示映射为中文，不暴露 PENDING_CONFIRM/ACCEPTED/CANCELLED 代码值."""

    def test_pending_confirm_shows_chinese_label_in_list_and_detail(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-status-pending")
        _open_request_detail(page, live_server_url, storage_dir, "req-status-pending")

        body = page.locator("body").inner_text()
        assert "待确认" in body
        assert "PENDING_CONFIRM" not in body

    def test_accepted_shows_chinese_label_in_list_and_detail(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _save_accepted_request(storage_dir, "葬送的芙莉莲", "req-status-accepted")
        _open_request_detail(page, live_server_url, storage_dir, "req-status-accepted")

        body = page.locator("body").inner_text()
        assert "已确认" in body
        assert "ACCEPTED" not in body

    def test_cancelled_shows_chinese_label_in_list_and_detail(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        from request_engine.controllers.request_controller import cancel_request

        request = cancel_request(
            create_saved_request(storage_dir, "葬送的芙莉莲", "req-status-cancelled"),
            "不需要了",
        )
        save_request_snapshot(load_storage_config(storage_dir), request)
        _open_request_detail(page, live_server_url, storage_dir, "req-status-cancelled")

        body = page.locator("body").inner_text()
        assert "已取消" in body
        assert "CANCELLED" not in body

    def test_status_filter_options_use_chinese_labels(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _save_accepted_request(storage_dir, "葬送的芙莉莲", "req-status-filter-accepted")
        create_saved_request(storage_dir, "咒术回战第三季", "req-status-filter-pending")
        _open_request_detail(page, live_server_url, storage_dir, "req-status-filter-pending")

        options = [
            opt.inner_text()
            for opt in page.locator("#request-list-status-filter option").all()
        ]
        assert "全部" in options
        assert "待确认" in options
        assert "已确认" in options
        # Raw codes never appear as visible filter options.
        assert not any(
            code in o for o in options for code in ("PENDING_CONFIRM", "ACCEPTED", "CANCELLED")
        )
