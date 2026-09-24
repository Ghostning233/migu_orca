from __future__ import annotations

import json
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.test_app_workbench import (
    _candidate,
    _candidate_result_json,
    _goto_workbench,
    _preview_request,
)
from tests.browser.visual_manifest import content_padding_inline

pytestmark = pytest.mark.browser


def _three_candidates() -> str:
    return _candidate_result_json(
        "芙莉莲",
        [
            _candidate(
                bangumi_id="2353",
                title="葬送的芙莉莲",
                mikan_url="https://mikan.example/Home/Bangumi/2353",
                total_episodes=28,
                poster_url="/api/v1/mikan/posters/2353",
            ),
            _candidate(
                bangumi_id="3072",
                title="葬送的芙莉莲 第二季",
                mikan_url="https://mikan.example/Home/Bangumi/3072",
                total_episodes=24,
            ),
            _candidate(
                bangumi_id="4096",
                title="葬送的芙莉莲 特别篇",
                mikan_url="https://mikan.example/Home/Bangumi/4096",
                total_episodes=2,
            ),
        ],
    )


def _open_candidates(page: Page, live_server_url: str) -> None:
    page.route(
        "**/api/v1/mikan/candidates",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=_three_candidates(),
        ),
    )
    _goto_workbench(page, live_server_url)
    page.fill("#mikan-candidate-query", "芙莉莲")
    page.click("#mikan-candidate-search-submit")
    expect(page.locator(".candidate-card")).to_have_count(3)


