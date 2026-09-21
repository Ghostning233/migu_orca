"""Stage 46：设计图测量、冻结 Token 硬门禁目标与像素门禁裁决记录。

坐标来源
--------
``SHELL_MEASUREMENTS`` 是 ``tests/visual/measure.py`` 对归一化设计图的实测结果
（六张 ``1586x992`` 源 PNG 以固定 LANCZOS 归一化到 ``1440x900`` 后按背景色差求
内容带），保留为可复现证据，供文档与诊断核对。

像素门禁裁决（3C）
------------------
现有六张设计 PNG 与冻结 Design Token V1 存在系统性几何冲突（见
``MOCKUP_VS_TOKEN_DELTAS``）。按总体 PRD 第 2.1 节的规格优先级，Token 明确数值
优先；实测证明无法用不超过 35% 的命名掩码覆盖两者的差异带（并集需 55.14%），
而 PRD 同时禁止整卡掩码。

因此 Stage 46 **不对现有六张 PNG 启用 ≤0.5% 的设计图像素硬门禁**。设计 PNG 只用于
归一化、fixture 状态诊断和非冲突视觉方向核对。Stage 46 的硬门禁是：比较器确定性、
fixture 连续三次稳定、冻结 Token 的 computed style、控件尺寸、可访问性、关键 DOM
几何、路由与安全 canary。

Stage 47/48 若要恢复「设计图像素级验收」，必须先提供并审批一套与冻结 Token V1
一致的新参考图或正式测量基线；在此之前不得把现有六张 PNG 的 ≤0.5% 写成硬门禁。
"""

from __future__ import annotations

from dataclasses import dataclass

CANVAS_WIDTH = 1440
CANVAS_HEIGHT = 900

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

    def matches(self, box: dict[str, float]) -> bool:
        return all(abs(box[field] - float(getattr(self, field))) <= self.tolerance for field in self.fields)

    def deviation(self, box: dict[str, float]) -> dict[str, float]:
        return {field: round(box[field] - float(getattr(self, field)), 2) for field in self.fields}


SHELL_ANCHORS: tuple[AnchorTarget, ...] = (
    AnchorTarget(
        "shell.header",
        ".app-header",
        0.0,
        0.0,
        CANVAS_WIDTH,
        72.0,
        "顶栏高度 = --size-shell-header（--top-nav-height 72px）",
    ),
    AnchorTarget(
        "shell.content",
        ".app-header-inner",
        0.0,
        0.0,
        CANVAS_WIDTH,
        72.0,
        "壳层内容容器 = min(100%, --size-content-max)，高 72px",
    ),
    AnchorTarget(
        "shell.brand",
        ".brand-block",
        20.0,
        0.0,
        0.0,
        0.0,
        "品牌左缘 = --space-5 页内边距（20px）",
        fields=("x",),
    ),
    AnchorTarget(
        "shell.nav-first",
        "#shell-nav-1",
        0.0,
        14.0,
        0.0,
        0.0,
        "首项导航垂直位置 = (72 - --control-height-md 44) / 2",
        fields=("y",),
    ),
    AnchorTarget(
        "shell.status",
        ".workspace-status",
        0.0,
        18.0,
        0.0,
        36.0,
        "连接胶囊 = --control-height-sm 36px 且与顶栏右侧对齐",
        fields=("y", "height"),
    ),
)

SHELL_DIAGNOSTIC_ANCHORS: tuple[AnchorTarget, ...] = (
    AnchorTarget(
        "mockup.brand-left",
        ".brand-block",
        float(SHELL_MEASUREMENTS["brand_text_x"][0]),
        0.0,
        0.0,
        0.0,
        "设计图品牌左缘实测 121（token 优先，仅记录差距）",
        fields=("x",),
        enforced=False,
    ),
    AnchorTarget(
        "mockup.nav-first-left",
        "#shell-nav-1",
        float(SHELL_MEASUREMENTS["nav_text_x"][0][0]) - 12.0,
        0.0,
        0.0,
        0.0,
        "设计图首项导航盒左缘实测 312（token 优先，仅记录差距）",
        fields=("x",),
        enforced=False,
    ),
    AnchorTarget(
        "mockup.status-right",
        ".workspace-status",
        float(SHELL_MEASUREMENTS["status_surface_x"][1]) - 143.0,
        0.0,
        143.0,
        0.0,
        "设计图胶囊右缘实测 1397（token 优先，仅记录差距）",
        fields=("x", "width"),
        enforced=False,
    ),
    AnchorTarget(
        "mockup.nav-underline",
        "#shell-nav-1",
        312.0,
        0.0,
        0.0,
        0.0,
        "设计图当前项下划线左缘实测 313（token 优先，仅记录差距）",
        fields=("x",),
        enforced=False,
    ),
)

SHELL_ANCHOR_SELECTORS: dict[str, str] = {
    anchor.name: anchor.selector
    for anchor in (*SHELL_ANCHORS, *SHELL_DIAGNOSTIC_ANCHORS)
}
