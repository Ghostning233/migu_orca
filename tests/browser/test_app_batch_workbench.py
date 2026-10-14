from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from apps.migu_orca_entry.controllers.entry_controller import generate_request
from shared.models import EntryRequest
from tests.browser.conftest import issue_draft_id, set_storage_preferences
from tests.browser.screen_support import wait_for_screen_scroll

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.browser


def _dist_built() -> bool:
    """True when the Vite production build exists (frontend/dist/index.html)."""
    return (REPO_ROOT / "frontend" / "dist" / "index.html").is_file()


def _require_dist() -> None:
    """The SPA build is a hard prerequisite for these browser tests."""
    if _dist_built():
        return
    if os.environ.get("MIGU_ORCA_CI") == "1":
        raise RuntimeError(
            "frontend/dist missing in CI — run `npm ci && npm run build` "
            "in frontend/ before the browser suite."
        )
    pytest.skip(
        "frontend/dist not built — run `cd frontend && npm ci && npm run build` "
        "to verify the US-205 batch workbench migration in the browser."
    )


def _goto_batch(page: Page, live_server_url: str) -> None:
    """Navigate to the SPA workbench and scroll the batch panel into view."""
    _require_dist()
    page.goto(f"{live_server_url}/app/workbench")
    # US-267 defaults the shared workbench to single mode.  Activate batch
    # mode before asserting the legacy batch controls used by this suite.
    page.wait_for_selector("#anime-mode-switch", timeout=5000)
    page.click("#anime-mode-batch")
    page.wait_for_selector("#batch-parse-form", timeout=5000)


def _preview_request(title: str, request_id: str) -> dict[str, Any]:
    """Build an unsaved preview Request dict (PENDING_CONFIRM, not on disk)."""
    generated = generate_request(EntryRequest(raw_title=title))
    if generated["request"] is None:
        generated = generate_request(EntryRequest(raw_title="葬送的芙莉莲"))
    assert generated["request"] is not None
    return {**generated["request"], "request_id": request_id}


def _preview_request_without_resources(title: str, request_id: str) -> dict[str, Any]:
    """A DRAFT preview whose confirmable config has no effective seed (US-347).

    Such an item is a real DRAFT card that the shared confirmability gate must
    keep out of the 保存并确认全部 scope.
    """
    preview = _preview_request(title, request_id)
    preview["confirmable_config"]["effective_seed_names"] = []
    return preview


def _batch_item(
    item_id: str,
    raw_title: str,
    *,
    status: str = "FOUND",
    canonical_title: str | None = None,
    candidate_title: str | None = None,
    season_hint: str | None = None,
    search_queries: list[str] | None = None,
    needs_user_review: bool = False,
    review_hints: list[str] | None = None,
    candidates: list[dict[str, Any]] | None = None,
    preview_request: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    title = canonical_title or candidate_title or raw_title
    item: dict[str, Any] = {
        "item_id": item_id,
        "raw_title": raw_title,
        "status": status,
        "canonical_title_candidates": [canonical_title] if canonical_title else [],
        "season_hint": season_hint,
        "search_queries": list(search_queries or [title]),
        "confidence": 0.9,
        "needs_user_review": needs_user_review,
        "source": "fake",
        "parse_result": None,
        "attempted_queries": [],
        "candidates": candidates or [],
        "applied_preferences": None,
        "preference_hits": [],
        "preference_warnings": [],
        "review_hints": list(review_hints or []),
        "enhanced_search_queries": [],
        "preview_request": preview_request,
        "error": error,
    }
    if preview_request is not None:
        # A card with a preview_request needs a server-authoritative draft_id
        # and draft_revision so preview-modify accepts it.
        item["draft_id"] = issue_draft_id(preview_request)
        item["draft_revision"] = 1
    return item


def _candidate(
    *,
    bangumi_id: str,
    title: str,
    mikan_url: str,
    season_evidence: dict[str, Any] | None = None,
    candidate_context: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "bangumi_id": bangumi_id,
        "title": title,
        "mikan_url": mikan_url,
        "poster_url": None,
        "source_query": title,
        "aliases": [],
        "recommendation": None,
        "total_episodes": None,
    }
    if season_evidence is not None:
        result["season_evidence"] = season_evidence
    if candidate_context is not None:
        result["candidate_context"] = candidate_context
    return result


def _batch_parse_result(items: list[dict[str, Any]], *, batch_id: str = "batch-spa") -> str:
    return json.dumps(
        {
            "ok": True,
            "result": {
                "batch_id": batch_id,
                "raw_input": "萌王S4\n路哥S4",
                "items": items,
            },
        },
        ensure_ascii=False,
    )


def _batch_accept_result(items: list[dict[str, Any]], queue_items: list[dict[str, Any]], *, batch_id: str = "batch-spa") -> str:
    summary = {"accepted": 0, "already_accepted": 0, "unacceptable": 0, "failed": 0}
    for item in items:
        status = item.get("status", "accepted")
        if status in summary:
            summary[status] += 1
    results = []
    for item in items:
        outcome = str(item.get("outcome") or ("CONFIRMED" if item.get("status") == "CONFIRMED" else "failed"))
        results.append({
            "item_id": item.get("item_id"),
            "outcome": outcome,
            "request_id": item.get("request_id"),
            "status": item.get("status") if outcome == "CONFIRMED" else None,
            "error_type": item.get("error_type") or (None if outcome == "CONFIRMED" else "batch_error"),
            "error_message": None,
            "tracking_id": item.get("tracking_id"),
            "tracking_ready": item.get("tracking_ready"),
        })
    return json.dumps(
        {
            "ok": True,
            "result": {
                "batch_id": batch_id,
                "results": results,
                "summary": summary,
            },
        },
        ensure_ascii=False,
    )


def _queue_item(item_id: str, request_id: str, title: str, status: str = "READY_TO_SUBMIT", *, batch_id: str = "batch-spa") -> dict[str, Any]:
    return {
        "queue_id": f"queue-{batch_id}",
        "batch_id": batch_id,
        "item_id": item_id,
        "request_id": request_id,
        "title": title,
        "status": status,
        "status_label": "待提交",
        "attempts": 0,
        "last_error": None,
        "ab_result_summary": None,
        "created_at": "2026-08-19T00:00:00+00:00",
        "updated_at": "2026-08-19T00:00:00+00:00",
    }


def _accept_route_handler(accepted_ids: set[str], *, batch_id: str = "batch-spa"):
    """Accept the given cards and mark everything else unacceptable."""

    def _handler(route: Any, request: Any) -> None:
        payload = json.loads(request.post_data or "{}")
        results = []
        queue_items = []
        for item in payload.get("items", []):
            item_id = item["item_id"]
            request_id = item.get("request_id")
            title = item.get("title") or "未命名订阅方案"
            if item_id in accepted_ids:
                results.append(
                    {
                        "item_id": item_id,
                        "request_id": request_id or f"req-{item_id}",
                        "title": title,
                        "status": "CONFIRMED",
                        "outcome": "CONFIRMED",
                        "tracking_id": f"tracking-{item_id}",
                        "tracking_ready": True,
                        "error_type": None,
                    }
                )
                queue_items.append(_queue_item(item_id, request_id, title, batch_id=batch_id))
            else:
                results.append(
                    {
                        "item_id": item_id,
                        "request_id": request_id,
                        "title": title,
                        "status": "unacceptable",
                        "reason": "卡片缺少订阅草案，无法接受",
                        "error_type": None,
                        "queued": False,
                    }
                )
        route.fulfill(
            status=200,
            content_type="application/json",
            body=_batch_accept_result(results, queue_items, batch_id=batch_id),
        )

    return _handler


def _open_title_search(page: Page) -> None:
    """#149：标题搜索默认收起为放大镜，浮层不参与布局；用例先展开再输入。"""
    page.click("#batch-review-search-toggle")
    page.wait_for_selector("#batch-review-search", timeout=5000)


def _fill_title_search(page: Page, value: str) -> None:
    if page.locator("#batch-review-search").count() == 0:
        _open_title_search(page)
    page.fill("#batch-review-search", value)


def _select_cards(page: Page, item_ids: list[str]) -> None:
    """#145：唯一保存入口按勾选范围保存，先明确勾选目标条目。"""
    for item_id in item_ids:
        page.locator(f'.batch-draft-card[data-item-id="{item_id}"] .batch-card-checkbox-row').check()


class TestAppBatchParse:
    """AC: 批量输入与独立 FOUND/EMPTY/FAILED 卡片."""

    def test_empty_input_is_validated_without_api_call(
        self, page: Page, live_server_url: str
    ) -> None:
        calls: list[str] = []

        def _capture(route: Any, request: Any) -> None:
            calls.append(request.url)
            route.fulfill(status=200, content_type="application/json", body='{"ok": true}')

        page.route("**/api/v1/batches/parse", _capture)
        _goto_batch(page, live_server_url)

        expect(page.locator("#batch-parse-submit")).to_be_disabled()
        expect(page.locator("#batch-input-count")).to_contain_text("当前 0 部")
        assert calls == []

    def test_parse_renders_independent_card_statuses(
        self, page: Page, live_server_url: str
    ) -> None:
        page.route(
            "**/api/v1/batches/parse",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(
                    [
                        _batch_item("item-found", "萌王S4", candidates=[_candidate(bangumi_id="42", title="转生史莱姆 第四季", mikan_url="https://mikan.example/Home/Bangumi/42")]),
                        _batch_item("item-empty", "路哥S4", status="EMPTY"),
                        _batch_item("item-failed", "杖剑谭S2", status="FAILED", error={"error_type": "mikan_unavailable", "error_message": "MiKan 候选搜索暂时不可用"}),
                    ]
                ),
            ),
        )
        _goto_batch(page, live_server_url)
        page.fill("#batch-raw-input", "萌王S4\n路哥S4\n杖剑谭S2")
        page.click("#batch-parse-submit")

        expect(page.locator(".batch-draft-card")).to_have_count(3)
        found = page.locator(".batch-draft-card", has_text="萌王S4")
        empty = page.locator(".batch-draft-card", has_text="路哥S4")
        failed = page.locator(".batch-draft-card", has_text="杖剑谭S2")
        expect(found.locator(".batch-card-status")).to_contain_text("找到候选")
        expect(empty.locator(".batch-card-status")).to_contain_text("未找到候选")
        expect(failed.locator(".batch-card-status")).to_contain_text("搜索失败")
        expect(failed.locator(".batch-candidate-feedback")).to_contain_text(
            "该条目候选搜索失败，请稍后重试。"
        )
        # The raw error_type never leaks into the DOM.
        body_text = page.locator("body").inner_text()
        assert "mikan_unavailable" not in body_text

    def test_parse_loading_message_and_batch_id_url(
        self, page: Page, live_server_url: str
    ) -> None:
        pending: list[Any] = []

        def _hold(route: Any, request: Any) -> None:
            pending.append(route)

        page.route("**/api/v1/batches/parse", _hold)
        _goto_batch(page, live_server_url)
        page.fill("#batch-raw-input", "萌王S4\n路哥S4")
        page.click("#batch-parse-submit")

        expect(page.locator("#batch-parse-result")).to_contain_text(
            "正在逐项搜索 2 个批量条目的 MiKan 候选"
        )
        expect(page.locator("#batch-parse-result")).to_contain_text("整体结果将在批量完成后统一展示")
        expect(page.locator("#batch-parse-result")).to_contain_text("数分钟")
        assert pending
        pending[0].fulfill(
            status=200,
            content_type="application/json",
            body=_batch_parse_result([_batch_item("item-1", "萌王S4", status="EMPTY")]),
        )

        expect(page.locator(".batch-draft-card")).to_have_count(1)
        # The public batch_id is pushed into the URL for queue refresh recovery.
        assert "batch_id=batch-spa" in page.url

    def test_360px_no_horizontal_overflow(
        self, page: Page, live_server_url: str
    ) -> None:
        page.route(
            "**/api/v1/batches/parse",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(
                    [_batch_item("item-1", "萌王S4", status="EMPTY")],
                ),
            ),
        )
        _goto_batch(page, live_server_url)
        page.set_viewport_size({"width": 360, "height": 800})
        page.fill("#batch-raw-input", "萌王S4")
        page.click("#batch-parse-submit")
        expect(page.locator(".batch-draft-card")).to_have_count(1)

        overflow = page.evaluate("() => document.body.scrollWidth > window.innerWidth")
        assert overflow is False

    @pytest.mark.parametrize("count,zoom", [(12, 1), (36, 2)])
    def test_populated_batch_layout_scrolls_without_horizontal_overflow(
        self, page: Page, live_server_url: str, count: int, zoom: int
    ) -> None:
        items = [
            _batch_item(
                f"item-{index}",
                f"番剧 {index}",
                status="DRAFT",
                preview_request=_preview_request(f"番剧 {index}", f"req-{index}"),
            )
            for index in range(count)
        ]
        page.route(
            "**/api/v1/batches/parse",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(items),
            ),
        )
        _goto_batch(page, live_server_url)
        page.set_viewport_size({"width": 1280, "height": 900})
        if zoom == 2:
            page.evaluate("() => { document.documentElement.style.zoom = '2' }")
        page.fill("#batch-raw-input", "\n".join(f"番剧 {index}" for index in range(count)))
        page.click("#batch-parse-submit")
        expect(page.locator(".batch-draft-card")).to_have_count(count)
        assert page.evaluate("() => document.body.scrollWidth <= window.innerWidth")
        expect(page.locator("#batch-accept-toolbar")).to_be_visible()
        page.locator(".batch-draft-card").last.scroll_into_view_if_needed()
        expect(page.locator(".batch-draft-card").last).to_be_visible()
        expect(page.locator("#batch-accept-submit")).to_be_visible()


