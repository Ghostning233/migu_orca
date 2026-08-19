from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from batch_engine.controllers.batch_queue_controller import (
    create_submission_queue,
    enqueue_item,
)
from storage_engine.controllers.queue_repository import save_submission_queue
from storage_engine.controllers.storage_config import load_storage_config
from tests.browser.conftest import create_saved_request, set_storage_preferences


pytestmark = pytest.mark.browser


def _preferences_path(storage_root: Path) -> Path:
    config = load_storage_config(storage_root)
    return config.preferences_dir / "user_preferences.json"


def _save_preferences_via_api(storage_root: Path, preferences: dict[str, Any]) -> None:
    """Persist a preference set directly through the repository."""
    from storage_engine.controllers.preference_repository import (
        build_preferences_from_api,
        save_user_preferences,
    )

    model = build_preferences_from_api(preferences)
    save_user_preferences(load_storage_config(storage_root), model)


def _fill_preference_form(
    page: Page,
    *,
    preferred: str = "",
    excluded: str = "",
    must_contain: str = "",
    must_not_contain: str = "",
) -> None:
    if preferred:
        page.fill("#preference-preferred-groups", preferred)
    if excluded:
        page.fill("#preference-excluded-groups", excluded)
    if must_contain:
        page.fill("#preference-filter-must-contain", must_contain)
    if must_not_contain:
        page.fill("#preference-filter-must-not-contain", must_not_contain)


