"""#153：批量草案工作台的真实 Chromium 验收与获批视觉基准门禁。

覆盖（父规格 #145 的验收目标）：

- 草案默认态 / 标题搜索浮层 / 资源明细（有效资源与已排除）在 1440×900 的真实
  截图与关键几何；
- 1／12／36 部、1280×800／1440×900／1920×1080 与 200% 缩放下的单行底栏、
  末项可达、滚动条不可见但导航可用；
- 资源明细弹窗的页签、焦点恢复与工作台滚动位置；
- 固定安全 fixture 各状态连续三次截图稳定；当前四个获批状态另有像素和 DOM 锚点硬门禁。

用户已于 2026-10-02 审核当前实际界面并通过。四张 Chromium 金样、证据清单与 DOM 锚点
位于 `batch-draft/`，由独立 record 开关显式写入；普通候选开关只写旧的 `pending-batch-draft/`。
当前获批界面要求状态芯片独立成行、模块间留白清楚、资源指标/安全样例在同一描边盒内且无额外
分割线。批量搜索首屏主按钮水平居中也已获用户审核通过；底部操作行主按钮垂直居中是既有要求。

常规截图、diff 与诊断值只写 pytest ``tmp_path``。显式设置
``MIGU_ORCA_CAPTURE_REVIEW=1`` 时，候选图只写入
``docs/design/assets/frontend-ux/acceptance-baseline/add-anime/pending-batch-draft/``；
本轮获批基准仅由独立 ``MIGU_ORCA_RECORD_BATCH_DRAFT_BASELINE=1`` 记录入口写入。

本轮视觉锚点（实施前先记录，用于选择可维护的几何约束而不是复刻旧实现）
-----------------------------------------------------------------------

设计源图为 1586×992，主验收画布 1440×900，比例 0.908；下文的「归一化」值按比例
换算，只用于确定目标区间，不宣称逐像素一致。设计图是视觉方向，业务安全语义仍以
产品契约与失败/恢复状态要求为准。

以下视觉锚点是 2026-09-26 的设计推导历史记录；与用户 2026-10-02 审核通过的实际页面不一致时，
以当前页面金样、DOM 锚点及 §5 明确更新的验收口径为准。当前资源结果使用统一盒子与模块留白，
不再要求多余发丝线或指标间竖分割线。

历史设计推导：

壳层
  * 两栏是画布上的两张白卡，没有包裹整页的「管理表单外框」；页头是深海蓝大标题
    （约 45px 视觉 → 复用 ``--type-display`` 40px）加右侧「返回搜索首屏」胶囊按钮。
  * 珊瑚橙只做状态强调（状态芯片、已选真实合集），不做大面积填充。

左栏（设计 x 62..578 → 归一化宽约 468）
  * 卡片行的主扫描信息是封面 / 标题 / 状态芯片 / 当前查看 / 勾选或删除，而不是
    带边框的表格式诊断条目；当前查看项是淡蓝底 + 左缘强调条，不是描边高亮。
  * 封面约 98×82（归一化）、卡片高约 97、间距约 14、标题约 25px。归一化后的实现
    目标区间：封面宽 76..108、高 56..84、比例 1.1..1.5，卡片高 ≥ 80，标题字号
    ≥ 18px —— 明显大于旧实现的 48×44 紧凑占位，但保留设计图的比例关系。

右栏（设计 x 610..1560 → 归一化宽约 863）
  * 合集身份 → 字幕与筛选 → 资源结果 → 折叠的高级设置；这些层级顺序仍适用，旧的分区发丝线
    与资源指标竖分隔线不再是当前视觉要求。
  * 资源结果四项指标使用 CSS 图标，集数两项继续固定「未开发」；实际界面获批规则见上文。

底栏（设计高约 48）
  * 白底 + 1px 顶边 + 极弱投影，一行：全选 + 「已选 N 部」纯文本 + 深海蓝主按钮。

资源明细弹窗（设计归一化约 767×693）
  * 标题约 26px、双页签（激活项主色 + 下划线）、行高约 57、蓝色描边文档图标；
    有效资源需要足够多条以覆盖「多行可见 + 弹窗内滚动」，已排除需要多条带不同
    安全原因的记录；页脚左侧计数、右侧次级「关闭」。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from playwright.sync_api import Page, expect

from tests.browser.batch_draft_visual_fixtures import (
    BASELINE_DIR,
    BATCH_ID,
    CHECKED_ITEM_IDS,
    CLICKED_ITEM_ID,
    DRAFT_LINES,
    REVIEW_DIR,
    SELECTIONS,
    UNCONFIRMED_ITEM_ID,
    BatchDraftVisualScenario,
    batch_draft_items,
    canary_values,
    poster_path,
    raw_input_for,
    repeat_items,
)
from tests.browser.visual_manifest import SHELL_ANCHORS
from tests.browser.visual_support import (
    CANVAS,
    anchor_summary,
    browser_surface,
    capture_canvas,
    collect_anchor_boxes,
    compare_with_design,
    report_json,
    stability_noise_pixels,
)
from tests.visual.compare import compare_images, read_image

pytestmark = pytest.mark.browser

CAPTURE_STATES: tuple[str, ...] = (
    "draft-workbench",
    "title-search",
    "resource-detail-effective",
    "resource-detail-excluded",
)

APPROVED_ANCHORS: dict[str, dict[str, str]] = {
    "draft-workbench": {
        "heading": ".batch-workbench-panel .panel-heading h2",
        "toolbar": "#batch-accept-toolbar",
        "list": ".batch-card-grid-wrapper",
        "detail": "#batch-detail-pane",
        "current_card": '.batch-draft-card[data-item-id="item-01"]',
        "resource_box": ".batch-resource-box",
        "primary_action": "#batch-accept-submit",
    },
    "title-search": {
        "heading": ".batch-workbench-panel .panel-heading h2",
        "toolbar": "#batch-accept-toolbar",
        "list": ".batch-card-grid-wrapper",
        "detail": "#batch-detail-pane",
        "search_popover": "#batch-review-search-popover",
        "search_input": "#batch-review-search",
    },
    "resource-detail-effective": {
        "dialog": ".resource-dialog",
        "dialog_title": ".resource-dialog-title",
        "tabs": ".resource-dialog-tabs",
        "resource_list": "#batch-resource-detail-panel-effective",
        "first_resource": "#batch-resource-detail-panel-effective .resource-dialog-item:first-child",
        "dialog_footer": ".resource-dialog-footer",
    },
    "resource-detail-excluded": {
        "dialog": ".resource-dialog",
        "dialog_title": ".resource-dialog-title",
        "tabs": ".resource-dialog-tabs",
        "resource_list": "#batch-resource-detail-panel-excluded",
        "first_resource": "#batch-resource-detail-panel-excluded .resource-dialog-item:first-child",
        "dialog_footer": ".resource-dialog-footer",
    },
}

MAX_BASELINE_DIFF_RATIO = 0.005
MAX_BASELINE_MASK_RATIO = 0.05
BASELINE_ANCHOR_TOLERANCE = 2.0
BASELINE_STABILITY_REPEATS = 3


class TestBatchDraftWorkbenchVisual:
    """AC：固定 fixture 可确定性进入、可测量、可连续三次稳定截图。"""

    def _scenario(
        self,
        page: Page,
        live_server_url: str,
        storage_dir: Path,
        *,
        items: list[dict[str, Any]] | None = None,
    ) -> BatchDraftVisualScenario:
        scenario = BatchDraftVisualScenario(page, live_server_url)
        scenario.install(storage_dir, items=items)
        return scenario

    def _capture_state(
        self,
        scenario: BatchDraftVisualScenario,
        name: str,
        tmp_path: Path,
        *,
        suffix: str = "",
    ) -> Path:
        """按状态名把页面推进到目标状态并截图（幂等，可重复调用）。"""
        scenario.goto_state(name)
        scenario.dismiss_toast()
        return capture_canvas(scenario.page, tmp_path / f"{name}{suffix}.png")

    def test_draft_workbench_geometry_targets_the_approved_direction(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """AC：#145 的审核工作台层级与单行底栏在真实 Chromium 中成立。

        断言表达的是设计目标（见模块 docstring 的视觉锚点），不是把当前实现尺寸
        固化为「正确」：封面、卡片高度、标题字号与页头层级都要求落在设计比例区间内，
        并明显大于旧的 48×44 紧凑占位。
        """
        scenario = self._scenario(page, live_server_url, storage_dir)
        scenario.enter_draft_workbench()

        geometry = page.evaluate(
            """() => {
                const box = (selector) => {
                    const element = document.querySelector(selector)
                    return element ? element.getBoundingClientRect() : null
                }
                const style = (selector, property) => {
                    const element = document.querySelector(selector)
                    return element ? getComputedStyle(element)[property] : null
                }
                const number = (selector, property) => {
                    const element = document.querySelector(selector)
                    return element ? parseFloat(getComputedStyle(element)[property]) || 0 : 0
                }
                const list = document.querySelector('.batch-card-grid-wrapper')
                const pane = document.querySelector('#batch-detail-pane')
                const column = document.querySelector('.batch-review-list-column')
                const currentCard = document.querySelector('.batch-draft-card[data-item-id="item-01"]')
                const otherCard = document.querySelector('.batch-draft-card[data-item-id="item-02"]')
                const poster = document.querySelector('.batch-draft-card[data-item-id="item-01"] .batch-card-poster')
                const chip = document.querySelector('.batch-draft-card[data-item-id="item-01"] .batch-card-status')
                return {
                    title: box('.batch-workbench-panel .panel-heading h2'),
                    titleFontSize: number('.batch-workbench-panel .panel-heading h2', 'fontSize'),
                    toolbar: box('#batch-accept-toolbar'),
                    row: box('.batch-accept-row'),
                    checkbox: box('#batch-select-all-checkbox'),
                    count: box('#batch-accept-selected-count'),
                    submit: box('#batch-accept-submit'),
                    list: box('.batch-card-grid-wrapper'),
                    listColumn: box('.batch-review-list-column'),
                    pane: box('#batch-detail-pane'),
                    card: box('.batch-draft-card[data-item-id="item-01"]'),
                    cardTitle: box('.batch-draft-card[data-item-id="item-01"] .batch-card-title'),
                    poster: box('.batch-draft-card[data-item-id="item-01"] .batch-card-poster'),
                    posterHasImage: Boolean(poster && poster.querySelector('img')),
                    posterState: poster ? poster.dataset.posterState : null,
                    chipRadius: chip ? parseFloat(getComputedStyle(chip).borderRadius) || 0 : 0,
                    currentBackground: currentCard ? getComputedStyle(currentCard).backgroundColor : null,
                    otherBackground: otherCard ? getComputedStyle(otherCard).backgroundColor : null,
                    listScrollbar: getComputedStyle(list).scrollbarWidth,
                    paneScrollbar: getComputedStyle(pane).scrollbarWidth,
                    listGutter: list.offsetWidth - list.clientWidth,
                    paneGutter: pane.offsetWidth - pane.clientWidth -
                        (parseFloat(getComputedStyle(pane).borderLeftWidth) || 0) * 2,
                    columnGutter: column.offsetWidth - column.clientWidth -
                        (parseFloat(getComputedStyle(column).borderLeftWidth) || 0) * 2,
                    documentWidth: document.body.scrollWidth,
                    viewportWidth: window.innerWidth,
                }
            }"""
        )
        # 单行底栏：复选框、精简计数与唯一主入口同排。
        centers = [
            geometry[key]["y"] + geometry[key]["height"] / 2
            for key in ("checkbox", "count", "submit")
        ]
        assert max(centers) - min(centers) <= 6, centers
        assert geometry["toolbar"]["height"] <= geometry["row"]["height"] + 24, geometry
        expect(page.locator("#batch-accept-all")).to_have_count(0)
        expect(page.locator("#batch-accept-selected-count")).to_contain_text("已选 2 部")
        expect(page.locator("#batch-accept-submit")).to_contain_text("保存并确认 2 部")

        # 页头：设计图是深海蓝大标题 + 右侧返回入口，不是面板内的小标题。
        assert geometry["title"]["height"] >= 32, geometry["title"]
        assert geometry["titleFontSize"] >= 28, geometry["titleFontSize"]
        expect(page.locator("#batch-back-to-search")).to_be_visible()

        # 双栏：左右各占一列，滚动条隐藏且不占槽。
        assert geometry["list"]["right"] <= geometry["pane"]["left"] + 0.5, geometry
        assert geometry["listScrollbar"] == "none"
        assert geometry["paneScrollbar"] == "none"
        assert geometry["listGutter"] == 0
        assert geometry["paneGutter"] == 0
        assert geometry["columnGutter"] == 0
        assert geometry["documentWidth"] <= geometry["viewportWidth"] + 1, geometry

        # 左栏是审核卡而不是表格式诊断行：封面按设计比例明显大于旧的 48px 占位，
        # 卡片本身有足够高度，标题是卡片标题级字号，状态用芯片表达。
        poster = geometry["poster"]
        assert 76 <= poster["width"] <= 108, poster
        assert 56 <= poster["height"] <= 84, poster
        assert 1.1 <= poster["width"] / poster["height"] <= 1.5, poster
        assert geometry["posterHasImage"] is True, geometry
        # 用户当前查看项已在这次会话中明确选择过真实合集，因此卡片封面是 selected。
        assert geometry["posterState"] in {"selected", "candidate"}, geometry
        assert geometry["card"]["height"] >= 80, geometry["card"]
        assert geometry["cardTitle"]["height"] >= 18, geometry["cardTitle"]
        assert geometry["chipRadius"] >= 8, geometry["chipRadius"]
        # 当前查看项用底色 + 左缘强调表达，与普通卡片区分。
        assert geometry["currentBackground"] != geometry["otherBackground"], geometry

        # 右栏信息层级：合集身份 → 字幕与筛选 → 资源结果 → 折叠的高级设置。
        pane_text = page.locator("#batch-detail-pane").inner_text()
        assert "已选真实合集" in pane_text
        assert "字幕与筛选" in pane_text
        assert "资源结果" in pane_text
        expect(page.locator('[data-metric="updated-episodes"]')).to_contain_text("未开发")
        expect(page.locator('[data-metric="total-episodes"]')).to_contain_text("未开发")
        assert "加入批量确认" not in pane_text
        expect(page.locator("#batch-preview-folder-name")).to_be_hidden()

        # 默认层只放少量安全示例（最多两条）；完整种子分组列表与旧技术详情都不在这里。
        samples = page.locator(".batch-resource-sample")
        assert 1 <= samples.count() <= 2, samples.count()
        expect(page.locator(".complete-seed-details")).to_have_count(0)
        expect(page.locator(".advanced-detail")).to_have_count(0)
        assert scenario.external_calls == []

    def test_unconfirmed_draft_never_claims_a_selected_collection(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """产品边界：只有服务端匹配/草案来源信息时，右栏不得声称「已选真实合集」。

        `item-05` 是一条未确认选择的草案：它有服务端匹配元数据与排除原因，但没有任何
        用户人工选择。界面必须显示待核对状态，且不得把匹配标题、季度或海报伪装成选择。
        """
        scenario = self._scenario(page, live_server_url, storage_dir)
        scenario.enter_draft_workbench()

        page.locator(f'.batch-draft-card[data-item-id="{UNCONFIRMED_ITEM_ID}"]').click()
        pane = page.locator("#batch-detail-pane")
        expect(pane).to_contain_text("字幕与筛选")

        identity = page.evaluate(
            """() => {
                const section = document.querySelector('.batch-draft-identity')
                return {
                    label: section.getAttribute('aria-label'),
                    state: section.dataset.selectionState,
                    text: section.innerText,
                    posterImages: section.querySelectorAll('.batch-draft-poster-image').length,
                    posterState: section.querySelector('.batch-draft-poster')?.dataset.posterState,
                }
            }"""
        )
        assert identity["state"] == "unconfirmed", identity
        assert identity["label"] == "尚未确认真实合集", identity
        assert "尚未确认真实合集" in identity["text"]
        assert "已选真实合集" not in identity["text"]
        # 服务端匹配到的合集名与季数不得出现在身份区，更不能当成用户选择。
        assert "第一季" not in identity["text"], identity
        assert identity["posterImages"] == 0, identity
        assert identity["posterState"] == "placeholder", identity

        # 确认过选择的条目仍然显示「已选真实合集」：当前查看项由 fixture 真实点选过。
        # （item-01 已在 enter_draft_workbench 中通过候选选择生成草案。）
        page.locator('.batch-draft-card[data-item-id="item-01"]').click()
        confirmed = page.evaluate(
            """() => {
                const section = document.querySelector('.batch-draft-identity')
                return {
                    label: section.getAttribute('aria-label'),
                    state: section.dataset.selectionState,
                    text: section.innerText,
                    posterImages: section.querySelectorAll('.batch-draft-poster-image').length,
                }
            }"""
        )
        assert confirmed["state"] == "confirmed", confirmed
        assert "已选真实合集" in confirmed["text"], confirmed
        assert "第 1 季" in confirmed["text"], confirmed
        assert confirmed["posterImages"] == 1, confirmed

        # 原始 MiKan 地址等非公开元数据不得进入详情面板。
        pane_text = pane.inner_text()
        assert "mikan.example" not in pane_text
        assert "https://" not in pane_text
        assert "draft-visual" not in pane_text
        assert scenario.external_calls == []

    def test_title_search_popover_does_not_move_the_layout(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """AC：#149 浮层打开/关闭都不改变筛选控件、卡片与底栏的几何位置。"""
        scenario = self._scenario(page, live_server_url, storage_dir)
        scenario.enter_draft_workbench()

        script = """() => {
            const box = (selector) => {
                const element = document.querySelector(selector)
                const rect = element.getBoundingClientRect()
                return [rect.x, rect.y, rect.width, rect.height]
            }
            return {
                filters: box('.batch-review-filters'),
                firstCard: box('.batch-draft-card'),
                toolbar: box('#batch-accept-toolbar'),
            }
        }"""
        def close_enough(first: dict[str, list[float]], second: dict[str, list[float]]) -> None:
            for key in first:
                assert all(abs(a - b) <= 0.5 for a, b in zip(first[key], second[key], strict=True)), (
                    key,
                    first,
                    second,
                )

        # 展开浮层本身不推挤筛选控件、卡片或底栏。
        before = page.evaluate(script)
        page.click("#batch-review-search-toggle")
        page.wait_for_selector("#batch-review-search", timeout=5000)
        expect(page.locator("#batch-review-search")).to_be_visible()
        close_enough(before, page.evaluate(script))

        # 输入关键词后筛选生效；此时再关闭浮层，只有浮层消失，布局不位移。
        page.fill("#batch-review-search", "迷宫")
        expect(page.locator(".batch-draft-card")).to_have_count(1)
        filtered = page.evaluate(script)
        page.keyboard.press("Escape")
        expect(page.locator("#batch-review-search")).to_have_count(0)
        close_enough(filtered, page.evaluate(script))

        # 关闭后关键词与筛选结果保留，放大镜如实反映筛选状态。
        expect(page.locator(".batch-draft-card")).to_have_count(1)
        expect(page.locator("#batch-review-search-toggle")).to_have_class(re.compile(r"is-active"))
        expect(page.locator("#batch-review-search-toggle")).to_have_attribute("aria-label", "标题搜索（已筛选）")
        assert scenario.external_calls == []

    def test_resource_detail_dialog_keeps_tabs_focus_and_scroll(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """AC：#151 页签、弹窗内长列表滚动、关闭后焦点与工作台滚动位置恢复。

        专用 fixture 提供足量的安全资源，弹窗必须呈现设计图中的多行密度并只在弹窗
        内部滚动（工作台与页面都不因它增长）。
        """
        scenario = self._scenario(page, live_server_url, storage_dir)
        scenario.enter_draft_workbench()

        page.evaluate("() => { document.querySelector('#batch-detail-pane').scrollTop = 40 }")
        before_scroll = page.evaluate(
            "() => ({ pane: document.querySelector('#batch-detail-pane').scrollTop, window: window.scrollY })"
        )
        document_height_before = page.evaluate("() => document.documentElement.scrollHeight")
        trigger = page.locator("#batch-preview-open-resources")
        trigger.focus()
        trigger.click()
        page.wait_for_selector(".resource-dialog", timeout=5000)

        dialog = page.locator(".resource-dialog")
        expect(dialog).to_have_attribute("aria-modal", "true")
        expect(dialog.locator("#batch-resource-detail-tab-effective")).to_have_attribute("aria-selected", "true")
        expect(dialog.locator("#batch-resource-detail-panel-effective")).to_be_visible()
        expect(dialog.locator("#batch-resource-detail-count")).to_contain_text("共")
        expect(dialog.locator("#batch-resource-detail-count")).to_contain_text("向下滚动查看")

        # 长列表：有效资源至少覆盖多行可见并在弹窗内部滚动；工作台与页面高度不变。
        effective = page.evaluate(
            """() => {
                const dialog = document.querySelector('.resource-dialog').getBoundingClientRect()
                const panel = document.querySelector('#batch-resource-detail-panel-effective')
                const rows = panel.querySelectorAll('.resource-dialog-item')
                const first = rows[0].getBoundingClientRect()
                return {
                    dialogWidth: dialog.width,
                    dialogHeight: dialog.height,
                    rowCount: rows.length,
                    rowHeight: first.height,
                    scrollable: panel.scrollHeight > panel.clientHeight + 1,
                    visibleRows: Math.floor(panel.clientHeight / Math.max(first.height, 1)),
                    titleFontSize: parseFloat(getComputedStyle(document.querySelector('.resource-dialog-title')).fontSize),
                }
            }"""
        )
        assert effective["rowCount"] >= 12, effective
        # 设计图弹窗约 767×693（归一化）；实现允许 ±10% 的宽度区间。
        assert 690 <= effective["dialogWidth"] <= 850, effective
        assert effective["dialogHeight"] >= 520, effective
        assert effective["rowHeight"] >= 46, effective
        assert effective["visibleRows"] >= 5, effective
        assert effective["scrollable"] is True, effective
        assert effective["titleFontSize"] >= 22, effective
        # 弹窗内滚动：滚到底不带动工作台或页面。
        page.evaluate(
            """() => {
                const panel = document.querySelector('#batch-resource-detail-panel-effective')
                panel.scrollTop = panel.scrollHeight
            }"""
        )
        assert page.evaluate(
            "() => document.querySelector('#batch-resource-detail-panel-effective').scrollTop > 0"
        ) is True
        assert page.evaluate("() => document.documentElement.scrollHeight") == document_height_before

        dialog.locator("#batch-resource-detail-tab-excluded").click()
        excluded_panel = dialog.locator("#batch-resource-detail-panel-excluded")
        expect(excluded_panel).to_be_visible()
        excluded_text = excluded_panel.inner_text()
        # 安全投影：不出现 URL、magnet 或本地路径。
        assert "magnet:" not in excluded_text
        assert "http" not in excluded_text
        assert "[已隐藏" in excluded_text or "排除" in excluded_text
        # 已排除页签有多条、带不同安全原因。
        excluded_rows = page.evaluate(
            """() => {
                const rows = Array.from(document.querySelectorAll('#batch-resource-detail-panel-excluded .resource-dialog-item'))
                return {
                    count: rows.length,
                    reasons: rows.map((row) => {
                        const reason = row.querySelector('.resource-dialog-reason')
                        return reason ? reason.textContent : ''
                    }),
                }
            }"""
        )
        assert excluded_rows["count"] >= 3, excluded_rows
        assert len(set(excluded_rows["reasons"])) >= 2, excluded_rows
        assert all(excluded_rows["reasons"]), excluded_rows

        page.keyboard.press("Escape")
        expect(page.locator(".resource-dialog")).to_have_count(0)
        after_scroll = page.evaluate(
            "() => ({ pane: document.querySelector('#batch-detail-pane').scrollTop, window: window.scrollY })"
        )
        assert after_scroll == before_scroll, (before_scroll, after_scroll)
        assert page.evaluate("() => document.activeElement && document.activeElement.id") == (
            "batch-preview-open-resources"
        )
        assert scenario.external_calls == []

    @pytest.mark.parametrize(
        "width,height,zoom",
        [(1280, 800, 1), (1440, 900, 1), (1920, 1080, 1), (1280, 800, 2)],
    )
    def test_desktop_matrix_keeps_one_row_and_reachable_items(
        self, page: Page, live_server_url: str, storage_dir: Path, width: int, height: int, zoom: int
    ) -> None:
        """AC：三档桌面与 200% 缩放下底栏保持一行、末项可达、无横向溢出。"""
        scenario = self._scenario(page, live_server_url, storage_dir)
        page.set_viewport_size({"width": width, "height": height})
        scenario.enter_draft_workbench()
        if zoom == 2:
            page.evaluate("() => { document.documentElement.style.zoom = '2' }")

        geometry = page.evaluate(
            """() => {
                const toolbar = document.querySelector('#batch-accept-toolbar').getBoundingClientRect()
                const row = document.querySelector('.batch-accept-row').getBoundingClientRect()
                return {
                    toolbarHeight: toolbar.height,
                    rowHeight: row.height,
                    documentWidth: document.body.scrollWidth,
                    viewportWidth: window.innerWidth,
                }
            }"""
        )
        if zoom == 1:
            # 桌面档位：正常运行态只有一行，底栏与唯一主入口都留在视口内。
            assert geometry["toolbarHeight"] <= geometry["rowHeight"] + 24, geometry
            expect(page.locator("#batch-accept-selected-scope")).to_have_count(0)
            expect(page.locator("#batch-accept-submit")).to_be_in_viewport()
        else:
            # 200% 缩放：允许底栏自然换行，也允许工作台屏自身滚动兜底；
            # 关键是唯一主入口仍可滚动到达并可用。
            assert geometry["toolbarHeight"] <= geometry["rowHeight"] * 3 + 24, geometry
            page.locator("#batch-accept-submit").scroll_into_view_if_needed()
            expect(page.locator("#batch-accept-submit")).to_be_visible()
            expect(page.locator("#batch-accept-submit")).to_be_enabled()
        assert geometry["documentWidth"] <= geometry["viewportWidth"] + 1, geometry

        # 末项可达：滚到底后最后一张卡完整落在左栏可视区内、底栏之上。
        page.evaluate(
            """() => {
                const list = document.querySelector('.batch-card-grid-wrapper')
                list.scrollTop = list.scrollHeight
            }"""
        )
        last = page.evaluate(
            """() => {
                const cards = document.querySelectorAll('.batch-draft-card')
                const card = cards[cards.length - 1].getBoundingClientRect()
                const list = document.querySelector('.batch-card-grid-wrapper').getBoundingClientRect()
                const toolbar = document.querySelector('#batch-accept-toolbar').getBoundingClientRect()
                return { cardBottom: card.bottom, listBottom: list.bottom, toolbarTop: toolbar.top }
            }"""
        )
        assert last["cardBottom"] <= last["listBottom"] + 1, last
        assert last["cardBottom"] <= last["toolbarTop"] + 1, last
        assert scenario.external_calls == []

    @pytest.mark.parametrize("count", [1, 12, 36])
    def test_boundary_batch_sizes_keep_the_single_row_toolbar(
        self, page: Page, live_server_url: str, storage_dir: Path, count: int
    ) -> None:
        """AC：1／12／36 部都不改变底栏的一行结构与唯一入口。"""
        items = repeat_items(count)
        scenario = self._scenario(page, live_server_url, storage_dir, items=items)
        checked = ("item-00",) if count == 1 else ("item-00", "item-01")
        scenario.enter_workbench(checked_item_ids=checked, click_item_id="item-00")

        expect(page.locator(".batch-draft-card")).to_have_count(count)
        expect(page.locator("#batch-accept-submit")).to_contain_text(f"保存并确认 {len(checked)} 部")
        expect(page.locator("#batch-accept-submit")).to_be_in_viewport()
        assert page.evaluate("() => document.body.scrollWidth <= window.innerWidth + 1")
        if count > 3:
            assert page.evaluate(
                "() => { const list = document.querySelector('.batch-card-grid-wrapper'); return list.scrollHeight > list.clientHeight }"
            ) is True
        assert scenario.external_calls == []

    def test_every_review_state_is_stable_across_three_captures(
        self, page: Page, live_server_url: str, storage_dir: Path, tmp_path: Path
    ) -> None:
        """AC：各状态连续三次截图尺寸与 DOM 锚点严格一致，差异只在噪声带内。"""
        scenario = self._scenario(page, live_server_url, storage_dir)
        scenario.enter_draft_workbench()

        canvas_pixels = CANVAS[0] * CANVAS[1]
        # #145：连续三次的显著差异像素上限（0.5% 画布）；同环境的栅格化噪声远低于它。
        significant_limit = round(canvas_pixels * 0.005)
        for state in CAPTURE_STATES:
            sizes: list[tuple[int, int]] = []
            anchors: list[dict[str, Any]] = []
            shots: list[Path] = []
            reports: list[dict[str, Any]] = []
            for run in range(3):
                shot = self._capture_state(scenario, state, tmp_path, suffix=f"-run{run}")
                with Image.open(shot) as captured:
                    sizes.append(captured.size)
                anchors.append(anchor_summary(page, SHELL_ANCHORS))
                shots.append(shot)
                # 设计图只用于诊断：按像素门禁裁决 3C 不启用设计图 ≤0.5% 硬阈值。
                reports.append(
                    compare_with_design(6, shot, diff_path=tmp_path / f"{state}-run{run}-diff.png").as_report()
                )
            assert sizes[0] == sizes[1] == sizes[2] == CANVAS, (state, sizes)
            assert report_json(anchors[0]) == report_json(anchors[1]) == report_json(anchors[2]), state
            # 设计图对比只作诊断（像素门禁裁决 3C 未对设计图启用阈值）；稳定性由
            # 下面的「连续截图彼此比较」严格证明。
            for report in reports:
                assert 0.0 <= float(report["diff_ratio"]) <= 1.0, (state, report["diff_ratio"])
            # 连续截图彼此比较：只允许同环境的栅格化噪声，且远低于 0.5% 口径。
            for first, second in ((shots[0], shots[1]), (shots[1], shots[2])):
                stats = compare_images(
                    read_image(first, error_code="actual_unreadable"),
                    read_image(second, error_code="actual_unreadable"),
                    diff_path=tmp_path / f"{state}-consecutive-diff.png",
                )
                assert stats.diff_pixels <= stability_noise_pixels(canvas_pixels), (
                    state,
                    stats.diff_pixels,
                )
                assert stats.diff_pixels <= significant_limit, (state, stats.diff_pixels)

    def test_canary_never_reaches_browser_surfaces_or_artifacts(
        self, page: Page, live_server_url: str, storage_dir: Path, tmp_path: Path
    ) -> None:
        """AC：真实草案能力标识不进入 URL、存储、DOM、日志或截图像素。"""
        scenario = self._scenario(page, live_server_url, storage_dir)
        scenario.enter_draft_workbench()
        scenario.open_resource_dialog("effective")
        scenario.dismiss_toast()

        shot = capture_canvas(page, tmp_path / "batch-draft-canary.png")
        surface = browser_surface(page)
        canaries = canary_values(scenario.items, scenario.created_draft_ids)
        assert scenario.created_draft_ids, "人工选择路径应当生成草案标识"
        assert canaries
        for canary in canaries:
            assert canary not in surface["url"]
            assert canary not in surface["historyState"]
            assert canary not in surface["localStorage"]
            assert canary not in surface["sessionStorage"]
            assert canary not in surface["bodyText"]
            assert canary not in surface["attributes"]
            assert all(canary not in message for message in scenario.console_messages)
            assert canary.encode() not in shot.read_bytes()

    def test_review_candidates_are_written_only_when_requested(
        self, page: Page, live_server_url: str, storage_dir: Path, tmp_path: Path
    ) -> None:
        """MIGU_ORCA_CAPTURE_REVIEW 仍只将候选图写入 pending 审核目录。

        默认（CI 与普通本地运行）只截图到 ``tmp_path``；此入口不更新获批基准。
        """
        scenario = self._scenario(page, live_server_url, storage_dir)
        scenario.enter_draft_workbench()

        captured: dict[str, Path] = {}
        for state in CAPTURE_STATES:
            captured[state] = self._capture_state(scenario, state, tmp_path)

        written = [
            target
            for state, shot in captured.items()
            if (target := scenario.write_review_screenshot(f"{state}.png", shot)) is not None
        ]
        if not scenario.review_screenshots_enabled():
            assert written == []
            return
        assert {target.name for target in written} == {f"{state}.png" for state in CAPTURE_STATES}
        assert all(target.parent == REVIEW_DIR for target in written)
        for target in written:
            assert target.is_file()
            with Image.open(target) as image:
                assert image.size == CANVAS
        for target in written:
            payload = target.read_bytes()
            for canary in canary_values(scenario.items, scenario.created_draft_ids):
                assert canary.encode() not in payload
            # #155：候选图必须随附证据清单（构建 + 实际加载资源 + 截图摘要），
            # 且清单同样不得携带候选上下文等能力标识。
            manifest_path = target.parent / f"{target.stem}.evidence.json"
            assert manifest_path.is_file(), target
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            assert manifest["screenshot"]["sha256"]
            assert manifest["build"]["artifact_digest"]
            assert manifest["fixture"]["id"] == "batch-draft-review-153"
            assert any(
                resource["path"].startswith("/app/assets/")
                for resource in manifest["page"]["loaded_resources"]
            )
            rendered = manifest_path.read_text(encoding="utf-8")
            for canary in canary_values(scenario.items, scenario.created_draft_ids):
                assert canary not in rendered

    def test_record_approved_batch_draft_baseline_only_when_explicitly_requested(
        self, page: Page, live_server_url: str, storage_dir: Path, tmp_path: Path
    ) -> None:
        """单独的 record 开关受控写获批基准；普通候选开关不会覆盖它。"""
        scenario = self._scenario(page, live_server_url, storage_dir)
        scenario.enter_draft_workbench()

        captured: dict[str, Path] = {}
        recorded_anchors: dict[str, dict[str, dict[str, float]]] = {}
        for state in CAPTURE_STATES:
            captured[state] = self._capture_state(scenario, state, tmp_path)
            anchors = collect_anchor_boxes(page, APPROVED_ANCHORS[state])
            assert all(box is not None for box in anchors.values()), (state, anchors)
            recorded_anchors[state] = anchors  # type: ignore[assignment]

        written = [
            target
            for state, shot in captured.items()
            if (target := scenario.write_approved_baseline_screenshot(f"{state}.png", shot)) is not None
        ]
        if not scenario.approved_baseline_recording_enabled():
            assert written == []
            return

        assert {target.name for target in written} == {f"{state}.png" for state in CAPTURE_STATES}
        assert all(target.parent == BASELINE_DIR for target in written)
        (BASELINE_DIR / "anchors.json").write_text(
            json.dumps(recorded_anchors, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        for target in written:
            with Image.open(target) as image:
                assert image.size == CANVAS
            manifest_path = target.parent / f"{target.stem}.evidence.json"
            assert manifest_path.is_file(), target
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            assert manifest["fixture"]["id"] == "batch-draft-review-153"
            assert manifest["screenshot"]["sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()

    def test_approved_batch_draft_baseline_pixels_anchors_and_stability(
        self, page: Page, live_server_url: str, storage_dir: Path, tmp_path: Path
    ) -> None:
        """四张获批基准必须存在，像素差异≤0.5%、DOM锚点≤2px且三次截图稳定。"""
        anchors_path = BASELINE_DIR / "anchors.json"
        assert anchors_path.is_file(), f"缺少批量草案获批锚点基准：{anchors_path}"
        expected_anchors = json.loads(anchors_path.read_text(encoding="utf-8"))
        assert set(expected_anchors) == set(CAPTURE_STATES)

        scenario = self._scenario(page, live_server_url, storage_dir)
        scenario.enter_draft_workbench()
        canvas_pixels = CANVAS[0] * CANVAS[1]

        for state in CAPTURE_STATES:
            baseline = BASELINE_DIR / f"{state}.png"
            manifest_path = BASELINE_DIR / f"{state}.evidence.json"
            assert baseline.is_file(), f"缺少获批批量草案像素基准：{baseline}"
            assert manifest_path.is_file(), f"缺少获批批量草案证据清单：{manifest_path}"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            assert manifest["fixture"]["id"] == "batch-draft-review-153"
            assert manifest["screenshot"]["sha256"] == hashlib.sha256(baseline.read_bytes()).hexdigest()

            actual_anchors: list[dict[str, dict[str, float] | None]] = []
            shots: list[Path] = []
            for run in range(BASELINE_STABILITY_REPEATS):
                shot = self._capture_state(scenario, state, tmp_path, suffix=f"-baseline-run{run}")
                anchors = collect_anchor_boxes(page, APPROVED_ANCHORS[state])
                assert set(anchors) == set(expected_anchors[state]), (state, anchors)
                for name, box in anchors.items():
                    expected = expected_anchors[state][name]
                    assert box is not None, (state, name)
                    for field in ("x", "y", "width", "height"):
                        assert abs(box[field] - expected[field]) <= BASELINE_ANCHOR_TOLERANCE, (
                            state,
                            name,
                            field,
                            box,
                            expected,
                        )
                stats = compare_images(
                    read_image(baseline, error_code="baseline_unreadable"),
                    read_image(shot, error_code="actual_unreadable"),
                    mask_area_limit=MAX_BASELINE_MASK_RATIO,
                    diff_path=tmp_path / f"{state}-baseline-run{run}-diff.png",
                )
                assert stats.mask_ratio == 0.0, (state, stats.as_report())
                assert stats.mask_ratio <= MAX_BASELINE_MASK_RATIO, (state, stats.as_report())
                assert stats.diff_ratio <= MAX_BASELINE_DIFF_RATIO, (state, stats.as_report())
                actual_anchors.append(anchors)
                shots.append(shot)

            assert actual_anchors[0] == actual_anchors[1] == actual_anchors[2], state
            for index in range(1, len(shots)):
                first, second = shots[index - 1], shots[index]
                stability = compare_images(
                    read_image(first, error_code="previous_unreadable"),
                    read_image(second, error_code="actual_unreadable"),
                )
                assert stability.diff_pixels <= stability_noise_pixels(canvas_pixels), (
                    state,
                    stability.as_report(),
                )

    def test_review_capture_manifest_is_verifiable_without_repo_writes(
        self, page: Page, live_server_url: str, storage_dir: Path, tmp_path: Path
    ) -> None:
        """#155：候选图清单在落盘开关关闭时也能组装并通过产物一致性校验。"""
        scenario = self._scenario(page, live_server_url, storage_dir)
        scenario.enter_draft_workbench()
        shot = self._capture_state(scenario, "draft-workbench", tmp_path)

        manifest = scenario.review_artifact_manifest("draft-workbench.png", shot)
        assert manifest["scenario"]["id"] == "batch-draft-draft-workbench-1440x900"
        assert manifest["fixture"]["id"] == "batch-draft-review-153"
        assert manifest["screenshot"]["sha256"]
        assert manifest["runtime"]["viewport"] == {"width": CANVAS[0], "height": CANVAS[1]}
        assert any(
            resource["path"].startswith("/app/assets/")
            for resource in manifest["page"]["loaded_resources"]
        )
        if not scenario.review_screenshots_enabled():
            assert scenario.write_review_screenshot("draft-workbench.png", shot) is None


def test_fixture_covers_the_designed_batch_states() -> None:
    """fixture 自身覆盖设计图要求的条目状态与信息密度，避免视觉用例退化成单一状态。

    「已选真实合集」只能来自用户人工选择，因此 fixture 把条目分为两组：
    待选择（由 fixture 在浏览器里真实点选候选生成草案）与**未确认选择**的草案
    （只有服务端匹配信息）。这里锁住两组的存在与安全形状。
    """
    items = batch_draft_items()
    assert len(items) == len(DRAFT_LINES)
    statuses = [item["status"] for item in items]
    # 初始状态下没有任何条目被伪造成「已选」：登记选择的条目仍是待选择状态。
    assert statuses.count("FOUND") == 3
    assert statuses.count("FAILED") == 1
    assert statuses.count("DRAFT") == 1
    assert [item["item_id"] for item in items if item["status"] == "DRAFT"] == [UNCONFIRMED_ITEM_ID]
    assert all(item["item_id"] for item in items)
    assert BATCH_ID in json.dumps(items, ensure_ascii=False)
    assert raw_input_for(items).count("\n") + 1 == len(DRAFT_LINES)
    assert CHECKED_ITEM_IDS and CLICKED_ITEM_ID in CHECKED_ITEM_IDS
    assert REVIEW_DIR.name == "pending-batch-draft"
    assert len(canary_values(items)) >= 3
    assert len(repeat_items(36)) == 36

    # 登记为「用户确认选择」的条目必须真的带候选，选择只能由人工点击产生。
    selected_ids = set(SELECTIONS)
    assert selected_ids == {"item-01", "item-02"}
    for item_id, (bangumi_id, title, effective_count) in SELECTIONS.items():
        item = next(entry for entry in items if entry["item_id"] == item_id)
        assert item["status"] == "FOUND"
        assert item["candidates"], item_id
        assert item["candidates"][0]["bangumi_id"] == bangumi_id
        assert item["candidates"][0]["title"] == title
        assert item["candidates"][0]["poster_url"] == poster_path(bangumi_id)
        assert item["preview_request"] is None, "待选择条目不得预置草案权威"
        assert effective_count >= 6

    # 候选阶段的卡片也有封面（尚未选定真实合集，标记为候选预览）。
    unconfirmed = next(entry for entry in items if entry["item_id"] == UNCONFIRMED_ITEM_ID)
    assert unconfirmed["status"] == "DRAFT"
    matched = unconfirmed["preview_request"]["source_info"]["matched_bangumi"]
    # 未确认态只有服务端匹配信息；界面必须显示待核对，不得声称「已选真实合集」。
    assert matched["title"] == f"{DRAFT_LINES[4]} 第一季"
    assert matched["poster_url"] == poster_path("4096")
    sources = unconfirmed["preview_request"]["source_info"]["rss_sources"][0]
    assert sources["valid_seed_names"] == []
    assert len(sources["excluded_seed_names"]) >= 3
    assert unconfirmed["preview_request"]["confirmable_config"]["effective_seed_names"] == []