class TestAppBatchCandidateAndDraft:
    """AC: 右侧候选、季数确认、草案详情与删除."""

    def test_found_card_selects_right_detail_candidate_and_generates_draft(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        captured: list[dict[str, Any]] = []
        preview = _preview_request("关于我转生变成史莱姆这档事 第四季", "req-batch-gen")
        page.route(
            "**/api/v1/batches/parse",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(
                    [
                        _batch_item(
                            "item-found",
                            "萌王S4",
                            candidates=[_candidate(bangumi_id="42", title="关于我转生变成史莱姆这档事 第四季", mikan_url="https://mikan.example/Home/Bangumi/42")],
                        )
                    ]
                ),
            ),
        )

        def _create(route: Any, request: Any) -> None:
            if request.method != "POST":
                route.continue_()
                return
            captured.append(request.post_data_json)
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": True,
                        "result": {
                            "request": preview,
                            "summary": {},
                            "draft_id": issue_draft_id(preview),
                            "draft_revision": 1,
                        },
                    },
                    ensure_ascii=False,
                ),
            )

        page.route("**/api/v1/requests", _create)
        set_storage_preferences(page, storage_dir)
        _goto_batch(page, live_server_url)
        page.fill("#batch-raw-input", "萌王S4")
        page.click("#batch-parse-submit")

        card = page.locator(".batch-draft-card", has_text="萌王S4")
        expect(card).to_have_attribute("aria-label", re.compile(r"查看条目"))
        card.click()

        choices = page.locator("#batch-detail-pane")
        expect(choices).to_be_visible()
        choices.locator(".candidate-select").click()
        page.wait_for_selector(".batch-draft-card .batch-card-status", timeout=5000)

        expect(card.locator(".batch-card-status")).to_contain_text("草案")
        assert captured
        payload = captured[0]
        assert payload["mikan_bangumi"] == "https://mikan.example/Home/Bangumi/42"
        # The draft_id never enters the URL or DOM.
        assert "request_id=" not in page.url
        assert "opaque" not in page.content()

    def test_needs_confirmation_candidate_blocks_until_checked(
        self, page: Page, live_server_url: str
    ) -> None:
        page.route(
            "**/api/v1/batches/parse",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(
                    [
                        _batch_item(
                            "item-found",
                            "芙莉莲S4",
                            candidates=[
                                _candidate(
                                    bangumi_id="2353",
                                    title="葬送的芙莉莲 第四季",
                                    mikan_url="https://mikan.example/Home/Bangumi/2353",
                                    season_evidence={"status": "NEEDS_CONFIRMATION", "season": 4, "requires_review": True},
                                    candidate_context="opaque-context",
                                )
                            ],
                        )
                    ]
                ),
            ),
        )
        _goto_batch(page, live_server_url)
        page.fill("#batch-raw-input", "芙莉莲S4")
        page.click("#batch-parse-submit")

        card = page.locator(".batch-draft-card", has_text="芙莉莲S4")
        card.click()
        choices = page.locator("#batch-detail-pane")
        confirmation = choices.locator(".candidate-season-confirmation input")
        choose = choices.locator(".candidate-select")
        expect(confirmation).not_to_be_checked()
        expect(choose).to_be_disabled()

        confirmation.check()
        expect(choose).to_be_enabled()
        # candidate_context never enters the DOM.
        assert "opaque-context" not in page.locator("body").inner_text()

    def test_draft_card_opens_the_batch_detail_hierarchy_without_duplicate_actions(
        self, page: Page, live_server_url: str
    ) -> None:
        page.route(
            "**/api/v1/batches/parse",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(
                    [
                        _batch_item("item-1", "萌王S4", status="DRAFT", canonical_title="关于我转生变成史莱姆这档事 第四季", preview_request=_preview_request("咒术回战", "req-batch-detail")),
                        _batch_item("item-2", "路哥S4", status="DRAFT", canonical_title="实力至上主义教室 第四季", preview_request=_preview_request("咒术回战", "req-batch-other")),
                    ]
                ),
            ),
        )
        _goto_batch(page, live_server_url)
        page.fill("#batch-raw-input", "萌王S4\n路哥S4")
        page.click("#batch-parse-submit")

        expect(page.locator(".batch-draft-card")).to_have_count(2)
        first = page.locator(".batch-draft-card", has_text="萌王S4")
        expect(first).to_have_attribute("aria-label", re.compile(r"查看条目"))
        first.click()

        panel = page.locator("#request-detail-container")
        expect(panel).to_be_visible()
        expanded_text = panel.inner_text()
        # #150：右栏信息层级 = 合集身份 + 字幕与筛选 + 资源结果 + 折叠的高级设置。
        # 产品边界：这条 fixture 只有服务端匹配信息、没有用户人工选择，因此身份区必须
        # 显示待核对，绝不声称「已选真实合集」。（真实人工选择后的确认态由
        # test_app_batch_draft_visual.py::test_unconfirmed_draft_never_claims_a_selected_collection
        # 与几何用例覆盖。）
        assert "尚未确认真实合集" in expanded_text
        assert "已选真实合集" not in expanded_text
        assert "字幕与筛选" in expanded_text
        assert "资源结果" in expanded_text
        assert "已更新集数" in expanded_text and "未开发" in expanded_text
        assert "预期总集数" in expanded_text
        # 移除默认层重复信息与重复动作。
        assert "加入批量确认" not in expanded_text
        expect(page.locator("#batch-detail-accept")).to_have_count(0)
        expect(page.locator("#batch-detail-delete")).to_have_count(0)
        expect(panel.locator(".filter-section")).to_have_count(0)
        expect(panel.locator(".advanced-detail")).to_have_count(0)
        expect(panel.locator(".complete-seed-details")).to_have_count(0)
        # 折叠的高级设置不参与布局，内容不可见也不可达。
        advanced = page.locator(".batch-draft-advanced")
        expect(advanced).to_have_count(1)
        assert advanced.evaluate("details => details.open") is False
        expect(page.locator("#batch-preview-folder-name")).to_be_hidden()
        # #149：删除未保存条目仍由左栏卡片的小图标承担。
        delete_icon = first.locator(".batch-card-delete")
        delete_icon.scroll_into_view_if_needed()
        delete_icon.click()
        expect(page.locator(".batch-draft-card")).to_have_count(1)
        assert "路哥S4" in page.locator("#batch-parse-result").inner_text()
        assert "萌王S4" not in page.locator("#batch-parse-result").inner_text()

    def test_current_view_switch_is_independent_from_checkbox_selection(
        self, page: Page, live_server_url: str
    ) -> None:
        """AC (US-345/F4)：批量「当前查看」只切换右栏，复选框只改变保存范围；
        固定操作栏是唯一批量主「保存并确认 N 部」入口。"""
        items = [
            _batch_item(
                f"item-{index:02d}",
                f"番剧{index:02d}",
                status="DRAFT",
                canonical_title=f"番剧{index:02d} 第 1 季",
                preview_request=_preview_request(f"番剧{index:02d}", f"req-f4-{index:02d}"),
            )
            for index in range(12)
        ]
        page.route(
            "**/api/v1/batches/parse",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(items),
            ),
        )
        _goto_batch(page, live_server_url)
        page.fill("#batch-raw-input", "\n".join(f"番剧{index:02d}" for index in range(12)))
        page.click("#batch-parse-submit")
        expect(page.locator(".batch-draft-card")).to_have_count(12)

        cards = page.locator(".batch-draft-card")
        second = cards.nth(1)
        second.locator(".batch-card-checkbox-row").check()
        expect(page.locator("#batch-accept-selected-count")).to_contain_text("已选 1 部")

        # 切换「当前查看」到第 5 项：只有右栏换条目，勾选与保存范围不变。
        cards.nth(4).click()
        expect(cards.nth(4)).to_have_class(re.compile(r"is-current"))
        expect(second).not_to_have_class(re.compile(r"is-current"))
        expect(second.locator(".batch-card-checkbox-row")).to_be_checked()
        expect(page.locator("#batch-accept-selected-count")).to_contain_text("已选 1 部")
        expect(page.locator("#batch-detail-pane")).to_contain_text("字幕与筛选")

        # 唯一主入口在固定操作栏；右栏与列内动作都是次要按钮。
        expect(page.locator("#batch-detail-pane")).to_be_visible()
        expect(page.locator("#batch-detail-pane .primary-button")).to_have_count(0)
        expect(page.locator("#batch-detail-accept")).to_have_count(0)
        expect(page.locator("#batch-detail-delete")).to_have_count(0)
        submit_class = page.locator("#batch-accept-submit").get_attribute("class") or ""
        assert "primary-button" in submit_class
        # #145：不再有并行的「保存并确认全部」入口。
        expect(page.locator("#batch-accept-all")).to_have_count(0)

        # 回到第 2 项：保存范围仍是同一个复选框，未被「当前查看」改写。
        second.click()
        expect(second).to_have_class(re.compile(r"is-current"))
        expect(second.locator(".batch-card-checkbox-row")).to_be_checked()
        expect(page.locator("#batch-accept-selected-count")).to_contain_text("已选 1 部")
        # 右栏仍显示被查看条目的批量草案信息层级。
        expect(page.locator("#batch-detail-pane")).to_contain_text("字幕与筛选")

    def test_expired_batch_draft_keeps_card_and_returns_to_candidates(
        self, page: Page, live_server_url: str
    ) -> None:
        preview = _preview_request("咒术回战", "req-batch-expired")
        page.route(
            "**/api/v1/batches/parse",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(
                    [_batch_item(
                        "item-expired",
                        "萌王S4",
                        status="DRAFT",
                        candidates=[_candidate(
                            bangumi_id="42",
                            title="关于我转生变成史莱姆这档事 第四季",
                            mikan_url="https://mikan.example/Home/Bangumi/42",
                        )],
                        preview_request=preview,
                    )]
                ),
            ),
        )
        page.route(
            "**/api/v1/requests/preview-modify",
            lambda route: route.fulfill(
                status=409,
                content_type="application/json",
                body=json.dumps({
                    "ok": False,
                    "error_type": "draft_revision_conflict",
                    "error_message": "草案已被更新，请基于最新版本重试",
                    "error_data": {"field": "base_revision"},
                }, ensure_ascii=False),
            ),
        )
        page.route(
            "**/api/v1/batches/batch-spa/save-confirm*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_accept_result(
                    [{
                        "item_id": "item-expired",
                        "request_id": None,
                        "title": "咒术回战",
                        "status": "unacceptable",
                        "reason": "旧失败反馈",
                        "error_type": None,
                        "queued": False,
                    }],
                    [],
                ),
            ),
        )
        _goto_batch(page, live_server_url)
        page.fill("#batch-raw-input", "萌王S4")
        page.click("#batch-parse-submit")
        card = page.locator(".batch-draft-card", has_text="萌王S4")
        card.locator(".batch-card-checkbox-row").check()
        page.click("#batch-accept-submit")
        page.wait_for_selector(".confirm-dialog", timeout=5000)
        page.locator(".confirm-dialog .primary-button").click()
        expect(card.locator(".batch-card-reason")).to_contain_text("保存确认失败，请重试。")
        expect(card.locator(".batch-card-status")).to_contain_text("草案")
        expect(card.locator(".batch-card-checkbox-row")).to_be_checked()

    def test_expanded_draft_ignores_sensitive_fields(
        self, page: Page, live_server_url: str
    ) -> None:
        preview = _preview_request("咒术回战", "req-batch-sec")
        preview["source_info"] = {
            "raw_html": "<html>secret-token</html>",
            "cookie": "session-cookie",
            "token": "secret-token",
            "raw_response_body": "raw-body-secret",
            "rss_sources": [
                {
                    "subtitle_group": "桜都字幕组",
                    "rss_url": "https://mikan.example/RSS/Bangumi?token=secret-token",
                    "seed_names": ["史莱姆 S4 01 [1080p]"],
                    "valid_seed_names": ["史莱姆 S4 01 [1080p]"],
                    "excluded_seed_names": [],
                }
            ],
        }
        page.route(
            "**/api/v1/batches/parse",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(
                    [_batch_item("item-sec", "萌王S4", status="DRAFT", preview_request=preview)],
                ),
            ),
        )
        _goto_batch(page, live_server_url)
        page.fill("#batch-raw-input", "萌王S4")
        page.click("#batch-parse-submit")
        page.locator(".batch-draft-card").first.click()

        body_text = page.locator("body").inner_text()
        assert "secret-token" not in body_text
        assert "session-cookie" not in body_text
        assert "<rss>" not in body_text
        assert "raw-body-secret" not in body_text
        assert "https://mikan.example/RSS/Bangumi" not in body_text


