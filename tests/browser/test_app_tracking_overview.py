"""Issue 115：我的追番状态总览与固定高度详情的真实 Chromium 门禁。

覆盖：

- 列表与详情各自在固定可用高度内滚动；展开记录或操作不拉长整页，
  也不移动另一列的位置；导航与状态总览留在外侧；
- 总集数无可信服务端值时显示「未开发」，不从资源数推断；
- 1280／1440／1920 桌面宽度下两列可达且无横向溢出。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import set_storage_preferences
from tests.browser.saved_tracking_fixtures import _status_groups_for

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


def _external_only_item() -> dict[str, Any]:
    """A retired read-only archive: real label, no card, only in 全部 (#224 A4)."""
    return {
        **_item(99),
        "tracking_id": "tracking-archive",
        "request_id": None,
        "title": "历史外部订阅",
        "status": "EXTERNAL_ONLY",
        "status_label": "仅外部",
        "status_group": "INACTIVE",
        "available_actions": [],
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


def _open(
    page: Page, live_server_url: str, storage_dir, items: list[dict[str, Any]],
    *, audits: int = 1,
) -> list[dict[str, Any]]:
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
        _groups = {
            entry["group"]: entry["count"] for entry in _status_groups_for(live_items)
        }
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "ok": True,
                    "result": {
                        "items": live_items,
                        # Issue #224 A4/A7: one derivation feeds both the
                        # summary and the published groups, so the fixture is a
                        # response the server could actually produce — the
                        # retired archive is in ``items``/``total`` only.
                        "summary": {
                            "total": len(live_items),
                            "pending": _groups["PENDING"],
                            "processing": _groups["PROCESSING"],
                            "active": _groups["ACTIVE"],
                            "inactive": _groups["INACTIVE"],
                            "needs_attention": _groups["ATTENTION"],
                            "added_to_download": 0,
                            "unreadable": 0,
                        },
                        "status_groups": _status_groups_for(live_items),
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



def _submittable_item(index: int) -> dict[str, Any]:
    """A row the batch pre-check accepts: PENDING_SUBMIT + SUBMIT action."""
    return {
        **_item(index),
        "status": "PENDING_SUBMIT",
        "status_label": "待提交",
        "status_group": "PENDING",
        "available_actions": [{
            "code": "SUBMIT", "label": "提交追番", "style": "PRIMARY",
            "requires_confirmation": True, "target_scopes": [],
        }],
    }


def _skeleton_geometry(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          const rect = (sel) => {
            const el = document.querySelector(sel)
            if (!el) return null
            const b = el.getBoundingClientRect()
            return {
              top: Math.round(b.top), bottom: Math.round(b.bottom),
              left: Math.round(b.left), right: Math.round(b.right),
              width: Math.round(b.width), height: Math.round(b.height),
            }
          }
          const tokenColor = (name) => {
            const probe = document.createElement('span')
            probe.style.color = `var(${name})`
            document.body.appendChild(probe)
            const value = getComputedStyle(probe).color
            probe.remove()
            return value
          }
          return {
            doc: {
              scrollHeight: document.scrollingElement.scrollHeight,
              clientHeight: document.scrollingElement.clientHeight,
              scrollWidth: document.documentElement.scrollWidth,
            },
            viewport: { width: window.innerWidth, height: window.innerHeight },
            nav: rect('.app-header'),
            pageHeader: rect('.tracking-page-header'),
            overview: rect('.tracking-status-overview'),
            workspace: rect('.tracking-workspace'),
            listPanel: rect('.tracking-list-panel'),
            inspector: rect('.tracking-inspector'),
            listScroller: rect('#tracking-list-container'),
            headingRow: rect('.tracking-list-heading-row'),
            columns: getComputedStyle(document.querySelector('.tracking-workspace')).gridTemplateColumns,
            infoSurface: tokenColor('--color-info-surface'),
            primary: tokenColor('--color-primary'),
          }
        }"""
    )


def _row_style_geometry(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          const rows = [...document.querySelectorAll('.tracking-list-row')]
          const first = rows[0]
          const selected = rows.find((row) => row.classList.contains('is-selected')) || first
          const unselected = rows.find((row) => row !== selected) || first
          const bw = (el) => {
            const b = el.getBoundingClientRect()
            return { width: Math.round(b.width), height: Math.round(b.height),
                     top: Math.round(b.top), left: Math.round(b.left) }
          }
          const bar = (row) => {
            const layer = row.querySelector('.tracking-row-background')
            const cs = getComputedStyle(layer, '::before')
            return { content: cs.content, width: cs.width, height: cs.height,
                     background: cs.backgroundColor,
                     radius: getComputedStyle(layer).borderRadius,
                     overflow: getComputedStyle(layer).overflow,
                     pointer: getComputedStyle(layer).pointerEvents }
          }
          const sep = (row) => {
            const cs = getComputedStyle(row, '::after')
            return { height: cs.height, background: cs.backgroundColor,
                     left: cs.left, right: cs.right }
          }
          const tokenColor = (name) => {
            const probe = document.createElement('span')
            probe.style.color = `var(${name})`
            document.body.appendChild(probe)
            const value = getComputedStyle(probe).color
            probe.remove()
            return value
          }
          return {
            rowCount: rows.length,
            row: bw(first),
            poster: bw(first.querySelector('.tracking-list-item .tracking-poster')),
            arrow: bw(first.querySelector('.tracking-list-arrow')),
            body: bw(first.querySelector('.tracking-list-item')),
            title: bw(first.querySelector('.tracking-list-title')),
            selectedBar: bar(selected),
            unselectedBar: bar(unselected),
            firstSeparator: sep(rows[0]),
            lastSeparator: sep(rows[rows.length - 1]),
            surface: tokenColor('--color-surface'),
            infoSurface: tokenColor('--color-info-surface'),
            primary: tokenColor('--color-primary'),
            rowBorder: getComputedStyle(first).borderTopWidth,
            rowShadow: getComputedStyle(first).boxShadow,
            rowTransform: getComputedStyle(first).transform,
            arrowTransform: getComputedStyle(first.querySelector('.tracking-list-arrow')).transform,
          }
        }"""
    )


def test_desktop_skeleton_has_no_page_scroll_and_equal_panels(
    page: Page, live_server_url: str, storage_dir
) -> None:
    """AC1 + AC5: no page scroll at 1440×900, equal columns, no retired modules."""
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, live_server_url, storage_dir, [_item(index) for index in range(24)])
    expect(page.locator(".tracking-list-item")).to_have_count(24)

    g = _skeleton_geometry(page)
    # AC1: the document itself never scrolls on the acceptance canvas.
    assert g["doc"]["scrollHeight"] <= g["doc"]["clientHeight"], g
    assert g["doc"]["scrollWidth"] <= g["viewport"]["width"], g
    # B3: both columns start and end on the same axis, with the same height.
    assert g["listPanel"]["top"] == g["inspector"]["top"], g
    assert g["listPanel"]["bottom"] == g["inspector"]["bottom"], g
    assert g["listPanel"]["height"] == g["inspector"]["height"], g
    # B3: navigation, page title and the status overview stay outside the modules.
    assert g["nav"]["bottom"] <= g["pageHeader"]["top"]
    assert g["pageHeader"]["bottom"] <= g["workspace"]["top"]
    assert g["overview"]["bottom"] <= g["workspace"]["top"]
    assert g["listPanel"]["bottom"] <= g["viewport"]["height"]

    # AC5: no header card, probe, connection module or capability summary.
    assert page.locator(".tracking-header").count() == 0
    assert page.locator("#tracking-probe-saved").count() == 0
    assert page.locator(".tracking-connection-status").count() == 0
    assert page.locator("#tracking-capability-summary").count() == 0
    # C5/2026-10-20: no refresh, status dropdown, 全部 or 清除筛选.
    assert page.locator("#tracking-refresh").count() == 0
    assert page.locator("#tracking-status-filter").count() == 0
    assert page.get_by_text("清除筛选", exact=True).count() == 0


def test_columns_scroll_independently_and_folds_keep_page_height(
    page: Page, live_server_url: str, storage_dir
) -> None:
    """AC2: each column scrolls alone and expanding a detail fold never grows the page."""
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, live_server_url, storage_dir, [_item(index) for index in range(24)], audits=40)
    page.locator(".tracking-list-item").first.click()
    _wait_for_loaded_detail(page)
    page_height = page.evaluate("() => document.scrollingElement.scrollHeight")

    before = page.evaluate(
        """() => {
          const list = document.querySelector('#tracking-list-container')
          const inspector = document.querySelector('.tracking-inspector')
          return { list: list.scrollTop, inspector: inspector.scrollTop,
                   listScrollable: list.scrollHeight > list.clientHeight,
                   inspectorScrollable: inspector.scrollHeight > inspector.clientHeight }
        }"""
    )
    assert before["listScrollable"] is True
    assert before["inspectorScrollable"] is True

    # Scroll the list to the bottom: the detail column must not move.
    page.evaluate(
        "() => { const list = document.querySelector('#tracking-list-container');"
        " list.scrollTop = list.scrollHeight }"
    )
    after_list = page.evaluate(
        """() => ({
          list: document.querySelector('#tracking-list-container').scrollTop,
          inspector: document.querySelector('.tracking-inspector').scrollTop,
        })"""
    )
    assert after_list["list"] > before["list"]
    assert after_list["inspector"] == before["inspector"]

    # Scroll the detail to the bottom: the list must not move.
    page.evaluate(
        "() => { const inspector = document.querySelector('.tracking-inspector');"
        " inspector.scrollTop = inspector.scrollHeight }"
    )
    after_inspector = page.evaluate(
        """() => ({
          list: document.querySelector('#tracking-list-container').scrollTop,
          inspector: document.querySelector('.tracking-inspector').scrollTop,
        })"""
    )
    assert after_inspector["list"] == after_list["list"]
    assert after_inspector["inspector"] > 0

    # Expand every detail fold: the bounded columns grow inside, not the page.
    for disclosure in ("#tracking-activity-log", "#tracking-tech-diagnostics"):
        page.locator(f"{disclosure} summary").click()
    assert page.evaluate("() => document.scrollingElement.scrollHeight") == page_height


