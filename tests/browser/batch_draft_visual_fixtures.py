"""#153：批量草案工作台的固定安全 fixture（真实 Chromium 验收与视觉基准候选）。

一个固定批次的五张「批量条目卡」覆盖设计图的关键状态：

- 三项 DRAFT（各带服务端草案，其中前两项已勾选；第一项是当前查看项）；
- 一项 FOUND（待选择真实 MiKan 合集）；
- 一项 FAILED（搜索失败）。

另外通过 ``repeat_items`` 构造 1／12／36 部的边界批次。全部数据来自仓库内的规则/
fixture（``generate_request`` 的离线输入），不访问真实 MiKan、Auto Bangumi 或
qBittorrent，也不读取或写入真实用户运行数据。截图、diff 与诊断值只写 pytest
``tmp_path``；只有显式设置 ``MIGU_ORCA_CAPTURE_REVIEW=1`` 时才把候选图写到仓库内的
pending 审核目录。
"""

from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, expect

from tests.browser.batch_visual_fixtures import batch_candidate as _visual_candidate
from tests.browser.conftest import set_storage_preferences
from tests.browser.screen_support import wait_for_screen_scroll
from tests.browser.test_app_batch_workbench import (
    _batch_item,
    _preview_request,
    _preview_request_without_resources,
)
from tests.browser.visual_support import install_shell_status_routes, prepare_canvas, require_dist

REPO_ROOT = Path(__file__).resolve().parents[2]
REVIEW_DIR = REPO_ROOT / "docs/design/assets/frontend-ux/acceptance-baseline/add-anime/pending-batch-draft"

BATCH_ID = "batch-draft-visual-153"

DRAFT_LINES: tuple[str, ...] = (
    "葬送的芙莉莲",
    "迷宫饭",
    "孤独摇滚",
    "咒术回战",
    "夏日重现",
)

CANARY_CANDIDATE_CONTEXT = "batch-draft-153-canary-candidate-context"
CANARY_DRAFT_MARKER = "batch-draft-153-canary-draft"

CHECKED_ITEM_IDS: tuple[str, ...] = ("item-01", "item-02")
CLICKED_ITEM_ID = "item-01"


def batch_draft_items() -> list[dict[str, Any]]:
    """固定批次：3 项草案（2 项已勾选）+ 1 项待选合集 + 1 项搜索失败。

    最后一项没有有效资源：它是真实 DRAFT，但位于可确认范围之外并给出就地原因。
    """
    items = [
        _batch_item(
            "item-01",
            DRAFT_LINES[0],
            status="DRAFT",
            canonical_title=f"{DRAFT_LINES[0]} 第一季",
            season_hint="第 1 季",
            candidates=[
                _visual_candidate(
                    bangumi_id="2353",
                    title=f"{DRAFT_LINES[0]} 第一季",
                    season=1,
                    total_episodes=28,
                    source_query=DRAFT_LINES[0],
                    candidate_context=CANARY_CANDIDATE_CONTEXT,
                )
            ],
            preview_request=_preview_request(DRAFT_LINES[0], f"req-{BATCH_ID}-01"),
        ),
        _batch_item(
            "item-02",
            DRAFT_LINES[1],
            status="DRAFT",
            canonical_title=f"{DRAFT_LINES[1]} 第一季",
            season_hint="第 1 季",
            preview_request=_preview_request(DRAFT_LINES[1], f"req-{BATCH_ID}-02"),
        ),
        _batch_item(
            "item-03",
            DRAFT_LINES[2],
            status="FOUND",
            canonical_title=f"{DRAFT_LINES[2]} 第一季",
            season_hint="第 1 季",
            candidates=[
                _visual_candidate(
                    bangumi_id="2888",
                    title=f"{DRAFT_LINES[2]} 第一季",
                    season=1,
                    total_episodes=12,
                    source_query=DRAFT_LINES[2],
                )
            ],
        ),
        _batch_item(
            "item-04",
            DRAFT_LINES[3],
            status="FAILED",
            error={
                "error_type": "mikan_unavailable",
                "error_message": "MiKan 候选搜索暂时不可用",
            },
        ),
        _batch_item(
            "item-05",
            DRAFT_LINES[4],
            status="DRAFT",
            canonical_title=f"{DRAFT_LINES[4]} 第一季",
            season_hint="第 1 季",
            preview_request=_preview_request_without_resources(DRAFT_LINES[4], f"req-{BATCH_ID}-05"),
        ),
    ]
    # 真实敏感 canary：只存在于客户端内存，任何浏览器表面或截图都不应出现它。
    items[0]["error"] = {"detail": CANARY_DRAFT_MARKER}
    return items


