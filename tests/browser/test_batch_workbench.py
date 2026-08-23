from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote_plus

import pytest
from playwright.sync_api import Page, expect

from apps.migu_orca_entry.controllers.entry_controller import generate_request
from mikan_engine.controllers.mikan_client import create_mikan_client
from mikan_engine.controllers.mikan_config import MikanConfig
from shared.models import EntryRequest
from tests.browser.conftest import set_storage_preferences


pytestmark = pytest.mark.browser


@pytest.fixture(autouse=True)
def _isolate_corrections_save(page: Page) -> Any:
    """Isolate the user-correction save the front end fires after a successful
    accept: intercept POST /api/v1/corrections so real saves never touch the
    default storage, and record the payloads so tests can assert the closure
    (US-155). Returns the recorded payload list."""
    calls: list[dict[str, Any]] = []

    def _fulfill(route: Any, request: Any) -> None:
        calls.append(json.loads(request.post_data or "{}"))
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"corrections": []}, ensure_ascii=False),
        )

    page.route("**/api/v1/corrections", _fulfill)
    yield calls


#: Sentinel to distinguish "field not provided by the caller" from an explicit
#: ``None`` (Stage 21 US-156 tests assert the no-preference fallback, where the
#: batch parse API returns ``applied_preferences: null`` / ``preference_hits:
#: null`` alongside a fallback warning).
_UNDEFINED = object()


def _batch_parse_result(items: list[dict[str, Any]], *, batch_id: str = "batch-browser") -> str:
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


def _batch_item(
    item_id: str,
    raw_title: str,
    *,
    status: str = "PARSED",
    canonical_title: str | None = None,
    candidate_title: str | None = None,
    poster_url: str | None = None,
    source_query: str | None = None,
    season_hint: str | None = None,
    confirmable_config: dict[str, Any] | None = None,
    source_info: dict[str, Any] | None = None,
    preview_request: dict[str, Any] | None = None,
    search_queries: list[str] | None = None,
    confidence: float = 0.9,
    needs_user_review: bool = False,
    applied_preferences: dict[str, Any] | None | object = _UNDEFINED,
    preference_hits: list[dict[str, Any]] | None | object = _UNDEFINED,
    preference_warnings: list[str] | None = None,
    review_hints: list[str] | None = None,
    enhanced_search_queries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    title = canonical_title or candidate_title or raw_title
    candidates = []
    if candidate_title:
        candidates.append(
            {
                "bangumi_id": item_id.replace("item-", "bangumi-"),
                "title": candidate_title,
                "mikan_url": f"https://mikan.example/Home/Bangumi/{item_id}",
                "poster_url": poster_url,
                "source_query": source_query or title,
                "aliases": [],
                "recommendation": None,
            }
        )
    item: dict[str, Any] = {
        "item_id": item_id,
        "raw_title": raw_title,
        "status": status,
        "canonical_title_candidates": [canonical_title] if canonical_title else [],
        "season_hint": season_hint,
        "search_queries": list(search_queries or [source_query or title]),
        "confidence": confidence,
        "needs_user_review": needs_user_review,
        "source": "fake",
        "candidates": candidates,
        "confirmable_config": confirmable_config,
        "source_info": source_info,
        "preview_request": preview_request,
    }
    if applied_preferences is not _UNDEFINED:
        item["applied_preferences"] = applied_preferences
    if preference_hits is not _UNDEFINED:
        item["preference_hits"] = preference_hits
    if preference_warnings is not None:
        item["preference_warnings"] = list(preference_warnings)
    if review_hints is not None:
        item["review_hints"] = list(review_hints)
    if enhanced_search_queries is not None:
        item["enhanced_search_queries"] = list(enhanced_search_queries)
    return item


def _preview_request(title: str, request_id: str) -> dict[str, Any]:
    generated = generate_request(EntryRequest(raw_title=title))
    if generated["request"] is None:
        # The rendered title is controlled by each API mock. Use an available
        # offline fixture only to supply the request-shaped preview payload.
        generated = generate_request(EntryRequest(raw_title="葬送的芙莉莲"))
    assert generated["request"] is not None
    return {**generated["request"], "request_id": request_id}


def _reviewable_batch_item(
    *,
    item_id: str = "item-review",
    preview_request: dict[str, Any] | None = None,
    confidence: float = 0.9,
    needs_user_review: bool = False,
    applied_preferences: dict[str, Any] | None | object = _UNDEFINED,
    preference_hits: list[dict[str, Any]] | None | object = _UNDEFINED,
    preference_warnings: list[str] | None = None,
    review_hints: list[str] | None = None,
    enhanced_search_queries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return _batch_item(
        item_id,
        "萌王S4",
        status="DRAFT",
        canonical_title="关于我转生变成史莱姆这档事 第四季",
        candidate_title="关于我转生变成史莱姆这档事 第四季",
        season_hint="S4",
        source_query="转生史莱姆 第四季",
        confirmable_config={
            "selected_subtitle_group": "桜都字幕组",
            "selected_rss_url": "https://mikan.example/RSS/Bangumi?token=secret-token",
            "filter_rule": {
                "must_contain": "1080p",
                "must_not_contain": "V2",
                "use_regex": False,
                "case_sensitive": False,
            },
            "effective_seed_names": ["史莱姆 S4 01 [1080p]"],
        },
        source_info={
            "raw_rss_xml": "<rss>secret-token</rss>",
            "cookie": "session-cookie",
            "token": "secret-token",
            "raw_response_body": "raw-body-secret",
            "rss_sources": [
                {
                    "subtitle_group": "桜都字幕组",
                    "rss_url": "https://mikan.example/RSS/Bangumi?token=secret-token",
                    "seed_names": [
                        "史莱姆 S4 01 [1080p]",
                        "史莱姆 S4 01 V2 [1080p]",
                    ],
                    "valid_seed_names": ["史莱姆 S4 01 [1080p]"],
                    "excluded_seed_names": [
                        {
                            "name": "史莱姆 S4 01 V2 [1080p]",
                            "reason": "命中排除规则：V2",
                        }
                    ],
                }
            ],
        },
        preview_request=preview_request or _preview_request(
            "关于我转生变成史莱姆这档事 第四季", "req-review"
        ),
        confidence=confidence,
        needs_user_review=needs_user_review,
        applied_preferences=applied_preferences,
        preference_hits=preference_hits,
        preference_warnings=preference_warnings,
        review_hints=review_hints,
        enhanced_search_queries=enhanced_search_queries,
    )


_QUEUE_STATUS_LABELS = {
    "READY_TO_SUBMIT": "待提交",
    "SUBMITTING": "提交中",
    "SUCCEEDED": "提交成功",
    "FAILED": "提交失败",
    "RETRYABLE": "可重试",
}


def _queue_item(
    item_id: str,
    request_id: str,
    title: str,
    status: str = "READY_TO_SUBMIT",
    *,
    attempts: int = 0,
    last_error: str | None = None,
    ab_result_summary: str | None = None,
    updated_at: str = "2026-08-19T00:00:00+00:00",
    batch_id: str = "batch-browser",
) -> dict[str, Any]:
    return {
        "queue_id": f"queue-{batch_id}",
        "batch_id": batch_id,
        "item_id": item_id,
        "request_id": request_id,
        "title": title,
        "status": status,
        "status_label": _QUEUE_STATUS_LABELS.get(status, status),
        "attempts": attempts,
        "last_error": last_error,
        "ab_result_summary": ab_result_summary,
        "created_at": "2026-08-19T00:00:00+00:00",
        "updated_at": updated_at,
    }


def _batch_submit_result(
    queue_items: list[dict[str, Any]],
    *,
    batch_id: str = "batch-browser",
) -> str:
    """Build a serialized batch submit response from post-submit queue items.

    Queue item ``status`` values (READY_TO_SUBMIT/SUBMITTING/SUCCEEDED/FAILED/
    RETRYABLE) are mapped to submit outcomes (succeeded/failed/retryable/skipped)
    the same way ``serialize_batch_submit_result`` counts them.
    """
    status_counts = {"succeeded": 0, "failed": 0, "retryable": 0, "skipped": 0}
    item_results = []
    for item in queue_items:
        outcome = {
            "SUCCEEDED": "succeeded",
            "FAILED": "failed",
            "RETRYABLE": "retryable",
        }.get(item["status"], "skipped")
        status_counts[outcome] += 1
        item_results.append(
            {
                "item_id": item["item_id"],
                "request_id": item["request_id"],
                "title": item["title"],
                "status": outcome,
                "reason": None,
                "error_type": None,
                "attempts": item["attempts"],
            }
        )
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
                "items": item_results,
                "summary": status_counts,
            },
        },
        ensure_ascii=False,
    )


def _batch_accept_result(
    items: list[dict[str, Any]],
    queue_items: list[dict[str, Any]] | None = None,
    *,
    batch_id: str = "batch-browser",
) -> str:
    queue_items = queue_items or []
    summary = {
        "accepted": 0,
        "already_accepted": 0,
        "unacceptable": 0,
        "failed": 0,
    }
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


def _accept_route_handler(accepted_ids: set[str], *, batch_id: str = "batch-browser"):
    """Build a Playwright route handler for the batch accept endpoint.

    Items whose ``item_id`` is in ``accepted_ids`` become ``accepted`` and are
    enqueued; every other item becomes ``unacceptable`` with the Chinese reason.
    """

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
                queue_items.append(
                    _queue_item(item_id, request_id, title, batch_id=batch_id)
                )
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