class TestPreferenceSettingsLoad:
    """AC: 页面加载时展示已保存偏好；无保存数据时展示默认偏好."""

    def test_loads_default_preferences_on_page_load(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        set_storage_preferences(page, storage_dir)
        page.goto(f"{live_server_url}/settings")

        expect(page.locator("#preference-settings-status")).to_contain_text(
            "已读取偏好默认值", timeout=5000
        )
        assert page.locator("#preference-preferred-groups").input_value() == ""
        assert page.locator("#preference-excluded-groups").input_value() == ""
        assert page.locator("#preference-fallback").input_value() == "next_preferred"
        assert page.locator("#preference-filter-must-contain").input_value() == ""
        assert page.locator("#preference-filter-must-not-contain").input_value() == ""
        assert not page.locator("#preference-filter-use-regex").is_checked()
        assert not page.locator("#preference-filter-case-sensitive").is_checked()
        assert (
            page.locator("#preference-naming-strategy").input_value()
            == "official_title_season"
        )
        assert page.locator("#preference-naming-template").input_value() == "{title}"
        assert page.locator("#preference-search-reuse-corrections").is_checked()

    def test_loads_saved_preferences_on_page_load(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _save_preferences_via_api(
            storage_dir,
            {
                "subtitle_groups": {
                    "preferred": ["喵萌"],
                    "excluded": ["Loli"],
                    "fallback": "none",
                },
                "filter_defaults": {
                    "must_contain": "1080p",
                    "must_not_contain": "合集版",
                    "use_regex": True,
                    "case_sensitive": True,
                },
                "naming": {"strategy": "raw_title", "template": "[{title}]"},
                "search": {"reuse_explicit_corrections": False},
            },
        )
        set_storage_preferences(page, storage_dir)
        page.goto(f"{live_server_url}/settings")

        expect(page.locator("#preference-settings-status")).to_contain_text(
            "已读取偏好默认值", timeout=5000
        )
        assert page.locator("#preference-preferred-groups").input_value() == "喵萌"
        assert page.locator("#preference-excluded-groups").input_value() == "Loli"
        assert page.locator("#preference-fallback").input_value() == "none"
        assert page.locator("#preference-filter-must-contain").input_value() == "1080p"
        assert page.locator("#preference-filter-must-not-contain").input_value() == "合集版"
        assert page.locator("#preference-filter-use-regex").is_checked()
        assert page.locator("#preference-filter-case-sensitive").is_checked()
        assert page.locator("#preference-naming-strategy").input_value() == "raw_title"
        assert page.locator("#preference-naming-template").input_value() == "[{title}]"
        assert not page.locator("#preference-search-reuse-corrections").is_checked()


class TestPreferenceSettingsSave:
    """AC: 保存成功后展示中文成功反馈并刷新规范化值；刷新后偏好保持."""

    def test_save_shows_success_and_persists_across_reload(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        set_storage_preferences(page, storage_dir)
        page.goto(f"{live_server_url}/settings")
        expect(page.locator("#preference-settings-status")).to_contain_text(
            "已读取偏好默认值", timeout=5000
        )

        _fill_preference_form(
            page,
            preferred="喵萌\nLoli",
            excluded="其他",
            must_contain="1080p",
            must_not_contain="合集版",
        )
        page.locator("#preference-naming-strategy").select_option("raw_title")
        page.locator("#preference-naming-template").fill("[{title}]")
        page.check("#preference-filter-use-regex")
        page.check("#preference-filter-case-sensitive")
        page.uncheck("#preference-search-reuse-corrections")
        page.click("#preference-settings-save")

        expect(page.locator("#preference-settings-status")).to_contain_text(
            "偏好默认值已保存", timeout=5000
        )
        expect(page.locator("#page-notification:not([hidden])")).to_contain_text(
            "偏好默认值已保存", timeout=5000
        )
        assert _preferences_path(storage_dir).exists()

        page.reload()
        expect(page.locator("#preference-settings-status")).to_contain_text(
            "已读取偏好默认值", timeout=5000
        )
        assert page.locator("#preference-preferred-groups").input_value() == "喵萌\nLoli"
        assert page.locator("#preference-excluded-groups").input_value() == "其他"
        assert page.locator("#preference-filter-must-contain").input_value() == "1080p"
        assert page.locator("#preference-filter-must-not-contain").input_value() == "合集版"
        assert page.locator("#preference-filter-use-regex").is_checked()
        assert page.locator("#preference-filter-case-sensitive").is_checked()
        assert page.locator("#preference-naming-strategy").input_value() == "raw_title"
        assert page.locator("#preference-naming-template").input_value() == "[{title}]"
        assert not page.locator("#preference-search-reuse-corrections").is_checked()

    def test_save_normalizes_preferred_groups(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        set_storage_preferences(page, storage_dir)
        page.goto(f"{live_server_url}/settings")
        expect(page.locator("#preference-settings-status")).to_contain_text(
            "已读取偏好默认值", timeout=5000
        )

        page.fill("#preference-preferred-groups", "喵萌\n\n   \nLoli")
        page.click("#preference-settings-save")

        expect(page.locator("#preference-settings-status")).to_contain_text(
            "偏好默认值已保存", timeout=5000
        )
        # 空行被规范化为删除，只保留非空字幕组。
        assert page.locator("#preference-preferred-groups").input_value() == "喵萌\nLoli"

    def test_save_accepts_empty_lists(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        set_storage_preferences(page, storage_dir)
        page.goto(f"{live_server_url}/settings")
        expect(page.locator("#preference-settings-status")).to_contain_text(
            "已读取偏好默认值", timeout=5000
        )

        page.click("#preference-settings-save")
        expect(page.locator("#preference-settings-status")).to_contain_text(
            "偏好默认值已保存", timeout=5000
        )
        assert page.locator("#preference-preferred-groups").input_value() == ""
        assert page.locator("#preference-excluded-groups").input_value() == ""


class TestPreferenceSettingsValidation:
    """AC: 非法输入展示统一中文错误，且不写入偏好文件."""

    def test_sensitive_value_shows_error_and_no_file_written(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        set_storage_preferences(page, storage_dir)
        page.goto(f"{live_server_url}/settings")
        expect(page.locator("#preference-settings-status")).to_contain_text(
            "已读取偏好默认值", timeout=5000
        )

        page.fill(
            "#preference-preferred-groups",
            "https://mikan.example/Home/Search",
        )
        page.click("#preference-settings-save")

        expect(page.locator("#preference-settings-error")).to_contain_text(
            "敏感内容", timeout=5000
        )
        expect(page.locator("#preference-settings-status")).to_contain_text(
            "保存偏好默认值失败", timeout=5000
        )
        assert not _preferences_path(storage_dir).exists()
        # 被拒绝的敏感输入不会残留在表单中。
        assert page.locator("#preference-preferred-groups").input_value() == ""

    def test_duplicate_subtitle_groups_shows_error(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        set_storage_preferences(page, storage_dir)
        page.goto(f"{live_server_url}/settings")
        expect(page.locator("#preference-settings-status")).to_contain_text(
            "已读取偏好默认值", timeout=5000
        )

        page.fill("#preference-preferred-groups", "喵萌\n喵萌")
        page.click("#preference-settings-save")

        expect(page.locator("#preference-settings-error")).to_contain_text(
            "重复字幕组", timeout=5000
        )
        assert not _preferences_path(storage_dir).exists()


class TestPreferenceSettingsReset:
    """AC: 恢复默认必须显式触发，且不会清除订阅方案、队列或 AB result 存储."""

    def test_reset_requires_confirm_and_restores_defaults(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        set_storage_preferences(page, storage_dir)
        page.goto(f"{live_server_url}/settings")
        expect(page.locator("#preference-settings-status")).to_contain_text(
            "已读取偏好默认值", timeout=5000
        )
        page.fill("#preference-preferred-groups", "喵萌")
        page.click("#preference-settings-save")
        expect(page.locator("#preference-settings-status")).to_contain_text(
            "偏好默认值已保存", timeout=5000
        )
        assert page.locator("#preference-preferred-groups").input_value() == "喵萌"

        dialogs: list[str] = []
        page.once(
            "dialog",
            lambda dialog: (dialogs.append(dialog.message), dialog.accept()),
        )
        page.click("#preference-settings-reset")

        assert dialogs and "确认恢复所有偏好为默认值" in dialogs[0]
        expect(page.locator("#preference-settings-status")).to_contain_text(
            "已恢复默认偏好", timeout=5000
        )
        assert page.locator("#preference-preferred-groups").input_value() == ""
        assert page.locator("#preference-fallback").input_value() == "next_preferred"
        assert page.locator("#preference-naming-strategy").input_value() == "official_title_season"

    def test_reset_cancelled_keeps_preferences(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        set_storage_preferences(page, storage_dir)
        page.goto(f"{live_server_url}/settings")
        expect(page.locator("#preference-settings-status")).to_contain_text(
            "已读取偏好默认值", timeout=5000
        )
        page.fill("#preference-preferred-groups", "喵萌")
        page.click("#preference-settings-save")
        expect(page.locator("#preference-settings-status")).to_contain_text(
            "偏好默认值已保存", timeout=5000
        )

        page.once("dialog", lambda dialog: dialog.dismiss())
        page.click("#preference-settings-reset")
        page.wait_for_timeout(300)

        # 取消后表单保持原值，未触发恢复默认。
        assert page.locator("#preference-preferred-groups").input_value() == "喵萌"
        assert "已恢复默认偏好" not in page.locator("#preference-settings-status").inner_text()

    def test_reset_does_not_touch_requests_or_queue(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        # 预置一个已保存订阅方案和一个提交队列，模拟 Stage 20 状态。
        create_saved_request(storage_dir, "咒术回战 第三季", "req-pref-reset")
        queue = create_submission_queue("batch-pref-reset")
        queue = enqueue_item(
            queue,
            item_id="item-pref-reset",
            request_id="req-pref-reset",
            title="咒术回战 第三季",
        )
        save_submission_queue(load_storage_config(storage_dir), queue)

        set_storage_preferences(page, storage_dir)
        page.goto(f"{live_server_url}/settings")
        expect(page.locator("#preference-settings-status")).to_contain_text(
            "已读取偏好默认值", timeout=5000
        )
        page.fill("#preference-preferred-groups", "喵萌")
        page.click("#preference-settings-save")
        expect(page.locator("#preference-settings-status")).to_contain_text(
            "偏好默认值已保存", timeout=5000
        )

        page.once("dialog", lambda dialog: dialog.accept())
        page.click("#preference-settings-reset")
        expect(page.locator("#preference-settings-status")).to_contain_text(
            "已恢复默认偏好", timeout=5000
        )

        config = load_storage_config(storage_dir)
        assert (config.requests_dir / "req-pref-reset.json").exists()
        assert (config.queue_dir / "batch-pref-reset.json").exists()
        assert (config.preferences_dir / "user_preferences.json").exists()


class TestPreferenceSettingsSensitiveBoundary:
    """AC: 表单与浏览器表面不出现外部 endpoint/token/cookie/raw 响应."""

    def test_sensitive_values_never_appear_in_browser_surfaces(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        set_storage_preferences(page, storage_dir)
        page.goto(f"{live_server_url}/settings")
        expect(page.locator("#preference-settings-status")).to_contain_text(
            "已读取偏好默认值", timeout=5000
        )

        sensitive = "https://mikan.example/Home/Search"
        page.fill("#preference-preferred-groups", sensitive)
        page.click("#preference-settings-save")
        expect(page.locator("#preference-settings-status")).to_contain_text(
            "保存偏好默认值失败", timeout=5000
        )

        body = page.locator("body").inner_text()
        assert sensitive not in body
        assert "mikan.example" not in body

        url = page.url
        assert sensitive not in url

        # 被拒绝的敏感输入不会残留在表单控件中。
        assert page.locator("#preference-preferred-groups").input_value() == ""

        stored = page.evaluate(
            "() => ({ls: Object.keys(localStorage).map(k => localStorage.getItem(k)), "
            "ss: Object.keys(sessionStorage).map(k => sessionStorage.getItem(k))})"
        )
        for values in (stored["ls"], stored["ss"]):
            assert not any(sensitive in (value or "") for value in values)
