from __future__ import annotations

import json
import time
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from apps.migu_orca_entry.controllers.entry_controller import generate_request
from shared.models import EntryRequest


pytestmark = pytest.mark.browser


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
    confirmable_config: dict[str, Any] | None = None,
    source_info: dict[str, Any] | None = None,
    preview_request: dict[str, Any] | None = None,
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
    return {
        "item_id": item_id,
        "raw_title": raw_title,
        "status": status,
        "canonical_title_candidates": [canonical_title] if canonical_title else [],
        "season_hint": None,
        "search_queries": [source_query or title],
        "confidence": 0.9,
        "needs_user_review": False,
        "source": "fake",
        "candidates": candidates,
        "confirmable_config": confirmable_config,
        "source_info": source_info,
        "preview_request": preview_request,
    }


def _preview_request(title: str, request_id: str) -> dict[str, Any]:
    return {
        **generate_request(EntryRequest(raw_title=title))["request"],
        "request_id": request_id,
    }


def _reviewable_batch_item(
    *, item_id: str = "item-review", preview_request: dict[str, Any] | None = None
) -> dict[str, Any]:
    return _batch_item(
        item_id,
        "萌王S4",
        status="DRAFT",
        canonical_title="关于我转生变成史莱姆这档事 第四季",
        candidate_title="关于我转生变成史莱姆这档事 第四季",
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
        preview_request=preview_request,
    )


def _queue_item(
    item_id: str,
    request_id: str,
    title: str,
    status: str = "READY_TO_SUBMIT",
) -> dict[str, Any]:
    return {
        "queue_id": "queue-browser",
        "batch_id": "batch-browser",
        "item_id": item_id,
        "request_id": request_id,
        "title": title,
        "status": status,
        "status_label": "待提交" if status == "READY_TO_SUBMIT" else status,
        "attempts": 0,
        "last_error": None,
        "ab_result_summary": None,
        "created_at": "2026-08-19T00:00:00+00:00",
        "updated_at": "2026-08-19T00:00:00+00:00",
    }