class TestAppBatchAccept:
    """AC: 选择、单个接受、批量接受与全接受."""

    def _setup_two_drafts(self, page: Page, live_server_url: str) -> None:
        page.route(
            "**/api/v1/batches/parse",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(
                    [
                        _batch_item("item-1", "萌王S4", status="DRAFT", canonical_title="关于我转生变成史莱姆这档事 第四季", preview_request=_preview_request("咒术回战", "req-1")),
                        _batch_item("item-2", "路哥S4", status="DRAFT", canonical_title="实力至上主义教室 第四季", preview_request=_preview_request("咒术回战", "req-2")),
                    ]
                ),
            ),
        )
        _goto_batch(page, live_server_url)
        page.fill("#batch-raw-input", "萌王S4\n路哥S4")
        page.click("#batch-parse-submit")
        expect(page.locator(".batch-draft-card")).to_have_count(2)

    def test_selected_accept_only_accepts_checked_cards(
        self, page: Page, live_server_url: str
    ) -> None:
        accept_calls: list[dict[str, Any]] = []
        def _accept(route: Any, request: Any) -> None:
            accept_calls.append(json.loads(request.post_data or "{}"))
            _accept_route_handler({"item-1"})(route, request)

        page.route("**/api/v1/batches/batch-spa/save-confirm*", _accept)
        self._setup_two_drafts(page, live_server_url)

        expect(page.locator("#batch-accept-toolbar")).to_be_visible()
        expect(page.locator("#batch-accept-selected-count")).to_contain_text("已选 0 部")
        expect(page.locator("#batch-accept-submit")).to_be_disabled()

        first = page.locator(".batch-draft-card", has_text="萌王S4")
        first.locator(".batch-card-checkbox-row").check()
        expect(page.locator("#batch-accept-selected-count")).to_contain_text("已选 1 部")
        expect(page.locator("#batch-accept-submit")).to_be_enabled()

        page.click("#batch-accept-submit")
        page.wait_for_selector(".confirm-dialog", timeout=5000)
        page.locator(".confirm-dialog .primary-button").click()
        page.wait_for_selector(".global-notification:not(:empty)", timeout=5000)

        expect(page.locator(".global-notification")).to_contain_text("批量保存确认完成")
        first_card = page.locator(".batch-draft-card", has_text="萌王S4")
        second_card = page.locator(".batch-draft-card", has_text="路哥S4")
        expect(first_card.locator(".batch-card-status")).to_contain_text("已确认待提交")
        expect(second_card.locator(".batch-card-status")).to_contain_text("草案")

        payload = accept_calls[-1]
        assert payload["item_ids"] == ["item-1"]
        assert [item["item_id"] for item in payload["items"]] == ["item-1"]
        assert payload["items"][0]["draft_id"]
        assert payload["storage_dir"] is None

    def test_save_confirm_sends_only_the_checked_eligible_set(
        self, page: Page, live_server_url: str
    ) -> None:
        """AC (#145)：唯一入口只保存「当前可确认的勾选集合」，失败项不进入请求。"""
        accept_calls: list[dict[str, Any]] = []
        def _accept(route: Any, request: Any) -> None:
            accept_calls.append(json.loads(request.post_data or "{}"))
            _accept_route_handler({"item-1"})(route, request)

        page.route("**/api/v1/batches/batch-spa/save-confirm*", _accept)
        page.route(
            "**/api/v1/batches/parse",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(
                    [
                        _batch_item("item-1", "萌王S4", status="DRAFT", canonical_title="关于我转生变成史莱姆这档事 第四季", preview_request=_preview_request("咒术回战", "req-ok")),
                        _batch_item("item-fail", "路哥S4", status="FAILED"),
                    ]
                ),
            ),
        )
        _goto_batch(page, live_server_url)
        page.fill("#batch-raw-input", "萌王S4\n路哥S4")
        page.click("#batch-parse-submit")

        # 搜索失败项不可确认，因此「全选当前可见可确认项」只勾到成功项。
        page.check("#batch-select-all-checkbox")
        expect(page.locator("#batch-accept-submit")).to_contain_text("保存并确认 1 部")
        page.click("#batch-accept-submit")
        page.wait_for_selector(".confirm-dialog", timeout=5000)
        page.locator(".confirm-dialog .primary-button").click()
        page.wait_for_selector(".global-notification:not(:empty)", timeout=5000)

        ok_card = page.locator(".batch-draft-card", has_text="萌王S4")
        fail_card = page.locator(".batch-draft-card", has_text="路哥S4")
        expect(ok_card.locator(".batch-card-status")).to_contain_text("已确认待提交")
        expect(fail_card.locator(".batch-card-status")).to_contain_text("搜索失败")
        expect(page.locator(".global-notification")).to_contain_text("批量保存确认完成")

        payload = accept_calls[-1]
        assert payload["item_ids"] == ["item-1"]
        assert [item["item_id"] for item in payload["items"]] == ["item-1"]

    def test_accept_all_selects_all_reviewable_and_unchecks_single(
        self, page: Page, live_server_url: str
    ) -> None:
        page.route(
            "**/api/v1/batches/parse",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(
                    [
                        _batch_item("item-1", "萌王S4", status="DRAFT", canonical_title="a", preview_request=_preview_request("咒术回战", "req-sel-1")),
                        _batch_item("item-2", "路哥S4", status="DRAFT", canonical_title="b", preview_request=_preview_request("咒术回战", "req-sel-2")),
                        _batch_item("item-3", "邻家天使S2", status="FAILED"),
                    ]
                ),
            ),
        )
        _goto_batch(page, live_server_url)
        page.fill("#batch-raw-input", "萌王S4\n路哥S4\n邻家天使S2")
        page.click("#batch-parse-submit")

        expect(page.locator(".batch-card-checkbox-row")).to_have_count(3)
        page.check("#batch-select-all-checkbox")
        expect(page.locator("#batch-accept-selected-count")).to_contain_text("已选 2 部")

        page.uncheck("#batch-select-all-checkbox")
        expect(page.locator("#batch-accept-selected-count")).to_contain_text("已选 0 部")

        page.check("#batch-select-all-checkbox")
        first_card = page.locator(".batch-draft-card", has_text="萌王S4")
        first_card.locator(".batch-card-checkbox-row").uncheck()
        expect(page.locator("#batch-accept-selected-count")).to_contain_text("已选 1 部")
        expect(page.locator("#batch-select-all-checkbox")).not_to_be_checked()

    def test_checked_hidden_items_still_travel_with_a_same_source_safety_list(
        self, page: Page, live_server_url: str
    ) -> None:
        """AC (D-02/#145)：筛选隐藏的手工勾选仍参与保存；数量、清单、描述符与 item_ids 同源。"""
        accept_calls: list[dict[str, Any]] = []

        def _accept(route: Any, request: Any) -> None:
            accept_calls.append(json.loads(request.post_data or "{}"))
            _accept_route_handler({"item-a", "item-b"})(route, request)

        hidden = _batch_item("item-a", "甲S1", status="DRAFT", canonical_title="甲 第一季", preview_request=_preview_request("咒术回战", "req-hidden-a"))
        # 被筛选隐藏的条目也要带上真实敏感 canary：它进入客户端内存后，
        # 保存请求的 body 仍只能包含生成的能力描述符。
        hidden["error"] = {"token": "stage43-hidden-token", "raw_html": "<html>stage43 hidden</html>"}
        page.route("**/api/v1/batches/batch-spa/save-confirm*", _accept)
        page.route(
            "**/api/v1/batches/parse",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(
                    [
                        hidden,
                        _batch_item("item-b", "乙S1", status="DRAFT", canonical_title="乙 第一季", preview_request=_preview_request("咒术回战", "req-visible-b")),
                        _batch_item("item-c", "丙S1", status="DRAFT", canonical_title="丙 第一季", preview_request=_preview_request_without_resources("咒术回战", "req-no-resources")),
                    ]
                ),
            ),
        )
        _goto_batch(page, live_server_url)
        page.fill("#batch-raw-input", "甲S1\n乙S1\n丙S1")
        page.click("#batch-parse-submit")
        expect(page.locator(".batch-draft-card")).to_have_count(3)

        # 明确勾选甲/乙，再把甲筛掉：隐藏的勾选仍是保存范围的一部分。
        _select_cards(page, ["item-a", "item-b"])
        _fill_title_search(page, "乙")
        expect(page.locator(".batch-draft-card")).to_have_count(1)

        counts = page.locator("#batch-accept-selected-count")
        expect(counts).to_contain_text("已选 2 部")
        expect(counts).to_contain_text("当前可见 1 部（隐藏仍参与）")
        expect(page.locator("#batch-accept-submit")).to_be_enabled()
        expect(page.locator("#batch-accept-submit")).to_contain_text("保存并确认 2 部")
        expect(counts).to_contain_text("当前可见 1 部（隐藏仍参与）")
        # #145：底栏只有一行，不再有独立范围段落。
        expect(page.locator("#batch-accept-selected-scope")).to_have_count(0)

        page.click("#batch-accept-submit")
        page.wait_for_selector(".confirm-dialog", timeout=5000)
        dialog = page.locator(".confirm-dialog")
        expect(dialog.locator(".confirm-dialog-title")).to_have_text("保存并确认 2 部")
        expect(dialog.locator(".confirm-dialog-message")).to_contain_text("完整批次 3 部中已勾选且当前可确认的 2 部")
        expect(dialog.locator(".confirm-dialog-message")).to_contain_text("其中 1 部被筛选隐藏，仍会一并保存并确认")
        page.locator(".confirm-dialog .primary-button").click()
        page.wait_for_selector(".global-notification:not(:empty)", timeout=5000)

        payload = accept_calls[-1]
        assert payload["item_ids"] == ["item-a", "item-b"]
        assert [item["item_id"] for item in payload["items"]] == ["item-a", "item-b"]
        assert all(item["draft_id"] for item in payload["items"])
        assert all(item["base_revision"] == 1 for item in payload["items"])
        assert payload["storage_dir"] is None
        # 只发送生成的能力描述符，不带完整 Request 或额外字段。
        assert set(payload) == {"items", "storage_dir", "item_ids"}
        assert all(
            set(item) == {"item_id", "draft_id", "base_revision", "idempotency_key"}
            for item in payload["items"]
        )
        serialized = json.dumps(payload)
        assert "stage43-hidden-token" not in serialized
        assert "stage43 hidden" not in serialized

    def test_checked_scope_stays_available_when_the_filter_hides_every_item(
        self, page: Page, live_server_url: str
    ) -> None:
        """AC (D-02/#145)：可见零项但已勾选条目有资格时，唯一入口仍可用并覆盖完整勾选集合。"""
        accept_calls: list[dict[str, Any]] = []

        def _accept(route: Any, request: Any) -> None:
            accept_calls.append(json.loads(request.post_data or "{}"))
            _accept_route_handler({"item-a", "item-b"})(route, request)

        page.route("**/api/v1/batches/batch-spa/save-confirm*", _accept)
        page.route(
            "**/api/v1/batches/parse",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(
                    [
                        _batch_item("item-a", "甲S1", status="DRAFT", canonical_title="甲 第一季", preview_request=_preview_request("咒术回战", "req-zero-a")),
                        _batch_item("item-b", "乙S1", status="DRAFT", canonical_title="乙 第一季", preview_request=_preview_request("咒术回战", "req-zero-b")),
                    ]
                ),
            ),
        )
        _goto_batch(page, live_server_url)
        page.fill("#batch-raw-input", "甲S1\n乙S1")
        page.click("#batch-parse-submit")
        expect(page.locator(".batch-draft-card")).to_have_count(2)

        _select_cards(page, ["item-a", "item-b"])
        _fill_title_search(page, "没有这个标题")
        expect(page.locator(".batch-draft-card")).to_have_count(0)
        # 可见项为空只影响浏览：全选没有可见项可操作，已勾选范围不因此失去资格。
        expect(page.locator("#batch-select-all-checkbox")).to_be_disabled()
        expect(page.locator("#batch-accept-submit")).to_be_enabled()
        expect(page.locator("#batch-accept-selected-count")).to_contain_text("已选 2 部")
        expect(page.locator("#batch-accept-selected-count")).to_contain_text("当前可见 0 部（隐藏仍参与）")

        page.click("#batch-accept-submit")
        page.wait_for_selector(".confirm-dialog", timeout=5000)
        expect(page.locator(".confirm-dialog-title")).to_have_text("保存并确认 2 部")
        page.locator(".confirm-dialog .primary-button").click()
        page.wait_for_selector(".global-notification:not(:empty)", timeout=5000)

        payload = accept_calls[-1]
        assert payload["item_ids"] == ["item-a", "item-b"]
        assert [item["item_id"] for item in payload["items"]] == ["item-a", "item-b"]

    def test_save_entry_is_disabled_when_nothing_can_be_confirmed(
        self, page: Page, live_server_url: str
    ) -> None:
        """AC (#145)：没有可确认条目时唯一入口禁用，阻断原因在卡片上就地可见。"""
        accept_calls: list[dict[str, Any]] = []

        def _accept(route: Any, request: Any) -> None:
            accept_calls.append(json.loads(request.post_data or "{}"))
            _accept_route_handler(set())(route, request)

        page.route("**/api/v1/batches/batch-spa/save-confirm*", _accept)
        page.route(
            "**/api/v1/batches/parse",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(
                    [
                        _batch_item("item-a", "甲S1", status="DRAFT", canonical_title="甲 第一季", preview_request=_preview_request_without_resources("咒术回战", "req-nr-a")),
                        _batch_item("item-b", "乙S1", status="DRAFT", canonical_title="乙 第一季", preview_request=_preview_request_without_resources("咒术回战", "req-nr-b")),
                    ]
                ),
            ),
        )
        _goto_batch(page, live_server_url)
        page.fill("#batch-raw-input", "甲S1\n乙S1")
        page.click("#batch-parse-submit")
        expect(page.locator(".batch-draft-card")).to_have_count(2)

        submit = page.locator("#batch-accept-submit")
        expect(submit).to_be_disabled()
        expect(submit).to_contain_text("保存并确认 0 部")
        expect(page.locator("#batch-accept-selected-count")).to_contain_text("已选 0 部")
        # 没有可勾选条目：可见全选不可用；静止态不输出伪造的禁用长句。
        expect(page.locator("#batch-select-all-checkbox")).to_be_disabled()
        expect(page.locator("#batch-accept-selected-scope")).to_have_count(0)
        assert submit.get_attribute("title") is None
        # 排除口径与原资格门一致：没有有效资源的草案仍给出就地原因。
        expect(
            page.locator(".batch-draft-card").first.locator(".batch-card-selection-help")
        ).to_contain_text("没有有效资源")
        assert accept_calls == []

    @pytest.mark.parametrize(
        "width,height,zoom",
        [(1280, 720, 1), (1440, 900, 1), (1920, 1080, 1), (1280, 720, 2)],
    )
    def test_save_scope_copy_is_reachable_at_desktop_sizes(
        self, page: Page, live_server_url: str, width: int, height: int, zoom: int
    ) -> None:
        """AC (#145)：三档桌面与 200% 缩放下唯一入口的范围文案可达、不裁切、无横向溢出。"""
        page.route(
            "**/api/v1/batches/parse",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(
                    [
                        _batch_item("item-a", "甲S1", status="DRAFT", canonical_title="甲 第一季", preview_request=_preview_request("咒术回战", "req-size-a")),
                        _batch_item("item-b", "乙S1", status="DRAFT", canonical_title="乙 第一季", preview_request=_preview_request("咒术回战", "req-size-b")),
                    ]
                ),
            ),
        )
        _goto_batch(page, live_server_url)
        page.set_viewport_size({"width": width, "height": height})
        page.fill("#batch-raw-input", "甲S1\n乙S1")
        page.click("#batch-parse-submit")
        expect(page.locator(".batch-draft-card")).to_have_count(2)
        if zoom == 2:
            page.evaluate("() => { document.documentElement.style.zoom = '2' }")
        _select_cards(page, ["item-a"])
        # 正常态：精简计数常驻可见，主入口可达并把它作为可访问描述。
        counts = page.locator("#batch-accept-selected-count")
        counts.scroll_into_view_if_needed()
        expect(counts).to_be_visible()
        expect(counts).to_contain_text("已选 1 部")
        expect(page.locator("#batch-accept-submit")).to_contain_text("保存并确认 1 部")
        page.locator("#batch-accept-submit").focus()
        assert page.locator("#batch-accept-submit").get_attribute("aria-describedby") == "batch-accept-selected-count"
        # 勾选被筛选隐藏时，同一行的计数芯片说明「隐藏仍参与」，底栏不新增第二行。
        _fill_title_search(page, "乙")
        expect(counts).to_contain_text("当前可见 0 部（隐藏仍参与）")
        assert page.locator("#batch-accept-submit").get_attribute("aria-describedby") == "batch-accept-selected-count"
        expect(page.locator("#batch-accept-selected-scope")).to_have_count(0)
        assert page.evaluate("() => document.body.scrollWidth <= window.innerWidth")

    def test_cancel_sends_nothing_and_keeps_the_scene(
        self, page: Page, live_server_url: str
    ) -> None:
        """AC (#145)：取消不发请求、不改变勾选与详情；弹窗不展示草案能力。"""
        accept_calls: list[dict[str, Any]] = []
        preview_a = _preview_request("咒术回战", "req-cancel-a")
        draft_a = issue_draft_id(preview_a)

        def _accept(route: Any, request: Any) -> None:
            accept_calls.append(json.loads(request.post_data or "{}"))
            _accept_route_handler({"item-a", "item-b"})(route, request)

        page.route("**/api/v1/batches/batch-spa/save-confirm*", _accept)
        page.route(
            "**/api/v1/batches/parse",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(
                    [
                        _batch_item("item-a", "甲S1", status="DRAFT", canonical_title="甲 第一季", preview_request=preview_a),
                        _batch_item("item-b", "乙S1", status="DRAFT", canonical_title="乙 第一季", preview_request=_preview_request("咒术回战", "req-cancel-b")),
                    ]
                ),
            ),
        )
        _goto_batch(page, live_server_url)
        page.fill("#batch-raw-input", "甲S1\n乙S1")
        page.click("#batch-parse-submit")
        expect(page.locator(".batch-draft-card")).to_have_count(2)

        first = page.locator(".batch-draft-card", has_text="甲S1")
        _select_cards(page, ["item-a"])
        page.click("#batch-accept-submit")
        page.wait_for_selector(".confirm-dialog", timeout=5000)
        expect(page.locator(".confirm-dialog-title")).to_have_text("保存并确认 1 部")
        expect(page.locator(".confirm-dialog-message")).to_contain_text("仅保存本地订阅方案")
        expect(page.locator(".confirm-dialog-message")).to_contain_text("外部提交需在我的追番再次确认")
        # 草案能力只在内存 intent 里：弹窗文案、URL 与浏览器存储都不含它。
        dialog_text = page.locator(".confirm-dialog").inner_text()
        assert draft_a not in dialog_text
        assert draft_a not in page.url
        assert draft_a not in page.evaluate("() => JSON.stringify(window.localStorage)")

        page.locator(".confirm-dialog .secondary-button").click()

        expect(page.locator(".confirm-dialog")).to_have_count(0)
        expect(page.locator("#batch-accept-selected-recheck")).to_have_count(0)
        assert accept_calls == []
        expect(first.locator(".batch-card-checkbox-row")).to_be_checked()
        expect(page.locator(".batch-draft-card")).to_have_count(2)
        expect(page.locator("#batch-accept-submit")).to_contain_text("保存并确认 1 部")
        # 取消后焦点回到原触发入口。
        assert page.evaluate("() => document.activeElement ? document.activeElement.id : ''") == "batch-accept-submit"

    def test_accept_failure_preserves_cards_with_safe_error(
        self, page: Page, live_server_url: str
    ) -> None:
        def _fail(route: Any, request: Any) -> None:
            route.fulfill(
                status=400,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": False,
                        "error_message": "批量接受失败：服务器内部错误",
                        "error_type": "batch_accept_failed",
                    },
                    ensure_ascii=False,
                ),
            )

        page.route("**/api/v1/batches/batch-spa/save-confirm*", _fail)
        self._setup_two_drafts(page, live_server_url)

        _select_cards(page, ["item-1"])
        page.click("#batch-accept-submit")
        page.wait_for_selector(".confirm-dialog", timeout=5000)
        page.locator(".confirm-dialog .primary-button").click()
        page.wait_for_selector(".global-notification:not(:empty)", timeout=5000)

        expect(page.locator(".global-notification")).to_contain_text("保存确认失败")
        # Cards stay reviewable after a failed accept.
        expect(page.locator(".batch-draft-card", has_text="萌王S4").locator(".batch-card-status")).to_contain_text("草案")
        # The raw error_type never reaches the DOM.
        body_text = page.locator("body").inner_text()
        assert "batch_accept_failed" not in body_text
        assert "服务器内部错误" not in body_text

    def test_saved_confirm_recovery_uses_accept_and_tracking_only(self, page: Page, live_server_url: str) -> None:
        batch_calls: list[dict[str, Any]] = []
        accept_calls: list[dict[str, Any]] = []
        accept_urls: list[str] = []
        tracking_calls: list[str] = []
        preview = _preview_request("萌王S4", "req-saved")
        page.route(
            "**/api/v1/batches/parse",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result([_batch_item("item-saved", "萌王S4", status="DRAFT", preview_request=preview)]),
            ),
        )

        def save_confirm(route: Any, request: Any) -> None:
            batch_calls.append(json.loads(request.post_data or "{}"))
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_accept_result([{
                    "item_id": "item-saved",
                    "outcome": "failed",
                    "request_id": "req-saved",
                    "status": None,
                    "error_type": "save_confirm_failed",
                    "tracking_id": None,
                    "tracking_ready": None,
                }], []),
            )

        def accept(route: Any, request: Any) -> None:
            accept_calls.append(json.loads(request.post_data or "{}"))
            accept_urls.append(request.url)
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "result": {"request": {"request_id": "req-saved"}}}))

        def tracking(route: Any, request: Any) -> None:
            tracking_calls.append(request.url)
            route.fulfill(status=200, content_type="application/json", body=json.dumps({
                "ok": True,
                "result": {"items": [{"request_id": "req-saved", "tracking_id": "tracking-real"}], "summary": {}},
            }))

        page.route("**/api/v1/batches/batch-spa/save-confirm*", save_confirm)
        page.route("**/api/v1/requests/req-saved/accept", accept)
        page.route("**/api/v1/tracking/items*", tracking)
        _goto_batch(page, live_server_url)
        page.fill("#batch-raw-input", "萌王S4")
        page.click("#batch-parse-submit")
        card = page.locator(".batch-draft-card", has_text="萌王S4")
        card.locator(".batch-card-checkbox-row").check()
        page.click("#batch-accept-submit")
        page.locator(".confirm-dialog .primary-button").click()
        expect(card.locator("#batch-retry-accept-item-saved")).to_be_visible()
        page.click("#batch-retry-accept-item-saved")
        expect(card.locator(".batch-card-status")).to_contain_text("已确认待提交")
        expect(card.locator("#batch-open-tracking-item-saved")).to_be_visible()

        assert len(batch_calls) == 1
        assert len(accept_calls) == 1
        assert "/api/v1/requests/req-saved/accept" in accept_urls[0]
        # Initial page hydration and the post-recovery tracking refresh are
        # both read-only calls; neither is a retired queue write.
        assert len(tracking_calls) == 2
        assert "retry_action" not in json.dumps(batch_calls[0])


