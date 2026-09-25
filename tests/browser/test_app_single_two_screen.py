"""#140：单番搜索首屏与候选工作台整屏切换的真实 Chromium 门禁。

父规格 #139 已确认的目标：

- 搜索中、失败与无候选留在搜索首屏；只有拿到候选才自动、平滑地进入工作台顶部，
  不停在两屏中间；从首屏一次向下手势完整进入工作台；
- 外层滚动属于文档：`#app-main` 内容、内边距与 1920 宽屏两侧留白都能驱动切屏，
  顶部一级导航保持可见，外层滚动条永久隐藏但滚轮／触控板／键盘仍可滚动；
- 工作台顶部向上滚动完整返回首屏；「返回搜索首屏」平滑定位结束后才聚焦输入，
  不因焦点瞬移，也不清空未保存现场；减少动态效果时即时定位但焦点与内容仍正确；
- 这套滚动模式只作用于「添加番剧」。

本文件是可对旧实现（容器内部滚动、可见滚动条、点击即聚焦）变红的定向用例。
"""

from __future__ import annotations

import json

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import set_storage_preferences
from tests.browser.screen_support import (
    screen_metrics,
    wait_for_hero_top,
    wait_for_screen_scroll,
    wheel_at,
)
from tests.browser.test_app_workbench import (
    _candidate,
    _candidate_result_json,
    _goto_workbench,
)


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


def _open(
    page: Page, live_server_url: str, storage_dir, *, viewport: tuple[int, int] = (1440, 900)
) -> None:
    set_storage_preferences(page, storage_dir)
    page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
    _goto_workbench(page, live_server_url)


def _search(page: Page, query: str = "芙莉莲") -> None:
    page.fill("#mikan-candidate-query", query)
    page.click("#mikan-candidate-search-submit")


def test_success_enters_the_workbench_screen_and_focuses_the_result_heading(
    page: Page, live_server_url: str, storage_dir
) -> None:
    _mock_candidates(page, 2)
    _open(page, live_server_url, storage_dir)
    _search(page)

    expect(page.locator(".candidate-card")).to_have_count(2)
    # 成功后自动滚到第二屏，并把键盘焦点移到结果标题。
    expect(page.locator("#candidate-search-heading")).to_be_focused()
    wait_for_screen_scroll(page)
    metrics = screen_metrics(page)
    assert metrics["workbench"] is not None and metrics["hero"] is not None
    # 停在两屏分界处不算通过：滚动位置必须等于工作台顶部。
    assert abs(float(metrics["scrollY"]) - float(metrics["workbench"])) <= 2, metrics


@pytest.mark.parametrize(
    ("viewport", "point"),
    [
        ((1440, 900), (720, 500)),  # 内容区
        ((1440, 900), (12, 500)),  # 主内容内边距
        ((1920, 1080), (60, 600)),  # 1920 宽屏两侧留白
    ],
)
def test_whole_viewport_drives_the_screen_switch(
    page: Page,
    live_server_url: str,
    storage_dir,
    viewport: tuple[int, int],
    point: tuple[int, int],
) -> None:
    _mock_candidates(page, 2)
    _open(page, live_server_url, storage_dir, viewport=viewport)
    _search(page)
    wait_for_screen_scroll(page)
    entered = screen_metrics(page)
    assert abs(float(entered["scrollY"]) - float(entered["workbench"])) <= 2

    # 回到首屏后，在指定坐标发一次向下手势：内容、内边距与宽屏留白都要能驱动切屏。
    page.click("#mikan-back-to-search")
    wait_for_hero_top(page)
    wheel_at(page, point[0], point[1], 240)
    wait_for_screen_scroll(page)
    metrics = screen_metrics(page)
    assert abs(float(metrics["scrollY"]) - float(metrics["workbench"])) <= 2, (viewport, point, metrics)


def test_outer_scrollbar_is_invisible_while_scrolling_and_navigation_stays_visible(
    page: Page, live_server_url: str, storage_dir
) -> None:
    _mock_candidates(page, 4)
    _open(page, live_server_url, storage_dir)
    _search(page)
    wait_for_screen_scroll(page)

    surface = page.evaluate(
        """() => {
          const root = getComputedStyle(document.documentElement)
          const header = document.querySelector('.app-header').getBoundingClientRect()
          const nav = document.querySelector('.top-nav').getBoundingClientRect()
          return {
            scrollbarWidth: root.scrollbarWidth,
            gutter: window.innerWidth - document.documentElement.clientWidth,
            scrollY: window.scrollY,
            headerTop: header.top,
            headerHeight: header.height,
            navTop: nav.top,
            navBottom: nav.bottom,
            viewportHeight: window.innerHeight,
          }
        }"""
    )
    # 外层滚动条任何鼠标状态下都不可见，但滚动确实发生了。
    assert surface["scrollbarWidth"] == "none"
    assert surface["gutter"] == 0
    assert surface["scrollY"] > 100
    # 顶部一级导航保持可见（吸附在顶栏内），不被内容盖住。
    assert surface["headerTop"] == 0
    assert surface["headerHeight"] > 0
    assert 0 <= surface["navTop"] < surface["navBottom"] <= surface["viewportHeight"]


