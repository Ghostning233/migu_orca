from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Page, Request


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
