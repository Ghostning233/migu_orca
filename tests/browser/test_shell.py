from __future__ import annotations

import pytest
from playwright.sync_api import Page


pytestmark = pytest.mark.browser


class TestRootRedirect:
    """AC: 浏览器测试验证 GET / 会跳转或最终到达 /index."""

    def test_root_returns_302(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/")
        page.wait_for_url("**/index")
        assert page.title().startswith("MiGuOrca")

    def test_root_lands_on_index_with_shell(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/")
        page.wait_for_url("**/index")
        # Verify we landed on a real page, not an error
        assert page.locator("h1").count() >= 1
        assert page.locator(".top-nav").count() >= 1


class TestIndexStage12Shell:
    """AC: /index 可加载 Stage 12 qBittorrent Direct 标识、顶部导航和运行模式提示."""

    def test_stage12_branding_visible(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/index")

        assert page.locator("text=MiGuOrca").count() >= 1
        assert page.locator("text=Stage 12 qBittorrent Direct").count() >= 1
        # Must NOT mention Stage 7
        assert page.locator("text=Stage 7 Web UI MVP").count() == 0

    def test_top_navigation_anchors(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/index")

        nav = page.locator(".top-nav")
        assert nav.count() >= 1
        for href in ("/index", "/settings"):
            assert nav.locator(f"a[href='{href}']").count() >= 1, (
                f"Missing nav anchor: {href}"
            )
        assert nav.locator("text=Request 工作台").count() >= 1
        assert nav.locator("text=Settings").count() >= 1

    def test_mode_hint_describes_local_storage(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/index")

        hint = page.locator("text=运行模式：本地 JSON storage").first
        assert hint.count() >= 1
        # Mode hint should mention offline/fixture behavior
        body = page.locator("body").inner_text()
        assert "fixture-backed" in body
        assert "真实 MiKan 与 qBittorrent 连接测试必须显式选择" in body
        assert "配置只用于当前请求且不写入 storage JSON" in body

    def test_main_panels_present(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/index")

        for panel_id in (
            "generate-panel",
            "qbittorrent-panel",
            "request-list-panel",
            "request-detail-panel",
            "acceptance-panel",
        ):
            assert page.locator(f"#{panel_id}").count() >= 1, (
                f"Missing panel: #{panel_id}"
            )

    def test_all_section_headings_present(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/index")

        for heading in (
            "Request 生成",
            "qBittorrent 连接测试",
            "Request 列表",
            "Request 详情",
            "验收说明",
        ):
            assert page.locator(f"text={heading}").count() >= 1, (
                f"Missing heading: {heading}"
            )


class TestSettingsShell:
    """AC: /settings provides a dedicated Settings page with shared navigation."""

    def test_settings_case_redirects(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/Settings")
        page.wait_for_url("**/settings")
        assert page.title() == "MiGuOrca Settings"

    def test_settings_page_shell_and_placeholders(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/settings")

        assert page.title() == "MiGuOrca Settings"
        assert page.locator("text=Stage 13 Settings").count() >= 1
        nav = page.locator(".top-nav")
        assert nav.locator("a[href='/index']").count() >= 1
        assert nav.locator("a[href='/settings']").count() >= 1
        assert nav.locator("a[aria-current='page'][href='/settings']").count() >= 1
        for panel_id in (
            "storage-settings-panel",
            "data-source-settings-panel",
            "qbittorrent-settings-panel",
            "auto-bangumi-settings-panel",
        ):
            assert page.locator(f"#{panel_id}.panel").count() >= 1
            assert page.locator(f"#{panel_id} .empty-state").count() >= 1

        for heading in ("Storage 偏好", "数据源", "qBittorrent", "Auto Bangumi"):
            assert page.locator(f"text={heading}").count() >= 1


class TestStaticAssets:
    """AC: 静态 CSS 与 JavaScript 资源成功加载，无关键控制台错误."""

    def test_css_loaded(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/index")
        assert page.locator('link[href*="style.css"]').count() >= 1

    def test_javascript_loaded(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/index")
        assert page.locator('script[src*="app.js"]').count() >= 1

    def test_no_critical_console_errors(self, page: Page, live_server_url: str) -> None:
        errors: list[str] = []

        def _capture(msg: object) -> None:
            if getattr(msg, "type", "") == "error":
                errors.append(str(getattr(msg, "text", "")))

        page.on("console", _capture)
        page.goto(f"{live_server_url}/index")
        page.wait_for_timeout(1000)

        critical = [e for e in errors if "favicon" not in e.lower()]
        assert not critical, f"Console errors after page load: {critical}"

    def test_viewport_meta_present(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/index")
        viewport = page.locator('meta[name="viewport"]')
        assert viewport.count() >= 1
        content = viewport.get_attribute("content")
        assert content and "width=device-width" in content


class TestNoSensitiveContent:
    """AC: 页面初始状态不展示 token、完整 endpoint URL、原始 HTML、原始 RSS XML 或本地绝对路径."""

    def test_no_urls_in_page(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/index")
        text = page.content().lower()
        assert "http://" not in text
        assert "https://" not in text

    def test_no_rss_xml_in_page(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/index")
        text = page.content().lower()
        assert "<rss" not in text

    def test_no_token_exposed(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/index")
        text = page.content().lower()
        assert "token" not in text

    def test_generation_form_descriptions_safe(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/index")
        body = page.locator("body").inner_text()
        # Form help text should be present and instructional
        assert "至少输入 1 个非空白字符" in body
        assert "留空时使用默认" in body
        assert "未勾选时只生成预览" in body


class TestEmptyListState:
    """AC: 缺少已保存 Request 时页面展示可恢复的空列表状态."""

    def test_list_count_shows_zero(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/index")
        count = page.locator("#request-list-count")
        assert count.count() >= 1
        assert "显示 0 / 0" in count.inner_text()

    def test_refresh_button_available(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/index")
        refresh = page.locator("#request-list-refresh")
        assert refresh.count() >= 1
        assert refresh.is_enabled()

    def test_list_container_empty_but_present(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/index")
        container = page.locator("#request-list-container")
        assert container.count() >= 1

    def test_search_and_filter_controls_present(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/index")
        assert page.locator("#request-list-search").count() >= 1
        assert page.locator("#request-list-status-filter").count() >= 1
        assert page.locator("#request-list-sort").count() >= 1