class TestAppBatchSensitiveBoundary:
    """AC: 批量解析/候选/接受全程不泄漏敏感值."""

    def test_search_results_do_not_persist_or_render_sensitive_values(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        sensitive_values = (
            "https://private-mikan.stage22.local/failed?token=stage22-token",
            "stage22-token",
            "stage22-cookie",
            "Bearer stage22-authorization",
            "<html>stage22 raw html</html>",
            "<rss>stage22 raw rss</rss>",
            "magnet:?xt=urn:btih:stage22-secret",
            "stage22 raw response body",
        )
        item = _batch_item(
            "item-public",
            "萌王S4",
            status="DRAFT",
            canonical_title="史莱姆 第四季",
            preview_request=_preview_request("咒术回战", "req-batch-sec"),
        )
        item["error"] = {
            "failed_url": sensitive_values[0],
            "token": sensitive_values[1],
            "cookie": sensitive_values[2],
            "authorization": sensitive_values[3],
            "raw_html": sensitive_values[4],
            "raw_rss_xml": sensitive_values[5],
            "magnet": sensitive_values[6],
            "raw_response_body": sensitive_values[7],
            "local_path": str(storage_dir),
        }
        item["candidates"] = [
            {
                **_candidate(bangumi_id="42", title="史莱姆 第四季", mikan_url="https://mikan.example/Home/Bangumi/42"),
                **item["error"],
            }
        ]

        def _fulfill(route: Any, request: Any) -> None:
            route.fulfill(status=200, content_type="application/json", body=_batch_parse_result([item]))

        page.route("**/api/v1/batches/parse", _fulfill)
        set_storage_preferences(page, storage_dir)
        _goto_batch(page, live_server_url)
        page.fill("#batch-raw-input", "萌王S4")
        page.click("#batch-parse-submit")
        expect(page.locator(".batch-draft-card")).to_have_count(1)
        # US-355: 按需展开的辅助信息层同样不得泄漏敏感值。
        page.locator(".batch-draft-card .batch-card-more summary").first.click()
        expect(page.locator(".batch-draft-card .batch-card-facts")).to_be_visible()

        browser_state = page.evaluate(
            """() => ({
                url: window.location.href,
                localStorage: JSON.stringify(window.localStorage),
                sessionStorage: JSON.stringify(window.sessionStorage),
                bodyText: document.body.innerText,
            })"""
        )
        persisted_json = "\n".join(
            path.read_text(encoding="utf-8")
            for path in storage_dir.rglob("*.json")
        ) if storage_dir.exists() else ""
        for value in sensitive_values:
            assert value not in browser_state["url"]
            assert value not in browser_state["localStorage"]
            assert value not in browser_state["sessionStorage"]
            assert value not in browser_state["bodyText"]
            assert value not in persisted_json


def _compact_items(count: int, *, prefix: str = "番剧") -> list[dict[str, Any]]:
    """US-355 fixture: a continuous list of ordinary short-title draft cards."""
    return [
        _batch_item(
            f"item-{index:02d}",
            f"{prefix}{index:02d}",
            status="DRAFT",
            canonical_title=f"{prefix}{index:02d} 第 1 季",
            preview_request=_preview_request(f"{prefix}{index:02d}", f"req-compact-{index:02d}"),
        )
        for index in range(count)
    ]


def _route_parse(page: Page, items: list[dict[str, Any]]) -> None:
    page.route(
        "**/api/v1/batches/parse",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=_batch_parse_result(items),
        ),
    )


def _open_compact_list(page: Page, live_server_url: str, items: list[dict[str, Any]]) -> None:
    _route_parse(page, items)
    _goto_batch(page, live_server_url)
    # #143：左栏列表可视区现在是「一屏减去标题、筛选与操作栏」的剩余高度，
    # 因此紧凑列表用例固定在 1440×900 验收画布上测量。
    page.set_viewport_size({"width": 1440, "height": 900})
    page.fill("#batch-raw-input", "\n".join(str(item["raw_title"]) for item in items))
    page.click("#batch-parse-submit")
    expect(page.locator(".batch-draft-card")).to_have_count(len(items))
    # 整批完成会自动把文档滚到工作台顶部；视图几何必须在滚动稳定后测量。
    wait_for_screen_scroll(page)


def _cards_fully_inside_list(page: Page) -> list[str]:
    """data-item-id of every card wholly inside the list scroll viewport."""
    return page.evaluate(
        """() => {
            const wrapper = document.querySelector('.batch-card-grid-wrapper')
            if (!wrapper) return []
            const box = wrapper.getBoundingClientRect()
            return Array.from(document.querySelectorAll('.batch-draft-card'))
                .filter((card) => {
                    const rect = card.getBoundingClientRect()
                    return rect.top >= box.top - 0.5 && rect.bottom <= box.bottom + 0.5
                })
                .map((card) => card.dataset.itemId)
        }"""
    )


def _active_item_id(page: Page) -> str | None:
    return page.evaluate("() => document.activeElement && document.activeElement.dataset.itemId")