def test_low_height_degrades_to_page_scroll_with_320px_columns(
    page: Page, live_server_url: str, storage_dir
) -> None:
    """AC3/B4: below the 320px floor the page may scroll; both columns keep the floor."""
    page.set_viewport_size({"width": 1280, "height": 600})
    _open(page, live_server_url, storage_dir, [_item(index) for index in range(24)])

    g = _skeleton_geometry(page)
    assert g["doc"]["scrollHeight"] > g["doc"]["clientHeight"]
    assert g["listPanel"]["height"] >= 320
    assert g["inspector"]["height"] >= 320
    assert g["listPanel"]["top"] == g["inspector"]["top"]
    assert g["listPanel"]["height"] == g["inspector"]["height"]
    # The scroll belongs to the document as the degradation, not to a squeezed column.
    assert g["listScroller"]["height"] > 0


@pytest.mark.parametrize("width", [780, 760])
def test_shell_vertical_reflow_starts_at_760_not_an_800px_breakpoint(
    page: Page, live_server_url: str, storage_dir, width: int
) -> None:
    """AC4/B2: only the shell's 760px breakpoint stacks the two columns."""
    page.set_viewport_size({"width": width, "height": 900})
    _open(page, live_server_url, storage_dir, [_item(index) for index in range(6)])
    page.locator("#tracking-batch-mode").click()

    g = _skeleton_geometry(page)
    columns = g["columns"].split()
    assert g["doc"]["scrollWidth"] <= g["viewport"]["width"]
    if width > 760:
        # Still the desktop two-column layout at 780.
        assert len(columns) == 2, g["columns"]
        assert g["listPanel"]["top"] == g["inspector"]["top"]
        search = page.locator("#tracking-search").bounding_box()
        assert search is not None and search["width"] <= 240.5
    else:
        # Stacked by the shell 760px rule; the search takes the full row.
        assert len(columns) == 1, g["columns"]
        assert g["inspector"]["top"] >= g["listPanel"]["bottom"]
        search = page.locator("#tracking-search").bounding_box()
        panel = page.locator(".tracking-list-panel").bounding_box()
        assert search is not None and panel is not None
        assert search["width"] >= panel["width"] - 60
        # Batch submit moves to its own full-width row.
        submit = page.locator("#tracking-batch-submit").bounding_box()
        toolbar = page.locator(".tracking-batch-toolbar").bounding_box()
        assert submit is not None and toolbar is not None
        assert submit["width"] >= toolbar["width"] - 60


