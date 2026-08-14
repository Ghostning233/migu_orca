from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Page, Request, expect


pytestmark = pytest.mark.browser


class TestQbittorrentNotOnWorkbench:
    """AC: /index does not render or call qBittorrent connection testing."""

    def test_index_does_not_render_qbittorrent_controls(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/index")

        assert page.locator("#qbittorrent-panel").count() == 0
        assert page.locator("#qbittorrent-test-form").count() == 0
        assert page.locator("#qbittorrent-config-toggle").count() == 0
        assert page.locator('input[name="qbittorrent_endpoint"]').count() == 0
        assert page.locator('input[name="qbittorrent_username"]').count() == 0
        assert page.locator('input[name="qbittorrent_password"]').count() == 0
        assert page.locator('input[name="qbittorrent_timeout_seconds"]').count() == 0
        assert page.locator('input[name="qbittorrent_verify_tls"]').count() == 0
        assert "qBittorrent 连接测试" not in page.locator("body").inner_text()

    def test_index_load_does_not_call_qbittorrent_api(
        self, page: Page, live_server_url: str
    ) -> None:
        calls: list[Request] = []

        def _capture(route: Any, request: Request) -> None:
            calls.append(request)
            route.abort()

        page.route("**/api/v1/qbittorrent/test-connection**", _capture)
        page.goto(f"{live_server_url}/index")
        page.wait_for_timeout(500)

        assert calls == []

    def test_generation_does_not_call_qbittorrent_api(
        self, page: Page, live_server_url: str
    ) -> None:
        qbt_calls: list[Request] = []

        def _capture_qbt(route: Any, request: Request) -> None:
            qbt_calls.append(request)
            route.abort()

        page.route("**/api/v1/qbittorrent/test-connection**", _capture_qbt)
        page.goto(f"{live_server_url}/index")
        page.fill('input[name="title"]', "葬送的芙莉莲")
        page.click("#request-generate-submit")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert qbt_calls == []
        storage_keys = page.evaluate("Object.keys(window.localStorage)")
        session_keys = page.evaluate("Object.keys(window.sessionStorage)")
        assert all("qbittorrent" not in key.lower() for key in storage_keys)
        assert all("qbittorrent" not in key.lower() for key in session_keys)


class TestQbittorrentSettingsConnection:
    """AC: Settings owns explicit qBittorrent connection testing."""

    def test_settings_renders_collapsed_qbittorrent_form(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/settings")

        details = page.locator("#qbittorrent-settings-details")
        assert details.count() == 1
        assert not details.evaluate("element => element.open")
        assert page.locator("#settings-qbittorrent-test-form").count() == 1
        assert page.locator("#settings-qbittorrent-password").get_attribute("type") == "password"

    def test_settings_qbittorrent_validation_blocks_api_call(
        self, page: Page, live_server_url: str
    ) -> None:
        calls: list[Request] = []

        def _capture(route: Any, request: Request) -> None:
            calls.append(request)
            route.abort()

        page.route("**/api/v1/qbittorrent/test-connection**", _capture)
        page.goto(f"{live_server_url}/settings")
        page.locator("#qbittorrent-settings-details").evaluate("element => element.open = true")
        page.click("#settings-qbittorrent-test-submit")

        assert calls == []
        assert "endpoint" in page.locator("#settings-qbittorrent-error").inner_text()

    def test_settings_qbittorrent_cancelled_confirmation_blocks_api_call(
        self, page: Page, live_server_url: str
    ) -> None:
        calls: list[Request] = []

        def _capture(route: Any, request: Request) -> None:
            calls.append(request)
            route.abort()

        page.route("**/api/v1/qbittorrent/test-connection**", _capture)
        page.add_init_script("window.confirm = () => false")
        page.goto(f"{live_server_url}/settings")
        page.locator("#qbittorrent-settings-details").evaluate("element => element.open = true")
        page.fill("#settings-qbittorrent-endpoint", "http://private-qbt.local")
        page.fill("#settings-qbittorrent-username", "private-user")
        page.fill("#settings-qbittorrent-password", "private-password")
        page.fill("#settings-qbittorrent-timeout-seconds", "3")
        page.click("#settings-qbittorrent-test-submit")

        assert calls == []

    def test_settings_qbittorrent_success_clears_sensitive_fields_and_renders_safe_summary(
        self, page: Page, live_server_url: str
    ) -> None:
        captured: dict[str, Any] = {}

        def _fulfill_success(route: Any, request: Request) -> None:
            captured["body"] = request.post_data_json
            route.fulfill(
                status=200,
                content_type="application/json",
                body=(
                    '{"ok": true, "result": {'
                    '"status": "ok", "reachable": true, "version": "4.6.5", '
                    '"endpoint": "http://private-qbt.local", "sid": "secret-session"'
                    "}}"
                ),
            )

        page.route("**/api/v1/qbittorrent/test-connection", _fulfill_success)
        page.add_init_script("window.confirm = () => true")
        page.goto(f"{live_server_url}/settings")
        page.locator("#qbittorrent-settings-details").evaluate("element => element.open = true")
        page.fill("#settings-qbittorrent-endpoint", "http://private-qbt.local")
        page.fill("#settings-qbittorrent-username", "private-user")
        page.fill("#settings-qbittorrent-password", "private-password")
        page.fill("#settings-qbittorrent-timeout-seconds", "3.5")
        page.uncheck("#settings-qbittorrent-verify-tls")
        page.click("#settings-qbittorrent-test-submit")

        expect(page.locator("#settings-qbittorrent-result")).to_contain_text("status: ok")
        result_text = page.locator("#settings-qbittorrent-result").inner_text()
        assert "reachable: true" in result_text
        assert "version: 4.6.5" in result_text
        assert "private-qbt" not in result_text
        assert "private-user" not in result_text
        assert "private-password" not in result_text
        assert "secret-session" not in result_text
        assert page.locator("#settings-qbittorrent-endpoint").input_value() == ""
        assert page.locator("#settings-qbittorrent-username").input_value() == ""
        assert page.locator("#settings-qbittorrent-password").input_value() == ""
        assert captured["body"]["qbittorrent_config"] == {
            "endpoint": "http://private-qbt.local",
            "username": "private-user",
            "password": "private-password",
            "timeout_seconds": 3.5,
            "verify_tls": False,
        }
        storage_keys = page.evaluate("Object.keys(window.localStorage)")
        session_keys = page.evaluate("Object.keys(window.sessionStorage)")
        assert all("qbittorrent" not in key.lower() for key in storage_keys)
        assert all("qbittorrent" not in key.lower() for key in session_keys)

    def test_settings_qbittorrent_failure_shows_redacted_error_and_preserves_fields(
        self, page: Page, live_server_url: str
    ) -> None:
        def _fulfill_failure(route: Any, request: Request) -> None:
            route.fulfill(
                status=400,
                content_type="application/json",
                body=(
                    '{"ok": false, "error_type": "qbittorrent_timeout", '
                    '"error_message": "qBittorrent HTTP 请求超时 from http://private-qbt.local '
                    'private-user private-password secret-session", '
                    '"error_data": {"details": {"endpoint": "http://private-qbt.local", '
                    '"username": "private-user", "password": "private-password", "sid": "secret-session"}}}'
                ),
            )

        page.route("**/api/v1/qbittorrent/test-connection", _fulfill_failure)
        page.add_init_script("window.confirm = () => true")
        page.goto(f"{live_server_url}/settings")
        page.locator("#qbittorrent-settings-details").evaluate("element => element.open = true")
        page.fill("#settings-qbittorrent-endpoint", "http://private-qbt.local")
        page.fill("#settings-qbittorrent-username", "private-user")
        page.fill("#settings-qbittorrent-password", "private-password")
        page.click("#settings-qbittorrent-test-submit")

        expect(page.locator("#settings-qbittorrent-result")).to_contain_text(
            "qBittorrent 连接测试失败。请检查配置后重试。"
        )
        result_text = page.locator("#settings-qbittorrent-result").inner_text()
        assert "http://" not in result_text
        assert "private-user" not in result_text
        assert "private-password" not in result_text
        assert "secret-session" not in result_text
        assert page.locator("#settings-qbittorrent-endpoint").input_value() == "http://private-qbt.local"
        assert page.locator("#settings-qbittorrent-username").input_value() == "private-user"
        assert page.locator("#settings-qbittorrent-password").input_value() == "private-password"
