from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, Request

from tests.browser.conftest import create_saved_request


pytestmark = pytest.mark.browser


def _open_index(page: Page, live_server_url: str) -> None:
    page.goto(f"{live_server_url}/index")
    page.wait_for_selector("#qbittorrent-config-toggle", timeout=5000)


class TestQbittorrentConnectionPanel:
    """AC: qBittorrent connection testing is explicit, request-scoped, and offline by default."""

    def test_panel_starts_collapsed_and_does_not_call_api_on_load(
        self, page: Page, live_server_url: str
    ) -> None:
        calls: list[Request] = []

        def _capture(route: Any, request: Request) -> None:
            calls.append(request)
            route.abort()

        page.route("**/api/v1/qbittorrent/test-connection**", _capture)
        _open_index(page, live_server_url)
        page.wait_for_timeout(500)

        assert page.locator("#qbittorrent-panel").count() >= 1
        assert page.locator("#qbittorrent-test-form").is_hidden()
        assert page.locator("#qbittorrent-config-toggle").get_attribute("aria-expanded") == "false"
        assert page.locator("#qbittorrent-password").get_attribute("type") == "password"
        assert calls == []

    def test_invalid_timeout_blocks_request_and_valid_submit_uses_confirmed_payload(
        self, page: Page, live_server_url: str
    ) -> None:
        calls: list[Request] = []
        captured: dict[str, object] = {}

        def _capture(route: Any, request: Request) -> None:
            if request.method != "POST":
                route.continue_()
                return
            calls.append(request)
            captured["body"] = request.post_data_json
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": True,
                        "result": {
                            "status": "reachable",
                            "reachable": True,
                            "version": "4.6.5",
                            "endpoint": "https://qbittorrent.example:8080",
                            "username": "browser-user",
                            "password": "browser-password",
                            "cookie": "SID=browser-cookie",
                            "sid": "browser-sid",
                            "download_path": "/home/test/downloads",
                        },
                    },
                    ensure_ascii=False,
                ),
            )

        page.route("**/api/v1/qbittorrent/test-connection**", _capture)
        _open_index(page, live_server_url)

        page.locator("#qbittorrent-config-toggle").click()
        page.wait_for_selector("#qbittorrent-test-form:not([hidden])", timeout=5000)
        assert page.locator("#qbittorrent-test-form").is_visible()
        assert page.locator("#qbittorrent-password").get_attribute("type") == "password"

        page.click("#qbittorrent-test-submit")
        page.wait_for_timeout(500)

        assert calls == []
        assert "必须填写 endpoint" in page.locator("#qbittorrent-form-error").inner_text()

        page.fill("#qbittorrent-endpoint", "https://qbittorrent.example:8080")
        page.fill("#qbittorrent-username", "browser-user")
        page.fill("#qbittorrent-password", "browser-password")
        page.fill("#qbittorrent-timeout-seconds", "0")
        page.click("#qbittorrent-test-submit")
        page.wait_for_timeout(500)

        assert calls == []
        assert "timeout_seconds 必须为正数" in page.locator("#qbittorrent-form-error").inner_text()
        assert page.locator("#qbittorrent-test-form").is_visible()
        assert page.locator("#qbittorrent-endpoint").input_value() == "https://qbittorrent.example:8080"
        assert page.locator("#qbittorrent-username").input_value() == "browser-user"

        dialogs: list[str] = []
        page.once("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.accept()))
        page.fill("#qbittorrent-timeout-seconds", "5")
        page.click("#qbittorrent-test-submit")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert dialogs == ["确认使用当前 qBittorrent 配置测试连接？"]
        assert calls
        assert captured["body"] == {
            "qbittorrent_config": {
                "endpoint": "https://qbittorrent.example:8080",
                "username": "browser-user",
                "password": "browser-password",
                "timeout_seconds": 5,
                "verify_tls": True,
            }
        }
        result_text = page.locator("#qbittorrent-test-result").inner_text()
        assert "reachable" in result_text
        assert "4.6.5" in result_text
        page_text = page.locator("body").inner_text()
        for sensitive in (
            "qbittorrent.example",
            "browser-user",
            "browser-password",
            "browser-cookie",
            "browser-sid",
            "/home/test/downloads",
        ):
            assert sensitive not in result_text
            assert sensitive not in page_text
        storage_keys = page.evaluate("Object.keys(window.localStorage)")
        session_keys = page.evaluate("Object.keys(window.sessionStorage)")
        assert all("qbittorrent" not in key.lower() for key in storage_keys)
        assert all("qbittorrent" not in key.lower() for key in session_keys)

    def test_failure_keeps_form_state_and_shows_sanitized_notification(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-qbt-failure")

        def _fail(route: Any, request: Request) -> None:
            if request.method != "POST":
                route.continue_()
                return
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": False,
                        "error_type": "qbittorrent_timeout",
                        "error_message": "qBittorrent HTTP 请求超时",
                        "error_data": {"category": "timeout", "status_code": 504},
                    },
                    ensure_ascii=False,
                ),
            )

        page.route("**/api/v1/qbittorrent/test-connection**", _fail)
        _open_index(page, live_server_url)
        page.locator('input[name="storage_dir"]').fill(str(storage_dir))
        page.locator("#request-list-refresh").click()
        page.wait_for_selector("[data-request-id='req-qbt-failure']", timeout=5000)
        page.locator("[data-request-id='req-qbt-failure']").click()
        page.wait_for_timeout(500)

        page.locator("#qbittorrent-config-toggle").click()
        page.wait_for_selector("#qbittorrent-test-form:not([hidden])", timeout=5000)
        page.fill("#qbittorrent-endpoint", "https://qbittorrent.example:8080")
        page.fill("#qbittorrent-username", "browser-user")
        page.fill("#qbittorrent-password", "browser-password")
        page.fill("#qbittorrent-timeout-seconds", "5")
        page.once("dialog", lambda dialog: dialog.accept())
        page.click("#qbittorrent-test-submit")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert page.locator("#request-list-container").is_visible()
        assert page.locator("#request-detail-container").is_visible()
        assert "req-qbt-failure" in page.locator("#request-detail-container").inner_text()
        assert page.locator("#qbittorrent-test-form").is_visible()
        assert page.locator("#qbittorrent-endpoint").input_value() == "https://qbittorrent.example:8080"
        assert page.locator("#qbittorrent-username").input_value() == "browser-user"
        assert page.locator("#qbittorrent-password").input_value() == "browser-password"
        assert "qBittorrent 连接测试未通过" in page.locator("#qbittorrent-test-result").inner_text()
        notification_text = page.locator("#page-notification").inner_text()
        assert "qBittorrent 连接失败" in notification_text or "qBittorrent HTTP 请求超时" in notification_text
        assert "browser-user" not in notification_text
        assert "browser-password" not in notification_text
        assert "qbittorrent.example" not in notification_text
        storage_keys = page.evaluate("Object.keys(window.localStorage)")
        session_keys = page.evaluate("Object.keys(window.sessionStorage)")
        assert all("qbittorrent" not in key.lower() for key in storage_keys)
        assert all("qbittorrent" not in key.lower() for key in session_keys)
