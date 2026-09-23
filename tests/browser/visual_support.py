"""Stage 46：真实 Chromium 视觉 fixture 的共享基础设施（测试期专用）。

职责：
- 固定标准像素环境（1440×900、reduced-motion、隐藏光标/插入符）；
- 等待 ``document.fonts.ready``、全部图片、以及两个 ``requestAnimationFrame``，
  不用任意 sleep 猜稳定；
- 把截图限制在 pytest ``tmp_path``，并调用 US-358 的确定性比较 helper；
- 采集壳层/页面锚点的 DOM 几何，供 manifest 断言；
- 统一的 canary 边界断言（DOM/属性/URL/history/storage/console/截图/diff）。

本模块不访问真实 MiKan、Auto Bangumi 或 qBittorrent，也不写仓库路径。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image
from playwright.sync_api import Page

from tests.browser.visual_manifest import (
    SHELL_ANCHOR_SELECTORS,
    SHELL_REGION,
    AnchorTarget,
)
from tests.visual.compare import CANVAS_SIZE, CompareStats, MaskRect, compare_images, read_image

REPO_ROOT = Path(__file__).resolve().parents[2]
DESIGN_DIR = REPO_ROOT / "docs/design/assets/frontend-ux/archive/review-2026-09-17"

DESIGN_FILES: dict[int, str] = {
    1: "01-single-search.png",
    2: "02-single-candidates-loading.png",
    3: "03-single-draft-review.png",
    4: "04-batch-search-loading.png",
    5: "05-batch-candidates-loading.png",
    6: "06-batch-draft-review.png",
}

CANVAS: tuple[int, int] = CANVAS_SIZE

_STABILITY_CSS = """
*, *::before, *::after {
  cursor: none !important;
  caret-color: transparent !important;
  animation: none !important;
  transition: none !important;
}
"""

_WAIT_SCRIPT = """
async () => {
  await document.fonts.ready;
  const images = Array.from(document.images);
  await Promise.all(
    images.map((image) =>
      image.complete
        ? Promise.resolve()
        : new Promise((resolve) => {
            image.addEventListener('load', resolve, { once: true });
            image.addEventListener('error', resolve, { once: true });
          }),
    ),
  );
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
}
"""


UNCONFIGURED_CONNECTION_BODY = json.dumps(
    {
        "ok": True,
        "result": {
            "configured": False,
            "credential_present": False,
            "connection_status": "UNCONFIGURED",
            "capabilities": None,
        },
    },
    ensure_ascii=False,
)
"""固定的「未配置」连接摘要：视觉/几何门禁不依赖部署端连接状态。"""

EMPTY_TRACKING_ITEMS_BODY = json.dumps({"ok": True, "result": {"items": []}}, ensure_ascii=False)
"""固定的空追番列表：待处理数量恒为 0，避免跨用例漂移。"""


def install_shell_status_routes(
    page: Page,
    *,
    connection_body: str | None = None,
    tracking_body: str | None = None,
) -> None:
    """统一注册 settings/tracking mock，避免各用例各写一份而逐步漂移。"""
    connection = connection_body if connection_body is not None else UNCONFIGURED_CONNECTION_BODY
    tracking = tracking_body if tracking_body is not None else EMPTY_TRACKING_ITEMS_BODY
    page.route(
        "**/api/v1/settings/autobangumi",
        lambda route: route.fulfill(status=200, content_type="application/json", body=connection),
    )
    page.route(
        "**/api/v1/tracking/items**",
        lambda route: route.fulfill(status=200, content_type="application/json", body=tracking),
    )


def require_dist() -> None:
    """SPA 生产构建是浏览器视觉用例的硬前置。"""
    if (REPO_ROOT / "frontend" / "dist" / "index.html").is_file():
        return
    raise RuntimeError(
        "frontend/dist missing — run `cd frontend && npm run build` before browser visual fixtures."
    )


def prepare_canvas(page: Page) -> None:
    """固定 1440×900 标准桌面画布，并把非必要动画降到 reduced-motion。"""
    page.set_viewport_size({"width": CANVAS[0], "height": CANVAS[1]})
    page.emulate_media(reduced_motion="reduce")


def install_stability_styles(page: Page) -> None:
    """比较前统一隐藏光标与插入符（否则闪烁相位会污染差异统计）。"""
    page.add_style_tag(content=_STABILITY_CSS)


def wait_for_visual_stability(page: Page) -> None:
    """等待字体、图片与双帧；替代任意 sleep。"""
    page.evaluate(_WAIT_SCRIPT)


def capture_canvas(page: Page, path: Path) -> Path:
    """截取恰好 1440×900 的视口截图（不是 full_page）。"""
    install_stability_styles(page)
    wait_for_visual_stability(page)
    page.screenshot(path=str(path))
    with Image.open(path) as captured:
        captured.load()
        if captured.size != CANVAS:
            raise AssertionError(f"截图尺寸不是 {CANVAS}: {captured.size}")
    return path


def design_reference(index: int) -> Image.Image:
    """读取一张设计源图（只读，不修改源文件）。"""
    name = DESIGN_FILES[index]
    return read_image(DESIGN_DIR / name, error_code="reference_unreadable")


def compare_with_design(
    index: int,
    screenshot: Path,
    *,
    region: tuple[int, int, int, int] | None = None,
    masks: tuple[MaskRect, ...] = (),
    diff_path: Path | None = None,
) -> CompareStats:
    """把截图与归一化设计图比较；所有产物路径只能落在 tmp_path。"""
    return compare_images(
        design_reference(index),
        read_image(screenshot, error_code="actual_unreadable"),
        masks=masks,
        diff_path=diff_path,
        region=region,
    )


def compare_shell(screenshot: Path, *, diff_path: Path | None = None) -> CompareStats:
    """壳层诊断：只统计顶栏条带的差异。

    按像素门禁裁决 3C，Stage 46 不对设计 PNG 设 ≤0.5% 硬阈值；本函数只产出
    可核对的诊断值，``test_shell_region_diagnostics_are_deterministic`` 只断言
    统计的确定性、合法性与连续三次一致。
    """
    return compare_with_design(1, screenshot, region=SHELL_REGION, diff_path=diff_path)


def collect_anchor_boxes(page: Page, selectors: dict[str, str]) -> dict[str, dict[str, float] | None]:
    """采集 selector 的视口几何；缺失元素返回 None（由调用方判定失败）。"""
    return page.evaluate(
        """(selectors) => {
            const result = {};
            for (const [name, selector] of Object.entries(selectors)) {
                const element = document.querySelector(selector);
                if (!element) { result[name] = null; continue; }
                const rect = element.getBoundingClientRect();
                result[name] = {
                    x: rect.x, y: rect.y, width: rect.width, height: rect.height,
                };
            }
            return result;
        }""",
        selectors,
    )


def collect_shell_anchors(page: Page) -> dict[str, dict[str, float] | None]:
    return collect_anchor_boxes(page, SHELL_ANCHOR_SELECTORS)


def anchor_summary(
    page: Page,
    anchors: tuple[AnchorTarget, ...],
) -> dict[str, Any]:
    """给出一组锚点的实测值、偏差与是否满足 <= 2 CSS px。"""
    boxes = collect_anchor_boxes(page, {anchor.name: anchor.selector for anchor in anchors})
    summary: dict[str, Any] = {}
    for anchor in anchors:
        box = boxes.get(anchor.name)
        if box is None:
            summary[anchor.name] = {"found": False, "selector": anchor.selector}
            continue
        summary[anchor.name] = {
            "found": True,
            "selector": anchor.selector,
            "box": {key: round(value, 2) for key, value in box.items()},
            "target": {
                "x": anchor.x,
                "y": anchor.y,
                "width": anchor.width,
                "height": anchor.height,
            },
            "deviation": anchor.deviation(box),
            "fields": list(anchor.fields),
            "enforced": anchor.enforced,
            "within_tolerance": anchor.matches(box),
            "purpose": anchor.purpose,
        }
    return summary


def browser_surface(page: Page) -> dict[str, str]:
    """收集 canary 必须保持干净的客户端边界。"""
    return page.evaluate(
        """() => ({
            url: window.location.href,
            historyState: JSON.stringify(window.history.state),
            localStorage: JSON.stringify(window.localStorage),
            sessionStorage: JSON.stringify(window.sessionStorage),
            bodyText: document.body.innerText,
            bodyHtml: document.body.innerHTML,
            attributes: Array.from(document.querySelectorAll('*'))
              .flatMap((element) => Array.from(element.attributes).map((a) => `${a.name}=${a.value}`))
              .join('\\n'),
        })"""
    )


STABILITY_NOISE_RATIO = 0.0001
"""连续截图允许的栅格化噪声比例（画布像素的 0.01%）。