def test_row_spec_structure_and_visual_tokens(
    page: Page, live_server_url: str, storage_dir
) -> None:
    """D0 row spec: two sibling buttons, no card chrome, separators, bar and hover."""
    page.set_viewport_size({"width": 1440, "height": 900})
    items = [_item(index) for index in range(4)]
    _open(page, live_server_url, storage_dir, items)
    # Browse-click selects a detail row; no checkbox exists in any row.
    page.locator(".tracking-list-item").first.click()
    _wait_for_loaded_detail(page)

    g = _row_style_geometry(page)
    assert page.locator('input[type="checkbox"]').count() == 0
    assert page.locator(".tracking-list-checkbox").count() == 0
    assert page.locator(".tracking-list-indicator").count() == 0
    assert page.locator(".tracking-list-row button").count() == g["rowCount"] * 2
    # Row: no four-side border, no shadow, no uplift; min height 115.
    assert g["rowBorder"] == "0px"
    assert g["rowShadow"] == "none"
    assert g["rowTransform"] == "none"
    assert g["arrowTransform"] == "none"
    assert g["row"]["height"] >= 115
    # Cover 60×90 (2:3) and a 44px-wide arrow hit area that never squeezes the title.
    assert abs(g["poster"]["width"] - 60) <= 1
    assert abs(g["poster"]["height"] - 90) <= 1
    assert g["arrow"]["width"] == 44
    assert g["arrow"]["height"] >= 44
    assert g["title"]["width"] > 0
    assert g["body"]["width"] <= g["row"]["width"] - 44
    # Shared background layer: 10px radius, clipped, decorative only.
    assert g["selectedBar"]["radius"] == "10px"
    assert g["selectedBar"]["overflow"] == "hidden"
    assert g["selectedBar"]["pointer"] == "none"
    # Detail-selected row: the only row with the 4px primary bar.
    assert g["selectedBar"]["content"] != "none"
    assert g["selectedBar"]["width"] == "4px"
    assert g["selectedBar"]["background"] == g["primary"]
    assert g["unselectedBar"]["content"] == "none"
    # One 1px separator per row; the last visible row keeps a transparent slot.
    assert g["firstSeparator"]["height"] == "1px"
    assert g["firstSeparator"]["background"] != "rgba(0, 0, 0, 0)"
    assert g["lastSeparator"]["height"] == "1px"
    assert g["lastSeparator"]["background"] == "rgba(0, 0, 0, 0)"

    # Hover is a temporary info-surface background with no extra bar.
    page.locator(".tracking-list-row").nth(1).hover()
    page.wait_for_timeout(250)
    hovered = page.evaluate(
        """() => {
          const row = document.querySelectorAll('.tracking-list-row')[1]
          const layer = row.querySelector('.tracking-row-background')
          const cs = getComputedStyle(layer, '::before')
          const probe = document.createElement('span')
          probe.style.color = 'var(--color-info-surface)'
          document.body.appendChild(probe)
          const info = getComputedStyle(probe).color
          probe.remove()
          return { background: getComputedStyle(layer).backgroundColor, info,
                   bar: cs.content }
        }"""
    )
    assert hovered["background"] == hovered["info"]
    assert hovered["bar"] == "none"


