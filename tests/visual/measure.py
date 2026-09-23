"""Stage 46：从归一化设计图测量壳层锚点的可复现工具。

``tests/browser/visual_manifest.py`` 里的目标坐标全部由本工具从六张
``1586x992`` 源 PNG 归一化到 ``1440x900`` 后测得；运行方式::

    UV_CACHE_DIR=.uv-cache uv run python -m tests.visual.measure

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


def measure_all() -> dict[str, object]:
    report: dict[str, object] = {
        "canvas": {"width": CANVAS_SIZE[0], "height": CANVAS_SIZE[1]},
        "source": "docs/design/assets/frontend-ux/archive/review-2026-09-17 (1586x992 PNG, LANCZOS -> 1440x900)",
        "files": {},
    }
    for name in DESIGN_FILES:
        image = read_image(REFERENCE_DIR / name, error_code="reference_unreadable")
        report["files"][name] = measure_shell(image)  # type: ignore[index]
    return report


def main() -> None:
    print(json.dumps(measure_all(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