class TestAppBatchCompactList:
    """AC (US-355)：默认左卡只回答「标题 / 中文状态 / 阻断或错误 / 下一步」，
    别名与偏好按需展开；1/12/36 连续列表不引入分页或虚拟滚动；查看与勾选分离；
    键盘、焦点、长内容、缩放、reduced-motion 与敏感 canary 都必须在真实 Chromium 通过。"""

    def test_default_layer_shows_title_status_and_only_stuck_guidance(
        self, page: Page, live_server_url: str
    ) -> None:
        items = [
            _batch_item(
                "item-draft",
                "甲S1",
                status="DRAFT",
                canonical_title="甲 第一季",
                preview_request=_preview_request("咒术回战", "req-layer-a"),
            ),
            _batch_item(
                "item-found",
                "乙S1",
                status="FOUND",
                canonical_title="乙 第一季",
                candidates=[_candidate(bangumi_id="42", title="乙 第一季", mikan_url="https://mikan.example/Home/Bangumi/42")],
            ),
            _batch_item(
                "item-failed",
                "丙S1",
                status="FAILED",
                error={"error_type": "mikan_unavailable", "error_message": "raw upstream canary"},
            ),
        ]
        _open_compact_list(page, live_server_url, items)

        draft = page.locator('.batch-draft-card[data-item-id="item-draft"]')
        expect(draft.locator(".batch-card-title")).to_have_text("甲 第一季")
        expect(draft.locator(".batch-card-status")).to_have_text("草案")
        # #145：可确认的草案卡默认层只有封面、标题、状态与勾选，没有通用下一步；
        # 输入原文与有效种子数移到按需展开的辅助信息里。
        expect(draft.locator(".batch-card-next-step")).to_have_count(0)
        expect(draft).not_to_contain_text("输入：")
        # 辅助信息默认折叠，但仍在按需层里可读。
        expect(draft.locator(".batch-card-facts")).not_to_be_visible()
        expect(draft.locator(".batch-card-facts")).to_contain_text("偏好")
        expect(draft.locator(".batch-card-more summary")).to_be_visible()

        # 待选合集不可勾选；进度由状态芯片与右栏候选列表表达，卡片不再重复说明。
        found = page.locator('.batch-draft-card[data-item-id="item-found"]')
        expect(found.locator(".batch-card-status")).to_have_text("找到候选")
        expect(found.locator(".batch-card-checkbox-row")).to_be_disabled()
        expect(found.locator(".batch-card-selection-help")).to_have_count(0)
        expect(found.locator(".batch-card-next-step")).to_have_count(0)

        # 失败信息与它的下一步都在默认层，不进入折叠。
        failed = page.locator('.batch-draft-card[data-item-id="item-failed"]')
        expect(failed.locator(".batch-candidate-feedback")).to_be_visible()
        expect(failed.locator(".batch-candidate-feedback")).to_contain_text("该条目候选搜索失败")
        expect(failed.locator(".batch-card-next-step")).to_contain_text("删除该条目")
        assert "raw upstream canary" not in page.locator("body").inner_text()

    def test_auxiliary_layer_opens_on_demand_without_leaking(
        self, page: Page, live_server_url: str
    ) -> None:
        item = _batch_item(
            "item-facts",
            "萌王S4",
            status="DRAFT",
            canonical_title="关于我转生变成史莱姆这档事 第四季",
            season_hint="S4",
            search_queries=["转生史莱姆 第四季"],
            preview_request=_preview_request("咒术回战", "req-facts-b"),
        )
        item["canonical_title_candidates"] = ["关于我转生变成史莱姆这档事 第四季", "转生史莱姆 第四季"]
        _open_compact_list(page, live_server_url, [item])

        card = page.locator('.batch-draft-card[data-item-id="item-facts"]')
        summary = card.locator(".batch-card-more summary")
        expect(summary).to_have_text("辅助信息")
        summary.click()
        facts = card.locator(".batch-card-facts")
        expect(facts).to_be_visible()
        expect(facts).to_contain_text("别名")
        expect(facts).to_contain_text("转生史莱姆 第四季")
        expect(facts).to_contain_text("检索关键词")
        expect(facts).to_contain_text("季数提示")
        expect(facts).to_contain_text("偏好")
        expect(facts).to_contain_text("总集数")

    @pytest.mark.parametrize("count", [1, 12, 36])
    def test_continuous_lists_render_without_pagination(
        self, page: Page, live_server_url: str, count: int
    ) -> None:
        items = _compact_items(count)
        _open_compact_list(page, live_server_url, items)

        # 全部条目同时存在于 DOM：没有分页，也没有默认虚拟滚动。
        expect(page.locator(".batch-draft-card")).to_have_count(count)
        assert page.locator(".batch-pagination, .virtual-list, nav[aria-label*='分页']").count() == 0
        # 可确认的草案卡默认层不再有通用下一步：卡片数量由卡片本体证明。
        expect(page.locator(".batch-card-next-step")).to_have_count(0)
        page.locator(".batch-draft-card").last.scroll_into_view_if_needed()
        expect(page.locator(".batch-draft-card").last).to_be_visible()
        assert page.evaluate("() => document.body.scrollWidth <= window.innerWidth")

    def test_compact_list_viewport_stays_readable_in_the_fixed_one_screen_workbench(
        self, page: Page, live_server_url: str
    ) -> None:
        """#143：批量工作台固定为一屏，顶部标题与底部操作栏必须同屏可见，因此左栏列表
        可视区是「一屏减去标题、筛选与操作栏」后的剩余高度，不再是独立的 572px 列高。
        1440×900 下它至少完整显示一张批量条目卡，其余条目由列表自身内部滚动到达；
        每张卡仍完整、不被列表容器裁切。"""
        items = _compact_items(12)
        _route_parse(page, items)
        _goto_batch(page, live_server_url)
        page.set_viewport_size({"width": 1440, "height": 900})
        page.fill("#batch-raw-input", "\n".join(str(item["raw_title"]) for item in items))
        page.click("#batch-parse-submit")
        expect(page.locator(".batch-draft-card")).to_have_count(12)

        box = page.locator(".batch-card-grid-wrapper").bounding_box()
        assert box is not None
        fully = _cards_fully_inside_list(page)
        assert fully[:1] == ["item-00"], f"列表开头至少要有一张完整卡，实际完整卡 {fully}"
        first_height = page.evaluate(
            "() => document.querySelector('.batch-draft-card').getBoundingClientRect().height"
        )
        assert box["height"] >= first_height + 10, (box["height"], first_height)

        # 12 部都能通过列表内部滚动到达，末卡停在列表可视区底部之内。
        reachable = page.evaluate(
            """() => {
                const wrapper = document.querySelector('.batch-card-grid-wrapper')
                const cards = document.querySelectorAll('.batch-draft-card')
                const last = cards[cards.length - 1]
                wrapper.scrollTop = wrapper.scrollHeight
                const wrapperBox = wrapper.getBoundingClientRect()
                const lastBox = last.getBoundingClientRect()
                return {
                    lastFullyInside: lastBox.top >= wrapperBox.top - 0.5
                        && lastBox.bottom <= wrapperBox.bottom + 0.5,
                    scrolled: wrapper.scrollTop > 0,
                }
            }"""
        )
        assert reachable["scrolled"] is True
        assert reachable["lastFullyInside"] is True, reachable

    def test_two_hundred_percent_zoom_keeps_the_compact_list_operable(
        self, page: Page, live_server_url: str
    ) -> None:
        items = _compact_items(12)
        _route_parse(page, items)
        _goto_batch(page, live_server_url)
        page.set_viewport_size({"width": 1440, "height": 900})
        page.evaluate("() => { document.documentElement.style.zoom = '2' }")
        page.fill("#batch-raw-input", "\n".join(str(item["raw_title"]) for item in items))
        page.click("#batch-parse-submit")
        expect(page.locator(".batch-draft-card")).to_have_count(12)

        # 200% 缩放下空间不足：优先保证内容完整可读——列表仍有可用高度并可内部
        # 滚动到全部条目，固定操作栏与首卡的下一步都可见，且没有横向溢出。
        assert page.evaluate("() => document.body.scrollWidth <= window.innerWidth")
        list_state = page.evaluate(
            """() => {
                const wrapper = document.querySelector('.batch-card-grid-wrapper')
                const card = document.querySelector('.batch-draft-card')
                return {
                    listHeight: wrapper.getBoundingClientRect().height,
                    cardHeight: card.getBoundingClientRect().height,
                    scrollable: wrapper.scrollHeight > wrapper.clientHeight + 1,
                }
            }"""
        )
        assert list_state["listHeight"] > 0, list_state
        assert list_state["scrollable"] is True, list_state
        page.locator(".batch-draft-card").last.scroll_into_view_if_needed()
        expect(page.locator(".batch-draft-card").last).to_be_visible()
        expect(page.locator("#batch-accept-submit")).to_be_visible()
        expect(page.locator(".batch-draft-card").first.locator(".batch-card-title")).to_be_visible()

    def test_long_content_grows_the_card_without_clipping(
        self, page: Page, live_server_url: str
    ) -> None:
        long_hint = "该条目候选标题与输入差异较大，请在确认前核对季数与字幕组。" * 6
        long_title = "非常长的官方合集标题" * 6
        items = [
            _batch_item(
                "item-short",
                "短S1",
                status="DRAFT",
                canonical_title="短 第一季",
                preview_request=_preview_request("咒术回战", "req-short"),
            ),
            _batch_item(
                "item-long",
                "长S1",
                status="DRAFT",
                canonical_title=long_title,
                review_hints=[long_hint],
                preview_request=_preview_request("咒术回战", "req-long"),
            ),
        ]
        _open_compact_list(page, live_server_url, items)

        short_box = page.locator('.batch-draft-card[data-item-id="item-short"]').bounding_box()
        long_box = page.locator('.batch-draft-card[data-item-id="item-long"]').bounding_box()
        assert short_box is not None and long_box is not None
        assert long_box["height"] > short_box["height"], "长错误/长标题必须自然增高，而不是被裁切"

        clipped = page.evaluate(
            """() => {
                const card = document.querySelector('.batch-draft-card[data-item-id="item-long"]')
                const nodes = [card, ...card.querySelectorAll('p')]
                return nodes.some((node) => {
                    const style = getComputedStyle(node)
                    return node.scrollHeight > node.clientHeight + 1 ||
                        node.scrollWidth > node.clientWidth + 1 ||
                        style.textOverflow === 'ellipsis' ||
                        (style.webkitLineClamp && style.webkitLineClamp !== 'none')
                })
            }"""
        )
        assert clipped is False, "长内容不得被裁切、截断或省略"

    def test_keyboard_keeps_card_shortcuts_out_of_inner_forms(
        self, page: Page, live_server_url: str
    ) -> None:
        items = _compact_items(2, prefix="条目")
        _open_compact_list(page, live_server_url, items)
        cards = page.locator(".batch-draft-card")

        # 读屏可区分：卡片本身是「查看条目」，复选框是「选择 <条目>」。
        card_label = cards.nth(0).get_attribute("aria-label") or ""
        assert "查看条目" in card_label
        assert (cards.nth(0).locator(".checkbox-row-label").text_content() or "").strip() == "选择 条目00"
        assert "查看条目" in (cards.nth(0).get_attribute("aria-label") or "")

        # 卡片自身仍由方向键移动「当前查看」。
        cards.nth(1).click()
        expect(cards.nth(1)).to_have_class(re.compile(r"is-current"))
        cards.nth(1).focus()
        page.keyboard.press("ArrowUp")
        expect(cards.nth(0)).to_have_class(re.compile(r"is-current"))

        # #145：卡片不再内嵌快捷字幕组表单；字幕组只在右栏编辑。
        expect(cards.nth(1).locator(".batch-card-subtitle-group")).to_have_count(0)

        # 卡片内的复选框由它自己消费键盘，不再被卡片快捷键截获，
        # 并且勾选只改变待确认集合。
        checkbox = cards.nth(1).locator(".batch-card-checkbox-row")
        checkbox.focus()
        page.keyboard.press("Space")
        expect(cards.nth(1).locator(".batch-card-checkbox-row")).to_be_checked()
        expect(cards.nth(0)).to_have_class(re.compile(r"is-current"))
        expect(page.locator("#batch-accept-selected-count")).to_contain_text("已选 1 部")

    def test_focus_ring_is_not_clipped_inside_the_scrolling_list(
        self, page: Page, live_server_url: str
    ) -> None:
        items = _compact_items(12)
        page.set_viewport_size({"width": 1440, "height": 900})
        _open_compact_list(page, live_server_url, items)

        # 键盘模态下聚焦最后一张卡，并把列表滚到底：焦点环仍在滚动区内。
        page.keyboard.press("Tab")
        page.evaluate(
            """() => {
                const wrapper = document.querySelector('.batch-card-grid-wrapper')
                wrapper.scrollTop = wrapper.scrollHeight
                const cards = document.querySelectorAll('.batch-draft-card')
                cards[cards.length - 1].focus()
            }"""
        )
        ring = page.evaluate(
            """() => {
                const wrapper = document.querySelector('.batch-card-grid-wrapper')
                const card = document.activeElement
                const style = getComputedStyle(card)
                const width = parseFloat(style.outlineWidth) || 0
                const offset = parseFloat(style.outlineOffset) || 0
                const rect = card.getBoundingClientRect()
                const box = wrapper.getBoundingClientRect()
                return {
                    style: style.outlineStyle,
                    ring: {
                        top: rect.top - width - offset,
                        bottom: rect.bottom + width + offset,
                        left: rect.left - width - offset,
                        right: rect.right + width + offset,
                    },
                    box: { top: box.top, bottom: box.bottom, left: box.left, right: box.right },
                    itemId: card.dataset.itemId,
                }
            }"""
        )
        assert ring["itemId"] == "item-11"
        assert ring["style"] != "none", "键盘聚焦的卡片必须有可见焦点环"
        assert ring["ring"]["top"] >= ring["box"]["top"] - 0.5, ring
        assert ring["ring"]["bottom"] <= ring["box"]["bottom"] + 0.5, ring
        assert ring["ring"]["left"] >= ring["box"]["left"] - 0.5, ring
        assert ring["ring"]["right"] <= ring["box"]["right"] + 0.5, ring

    def test_deleting_a_card_keeps_focus_in_the_list(
        self, page: Page, live_server_url: str
    ) -> None:
        items = _compact_items(3)
        _open_compact_list(page, live_server_url, items)
        cards = page.locator(".batch-draft-card")

        cards.nth(1).locator(".batch-card-delete").click()
        expect(cards).to_have_count(2)
        assert _active_item_id(page) == "item-02", "删除后焦点应落到下一项"

        cards.nth(1).locator(".batch-card-delete").click()
        expect(cards).to_have_count(1)
        assert _active_item_id(page) == "item-00", "末尾删除后焦点应落到上一项"

        cards.nth(0).locator(".batch-card-delete").click()
        expect(cards).to_have_count(0)
        assert page.evaluate("() => document.activeElement && document.activeElement.id") == "panel-section-批量工作台"

    def test_next_exception_entry_is_removed_with_its_placeholder(
        self, page: Page, live_server_url: str
    ) -> None:
        """#158：删除「下一异常」入口及其专用占位；筛选隐藏的条目仍如实保留数据与详情。"""
        items = [
            _compact_items(1, prefix="正常")[0],
            _batch_item(
                "item-failed",
                "异常S1",
                status="FAILED",
                canonical_title="异常 第一季",
                error={"error_type": "mikan_unavailable", "error_message": "x"},
            ),
        ]
        _open_compact_list(page, live_server_url, items)

        page.locator('.batch-draft-card[data-item-id="item-00"]').click()
        expect(page.locator('.batch-draft-card[data-item-id="item-00"]')).to_have_class(
            re.compile(r"is-current")
        )
        _fill_title_search(page, "正常00")
        expect(page.locator(".batch-draft-card")).to_have_count(1)

        # 入口与「无异常时不可用」占位都不在真实 DOM 里，也没有预留空白。
        expect(page.locator("#batch-next-exception")).to_have_count(0)
        expect(page.locator("#batch-review-clear")).to_have_count(0)
        expect(page.locator(".batch-review-navigation")).not_to_contain_text("无异常时不可用")
        # 被筛选隐藏的失败条目仍留在完整批次里：删空搜索词即可恢复。
        page.fill("#batch-review-search", "")
        failed = page.locator('.batch-draft-card[data-item-id="item-failed"]')
        expect(failed).to_be_visible()

    def test_filter_without_match_is_never_an_empty_batch(
        self, page: Page, live_server_url: str
    ) -> None:
        items = _compact_items(2)
        _open_compact_list(page, live_server_url, items)

        page.locator(".batch-draft-card").nth(1).click()
        expect(page.locator("#batch-detail-pane")).to_contain_text("字幕与筛选")
        page.locator(".batch-draft-card").nth(0).locator(".batch-card-checkbox-row").check()
        _fill_title_search(page, "不存在的标题")

        expect(page.locator(".batch-draft-card")).to_have_count(0)
        no_match = page.locator("#batch-review-no-match")
        expect(no_match).to_be_visible()
        expect(no_match).to_contain_text("没有符合当前筛选条件")
        expect(no_match).to_contain_text("2 部")
        # 不能被当成空批次。
        expect(page.locator(".empty-state")).to_have_count(0)
        expect(page.locator(".batch-review-count")).to_contain_text("共 2 部，当前显示 0 部")
        # 右栏详情与勾选都还在；#158 之后由搜索控件自身恢复默认（删空关键词）。
        expect(page.locator("#batch-detail-pane")).to_contain_text("字幕与筛选")
        expect(page.locator(".batch-filter-hidden")).to_be_visible()
        search = page.locator("#batch-review-search")
        expect(search).to_be_visible()
        page.fill("#batch-review-search", "")

        expect(page.locator(".batch-draft-card")).to_have_count(2)
        expect(page.locator("#batch-review-no-match")).to_have_count(0)
        expect(page.locator(".batch-draft-card").nth(0).locator(".batch-card-checkbox-row")).to_be_checked()

    def test_order_changes_only_on_an_explicit_sort(
        self, page: Page, live_server_url: str
    ) -> None:
        items = [
            _batch_item(
                "item-found",
                "甲S1",
                status="FOUND",
                canonical_title="甲 第一季",
                candidates=[_candidate(bangumi_id="42", title="甲 第一季", mikan_url="https://mikan.example/Home/Bangumi/42")],
            ),
            _compact_items(1, prefix="乙")[0],
        ]
        _route_parse(page, items)
        page.route(
            "**/api/v1/requests",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": True,
                        "result": {
                            "request": _preview_request("咒术回战", "req-order-a"),
                            "draft_id": "draft-order-a",
                            "draft_revision": 1,
                            "summary": {},
                        },
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        _goto_batch(page, live_server_url)
        page.fill("#batch-raw-input", "甲S1\n乙S1")
        page.click("#batch-parse-submit")
        expect(page.locator(".batch-draft-card")).to_have_count(2)
        order = lambda: page.locator(".batch-draft-card").evaluate_all(  # noqa: E731
            "cards => cards.map((card) => card.dataset.itemId)"
        )
        assert order() == ["item-found", "item-00"]

        # 生成草案属于「修复」，它不自动跳位。
        page.locator('.batch-draft-card[data-item-id="item-found"]').click()
        page.locator("#batch-detail-pane .candidate-select").click()
        expect(page.locator('.batch-draft-card[data-item-id="item-found"] .batch-card-status')).to_contain_text("草案")
        assert order() == ["item-found", "item-00"]
        # #149：不再提供二次排序入口，条目顺序在解析后固定，修复不跳位。
        expect(page.locator("#batch-review-sort-exceptions")).to_have_count(0)
        expect(page.locator(".batch-review-count")).to_contain_text("共 2 部，当前显示 2 部")

    def test_reduced_motion_keeps_the_list_navigable(
        self, page: Page, live_server_url: str
    ) -> None:
        page.emulate_media(reduced_motion="reduce")
        items = _compact_items(6)
        _open_compact_list(page, live_server_url, items)

        expect(page.locator(".batch-draft-card").first).to_have_css("scroll-behavior", "auto")
        cards = page.locator(".batch-draft-card")
        cards.nth(0).focus()
        page.keyboard.press("ArrowDown")
        expect(cards.nth(1)).to_have_class(re.compile(r"\bis-current\b"))
        expect(cards.nth(1)).to_have_class(re.compile(r"is-current"))


def _confirm_scope_items() -> list[dict[str, Any]]:
    """US-356 fixture: three independent, confirmable draft cards."""
    return [
        _batch_item("item-a", "甲S1", status="DRAFT", canonical_title="甲 第一季", preview_request=_preview_request("咒术回战", "req-scope-a")),
        _batch_item("item-b", "乙S1", status="DRAFT", canonical_title="乙 第一季", preview_request=_preview_request("咒术回战", "req-scope-b")),
        _batch_item("item-c", "丙S1", status="DRAFT", canonical_title="丙 第一季", preview_request=_preview_request("咒术回战", "req-scope-c")),
    ]


class TestAppBatchConfirmScope:
    """AC (US-356)：N 部（完整批次中手工勾选且当前可确认）与确认全部（完整批次资格）
    是两个明确的范围；两入口的数量、安全标题清单、描述符与 item_ids 同源；弹窗打开后
    任何资格/版本/批次变化都零请求并要求重新确认；固定栏按真实多行高度预留空间，
    禁用原因常驻可见。"""

    def _open(self, page: Page, live_server_url: str, items: list[dict[str, Any]], raw: str) -> None:
        _route_parse(page, items)
        _goto_batch(page, live_server_url)
        page.fill("#batch-raw-input", raw)
        page.click("#batch-parse-submit")
        expect(page.locator(".batch-draft-card")).to_have_count(len(items))

    def _check(self, page: Page, item_id: str) -> None:
        page.locator(f'.batch-draft-card[data-item-id="{item_id}"] .batch-card-checkbox-row').check()

    def test_n_covers_filter_hidden_checked_items_with_a_same_source_safety_list(
        self, page: Page, live_server_url: str
    ) -> None:
        """AC (D-02)：筛选隐藏的手工勾选仍参与 N；弹窗的数量、清单、描述符与 item_ids 同源。"""
        accept_calls: list[dict[str, Any]] = []

        def _accept(route: Any, request: Any) -> None:
            accept_calls.append(json.loads(request.post_data or "{}"))
            _accept_route_handler({"item-a", "item-b"})(route, request)

        page.route("**/api/v1/batches/batch-spa/save-confirm*", _accept)
        items = _confirm_scope_items()
        # 被隐藏的条目携带真实敏感 canary：它进入内存后，扩大范围后的请求仍只能带描述符。
        items[0]["error"] = {"token": "stage45-hidden-token", "raw_html": "<html>stage45 hidden</html>"}
        self._open(page, live_server_url, items, "甲S1\n乙S1\n丙S1")

        self._check(page, "item-a")
        self._check(page, "item-b")
        _fill_title_search(page, "乙")
        expect(page.locator(".batch-draft-card")).to_have_count(1)

        counts = page.locator("#batch-accept-selected-count")
        expect(counts).to_contain_text("已选 2 部")
        expect(counts).to_contain_text("当前可见 1 部（隐藏仍参与）")
        expect(page.locator("#batch-accept-submit")).to_be_enabled()
        expect(page.locator("#batch-accept-submit")).to_contain_text("保存并确认 2 部")
        expect(page.locator("#batch-accept-selected-scope")).to_have_count(0)

        page.click("#batch-accept-submit")
        page.wait_for_selector(".confirm-dialog", timeout=5000)
        dialog = page.locator(".confirm-dialog")
        expect(dialog.locator(".confirm-dialog-title")).to_have_text("保存并确认 2 部")
        expect(dialog.locator(".confirm-dialog-message")).to_contain_text("完整批次 3 部中已勾选且当前可确认的 2 部")
        expect(dialog.locator(".confirm-dialog-message")).to_contain_text("其中 1 部被筛选隐藏，仍会一并保存并确认")
        expect(dialog.locator(".confirm-dialog-message")).to_contain_text("仅保存本地订阅方案")
        expect(dialog.locator(".confirm-dialog-message")).to_contain_text("外部提交需在我的追番再次确认")
        expect(dialog.locator(".confirm-dialog-items li")).to_have_count(2)
        assert dialog.locator(".confirm-dialog-items li").all_inner_texts() == ["甲 第一季", "乙 第一季"]
        # 草案能力只留在内存 intent 里，不进入弹窗。
        assert "draft" not in dialog.inner_text()

        dialog.locator(".primary-button").click()
        page.wait_for_selector(".global-notification:not(:empty)", timeout=5000)

        payload = accept_calls[-1]
        assert payload["item_ids"] == ["item-a", "item-b"]
        assert [item["item_id"] for item in payload["items"]] == ["item-a", "item-b"]
        assert set(payload) == {"items", "storage_dir", "item_ids"}
        assert all(
            set(item) == {"item_id", "draft_id", "base_revision", "idempotency_key"}
            for item in payload["items"]
        )
        serialized = json.dumps(payload)
        assert "stage45-hidden-token" not in serialized
        assert "stage45 hidden" not in serialized
        assert "stage45-hidden-token" not in page.locator("body").inner_text()

    def test_visible_select_all_only_changes_visible_items(
        self, page: Page, live_server_url: str
    ) -> None:
        """AC：全选当前可见可确认项只改可见项；N 仍按完整批次的手工勾选集合计数。"""
        _route_parse(page, _confirm_scope_items())
        _goto_batch(page, live_server_url)
        page.fill("#batch-raw-input", "甲S1\n乙S1\n丙S1")
        page.click("#batch-parse-submit")
        expect(page.locator(".batch-draft-card")).to_have_count(3)

        page.check("#batch-select-all-checkbox")
        expect(page.locator("#batch-accept-submit")).to_contain_text("保存并确认 3 部")
        _fill_title_search(page, "乙")
        expect(page.locator(".batch-draft-card")).to_have_count(1)
        # 可见只剩乙，但隐藏的勾选仍是 N 的一部分。
        expect(page.locator("#batch-accept-submit")).to_contain_text("保存并确认 3 部")
        expect(page.locator("#batch-accept-selected-count")).to_contain_text("当前可见 1 部（隐藏仍参与）")

        # 取消可见全选只取消可见项：甲/丙 仍是手工勾选。
        page.uncheck("#batch-select-all-checkbox")
        expect(page.locator("#batch-accept-submit")).to_contain_text("保存并确认 2 部")
        # #158：删空搜索词即可恢复完整批次（不再有单独的「清除条件」入口）。
        expect(page.locator("#batch-review-clear")).to_have_count(0)
        page.fill("#batch-review-search", "")
        expect(page.locator(".batch-draft-card")).to_have_count(3)
        checked = page.evaluate(
            """() => Array.from(document.querySelectorAll('.batch-draft-card')).map((card) => [
                card.dataset.itemId,
                card.querySelector('input[type="checkbox"]').checked,
            ])"""
        )
        assert checked == [["item-a", True], ["item-b", False], ["item-c", True]], checked

    def test_n_dialog_rechecks_a_version_change_with_zero_requests(
        self, page: Page, live_server_url: str
    ) -> None:
        """AC：弹窗后 revision 变化 → 零 save-confirm 请求 + 常驻重新确认；再确认才发送。"""
        accept_calls: list[dict[str, Any]] = []
        held: list[Any] = []

        def _accept(route: Any, request: Any) -> None:
            accept_calls.append(json.loads(request.post_data or "{}"))
            _accept_route_handler({"item-a", "item-b"})(route, request)

        def _hold_modify(route: Any, request: Any) -> None:
            # held route：保留在途响应，断言后由测试显式 fulfill，不在 handler 里 sleep。
            if request.method != "POST":
                route.continue_()
                return
            held.append(route)

        items = _confirm_scope_items()[:2]
        page.route("**/api/v1/batches/batch-spa/save-confirm*", _accept)
        page.route("**/api/v1/requests/preview-modify", _hold_modify)
        self._open(page, live_server_url, items, "甲S1\n乙S1")
        self._check(page, "item-a")
        self._check(page, "item-b")

        # 先发出修改并保持响应在途：甲被阻断，N 此刻只剩乙。
        page.locator('.batch-draft-card[data-item-id="item-a"]').click()
        page.fill("#batch-preview-must-contain", "新筛选")
        page.locator("#detail-preview-edit-form").evaluate("form => form.requestSubmit()")
        expect(page.locator("#batch-accept-submit")).to_contain_text("保存并确认 1 部")
        assert held

        page.click("#batch-accept-submit")
        page.wait_for_selector(".confirm-dialog", timeout=5000)
        expect(page.locator(".confirm-dialog-title")).to_have_text("保存并确认 1 部")

        # 弹窗期间在途响应到达：甲带着新 revision 回到资格集合。
        applied = _preview_request("咒术回战", "req-scope-a")
        applied["confirmable_config"]["filter_rule"]["must_contain"] = "新筛选"
        assert items[0]["draft_id"]
        held[0].fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "ok": True,
                    "result": {
                        "request": applied,
                        "summary": {},
                        "draft_id": items[0]["draft_id"],
                        "draft_revision": 2,
                    },
                },
                ensure_ascii=False,
            ),
        )
        expect(page.locator("#batch-accept-submit")).to_contain_text("保存并确认 2 部")

        page.locator(".confirm-dialog .primary-button").click()

        # 零 save-confirm POST：弹窗关闭，固定栏留下常驻说明并获得焦点。
        expect(page.locator("#batch-accept-selected-recheck")).to_be_visible()
        expect(page.locator("#batch-accept-selected-recheck")).to_contain_text("资格或草案版本已变化")
        expect(page.locator(".confirm-dialog")).to_have_count(0)
        assert accept_calls == []
        assert page.evaluate("() => document.activeElement && document.activeElement.id") == "batch-accept-selected-recheck"
        assert page.locator("#batch-accept-submit").get_attribute("aria-describedby") == (
            "batch-accept-selected-count batch-accept-selected-recheck"
        )

        # 明确重新确认后才按新的完整集合发送，并带上新版本。
        page.click("#batch-accept-submit")
        page.wait_for_selector(".confirm-dialog", timeout=5000)
        expect(page.locator("#batch-accept-selected-recheck")).to_have_count(0)
        expect(page.locator(".confirm-dialog-title")).to_have_text("保存并确认 2 部")
        page.locator(".confirm-dialog .primary-button").click()
        page.wait_for_selector(".global-notification:not(:empty)", timeout=5000)

        payload = accept_calls[-1]
        assert payload["item_ids"] == ["item-a", "item-b"]
        assert [(item["item_id"], item["base_revision"]) for item in payload["items"]] == [
            ("item-a", 2),
            ("item-b", 1),
        ]

    def test_disabled_entries_always_state_a_visible_reason(
        self, page: Page, live_server_url: str
    ) -> None:
        """AC (#145)：静止态与待核验都有可访问的说明，不依赖 title。"""
        page.route("**/api/v1/batches/batch-spa/save-confirm*", lambda route: route.abort())
        self._open(page, live_server_url, _confirm_scope_items()[:2], "甲S1\n乙S1")

        submit = page.locator("#batch-accept-submit")
        expect(submit).to_be_disabled()
        expect(submit).to_contain_text("保存并确认 0 部")
        assert submit.get_attribute("title") is None
        # 静止态（没有勾选）不输出伪造的禁用长句。
        expect(page.locator("#batch-accept-selected-scope")).to_have_count(0)
        expect(page.locator("#batch-accept-selected-reason")).to_have_count(0)

        # 勾选后发一次保存但结果未知：唯一入口禁用，并给出常驻原因。
        self._check(page, "item-a")
        expect(submit).to_be_enabled()
        page.click("#batch-accept-submit")
        page.wait_for_selector(".confirm-dialog", timeout=5000)
        page.locator(".confirm-dialog .primary-button").click()
        page.wait_for_selector("#batch-retry-frozen-operation", timeout=5000)

        expect(page.locator("#batch-accept-submit")).to_be_disabled()
        expect(page.locator("#batch-accept-selected-reason")).to_be_visible()
        expect(page.locator("#batch-accept-selected-reason")).to_contain_text("待核验")
        # 结果待核验时该条目暂不可确认：计数芯片说明排除，禁用原因常驻为唯一入口的
        # 可访问描述；底栏仍只有一行。
        expect(page.locator("#batch-accept-selected-count")).to_contain_text("1 部暂不可确认，已排除")
        expect(page.locator("#batch-accept-selected-scope")).to_have_count(0)
        assert page.locator("#batch-accept-submit").get_attribute("aria-describedby") == (
            "batch-accept-selected-count batch-accept-selected-reason"
        )
        expect(page.locator("#batch-accept-all")).to_have_count(0)

    def test_entry_keeps_its_safety_list_and_payload_in_step(
        self, page: Page, live_server_url: str
    ) -> None:
        """AC (#145)：唯一入口的按钮数量、弹窗安全清单、描述符与 item_ids 同源。"""
        accept_calls: list[dict[str, Any]] = []

        def _accept(route: Any, request: Any) -> None:
            accept_calls.append(json.loads(request.post_data or "{}"))
            _accept_route_handler({"item-a", "item-b", "item-c"})(route, request)

        page.route("**/api/v1/batches/batch-spa/save-confirm*", _accept)
        items = _confirm_scope_items()
        # 被筛选隐藏的条目也要验证清单同源。
        page.route(
            "**/api/v1/batches/parse",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(items),
            ),
        )
        _goto_batch(page, live_server_url)
        page.fill("#batch-raw-input", "甲S1\n乙S1\n丙S1")
        page.click("#batch-parse-submit")
        expect(page.locator(".batch-draft-card")).to_have_count(3)
        self._check(page, "item-a")

        # 按钮 1 部 = 清单 1 项，取消后现场不变。
        expect(page.locator("#batch-accept-submit")).to_contain_text("保存并确认 1 部")
        page.click("#batch-accept-submit")
        page.wait_for_selector(".confirm-dialog", timeout=5000)
        expect(page.locator(".confirm-dialog-items li")).to_have_count(1)
        page.locator(".confirm-dialog .secondary-button").click()
        assert accept_calls == []

        # 勾选全部三项后：按钮 3 部 = 清单 3 项 = 描述符 3 个 = item_ids 3 个。
        page.check("#batch-select-all-checkbox")
        expect(page.locator("#batch-accept-submit")).to_contain_text("保存并确认 3 部")
        page.click("#batch-accept-submit")
        page.wait_for_selector(".confirm-dialog", timeout=5000)
        expect(page.locator(".confirm-dialog-items li")).to_have_count(3)
        page.locator(".confirm-dialog .primary-button").click()
        page.wait_for_selector(".global-notification:not(:empty)", timeout=5000)
        all_payload = accept_calls[-1]
        assert all_payload["item_ids"] == ["item-a", "item-b", "item-c"]
        assert len(all_payload["items"]) == 3
        assert all(item["draft_id"] for item in all_payload["items"])

    def test_saving_entries_state_a_persistent_reason(
        self, page: Page, live_server_url: str
    ) -> None:
        """AC (#145)：保存进行中唯一入口禁用，并在固定栏常驻可见原因（不是 title）。"""
        held: list[Any] = []

        def _hold_accept(route: Any, request: Any) -> None:
            # held route：保留在途保存响应，断言后显式 fulfill。
            held.append(route)

        page.route("**/api/v1/batches/batch-spa/save-confirm*", _hold_accept)
        self._open(page, live_server_url, _confirm_scope_items()[:2], "甲S1\n乙S1")
        self._check(page, "item-a")
        page.click("#batch-accept-submit")
        page.wait_for_selector(".confirm-dialog", timeout=5000)
        page.locator(".confirm-dialog .primary-button").click()
        assert held

        expect(page.locator("#batch-accept-submit")).to_be_disabled()
        expect(page.locator("#batch-accept-selected-reason")).to_be_visible()
        expect(page.locator("#batch-accept-selected-reason")).to_contain_text("正在保存确认")

        held[0].fulfill(
            status=200,
            content_type="application/json",
            body=_batch_accept_result(
                [{"item_id": "item-a", "outcome": "CONFIRMED", "request_id": "req-scope-a", "status": "CONFIRMED", "tracking_id": "tracking-scope-a", "tracking_ready": True}],
                [],
            ),
        )
        page.wait_for_selector(".global-notification:not(:empty)", timeout=5000)
        expect(page.locator("#batch-accept-selected-reason")).to_have_count(0)

    def test_fixed_toolbar_keeps_one_row_and_does_not_cover_the_columns(
        self, page: Page, live_server_url: str
    ) -> None:
        """#143/#145：批量工作台固定为一屏，正常审核态底栏只有一行（全选 + 已选计数 +
        保存并确认 N 部），占据它在屏内的真实高度且不遮挡双栏末项。"""
        items = _compact_items(12)
        _route_parse(page, items)
        _goto_batch(page, live_server_url)
        page.set_viewport_size({"width": 1440, "height": 900})
        page.fill("#batch-raw-input", "\n".join(str(item["raw_title"]) for item in items))
        page.click("#batch-parse-submit")
        expect(page.locator(".batch-draft-card")).to_have_count(12)
        wait_for_screen_scroll(page)

        geometry = page.evaluate(
            """() => {
                const toolbar = document.querySelector('#batch-accept-toolbar')
                const layout = document.querySelector('.batch-review-layout')
                const screen = document.querySelector('.batch-workbench-screen')
                const toolbarBox = toolbar.getBoundingClientRect()
                const layoutBox = layout.getBoundingClientRect()
                const paneBox = document.querySelector('#batch-detail-pane').getBoundingClientRect()
                const listBox = document.querySelector('.batch-card-grid-wrapper').getBoundingClientRect()
                return {
                    measured: toolbarBox.height,
                    toolbarTop: toolbarBox.top,
                    toolbarBottom: toolbarBox.bottom,
                    layoutBottom: layoutBox.bottom,
                    paneBottom: paneBox.bottom,
                    listBottom: listBox.bottom,
                    screenHeight: screen.getBoundingClientRect().height,
                    viewportHeight: window.innerHeight,
                    documentHeight: document.documentElement.scrollHeight,
                    headerHeight: document.querySelector('.app-header').getBoundingClientRect().height,
                }
            }"""
        )
        assert geometry["measured"] > 0
        assert geometry["measured"] < geometry["viewportHeight"] * 0.3, geometry
        # #145：正常审核态只有一行——全选复选框与唯一主入口的垂直中心同排，
        # 操作栏高度不超过这一行加上下内边距。
        row_box = page.locator(".batch-accept-row").bounding_box()
        checkbox_box = page.locator("#batch-select-all-checkbox").bounding_box()
        count_box = page.locator("#batch-accept-selected-count").bounding_box()
        submit_box = page.locator("#batch-accept-submit").bounding_box()
        assert row_box and checkbox_box and count_box and submit_box
        centers = [
            box["y"] + box["height"] / 2
            for box in (checkbox_box, count_box, submit_box)
        ]
        assert max(centers) - min(centers) <= 6, centers
        assert geometry["measured"] <= row_box["height"] + 24, (geometry["measured"], row_box["height"])
        # 静止态没有额外的范围长句或禁用原因行。
        expect(page.locator("#batch-accept-selected-scope")).to_have_count(0)
        expect(page.locator("#batch-accept-selected-reason")).to_have_count(0)
        # 操作栏取真实高度并留在视口内；双栏可视区在它之上结束，没有重叠。
        assert geometry["toolbarBottom"] <= geometry["viewportHeight"] + 0.5, geometry
        assert geometry["layoutBottom"] <= geometry["toolbarTop"] + 0.5, geometry
        assert geometry["paneBottom"] <= geometry["toolbarTop"] + 0.5, geometry
        assert geometry["listBottom"] <= geometry["toolbarTop"] + 0.5, geometry
        # 工作台屏固定为一屏；短输入的空闲首屏也在一屏内，整页仍只有两屏高。
        assert geometry["screenHeight"] <= geometry["viewportHeight"] - geometry["headerHeight"] + 0.5
        assert geometry["documentHeight"] <= 2 * geometry["viewportHeight"] + 1

        # 列表滚到底 + 键盘聚焦最后一张卡：卡片与焦点环都在栏内且在操作栏之上。
        page.evaluate(
            """() => {
                const wrapper = document.querySelector('.batch-card-grid-wrapper')
                wrapper.scrollTop = wrapper.scrollHeight
            }"""
        )
        page.locator(".batch-draft-card").last.focus()
        focused = page.evaluate(
            """() => {
                const card = document.activeElement
                const style = getComputedStyle(card)
                const width = parseFloat(style.outlineWidth) || 0
                const offset = parseFloat(style.outlineOffset) || 0
                const rect = card.getBoundingClientRect()
                const wrapper = document.querySelector('.batch-card-grid-wrapper').getBoundingClientRect()
                const toolbar = document.querySelector('#batch-accept-toolbar').getBoundingClientRect()
                return {
                    id: card.dataset.itemId,
                    ringBottom: rect.bottom + width + offset,
                    ringTop: rect.top - width - offset,
                    listTop: wrapper.top,
                    listBottom: wrapper.bottom,
                    toolbarTop: toolbar.top,
                    top: rect.top,
                }
            }"""
        )
        assert focused["id"] == "item-11", focused
        assert focused["ringTop"] >= focused["listTop"] - 0.5, focused
        assert focused["ringBottom"] <= focused["listBottom"] + 0.5, focused
        assert focused["ringBottom"] <= focused["toolbarTop"] + 0.5, focused
        assert focused["top"] >= 0, focused

        # 右栏自身内部滚动；滚到底后末字段仍在栏内且在操作栏之上。
        bottom = page.evaluate(
            """() => {
                const pane = document.querySelector('#batch-detail-pane')
                pane.scrollTop = pane.scrollHeight
                const paneBox = pane.getBoundingClientRect()
                const toolbar = document.querySelector('#batch-accept-toolbar').getBoundingClientRect()
                // 折叠的 details 子树由 ::details-content 的 content-visibility 隐藏：
                // 它不参与滚动溢出，也不属于可达的审核面，因此不参与末项测量。
                const rects = Array.from(pane.querySelectorAll('input, select, textarea, p, button'))
                    .filter((el) => (el.checkVisibility ? el.checkVisibility() : true))
                    .map((el) => el.getBoundingClientRect().bottom)
                return {
                    lastPaneBottom: rects.length ? Math.max(...rects) : null,
                    paneBottom: paneBox.bottom,
                    toolbarTop: toolbar.top,
                }
            }"""
        )
        assert bottom["lastPaneBottom"] is not None
        assert bottom["lastPaneBottom"] <= bottom["paneBottom"] + 0.5, bottom
        assert bottom["paneBottom"] <= bottom["toolbarTop"] + 0.5, bottom

    @pytest.mark.parametrize(
        "width,height,zoom",
        [(1280, 720, 1), (1440, 900, 1), (1920, 1080, 1), (1280, 720, 2)],
    )
    def test_confirm_scope_copy_is_reachable_at_desktop_sizes(
        self, page: Page, live_server_url: str, width: int, height: int, zoom: int
    ) -> None:
        """AC：三档桌面与 200% 缩放下两个入口的范围文案与清单可达、不裁切、无横向溢出。"""
        _route_parse(page, _confirm_scope_items())
        _goto_batch(page, live_server_url)
        page.set_viewport_size({"width": width, "height": height})
        page.fill("#batch-raw-input", "甲S1\n乙S1\n丙S1")
        page.click("#batch-parse-submit")
        expect(page.locator(".batch-draft-card")).to_have_count(3)
        wait_for_screen_scroll(page)
        if zoom == 2:
            page.evaluate("() => { document.documentElement.style.zoom = '2' }")
        self._check(page, "item-a")

        # #145：底栏始终只有一行——精简计数常驻可见，主入口把它作为可访问描述。
        counts = page.locator("#batch-accept-selected-count")
        counts.scroll_into_view_if_needed()
        expect(counts).to_be_visible()
        expect(counts).to_contain_text("已选 1 部")
        expect(page.locator("#batch-accept-submit")).to_contain_text("保存并确认 1 部")
        assert page.locator("#batch-accept-submit").get_attribute("aria-describedby") == "batch-accept-selected-count"

        # 勾选被筛选隐藏时信息仍在同一行的计数芯片里，不新增第二行。
        _fill_title_search(page, "乙")
        expect(counts).to_contain_text("当前可见 0 部（隐藏仍参与）")
        assert page.locator("#batch-accept-submit").get_attribute("aria-describedby") == "batch-accept-selected-count"
        expect(page.locator("#batch-accept-selected-scope")).to_have_count(0)

        page.click("#batch-accept-submit")
        page.wait_for_selector(".confirm-dialog", timeout=5000)
        expect(page.locator(".confirm-dialog-items li")).to_have_count(1)
        dialog_box = page.locator(".confirm-dialog").bounding_box()
        assert dialog_box is not None
        assert dialog_box["width"] <= width + 1
        # 缩放下模态背景同样不可交互：固定栏仍在 inert 子树里。
        zoom_layers = page.evaluate(
            """() => {
                const backdrop = document.querySelector('.confirm-dialog-backdrop')
                const toolbar = document.querySelector('#batch-accept-toolbar')
                const root = document.body
                const children = Array.from(root.children)
                return {
                    backdrop: getComputedStyle(backdrop).zIndex,
                    toolbar: getComputedStyle(toolbar).zIndex,
                    toolbarInert: toolbar.closest('[inert]') !== null,
                    backdropAfterApp: children.indexOf(backdrop) === children.length - 1,
                }
            }"""
        )
        assert int(zoom_layers["backdrop"]) > int(zoom_layers["toolbar"])
        assert zoom_layers["toolbarInert"] is True
        assert zoom_layers["backdropAfterApp"] is True
        page.locator(".confirm-dialog .secondary-button").click()
        assert page.evaluate("() => document.body.scrollWidth <= window.innerWidth + 1")

    def test_confirm_dialog_traps_focus_and_restores_it(
        self, page: Page, live_server_url: str
    ) -> None:
        """AC：ConfirmDialog 的 trap/Escape/焦点恢复沿用既有实现；弹窗期间背景不可交互。"""
        accept_calls: list[dict[str, Any]] = []

        def _accept(route: Any, request: Any) -> None:
            accept_calls.append(json.loads(request.post_data or "{}"))
            _accept_route_handler({"item-a"})(route, request)

        page.route("**/api/v1/batches/batch-spa/save-confirm*", _accept)
        self._open(page, live_server_url, _confirm_scope_items()[:2], "甲S1\n乙S1")
        self._check(page, "item-a")

        page.locator("#batch-accept-submit").focus()
        page.keyboard.press("Enter")
        page.wait_for_selector(".confirm-dialog", timeout=5000)
        # 弹窗层级高于固定栏，且背景被 inert：模态期间无法再触发一次保存。
        layers = page.evaluate(
            """() => {
                const backdrop = document.querySelector('.confirm-dialog-backdrop')
                const toolbar = document.querySelector('#batch-accept-toolbar')
                return {
                    backdrop: getComputedStyle(backdrop).zIndex,
                    toolbar: getComputedStyle(toolbar).zIndex,
                    inertCount: document.querySelectorAll('[inert]').length,
                    toolbarInert: toolbar.closest('[inert]') !== null,
                    focusedInsideDialog: document.querySelector('.confirm-dialog').contains(document.activeElement),
                }
            }"""
        )
        assert int(layers["backdrop"]) > int(layers["toolbar"])
        assert layers["toolbarInert"] is True
        assert layers["focusedInsideDialog"] is True
        assert layers["inertCount"] >= 1

        page.keyboard.press("Tab")
        page.keyboard.press("Shift+Tab")
        assert page.evaluate("() => document.querySelector('.confirm-dialog').contains(document.activeElement)")

        page.keyboard.press("Escape")
        expect(page.locator(".confirm-dialog")).to_have_count(0)
        assert accept_calls == []
        assert page.evaluate("() => document.activeElement && document.activeElement.id") == "batch-accept-submit"
        assert page.evaluate("() => document.querySelectorAll('[inert]').length") == 0

        page.locator("#batch-accept-submit").click()
        page.wait_for_selector(".confirm-dialog", timeout=5000)
        page.locator(".confirm-dialog .primary-button").click()
        page.wait_for_selector(".global-notification:not(:empty)", timeout=5000)
        assert [item["item_id"] for item in accept_calls[-1]["items"]] == ["item-a"]