def test_keyboard_can_reach_the_workbench_without_a_visible_scrollbar(
    page: Page, live_server_url: str, storage_dir
) -> None:
    _mock_candidates(page, 4)
    _open(page, live_server_url, storage_dir)
    _search(page)
    wait_for_screen_scroll(page)
    page.click("#mikan-back-to-search")
    wait_for_hero_top(page)

    # 键盘滚动不依赖可见滚动条：焦点在结果标题等非表单元素上时仍可到达两屏内容。
    page.locator("#candidate-search-heading").focus()
    page.keyboard.press("PageDown")
    page.wait_for_function("() => window.scrollY > 100")
    assert page.locator(".candidate-card").first.is_visible()
    page.keyboard.press("Home")
    wait_for_hero_top(page)


def test_return_button_scrolls_first_then_focuses_the_input(
    page: Page, live_server_url: str, storage_dir
) -> None:
    _mock_candidates(page, 3)
    _open(page, live_server_url, storage_dir)
    _search(page)
    expect(page.locator(".candidate-card")).to_have_count(3)
    wait_for_screen_scroll(page)

    page.click("#mikan-back-to-search")
    # 平滑定位结束后才聚焦输入：焦点落到输入时文档已经在首屏顶部，不会瞬移。
    page.wait_for_function("() => document.activeElement?.id === 'mikan-candidate-query'")
    assert page.evaluate("() => window.scrollY") <= 2
    expect(page.locator("#mikan-candidate-query")).to_have_value("芙莉莲")
    # 不清空下方未保存的候选现场。
    expect(page.locator(".candidate-card")).to_have_count(3)


def test_workbench_top_scrolls_back_to_the_search_screen(
    page: Page, live_server_url: str, storage_dir
) -> None:
    _mock_candidates(page, 2)
    _open(page, live_server_url, storage_dir)
    _search(page)
    wait_for_screen_scroll(page)

    # 工作台顶部向上滚动：下一次手势完整返回首屏，不停在分界处。
    wheel_at(page, 720, 400, -240)
    wait_for_hero_top(page)
    metrics = screen_metrics(page)
    assert float(metrics["scrollY"]) <= 2


def test_reduced_motion_positions_immediately_with_correct_focus(
    page: Page, live_server_url: str, storage_dir
) -> None:
    page.emulate_media(reduced_motion="reduce")
    _mock_candidates(page, 2)
    _open(page, live_server_url, storage_dir)
    _search(page)

    expect(page.locator(".candidate-card")).to_have_count(2)
    expect(page.locator("#candidate-search-heading")).to_be_focused()
    assert page.evaluate("() => window.scrollY") > 100

    page.click("#mikan-back-to-search")
    expect(page.locator("#mikan-candidate-query")).to_be_focused()
    assert page.evaluate("() => window.scrollY") <= 2
    expect(page.locator(".candidate-card")).to_have_count(2)


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
    assert page.evaluate("() => document.activeElement?.id ?? ''") != "mikan-search-feedback-action"
    assert "mikan_timeout" not in page.locator("body").inner_text()
    # 没有第二屏时，任何滚动都不应把页面切到不存在的工作台。
    wheel_at(page, 720, 500, 600)
    page.wait_for_timeout(150)
    assert page.evaluate("() => window.scrollY") <= 2

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


def test_add_anime_scroll_mode_does_not_leak_to_other_pages(
    page: Page, live_server_url: str, storage_dir
) -> None:
    _mock_candidates(page, 2)
    _open(page, live_server_url, storage_dir)
    _search(page)
    wait_for_screen_scroll(page)
    assert (
        page.evaluate("() => document.documentElement.classList.contains('add-anime-scroll')")
        is True
    )

    page.goto(f"{live_server_url}/app/settings")
    page.wait_for_selector("#app-main", timeout=5000)
    assert (
        page.evaluate("() => document.documentElement.classList.contains('add-anime-scroll')")
        is False
    )
    assert (
        page.evaluate("() => getComputedStyle(document.documentElement).scrollbarWidth") != "none"
    )
    assert (
        page.evaluate("() => getComputedStyle(document.querySelector('.app-header')).position")
        != "sticky"
    )
