from __future__ import annotations

import os
from pathlib import Path

import pytest
from playwright.sync_api import Page

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
        "to verify the US-200 primitives in the browser."
    )


def _goto_demo(page: Page, live_server_url: str) -> None:
    _require_dist()
    page.goto(f"{live_server_url}/app/components-demo")
    page.wait_for_selector(".components-demo-title", timeout=5000)


class TestPrimitiveRender:
    """AC: 每个原语都在真实浏览器中渲染并可交互."""

    def test_demo_view_mounts_all_primitives(
        self, page: Page, live_server_url: str
    ) -> None:
        _goto_demo(page, live_server_url)

        # Layout primitive renders titled panels.
        assert page.locator(".panel-section h2").count() >= 4
        # Button variants (danger lives inside the ConfirmDialog; opened later).
        assert page.locator(".primary-button").count() >= 1
        assert page.locator(".secondary-button").count() >= 1
        # Form controls.
        assert page.locator("input.base-input").count() >= 4
        assert page.locator("textarea.base-textarea").count() >= 1
        assert page.locator("select.base-select").count() >= 1
        assert page.locator("input.base-checkbox").count() >= 1
        # Status alerts carry both visual and ARIA state.
        success = page.locator(".status-alert-success")
        assert success.get_attribute("role") == "status"
        error = page.locator(".status-alert-error")
        assert error.get_attribute("role") == "alert"
        assert error.get_attribute("aria-live") == "assertive"

    def test_360px_no_horizontal_overflow(self, page: Page, live_server_url: str) -> None:
        """US-200 AC: 360px 窄屏无横向溢出 (no overflow of critical actions)."""
        _goto_demo(page, live_server_url)

        page.set_viewport_size({"width": 360, "height": 780})
        body = page.locator("body")
        body_width = body.evaluate("el => el.scrollWidth")
        viewport_width = page.evaluate("() => window.innerWidth")
        assert body_width <= viewport_width, (
            f"Body scrollWidth ({body_width}) exceeds viewport ({viewport_width})"
        )

        # The confirm dialog actions stay inside the viewport at 360px.
        page.locator("#demo-confirm-trigger").click()
        dialog = page.locator(".confirm-dialog")
        dialog.wait_for(state="visible")
        box = dialog.bounding_box()
        assert box is not None
        assert box["width"] <= viewport_width
        page.keyboard.press("Escape")
        dialog.wait_for(state="hidden")


class TestConfirmDialog:
    """AC: 确认流程（打开、确认、取消、Escape、焦点恢复）."""

    def test_confirm_flow(self, page: Page, live_server_url: str) -> None:
        _goto_demo(page, live_server_url)
        page.locator("#demo-confirm-trigger").click()

        dialog = page.locator(".confirm-dialog")
        dialog.wait_for(state="visible")
        assert dialog.get_attribute("role") == "alertdialog"
        assert dialog.get_attribute("aria-modal") == "true"
        assert dialog.locator(".confirm-dialog-title").inner_text() == "确认删除"
        assert "不可恢复" in dialog.locator(".confirm-dialog-message").inner_text()
        # The danger variant is rendered inside the dialog.
        assert dialog.locator(".danger-button").count() == 1

        dialog.locator(".danger-button").click()
        dialog.wait_for(state="hidden")
        expect_result = page.locator(".demo-result")
        assert "已确认" in expect_result.inner_text()

    def test_cancel_flow_and_focus_restore(
        self, page: Page, live_server_url: str
    ) -> None:
        _goto_demo(page, live_server_url)

        # Focus the open button, then open the dialog: focus should move into
        # the dialog and come back to the button after cancel.
        trigger = page.locator("#demo-confirm-trigger")
        trigger.focus()
        trigger.click()

        dialog = page.locator(".confirm-dialog")
        dialog.wait_for(state="visible")
        # Focus is inside the dialog (first focusable).
        focused = page.evaluate("() => document.activeElement?.className || ''")
        assert "confirm-dialog" in focused or "secondary-button" in focused

        dialog.locator(".secondary-button").click()
        dialog.wait_for(state="hidden")
        # Focus restored to the triggering button.
        active_id = page.evaluate("() => document.activeElement?.id || ''")
        assert active_id == "demo-confirm-trigger"

    def test_escape_closes_and_marks_background_inert(
        self, page: Page, live_server_url: str
    ) -> None:
        _goto_demo(page, live_server_url)
        page.locator("#demo-confirm-trigger").click()

        dialog = page.locator(".confirm-dialog")
        dialog.wait_for(state="visible")
        # The dialog teleports to <body>; its sibling (the whole #app) becomes
        # inert while the dialog is open, so background content is not
        # reachable by keyboard or screen reader.
        app = page.locator("#app")
        assert app.get_attribute("inert") is not None

        page.keyboard.press("Escape")
        dialog.wait_for(state="hidden")
        assert page.locator(".demo-result").inner_text() == "上次结果：已取消"
        # Background is interactive again.
        assert app.get_attribute("inert") is None


class TestCredentialFormPrimitive:
    """AC: 敏感字段只存在于组件内存，成功后清空，取消后清空."""

    def test_success_clears_sensitive_fields(
        self, page: Page, live_server_url: str
    ) -> None:
        _goto_demo(page, live_server_url)

        creds = page.locator(".panel-section", has_text="敏感凭据表单")
        creds.locator("#demo-credential-endpoint").fill("http://qb.local")
        creds.locator("#demo-credential-username").fill("user")
        creds.locator("#demo-credential-password").fill("pw")
        creds.locator("#demo-credential-test").click()

        alert = creds.locator(".status-alert-success")
        alert.wait_for(state="visible")
        assert "已清空" in alert.inner_text()
        # No sensitive value remains in any input or in browser storage.
        assert creds.locator("#demo-credential-endpoint").input_value() == ""
        assert creds.locator("#demo-credential-username").input_value() == ""
        assert creds.locator("#demo-credential-password").input_value() == ""
        assert page.evaluate("() => localStorage.length") == 0
        assert page.evaluate("() => sessionStorage.length") == 0

    def test_cancel_clears_sensitive_fields(
        self, page: Page, live_server_url: str
    ) -> None:
        _goto_demo(page, live_server_url)

        creds = page.locator(".panel-section", has_text="敏感凭据表单")
        creds.locator("#demo-credential-endpoint").fill("http://qb.local")
        creds.locator("#demo-credential-cancel").click()

        alert = creds.locator(".status-alert-info")
        alert.wait_for(state="visible")
        assert "已取消并清空" in alert.inner_text()
        assert creds.locator("#demo-credential-endpoint").input_value() == ""

    def test_missing_required_field_shows_error_alert(
        self, page: Page, live_server_url: str
    ) -> None:
        _goto_demo(page, live_server_url)

        creds = page.locator(".panel-section", has_text="敏感凭据表单")
        creds.locator("#demo-credential-test").click()

        alert = creds.locator(".status-alert-error")
        alert.wait_for(state="visible")
        assert "请填写" in alert.inner_text()
