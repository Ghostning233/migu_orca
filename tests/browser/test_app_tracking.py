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
        connection = page.locator(".tracking-connection-status")
        expect(connection).to_contain_text("已验证")
        expect(connection).not_to_contain_text("VERIFIED")
        capability_summary = page.locator("#tracking-capability-summary")
        expect(capability_summary).to_contain_text("3.1.18")
        expect(capability_summary).to_contain_text("探测状态")
        expect(capability_summary).to_contain_text("新增订阅")
        expect(capability_summary).to_contain_text("支持")
        expect(capability_summary).not_to_contain_text("SUPPORTED")
        expect(capability_summary).not_to_contain_text("UNKNOWN")
        expect(page).to_have_url(f"{live_server_url}/app/tracking")
        expect(page.locator("body")).not_to_contain_text("https://private.invalid")
        expect(page.locator("body")).not_to_contain_text("secret-user")
        expect(page.locator("body")).not_to_contain_text("secret-password")
        page.locator(".tracking-clear-connection").click()
        page.locator("#tracking-connect").click()
        expect(page.locator("#tracking-ab-password")).to_have_value("")
        expect(page.locator("body")).not_to_contain_text("secret-password")

    def test_sync_requires_connected_session_and_second_confirmation(self, page: Page, live_server_url: str) -> None:
        _require_dist()
        _mock_list(page)
        sync_calls: list[dict[str, Any]] = []

        def probe(route: Any, request: Any) -> None:
            assert request.method == "POST"
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "result": {
                "probe_status": "VERIFIED", "version": "3.1.18", "adapter": "legacy_3_1",
                "subscription_list": "SUPPORTED", "subscription_detail": "SUPPORTED", "subscription_submit": "SUPPORTED",
                "subscription_modify": "SUPPORTED", "subscription_enable": "SUPPORTED", "subscription_disable": "SUPPORTED",
                "subscription_delete": "SUPPORTED", "rss_list": "SUPPORTED", "rss_modify": "SUPPORTED", "rss_enable": "SUPPORTED",
                "rss_disable": "SUPPORTED", "rss_delete": "SUPPORTED", "rss_refresh": "SUPPORTED", "external_verify": "SUPPORTED",
                "checked_at": None, "safe_message": "已完成安全探测",
            }}, ensure_ascii=False))

        def sync(route: Any, request: Any) -> None:
            assert request.method == "POST"
            sync_calls.append(json.loads(request.post_data or "{}"))
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "result": {
                "sync_status": "COMPLETE", "checked_at": "2026-09-13T01:00:00+00:00",
                "capabilities": {
                    "probe_status": "VERIFIED", "version": "3.1.18", "adapter": "legacy_3_1",
                    "subscription_list": "SUPPORTED", "subscription_detail": "SUPPORTED", "subscription_submit": "SUPPORTED",
                    "subscription_modify": "SUPPORTED", "subscription_enable": "SUPPORTED", "subscription_disable": "SUPPORTED",
                    "subscription_delete": "SUPPORTED", "rss_list": "SUPPORTED", "rss_modify": "SUPPORTED", "rss_enable": "SUPPORTED",
                    "rss_disable": "SUPPORTED", "rss_delete": "SUPPORTED", "rss_refresh": "SUPPORTED", "external_verify": "SUPPORTED",
                    "checked_at": None, "safe_message": "同步安全摘要",
                },
                "summary": {"checked": 1, "created": 0, "updated": 1, "unchanged": 0, "external_only": 0, "failed": 0, "unreadable": 0},
                "items": [_item("tracking-a", "同步后的记录")], "warnings": [],
            }}, ensure_ascii=False))

        page.route("**/api/v1/autobangumi/capabilities", probe)
        page.route("**/api/v1/tracking/sync", sync)
        page.goto(f"{live_server_url}/app/tracking")
        page.wait_for_selector("#tracking-overview")
        expect(page.locator("#tracking-sync")).to_have_count(0)
        page.locator("#tracking-connect").click()
        page.locator("#tracking-ab-base-url").fill("https://private.invalid")
        page.locator("#tracking-ab-username").fill("user")
        page.locator("#tracking-ab-password").fill("secret-password")
        page.locator("#tracking-ab-probe").click()
        page.wait_for_selector("#tracking-sync")
        page.locator("#tracking-sync").click()
        assert not sync_calls
        expect(page.locator(".confirm-dialog")).to_be_visible()
        page.locator(".confirm-dialog-actions button").filter(has_text="确认同步").click()
        expect(page.locator("#tracking-sync-status")).to_contain_text("同步完成")
        expect(page.locator(".tracking-list-item")).to_contain_text("同步后的记录")
        assert len(sync_calls) == 1
        assert sync_calls[0]["confirm"] is True
        expect(page.locator("body")).not_to_contain_text("secret-password")

    def test_local_revalidate_reports_issues_and_never_creates_a_subscription(
        self, page: Page, live_server_url: str
    ) -> None:
        _require_dist()
        _mock_list(page)
        detail_reads: list[str] = []
        revalidate_calls: list[dict[str, Any]] = []

        def detail(route: Any, request: Any) -> None:
            detail_reads.append(request.method)
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"ok": True, "result": {
                    **_item("tracking-a", "葬送的芙莉莲", "ATTENTION"),
                    "status": "NEEDS_RECONFIRM", "status_label": "需重新确认",
                    "available_actions": [{
                        "code": "REVALIDATE", "label": "重新复核", "style": "SECONDARY",
                        "requires_confirmation": False, "target_scopes": [],
                    }],
                    "origin": "single", "batch_id": None, "created_at": "2026-09-01T00:00:00+00:00",
                    "updated_at": "2026-09-13T00:00:00+00:00", "last_synced_at": None,
                    "safe_info": None, "current_operation": None, "revalidation_issues": [],
                    "external_mapping": None, "audit_events": [], "warnings": [],
                }}, ensure_ascii=False),
            )

        def revalidate(route: Any, request: Any) -> None:
            assert request.method == "POST"
            revalidate_calls.append(json.loads(request.post_data or "{}"))
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "result": {
                "tracking_id": "tracking-a", "ready": False, "checked_revision": 1, "next_revision": 2,
                "checked_at": "2026-09-13T02:00:00+00:00", "next_status": "NEEDS_RECONFIRM",
                "issues": [{
                    "code": "REQUEST_CHANGED", "field": None,
                    "message": "本地方案已变化，需要重新确认后再提交", "recovery_action": "SUBMIT",
                }],
                "tracking": {
                    **_item("tracking-a", "葬送的芙莉莲", "ATTENTION"),
                    "status": "NEEDS_RECONFIRM", "status_label": "需重新确认", "revision": 2,
                    "available_actions": [{
                        "code": "REVALIDATE", "label": "重新复核", "style": "SECONDARY",
                        "requires_confirmation": False, "target_scopes": [],
                    }],
                },
            }}, ensure_ascii=False))

        page.route("**/api/v1/tracking/items/tracking-a/revalidate", revalidate)
        page.route("**/api/v1/tracking/items/tracking-a", detail)
        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        page.wait_for_selector("#tracking-overview")
        # Revalidation is pure local: it is offered with no Auto Bangumi session.
        expect(page.locator("#tracking-sync")).to_have_count(0)
        page.locator("#tracking-revalidate").click()
        page.wait_for_selector("#tracking-revalidate-result")

        result = page.locator("#tracking-revalidate-result")
        expect(result).to_contain_text("提交前复核未通过")
        expect(result).to_contain_text("尚未向 Auto Bangumi 创建订阅")
        expect(page.locator(".tracking-revalidate-issues")).to_contain_text("本地方案已变化")
        assert detail_reads == ["GET"], detail_reads
        assert len(revalidate_calls) == 1, revalidate_calls
        assert revalidate_calls[0] == {"expected_revision": 1}, revalidate_calls
        # The returned tracking converges the list row without a second read.
        expect(page.locator(".tracking-list-item").first).to_contain_text("需重新确认")
        # A real local plan exists, so the deep link back to it stays available.
        expect(page.locator(".tracking-plan-link")).to_have_attribute(
            "href", "/app/plans?request_id=request-tracking-a"
        )
        expect(page).to_have_url(f"{live_server_url}/app/tracking?tracking_id=tracking-a")

    def test_revalidate_conflict_refreshes_detail_and_requires_new_confirmation(
        self, page: Page, live_server_url: str
    ) -> None:
        _require_dist()
        _mock_list(page)
        state = {"revision": 1, "detail_reads": 0}
        revalidate_calls: list[dict[str, Any]] = []

        def detail(route: Any, request: Any) -> None:
            state["detail_reads"] += 1
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"ok": True, "result": {
                    **_item("tracking-a", "葬送的芙莉莲", "ATTENTION"),
                    "status": "NEEDS_RECONFIRM", "status_label": "需重新确认",
                    "revision": state["revision"],
                    "available_actions": [{
                        "code": "REVALIDATE", "label": "重新复核", "style": "SECONDARY",
                        "requires_confirmation": False, "target_scopes": [],
                    }],
                    "origin": "single", "batch_id": None, "created_at": "2026-09-01T00:00:00+00:00",
                    "updated_at": "2026-09-13T00:00:00+00:00", "last_synced_at": None,
                    "safe_info": None, "current_operation": None, "revalidation_issues": [],
                    "external_mapping": None, "audit_events": [], "warnings": [],
                }}, ensure_ascii=False),
            )

        def revalidate(route: Any, request: Any) -> None:
            assert request.method == "POST"
            body = json.loads(request.post_data or "{}")
            revalidate_calls.append(body)
            if len(revalidate_calls) == 1:
                # The record moved on while the user was looking at it.
                state["revision"] = 5
                route.fulfill(status=409, content_type="application/json", body=json.dumps({
                    "ok": False, "error_type": "tracking_revision_conflict",
                    "error_message": "追番记录版本已变化，请刷新后重试", "error_data": None,
                }, ensure_ascii=False))
                return
            assert body == {"expected_revision": 5}, body
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "result": {
                "tracking_id": "tracking-a", "ready": True, "checked_revision": 5, "next_revision": 5,
                "checked_at": "2026-09-13T02:05:00+00:00", "next_status": "PENDING_SUBMIT", "issues": [],
                "tracking": {
                    **_item("tracking-a", "葬送的芙莉莲"), "status": "PENDING_SUBMIT",
                    "status_label": "待提交", "status_group": "PENDING", "revision": 5,
                    "available_actions": [{
                        "code": "REVALIDATE", "label": "重新复核", "style": "SECONDARY",
                        "requires_confirmation": False, "target_scopes": [],
                    }],
                },
            }}, ensure_ascii=False))

        page.route("**/api/v1/tracking/items/tracking-a/revalidate", revalidate)
        page.route("**/api/v1/tracking/items/tracking-a", detail)
        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        page.wait_for_selector("#tracking-revalidate")
        page.locator("#tracking-revalidate").click()
        page.wait_for_selector("#tracking-revalidate-result")

        expect(page.locator("#tracking-revalidate-result")).to_contain_text("请重新确认后再发起复核")
        expect(page.locator("body")).not_to_contain_text("tracking_revision_conflict")
        # Nothing was silently resent; the stale intent forced a fresh detail read.
        assert len(revalidate_calls) == 1, revalidate_calls
        assert state["detail_reads"] == 2, state

        page.locator("#tracking-revalidate").click()
        expect(page.locator("#tracking-revalidate-result")).to_contain_text("复核通过")
        assert len(revalidate_calls) == 2, revalidate_calls
        expect(page.locator(".tracking-list-item").first).to_contain_text("待提交")
