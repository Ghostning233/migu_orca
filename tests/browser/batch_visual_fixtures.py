"""Stage 46 / US-360：图 04～06 的真实 Chromium 视觉 fixture。

三态共享批量构造器与真实 envelope：

- 图 04「六行搜索中」：固定六行原文，held ``POST /api/v1/batches/parse``，
  显示 6/36 与诚实不定进度，输入保持原样；
- 图 05「六项混合状态」：三项待选合集、两项草案待审核、一项搜索失败；当前查看
  第一项并 held 其候选详情生成（``POST /api/v1/requests``）；
- 图 06「两项手工勾选」：当前查看草案项，恰有两项手工勾选且可确认。

D-02（隐藏的手工勾选仍参与 N 部范围）与 D-04（导航）语义完全复用既有服务端契约
与 Stage 45 派生，不由 fixture 伪造。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, expect

from apps.migu_orca_entry.controllers.entry_controller import generate_request
from shared.models import EntryRequest
from tests.browser.conftest import issue_draft_id, set_storage_preferences
from tests.browser.visual_support import prepare_canvas, require_dist

BATCH_ID = "batch-visual-360"
BATCH_RAW_LINES: tuple[str, ...] = (
    "葬送的芙莉莲",
    "咒术回战",
    "孤独摇滚",
    "迷宫饭",
    "灵能百分百",
    "夏日重现",
)
BATCH_RAW_INPUT = "\n".join(BATCH_RAW_LINES)

CANARY_CANDIDATE_CONTEXT = "visual-360-canary-candidate-context"

BATCH_CANDIDATES: tuple[dict[str, Any], ...] = (
    {
        "bangumi_id": "2353",
        "title": "葬送的芙莉莲",
        "mikan_url": "https://mikan.example/Home/Bangumi/2353",
        "poster_url": None,
        "source_query": "葬送的芙莉莲",
        "aliases": [],
        "recommendation": None,
        "season_evidence": {"status": "PROVEN", "season": 1, "requires_review": False},
        "candidate_context": CANARY_CANDIDATE_CONTEXT,
        "total_episodes": 28,
    },
    {
        "bangumi_id": "3072",
        "title": "葬送的芙莉莲 第二季",
        "mikan_url": "https://mikan.example/Home/Bangumi/3072",
        "poster_url": None,
        "source_query": "葬送的芙莉莲",
        "aliases": [],
        "season_evidence": {"status": "PROVEN", "season": 2, "requires_review": False},
        "total_episodes": 24,
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


def preview_request(title: str, request_id: str) -> dict[str, Any]:
    generated = generate_request(EntryRequest(raw_title=title))
    if generated["request"] is None:
        generated = generate_request(EntryRequest(raw_title="葬送的芙莉莲"))
    assert generated["request"] is not None
    return {**generated["request"], "request_id": request_id}


def batch_candidate(
    *,
    bangumi_id: str,
    title: str,
    season: int,
    total_episodes: int,
    source_query: str,
    candidate_context: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "bangumi_id": bangumi_id,
        "title": title,
        "mikan_url": f"https://mikan.example/Home/Bangumi/{bangumi_id}",
        "poster_url": None,
        "source_query": source_query,
        "aliases": [],
        "recommendation": None,
        "season_evidence": {"status": "PROVEN", "season": season, "requires_review": False},
        "total_episodes": total_episodes,
    }
    if candidate_context is not None:
        payload["candidate_context"] = candidate_context
    return payload


def batch_item(
    item_id: str,
    raw_title: str,
    *,
    status: str = "FOUND",
    canonical_title: str | None = None,
    season_hint: str | None = None,
    candidates: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
    preview_request_payload: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """真实批量 item 形状（与 ``/api/v1/batches/parse`` 的 items 同构）。"""
    title = canonical_title or raw_title
    item: dict[str, Any] = {
        "item_id": item_id,
        "raw_title": raw_title,
        "status": status,
        "canonical_title_candidates": [canonical_title] if canonical_title else [],
        "season_hint": season_hint,
        "search_queries": [title],
        "confidence": 0.9,
        "needs_user_review": False,
        "source": "fake",
        "parse_result": None,
        "attempted_queries": [],
        "candidates": list(candidates),
        "applied_preferences": None,
        "preference_hits": [],
        "preference_warnings": [],
        "review_hints": [],
        "enhanced_search_queries": [],
        "preview_request": preview_request_payload,
        "error": error,
    }
    if preview_request_payload is not None:
        item["draft_id"] = issue_draft_id(preview_request_payload)
        item["draft_revision"] = 1
    return item


def batch_parse_envelope(items: list[dict[str, Any]], *, batch_id: str = BATCH_ID) -> str:
    return json.dumps(
        {
            "ok": True,
            "result": {
                "batch_id": batch_id,
                "raw_input": BATCH_RAW_INPUT,
                "items": items,
            },
        },
        ensure_ascii=False,
    )


def mixed_batch_items() -> list[dict[str, Any]]:
    """三项待选合集、两项草案待审核、一项搜索失败（图 05/06 同源）。"""
    found_titles = BATCH_RAW_LINES[:3]
    draft_titles = BATCH_RAW_LINES[3:5]
    items: list[dict[str, Any]] = []
    for index, title in enumerate(found_titles, start=1):
        candidates = list(BATCH_CANDIDATES) if index == 1 else [
            batch_candidate(
                bangumi_id=f"9{index:03d}",
                title=f"{title} 第一季",
                season=1,
                total_episodes=12 + index,
                source_query=title,
            )
        ]
        items.append(
            batch_item(
                f"item-{index:02d}",
                title,
                status="FOUND",
                canonical_title=f"{title} 第一季",
                season_hint="第 1 季",
                candidates=candidates,
            )
        )
    for offset, title in enumerate(draft_titles, start=4):
        items.append(
            batch_item(
                f"item-{offset:02d}",
                title,
                status="DRAFT",
                canonical_title=f"{title} 第一季",
                season_hint="第 1 季",
                preview_request_payload=preview_request(title, f"req-visual-360-{offset:02d}"),
            )
        )
    items.append(
        batch_item(
            f"item-{len(BATCH_RAW_LINES):02d}",
            BATCH_RAW_LINES[-1],
            status="FAILED",
            error={
                "error_type": "mikan_unavailable",
                "error_message": "MiKan 候选搜索暂时不可用",
            },
        )
    )
    return items


class BatchVisualScenario:
    """图 04～06 共享的三态构造器。"""

    def __init__(self, page: Page, base_url: str) -> None:
        self.page = page
        self.base_url = base_url
        self.held_parse: list[Any] = []
        self.held_draft: list[Any] = []
        self.console_messages: list[str] = []
        self.external_calls: list[str] = []
        self.save_confirm_calls: list[str] = []
        self.parse_body = ""
        self.draft_body = ""
        self.draft_id = ""

    # -- routes ---------------------------------------------------------

    def install(self, storage_dir: Path, *, items: list[dict[str, Any]] | None = None) -> None:
        require_dist()
        prepare_canvas(self.page)
        set_storage_preferences(self.page, storage_dir)
        self.page.on("console", lambda message: self.console_messages.append(message.text))
        self.page.on("pageerror", lambda error: self.console_messages.append(str(error)))

        payload = list(items) if items is not None else mixed_batch_items()
        self.parse_body = batch_parse_envelope(payload)
        # Broad guard first: Playwright resolves the last registered match first.
        self.page.route("**/api/v1/mikan/**", self._on_unexpected_external)
        self.page.route("**/api/v1/batches/*/save-confirm**", self._on_save_confirm)
        self.page.route("**/api/v1/batches/parse", self._on_parse)
        self.page.route("**/api/v1/settings/autobangumi", self._on_connection_summary)
        self.page.route("**/api/v1/tracking/items**", self._on_tracking_items)
        self.page.route("**/api/v1/requests/*/safe-info", self._on_safe_info)
        self.page.route("**/api/v1/requests", self._on_requests)

    def _on_parse(self, route: Any, request: Any) -> None:
        if request.method != "POST":
            route.continue_()
            return
        self.held_parse.append(route)

    def _on_requests(self, route: Any, request: Any) -> None:
        if request.method != "POST":
            route.continue_()
            return
        self.held_draft.append(route)

    def _on_save_confirm(self, route: Any, request: Any) -> None:
        self.save_confirm_calls.append(request.url)
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

    def _on_unexpected_external(self, route: Any, request: Any) -> None:
        self.external_calls.append(request.url)
        route.abort()

    def _on_connection_summary(self, route: Any, _request: Any) -> None:
        route.fulfill(status=200, content_type="application/json", body=CONNECTION_SUMMARY_BODY)

    def _on_tracking_items(self, route: Any, _request: Any) -> None:
        route.fulfill(status=200, content_type="application/json", body=TRACKING_ITEMS_BODY)

    # -- states ---------------------------------------------------------

    def open_batch_input(self) -> None:
        self.page.goto(f"{self.base_url}/app/add")
        self.page.wait_for_selector("#anime-mode-switch", timeout=10_000)
        self.page.click("#anime-mode-batch")
        self.page.wait_for_selector("#batch-parse-form", timeout=10_000)

    def submit_six_lines_held(self) -> None:
        """图 04：六行原文提交后停在整体搜索中。"""
        self.page.fill("#batch-raw-input", BATCH_RAW_INPUT)
        self.page.click("#batch-parse-submit")
        self.wait_for_held(self.held_parse, 1)

    def release_parse(self, expected: int | None = None) -> None:
        self.held_parse[0].fulfill(status=200, content_type="application/json", body=self.parse_body)
        expect(self.page.locator(".batch-draft-card")).to_have_count(
            expected if expected is not None else len(BATCH_RAW_LINES)
        )

    def hold_current_candidate_generation(self) -> None:
        """图 05：当前查看第一项并 held 其候选详情生成。"""
        first = self.page.locator('.batch-draft-card[data-item-id="item-01"]')
        first.locator(".batch-card-expand").click()
        detail = self.page.locator("#batch-detail-pane")
        expect(detail).to_be_visible()
        detail.locator(".candidate-select").first.click()
        self.wait_for_held(self.held_draft, 1)

    def release_candidate_and_check_two_drafts(self) -> None:
        """图 06：释放候选 envelope，查看草案项并手工勾选恰两项。"""
        preview = preview_request("迷宫饭", "req-visual-360-current")
        self.draft_body = json.dumps({"ok": True, "result": {"request": preview, "draft_id": issue_draft_id(preview), "draft_revision": 1}}, ensure_ascii=False)
        self.draft_id = json.loads(self.draft_body)["result"]["draft_id"]
        self.held_draft[0].fulfill(status=200, content_type="application/json", body=self.draft_body)
        expect(self.page.locator(".candidate-card")).to_have_count(0)
        for item_id in ("item-04", "item-05"):
            self.page.locator(f'.batch-draft-card[data-item-id="{item_id}"] .batch-card-checkbox-row').check()
        self.page.locator('.batch-draft-card[data-item-id="item-04"] .batch-card-expand').click()

    def wait_for_held(self, held: list[Any], expected: int = 1, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while len(held) < expected and time.monotonic() < deadline:
            self.page.wait_for_timeout(50)
        assert len(held) >= expected, f"expected {expected} held request(s), captured {len(held)}"

    # -- state entry helpers --------------------------------------------

    def _reset(self) -> None:
        self.held_parse.clear()
        self.held_draft.clear()
        self.console_messages.clear()
        self.external_calls.clear()
        self.save_confirm_calls.clear()

    def enter_figure_04(self) -> None:
        self._reset()
        self.open_batch_input()
        self.submit_six_lines_held()

    def enter_figure_05(self) -> None:
        self._reset()
        self.open_batch_input()
        self.submit_six_lines_held()
        self.release_parse()
        self.hold_current_candidate_generation()

    def enter_figure_06(self) -> None:
        self._reset()
        self.open_batch_input()
        self.submit_six_lines_held()
        self.release_parse()
        self.hold_current_candidate_generation()
        self.release_candidate_and_check_two_drafts()

    def canary_values(self) -> tuple[str, ...]:
        return tuple(value for value in (CANARY_CANDIDATE_CONTEXT, self.draft_id) if value)