def repeat_items(count: int) -> list[dict[str, Any]]:
    """1／12／36 部边界批次：每项各自持有唯一草案，结构一致。"""
    items: list[dict[str, Any]] = []
    for index in range(count):
        title = f"边界番剧{index:02d}"
        items.append(
            _batch_item(
                f"item-{index:02d}",
                title,
                status="DRAFT",
                canonical_title=f"{title} 第一季",
                season_hint="第 1 季",
                preview_request=_preview_request(title, f"req-{BATCH_ID}-boundary-{index:02d}"),
            )
        )
    return items


def raw_input_for(items: Iterable[dict[str, Any]]) -> str:
    return "\n".join(str(item["raw_title"]) for item in items)


def batch_parse_envelope(items: list[dict[str, Any]], raw_input: str) -> str:
    return json.dumps(
        {
            "ok": True,
            "result": {
                "batch_id": BATCH_ID,
                "raw_input": raw_input,
                "items": items,
            },
        },
        ensure_ascii=False,
    )


def canary_values(items: list[dict[str, Any]]) -> tuple[str, ...]:
    """真实的草案能力标识：绝不能进入 URL、存储、DOM 文本、日志或截图像素。"""
    values = [CANARY_CANDIDATE_CONTEXT, CANARY_DRAFT_MARKER]
    for item in items:
        draft_id = item.get("draft_id")
        if isinstance(draft_id, str) and draft_id:
            values.append(draft_id)
    return tuple(values)


