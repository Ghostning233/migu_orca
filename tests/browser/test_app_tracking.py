from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser
REPO_ROOT = Path(__file__).resolve().parents[2]


def _require_dist() -> None:
    if (REPO_ROOT / "frontend" / "dist" / "index.html").is_file():
        return
    if os.environ.get("MIGU_ORCA_CI") == "1":
        raise RuntimeError("frontend/dist missing in CI — build the frontend before browser tests.")
    pytest.skip("frontend/dist not built — run `cd frontend && npm run build` first.")


def _item(tracking_id: str, title: str, group: str = "ACTIVE") -> dict[str, Any]:
    return {
        "tracking_id": tracking_id,
        "request_id": f"request-{tracking_id}",
        "title": title,
        "season": 1,
        "subtitle_group": "喵萌奶茶屋",
        "poster_path": None,
        "status": "ACTIVE" if group == "ACTIVE" else "SUBMIT_FAILED",
        "status_label": "追番中" if group == "ACTIVE" else "提交失败",
        "status_group": group,
        "available_actions": [],
        "valid_resource_count": 1,
        "updated_episode": None,
        "updated_episode_status": "NOT_IMPLEMENTED",
        "total_episodes": None,
        "revision": 1,
        "updated_at": "2026-09-13T00:00:00+00:00",
    }


def _mock_list(page: Page, *, failed: bool = False) -> None:
    def handler(route: Any, request: Any) -> None:
        if request.method != "GET" or "/api/v1/tracking/items" not in request.url:
            route.continue_()
            return
        if failed:
            route.fulfill(status=503, content_type="application/json", body=json.dumps({"ok": False}))
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "ok": True,
                    "result": {
                        "items": [_item("tracking-a", "葬送的芙莉莲"), _item("tracking-b", "咒术回战", "ATTENTION")],
                        "summary": {"total": 2, "pending": 0, "processing": 0, "active": 1, "needs_attention": 1, "unreadable": 0},
                        "warnings": [],
                    },
                },
                ensure_ascii=False,
            ),
        )

    page.route("**/api/v1/tracking/items*", handler)


class TestAppTrackingStage38:
    def test_formal_overview_single_select_and_filter(self, page: Page, live_server_url: str) -> None:
        _require_dist()
        _mock_list(page)
        page.goto(f"{live_server_url}/app/tracking")
        page.wait_for_selector("#tracking-overview")
        expect(page.locator("#tracking-list-container")).to_be_visible()
        expect(page.locator(".tracking-status-card")).to_have_count(5)
        expect(page.locator(".tracking-list-item")).to_have_count(2)
        expect(page.locator("input[type=checkbox]")).to_have_count(0)

        page.locator(".tracking-list-item").first.click()
        page.wait_for_url("**/app/tracking?tracking_id=tracking-a")
        expect(page.locator('[aria-current="true"]')).to_have_count(1)
        expect(page.locator(".tracking-inspector-placeholder")).to_contain_text("葬送的芙莉莲")

        page.locator("#tracking-search").fill("不存在")
        expect(page.locator(".empty-state")).to_contain_text("没有符合当前搜索")

    def test_invalid_query_and_list_failure_are_safe(self, page: Page, live_server_url: str) -> None:
        _require_dist()
        _mock_list(page, failed=True)
        page.goto(f"{live_server_url}/app/tracking?tracking_id=https://private.invalid")
        page.wait_for_selector(".error-state")
        expect(page).to_have_url(f"{live_server_url}/app/tracking")
        expect(page.locator(".error-state")).to_contain_text("暂时无法读取本地追番列表")
        expect(page.locator("body")).not_to_contain_text("private.invalid")
