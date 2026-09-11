from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from apps.migu_orca_entry.controllers.entry_controller import generate_request
from shared.models import EntryRequest
from tests.browser.conftest import issue_draft_id, save_preview_handler, set_storage_preferences

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
        # US-194/211: a card with a preview_request needs a server-authoritative
        # draft_id + draft_revision so the real preview-modify/preview-save
        # backend accepts it (issue returns revision=1).
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
    return json.dumps(
        {
            "ok": True,
            "result": {
                "batch_id": batch_id,
                "queue": {
                    "queue_id": f"queue-{batch_id}",
                    "batch_id": batch_id,
                    "created_at": "2026-08-19T00:00:00+00:00",
                    "updated_at": "2026-08-19T00:00:00+00:00",
                    "items": queue_items,
                },
                "items": items,
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
                        "request_id": request_id,
                        "title": title,
                        "status": "accepted",
                        "reason": None,
                        "error_type": None,
                        "queued": True,
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

        page.click("#batch-parse-submit")
        expect(page.locator("#batch-parse-error")).to_contain_text(
            "批量获取前必须输入至少一个番剧名称"
        )
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
            "MiKan 候选搜索暂时不可用"
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
            "正在搜索 2 个批量条目的 MiKan 候选"
        )
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


class TestAppBatchCandidateAndDraft:
    """AC: 候选浮层、季数确认、草案详情与删除."""

    def test_found_card_opens_candidate_popover_and_generates_draft(
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
        expect(card.locator(".batch-card-expand")).to_contain_text("查看候选")
        card.locator(".batch-card-expand").click()

        choices = page.locator("#batch-candidate-choices")
        expect(choices).to_be_visible()
        expect(choices).to_have_attribute("role", "dialog")
        choices.locator(".candidate-select").click()
        page.wait_for_selector(".batch-draft-card .batch-card-status", timeout=5000)

        expect(card.locator(".batch-card-status")).to_contain_text("草案")
        assert captured
        payload = captured[0]
        assert payload["source"] == "mikan"
        assert payload["mikan_bangumi"] == "https://mikan.example/Home/Bangumi/42"
        assert payload["save_request"] is False
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
        card.locator(".batch-card-expand").click()
        choices = page.locator("#batch-candidate-choices")
        confirmation = choices.locator(".candidate-season-confirmation input")
        choose = choices.locator(".candidate-select")
        expect(confirmation).not_to_be_checked()
        expect(choose).to_be_disabled()

        confirmation.check()
        expect(choose).to_be_enabled()
        # candidate_context never enters the DOM.
        assert "opaque-context" not in page.locator("body").inner_text()

    def test_draft_card_opens_shared_detail_with_batch_actions_and_delete(
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
        expect(first.locator(".batch-card-expand")).to_contain_text("查看草案")
        first.locator(".batch-card-expand").click()

        panel = page.locator("#request-detail-container")
        expect(panel).to_be_visible()
        expanded_text = panel.inner_text()
        assert "订阅草案（未保存）" in expanded_text
        assert "编辑订阅草案" in expanded_text
        # Batch-specific actions are present.
        expect(page.locator("#batch-detail-accept")).to_be_visible()
        expect(page.locator("#batch-detail-delete")).to_be_visible()

        # Delete removes only the selected card.
        page.locator("#batch-detail-delete").click()
        expect(page.locator(".batch-draft-card")).to_have_count(1)
        assert "路哥S4" in page.locator("#batch-parse-result").inner_text()
        assert "萌王S4" not in page.locator("#batch-parse-result").inner_text()

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
        _goto_batch(page, live_server_url)
        page.fill("#batch-raw-input", "萌王S4")
        page.click("#batch-parse-submit")
        card = page.locator(".batch-draft-card", has_text="萌王S4")
        card.locator(".batch-card-expand").click()
        page.locator("#batch-preview-must-contain").fill("新目录")
        page.locator("#batch-preview-apply-button").click()

        expect(page.locator(".batch-draft-card")).to_have_count(1)
        expect(page.locator(".batch-card-status")).to_contain_text("找到候选")
        expect(page.locator("#request-detail-container")).to_have_count(0)
        expect(page.locator(".batch-card-expand")).to_contain_text("查看候选")
        expect(page.locator(".global-notification")).to_contain_text("订阅草案已失效")
        assert "已删除批量卡片" not in page.locator("body").inner_text()

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
        page.locator(".batch-draft-card .batch-card-expand").click()

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
        page.route("**/api/v1/requests/preview-save", save_preview_handler())

        def _accept(route: Any, request: Any) -> None:
            accept_calls.append(json.loads(request.post_data or "{}"))
            _accept_route_handler({"item-1"})(route, request)

        page.route("**/api/v1/batches/batch-spa/accept*", _accept)
        self._setup_two_drafts(page, live_server_url)

        expect(page.locator("#batch-accept-toolbar")).to_be_visible()
        expect(page.locator("#batch-accept-selected-count")).to_contain_text("已选择 0 项")
        expect(page.locator("#batch-accept-submit")).to_be_disabled()

        first = page.locator(".batch-draft-card", has_text="萌王S4")
        first.locator(".batch-card-checkbox-row").check()
        expect(page.locator("#batch-accept-selected-count")).to_contain_text("已选择 1 项")
        expect(page.locator("#batch-accept-submit")).to_be_enabled()

        page.click("#batch-accept-submit")
        page.wait_for_selector(".confirm-dialog", timeout=5000)
        page.locator(".confirm-dialog .primary-button").click()
        page.wait_for_selector(".global-notification:not(:empty)", timeout=5000)

        expect(page.locator(".global-notification")).to_contain_text("批量接受成功")
        first_card = page.locator(".batch-draft-card", has_text="萌王S4")
        second_card = page.locator(".batch-draft-card", has_text="路哥S4")
        expect(first_card.locator(".batch-card-status")).to_contain_text("已接受")
        expect(first_card.locator(".batch-card-queue-status")).to_contain_text("待提交")
        expect(second_card.locator(".batch-card-status")).to_contain_text("草案")

        payload = accept_calls[-1]
        assert payload["item_ids"] == ["item-1"]
        assert [item["item_id"] for item in payload["items"]] == ["item-1"]
        assert payload["storage_dir"] is None

    def test_accept_all_accepts_reviewable_and_shows_failed_reason(
        self, page: Page, live_server_url: str
    ) -> None:
        accept_calls: list[dict[str, Any]] = []
        page.route("**/api/v1/requests/preview-save", save_preview_handler())

        def _accept(route: Any, request: Any) -> None:
            accept_calls.append(json.loads(request.post_data or "{}"))
            _accept_route_handler({"item-1"})(route, request)

        page.route("**/api/v1/batches/batch-spa/accept*", _accept)
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

        page.click("#batch-accept-all")
        page.wait_for_selector(".confirm-dialog", timeout=5000)
        page.locator(".confirm-dialog .primary-button").click()
        page.wait_for_selector(".global-notification:not(:empty)", timeout=5000)

        ok_card = page.locator(".batch-draft-card", has_text="萌王S4")
        fail_card = page.locator(".batch-draft-card", has_text="路哥S4")
        expect(ok_card.locator(".batch-card-status")).to_contain_text("已接受")
        expect(fail_card.locator(".batch-card-status")).to_contain_text("搜索失败")
        expect(fail_card.locator(".batch-card-reason")).to_contain_text(
            "无法接受：卡片缺少订阅草案，无法接受"
        )
        expect(page.locator(".global-notification")).to_contain_text("批量接受完成")

        payload = accept_calls[-1]
        assert "item_ids" not in payload
        assert [item["item_id"] for item in payload["items"]] == ["item-1", "item-fail"]

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
        expect(page.locator("#batch-accept-selected-count")).to_contain_text("已选择 2 项")

        page.uncheck("#batch-select-all-checkbox")
        expect(page.locator("#batch-accept-selected-count")).to_contain_text("已选择 0 项")

        page.check("#batch-select-all-checkbox")
        first_card = page.locator(".batch-draft-card", has_text="萌王S4")
        first_card.locator(".batch-card-checkbox-row").uncheck()
        expect(page.locator("#batch-accept-selected-count")).to_contain_text("已选择 1 项")
        expect(page.locator("#batch-select-all-checkbox")).not_to_be_checked()

    def test_accept_failure_preserves_cards_with_safe_error(
        self, page: Page, live_server_url: str
    ) -> None:
        page.route("**/api/v1/requests/preview-save", save_preview_handler())

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

        page.route("**/api/v1/batches/batch-spa/accept*", _fail)
        self._setup_two_drafts(page, live_server_url)

        page.click("#batch-accept-all")
        page.wait_for_selector(".confirm-dialog", timeout=5000)
        page.locator(".confirm-dialog .primary-button").click()
        page.wait_for_selector(".global-notification:not(:empty)", timeout=5000)

        expect(page.locator(".global-notification")).to_contain_text("接受失败")
        # Cards stay reviewable after a failed accept.
        expect(page.locator(".batch-draft-card", has_text="萌王S4").locator(".batch-card-status")).to_contain_text("草案")
        # The raw error_type never reaches the DOM.
        body_text = page.locator("body").inner_text()
        assert "batch_accept_failed" not in body_text
        assert "服务器内部错误" not in body_text


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
