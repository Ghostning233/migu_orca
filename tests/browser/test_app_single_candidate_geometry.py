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
    def test_candidate_grid_matches_approved_desktop_geometry(
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
                summary: read('.candidate-search-summary-row'),
                grid: read('.candidate-collection-list'),
                first: read('.candidate-card:nth-child(1)'),
                second: read('.candidate-card:nth-child(2)'),
                third: read('.candidate-card:nth-child(3)'),
                poster: read('.candidate-card:nth-child(1) .candidate-poster'),
                edit: read('#mikan-edit-search'),
              }
            }"""
        )

        assert boxes["summary"] == {"x": 32, "y": 96, "width": 1376, "height": 44}
        assert boxes["grid"] == {"x": 32, "y": 160, "width": 1376, "height": 196}
        assert boxes["first"] == {"x": 32, "y": 160, "width": 448, "height": 196}
        assert boxes["second"] == {"x": 496, "y": 160, "width": 448, "height": 196}
        assert boxes["third"] == {"x": 960, "y": 160, "width": 448, "height": 196}
        assert boxes["poster"] == {"x": 48, "y": 176, "width": 120, "height": 160}
        assert boxes["edit"]["width"] == 176
        assert boxes["edit"]["height"] == 44

    def test_candidate_grid_reflows_to_two_columns_at_1280(
        self, page: Page, live_server_url: str
    ) -> None:
        page.set_viewport_size({"width": 1280, "height": 720})
        _open_candidates(page, live_server_url)

        metrics = page.evaluate(
            """() => {
              const grid = document.querySelector('.candidate-collection-list')
              const card = document.querySelector('.candidate-card')
              return {
                columns: getComputedStyle(grid).gridTemplateColumns.split(' ').length,
                cardWidth: card.getBoundingClientRect().width,
                bodyScrollWidth: document.body.scrollWidth,
              }
            }"""
        )
        assert metrics["columns"] == 2
        # Issue 109（AC4）：1280 属紧凑桌面档位，页内边距为 24px（原写死 32px），
        # 双列候选网格内容宽 = 1280 − 2×24，每列 = (1232 − --space-4 16) / 2。
        content_width = 1280 - 2 * content_padding_inline(1280)
        assert metrics["cardWidth"] == (content_width - 16) / 2
        assert metrics["bodyScrollWidth"] <= 1280

    def test_candidate_grid_stays_operable_at_two_hundred_percent_zoom(
        self, page: Page, live_server_url: str
    ) -> None:
        # A 720 CSS-pixel viewport models the 1440px desktop at 200% browser zoom.
        page.set_viewport_size({"width": 720, "height": 450})
        _open_candidates(page, live_server_url)

        metrics = page.evaluate(
            """() => {
              const grid = document.querySelector('.candidate-collection-list')
              return {
                columns: getComputedStyle(grid).gridTemplateColumns.split(' ').length,
                bodyScrollWidth: document.body.scrollWidth,
                cards: document.querySelectorAll('.candidate-card').length,
              }
            }"""
        )
        assert metrics["columns"] == 1
        assert metrics["cards"] == 3
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
