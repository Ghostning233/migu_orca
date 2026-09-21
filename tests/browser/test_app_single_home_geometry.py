"""Stage 47 / US-363：单番搜索首页（图 01）的获批几何门禁。

基线形态为 B（数值型正式测量基线，见
``docs/design/frontend-ux-stage47-single-anime-geometry-baseline.md``），因此本文件不启用像素层，
门禁由锚点（<=2 CSS px）、computed style（冻结 Token）与几何/状态断言组成。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.stage47_single_home_baseline import (
    CENTER_X,
    FORBIDDEN_INITIAL_SELECTORS,
    HOME_BOXES,
    HOME_CENTERED,
    HOME_SELECTORS,
    HOME_SPACING,
    TOLERANCE,
    VIEWPORT,
)
from tests.browser.visual_support import (
    install_shell_status_routes,
    prepare_canvas,
    require_dist,
)

pytestmark = pytest.mark.browser


PAGE_TOLERANCE = 2.0


def _open_single_home(page: Page, live_server_url: str) -> list[str]:
    """打开单番首页并记录所有非本地 API 之外的请求，返回 request URL 列表。"""
    require_dist()
    prepare_canvas(page)
    requested: list[str] = []
    page.on("request", lambda request: requested.append(request.url))
    install_shell_status_routes(page)
    page.goto(f"{live_server_url}/app/add")
    page.wait_for_selector(".single-home-hero", timeout=10_000)
    return requested


class TestSingleHomeGeometry:
    """AC: 首页只组织一次搜索任务，并按获批 Token V1 几何呈现。"""

    def test_approved_geometry_matches_baseline(self, page: Page, live_server_url: str) -> None:
        """容器盒尺寸、水平居中、相邻间距与垂直居中全部对齐获批基线（<=2 CSS px）。"""
        _open_single_home(page, live_server_url)
        boxes = page.evaluate(
            """(selectors) => {
                const out = {}
                for (const [name, selector] of Object.entries(selectors)) {
                    const element = document.querySelector(selector)
                    if (!element) { out[name] = null; continue }
                    const rect = element.getBoundingClientRect()
                    out[name] = {
                        x: rect.x, y: rect.y, width: rect.width, height: rect.height,
                        centerX: rect.x + rect.width / 2,
                    }
                }
                return out
            }""",
            HOME_SELECTORS,
        )
        problems: list[str] = []
        for name, (_, width, height) in HOME_BOXES.items():
            box = boxes.get(name)
            if box is None:
                problems.append(f"{name}: element missing")
                continue
            if abs(box["width"] - width) > TOLERANCE:
                problems.append(f"{name}: width {box['width']} != {width}")
            if abs(box["height"] - height) > TOLERANCE:
                problems.append(f"{name}: height {box['height']} != {height}")
        for name in HOME_CENTERED:
            box = boxes.get(name)
            if box is not None and abs(box["centerX"] - CENTER_X) > TOLERANCE:
                problems.append(f"{name}: centerX {box['centerX']} != {CENTER_X}")
        for previous, following, gap in HOME_SPACING:
            first, second = boxes.get(previous), boxes.get(following)
            if first and second:
                actual = second["y"] - (first["y"] + first["height"])
                if abs(actual - gap) > TOLERANCE:
                    problems.append(f"{previous}->{following}: gap {actual} != {gap}")
        hero = boxes.get("hero")
        steps, title = boxes.get("steps"), boxes.get("title")
        if hero and steps and title:
            top_gap = title["y"] - hero["y"]
            bottom_gap = (hero["y"] + hero["height"]) - (steps["y"] + steps["height"])
            if abs(top_gap - bottom_gap) > TOLERANCE:
                problems.append(f"vertical centring: top {top_gap} != bottom {bottom_gap}")
        assert not problems, json.dumps(problems, ensure_ascii=False, indent=2)

    def test_content_area_uses_token_page_padding(self, page: Page, live_server_url: str) -> None:
        _open_single_home(page, live_server_url)
        box = page.evaluate(
            """() => {
                const main = document.querySelector('.app-main').getBoundingClientRect()
                return { x: main.x, width: main.width, paddingTop: getComputedStyle(document.querySelector('.app-main')).paddingTop,
                         paddingLeft: getComputedStyle(document.querySelector('.app-main')).paddingLeft }
            }"""
        )
        # Token 档位：1440 视口 -> 32px 水平页内边距；垂直 --space-6 24px。
        assert box["paddingLeft"] == "32px"
        assert box["paddingTop"] == "24px"
        # 内容宽度 = 视口 − 2 × 32px 页内边距（1440 -> 1376）。
        assert abs(box["width"] - VIEWPORT[0]) <= 0.5

    def test_computed_styles_use_frozen_tokens(self, page: Page, live_server_url: str) -> None:
        _open_single_home(page, live_server_url)
        styles = page.evaluate(
            """() => {
                const read = (selector, pseudo) => {
                    const el = document.querySelector(selector)
                    return el ? getComputedStyle(el, pseudo || null) : null
                }
                const title = read('#workbench-heading')
                const query = read('#mikan-candidate-query')
                const submit = read('#mikan-candidate-search-submit')
                const option = read('#anime-mode-single')
                const hero = read('.single-home-hero')
                return {
                    titleFontSize: title.fontSize,
                    titleLineHeight: title.lineHeight,
                    queryHeight: query.minHeight,
                    submitHeight: submit.minHeight,
                    submitWidth: submit.width,
                    submitBackground: submit.backgroundColor,
                    optionHeight: option.minHeight,
                    optionMinWidth: option.minWidth,
                    heroWidth: hero.width,
                    stepsColumns: read('.journey-steps').gridTemplateColumns,
                }
            }"""
        )
        assert styles["titleFontSize"] == "40px"
        assert styles["titleLineHeight"] == "48px"
        assert styles["queryHeight"] == "52px"
        assert styles["submitHeight"] == "52px"
        assert styles["submitWidth"] == "176px"
        # primary 深海蓝，不使用珊瑚红作为第二套主按钮。
        assert styles["submitBackground"] == "rgb(11, 42, 85)"
        assert styles["optionHeight"] == "52px"
        assert styles["optionMinWidth"] == "112px"
        assert styles["heroWidth"] == "720px"
        assert len(styles["stepsColumns"].split()) == 3

    def test_initial_state_renders_no_results_and_makes_no_candidate_call(
        self, page: Page, live_server_url: str
    ) -> None:
        requested = _open_single_home(page, live_server_url)
        for selector in FORBIDDEN_INITIAL_SELECTORS:
            assert page.locator(selector).count() == 0, selector
        assert page.locator(".single-home-hero .journey-steps").count() == 1
        assert page.locator(".single-home-hero #anime-mode-switch").count() == 1
        # 初始态不得发起候选搜索或任何 MiKan 外部请求。
        assert [url for url in requested if "/api/v1/mikan/" in url] == []
        assert [url for url in requested if "mikan.example" in url or ".invalid" in url] == []

    def test_search_keeps_the_hero_in_place_while_loading(self, page: Page, live_server_url: str) -> None:
        """点击搜索后英雄区与两个控件保持在原位，不因状态切换而卸载。"""
        _open_single_home(page, live_server_url)
        held: list[Any] = []
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route, request: held.append(route) if request.method == "POST" else route.continue_(),
        )
        before = {
            "query": page.locator("#mikan-candidate-query").bounding_box(),
            "submit": page.locator("#mikan-candidate-search-submit").bounding_box(),
        }
        page.fill("#mikan-candidate-query", "葬送的芙莉莲")
        # held route 语义：请求被保存后由测试显式 fulfill，handler 内不 sleep；
        # 测试侧用 expect_request + 可观察的 loading 状态等待，不做轮询或固定延时。
        with page.expect_request(
            lambda request: request.method == "POST" and "/api/v1/mikan/candidates" in request.url
        ):
            page.click("#mikan-candidate-search-submit")
        expect(page.locator("#mikan-candidate-search-submit")).to_have_attribute("aria-busy", "true")
        assert held, "candidate search was not held"
        after = {
            "query": page.locator("#mikan-candidate-query").bounding_box(),
            "submit": page.locator("#mikan-candidate-search-submit").bounding_box(),
        }
        assert page.locator(".single-home-hero").count() == 1
        for key in ("query", "submit"):
            assert abs(after[key]["width"] - before[key]["width"]) <= 1.0, key
            assert abs(after[key]["height"] - before[key]["height"]) <= 1.0, key
        expect(page.locator("#mikan-candidate-search-submit")).to_have_attribute("aria-busy", "true")
        held[0].fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "ok": True,
                    "result": {
                        "query": "葬送的芙莉莲",
                        "status": "EMPTY",
                        "parse_result": None,
                        "attempted_queries": [],
                        "candidates": [],
                        "error": None,
                    },
                },
                ensure_ascii=False,
            ),
        )

    @pytest.mark.parametrize(("width", "height"), [(1280, 720), (1440, 900), (1920, 1080)])
    def test_hero_holds_at_desktop_viewports(
        self, page: Page, live_server_url: str, width: int, height: int
    ) -> None:
        require_dist()
        page.set_viewport_size({"width": width, "height": height})
        install_shell_status_routes(page)
        page.goto(f"{live_server_url}/app/add")
        page.wait_for_selector(".single-home-hero", timeout=10_000)
        metrics = page.evaluate(
            """() => {
                const hero = document.querySelector('.single-home-hero').getBoundingClientRect()
                return {
                    viewportWidth: window.innerWidth,
                    bodyScrollWidth: document.body.scrollWidth,
                    heroWidth: hero.width,
                    heroLeft: hero.left,
                    submitRight: document.querySelector('#mikan-candidate-search-submit').getBoundingClientRect().right,
                }
            }"""
        )
        assert metrics["bodyScrollWidth"] <= metrics["viewportWidth"] + 1
        assert metrics["heroWidth"] <= metrics["viewportWidth"]
        assert metrics["heroLeft"] >= 0
        assert metrics["submitRight"] <= metrics["viewportWidth"] + 1

    def test_hero_reflows_under_two_hundred_percent_zoom(
        self, page: Page, live_server_url: str
    ) -> None:
        require_dist()
        page.set_viewport_size({"width": 720, "height": 450})
        install_shell_status_routes(page)
        page.goto(f"{live_server_url}/app/add")
        page.wait_for_selector(".single-home-hero", timeout=10_000)
        metrics = page.evaluate(
            """() => ({
                viewportWidth: window.innerWidth,
                bodyScrollWidth: document.body.scrollWidth,
                submitVisible: document.querySelector('#mikan-candidate-search-submit')
                    .getBoundingClientRect().width > 0,
                switchVisible: document.querySelector('#anime-mode-switch') !== null,
            })"""
        )
        assert metrics["bodyScrollWidth"] <= metrics["viewportWidth"] + 1
        assert metrics["submitVisible"] is True
        assert metrics["switchVisible"] is True

    def test_mode_switch_stays_keyboard_operable_with_reduced_motion(
        self, page: Page, live_server_url: str
    ) -> None:
        require_dist()
        prepare_canvas(page)
        page.emulate_media(reduced_motion="reduce")
        install_shell_status_routes(page)
        page.goto(f"{live_server_url}/app/add")
        page.wait_for_selector(".single-home-hero", timeout=10_000)
        page.fill("#mikan-candidate-query", "葬送的芙莉莲")
        page.locator("#anime-mode-single").focus()
        page.keyboard.press("ArrowRight")
        expect(page.locator("#anime-mode-batch")).to_have_attribute("aria-selected", "true")
        # 切换模式不清空任一输入。
        assert page.input_value("#batch-raw-input") == ""
        page.locator("#anime-mode-batch").focus()
        page.keyboard.press("ArrowLeft")
        expect(page.locator("#anime-mode-single")).to_have_attribute("aria-selected", "true")
        assert page.input_value("#mikan-candidate-query") == "葬送的芙莉莲"

    def test_selectors_are_resolvable(self, page: Page, live_server_url: str) -> None:
        _open_single_home(page, live_server_url)
        for name, selector in HOME_SELECTORS.items():
            assert page.locator(selector).count() == 1, name
        assert (page.viewport_size["width"], page.viewport_size["height"]) == VIEWPORT

    def test_mode_switch_preserves_each_mode_scene(self, page: Page, live_server_url: str) -> None:
        """AC3：切换模式不得清除任一模式的输入、结果或未保存现场。"""
        _open_single_home(page, live_server_url)
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
        page.fill("#mikan-candidate-query", "葬送的芙莉莲")
        page.click("#mikan-candidate-search-submit")
        expect(page.locator(".candidate-card")).to_have_count(1)

        page.click("#anime-mode-batch")
        page.fill("#batch-raw-input", "萌王S4")
        expect(page.locator(".candidate-card")).to_have_count(0)
        page.click("#anime-mode-single")
        # 单番的搜索结果在切回后仍然保留（未被切换清除）。
        expect(page.locator(".candidate-card")).to_have_count(1)
        # 回到输入态后，单番输入也没有被清除。
        page.click("#mikan-edit-search")
        expect(page.locator("#mikan-candidate-query")).to_have_value("葬送的芙莉莲")
        # 批量输入同样保留。
        page.click("#anime-mode-batch")
        assert page.input_value("#batch-raw-input") == "萌王S4"

    def test_hero_title_and_subtitle_keep_fixed_height(self, page: Page, live_server_url: str) -> None:
        """超长文案在固定高度的单行容器内截断，不推挤后续控件。"""
        _open_single_home(page, live_server_url)
        page.evaluate(
            """() => {
                document.querySelector('#workbench-heading').textContent = '超长标题'.repeat(80)
                document.querySelector('.single-home-subtitle').textContent = '超长说明文字'.repeat(120)
            }"""
        )
        boxes = page.evaluate(
            """() => {
                const read = (selector) => {
                    const rect = document.querySelector(selector).getBoundingClientRect()
                    return { y: rect.y, height: rect.height }
                }
                return {
                    title: read('#workbench-heading'),
                    subtitle: read('.single-home-subtitle'),
                    mode: read('#anime-mode-switch'),
                }
            }"""
        )
        assert abs(boxes["title"]["height"] - 48.0) <= TOLERANCE
        assert abs(boxes["subtitle"]["height"] - 24.0) <= TOLERANCE
        gap = boxes["mode"]["y"] - (boxes["subtitle"]["y"] + boxes["subtitle"]["height"])
        assert abs(gap - 24.0) <= TOLERANCE, gap


    def test_mode_switch_enter_and_space_work_end_to_end(
        self, page: Page, live_server_url: str
    ) -> None:
        """AC3：除方向键外，Enter 与空格也必须能在真实页面切换模式。"""
        _open_single_home(page, live_server_url)

        page.locator("#anime-mode-batch").focus()
        page.keyboard.press("Enter")
        expect(page.locator("#anime-mode-batch")).to_have_attribute("aria-selected", "true")
        expect(page.locator("#batch-parse-form")).to_be_visible()

        page.locator("#anime-mode-single").focus()
        page.keyboard.press(" ")
        expect(page.locator("#anime-mode-single")).to_have_attribute("aria-selected", "true")
        expect(page.locator(".single-home-hero")).to_be_visible()

    def test_batch_workbench_keeps_its_scene_across_mode_switch(
        self, page: Page, live_server_url: str
    ) -> None:
        """AC3：切回单番不得丢弃批量工作台的候选 / 筛选 / 勾选等未保存现场。"""
        from tests.browser.batch_visual_fixtures import (
            batch_candidate,
            batch_item,
            batch_parse_envelope,
        )

        _open_single_home(page, live_server_url)
        items = [
            batch_item(
                f"item-{index:02d}",
                title,
                status="FOUND",
                canonical_title=f"{title} 第一季",
                candidates=[
                    batch_candidate(
                        bangumi_id=f"9{index:03d}",
                        title=f"{title} 第一季",
                        season=1,
                        total_episodes=12,
                        source_query=title,
                    )
                ],
            )
            for index, title in enumerate(("甲", "乙"), start=1)
        ]
        page.route(
            "**/api/v1/batches/parse",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=batch_parse_envelope(items),
            ),
        )

        page.click("#anime-mode-batch")
        page.fill("#batch-raw-input", "甲\n乙")
        page.click("#batch-parse-submit")
        expect(page.locator(".batch-draft-card")).to_have_count(2)

        # 在批量工作台内部制造现场：筛选只留一项、展开当前查看项。
        page.fill("#batch-review-search", "甲")
        expect(page.locator(".batch-draft-card")).to_have_count(1)
        page.locator('.batch-draft-card[data-item-id="item-01"] .batch-card-expand').click()
        expect(page.locator("#batch-detail-pane")).to_be_visible()

        # 切回单番：批量区隐藏但不卸载。
        page.click("#anime-mode-single")
        expect(page.locator("#batch-parse-form")).not_to_be_visible()
        expect(page.locator(".single-home-hero")).to_be_visible()

        # 再切回批量：候选现场、筛选值与当前查看项都还在。
        page.click("#anime-mode-batch")
        expect(page.locator(".batch-draft-card")).to_have_count(1)
        assert page.input_value("#batch-review-search") == "甲"
        expect(page.locator("#batch-detail-pane")).to_be_visible()
