"""设计图测量、冻结 Token 硬门禁目标与像素门禁裁决记录。

坐标来源
--------
``SHELL_MEASUREMENTS`` 是 ``tests/visual/measure.py`` 对归一化设计图的实测结果
（六张 ``1586x992`` 源 PNG 以固定 LANCZOS 归一化到 ``1440x900`` 后按背景色差求
内容带），保留为 Stage 46 的可复现追溯证据。

``REDESIGN_SHELL_MEASUREMENTS`` 是同工具对现行设计图的实测（``measure_redesign_shell``），
只作 Issue 109 壳层数值基线的人工对照与诊断。可审核的硬门禁是 ``shell_anchors_for``：
1280／1440／1920 下由冻结 Token 直接决定的容器盒、档位内边距与控件居中位置。

像素门禁裁决（3C）
------------------
现有六张设计 PNG 与冻结 Design Token V1 存在系统性几何冲突（见
``MOCKUP_VS_TOKEN_DELTAS``）。按总体 PRD 第 2.1 节的规格优先级，Token 明确数值
优先；实测证明无法用不超过 35% 的命名掩码覆盖两者的差异带（并集需 55.14%），
而 PRD 同时禁止整卡掩码。

因此**不对设计 PNG 启用 ≤0.5% 的像素硬门禁**。设计 PNG 只用于
归一化、fixture 状态诊断和非冲突视觉方向核对。硬门禁是：比较器确定性、
fixture 连续三次稳定、冻结 Token 的 computed style、控件尺寸、可访问性、关键 DOM
几何、路由与安全 canary。

若要恢复「设计图像素级验收」，必须先提供并审批一套与冻结 Token V1
一致的新参考图或正式测量基线；在此之前不得把现有 PNG 的 ≤0.5% 写成硬门禁。
"""

from __future__ import annotations

from dataclasses import dataclass

CANVAS_WIDTH = 1440
CANVAS_HEIGHT = 900

# Issue 109 shell numeric baseline (Token V1 §6.1 + §6.2). The 1440×900 canvas
# stays the primary acceptance canvas and every number below is measured at
# 1280/1440/1920 desktop widths; mockup bitmaps are human comparison aids only.
SHELL_HEADER_HEIGHT = 72.0
SHELL_NAV_HEIGHT = 44.0
SHELL_STATUS_HEIGHT = 36.0
CONTENT_MAX = 1512.0
SHELL_VIEWPORTS: tuple[int, ...] = (1280, 1440, 1920)


def content_padding_inline(width: int) -> float:
    """镜像 tokens.css 的 ``--content-padding-inline``（Token V1 §6.1 宽度档位）。

    紧凑桌面 <1440 取 24px，标准桌面 1440–1679 取 32px（1440×900 验收画布），
    宽桌面 ≥1680 取 48px。实现与断言共用同一档位映射，避免两处漂移。
    """
    if width >= 1680:
        return 48.0
    if width >= 1440:
        return 32.0
    return 24.0


SHELL_MEASUREMENTS: dict[str, object] = {
    "method": "tests/visual/measure.py（LANCZOS 归一化 + 背景色差内容带）",
    "header_text_rows": (30, 55),
    "underline_rows": (81, 86),
    "brand_text_x": (120, 264),
    "nav_text_x": ((324, 406), (457, 535), (592, 670), (729, 767)),
    "status_text_x": (1300, 1377),
    "status_surface_x": (1285, 1396),
    "underline_color_rgb": (250, 100, 85),
    "background_rgb": (254, 253, 251),
    "nav_font_px": 20,
    "home_control_height_px": 70,
    "segmented_track_height_px": 64,
}

MOCKUP_VS_TOKEN_DELTAS: tuple[tuple[str, str, str], ...] = (
    ("header height", "86 px (设计图下划线底缘)", "72 px (--top-nav-height)"),
    ("brand left", "121 px (设计图留白)", "20 px (--space-5 页内边距)"),
    ("nav font", "≈20 px", "15 px (--type-body)"),
    ("home control height", "70 px", "52 px (--control-height-lg)"),
    ("segmented track height", "64 px", "60 px (52 px 选项 + 2×4 px 轨道内边距)"),
    ("status pill right", "1397 px", "页内边距右对齐 (1420 px)"),
)

