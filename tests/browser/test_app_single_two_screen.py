"""Issue 110：单番搜索两屏旅程的真实 Chromium 门禁。

覆盖设计图 01/02/06 的已确认方向：

- 搜索首屏与候选工作台是同一页面的上下两屏，成功后自动进入第二屏并把键盘焦点
  移到结果标题；
- 「返回搜索首屏」只滚动与聚焦，不清空下方未保存的候选现场；
- 容器自身滚动带轻柔吸附，模块内部滚动独立且 `overscroll-behavior: contain`，
  滚到边界不会带动整页切屏；
- 失败与无候选都留在首屏就地恢复，直连救援入口默认收起。
"""

from __future__ import annotations

import json

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import set_storage_preferences
from tests.browser.screen_support import wait_for_screen_scroll
from tests.browser.test_app_workbench import (
    _candidate,
    _candidate_result_json,
    _goto_workbench,
)

pytestmark = pytest.mark.browser

def _mock_candidates(page: Page, count: int = 2) -> None:
    candidates = [
        _candidate(
            bangumi_id=str(2000 + index),
            title=f"候选 {index + 1}",
            mikan_url=f"https://mikan.example/Home/Bangumi/{2000 + index}",
            total_episodes=12,
        )
        for index in range(count)
    ]
    page.route(
        "**/api/v1/mikan/candidates",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=_candidate_result_json("芙莉莲", candidates),
        ),
    )


def _open(page: Page, live_server_url: str, storage_dir) -> None:
    set_storage_preferences(page, storage_dir)
    page.set_viewport_size({"width": 1440, "height": 900})
    _goto_workbench(page, live_server_url)


def _search(page: Page, query: str = "芙莉莲") -> None:
    page.fill("#mikan-candidate-query", query)
    page.click("#mikan-candidate-search-submit")


def test_success_enters_the_second_screen_and_focuses_the_result_heading(
    page: Page, live_server_url: str, storage_dir
) -> None:
    _mock_candidates(page, 2)
    _open(page, live_server_url, storage_dir)
    _search(page)

    expect(page.locator(".candidate-card")).to_have_count(2)
    # 成功后自动滚到第二屏，并把键盘焦点移到结果标题。
    expect(page.locator("#candidate-search-heading")).to_be_focused()
    wait_for_screen_scroll(page)
    geometry = page.evaluate(
        """() => {
          const screens = document.querySelector('.add-anime-screens')
          const heading = document.querySelector('#candidate-search-heading')
          return {
            scrollTop: screens.scrollTop,
            containerTop: screens.getBoundingClientRect().top,
            headingTop: heading.getBoundingClientRect().top,
            snapType: getComputedStyle(screens).scrollSnapType,
          }
        }"""
    )
    assert geometry["scrollTop"] > 0
    assert geometry["headingTop"] >= geometry["containerTop"] - 2
    # Chromium 把 `y proximity` 归一化回默认的 `y`；两者都表示纵向轻柔吸附。
    assert geometry["snapType"].split(" ")[0] == "y"


def test_return_to_search_keeps_the_unsaved_candidate_work(
    page: Page, live_server_url: str, storage_dir
) -> None:
    _mock_candidates(page, 3)
    _open(page, live_server_url, storage_dir)
    _search(page)
    expect(page.locator(".candidate-card")).to_have_count(3)
    wait_for_screen_scroll(page)

    page.click("#mikan-back-to-search")
    # 回到首屏：输入聚焦、候选与输入内容都保留。
    expect(page.locator("#mikan-candidate-query")).to_be_focused()
    expect(page.locator("#mikan-candidate-query")).to_have_value("芙莉莲")
    expect(page.locator(".candidate-card")).to_have_count(3)
    page.wait_for_function(
        "() => document.querySelector('.add-anime-screens').scrollTop < 10"
    )


def test_inner_module_scroll_never_switches_screens(
    page: Page, live_server_url: str, storage_dir
) -> None:
    _mock_candidates(page, 4)
    _open(page, live_server_url, storage_dir)
    _search(page)
    expect(page.locator(".candidate-card")).to_have_count(4)
    wait_for_screen_scroll(page)

    styles = page.evaluate(
        """() => {
          const wrapper = document.querySelector(
            '.candidate-workbench-screen .candidate-list-wrapper')
          return {
            overscroll: getComputedStyle(wrapper).overscrollBehaviorY,
            overflowY: getComputedStyle(wrapper).overflowY,
          }
        }"""
    )
    # 内部滚动容器截断滚动链：滚到边界不会把整页切回第一屏。
    assert styles["overscroll"] == "contain"
    assert styles["overflowY"] == "auto"

    before = page.evaluate("() => document.querySelector('.add-anime-screens').scrollTop")
    page.evaluate(
        """() => {
          const wrapper = document.querySelector(
            '.candidate-workbench-screen .candidate-list-wrapper')
          wrapper.scrollTop = wrapper.scrollHeight
          wrapper.dispatchEvent(new WheelEvent('wheel', { deltaY: 600, bubbles: true }))
        }"""
    )
    after = page.evaluate("() => document.querySelector('.add-anime-screens').scrollTop")
    assert after == before, f"inner scroll changed the outer screen position: {before} -> {after}"


def test_failure_and_empty_stay_on_the_first_screen_with_in_place_recovery(
    page: Page, live_server_url: str, storage_dir
) -> None:
    page.route(
        "**/api/v1/mikan/candidates",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {"ok": False, "error_type": "mikan_timeout", "error_message": "内部错误"},
                ensure_ascii=False,
            ),
        ),
    )
    _open(page, live_server_url, storage_dir)
    _search(page)

    # 失败留在首屏：第二屏不出现，输入保留，重试按钮就地可用。
    expect(page.locator("#candidate-search-heading")).to_have_count(0)
    expect(page.locator("#mikan-candidate-query")).to_have_value("芙莉莲")
    expect(page.locator("#mikan-search-feedback-action")).to_contain_text("重试搜索")
    # 失败就地恢复但不抢焦点：用户仍停在原控件上（Stage 42 无障碍保证）。
    assert page.evaluate(
        "() => document.activeElement?.id ?? ''"
    ) != "mikan-search-feedback-action"
    assert "mikan_timeout" not in page.locator("body").inner_text()

    # 无候选：同样留在首屏，提示核对关键词，直连救援默认收起。
    page.route(
        "**/api/v1/mikan/candidates",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=_candidate_result_json("芙莉莲", []),
        ),
    )
    page.click("#mikan-search-feedback-action")
    expect(page.locator("#mikan-candidate-search-result")).to_contain_text("核对番剧名称或季度")
    expect(page.locator("#candidate-search-heading")).to_have_count(0)
    expect(page.locator("#mikan-search-feedback-action")).to_contain_text("重新搜索")
    expect(page.locator("#mikan-fallback-enabled")).to_be_visible()
    expect(page.locator("#mikan-fallback-form")).to_be_hidden()
