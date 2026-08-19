from __future__ import annotations

import json
import time
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from apps.migu_orca_entry.controllers.entry_controller import generate_request
from shared.models import EntryRequest


pytestmark = pytest.mark.browser


def _batch_parse_result(items: list[dict[str, Any]]) -> str:
    return json.dumps(
        {
            "ok": True,
            "result": {
                "batch_id": "batch-browser",
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
        assert "喵萌" not in second_text
        assert "V2" not in second_text
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