REDESIGN_SHELL_MEASUREMENTS: dict[str, object] = {
    "method": "tests/visual/measure.py::measure_redesign_shell（LANCZOS 归一化 + 背景色差内容带）",
    "source": "docs/design/assets/frontend-ux/redesign-2026-09-23/添加番剧－单番－搜索首屏.png (1586x992 PNG, LANCZOS -> 1440x900)",
    "header_band_rows": (0, 74),
    "header_text_rows": (24, 48),
    "underline_rows": (61, 63),
    "brand_text_x": (49, 196),
    "nav_first_text_x": (263, 278),
    "status_surface_x": (1296, 1394),
}
"""Issue 109 现行设计图的壳层实测；只作人工对照与诊断，不改写 Token 门禁。"""

REDESIGN_VS_TOKEN_DELTAS: tuple[tuple[str, str, str], ...] = (
    ("header band height", "75 px (0..74，图内白底带)", "72 px (--size-shell-header)"),
    ("brand left", "49 px (图内留白)", "32 px (1440 档 --content-padding-inline)"),
    ("nav first glyph", "263 px (紧随品牌的左组)", "随品牌文本宽度 + --space-10 组合，非独立常量"),
    ("status pill right", "1394 px", "1408 px (内容容器右缘 − 32 px 档位内边距)"),
)
"""现行设计图取景近似（生成器非精确像素），Token 档位与浏览器实测优先。"""

PIXEL_GATE_RULING = {
    "ruling": "3C",
    "design_pixel_gate_enabled": False,
    "reason": (
        "设计图与冻结 Token V1 的几何冲突使差异带并集需要 55.14% 命名掩码，"
        "超过 35% 上限且不允许整卡掩码；按规格优先级采用 Token 值。"
    ),
    "stage46_hard_gates": (
        "比较器确定性",
        "fixture 连续三次稳定",
        "冻结 Token 的 computed style",
        "控件尺寸（44/52px、>=44x44px）",
        "可访问性（键盘、焦点环、对比度、reduced-motion）",
        "关键 DOM 几何",
        "路由与安全 canary",
    ),
    "stage47_48_precondition": (
        "若要恢复设计图像素级验收，必须先提供并审批一套与冻结 Token V1 一致的新参考图或正式测量基线。"
    ),
}

SHELL_REGION: tuple[int, int, int, int] = (0, 0, CANVAS_WIDTH, 90)
"""顶栏诊断区域：涵盖冻结 Token 的 72px 顶栏带。仅用于诊断输出，不设阈值。"""

CONTROLS_REGION: tuple[int, int, int, int] = (280, 300, 1160, 530)
"""共享控件诊断区域：图 01/04 的模式切换 + 搜索控件带。仅用于诊断输出。"""

CONTROLS_TOKEN_GEOMETRY: dict[str, float] = {
    "control_height_md": 44.0,
    "control_height_lg": 52.0,
    "control_target_min": 44.0,
    "segmented_track_height": 60.0,
}
"""共享控件的冻结 token 几何（硬门禁目标）。"""


@dataclass(frozen=True)
class AnchorTarget:
    """一个锚点的目标几何（CSS 像素，相对视口左上角）。

    ``fields`` 限定真正参与硬门禁的几何量：只有由冻结 token 直接决定的量
    （容器盒、内边距、控件居中位置）纳入门禁，字体渲染与设计图布局决定的量记为诊断。
    """

    name: str
    selector: str
    x: float
    y: float
    width: float
    height: float
    purpose: str
    fields: tuple[str, ...] = ("x", "y", "width", "height")
    enforced: bool = True
    tolerance: float = 2.0
    right: float = 0.0

    def matches(self, box: dict[str, float]) -> bool:
        return all(abs(box[field] - float(getattr(self, field))) <= self.tolerance for field in self.fields)

    def deviation(self, box: dict[str, float]) -> dict[str, float]:
        return {field: round(box[field] - float(getattr(self, field)), 2) for field in self.fields}