def _batch_accept_result(
    items: list[dict[str, Any]],
    queue_items: list[dict[str, Any]] | None = None,
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
                "batch_id": "batch-browser",
                "queue": {
                    "queue_id": "queue-browser",
                    "batch_id": "batch-browser",
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


def _accept_route_handler(accepted_ids: set[str]):
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
                queue_items.append(_queue_item(item_id, request_id, title))
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
            body=_batch_accept_result(results, queue_items),
        )

    return _handler


class TestBatchWorkbenchEntry:
    """Stage 19 batch workbench entry and draft-card rendering."""

    def test_batch_entry_is_visible_with_multiline_examples(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/index")

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

        def _fulfill(route: Any, request: Any) -> None:
            captured_payloads.append(json.loads(request.post_data or "{}"))
            time.sleep(0.2)
            route.fulfill(
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

        page.route("**/api/v1/batches/parse", _fulfill)
        page.goto(f"{live_server_url}/index")
        page.fill("#batch-raw-input", "萌王S4\n\n路哥S4")
        page.click("#batch-parse-submit")

        expect(page.locator("#batch-parse-result")).to_contain_text(
            "正在解析批量番剧名称"
        )
        expect(page.locator(".batch-draft-card")).to_have_count(2)
        result_text = page.locator("#batch-parse-result").inner_text()
        assert "萌王S4" in result_text
        assert "路哥S4" in result_text
        assert "关于我转生变成史莱姆这档事 第四季" in result_text
        assert "源名称：MiKan：萌王 第四季" in result_text
        assert "有效种子数：待展开" in result_text
        assert "已解析" in result_text
        assert "解析失败" in result_text
        expect(page.locator(".batch-card-poster img")).to_have_count(1)
        expect(page.locator(".batch-card-expand")).to_have_count(2)
        expect(page.locator("#page-notification")).to_contain_text("批量草案已获取")
        assert captured_payloads == [{"raw_input": "萌王S4\n\n路哥S4"}]

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

    def test_batch_draft_card_expands_filter_and_seed_summary(
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
        page.fill("#batch-raw-input", "萌王S4")
        page.click("#batch-parse-submit")

        card = page.locator(".batch-draft-card")
        panel = card.locator(".batch-card-review")
        expect(card.locator(".batch-card-status")).to_contain_text("草案")
        expect(panel).to_be_hidden()

        card.locator(".batch-card-expand").click()

        expect(panel).to_be_visible()
        expanded_text = panel.inner_text()
        assert "当前字幕组" in expanded_text
        assert "桜都字幕组" in expanded_text
        assert "包含规则" in expanded_text
        assert "1080p" in expanded_text
        assert "排除规则" in expanded_text
        assert "V2" in expanded_text
        assert "匹配模式" in expanded_text
        assert "普通字符" in expanded_text
        assert "大小写" in expanded_text
        assert "不区分大小写" in expanded_text
        assert "有效种子（当前选中字幕组：桜都字幕组）(1)" in expanded_text
        assert "史莱姆 S4 01 [1080p]" in expanded_text
        assert "排除种子 (1)" in expanded_text
        assert "史莱姆 S4 01 V2 [1080p]" in expanded_text
        assert "命中排除规则：V2" in expanded_text

        card.locator(".batch-card-expand").click()
        expect(panel).to_be_hidden()

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
        page.fill("#batch-raw-input", "萌王S4")
        page.click("#batch-parse-submit")
        page.locator(".batch-draft-card .batch-card-expand").click()

        body_text = page.locator("body").inner_text()
        assert "secret-token" not in body_text
        assert "session-cookie" not in body_text
        assert "<rss>" not in body_text
        assert "raw-body-secret" not in body_text
        assert "https://mikan.example/RSS/Bangumi" not in body_text

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
        page.fill("#batch-raw-input", "萌王S4\n路哥S4")
        page.click("#batch-parse-submit")

        first_card = page.locator(".batch-draft-card", has_text="萌王S4")
        second_card = page.locator(".batch-draft-card", has_text="路哥S4")
        first_card.locator(".batch-card-expand").click()
        first_card.locator(".batch-card-modify").click()

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
        first_card.locator(".batch-card-expand").click()
        first_text = first_card.locator(".batch-card-review").inner_text()
        assert "当前字幕组" in first_text
        assert "喵萌" in first_text
        assert "排除规则" in first_text
        assert "V2" in first_text
        assert "有效种子（当前选中字幕组：喵萌）(1)" in first_text

        second_card.locator(".batch-card-expand").click()
        second_text = second_card.locator(".batch-card-review").inner_text()
        # 第二个卡片必须保持独立：字幕组不变成喵萌，有效种子区不引用喵萌组。
        # 注意：不能断言 "V2" not in second_text——咒术回战 fixture 的默认排除规则
        # 与种子标题本身含 "V2"（如 [Loli] 咒术回战 第三季 - 01 V2 [1080p]）。
        assert "喵萌" not in second_text
        assert "有效种子（当前选中字幕组：喵萌）" not in second_text
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
        page.fill("#batch-raw-input", "萌王S4")
        page.click("#batch-parse-submit")

        card = page.locator(".batch-draft-card")
        card.locator(".batch-card-expand").click()
        before = card.locator(".batch-card-review").inner_text()
        card.locator(".batch-card-modify").click()

        page.check("#preview-filter-use-regex")
        page.fill("#preview-must-not-contain", "[")
        page.click("button:has-text('应用修改')")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        expect(page.locator("#preview-edit-error")).to_contain_text("不是合法正则")
        expect(page.locator("#page-notification")).to_contain_text("修改失败")
        after = card.locator(".batch-card-review").inner_text()
        assert after == before
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
        page.fill("#batch-raw-input", "萌王S4\n路哥S4")
        page.click("#batch-parse-submit")

        first_card = page.locator(".batch-draft-card", has_text="萌王S4")
        second_card = page.locator(".batch-draft-card", has_text="路哥S4")
        first_card.locator(".batch-card-expand").click()
        page.once("dialog", lambda dialog: dialog.accept())
        first_card.locator(".batch-card-accept").click()
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
        page.fill("#batch-raw-input", "\n".join(item["raw_title"] for item in items))
        page.click("#batch-parse-submit")

        wrapper = page.locator(".batch-card-grid-wrapper")
        expect(page.locator(".batch-draft-card")).to_have_count(24)
        scroll_metrics = wrapper.evaluate(
            "el => ({clientHeight: el.clientHeight, scrollHeight: el.scrollHeight})"
        )
        assert scroll_metrics["scrollHeight"] > scroll_metrics["clientHeight"]


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
        expect(fail_card.locator(".batch-card-status")).to_contain_text("解析失败")
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
        page.fill("#batch-raw-input", "萌王S4")
        page.click("#batch-parse-submit")
        page.wait_for_selector(".batch-card-accept", state="attached", timeout=5000)

        page.once("dialog", lambda dialog: dialog.accept())
        page.click("#batch-accept-all")

        # 提交中：接受入口与选择控件进入 loading/disabled 状态
        expect(page.locator("#batch-accept-all")).to_contain_text("正在接受...")
        expect(page.locator(".batch-card-accept")).to_be_disabled()
        expect(page.locator(".batch-card-checkbox")).to_be_disabled()
        expect(page.locator("#batch-accept-all")).to_be_disabled()
        expect(page.locator("#batch-accept-submit")).to_be_disabled()

        # 失败后恢复可操作：按钮文案还原、重新启用、卡片保持草案
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
        expect(page.locator("#page-notification")).to_contain_text("接受失败")
        expect(page.locator("#batch-accept-all")).to_contain_text("全接受")
        expect(page.locator("#batch-accept-all")).to_be_enabled()
        expect(page.locator(".batch-card-accept")).to_be_enabled()
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
