"""Stage 46 / US-358：像素比较 helper 的纯合成图边界测试。

这些用例不依赖 Chromium、不读取页面、不访问外部系统：它们用内存/临时目录里的
合成 PNG 固定比较算法的语义，因此浏览器缺失时也不允许被 skip。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from tests.visual.compare import (
    CANVAS_SIZE,
    CHANNEL_THRESHOLD,
    DEFAULT_MASK_AREA_LIMIT,
    REFERENCE_SOURCE_SIZE,
    CompareStats,
    MaskRect,
    VisualCompareError,
    build_mask,
    compare_images,
    compare_png,
    find_visual_artifacts,
    normalize_reference,
    validate_region,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DESIGN_DIR = REPO_ROOT / "docs/design/assets/frontend-ux/archive/review-2026-09-17"
DESIGN_NAMES = (
    "01-single-search.png",
    "02-single-candidates-loading.png",
    "03-single-draft-review.png",
    "04-batch-search-loading.png",
    "05-batch-candidates-loading.png",
    "06-batch-draft-review.png",
)


def _solid(color: tuple[int, int, int] = (255, 255, 255), size: tuple[int, int] = CANVAS_SIZE) -> Image.Image:
    return Image.new("RGB", size, color)


def _with_pixels(
    image: Image.Image,
    pixels: dict[tuple[int, int], tuple[int, int, int]],
) -> Image.Image:
    copy = image.copy()
    for (x, y), color in pixels.items():
        copy.putpixel((x, y), color)
    return copy


def _save(path: Path, image: Image.Image) -> Path:
    image.save(path, format="PNG")
    return path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# 归一化与输入校验
# ---------------------------------------------------------------------------


def test_identical_images_have_zero_difference() -> None:
    stats = compare_images(_solid(), _solid())
    assert stats.diff_pixels == 0
    assert stats.diff_ratio == 0.0
    assert stats.max_channel_delta == 0
    assert stats.compared_pixels == CANVAS_SIZE[0] * CANVAS_SIZE[1]
    assert stats.mask_pixels == 0
    assert stats.masks == ()


def test_reference_is_normalized_to_canvas_with_lanczos() -> None:
    source = _solid((10, 20, 30), size=REFERENCE_SOURCE_SIZE)
    normalized = normalize_reference(source)
    assert normalized.size == CANVAS_SIZE
    assert normalized.mode == "RGB"
    stats = compare_images(source, _solid((10, 20, 30)))
    assert stats.reference_size == REFERENCE_SOURCE_SIZE
    assert stats.actual_size == CANVAS_SIZE
    assert stats.resample == "LANCZOS"
    assert stats.channel_threshold == CHANNEL_THRESHOLD == 12
    assert stats.diff_pixels == 0


def test_design_source_pngs_are_unchanged_by_normalization() -> None:
    assert DESIGN_DIR.is_dir(), "设计源图目录缺失"
    for name in DESIGN_NAMES:
        path = DESIGN_DIR / name
        before = _digest(path)
        with Image.open(path) as opened:
            opened.load()
            assert opened.size == REFERENCE_SOURCE_SIZE
            normalized = normalize_reference(opened)
        assert normalized.size == CANVAS_SIZE
        assert _digest(path) == before, f"{name} 被 helper 改写"


def test_reference_smaller_than_canvas_is_rejected() -> None:
    with pytest.raises(VisualCompareError) as excinfo:
        normalize_reference(_solid(size=(1440, 899)))
    assert excinfo.value.code == "reference_too_small"


def test_actual_size_must_match_canvas_exactly() -> None:
    with pytest.raises(VisualCompareError) as excinfo:
        compare_images(_solid(), _solid(size=(1440, 899)))
    assert excinfo.value.code == "actual_size_mismatch"


def test_unsupported_mode_is_rejected() -> None:
    grayscale_float = Image.new("F", CANVAS_SIZE, 0.5)
    with pytest.raises(VisualCompareError) as excinfo:
        compare_images(grayscale_float, _solid())
    assert excinfo.value.code == "reference_mode_unsupported"
    with pytest.raises(VisualCompareError) as excinfo:
        compare_images(_solid(), grayscale_float)
    assert excinfo.value.code == "actual_mode_unsupported"


def test_corrupt_png_fails_without_leaking_the_path(tmp_path: Path) -> None:
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not a real png payload")
    with pytest.raises(VisualCompareError) as excinfo:
        compare_png(_save(tmp_path / "ok.png", _solid()), broken)
    assert excinfo.value.code == "actual_unreadable"
    assert str(tmp_path) not in str(excinfo.value)

    with pytest.raises(VisualCompareError) as excinfo:
        compare_png(broken, _save(tmp_path / "ok2.png", _solid()))
    assert excinfo.value.code == "reference_unreadable"
    assert str(tmp_path) not in str(excinfo.value)


# ---------------------------------------------------------------------------
# 阈值与通道语义
# ---------------------------------------------------------------------------


def test_threshold_boundary_counts_only_deltas_above_twelve() -> None:
    reference = _solid()
    at_limit = _with_pixels(reference, {(5, 5): (255 - CHANNEL_THRESHOLD, 255, 255)})
    above_limit = _with_pixels(reference, {(5, 5): (255 - CHANNEL_THRESHOLD - 1, 255, 255)})

    boundary = compare_images(reference, at_limit)
    assert boundary.diff_pixels == 0
    assert boundary.max_channel_delta == CHANNEL_THRESHOLD

    exceeded = compare_images(reference, above_limit)
    assert exceeded.diff_pixels == 1
    assert exceeded.max_channel_delta == CHANNEL_THRESHOLD + 1
    assert exceeded.diff_ratio == pytest.approx(1 / (CANVAS_SIZE[0] * CANVAS_SIZE[1]))


def test_single_pixel_difference_is_counted_exactly() -> None:
    reference = _solid((0, 0, 0))
    actual = _with_pixels(reference, {(1439, 899): (255, 255, 255)})
    stats = compare_images(reference, actual)
    assert stats.diff_pixels == 1
    assert stats.max_channel_delta == 255


def test_rgba_inputs_compare_visible_rgb_only() -> None:
    reference = _solid((30, 40, 50))
    opaque = Image.new("RGBA", CANVAS_SIZE, (30, 40, 50, 255))
    transparent_same_rgb = Image.new("RGBA", CANVAS_SIZE, (30, 40, 50, 0))
    transparent_other_rgb = Image.new("RGBA", CANVAS_SIZE, (30, 40, 99, 0))

    assert compare_images(reference, opaque).diff_pixels == 0
    assert compare_images(reference, transparent_same_rgb).diff_pixels == 0
    changed = compare_images(reference, transparent_other_rgb)
    assert changed.diff_pixels == CANVAS_SIZE[0] * CANVAS_SIZE[1]
    assert changed.max_channel_delta == 49


# ---------------------------------------------------------------------------
# 掩码语义
# ---------------------------------------------------------------------------


def test_overlapping_masks_count_once_but_report_each_name() -> None:
    reference = _solid((0, 0, 0))
    actual = _solid((255, 255, 255))
    masks = (
        MaskRect("poster", 0, 0, 100, 100, "fixture 海报内部"),
        MaskRect("poster-glow", 50, 50, 100, 100, "fixture 海报边缘"),
    )
    summary = build_mask(masks)
    assert summary.pixels == 100 * 100 + 100 * 100 - 50 * 50
    assert [mask.area for mask in summary.masks] == [10_000, 10_000]
    assert [mask.name for mask in summary.masks] == ["poster", "poster-glow"]

    stats = compare_images(reference, actual, masks=masks)
    assert stats.mask_pixels == summary.pixels
    assert stats.compared_pixels == CANVAS_SIZE[0] * CANVAS_SIZE[1] - summary.pixels
    assert stats.diff_pixels == stats.compared_pixels


def test_mask_is_clipped_to_the_canvas() -> None:
    summary = build_mask((MaskRect("corner", 1400, 880, 100, 100, "固定 selector 溢出"),))
    assert summary.masks[0].area == 40 * 20
    assert (summary.masks[0].x, summary.masks[0].y) == (1400, 880)
    assert (summary.masks[0].width, summary.masks[0].height) == (40, 20)


def test_mask_validation_rejects_empty_outside_and_negative() -> None:
    cases = [
        (lambda: MaskRect("", 0, 0, 10, 10, "理由"), "mask_name_empty"),
        (lambda: MaskRect("   ", 0, 0, 10, 10, "理由"), "mask_name_empty"),
        (lambda: MaskRect("reason", 0, 0, 10, 10, ""), "mask_purpose_empty"),
        (lambda: MaskRect("zero", 0, 0, 0, 10, "理由"), "mask_empty"),
        (lambda: MaskRect("negative", 0, 0, -1, 10, "理由"), "mask_negative_size"),
        (lambda: MaskRect("negative-y", 0, -1, 10, 10, "理由"), "mask_outside_canvas"),
        (lambda: MaskRect("fraction", 0.5, 0, 10, 10, "理由"), "mask_not_integer"),
    ]
    for factory, code in cases:
        with pytest.raises(VisualCompareError) as excinfo:
            factory()
        assert excinfo.value.code == code, code

    with pytest.raises(VisualCompareError) as excinfo:
        build_mask((MaskRect("outside", 1440, 0, 10, 10, "全越界"),))
    assert excinfo.value.code == "mask_outside_canvas"

    with pytest.raises(VisualCompareError) as excinfo:
        build_mask(
            (
                MaskRect("dup", 0, 0, 10, 10, "理由"),
                MaskRect("dup", 20, 20, 10, 10, "理由"),
            )
        )
    assert excinfo.value.code == "mask_name_duplicate"


def test_mask_area_upper_bound_is_enforced_by_default() -> None:
    exact_limit = build_mask((MaskRect("limit", 0, 0, 1440, 315, "恰好 35%"),))
    assert exact_limit.ratio == pytest.approx(DEFAULT_MASK_AREA_LIMIT)
    with pytest.raises(VisualCompareError) as excinfo:
        build_mask((MaskRect("over", 0, 0, 1440, 316, "超过 35%"),))
    assert excinfo.value.code == "mask_area_exceeded"


def test_mask_area_limit_can_be_tightened_but_never_relaxed() -> None:
    with pytest.raises(VisualCompareError) as excinfo:
        build_mask((MaskRect("over", 0, 0, 200, 200, "超过自定上限"),), area_limit=0.01)
    assert excinfo.value.code == "mask_area_exceeded"

    for attempt in (0.5, 1.0):
        with pytest.raises(VisualCompareError) as excinfo:
            build_mask((), area_limit=attempt)
        assert excinfo.value.code == "mask_area_limit_relaxed"

    with pytest.raises(VisualCompareError) as excinfo:
        build_mask((), area_limit=None)  # type: ignore[arg-type]
    assert excinfo.value.code == "mask_area_limit_disabled"

    with pytest.raises(VisualCompareError) as excinfo:
        build_mask((), area_limit=0)
    assert excinfo.value.code == "mask_area_limit_invalid"


def test_masked_pixels_are_excluded_from_the_difference_statistics() -> None:
    reference = _solid((0, 0, 0))
    actual = _with_pixels(_solid((0, 0, 0)), {(10, 10): (255, 255, 255)})
    stats = compare_images(
        reference,
        actual,
        masks=(MaskRect("moving-cover", 0, 0, 100, 100, "fixture 封面"),),
    )
    assert stats.diff_pixels == 0
    assert stats.max_channel_delta == 0
    assert stats.mask_pixels == 10_000


# ---------------------------------------------------------------------------
# 确定性与产物边界
# ---------------------------------------------------------------------------


def test_three_consecutive_runs_are_identical() -> None:
    reference = _solid((12, 34, 56), size=REFERENCE_SOURCE_SIZE)
    actual = _with_pixels(_solid((12, 34, 56)), {(700, 400): (200, 34, 56)})
    masks = (MaskRect("text", 100, 100, 300, 40, "字形边缘"),)
    reports = [compare_images(reference, actual, masks=masks).as_report() for _ in range(3)]
    assert reports[0] == reports[1] == reports[2]
    assert reports[0]["diff_pixels"] == 1


def test_diff_image_is_written_only_when_requested(tmp_path: Path) -> None:
    reference = _solid()
    actual = _with_pixels(reference, {(3, 3): (0, 0, 0)})
    before = sorted(path.name for path in tmp_path.iterdir())

    stats = compare_images(reference, actual)
    assert stats.diff_written is False
    assert sorted(path.name for path in tmp_path.iterdir()) == before

    target = tmp_path / "diff.png"
    written = compare_images(reference, actual, diff_path=target)
    assert written.diff_written is True
    assert target.is_file()
    assert sorted(path.name for path in tmp_path.iterdir()) == [*before, "diff.png"]
    with Image.open(target) as diff_image:
        assert diff_image.size == CANVAS_SIZE


def test_diff_target_must_be_a_png_in_an_existing_directory(tmp_path: Path) -> None:
    with pytest.raises(VisualCompareError) as excinfo:
        compare_images(_solid(), _solid(), diff_path=tmp_path / "diff.jpg")
    assert excinfo.value.code == "diff_target_not_png"

    with pytest.raises(VisualCompareError) as excinfo:
        compare_images(_solid(), _solid(), diff_path=tmp_path / "missing" / "diff.png")
    assert excinfo.value.code == "diff_target_missing"


def test_report_exposes_required_fields_without_paths_or_pixel_payload(tmp_path: Path) -> None:
    reference = _solid((0, 0, 0))
    actual = _with_pixels(_solid((0, 0, 0)), {(1, 1): (255, 255, 255)})
    stats: CompareStats = compare_images(
        reference,
        actual,
        masks=(MaskRect("arc", 100, 100, 8, 8, "旋转进度弧"),),
    )
    report = stats.as_report()
    assert set(report) >= {
        "canvas_pixels",
        "compared_pixels",
        "diff_pixels",
        "diff_ratio",
        "max_channel_delta",
        "mask_pixels",
        "mask_ratio",
        "masks",
    }
    assert report["masks"][0]["name"] == "arc"
    assert report["masks"][0]["purpose"] == "旋转进度弧"
    assert report["masks"][0]["area"] == 64

    text = json.dumps(report, ensure_ascii=False)
    assert str(tmp_path) not in text
    assert "/" not in text
    assert stats.within(0.005) is True
    assert stats.within(0.0) is False
    with pytest.raises(VisualCompareError) as excinfo:
        stats.within(1.5)
    assert excinfo.value.code == "threshold_out_of_range"


def test_region_limits_the_comparison_to_a_fixed_rectangle(tmp_path: Path) -> None:
    """壳层硬门禁只比较固定条带，而不是靠整页掩码隐藏页面专属区域。"""
    reference = _solid((0, 0, 0))
    actual = _with_pixels(_solid((0, 0, 0)), {(400, 10): (255, 255, 255)})
    full = compare_images(reference, actual)
    assert full.diff_pixels == 1

    stats = compare_images(
        reference,
        actual,
        region=(0, 0, 200, 60),
        masks=(MaskRect("brand", 0, 0, 50, 20, "品牌文字字形"),),
    )
    assert stats.canvas == (200, 60)
    assert stats.canvas_pixels == 200 * 60
    assert stats.compared_pixels == 200 * 60 - 50 * 20
    assert stats.diff_pixels == 0
    assert stats.mask_pixels == 50 * 20

    inside = _with_pixels(_solid((0, 0, 0)), {(150, 30): (255, 255, 255)})
    assert compare_images(reference, inside, region=(0, 0, 200, 60)).diff_pixels == 1


def test_region_and_mask_validation_fail_closed() -> None:
    assert validate_region(None) is None
    with pytest.raises(VisualCompareError) as excinfo:
        validate_region((0, 0, 200))
    assert excinfo.value.code == "region_invalid"

    for bad in ((-1, 0, 200, 60), (0, 0, 1441, 60), (10, 0, 10, 60), (0, 20, 200, 20)):
        with pytest.raises(VisualCompareError) as excinfo:
            validate_region(bad)
        assert excinfo.value.code == "region_out_of_canvas", bad

    # A mask that no longer intersects the cropped region is rejected instead of
    # being silently ignored.
    with pytest.raises(VisualCompareError) as excinfo:
        compare_images(
            _solid(),
            _solid(),
            region=(0, 0, 200, 60),
            masks=(MaskRect("outside", 400, 400, 10, 10, "区域外掩码"),),
        )
    assert excinfo.value.code == "mask_outside_canvas"


def test_find_visual_artifacts_flags_stray_outputs(tmp_path: Path) -> None:
    (tmp_path / "tests" / "generated").mkdir(parents=True)
    (tmp_path / "tests" / "generated" / "screenshot.png").write_bytes(b"x")
    (tmp_path / "frontend" / "node_modules").mkdir(parents=True)
    (tmp_path / "frontend" / "node_modules" / "vendored.png").write_bytes(b"x")
    (tmp_path / "frontend" / "dist").mkdir(parents=True)
    (tmp_path / "frontend" / "dist" / "asset.png").write_bytes(b"x")

    assert find_visual_artifacts(tmp_path) == ("tests/generated/screenshot.png",)


def test_repository_has_no_visual_run_artifacts() -> None:
    assert find_visual_artifacts(REPO_ROOT) == ()
