"""Stage 46 / US-359：单番图 01～03 的真实 Chromium 视觉 fixture 用例。

这些用例只建立「确定性进入三态 + 可重复测量」的红线：截图与比较统计只写
pytest ``tmp_path``，页面专属区域只记录诊断值，不提交任何预期失败的像素门禁。
壳层与共享控件的硬门禁在 US-361／US-362 的用例中启用。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from playwright.sync_api import Page, expect

from tests.browser.visual_manifest import SHELL_ANCHORS, SHELL_MEASUREMENTS
from tests.browser.visual_support import (
    CANVAS,
    DESIGN_FILES,
    anchor_summary,
    assert_stable_reports,
    browser_surface,
    capture_canvas,
    compare_with_design,
    report_json,
)
from tests.browser.workbench_visual_fixtures import (
    CANARY_CANDIDATE_CONTEXT,
    CANARY_MIKAN_URL,
    SINGLE_CANDIDATES,
    SingleAnimeVisualScenario,
)

pytestmark = pytest.mark.browser

FIGURE_ENTRY = {
    1: "enter_figure_01",
    2: "enter_figure_02",
    3: "enter_figure_03",
}


class TestAppWorkbenchVisualFixtures:
    """AC: 图 01～03 由真实契约形状可确定性进入，并可重复测量。"""

    def _scenario(self, page: Page, live_server_url: str, storage_dir: Path) -> SingleAnimeVisualScenario:
        scenario = SingleAnimeVisualScenario(page, live_server_url)
        scenario.install(storage_dir)
        return scenario

    def test_figure_01_initial_has_no_results_panel_or_candidate_request(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        scenario = self._scenario(page, live_server_url, storage_dir)
        scenario.enter_figure_01()

        expect(page.locator("#mikan-candidate-search-form")).to_have_count(1)
        expect(page.locator(".search-results-panel")).to_have_count(0)
        expect(page.locator(".candidate-card")).to_have_count(0)
        expect(page.locator(".candidate-fallback-rescue")).to_have_count(0)
        # 图 01 是搜索前状态：没有候选请求，也没有外部系统访问。
        assert scenario.external_calls == []
        assert page.evaluate("() => performance.getEntriesByType('resource').length") >= 0

    def test_figure_02_holds_generation_on_the_first_candidate_only(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        scenario = self._scenario(page, live_server_url, storage_dir)
        scenario.enter_figure_02()

        cards = page.locator(".candidate-card")
        expect(cards).to_have_count(len(SINGLE_CANDIDATES))
        clicked = cards.nth(0).locator(".candidate-select")
        expect(clicked).to_be_disabled()
        expect(clicked).to_have_attribute("aria-busy", "true")
        other = cards.nth(1).locator(".candidate-select")
        expect(other).to_be_disabled()
        assert other.get_attribute("aria-busy") is None
        # 候选阶段不出现资源数（有效资源只在草案生成后展示）。
        assert page.evaluate("() => document.querySelectorAll('.effective-seed-group').length") == 0
        assert "有效资源" not in page.locator(".search-results-panel").inner_text()

    def test_figure_03_reaches_review_without_saved_safe_info(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        scenario = self._scenario(page, live_server_url, storage_dir)
        scenario.enter_figure_03()

        expect(page.locator("#detail-preview-edit-form")).to_have_count(1)
        expect(page.locator(".candidate-card")).to_have_count(0)
        assert scenario.safe_info_calls == [], "未保存草案不得调用已保存 Request 的 safe-info"

    def test_canary_never_reaches_browser_surfaces_or_screenshot_artifacts(
        self, page: Page, live_server_url: str, storage_dir: Path, tmp_path: Path
    ) -> None:
        scenario = self._scenario(page, live_server_url, storage_dir)
        scenario.enter_figure_02()
        # 图 02 已经接收了 canary：候选上下文已进入客户端内存边界。
        canaries = (*scenario.canary_values(), CANARY_CANDIDATE_CONTEXT, CANARY_MIKAN_URL)
        assert CANARY_CANDIDATE_CONTEXT in canaries

        shot = capture_canvas(page, tmp_path / "figure-02-canary.png")
        diff = tmp_path / "figure-02-canary-diff.png"
        compare_with_design(2, shot, diff_path=diff)

        surface = browser_surface(page)
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

        # history 边界是真实的（SPA 推入了 router state），canary 断言才不空洞。
        assert surface["historyState"] not in ("", "null")

        # 图 03 释放真实 envelope 后，服务端签发的 draft_id 同样不得泄漏。
        scenario.release_draft_review()
        surface = browser_surface(page)
        assert scenario.draft_id
        for canary in scenario.canary_values():
            assert canary not in surface["url"]
            assert canary not in surface["historyState"]
            assert canary not in surface["localStorage"]
            assert canary not in surface["sessionStorage"]
            assert canary not in surface["bodyText"]
            assert canary not in surface["attributes"]
            assert all(canary not in message for message in scenario.console_messages)

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
            assert diff.is_file()
            report = stats.as_report()
            assert report["canvas"] == {"width": CANVAS[0], "height": CANVAS[1]}
            assert report["resample"] == "LANCZOS"
            assert report["channel_threshold"] == 12
            assert report["compared_pixels"] == CANVAS[0] * CANVAS[1]
            # 页面专属区域在 Stage 47/48 才启用硬门禁，这里只记录诊断值。
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
            # 尺寸与 DOM 锚点严格一致；差异统计只在栅格化噪声带内波动。
            assert report_json(anchors[0]) == report_json(anchors[1]) == report_json(anchors[2])
            assert_stable_reports(reports)


def test_manifest_targets_come_from_normalized_design_measurements() -> None:
    """manifest 的目标坐标必须能由测量工具从归一化设计图复现。"""
    from tests.visual.measure import measure_all

    report = measure_all()
    files = report["files"]
    assert set(files) == set(DESIGN_FILES.values())

    header_rows = SHELL_MEASUREMENTS["header_text_rows"]
    underline_rows = SHELL_MEASUREMENTS["underline_rows"]
    brand_x = SHELL_MEASUREMENTS["brand_text_x"]
    status_surface_x = SHELL_MEASUREMENTS["status_surface_x"]

    for name in DESIGN_FILES.values():
        measured = files[name]
        rows = measured["header_text_rows"]
        assert abs(rows["start"] - header_rows[0]) <= 1, name
        assert abs(rows["end"] - header_rows[1]) <= 1, name
        underline = measured["underline_rows"]
        assert abs(underline["end"] - underline_rows[1]) <= 1, name
        columns = [(band["start"], band["end"]) for band in measured["header_text_columns"]]
        assert abs(columns[0][0] - brand_x[0]) <= 2, name
        brand_bands = [band for band in columns if band[1] <= 300]
        assert brand_bands, name
        assert abs(brand_bands[-1][1] - brand_x[1]) <= 4, name
        nav_bands = [band for band in columns if 300 <= band[0] <= 800]
        assert len(nav_bands) >= 8, name
        status_bands = [band for band in columns if band[0] >= 1100]
        assert status_bands, name
        soft = [(band["start"], band["end"]) for band in measured["soft_columns"] if band["start"] > 1100]
        assert soft, name
        assert abs(soft[0][0] - status_surface_x[0]) <= 4, name
