"""#153：批量草案工作台的真实 Chromium 验收与视觉基准候选。

覆盖（父规格 #145 的验收目标）：

- 草案默认态 / 标题搜索浮层 / 资源明细（有效资源与已排除）在 1440×900 的真实
  截图与关键几何；
- 1／12／36 部、1280×800／1440×900／1920×1080 与 200% 缩放下的单行底栏、
  末项可达、滚动条不可见但导航可用；
- 资源明细弹窗的页签、焦点恢复与工作台滚动位置；
- 固定安全 fixture 各状态连续三次稳定，才允许作为视觉回归基准候选提交用户审核。

截图、diff 与诊断值只写 pytest ``tmp_path``。只有显式设置
``MIGU_ORCA_CAPTURE_REVIEW=1`` 时，才会把候选图写到
``docs/design/assets/frontend-ux/acceptance-baseline/add-anime/pending-batch-draft/``
供用户审核；在用户明确认可前它们不是回归基准，也不得直接替换既有基准。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from playwright.sync_api import Page, expect

from tests.browser.batch_draft_visual_fixtures import (
    BATCH_ID,
    CHECKED_ITEM_IDS,
    CLICKED_ITEM_ID,
    DRAFT_LINES,
    REVIEW_DIR,
    BatchDraftVisualScenario,
    batch_draft_items,
    canary_values,
    raw_input_for,
    repeat_items,
)
from tests.browser.visual_manifest import SHELL_ANCHORS
from tests.browser.visual_support import (
    CANVAS,
    anchor_summary,
    browser_surface,
    capture_canvas,
    compare_with_design,
    report_json,
    stability_noise_pixels,
)
from tests.visual.compare import compare_images, read_image

pytestmark = pytest.mark.browser

CAPTURE_STATES: tuple[str, ...] = (
    "draft-workbench",
    "title-search",
    "resource-detail-effective",
    "resource-detail-excluded",
)


class TestBatchDraftWorkbenchVisual:
    """AC：固定 fixture 可确定性进入、可测量、可连续三次稳定截图。"""

    def _scenario(
        self,
        page: Page,
        live_server_url: str,
        storage_dir: Path,
        *,
        items: list[dict[str, Any]] | None = None,
    ) -> BatchDraftVisualScenario:
        scenario = BatchDraftVisualScenario(page, live_server_url)
        scenario.install(storage_dir, items=items)
        return scenario

    def _capture_state(
        self,
        scenario: BatchDraftVisualScenario,
        name: str,
        tmp_path: Path,
        *,
        suffix: str = "",
    ) -> Path:
        """按状态名把页面推进到目标状态并截图（幂等，可重复调用）。"""
        scenario.goto_state(name)
        scenario.dismiss_toast()
        return capture_canvas(scenario.page, tmp_path / f"{name}{suffix}.png")

    def test_draft_workbench_geometry_targets_the_approved_direction(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """AC：#145 的信息层级与单行底栏在真实 Chromium 中成立。"""
        scenario = self._scenario(page, live_server_url, storage_dir)
        scenario.enter_draft_workbench()

        geometry = page.evaluate(
            """() => {
                const box = (selector) => {
                    const element = document.querySelector(selector)
                    return element ? element.getBoundingClientRect() : null
                }
                const list = document.querySelector('.batch-card-grid-wrapper')
                const pane = document.querySelector('#batch-detail-pane')
                return {
                    toolbar: box('#batch-accept-toolbar'),
                    row: box('.batch-accept-row'),
                    checkbox: box('#batch-select-all-checkbox'),
                    count: box('#batch-accept-selected-count'),
                    submit: box('#batch-accept-submit'),
                    list: box('.batch-card-grid-wrapper'),
                    pane: box('#batch-detail-pane'),
                    poster: box('.batch-draft-card[data-item-id="item-01"] .batch-card-poster'),
                    listScrollbar: getComputedStyle(list).scrollbarWidth,
                    paneScrollbar: getComputedStyle(pane).scrollbarWidth,
                    listGutter: list.offsetWidth - list.clientWidth,
                    paneGutter: pane.offsetWidth - pane.clientWidth -
                        (parseFloat(getComputedStyle(pane).borderLeftWidth) || 0) * 2,
                    documentWidth: document.body.scrollWidth,
                    viewportWidth: window.innerWidth,
                }
            }"""
        )
        # 单行底栏：复选框、精简计数与唯一主入口同排。
        centers = [
            geometry[key]["y"] + geometry[key]["height"] / 2
            for key in ("checkbox", "count", "submit")
        ]
        assert max(centers) - min(centers) <= 6, centers
        assert geometry["toolbar"]["height"] <= geometry["row"]["height"] + 24, geometry
        expect(page.locator("#batch-accept-all")).to_have_count(0)
        expect(page.locator("#batch-accept-selected-count")).to_contain_text("已选 2 部")
        expect(page.locator("#batch-accept-submit")).to_contain_text("保存并确认 2 部")

        # 双栏：左右各占一列，滚动条隐藏且不占槽。
        assert geometry["list"]["right"] <= geometry["pane"]["left"] + 0.5, geometry
        assert geometry["listScrollbar"] == "none"
        assert geometry["paneScrollbar"] == "none"
        assert geometry["listGutter"] == 0
        assert geometry["paneGutter"] == 0
        # 紧凑条目卡：封面约 44px、页面无横向溢出。
        assert 40 <= geometry["poster"]["height"] <= 52, geometry
        assert geometry["documentWidth"] <= geometry["viewportWidth"] + 1, geometry

        # 右栏信息层级：合集身份 → 字幕与筛选 → 资源结果 → 折叠的高级设置。
        pane_text = page.locator("#batch-detail-pane").inner_text()
        assert "已选真实合集" in pane_text
        assert "字幕与筛选" in pane_text
        assert "资源结果" in pane_text
        expect(page.locator('[data-metric="updated-episodes"]')).to_contain_text("未开发")
        expect(page.locator('[data-metric="total-episodes"]')).to_contain_text("未开发")
        assert "加入批量确认" not in pane_text
        expect(page.locator("#batch-preview-folder-name")).to_be_hidden()

        # 默认层只放少量安全示例（最多两条）；完整种子分组列表与旧技术详情都不在这里。
        samples = page.locator(".batch-resource-sample")
        assert 1 <= samples.count() <= 2, samples.count()
        expect(page.locator(".complete-seed-details")).to_have_count(0)
        expect(page.locator(".advanced-detail")).to_have_count(0)
        assert scenario.external_calls == []

    def test_title_search_popover_does_not_move_the_layout(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """AC：#149 浮层打开/关闭都不改变筛选控件、卡片与底栏的几何位置。"""
        scenario = self._scenario(page, live_server_url, storage_dir)
        scenario.enter_draft_workbench()

        script = """() => {
            const box = (selector) => {
                const element = document.querySelector(selector)
                const rect = element.getBoundingClientRect()
                return [rect.x, rect.y, rect.width, rect.height]
            }
            return {
                filters: box('.batch-review-filters'),
                firstCard: box('.batch-draft-card'),
                toolbar: box('#batch-accept-toolbar'),
            }
        }"""
        def close_enough(first: dict[str, list[float]], second: dict[str, list[float]]) -> None:
            for key in first:
                assert all(abs(a - b) <= 0.5 for a, b in zip(first[key], second[key], strict=True)), (
                    key,
                    first,
                    second,
                )

        # 展开浮层本身不推挤筛选控件、卡片或底栏。
        before = page.evaluate(script)
        page.click("#batch-review-search-toggle")
        page.wait_for_selector("#batch-review-search", timeout=5000)
        expect(page.locator("#batch-review-search")).to_be_visible()
        close_enough(before, page.evaluate(script))

        # 输入关键词后筛选生效；此时再关闭浮层，只有浮层消失，布局不位移。
        page.fill("#batch-review-search", "迷宫")
        expect(page.locator(".batch-draft-card")).to_have_count(1)
        filtered = page.evaluate(script)
        page.keyboard.press("Escape")
        expect(page.locator("#batch-review-search")).to_have_count(0)
        close_enough(filtered, page.evaluate(script))

        # 关闭后关键词与筛选结果保留，放大镜如实反映筛选状态。
        expect(page.locator(".batch-draft-card")).to_have_count(1)
        expect(page.locator("#batch-review-search-toggle")).to_have_class(re.compile(r"is-active"))
        expect(page.locator("#batch-review-search-toggle")).to_have_attribute("aria-label", "标题搜索（已筛选）")
        assert scenario.external_calls == []

    def test_resource_detail_dialog_keeps_tabs_focus_and_scroll(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """AC：#151 页签、在弹窗内滚动、关闭后焦点与工作台滚动位置恢复。"""
        scenario = self._scenario(page, live_server_url, storage_dir)
        scenario.enter_draft_workbench()

        page.evaluate("() => { document.querySelector('#batch-detail-pane').scrollTop = 40 }")
        before_scroll = page.evaluate(
            "() => ({ pane: document.querySelector('#batch-detail-pane').scrollTop, window: window.scrollY })"
        )
        trigger = page.locator("#batch-preview-open-resources")
        trigger.focus()
        trigger.click()
        page.wait_for_selector(".resource-dialog", timeout=5000)

        dialog = page.locator(".resource-dialog")
        expect(dialog).to_have_attribute("aria-modal", "true")
        expect(dialog.locator("#batch-resource-detail-tab-effective")).to_have_attribute("aria-selected", "true")
        expect(dialog.locator("#batch-resource-detail-panel-effective")).to_be_visible()
        expect(dialog.locator("#batch-resource-detail-count")).to_contain_text("共")

        dialog.locator("#batch-resource-detail-tab-excluded").click()
        excluded_panel = dialog.locator("#batch-resource-detail-panel-excluded")
        expect(excluded_panel).to_be_visible()
        excluded_text = excluded_panel.inner_text()
        # 安全投影：不出现 URL、magnet 或本地路径。
        assert "magnet:" not in excluded_text
        assert "http" not in excluded_text
        assert "[已隐藏" in excluded_text or "排除" in excluded_text

        page.keyboard.press("Escape")
        expect(page.locator(".resource-dialog")).to_have_count(0)
        after_scroll = page.evaluate(
            "() => ({ pane: document.querySelector('#batch-detail-pane').scrollTop, window: window.scrollY })"
        )
        assert after_scroll == before_scroll, (before_scroll, after_scroll)
        assert page.evaluate("() => document.activeElement && document.activeElement.id") == (
            "batch-preview-open-resources"
        )
        assert scenario.external_calls == []

    @pytest.mark.parametrize(
        "width,height,zoom",
        [(1280, 800, 1), (1440, 900, 1), (1920, 1080, 1), (1280, 800, 2)],
    )
    def test_desktop_matrix_keeps_one_row_and_reachable_items(
        self, page: Page, live_server_url: str, storage_dir: Path, width: int, height: int, zoom: int
    ) -> None:
        """AC：三档桌面与 200% 缩放下底栏保持一行、末项可达、无横向溢出。"""
        scenario = self._scenario(page, live_server_url, storage_dir)
        page.set_viewport_size({"width": width, "height": height})
        scenario.enter_draft_workbench()
        if zoom == 2:
            page.evaluate("() => { document.documentElement.style.zoom = '2' }")

        geometry = page.evaluate(
            """() => {
                const toolbar = document.querySelector('#batch-accept-toolbar').getBoundingClientRect()
                const row = document.querySelector('.batch-accept-row').getBoundingClientRect()
                return {
                    toolbarHeight: toolbar.height,
                    rowHeight: row.height,
                    documentWidth: document.body.scrollWidth,
                    viewportWidth: window.innerWidth,
                }
            }"""
        )
        if zoom == 1:
            # 桌面档位：正常运行态只有一行，底栏与唯一主入口都留在视口内。
            assert geometry["toolbarHeight"] <= geometry["rowHeight"] + 24, geometry
            expect(page.locator("#batch-accept-selected-scope")).to_have_count(0)
            expect(page.locator("#batch-accept-submit")).to_be_in_viewport()
        else:
            # 200% 缩放：允许底栏自然换行，也允许工作台屏自身滚动兜底；
            # 关键是唯一主入口仍可滚动到达并可用。
            assert geometry["toolbarHeight"] <= geometry["rowHeight"] * 3 + 24, geometry
            page.locator("#batch-accept-submit").scroll_into_view_if_needed()
            expect(page.locator("#batch-accept-submit")).to_be_visible()
            expect(page.locator("#batch-accept-submit")).to_be_enabled()
        assert geometry["documentWidth"] <= geometry["viewportWidth"] + 1, geometry

        # 末项可达：滚到底后最后一张卡完整落在左栏可视区内、底栏之上。
        page.evaluate(
            """() => {
                const list = document.querySelector('.batch-card-grid-wrapper')
                list.scrollTop = list.scrollHeight
            }"""
        )
        last = page.evaluate(
            """() => {
                const cards = document.querySelectorAll('.batch-draft-card')
                const card = cards[cards.length - 1].getBoundingClientRect()
                const list = document.querySelector('.batch-card-grid-wrapper').getBoundingClientRect()
                const toolbar = document.querySelector('#batch-accept-toolbar').getBoundingClientRect()
                return { cardBottom: card.bottom, listBottom: list.bottom, toolbarTop: toolbar.top }
            }"""
        )
        assert last["cardBottom"] <= last["listBottom"] + 1, last
        assert last["cardBottom"] <= last["toolbarTop"] + 1, last
        assert scenario.external_calls == []

    @pytest.mark.parametrize("count", [1, 12, 36])
    def test_boundary_batch_sizes_keep_the_single_row_toolbar(
        self, page: Page, live_server_url: str, storage_dir: Path, count: int
    ) -> None:
        """AC：1／12／36 部都不改变底栏的一行结构与唯一入口。"""
        items = repeat_items(count)
        scenario = self._scenario(page, live_server_url, storage_dir, items=items)
        checked = ("item-00",) if count == 1 else ("item-00", "item-01")
        scenario.enter_workbench(checked_item_ids=checked, click_item_id="item-00")

        expect(page.locator(".batch-draft-card")).to_have_count(count)
        expect(page.locator("#batch-accept-submit")).to_contain_text(f"保存并确认 {len(checked)} 部")
        expect(page.locator("#batch-accept-submit")).to_be_in_viewport()
        assert page.evaluate("() => document.body.scrollWidth <= window.innerWidth + 1")
        if count > 3:
            assert page.evaluate(
                "() => { const list = document.querySelector('.batch-card-grid-wrapper'); return list.scrollHeight > list.clientHeight }"
            ) is True
        assert scenario.external_calls == []

    def test_every_review_state_is_stable_across_three_captures(
        self, page: Page, live_server_url: str, storage_dir: Path, tmp_path: Path
    ) -> None:
        """AC：各状态连续三次截图尺寸与 DOM 锚点严格一致，差异只在噪声带内。"""
        scenario = self._scenario(page, live_server_url, storage_dir)
        scenario.enter_draft_workbench()

        canvas_pixels = CANVAS[0] * CANVAS[1]
        # #145：连续三次的显著差异像素上限（0.5% 画布）；同环境的栅格化噪声远低于它。
        significant_limit = round(canvas_pixels * 0.005)
        for state in CAPTURE_STATES:
            sizes: list[tuple[int, int]] = []
            anchors: list[dict[str, Any]] = []
            shots: list[Path] = []
            reports: list[dict[str, Any]] = []
            for run in range(3):
                shot = self._capture_state(scenario, state, tmp_path, suffix=f"-run{run}")
                with Image.open(shot) as captured:
                    sizes.append(captured.size)
                anchors.append(anchor_summary(page, SHELL_ANCHORS))
                shots.append(shot)
                # 设计图只用于诊断：按像素门禁裁决 3C 不启用设计图 ≤0.5% 硬阈值。
                reports.append(
                    compare_with_design(6, shot, diff_path=tmp_path / f"{state}-run{run}-diff.png").as_report()
                )
            assert sizes[0] == sizes[1] == sizes[2] == CANVAS, (state, sizes)
            assert report_json(anchors[0]) == report_json(anchors[1]) == report_json(anchors[2]), state
            # 设计图对比只作诊断（像素门禁裁决 3C 未对设计图启用阈值）；稳定性由
            # 下面的「连续截图彼此比较」严格证明。
            for report in reports:
                assert 0.0 <= float(report["diff_ratio"]) <= 1.0, (state, report["diff_ratio"])
            # 连续截图彼此比较：只允许同环境的栅格化噪声，且远低于 0.5% 口径。
            for first, second in ((shots[0], shots[1]), (shots[1], shots[2])):
                stats = compare_images(
                    read_image(first, error_code="actual_unreadable"),
                    read_image(second, error_code="actual_unreadable"),
                    diff_path=tmp_path / f"{state}-consecutive-diff.png",
                )
                assert stats.diff_pixels <= stability_noise_pixels(canvas_pixels), (
                    state,
                    stats.diff_pixels,
                )
                assert stats.diff_pixels <= significant_limit, (state, stats.diff_pixels)

    def test_canary_never_reaches_browser_surfaces_or_artifacts(
        self, page: Page, live_server_url: str, storage_dir: Path, tmp_path: Path
    ) -> None:
        """AC：真实草案能力标识不进入 URL、存储、DOM、日志或截图像素。"""
        scenario = self._scenario(page, live_server_url, storage_dir)
        scenario.enter_draft_workbench()
        scenario.open_resource_dialog("effective")
        scenario.dismiss_toast()

        shot = capture_canvas(page, tmp_path / "batch-draft-canary.png")
        surface = browser_surface(page)
        canaries = canary_values(scenario.items)
        assert canaries
        for canary in canaries:
            assert canary not in surface["url"]
            assert canary not in surface["historyState"]
            assert canary not in surface["localStorage"]
            assert canary not in surface["sessionStorage"]
            assert canary not in surface["bodyText"]
            assert canary not in surface["attributes"]
            assert all(canary not in message for message in scenario.console_messages)
            assert canary.encode() not in shot.read_bytes()

    def test_review_candidates_are_written_only_when_requested(
        self, page: Page, live_server_url: str, storage_dir: Path, tmp_path: Path
    ) -> None:
        """AC：仅显式请求时写候选图到 pending 审核目录供用户审核。

        默认（CI 与普通本地运行）只截图到 ``tmp_path``；候选图在用户明确认可前
        不是视觉回归基准，也不得直接替换基准。
        """
        scenario = self._scenario(page, live_server_url, storage_dir)
        scenario.enter_draft_workbench()

        captured: dict[str, Path] = {}
        for state in CAPTURE_STATES:
            captured[state] = self._capture_state(scenario, state, tmp_path)

        written = [
            target
            for state, shot in captured.items()
            if (target := scenario.write_review_screenshot(f"{state}.png", shot)) is not None
        ]
        if not scenario.review_screenshots_enabled():
            assert written == []
            return
        assert written, "显式请求审核截图时应当写出候选图"
        for target in written:
            assert target.is_file()
            with Image.open(target) as image:
                assert image.size == CANVAS
        for target in written:
            payload = target.read_bytes()
            for canary in canary_values(scenario.items):
                assert canary.encode() not in payload


def test_fixture_covers_the_designed_batch_states() -> None:
    """fixture 自身覆盖设计图要求的条目状态，避免视觉用例退化成单一状态。"""
    items = batch_draft_items()
    assert len(items) == len(DRAFT_LINES)
    statuses = [item["status"] for item in items]
    assert statuses.count("DRAFT") == 3
    assert statuses.count("FOUND") == 1
    assert statuses.count("FAILED") == 1
    assert all(item["item_id"] for item in items)
    assert all(item["preview_request"] is None or item["draft_id"] for item in items)
    assert BATCH_ID in json.dumps(items, ensure_ascii=False)
    assert raw_input_for(items).count("\n") + 1 == len(DRAFT_LINES)
    assert CHECKED_ITEM_IDS and CLICKED_ITEM_ID in CHECKED_ITEM_IDS
    assert REVIEW_DIR.name == "pending-batch-draft"
    assert len(canary_values(items)) >= 3
    assert len(repeat_items(36)) == 36
