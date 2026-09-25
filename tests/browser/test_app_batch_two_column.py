"""#143/#148：批量搜索与工作台切屏、双栏独立滚动的真实 Chromium 门禁。

父规格 #139 已确认的目标，经 #145 于 2026-09-25 修订：

- 批量搜索的加载／失败仍留在搜索首屏；整批搜索完成后完整进入工作台，不停在两屏
  中间；模块外空白区（包括主内容内边距与宽屏两侧留白）可驱动整屏切换，外层滚动条
  永久隐藏；返回按钮平滑返回且不清除未保存审核现场；
- 左栏「批量条目卡」列表与右栏「当前详情／批量合集候选卡」各有独立内部滚动能力，
  但按 #145 目标隐藏可见滚动条（`scrollbar-width: none` 且不占滚动条槽）；
  鼠标在任一栏内滚到顶或到底后继续滚，仍不切屏；两栏滚动互不干扰；
- 顶部标题与底部操作栏可见，底部不遮挡任一栏末项；1／12／36 部可遍历和操作。

本文件对旧实现（容器内部滚动、`.add-anime-screens` 位置判定）是红测。
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import set_storage_preferences
from tests.browser.screen_support import (
    screen_metrics,
    wait_for_hero_top,
    wait_for_screen_scroll,
    wait_for_scroll_idle,
    wheel_at,
)
from tests.browser.test_app_batch_workbench import (
    _batch_item,
    _candidate,
    _compact_items,
    _goto_batch,
    _preview_request,
    _route_parse,
)

pytestmark = pytest.mark.browser


def _parse(page: Page, live_server_url: str, items: list[dict], storage_dir) -> None:
    _route_parse(page, items)
    set_storage_preferences(page, storage_dir)
    _goto_batch(page, live_server_url)
    page.set_viewport_size({"width": 1440, "height": 900})
    page.fill("#batch-raw-input", "\n".join(str(item["raw_title"]) for item in items))
    page.click("#batch-parse-submit")
    expect(page.locator(".batch-draft-card")).to_have_count(len(items))
    # 等切屏滚动稳定，避免把动画中间态当成布局结果。
    wait_for_screen_scroll(page)


def _draft_items(count: int) -> list[dict]:
    return [
        _batch_item(
            f"item-{index:02d}",
            f"番剧{index:02d}",
            status="DRAFT",
            canonical_title=f"番剧 {index} 第一季",
            preview_request=_preview_request(f"番剧{index}", f"req-143-{index:02d}"),
        )
        for index in range(count)
    ]


def _candidate_items(count: int) -> list[dict]:
    return [
        _batch_item(
            f"item-{index:02d}",
            f"番剧{index:02d}",
            candidates=[
                _candidate(
                    bangumi_id=str(100 + index),
                    title=f"番剧{index:02d} 合集",
                    mikan_url=f"https://mikan.example/Home/Bangumi/{100 + index}",
                )
            ],
        )
        for index in range(count)
    ]


def test_batch_workbench_is_a_second_screen_with_internal_column_scroll(
    page: Page, live_server_url: str, storage_dir
) -> None:
    _parse(page, live_server_url, _candidate_items(12), storage_dir)

    # 工作台屏已经对齐到顶栏之下，外层滚动条不可见但仍可滚动。
    metrics = page.evaluate(
        """() => {
          const list = document.querySelector('.batch-card-grid-wrapper')
          const detail = document.querySelector('#batch-detail-pane')
          // 滚动条槽 = 盒宽 − 内容宽 − 左右边框；隐藏滚动条时应为 0。
          const gutter = (element) => {
            const style = getComputedStyle(element)
            const borders = (parseFloat(style.borderLeftWidth) || 0) + (parseFloat(style.borderRightWidth) || 0)
            return element.offsetWidth - element.clientWidth - borders
          }
          return {
            scrollY: window.scrollY,
            listScrollable: list.scrollHeight > list.clientHeight,
            listOverflow: getComputedStyle(list).overflowY,
            listOverscroll: getComputedStyle(list).overscrollBehaviorY,
            listOwner: list.dataset.screenScroll,
            listScrollbar: getComputedStyle(list).scrollbarWidth,
            listGutter: gutter(list),
            detailOverflow: getComputedStyle(detail).overflowY,
            detailOverscroll: getComputedStyle(detail).overscrollBehaviorY,
            detailOwner: detail.dataset.screenScroll,
            detailScrollbar: getComputedStyle(detail).scrollbarWidth,
            detailGutter: gutter(detail),
            scrollbarWidth: getComputedStyle(document.documentElement).scrollbarWidth,
            documentHeight: document.documentElement.scrollHeight,
            viewportHeight: window.innerHeight,
          }
        }"""
    )
    assert metrics["scrollY"] > 100
    # #148：双栏保留独立内部滚动能力并继续声明为内部滚动所有者（滚轮不参与切屏），
    # 但可见滚动条被隐藏，且不占用滚动条槽（内容宽度不因滚动条出现/消失而抖动）。
    assert metrics["listScrollable"] is True
    assert metrics["listOverflow"] == "auto"
    assert metrics["listOverscroll"] == "contain"
    assert metrics["listOwner"] == "inner"
    assert metrics["listScrollbar"] == "none"
    assert metrics["listGutter"] == 0
    assert metrics["detailOverflow"] == "auto"
    assert metrics["detailOverscroll"] == "contain"
    assert metrics["detailOwner"] == "inner"
    assert metrics["detailScrollbar"] == "none"
    assert metrics["detailGutter"] == 0
    assert metrics["scrollbarWidth"] == "none"
    # 文档高度固定为两屏：长列表不撑长整页。
    assert metrics["documentHeight"] <= 2 * metrics["viewportHeight"] + 1

    # 固定操作栏在工作台屏内可见。
    expect(page.locator("#batch-accept-toolbar")).to_be_in_viewport()


def test_inner_scroll_boundary_never_switches_back_to_the_search_screen(
    page: Page, live_server_url: str, storage_dir
) -> None:
    _parse(page, live_server_url, _compact_items(36), storage_dir)

    before = page.evaluate("() => window.scrollY")
    boundary = page.evaluate(
        """() => {
          const list = document.querySelector('.batch-card-grid-wrapper')
          list.scrollTop = list.scrollHeight
          const detail = document.querySelector('#batch-detail-pane')
          detail.scrollTop = detail.scrollHeight
          return {
            listAtBottom: list.scrollTop + list.clientHeight >= list.scrollHeight - 1,
            detailAtBottom: detail.scrollTop + detail.clientHeight >= detail.scrollHeight - 1,
          }
        }"""
    )
    assert boundary["listAtBottom"] is True
    assert boundary["detailAtBottom"] is True

    # 栏内滚到边界后继续滚动：真实滚轮事件也不切屏。
    wheel_at(page, 300, 400, 900)
    wheel_at(page, 1180, 400, 900)
    wait_for_scroll_idle(page)
    after = page.evaluate("() => window.scrollY")
    assert after == before, f"模块内部滚动切回了搜索首屏：{before} -> {after}"


def test_module_outside_whitespace_switches_back_to_the_search_screen(
    page: Page, live_server_url: str, storage_dir
) -> None:
    _parse(page, live_server_url, _candidate_items(12), storage_dir)

    # 模块外空白区（面板内边距带）向上滚动：完整回到搜索首屏，不清除现场。
    wheel_at(page, 60, 260, -400)
    wait_for_hero_top(page)
    assert page.evaluate("() => window.scrollY") <= 2
    expect(page.locator(".batch-draft-card")).to_have_count(12)
    expect(page.locator("#batch-raw-input")).to_have_count(1)


def test_detail_pane_scrolls_without_moving_the_list(
    page: Page, live_server_url: str, storage_dir
) -> None:
    _parse(page, live_server_url, _draft_items(3), storage_dir)
    # #145/#150：新的批量草案右栏在 1440×900 下通常刚好装得下，不溢出是正常状态；
    # 这里用 200% 缩放强制它超过可用高度，验证右栏仍是独立的内部滚动所有者。
    page.evaluate("() => { document.documentElement.style.zoom = '2' }")

    before = page.evaluate(
        """() => {
          const list = document.querySelector('.batch-card-grid-wrapper')
          list.scrollTop = 40
          return list.scrollTop
        }"""
    )
    metrics = page.evaluate(
        """() => {
          const detail = document.querySelector('#batch-detail-pane')
          const list = document.querySelector('.batch-card-grid-wrapper')
          detail.scrollTop = detail.scrollHeight
          return {
            detailScrollable: detail.scrollHeight > detail.clientHeight,
            detailScrollTop: detail.scrollTop,
            listScrollTop: list.scrollTop,
          }
        }"""
    )
    assert metrics["detailScrollable"] is True
    assert metrics["detailScrollTop"] > 0
    # 详情滚动不影响左列位置。
    assert metrics["listScrollTop"] == before


@pytest.mark.parametrize("count", [1, 12, 36])
def test_boundary_batch_sizes_keep_the_fixed_toolbar_and_last_card_reachable(
    page: Page, live_server_url: str, storage_dir, count: int
) -> None:
    _parse(page, live_server_url, _compact_items(count), storage_dir)

    toolbar = page.locator("#batch-accept-toolbar")
    expect(toolbar).to_be_in_viewport()
    # 工作台标题留在屏内顶部且可见。
    expect(page.locator("#panel-section-批量工作台")).to_be_visible()

    geometry = page.evaluate(
        """() => {
          const list = document.querySelector('.batch-card-grid-wrapper')
          const cards = document.querySelectorAll('.batch-draft-card')
          const last = cards[cards.length - 1]
          list.scrollTop = list.scrollHeight
          const listBox = list.getBoundingClientRect()
          const lastBox = last.getBoundingClientRect()
          const toolbar = document.querySelector('#batch-accept-toolbar').getBoundingClientRect()
          return {
            scrollable: list.scrollHeight > list.clientHeight,
            lastBottom: lastBox.bottom,
            listBottom: listBox.bottom,
            toolbarTop: toolbar.top,
            reserved: parseFloat(getComputedStyle(list).paddingBottom) || 0,
          }
        }"""
    )
    if count > 3:
        assert geometry["scrollable"] is True
    # 滚到底后末卡完整落在列表可视区内，并停在为固定操作栏预留的空间之上。
    assert geometry["lastBottom"] <= geometry["listBottom"] + 1
    assert geometry["lastBottom"] <= geometry["listBottom"] - geometry["reserved"] + 1, geometry
    assert geometry["lastBottom"] <= geometry["toolbarTop"] + 1, geometry


def test_long_list_does_not_grow_the_document(
    page: Page, live_server_url: str, storage_dir
) -> None:
    _parse(page, live_server_url, _compact_items(3), storage_dir)
    short_height = page.evaluate("() => document.documentElement.scrollHeight")

    _parse(page, live_server_url, _compact_items(36), storage_dir)
    long_height = page.evaluate("() => document.documentElement.scrollHeight")
    # 36 部只让左栏内部滚动变长，不让整页增长。
    assert abs(long_height - short_height) <= 2, (short_height, long_height)


def test_hidden_scrollbars_keep_keyboard_navigation_inside_the_columns(
    page: Page, live_server_url: str, storage_dir
) -> None:
    """#148 AC3：滚动条不可见，但键盘仍能到达两栏全部内容且停在栏内。"""
    _parse(page, live_server_url, _draft_items(36), storage_dir)
    before = page.evaluate(
        """() => ({
            listScrollTop: document.querySelector('.batch-card-grid-wrapper').scrollTop,
            scrollY: window.scrollY,
        })"""
    )
    assert before["scrollY"] > 100

    # 左栏：卡片自身可聚焦，方向键在可见卡片间移动并让左栏内部滚动。
    page.locator(".batch-draft-card").first.focus()
    for _ in range(20):
        page.keyboard.press("ArrowDown")
    # 卡片焦点移动触发的是平滑滚动；连续按键会互相取消动画，因此等它真正停稳再断言。
    wait_for_scroll_idle(page)
    left = page.evaluate(
        """() => {
          const list = document.querySelector('.batch-card-grid-wrapper')
          const active = document.activeElement
          return {
            focusedIsCard: active.classList.contains('batch-draft-card'),
            listScrollTop: list.scrollTop,
            scrollY: window.scrollY,
          }
        }"""
    )
    assert left["focusedIsCard"] is True
    assert left["listScrollTop"] > before["listScrollTop"], left
    # 仍在工作台屏内：方向键浏览卡片不会把页面带回搜索首屏。
    assert left["scrollY"] >= before["scrollY"] - 1, left

    # 右栏：200% 缩放让长草案真实溢出，Tab 前进时由右栏自身滚动承载。
    page.evaluate("() => { document.documentElement.style.zoom = '2' }")
    pane = page.locator("#batch-detail-pane")
    assert page.evaluate(
        """() => {
          const pane = document.querySelector('#batch-detail-pane')
          return pane.scrollHeight > pane.clientHeight
        }"""
    ) is True, "200% 缩放下右栏应当溢出并保留内部滚动"
    page.locator("#batch-detail-pane .base-button, #batch-detail-pane select, #batch-detail-pane input").first.focus()
    for _ in range(24):
        if page.evaluate("() => document.querySelector('#batch-detail-pane').scrollTop") > 0:
            break
        page.keyboard.press("Tab")
    right = page.evaluate(
        """() => {
          const pane = document.querySelector('#batch-detail-pane')
          return {
            scrollTop: pane.scrollTop,
            activeInside: pane.contains(document.activeElement),
          }
        }"""
    )
    assert right["activeInside"] is True
    assert right["scrollTop"] > 0, right
    assert pane.is_visible()


def test_batch_loading_and_failure_stay_on_the_search_screen(
    page: Page, live_server_url: str, storage_dir
) -> None:
    _route_parse(page, [])
    set_storage_preferences(page, storage_dir)
    _goto_batch(page, live_server_url)
    page.set_viewport_size({"width": 1440, "height": 900})
    # 只输入非法内容：工作台不会出现，滚轮也不切屏。
    page.fill("#batch-raw-input", "   ")
    assert page.evaluate("() => window.scrollY") == 0
    wheel_at(page, 720, 500, 400)
    wait_for_scroll_idle(page)
    assert page.evaluate("() => window.scrollY") == 0
    # 工作台屏尚未切换（v-show 隐藏），因此没有可切屏的第二屏。
    metrics = screen_metrics(page)
    assert metrics["workbench"] is None or page.locator(".batch-workbench-screen").is_visible() is False