class TestBatchWorkbenchEntry:
    """Stage 19 batch workbench entry and draft-card rendering."""

    def test_production_batch_states_select_real_candidate_before_draft(
        self,
        page: Page,
        live_server_url: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The browser consumes the real parse serializer, not a DRAFT-shaped mock.

        Only the outbound MiKan transport is replaced.  The Flask batch parse
        endpoint, candidate serialization, and selected-candidate request
        generation all run through their production implementations.
        """

        class _MikanTransport:
            def __init__(self) -> None:
                self.requests: list[str] = []

            def get_text(self, url: str, *, timeout: float) -> str:
                del timeout
                self.requests.append(url)
                if "/Home/Search" in url:
                    query = unquote_plus(url.split("searchstr=", 1)[-1])
                    if "杖与剑" in query or "杖剑谭" in query:
                        raise ConnectionError("external MiKan is unavailable")
                    if "关于我转生" in query or "转生史莱姆" in query:
                        return (
                            '<article class="search-result">'
                            '<a href="/Home/Bangumi/4001">'
                            '关于我转生变成史莱姆这档事 第四季</a>'
                            '<img class="poster" src="/images/slime.jpg">'
                            "</article>"
                        )
                    return "<section class=\"search-result\"></section>"
                if "/Home/Bangumi/4001" in url:
                    return (
                        '<h1 class="bangumi-title">关于我转生变成史莱姆这档事 第四季</h1>'
                        '<section class="subgroup-section">'
                        '<h2 class="subgroup-name">Loli</h2>'
                        '<a href="/RSS/Bangumi?bangumiId=4001&subgroupid=10">RSS</a>'
                        "</section>"
                    )
                if "/RSS/Bangumi?bangumiId=4001&subgroupid=10" in url:
                    return (
                        "<rss><channel><item><title>史莱姆 S4 - 01 [1080p]</title>"
                        "<link>https://example.invalid/episode/1</link>"
                        "</item></channel></rss>"
                    )
                raise AssertionError(f"unexpected mocked MiKan URL: {url}")

        transport = _MikanTransport()

        def _create_client(config: MikanConfig):
            return create_mikan_client(config, transport=transport)

        monkeypatch.setattr(
            "mikan_engine.controllers.mikan_client.create_mikan_client",
            _create_client,
        )

        page.goto(f"{live_server_url}/index")
        page.get_by_role("tab", name="批量搜索").click()
        page.fill("#batch-raw-input", "萌王S4\n路哥S4\n杖剑谭S2")
        page.click("#batch-parse-submit")

        found = page.locator(".batch-draft-card", has_text="萌王S4")
        empty = page.locator(".batch-draft-card", has_text="路哥S4")
        failed = page.locator(".batch-draft-card", has_text="杖剑谭S2")
        expect(found.locator(".batch-card-status")).to_contain_text("找到候选")
        expect(found.locator(".batch-card-poster")).to_contain_text("待选择合集")
        expect(found.locator(".batch-card-expand")).to_be_enabled()
        expect(empty.locator(".batch-card-status")).to_contain_text("未找到候选")
        expect(empty.locator(".batch-card-expand")).to_be_disabled()
        expect(failed.locator(".batch-card-status")).to_contain_text("搜索失败")
        expect(failed.locator(".batch-card-expand")).to_be_disabled()

        found.locator(".batch-card-expand").click()
        choices = page.locator("#batch-candidate-choices")
        expect(choices.locator("img.candidate-poster")).to_have_count(1)
        choices.locator(".batch-candidate-select").click()
        expect(found.locator(".batch-card-status")).to_contain_text("草案")
        expect(found.locator(".batch-card-expand")).to_be_enabled()
        found.locator(".batch-card-expand").click()
        expect(page.locator("#request-detail-container")).to_contain_text("Loli")
        assert any("/Home/Search" in url for url in transport.requests)
        assert any("/Home/Bangumi/4001" in url for url in transport.requests)

    def test_found_candidate_selection_creates_only_that_batch_draft(
        self, page: Page, live_server_url: str
    ) -> None:
        """FOUND items use the normal MiKan preview chain; other states cannot act."""
        preview = _preview_request("关于我转生变成史莱姆这档事 第四季", "req-selected")
        captured: list[dict[str, Any]] = []

        def _parse(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(
                    [
                        _batch_item(
                            "item-found",
                            "萌王S4",
                            status="FOUND",
                            candidate_title="关于我转生变成史莱姆这档事 第四季",
                        ),
                        _batch_item("item-empty", "路哥S4", status="EMPTY"),
                        _batch_item("item-failed", "杖剑谭S2", status="FAILED"),
                    ]
                ),
            )

        def _create(route: Any, request: Any) -> None:
            if request.method != "POST":
                route.continue_()
                return
            captured.append(json.loads(request.post_data or "{}"))
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {"ok": True, "result": {"request": preview}},
                    ensure_ascii=False,
                ),
            )

        page.route("**/api/v1/batches/parse", _parse)
        page.route("**/api/v1/requests", _create)
        page.goto(f"{live_server_url}/index")
        page.get_by_role("tab", name="批量搜索").click()
        page.fill("#batch-raw-input", "萌王S4\n路哥S4\n杖剑谭S2")
        page.click("#batch-parse-submit")

        found = page.locator(".batch-draft-card", has_text="萌王S4")
        empty = page.locator(".batch-draft-card", has_text="路哥S4")
        failed = page.locator(".batch-draft-card", has_text="杖剑谭S2")
        expect(found.locator(".batch-candidate-select")).to_have_count(0)
        expect(empty.locator(".batch-candidate-select")).to_have_count(0)
        expect(failed.locator(".batch-candidate-select")).to_have_count(0)
        expect(empty.locator(".batch-card-expand")).to_be_disabled()
        expect(failed.locator(".batch-card-expand")).to_be_disabled()
        expect(empty.locator(".batch-card-checkbox")).to_be_disabled()
        expect(failed.locator(".batch-card-checkbox")).to_be_disabled()
        assert captured == []

        found.locator(".batch-card-expand").click()
        page.locator("#batch-candidate-choices .batch-candidate-select").click()
        expect(found.locator(".batch-card-status")).to_contain_text("草案")
        expect(found.locator(".batch-card-expand")).to_be_enabled()
        assert captured == [
            {
                "title": "关于我转生变成史莱姆这档事 第四季",
                "source": "mikan",
                "mikan_bangumi": "https://mikan.example/Home/Bangumi/item-found",
                "storage_dir": None,
                "save_request": False,
            }
        ]

    def test_batch_entry_is_visible_with_multiline_examples(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/index")
        page.get_by_role("tab", name="批量搜索").click()

        expect(page.locator("#batch-workbench-entry")).to_be_visible()
        expect(page.locator("#batch-parse-form")).to_be_visible()
        expect(page.locator("#batch-raw-input")).to_be_visible()
        expect(page.locator("#batch-parse-submit")).to_contain_text("获取批量草案")
        placeholder = page.locator("#batch-raw-input").get_attribute("placeholder") or ""
        assert "萌王S4" in placeholder
        assert "路哥S4" in placeholder
        assert "杖剑谭S2" in placeholder
        assert "邻家天使S2" in placeholder

    def test_batch_empty_input_is_validated_without_api_call(
        self, page: Page, live_server_url: str
    ) -> None:
        calls: list[str] = []

        def _capture(route: Any, request: Any) -> None:
            calls.append(request.url)
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"ok": false, "error_message": "should not be called"}',
            )

        page.route("**/api/v1/batches/parse", _capture)
        page.goto(f"{live_server_url}/index")
        page.get_by_role("tab", name="批量搜索").click()
        page.click("#batch-parse-submit")

        expect(page.locator("#batch-parse-error")).to_contain_text(
            "批量获取前必须输入至少一个番剧名称"
        )
        expect(page.locator("#batch-parse-result")).to_contain_text(
            "请修正批量输入后再获取草案"
        )
        assert calls == []

    def test_batch_submit_shows_loading_and_renders_card_grid(
        self, page: Page, live_server_url: str
    ) -> None:
        captured_payloads: list[dict[str, Any]] = []
        pending_routes: list[Any] = []

        def _fulfill(route: Any, request: Any) -> None:
            captured_payloads.append(json.loads(request.post_data or "{}"))
            # 保持请求挂起，由测试线程稍后 fulfill，从而稳定观察 transient
            # loading 状态（route handler 内 sleep 会阻塞 dispatcher，无法可靠观察）。
            pending_routes.append(route)

        page.route("**/api/v1/batches/parse", _fulfill)
        page.goto(f"{live_server_url}/index")
        page.get_by_role("tab", name="批量搜索").click()
        page.fill("#batch-raw-input", "萌王S4\n\n路哥S4")
        page.click("#batch-parse-submit")

        expect(page.locator("#batch-parse-result")).to_contain_text(
            "正在搜索 2 个批量条目的 MiKan 候选"
        )
        expect(page.locator("#batch-raw-input")).to_be_disabled()
        expect(page.locator("#batch-parse-submit")).to_be_disabled()
        expect(page.locator("#single-search-tab")).to_be_disabled()
        expect(page.locator("#batch-search-tab")).to_be_disabled()
        assert pending_routes
        pending_routes[0].fulfill(
            status=200,
            content_type="application/json",
            body=_batch_parse_result(
                [
                    _batch_item(
                        "item-1",
                        "萌王S4",
                        canonical_title="关于我转生变成史莱姆这档事 第四季",
                        candidate_title="关于我转生变成史莱姆这档事 第四季",
                        poster_url="https://mikan.example/poster.jpg",
                        source_query="萌王 第四季",
                    ),
                    _batch_item(
                        "item-2",
                        "路哥S4",
                        status="FAILED",
                    ),
                ]
            ),
        )
        expect(page.locator(".batch-draft-card")).to_have_count(2)
        result_text = page.locator("#batch-parse-result").inner_text()
        assert "萌王S4" in result_text
        assert "路哥S4" in result_text
        assert "关于我转生变成史莱姆这档事 第四季" in result_text
        assert "源名称：搜索词：萌王 第四季" in result_text
        assert "有效种子数：待展开" in result_text
        assert "已解析" in result_text
        assert "搜索失败" in result_text
        expect(page.locator(".batch-card-expand")).to_have_count(2)
        expect(page.locator("#page-notification")).to_contain_text("批量搜索完成")
        assert captured_payloads == [
            {"raw_input": "萌王S4\n\n路哥S4", "storage_dir": None}
        ]

    def test_batch_found_candidates_share_public_card_details_without_default_selection(
        self, page: Page, live_server_url: str
    ) -> None:
        item = _batch_item(
            "item-found", "萌王S4", status="FOUND", source_query="萌王 第四季"
        )
        item["candidates"] = [
            {
                "bangumi_id": "4001",
                "title": "关于我转生变成史莱姆这档事 第四季",
                "mikan_url": "https://mikan.example/Home/Bangumi/4001",
                "poster_url": "https://mikan.example/poster.jpg",
                "source_query": "萌王 第四季",
                "aliases": [],
            },
            {
                "bangumi_id": "4002",
                "title": "关于我转生变成史莱姆这档事 第三季",
                "mikan_url": "https://mikan.example/Home/Bangumi/4002",
                "poster_url": None,
                "source_query": "萌王 第四季",
                "aliases": [],
            },
        ]
        empty_item = _batch_item("item-empty", "路哥S4", status="EMPTY")
        failed_item = _batch_item("item-failed", "杖剑谭S2", status="FAILED")
        failed_item["error"] = {
            "error_type": "mikan_unavailable",
            "error_message": "MiKan 候选搜索暂时不可用",
        }

        page.route(
            "**/api/v1/batches/parse",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result([item, empty_item, failed_item]),
            ),
        )
        page.goto(f"{live_server_url}/index")
        page.get_by_role("tab", name="批量搜索").click()
        page.fill("#batch-raw-input", "萌王S4")
        page.click("#batch-parse-submit")

        card = page.locator(".batch-draft-card", has_text="萌王S4")
        card.locator(".batch-card-expand").click()
        choices = page.locator("#batch-candidate-choices .batch-candidate-list")
        expect(choices.locator(".candidate-card")).to_have_count(2)
        expect(choices).to_contain_text("MiKan ID: 4001")
        expect(choices).to_contain_text("MiKan ID: 4002")
        expect(choices).to_contain_text("暂无封面")
        # The fixture deliberately has no image route; the renderer replaces
        # failed poster loads with its stable public-only placeholder.
        expect(choices.locator("img.candidate-poster")).to_have_count(0)
        expect(choices.locator(".batch-candidate-select")).to_have_count(2)
        expect(card.locator(".batch-card-status")).to_contain_text("找到候选")
        expect(card.locator(".batch-card-expand")).to_be_enabled()
        expect(
            page.locator(".batch-draft-card", has_text="路哥S4").locator(
                ".batch-candidate-feedback"
            )
        ).to_contain_text("未找到匹配的 MiKan 合集")
        expect(
            page.locator(".batch-draft-card", has_text="杖剑谭S2").locator(
                ".batch-candidate-feedback"
            )
        ).to_contain_text("MiKan 候选搜索暂时不可用")

    def test_batch_card_delete_removes_only_selected_card(
        self, page: Page, live_server_url: str
    ) -> None:
        def _fulfill(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(
                    [
                        _batch_item("item-1", "萌王S4", canonical_title="史莱姆 第四季"),
                        _batch_item("item-2", "路哥S4", canonical_title="实力至上主义教室 第四季"),
                        _batch_item("item-3", "邻家天使S2", canonical_title="邻家天使 第二季"),
                    ]
                ),
            )

        page.route("**/api/v1/batches/parse", _fulfill)
        page.goto(f"{live_server_url}/index")
        page.get_by_role("tab", name="批量搜索").click()
        page.fill("#batch-raw-input", "萌王S4\n路哥S4\n邻家天使S2")
        page.click("#batch-parse-submit")

        expect(page.locator(".batch-draft-card")).to_have_count(3)
        page.locator(".batch-draft-card", has_text="路哥S4").locator(
            ".batch-card-delete"
        ).click()

        expect(page.locator(".batch-draft-card")).to_have_count(2)
        cards_text = page.locator("#batch-parse-result").inner_text()
        assert "萌王S4" in cards_text
        assert "邻家天使S2" in cards_text
        assert "路哥S4" not in cards_text
        assert "史莱姆 第四季" in cards_text
        assert "邻家天使 第二季" in cards_text

    def test_batch_draft_opens_shared_detail_with_filter_and_seed_summary(
        self, page: Page, live_server_url: str
    ) -> None:
        def _fulfill(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result([_reviewable_batch_item()]),
            )

        page.route("**/api/v1/batches/parse", _fulfill)
        page.goto(f"{live_server_url}/index")
        page.get_by_role("tab", name="批量搜索").click()
        page.fill("#batch-raw-input", "萌王S4")
        page.click("#batch-parse-submit")

        card = page.locator(".batch-draft-card")
        expect(card.locator(".batch-card-status")).to_contain_text("草案")
        expect(card.locator(".batch-card-review")).to_have_count(0)

        card.locator(".batch-card-expand").click()

        panel = page.locator("#request-detail-container")
        expect(panel).to_be_visible()
        expanded_text = panel.inner_text()
        assert "字幕组" in expanded_text
        assert "包含规则" in expanded_text
        assert "排除规则" in expanded_text
        assert "匹配模式" in expanded_text
        assert "普通字符" in expanded_text
        assert "大小写" in expanded_text
        assert "不区分大小写" in expanded_text
        assert "有效种子（当前选中字幕组：" in expanded_text
        assert "排除种子 (" in expanded_text

        expect(card.locator(".batch-card-expand")).to_have_attribute(
            "aria-controls", "request-detail-panel"
        )

    def test_batch_expanded_card_ignores_sensitive_fields(
        self, page: Page, live_server_url: str
    ) -> None:
        def _fulfill(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result([_reviewable_batch_item()]),
            )

        page.route("**/api/v1/batches/parse", _fulfill)
        page.goto(f"{live_server_url}/index")
        page.get_by_role("tab", name="批量搜索").click()
        page.fill("#batch-raw-input", "萌王S4")
        page.click("#batch-parse-submit")
        page.locator(".batch-draft-card .batch-card-expand").click()

        body_text = page.locator("body").inner_text()
        assert "secret-token" not in body_text
        assert "session-cookie" not in body_text
        assert "<rss>" not in body_text
        assert "raw-body-secret" not in body_text
        assert "https://mikan.example/RSS/Bangumi" not in body_text

    def test_search_results_do_not_persist_or_render_sensitive_transport_data(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """Stage 22 results stay public-only even if an upstream payload is noisy."""
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
            "item-public", "萌王S4", status="FOUND", candidate_title="史莱姆 第四季"
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
        item["candidates"][0].update(item["error"])

        def _fulfill(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result([item]),
            )

        page.route("**/api/v1/batches/parse", _fulfill)
        set_storage_preferences(page, storage_dir, save_request=False)
        page.goto(f"{live_server_url}/index")
        page.get_by_role("tab", name="批量搜索").click()
        page.fill("#batch-raw-input", "萌王S4")
        page.click("#batch-parse-submit")
        expect(page.locator("#search-results-panel")).to_be_visible()
        page.locator(".batch-draft-card", has_text="萌王S4").locator(
            ".batch-card-expand"
        ).click()
        expect(page.locator(".candidate-card")).to_have_count(1)

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

    def test_batch_card_modify_updates_only_current_card(
        self, page: Page, live_server_url: str
    ) -> None:
        first_preview = _preview_request("咒术回战", "req-batch-first")
        second_preview = _preview_request("咒术回战", "req-batch-second")

        def _fulfill(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(
                    [
                        _reviewable_batch_item(
                            item_id="item-first", preview_request=first_preview
                        ),
                        _batch_item(
                            "item-second",
                            "路哥S4",
                            status="DRAFT",
                            canonical_title="实力至上主义教室 第四季",
                            preview_request=second_preview,
                        ),
                    ]
                ),
            )

        page.route("**/api/v1/batches/parse", _fulfill)
        page.goto(f"{live_server_url}/index")
        page.get_by_role("tab", name="批量搜索").click()
        page.fill("#batch-raw-input", "萌王S4\n路哥S4")
        page.click("#batch-parse-submit")

        first_card = page.locator(".batch-draft-card", has_text="萌王S4")
        second_card = page.locator(".batch-draft-card", has_text="路哥S4")
        first_card.locator(".batch-card-expand").click()

        expect(page.locator("#detail-preview-edit-form")).to_be_visible()
        page.select_option("#preview-subtitle-group", value="喵萌")
        page.fill("#preview-must-not-contain", "V2")
        page.fill("#preview-folder-name", "BatchCustomFolder")
        page.click("button:has-text('应用修改')")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        expect(page.locator("#page-notification")).to_contain_text(
            "当前批量卡片已回流最新订阅草案"
        )
        first_card = page.locator(".batch-draft-card", has_text="萌王S4")
        second_card = page.locator(".batch-draft-card", has_text="路哥S4")
        expect(first_card.locator(".batch-card-seeds")).to_contain_text("1")
        first_text = page.locator("#request-detail-container").inner_text()
        assert "喵萌" in first_text
        assert "V2" in first_text

        second_card.locator(".batch-card-expand").click()
        second_text = page.locator("#request-detail-container").inner_text()
        # 第二张卡片必须保持独立，当前字幕组仍为原来的 Loli。
        expect(page.locator("#preview-subtitle-group")).to_have_value("Loli")
        assert "咒术回战" in second_text
        expect(second_card.locator(".batch-card-seeds")).to_contain_text("2")

    def test_batch_card_modify_failure_preserves_card_state(
        self, page: Page, live_server_url: str
    ) -> None:
        preview = _preview_request("咒术回战", "req-batch-fail")
        calls: list[dict[str, Any]] = []

        def _fulfill_batch(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(
                    [_reviewable_batch_item(preview_request=preview)]
                ),
            )

        def _fail_preview_modify(route: Any, request: Any) -> None:
            calls.append(json.loads(request.post_data or "{}"))
            route.fulfill(
                status=400,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": False,
                        "error_message": "不是合法正则",
                        "error_type": "invalid_filter_rule",
                    },
                    ensure_ascii=False,
                ),
            )

        page.route("**/api/v1/batches/parse", _fulfill_batch)
        page.route("**/api/v1/requests/preview-modify", _fail_preview_modify)
        page.goto(f"{live_server_url}/index")
        page.get_by_role("tab", name="批量搜索").click()
        page.fill("#batch-raw-input", "萌王S4")
        page.click("#batch-parse-submit")

        card = page.locator(".batch-draft-card")
        card.locator(".batch-card-expand").click()
        before = page.locator("#request-detail-container").inner_text()

        page.check("#preview-filter-use-regex")
        page.fill("#preview-must-not-contain", "[")
        page.click("button:has-text('应用修改')")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        expect(page.locator("#preview-edit-error")).to_contain_text("不是合法正则")
        expect(page.locator("#page-notification")).to_contain_text("修改失败")
        after = page.locator("#request-detail-container").inner_text()
        assert "咒术回战" in before
        assert "咒术回战" in after
        assert calls and calls[0]["request"]["request_id"] == "req-batch-fail"

    def test_batch_card_accept_updates_only_current_card(
        self, page: Page, live_server_url: str
    ) -> None:
        first_preview = _preview_request("咒术回战", "req-batch-accept")
        second_preview = _preview_request("咒术回战", "req-batch-other")
        saved_calls: list[dict[str, Any]] = []
        accept_calls: list[dict[str, Any]] = []

        def _fulfill_batch(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(
                    [
                        _reviewable_batch_item(
                            item_id="item-accept", preview_request=first_preview
                        ),
                        _batch_item(
                            "item-other",
                            "路哥S4",
                            status="DRAFT",
                            canonical_title="实力至上主义教室 第四季",
                            preview_request=second_preview,
                        ),
                    ]
                ),
            )

        def _save_preview(route: Any, request: Any) -> None:
            payload = json.loads(request.post_data or "{}")
            saved_calls.append(payload)
            saved = dict(payload["request"])
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": True,
                        "result": {
                            "request": saved,
                            "summary": {"request_id": saved["request_id"]},
                        },
                    },
                    ensure_ascii=False,
                ),
            )

        def _accept(route: Any, request: Any) -> None:
            accept_calls.append(json.loads(request.post_data or "{}"))
            _accept_route_handler({"item-accept"})(route, request)

        page.route("**/api/v1/batches/parse", _fulfill_batch)
        page.route("**/api/v1/requests/preview-save", _save_preview)
        page.route("**/api/v1/batches/batch-browser/accept*", _accept)
        page.goto(f"{live_server_url}/index")
        page.get_by_role("tab", name="批量搜索").click()
        page.fill("#batch-raw-input", "萌王S4\n路哥S4")
        page.click("#batch-parse-submit")

        first_card = page.locator(".batch-draft-card", has_text="萌王S4")
        second_card = page.locator(".batch-draft-card", has_text="路哥S4")
        first_card.locator(".batch-card-expand").click()
        page.once("dialog", lambda dialog: dialog.accept())
        page.locator(".batch-detail-accept").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        first_card = page.locator(".batch-draft-card", has_text="萌王S4")
        second_card = page.locator(".batch-draft-card", has_text="路哥S4")
        expect(first_card.locator(".batch-card-status")).to_contain_text("已接受")
        expect(first_card.locator(".batch-card-queue-status")).to_contain_text("待提交")
        expect(first_card.locator(".batch-card-delete")).to_be_hidden()
        expect(first_card.locator(".batch-card-expand")).to_be_disabled()
        expect(second_card.locator(".batch-card-status")).to_contain_text("草案")
        expect(second_card.locator(".batch-card-delete")).to_be_visible()
        assert saved_calls and saved_calls[0]["request"]["request_id"] == "req-batch-accept"
        assert accept_calls and accept_calls[0]["items"][0]["item_id"] == "item-accept"
        assert accept_calls[0]["storage_dir"] is None
        assert "item_ids" not in accept_calls[0]

    def test_accept_records_user_correction(
        self,
        page: Page,
        live_server_url: str,
        _isolate_corrections_save: list[dict[str, Any]],
    ) -> None:
        """US-155 closure: accepting a card records the user-confirmed
        raw_title -> canonical_title correction through the corrections API, so
        later batch inputs reuse the confirmed title/search query."""
        first_preview = _preview_request("咒术回战", "req-batch-corr")

        def _fulfill_batch(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(
                    [
                        _reviewable_batch_item(
                            item_id="item-corr", preview_request=first_preview
                        )
                    ]
                ),
            )

        def _save_preview(route: Any, request: Any) -> None:
            payload = json.loads(request.post_data or "{}")
            saved = dict(payload["request"])
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": True,
                        "result": {
                            "request": saved,
                            "summary": {"request_id": saved["request_id"]},
                        },
                    },
                    ensure_ascii=False,
                ),
            )

        page.route("**/api/v1/batches/parse", _fulfill_batch)
        page.route("**/api/v1/requests/preview-save", _save_preview)
        page.route("**/api/v1/batches/batch-browser/accept*", _accept_route_handler({"item-corr"}))
        page.goto(f"{live_server_url}/index")
        page.get_by_role("tab", name="批量搜索").click()
        page.fill("#batch-raw-input", "萌王S4")
        page.click("#batch-parse-submit")

        first_card = page.locator(".batch-draft-card", has_text="萌王S4")
        first_card.locator(".batch-card-expand").click()
        page.once("dialog", lambda dialog: dialog.accept())
        page.locator(".batch-detail-accept").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        expect(first_card.locator(".batch-card-status")).to_contain_text("已接受")
        # The corrections API received the confirmed mapping.
        assert _isolate_corrections_save, "corrections API was not called"
        correction = _isolate_corrections_save[0]["correction"]
        assert correction["raw_title"] == "萌王S4"
        assert correction["canonical_title"] == "关于我转生变成史莱姆这档事 第四季"
        assert correction["season_hint"] == "S4"
        assert correction["query_correction"] == "关于我转生变成史莱姆这档事 第四季"
        # Only non-sensitive public fields are submitted.
        body = json.dumps(_isolate_corrections_save[0], ensure_ascii=False)
        assert "secret-token" not in body
        assert "token" not in body

    def test_batch_card_grid_uses_single_column_on_narrow_screen(
        self, page: Page, live_server_url: str
    ) -> None:
        def _fulfill(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(
                    [
                        _batch_item("item-1", "萌王S4"),
                        _batch_item("item-2", "路哥S4"),
                    ]
                ),
            )

        page.set_viewport_size({"width": 390, "height": 760})
        page.route("**/api/v1/batches/parse", _fulfill)
        page.goto(f"{live_server_url}/index")
        page.get_by_role("tab", name="批量搜索").click()
        page.fill("#batch-raw-input", "萌王S4\n路哥S4")
        page.click("#batch-parse-submit")

        expect(page.locator(".batch-draft-card")).to_have_count(2)
        column_count = page.locator(".batch-card-grid").evaluate(
            "el => getComputedStyle(el).gridTemplateColumns.split(' ').length"
        )
        assert column_count == 1

    def test_batch_card_grid_is_scrollable_for_long_lists(
        self, page: Page, live_server_url: str
    ) -> None:
        items = [
            _batch_item(
                f"item-{index}",
                f"测试番剧{index}",
                canonical_title=f"测试番剧 第{index}季",
            )
            for index in range(1, 25)
        ]

        def _fulfill(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(items),
            )

        page.route("**/api/v1/batches/parse", _fulfill)
        page.goto(f"{live_server_url}/index")
        page.get_by_role("tab", name="批量搜索").click()
        page.fill("#batch-raw-input", "\n".join(item["raw_title"] for item in items))
        page.click("#batch-parse-submit")

        wrapper = page.locator(".batch-card-grid-wrapper")
        expect(page.locator(".batch-draft-card")).to_have_count(24)
        scroll_metrics = wrapper.evaluate(
            "el => ({clientHeight: el.clientHeight, scrollHeight: el.scrollHeight})"
        )
        assert scroll_metrics["scrollHeight"] > scroll_metrics["clientHeight"]

    def test_found_candidates_use_one_anchored_popover_with_keyboard_closure(
        self, page: Page, live_server_url: str
    ) -> None:
        """US-168: candidate choices overlay the grid and return focus on close."""
        items = [
            _batch_item(
                "item-one", "萌王S4", status="FOUND", candidate_title="史莱姆 第四季"
            ),
            _batch_item(
                "item-two", "路哥S4", status="FOUND", candidate_title="实力至上主义教室 第四季"
            ),
        ]

        page.route(
            "**/api/v1/batches/parse",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(items),
            ),
        )
        page.goto(f"{live_server_url}/index")
        page.get_by_role("tab", name="批量搜索").click()
        page.fill("#batch-raw-input", "萌王S4\n路哥S4")
        page.click("#batch-parse-submit")

        grid = page.locator(".batch-card-grid")
        height_before = grid.bounding_box()["height"]
        first = page.locator('.batch-draft-card[data-item-id="item-one"]')
        second = page.locator('.batch-draft-card[data-item-id="item-two"]')
        first_trigger = first.locator(".batch-card-expand")
        second_trigger = second.locator(".batch-card-expand")
        first_trigger.click()

        popover = page.locator("#batch-candidate-choices")
        expect(popover).to_have_attribute("role", "dialog")
        expect(first_trigger).to_have_attribute("aria-expanded", "true")
        assert grid.bounding_box()["height"] == height_before
        geometry = popover.evaluate(
            "el => ({position: getComputedStyle(el).position, left: el.getBoundingClientRect().left, right: el.getBoundingClientRect().right, viewport: window.innerWidth})"
        )
        assert geometry["position"] == "fixed"
        assert geometry["left"] >= 0
        assert geometry["right"] <= geometry["viewport"]
        expect(popover.locator(".batch-candidate-close")).to_be_focused()

        second_trigger.click()
        expect(page.locator("#batch-candidate-choices")).to_have_count(1)
        expect(first_trigger).to_have_attribute("aria-expanded", "false")
        expect(second_trigger).to_have_attribute("aria-expanded", "true")

        page.keyboard.press("Escape")
        expect(page.locator("#batch-candidate-choices")).to_have_count(0)
        expect(second_trigger).to_be_focused()

        first_trigger.click()
        page.locator(".batch-card-source").first.click()
        expect(page.locator("#batch-candidate-choices")).to_have_count(0)


class TestBatchAcceptWorkbench:
    """Stage 20 batch accept workbench: single, selected, accept-all, and reasons."""

    def test_batch_selected_accept_only_accepts_checked_cards(
        self, page: Page, live_server_url: str
    ) -> None:
        previews = [
            _preview_request("咒术回战", f"req-batch-{index}") for index in (1, 2, 3)
        ]
        accept_calls: list[dict[str, Any]] = []

        def _fulfill_batch(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(
                    [
                        _reviewable_batch_item(
                            item_id="item-1", preview_request=previews[0]
                        ),
                        _batch_item(
                            "item-2",
                            "路哥S4",
                            status="DRAFT",
                            canonical_title="实力至上主义教室 第四季",
                            preview_request=previews[1],
                        ),
                        _batch_item(
                            "item-3",
                            "邻家天使S2",
                            status="DRAFT",
                            canonical_title="邻家天使 第二季",
                            preview_request=previews[2],
                        ),
                    ]
                ),
            )

        def _save_preview(route: Any, request: Any) -> None:
            payload = json.loads(request.post_data or "{}")
            saved = dict(payload["request"])
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": True,
                        "result": {
                            "request": saved,
                            "summary": {"request_id": saved["request_id"]},
                        },
                    },
                    ensure_ascii=False,
                ),
            )

        def _accept(route: Any, request: Any) -> None:
            accept_calls.append(json.loads(request.post_data or "{}"))
            _accept_route_handler({"item-1", "item-3"})(route, request)

        page.route("**/api/v1/batches/parse", _fulfill_batch)
        page.route("**/api/v1/requests/preview-save", _save_preview)
        page.route("**/api/v1/batches/batch-browser/accept*", _accept)
        page.goto(f"{live_server_url}/index")
        page.get_by_role("tab", name="批量搜索").click()
        page.fill("#batch-raw-input", "萌王S4\n路哥S4\n邻家天使S2")
        page.click("#batch-parse-submit")

        expect(page.locator("#batch-accept-toolbar")).to_be_visible()
        expect(page.locator("#batch-accept-selected-count")).to_contain_text(
            "已选择 0 项"
        )
        expect(page.locator("#batch-accept-submit")).to_be_disabled()

        first_card = page.locator(".batch-draft-card", has_text="萌王S4")
        third_card = page.locator(".batch-draft-card", has_text="邻家天使S2")
        first_card.locator(".batch-card-checkbox").check()
        third_card.locator(".batch-card-checkbox").check()

        expect(page.locator("#batch-accept-selected-count")).to_contain_text(
            "已选择 2 项"
        )
        expect(page.locator("#batch-accept-submit")).to_be_enabled()

        page.once("dialog", lambda dialog: dialog.accept())
        page.click("#batch-accept-submit")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        expect(page.locator("#page-notification")).to_contain_text("批量接受成功")
        first_card = page.locator(".batch-draft-card", has_text="萌王S4")
        second_card = page.locator(".batch-draft-card", has_text="路哥S4")
        third_card = page.locator(".batch-draft-card", has_text="邻家天使S2")
        expect(first_card.locator(".batch-card-status")).to_contain_text("已接受")
        expect(first_card.locator(".batch-card-queue-status")).to_contain_text("待提交")
        expect(third_card.locator(".batch-card-status")).to_contain_text("已接受")
        expect(third_card.locator(".batch-card-queue-status")).to_contain_text("待提交")
        expect(second_card.locator(".batch-card-status")).to_contain_text("草案")

        payload = accept_calls[-1]
        assert payload["item_ids"] == ["item-1", "item-3"]
        assert [item["item_id"] for item in payload["items"]] == [
            "item-1",
            "item-3",
        ]

    def test_batch_accept_all_accepts_reviewable_and_shows_failed_reason(
        self, page: Page, live_server_url: str
    ) -> None:
        preview = _preview_request("咒术回战", "req-batch-ok")
        accept_calls: list[dict[str, Any]] = []

        def _fulfill_batch(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(
                    [
                        _reviewable_batch_item(
                            item_id="item-ok", preview_request=preview
                        ),
                        _batch_item("item-fail", "路哥S4", status="FAILED"),
                    ]
                ),
            )

        def _save_preview(route: Any, request: Any) -> None:
            payload = json.loads(request.post_data or "{}")
            saved = dict(payload["request"])
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": True,
                        "result": {
                            "request": saved,
                            "summary": {"request_id": saved["request_id"]},
                        },
                    },
                    ensure_ascii=False,
                ),
            )

        def _accept(route: Any, request: Any) -> None:
            accept_calls.append(json.loads(request.post_data or "{}"))
            _accept_route_handler({"item-ok"})(route, request)

        page.route("**/api/v1/batches/parse", _fulfill_batch)
        page.route("**/api/v1/requests/preview-save", _save_preview)
        page.route("**/api/v1/batches/batch-browser/accept*", _accept)
        page.goto(f"{live_server_url}/index")
        page.get_by_role("tab", name="批量搜索").click()
        page.fill("#batch-raw-input", "萌王S4\n路哥S4")
        page.click("#batch-parse-submit")

        expect(page.locator(".batch-draft-card")).to_have_count(2)
        page.once("dialog", lambda dialog: dialog.accept())
        page.click("#batch-accept-all")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        ok_card = page.locator(".batch-draft-card", has_text="萌王S4")
        fail_card = page.locator(".batch-draft-card", has_text="路哥S4")
        expect(ok_card.locator(".batch-card-status")).to_contain_text("已接受")
        expect(ok_card.locator(".batch-card-queue-status")).to_contain_text("待提交")
        expect(fail_card.locator(".batch-card-status")).to_contain_text("搜索失败")
        expect(fail_card.locator(".batch-card-reason")).to_contain_text(
            "无法接受：卡片缺少订阅草案，无法接受"
        )
        expect(page.locator("#page-notification")).to_contain_text("批量接受完成")

        payload = accept_calls[-1]
        assert "item_ids" not in payload
        assert [item["item_id"] for item in payload["items"]] == [
            "item-ok",
            "item-fail",
        ]

    def test_batch_accept_select_all_checkbox_and_count(
        self, page: Page, live_server_url: str
    ) -> None:
        def _fulfill(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(
                    [
                        _reviewable_batch_item(item_id="item-1", preview_request=_preview_request("咒术回战", "req-sel-1")),
                        _batch_item("item-2", "路哥S4", status="DRAFT", canonical_title="实力至上主义教室 第四季", preview_request=_preview_request("咒术回战", "req-sel-2")),
                        _batch_item("item-3", "邻家天使S2", status="DRAFT", canonical_title="邻家天使 第二季", preview_request=_preview_request("咒术回战", "req-sel-3")),
                    ]
                ),
            )

        page.route("**/api/v1/batches/parse", _fulfill)
        page.goto(f"{live_server_url}/index")
        page.get_by_role("tab", name="批量搜索").click()
        page.fill("#batch-raw-input", "萌王S4\n路哥S4\n邻家天使S2")
        page.click("#batch-parse-submit")

        expect(page.locator(".batch-card-checkbox")).to_have_count(3)
        page.check("#batch-select-all-checkbox")
        expect(page.locator("#batch-accept-selected-count")).to_contain_text(
            "已选择 3 项"
        )
        expect(page.locator("#batch-accept-submit")).to_be_enabled()

        page.uncheck("#batch-select-all-checkbox")
        expect(page.locator("#batch-accept-selected-count")).to_contain_text(
            "已选择 0 项"
        )
        expect(page.locator("#batch-accept-submit")).to_be_disabled()

        # 单卡取消勾选后计数同步减少
        page.check("#batch-select-all-checkbox")
        first_card = page.locator(".batch-draft-card", has_text="萌王S4")
        first_card.locator(".batch-card-checkbox").uncheck()
        expect(page.locator("#batch-accept-selected-count")).to_contain_text(
            "已选择 2 项"
        )
        expect(page.locator("#batch-select-all-checkbox")).not_to_be_checked()

    def test_batch_accept_disables_controls_while_in_flight(
        self, page: Page, live_server_url: str
    ) -> None:
        preview = _preview_request("咒术回战", "req-batch-loading")

        def _fulfill_batch(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(
                    [_reviewable_batch_item(preview_request=preview)],
                    batch_id="test-slow-accept",
                ),
            )

        def _save_preview(route: Any, request: Any) -> None:
            payload = json.loads(request.post_data or "{}")
            saved = dict(payload["request"])
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": True,
                        "result": {
                            "request": saved,
                            "summary": {"request_id": saved["request_id"]},
                        },
                    },
                    ensure_ascii=False,
                ),
            )

        page.route("**/api/v1/batches/parse", _fulfill_batch)
        page.route("**/api/v1/requests/preview-save", _save_preview)
        # 接受端点不 mock：由 conftest 的 test-slow-accept 延迟路由真实返回 400，
        # 让浏览器 fetch 保持 ~1.5s，从而稳定观察 in-flight 的 loading/disabled 状态。
        page.goto(f"{live_server_url}/index")
        page.get_by_role("tab", name="批量搜索").click()
        page.fill("#batch-raw-input", "萌王S4")
        page.click("#batch-parse-submit")
        page.once("dialog", lambda dialog: dialog.accept())
        page.click("#batch-accept-all")

        # 提交中：接受入口与选择控件进入 loading/disabled 状态
        expect(page.locator("#batch-accept-all")).to_contain_text("正在接受...")
        expect(page.locator(".batch-card-checkbox")).to_be_disabled()
        expect(page.locator("#batch-accept-all")).to_be_disabled()
        expect(page.locator("#batch-accept-submit")).to_be_disabled()

        # 失败后恢复可操作：按钮文案还原、重新启用、卡片保持草案
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
        expect(page.locator("#page-notification")).to_contain_text("接受失败")
        expect(page.locator("#batch-accept-all")).to_contain_text("全接受")
        expect(page.locator("#batch-accept-all")).to_be_enabled()
        expect(page.locator(".batch-card-checkbox")).to_be_enabled()
        expect(page.locator(".batch-card-status")).to_contain_text("草案")

    def test_batch_accept_partial_failure_keeps_other_cards_unchanged(
        self, page: Page, live_server_url: str
    ) -> None:
        first_preview = _preview_request("咒术回战", "req-batch-partial-ok")
        second_preview = _preview_request("咒术回战", "req-batch-partial-fail")

        def _fulfill_batch(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result(
                    [
                        _reviewable_batch_item(
                            item_id="item-ok", preview_request=first_preview
                        ),
                        _batch_item(
                            "item-fail",
                            "路哥S4",
                            status="DRAFT",
                            canonical_title="实力至上主义教室 第四季",
                            preview_request=second_preview,
                        ),
                    ]
                ),
            )

        def _save_preview(route: Any, request: Any) -> None:
            payload = json.loads(request.post_data or "{}")
            saved = dict(payload["request"])
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": True,
                        "result": {
                            "request": saved,
                            "summary": {"request_id": saved["request_id"]},
                        },
                    },
                    ensure_ascii=False,
                ),
            )

        def _accept(route: Any, request: Any) -> None:
            _accept_route_handler({"item-ok"})(route, request)

        page.route("**/api/v1/batches/parse", _fulfill_batch)
        page.route("**/api/v1/requests/preview-save", _save_preview)
        page.route("**/api/v1/batches/batch-browser/accept*", _accept)
        page.goto(f"{live_server_url}/index")
        page.get_by_role("tab", name="批量搜索").click()
        page.fill("#batch-raw-input", "萌王S4\n路哥S4")
        page.click("#batch-parse-submit")

        page.once("dialog", lambda dialog: dialog.accept())
        page.click("#batch-accept-all")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        ok_card = page.locator(".batch-draft-card", has_text="萌王S4")
        fail_card = page.locator(".batch-draft-card", has_text="路哥S4")
        expect(ok_card.locator(".batch-card-status")).to_contain_text("已接受")
        expect(ok_card.locator(".batch-card-queue-status")).to_contain_text("待提交")
        # 失败卡片保持草案状态，仅新增中文原因
        expect(fail_card.locator(".batch-card-status")).to_contain_text("草案")
        expect(fail_card.locator(".batch-card-reason")).to_contain_text(
            "无法接受：卡片缺少订阅草案，无法接受"
        )
        expect(fail_card.locator(".batch-card-expand")).to_be_enabled()


def _accept_all_reviewable(
    page: Page,
    live_server_url: str,
    item_ids: list[str],
    *,
    batch_id: str = "batch-browser",
) -> None:
    """Load one reviewable card per item id and accept all via the accept API.

    The accept endpoint enqueues every accepted card, so after this helper
    returns the queue panel is populated with READY_TO_SUBMIT items. The
    queue GET is mocked to ``queue: None`` because the accept response itself
    carries the enqueued items (the real storage has no queue to read).
    """
    previews = {
        item_id: _preview_request("咒术回战", f"req-{item_id}")
        for item_id in item_ids
    }
    parse_items = [
        _reviewable_batch_item(item_id=item_id, preview_request=previews[item_id])
        for item_id in item_ids
    ]

    def _fulfill_batch(route: Any, request: Any) -> None:
        route.fulfill(
            status=200,
            content_type="application/json",
            body=_batch_parse_result(parse_items, batch_id=batch_id),
        )

    def _save_preview(route: Any, request: Any) -> None:
        payload = json.loads(request.post_data or "{}")
        saved = dict(payload["request"])
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "ok": True,
                    "result": {
                        "request": saved,
                        "summary": {"request_id": saved["request_id"]},
                    },
                },
                ensure_ascii=False,
            ),
        )

    def _queue_get(route: Any, request: Any) -> None:
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "ok": True,
                    "result": {
                        "batch_id": batch_id,
                        "queue": None,
                    },
                },
                ensure_ascii=False,
            ),
        )

    page.route("**/api/v1/batches/parse", _fulfill_batch)
    page.route("**/api/v1/requests/preview-save", _save_preview)
    page.route(
        f"**/api/v1/batches/{batch_id}/accept*",
        _accept_route_handler(set(item_ids), batch_id=batch_id),
    )
    page.route(f"**/api/v1/batches/{batch_id}/queue*", _queue_get)
    page.goto(f"{live_server_url}/index")
    page.get_by_role("tab", name="批量搜索").click()
    page.fill(
        "#batch-raw-input",
        "\n".join(f"番剧{index}" for index in range(1, len(item_ids) + 1)),
    )
    page.click("#batch-parse-submit")
    page.once("dialog", lambda dialog: dialog.accept())
    page.click("#batch-accept-all")
    page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)


class TestBatchQueuePanel:
    """Stage 20 pre-submission queue result panel (US-147).

    Covers queue display after accept, submit success / partial failure with
    per-item status refresh, sensitive input clearing, and refresh recovery
    of recorded result summaries.
    """

    def test_batch_queue_panel_shows_items_after_accept(
        self, page: Page, live_server_url: str
    ) -> None:
        _accept_all_reviewable(page, live_server_url, ["item-queue"])

        expect(page.locator("#batch-queue-panel")).to_be_visible()
        expect(page.locator("#batch-queue-count")).to_contain_text("队列中 1 项")
        expect(page.locator(".batch-queue-item")).to_have_count(1)
        item = page.locator('.batch-queue-item[data-item-id="item-queue"]')
        expect(item.locator(".batch-queue-item-title")).to_contain_text(
            "关于我转生变成史莱姆这档事 第四季"
        )
        expect(item.locator(".batch-queue-status")).to_contain_text("待提交")
        expect(item.locator(".batch-queue-item-meta")).to_contain_text(
            "尝试次数：0"
        )
        expect(item.locator(".batch-queue-item-summary")).to_contain_text(
            "尚无结果摘要"
        )
        expect(page.locator("#batch-queue-refresh")).to_be_enabled()
        expect(page.locator("#batch-queue-submit-form")).to_be_visible()
        # 接受后 URL 携带公开的 batch_id，供刷新恢复使用
        assert "batch_id=batch-browser" in page.url

    def test_batch_queue_submit_success_clears_sensitive_inputs(
        self, page: Page, live_server_url: str
    ) -> None:
        submitted: list[dict[str, Any]] = []
        succeeded = _queue_item(
            "item-queue",
            "req-item-queue",
            "关于我转生变成史莱姆这档事 第四季",
            status="SUCCEEDED",
            attempts=1,
            ab_result_summary="Auto Bangumi 已接受该订阅方案",
            updated_at="2026-08-19T00:01:00+00:00",
        )

        def _submit(route: Any, request: Any) -> None:
            submitted.append(json.loads(request.post_data or "{}"))
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_submit_result([succeeded]),
            )

        page.route("**/api/v1/batches/batch-browser/submit*", _submit)
        _accept_all_reviewable(page, live_server_url, ["item-queue"])

        page.fill("#batch-queue-ab-endpoint", "https://ab.example/api")
        page.fill("#batch-queue-ab-token", "ab-secret-token")
        page.check("#batch-queue-ab-fallback-enabled")
        page.check("#batch-queue-ab-confirm")
        page.click("#batch-queue-submit-button")

        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
        expect(page.locator("#page-notification")).to_contain_text("批量提交成功")
        expect(page.locator("#batch-queue-submit-button")).to_contain_text("提交队列")
        expect(page.locator("#batch-queue-submit-button")).to_be_enabled()

        # 成功后清空敏感输入与确认；fallback 是公开非敏感偏好，保持勾选
        expect(page.locator("#batch-queue-ab-endpoint")).to_have_value("")
        expect(page.locator("#batch-queue-ab-token")).to_have_value("")
        expect(page.locator("#batch-queue-ab-confirm")).not_to_be_checked()
        expect(page.locator("#batch-queue-ab-fallback-enabled")).to_be_checked()

        item = page.locator('.batch-queue-item[data-item-id="item-queue"]')
        expect(item.locator(".batch-queue-status")).to_contain_text("提交成功")
        expect(item.locator(".batch-queue-item-meta")).to_contain_text(
            "尝试次数：1"
        )
        expect(item.locator(".batch-queue-item-summary")).to_contain_text(
            "结果：Auto Bangumi 已接受该订阅方案"
        )
        expect(page.locator("#batch-queue-submit-result")).to_contain_text(
            "提交成功 1 项"
        )
        # 成功项目不显示重试按钮（单项重试是 US-148）
        expect(page.locator(".batch-queue-item-retry")).to_have_count(0)
        expect(page.locator(".batch-queue-retry")).to_have_count(0)
        # 批量卡片 chip 同步为提交成功
        card = page.locator(
            ".batch-draft-card", has_text="关于我转生变成史莱姆这档事 第四季"
        )
        expect(card.locator(".batch-card-queue-status")).to_contain_text("提交成功")

        payload = submitted[0]
        assert payload["ab_config"]["endpoint"] == "https://ab.example/api"
        assert payload["ab_config"]["token"] == "ab-secret-token"
        assert payload["ab_config"]["fallback_enabled"] is True
        assert payload["confirm"] is True
        # 敏感配置不进入 DOM
        body_text = page.locator("body").inner_text()
        assert "ab-secret-token" not in body_text

    def test_batch_queue_submit_partial_failure_refreshes_each_item(
        self, page: Page, live_server_url: str
    ) -> None:
        ok_item = _queue_item(
            "item-ok",
            "req-item-ok",
            "关于我转生变成史莱姆这档事 第四季",
            status="SUCCEEDED",
            attempts=1,
            ab_result_summary="Auto Bangumi 已接受该订阅方案",
        )
        fail_item = _queue_item(
            "item-fail",
            "req-item-fail",
            "实力至上主义教室 第四季",
            status="FAILED",
            attempts=1,
            last_error="订阅方案已不存在，跳过提交",
        )
        retryable_item = _queue_item(
            "item-retry",
            "req-item-retry",
            "邻家天使 第二季",
            status="RETRYABLE",
            attempts=2,
            last_error="Auto Bangumi 暂时不可用，稍后重试",
        )

        def _submit(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_submit_result([ok_item, fail_item, retryable_item]),
            )

        page.route("**/api/v1/batches/batch-browser/submit*", _submit)
        _accept_all_reviewable(
            page, live_server_url, ["item-ok", "item-fail", "item-retry"]
        )
        page.fill("#batch-queue-ab-endpoint", "https://ab.example/api")
        page.fill("#batch-queue-ab-token", "ab-secret-token")
        page.check("#batch-queue-ab-confirm")
        page.click("#batch-queue-submit-button")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        # 每项状态独立刷新
        ok = page.locator('.batch-queue-item[data-item-id="item-ok"]')
        fail = page.locator('.batch-queue-item[data-item-id="item-fail"]')
        retryable = page.locator('.batch-queue-item[data-item-id="item-retry"]')
        expect(ok.locator(".batch-queue-status")).to_contain_text("提交成功")
        expect(fail.locator(".batch-queue-status")).to_contain_text("提交失败")
        expect(retryable.locator(".batch-queue-status")).to_contain_text("可重试")
        # 成功项显示结果摘要，失败项显示脱敏错误摘要
        expect(ok.locator(".batch-queue-item-summary")).to_contain_text(
            "结果：Auto Bangumi 已接受该订阅方案"
        )
        expect(fail.locator(".batch-queue-item-summary")).to_contain_text(
            "错误：订阅方案已不存在，跳过提交"
        )
        expect(retryable.locator(".batch-queue-item-summary")).to_contain_text(
            "错误：Auto Bangumi 暂时不可用，稍后重试"
        )
        expect(retryable.locator(".batch-queue-item-meta")).to_contain_text(
            "尝试次数：2"
        )
        # 成功项不显示重试按钮
        expect(ok.locator(".batch-queue-item-retry")).to_have_count(0)
        expect(page.locator(".batch-queue-retry")).to_have_count(0)
        # 结果与通知反映成功 + 失败 + 可重试计数
        expect(page.locator("#batch-queue-submit-result")).to_contain_text(
            "提交成功 1 项"
        )
        expect(page.locator("#batch-queue-submit-result")).to_contain_text(
            "提交失败 1 项"
        )
        expect(page.locator("#batch-queue-submit-result")).to_contain_text(
            "可重试 1 项"
        )
        expect(page.locator("#page-notification")).to_contain_text("批量提交完成")
        # 批量卡片 chip 独立同步
        ok_card = page.locator('.batch-draft-card[data-item-id="item-ok"]')
        expect(ok_card.locator(".batch-card-queue-status")).to_contain_text(
            "提交成功"
        )

    def test_batch_queue_submit_failure_preserves_inputs_for_retry(
        self, page: Page, live_server_url: str
    ) -> None:
        def _submit_fail(route: Any, request: Any) -> None:
            route.fulfill(
                status=400,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": False,
                        "error_message": "Auto Bangumi 连接失败",
                        "error_type": "ab_connection_failed",
                    },
                    ensure_ascii=False,
                ),
            )

        page.route("**/api/v1/batches/batch-browser/submit*", _submit_fail)
        _accept_all_reviewable(page, live_server_url, ["item-queue"])
        page.fill("#batch-queue-ab-endpoint", "https://ab.example/api")
        page.fill("#batch-queue-ab-token", "ab-secret-token")
        page.check("#batch-queue-ab-confirm")
        page.click("#batch-queue-submit-button")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        # HTTP 级失败：保留敏感输入与确认，便于重试
        expect(page.locator("#batch-queue-ab-endpoint")).to_have_value(
            "https://ab.example/api"
        )
        expect(page.locator("#batch-queue-ab-token")).to_have_value(
            "ab-secret-token"
        )
        expect(page.locator("#batch-queue-ab-confirm")).to_be_checked()
        expect(page.locator("#batch-queue-submit-result")).to_contain_text(
            "Auto Bangumi 批量提交失败"
        )
        expect(page.locator("#page-notification")).to_contain_text("批量提交失败")
        # 队列项目保持待提交
        item = page.locator('.batch-queue-item[data-item-id="item-queue"]')
        expect(item.locator(".batch-queue-status")).to_contain_text("待提交")
        # 敏感值不进入 DOM
        body_text = page.locator("body").inner_text()
        assert "ab-secret-token" not in body_text

    def test_batch_queue_submit_disables_controls_while_in_flight(
        self, page: Page, live_server_url: str
    ) -> None:
        # 提交端点不 mock：由 conftest 的 test-slow-submit 延迟路由真实返回 400，
        # 让浏览器 fetch 保持 ~1.5s，从而稳定观察 in-flight 的 loading/disabled 状态。
        _accept_all_reviewable(
            page, live_server_url, ["item-queue"], batch_id="test-slow-submit"
        )
        page.fill("#batch-queue-ab-endpoint", "https://ab.example/api")
        page.fill("#batch-queue-ab-token", "ab-secret-token")
        page.check("#batch-queue-ab-confirm")
        page.click("#batch-queue-submit-button")

        # 提交中：提交按钮与表单输入全部禁用
        expect(page.locator("#batch-queue-submit-button")).to_contain_text(
            "正在提交..."
        )
        expect(page.locator("#batch-queue-submit-button")).to_be_disabled()
        expect(page.locator("#batch-queue-ab-endpoint")).to_be_disabled()
        expect(page.locator("#batch-queue-ab-token")).to_be_disabled()
        expect(page.locator("#batch-queue-ab-confirm")).to_be_disabled()

        # 失败后恢复可操作，保留输入便于重试；队列保持待提交
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
        expect(page.locator("#page-notification")).to_contain_text("批量提交失败")
        expect(page.locator("#batch-queue-submit-button")).to_contain_text("提交队列")
        expect(page.locator("#batch-queue-submit-button")).to_be_enabled()
        expect(page.locator("#batch-queue-ab-endpoint")).to_have_value(
            "https://ab.example/api"
        )
        expect(page.locator("#batch-queue-ab-token")).to_have_value(
            "ab-secret-token"
        )
        item = page.locator('.batch-queue-item[data-item-id="item-queue"]')
        expect(item.locator(".batch-queue-status")).to_contain_text("待提交")
        # 敏感值不进入 DOM
        body_text = page.locator("body").inner_text()
        assert "ab-secret-token" not in body_text

    def test_batch_queue_refresh_restores_recorded_results(
        self, page: Page, live_server_url: str
    ) -> None:
        persisted = [
            _queue_item(
                "item-1",
                "req-item-1",
                "关于我转生变成史莱姆这档事 第四季",
                status="SUCCEEDED",
                attempts=1,
                ab_result_summary="Auto Bangumi 已接受该订阅方案",
                updated_at="2026-08-19T00:05:00+00:00",
            ),
            _queue_item(
                "item-2",
                "req-item-2",
                "实力至上主义教室 第四季",
                status="FAILED",
                attempts=2,
                last_error="订阅方案已不存在，跳过提交",
                updated_at="2026-08-19T00:05:30+00:00",
            ),
        ]

        def _queue_get(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": True,
                        "result": {
                            "batch_id": "batch-browser",
                            "queue": {
                                "queue_id": "queue-browser",
                                "batch_id": "batch-browser",
                                "created_at": "2026-08-19T00:00:00+00:00",
                                "updated_at": "2026-08-19T00:05:30+00:00",
                                "items": persisted,
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
            )

        page.route("**/api/v1/batches/batch-browser/queue*", _queue_get)
        # 刷新恢复：URL 直接携带 batch_id，页面加载后从队列/结果存储读取
        page.goto(f"{live_server_url}/index?batch_id=batch-browser")

        expect(page.locator("#batch-queue-count")).to_contain_text("队列中 2 项")
        expect(page.locator(".batch-queue-item")).to_have_count(2)
        first = page.locator('.batch-queue-item[data-item-id="item-1"]')
        second = page.locator('.batch-queue-item[data-item-id="item-2"]')
        expect(first.locator(".batch-queue-status")).to_contain_text("提交成功")
        expect(first.locator(".batch-queue-item-summary")).to_contain_text(
            "结果：Auto Bangumi 已接受该订阅方案"
        )
        expect(first.locator(".batch-queue-item-meta")).to_contain_text(
            "更新于：2026-08-19T00:05:00+00:00"
        )
        expect(second.locator(".batch-queue-status")).to_contain_text("提交失败")
        expect(second.locator(".batch-queue-item-summary")).to_contain_text(
            "错误：订阅方案已不存在，跳过提交"
        )
        expect(page.locator("#batch-queue-refresh")).to_be_enabled()
        expect(page.locator("#batch-queue-submit-form")).to_be_visible()


def _open_queue_with_items(
    page: Page,
    live_server_url: str,
    items: list[dict[str, Any]],
    *,
    batch_id: str = "batch-browser",
) -> None:
    """Load the index with a mocked queue GET returning the given items."""
    queue_items = []
    for item in items:
        queue_items.append(dict(item, batch_id=batch_id))

    def _queue_get(route: Any, request: Any) -> None:
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
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
                    },
                },
                ensure_ascii=False,
            ),
        )

    page.route(f"**/api/v1/batches/{batch_id}/queue*", _queue_get)
    page.goto(f"{live_server_url}/index?batch_id={batch_id}")


class TestBatchQueueRetry:
    """Stage 20 failed-item independent retry (US-148).

    Covers retry button visibility (FAILED/RETRYABLE only), single-item retry
    success/failure with attempt counting, sensitive input clearing on success,
    in-flight disabling, and no re-submission of already-succeeded items.
    """

    def test_batch_queue_retry_button_only_shows_for_failed_and_retryable(
        self, page: Page, live_server_url: str
    ) -> None:
        items = [
            _queue_item(
                "item-ok",
                "req-ok",
                "关于我转生变成史莱姆这档事 第四季",
                status="SUCCEEDED",
                attempts=1,
                ab_result_summary="Auto Bangumi 已接受该订阅方案",
            ),
            _queue_item(
                "item-fail",
                "req-fail",
                "实力至上主义教室 第四季",
                status="FAILED",
                attempts=1,
                last_error="订阅方案已不存在，跳过提交",
            ),
            _queue_item(
                "item-retry",
                "req-retry",
                "邻家天使 第二季",
                status="RETRYABLE",
                attempts=2,
                last_error="Auto Bangumi 暂时不可用，稍后重试",
            ),
            _queue_item(
                "item-ready",
                "req-ready",
                "另一部新番",
                status="READY_TO_SUBMIT",
                attempts=0,
            ),
        ]
        _open_queue_with_items(page, live_server_url, items)

        # 仅 FAILED/RETRYABLE 项目提供单项重试按钮
        expect(page.locator(".batch-queue-item-retry")).to_have_count(2)
        fail_item = page.locator('.batch-queue-item[data-item-id="item-fail"]')
        retry_item = page.locator('.batch-queue-item[data-item-id="item-retry"]')
        ok_item = page.locator('.batch-queue-item[data-item-id="item-ok"]')
        ready_item = page.locator('.batch-queue-item[data-item-id="item-ready"]')
        expect(fail_item.locator(".batch-queue-item-retry")).to_have_count(1)
        expect(retry_item.locator(".batch-queue-item-retry")).to_have_count(1)
        expect(ok_item.locator(".batch-queue-item-retry")).to_have_count(0)
        expect(ready_item.locator(".batch-queue-item-retry")).to_have_count(0)
        # 重试按钮携带公开的 request_id，文本为“重试”
        retry_button = retry_item.locator(".batch-queue-item-retry")
        expect(retry_button).to_contain_text("重试")
        assert retry_button.get_attribute("data-request-id") == "req-retry"

    def test_batch_queue_retry_success_updates_item_and_clears_sensitive_inputs(
        self, page: Page, live_server_url: str
    ) -> None:
        failed = _queue_item(
            "item-fail",
            "req-fail",
            "实力至上主义教室 第四季",
            status="FAILED",
            attempts=1,
            last_error="Auto Bangumi HTTP 提交失败",
        )
        succeeded = _queue_item(
            "item-fail",
            "req-fail",
            "实力至上主义教室 第四季",
            status="SUCCEEDED",
            attempts=2,
            ab_result_summary="Auto Bangumi 已接受该订阅方案",
            updated_at="2026-08-19T00:05:00+00:00",
        )
        retry_calls: list[dict[str, Any]] = []

        def _retry(route: Any, request: Any) -> None:
            retry_calls.append(json.loads(request.post_data or "{}"))
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_submit_result([succeeded]),
            )

        page.route("**/api/v1/batches/batch-browser/retry*", _retry)
        _open_queue_with_items(page, live_server_url, [failed])

        page.fill("#batch-queue-ab-endpoint", "https://ab.example/api")
        page.fill("#batch-queue-ab-token", "ab-secret-token")
        page.check("#batch-queue-ab-confirm")
        page.click(
            '.batch-queue-item[data-item-id="item-fail"] .batch-queue-item-retry'
        )

        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
        expect(page.locator("#page-notification")).to_contain_text("批量提交成功")
        expect(page.locator("#batch-queue-submit-result")).to_contain_text(
            "提交成功 1 项"
        )
        item = page.locator('.batch-queue-item[data-item-id="item-fail"]')
        expect(item.locator(".batch-queue-status")).to_contain_text("提交成功")
        expect(item.locator(".batch-queue-item-meta")).to_contain_text("尝试次数：2")
        expect(item.locator(".batch-queue-item-summary")).to_contain_text(
            "结果：Auto Bangumi 已接受该订阅方案"
        )
        # 重试成功后按钮消失，敏感输入清空，确认取消勾选
        expect(item.locator(".batch-queue-item-retry")).to_have_count(0)
        expect(page.locator("#batch-queue-ab-endpoint")).to_have_value("")
        expect(page.locator("#batch-queue-ab-token")).to_have_value("")
        expect(page.locator("#batch-queue-ab-confirm")).not_to_be_checked()

        payload = retry_calls[0]
        assert payload["request_id"] == "req-fail"
        assert payload["ab_config"]["endpoint"] == "https://ab.example/api"
        assert payload["ab_config"]["token"] == "ab-secret-token"
        assert payload["confirm"] is True
        # 敏感配置不进入 DOM
        body_text = page.locator("body").inner_text()
        assert "ab-secret-token" not in body_text

    def test_batch_queue_retry_success_leaves_sibling_items_unchanged(
        self, page: Page, live_server_url: str
    ) -> None:
        failed = _queue_item(
            "item-fail",
            "req-fail",
            "实力至上主义教室 第四季",
            status="FAILED",
            attempts=1,
            last_error="Auto Bangumi HTTP 提交失败",
        )
        sibling = _queue_item(
            "item-sibling",
            "req-sibling",
            "关于我转生变成史莱姆这档事 第四季",
            status="SUCCEEDED",
            attempts=1,
            ab_result_summary="Auto Bangumi 已接受该订阅方案",
        )
        succeeded = _queue_item(
            "item-fail",
            "req-fail",
            "实力至上主义教室 第四季",
            status="SUCCEEDED",
            attempts=2,
            ab_result_summary="Auto Bangumi 已接受该订阅方案",
            updated_at="2026-08-19T00:05:00+00:00",
        )

        def _retry(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_submit_result([succeeded, sibling]),
            )

        page.route("**/api/v1/batches/batch-browser/retry*", _retry)
        _open_queue_with_items(page, live_server_url, [failed, sibling])

        page.fill("#batch-queue-ab-endpoint", "https://ab.example/api")
        page.fill("#batch-queue-ab-token", "ab-secret-token")
        page.check("#batch-queue-ab-confirm")
        page.click(
            '.batch-queue-item[data-item-id="item-fail"] .batch-queue-item-retry'
        )

        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
        fail_item = page.locator('.batch-queue-item[data-item-id="item-fail"]')
        sibling_item = page.locator('.batch-queue-item[data-item-id="item-sibling"]')
        expect(fail_item.locator(".batch-queue-status")).to_contain_text("提交成功")
        expect(fail_item.locator(".batch-queue-item-meta")).to_contain_text(
            "尝试次数：2"
        )
        # 兄弟项目保持不变
        expect(sibling_item.locator(".batch-queue-status")).to_contain_text("提交成功")
        expect(sibling_item.locator(".batch-queue-item-meta")).to_contain_text(
            "尝试次数：1"
        )
        expect(sibling_item.locator(".batch-queue-item-summary")).to_contain_text(
            "结果：Auto Bangumi 已接受该订阅方案"
        )
        expect(sibling_item.locator(".batch-queue-item-retry")).to_have_count(0)

    def test_batch_queue_retry_failure_preserves_inputs_and_keeps_item_retryable(
        self, page: Page, live_server_url: str
    ) -> None:
        failed = _queue_item(
            "item-fail",
            "req-fail",
            "实力至上主义教室 第四季",
            status="FAILED",
            attempts=1,
            last_error="Auto Bangumi HTTP 提交失败",
        )

        def _retry_fail(route: Any, request: Any) -> None:
            route.fulfill(
                status=400,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": False,
                        "error_message": "Auto Bangumi 单项重试失败：连接超时",
                        "error_type": "ab_connection_failed",
                    },
                    ensure_ascii=False,
                ),
            )

        page.route("**/api/v1/batches/batch-browser/retry*", _retry_fail)
        _open_queue_with_items(page, live_server_url, [failed])

        page.fill("#batch-queue-ab-endpoint", "https://ab.example/api")
        page.fill("#batch-queue-ab-token", "ab-secret-token")
        page.check("#batch-queue-ab-confirm")
        page.click(
            '.batch-queue-item[data-item-id="item-fail"] .batch-queue-item-retry'
        )

        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
        expect(page.locator("#page-notification")).to_contain_text("单项重试失败")
        expect(page.locator("#batch-queue-submit-result")).to_contain_text(
            "Auto Bangumi 单项重试失败"
        )
        # HTTP 级失败：保留敏感输入与确认，便于再次重试
        expect(page.locator("#batch-queue-ab-endpoint")).to_have_value(
            "https://ab.example/api"
        )
        expect(page.locator("#batch-queue-ab-token")).to_have_value(
            "ab-secret-token"
        )
        expect(page.locator("#batch-queue-ab-confirm")).to_be_checked()
        # 项目保持提交失败，重试按钮仍在
        item = page.locator('.batch-queue-item[data-item-id="item-fail"]')
        expect(item.locator(".batch-queue-status")).to_contain_text("提交失败")
        expect(item.locator(".batch-queue-item-meta")).to_contain_text("尝试次数：1")
        expect(item.locator(".batch-queue-item-retry")).to_have_count(1)
        # 敏感值不进入 DOM
        body_text = page.locator("body").inner_text()
        assert "ab-secret-token" not in body_text

    def test_batch_queue_retry_disables_controls_while_in_flight(
        self, page: Page, live_server_url: str
    ) -> None:
        # 重试端点不 mock：由 conftest 的 test-slow-retry 延迟路由真实返回 400，
        # 让浏览器 fetch 保持 ~1.5s，从而稳定观察 in-flight 的 loading/disabled 状态。
        failed = _queue_item(
            "item-fail",
            "req-fail",
            "实力至上主义教室 第四季",
            status="FAILED",
            attempts=1,
            last_error="Auto Bangumi HTTP 提交失败",
            batch_id="test-slow-retry",
        )
        _open_queue_with_items(page, live_server_url, [failed], batch_id="test-slow-retry")
        page.fill("#batch-queue-ab-endpoint", "https://ab.example/api")
        page.fill("#batch-queue-ab-token", "ab-secret-token")
        page.check("#batch-queue-ab-confirm")
        page.click(
            '.batch-queue-item[data-item-id="item-fail"] .batch-queue-item-retry'
        )

        # 重试中：结果区显示 loading，重试按钮与提交按钮、敏感输入全部禁用
        expect(page.locator("#batch-queue-submit-result")).to_contain_text(
            "正在重试到 Auto Bangumi"
        )
        expect(page.locator("#batch-queue-submit-result")).to_have_class(
            "loading-state compact-state"
        )
        expect(page.locator(".batch-queue-item-retry")).to_be_disabled()
        expect(page.locator("#batch-queue-submit-button")).to_be_disabled()
        expect(page.locator("#batch-queue-ab-endpoint")).to_be_disabled()
        expect(page.locator("#batch-queue-ab-token")).to_be_disabled()
        expect(page.locator("#batch-queue-ab-confirm")).to_be_disabled()

        # 失败后恢复可操作，保留输入便于再次重试；项目保持提交失败
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
        expect(page.locator("#page-notification")).to_contain_text("单项重试失败")
        expect(page.locator("#batch-queue-submit-result")).to_contain_text(
            "Auto Bangumi 单项重试失败"
        )
        expect(page.locator(".batch-queue-item-retry")).to_be_enabled()
        expect(page.locator("#batch-queue-submit-button")).to_be_enabled()
        expect(page.locator("#batch-queue-ab-endpoint")).to_have_value(
            "https://ab.example/api"
        )
        expect(page.locator("#batch-queue-ab-token")).to_have_value(
            "ab-secret-token"
        )
        item = page.locator('.batch-queue-item[data-item-id="item-fail"]')
        expect(item.locator(".batch-queue-status")).to_contain_text("提交失败")
        # 敏感值不进入 DOM
        body_text = page.locator("body").inner_text()
        assert "ab-secret-token" not in body_text


def _preference_hits() -> list[dict[str, str]]:
    return [
        {
            "field": "subtitle_groups",
            "applied": True,
            "summary": "字幕组偏好已作为可编辑默认值",
        },
        {
            "field": "filter_rule",
            "applied": True,
            "summary": "筛选默认值已作为可编辑默认规则",
        },
        {
            "field": "naming",
            "applied": True,
            "summary": "命名策略已生成默认目录名：关于我转生变成史莱姆这档事 第四季",
        },
    ]


def _applied_preferences() -> dict[str, Any]:
    return {
        "subtitle_groups": {
            "preferred": ["喵萌"],
            "excluded": ["Loli"],
            "fallback": "next_preferred",
        },
        "filter_rule": {
            "must_contain": "1080p",
            "must_not_contain": "合集版",
            "use_regex": True,
            "case_sensitive": False,
        },
        "naming": {"strategy": "official_title_season", "template": "{title}"},
        "expected_folder_name": "关于我转生变成史莱姆这档事 第四季",
    }


def _enhanced_queries() -> list[dict[str, str]]:
    return [
        {
            "query": "转生史莱姆 第四季",
            "original_query": "转生史莱姆",
            "source": "correction:canonical",
        },
        {
            "query": "转生史莱姆 S4",
            "original_query": "转生史莱姆",
            "source": "correction:canonical",
        },
    ]


class TestBatchWorkbenchPreferenceDisplay:
    """US-156: 批量卡片展示偏好命中摘要、搜索词来源、审核提示与当前默认配置."""

    def test_batch_card_shows_preference_hits_and_default_config(
        self, page: Page, live_server_url: str
    ) -> None:
        item = _reviewable_batch_item(
            applied_preferences=_applied_preferences(),
            preference_hits=_preference_hits(),
            preference_warnings=["fallback 为 next_preferred，未配置时回退到第一个偏好字幕组"],
            review_hints=["该条目需要人工核对后再接受。"],
            enhanced_search_queries=_enhanced_queries(),
        )

        def _fulfill(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result([item]),
            )

        page.route("**/api/v1/batches/parse", _fulfill)
        page.goto(f"{live_server_url}/index")
        page.get_by_role("tab", name="批量搜索").click()
        page.fill("#batch-raw-input", "萌王S4")
        page.click("#batch-parse-submit")

        card = page.locator(".batch-draft-card")
        expect(card.locator(".batch-card-preference")).to_contain_text(
            "偏好命中：字幕组、筛选、命名"
        )
        card.locator(".batch-card-expand").click()

        panel = page.locator("#request-detail-container")
        text = panel.inner_text()
        assert "偏好与审核" in text
        assert "偏好命中摘要" in text
        assert "字幕组：字幕组偏好已作为可编辑默认值" in text
        assert "筛选：筛选默认值已作为可编辑默认规则" in text
        assert "命名：命名策略已生成默认目录名：关于我转生变成史莱姆这档事 第四季" in text
        assert "偏好警告" in text
        assert "fallback 为 next_preferred" in text
        assert "审核提示" in text
        assert "该条目需要人工核对后再接受。" in text
        assert "当前默认配置" in text
        assert "偏好字幕组" in text
        assert "喵萌" in text
        assert "排除字幕组" in text
        assert "Loli" in text
        assert "Fallback" in text
        assert "偏好字幕组优先" in text
        assert "默认筛选" in text
        assert "1080p / 合集版" in text
        assert "匹配模式" in text
        assert "正则" in text
        assert "命名策略" in text
        assert "官方标题+季" in text
        assert "默认目录名" in text
        assert "搜索词来源" in text
        assert "修正增强搜索词" in text
        assert "转生史莱姆 第四季（来源：correction:canonical）" in text
        assert "转生史莱姆 S4（来源：correction:canonical）" in text
        assert "原始搜索词" in text
        assert "转生史莱姆" in text

    def test_batch_card_shows_low_confidence_review_status(
        self, page: Page, live_server_url: str
    ) -> None:
        item = _reviewable_batch_item(
            needs_user_review=True,
            confidence=0.62,
            review_hints=[
                "名称解析置信度较低（0.62），建议核对候选合集。",
                "存在多个候选名称（2 个），建议确认正确的合集。",
            ],
        )

        def _fulfill(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result([item]),
            )

        page.route("**/api/v1/batches/parse", _fulfill)
        page.goto(f"{live_server_url}/index")
        page.get_by_role("tab", name="批量搜索").click()
        page.fill("#batch-raw-input", "萌王S4")
        page.click("#batch-parse-submit")

        card = page.locator(".batch-draft-card")
        expect(card.locator(".batch-card-review-status")).to_contain_text(
            "需人工核对"
        )
        card.locator(".batch-card-expand").click()

        panel = page.locator("#request-detail-container")
        text = panel.inner_text()
        assert "审核提示" in text
        assert "名称解析置信度较低（0.62），建议核对候选合集。" in text
        assert "存在多个候选名称（2 个），建议确认正确的合集。" in text

    def test_batch_card_no_preference_fallback(
        self, page: Page, live_server_url: str
    ) -> None:
        item = _reviewable_batch_item(
            applied_preferences=None,
            preference_hits=None,
            preference_warnings=["偏好读取失败，已回退默认流程"],
            needs_user_review=True,
            review_hints=["该条目需要人工核对后再接受。"],
        )

        def _fulfill(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result([item]),
            )

        page.route("**/api/v1/batches/parse", _fulfill)
        page.goto(f"{live_server_url}/index")
        page.get_by_role("tab", name="批量搜索").click()
        page.fill("#batch-raw-input", "萌王S4")
        page.click("#batch-parse-submit")

        card = page.locator(".batch-draft-card")
        expect(card.locator(".batch-card-preference")).to_contain_text(
            "偏好不可用，已回退默认流程"
        )
        card.locator(".batch-card-expand").click()

        panel = page.locator("#request-detail-container")
        text = panel.inner_text()
        assert "偏好与审核" in text
        assert "偏好读取失败，已回退默认流程" in text
        assert "未配置偏好默认值" not in text
        assert "当前默认配置" not in text
        assert "审核提示" in text
        assert "该条目需要人工核对后再接受。" in text

    def test_batch_card_modify_syncs_only_current_card(
        self, page: Page, live_server_url: str
    ) -> None:
        first_preview = _preview_request("咒术回战", "req-pref-first")
        second_preview = _preview_request("咒术回战", "req-pref-second")
        first_item = _reviewable_batch_item(
            item_id="item-first",
            preview_request=first_preview,
            applied_preferences=_applied_preferences(),
            preference_hits=_preference_hits(),
            preference_warnings=["fallback 为 next_preferred"],
            needs_user_review=True,
            review_hints=["该条目需要人工核对后再接受。"],
        )
        second_item = _batch_item(
            "item-second",
            "路哥S4",
            status="DRAFT",
            canonical_title="实力至上主义教室 第四季",
            preview_request=second_preview,
            applied_preferences=_applied_preferences(),
            preference_hits=_preference_hits(),
            preference_warnings=["fallback 为 next_preferred"],
            needs_user_review=True,
            review_hints=["该条目需要人工核对后再接受。"],
        )

        def _fulfill(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result([first_item, second_item]),
            )

        page.route("**/api/v1/batches/parse", _fulfill)
        page.goto(f"{live_server_url}/index")
        page.get_by_role("tab", name="批量搜索").click()
        page.fill("#batch-raw-input", "萌王S4\n路哥S4")
        page.click("#batch-parse-submit")

        first_card = page.locator(".batch-draft-card", has_text="萌王S4")
        second_card = page.locator(".batch-draft-card", has_text="路哥S4")

        def _panel_text() -> str:
            return page.locator("#request-detail-container").inner_text()

        second_card.locator(".batch-card-expand").click()
        second_text_before = _panel_text()

        # 修改第一张卡片：更换字幕组并刷新偏好/审核区域，第二张卡片保持完全不变。
        first_card.locator(".batch-card-expand").click()
        expect(page.locator("#detail-preview-edit-form")).to_be_visible()
        page.select_option("#preview-subtitle-group", value="喵萌")
        page.fill("#preview-must-not-contain", "V2")
        page.click("button:has-text('应用修改')")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        expect(page.locator("#page-notification")).to_contain_text(
            "当前批量卡片已回流最新订阅草案"
        )
        first_card = page.locator(".batch-draft-card", has_text="萌王S4")
        first_text = _panel_text()
        assert "喵萌" in first_text
        assert "偏好与审核" in first_text
        assert "偏好命中：字幕组、筛选、命名" not in first_text

        second_card = page.locator(".batch-draft-card", has_text="路哥S4")
        second_card.locator(".batch-card-expand").click()
        second_text_after = _panel_text()
        assert second_text_after == second_text_before
        # 第二张卡片的当前选择仍是 fixture 默认（Loli），修改未回流到其他卡片。
        expect(page.locator("#preview-subtitle-group")).to_have_value("Loli")

    def test_batch_card_preference_metadata_never_leaks_sensitive_config(
        self, page: Page, live_server_url: str
    ) -> None:
        applied = _applied_preferences()
        # 攻击性注入：即使后端意外把敏感字段塞进偏好元数据，渲染器也只读取
        # 白名单公开字段，绝不渲染这些键。
        applied["token"] = "preference-token-secret"
        applied["endpoint"] = "https://mikan.example/Home/Search"
        applied["raw_rss_xml"] = "<rss>preference-raw</rss>"
        item = _reviewable_batch_item(
            applied_preferences=applied,
            preference_hits=_preference_hits(),
            preference_warnings=["fallback 为 next_preferred"],
            enhanced_search_queries=_enhanced_queries(),
        )

        def _fulfill(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_result([item]),
            )

        page.route("**/api/v1/batches/parse", _fulfill)
        page.goto(f"{live_server_url}/index")
        page.get_by_role("tab", name="批量搜索").click()
        page.fill("#batch-raw-input", "萌王S4")
        page.click("#batch-parse-submit")
        page.locator(".batch-draft-card .batch-card-expand").click()

        body_text = page.locator("body").inner_text()
        assert "preference-token-secret" not in body_text
        assert "mikan.example" not in body_text
        assert "preference-raw" not in body_text
        assert "secret-token" not in body_text
        assert "session-cookie" not in body_text
        assert "<rss>" not in body_text
        assert "raw-body-secret" not in body_text
