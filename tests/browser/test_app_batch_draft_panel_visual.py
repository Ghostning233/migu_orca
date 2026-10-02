"""#157：批量草案右栏留白、资源盒子、高级设置与资源入口（真实 Chromium）。

断言：

- 右栏内边距为常规桌面 24px、窄屏 16px（computed style 实测）；
- 资源结果四项、安全示例与入口同处一个与「字幕与筛选」一致的描边盒子，盒内没有
  设计图以外的横/竖分割线；两项资源计数与两个「未开发」集数占位不变；
- 高级设置默认折叠，展开后紧凑并使用共享复选框；
- 资源入口默认 primary 蓝、hover 淡蓝圆角背景、键盘有可见焦点；点击打开双页签弹窗，
  关闭后焦点与右栏滚动位置恢复；
- 1280／1920／200% 缩放下可达且无横向溢出；右栏末项在固定底栏之上。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.evidence import (
    FixtureDescriptor,
    LoadedResourceRecorder,
    ScenarioDescriptor,
    capture_evidence,
    file_digest,
    write_manifest,
)
from tests.browser.screen_support import wait_for_scroll_idle
from tests.browser.test_app_batch_workbench import _compact_items, _open_compact_list
from tests.browser.visual_support import capture_canvas, require_dist

pytestmark = pytest.mark.browser

TOLERANCE = 1.0
PRIMARY_RGB = "rgb(11, 42, 85)"
PRIMARY_SUBTLE_RGB = "rgb(234, 240, 248)"
FOCUS_RGB = "rgb(37, 99, 235)"

_PANE_SCRIPT = """
() => {
  const read = (selector) => {
    const element = document.querySelector(selector)
    if (!element) return null
    const style = getComputedStyle(element)
    const rect = element.getBoundingClientRect()
    return {
      paddingTop: style.paddingTop,
      paddingLeft: style.paddingLeft,
      borderTopWidth: style.borderTopWidth,
      borderLeftWidth: style.borderLeftWidth,
      borderBottomWidth: style.borderBottomWidth,
      borderRadius: style.borderTopLeftRadius,
      backgroundColor: style.backgroundColor,
      color: style.color,
      fontSize: style.fontSize,
      outlineWidth: style.outlineWidth,
      outlineColor: style.outlineColor,
      width: rect.width,
      height: rect.height,
    }
  }
  return {
    pane: read('#batch-detail-pane'),
    box: read('.batch-resource-box'),
    firstMetric: read('.batch-resource-metric'),
    firstSample: read('.batch-resource-sample'),
    filterBox: read('.batch-draft-filter-form'),
    link: read('#batch-preview-open-resources'),
    advanced: read('.batch-draft-advanced'),
    advancedSummary: read('.batch-draft-advanced > summary'),
    regexBox: read('#batch-preview-use-regex'),
    bodyScrollWidth: document.body.scrollWidth,
    viewportWidth: window.innerWidth,
  }
}
"""


def _open_batch_draft(page: Page, live_server_url: str, width: int = 1440, height: int = 900) -> None:
    require_dist()
    page.emulate_media(reduced_motion="reduce")
    _open_compact_list(page, live_server_url, _compact_items(1))
    # _open_compact_list 固定 1440×900 验收画布；窄屏档位在它之后设置才生效，
    # 视口高度变化会改变两屏几何，因此把文档重新对齐到工作台顶部再测量。
    page.set_viewport_size({"width": width, "height": height})
    page.evaluate(
        """() => {
          const screen = document.querySelector('.batch-workbench-screen')
          const padding = Number.parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 0
          window.scrollTo({ top: screen.getBoundingClientRect().top + window.scrollY - padding, behavior: 'auto' })
        }"""
    )
    wait_for_scroll_idle(page)
    page.locator('.batch-draft-card[data-item-id="item-00"]').click()
    page.wait_for_selector("#batch-detail-pane .batch-resource-box", timeout=10_000)


def test_right_pane_padding_resource_box_and_advanced_settings(page: Page, live_server_url: str) -> None:
    _open_batch_draft(page, live_server_url)
    styles = page.evaluate(_PANE_SCRIPT)

    # #157：常规桌面右栏内边距 24px。
    assert styles["pane"]["paddingTop"] == "24px", styles["pane"]
    assert styles["pane"]["paddingLeft"] == "24px", styles["pane"]

    # 资源结果与「字幕与筛选」同一描边盒子层级：边框、圆角、背景、内边距一致。
    box, filter_box = styles["box"], styles["filterBox"]
    assert box is not None and filter_box is not None, styles
    assert box["borderTopWidth"] == "1px", box
    assert box["borderRadius"] == filter_box["borderRadius"], (box, filter_box)
    assert box["backgroundColor"] == filter_box["backgroundColor"], (box, filter_box)
    assert box["paddingTop"] != "0px" and box["paddingLeft"] != "0px", box

    # 盒内没有无设计依据的横/竖分割线。
    assert styles["firstMetric"]["borderLeftWidth"] == "0px", styles["firstMetric"]
    assert styles["firstSample"]["borderBottomWidth"] == "0px", styles["firstSample"]

    # 两项资源计数 + 两个「未开发」集数占位仍在，不增后端数据。
    expect(page.locator(".batch-resource-metric")).to_have_count(4)
    expect(page.locator('.batch-resource-metric[data-metric="updated-episodes"]')).to_contain_text("未开发")
    expect(page.locator('.batch-resource-metric[data-metric="total-episodes"]')).to_contain_text("未开发")
    expect(page.locator('[data-metric="effective"]')).to_contain_text("有效资源")
    expect(page.locator('[data-metric="excluded"]')).to_contain_text("已排除")

    # 高级设置默认折叠，展开后紧凑并使用共享 18px 复选框。
    assert page.locator(".batch-draft-advanced").evaluate("(el) => el.open") is False
    page.click(".batch-draft-advanced > summary")
    expanded = page.evaluate(_PANE_SCRIPT)
    assert styles["advancedSummary"]["fontSize"] == "14px", expanded["advancedSummary"]
    assert expanded["advancedSummary"]["height"] <= 30, expanded["advancedSummary"]
    assert abs(expanded["regexBox"]["width"] - 18) <= TOLERANCE, expanded["regexBox"]
    assert expanded["regexBox"]["borderTopWidth"] == "1px", expanded["regexBox"]

    # 资源入口默认 primary 蓝；hover 淡蓝圆角背景；键盘聚焦有可见焦点。
    assert styles["link"]["color"] == PRIMARY_RGB, styles["link"]
    page.locator("#batch-preview-open-resources").hover()
    hovered = page.evaluate(_PANE_SCRIPT)
    assert hovered["link"]["backgroundColor"] == PRIMARY_SUBTLE_RGB, hovered["link"]
    assert hovered["link"]["borderRadius"] != "0px", hovered["link"]
    page.locator("#batch-preview-open-resources").focus()
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Tab")
    focused = page.evaluate(_PANE_SCRIPT)
    assert focused["link"]["outlineWidth"] == "3px", focused["link"]
    assert focused["link"]["outlineColor"] == FOCUS_RGB, focused["link"]


def test_resource_entry_opens_dialog_and_restores_focus_and_scroll(page: Page, live_server_url: str) -> None:
    _open_batch_draft(page, live_server_url)
    before = page.evaluate("() => document.querySelector('#batch-detail-pane').scrollTop")

    page.locator("#batch-preview-open-resources").focus()
    page.keyboard.press("Enter")
    dialog = page.locator('[role="dialog"][aria-labelledby]').last
    expect(page.locator("#batch-resource-detail-tab-effective")).to_be_visible()
    expect(page.locator("#batch-resource-detail-tab-excluded")).to_be_visible()
    page.click("#batch-resource-detail-tab-excluded")
    expect(page.locator("#batch-resource-detail-panel-excluded")).to_be_visible()
    page.click("#batch-resource-detail-close")
    expect(page.locator("#batch-resource-detail-panel-excluded")).to_have_count(0)

    # 关闭后焦点回到入口；右栏滚动位置不变。
    after_focus = page.evaluate("() => document.activeElement && document.activeElement.id")
    assert after_focus == "batch-preview-open-resources", after_focus
    after = page.evaluate("() => document.querySelector('#batch-detail-pane').scrollTop")
    assert abs(after - before) <= TOLERANCE, (before, after)
    assert dialog is not None


@pytest.mark.parametrize(("width", "height", "padding"), [(1280, 800, "24px"), (1920, 1080, "24px"), (1000, 800, "16px")])
def test_pane_padding_tier_and_reachability(
    page: Page, live_server_url: str, width: int, height: int, padding: str
) -> None:
    _open_batch_draft(page, live_server_url, width=width, height=height)
    styles = page.evaluate(_PANE_SCRIPT)
    assert styles["pane"]["paddingLeft"] == padding, (width, styles["pane"])
    assert styles["bodyScrollWidth"] <= styles["viewportWidth"] + 1, styles

    # 右栏滚到底：末项（高级设置）在栏内可达，固定底栏仍完整可见。
    page.evaluate("() => { document.querySelector('#batch-detail-pane').scrollTop = 1e6 }")
    reachable = page.evaluate(
        """() => {
          const pane = document.querySelector('#batch-detail-pane').getBoundingClientRect()
          const last = document.querySelector('.batch-draft-advanced').getBoundingClientRect()
          const toolbar = document.querySelector('#batch-accept-toolbar').getBoundingClientRect()
          return { lastBottom: last.bottom, paneBottom: pane.bottom, toolbarTop: toolbar.top, toolbarBottom: toolbar.bottom, viewport: window.innerHeight }
        }"""
    )
    assert reachable["lastBottom"] <= reachable["paneBottom"] + 1, reachable
    assert reachable["paneBottom"] <= reachable["toolbarTop"] + 1, reachable
    assert reachable["toolbarBottom"] <= reachable["viewport"] + 1, reachable
    expect(page.locator("#batch-preview-open-resources")).to_be_visible()


def test_pane_holds_under_two_hundred_percent_zoom(page: Page, live_server_url: str) -> None:
    """720 CSS 视口等效 1440 桌面 200% 缩放：右栏仍可达且无横向溢出。"""
    _open_batch_draft(page, live_server_url, width=720, height=450)
    styles = page.evaluate(_PANE_SCRIPT)
    assert styles["bodyScrollWidth"] <= styles["viewportWidth"] + 1, styles
    expect(page.locator("#batch-detail-pane .batch-resource-box")).to_be_visible()
    expect(page.locator("#batch-preview-open-resources")).to_be_visible()

FIXTURE = FixtureDescriptor(
    fixture_id="batch-draft-panel-safe",
    description="固定安全 fixture：离线草案、确定性海报与安全资源样例；不连接真实 MiKan／AB／qB。",
    mock_routes=("/api/v1/batches/parse", "/api/v1/requests"),
)


def _capture(
    page: Page,
    recorder: LoadedResourceRecorder,
    tmp_path: Path,
    live_server_url: str,
    scenario_id: str,
    title: str,
    steps: tuple[str, ...],
) -> dict[str, Any]:
    screenshot = tmp_path / f"{scenario_id}.png"
    capture_canvas(page, screenshot)
    manifest = capture_evidence(
        page,
        screenshot,
        base_url=live_server_url,
        scenario=ScenarioDescriptor(scenario_id, title, steps),
        fixture=FIXTURE,
        resources=recorder.records(),
        route="/app/workbench",
    )
    write_manifest(manifest, tmp_path, scenario_id)
    return json.loads((tmp_path / f"{scenario_id}.evidence.json").read_text(encoding="utf-8"))


def test_1440_review_captures_ship_with_evidence_manifests(
    page: Page, live_server_url: str, tmp_path: Path
) -> None:
    """#157／#155：默认态、高级设置展开、入口 hover／focus 与双页签截图各随附证据清单。"""
    require_dist()
    recorder = LoadedResourceRecorder(live_server_url)
    recorder.attach(page)
    _open_batch_draft(page, live_server_url)

    payloads: dict[str, dict[str, Any]] = {}
    payloads["default"] = _capture(
        page, recorder, tmp_path, live_server_url, "batch-draft-default-1440x900",
        "批量草案右栏默认态", ("1440×900 打开 /app/workbench", "选中条目 item-00", "等待右栏资源盒子渲染后截图"),
    )

    page.click(".batch-draft-advanced > summary")
    payloads["advanced"] = _capture(
        page, recorder, tmp_path, live_server_url, "batch-draft-advanced-expanded-1440x900",
        "批量草案高级设置展开", ("默认态基础上展开高级设置", "等待正则／大小写与目录字段可见"),
    )

    page.locator("#batch-preview-open-resources").hover()
    payloads["hover"] = _capture(
        page, recorder, tmp_path, live_server_url, "batch-draft-resource-link-hover-1440x900",
        "资源入口 hover", ("鼠标悬停在「查看完整资源列表」",),
    )

    page.locator("#batch-preview-open-resources").focus()
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Tab")
    payloads["focus"] = _capture(
        page, recorder, tmp_path, live_server_url, "batch-draft-resource-link-focus-1440x900",
        "资源入口键盘焦点", ("用键盘导航把焦点移到「查看完整资源列表」",),
    )

    page.keyboard.press("Enter")
    expect(page.locator("#batch-resource-detail-tab-effective")).to_be_visible()
    payloads["dialog_effective"] = _capture(
        page, recorder, tmp_path, live_server_url, "batch-resource-dialog-effective-1440x900",
        "资源明细弹窗（有效资源页签）", ("键盘 Enter 打开资源明细", "停在有效资源页签"),
    )
    page.click("#batch-resource-detail-tab-excluded")
    payloads["dialog_excluded"] = _capture(
        page, recorder, tmp_path, live_server_url, "batch-resource-dialog-excluded-1440x900",
        "资源明细弹窗（已排除页签）", ("切到已排除页签",),
    )

    digests = set()
    for name, payload in payloads.items():
        assert payload["screenshot"]["sha256"], name
        assert payload["build"]["artifact_digest"], name
        assert payload["runtime"]["viewport"] == {"width": 1440, "height": 900}, name
        assert any(resource["path"].startswith("/app/assets/") for resource in payload["page"]["loaded_resources"]), name
        digests.add(payload["screenshot"]["sha256"])
    # 每个状态都是独立画面，不是同一张截图重复贴清单。
    assert len(digests) == len(payloads), sorted(digests)
    assert file_digest(tmp_path / "batch-draft-default-1440x900.png") == payloads["default"]["screenshot"]["sha256"]

