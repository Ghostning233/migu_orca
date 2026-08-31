from __future__ import annotations

import pytest
from playwright.sync_api import Page

from tests.browser.conftest import open_dev_fixture_panel

pytestmark = [pytest.mark.browser, pytest.mark.legacy_entry]


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


class TestIndexStage13WorkbenchShell:
    """AC: /index 可加载 Stage 13 Request 工作台、顶部导航和运行模式提示."""

    def test_stage13_workbench_branding_visible(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/index")

        assert page.locator("text=MiGuOrca").count() >= 1
        assert page.locator("text=Stage 13 订阅方案工作台").count() >= 1
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
        assert nav.locator("text=订阅方案工作台").count() >= 1
        assert nav.locator("text=Settings").count() >= 1

    def test_mode_hint_describes_local_storage(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/index")

        hint = page.locator("text=运行模式：本地 JSON storage").first
        assert hint.count() >= 1
        # Mode hint should mention offline/fixture behavior
        body = page.locator("body").inner_text()
        assert "fixture-backed" in body
        assert "外部数据源、连接测试与提交配置集中在 Settings" in body

    def test_main_panels_present(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/index")

        for panel_id in (
            "generate-panel",
            "search-results-panel",
            "request-list-panel",
            "request-detail-panel",
        ):
            assert page.locator(f"#{panel_id}").count() >= 1, (
                f"Missing panel: #{panel_id}"
            )
        for removed_panel_id in ("qbittorrent-panel", "acceptance-panel"):
            assert page.locator(f"#{removed_panel_id}").count() == 0

    def test_all_section_headings_present(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/index")

        for heading in (
            "创建订阅方案",
            "搜索结果",
            "订阅方案列表",
            "订阅方案详情",
        ):
            assert page.locator(f"text={heading}").count() >= 1, (
                f"Missing heading: {heading}"
            )
        assert page.locator("text=qBittorrent 连接测试").count() == 0
        assert page.locator("text=验收说明").count() == 0

    def test_search_modes_keep_inputs_and_results_separate(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/index")

        single_tab = page.get_by_role("tab", name="单个搜索")
        batch_tab = page.get_by_role("tab", name="批量搜索")
        assert single_tab.get_attribute("aria-selected") == "true"
        assert batch_tab.get_attribute("aria-selected") == "false"
        assert page.locator("#single-search-entry").is_visible()
        assert page.locator("#batch-workbench-entry").is_hidden()
        assert page.locator("#mikan-candidate-search-result").is_visible()
        assert page.locator("#batch-search-results").is_hidden()

        batch_tab.click()
        assert batch_tab.get_attribute("aria-selected") == "true"
        assert single_tab.get_attribute("aria-selected") == "false"
        assert page.locator("#batch-workbench-entry").is_visible()
        assert page.locator("#single-search-entry").is_hidden()
        assert page.locator("#batch-search-results").is_visible()
        assert page.locator("#mikan-candidate-search-result").is_hidden()

        batch_tab.press("ArrowLeft")
        assert single_tab.get_attribute("aria-selected") == "true"
        assert page.locator("#single-search-entry").is_visible()


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
            "preference-settings-panel",
            "data-source-settings-panel",
            "qbittorrent-settings-panel",
            "auto-bangumi-settings-panel",
        ):
            assert page.locator(f"#{panel_id}.panel").count() >= 1
            assert page.locator(f"#{panel_id} .empty-state").count() >= 1

        for heading in ("Storage 偏好", "偏好默认值", "数据源", "qBittorrent", "Auto Bangumi"):
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
        # 提交前队列表单（US-147）合法包含空 token 输入框；安全契约是不得携带
        # 任何实际 token 值，而不是“token”这个词永远不出现。
        token_input = page.locator("#batch-queue-ab-token")
        assert token_input.count() >= 1
        assert token_input.get_attribute("type") == "password"
        assert token_input.input_value() == ""
        # 初始状态下所有文本/密码输入均为空，避免预填秘密值进入 DOM
        for element in page.locator(
            "input[type=text], input[type=password], input[type=search], "
            "input[type=url], input:not([type]), textarea"
        ).all():
            assert element.input_value() == "", (
                f"input #{element.get_attribute('id')} has a prefilled value"
            )

    def test_generation_form_descriptions_safe(self, page: Page, live_server_url: str) -> None:
        page.goto(f"{live_server_url}/index")
        # The fixture form is inside the collapsed dev/offline-test disclosure
        # (US-130), so expand it before asserting its help text is instructional.
        open_dev_fixture_panel(page)
        body = page.locator("body").inner_text()
        # Form help text should be present and instructional
        assert "至少输入 1 个非空白字符" in body
        assert "默认服务器 storage 根目录" in body
        assert "默认保存订阅方案 JSON" in body
        assert "前往 Settings" in body
        assert "search_endpoint" not in body
        assert "timeout_seconds" not in body


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