class BatchDraftVisualScenario:
    """#153 各状态共享的构造器。"""

    def __init__(self, page: Page, base_url: str) -> None:
        self.page = page
        self.base_url = base_url
        self.items: list[dict[str, Any]] = batch_draft_items()
        self.console_messages: list[str] = []
        self.external_calls: list[str] = []

    def install(self, storage_dir: Path, *, items: list[dict[str, Any]] | None = None) -> None:
        require_dist()
        prepare_canvas(self.page)
        set_storage_preferences(self.page, storage_dir)
        install_shell_status_routes(self.page)
        self.page.on("console", lambda message: self.console_messages.append(message.text))
        self.page.on("pageerror", lambda error: self.console_messages.append(str(error)))
        if items is not None:
            self.items = items
        payload = batch_parse_envelope(self.items, raw_input_for(self.items))
        # 宽泛的兜底 route 先注册：Playwright 以最后注册的匹配为先。
        self.page.route("**/api/v1/mikan/**", self._on_unexpected_external)
        self.page.route("**/api/v1/batches/*/save-confirm**", self._on_save_confirm)
        self.page.route("**/api/v1/requests/*/safe-info", self._on_safe_info)
        self.page.route("**/api/v1/requests", self._on_unexpected_external)
        self.page.route(
            "**/api/v1/batches/parse",
            lambda route: route.fulfill(status=200, content_type="application/json", body=payload),
        )

    def _on_unexpected_external(self, route: Any, request: Any) -> None:
        self.external_calls.append(request.url)
        route.abort()

    def _on_save_confirm(self, route: Any, request: Any) -> None:
        self.external_calls.append(request.url)
        route.fulfill(
            status=409,
            content_type="application/json",
            body=json.dumps({"ok": False, "error": {"code": "not_found", "message": "未找到"}, "result": None}),
        )

    def _on_safe_info(self, route: Any, _request: Any) -> None:
        self.external_calls.append("safe-info")
        route.fulfill(
            status=404,
            content_type="application/json",
            body=json.dumps({"ok": False, "error": {"code": "not_found", "message": "未找到"}}),
        )

    # -- states ---------------------------------------------------------

    def open_batch_input(self) -> None:
        self.page.goto(f"{self.base_url}/app/add")
        self.page.wait_for_selector("#anime-mode-switch", timeout=10_000)
        self.page.click("#anime-mode-batch")
        self.page.wait_for_selector("#batch-parse-form", timeout=10_000)

    def enter_workbench(
        self,
        *,
        checked_item_ids: tuple[str, ...] | None = None,
        click_item_id: str | None = None,
    ) -> None:
        """进入批量工作台：按参数勾选条目，并把当前查看项定在指定卡片。"""
        checked = checked_item_ids if checked_item_ids is not None else CHECKED_ITEM_IDS
        clicked = click_item_id if click_item_id is not None else CLICKED_ITEM_ID
        self.open_batch_input()
        self.page.fill("#batch-raw-input", raw_input_for(self.items))
        self.page.click("#batch-parse-submit")
        expect(self.page.locator(".batch-draft-card")).to_have_count(len(self.items))
        for item_id in checked:
            self.page.locator(
                f'.batch-draft-card[data-item-id="{item_id}"] input[type="checkbox"]'
            ).set_checked(True)
        if clicked is not None:
            self.page.locator(f'.batch-draft-card[data-item-id="{clicked}"]').click()
            expect(self.page.locator("#batch-detail-pane")).to_contain_text("字幕与筛选")
            # 审核截图从当前查看项开始取景：列表滚到该卡片顶部（保留焦点环余量），
            # 不让上一张卡片只露出半行。
            self.page.evaluate(
                """(itemId) => {
                    const list = document.querySelector('.batch-card-grid-wrapper')
                    const card = document.querySelector(`.batch-draft-card[data-item-id="${itemId}"]`)
                    if (!list || !card) return
                    const delta = card.getBoundingClientRect().top - list.getBoundingClientRect().top
                    list.scrollTop = Math.max(0, list.scrollTop + delta - 8)
                }""",
                clicked,
            )
        if checked:
            expect(self.page.locator("#batch-accept-submit")).to_contain_text(
                f"保存并确认 {len(checked)} 部"
            )
        # 等切屏动画真的停在工作台顶部，否则几何与截图会把动画中间态当成结果。
        wait_for_screen_scroll(self.page)
        # 解析完成的提示条在这里就关掉，首次截图不会落在淡出过程中。
        self.dismiss_toast()

    def enter_draft_workbench(self) -> None:
        self.enter_workbench()

    def open_title_search(self, keyword: str = "迷宫") -> None:
        self.page.click("#batch-review-search-toggle")
        self.page.wait_for_selector("#batch-review-search", timeout=10_000)
        self.page.fill("#batch-review-search", keyword)
        expect(self.page.locator(".batch-draft-card")).to_have_count(1)

    def reset_title_search(self) -> None:
        """关闭浮层并清空关键词，回到完整批次。"""
        self.page.click("#batch-review-search-toggle")
        expect(self.page.locator("#batch-review-search")).to_have_count(0)
        self.page.click("#batch-review-clear")
        expect(self.page.locator(".batch-draft-card")).to_have_count(len(self.items))

    def open_resource_dialog(self, tab: str = "effective") -> None:
        # 用键盘打开：焦点陷阱的焦点环与「键盘可达」语义在每次截图中都一致，
        # 不会因鼠标/键盘模态不同而出现不稳定的焦点环像素差。
        trigger = self.page.locator("#batch-preview-open-resources")
        trigger.focus()
        self.page.keyboard.press("Enter")
        self.page.wait_for_selector(".resource-dialog", timeout=10_000)
        if tab == "excluded":
            self.switch_resource_tab("excluded")

    def switch_resource_tab(self, tab: str) -> None:
        self.page.click(f"#batch-resource-detail-tab-{tab}")
        expect(self.page.locator(f"#batch-resource-detail-panel-{tab}")).to_be_visible()

    def open_excluded_resources(self) -> None:
        self.open_resource_dialog("excluded")

    def close_resource_dialog(self) -> None:
        self.page.keyboard.press("Escape")
        expect(self.page.locator(".resource-dialog")).to_have_count(0)

    def goto_state(self, name: str) -> None:
        """幂等地把页面推进到某个审核状态（重复调用不重复开合）。"""
        if self.page.locator(".resource-dialog").count():
            self.close_resource_dialog()
        if name == "draft-workbench":
            if self.page.locator("#batch-review-search").count():
                self.reset_title_search()
            return
        if name == "title-search":
            if not self.page.locator("#batch-review-search").count():
                self.open_title_search()
            return
        if name == "resource-detail-effective":
            if self.page.locator("#batch-review-search").count():
                self.reset_title_search()
            self.open_resource_dialog("effective")
            return
        if name == "resource-detail-excluded":
            if not self.page.locator(".resource-dialog").count():
                if self.page.locator("#batch-review-search").count():
                    self.reset_title_search()
                self.open_resource_dialog("effective")
            self.switch_resource_tab("excluded")
            return
        raise AssertionError(f"unknown state: {name}")

    def dismiss_toast(self) -> None:
        """关掉页面级提示条：视觉基准只反映业务界面，不受提示条开合影响。

        提示条可能刚好自动关闭（元素已脱离），因此点击失败不算错误，只以最终
        状态为准；这样截图不会把淡出中的提示条当成业务布局。
        """
        close = self.page.locator(".global-notification-close")
        if close.count():
            with contextlib.suppress(PlaywrightError):
                close.click(timeout=2000)
        expect(self.page.locator(".global-notification")).to_have_count(0)

    # -- review capture -------------------------------------------------

    def review_screenshots_enabled(self) -> bool:
        return os.environ.get("MIGU_ORCA_CAPTURE_REVIEW") == "1"

    def write_review_screenshot(self, name: str, shot: Path) -> Path | None:
        """把候选图写到仓库内 pending 审核目录（仅在显式要求时）。"""
        if not self.review_screenshots_enabled():
            return None
        REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        target = REVIEW_DIR / name
        target.write_bytes(shot.read_bytes())
        return target
