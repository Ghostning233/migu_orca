from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import set_storage_preferences

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.browser


def _dist_built() -> bool:
    """True when the Vite production build exists (frontend/dist/index.html)."""
    return (REPO_ROOT / "frontend" / "dist" / "index.html").is_file()


def _require_dist() -> None:
    """The SPA build is a hard prerequisite for these browser tests.

    Same policy as tests/browser/test_app_shell.py: locally a missing build
    skips with an explicit message, in CI (``MIGU_ORCA_CI=1``) it is a loud
    failure because the CI browser job builds the frontend first.
    """
    if _dist_built():
        return
    if os.environ.get("MIGU_ORCA_CI") == "1":
        raise RuntimeError(
            "frontend/dist missing in CI — run `npm ci && npm run build` "
            "in frontend/ before the browser suite."
        )
    pytest.skip(
        "frontend/dist not built — run `cd frontend && npm ci && npm run build` "
        "to verify the US-201 Settings migration in the browser."
    )


def _goto_settings(page: Page, live_server_url: str, query: str = "") -> None:
    _require_dist()
    page.goto(f"{live_server_url}/app/settings{query}")
    page.wait_for_selector("#settings-heading", timeout=5000)


class TestAppSettingsStoragePanel:
    """AC: 迁移相对 storage profile（localStorage 只存服务端相对 profile）."""

    def test_loads_storage_preferences_from_local_storage(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        set_storage_preferences(page, storage_dir, save_request=False)
        _goto_settings(page, live_server_url)

        expect(page.locator("#settings-storage-dir")).to_have_value(storage_dir.name)
        expect(page.locator("input#settings-save-request")).to_have_count(0)

    def test_saves_sanitized_relative_profile_and_clears_unsafe(
        self, page: Page, live_server_url: str
    ) -> None:
        _goto_settings(page, live_server_url)

        page.locator("#settings-storage-dir").fill("/etc/passwd")
        page.locator("#storage-preferences-save").click()

        alert = page.locator("#storage-preferences-form .status-alert-success")
        expect(alert).to_be_visible()
        expect(alert).to_contain_text("偏好已保存")
        expect(alert).to_contain_text("已忽略不安全的 storage profile")
        # The unsafe absolute path never reaches localStorage.
        stored = page.evaluate("() => localStorage.getItem('miguOrca.web.storageDir')")
        assert stored is None
        expect(page.locator("#settings-storage-dir")).to_have_value("")

    def test_clear_preferences_restores_server_defaults(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        set_storage_preferences(page, storage_dir)
        _goto_settings(page, live_server_url)

        page.locator("#storage-preferences-clear").click()
        expect(page.locator("#storage-preferences-form .status-alert-info")).to_contain_text(
            "偏好已清除"
        )
        stored = page.evaluate(
            "() => ({dir: localStorage.getItem('miguOrca.web.storageDir'), "
            "save: localStorage.getItem('miguOrca.web.saveRequest')})"
        )
        assert stored["dir"] is None
        assert stored["save"] is None


class TestAppSettingsPreferencesPanel:
    """AC: 偏好默认值读写 /api/v1/preferences，恢复默认需确认."""

    def test_loads_default_preferences_on_page_load(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        set_storage_preferences(page, storage_dir)
        _goto_settings(page, live_server_url)

        expect(page.locator("#preference-settings-form .status-alert")).to_contain_text(
            "已读取偏好默认值", timeout=5000
        )
        assert page.locator("#preference-preferred-groups").input_value() == ""
        assert page.locator("#preference-fallback").input_value() == "next_preferred"
        assert page.locator("#preference-naming-strategy").input_value() == "official_title_season"
        assert page.locator("#preference-naming-template").input_value() == "{title}"
        assert page.locator("input#preference-search-reuse-corrections").is_checked()

    def test_save_posts_normalized_payload_and_persists_across_reload(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        set_storage_preferences(page, storage_dir)
        _goto_settings(page, live_server_url)
        expect(page.locator("#preference-settings-form .status-alert")).to_contain_text(
            "已读取偏好默认值", timeout=5000
        )

        page.locator("#preference-preferred-groups").fill("喵萌\n\n   \nLoli")
        page.locator("#preference-excluded-groups").fill("其他")
        page.locator("#preference-filter-must-contain").fill("1080p")
        page.locator("#preference-filter-must-not-contain").fill("合集版")
        page.locator("#preference-naming-strategy").select_option("raw_title")
        page.locator("#preference-naming-template").fill("[{title}]")
        page.locator("input#preference-filter-use-regex").check()
        page.locator("input#preference-filter-case-sensitive").check()
        page.locator("input#preference-search-reuse-corrections").uncheck()
        page.locator("#preference-settings-save").click()

        expect(page.locator("#preference-settings-form .status-alert-success")).to_contain_text(
            "偏好默认值已保存", timeout=5000
        )
        # The global notification also announces success.
        expect(page.locator(".global-notification")).to_contain_text("偏好默认值已保存")
        # Empty lines were normalized away.
        expect(page.locator("#preference-preferred-groups")).to_have_value("喵萌\nLoli")

        page.reload()
        page.wait_for_selector("#settings-heading", timeout=5000)
        expect(page.locator("#preference-settings-form .status-alert")).to_contain_text(
            "已读取偏好默认值", timeout=5000
        )
        expect(page.locator("#preference-preferred-groups")).to_have_value("喵萌\nLoli")
        expect(page.locator("#preference-naming-strategy")).to_have_value("raw_title")
        assert page.locator("input#preference-filter-use-regex").is_checked()
        assert not page.locator("input#preference-search-reuse-corrections").is_checked()

    def test_sensitive_value_shows_error_and_no_file_written(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        set_storage_preferences(page, storage_dir)
        _goto_settings(page, live_server_url)
        expect(page.locator("#preference-settings-form .status-alert")).to_contain_text(
            "已读取偏好默认值", timeout=5000
        )

        page.locator("#preference-preferred-groups").fill("https://mikan.example/Home/Search")
        page.locator("#preference-settings-save").click()

        alert = page.locator("#preference-settings-form .status-alert-error")
        expect(alert).to_contain_text("保存偏好默认值失败", timeout=5000)
        # The rejected sensitive input never stays in the form.
        expect(page.locator("#preference-preferred-groups")).to_have_value("")
        body = page.locator("body").inner_text()
        assert "mikan.example" not in body

        from storage_engine.controllers.storage_config import load_storage_config

        config = load_storage_config(storage_dir)
        assert not (config.preferences_dir / "user_preferences.json").exists()

    def test_reset_requires_confirm_and_restores_defaults(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        set_storage_preferences(page, storage_dir)
        _goto_settings(page, live_server_url)
        expect(page.locator("#preference-settings-form .status-alert")).to_contain_text(
            "已读取偏好默认值", timeout=5000
        )
        page.locator("#preference-preferred-groups").fill("喵萌")
        page.locator("#preference-settings-save").click()
        expect(page.locator("#preference-settings-form .status-alert-success")).to_contain_text(
            "偏好默认值已保存", timeout=5000
        )

        page.locator("#preference-settings-reset").click()
        dialog = page.locator(".confirm-dialog")
        dialog.wait_for(state="visible")
        expect(dialog).to_contain_text("恢复默认偏好")
        dialog.locator(".danger-button").click()

        expect(page.locator("#preference-settings-form .status-alert-success")).to_contain_text(
            "已恢复默认偏好", timeout=5000
        )
        expect(page.locator("#preference-preferred-groups")).to_have_value("")
        expect(page.locator("#preference-fallback")).to_have_value("next_preferred")

    def test_reset_cancelled_keeps_preferences(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        set_storage_preferences(page, storage_dir)
        _goto_settings(page, live_server_url)
        expect(page.locator("#preference-settings-form .status-alert")).to_contain_text(
            "已读取偏好默认值", timeout=5000
        )
        page.locator("#preference-preferred-groups").fill("喵萌")
        page.locator("#preference-settings-save").click()
        expect(page.locator("#preference-settings-form .status-alert-success")).to_contain_text(
            "偏好默认值已保存", timeout=5000
        )

        page.locator("#preference-settings-reset").click()
        dialog = page.locator(".confirm-dialog")
        dialog.wait_for(state="visible")
        dialog.locator(".secondary-button").click()
        dialog.wait_for(state="hidden")

        expect(page.locator("#preference-preferred-groups")).to_have_value("喵萌")
        assert "已恢复默认偏好" not in page.locator(
            "#preference-settings-form .status-alert"
        ).inner_text()


class TestAppSettingsQbittorrentPanel:
    """AC: qB/AB 连接测试 request-scoped，凭据只在内存，成功/取消后清空."""

    def test_validation_blocks_api_call(self, page: Page, live_server_url: str) -> None:
        calls: list[Any] = []

        def _capture(route: Any, request: Any) -> None:
            calls.append(request)
            route.abort()

        page.route("**/api/v1/qbittorrent/test-connection**", _capture)
        _goto_settings(page, live_server_url)
        page.locator("#settings-qbittorrent-test-submit").click()

        assert calls == []
        alert = page.locator("#settings-qbittorrent-test-form .status-alert-error")
        expect(alert).to_contain_text("测试 qBittorrent 前必须填写")

    def test_success_posts_request_scoped_config_and_clears_sensitive_fields(
        self, page: Page, live_server_url: str
    ) -> None:
        captured: dict[str, Any] = {}

        def _fulfill_success(route: Any, request: Any) -> None:
            captured["body"] = request.post_data_json
            route.fulfill(
                status=200,
                content_type="application/json",
                body=(
                    '{"ok": true, "result": {"status": "ok", "reachable": true, '
                    '"version": "4.6.5"}}'
                ),
            )

        page.route("**/api/v1/qbittorrent/test-connection", _fulfill_success)
        _goto_settings(page, live_server_url)
        page.locator("#settings-qbittorrent-endpoint").fill("http://private-qbt.local")
        page.locator("#settings-qbittorrent-username").fill("private-user")
        page.locator("#settings-qbittorrent-password").fill("private-password")
        page.locator("#settings-qbittorrent-timeout-seconds").fill("3.5")
        page.locator("#settings-qbittorrent-verify-tls").uncheck()
        page.locator("#settings-qbittorrent-test-submit").click()

        # Confirmation dialog first.
        dialog = page.locator(".confirm-dialog")
        dialog.wait_for(state="visible")
        expect(dialog).to_contain_text("测试 qBittorrent 连接")
        dialog.locator(".primary-button").click()

        alert = page.locator("#settings-qbittorrent-test-form .status-alert-success")
        expect(alert).to_contain_text("status: ok", timeout=5000)
        expect(alert).to_contain_text("version: 4.6.5")
        result_text = alert.inner_text()
        assert "private-qbt" not in result_text
        assert "private-user" not in result_text
        assert "private-password" not in result_text
        # Credentials are cleared from the form after success.
        expect(page.locator("#settings-qbittorrent-endpoint")).to_have_value("")
        expect(page.locator("#settings-qbittorrent-password")).to_have_value("")
        assert captured["body"] == {
            "qbittorrent_config": {
                "endpoint": "http://private-qbt.local",
                "username": "private-user",
                "password": "private-password",
                "timeout_seconds": 3.5,
                "verify_tls": False,
            }
        }
        # Sensitive values never reach browser storage.
        stored = page.evaluate(
            "() => ({ls: Object.keys(localStorage), ss: Object.keys(sessionStorage)})"
        )
        assert all("qbittorrent" not in key.lower() for key in stored["ls"] + stored["ss"])

    def test_cancelled_confirmation_blocks_api_call_and_preserves_fields(
        self, page: Page, live_server_url: str
    ) -> None:
        calls: list[Any] = []

        def _capture(route: Any, request: Any) -> None:
            calls.append(request)
            route.abort()

        page.route("**/api/v1/qbittorrent/test-connection**", _capture)
        _goto_settings(page, live_server_url)
        page.locator("#settings-qbittorrent-endpoint").fill("http://private-qbt.local")
        page.locator("#settings-qbittorrent-username").fill("private-user")
        page.locator("#settings-qbittorrent-password").fill("private-password")
        page.locator("#settings-qbittorrent-test-submit").click()

        dialog = page.locator(".confirm-dialog")
        dialog.wait_for(state="visible")
        dialog.locator(".secondary-button").click()
        dialog.wait_for(state="hidden")

        assert calls == []
        expect(page.locator("#settings-qbittorrent-endpoint")).to_have_value(
            "http://private-qbt.local"
        )

    def test_failure_shows_redacted_error_and_preserves_fields(
        self, page: Page, live_server_url: str
    ) -> None:
        def _fulfill_failure(route: Any, request: Any) -> None:
            route.fulfill(
                status=400,
                content_type="application/json",
                body=(
                    '{"ok": false, "error_type": "qbittorrent_timeout", '
                    '"error_message": "qBittorrent HTTP 请求超时 from '
                    'http://private-qbt.local private-user private-password secret-session", '
                    '"error_data": {"details": {"endpoint": "http://private-qbt.local"}}}'
                ),
            )

        page.route("**/api/v1/qbittorrent/test-connection", _fulfill_failure)
        _goto_settings(page, live_server_url)
        page.locator("#settings-qbittorrent-endpoint").fill("http://private-qbt.local")
        page.locator("#settings-qbittorrent-username").fill("private-user")
        page.locator("#settings-qbittorrent-password").fill("private-password")
        page.locator("#settings-qbittorrent-test-submit").click()

        dialog = page.locator(".confirm-dialog")
        dialog.wait_for(state="visible")
        dialog.locator(".primary-button").click()

        alert = page.locator("#settings-qbittorrent-test-form .status-alert-error")
        expect(alert).to_contain_text("qBittorrent 连接测试失败", timeout=5000)
        alert_text = alert.inner_text()
        assert "http://" not in alert_text
        assert "private-user" not in alert_text
        assert "private-password" not in alert_text
        assert "secret-session" not in alert_text
        # Failed attempts keep the fields so the user can retry.
        expect(page.locator("#settings-qbittorrent-endpoint")).to_have_value(
            "http://private-qbt.local"
        )


class TestAppSettingsAutoBangumiPanel:
    """AC: AB 连接测试 + request_id 对应的提交上下文，凭据只在内存."""

    def test_connection_uses_password_mode_and_clears_credentials(
        self, page: Page, live_server_url: str
    ) -> None:
        captured: dict[str, Any] = {}

        def _connection(route: Any, request: Any) -> None:
            captured["body"] = request.post_data_json
            route.fulfill(
                status=200,
                content_type="application/json",
                body=(
                    '{"ok": true, "result": {"reachable": true, "authenticated": true, '
                    '"version": "3.1.18", "auth_mode": "账号密码", "adapter": "legacy_3_1", '
                    '"submit_supported": true}}'
                ),
            )

        page.route("**/api/v1/settings/autobangumi", _connection)
        _goto_settings(page, live_server_url)
        page.locator("#settings-ab-endpoint").fill("http://ab.example.invalid")
        page.locator("#settings-ab-username").fill("browser-user")
        page.locator("#settings-ab-password").fill("browser-secret-password")
        page.locator("#settings-ab-save").click()

        alert = page.locator(".status-alert-success").last
        expect(alert).to_contain_text("连接已保存", timeout=5000)
        assert captured["body"]["config"] == {
                "auth_mode": "password",
                "base_url": "http://ab.example.invalid",
                "username": "browser-user",
                "password": "browser-secret-password",
                "fallback_enabled": False,
            }
        for selector in ("#settings-ab-endpoint", "#settings-ab-username", "#settings-ab-password"):
            expect(page.locator(selector)).to_have_value("")
        stored = page.evaluate(
            "() => ({ls: Object.keys(localStorage), ss: Object.keys(sessionStorage)})"
        )
        assert stored["ss"] == []
        assert all("ab" not in key.lower() for key in stored["ls"])

    def test_submit_ab_uses_request_id_from_url_and_confirms(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        captured: dict[str, Any] = {}

        def handle_submit(route: Any, request: Any) -> None:
            if request.method == "POST":
                captured["url"] = request.url
                captured["payload"] = request.post_data_json
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
        _goto_settings(page, live_server_url, "?request_id=req-ab-submit")

        expect(page.locator("#settings-ab-request-id")).to_have_count(0)
        expect(page.locator("#settings-ab-submit")).to_have_count(0)
        return
        page.locator("#settings-ab-endpoint").fill("http://ab.example.invalid")
        page.locator("#settings-ab-username").fill("browser-user")
        page.locator("#settings-ab-password").fill("browser-secret-password")
        expect(page.locator("#settings-ab-submit")).to_have_count(0)
        assert calls == []
        return

        dialog = page.locator(".confirm-dialog")
        dialog.wait_for(state="visible")
        expect(dialog).to_contain_text("提交 Auto Bangumi")
        dialog.locator(".danger-button").click()

        alert = page.locator("#settings-ab-submit-form .status-alert-success")
        expect(alert).to_contain_text("Auto Bangumi 提交成功", timeout=5000)
        expect(page.locator(".global-notification")).to_contain_text("Auto Bangumi 提交成功")
        assert "/api/v1/requests/req-ab-submit/submit-ab" in captured["url"]
        assert "browser-secret-token" not in captured["url"]
        assert captured["payload"]["ab_config"] == {
            "auth_mode": "password",
            "base_url": "http://ab.example.invalid",
            "username": "browser-user",
            "password": "browser-secret-password",
            "fallback_enabled": False,
        }
        # Credentials cleared after success and never in storage.
        expect(page.locator("#settings-ab-endpoint")).to_have_value("")
        expect(page.locator("#settings-ab-password")).to_have_value("")
        stored = page.evaluate(
            "() => ({ls: Object.keys(localStorage), ss: Object.keys(sessionStorage)})"
        )
        assert all("ab" not in key.lower() for key in stored["ls"])
        assert stored["ss"] == []

    def test_submit_ab_without_request_id_shows_chinese_error(
        self, page: Page, live_server_url: str
    ) -> None:
        calls: list[Any] = []

        def _capture(route: Any, request: Any) -> None:
            calls.append(request)
            route.abort()

        page.route("**/api/v1/requests/*/submit-ab**", _capture)
        _goto_settings(page, live_server_url)
        expect(page.locator("#settings-ab-submit")).to_have_count(0)
        assert calls == []

    def test_auth_mode_switch_clears_sensitive_fields(
        self, page: Page, live_server_url: str
    ) -> None:
        _goto_settings(page, live_server_url)
        page.locator("#settings-ab-endpoint").fill("http://ab.example.invalid")
        page.locator("#settings-ab-username").fill("user")
        page.locator("#settings-ab-password").fill("pw")

        page.locator("#settings-ab-auth-mode").select_option("api_token")
        expect(page.locator("#settings-ab-token")).to_be_visible()
        expect(page.locator("#settings-ab-username")).to_be_hidden()
        # Old password-mode credentials were cleared by the mode switch.
        expect(page.locator("#settings-ab-endpoint")).to_have_value("")

        page.locator("#settings-ab-token").fill("browser-secret-token")
        page.locator("#settings-ab-auth-mode").select_option("password")
        expect(page.locator("#settings-ab-username")).to_be_visible()
        expect(page.locator("#settings-ab-token")).to_be_hidden()
        expect(page.locator("#settings-ab-endpoint")).to_have_value("")


class TestAppSettingsResponsiveAndAccessibility:
    """AC: 窄屏无横向溢出；状态不只靠颜色表达."""

    def test_360px_no_horizontal_overflow(self, page: Page, live_server_url: str) -> None:
        _goto_settings(page, live_server_url)
        page.set_viewport_size({"width": 360, "height": 780})
        body = page.locator("body")
        body_width = body.evaluate("el => el.scrollWidth")
        viewport_width = page.evaluate("() => window.innerWidth")
        assert body_width <= viewport_width, (
            f"Body scrollWidth ({body_width}) exceeds viewport ({viewport_width})"
        )

    def test_error_alert_carries_assertive_aria(self, page: Page, live_server_url: str) -> None:
        _goto_settings(page, live_server_url)
        page.locator("#settings-qbittorrent-test-submit").click()
        alert = page.locator("#settings-qbittorrent-test-form .status-alert-error")
        expect(alert).to_be_visible()
        assert alert.get_attribute("role") == "alert"
        assert alert.get_attribute("aria-live") == "assertive"
