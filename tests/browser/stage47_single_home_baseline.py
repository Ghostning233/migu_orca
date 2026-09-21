"""Stage 47 获批几何基线：图 01 / US-363 单番搜索首页。

来源：``docs/design/frontend-ux-stage47-single-anime-geometry-baseline.md``（2026-09-21 获批，
形态 B：本数值即正式测量基线）。间距/字号/控件高取冻结 Design Token V1；
页面专属量按获批数值断言：英雄区宽 720、主按钮宽 176、模式选项 min-width 112。

实现校正（同步记入 PRD 与 progress）：提案把「搜索行」记作 52px，实际该字段遵循
Token V1 §7.3「字段标签始终可见」，因此表单项高度是 label 21 + `--space-2` 8 + 输入 52 = 81px。
绝对 y 坐标因此随内容高度（415px）变化且依赖字体度量，本基线改为断言**可测量关系**：
容器盒尺寸、元素宽高、相邻元素间距、水平与垂直居中，而不是写死绝对 y。
"""

from __future__ import annotations

VIEWPORT = (1440, 900)

CONTENT_RECT = (32, 96, 1376, 780)
"""Token 档位页内边距（1440 -> 32px 水平）+ `--space-6` 24px 垂直内边距下的内容区。"""

HERO_CONTAINER_RECT = (360, 96, 720, 780)
"""英雄区容器盒：720px 居中，占满内容区高度。"""

HERO_CONTENT_HEIGHT = 421.4
"""英雄区内容块高度：48+8+24+24+62+32+81+16+22.4+40+64（轨道含边框、帮助文字 14/1.6）。"""

HERO_CONTENT_TOP = 275.3
"""内容块顶：96 + (780 − 421.4) / 2；实际由浏览器取整，门禁用 TOLERANCE。"""

CENTER_X = 720.0
"""1440 视口的内容水平中心。"""

TOLERANCE = 2.0

HOME_BOXES: dict[str, tuple[str, float, float]] = {
    "hero": (".single-home-hero", 720.0, 780.0),
    "title": ("#workbench-heading", 720.0, 48.0),
    "subtitle": (".single-home-subtitle", 720.0, 24.0),
    "mode": ("#anime-mode-switch", 238.0, 62.0),
    "form": ("#mikan-candidate-search-form", 720.0, 81.0),
    "query": ("#mikan-candidate-query", 532.0, 52.0),
    "submit": ("#mikan-candidate-search-submit", 176.0, 52.0),
    "help": (".single-home-help", 720.0, 22.4),
    "steps": (".journey-steps", 720.0, 64.0),
}
"""每个元素的 selector 与获批宽高。"""

HOME_CENTERED: tuple[str, ...] = ("hero", "title", "subtitle", "mode", "form", "help", "steps")
"""水平中心必须落在 CENTER_X 的元素。"""

HOME_SPACING: tuple[tuple[str, str, float], ...] = (
    ("title", "subtitle", 8.0),
    ("subtitle", "mode", 24.0),
    ("mode", "form", 32.0),
    ("form", "help", 16.0),
    ("help", "steps", 40.0),
)
"""相邻元素垂直间距（前一个 bottom -> 后一个 top），全部取自 `--space-*`。"""

HOME_SELECTORS: dict[str, str] = {name: selector for name, (selector, _, _) in HOME_BOXES.items()}
"""所有基线选择器，供实现与门禁共用。"""

HOME_ANCHOR_SELECTORS: dict[str, str] = {**HOME_SELECTORS, "content": ".app-main"}

FORBIDDEN_INITIAL_SELECTORS: tuple[str, ...] = (
    ".search-results-panel",
    "#mikan-candidate-search-result",
    ".candidate-card",
    ".candidate-fallback-rescue",
    ".effective-seed-group",
    "#detail-preview-edit-form",
    "#batch-parse-form",
)
"""单番初始态不得存在的结构：结果区、候选卡、救援面板、有效资源数与草案/批量区。"""
