"""Stage 46 / US-358：确定性 PNG 像素比较 helper。

设计约束见 ``docs/MiGuOrca_stage46_pixel_foundation_PRD.md`` 第 5 节：

- 只用于测试期；Pillow 是 Python dev dependency，不进入生产轮子或前端 bundle。
- 六张设计源图是只读资产；参考图以固定 LANCZOS 参数归一化到标准桌面基线
  （``1440x900``），页面截图必须原生等于该基线。
- 差异判定为「任一 RGB 通道差值 > 12」；RGBA 输入只比较可见 RGB。
- 掩码是显式命名矩形，裁剪到画布、重叠只计一次、默认总面积不得超过画布 35%，
  且不允许调用者放宽该上限。
- 失败都是固定分类的安全错误：消息不含绝对路径、像素内容、响应载荷或 fixture 载荷。
- 可选 diff 图只由调用者显式给出路径（测试统一传 pytest ``tmp_path``）。

本模块不读取环境变量、不访问网络、不写仓库路径。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw

CANVAS_SIZE: tuple[int, int] = (1440, 900)
"""标准桌面参考画布（CSS 像素），也是页面截图的唯一合法尺寸。"""

REFERENCE_SOURCE_SIZE: tuple[int, int] = (1586, 992)
"""六张设计源 PNG 的位图尺寸；用于文档与冻结检查，不参与缩放算法。"""

LANCZOS: Image.Resampling = Image.Resampling.LANCZOS
LANCZOS_NAME = "LANCZOS"
CHANNEL_THRESHOLD = 12
"""任一 RGB 通道差值严格大于该值才计为差异像素。"""

DEFAULT_MASK_AREA_LIMIT = 0.35
"""掩码并集面积占画布比例的上限；只能调低，不能调高。"""

MAX_CANVAS_PIXELS = 1440 * 900 * 4
"""画布尺寸的绝对上界，避免畸形输入造成无界内存占用。"""

_SUPPORTED_MODES = frozenset({"1", "L", "LA", "P", "PA", "RGB", "RGBA", "CMYK", "YCbCr"})
_ARTIFACT_SUFFIXES = frozenset({".png", ".webp", ".jpg", ".jpeg", ".trace", ".har", ".zip"})
_ARTIFACT_IGNORED_PARTS = frozenset(
    {".git", "node_modules", "dist", "__pycache__", ".venv", ".uv-cache", ".migu_orca", "logs"}
)


class VisualCompareError(Exception):
    """固定分类的安全错误。

    ``code`` 是稳定的机器可读分类（见各 ``raise`` 点）；``detail`` 只允许放
    固定标识（掩码名、模式名、尺寸数字），绝不放路径或像素内容。
    """

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class MaskRect:
    """一个来自固定 selector/矩形的命名排除区。

    ``purpose`` 是审核要求的人工理由；空理由会被拒绝，避免出现无法解释的掩码。
    """

    name: str
    x: int
    y: int
    width: int
    height: int
    purpose: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise VisualCompareError("mask_name_empty")
        if not isinstance(self.purpose, str) or not self.purpose.strip():
            raise VisualCompareError("mask_purpose_empty", self.name)
        for label, value in (
            ("x", self.x),
            ("y", self.y),
            ("width", self.width),
            ("height", self.height),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise VisualCompareError("mask_not_integer", f"{self.name}:{label}")
        if self.width < 0 or self.height < 0:
            raise VisualCompareError("mask_negative_size", self.name)
        if self.width == 0 or self.height == 0:
            raise VisualCompareError("mask_empty", self.name)
        if self.x < 0 or self.y < 0:
            raise VisualCompareError("mask_outside_canvas", self.name)


@dataclass(frozen=True)
class MaskArea:
    """裁剪到画布后的单个命名掩码面积。"""

    name: str
    purpose: str
    area: int
    x: int
    y: int
    width: int
    height: int


@dataclass
class MaskSummary:
    """掩码并集图像与面积统计。"""

    image: Image.Image
    masks: tuple[MaskArea, ...]
    pixels: int
    ratio: float


@dataclass(frozen=True)
class CompareStats:
    """一次比较的安全结果；不含任何路径或像素内容。"""

    canvas: tuple[int, int]
    reference_size: tuple[int, int]
    actual_size: tuple[int, int]
    channel_threshold: int
    resample: str
    canvas_pixels: int
    compared_pixels: int
    diff_pixels: int
    diff_ratio: float
    max_channel_delta: int
    mask_pixels: int
    mask_ratio: float
    masks: tuple[MaskArea, ...]
    diff_written: bool

    def within(self, max_ratio: float) -> bool:
        """差异比例是否不超过给定阈值（用于诊断，不是硬门禁开关）。"""
        if not 0.0 <= max_ratio <= 1.0:
            raise VisualCompareError("threshold_out_of_range")
        return self.diff_ratio <= max_ratio

    def as_report(self) -> dict[str, Any]:
        """JSON 友好、可安全打印的诊断报告。"""
        return {
            "canvas": {"width": self.canvas[0], "height": self.canvas[1]},
            "reference_size": {"width": self.reference_size[0], "height": self.reference_size[1]},
            "actual_size": {"width": self.actual_size[0], "height": self.actual_size[1]},
            "channel_threshold": self.channel_threshold,
            "resample": self.resample,
            "canvas_pixels": self.canvas_pixels,
            "compared_pixels": self.compared_pixels,
            "diff_pixels": self.diff_pixels,
            "diff_ratio": round(self.diff_ratio, 6),
            "max_channel_delta": self.max_channel_delta,
            "mask_pixels": self.mask_pixels,
            "mask_ratio": round(self.mask_ratio, 6),
            "masks": [
                {
                    "name": mask.name,
                    "purpose": mask.purpose,
                    "area": mask.area,
                    "rect": {
                        "x": mask.x,
                        "y": mask.y,
                        "width": mask.width,
                        "height": mask.height,
                    },
                }
                for mask in self.masks
            ],
            "diff_written": self.diff_written,
        }


def _check_size(size: tuple[int, int]) -> None:
    if (
        not isinstance(size, tuple)
        or len(size) != 2
        or any(isinstance(value, bool) or not isinstance(value, int) for value in size)
    ):
        raise VisualCompareError("canvas_size_invalid")
    width, height = size
    if width <= 0 or height <= 0:
        raise VisualCompareError("canvas_size_invalid")
    if width * height > MAX_CANVAS_PIXELS:
        raise VisualCompareError("canvas_too_large")


def _to_rgb(image: Image.Image, error_code: str) -> Image.Image:
    if image.mode not in _SUPPORTED_MODES:
        raise VisualCompareError(error_code, f"mode={image.mode}")
    return image.convert("RGB")


def read_image(source: str | Path, *, error_code: str) -> Image.Image:
    """读取一张 PNG/图片为内存副本；任何读取失败都归为该分类错误。

    错误消息不含路径，避免把本地绝对路径写进测试输出或截图。
    """
    try:
        with Image.open(source) as opened:
            opened.load()
            return opened.copy()
    except Exception:  # 统一归类，避免把底层异常里的本地路径带进测试输出
        raise VisualCompareError(error_code) from None


def normalize_reference(image: Image.Image, *, size: tuple[int, int] = CANVAS_SIZE) -> Image.Image:
    """把设计源图按固定 LANCZOS 参数归一化到标准桌面画布。

    源图是只读资产：本函数只产生新的内存图像。比目标画布更小的输入会被拒绝，
    以免用放大插值伪造参考基线。
    """
    _check_size(size)
    rgb = _to_rgb(image, "reference_mode_unsupported")
    if rgb.size == size:
        return rgb
    if rgb.width < size[0] or rgb.height < size[1]:
        raise VisualCompareError("reference_too_small")
    return rgb.resize(size, resample=LANCZOS)


def load_actual(image: Image.Image, *, size: tuple[int, int] = CANVAS_SIZE) -> Image.Image:
    """校验页面截图的尺寸与模式；截图必须原生等于目标画布。"""
    _check_size(size)
    rgb = _to_rgb(image, "actual_mode_unsupported")
    if rgb.size != size:
        raise VisualCompareError("actual_size_mismatch", f"{rgb.width}x{rgb.height}")
    return rgb


def _validate_area_limit(area_limit: float) -> float:
    if area_limit is None:
        raise VisualCompareError("mask_area_limit_disabled")
    if isinstance(area_limit, bool) or not isinstance(area_limit, (int, float)):
        raise VisualCompareError("mask_area_limit_invalid")
    value = float(area_limit)
    if value <= 0.0:
        raise VisualCompareError("mask_area_limit_invalid")
    if value > DEFAULT_MASK_AREA_LIMIT:
        raise VisualCompareError("mask_area_limit_relaxed")
    return value


def build_mask(
    masks: Sequence[MaskRect],
    *,
    size: tuple[int, int] = CANVAS_SIZE,
    area_limit: float = DEFAULT_MASK_AREA_LIMIT,
) -> MaskSummary:
    """把命名矩形合成为一张并集掩码图并计算面积。

    矩形会裁剪到画布；完全落在画布外的矩形被拒绝。重叠区域在并集里只计一次，
    但每个命名掩码仍报告自己的裁剪面积，便于审核逐项对照。
    """
    limit = _validate_area_limit(area_limit)
    _check_size(size)
    canvas_pixels = size[0] * size[1]
    mask_image = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask_image)
    areas: list[MaskArea] = []
    seen: set[str] = set()
    for rect in masks:
        if rect.name in seen:
            raise VisualCompareError("mask_name_duplicate", rect.name)
        seen.add(rect.name)
        if rect.x >= size[0] or rect.y >= size[1]:
            raise VisualCompareError("mask_outside_canvas", rect.name)
        right = min(rect.x + rect.width, size[0])
        bottom = min(rect.y + rect.height, size[1])
        width = right - rect.x
        height = bottom - rect.y
        draw.rectangle([rect.x, rect.y, right - 1, bottom - 1], fill=255)
        areas.append(
            MaskArea(
                name=rect.name,
                purpose=rect.purpose,
                area=width * height,
                x=rect.x,
                y=rect.y,
                width=width,
                height=height,
            )
        )
    mask_pixels = canvas_pixels - mask_image.histogram()[0]
    ratio = mask_pixels / canvas_pixels
    if ratio > limit + 1e-9:
        raise VisualCompareError("mask_area_exceeded", f"{ratio:.4f}>{limit:.4f}")
    return MaskSummary(image=mask_image, masks=tuple(areas), pixels=mask_pixels, ratio=ratio)


def validate_region(
    region: tuple[int, int, int, int] | None,
    size: tuple[int, int] = CANVAS_SIZE,
) -> tuple[int, int, int, int] | None:
    """校验比较区域 ``(left, top, right, bottom)``。

    Stage 46 的硬门禁只覆盖共享壳层/共享控件，因此比较区域由固定矩形限定，
    而不是靠整页掩码把页面专属区域涂掉。
    """
    if region is None:
        return None
    _check_size(size)
    if len(region) != 4 or any(
        isinstance(value, bool) or not isinstance(value, int) for value in region
    ):
        raise VisualCompareError("region_invalid")
    left, top, right, bottom = region
    if left < 0 or top < 0 or right > size[0] or bottom > size[1] or left >= right or top >= bottom:
        raise VisualCompareError("region_out_of_canvas")
    return left, top, right, bottom


def _shift_masks(masks: Sequence[MaskRect], left: int, top: int) -> tuple[MaskRect, ...]:
    """把画布坐标掩码平移到裁剪区域的局部坐标。"""
    if not left and not top:
        return tuple(masks)
    return tuple(
        MaskRect(mask.name, mask.x - left, mask.y - top, mask.width, mask.height, mask.purpose)
        for mask in masks
    )


def _channel_delta(reference: Image.Image, actual: Image.Image) -> Image.Image:
    """每像素的三个 RGB 通道绝对差取最大值（L 模式）。"""
    difference = ImageChops.difference(reference, actual)
    red, green, blue = difference.split()
    return ImageChops.lighter(ImageChops.lighter(red, green), blue)


def _write_diff(path: Path, actual: Image.Image, delta: Image.Image) -> None:
    if path.suffix.lower() != ".png":
        raise VisualCompareError("diff_target_not_png")
    if not path.parent.is_dir():
        raise VisualCompareError("diff_target_missing")
    highlight = delta.point(lambda value: 255 if value > CHANNEL_THRESHOLD else 0)
    base = actual.convert("L").convert("RGB")
    marker = Image.new("RGB", actual.size, (217, 67, 31))
    Image.composite(marker, base, highlight).save(path, format="PNG")


def compare_images(
    reference: Image.Image,
    actual: Image.Image,
    *,
    masks: Sequence[MaskRect] = (),
    mask_area_limit: float = DEFAULT_MASK_AREA_LIMIT,
    diff_path: str | Path | None = None,
    region: tuple[int, int, int, int] | None = None,
) -> CompareStats:
    """归一化参考图、校验截图并返回确定性比较统计。

    ``region`` 把比较限定在一个固定矩形内（例如共享壳层条带），掩码坐标仍使用
    全画布坐标、内部平移到区域局部坐标。``diff_path`` 只在显式给出时写出一张
    差异高亮 PNG；路径不作为结果的一部分输出。
    """
    normalized = normalize_reference(reference)
    loaded = load_actual(actual, size=normalized.size)
    checked_region = validate_region(region, normalized.size)
    if checked_region is not None:
        left, top, right, bottom = checked_region
        normalized = normalized.crop(checked_region)
        loaded = loaded.crop(checked_region)
        masks = _shift_masks(masks, left, top)
    summary = build_mask(masks, size=normalized.size, area_limit=mask_area_limit)

    delta = _channel_delta(normalized, loaded)
    if summary.pixels:
        delta = ImageChops.multiply(delta, ImageChops.invert(summary.image))

    histogram = delta.histogram()
    canvas_pixels = normalized.size[0] * normalized.size[1]
    compared_pixels = canvas_pixels - summary.pixels
    diff_pixels = sum(histogram[CHANNEL_THRESHOLD + 1 :])
    max_channel_delta = max((value for value, count in enumerate(histogram) if count), default=0)

    diff_written = False
    if diff_path is not None:
        _write_diff(Path(diff_path), loaded, delta)
        diff_written = True

    return CompareStats(
        canvas=normalized.size,
        reference_size=reference.size,
        actual_size=loaded.size,
        channel_threshold=CHANNEL_THRESHOLD,
        resample=LANCZOS_NAME,
        canvas_pixels=canvas_pixels,
        compared_pixels=compared_pixels,
        diff_pixels=diff_pixels,
        diff_ratio=(diff_pixels / compared_pixels) if compared_pixels else 0.0,
        max_channel_delta=max_channel_delta,
        mask_pixels=summary.pixels,
        mask_ratio=summary.ratio,
        masks=summary.masks,
        diff_written=diff_written,
    )


def compare_png(
    reference_path: str | Path,
    actual_path: str | Path,
    *,
    masks: Sequence[MaskRect] = (),
    mask_area_limit: float = DEFAULT_MASK_AREA_LIMIT,
    diff_path: str | Path | None = None,
    region: tuple[int, int, int, int] | None = None,
) -> CompareStats:
    """文件版比较入口：设计源 PNG（只读）对页面截图。"""
    reference = read_image(reference_path, error_code="reference_unreadable")
    actual = read_image(actual_path, error_code="actual_unreadable")
    return compare_images(
        reference,
        actual,
        masks=masks,
        mask_area_limit=mask_area_limit,
        diff_path=diff_path,
        region=region,
    )


def find_visual_artifacts(repo_root: str | Path) -> tuple[str, ...]:
    """仓库中残留的视觉运行产物（仓库相对路径，已排序）。

    Stage 46 明确不提交 screenshot/diff/trace；测试用本函数把「产物不入库」
    变成可执行检查，而不是只靠人工 review。
    """
    root = Path(repo_root)
    found: list[str] = []
    for base in (root / "tests", root / "frontend"):
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in _ARTIFACT_SUFFIXES:
                continue
            relative = path.relative_to(root)
            if _ARTIFACT_IGNORED_PARTS.intersection(relative.parts):
                continue
            found.append(relative.as_posix())
    return tuple(found)
