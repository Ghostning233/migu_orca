"""Issue 113：批量双栏工作台的真实 Chromium 门禁。

覆盖：

- 批量工作台是第二屏；左列列表与右列详情各自拥有可见内部滚动条，
  列表/草案变长不让整页或工作台屏随之增长；
- 模块内部滚轮滚到边界不会切回搜索首屏，只有屏外空白区或返回操作才切屏；
- 1／12／36 部都保持固定操作栏可见，且 36 部可滚到末卡仍不被操作栏遮挡。
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import set_storage_preferences
from tests.browser.screen_support import wait_for_screen_scroll
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
            preview_request=_preview_request(f"番剧{index}", f"req-113-{index:02d}"),
        )
        for index in range(count)
    ]


def test_batch_workbench_is_a_second_screen_with_internal_column_scroll(
    page: Page, live_server_url: str, storage_dir
) -> None:
    items = [
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
        for index in range(12)
    ]
    _parse(page, live_server_url, items, storage_dir)

    # 工作台屏已经在视口内，整页高度仍等于视口（滚动发生在容器与栏内）。
    metrics = page.evaluate(
        """() => {
          const screens = document.querySelector('.add-anime-screens')
          const list = document.querySelector('.batch-card-grid-wrapper')
          const detail = document.querySelector('.batch-detail-pane')
          return {
            scrollTop: screens.scrollTop,
            listScrollable: list.scrollHeight > list.clientHeight,
            listOverflow: getComputedStyle(list).overflowY,
            listOverscroll: getComputedStyle(list).overscrollBehaviorY,
            detailOverflow: getComputedStyle(detail).overflowY,
            detailOverscroll: getComputedStyle(detail).overscrollBehaviorY,
            documentHeight: document.documentElement.scrollHeight,
            viewportHeight: window.innerHeight,
          }
        }"""
    )
    assert metrics["scrollTop"] > 100
    assert metrics["listScrollable"] is True
    assert metrics["listOverflow"] == "auto"
    assert metrics["listOverscroll"] == "contain"
    assert metrics["detailOverflow"] == "auto"
    assert metrics["detailOverscroll"] == "contain"
    # 长列表不撑长整页：文档高度始终是一屏。
    assert metrics["documentHeight"] <= metrics["viewportHeight"] + 1

    # 固定操作栏在屏内可见，且不随列表滚动。
    expect(page.locator("#batch-accept-toolbar")).to_be_in_viewport()


def test_inner_scroll_boundary_never_switches_back_to_the_search_screen(
    page: Page, live_server_url: str, storage_dir
) -> None:
    _parse(page, live_server_url, _compact_items(36), storage_dir)

    before = page.evaluate("() => document.querySelector('.add-anime-screens').scrollTop")
    boundary = page.evaluate(
        """() => {
          const list = document.querySelector('.batch-card-grid-wrapper')
          list.scrollTop = list.scrollHeight
          list.dispatchEvent(new WheelEvent('wheel', { deltaY: 900, bubbles: true }))
          const detail = document.querySelector('.batch-detail-pane')
          detail.scrollTop = detail.scrollHeight
          detail.dispatchEvent(new WheelEvent('wheel', { deltaY: 900, bubbles: true }))
          return { listAtBottom: list.scrollTop + list.clientHeight >= list.scrollHeight - 1 }
        }"""
    )
    assert boundary["listAtBottom"] is True
    after = page.evaluate("() => document.querySelector('.add-anime-screens').scrollTop")
    assert after == before, f"模块内部滚动切回了搜索首屏：{before} -> {after}"


def test_detail_pane_scrolls_without_moving_the_list(
    page: Page, live_server_url: str, storage_dir
) -> None:
    items = _draft_items(3)
    _parse(page, live_server_url, items, storage_dir)

    before = page.evaluate(
        """() => {
          const list = document.querySelector('.batch-card-grid-wrapper')
          list.scrollTop = 40
          return list.scrollTop
        }"""
    )
    metrics = page.evaluate(
        """() => {
          const detail = document.querySelector('.batch-detail-pane')
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


@pytest.mark.parametrize("count", [1, 36])
def test_boundary_batch_sizes_keep_the_fixed_toolbar_and_last_card_reachable(
    page: Page, live_server_url: str, storage_dir, count: int
) -> None:
    _parse(page, live_server_url, _compact_items(count), storage_dir)

    toolbar = page.locator("#batch-accept-toolbar")
    expect(toolbar).to_be_in_viewport()

    geometry = page.evaluate(
        """() => {
          const list = document.querySelector('.batch-card-grid-wrapper')
          const cards = document.querySelectorAll('.batch-draft-card')
          const last = cards[cards.length - 1]
          list.scrollTop = list.scrollHeight
          const listBox = list.getBoundingClientRect()
          const lastBox = last.getBoundingClientRect()
          return {
            scrollable: list.scrollHeight > list.clientHeight,
            lastBottom: lastBox.bottom,
            listBottom: listBox.bottom,
            reserved: parseFloat(getComputedStyle(list).paddingBottom) || 0,
          }
        }"""
    )
    if count > 3:
        assert geometry["scrollable"] is True
    # 滚到底后末卡完整落在列表可视区内，并停在为固定操作栏预留的空间之上。
    assert geometry["lastBottom"] <= geometry["listBottom"] + 1
    assert geometry["lastBottom"] <= geometry["listBottom"] - geometry["reserved"] + 1, geometry
