from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import create_saved_request, set_storage_preferences

pytestmark = pytest.mark.browser


def _tracking_item(request_id: str) -> dict[str, Any]:
    return {
        "tracking_id": "tracking-stage37",
        "request_id": request_id,
        "title": "葬送的芙莉莲",
        "season": 1,
        "subtitle_group": "喵萌奶茶屋",
        "poster_path": None,
        "status": "ACTIVE",
        "status_label": "追番中",
        "status_group": "ACTIVE",
        "valid_resource_count": 2,
        "updated_episode": None,
        "updated_episode_status": "NOT_IMPLEMENTED",
        "total_episodes": None,
        "revision": 1,
        "updated_at": "2026-09-01T00:00:00+00:00",
    }


def _mock_tracking(page: Page, *, failed: bool = False) -> None:
    def handler(route: Any, request: Any) -> None:
        if request.method != "GET" or "/api/v1/tracking/items" not in request.url:
            route.continue_()
            return
        if failed:
            route.fulfill(status=500, content_type="application/json", body=json.dumps({"ok": False}))
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "ok": True,
                    "result": {
                        "items": [_tracking_item("req-stage37")],
                        "summary": {
                            "total": 1,
                            "pending": 0,
                            "processing": 0,
                            "active": 1,
                            "needs_attention": 0,
                            "unreadable": 0,
                        },
                        "warnings": [],
                    },
                },
                ensure_ascii=False,
            ),
        )

    page.route("**/api/v1/tracking/items*", handler)


class TestAppPlansStage37:
    def test_plans_list_detail_layout_and_tracking_projection(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-stage37")
        set_storage_preferences(page, storage_dir)
        _mock_tracking(page)

        page.goto(f"{live_server_url}/app/plans")
        page.wait_for_selector(".plans-layout", timeout=5000)
        page.wait_for_selector(".request-list-item", timeout=5000)

        expect(page.locator(".plan-list-item")).to_contain_text("季度：")
        expect(page.locator(".plan-list-item")).to_contain_text("方案状态：待确认")
        expect(page.locator(".plan-list-item")).to_contain_text("追番状态：追番中")
        expect(page.locator(".copy-request-id")).to_have_count(0)
        expect(page.locator("body")).not_to_contain_text("request_id、")

        page.locator(".request-list-item").click()
        page.wait_for_url("**/app/plans?request_id=req-stage37", timeout=5000)
        expect(page.locator("#request-detail-container")).to_be_visible()

    def test_tracking_failure_keeps_plan_list_usable(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-stage37")
        set_storage_preferences(page, storage_dir)
        _mock_tracking(page, failed=True)

        page.goto(f"{live_server_url}/app/plans")
        page.wait_for_selector(".plans-tracking-error", timeout=5000)
        expect(page.locator(".request-list-item")).to_have_count(1)
        expect(page.locator(".plans-tracking-error")).to_contain_text("追番状态暂不可用")
