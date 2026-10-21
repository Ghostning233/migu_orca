"""#156：全站共享复选框（CheckboxRow 与原生 checkbox）的真实 Chromium 覆盖矩阵。

覆盖实际使用处：添加番剧（单番救援 CheckboxRow、批量卡片与底栏 CheckboxRow）、设置页三个
CheckboxRow、我的追番批量列表里的原生 checkbox。断言：

- 可见方框固定 18px，不因 44px 触控目标被放大；标签提供可点区域；
- checked / unchecked / indeterminate / disabled / hover / focus-visible 可辨认；
- 标签点击与原生键盘 Space 都能切换；禁用行点击不改变状态；
- 1280／1440／1920 下尺寸不变且无横向溢出。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import set_storage_preferences
from tests.browser.saved_tracking_fixtures import _status_groups_for, _summary
from tests.browser.screen_support import wait_for_screen_scroll
from tests.browser.test_app_batch_workbench import (
    _compact_items,
    _goto_batch,
    _route_parse,
)
from tests.browser.test_app_tracking_batch_submit import _open as _open_tracking
from tests.browser.test_app_tracking_batch_submit import _pending, _processing
from tests.browser.test_app_tracking_workbench import _item, _plan_snapshot
from tests.browser.test_app_workbench import _candidate, _candidate_result_json
from tests.browser.visual_support import install_shell_status_routes, prepare_canvas, require_dist

pytestmark = pytest.mark.browser

BOX = 18.0
TOLERANCE = 1.0
PRIMARY_RGB = "rgb(11, 42, 85)"
FOCUS_RGB = "rgb(37, 99, 235)"

_BOX_SCRIPT = """
(selector) => {
  const input = document.querySelector(selector)
  if (!input) return null
  const rect = input.getBoundingClientRect()
  const style = getComputedStyle(input)
  return {
    width: rect.width,
    height: rect.height,
    appearance: style.appearance || style.webkitAppearance,
    backgroundColor: style.backgroundColor,
    borderColor: style.borderColor,
    backgroundImage: style.backgroundImage,
    outlineWidth: style.outlineWidth,
    outlineColor: style.outlineColor,
    cursor: style.cursor,
    disabled: input.disabled,
    checked: input.checked,
    indeterminate: input.indeterminate,
  }
}
"""

_EMPTY_CANDIDATES = json.dumps(
    {
        "ok": True,
        "result": {
            "query": "找不到的番剧",
            "status": "EMPTY",
            "parse_result": None,
            "attempted_queries": [],
            "candidates": [],
            "error": None,
        },
    },
    ensure_ascii=False,
)


def _box(page: Page, selector: str) -> dict[str, Any]:
    value = page.evaluate(_BOX_SCRIPT, selector)
    assert value is not None, f"{selector}: checkbox missing"
    return value


def _assert_shared_box(box: dict[str, Any], label: str) -> None:
    assert abs(box["width"] - BOX) <= TOLERANCE, (label, box)
    assert abs(box["height"] - BOX) <= TOLERANCE, (label, box)
    # appearance:none 表示方框完全由共享 CSS 绘制，不再是 44px 的原生控件。
    assert box["appearance"] == "none", (label, box)


def _first_label(page: Page, input_id: str) -> Any:
    """CheckboxRow 有方框与文字两个 label；取第一个可点区域点击。"""
    return page.locator(f'label[for="{input_id}"]').first


def _open_single_fallback(page: Page, live_server_url: str) -> None:
    require_dist()
    install_shell_status_routes(page)
    prepare_canvas(page)
    page.route(
        "**/api/v1/mikan/candidates",
        lambda route: route.fulfill(status=200, content_type="application/json", body=_EMPTY_CANDIDATES),
    )
    page.goto(f"{live_server_url}/app/add")
    page.wait_for_selector(".single-home-hero", timeout=10_000)
    page.fill("#mikan-candidate-query", "找不到的番剧")
    page.click("#mikan-candidate-search-submit")
    page.wait_for_selector("#mikan-fallback-enabled", timeout=10_000)


def test_single_fallback_checkbox_is_compact_and_keyboard_operable(
    page: Page, live_server_url: str
) -> None:
    _open_single_fallback(page, live_server_url)
    selector = "#mikan-fallback-enabled"

    box = _box(page, selector)
    _assert_shared_box(box, "single-fallback")
    assert box["checked"] is False
    assert box["backgroundColor"] == "rgb(255, 255, 255)", box

    # hover：未选中方框的描边转为 primary。
    page.locator(selector).hover()
    assert _box(page, selector)["borderColor"] == PRIMARY_RGB

    # 标签点击（可点区域）勾选，方框保持 18px 且用 primary 色 + 勾选图形。
    _first_label(page, "mikan-fallback-enabled").click()
    expect(page.locator("#mikan-fallback-form")).to_be_visible()
    checked = _box(page, selector)
    assert checked["checked"] is True
    assert checked["backgroundColor"] == PRIMARY_RGB, checked
    assert "data:image/svg+xml" in checked["backgroundImage"], checked
    _assert_shared_box(checked, "single-fallback-checked")

    # 原生键盘 Space 切换。
    page.locator(selector).focus()
    page.keyboard.press(" ")
    expect(page.locator("#mikan-fallback-form")).to_have_count(0)
    assert _box(page, selector)["checked"] is False

    # focus-visible：键盘导航聚焦时是 3px 共享焦点环。
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Tab")
    focused = _box(page, selector)
    assert focused["outlineWidth"] == "3px", focused
    assert focused["outlineColor"] == FOCUS_RGB, focused


def test_batch_workbench_checkboxes_cover_checked_indeterminate_and_label_click(
    page: Page, live_server_url: str
) -> None:
    page.emulate_media(reduced_motion="reduce")
    _route_parse(page, _compact_items(2))
    _goto_batch(page, live_server_url)
    page.fill("#batch-raw-input", "番剧00\n番剧01")
    page.click("#batch-parse-submit")
    expect(page.locator(".batch-draft-card")).to_have_count(2)
    wait_for_screen_scroll(page)

    card = '.batch-draft-card[data-item-id="item-00"] .batch-card-checkbox-row'
    _assert_shared_box(_box(page, card), "card")
    select_all = _box(page, "#batch-select-all-checkbox")
    _assert_shared_box(select_all, "select-all")
    assert select_all["indeterminate"] is False

    # 卡片勾选不切换右栏当前查看项（控制列整体 stop 冒泡）。
    page.locator('.batch-draft-card[data-item-id="item-00"]').click()
    expect(page.locator('.batch-draft-card[data-item-id="item-00"]')).to_have_class(re.compile(r"is-current"))
    page.locator(card).check()
    assert _box(page, card)["checked"] is True
    expect(page.locator('.batch-draft-card[data-item-id="item-00"]')).to_have_class(re.compile(r"is-current"))

    # 部分勾选 → 全选是 indeterminate（虚线图形 + primary 底，与勾选态可辨认）。
    partial = _box(page, "#batch-select-all-checkbox")
    assert partial["indeterminate"] is True
    assert partial["checked"] is False
    assert partial["backgroundColor"] == PRIMARY_RGB, partial
    assert "data:image/svg+xml" in partial["backgroundImage"]

    # 标签点击勾选第二项后，全选变为 checked 且不再是 indeterminate。
    page.locator('.batch-draft-card[data-item-id="item-01"] input[type="checkbox"]').check()
    full = _box(page, "#batch-select-all-checkbox")
    assert full["checked"] is True
    assert full["indeterminate"] is False

    # 全选禁用态：清空可见可选集合后（搜索无匹配）方框仍 18px 且不可点。
    page.click("#batch-review-search-toggle")
    page.wait_for_selector("#batch-review-search")
    page.fill("#batch-review-search", "不存在的标题")
    expect(page.locator(".batch-draft-card")).to_have_count(0)
    disabled = _box(page, "#batch-select-all-checkbox")
    _assert_shared_box(disabled, "select-all-disabled")
    assert disabled["disabled"] is True
    assert disabled["cursor"] == "not-allowed", disabled


@pytest.mark.parametrize(
    ("width", "height"),
    [(1280, 800), (1440, 900), (1920, 1080), (720, 450)],  # 末项 = 1440 桌面 200% 缩放
)
def test_settings_checkboxes_use_the_shared_box_at_desktop_viewports(
    page: Page, live_server_url: str, width: int, height: int
) -> None:
    require_dist()
    install_shell_status_routes(page)
    page.emulate_media(reduced_motion="reduce")
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{live_server_url}/app/settings")
    page.wait_for_selector("#settings-heading", timeout=10_000)

    for selector in (
        "#preference-filter-use-regex",
        "#preference-filter-case-sensitive",
        "#preference-search-reuse-corrections",
    ):
        _assert_shared_box(_box(page, selector), selector)
    assert page.evaluate("() => document.body.scrollWidth <= window.innerWidth + 1")

    _first_label(page, "preference-filter-use-regex").click()
    assert _box(page, "#preference-filter-use-regex")["checked"] is True
    page.locator("#preference-filter-use-regex").focus()
    page.keyboard.press(" ")
    assert _box(page, "#preference-filter-use-regex")["checked"] is False


def test_tracking_list_uses_no_checkbox_after_the_row_spec_revision(
    page: Page, live_server_url: str, storage_dir: Path
) -> None:
    """#225/D0 2026-10-20: the tracking list retired the shared checkbox and the
    selection column; multi-select is expressed only by the shared row background.
    The shared checkbox itself stays untouched for every other screen."""
    page.emulate_media(reduced_motion="reduce")
    _open_tracking(
        page,
        live_server_url,
        storage_dir,
        [_pending("tracking-a", "番 A"), _processing("tracking-b", "番 B")],
    )
    assert page.locator(".tracking-list-checkbox").count() == 0
    assert page.locator('input[type="checkbox"]').count() == 0

    page.locator("#tracking-batch-mode").click()
    assert page.locator(".tracking-list-checkbox").count() == 0
    assert page.locator('input[type="checkbox"]').count() == 0

    rows = page.locator(".tracking-list-row")
    # The body toggles the selection; the detail identity stays independent.
    rows.nth(0).locator(".tracking-list-item").click()
    expect(page.locator("#tracking-batch-count")).to_contain_text("已选 1 部")
    assert "is-batch-selected" in (rows.nth(0).get_attribute("class") or "")
    assert page.locator(".tracking-list-row.is-selected").count() == 0

    # A transient row's body is disabled and cannot join the selection.
    expect(rows.nth(1).locator(".tracking-list-item")).to_be_disabled()
    rows.nth(1).locator(".tracking-list-item").click(force=True)
    expect(page.locator("#tracking-batch-count")).to_contain_text("已选 1 部")

def test_candidate_season_confirmation_uses_the_shared_box(page: Page, live_server_url: str) -> None:
    """候选季数确认（CandidateCard 原生 checkbox）也使用共享 18px 方框。"""
    require_dist()
    install_shell_status_routes(page)
    page.emulate_media(reduced_motion="reduce")
    prepare_canvas(page)
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
                        season_evidence={"status": "NEEDS_CONFIRMATION", "season": 4, "requires_review": True},
                        candidate_context="opaque-candidate-context",
                    )
                ],
            ),
        ),
    )
    page.goto(f"{live_server_url}/app/add")
    page.wait_for_selector(".single-home-hero", timeout=10_000)
    page.fill("#mikan-candidate-query", "芙莉莲")
    page.click("#mikan-candidate-search-submit")
    page.wait_for_selector(".candidate-season-confirmation", timeout=10_000)

    selector = ".candidate-season-confirmation input"
    box = _box(page, selector)
    _assert_shared_box(box, "candidate-season-confirmation")
    assert box["checked"] is False
    # 未确认季数时候选不可选；勾选共享方框后按钮恢复可用。
    expect(page.locator(".candidate-card .candidate-select")).to_be_disabled()
    page.click(".candidate-season-confirmation")
    expect(page.locator(".candidate-season-confirmation input")).to_be_checked()
    expect(page.locator(".candidate-card .candidate-select")).to_be_enabled()

def test_saved_plan_and_external_delete_checkboxes_use_the_shared_box(
    page: Page, live_server_url: str, storage_dir: Path
) -> None:
    """已保存方案（TrackingInspector 的 saved 模式）与「同时删除外部订阅」也走共享方框。"""
    require_dist()
    set_storage_preferences(page, storage_dir)
    page.emulate_media(reduced_motion="reduce")
    item = {
        **_item("tracking-a", "葬送的芙莉莲"),
        "request_id": "request-plan",
        "status": "PENDING_SUBMIT",
        "status_label": "待提交",
        "status_group": "PENDING",
        "available_actions": [],
    }
    # external_mapping 非空 → 删除方案流程会给出「同时删除外部订阅」复选框。
    detail = {
        **item,
        "origin": "single",
        "batch_id": None,
        "created_at": "2026-09-01T00:00:00Z",
        "last_synced_at": None,
        "safe_info": None,
        "current_operation": None,
        "revalidation_issues": [],
        "external_mapping": {"match_reason": "标题", "enabled": True, "external_deleted": False},
        "audit_events": [],
        "warnings": [],
    }

    def handler(route: Any, request: Any) -> None:
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "configured": True,
                        "credential_present": True,
                        "connection_ref": "11111111-1111-4111-8111-111111111111",
                        "configuration_revision": 1,
                        "connection_status": "CONFIGURED",
                    },
                }
            )
            return
        if request.method == "GET" and path == "/tracking/items":
            route.fulfill(json={"ok": True, "result": {"items": [item], "summary": _summary(1, pending=1), "status_groups": _status_groups_for([item]), "warnings": []}})
            return
        if request.method == "GET" and path == "/tracking/items/tracking-a":
            route.fulfill(json={"ok": True, "result": detail})
            return
        if request.method == "GET" and path == "/requests/request-plan":
            route.fulfill(json={"ok": True, "result": _plan_snapshot("芙莉莲")})
            return
        route.continue_()

    page.route("**/api/v1/**", handler)
    page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
    page.wait_for_selector("#tracking-edit-plan")
    page.locator("#tracking-edit-plan").click()
    page.wait_for_selector("#tracking-plan-editor")
    page.evaluate(
        "() => document.querySelectorAll('#tracking-plan-editor details')"
        ".forEach((el) => { el.open = true; })"
    )

    # 已保存方案的五项复选框都使用共享 18px 方框。
    saved_ids = (
        "tracking-plan-clear-must-contain",
        "tracking-plan-clear-must-not-contain",
        "tracking-plan-use-regex",
        "tracking-plan-case-sensitive",
        "tracking-plan-clear-folder-name",
    )
    for input_id in saved_ids:
        _assert_shared_box(_box(page, f"#{input_id}"), input_id)

    # 标签点击与原生键盘 Space 都能切换（清空目录名只在 saved 模式出现）。
    _first_label(page, "tracking-plan-clear-folder-name").click()
    assert _box(page, "#tracking-plan-clear-folder-name")["checked"] is True
    page.locator("#tracking-plan-clear-folder-name").focus()
    page.keyboard.press(" ")
    assert _box(page, "#tracking-plan-clear-folder-name")["checked"] is False
    _first_label(page, "tracking-plan-use-regex").click()
    assert _box(page, "#tracking-plan-use-regex")["checked"] is True

    # 「同时删除 Auto Bangumi 中的受控外部订阅」也在盘点范围内。
    page.locator("#tracking-delete-plan").click()
    page.wait_for_selector("#tracking-delete-plan-external")
    _assert_shared_box(_box(page, "#tracking-delete-plan-external"), "tracking-delete-plan-external")
    _first_label(page, "tracking-delete-plan-external").click()
    assert _box(page, "#tracking-delete-plan-external")["checked"] is True
    page.locator("#tracking-delete-plan-external").focus()
    page.keyboard.press(" ")
    assert _box(page, "#tracking-delete-plan-external")["checked"] is False