def test_row_and_arrow_actions_follow_the_documented_mode_matrix(
    page: Page, live_server_url: str, storage_dir
) -> None:
    """D0 action matrix: body toggles selection in multi-select, arrow always opens detail."""
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, live_server_url, storage_dir, [_submittable_item(index) for index in range(3)])

    # Browse: the row body opens the detail.
    page.locator(".tracking-list-item").first.click()
    _wait_for_loaded_detail(page)
    assert "is-selected" in (page.locator(".tracking-list-row").first.get_attribute("class") or "")
    selected_id = page.evaluate(
        "() => document.querySelector('.tracking-list-row.is-selected')?.dataset.trackingId"
    )

    page.locator("#tracking-batch-mode").click()
    expect(page.locator("#tracking-batch-mode")).to_have_text("完成")
    # Multi-select: the body toggles the selection only and leaves the detail alone.
    page.locator(".tracking-list-item").nth(1).click()
    second_class = page.locator(".tracking-list-row").nth(1).get_attribute("class") or ""
    assert "is-batch-selected" in second_class
    assert "is-selected" not in second_class
    assert page.evaluate(
        "() => document.querySelector('.tracking-list-row.is-selected')?.dataset.trackingId"
    ) == selected_id
    expect(page.locator("#tracking-batch-count")).to_contain_text("已选 1 部")

    # The arrow always opens the detail and never changes the batch selection.
    page.locator(".tracking-list-row").nth(2).locator(".tracking-list-arrow").click()
    _wait_for_loaded_detail(page)
    third_class = page.locator(".tracking-list-row").nth(2).get_attribute("class") or ""
    assert "is-selected" in third_class
    assert "is-batch-selected" not in third_class
    expect(page.locator("#tracking-batch-count")).to_contain_text("已选 1 部")


