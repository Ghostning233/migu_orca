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
        if "/api/v1/tracking/items/tracking-a" in request.url:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"ok": True, "result": {
                    **_item("tracking-a", "葬送的芙莉莲"),
                    "origin": "single", "batch_id": None, "created_at": "2026-09-01T00:00:00+00:00",
                    "updated_at": "2026-09-13T00:00:00+00:00", "last_synced_at": None,
                    "safe_info": None, "current_operation": None, "revalidation_issues": [],
                    "external_mapping": None, "audit_events": [], "warnings": [],
                }}, ensure_ascii=False))
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
    page.route(
        "**/api/v1/tracking/items/tracking-a*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"ok": True, "result": {
                **_item("tracking-a", "葬送的芙莉莲"),
                "origin": "single", "batch_id": None, "created_at": "2026-09-01T00:00:00+00:00",
                "updated_at": "2026-09-13T00:00:00+00:00", "last_synced_at": None,
                "safe_info": None, "current_operation": None, "revalidation_issues": [],
                "external_mapping": None, "audit_events": [], "warnings": [],
            }}, ensure_ascii=False),
        ),
    )


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
        expect(page.locator(".tracking-inspector-detail")).to_contain_text("葬送的芙莉莲")

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

    def test_credential_session_probe_is_explicit_and_clearable(self, page: Page, live_server_url: str) -> None:
        _require_dist()
        _mock_list(page)

        def probe(route: Any, request: Any) -> None:
            assert request.method == "POST"
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"ok": True, "result": {
                    "probe_status": "VERIFIED", "version": "3.1.18", "adapter": "legacy_3_1",
                    "subscription_list": "SUPPORTED", "subscription_detail": "SUPPORTED",
                    "subscription_submit": "SUPPORTED", "subscription_modify": "SUPPORTED",
                    "subscription_enable": "SUPPORTED", "subscription_disable": "SUPPORTED",
                    "subscription_delete": "SUPPORTED", "rss_list": "SUPPORTED", "rss_modify": "SUPPORTED",
                    "rss_enable": "SUPPORTED", "rss_disable": "SUPPORTED", "rss_delete": "SUPPORTED",
                    "rss_refresh": "SUPPORTED", "external_verify": "SUPPORTED", "checked_at": None,
                    "safe_message": "已完成安全探测",
                }}, ensure_ascii=False),
            )

        page.route("**/api/v1/autobangumi/capabilities", probe)
        page.goto(f"{live_server_url}/app/tracking")
        page.wait_for_selector("#tracking-overview")
        page.locator("#tracking-connect").click()
        page.locator("#tracking-ab-base-url").fill("https://private.invalid")
        page.locator("#tracking-ab-username").fill("secret-user")
        page.locator("#tracking-ab-password").fill("secret-password")
        page.locator("#tracking-ab-probe").click()
        expect(page.locator(".tracking-connection-status")).to_contain_text("VERIFIED")
        expect(page).to_have_url(f"{live_server_url}/app/tracking")
        expect(page.locator("body")).not_to_contain_text("https://private.invalid")
        page.locator(".tracking-clear-connection").click()
        page.locator("#tracking-connect").click()
        expect(page.locator("#tracking-ab-password")).to_have_value("")
        expect(page.locator("body")).not_to_contain_text("secret-password")
