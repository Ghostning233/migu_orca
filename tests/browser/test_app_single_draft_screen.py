"""Issue 111：单番草案审核、重新选择合集与第二屏内部滚动的真实 Chromium 门禁。

覆盖：

- 选择候选后，同一第二屏从候选切换为草案审核，不新开第三屏；
- 「重新选择合集」返回该屏的候选状态并保留搜索结果；
- 草案资源数只在真实草案阶段出现，候选阶段不展示；
- 长草案只在第二屏内容面板内滚动，不撑长整页，也不带动整页切屏。
"""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import preview_result_json, set_storage_preferences
from tests.browser.test_app_workbench import (
    _candidate,
    _candidate_result_json,
    _goto_workbench,
    _preview_request,
    _register_generation_capture,
)

pytestmark = pytest.mark.browser

SCREENS = ".add-anime-screens"


def _mock_candidates(page: Page) -> None:
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
                        title="葬送的芙莉莲",
                        mikan_url="https://mikan.example/Home/Bangumi/2353",
                        total_episodes=28,
                    )
                ],
            ),
        ),
    )


def _open_draft(
    page: Page, live_server_url: str, storage_dir, *, viewport: tuple[int, int] = (1440, 900)
) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []
    _register_generation_capture(
        page, captured, body=preview_result_json(_preview_request("葬送的芙莉莲", "req-111"))
    )
    _mock_candidates(page)
    set_storage_preferences(page, storage_dir)
    page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
    _goto_workbench(page, live_server_url)
    page.fill("#mikan-candidate-query", "芙莉莲")
    page.click("#mikan-candidate-search-submit")
    expect(page.locator(".candidate-card")).to_have_count(1)
    page.locator(".candidate-card button:has-text('选择此合集')").click()
    page.wait_for_selector("#single-anime-review-step", timeout=10_000)
    return captured


def test_candidate_selection_switches_the_second_screen_to_draft_review(
    page: Page, live_server_url: str, storage_dir
) -> None:
    _open_draft(page, live_server_url, storage_dir)

    # 同一第二屏切换为草案审核：候选卡消失，未跳转到新的路由或第三屏。
    expect(page.locator(".candidate-card")).to_have_count(0)
    expect(page.locator("#single-anime-review-step")).to_be_visible()
    assert page.url.endswith("/app/add")
    # 第一屏仍在：输入与模式切换没有被草案步骤替换。
    expect(page.locator("#mikan-candidate-search-form")).to_have_count(1)
    expect(page.locator("#candidate-search-heading")).to_have_count(0)

    # 草案阶段才出现资源数；候选阶段从不展示。
    detail = page.locator("#request-detail-container")
    expect(detail).to_contain_text("有效资源")
    expect(detail.locator("#single-review-save-button")).to_be_enabled()


def test_reselect_collection_returns_to_the_candidate_screen(
    page: Page, live_server_url: str, storage_dir
) -> None:
    _open_draft(page, live_server_url, storage_dir)

    page.click("#single-review-back-candidates")
    dialog = page.locator(".confirm-dialog")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("重新选择合集")
    # 丢弃草案是危险操作，确认按钮使用 danger 样式。
    dialog.get_by_role("button", name="确认离开").click()

    # 回到同一第二屏的候选状态，搜索结果保留，仍未离开 /app/add。
    expect(page.locator("#candidate-search-heading")).to_be_visible()
    expect(page.locator(".candidate-card")).to_have_count(1)
    expect(page.locator("#single-anime-review-step")).to_have_count(0)
    assert page.url.endswith("/app/add")


def test_long_draft_scrolls_inside_the_second_screen(
    page: Page, live_server_url: str, storage_dir
) -> None:
    _open_draft(page, live_server_url, storage_dir, viewport=(1440, 620))
    page.wait_for_function(
        "() => document.querySelector('.add-anime-screens').scrollTop > 100"
    )

    styles = page.evaluate(
        """() => {
          const panel = document.querySelector('.draft-scroll-panel')
          const screens = document.querySelector('.add-anime-screens')
          return {
            overflowY: getComputedStyle(panel).overflowY,
            overscroll: getComputedStyle(panel).overscrollBehaviorY,
            scrollHeight: panel.scrollHeight,
            clientHeight: panel.clientHeight,
            outerTop: screens.scrollTop,
            documentHeight: document.documentElement.scrollHeight,
            viewportHeight: window.innerHeight,
          }
        }"""
    )
    assert styles["overflowY"] == "auto"
    assert styles["overscroll"] == "contain"
    # 内容高于第二屏可用高度时，滚动发生在内容面板内部。
    assert styles["scrollHeight"] > styles["clientHeight"]
    # 整页高度不随草案增长（滚动容器自身固定为一屏）。
    assert styles["documentHeight"] <= styles["viewportHeight"] + 1

    before = styles["outerTop"]
    page.evaluate(
        """() => {
          const panel = document.querySelector('.draft-scroll-panel')
          panel.scrollTop = panel.scrollHeight
          panel.dispatchEvent(new WheelEvent('wheel', { deltaY: 800, bubbles: true }))
        }"""
    )
    after = page.evaluate("() => document.querySelector('.add-anime-screens').scrollTop")
    assert after == before, f"draft inner scroll moved the outer screen: {before} -> {after}"
