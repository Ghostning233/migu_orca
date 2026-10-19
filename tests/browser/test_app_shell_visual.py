"""共享应用壳层的真实 Chromium 门禁（Issue 109 数值基线）。

三层证据：

1. 锚点：1280／1440／1920 下顶栏高度、内容容器盒、品牌左缘、连接胶囊右缘、
   首项导航与胶囊的垂直居中全部由冻结 Token 决定，相差 <= 2 CSS px；
2. computed style：品牌/导航/下划线的颜色、字号、边框、阴影与档位内边距
   全部来自语义 token（24／32／48px）；
3. 图像：顶栏条带（``SHELL_REGION``）与归一化设计图的差异比例只作诊断，
   按像素门禁裁决 3C 不设硬阈值（位图仅作人工辅助）。

另外覆盖 200% 缩放、键盘焦点、reduced-motion 与另外两个一级页面的定向不回归。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.saved_tracking_fixtures import _status_groups, _summary
from tests.browser.visual_manifest import (
    CONTENT_MAX,
    PIXEL_GATE_RULING,
    SHELL_DIAGNOSTIC_ANCHORS,
    SHELL_REGION,
    SHELL_VIEWPORTS,
    content_padding_inline,
    shell_anchors_for,
)
from tests.browser.visual_support import (
    anchor_summary,
    assert_stable_reports,
    browser_surface,
    capture_canvas,
    compare_shell,
    prepare_canvas,
    require_dist,
)

pytestmark = pytest.mark.browser

DIFF_MARKER_RGB = (217, 67, 31)


def _diff_distribution(path: Path) -> dict[str, Any]:
    """诊断用：差异高亮图的行/列分布（仅打印，不参与通过判定）。"""
    from PIL import Image

    with Image.open(path) as image:
        rgb = image.convert("RGB")
        pixels = rgb.load()
        width, height = rgb.size
        rows: dict[int, int] = {}
        columns: dict[int, int] = {}
        for y in range(height):
            for x in range(width):
                if pixels[x, y] == DIFF_MARKER_RGB:
                    rows[y] = rows.get(y, 0) + 1
                    columns[x] = columns.get(x, 0) + 1
    top_rows = sorted(rows.items(), key=lambda item: -item[1])[:8]
    top_columns = sorted(columns.items(), key=lambda item: -item[1])[:8]
    return {"rows": top_rows, "columns": top_columns}

CONNECTION_SUMMARY_BODY = json.dumps(
    {
        "ok": True,
        "result": {
            "configured": False,
            "credential_present": False,
            "connection_status": "UNCONFIGURED",
            "capabilities": None,
        },
    },
    ensure_ascii=False,
)
TRACKING_BODY = json.dumps(
    {
        "ok": True,
        "result": {
            "items": [],
            "summary": _summary(0),
            "status_groups": _status_groups(),
            "warnings": [],
        },
    },
    ensure_ascii=False,
)

SHELL_ROUTES = {
    "add": "/app/add",
    "tracking": "/app/tracking",
    "settings": "/app/settings",
}


def _install_shell_routes(page: Page) -> None:
    """固定连接状态与待处理数量，避免真实外部依赖影响壳层渲染。"""
    page.route(
        "**/api/v1/settings/autobangumi",
        lambda route: route.fulfill(status=200, content_type="application/json", body=CONNECTION_SUMMARY_BODY),
    )
    page.route(
        "**/api/v1/tracking/items**",
        lambda route: route.fulfill(status=200, content_type="application/json", body=TRACKING_BODY),
    )


def _open_shell(page: Page, live_server_url: str, route: str = "/app/add", width: int | None = None) -> None:
    require_dist()
    prepare_canvas(page)
    if width is not None:
        page.set_viewport_size({"width": width, "height": 900})
    _install_shell_routes(page)
    page.goto(f"{live_server_url}{route}")
    page.wait_for_selector(".app-header", timeout=10_000)


class TestAppShellVisual:
    """AC: 1440×900 下壳层结构、状态与无障碍语义与设计一致。"""

    def test_header_uses_text_brand_three_nav_items_and_status_pill(
        self, page: Page, live_server_url: str
    ) -> None:
        _open_shell(page, live_server_url)

        expect(page.locator(".brand-block")).to_have_count(1)
        expect(page.locator(".app-title")).to_have_text("MiGuOrca")
        # 设计图没有可见 M 方块与 eyebrow。
        assert page.evaluate("() => document.querySelectorAll('.brand-mark, .brand-eyebrow').length") == 0
        expect(page.locator(".brand-block")).to_have_attribute("aria-label", "返回添加番剧")

        links = page.locator(".top-nav .nav-link")
        expect(links).to_have_count(3)
        assert links.all_inner_texts() == ["添加番剧", "我的追番", "设置"]
        expect(links.nth(0)).to_have_attribute("aria-current", "page")
        for index in (1, 2):
            assert links.nth(index).get_attribute("aria-current") is None

        status = page.locator(".workspace-status")
        expect(status).to_be_visible()
        # 未配置时可见文案紧凑，完整中文语义留在 accessible name。
        expect(status.locator(".workspace-status-label")).to_have_text("未配置")
        aria = status.get_attribute("aria-label") or ""
        assert "Auto Bangumi 连接状态" in aria and "未配置" in aria
        assert "endpoint" not in aria.lower()

    @pytest.mark.parametrize("width", SHELL_VIEWPORTS)
    def test_shell_anchors_are_within_two_css_px(
        self, page: Page, live_server_url: str, width: int
    ) -> None:
        """Issue 109: 1280/1440/1920 下壳层锚点都由 Token 档位决定。"""
        _open_shell(page, live_server_url, width=width)
        summary = anchor_summary(page, shell_anchors_for(width))
        failures = {
            name: entry
            for name, entry in summary.items()
            if not entry.get("found") or not entry.get("within_tolerance")
        }
        assert not failures, json.dumps(failures, ensure_ascii=False, indent=2)

        diagnostic = anchor_summary(page, SHELL_DIAGNOSTIC_ANCHORS)
        print(f"shell diagnostic anchors @{width}:", json.dumps(diagnostic, ensure_ascii=False))

    @pytest.mark.parametrize("width", SHELL_VIEWPORTS)
    def test_shell_width_tier_padding_is_shared_by_header_and_page(
        self, page: Page, live_server_url: str, width: int
    ) -> None:
        """Issue 109: 顶栏与页面容器共用 Token V1 §6.1 的档位内边距。"""
        _open_shell(page, live_server_url, width=width)
        expected_padding = content_padding_inline(width)
        expected_width = min(float(width), CONTENT_MAX)
        expected_left = (width - expected_width) / 2.0
        metrics = page.evaluate(
            """() => {
                const headerInner = document.querySelector('.app-header-inner')
                const main = document.querySelector('.app-main')
                const mainStyle = getComputedStyle(main)
                const headerStyle = getComputedStyle(headerInner)
                return {
                    headerPaddingLeft: parseFloat(headerStyle.paddingLeft),
                    headerPaddingRight: parseFloat(headerStyle.paddingRight),
                    mainPaddingLeft: parseFloat(mainStyle.paddingLeft),
                    mainPaddingRight: parseFloat(mainStyle.paddingRight),
                    mainBox: main.getBoundingClientRect().x,
                    mainWidth: main.getBoundingClientRect().width,
                    headerLeft: headerInner.getBoundingClientRect().x,
                    headerWidth: headerInner.getBoundingClientRect().width,
                    brandLeft: document.querySelector('.brand-block').getBoundingClientRect().x,
                    statusRight: document.querySelector('.workspace-status').getBoundingClientRect().right,
                    navLeft: document.querySelector('.top-nav').getBoundingClientRect().x,
                    brandRight: document.querySelector('.brand-block').getBoundingClientRect().right,
                    bodyScrollWidth: document.body.scrollWidth,
                    viewportWidth: window.innerWidth,
                }
            }"""
        )
        # 档位内边距：24（<1440）/ 32（1440–1679）/ 48（≥1680），顶栏与页面一致。
        assert metrics["headerPaddingLeft"] == expected_padding
        assert metrics["headerPaddingRight"] == expected_padding
        assert metrics["mainPaddingLeft"] == expected_padding
        assert metrics["mainPaddingRight"] == expected_padding
        # 内容容器在 1920 宽度下居中且不超过 --size-content-max。
        assert abs(metrics["headerLeft"] - expected_left) <= 0.5
        assert abs(metrics["headerWidth"] - expected_width) <= 0.5
        assert abs(metrics["mainBox"] - expected_left) <= 0.5
        assert abs(metrics["mainWidth"] - expected_width) <= 0.5
        # 品牌与连接胶囊分别落在内容容器的两端，导航紧随品牌（左组）。
        assert abs(metrics["brandLeft"] - (expected_left + expected_padding)) <= 0.5
        assert abs(metrics["statusRight"] - (expected_left + expected_width - expected_padding)) <= 0.5
        assert metrics["navLeft"] >= metrics["brandRight"] - 0.5
        # 无水平溢出。
        assert metrics["bodyScrollWidth"] <= metrics["viewportWidth"] + 1

    def test_shell_region_diagnostics_are_deterministic(
        self, page: Page, live_server_url: str, tmp_path: Path
    ) -> None:
        """壳层区域诊断：只断言统计确定性与合法性。

        按像素门禁裁决 3C，Stage 46 不对现有六张设计 PNG 启用 ≤0.5% 硬阈值
        （设计图 86px/121px 与冻结 Token 72px/20px 的结构性冲突无法用 ≤35% 的
        命名掩码覆盖）。这里保留连续三次诊断证据，硬门禁由 ``SHELL_ANCHORS``
        几何、computed style、键盘/对比度与三页回归承担。
        """
        assert PIXEL_GATE_RULING["design_pixel_gate_enabled"] is False
        _open_shell(page, live_server_url)
        reports: list[dict[str, Any]] = []
        for run in range(3):
            shot = capture_canvas(page, tmp_path / f"shell-run{run}.png")
            diff = tmp_path / f"shell-run{run}-diff.png"
            stats = compare_shell(shot, diff_path=diff)
            report = stats.as_report()
            reports.append(report)
            print(f"shell run{run} diff_ratio={report['diff_ratio']} mask_ratio={report['mask_ratio']}")
            print(f"shell run{run} diff distribution={_diff_distribution(diff)}")
        assert_stable_reports(reports)
        assert reports[0]["canvas"] == {"width": SHELL_REGION[2], "height": SHELL_REGION[3]}
        assert reports[0]["compared_pixels"] == SHELL_REGION[2] * SHELL_REGION[3]
        assert 0.0 <= reports[0]["diff_ratio"] <= 1.0
        assert reports[0]["resample"] == "LANCZOS"
        assert reports[0]["channel_threshold"] == 12

    def test_shell_computed_styles_consume_semantic_tokens(
        self, page: Page, live_server_url: str
    ) -> None:
        _open_shell(page, live_server_url)
        styles = page.evaluate(
            """() => {
                const header = getComputedStyle(document.querySelector('.app-header'))
                const current = getComputedStyle(document.querySelector('.nav-link[aria-current="page"]'))
                const underline = getComputedStyle(
                    document.querySelector('.nav-link[aria-current="page"]'), '::after')
                const title = getComputedStyle(document.querySelector('.app-title'))
                const status = getComputedStyle(document.querySelector('.workspace-status'))
                return {
                    headerHeight: document.querySelector('.app-header').getBoundingClientRect().height,
                    headerBackground: header.backgroundColor,
                    titleColor: title.color,
                    titleFontSize: title.fontSize,
                    currentColor: current.color,
                    underlineHeight: underline.height,
                    underlineColor: underline.backgroundColor,
                    statusBorderRadius: status.borderRadius,
                    statusBorderWidth: status.borderTopWidth,
                    statusBackground: status.backgroundColor,
                }
            }"""
        )
        # 顶栏高取冻结 token --size-shell-header(72px)；白色表面与珊瑚红当前项/下划线。
        assert abs(styles["headerHeight"] - 72) <= 0.5
        assert styles["headerBackground"] == "rgb(255, 255, 255)"
        assert styles["titleColor"] == "rgb(16, 35, 63)"
        assert styles["titleFontSize"] == "28px"
        assert styles["currentColor"] == "rgb(217, 67, 31)"
        assert styles["underlineColor"] == "rgb(217, 67, 31)"
        assert styles["underlineHeight"] == "4px"
        assert styles["statusBorderRadius"] == "999px"
        assert styles["statusBorderWidth"] == "1px"
        assert styles["statusBackground"] == "rgb(242, 245, 248)"

    def test_shell_status_never_renders_secrets(
        self, page: Page, live_server_url: str
    ) -> None:
        """配置存在时也只展示中文摘要与设置入口，不出现 endpoint/凭据/内部代码。"""
        require_dist()
        prepare_canvas(page)
        page.route(
            "**/api/v1/settings/autobangumi",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": True,
                        "result": {
                            "configured": True,
                            "credential_present": True,
                            "connection_status": "VERIFIED",
                            "endpoint": "https://canary-361.invalid/ab",
                            "credential": "canary-361-secret",
                            "capabilities": {"probe_status": "VERIFIED"},
                        },
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        page.route(
            "**/api/v1/tracking/items**",
            lambda route: route.fulfill(status=200, content_type="application/json", body=TRACKING_BODY),
        )
        page.goto(f"{live_server_url}/app/add")
        page.wait_for_selector(".workspace-status", timeout=10_000)
        expect(page.locator(".workspace-status-label")).to_have_text("连接可用")
        surface = browser_surface(page)
        for canary in ("canary-361.invalid", "canary-361-secret", "endpoint="):
            assert canary not in surface["bodyText"]
            assert canary not in surface["attributes"]
            assert canary not in surface["url"]
            assert canary not in surface["localStorage"]
        # 链接目的地仍是设置页。
        assert (page.locator(".workspace-status").get_attribute("href") or "").endswith("/settings")

    @pytest.mark.parametrize(
        ("width", "height"),
        [(1280, 720), (1440, 900), (1920, 1080)],
    )
    def test_shell_holds_at_desktop_viewports(
        self, page: Page, live_server_url: str, width: int, height: int
    ) -> None:
        require_dist()
        _install_shell_routes(page)
        page.set_viewport_size({"width": width, "height": height})
        page.goto(f"{live_server_url}/app/add")
        page.wait_for_selector(".app-header", timeout=10_000)
        metrics = page.evaluate(
            """() => {
                const nav = document.querySelector('.top-nav').getBoundingClientRect()
                const status = document.querySelector('.workspace-status').getBoundingClientRect()
                const links = Array.from(document.querySelectorAll('.nav-link')).map(
                    (el) => el.getBoundingClientRect())
                return {
                    navRight: nav.right,
                    statusLeft: status.left,
                    statusRight: status.right,
                    viewportWidth: window.innerWidth,
                    bodyScrollWidth: document.body.scrollWidth,
                    linksInsideViewport: links.every((box) => box.left >= 0 && box.right <= window.innerWidth),
                }
            }"""
        )
        assert metrics["linksInsideViewport"] is True
        assert metrics["statusRight"] <= metrics["viewportWidth"] + 1
        # 状态胶囊不覆盖导航。
        assert metrics["statusLeft"] >= metrics["navRight"] - 1
        assert metrics["bodyScrollWidth"] <= metrics["viewportWidth"] + 1

    def test_shell_holds_under_two_hundred_percent_zoom(
        self, page: Page, live_server_url: str
    ) -> None:
        """桌面 200% 缩放（等效 720 CSS px 视口）：导航重排且胶囊不遮挡。"""
        require_dist()
        _install_shell_routes(page)
        page.set_viewport_size({"width": 720, "height": 450})
        page.goto(f"{live_server_url}/app/add")
        page.wait_for_selector(".app-header", timeout=10_000)
        metrics = page.evaluate(
            """() => {
                const header = document.querySelector('.app-header').getBoundingClientRect()
                const status = document.querySelector('.workspace-status').getBoundingClientRect()
                const links = Array.from(document.querySelectorAll('.nav-link')).map(
                    (el) => el.getBoundingClientRect())
                return {
                    headerHeight: header.height,
                    statusTop: status.top,
                    minLinkBottom: Math.min(...links.map((box) => box.bottom)),
                    bodyScrollWidth: document.body.scrollWidth,
                    viewportWidth: window.innerWidth,
                }
            }"""
        )
        # 重排后胶囊回到正常流：不覆盖导航。
        assert metrics["statusTop"] >= metrics["minLinkBottom"] - 1
        assert metrics["bodyScrollWidth"] <= metrics["viewportWidth"] + 1
        assert (page.locator(".workspace-status").get_attribute("href") or "").endswith("/settings")

    def test_shell_keyboard_focus_and_skip_link(self, page: Page, live_server_url: str) -> None:
        _open_shell(page, live_server_url)
        # The add page autofocuses its search input on mount; drop focus first so
        # the assertion measures the real document tab order from the top.
        page.evaluate("() => document.activeElement instanceof HTMLElement && document.activeElement.blur()")
        labels: list[str] = []
        for _ in range(9):
            page.keyboard.press("Tab")
            labels.append(
                page.evaluate(
                    """() => {
                        const element = document.activeElement
                        if (!element) return ''
                        return element.id || element.getAttribute('aria-label') || element.className || element.tagName
                    }"""
                )
            )
        assert "skip-link" in labels, labels
        index = labels.index("skip-link")
        # Skip link 是第一个可聚焦元素，其后是品牌返回与四项导航。
        assert labels[index + 1] == "返回添加番剧", labels
        # Issue #93: three primary navigation entries.
        assert labels[index + 2 : index + 5] == ["shell-nav-1", "shell-nav-2", "shell-nav-3"], labels

        page.locator("#skip-link").focus()
        page.keyboard.press("Enter")
        expect(page.locator("#app-main")).to_be_focused()

    def test_shell_current_item_is_identifiable_under_reduced_motion(
        self, page: Page, live_server_url: str
    ) -> None:
        require_dist()
        prepare_canvas(page)
        page.emulate_media(reduced_motion="reduce")
        _install_shell_routes(page)
        page.goto(f"{live_server_url}/app/tracking")
        page.wait_for_selector(".app-header", timeout=10_000)
        current = page.locator('.nav-link[aria-current="page"]')
        expect(current).to_have_text("我的追番")
        styles = page.evaluate(
            """() => {
                const el = document.querySelector('.nav-link[aria-current="page"]')
                const after = getComputedStyle(el, '::after')
                return { color: getComputedStyle(el).color, background: after.backgroundColor, height: after.height }
            }"""
        )
        # reduced-motion 下当前项仍由文字颜色 + 下划线共同表达，不只是颜色。
        assert styles["color"] == "rgb(217, 67, 31)"
        assert styles["background"] == "rgb(217, 67, 31)"
        assert styles["height"] == "4px"

    @pytest.mark.parametrize("route_key", ["tracking", "settings"])
    def test_other_primary_pages_keep_navigation_and_content(
        self, page: Page, live_server_url: str, route_key: str
    ) -> None:
        """三个非目标页面只做导航/内容定向回归，不做像素改版。"""
        _open_shell(page, live_server_url, SHELL_ROUTES[route_key])
        expect(page.locator(".top-nav .nav-link")).to_have_count(3)
        expect(page.locator(f'#shell-nav-{list(SHELL_ROUTES).index(route_key) + 1}')).to_have_attribute(
            "aria-current", "page"
        )
        expect(page.locator("#app-main")).to_be_visible()
        main_text = page.locator("#app-main").inner_text()
        assert main_text.strip(), f"{route_key} 页面没有渲染内容"
        assert "跳到主要内容" not in main_text
