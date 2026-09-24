"""#140～#144：添加番剧的视觉回归硬门禁（真实 Chromium，固定 fixture）。

父规格 #139 的验收口径（已冻结，不得按单次 PR 反向调宽）：

- 只比较同一固定环境与同一业务 fixture 的基准／当前截图；
- 任一 RGB 通道差值 >12 计为显著差异像素，显著差异比例必须 ≤0.5%；
- 具名、说明原因的动态掩码总面积 ≤5%，且不得遮导航、整卡或主按钮（当前场景不使用
  掩码，即实际 0%）；
- 关键锚点与尺寸偏差 ≤2 CSS px；
- 先证明同一场景连续三次截图稳定，截图噪声超阈值时先修环境而不是放宽门槛。

基准图片只在人工（或具备读图能力的 Agent）审核真实浏览器画面后入库。记录方式：

    MIGU_ORCA_RECORD_VISUAL_BASELINE=1 uv run pytest tests/browser/test_app_add_anime_visual.py -q

记录会把当次截图与锚点写入 ``docs/design/assets/frontend-ux/acceptance-baseline/add-anime/``；正常情况下
该用例只做比较，缺基准即失败，不会静默生成。
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from playwright.sync_api import Page

from tests.browser.add_anime_visual_fixtures import (
    SCENARIOS,
    anchor_values,
    anchors_json,
)
from tests.browser.visual_support import (
    assert_stable_reports,
    capture_canvas,
    require_dist,
)
from tests.visual.compare import MaskRect, compare_images, read_image

pytestmark = pytest.mark.browser

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_DIR = REPO_ROOT / "docs/design/assets/frontend-ux/acceptance-baseline/add-anime"
ANCHORS_FILE = BASELINE_DIR / "anchors.json"
RECORD_FLAG = "MIGU_ORCA_RECORD_VISUAL_BASELINE"

MAX_DIFF_RATIO = 0.005
MAX_MASK_RATIO = 0.05
ANCHOR_TOLERANCE = 2.0
STABILITY_REPEATS = 3


def _recording() -> bool:
    return os.environ.get(RECORD_FLAG) == "1"


def _load_recorded_anchors() -> dict[str, dict[str, dict[str, float] | None]]:
    if not ANCHORS_FILE.is_file():
        return {}
    return json.loads(ANCHORS_FILE.read_text(encoding="utf-8"))


def _record(scenario_name: str, capture: Path, anchors: dict[str, dict[str, float] | None]) -> None:
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(capture, BASELINE_DIR / f"{scenario_name}.png")
    recorded = _load_recorded_anchors()
    recorded[scenario_name] = anchors
    ANCHORS_FILE.write_text(anchors_json(recorded), encoding="utf-8")


def _assert_anchors(
    actual: dict[str, dict[str, float] | None],
    expected: dict[str, dict[str, float] | None],
) -> None:
    assert set(actual) == set(expected), (sorted(actual), sorted(expected))
    for selector, expected_box in expected.items():
        box = actual[selector]
        assert box is not None, f"锚点缺失：{selector}"
        assert expected_box is not None, f"基准缺少锚点：{selector}"
        for field in ("x", "y", "width", "height"):
            deviation = abs(box[field] - expected_box[field])
            assert deviation <= ANCHOR_TOLERANCE, (selector, field, box, expected_box)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[scenario.name for scenario in SCENARIOS])
def test_add_anime_scene_matches_the_approved_baseline(
    page: Page, live_server_url: str, tmp_path: Path, scenario
) -> None:
    require_dist()
    scenario.setup(page, live_server_url)
    capture = tmp_path / f"{scenario.name}.png"
    capture_canvas(page, capture)
    anchors = anchor_values(page, scenario.anchors)

    if _recording():
        _record(scenario.name, capture, anchors)
        return

    baseline = BASELINE_DIR / f"{scenario.name}.png"
    assert baseline.is_file(), (
        f"缺少获批视觉基准 {baseline.name}；先由用户审核真实浏览器画面，"
        f"再用 MIGU_ORCA_RECORD_VISUAL_BASELINE=1 记录。"
    )
    masks = tuple(
        MaskRect(name, x, y, width, height, purpose)
        for name, x, y, width, height, purpose in scenario.masks
    )
    stats = compare_images(
        read_image(baseline, error_code="baseline_unreadable"),
        read_image(capture, error_code="actual_unreadable"),
        masks=masks,
        mask_area_limit=MAX_MASK_RATIO,
        diff_path=tmp_path / f"{scenario.name}-diff.png",
    )
    assert stats.mask_ratio <= MAX_MASK_RATIO, stats.as_report()
    assert stats.diff_ratio <= MAX_DIFF_RATIO, (
        f"{scenario.name} 显著像素差异 {stats.diff_ratio:.4%} 超过 {MAX_DIFF_RATIO:.1%}；"
        "先核对 fixture／字体／构建是否稳定，再由用户判断是代码修复还是目标设计变化。"
    )

    recorded = _load_recorded_anchors()
    assert scenario.name in recorded, f"基准缺少 {scenario.name} 的锚点记录"
    _assert_anchors(anchors, recorded[scenario.name])


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[scenario.name for scenario in SCENARIOS])
def test_add_anime_scene_captures_are_stable(
    page: Page, live_server_url: str, tmp_path: Path, scenario
) -> None:
    """连续三次截图必须稳定：几何严格一致，差异只在栅格化噪声带内。"""
    require_dist()
    scenario.setup(page, live_server_url)

    reports: list[dict[str, object]] = []
    previous: Path | None = None
    for index in range(STABILITY_REPEATS):
        capture = tmp_path / f"{scenario.name}-{index}.png"
        capture_canvas(page, capture)
        if previous is not None:
            reports.append(
                compare_images(
                    read_image(previous, error_code="previous_unreadable"),
                    read_image(capture, error_code="actual_unreadable"),
                    mask_area_limit=MAX_MASK_RATIO,
                ).as_report()
            )
        previous = capture

    assert_stable_reports(reports)
