from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, Request, expect

from tests.browser.conftest import (
    open_dev_fixture_panel,
    set_storage_preferences,
)

pytestmark = [pytest.mark.browser, pytest.mark.legacy_entry]


class TestFormValidation:
    """AC: 提交空白或纯空白标题时，表单附近出现可读错误且不会发起 API 调用."""

    def test_blank_title_shows_error(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/index")
        open_dev_fixture_panel(page)

        # Fill with a space (trims to empty, triggers JS validation like blank input)
        page.locator('input[name="title"]').fill(" ")
        page.locator('input[name="title"]').press("Enter")

        page.wait_for_timeout(500)
        error_text = page.locator("#request-form-error").inner_text()
        assert "请输入标题" in error_text, f"Got: '{error_text}'"

    def test_whitespace_only_title_shows_error(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/index")
        open_dev_fixture_panel(page)

        page.locator('input[name="title"]').fill("   ")
        page.locator('input[name="title"]').press("Enter")
        page.wait_for_timeout(500)

        error = page.locator("#request-form-error")
        assert "请输入标题" in error.inner_text()

    def test_validation_error_visible(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/index")
        open_dev_fixture_panel(page)

        page.locator('input[name="title"]').fill(" ")
        page.locator('input[name="title"]').press("Enter")
        page.wait_for_timeout(500)

        error_text = page.locator("#request-form-error").inner_text().strip()
        assert len(error_text) > 0


class TestWorkbenchSourceControls:
    """AC: /index 不再展示真实 MiKan 配置字段，生成默认使用 fixture 数据源."""

    def test_index_does_not_render_mikan_config(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/index")

        assert page.locator('select[name="source"]').count() == 0
        assert page.locator("#mikan-config-fields").count() == 0
        assert page.locator('input[name="mikan_search_endpoint"]').count() == 0
        assert page.locator('input[name="mikan_timeout_seconds"]').count() == 0

    def test_workbench_payload_uses_fixture_source_and_excludes_mikan_config(
        self, page: Page, live_server_url: str
    ) -> None:
        bodies: list[dict[str, object]] = []

        def _capture(route: Any, request: Request) -> None:
            if request.method != "POST":
                route.continue_()
                return
            bodies.append(request.post_data_json)
            route.fulfill(
                status=200,
                content_type="application/json",
                body=(
                    '{"ok": true, "result": {"request": {"request_id": "browser-fixture", '
                    '"status": "PENDING_CONFIRM", "input": {"raw_title": "葬送的芙莉莲"}, '
                    '"source_info": {}, "confirmable_config": {}}}}'
                ),
            )

        page.route("**/api/v1/requests", _capture)
        page.goto(f"{live_server_url}/index")
        open_dev_fixture_panel(page)
        page.fill('input[name="title"]', "葬送的芙莉莲")

        page.click("#request-generate-submit")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert bodies
        assert bodies[0]["source"] == "static-fixture"
        assert "mikan_config" not in bodies[0]


class TestGenerateWithoutSave:
    """AC: 填写有效标题并保持 save_request 未勾选时，生成成功通知出现."""

    def test_generate_success_notification(self, page: Page, live_server_url: str) -> None:
        set_storage_preferences(page, "preview-profile", save_request=False)
        page.goto(f"{live_server_url}/index")
        open_dev_fixture_panel(page)

        page.fill('input[name="title"]', "葬送的芙莉莲")
        page.click("#request-generate-submit")

        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
        notif = page.locator("#page-notification")
        text = notif.inner_text()
        assert "预览已生成" in text
        assert "订阅草案（未保存）" in page.locator("#request-detail-container").inner_text()

    def test_no_storage_written_when_save_unchecked(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        set_storage_preferences(page, storage_dir, save_request=False)
        page.goto(f"{live_server_url}/index")
        open_dev_fixture_panel(page)

        page.fill('input[name="title"]', "葬送的芙莉莲")
        page.click("#request-generate-submit")

        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
        assert not storage_dir.exists() or not any(storage_dir.iterdir())

    def test_preview_generation_does_not_write_request_id_to_url(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        set_storage_preferences(page, storage_dir, save_request=False)
        page.goto(f"{live_server_url}/index")
        open_dev_fixture_panel(page)

        page.fill('input[name="title"]', "葬送的芙莉莲")
        page.click("#request-generate-submit")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert "request_id=" not in page.url

    def test_preview_detail_is_editable_draft_and_does_not_call_saved_actions(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        set_storage_preferences(page, storage_dir, save_request=False)
        blocked_calls: list[str] = []

        def _capture_saved_action(route: Any, request: Request) -> None:
            blocked_calls.append(request.url)
            route.fulfill(
                status=500,
                content_type="application/json",
                body='{"ok": false, "error_message": "unexpected saved action"}',
            )

        page.route("**/api/v1/requests/*/accept**", _capture_saved_action)
        page.route("**/api/v1/requests/*/cancel**", _capture_saved_action)
        page.route("**/api/v1/requests/*/modify**", _capture_saved_action)
        page.route("**/api/v1/requests/*/delete**", _capture_saved_action)
        page.route("**/api/v1/requests/*/submit-ab**", _capture_saved_action)

        page.goto(f"{live_server_url}/index")
        open_dev_fixture_panel(page)
        page.fill('input[name="title"]', "咒术回战")
        page.click("#request-generate-submit")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        detail = page.locator("#request-detail-container")
        detail_text = detail.inner_text()
        assert "订阅草案（未保存）" in detail_text
        expect(detail.locator("#detail-preview-edit-form")).to_be_visible()
        expect(detail.locator(".detail-actions button:has-text('保存草案')")).to_be_visible()
        # The preview draft offers no saved-request actions.
        expect(detail.locator(".detail-actions button:has-text('确认')")).to_have_count(0)
        expect(detail.locator(".detail-actions button:has-text('取消')")).to_have_count(0)
        expect(detail.locator(".detail-actions button:has-text('删除')")).to_have_count(0)
        expect(detail.locator("text=去 Settings 提交 Auto Bangumi")).to_have_count(0)
        expect(detail.locator("#detail-cancel-form")).to_have_count(0)
        expect(detail.locator("#detail-modify-form")).to_have_count(0)
        assert "request_id=" not in page.url
        assert blocked_calls == []

    def test_preview_save_restores_operable_saved_detail_list_and_url(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        set_storage_preferences(page, storage_dir, save_request=False)
        page.goto(f"{live_server_url}/index")
        open_dev_fixture_panel(page)

        page.fill('input[name="title"]', "咒术回战")
        page.click("#request-generate-submit")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
        assert "request_id=" not in page.url

        page.locator("#request-detail-container button:has-text('保存草案')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        text = page.locator("#page-notification").inner_text()
        assert "保存成功" in text
        assert "request_id=" in page.url
        request_id = page.url.split("request_id=", 1)[1].split("&", 1)[0]
        assert request_id
        expect(page.locator(f"[data-request-id='{request_id}']")).to_be_visible()
        detail = page.locator("#request-detail-container")
        assert "已保存" in detail.inner_text()
        expect(detail.locator(".detail-actions button:has-text('确认')")).to_be_visible()
        expect(detail.locator(".detail-actions button:has-text('取消')")).to_be_visible()
        expect(detail.locator(".detail-actions button:has-text('修改')")).to_be_visible()


class TestGenerateWithSave:
    """AC: 填写有效标题并勾选 save_request 时，保存成功通知包含 request_id."""

    def test_save_success_notification(self, page: Page, live_server_url: str, storage_dir: Path) -> None:
        set_storage_preferences(page, storage_dir, save_request=True)
        page.goto(f"{live_server_url}/index")
        open_dev_fixture_panel(page)

        page.fill('input[name="title"]', "葬送的芙莉莲")
        page.click("#request-generate-submit")

        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
        notif = page.locator("#page-notification")
        text = notif.inner_text()
        assert "保存成功" in text or "已保存订阅方案" in text

    def test_storage_contains_saved_request(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        set_storage_preferences(page, storage_dir, save_request=True)
        page.goto(f"{live_server_url}/index")
        open_dev_fixture_panel(page)

        page.fill('input[name="title"]', "葬送的芙莉莲")
        page.click("#request-generate-submit")

        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
        req_dir = storage_dir / "requests"
        assert req_dir.is_dir()
        assert len(list(req_dir.glob("*.json"))) >= 1

    def test_saved_generation_writes_request_id_to_url(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        set_storage_preferences(page, storage_dir, save_request=True)
        page.goto(f"{live_server_url}/index")
        open_dev_fixture_panel(page)

        page.fill('input[name="title"]', "葬送的芙莉莲")
        page.click("#request-generate-submit")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert "request_id=" in page.url
        request_id = page.url.split("request_id=", 1)[1].split("&", 1)[0]
        assert request_id


class TestDefaultGenerateOperableSavedRequest:
    """US-097: 默认生成流程产出已保存且可操作的 Request."""

    def _seed_storage_dir_only(self, page: Page, storage_root: Path) -> None:
        page.add_init_script(
            """
            window.localStorage.setItem("miguOrca.web.storageDir", %s);
            window.localStorage.removeItem("miguOrca.web.saveRequest");
            """
            % json.dumps(storage_root.name)
        )

    def _generate_default_request(
        self, page: Page, live_server_url: str, storage_dir: Path, title: str
    ) -> str:
        self._seed_storage_dir_only(page, storage_dir)
        page.goto(f"{live_server_url}/index")
        open_dev_fixture_panel(page)
        page.fill('input[name="title"]', title)
        page.click("#request-generate-submit")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        text = page.locator("#page-notification").inner_text()
        assert "保存成功" in text or "已保存订阅方案" in text
        assert "未找到已保存的订阅方案" not in page.locator("body").inner_text()
        assert "request_id=" in page.url
        request_id = page.url.split("request_id=", 1)[1].split("&", 1)[0]
        assert request_id
        expect(page.locator(f"[data-request-id='{request_id}']")).to_be_visible()
        expect(page.locator(".detail-actions button:has-text('确认')")).to_be_visible()
        expect(page.locator(".detail-actions button:has-text('取消')")).to_be_visible()
        expect(page.locator(".detail-actions button:has-text('修改')")).to_be_visible()
        return request_id

    def test_default_generate_syncs_list_url_and_confirm(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        request_id = self._generate_default_request(
            page, live_server_url, storage_dir, "咒术回战"
        )

        page.on("dialog", lambda dialog: dialog.accept())
        page.locator(".detail-actions button:has-text('确认')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert "确认成功" in page.locator("#page-notification").inner_text()
        assert "已确认" in page.locator("#request-detail-container").inner_text()
        assert "已确认" in page.locator(f"[data-request-id='{request_id}']").inner_text()
        assert "未找到已保存的订阅方案" not in page.locator("body").inner_text()

    def test_default_generated_request_can_cancel(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        request_id = self._generate_default_request(
            page, live_server_url, storage_dir, "咒术回战"
        )

        page.locator(".detail-actions button:has-text('取消')").click()
        page.locator("#cancel-reason").fill("默认生成取消验证")
        page.on("dialog", lambda dialog: dialog.accept())
        page.locator("#detail-cancel-form button:has-text('提交取消')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert "取消成功" in page.locator("#page-notification").inner_text()
        assert "已取消" in page.locator("#request-detail-container").inner_text()
        assert "已取消" in page.locator(f"[data-request-id='{request_id}']").inner_text()
        assert "未找到已保存的订阅方案" not in page.locator("body").inner_text()

    def test_default_generated_request_can_modify(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        request_id = self._generate_default_request(
            page, live_server_url, storage_dir, "咒术回战"
        )

        page.locator(".detail-actions button:has-text('修改')").click()
        page.locator("#modify-folder-name").fill("Jujutsu Stage 14")
        page.locator("#detail-modify-form button:has-text('提交修改')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert "修改成功" in page.locator("#page-notification").inner_text()
        detail_text = page.locator("#request-detail-container").inner_text()
        assert "待确认" in detail_text
        assert "Jujutsu Stage 14" in detail_text
        assert "待确认" in page.locator(f"[data-request-id='{request_id}']").inner_text()
        assert "未找到已保存的订阅方案" not in page.locator("body").inner_text()


class TestSubmitButtonState:
    """AC: 验证提交期间生成按钮禁用并在完成后恢复."""

    def test_button_enabled_after_completion(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        set_storage_preferences(page, storage_dir, save_request=True)
        page.goto(f"{live_server_url}/index")
        open_dev_fixture_panel(page)

        page.fill('input[name="title"]', "葬送的芙莉莲")
        page.click("#request-generate-submit")

        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
        submit = page.locator("#request-generate-submit")
        assert submit.is_enabled()
        assert "生成" in submit.inner_text()


class TestBrowserPreferences:
    """AC: Settings storage_dir 和 save_request 浏览器偏好可保存、刷新后恢复、可清除."""

    def test_preferences_persist_across_reload(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/settings")

        custom_dir = "backups"
        page.fill("#settings-storage-dir", custom_dir)
        page.check("#settings-save-request")
        page.click("#storage-preferences-save")

        page.reload()
        page.wait_for_load_state("networkidle")

        assert page.locator("#settings-storage-dir").input_value() == custom_dir
        assert page.locator("#settings-save-request").is_checked()

    def test_clear_preferences_resets_to_defaults(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/settings")

        page.fill("#settings-storage-dir", "some-dir")
        page.check("#settings-save-request")
        page.click("#storage-preferences-save")

        page.click("#storage-preferences-clear")
        page.wait_for_timeout(300)

        assert page.locator("#settings-storage-dir").input_value() == ""
        assert page.locator("#settings-save-request").is_checked()

    def test_clear_button_present(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/settings")
        btn = page.locator("#storage-preferences-clear")
        assert btn.count() >= 1
        assert "清除" in btn.inner_text()

    def test_index_reads_settings_storage_preferences(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        set_storage_preferences(page, storage_dir, save_request=True)
        page.goto(f"{live_server_url}/index")

        summary = page.locator("#storage-preference-summary")
        text = summary.inner_text()
        assert storage_dir.name in text
        assert "默认保存订阅方案 JSON" in text

    def test_cleared_settings_preferences_restore_index_defaults(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/settings")
        page.fill("#settings-storage-dir", "cleared-dir")
        page.check("#settings-save-request")
        page.click("#storage-preferences-save")
        page.click("#storage-preferences-clear")

        page.goto(f"{live_server_url}/index")
        summary = page.locator("#storage-preference-summary")
        text = summary.inner_text()
        assert "默认服务器 storage 根目录" in text
        assert "默认保存订阅方案 JSON" in text

    def test_legacy_absolute_storage_dir_is_ignored_and_falls_back_to_default(
        self, page: Page, live_server_url: str
    ) -> None:
        """US-193: an old localStorage absolute path must be ignored (smooth
        migration) and never leak into the UI, URL, or API payload."""
        page.add_init_script(
            """
            window.localStorage.setItem("miguOrca.web.storageDir", %s);
            window.localStorage.setItem("miguOrca.web.saveRequest", "true");
            """
            % json.dumps("/tmp/legacy-migu-absolute-path")
        )
        page.goto(f"{live_server_url}/index")

        summary = page.locator("#storage-preference-summary")
        text = summary.inner_text()
        assert "默认服务器 storage 根目录" in text
        assert "/tmp/legacy-migu-absolute-path" not in text

        # The sanitized value never enters the URL query on API calls.
        page.wait_for_selector("#storage-preference-summary")
        assert "storage_dir=" not in page.url

        # localStorage was re-seeded on load (the unsafe value is dropped).
        stored = page.evaluate(
            "() => window.localStorage.getItem('miguOrca.web.storageDir')"
        )
        assert stored is None or stored == ""

    def test_absolute_storage_dir_entered_in_settings_is_ignored(
        self, page: Page, live_server_url: str
    ) -> None:
        """US-193: entering an absolute path in Settings falls back to default
        instead of being persisted to localStorage."""
        page.goto(f"{live_server_url}/settings")
        page.fill("#settings-storage-dir", "/etc/migu-orca/evil")
        page.check("#settings-save-request")
        page.click("#storage-preferences-save")
        page.wait_for_timeout(300)

        assert page.locator("#settings-storage-dir").input_value() == ""
        assert page.locator("#settings-save-request").is_checked()
        stored = page.evaluate(
            "() => window.localStorage.getItem('miguOrca.web.storageDir')"
        )
        assert stored is None or stored == ""
        assert "etc" not in page.locator("body").inner_text()
