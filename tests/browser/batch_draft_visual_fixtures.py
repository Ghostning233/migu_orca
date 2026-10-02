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

from tests.browser.add_anime_visual_fixtures import install_poster_route
from tests.browser.batch_visual_fixtures import batch_candidate as _visual_candidate
from tests.browser.conftest import issue_draft_id, set_storage_preferences
from tests.browser.evidence import (
    FixtureDescriptor,
    LoadedResourceRecorder,
    ScenarioDescriptor,
    capture_evidence,
    write_manifest,
)
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

# 资源明细弹窗的固定安全密度：设计图的「有效资源」需要多行可见并在弹窗内滚动，
# 「已排除」需要多条带不同安全原因。全部是离线确定性文案，不含 URL、magnet 或路径。
RESOURCE_EFFECTIVE_COUNT = 24
EXCLUDED_RESOURCE_SUFFIXES: tuple[tuple[str, str], ...] = (
    ("S01E01 720p.mkv", "未命中包含规则：1080p"),
    ("S01E03 [v2].mkv", "命中排除规则：[v2]"),
    ("特典 SP01.mkv", "未命中包含规则：1080p"),
    ("S02E01 1080p HEVC.mkv", "命中排除规则：HEVC"),
)

# 明确确认选择的草案态：item_id → (bangumi_id, 合集标题, 有效资源条数)。
# 这些条目一开始是 FOUND，由 fixture 在真实浏览器里点开卡片、选择候选，再由
# `POST /api/v1/requests` 生成草案——「已选真实合集」只能来自这条人工路径。
SELECTIONS: dict[str, tuple[str, str, int]] = {
    "item-01": ("2353", DRAFT_LINES[0], RESOURCE_EFFECTIVE_COUNT),
    "item-02": ("3072", DRAFT_LINES[1], 12),
}

# 未确认选择态：只有服务端匹配/草案来源信息，没有用户人工选择。
UNCONFIRMED_ITEM_ID = "item-05"



def poster_path(bangumi_id: str) -> str:
    """同源不透明海报键路径：与单番视觉 fixture 复用同一套确定性图片。"""
    return f"/api/v1/mikan/posters/{bangumi_id}"


def _resource_seed_names(title: str, count: int = RESOURCE_EFFECTIVE_COUNT) -> list[str]:
    return [f"{title} S01E{index:02d} 1080p WEB-DL x264.mkv" for index in range(1, count + 1)]


def _excluded_seed_entries(title: str) -> list[dict[str, str]]:
    return [
        {"name": f"{title} {suffix}", "reason": reason}
        for suffix, reason in EXCLUDED_RESOURCE_SUFFIXES
    ]


def with_public_resources(
    preview: dict[str, Any],
    *,
    bangumi_id: str,
    title: str,
    effective_count: int = RESOURCE_EFFECTIVE_COUNT,
) -> dict[str, Any]:
    """给固定的未保存草案补上公开、确定的资源密度与同源海报键（仅供视觉审核）。

    只写 ``source_info`` / ``confirmable_config`` 已有的公开字段，不新增接口、不写业务
    逻辑，也不产生任何真实 MiKan 数据。
    """
    request = json.loads(json.dumps(preview, ensure_ascii=False))
    matched = request.setdefault("source_info", {}).setdefault("matched_bangumi", {})
    matched["title"] = title
    matched["poster_url"] = poster_path(bangumi_id)
    sources = request["source_info"].setdefault("rss_sources", [])
    if sources:
        source = sources[0]
        effective = _resource_seed_names(title, effective_count)
        excluded = _excluded_seed_entries(title)
        source["valid_seed_names"] = effective
        source["excluded_seed_names"] = excluded
        source["valid_seed_count"] = len(effective)
        source["invalid_seed_count"] = len(excluded)
        source["total_seed_count"] = len(effective) + len(excluded)
        request.setdefault("confirmable_config", {})["effective_seed_names"] = list(effective)
    return request