def test_arrow_is_not_in_the_tab_order(
    page: Page, live_server_url: str, storage_dir
) -> None:
    """AC10/spec 9: the arrow is decorative; Tab only reaches the row body."""
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, live_server_url, storage_dir, [_item(index) for index in range(3)])
    arrow = page.locator(".tracking-list-arrow").first
    expect(arrow).to_have_attribute("tabindex", "-1")
    expect(arrow).to_have_attribute("aria-hidden", "true")

    page.locator("#tracking-search").focus()
    for _ in range(8):
        page.keyboard.press("Tab")
        focused = page.evaluate(
            "() => ({ cls: document.activeElement?.className || '', tag: document.activeElement?.tagName })"
        )
        assert "tracking-list-arrow" not in focused["cls"], focused


def test_batch_toolbar_is_its_own_row_with_the_single_primary_action(
    page: Page, live_server_url: str, storage_dir
) -> None:
    """2026-10-20: toolbar below the title row; left selection text, one primary action."""
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, live_server_url, storage_dir, [_submittable_item(index) for index in range(3)])

    page.locator("#tracking-batch-mode").click()
    toolbar = page.locator(".tracking-batch-toolbar")
    heading = page.locator(".tracking-list-heading-row")
    expect(toolbar).to_be_visible()
    toolbar_box = toolbar.bounding_box()
    heading_box = heading.bounding_box()
    assert toolbar_box is not None and heading_box is not None
    assert toolbar_box["y"] >= heading_box["y"] + heading_box["height"]
    # The toolbar lives inside the list module, not as a workspace sibling.
    assert page.evaluate(
        "() => !!document.querySelector('.tracking-list-panel .tracking-batch-toolbar')"
    )
    assert page.evaluate(
        "() => !!document.querySelector('.tracking-list-panel #tracking-batch-submit')"
    )

    expect(page.locator("#tracking-batch-count")).to_contain_text("已选 0 部")
    expect(page.locator("#tracking-batch-select-all")).to_have_text("全选当前 3 部")
    expect(page.locator("#tracking-batch-clear")).to_have_text("清除选择")
    expect(page.locator("#tracking-batch-submit")).to_have_text("提交选中")
    assert "primary-button" in (
        page.locator("#tracking-batch-submit").get_attribute("class") or ""
    )
    # Text actions are plain buttons (no filled/bordered control).
    assert page.evaluate(
        """() => {
          const el = document.querySelector('#tracking-batch-select-all')
          const cs = getComputedStyle(el)
          return { tag: el.tagName, border: cs.borderTopWidth, background: cs.backgroundColor }
        }"""
    ) == {"tag": "BUTTON", "border": "0px", "background": "rgba(0, 0, 0, 0)"}

    page.locator("#tracking-batch-select-all").click()
    expect(page.locator("#tracking-batch-count")).to_contain_text("已选 3 部")
    # C7: the list container is never replaced by the skip notice.
    assert page.locator("#tracking-list-container").count() == 1
    # Entering multi-select keeps the page inside the viewport budget.
    assert page.evaluate(
        "() => document.scrollingElement.scrollHeight <= document.scrollingElement.clientHeight"
    )




