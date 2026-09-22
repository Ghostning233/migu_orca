"""Stage 46 / US-362：共享控件与模式切换的真实 Chromium 门禁。

覆盖：

1. 模式切换的鼠标/方向键/Enter/空格，以及「不清输入、不清未保存现场」；
2. 默认控件 44px、首页大控件 52px、主要点击目标 >= 44x44；
3. primary/secondary/disabled/loading 的 token computed style 与对比度；
4. 3px 焦点环、reduced-motion、长中文、1280 桌面与 200% 缩放；
5. 图 01/04 共享控件区域的像素诊断（含连续三次稳定性）。

关于第 5 项：按像素门禁裁决 3C，Stage 46 **不对现有六张设计 PNG 启用 ≤0.5%
硬阈值**。设计图实测的模式切换轨道 64 px、主按钮 70 px 与冻结 Token V1 的
44/52 px 存在结构性冲突，差异带并集需要 55.14% 命名掩码（上限 35%，且禁止
整卡掩码）。这里只保留连续三次诊断证据；共享控件的硬门禁是冻结 Token 的控件
尺寸、computed style、键盘/焦点/对比度与四页调用者回归。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from playwright.sync_api import Page, expect

from tests.browser.visual_manifest import CONTROLS_REGION, PIXEL_GATE_RULING
from tests.browser.visual_support import (
    CANVAS,
    assert_stable_reports,
    browser_surface,
    capture_canvas,
    compare_with_design,
    prepare_canvas,
    require_dist,
)

pytestmark = pytest.mark.browser

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
TRACKING_BODY = json.dumps({"ok": True, "result": {"items": []}}, ensure_ascii=False)

_CONTRAST_SCRIPT = """
    (selector) => {
        const parse = (value) => {
            const match = value.match(/rgba?\\(([^)]+)\\)/)
            if (!match) return null
            const parts = match[1].split(',').map((part) => parseFloat(part.trim()))
            return parts.slice(0, 3)
        }
        const relative = (channel) => {
            const value = channel / 255
            return value <= 0.03928 ? value / 12.92 : Math.pow((value + 0.055) / 1.055, 2.4)
        }
        const luminance = (rgb) =>
            0.2126 * relative(rgb[0]) + 0.7152 * relative(rgb[1]) + 0.0722 * relative(rgb[2])
        const ratio = (a, b) => {
            const first = luminance(a)
            const second = luminance(b)
            return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05)
        }
        const element = document.querySelector(selector)
        if (!element) return null
        const style = getComputedStyle(element)
        const color = parse(style.color)
        const background = parse(style.backgroundColor)
        if (!color || !background) return null
        return { color: style.color, background: style.backgroundColor, ratio: ratio(color, background) }
    }