class TestAppBatchOutcomeRecovery:
    """US-357：逐条 results[] 收敛、unknown 冻结恢复与完成导航。"""

    def _open(self, page: Page, live_server_url: str, items: list[dict[str, Any]], raw: str) -> None:
        page.route(
            "**/api/v1/batches/parse",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(items),
            ),
        )
        _goto_batch(page, live_server_url)
        page.fill("#batch-raw-input", raw)
        page.click("#batch-parse-submit")
        expect(page.locator(".batch-draft-card")).to_have_count(len(items))

    @staticmethod
    def _check(page: Page, item_id: str) -> None:
        page.locator(f'.batch-draft-card[data-item-id="{item_id}"] .batch-card-checkbox-row').check()

    def test_partial_success_keeps_persistent_result_and_excludes_success(
        self, page: Page, live_server_url: str
    ) -> None:
        calls: list[dict[str, Any]] = []

        def _accept(route: Any, request: Any) -> None:
            calls.append(json.loads(request.post_data or "{}"))
            _accept_route_handler({"item-a"})(route, request)

        page.route("**/api/v1/batches/batch-spa/save-confirm*", _accept)
        items = [
            _batch_item("item-a", "甲S1", status="DRAFT", canonical_title="甲 第一季", preview_request=_preview_request("甲", "req-a")),
            _batch_item("item-b", "乙S1", status="DRAFT", canonical_title="乙 第一季", preview_request=_preview_request("乙", "req-b")),
            _batch_item("item-c", "丙S1", status="DRAFT", canonical_title="丙 第一季", preview_request=_preview_request("丙", "req-c")),
        ]
        self._open(page, live_server_url, items, "甲S1\n乙S1\n丙S1")
        self._check(page, "item-a")
        self._check(page, "item-b")
        page.click("#batch-accept-submit")
        page.locator(".confirm-dialog .primary-button").click()
        expect(page.locator(".global-notification")).to_contain_text("批量保存确认完成")

        expect(page.locator("#batch-save-summary")).to_contain_text("本次结果：已确认 1 项；失败 1 项；完整批次剩余 2 项。")
        expect(page.locator('.batch-draft-card[data-item-id="item-a"] .batch-card-status')).to_contain_text("已确认待提交")
        expect(page.locator('.batch-draft-card[data-item-id="item-a"] .batch-card-checkbox-row')).to_be_disabled()
        # 成功项退出勾选与可确认集合；可重试的失败项保留勾选，等用户明确重试；
        # 从未勾选的条目不会因为一次保存而被悄悄纳入范围。
        expect(page.locator('.batch-draft-card[data-item-id="item-b"] .batch-card-checkbox-row')).to_be_checked()
        expect(page.locator('.batch-draft-card[data-item-id="item-c"] .batch-card-checkbox-row')).not_to_be_checked()
        expect(page.locator("#batch-accept-submit")).to_contain_text("保存并确认 1 部")
        assert len(calls) == 1

    def test_unknown_response_retries_the_exact_frozen_operation(
        self, page: Page, live_server_url: str
    ) -> None:
        held: list[Any] = []
        calls: list[dict[str, Any]] = []
        item = _batch_item("item-a", "甲S1", status="DRAFT", canonical_title="甲 第一季", preview_request=_preview_request("甲", "req-a"))

        def _accept(route: Any, request: Any) -> None:
            payload = json.loads(request.post_data or "{}")
            calls.append(payload)
            if len(calls) == 1:
                held.append(route)
                return
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_accept_result(
                    [{"item_id": "item-a", "outcome": "CONFIRMED", "request_id": "req-a", "status": "CONFIRMED", "tracking_id": "tracking-a", "tracking_ready": True}],
                    [],
                ),
            )

        page.route("**/api/v1/batches/batch-spa/save-confirm*", _accept)
        self._open(page, live_server_url, [item], "甲S1")
        self._check(page, "item-a")
        page.click("#batch-accept-submit")
        page.locator(".confirm-dialog .primary-button").click()
        expect(page.locator("#batch-accept-selected-reason")).to_contain_text("正在保存确认")
        assert held
        frozen = json.loads(json.dumps(calls[0]))
        held[0].fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"ok": True, "result": {"batch_id": "batch-spa", "results": [], "summary": {}}}),
        )
        expect(page.locator(".batch-card-status")).to_contain_text("结果待核验")
        page.click("#batch-retry-frozen-operation")
        expect(page.locator(".global-notification")).to_contain_text("批量保存确认完成")
        assert len(calls) == 2
        assert calls[1] == frozen

    def test_no_new_failure_stays_and_locates_first_remaining_item(
        self, page: Page, live_server_url: str
    ) -> None:
        def _accept(route: Any, request: Any) -> None:
            _accept_route_handler({"item-a"})(route, request)

        page.route("**/api/v1/batches/batch-spa/save-confirm*", _accept)
        items = [
            _batch_item("item-a", "甲S1", status="DRAFT", canonical_title="甲 第一季", preview_request=_preview_request("甲", "req-a")),
            _batch_item("item-b", "乙S1", status="DRAFT", canonical_title="乙 第一季", preview_request=_preview_request("乙", "req-b")),
        ]
        self._open(page, live_server_url, items, "甲S1\n乙S1")
        self._check(page, "item-a")
        page.click("#batch-accept-submit")
        page.locator(".confirm-dialog .primary-button").click()
        expect(page.locator("#batch-save-summary")).to_contain_text("完整批次剩余 1 项")
        expect(page.locator(".batch-review-navigation")).to_contain_text("首个未处理条目")
        expect(page.locator('.batch-draft-card[data-item-id="item-b"]')).to_have_class(re.compile(r"\bis-current\b"))
        assert "/app/add" in page.url

    def test_all_success_enters_tracking_with_public_identifier(
        self, page: Page, live_server_url: str
    ) -> None:
        page.route(
            "**/api/v1/batches/batch-spa/save-confirm*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_accept_result(
                    [{"item_id": "item-a", "outcome": "CONFIRMED", "request_id": "req-a", "status": "CONFIRMED", "tracking_id": "tracking-public-a", "tracking_ready": True}],
                    [],
                ),
            ),
        )
        item = _batch_item("item-a", "甲S1", status="DRAFT", canonical_title="甲 第一季", preview_request=_preview_request("甲", "req-a"))
        self._open(page, live_server_url, [item], "甲S1")
        self._check(page, "item-a")
        page.click("#batch-accept-submit")
        page.locator(".confirm-dialog .primary-button").click()
        page.wait_for_url(re.compile(r"/app/tracking\?tracking_id=tracking-public-a$"), timeout=5000)
        assert "tracking-public-a" in page.url


