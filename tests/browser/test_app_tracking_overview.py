"""Issue 115：我的追番状态总览与固定高度详情的真实 Chromium 门禁。

覆盖：

- 列表与详情各自在固定可用高度内滚动；展开记录或操作不拉长整页，
  也不移动另一列的位置；导航与状态总览留在外侧；
- 总集数无可信服务端值时显示「未知」，不从资源数推断；
- 1280／1440／1920 桌面宽度下两列可达且无横向溢出。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import set_storage_preferences

pytestmark = pytest.mark.browser

REPO_ROOT_MARKER = "tracking-overview"


def _item(index: int, *, total_episodes: int | None = None) -> dict[str, Any]:
    return {
        "tracking_id": f"tracking-{index:02d}",
        "request_id": f"request-{index:02d}",
        "title": f"追番记录 {index:02d}",
        "season": 1,
        "subtitle_group": "喵萌奶茶屋",
        "poster_path": None,
        "status": "ACTIVE",
        "status_label": "追番中",
        "status_group": "ACTIVE",
        "available_actions": [],
        "valid_resource_count": 7,
        "updated_episode": None,
        "updated_episode_status": "NOT_IMPLEMENTED",
        "total_episodes": total_episodes,
        "revision": 1,
        "updated_at": "2026-09-13T00:00:00+00:00",
    }


def _detail(item: dict[str, Any], *, audit_events: int = 1) -> dict[str, Any]:
    return {
        **item,
        "origin": "single",
        "batch_id": None,
        "created_at": "2026-09-01T00:00:00+00:00",
        "last_synced_at": None,
        "safe_info": None,
        "current_operation": {
            "operation_id": "op-1",
            "state": "UNKNOWN",
            "operation": "SUBMIT",
            "attempt": 1,
        },
        "revalidation_issues": [],
        "external_mapping": {"match_reason": "标题", "enabled": True, "external_deleted": False},
        "audit_events": [
            {
                "action": "SUBMIT",
                "safe_message": f"第 {index} 条安全操作记录，不包含外部标识或凭据。",
                "created_at": "2026-09-13T00:00:00+00:00",
            }
            for index in range(1, audit_events + 1)
        ],
        "warnings": [],
    }


def _open(page: Page, live_server_url: str, storage_dir, items: list[dict[str, Any]], *, audits: int = 1) -> list[dict[str, Any]]:
    """Mock the tracking list/detail DTOs; the returned list is mutable so a
    test can reload the same page with a different number of records."""
    live_items = list(items)

    def handler(route: Any, request: Any) -> None:
        if request.method != "GET" or "/api/v1/tracking/items" not in request.url:
            route.continue_()
            return
        for item in live_items:
            if f"/api/v1/tracking/items/{item['tracking_id']}" in request.url:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {"ok": True, "result": _detail(item, audit_events=audits)},
                        ensure_ascii=False,
                    ),
                )
                return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "ok": True,
                    "result": {
                        "items": live_items,
                        "summary": {
                            "total": len(live_items),
                            "pending": 0,
                            "processing": 0,
                            "active": len(live_items),
                            "inactive": 0,
                            "needs_attention": 0,
                            "added_to_download": 0,
                            "unreadable": 0,
                        },
                        "warnings": [],
                    },
                },
                ensure_ascii=False,
            ),
        )

    page.route("**/api/v1/tracking/items*", handler)
    page.route("**/api/v1/tracking/items/**", handler)
    set_storage_preferences(page, storage_dir)
    page.goto(f"{live_server_url}/app/tracking")
    page.wait_for_selector(f"#{REPO_ROOT_MARKER}")
    return live_items


def _wait_for_loaded_detail(page: Page) -> None:
    """Wait for the loaded safe detail, not just the loading container.

    `.tracking-inspector-content` renders immediately with「正在读取安全详情…」,
    so geometry assertions must wait for a marker that only exists after the
    detail response has been rendered.
    """
    expect(page.locator(".tracking-inspector-summary")).to_contain_text("总集数")

def test_long_list_scrolls_inside_while_overview_and_inspector_stay_put(
    page: Page, live_server_url: str, storage_dir
) -> None:
    items = [_item(index) for index in range(24)]
    page.set_viewport_size({"width": 1440, "height": 900})
    live_items = _open(page, live_server_url, storage_dir, items)
    expect(page.locator(".tracking-list-item")).to_have_count(24)
    first_page_height = page.evaluate("() => document.documentElement.scrollHeight")

    # 再加到 40 条：列表到达固定可用高度后整页不再增长，只在栏内滚动。
    live_items[:] = [_item(index) for index in range(40)]
    page.reload()
    page.wait_for_selector(f"#{REPO_ROOT_MARKER}")
    expect(page.locator(".tracking-list-item")).to_have_count(40)
    grown_page_height = page.evaluate("() => document.documentElement.scrollHeight")
    assert grown_page_height == first_page_height

    page.locator(".tracking-list-item").first.click()
    _wait_for_loaded_detail(page)

    geometry = page.evaluate(
        """() => {
          const list = document.querySelector('#tracking-list-container')
          const inspector = document.querySelector('.tracking-inspector')
          const overview = document.querySelector('.tracking-status-overview')
          const nav = document.querySelector('.app-header')
          return {
            listScrollable: list.scrollHeight > list.clientHeight,
            listHeight: Math.round(list.getBoundingClientRect().height),
            listMaxHeight: Math.round(parseFloat(getComputedStyle(list).maxHeight)),
            listOverflow: getComputedStyle(list).overflowY,
            listOverscroll: getComputedStyle(list).overscrollBehaviorY,
            inspectorScrollable: inspector.scrollHeight > inspector.clientHeight,
            inspectorOverflow: getComputedStyle(inspector).overflowY,
            inspectorTop: inspector.getBoundingClientRect().top,
            overviewTop: overview.getBoundingClientRect().top,
            navTop: nav.getBoundingClientRect().top,
            documentHeight: document.documentElement.scrollHeight,
            viewportHeight: window.innerHeight,
          }
        }"""
    )
    assert geometry["listScrollable"] is True
    assert geometry["listOverflow"] == "auto"
    assert geometry["listOverscroll"] == "contain"
    assert geometry["inspectorOverflow"] == "auto"
    # 列表到达固定可用高度后不再增长；选中详情也不改变整页高度。
    assert geometry["documentHeight"] == first_page_height
    assert geometry["listHeight"] == geometry["listMaxHeight"]
    assert geometry["overviewTop"] >= geometry["navTop"]
    assert geometry["overviewTop"] < geometry["viewportHeight"]

    before = page.evaluate(
        """() => ({
          inspectorTop: document.querySelector('.tracking-inspector').getBoundingClientRect().top,
          overviewTop: document.querySelector('.tracking-status-overview').getBoundingClientRect().top,
        })"""
    )
    page.evaluate(
        """() => {
          const list = document.querySelector('#tracking-list-container')
          list.scrollTop = list.scrollHeight
          list.dispatchEvent(new WheelEvent('wheel', { deltaY: 900, bubbles: true }))
        }"""
    )
    after = page.evaluate(
        """() => ({
          inspectorTop: document.querySelector('.tracking-inspector').getBoundingClientRect().top,
          overviewTop: document.querySelector('.tracking-status-overview').getBoundingClientRect().top,
        })"""
    )
    # 列表内部滚到底不移动另一列，也不移动状态总览。
    assert after["inspectorTop"] == before["inspectorTop"]
    assert after["overviewTop"] == before["overviewTop"]


def test_long_detail_scrolls_inside_without_moving_the_list(
    page: Page, live_server_url: str, storage_dir
) -> None:
    items = [_item(index) for index in range(6)]
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, live_server_url, storage_dir, items, audits=1)

    page.locator(".tracking-list-item").first.click()
    _wait_for_loaded_detail(page)
    short_detail_height = page.evaluate("() => document.documentElement.scrollHeight")

    # 同一详情换成 40 条安全记录：整页高度不变，详情在栏内滚动。
    _open(page, live_server_url, storage_dir, items, audits=40)
    page.locator(".tracking-list-item").first.click()
    _wait_for_loaded_detail(page)

    metrics = page.evaluate(
        """() => {
          const list = document.querySelector('#tracking-list-container')
          const inspector = document.querySelector('.tracking-inspector')
          list.scrollTop = 30
          const listBefore = list.scrollTop
          inspector.scrollTop = inspector.scrollHeight
          return {
            listBefore,
            listAfter: list.scrollTop,
            inspectorScrollable: inspector.scrollHeight > inspector.clientHeight,
            inspectorScrolled: inspector.scrollTop > 0,
            documentHeight: document.documentElement.scrollHeight,
          }
        }"""
    )
    assert metrics["inspectorScrollable"] is True
    assert metrics["inspectorScrolled"] is True
    # 详情内部滚动不影响列表位置，也不拉长整页。
    assert metrics["listAfter"] == metrics["listBefore"]
    assert metrics["documentHeight"] == short_detail_height


def test_unknown_episode_counts_never_infer_from_resources(
    page: Page, live_server_url: str, storage_dir
) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, live_server_url, storage_dir, [_item(1, total_episodes=None)])

    page.locator(".tracking-list-item").first.click()
    _wait_for_loaded_detail(page)
    rows = page.evaluate(
        """() => {
          const pairs = {}
          document.querySelectorAll('.tracking-inspector-summary div').forEach((row) => {
            const dt = row.querySelector('dt')
            const dd = row.querySelector('dd')
            if (dt && dd) pairs[dt.textContent.trim()] = dd.textContent.trim()
          })
          return pairs
        }"""
    )
    # 无可信服务端值：总集数显示「未知」；「已更新集数」仍是待开发占位（冻结规则）。
    assert rows["总集数"] == "未知"
    assert rows["已更新集数"] == "待开发"
    # 有效资源数 7 只作为资源计数呈现，绝不被当成集数。
    assert rows["有效资源"] == "7"


@pytest.mark.parametrize("width", [1280, 1920])
def test_desktop_widths_keep_both_columns_reachable_without_overflow(
    page: Page, live_server_url: str, storage_dir, width: int
) -> None:
    items = [_item(index) for index in range(12)]
    page.set_viewport_size({"width": width, "height": 900})
    _open(page, live_server_url, storage_dir, items)
    page.locator(".tracking-list-item").first.click()
    _wait_for_loaded_detail(page)

    metrics = page.evaluate(
        """() => {
          const list = document.querySelector('#tracking-list-container')
          const inspector = document.querySelector('.tracking-inspector')
          return {
            bodyScrollWidth: document.body.scrollWidth,
            viewportWidth: window.innerWidth,
            listOverflow: getComputedStyle(list).overflowY,
            inspectorOverflow: getComputedStyle(inspector).overflowY,
            listVisible: list.getBoundingClientRect().width > 0,
            inspectorVisible: inspector.getBoundingClientRect().width > 0,
          }
        }"""
    )
    assert metrics["listVisible"] is True
    assert metrics["inspectorVisible"] is True
    assert metrics["listOverflow"] == "auto"
    assert metrics["inspectorOverflow"] == "auto"
    assert metrics["bodyScrollWidth"] <= metrics["viewportWidth"] + 1
