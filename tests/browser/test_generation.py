from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, Request

from tests.browser.conftest import create_saved_request


pytestmark = pytest.mark.browser


class TestFormValidation:
    """AC: 提交空白或纯空白标题时，表单附近出现可读错误且不会发起 API 调用."""

    def test_blank_title_shows_error(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/index")

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

        page.locator('input[name="title"]').fill("   ")
        page.locator('input[name="title"]').press("Enter")
        page.wait_for_timeout(500)

        error = page.locator("#request-form-error")
        assert "请输入标题" in error.inner_text()

    def test_validation_error_visible(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/index")

        page.locator('input[name="title"]').fill(" ")
        page.locator('input[name="title"]').press("Enter")
        page.wait_for_timeout(500)

        error_text = page.locator("#request-form-error").inner_text().strip()
        assert len(error_text) > 0


class TestMikanSourceControls:
    """AC: 真实 MiKan 入口默认隐藏，选择 mikan 后显示并执行浏览器端校验."""

    def test_default_source_hides_mikan_config(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/index")

        assert page.locator('select[name="source"]').input_value() == "static-fixture"
        assert page.locator("#mikan-config-fields").is_hidden()

    def test_selecting_mikan_shows_config_fields(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/index")

        page.select_option('select[name="source"]', "mikan")

        assert page.locator("#mikan-config-fields").is_visible()
        assert page.locator('input[name="mikan_search_endpoint"]').count() == 1
        assert page.locator('input[name="mikan_timeout_seconds"]').count() == 1

    def test_missing_mikan_endpoint_blocks_api_request(
        self, page: Page, live_server_url: str
    ) -> None:
        calls: list[Request] = []

        def _capture_generation(route: Any, request: Request) -> None:
            if request.method != "POST":
                route.continue_()
                return
            calls.append(request)
            route.fulfill(
                status=500,
                content_type="application/json",
                body='{"ok": false, "error_type": "unexpected", "error_message": "should not call"}',
            )

        page.route("**/api/v1/requests", _capture_generation)
        page.goto(f"{live_server_url}/index")
        page.fill('input[name="title"]', "葬送的芙莉莲")
        page.select_option('select[name="source"]', "mikan")
        page.fill('input[name="mikan_search_endpoint"]', "")

        page.click("#request-generate-submit")
        page.wait_for_timeout(500)

        assert not calls
        assert "必须填写 search_endpoint" in page.locator("#request-form-error").inner_text()

    def test_invalid_mikan_timeout_blocks_api_request(
        self, page: Page, live_server_url: str
    ) -> None:
        calls: list[Request] = []

        def _capture_generation(route: Any, request: Request) -> None:
            if request.method != "POST":
                route.continue_()
                return
            calls.append(request)
            route.fulfill(
                status=500,
                content_type="application/json",
                body='{"ok": false, "error_type": "unexpected", "error_message": "should not call"}',
            )

        page.route("**/api/v1/requests", _capture_generation)
        page.goto(f"{live_server_url}/index")
        page.fill('input[name="title"]', "葬送的芙莉莲")
        page.select_option('select[name="source"]', "mikan")
        page.fill('input[name="mikan_search_endpoint"]', "redacted-search-entry")
        page.fill('input[name="mikan_timeout_seconds"]', "0")

        page.click("#request-generate-submit")
        page.wait_for_timeout(500)

        assert not calls
        assert "timeout_seconds 必须为正数" in page.locator("#request-form-error").inner_text()

    def test_fixture_payload_excludes_mikan_config(
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
        page.fill('input[name="title"]', "葬送的芙莉莲")

        page.click("#request-generate-submit")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert bodies
        assert bodies[0]["source"] == "static-fixture"
        assert "mikan_config" not in bodies[0]

    def test_mikan_payload_includes_request_scoped_config(
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
                    '{"ok": true, "result": {"request": {"request_id": "browser-mikan", '
                    '"status": "PENDING_CONFIRM", "input": {"raw_title": "葬送的芙莉莲"}, '
                    '"source_info": {}, "confirmable_config": {}}}}'
                ),
            )

        page.route("**/api/v1/requests", _capture)
        page.goto(f"{live_server_url}/index")
        page.fill('input[name="title"]', "葬送的芙莉莲")
        page.select_option('select[name="source"]', "mikan")
        page.fill('input[name="mikan_search_endpoint"]', "redacted-search-entry")
        page.fill('input[name="mikan_timeout_seconds"]', "5")

        page.click("#request-generate-submit")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert bodies
        assert bodies[0]["source"] == "mikan"
        assert bodies[0]["mikan_config"] == {
            "search_endpoint": "redacted-search-entry",
            "timeout_seconds": 5,
        }
        storage_keys = page.evaluate("Object.keys(window.localStorage)")
        assert all("mikan" not in key.lower() for key in storage_keys)


class TestGenerateWithoutSave:
    """AC: 填写有效标题并保持 save_request 未勾选时，生成成功通知出现."""

    def test_generate_success_notification(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/index")

        page.fill('input[name="title"]', "葬送的芙莉莲")
        save_cb = page.locator('input[name="save_request"]')
        if save_cb.is_checked():
            save_cb.uncheck()
        page.click("#request-generate-submit")

        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
        notif = page.locator("#page-notification")
        text = notif.inner_text()
        assert "生成成功" in text

    def test_no_storage_written_when_save_unchecked(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        page.goto(f"{live_server_url}/index")

        page.fill('input[name="title"]', "葬送的芙莉莲")
        page.fill('input[name="storage_dir"]', str(storage_dir))
        save_cb = page.locator('input[name="save_request"]')
        if save_cb.is_checked():
            save_cb.uncheck()
        page.click("#request-generate-submit")

        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
        assert not storage_dir.exists() or not any(storage_dir.iterdir())


class TestGenerateWithSave:
    """AC: 填写有效标题并勾选 save_request 时，保存成功通知包含 request_id."""

    def test_save_success_notification(self, page: Page, live_server_url: str, storage_dir: Path) -> None:
        page.goto(f"{live_server_url}/index")

        page.fill('input[name="title"]', "葬送的芙莉莲")
        page.fill('input[name="storage_dir"]', str(storage_dir))
        save_cb = page.locator('input[name="save_request"]')
        if not save_cb.is_checked():
            save_cb.check()
        page.click("#request-generate-submit")

        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
        notif = page.locator("#page-notification")
        text = notif.inner_text()
        assert "保存成功" in text or "已保存 Request" in text

    def test_storage_contains_saved_request(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        page.goto(f"{live_server_url}/index")

        page.fill('input[name="title"]', "葬送的芙莉莲")
        page.fill('input[name="storage_dir"]', str(storage_dir))
        save_cb = page.locator('input[name="save_request"]')
        if not save_cb.is_checked():
            save_cb.check()
        page.click("#request-generate-submit")

        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
        req_dir = storage_dir / "requests"
        assert req_dir.is_dir()
        assert len(list(req_dir.glob("*.json"))) >= 1


class TestSubmitButtonState:
    """AC: 验证提交期间生成按钮禁用并在完成后恢复."""

    def test_button_enabled_after_completion(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        page.goto(f"{live_server_url}/index")

        page.fill('input[name="title"]', "葬送的芙莉莲")
        page.fill('input[name="storage_dir"]', str(storage_dir))
        save_cb = page.locator('input[name="save_request"]')
        if not save_cb.is_checked():
            save_cb.check()
        page.click("#request-generate-submit")

        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
        submit = page.locator("#request-generate-submit")
        assert submit.is_enabled()
        assert "生成" in submit.inner_text()


class TestBrowserPreferences:
    """AC: storage_dir 和 save_request 浏览器偏好可保存、刷新后恢复、可清除."""

    def test_preferences_persist_across_reload(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/index")

        custom_dir = "/tmp/test-migu-storage"
        page.fill('input[name="storage_dir"]', custom_dir)
        save_cb = page.locator('input[name="save_request"]')
        if not save_cb.is_checked():
            save_cb.check()
        page.wait_for_timeout(300)

        page.reload()
        page.wait_for_load_state("networkidle")

        assert page.locator('input[name="storage_dir"]').input_value() == custom_dir
        assert page.locator('input[name="save_request"]').is_checked()

    def test_clear_preferences_resets_to_defaults(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/index")

        page.fill('input[name="storage_dir"]', "/tmp/some-dir")
        save_cb = page.locator('input[name="save_request"]')
        if not save_cb.is_checked():
            save_cb.check()
        page.wait_for_timeout(300)

        page.click("#clear-web-preferences")
        page.wait_for_timeout(300)

        assert page.locator('input[name="storage_dir"]').input_value() == ""
        assert not page.locator('input[name="save_request"]').is_checked()

    def test_clear_button_present(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/index")
        btn = page.locator("#clear-web-preferences")
        assert btn.count() >= 1
        assert "清除" in btn.inner_text()