# ---------------------------------------------------------------------------
# Issue 196: 会话 effect 的可观察结果（列表滚动按筛选键恢复、焦点落到会话声明的目标）
# 与离开守卫取消分支的真实 Chromium 证据。只补断言，不改产品行为。
# ---------------------------------------------------------------------------


def _save_confirm_rows(item_ids: list[str], *, failed_id: str | None = None) -> str:
    """#196：逐条保存结果——除 ``failed_id`` 外全部 CONFIRMED。"""
    results: list[dict[str, Any]] = []
    for item_id in item_ids:
        failed = item_id == failed_id
        results.append(
            {
                "item_id": item_id,
                "outcome": "FAILED" if failed else "CONFIRMED",
                "request_id": None if failed else f"req-{item_id}",
                "status": None if failed else "CONFIRMED",
                "error_type": "draft_reserved" if failed else None,
                "error_message": None,
                "tracking_id": None if failed else f"tracking-{item_id}",
                "tracking_ready": None if failed else True,
            }
        )
    confirmed = sum(1 for result in results if result["outcome"] == "CONFIRMED")
    return json.dumps(
        {
            "ok": True,
            "result": {
                "batch_id": "batch-spa",
                "results": results,
                "summary": {
                    "requested": len(results),
                    "confirmed": confirmed,
                    "failed": len(results) - confirmed,
                },
            },
        },
        ensure_ascii=False,
    )


