"""Stage 46 / US-360：批量图 04～06 的真实 Chromium 视觉 fixture 用例。

与单番一致：截图、锚点与比较统计只写 pytest ``tmp_path``，页面专属区域只记录
诊断值。D-02/D-04 语义与 1/12/36 边界用既有服务端契约的构造器验证，不伪造。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from playwright.sync_api import Page, expect

from tests.browser.batch_visual_fixtures import (
    BATCH_RAW_INPUT,
    BATCH_RAW_LINES,
    BatchVisualScenario,
    batch_candidate,
    batch_item,
    mixed_batch_items,
)
from tests.browser.visual_manifest import SHELL_ANCHORS
from tests.browser.visual_support import (
    CANVAS,
    anchor_summary,
    browser_surface,
    capture_canvas,
    compare_with_design,
    report_json,
)

pytestmark = pytest.mark.browser

FIGURE_ENTRY = {
    4: "enter_figure_04",
    5: "enter_figure_05",
    6: "enter_figure_06",
}


class TestAppBatchVisualFixtures:
    """AC: 图 04～06 由真实契约形状可确定性进入，并可重复测量。"""

    def _scenario(
        self,
        page: Page,
        live_server_url: str,
        storage_dir: Path,
        *,
        items: list[dict[str, Any]] | None = None,
    ) -> BatchVisualScenario:
        scenario = BatchVisualScenario(page, live_server_url)
        scenario.install(storage_dir, items=items)
        return scenario

    def test_figure_04_holds_six_line_search_with_honest_progress(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        scenario = self._scenario(page, live_server_url, storage_dir)
        scenario.enter_figure_04()

        expect(page.locator("#batch-parse-loading-summary")).to_contain_text("整体搜索进行中")
        expect(page.locator("#batch-parse-loading-summary")).to_contain_text("本次提交规模：6 部")
        expect(page.locator("#batch-input-count")).to_contain_text("当前 6 部")
        assert page.input_value("#batch-raw-input") == BATCH_RAW_INPUT
        # 不伪造逐条百分比：没有进度条元素。
        assert page.evaluate("() => document.querySelectorAll('progress').length") == 0
        assert scenario.external_calls == []

    def test_figure_05_mixes_candidate_draft_and_failure_states(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        scenario = self._scenario(page, live_server_url, storage_dir)
        scenario.enter_figure_05()

        cards = page.locator(".batch-draft-card")
        expect(cards).to_have_count(len(BATCH_RAW_LINES))
        statuses = page.locator(".batch-draft-card .batch-card-status").all_inner_texts()
        assert len(statuses) == len(BATCH_RAW_LINES)
        assert sum("搜索失败" in status for status in statuses) == 1
        assert sum("草案" in status for status in statuses) == 2
        assert sum("找到候选" in status for status in statuses) == 3
        # 当前查看第一项，其候选就地 loading，其余 item 仍可操作。
        detail = page.locator("#batch-detail-pane")
        expect(detail).to_be_visible()
        loading = detail.locator(".candidate-select[aria-busy='true']")
        expect(loading).to_have_count(1)
        assert "有效资源" not in detail.inner_text()

    def test_figure_06_two_manual_checks_are_confirmable(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        scenario = self._scenario(page, live_server_url, storage_dir)
        scenario.enter_figure_06()

        expect(page.locator("#batch-accept-selected-count")).to_contain_text("已选且可确认 2 项")
        expect(page.locator("#batch-accept-selected-count")).to_contain_text("完整批次 6 部")
        submit = page.locator("#batch-accept-submit")
        expect(submit).to_be_visible()
        assert "primary-button" in (submit.get_attribute("class") or "")
        expect(page.locator("#batch-detail-pane")).to_be_visible()
        # Stage 45 语义：右栏不复制主按钮。
        expect(page.locator("#batch-detail-pane .primary-button")).to_have_count(0)
        # D-04：fixture 不触发导航，仍停留在添加页。
        assert "/app/add" in page.url

    def test_fixture_preserves_hidden_check_and_visible_select_all_semantics(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """D-02：筛选隐藏的手工勾选仍参与范围；可见全选只改可见项。"""
        scenario = self._scenario(page, live_server_url, storage_dir)
        scenario.enter_figure_06()

        page.fill("#batch-review-search", "迷宫")
        expect(page.locator(".batch-draft-card")).to_have_count(1)
        counts = page.locator("#batch-accept-selected-count")
        expect(counts).to_contain_text("已选且可确认 2 项")
        expect(counts).to_contain_text("其中被筛选隐藏仍参与 1 项")

    @pytest.mark.parametrize("count", [1, 12, 36])
    def test_constructor_keeps_one_twelve_thirty_six_boundaries(
        self, page: Page, live_server_url: str, storage_dir: Path, count: int
    ) -> None:
        items = [
            batch_item(
                f"item-{index:02d}",
                f"番剧{index:02d}",
                status="FOUND",
                canonical_title=f"番剧{index:02d} 第一季",
                candidates=[
                    batch_candidate(
                        bangumi_id=f"8{index:03d}",
                        title=f"番剧{index:02d} 第一季",
                        season=1,
                        total_episodes=12,
                        source_query=f"番剧{index:02d}",
                    )
                ],
            )
            for index in range(count)
        ]
        scenario = self._scenario(page, live_server_url, storage_dir, items=items)
        scenario.open_batch_input()
        page.fill("#batch-raw-input", "\n".join(f"番剧{index:02d}" for index in range(count)))
        page.click("#batch-parse-submit")
        scenario.wait_for_held(scenario.held_parse, 1)
        scenario.release_parse(count)
        expect(page.locator(".batch-draft-card")).to_have_count(count)
        expect(page.locator("#batch-input-count")).to_contain_text(f"当前 {count} 部")

    def test_canary_never_reaches_browser_surfaces_or_artifacts(
        self, page: Page, live_server_url: str, storage_dir: Path, tmp_path: Path
    ) -> None:
        scenario = self._scenario(page, live_server_url, storage_dir)
        scenario.enter_figure_06()

        shot = capture_canvas(page, tmp_path / "figure-06-canary.png")
        diff = tmp_path / "figure-06-canary-diff.png"
        compare_with_design(6, shot, diff_path=diff)

        surface = browser_surface(page)
        canaries = scenario.canary_values()
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
            assert canary.encode() not in diff.read_bytes()
        assert scenario.save_confirm_calls == []

    def test_screenshots_are_canvas_sized_and_compare_against_design(
        self, page: Page, live_server_url: str, storage_dir: Path, tmp_path: Path
    ) -> None:
        scenario = self._scenario(page, live_server_url, storage_dir)
        for index, entry in FIGURE_ENTRY.items():
            getattr(scenario, entry)()
            shot = capture_canvas(page, tmp_path / f"figure-{index:02d}.png")
            with Image.open(shot) as captured:
                assert captured.size == CANVAS
            diff = tmp_path / f"figure-{index:02d}-diff.png"
            stats = compare_with_design(index, shot, diff_path=diff)
            assert stats.diff_written is True
            report = stats.as_report()
            assert report["compared_pixels"] == CANVAS[0] * CANVAS[1]
            assert 0.0 <= report["diff_ratio"] <= 1.0
            print(f"figure-{index:02d} diagnostic diff_ratio={report['diff_ratio']}")

    def test_three_consecutive_captures_are_stable(
        self, page: Page, live_server_url: str, storage_dir: Path, tmp_path: Path
    ) -> None:
        scenario = self._scenario(page, live_server_url, storage_dir)
        for index, entry in FIGURE_ENTRY.items():
            sizes: list[tuple[int, int]] = []
            anchors: list[dict[str, Any]] = []
            reports: list[dict[str, Any]] = []
            for run in range(3):
                getattr(scenario, entry)()
                shot = capture_canvas(page, tmp_path / f"figure-{index:02d}-run{run}.png")
                with Image.open(shot) as captured:
                    sizes.append(captured.size)
                anchors.append(anchor_summary(page, SHELL_ANCHORS))
                reports.append(compare_with_design(index, shot).as_report())
            assert sizes[0] == sizes[1] == sizes[2] == CANVAS
            assert report_json(anchors[0]) == report_json(anchors[1]) == report_json(anchors[2])
            assert report_json(reports[0]) == report_json(reports[1]) == report_json(reports[2])

    def test_mixed_items_cover_three_signalled_states(self) -> None:
        items = mixed_batch_items()
        assert len(items) == len(BATCH_RAW_LINES)
        statuses = [item["status"] for item in items]
        assert statuses.count("FOUND") == 3
        assert statuses.count("DRAFT") == 2
        assert statuses.count("FAILED") == 1
        assert all(item["item_id"] for item in items)
        assert all(item["preview_request"] is None or item["draft_id"] for item in items)
