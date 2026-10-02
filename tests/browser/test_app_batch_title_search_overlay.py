"""#158：标题搜索浮层的独立关闭、背景与工具精简（真实 Chromium）。

要点：

- 浮层里只有一个具读屏名称的关闭按钮（真实点击，不用 Escape 代替）；
- 关闭按钮／Escape／再次点击放大镜都能收起并恢复放大镜焦点；
- 关键词与筛选结果保留、图标显示搜索活动状态；删空关键词恢复标题搜索范围；
- 浮层是独立悬浮背景（内边距/圆角/阴影），输入框本身不描边；
- 打开/关闭不推挤筛选行、卡片与底栏：关键锚点偏差 ≤2 CSS px；
- 已删除的「清除条件」「下一异常」及其占位不在 DOM 里，工具栏没有右侧预留空白。
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.screen_support import wait_for_screen_scroll
from tests.browser.test_app_batch_workbench import (
    _compact_items,
    _goto_batch,
    _route_parse,
)
from tests.browser.visual_support import require_dist

pytestmark = pytest.mark.browser

TOLERANCE = 2.0

_ANCHORS_SCRIPT = """
() => {
  const read = (selector) => {
    const element = document.querySelector(selector)
    if (!element) return null
    const rect = element.getBoundingClientRect()
    return { x: rect.x, y: rect.y, width: rect.width, height: rect.height, right: rect.right }
  }
  const screen = document.querySelector('.batch-workbench-screen')
  return {
    scrollY: window.scrollY,
    screenTop: screen ? screen.getBoundingClientRect().top : 0,
    screenScrollTop: screen ? screen.scrollTop : 0,
    listScrollTop: (() => {
      const list = document.querySelector('.batch-card-grid-wrapper')
      return list ? list.scrollTop : 0
    })(),
    filters: read('.batch-review-filters'),
    toggle: read('#batch-review-search-toggle'),
    status: read('#batch-review-status'),
    toggleSwitch: read('#batch-review-needs-processing'),
    list: read('.batch-card-grid-wrapper'),
    firstCard: read('.batch-draft-card'),
    toolbar: read('#batch-accept-toolbar'),
  }
}
"""

_POPOVER_SCRIPT = """
() => {
  const popover = document.querySelector('#batch-review-search-popover')
  if (!popover) return null
  const input = popover.querySelector('#batch-review-search')
  const close = popover.querySelector('#batch-review-search-close')
  const popoverStyle = getComputedStyle(popover)
  const inputStyle = getComputedStyle(input)
  return {
    background: popoverStyle.backgroundColor,
    borderWidth: popoverStyle.borderTopWidth,
    radius: popoverStyle.borderTopLeftRadius,
    boxShadow: popoverStyle.boxShadow,
    paddingTop: popoverStyle.paddingTop,
    position: popoverStyle.position,
    zIndex: popoverStyle.zIndex,
    inputBorderWidth: inputStyle.borderTopWidth,
    inputBackground: inputStyle.backgroundColor,
    closeLabel: close ? close.getAttribute('aria-label') : null,
    closeVisible: Boolean(close && close.getBoundingClientRect().width > 0),
    clearCount: popover.querySelectorAll('#batch-review-search-clear').length,
    closeCount: popover.querySelectorAll('#batch-review-search-close').length,
  }
}
"""


def _open_batch(page: Page, live_server_url: str, count: int = 3) -> None:
    _route_parse(page, _compact_items(count))
    _goto_batch(page, live_server_url)
    page.fill("#batch-raw-input", "\n".join(f"番剧{index:02d}" for index in range(count)))
    page.click("#batch-parse-submit")
    expect(page.locator(".batch-draft-card")).to_have_count(count)
    # 等切屏滚动稳定，再取锚点：动画中间态不是布局结果。
    wait_for_screen_scroll(page)


def _assert_anchors_stable(before: dict[str, Any], after: dict[str, Any]) -> None:
    """布局稳定性：用工作台屏的内容坐标比较，把「聚焦输入导致容器滚动」与「浮层推挤布局」分开。"""
    def content_y(metrics: dict[str, Any], name: str) -> float:
        return (
            float(metrics[name]["y"])
            - float(metrics.get("screenTop", 0))
            + float(metrics.get("screenScrollTop", 0))
        )

    for name in ("filters", "toggle", "status", "toggleSwitch", "list", "toolbar"):
        first, second = before.get(name), after.get(name)
        assert first is not None and second is not None, name
        assert abs(content_y(before, name) - content_y(after, name)) <= TOLERANCE, (name, before, after)
        for field in ("x", "width", "height"):
            assert abs(first[field] - second[field]) <= TOLERANCE, (name, field, first, second)
    # 卡片不被浮层推挤：相对左侧列表的内容坐标比较（列表自身滚动不算推挤）。
    first_card, second_card = before.get("firstCard"), after.get("firstCard")
    if first_card and second_card:
        def card_content_y(metrics: dict[str, Any]) -> float:
            return (
                float(metrics["firstCard"]["y"])
                - float(metrics["list"]["y"])
                + float(metrics.get("listScrollTop", 0))
            )

        assert abs(card_content_y(before) - card_content_y(after)) <= TOLERANCE, (before["firstCard"], after["firstCard"])
        for field in ("x", "width", "height"):
            assert abs(first_card[field] - second_card[field]) <= TOLERANCE, (field, first_card, second_card)


def test_close_button_really_closes_and_restores_focus(page: Page, live_server_url: str) -> None:
    require_dist()
    _open_batch(page, live_server_url)
    before = page.evaluate(_ANCHORS_SCRIPT)

    page.click("#batch-review-search-toggle")
    page.wait_for_selector("#batch-review-search")
    opened = page.evaluate(_ANCHORS_SCRIPT)
    _assert_anchors_stable(before, opened)

    popover = page.evaluate(_POPOVER_SCRIPT)
    assert popover is not None
    # 独立悬浮背景：有背景色/描边/圆角/阴影/内边距；输入框本身不描边。
    assert popover["background"] == "rgb(255, 255, 255)", popover
    assert popover["borderWidth"] == "1px", popover
    assert popover["radius"] != "0px", popover
    assert popover["boxShadow"] != "none", popover
    assert popover["paddingTop"] != "0px", popover
    assert popover["position"] == "absolute", popover
    assert popover["inputBorderWidth"] == "0px", popover
    assert popover["inputBackground"] == "rgba(0, 0, 0, 0)", popover
    # 唯一的关闭入口；自定义清空按钮不存在。
    assert popover["closeCount"] == 1, popover
    assert popover["clearCount"] == 0, popover
    assert popover["closeLabel"] == "关闭标题搜索", popover
    assert popover["closeVisible"] is True, popover

    page.fill("#batch-review-search", "番剧00")
    expect(page.locator(".batch-draft-card")).to_have_count(1)

    # 真实点击关闭按钮。
    page.click("#batch-review-search-close")
    expect(page.locator("#batch-review-search-popover")).to_have_count(0)
    closed = page.evaluate(_ANCHORS_SCRIPT)
    _assert_anchors_stable(before, closed)
    # 焦点回到放大镜；关键词与筛选结果保留，图标显示搜索活动状态。
    assert page.evaluate("() => document.activeElement && document.activeElement.id") == "batch-review-search-toggle"
    expect(page.locator(".batch-draft-card")).to_have_count(1)
    expect(page.locator("#batch-review-search-toggle")).to_have_class(
        re.compile(r"is-active")
    )
    expect(page.locator("#batch-review-search-toggle")).to_have_attribute("aria-expanded", "false")

    # 重开继续编辑；手动删空关键词恢复标题搜索范围。
    page.click("#batch-review-search-toggle")
    page.wait_for_selector("#batch-review-search")
    assert page.input_value("#batch-review-search") == "番剧00"
    page.fill("#batch-review-search", "")
    expect(page.locator(".batch-draft-card")).to_have_count(3)
    expect(page.locator("#batch-review-search-toggle")).not_to_have_class(
        re.compile(r"is-active")
    )


def test_escape_and_second_magnifier_click_also_close(page: Page, live_server_url: str) -> None:
    _open_batch(page, live_server_url)
    page.click("#batch-review-search-toggle")
    page.wait_for_selector("#batch-review-search")
    page.fill("#batch-review-search", "番剧01")
    expect(page.locator(".batch-draft-card")).to_have_count(1)

    page.keyboard.press("Escape")
    expect(page.locator("#batch-review-search-popover")).to_have_count(0)
    assert page.evaluate("() => document.activeElement && document.activeElement.id") == "batch-review-search-toggle"
    expect(page.locator(".batch-draft-card")).to_have_count(1)

    # 再次点击放大镜也能收起（活动标记保留）。
    page.click("#batch-review-search-toggle")
    page.wait_for_selector("#batch-review-search")
    page.click("#batch-review-search-toggle")
    expect(page.locator("#batch-review-search-popover")).to_have_count(0)
    expect(page.locator("#batch-review-search-toggle")).to_have_class(
        re.compile(r"is-active")
    )


def test_toolbar_has_no_reserved_space_for_removed_entries(page: Page, live_server_url: str) -> None:
    _open_batch(page, live_server_url)
    expect(page.locator("#batch-review-clear")).to_have_count(0)
    expect(page.locator("#batch-next-exception")).to_have_count(0)
    expect(page.locator(".batch-review-navigation")).not_to_contain_text("无异常时不可用")
    # 筛选行只剩四个真实控件：没有被删除按钮留下的空占位，也没有 auto 边距预留的右侧空白。
    controls = page.evaluate(
        """() => Array.from(document.querySelectorAll('.batch-review-filters > *'))
          .filter((child) => child.getBoundingClientRect().width > 0)
          .map((child) => ({
            id: child.id || child.className,
            position: getComputedStyle(child).position,
            marginLeft: getComputedStyle(child).marginLeft,
          }))"""
    )
    assert len(controls) in (4, 5), controls
    assert all(item["marginLeft"] in ("0px", "0") for item in controls), controls
    assert not any("clear" in str(item["id"]) or "exception" in str(item["id"]) for item in controls), controls


@pytest.mark.parametrize(
    ("width", "height", "count"),
    [
        (1280, 800, 1),
        (1920, 1080, 12),
        (1440, 900, 36),
        (720, 450, 12),  # 末项 = 1440 桌面 200% 缩放
    ],
)
def test_overlay_does_not_cover_the_task_area_at_desktop_viewports(
    page: Page, live_server_url: str, width: int, height: int, count: int
) -> None:
    require_dist()
    page.set_viewport_size({"width": width, "height": height})
    _open_batch(page, live_server_url, count=count)
    before = page.evaluate(_ANCHORS_SCRIPT)
    page.click("#batch-review-search-toggle")
    page.wait_for_selector("#batch-review-search")
    after = page.evaluate(_ANCHORS_SCRIPT)
    _assert_anchors_stable(before, after)
    geometry = page.evaluate(
        """() => {
          const popover = document.querySelector('#batch-review-search-popover').getBoundingClientRect()
          const toolbar = document.querySelector('#batch-accept-toolbar').getBoundingClientRect()
          return {
            popoverBottom: popover.bottom,
            toolbarTop: toolbar.top,
            toolbarBottom: toolbar.bottom,
            bodyScrollWidth: document.body.scrollWidth,
            viewportWidth: window.innerWidth,
          }
        }"""
    )
    # 浮层悬浮在列表上方（不推挤任何布局），但绝不遮住固定底栏；底栏可滚动到达。
    assert geometry["popoverBottom"] <= geometry["toolbarTop"] + 1, geometry
    assert geometry["bodyScrollWidth"] <= geometry["viewportWidth"] + 1, geometry
    page.locator("#batch-accept-toolbar").scroll_into_view_if_needed()
    expect(page.locator("#batch-accept-toolbar")).to_be_in_viewport()
    # 关闭后末卡仍可达；浮层不改变卡片与底栏几何。
    page.click("#batch-review-search-close")
    expect(page.locator(".batch-draft-card").last).to_be_visible()
    closed = page.evaluate(_ANCHORS_SCRIPT)
    _assert_anchors_stable(before, closed)