class TestSingleCandidateGeometry:
    def test_candidate_screen_matches_approved_desktop_geometry(
        self, page: Page, live_server_url: str
    ) -> None:
        page.set_viewport_size({"width": 1440, "height": 900})
        _open_candidates(page, live_server_url)

        boxes = page.evaluate(
            """() => {
              const read = (selector) => {
                const rect = document.querySelector(selector).getBoundingClientRect()
                return {x: rect.x, y: rect.y, width: rect.width, height: rect.height}
              }
              return {
                screen: read('.candidate-workbench-screen'),
                heading: read('#candidate-search-heading'),
                first: read('.candidate-card:nth-child(1)'),
                second: read('.candidate-card:nth-child(2)'),
                third: read('.candidate-card:nth-child(3)'),
                poster: read('.candidate-card:nth-child(1) .candidate-poster'),
                back: read('#mikan-back-to-search'),
              }
            }"""
        )

        # Issue 110：候选工作台是第二屏，与页面内容容器同宽同轴。
        assert boxes["screen"]["x"] == 32
        assert boxes["screen"]["width"] == 1376
        # 结果标题在第二屏内水平居中。
        assert abs((boxes["heading"]["x"] + boxes["heading"]["width"] / 2) - 720) <= 2
        # 1～4 项同排：卡宽 = (1376 − 3×--space-4) / 4 = 332，行内容居中。
        assert boxes["first"]["width"] == 332
        assert boxes["second"]["width"] == 332
        assert boxes["third"]["width"] == 332
        assert boxes["first"]["y"] == boxes["second"]["y"] == boxes["third"]["y"]
        assert boxes["second"]["x"] - boxes["first"]["x"] == 348
        assert boxes["first"]["x"] - boxes["screen"]["x"] == 174
        assert (
            boxes["screen"]["x"]
            + boxes["screen"]["width"]
            - (boxes["third"]["x"] + boxes["third"]["width"])
            == 174
        )
        # 封面按 16:9 撑满卡片内容宽（332 − 2×15 内边距 − 2×1 边框 = 300）。
        assert boxes["poster"]["width"] == 300
        assert abs(boxes["poster"]["height"] - 300 * 9 / 16) <= 0.5
        # 返回搜索首屏是标准 44px 控件。
        assert boxes["back"]["height"] == 44

    def test_candidate_row_keeps_one_centered_row_at_1280(
        self, page: Page, live_server_url: str
    ) -> None:
        page.set_viewport_size({"width": 1280, "height": 720})
        _open_candidates(page, live_server_url)

        metrics = page.evaluate(
            """() => {
              const cards = Array.from(document.querySelectorAll('.candidate-card')).map(
                (el) => el.getBoundingClientRect())
              return {
                cardWidths: cards.map((box) => box.width),
                cardTops: cards.map((box) => box.top),
                firstLeft: cards[0].x,
                lastRight: cards[cards.length - 1].x + cards[cards.length - 1].width,
                bodyScrollWidth: document.body.scrollWidth,
              }
            }"""
        )
        # Issue 110：1280 档内容宽 1232，三张 332px 卡片仍在同一行居中。
        assert metrics["cardWidths"] == [332, 332, 332]
        assert len(set(metrics["cardTops"])) == 1
        expected_left = content_padding_inline(1280) + (
            1280 - 2 * content_padding_inline(1280) - (3 * 332 + 2 * 16)
        ) / 2
        assert abs(metrics["firstLeft"] - expected_left) <= 0.5
        assert abs(expected_left - (1280 - metrics["lastRight"])) <= 0.5
        assert metrics["bodyScrollWidth"] <= 1280

    def test_candidate_row_stays_operable_at_two_hundred_percent_zoom(
        self, page: Page, live_server_url: str
    ) -> None:
        # A 720 CSS-pixel viewport models the 1440px desktop at 200% browser zoom.
        page.set_viewport_size({"width": 720, "height": 450})
        _open_candidates(page, live_server_url)

        metrics = page.evaluate(
            """() => {
              const cards = Array.from(document.querySelectorAll('.candidate-card')).map(
                (el) => el.getBoundingClientRect())
              return {
                widths: cards.map((box) => box.width),
                bodyScrollWidth: document.body.scrollWidth,
                cards: cards.length,
              }
            }"""
        )
        # Issue 110：极窄视口下卡片保持可用下限并换行，不横向溢出。
        assert metrics["cards"] == 3
        assert all(width >= 240 for width in metrics["widths"])
        assert metrics["bodyScrollWidth"] <= 720

    def test_long_title_keeps_full_accessible_name_and_hides_canary(
        self, page: Page, live_server_url: str
    ) -> None:
        long_title = "葬送的芙莉莲 第二季 超长合集标题用于验证两行截断"
        canary = "us364-candidate-context-canary"
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_candidate_result_json(
                    "芙莉莲",
                    [
                        _candidate(
                            bangumi_id="2353",
                            title=long_title,
                            mikan_url="https://mikan.example/Home/Bangumi/2353",
                            candidate_context=canary,
                            season_evidence={
                                "status": "NEEDS_CONFIRMATION",
                                "season": 2,
                                "requires_review": True,
                            },
                        )
                    ],
                ),
            ),
        )
        _goto_workbench(page, live_server_url)
        page.fill("#mikan-candidate-query", "芙莉莲")
        page.click("#mikan-candidate-search-submit")

        title = page.locator(".candidate-title")
        expect(title).to_have_attribute("title", long_title)
        expect(page.locator(".candidate-select")).to_have_attribute("aria-label", f"选择此合集：{long_title}")
        assert title.evaluate("el => el.getBoundingClientRect().height") <= 48
        expect(page.locator(".candidate-season-confirmation")).to_be_visible()
        surface = page.evaluate(
            "() => ({body: document.body.innerText, url: location.href, local: JSON.stringify(localStorage), session: JSON.stringify(sessionStorage), history: JSON.stringify(history.state)})"
        )
        assert all(canary not in value for value in surface.values())

    def test_reduced_motion_loading_has_textual_state_without_spinner(
        self, page: Page, live_server_url: str
    ) -> None:
        page.emulate_media(reduced_motion="reduce")
        held: list[Any] = []

        def hold_generation(route: Any, request: Any) -> None:
            if request.method == "POST":
                held.append(route)
            else:
                route.continue_()

        page.route("**/api/v1/requests", hold_generation)
        _open_candidates(page, live_server_url)
        page.locator(".candidate-select").first.click()
        expect(page.locator(".candidate-select").first).to_have_attribute("aria-busy", "true")
        expect(page.locator(".candidate-generating-status")).to_contain_text("正在生成订阅草案")
        assert page.locator(".candidate-select .base-button-spinner").evaluate(
            "el => getComputedStyle(el).display"
        ) == "none"

    def test_held_generation_marks_only_clicked_candidate_and_enters_review(
        self, page: Page, live_server_url: str
    ) -> None:
        held: list[Any] = []

        def hold_generation(route: Any, request: Any) -> None:
            if request.method != "POST":
                route.continue_()
                return
            held.append(route)

        page.route("**/api/v1/requests", hold_generation)
        _open_candidates(page, live_server_url)

        cards = page.locator(".candidate-card")
        cards.nth(0).locator(".candidate-select").click()
        expect(cards.nth(0).locator(".candidate-select")).to_have_attribute("aria-busy", "true")
        expect(cards.nth(1).locator(".candidate-select")).to_be_disabled()
        expect(cards.nth(2).locator(".candidate-select")).to_be_disabled()
        expect(cards.nth(1).locator(".candidate-select")).not_to_have_attribute("aria-busy", "true")
        expect(cards.nth(2).locator(".candidate-select")).not_to_have_attribute("aria-busy", "true")
        assert page.locator(".candidate-valid-resource-count").count() == 0
        assert page.locator(".candidate-excluded-resource-count").count() == 0
        expect(page.locator(".candidate-generating-status")).to_have_count(1)

        assert len(held) == 1
        held[0].fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "ok": True,
                    "result": {
                        "draft_id": "draft-us364",
                        "draft_revision": 1,
                        "request": _preview_request("葬送的芙莉莲", "draft-us364"),
                    },
                },
                ensure_ascii=False,
            ),
        )
        expect(page.locator("#single-anime-review-step")).to_be_visible()
        expect(page.locator(".candidate-card")).to_have_count(0)