def shell_anchors_for(width: int) -> tuple[AnchorTarget, ...]:
    """给定桌面宽度下壳层的可审核锚点（Issue 109 数值基线）。

    只纳入由 Token 直接决定的量：视口/容器盒、档位内边距决定的品牌左缘、
    内容容器右缘决定的连接胶囊右缘，以及控件在 72px 顶栏内的垂直居中位置。
    品牌宽度、导航左缘与文本渲染相关，记为诊断而非门禁。
    """
    container_width = min(float(width), CONTENT_MAX)
    container_left = (float(width) - container_width) / 2.0
    padding = content_padding_inline(width)
    return (
        AnchorTarget(
            "shell.header",
            ".app-header",
            0.0,
            0.0,
            float(width),
            SHELL_HEADER_HEIGHT,
            "顶栏铺满视口，高 = --size-shell-header（--top-nav-height 72px）",
        ),
        AnchorTarget(
            "shell.content",
            ".app-header-inner",
            container_left,
            0.0,
            container_width,
            SHELL_HEADER_HEIGHT,
            "壳层内容容器 = min(100%, --size-content-max 1512px) 居中，高 72px",
        ),
        AnchorTarget(
            "shell.brand",
            ".brand-block",
            container_left + padding,
            0.0,
            0.0,
            0.0,
            "品牌左缘 = 内容容器左缘 + --content-padding-inline 档位内边距",
            fields=("x",),
        ),
        AnchorTarget(
            "shell.nav-first",
            "#shell-nav-1",
            0.0,
            (SHELL_HEADER_HEIGHT - SHELL_NAV_HEIGHT) / 2,
            0.0,
            0.0,
            "首项导航垂直位置 = (72 - --control-height-md 44) / 2",
            fields=("y",),
        ),
        AnchorTarget(
            "shell.status",
            ".workspace-status",
            0.0,
            (SHELL_HEADER_HEIGHT - SHELL_STATUS_HEIGHT) / 2,
            0.0,
            SHELL_STATUS_HEIGHT,
            "连接胶囊 = --control-height-sm 36px 且在 72px 顶栏内垂直居中",
            fields=("y", "height"),
        ),
        AnchorTarget(
            "shell.status-right",
            ".workspace-status",
            0.0,
            0.0,
            0.0,
            0.0,
            "连接胶囊右缘 = 内容容器右缘 - 档位内边距（品牌与导航保持左组）",
            fields=("right",),
            right=container_left + container_width - padding,
        ),
        AnchorTarget(
            "shell.main",
            ".app-main",
            container_left,
            SHELL_HEADER_HEIGHT,
            container_width,
            0.0,
            "页面容器与顶栏内容同宽同轴，内容自 y=72 起",
            fields=("x", "y", "width"),
        ),
    )


SHELL_ANCHORS: tuple[AnchorTarget, ...] = shell_anchors_for(CANVAS_WIDTH)
"""1440×900 主验收画布的壳层锚点（兼容既有调用方）。"""

SHELL_DIAGNOSTIC_ANCHORS: tuple[AnchorTarget, ...] = (
    AnchorTarget(
        "mockup.brand-left",
        ".brand-block",
        float(REDESIGN_SHELL_MEASUREMENTS["brand_text_x"][0]),
        0.0,
        0.0,
        0.0,
        "现行设计图品牌左缘实测 49（token 优先，仅记录差距）",
        fields=("x",),
        enforced=False,
    ),
    AnchorTarget(
        "mockup.nav-first-left",
        "#shell-nav-1",
        float(REDESIGN_SHELL_MEASUREMENTS["nav_first_text_x"][0]) - 12.0,
        0.0,
        0.0,
        0.0,
        "现行设计图首项导航盒左缘实测 251（token 优先，仅记录差距）",
        fields=("x",),
        enforced=False,
    ),
    AnchorTarget(
        "mockup.status-right",
        ".workspace-status",
        0.0,
        0.0,
        0.0,
        0.0,
        "现行设计图胶囊右缘实测 1394（token 优先，仅记录差距）",
        fields=("right",),
        enforced=False,
        right=float(REDESIGN_SHELL_MEASUREMENTS["status_surface_x"][1]),
    ),
)

SHELL_ANCHOR_SELECTORS: dict[str, str] = {
    anchor.name: anchor.selector
    for anchor in (*SHELL_ANCHORS, *SHELL_DIAGNOSTIC_ANCHORS)
}
