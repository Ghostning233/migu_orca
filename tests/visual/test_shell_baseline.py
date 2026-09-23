"""Issue 109：壳层数值基线与 Token 源、设计图测量的可复现核对。

这些用例不依赖 Chromium、不读取页面、不访问外部系统：它们把
``tests/browser/visual_manifest.py`` 里的 1280／1440／1920 壳层档位、锚点与现行
设计图实测，和 ``frontend/src/styles/`` 的 Token 源以及 ``measure.py`` 的测量结果
直接对齐，防止断言常量与实现各自漂移。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.browser.visual_manifest import (
    CONTENT_MAX,
    REDESIGN_SHELL_MEASUREMENTS,
    SHELL_HEADER_HEIGHT,
    SHELL_STATUS_HEIGHT,
    SHELL_VIEWPORTS,
    content_padding_inline,
    shell_anchors_for,
)
from tests.visual.measure import measure_redesign_shell

REPO_ROOT = Path(__file__).resolve().parents[2]
TOKENS_CSS = REPO_ROOT / "frontend/src/styles/tokens.css"
MAIN_CSS = REPO_ROOT / "frontend/src/styles/main.css"


def test_shipped_shell_viewports_cover_the_token_v1_desktop_range() -> None:
    assert SHELL_VIEWPORTS == (1280, 1440, 1920)


@pytest.mark.parametrize(
    ("width", "expected"),
    [(1280, 24.0), (1439, 24.0), (1440, 32.0), (1679, 32.0), (1680, 48.0), (1920, 48.0)],
)
def test_content_padding_tiers_match_token_v1_6_1(width: int, expected: float) -> None:
    assert content_padding_inline(width) == expected


def test_token_source_declares_the_same_padding_tiers_as_the_manifest() -> None:
    tokens = TOKENS_CSS.read_text(encoding="utf-8")
    # Base = compact tier; each media query steps one Token level up.
    assert "--content-padding-inline: var(--space-6)" in tokens
    assert "@media (min-width: 1440px)" in tokens
    assert "@media (min-width: 1680px)" in tokens
    assert tokens.index("@media (min-width: 1440px)") < tokens.index("@media (min-width: 1680px)")
    # The manifest maps 1440 -> --space-8 (32px) and 1680 -> --space-12 (48px).
    assert content_padding_inline(1440) == 32.0
    assert content_padding_inline(1680) == 48.0

    main = MAIN_CSS.read_text(encoding="utf-8")
    assert "padding-inline: var(--content-padding-inline)" in main
    assert "padding: var(--space-6) var(--content-padding-inline)" in main


@pytest.mark.parametrize("width", SHELL_VIEWPORTS)
def test_shell_anchor_boxes_are_width_consistent(width: int) -> None:
    anchors = {anchor.name: anchor for anchor in shell_anchors_for(width)}
    padding = content_padding_inline(width)
    container_width = min(float(width), CONTENT_MAX)
    container_left = (width - container_width) / 2.0

    assert anchors["shell.header"].width == float(width)
    assert anchors["shell.header"].height == SHELL_HEADER_HEIGHT
    assert anchors["shell.content"].x == container_left
    assert anchors["shell.content"].width == container_width
    assert anchors["shell.brand"].x == container_left + padding
    assert anchors["shell.status-right"].right == container_left + container_width - padding
    assert anchors["shell.status"].height == SHELL_STATUS_HEIGHT
    assert anchors["shell.status"].y == (SHELL_HEADER_HEIGHT - SHELL_STATUS_HEIGHT) / 2
    assert anchors["shell.main"].x == container_left
    assert anchors["shell.main"].width == container_width
    assert anchors["shell.main"].y == SHELL_HEADER_HEIGHT


def test_redesign_shell_measurements_are_reproducible() -> None:
    measured = measure_redesign_shell()
    assert measured["source"] == REDESIGN_SHELL_MEASUREMENTS["source"]
    for key in (
        "header_band_rows",
        "header_text_rows",
        "underline_rows",
        "brand_text_x",
        "nav_first_text_x",
        "status_surface_x",
    ):
        assert measured[key] is not None, key
        expected = REDESIGN_SHELL_MEASUREMENTS[key]
        assert tuple(measured[key]) == tuple(expected), key
