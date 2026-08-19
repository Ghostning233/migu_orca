from __future__ import annotations

import json
import time
from typing import Any

import pytest
from playwright.sync_api import Page, expect


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


class TestBatchWorkbenchEntry:
    """US-136: `/index` exposes batch input and renders parse status rows."""

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

    def test_batch_submit_shows_loading_and_renders_raw_title_status_rows(
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
                        {
                            "item_id": "item-1",
                            "raw_title": "萌王S4",
                            "status": "PARSED",
                            "canonical_title_candidates": ["关于我转生变成史莱姆这档事 第四季"],
                            "season_hint": "S4",
                            "search_queries": ["萌王 第四季"],
                            "confidence": 0.9,
                            "needs_user_review": False,
                            "source": "fake",
                            "candidates": [],
                        },
                        {
                            "item_id": "item-2",
                            "raw_title": "路哥S4",
                            "status": "FAILED",
                            "canonical_title_candidates": [],
                            "season_hint": None,
                            "search_queries": [],
                            "confidence": 0,
                            "needs_user_review": True,
                            "source": "fake",
                            "candidates": [],
                            "error": {"error_type": "mikan_search_failed"},
                        },
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
        expect(page.locator(".batch-result-item")).to_have_count(2)
        result_text = page.locator("#batch-parse-result").inner_text()
        assert "萌王S4" in result_text
        assert "路哥S4" in result_text
        assert "解析状态：已解析" in result_text
        assert "解析状态：解析失败" in result_text
        expect(page.locator("#page-notification")).to_contain_text("批量草案已获取")
        assert captured_payloads == [{"raw_input": "萌王S4\n\n路哥S4"}]