def _sync_page(page: Page, live_server_url: str, storage_dir, sync_result: dict[str, Any]) -> None:
    """Open the tracking page with a saved connection and a fixed sync result."""
    ref = "11111111-1111-4111-8111-111111111111"
    probes: list[str] = []

    def handler(route: Any, request: Any) -> None:
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
            route.fulfill(json={"ok": True, "result": {
                "configured": True, "credential_present": True, "connection_ref": ref,
                "configuration_revision": 3, "connection_status": "CONFIGURED",
            }})
            return
        if request.method == "POST" and path == "/settings/autobangumi/probe":
            probes.append(path)
            route.fulfill(json={"ok": True, "result": {
                "probe_status": "VERIFIED", "version": "3.1.18", "adapter": "legacy_3_1",
                "subscription_list": "SUPPORTED", "subscription_detail": "SUPPORTED",
                "subscription_submit": "SUPPORTED", "subscription_modify": "SUPPORTED",
                "subscription_enable": "SUPPORTED", "subscription_disable": "SUPPORTED",
                "subscription_delete": "SUPPORTED", "rss_list": "SUPPORTED",
                "rss_modify": "SUPPORTED", "rss_enable": "SUPPORTED",
                "rss_disable": "SUPPORTED", "rss_delete": "SUPPORTED",
                "rss_refresh": "SUPPORTED", "external_verify": "SUPPORTED",
                "checked_at": None, "safe_message": "ok",
            }})
            return
        if request.method == "GET" and path == "/tracking/items":
            item = _item(1)
            route.fulfill(json={"ok": True, "result": {
                "items": [item],
                "summary": {"total": 1, "active": 1},
                "status_groups": _status_groups_for([item]),
                "warnings": [],
            }})
            return
        if request.method == "POST" and path == "/tracking/sync":
            route.fulfill(json={"ok": True, "result": sync_result})
            return
        route.continue_()

    page.route("**/api/v1/**", handler)
    set_storage_preferences(page, storage_dir)
    page.goto(f"{live_server_url}/app/tracking")
    page.wait_for_selector("#tracking-sync")


def _sync_once(page: Page) -> None:
    page.locator("#tracking-sync").click()
    page.locator(".confirm-dialog .danger-button, .confirm-dialog .primary-button").last.click()
    page.wait_for_timeout(300)


def test_clean_sync_success_uses_the_global_notification(
    page: Page, live_server_url: str, storage_dir
) -> None:
    """B5: a clean sync success is a global toast, not an inline page region."""
    caps = _probe_caps()
    _sync_page(page, live_server_url, storage_dir, {
        "sync_status": "COMPLETE", "checked_at": "2026-10-21T00:00:00Z",
        "capabilities": caps,
        "summary": {"checked": 1, "created": 0, "updated": 1, "unchanged": 0,
                    "ignored": 0, "failed": 0, "unreadable": 0},
        "warnings": [], "items": [_item(1)],
    })
    _sync_once(page)

    expect(page.locator(".global-notification")).to_contain_text("同步完成")
    # The list-module status area stays empty for a clean success.
    assert page.locator("#tracking-sync-status").count() == 0
    assert page.locator(".tracking-toolbar-status").count() == 0


def test_degraded_or_ignoring_sync_stays_in_the_list_status_area(
    page: Page, live_server_url: str, storage_dir
) -> None:
    """B5: incomplete / ignored sync results stay in the bounded list toolbar area."""
    caps = _probe_caps()
    _sync_page(page, live_server_url, storage_dir, {
        "sync_status": "PARTIAL", "checked_at": "2026-10-21T00:00:00Z",
        "capabilities": caps,
        "summary": {"checked": 3, "created": 0, "updated": 1, "unchanged": 1,
                    "ignored": 2, "failed": 1, "unreadable": 0},
        "warnings": [], "items": [_item(1)],
    })
    _sync_once(page)

    status = page.locator("#tracking-sync-status")
    expect(status).to_be_visible()
    expect(status).to_contain_text("同步部分完成")
    expect(page.locator(".tracking-list-panel #tracking-sync-status")).to_have_count(1)
    # No success toast is claimed for a degraded result.
    assert page.locator(".global-notification").count() == 0