def batch_draft_items() -> list[dict[str, Any]]:
    """固定批次：3 项待选合集 + 1 项搜索失败 + 1 项「未确认真实合集」的草案。

    - ``item-01``／``item-02`` 是**待选择**条目：fixture 会在真实浏览器里点开卡片、
      选择候选，让服务端生成草案，「已选真实合集」只来自这条人工选择路径。
    - ``item-03`` 始终停留在待选择状态（候选阶段的视觉与语义）。
    - ``item-04`` 搜索失败，失败原因与唯一恢复动作留在卡片内。
    - ``item-05`` 是**未确认选择**的草案：只有服务端匹配/草案来源信息，没有用户人工
      选择，界面必须显示待核对而不是「已选真实合集」。
    """
    items = [
        _batch_item(
            "item-01",
            DRAFT_LINES[0],
            status="FOUND",
            canonical_title=DRAFT_LINES[0],
            season_hint="第 1 季",
            candidates=[
                _visual_candidate(
                    bangumi_id="2353",
                    title=DRAFT_LINES[0],
                    season=1,
                    total_episodes=28,
                    source_query=DRAFT_LINES[0],
                    candidate_context=CANARY_CANDIDATE_CONTEXT,
                )
                | {"poster_url": poster_path("2353")},
            ],
        ),
        _batch_item(
            "item-02",
            DRAFT_LINES[1],
            status="FOUND",
            canonical_title=DRAFT_LINES[1],
            season_hint="第 1 季",
            candidates=[
                _visual_candidate(
                    bangumi_id="3072",
                    title=DRAFT_LINES[1],
                    season=1,
                    total_episodes=12,
                    source_query=DRAFT_LINES[1],
                )
                | {"poster_url": poster_path("3072")},
            ],
        ),
        _batch_item(
            "item-03",
            DRAFT_LINES[2],
            status="FOUND",
            canonical_title=DRAFT_LINES[2],
            season_hint="第 1 季",
            candidates=[
                _visual_candidate(
                    bangumi_id="2888",
                    title=DRAFT_LINES[2],
                    season=1,
                    total_episodes=12,
                    source_query=DRAFT_LINES[2],
                )
                | {"poster_url": poster_path("2888")},
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
            UNCONFIRMED_ITEM_ID,
            DRAFT_LINES[4],
            status="DRAFT",
            canonical_title=DRAFT_LINES[4],
            season_hint="第 1 季",
            # 未确认选择 + 没有有效资源：只有服务端匹配信息与排除原因，
            # 因此既不能声称「已选真实合集」，也不能进入保存确认范围。
            preview_request=with_public_resources(
                _preview_request_without_resources(DRAFT_LINES[4], f"req-{BATCH_ID}-05"),
                bangumi_id="4096",
                title=f"{DRAFT_LINES[4]} 第一季",
                effective_count=0,
            ),
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


def canary_values(
    items: list[dict[str, Any]], extra: Iterable[str] = ()
) -> tuple[str, ...]:
    """真实的草案能力标识：绝不能进入 URL、存储、DOM 文本、日志或截图像素。"""
    values = [CANARY_CANDIDATE_CONTEXT, CANARY_DRAFT_MARKER, *extra]
    for item in items:
        draft_id = item.get("draft_id")
        if isinstance(draft_id, str) and draft_id:
            values.append(draft_id)
    return tuple(values)


REVIEW_FIXTURE = FixtureDescriptor(
    fixture_id="batch-draft-review-153",
    description="固定安全批次：离线草案、确定性海报与安全资源样例；不连接真实 MiKan／AB／qB。",
    mock_routes=("/api/v1/batches/parse", "/api/v1/requests", "/api/v1/mikan/posters"),
)
"""候选图所属的固定 fixture 标识（写进每张图的证据清单）。"""


class BatchDraftVisualScenario:
    """#153 各状态共享的构造器。"""

    def __init__(self, page: Page, base_url: str) -> None:
        self.page = page
        self.base_url = base_url
        # #155：候选图与截图一样要能证明「页面真的加载了本次构建的产物」。
        self.recorder = LoadedResourceRecorder(base_url)
        self.recorder.attach(page)
        self.items: list[dict[str, Any]] = batch_draft_items()
        self.console_messages: list[str] = []
        self.external_calls: list[str] = []
        # 人工选择产生的草案标识：同样属于不得进入浏览器表面的能力标识。
        self.created_draft_ids: list[str] = []
        self.selection_specs: dict[str, tuple[str, int]] = {
            bangumi_id: (title, effective_count)
            for bangumi_id, title, effective_count in SELECTIONS.values()
        }

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
        # 同源海报接口是公开的确定性 fixture；比兜底 route 后注册，因此优先命中。
        install_poster_route(self.page)
        self.page.route("**/api/v1/batches/*/save-confirm**", self._on_save_confirm)
        self.page.route("**/api/v1/requests/*/safe-info", self._on_safe_info)
        # 用户点选候选后的草案生成：这是「已选真实合集」的唯一合法来源。
        self.page.route("**/api/v1/requests", self._on_create_request)
        self.page.route(
            "**/api/v1/batches/parse",
            lambda route: route.fulfill(status=200, content_type="application/json", body=payload),
        )

    def _on_unexpected_external(self, route: Any, request: Any) -> None:
        self.external_calls.append(request.url)
        route.abort()

    def _on_create_request(self, route: Any, request: Any) -> None:
        """真实人工选择路径：服务端为被点选的候选返回草案快照。

        只有 fixture 明确登记过的候选（``SELECTIONS``）才生成草案；其他请求仍然按
        「意外外部调用」记帐并中止，避免把未登记的网络行为当成合法路径。
        """
        if request.method != "POST":
            self._on_unexpected_external(route, request)
            return
        body = request.post_data_json or {}
        bangumi_id = str(body.get("mikan_bangumi") or "").rsplit("/", 1)[-1]
        spec = self.selection_specs.get(bangumi_id)
        if spec is None:
            self._on_unexpected_external(route, request)
            return
        title, effective_count = spec
        preview = with_public_resources(
            _preview_request(title, f"req-{BATCH_ID}-selected-{bangumi_id}"),
            bangumi_id=bangumi_id,
            title=title,
            effective_count=effective_count,
        )
        draft_id = issue_draft_id(preview)
        self.created_draft_ids.append(draft_id)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "ok": True,
                    "result": {
                        "request": preview,
                        "summary": {},
                        "draft_id": draft_id,
                        "draft_revision": 1,
                    },
                },
                ensure_ascii=False,
            ),
        )

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

    def default_selections(self) -> tuple[str, ...]:
        """本批次中真正存在候选、且登记为「用户确认选择」的条目。"""
        by_id = {str(item.get("item_id") or ""): item for item in self.items}
        return tuple(
            item_id
            for item_id in SELECTIONS
            if by_id.get(item_id, {}).get("candidates")
        )

    def select_candidate_for(self, item_id: str) -> None:
        """走真实人工路径：点开条目 → 选择候选 → 服务端生成草案。

        「已选真实合集」只能由这条路径产生；fixture 不伪造选择结果。
        """
        card = self.page.locator(f'.batch-draft-card[data-item-id="{item_id}"]')
        card.click()
        pane = self.page.locator("#batch-detail-pane")
        expect(pane).to_contain_text("候选合集")
        pane.locator(".candidate-select").first.click()
        expect(card.locator(".batch-card-status")).to_contain_text("草案")
        expect(pane).to_contain_text("已选真实合集")

    def enter_workbench(
        self,
        *,
        checked_item_ids: tuple[str, ...] | None = None,
        click_item_id: str | None = None,
        select_item_ids: tuple[str, ...] | None = None,
    ) -> None:
        """进入批量工作台：先按真实路径确认选择的条目，再勾选并把当前项定在指定卡片。"""
        checked = checked_item_ids if checked_item_ids is not None else CHECKED_ITEM_IDS
        clicked = click_item_id if click_item_id is not None else CLICKED_ITEM_ID
        # 默认只对「本批次里真有候选」的登记条目走人工选择；边界批次（repeat_items）
        # 没有这些条目，不需要也不会伪造选择。
        selections = (
            select_item_ids
            if select_item_ids is not None
            else self.default_selections()
        )
        self.open_batch_input()
        self.page.fill("#batch-raw-input", raw_input_for(self.items))
        self.page.click("#batch-parse-submit")
        expect(self.page.locator(".batch-draft-card")).to_have_count(len(self.items))
        for item_id in selections:
            self.select_candidate_for(item_id)
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
        """关闭浮层并清空关键词，回到完整批次（#158：关闭入口是唯一的具名按钮）。"""
        if self.page.locator("#batch-review-search").count() == 0:
            self.page.click("#batch-review-search-toggle")
            self.page.wait_for_selector("#batch-review-search", timeout=10_000)
        self.page.fill("#batch-review-search", "")
        self.page.click("#batch-review-search-close")
        expect(self.page.locator("#batch-review-search")).to_have_count(0)
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
        # #145：审核截图从左栏列表顶部取景，让置顶的异常卡片（原因与唯一恢复动作）
        # 与当前查看项同时完整可见；否则更高的审核卡会把异常卡挤出取景。
        self.page.evaluate(
            """() => {
                const list = document.querySelector('.batch-card-grid-wrapper')
                if (list) list.scrollTop = 0
            }"""
        )
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

    def review_artifact_manifest(self, name: str, shot: Path) -> dict[str, Any]:
        """为一张候选图组装安全证据清单（#155）：构建、实际加载资源与截图摘要。

        无论是否落盘都先校验：dist 必须是当前源码的构建，页面加载的 ``/app`` 资源必须
        与 dist 逐字节一致；不满足就直接失败，不产出「看起来像证据」的图。
        """
        from urllib.parse import urlparse

        state = name.removesuffix(".png")
        return capture_evidence(
            self.page,
            shot,
            base_url=self.base_url,
            scenario=ScenarioDescriptor(
                f"batch-draft-{state}-1440x900",
                f"批量草案工作台候选图（{state}）",
                (
                    "以 1440×900、reduced-motion 进入固定批量草案工作台",
                    f"推进到 {state} 状态并关闭页面级提示条",
                    "等待字体/图片与双帧稳定后截图，并校验实际加载产物与 dist 一致",
                ),
            ),
            fixture=REVIEW_FIXTURE,
            resources=self.recorder.records(),
            route=urlparse(self.page.url).path or "/app/add",
        )

    def write_review_screenshot(self, name: str, shot: Path) -> Path | None:
        """把候选图与证据清单写到仓库内 pending 审核目录（仅在显式要求时）。"""
        if not self.review_screenshots_enabled():
            return None
        manifest = self.review_artifact_manifest(name, shot)
        REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        target = REVIEW_DIR / name
        target.write_bytes(shot.read_bytes())
        write_manifest(manifest, REVIEW_DIR, Path(name).stem)
        return target