def _list_scroll_geometry(page: Page) -> dict[str, float]:
    return page.evaluate(
        """() => {
            const wrapper = document.querySelector('.batch-card-grid-wrapper')
            return {
                scrollTop: wrapper.scrollTop,
                max: wrapper.scrollHeight - wrapper.clientHeight,
            }
        }"""
    )


class TestAppBatchSessionObservables:
    """#196：会话/视图声明的效果在页面上的可观察结果。

    焦点目标由会话 effect 声明（`useBatchReviewJourney`），视图执行；列表滚动记忆是
    **视图本地**的按筛选键 Map（`BatchWorkbenchView.vue:534`）及其恢复，不是会话声明。
    两条断言都只锚定 DOM 可观察结果（scrollTop / activeElement / 可视区几何），
    不复述视图内部实现。
    """

    def test_review_list_scroll_is_remembered_per_filter_key(
        self, page: Page, live_server_url: str
    ) -> None:
        items = _compact_items(12)
        _open_compact_list(page, live_server_url, items)
        expect(page.locator(".batch-draft-card")).to_have_count(12)

        geometry = _list_scroll_geometry(page)
        assert geometry["max"] > 200, geometry
        all_pos = int(geometry["max"] * 0.3)
        draft_pos = int(geometry["max"] * 0.75)

        page.evaluate(
            "(value) => { document.querySelector('.batch-card-grid-wrapper').scrollTop = value }",
            all_pos,
        )
        assert _list_scroll_geometry(page)["scrollTop"] == all_pos

        # 「全部状态」→「草案」：条目集合不变（12 部都是 DRAFT），但这是另一个筛选键，
        # 切过去恢复的是该键自己的位置（尚未记录 → 0）。
        page.select_option("#batch-review-status", "DRAFT")
        expect(page.locator(".batch-draft-card")).to_have_count(12)
        page.wait_for_function(
            "() => document.querySelector('.batch-card-grid-wrapper').scrollTop === 0"
        )
        page.evaluate(
            "(value) => { document.querySelector('.batch-card-grid-wrapper').scrollTop = value }",
            draft_pos,
        )
        assert _list_scroll_geometry(page)["scrollTop"] == draft_pos

        # 切回「全部状态」：恢复该键记住的位置，而不是沿用上一个键的位置。
        page.select_option("#batch-review-status", "")
        page.wait_for_function(
            "(expected) => Math.abs(document.querySelector('.batch-card-grid-wrapper').scrollTop - expected) <= 1",
            arg=all_pos,
        )
        assert abs(_list_scroll_geometry(page)["scrollTop"] - all_pos) <= 1

        # 再切回「草案」：它记住的是自己的位置（draft_pos），两次往返互不覆盖。
        page.select_option("#batch-review-status", "DRAFT")
        page.wait_for_function(
            "(expected) => Math.abs(document.querySelector('.batch-card-grid-wrapper').scrollTop - expected) <= 1",
            arg=draft_pos,
        )
        assert abs(_list_scroll_geometry(page)["scrollTop"] - draft_pos) <= 1

    def test_save_result_focus_lands_on_the_session_declared_card_and_is_visible(
        self, page: Page, live_server_url: str
    ) -> None:
        items = _compact_items(12)
        item_ids = [str(item["item_id"]) for item in items]
        page.route(
            "**/api/v1/batches/batch-spa/save-confirm*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_save_confirm_rows(item_ids, failed_id="item-07"),
            ),
        )
        _open_compact_list(page, live_server_url, items)

        # 勾选全部 12 部，再用标题搜索把稍后失败的目标筛出可见列表：
        # 焦点目标仍然由会话声明，视图按揭示规则把它临时显示出来。
        page.check("#batch-select-all-checkbox")
        expect(page.locator("#batch-accept-submit")).to_contain_text("保存并确认 12 部")
        _fill_title_search(page, "番剧03")
        expect(page.locator(".batch-draft-card")).to_have_count(1)
        expect(page.locator('.batch-draft-card[data-item-id="item-07"]')).to_have_count(0)

        page.click("#batch-accept-submit")
        page.locator(".confirm-dialog .primary-button").click()

        expect(page.locator(".batch-review-navigation")).to_contain_text("首个失败条目")
        card = page.locator('.batch-draft-card[data-item-id="item-07"]')
        expect(card).to_have_count(1)
        page.wait_for_function(
            "() => document.activeElement && document.activeElement.dataset"
            " && document.activeElement.dataset.itemId === 'item-07'",
            timeout=5000,
        )
        expect(card).to_be_in_viewport()
        geometry = page.evaluate(
            """() => {
                const card = document.querySelector('.batch-draft-card[data-item-id="item-07"]')
                const wrapper = document.querySelector('.batch-card-grid-wrapper').getBoundingClientRect()
                const rect = card.getBoundingClientRect()
                return { top: rect.top, bottom: rect.bottom, listTop: wrapper.top, listBottom: wrapper.bottom }
            }"""
        )
        assert geometry["top"] >= geometry["listTop"] - 0.5, geometry
        assert geometry["bottom"] <= geometry["listBottom"] + 0.5, geometry
        assert _active_item_id(page) == "item-07"


# ---------------------------------------------------------------------------
# Issue 198: 右栏详情滚动策略——切换条目回顶（不做按条目记忆），
# 同一条目内的编辑不打断栏内滚动。断言只锚定 DOM 可观察结果（scrollTop）。
# ---------------------------------------------------------------------------


def _detail_pane_scroll_top(page: Page) -> float:
    return page.eval_on_selector("#batch-detail-pane", "el => el.scrollTop")


def _switch_detail_item(page: Page, item_id: str) -> None:
    """点击另一张条目卡，并等右栏详情编辑器真的按条目 key 重新挂载。

    右栏 pane 本身没有 `:key`，只有内部 AnimeDraftEditor 换挂载，因此这里用
    「旧表单被新表单替换」作为切换完成的同步点，而不是等一个固定时长。
    """
    page.eval_on_selector("#detail-preview-edit-form", "el => { el.dataset.probe = '1' }")
    page.locator(f'.batch-draft-card[data-item-id="{item_id}"]').click()
    page.wait_for_function(
        """() => {
            const form = document.querySelector('#detail-preview-edit-form')
            return Boolean(form) && form.dataset.probe !== '1'
        }""",
        timeout=10_000,
    )


class TestAppBatchDetailPaneScrollPolicy:
    """#198：切换条目时右栏回到顶部，且同一条目内的编辑不打断栏内滚动。

    实测取证（#198 评论）：右栏滚动容器是外层 `#batch-detail-pane`，内部编辑器按条目
    重挂载不会移动它——不重置就会把上一条目的偏移带到另一个条目上（300 → 300）。
    """

    def test_switching_item_resets_the_detail_pane_and_same_item_edit_keeps_scroll(
        self, page: Page, live_server_url: str
    ) -> None:
        _open_compact_list(page, live_server_url, _compact_items(12))
        # 1440×900 下右栏内容恰好放得下（无法观察滚动）；1280×600 下右栏真实溢出。
        page.set_viewport_size({"width": 1280, "height": 600})
        page.locator('.batch-draft-card[data-item-id="item-00"]').click()
        page.wait_for_selector("#batch-detail-pane .batch-resource-box", timeout=10_000)

        overflow = page.eval_on_selector(
            "#batch-detail-pane", "el => el.scrollHeight - el.clientHeight"
        )
        assert overflow >= 300, overflow

        page.eval_on_selector("#batch-detail-pane", "el => el.scrollTop = 300")
        assert _detail_pane_scroll_top(page) == 300

        # 同一条目内的真实编辑（筛选输入 → v-model → 未应用编辑）不改变 currentItemId，
        # 因此不得打断栏内滚动。这里用 input 事件而不是点击控件：点击会带上浏览器把
        # 焦点元素滚进可见区的行为，那不属于本票的滚动策略。
        page.evaluate(
            """() => {
                const input = document.querySelector('#batch-preview-must-contain')
                input.value = '未应用修改'
                input.dispatchEvent(new Event('input', { bubbles: true }))
            }"""
        )
        page.wait_for_function(
            "() => document.querySelector('#batch-preview-must-contain').value === '未应用修改'"
        )
        expect(page.locator("#batch-detail-pane")).to_contain_text("有尚未应用的编辑")
        assert _detail_pane_scroll_top(page) == 300

        # 切换到另一条目：右栏回顶。
        _switch_detail_item(page, "item-01")
        assert _detail_pane_scroll_top(page) == 0

        # 不做按条目记忆：切回原条目同样回顶，而不是恢复离开时记住的偏移。
        page.eval_on_selector("#batch-detail-pane", "el => el.scrollTop = 240")
        _switch_detail_item(page, "item-00")
        assert _detail_pane_scroll_top(page) == 0


class TestAppBatchLeaveGuardCancel:
    """#196：离开守卫取消分支的真实 Chromium 证据（取消必须完全无副作用）。"""

    def test_cancelling_the_leave_dialog_keeps_scene_url_and_unsaved_edit(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        canary = "https://private.invalid/leave-guard-canary?token=leave-guard-token"
        console_messages: list[str] = []
        page.on("console", lambda message: console_messages.append(message.text))
        page.on("pageerror", lambda error: console_messages.append(str(error)))
        held_modify: list[Any] = []

        def _hold_modify(route: Any, request: Any) -> None:
            # held route：未保存编辑的防抖请求保持在途，确保取消分支不依赖它的响应。
            if request.method != "POST":
                route.continue_()
                return
            held_modify.append(route)

        page.route("**/api/v1/requests/preview-modify", _hold_modify)
        items = [
            _batch_item(
                "item-a",
                "甲S1",
                status="DRAFT",
                canonical_title="甲 第一季",
                preview_request=_preview_request("甲", "req-leave-a"),
                error={"error_type": "mikan_unavailable", "error_message": canary},
            ),
            _batch_item(
                "item-b",
                "乙S1",
                status="DRAFT",
                canonical_title="乙 第一季",
                preview_request=_preview_request("乙", "req-leave-b"),
            ),
        ]
        _route_parse(page, items)
        set_storage_preferences(page, storage_dir)
        _goto_batch(page, live_server_url)
        page.set_viewport_size({"width": 1440, "height": 900})
        page.fill("#batch-raw-input", "甲S1\n乙S1")
        page.click("#batch-parse-submit")
        expect(page.locator(".batch-draft-card")).to_have_count(2)

        # 制造 shouldGuard 为真的现场：勾选 + 右栏未保存编辑。
        page.locator('.batch-draft-card[data-item-id="item-a"] .batch-card-checkbox-row').check()
        page.locator('.batch-draft-card[data-item-id="item-a"]').click()
        page.fill("#batch-preview-must-contain", "未保存的编辑")

        url_before = page.url
        history_before = page.evaluate("() => window.history.length")

        # 通过主导航离开：审计中取消「留在此页」。
        page.click("#shell-nav-2")
        dialog = page.locator(".confirm-dialog")
        expect(dialog).to_be_visible()
        expect(dialog).to_contain_text("离开批量审核")
        dialog.get_by_role("button", name="留在此页").click()
        expect(page.locator(".confirm-dialog")).to_have_count(0)

        # URL 不变、没有导航，也没有清理批量现场。
        assert page.url == url_before
        assert page.evaluate("() => window.history.length") == history_before
        expect(page.locator("#batch-parse-form")).to_be_visible()
        expect(page.locator(".batch-draft-card")).to_have_count(2)
        expect(
            page.locator('.batch-draft-card[data-item-id="item-a"] .batch-card-checkbox-row')
        ).to_be_checked()
        expect(
            page.locator('.batch-draft-card[data-item-id="item-a"]')
        ).to_have_class(re.compile(r"\bis-current\b"))
        expect(page.locator("#batch-preview-must-contain")).to_have_value("未保存的编辑")
        expect(page.locator("#batch-accept-submit")).to_contain_text("保存并确认")

        # 守卫没有被消费：再次尝试离开仍然重新询问且同样可取消，证明取消分支没有
        # 执行任何清理，也没有把守卫置为非活动。
        page.click("#shell-nav-2")
        expect(page.locator(".confirm-dialog")).to_be_visible()
        page.locator(".confirm-dialog").get_by_role("button", name="留在此页").click()
        expect(page.locator(".confirm-dialog")).to_have_count(0)
        assert page.url == url_before

        # canary：DOM / URL / history.state / storage / console / 落盘 JSON 都不泄漏。
        # 说明：本用例不做服务端写（parse 与 preview-modify 都被 route 拦下），落盘清单
        # 可能为空——空清单上的负向断言自动成立，不把它当作「服务端确实落盘且未泄漏」的证据。
        browser_state = page.evaluate(
            """() => ({
                url: window.location.href,
                historyState: JSON.stringify(window.history.state),
                localStorage: JSON.stringify(window.localStorage),
                sessionStorage: JSON.stringify(window.sessionStorage),
                bodyText: document.body.innerText,
            })"""
        )
        persisted_json = (
            "\n".join(path.read_text(encoding="utf-8") for path in storage_dir.rglob("*.json"))
            if storage_dir.exists()
            else ""
        )
        for value in (canary, "leave-guard-token"):
            assert value not in browser_state["url"]
            assert value not in browser_state["historyState"]
            assert value not in browser_state["localStorage"]
            assert value not in browser_state["sessionStorage"]
            assert value not in browser_state["bodyText"]
            assert value not in persisted_json
            assert all(value not in message for message in console_messages)

        # frontend/AGENTS：held route 先存后用。取消分支不依赖该响应，断言完成后释放
        # 仍挂在途的请求，避免留下未收尾的路由。
        for held in held_modify:
            held.abort()
