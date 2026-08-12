from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, Request

from request_engine.controllers.request_controller import accept_request
from storage_engine.controllers.request_repository import save_request_snapshot
from storage_engine.controllers.storage_config import load_storage_config
from tests.browser.conftest import create_saved_request


pytestmark = pytest.mark.browser


SENSITIVE_ENDPOINT = "http://auto-bangumi.local/api/subscriptions?token=browser-secret-token"
SENSITIVE_TOKEN = "browser-secret-token"
RAW_HTML = "<html><body>remote failure</body></html>"
RAW_RSS = "<rss><channel><title>raw</title></channel></rss>"


def _open_request_detail(
    page: Page, live_server_url: str, storage_dir: Path, request_id: str
) -> None:
    page.goto(f"{live_server_url}/index")
    page.fill('input[name="storage_dir"]', str(storage_dir))
    page.click("#request-list-refresh")
    page.wait_for_selector(f"[data-request-id='{request_id}']", timeout=5000)
    page.locator(f"[data-request-id='{request_id}']").click()
    page.wait_for_timeout(500)


def _save_accepted_request(
    storage_dir: Path, title: str, request_id: str
) -> dict[str, object]:
    request = accept_request(create_saved_request(storage_dir, title, request_id))
    save_request_snapshot(load_storage_config(storage_dir), request)
    return request


def _visible_text(page: Page) -> str:
    return page.locator("body").inner_text()


def _assert_sensitive_values_not_rendered(page: Page) -> None:
    text = _visible_text(page)
    lowered = text.lower()
    assert SENSITIVE_ENDPOINT not in text
    assert SENSITIVE_TOKEN not in text
    assert RAW_HTML not in text
    assert RAW_RSS not in text
    assert "authorization" not in lowered
    assert "cookie" not in lowered


class TestStage11MikanBrowserRegressions:
    """AC: MiKan entry points remain explicit, validated, and offline by default."""

    def test_default_fixture_mode_hides_mikan_config_and_generates_locally(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        page.goto(f"{live_server_url}/index")
        page.fill('input[name="storage_dir"]', str(storage_dir))
        page.fill('input[name="title"]', "葬送的芙莉莲")
        save_checkbox = page.locator('input[name="save_request"]')
        if save_checkbox.is_checked():
            save_checkbox.uncheck()

        assert page.locator('select[name="source"]').input_value() == "static-fixture"
        assert page.locator("#mikan-config-fields").is_hidden()

        page.click("#request-generate-submit")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert "生成成功" in page.locator("#page-notification").inner_text()
        assert not storage_dir.exists() or not any(storage_dir.iterdir())
        _assert_sensitive_values_not_rendered(page)

    def test_mikan_selection_displays_fields_and_blocks_invalid_config(
        self, page: Page, live_server_url: str
    ) -> None:
        calls: list[Request] = []

        def _capture_generation(route: Any, request: Request) -> None:
            if request.method == "POST":
                calls.append(request)
                route.fulfill(
                    status=500,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "ok": False,
                            "error_type": "unexpected",
                            "error_message": "validation should block this request",
                        }
                    ),
                )
                return
            route.continue_()

        page.route("**/api/v1/requests", _capture_generation)
        page.goto(f"{live_server_url}/index")
        page.fill('input[name="title"]', "葬送的芙莉莲")
        page.select_option('select[name="source"]', "mikan")

        assert page.locator("#mikan-config-fields").is_visible()

        page.click("#request-generate-submit")
        page.wait_for_timeout(300)
        assert not calls
        assert "必须填写 search_endpoint" in page.locator("#request-form-error").inner_text()

        page.fill('input[name="mikan_search_endpoint"]', "redacted-search-entry")
        page.fill('input[name="mikan_timeout_seconds"]', "-1")
        page.click("#request-generate-submit")
        page.wait_for_timeout(300)
        assert not calls
        assert "timeout_seconds 必须为正数" in page.locator("#request-form-error").inner_text()


class TestStage11AutoBangumiBrowserRegressions:
    """AC: AB submit is accepted-only, confirmed, temporary, and non-destructive."""

    def test_ab_entry_is_accepted_only_and_requires_password_token_confirmation(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-stage11-pending")
        _save_accepted_request(storage_dir, "葬送的芙莉莲", "req-stage11-accepted")

        _open_request_detail(page, live_server_url, storage_dir, "req-stage11-pending")
        assert (
            page.locator(
                "#request-detail-container .detail-actions "
                "button:visible:has-text('提交 Auto Bangumi')"
            ).count()
            == 0
        )

        _open_request_detail(page, live_server_url, storage_dir, "req-stage11-accepted")
        page.locator(
            "#request-detail-container .detail-actions "
            "button:visible:has-text('提交 Auto Bangumi')"
        ).click()

        assert page.locator("#detail-ab-submit-form").is_visible()
        assert page.locator("#ab-submit-token").get_attribute("type") == "password"

        dialogs: list[str] = []
        page.once("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
        page.fill("#ab-submit-endpoint", "redacted-ab-entry")
        page.fill("#ab-submit-token", SENSITIVE_TOKEN)
        page.locator("#detail-ab-submit-form button:has-text('提交 Auto Bangumi')").click()
        page.wait_for_timeout(300)

        assert dialogs == ["确认提交此 Request 到 Auto Bangumi？"]
        storage_keys = page.evaluate("Object.keys(window.localStorage)")
        session_keys = page.evaluate("Object.keys(window.sessionStorage)")
        assert all("ab" not in key.lower() for key in storage_keys)
        assert session_keys == []

    def test_ab_submit_failure_preserves_detail_list_and_redacts_notification(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _save_accepted_request(storage_dir, "葬送的芙莉莲", "req-stage11-ab-fail")
        create_saved_request(storage_dir, "咒术回战第三季", "req-stage11-list-kept")

        def _fail_submit(route: Any) -> None:
            if route.request.method != "POST":
                route.continue_()
                return
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": False,
                        "error_type": "ab_submit_failed",
                        "error_message": "Auto Bangumi 提交失败：[redacted-url] [redacted]",
                    },
                    ensure_ascii=False,
                ),
            )

        page.route("**/api/v1/requests/req-stage11-ab-fail/submit-ab**", _fail_submit)
        _open_request_detail(page, live_server_url, storage_dir, "req-stage11-ab-fail")

        page.locator(".detail-actions button:has-text('提交 Auto Bangumi')").click()
        page.fill("#ab-submit-endpoint", SENSITIVE_ENDPOINT)
        page.fill("#ab-submit-token", SENSITIVE_TOKEN)
        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("#detail-ab-submit-form button:has-text('提交 Auto Bangumi')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        detail_text = page.locator("#request-detail-container").inner_text()
        list_text = page.locator("#request-list-container").inner_text()
        notification_text = page.locator("#page-notification").inner_text()

        assert "req-stage11-ab-fail" in detail_text
        assert "ACCEPTED" in detail_text
        assert "咒术回战 第三季" in list_text
        assert "Auto Bangumi 提交失败" in notification_text
        _assert_sensitive_values_not_rendered(page)
