from __future__ import annotations

import pytest
from playwright.sync_api import Page


pytestmark = pytest.mark.browser


class TestResponsiveLayout:
    """AC: 移动宽度下表单、列表和详情区域为单列或不横向溢出."""

    def test_mobile_width_no_horizontal_overflow(
        self, page: Page, live_server_url: str
    ) -> None:
        page.set_viewport_size({"width": 375, "height": 812})
        page.goto(f"{live_server_url}/index")

        body = page.locator("body")
        body_width = body.evaluate("el => el.scrollWidth")
        viewport_width = page.evaluate("() => window.innerWidth")
        assert body_width <= viewport_width, (
            f"Body scrollWidth ({body_width}) exceeds viewport ({viewport_width})"
        )

    def test_mobile_width_panels_visible(
        self, page: Page, live_server_url: str
    ) -> None:
        page.set_viewport_size({"width": 375, "height": 812})
        page.goto(f"{live_server_url}/index")

        panels = page.locator(".panel")
        count = panels.count()
        assert count >= 3, f"Expected at least 3 panels, got {count}"

    def test_mobile_width_list_container_visible(
        self, page: Page, live_server_url: str
    ) -> None:
        page.set_viewport_size({"width": 375, "height": 812})
        page.goto(f"{live_server_url}/index")

        container = page.locator("#request-list-container")
        assert container.count() >= 1
        assert container.is_visible()


class TestKeyboardNavigation:
    """AC: 使用键盘 Tab 聚焦主要表单控件和操作按钮."""

    def test_tab_focuses_title_input(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/index")
        page.locator("body").click()

        found = False
        for _ in range(10):
            page.keyboard.press("Tab")
            name = page.evaluate("() => document.activeElement?.name || ''")
            if name == "title":
                found = True
                break
        assert found, "title input was not reachable via keyboard"

    def test_tab_focuses_generate_button(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/index")
        page.locator("body").click()

        found = False
        for _ in range(20):
            page.keyboard.press("Tab")
            fid = page.evaluate("() => document.activeElement?.id || ''")
            if fid == "request-generate-submit":
                found = True
                break
        assert found, "generate submit button was not reachable via keyboard"

    def test_tab_focuses_refresh_button(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/index")
        page.locator("body").click()

        found = False
        for _ in range(15):
            page.keyboard.press("Tab")
            fid = page.evaluate("() => document.activeElement?.id || ''")
            if fid == "request-list-refresh":
                found = True
                break
        assert found, "refresh button was not reachable via keyboard"

    def test_tab_focuses_settings_storage_dir_input(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/settings")
        page.locator("body").click()

        found = False
        for _ in range(15):
            page.keyboard.press("Tab")
            name = page.evaluate("() => document.activeElement?.name || ''")
            if name == "storage_dir":
                found = True
                break
        assert found, "Settings storage_dir input was not reachable via keyboard"


class TestFocusStyles:
    """AC: 焦点样式可见."""

    def test_focus_outline_on_input(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/index")

        title_input = page.locator('input[name="title"]')
        title_input.focus()

        outline = title_input.evaluate(
            "el => window.getComputedStyle(el).outlineStyle"
        )
        outline_width = title_input.evaluate(
            "el => window.getComputedStyle(el).outlineWidth"
        )
        assert outline != "none" or outline_width != "0px", (
            f"Focus outline should be visible, got style={outline}, width={outline_width}"
        )

    def test_focus_outline_on_button(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/index")

        submit = page.locator("#request-generate-submit")
        submit.focus()

        outline = submit.evaluate("el => window.getComputedStyle(el).outlineStyle")
        outline_width = submit.evaluate(
            "el => window.getComputedStyle(el).outlineWidth"
        )
        assert outline != "none" or outline_width != "0px", (
            f"Button focus outline should be visible, got style={outline}, width={outline_width}"
        )


class TestAccessibilityAttributes:
    """AC: 关键区域具备 ARIA 语义标记，状态不只依赖颜色表达."""

    def test_notification_has_aria_live(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/index")
        notif = page.locator("#page-notification")
        assert notif.get_attribute("aria-live") == "polite"
        assert notif.get_attribute("role") == "status"

    def test_form_error_has_role_alert(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/index")
        error = page.locator("#request-form-error")
        assert error.get_attribute("role") == "alert"

    def test_refresh_button_has_aria_label(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/index")
        refresh = page.locator("#request-list-refresh")
        label = refresh.get_attribute("aria-label")
        assert label and "刷新" in label

    def test_list_container_has_aria_attributes(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/index")
        container = page.locator("#request-list-container")
        assert container.get_attribute("aria-live") == "polite"
        assert container.get_attribute("aria-relevant") == "additions text"

    def test_error_state_has_text_not_color_only(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/index")

        # Trigger form validation error
        page.locator('input[name="title"]').fill(" ")
        page.locator('input[name="title"]').press("Enter")
        page.wait_for_timeout(300)

        error = page.locator("#request-form-error")
        text = error.inner_text().strip()
        assert len(text) > 0, "Error state must have readable text, not just color"