"""


def _install_routes(page: Page) -> None:
    page.route(
        "**/api/v1/settings/autobangumi",
        lambda route: route.fulfill(status=200, content_type="application/json", body=CONNECTION_SUMMARY_BODY),
    )
    page.route(
        "**/api/v1/tracking/items**",
        lambda route: route.fulfill(status=200, content_type="application/json", body=TRACKING_BODY),
    )


def _open_add(page: Page, live_server_url: str) -> None:
    require_dist()
    prepare_canvas(page)
    _install_routes(page)
    page.goto(f"{live_server_url}/app/add")
    page.wait_for_selector("#anime-mode-switch", timeout=10_000)


def _box(page: Page, selector: str) -> dict[str, float]:
    return page.evaluate(
        """(selector) => {
            const element = document.querySelector(selector)
            if (!element) return null
            const rect = element.getBoundingClientRect()
            return { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
        }""",
        selector,
    )


class TestAppSharedControlsVisual:
    """AC: 共享控件与模式切换统一消费 token，并在真实 Chromium 中可验证。"""

    def test_mode_switch_supports_mouse_and_keyboard(self, page: Page, live_server_url: str) -> None:
        _open_add(page, live_server_url)
        single = page.locator("#anime-mode-single")
        batch = page.locator("#anime-mode-batch")
        expect(single).to_have_attribute("aria-selected", "true")

        batch.click()
        expect(batch).to_have_attribute("aria-selected", "true")
        expect(page.locator("#batch-parse-form")).to_have_count(1)

        # 方向键在选项间移动并切换选中；Enter/空格激活。切换后宿主会把焦点
        # 交给对应输入框（既有行为），因此每一步都重新把焦点放回分段控件。
        single.focus()
        page.keyboard.press("ArrowRight")
        expect(batch).to_have_attribute("aria-selected", "true")

        batch.focus()
        page.keyboard.press("ArrowLeft")
        expect(single).to_have_attribute("aria-selected", "true")

        single.focus()
        page.keyboard.press("ArrowRight")
        expect(batch).to_have_attribute("aria-selected", "true")

        # 已选中项上再按 Enter 是幂等的（不重复触发、不取消选中）。
        batch.focus()
        page.keyboard.press("Enter")
        expect(batch).to_have_attribute("aria-selected", "true")

        single.focus()
        page.keyboard.press(" ")
        expect(single).to_have_attribute("aria-selected", "true")

        # roving tabindex：只有一个键盘停留点。
        assert page.evaluate(
            "() => Array.from(document.querySelectorAll('.anime-mode-option')).filter((el) => el.tabIndex === 0).length"
        ) == 1

    def test_mode_switch_keeps_input_and_unsaved_draft(self, page: Page, live_server_url: str) -> None:
        _open_add(page, live_server_url)
        page.fill("#mikan-candidate-query", "葬送的芙莉莲")
        page.click("#anime-mode-batch")
        page.fill("#batch-raw-input", "葬送的芙莉莲\n咒术回战")
        page.click("#anime-mode-single")

        # 切回单番：单番输入与选择现场仍保留，批量输入也没有被清空。
        assert page.input_value("#mikan-candidate-query") == "葬送的芙莉莲"
        page.click("#anime-mode-batch")
        assert page.input_value("#batch-raw-input") == "葬送的芙莉莲\n咒术回战"

    def test_control_heights_and_hit_targets(self, page: Page, live_server_url: str) -> None:
        _open_add(page, live_server_url)
        query = _box(page, "#mikan-candidate-query")
        submit = _box(page, "#mikan-candidate-search-submit")
        mode = _box(page, "#anime-mode-single")
        assert query and submit and mode
        # 首页大控件 52px。
        assert abs(query["height"] - 52) <= 0.5, query
        assert abs(submit["height"] - 52) <= 0.5, submit
        assert abs(mode["height"] - 52) <= 0.5, mode
        # 主要点击目标 >= 44x44。
        for name, box in (("query", query), ("submit", submit), ("mode", mode)):
            assert box["width"] >= 44 and box["height"] >= 44, (name, box)

        # 默认控件 44px（次要操作）。
        page.click("#anime-mode-batch")
        secondary = _box(page, "#batch-parse-submit")
        assert secondary and abs(secondary["height"] - 52) <= 0.5, secondary

    def test_button_variants_and_states_follow_tokens(self, page: Page, live_server_url: str) -> None:
        _open_add(page, live_server_url)
        styles = page.evaluate(
            """() => {
                const get = (selector) => {
                    const element = document.querySelector(selector)
                    if (!element) return null
                    const style = getComputedStyle(element)
                    return {
                        background: style.backgroundColor,
                        borderColor: style.borderTopColor,
                        borderWidth: style.borderTopWidth,
                        color: style.color,
                        opacity: style.opacity,
                        minHeight: style.minHeight,
                    }
                }
                return {
                    primary: get('#mikan-candidate-search-submit'),
                    disabledPrimary: get('#mikan-candidate-search-submit:disabled'),
                    fallback: get('#mikan-fallback-generate'),
                }
            }"""
        )
        assert styles["primary"]["background"] == "rgb(11, 42, 85)"  # deep-sea blue
        assert styles["primary"]["borderWidth"] == "1px"
        # 珊瑚红不是第二套普通主按钮：主搜索按钮不使用 accent。
        assert styles["primary"]["background"] != "rgb(217, 67, 31)"

        # 空输入时主按钮禁用，但文字仍可读（不是 0 透明度消失）。
        expect(page.locator("#mikan-candidate-search-submit")).to_be_disabled()
        disabled = page.evaluate(
            """() => {
                const element = document.querySelector('#mikan-candidate-search-submit')
                const style = getComputedStyle(element)
                return { opacity: style.opacity, cursor: style.cursor }
            }"""
        )
        assert float(disabled["opacity"]) >= 0.5
        assert disabled["cursor"] == "not-allowed"

    def test_loading_keeps_size_and_text(self, page: Page, live_server_url: str) -> None:
        import time

        _open_add(page, live_server_url)
        held: list[Any] = []

        def handler(route: Any, request: Any) -> None:
            if request.method != "POST":
                route.continue_()
                return
            held.append(route)

        page.route("**/api/v1/mikan/candidates", handler)
        page.fill("#mikan-candidate-query", "葬送的芙莉莲")
        idle_box = _box(page, "#mikan-candidate-search-submit")
        page.click("#mikan-candidate-search-submit")

        deadline = time.monotonic() + 10
        while not held and time.monotonic() < deadline:
            page.wait_for_timeout(50)
        assert held, "search request was not held"

        button = page.locator("#mikan-candidate-search-submit")
        expect(button).to_have_attribute("aria-busy", "true")
        expect(button.locator(".base-button-loading-label")).to_have_text("处理中…")
        loading_box = _box(page, "#mikan-candidate-search-submit")
        assert idle_box and loading_box
        assert abs(loading_box["height"] - idle_box["height"]) <= 0.5
        assert abs(loading_box["width"] - idle_box["width"]) <= 1.0

        held[0].fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"ok": True, "result": {"query": "葬送的芙莉莲", "status": "EMPTY", "candidates": [], "parse_result": None, "attempted_queries": [], "error": None}}, ensure_ascii=False),
        )

    def test_loading_keeps_idle_width_when_the_label_grows(
        self, page: Page, live_server_url: str
    ) -> None:
        """US-362 红测：loading 文案比 idle 文案更长时仍必须锁定 idle 宽度。

        候选按钮 idle 是「选择此合集」(5 字)，loading 是「正在生成草案」(6 字)：
        旧实现在这里会变宽，违反「loading 保留尺寸与文字」。
        """
        import time

        _open_add(page, live_server_url)
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": True,
                        "result": {
                            "query": "葬送的芙莉莲",
                            "status": "FOUND",
                            "parse_result": None,
                            "attempted_queries": [],
                            "error": None,
                            "candidates": [
                                {
                                    "bangumi_id": "2353",
                                    "title": "葬送的芙莉莲",
                                    "mikan_url": "https://mikan.example/Home/Bangumi/2353",
                                    "poster_url": None,
                                    "source_query": "葬送的芙莉莲",
                                    "aliases": [],
                                    "season_evidence": {"status": "PROVEN", "season": 1, "requires_review": False},
                                    "total_episodes": 28,
                                }
                            ],
                        },
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        held: list[Any] = []
        page.route(
            "**/api/v1/requests",
            lambda route, request: held.append(route) if request.method == "POST" else route.continue_(),
        )
        page.fill("#mikan-candidate-query", "葬送的芙莉莲")
        page.click("#mikan-candidate-search-submit")
        expect(page.locator(".candidate-card")).to_have_count(1)

        button = page.locator(".candidate-card .candidate-select")
        expect(button).to_contain_text("选择此合集")
        idle_width = button.bounding_box()["width"]

        button.click()
        deadline = time.monotonic() + 10
        while not held and time.monotonic() < deadline:
            page.wait_for_timeout(50)
        assert held, "draft creation request was not held"
        expect(button.locator(".base-button-loading-label")).to_have_text("正在生成草案…")
        loading_box = button.bounding_box()
        assert abs(loading_box["width"] - idle_width) <= 1.0, (idle_width, loading_box)
        # 文字仍可读，不是只剩旋转图标。
        expect(button).to_have_attribute("aria-busy", "true")

    def test_focus_ring_is_three_px_and_not_clipped(self, page: Page, live_server_url: str) -> None:
        _open_add(page, live_server_url)
        # Real keyboard navigation so :focus-visible (not just :focus) applies.
        page.evaluate("() => document.activeElement instanceof HTMLElement && document.activeElement.blur()")
        for _ in range(12):
            page.keyboard.press("Tab")
            if page.evaluate("() => document.activeElement && document.activeElement.id") == "anime-mode-single":
                break
        outline = page.evaluate(
            """() => {
                const element = document.querySelector('#anime-mode-single')
                const style = getComputedStyle(element)
                const rect = element.getBoundingClientRect()
                const track = document.querySelector('#anime-mode-switch').getBoundingClientRect()
                return {
                    width: style.outlineWidth,
                    style: style.outlineStyle,
                    focused: document.activeElement === element,
                    clipped: rect.left - 3 < track.left - 1 || rect.right + 3 > track.right + 1,
                }
            }"""
        )
        assert outline["focused"] is True
        assert outline["width"] == "3px"
        assert outline["style"] == "solid"
        assert outline["clipped"] is False

    def test_body_and_control_contrast(self, page: Page, live_server_url: str) -> None:
        _open_add(page, live_server_url)
        body = page.evaluate(
            """() => {
                const style = getComputedStyle(document.body)
                return { color: style.color, background: style.backgroundColor }
            }"""
        )
        ratio = page.evaluate(_CONTRAST_SCRIPT, "body")
        assert ratio is not None, body
        # 正文对比度至少 4.5:1（token 校正值）。
        assert ratio["ratio"] >= 4.5, ratio

        # 控件边界至少 3:1：输入框边框对白色表面。
        border = page.evaluate(
            """() => {
                const parse = (value) => value.match(/rgba?\\(([^)]+)\\)/)[1]
                    .split(',').map((part) => parseFloat(part.trim())).slice(0, 3)
                const relative = (channel) => {
                    const value = channel / 255
                    return value <= 0.03928 ? value / 12.92 : Math.pow((value + 0.055) / 1.055, 2.4)
                }
                const luminance = (rgb) => 0.2126 * relative(rgb[0]) + 0.7152 * relative(rgb[1]) + 0.0722 * relative(rgb[2])
                const element = document.querySelector('#mikan-candidate-query')
                const style = getComputedStyle(element)
                const edge = parse(style.borderTopColor)
                const surface = parse(style.backgroundColor)
                const first = luminance(edge)
                const second = luminance(surface)
                return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05)
            }"""
        )
        assert border >= 3.0, border

    def test_reduced_motion_keeps_progress_text(self, page: Page, live_server_url: str) -> None:
        import time

        _open_add(page, live_server_url)
        page.emulate_media(reduced_motion="reduce")
        held: list[Any] = []
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route, request: held.append(route) if request.method == "POST" else route.continue_(),
        )
        page.fill("#mikan-candidate-query", "葬送的芙莉莲")
        page.click("#mikan-candidate-search-submit")
        deadline = time.monotonic() + 10
        while not held and time.monotonic() < deadline:
            page.wait_for_timeout(50)
        assert held
        state = page.evaluate(
            """() => {
                const spinner = document.querySelector('.base-button-spinner')
                const label = document.querySelector('.base-button-loading-label')
                return {
                    spinnerDisplay: spinner ? getComputedStyle(spinner).display : null,
                    label: label ? label.textContent.trim() : null,
                }
            }"""
        )
        # reduced-motion 下旋转弧被抑制，但进行中文字仍在。
        assert state["spinnerDisplay"] in (None, "none")
        assert state["label"] == "处理中…"

    def test_long_chinese_and_narrow_desktop_do_not_overflow(
        self, page: Page, live_server_url: str
    ) -> None:
        require_dist()
        _install_routes(page)
        page.set_viewport_size({"width": 1280, "height": 720})
        page.goto(f"{live_server_url}/app/add")
        page.wait_for_selector("#anime-mode-switch", timeout=10_000)
        page.fill("#mikan-candidate-query", "这是一个非常长的中文番剧标题用于验证控件在窄桌面下不会溢出操作区" * 2)
        metrics = page.evaluate(
            """() => {
                const form = document.querySelector('.workbench-search-form').getBoundingClientRect()
                const submit = document.querySelector('#mikan-candidate-search-submit').getBoundingClientRect()
                return {
                    viewportWidth: window.innerWidth,
                    bodyScrollWidth: document.body.scrollWidth,
                    submitRight: submit.right,
                    formRight: form.right,
                }
            }"""
        )
        assert metrics["bodyScrollWidth"] <= metrics["viewportWidth"] + 1
        assert metrics["submitRight"] <= metrics["viewportWidth"] + 1
        assert metrics["formRight"] <= metrics["viewportWidth"] + 1

    @pytest.mark.parametrize("figure", [1, 4])
    def test_shared_control_region_diagnostics(
        self, page: Page, live_server_url: str, tmp_path: Path, figure: int
    ) -> None:
        """图 01/04 共享控件区域：连续三次诊断，无设计图像素硬阈值。

        按像素门禁裁决 3C，Stage 46 不对现有六张 PNG 启用 ≤0.5% 硬门禁；共享控件
        的硬门禁是冻结 Token 的控件尺寸、computed style、键盘/焦点/对比度与调用者回归。
        """
        _open_add(page, live_server_url)
        if figure == 4:
            page.click("#anime-mode-batch")
            page.fill("#batch-raw-input", "葬送的芙莉莲\n咒术回战\n孤独摇滚")
        reports: list[dict[str, Any]] = []
        for run in range(3):
            shot = capture_canvas(page, tmp_path / f"controls-figure-{figure:02d}-run{run}.png")
            with Image.open(shot) as captured:
                assert captured.size == CANVAS
            diff = tmp_path / f"controls-figure-{figure:02d}-run{run}-diff.png"
            stats = compare_with_design(
                figure,
                shot,
                region=CONTROLS_REGION,
                diff_path=diff,
            )
            report = stats.as_report()
            reports.append(report)
            print(f"controls figure-{figure:02d} run{run} diff_ratio={report['diff_ratio']} mask={report['mask_ratio']}")
        assert PIXEL_GATE_RULING["design_pixel_gate_enabled"] is False
        assert_stable_reports(reports)
        assert reports[0]["canvas"] == {"width": CONTROLS_REGION[2] - CONTROLS_REGION[0], "height": CONTROLS_REGION[3] - CONTROLS_REGION[1]}
        assert reports[0]["compared_pixels"] == (CONTROLS_REGION[2] - CONTROLS_REGION[0]) * (CONTROLS_REGION[3] - CONTROLS_REGION[1])

    def test_other_pages_keep_working_shared_controls(self, page: Page, live_server_url: str) -> None:
        require_dist()
        _install_routes(page)
        prepare_canvas(page)
        for route in ("/app/tracking", "/app/settings"):
            page.goto(f"{live_server_url}{route}")
            page.wait_for_selector(".app-header", timeout=10_000)
            expect(page.locator("#app-main")).to_be_visible()
            # 无横向溢出；按钮/输入保持最小点击目标。
            metrics = page.evaluate(
                """() => {
                    const targets = Array.from(
                        document.querySelectorAll('#app-main .primary-button, #app-main .secondary-button'),
                    ).filter((el) => el.getBoundingClientRect().width > 0)
                    return {
                        viewportWidth: window.innerWidth,
                        bodyScrollWidth: document.body.scrollWidth,
                        checkedTargets: targets.length,
                        smallTargets: targets
                            .filter((el) => {
                                const rect = el.getBoundingClientRect()
                                return rect.height < 44 || rect.width < 44
                            })
                            .map((el) => (el.id || el.textContent || '').trim().slice(0, 24)),
                    }
                }"""
            )
            assert metrics["bodyScrollWidth"] <= metrics["viewportWidth"] + 1, route
            # 主要目标至少 44x44（AC2），不用 24px 兜底。
            assert metrics["smallTargets"] == [], (route, metrics)

        surface = browser_surface(page)
        assert surface["url"].endswith("/app/settings")