def _probe_caps() -> dict[str, Any]:
    return {
        "probe_status": "VERIFIED", "version": "3.1.18", "adapter": "legacy_3_1",
        "subscription_list": "SUPPORTED", "subscription_detail": "SUPPORTED",
        "subscription_submit": "SUPPORTED", "subscription_modify": "SUPPORTED",
        "subscription_enable": "SUPPORTED", "subscription_disable": "SUPPORTED",
        "subscription_delete": "SUPPORTED", "rss_list": "SUPPORTED",
        "rss_modify": "SUPPORTED", "rss_enable": "SUPPORTED",
        "rss_disable": "SUPPORTED", "rss_delete": "SUPPORTED",
        "rss_refresh": "SUPPORTED", "external_verify": "SUPPORTED",
        "checked_at": None, "safe_message": "ok",
    }

def test_overview_cards_keep_the_server_count_and_clear_the_search(
    page: Page, live_server_url: str, storage_dir
) -> None:
    """Issue #224 A2/A4/A5: four cards, authoritative numbers, search cleared.

    The fixture is a response the server can actually produce: five 追番中 rows
    plus one retired ``EXTERNAL_ONLY`` archive, so 全部 has 6 rows while the
    追番中 card has 5 and 已停用 has 0.  A frontend recount of loaded rows, a card
    that reads ``summary.total``, or a filter that lets the archive through
    would all fail instead of accidentally matching the mock.
    """
    items = [*[_item(index) for index in range(5)], _external_only_item()]
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, live_server_url, storage_dir, items)

    cards = page.locator(".tracking-status-card")
    assert cards.count() == 4
    assert ["".join(text.split()) for text in cards.all_inner_texts()] == [
        "待处理0", "追番中5", "需处理0", "已停用0",
    ]
    # 全部 keeps the archive visible with its real label and the server total.
    rows = page.locator(".tracking-list-item")
    expect(rows).to_have_count(6)
    expect(rows.filter(has_text="仅外部")).to_have_count(1)
    # 全部 without a search: the bottom number is the server total, not a recount.
    assert page.locator(".tracking-list-count").inner_text() == "共 6 部"

    # Every card's number equals the rows it reveals without a search condition.
    expected = {
        "pending": ("待处理", 0), "active": ("追番中", 5),
        "attention": ("需处理", 0), "inactive": ("已停用", 0),
    }
    for group, (_label, count) in expected.items():
        card = page.locator(f"#tracking-overview-{group}")
        card.click()
        assert card.get_attribute("aria-pressed") == "true"
        expect(page.locator(".tracking-list-item")).to_have_count(count)
        assert page.locator(".tracking-list-count").inner_text() == f"共 {count} 部"

    # 追番中: a search narrows only the rows; the card number stays authoritative.
    page.locator("#tracking-overview-active").click()
    expect(page.locator(".tracking-list-item")).to_have_count(5)
    page.fill("#tracking-search", "04")
    expect(page.locator(".tracking-list-item")).to_have_count(1)
    assert page.locator(".tracking-list-count").inner_text() == "筛选出 1 部 · 共 5 部"

    # Clicking another card clears the search box (the user's decision).
    page.locator("#tracking-overview-inactive").click()
    expect(page.locator("#tracking-search")).to_have_value("")
    expect(page.locator(".tracking-list-item")).to_have_count(0)
    assert page.locator(".tracking-list-count").inner_text() == "共 0 部"
    assert page.locator("#tracking-overview-inactive").get_attribute("aria-pressed") == "true"


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
    # 无可信服务端值：两个集数字段都显示「未开发」（Issue #131/#165），不从资源数推断。
    assert rows["总集数"] == "未开发"
    assert rows["已更新集数"] == "未开发"
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
