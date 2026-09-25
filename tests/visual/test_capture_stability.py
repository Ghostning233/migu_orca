"""连续真实截图的稳定性判定不能只比较差异数量的波动。"""

from __future__ import annotations

import pytest

from tests.browser.visual_support import assert_consecutive_captures_stable


def _report(diff_pixels: int) -> dict[str, object]:
    return {
        "canvas": {"width": 1440, "height": 900},
        "compared_pixels": 1440 * 900,
        "mask_pixels": 0,
        "resample": "none",
        "channel_threshold": 12,
        "diff_pixels": diff_pixels,
        "masks": [],
    }


def test_consecutive_captures_allow_only_small_rasterization_noise() -> None:
    assert_consecutive_captures_stable([_report(0), _report(8)])


def test_equal_large_differences_do_not_count_as_stable() -> None:
    with pytest.raises(AssertionError, match="超过噪声上限"):
        assert_consecutive_captures_stable([_report(10_000), _report(10_000)])
