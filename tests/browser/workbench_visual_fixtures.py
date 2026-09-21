"""Stage 46 / US-359：图 01～03 的真实 Chromium 视觉 fixture。

三态共享同一套安全构造器：

- 图 01「单番初始」：``/app/add`` 首屏，只有名称输入与模式切换，无结果面板、
  无候选请求；
- 图 02「候选首项生成中」：固定标题返回三条公开候选，点击第一条后由 held route
  停在草案生成中；第一条就地 loading、其余候选防重复、候选阶段无资源数；
- 图 03「未保存草案审核」：释放真实 envelope，进入服务端草案审核。

所有 envelope 使用真实 DTO 形状：候选搜索走 ``/api/v1/mikan/candidates`` 的
``result`` 结构，草案走 ``POST /api/v1/requests`` + 服务端 ``draft_store`` 的
``preview_result_json``。不访问真实 MiKan / Auto Bangumi / qBittorrent。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, expect

from apps.migu_orca_entry.controllers.entry_controller import generate_request
from shared.models import EntryRequest
from tests.browser.conftest import preview_result_json, set_storage_preferences
from tests.browser.visual_support import prepare_canvas, require_dist

SINGLE_QUERY = "葬送的芙莉莲"
DRAFT_REQUEST_ID = "req-visual-359"

CANARY_CANDIDATE_CONTEXT = "visual-359-canary-candidate-context"
CANARY_MIKAN_URL = "https://visual-359-canary.invalid/Home/Bangumi/2353"

SINGLE_CANDIDATES: tuple[dict[str, Any], ...] = (
    {
        "bangumi_id": "2353",
        "title": "葬送的芙莉莲",
        "mikan_url": CANARY_MIKAN_URL,
        "poster_url": None,
        "source_query": SINGLE_QUERY,
        "aliases": [],
        "recommendation": "季度证据已在合集页确认",
        "season_evidence": {"status": "PROVEN", "season": 1, "requires_review": False},
        "candidate_context": CANARY_CANDIDATE_CONTEXT,
        "total_episodes": 28,
    },
    {
        "bangumi_id": "3072",
        "title": "葬送的芙莉莲 第二季",
        "mikan_url": "https://mikan.example/Home/Bangumi/3072",
        "poster_url": None,
        "source_query": SINGLE_QUERY,
        "aliases": ["Frieren S2"],
        "season_evidence": {"status": "PROVEN", "season": 2, "requires_review": False},
        "total_episodes": 24,
    },
    {
        "bangumi_id": "3510",
        "title": "葬送的芙莉莲 外传",
        "mikan_url": "https://mikan.example/Home/Bangumi/3510",
        "poster_url": None,
        "source_query": SINGLE_QUERY,
        "aliases": [],
        "season_evidence": {"status": "NEEDS_CONFIRMATION", "season": 1, "requires_review": True},
        "total_episodes": 12,
    },
)

CONNECTION_SUMMARY_BODY = json.dumps(
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

TRACKING_ITEMS_BODY = json.dumps({"ok": True, "result": {"items": []}}, ensure_ascii=False)


def candidate_search_envelope(query: str, candidates: list[dict[str, Any]]) -> str:
    """真实候选搜索 envelope（与 ``/api/v1/mikan/candidates`` 的 result 同形）。"""
    return json.dumps(
        {
            "ok": True,
            "result": {
                "query": query,
                "status": "FOUND",
                "parse_result": {
                    "normalized_title": query,
                    "base_title": query,
                    "season": {"number": None, "raw": None, "normalized": None, "source": "none"},
                    "season_number": None,
                    "season_hint": None,
                    "query_plan": [{"query": query, "source": "rule", "priority": 1}],
                    "search_queries": [query],
                    "source": "rule",
                    "confidence": 0.9,
                    "needs_user_review": False,
                    "review_hints": [],
                    "raw_title": query,
                },
                "attempted_queries": [{"query": query, "source": "rule", "priority": 1}],
                "candidates": candidates,
                "error": None,
            },
        },
        ensure_ascii=False,
    )


def preview_request(title: str, request_id: str) -> dict[str, Any]:
    """固定安全数据的未保存预览 Request（服务端静态 fixture 数据源）。"""
    return {
        **generate_request(EntryRequest(raw_title=title))["request"],
        "request_id": request_id,
    }


class SingleAnimeVisualScenario:
    """图 01～03 共享的三态构造器（真实 envelope + held route）。"""

    def __init__(self, page: Page, base_url: str) -> None:
        self.page = page
        self.base_url = base_url
        self.held_draft: list[Any] = []
        self.console_messages: list[str] = []
        self.safe_info_calls: list[str] = []
        self.external_calls: list[str] = []
        self.draft_body = ""
        self.draft_id = ""

    # -- routes ---------------------------------------------------------

    def install(self, storage_dir: Path, *, candidates: tuple[dict[str, Any], ...] | None = None) -> None:
        require_dist()
        prepare_canvas(self.page)
        set_storage_preferences(self.page, storage_dir)
        self.page.on("console", lambda message: self.console_messages.append(message.text))
        self.page.on("pageerror", lambda error: self.console_messages.append(str(error)))

        selected = tuple(candidates) if candidates is not None else SINGLE_CANDIDATES
        # Playwright resolves the *last* registered matching route first, so the
        # broad external-access guard is registered before the concrete routes.
        self.page.route("**/api/v1/mikan/**", self._on_unexpected_external)
        self.page.route("**/api/v1/mikan/candidates", self._on_candidates(selected))
        self.page.route("**/api/v1/requests/*/safe-info", self._on_safe_info)
        self.page.route("**/api/v1/settings/autobangumi", self._on_connection_summary)
        self.page.route("**/api/v1/tracking/items**", self._on_tracking_items)
        self.page.route("**/api/v1/requests", self._on_requests)

    def _on_candidates(self, candidates: tuple[dict[str, Any], ...]):
        body = candidate_search_envelope(SINGLE_QUERY, list(candidates))

        def handler(route: Any, _request: Any) -> None:
            route.fulfill(status=200, content_type="application/json", body=body)

        return handler

    def _on_requests(self, route: Any, request: Any) -> None:
        if request.method != "POST":
            route.continue_()
            return
        # Held: the fixture observes the honest in-flight loading state instead
        # of sleeping in the handler.
        self.held_draft.append(route)

    def _on_safe_info(self, route: Any, request: Any) -> None:
        self.safe_info_calls.append(request.url)
        route.fulfill(
            status=404,
            content_type="application/json",
            body=json.dumps({"ok": False, "error": {"code": "not_found", "message": "未找到"}}),
        )

    def _on_unexpected_external(self, route: Any, request: Any) -> None:
        self.external_calls.append(request.url)
        route.abort()

    def _on_connection_summary(self, route: Any, _request: Any) -> None:
        route.fulfill(status=200, content_type="application/json", body=CONNECTION_SUMMARY_BODY)

    def _on_tracking_items(self, route: Any, _request: Any) -> None:
        route.fulfill(status=200, content_type="application/json", body=TRACKING_ITEMS_BODY)

    # -- states ---------------------------------------------------------

    def open_initial(self) -> None:
        """图 01：单番初始态。"""
        self.page.goto(f"{self.base_url}/app/add")
        self.page.wait_for_selector("#mikan-candidate-search-form", timeout=10_000)
        expect(self.page.locator(".search-results-panel")).to_have_count(0)

    def search_candidates(self) -> None:
        """输入固定标题并等待三条真实候选渲染。"""
        self.page.fill("#mikan-candidate-query", SINGLE_QUERY)
        self.page.click("#mikan-candidate-search-submit")
        expect(self.page.locator(".candidate-card")).to_have_count(len(SINGLE_CANDIDATES))

    def hold_first_candidate_generation(self) -> None:
        """图 02：点击第一条候选并停在草案生成中。"""
        self.page.locator(".candidate-card").nth(0).locator(".candidate-select").click()
        self.wait_for_held(1)

    def release_draft_review(self) -> None:
        """图 03：释放真实 envelope 进入未保存草案审核。"""
        preview = preview_request(SINGLE_QUERY, DRAFT_REQUEST_ID)
        self.draft_body = preview_result_json(preview)
        self.draft_id = json.loads(self.draft_body)["result"]["draft_id"]
        self.held_draft[0].fulfill(status=200, content_type="application/json", body=self.draft_body)
        self.page.wait_for_selector("#detail-preview-edit-form", timeout=10_000)

    def wait_for_held(self, expected: int = 1, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while len(self.held_draft) < expected and time.monotonic() < deadline:
            self.page.wait_for_timeout(50)
        assert len(self.held_draft) >= expected, (
            f"expected {expected} in-flight draft request(s), captured {len(self.held_draft)}"
        )

    # -- state entry helpers --------------------------------------------

    def _reset(self) -> None:
        self.held_draft.clear()
        self.safe_info_calls.clear()
        self.external_calls.clear()
        self.console_messages.clear()

    def enter_figure_01(self) -> None:
        self._reset()
        self.open_initial()

    def enter_figure_02(self) -> None:
        self._reset()
        self.open_initial()
        self.search_candidates()
        self.hold_first_candidate_generation()

    def enter_figure_03(self) -> None:
        self._reset()
        self.open_initial()
        self.search_candidates()
        self.hold_first_candidate_generation()
        self.release_draft_review()

    def canary_values(self) -> tuple[str, ...]:
        return tuple(value for value in (CANARY_CANDIDATE_CONTEXT, self.draft_id) if value)