同一环境下重复截图仍可能出现个位数像素的子像素栅格化差异。尺寸与 DOM 锚点必须
严格相等；只有差异统计在该噪声带内容忍，且它远小于 Stage 46 的 0.5% 口径，
不构成对业务或布局漂移的放宽。
"""


def stability_noise_pixels(canvas_pixels: int) -> int:
    return max(16, round(canvas_pixels * STABILITY_NOISE_RATIO))


def assert_stable_reports(reports: list[dict[str, Any]]) -> None:
    """断言连续三次截图的几何严格一致、差异统计只在栅格化噪声带内波动。"""
    assert reports, "at least one report is required"
    first = reports[0]
    canvas_pixels = int(first["compared_pixels"]) + int(first["mask_pixels"])
    noise = stability_noise_pixels(canvas_pixels)
    for report in reports:
        assert report["canvas"] == first["canvas"]
        assert report["compared_pixels"] == first["compared_pixels"]
        assert report["mask_pixels"] == first["mask_pixels"]
        assert report["resample"] == first["resample"]
        assert report["channel_threshold"] == first["channel_threshold"]
        assert abs(int(report["diff_pixels"]) - int(first["diff_pixels"])) <= noise
        assert report["masks"] == first["masks"]


def report_json(report: dict[str, Any]) -> str:
    """把诊断报告序列化成稳定字符串（用于三次稳定性比较）。"""
    return json.dumps(report, ensure_ascii=False, sort_keys=True)
