"""从归一化设计图测量壳层锚点的可复现工具。

``tests/browser/visual_manifest.py`` 里的设计图对照坐标由本工具测得；运行方式::

    UV_CACHE_DIR=.uv-cache uv run python -m tests.visual.measure

- 归档的六张 ``1586x992`` 源 PNG（旧基线，Stage 46 追溯）归一化到 ``1440x900``；
- 现行设计图 ``redesign-2026-09-23/添加番剧－单番－搜索首屏.png`` 由
  :func:`measure_redesign_shell` 测量，为 Issue 109 的壳层数值基线提供位图对照。

工具只读取设计资产、不写任何文件，输出可直接对照的 JSON。
测量是「背景色差」驱动的：像素与画布背景色 ``(254, 253, 251)`` 的任一 RGB
通道差超过阈值才计入内容，因此结果不受 AI 生成图轻微渐变噪声影响。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image

from tests.visual.compare import CANVAS_SIZE, normalize_reference, read_image

REPO_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_DIR = REPO_ROOT / "docs/design/assets/frontend-ux/archive/review-2026-09-17"
DESIGN_FILES: tuple[str, ...] = (
    "01-single-search.png",
    "02-single-candidates-loading.png",
    "03-single-draft-review.png",
    "04-batch-search-loading.png",
    "05-batch-candidates-loading.png",
    "06-batch-draft-review.png",
)

REDESIGN_DIR = REPO_ROOT / "docs/design/assets/frontend-ux/redesign-2026-09-23"
REDESIGN_SHELL_FILE = "添加番剧－单番－搜索首屏.png"
"""现行设计图（Issue 109 壳层数值基线的位图对照来源）。"""


BACKGROUND = (254, 253, 251)
STRONG_DELTA = 30
"""文字/边框级别内容；用于定位可见文本块。"""

SOFT_DELTA = 4
"""表面级差异；用于发现浅色胶囊等弱对比元素。"""

HEADER_SCAN_ROWS = 160
"""顶栏扫描的纵向范围（归一化后 CSS 像素）。"""


@dataclass(frozen=True)
class Band:
    start: int
    end: int
    peak: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


def delta(pixel: tuple[int, int, int], background: tuple[int, int, int] = BACKGROUND) -> int:
    return max(abs(pixel[0] - background[0]), abs(pixel[1] - background[1]), abs(pixel[2] - background[2]))


def bands(values: list[int], minimum: int) -> list[Band]:
    """把一串逐行/逐列计数压成连续内容带。"""
    result: list[Band] = []
    start: int | None = None
    for index, value in enumerate(values):
        if value >= minimum and start is None:
            start = index
        elif value < minimum and start is not None:
            result.append(Band(start, index - 1, max(values[start:index])))
            start = None
    if start is not None:
        result.append(Band(start, len(values) - 1, max(values[start:])))
    return result


def _row_counts(image: Image.Image, y_from: int, y_to: int, threshold: int) -> list[int]:
    pixels = image.load()
    width = image.size[0]
    return [
        sum(1 for x in range(width) if delta(pixels[x, y]) > threshold)
        for y in range(y_from, y_to)
    ]


def _column_counts(image: Image.Image, y_from: int, y_to: int, threshold: int) -> list[int]:
    pixels = image.load()
    width = image.size[0]
    return [
        sum(1 for y in range(y_from, y_to) if delta(pixels[x, y]) > threshold)
        for x in range(width)
    ]


def measure_shell(image: Image.Image) -> dict[str, object]:
    """测量一张设计图的共享壳层结构。"""
    normalized = normalize_reference(image)
    assert normalized.size == CANVAS_SIZE
    pixels = normalized.load()

    text_rows = _row_counts(normalized, 0, HEADER_SCAN_ROWS, STRONG_DELTA)
    text_row_bands = bands(text_rows, 2)
    header_text = next(
        (band for band in text_row_bands if band.start > 10 and band.peak > 100),
        None,
    )
    underline = next(
        (band for band in text_row_bands if header_text and band.start > header_text.end),
        None,
    )

    text_columns = _column_counts(normalized, header_text.start, header_text.end + 1, STRONG_DELTA) if header_text else []
    text_col_bands = bands(text_columns, 2)
    soft_columns = _column_counts(normalized, 10, 80, SOFT_DELTA)
    soft_col_bands = bands(soft_columns, 20)

    return {
        "header_text_rows": asdict(header_text) if header_text else None,
        "underline_rows": asdict(underline) if underline else None,
        "header_text_columns": [asdict(band) for band in text_col_bands],
        "soft_columns": [asdict(band) for band in soft_col_bands],
        "underline_color": _sample_underline_color(pixels, underline),
        "background": BACKGROUND,
    }


def _sample_underline_color(pixels: object, underline: Band | None) -> list[int] | None:
    if underline is None:
        return None
    samples: list[tuple[int, int, int]] = []
    for x in range(330, 410, 4):
        for y in range(underline.start + 1, max(underline.start + 2, underline.end - 1)):
            pixel = pixels[x, y]  # type: ignore[index]
            if delta(pixel) > 60:
                samples.append(pixel)
    if not samples:
        return None
    count = len(samples)
    return [round(sum(pixel[channel] for pixel in samples) / count) for channel in range(3)]


def _first_surface_drop(pixels: object, x: int, *, scan_rows: int = 200, run: int = 3) -> int | None:
    """返回顶栏白色表面带结束后的第一个行号（连续 ``run`` 行不再是近白）。

    设计图的页眉是接近纯白的表面，正文画布是暖白；单行插值噪声不算结束，
    必须连续 ``run`` 行低于阈值才认定为页面画布起点。
    """
    below = 0
    for y in range(scan_rows):
        pixel = pixels[x, y]  # type: ignore[index]
        if max(pixel) < 253:
            below += 1
            if below >= run:
                return y - run + 1
        else:
            below = 0
    return None


def measure_redesign_shell() -> dict[str, object]:
    """测量现行设计图（Issue 109）的共享壳层，供数值基线人工对照。

    只读设计资产、不写文件。输出与 ``visual_manifest.REDESIGN_SHELL_MEASUREMENTS``
    必须一致（由 ``tests/visual/test_shell_baseline.py`` 复现核对）。
    """
    image = read_image(REDESIGN_DIR / REDESIGN_SHELL_FILE, error_code="reference_unreadable")
    normalized = normalize_reference(image)
    pixels = normalized.load()
    width, _height = normalized.size

    text_rows = bands(_row_counts(normalized, 0, HEADER_SCAN_ROWS, STRONG_DELTA), 2)
    header_text = next((band for band in text_rows if band.start > 10 and band.peak > 100), None)
    underline = next(
        (band for band in text_rows if header_text is not None and band.start > header_text.end),
        None,
    )
    columns = (
        bands(_column_counts(normalized, header_text.start, header_text.end + 1, STRONG_DELTA), 2)
        if header_text
        else []
    )
    soft_columns = bands(_column_counts(normalized, 10, 80, SOFT_DELTA), 20)
    status_surface = next((band for band in soft_columns if band.start > 1100), None)
    brand_end = max((band.end for band in columns if band.end <= 240), default=None)
    nav_first = next((band for band in columns if band.start > 240), None)
    surface_end = _first_surface_drop(pixels, width // 2)
    source = (REDESIGN_DIR / REDESIGN_SHELL_FILE).relative_to(REPO_ROOT).as_posix()

    return {
        "source": f"{source} ({image.size[0]}x{image.size[1]} PNG, LANCZOS -> 1440x900)",
        "header_band_rows": (0, surface_end - 1) if surface_end else None,
        "header_text_rows": (header_text.start, header_text.end) if header_text else None,
        "underline_rows": (underline.start, underline.end) if underline else None,
        "brand_text_x": (columns[0].start, brand_end) if columns and brand_end is not None else None,
        "nav_first_text_x": (nav_first.start, nav_first.end) if nav_first else None,
        "status_surface_x": (status_surface.start, status_surface.end) if status_surface else None,
    }


def measure_all() -> dict[str, object]:
    report: dict[str, object] = {
        "canvas": {"width": CANVAS_SIZE[0], "height": CANVAS_SIZE[1]},
        "source": "docs/design/assets/frontend-ux/archive/review-2026-09-17 (1586x992 PNG, LANCZOS -> 1440x900)",
        "files": {},
        "redesign": measure_redesign_shell(),
    }
    for name in DESIGN_FILES:
        image = read_image(REFERENCE_DIR / name, error_code="reference_unreadable")
        report["files"][name] = measure_shell(image)  # type: ignore[index]
    return report


def main() -> None:
    print(json.dumps(measure_all(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
