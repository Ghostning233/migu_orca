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

    def test_explicit_submit_confirms_once_and_keeps_the_key_in_page_memory(
        self, page: Page, live_server_url: str
    ) -> None:
        _require_dist()
        _mock_list(page)
        submits: list[dict[str, Any]] = []
        state = {"revision": 1, "detail_reads": 0}

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

        def detail(route: Any, request: Any) -> None:
            state["detail_reads"] += 1
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "result": {
                **_item("tracking-a", "葬送的芙莉莲"),
                "status": "PENDING_SUBMIT", "status_label": "待提交", "revision": state["revision"],
                "available_actions": [
                    {"code": "REVALIDATE", "label": "重新复核", "style": "SECONDARY",
                     "requires_confirmation": False, "target_scopes": []},
                    {"code": "SUBMIT", "label": "提交到 Auto Bangumi", "style": "PRIMARY",
                     "requires_confirmation": True, "target_scopes": []},
                ],
                "origin": "single", "batch_id": None, "created_at": "2026-09-01T00:00:00+00:00",
                "updated_at": "2026-09-13T00:00:00+00:00", "last_synced_at": None,
                "safe_info": None, "current_operation": None, "revalidation_issues": [],
                "external_mapping": None, "audit_events": [], "warnings": [],
            }}, ensure_ascii=False))

        def submit(route: Any, request: Any) -> None:
            assert request.method == "POST"
            submits.append(json.loads(request.post_data or "{}"))
            state["revision"] = 2
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "result": {
                "tracking_id": "tracking-a", "outcome": "ACTIVE", "checked_revision": 1, "next_revision": 2,
                "checked_at": "2026-09-13T03:00:00+00:00", "operation_id": "operation-1", "issues": [],
                "tracking": {
                    **_item("tracking-a", "葬送的芙莉莲"), "status_label": "已提交外部订阅", "revision": 2,
                },
            }}, ensure_ascii=False))

        page.route("**/api/v1/autobangumi/capabilities", probe)
        # Registered after the two broader tracking routes: later routes win.
        page.route("**/api/v1/tracking/items/tracking-a/submit", submit)
        page.route("**/api/v1/tracking/items/tracking-a", detail)
        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        page.wait_for_selector("#tracking-overview")
        # No page credential session yet, so no external write is offered.
        expect(page.locator("#tracking-submit")).to_have_count(0)

        page.locator("#tracking-connect").click()
        page.locator("#tracking-ab-base-url").fill("https://private.invalid")
        page.locator("#tracking-ab-username").fill("secret-user")
        page.locator("#tracking-ab-password").fill("secret-password")
        page.locator("#tracking-ab-probe").click()
        page.wait_for_selector("#tracking-submit")
        # Connecting never submits on the user's behalf.
        assert not submits, submits

        page.locator("#tracking-submit").click()
        expect(page.locator(".confirm-dialog")).to_be_visible()
        expect(page.locator(".confirm-dialog-message")).to_contain_text("创建该追番的外部订阅")
        assert not submits, submits
        page.locator(".confirm-dialog-actions button").filter(has_text="取消").click()
        # Cancelling the impact confirmation sends zero requests.
        assert not submits, submits

        page.locator("#tracking-submit").click()
        page.locator(".confirm-dialog-actions button").filter(has_text="确认提交").click()
        page.wait_for_selector("#tracking-submit-result")

        expect(page.locator("#tracking-submit-result")).to_contain_text("提交成功")
        expect(page.locator("#tracking-submit-result")).not_to_contain_text("ACTIVE")
        assert len(submits) == 1, submits
        body = submits[0]
        assert body["confirm"] is True, body
        assert body["expected_revision"] == 1, body
        assert body["ab_config"]["password"] == "secret-password", body
        key = body["idempotency_key"]
        assert isinstance(key, str) and len(key) >= 8, body
        # The key lives in page memory only, and the write result converges the
        # list row from the returned tracking without a reload of the page.
        expect(page.locator(".tracking-list-item").first).to_contain_text("已提交外部订阅")
        expect(page).to_have_url(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        expect(page.locator("body")).not_to_contain_text("secret-password")
        expect(page.locator("body")).not_to_contain_text("secret-user")
        expect(page.locator("body")).not_to_contain_text(key)
        assert state["detail_reads"] >= 2, state

    def test_explicit_retry_requires_session_and_confirmation_and_keeps_the_key_in_memory(
        self, page: Page, live_server_url: str
    ) -> None:
        _require_dist()
        _mock_list(page)
        retries: list[dict[str, Any]] = []
        state = {"revision": 3, "detail_reads": 0}

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

        def detail(route: Any, request: Any) -> None:
            state["detail_reads"] += 1
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "result": {
                **_item("tracking-a", "葬送的芙莉莲", "ATTENTION"),
                "status": "SUBMIT_FAILED", "status_label": "提交失败", "revision": state["revision"],
                "available_actions": [
                    {"code": "REVALIDATE", "label": "重新复核", "style": "SECONDARY",
                     "requires_confirmation": False, "target_scopes": []},
                    {"code": "RETRY", "label": "重试提交", "style": "SECONDARY",
                     "requires_confirmation": True, "target_scopes": []},
                ],
                "origin": "single", "batch_id": None, "created_at": "2026-09-01T00:00:00+00:00",
                "updated_at": "2026-09-13T00:00:00+00:00", "last_synced_at": None,
                "safe_info": None, "current_operation": None, "revalidation_issues": [],
                "external_mapping": None, "audit_events": [], "warnings": [],
            }}, ensure_ascii=False))

        def retry(route: Any, request: Any) -> None:
            assert request.method == "POST"
            retries.append(json.loads(request.post_data or "{}"))
            state["revision"] = 4
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "result": {
                "tracking_id": "tracking-a", "outcome": "ACTIVE", "checked_revision": 3, "next_revision": 4,
                "checked_at": "2026-09-13T04:00:00+00:00", "operation_id": "operation-2", "issues": [],
                "tracking": {
                    **_item("tracking-a", "葬送的芙莉莲"), "status_label": "重试成功", "revision": 4,
                },
            }}, ensure_ascii=False))

        page.route("**/api/v1/autobangumi/capabilities", probe)
        # Registered after the broader tracking routes: later routes win.
        page.route("**/api/v1/tracking/items/tracking-a/retry", retry)
        page.route("**/api/v1/tracking/items/tracking-a", detail)
        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        page.wait_for_selector("#tracking-overview")
        # The retry action is server-computed and capability-gated: no session, no button.
        expect(page.locator("#tracking-retry")).to_have_count(0)
        expect(page.locator("#tracking-submit")).to_have_count(0)

        page.locator("#tracking-connect").click()
        page.locator("#tracking-ab-base-url").fill("https://private.invalid")
        page.locator("#tracking-ab-username").fill("secret-user")
        page.locator("#tracking-ab-password").fill("secret-password")
        page.locator("#tracking-ab-probe").click()
        page.wait_for_selector("#tracking-retry")
        # Connecting never retries on the user's behalf.
        assert not retries, retries

        page.locator("#tracking-retry").click()
        expect(page.locator(".confirm-dialog")).to_be_visible()
        expect(page.locator(".confirm-dialog-message")).to_contain_text("重新创建外部订阅")
        assert not retries, retries
        page.locator(".confirm-dialog-actions button").filter(has_text="取消").click()
        # Cancelling the impact confirmation sends zero requests.
        assert not retries, retries

        page.locator("#tracking-retry").click()
        page.locator(".confirm-dialog-actions button").filter(has_text="确认重试").click()
        page.wait_for_selector("#tracking-submit-result")

        expect(page.locator("#tracking-submit-result")).to_contain_text("提交成功")
        expect(page.locator("#tracking-submit-result")).not_to_contain_text("ACTIVE")
        assert len(retries) == 1, retries
        body = retries[0]
        assert body["confirm"] is True, body
        assert body["expected_revision"] == 3, body
        assert body["ab_config"]["password"] == "secret-password", body
        key = body["idempotency_key"]
        assert isinstance(key, str) and len(key) >= 8, body
        # The key lives in page memory only, and the returned tracking converges
        # the list row without a reload of the page.
        expect(page.locator(".tracking-list-item").first).to_contain_text("重试成功")
        expect(page).to_have_url(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        expect(page.locator("body")).not_to_contain_text("secret-password")
        expect(page.locator("body")).not_to_contain_text("secret-user")
        expect(page.locator("body")).not_to_contain_text(key)

    def test_retry_transport_unknown_locks_the_key_and_only_reads_back(
        self, page: Page, live_server_url: str
    ) -> None:
        _require_dist()
        _mock_list(page)
        retries: list[dict[str, Any]] = []
        state = {"detail_reads": 0}

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

        def detail(route: Any, request: Any) -> None:
            state["detail_reads"] += 1
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "result": {
                **_item("tracking-a", "葬送的芙莉莲", "ATTENTION"),
                "status": "SUBMIT_FAILED", "status_label": "提交失败", "revision": 3,
                "available_actions": [{
                    "code": "RETRY", "label": "重试提交", "style": "SECONDARY",
                    "requires_confirmation": True, "target_scopes": [],
                }],
                "origin": "single", "batch_id": None, "created_at": "2026-09-01T00:00:00+00:00",
                "updated_at": "2026-09-13T00:00:00+00:00", "last_synced_at": None,
                "safe_info": None, "current_operation": None, "revalidation_issues": [],
                "external_mapping": None, "audit_events": [], "warnings": [],
            }}, ensure_ascii=False))

        def retry(route: Any, request: Any) -> None:
            assert request.method == "POST"
            retries.append(json.loads(request.post_data or "{}"))
            if len(retries) == 1:
                # The request never got a readable answer: the external result is
                # unknown, so the page may only read back.
                route.abort()
                return
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "result": {
                "tracking_id": "tracking-a", "outcome": "ACTIVE", "checked_revision": 3, "next_revision": 4,
                "checked_at": "2026-09-13T04:05:00+00:00", "operation_id": "operation-2", "issues": [],
                "tracking": {
                    **_item("tracking-a", "葬送的芙莉莲"), "status_label": "重试成功", "revision": 4,
                },
            }}, ensure_ascii=False))

        page.route("**/api/v1/autobangumi/capabilities", probe)
        page.route("**/api/v1/tracking/items/tracking-a/retry", retry)
        page.route("**/api/v1/tracking/items/tracking-a", detail)
        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        page.wait_for_selector("#tracking-overview")
        page.locator("#tracking-connect").click()
        page.locator("#tracking-ab-base-url").fill("https://private.invalid")
        page.locator("#tracking-ab-username").fill("user")
        page.locator("#tracking-ab-password").fill("secret-password")
        page.locator("#tracking-ab-probe").click()
        page.wait_for_selector("#tracking-retry")

        page.locator("#tracking-retry").click()
        page.locator(".confirm-dialog-actions button").filter(has_text="确认重试").click()
        page.wait_for_selector("#tracking-submit-result")
        # Exactly one retry reached the server, and it says nothing was confirmed.
        expect(page.locator("#tracking-submit-result")).to_contain_text("提交结果未知")
        expect(page.locator("#tracking-submit-result")).to_contain_text("只读回查")
        expect(page.locator("body")).not_to_contain_text("network_error")
        assert len(retries) == 1, retries
        assert state["detail_reads"] >= 2, state

        # The explicit retry replays the very same key and revision binding.
        page.locator("#tracking-retry").click()
        page.locator(".confirm-dialog-actions button").filter(has_text="确认重试").click()
        page.wait_for_selector("#tracking-submit-result:has-text('提交成功')")
        assert len(retries) == 2, retries
        assert retries[1]["idempotency_key"] == retries[0]["idempotency_key"], retries
        assert retries[1]["expected_revision"] == retries[0]["expected_revision"], retries
        expect(page.locator(".tracking-list-item").first).to_contain_text("重试成功")

    def test_retry_conflict_converges_on_server_tracking_and_needs_a_new_key(
        self, page: Page, live_server_url: str
    ) -> None:
        _require_dist()
        _mock_list(page)
        retries: list[dict[str, Any]] = []
        state = {"revision": 3, "detail_reads": 0}

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

        def detail(route: Any, request: Any) -> None:
            state["detail_reads"] += 1
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "result": {
                **_item("tracking-a", "葬送的芙莉莲", "ATTENTION"),
                "status": "SUBMIT_FAILED", "status_label": "提交失败", "revision": state["revision"],
                "available_actions": [{
                    "code": "RETRY", "label": "重试提交", "style": "SECONDARY",
                    "requires_confirmation": True, "target_scopes": [],
                }],
                "origin": "single", "batch_id": None, "created_at": "2026-09-01T00:00:00+00:00",
                "updated_at": "2026-09-13T00:00:00+00:00", "last_synced_at": None,
                "safe_info": None, "current_operation": None, "revalidation_issues": [],
                "external_mapping": None, "audit_events": [], "warnings": [],
            }}, ensure_ascii=False))

        def retry(route: Any, request: Any) -> None:
            assert request.method == "POST"
            body = json.loads(request.post_data or "{}")
            retries.append(body)
            if len(retries) == 1:
                # The record moved on while the retry was in flight.
                state["revision"] = 9
                route.fulfill(status=409, content_type="application/json", body=json.dumps({
                    "ok": False, "error_type": "tracking_state_conflict",
                    "error_message": "只有明确提交失败的记录可以重试", "error_data": None,
                }, ensure_ascii=False))
                return
            assert body["expected_revision"] == 9, body
            assert body["idempotency_key"] != retries[0]["idempotency_key"], retries
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "result": {
                "tracking_id": "tracking-a", "outcome": "ACTIVE", "checked_revision": 9, "next_revision": 10,
                "checked_at": "2026-09-13T04:10:00+00:00", "operation_id": "operation-2", "issues": [],
                "tracking": {
                    **_item("tracking-a", "葬送的芙莉莲"), "status_label": "重试成功", "revision": 10,
                },
            }}, ensure_ascii=False))

        page.route("**/api/v1/autobangumi/capabilities", probe)
        page.route("**/api/v1/tracking/items/tracking-a/retry", retry)
        page.route("**/api/v1/tracking/items/tracking-a", detail)
        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        page.wait_for_selector("#tracking-overview")
        page.locator("#tracking-connect").click()
        page.locator("#tracking-ab-base-url").fill("https://private.invalid")
        page.locator("#tracking-ab-username").fill("user")
        page.locator("#tracking-ab-password").fill("secret-password")
        page.locator("#tracking-ab-probe").click()
        page.wait_for_selector("#tracking-retry")
        detail_reads_before = state["detail_reads"]

        page.locator("#tracking-retry").click()
        page.locator(".confirm-dialog-actions button").filter(has_text="确认重试").click()
        page.wait_for_selector("#tracking-submit-result")

        result = page.locator("#tracking-submit-result")
        expect(result).to_contain_text("未提交到 Auto Bangumi")
        expect(result).to_contain_text("请按最新状态重新确认")
        expect(page.locator("body")).not_to_contain_text("tracking_state_conflict")
        # Nothing was silently resent; the conflict re-read the server tracking.
        assert len(retries) == 1, retries
        assert state["detail_reads"] > detail_reads_before, state

        page.locator("#tracking-retry").click()
        page.locator(".confirm-dialog-actions button").filter(has_text="确认重试").click()
        page.wait_for_selector("#tracking-submit-result:has-text('提交成功')")
        assert len(retries) == 2, retries
        expect(page.locator(".tracking-list-item").first).to_contain_text("重试成功")

    def test_explicit_modify_sends_only_the_selected_scope_patch(
        self, page: Page, live_server_url: str
    ) -> None:
        _require_dist()
        _mock_list(page)
        modifies: list[dict[str, Any]] = []
        state = {"revision": 1, "detail_reads": 0}

        def detail(route: Any, request: Any) -> None:
            state["detail_reads"] += 1
            route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps(_modify_detail(state["revision"]), ensure_ascii=False),
            )

        def modify(route: Any, request: Any) -> None:
            assert request.method == "POST"
            modifies.append(json.loads(request.post_data or "{}"))
            state["revision"] = 2
            route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps(_modify_success_payload("已修改外部方案", 2), ensure_ascii=False),
            )

        page.route("**/api/v1/autobangumi/capabilities", _modify_probe)
        # Registered after the broader tracking routes: later routes win.
        page.route("**/api/v1/tracking/items/tracking-a/modify", modify)
        page.route("**/api/v1/tracking/items/tracking-a", detail)
        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        page.wait_for_selector("#tracking-overview")
        # MODIFY is server-computed and capability-gated: no session, no form.
        expect(page.locator("#tracking-modify-subscription-submit")).to_have_count(0)
        expect(page.locator("#tracking-modify-rss-submit")).to_have_count(0)

        page.locator("#tracking-connect").click()
        page.locator("#tracking-ab-base-url").fill("https://private.invalid")
        page.locator("#tracking-ab-username").fill("secret-user")
        page.locator("#tracking-ab-password").fill("secret-password")
        page.locator("#tracking-ab-probe").click()
        page.wait_for_selector("#tracking-modify-subscription-submit")
        # Both server-offered scopes are shown with user copy and no raw enum.
        expect(page.locator(".tracking-modify-scope")).to_have_count(2)
        section = page.locator(".tracking-modify-section")
        expect(section).to_contain_text("外部番剧订阅")
        expect(section).to_contain_text("关联 RSS")
        expect(section).not_to_contain_text("SUBSCRIPTION")
        expect(section).not_to_contain_text("ASSOCIATED_RSS")
        # Connecting never modifies anything on the user's behalf.
        assert not modifies, modifies

        # An empty form is not submittable at all.
        expect(page.locator("#tracking-modify-subscription-submit")).to_be_disabled()

        # The two scope forms are separate: the RSS selection never leaks into
        # the subscription request.
        page.locator("#tracking-modify-title-enabled").check()
        page.locator("#tracking-modify-title").fill("公开新标题")
        page.locator("#tracking-modify-rss-name-enabled").check()
        page.locator("#tracking-modify-rss-name").fill("不该出现在订阅请求里")
        page.locator("#tracking-modify-subscription-submit").click()
        expect(page.locator(".confirm-dialog")).to_be_visible()
        expect(page.locator(".confirm-dialog-message")).to_contain_text("不修改 MiGuOrca 本地方案")
        assert not modifies, modifies
        page.locator(".confirm-dialog-actions button").filter(has_text="取消").click()
        assert not modifies, modifies

        page.locator("#tracking-modify-subscription-submit").click()
        page.locator(".confirm-dialog-actions button").filter(has_text="确认修改订阅").click()
        page.wait_for_selector("#tracking-modify-result")

        expect(page.locator("#tracking-modify-result")).to_contain_text("已应用本次修改")
        expect(page.locator("#tracking-modify-result")).not_to_contain_text("SUCCEEDED")
        assert len(modifies) == 1, modifies
        body = modifies[0]
        assert body["target_scope"] == "SUBSCRIPTION", body
        assert body["patch"] == {"title": "公开新标题"}, body
        assert body["confirm"] is True, body
        assert body["expected_revision"] == 1, body
        assert body["ab_config"]["password"] == "secret-password", body
        key = body["idempotency_key"]
        assert isinstance(key, str) and len(key) >= 8, body
        # The returned tracking converges the list row in place.
        expect(page.locator(".tracking-list-item").first).to_contain_text("已修改外部方案")
        expect(page.locator("body")).not_to_contain_text("secret-password")
        expect(page.locator("body")).not_to_contain_text("secret-user")
        expect(page.locator("body")).not_to_contain_text(key)
        assert state["detail_reads"] >= 2, state

    def test_modify_unknown_result_locks_the_intent_and_never_resends(
        self, page: Page, live_server_url: str
    ) -> None:
        _require_dist()
        _mock_list(page)
        modifies: list[dict[str, Any]] = []
        state = {"revision": 1, "detail_reads": 0}

        def detail(route: Any, request: Any) -> None:
            state["detail_reads"] += 1
            route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps(
                    _modify_detail(state["revision"], scopes=["ASSOCIATED_RSS"]), ensure_ascii=False,
                ),
            )

        def modify(route: Any, request: Any) -> None:
            assert request.method == "POST"
            modifies.append(json.loads(request.post_data or "{}"))
            if len(modifies) == 1:
                # The request never got a readable answer: the external result is
                # unknown, so the page may only read back.
                route.abort()
                return
            state["revision"] = 2
            route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps(_modify_success_payload("已修改外部方案", 2), ensure_ascii=False),
            )

        page.route("**/api/v1/autobangumi/capabilities", _modify_probe)
        page.route("**/api/v1/tracking/items/tracking-a/modify", modify)
        page.route("**/api/v1/tracking/items/tracking-a", detail)
        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        page.wait_for_selector("#tracking-overview")
        page.locator("#tracking-connect").click()
        page.locator("#tracking-ab-base-url").fill("https://private.invalid")
        page.locator("#tracking-ab-username").fill("user")
        page.locator("#tracking-ab-password").fill("secret-password")
        page.locator("#tracking-ab-probe").click()
        page.wait_for_selector("#tracking-modify-rss-submit")

        page.locator("#tracking-modify-rss-name-enabled").check()
        page.locator("#tracking-modify-rss-name").fill("第一次修改")
        page.locator("#tracking-modify-rss-submit").click()
        page.locator(".confirm-dialog-actions button").filter(has_text="确认修改 RSS").click()
        page.wait_for_selector("#tracking-modify-result")

        expect(page.locator("#tracking-modify-result")).to_contain_text("外部修改结果未知")
        expect(page.locator("#tracking-modify-result")).to_contain_text("只读回查")
        expect(page.locator("body")).not_to_contain_text("network_error")
        assert len(modifies) == 1, modifies
        assert state["detail_reads"] >= 2, state

        # A *different* request while the result is still unresolved is refused
        # with zero requests — and the page states the fixed next step instead of
        # leaving the user with a dead button. The unresolved result panel keeps
        # its own copy.
        page.locator("#tracking-modify-rss-name-enabled").check()
        page.locator("#tracking-modify-rss-name").fill("第二次不同修改")
        page.locator("#tracking-modify-rss-submit").click()
        expect(page.locator("#tracking-intent-blocked-notice")).to_be_visible()
        expect(page.locator("#tracking-intent-blocked-notice")).to_have_attribute("role", "status")
        expect(page.locator("#tracking-intent-blocked-notice")).to_contain_text(
            "上一次外部操作的结果仍未确认"
        )
        expect(page.locator("#tracking-modify-result")).to_contain_text("外部修改结果未知")
        expect(page.locator("body")).not_to_contain_text("network_error")
        assert len(modifies) == 1, modifies

        # The user re-selects the identical field set; the page recognises the
        # locked intent and replays the very same key and revision binding.
        page.locator("#tracking-modify-rss-name-enabled").check()
        page.locator("#tracking-modify-rss-name").fill("第一次修改")
        page.locator("#tracking-modify-rss-submit").click()
        page.locator(".confirm-dialog-actions button").filter(has_text="确认修改 RSS").click()
        page.wait_for_selector("#tracking-modify-result:has-text('已应用本次修改')")
        # Replaying the same intent ends the refusal, so the notice disappears.
        expect(page.locator("#tracking-intent-blocked-notice")).to_have_count(0)
        assert len(modifies) == 2, modifies
        assert modifies[1]["idempotency_key"] == modifies[0]["idempotency_key"], modifies
        assert modifies[1]["expected_revision"] == modifies[0]["expected_revision"], modifies
        expect(page.locator(".tracking-list-item").first).to_contain_text("已修改外部方案")

    def test_modify_conflict_rereads_both_views_and_needs_a_new_key(
        self, page: Page, live_server_url: str
    ) -> None:
        _require_dist()
        _mock_list(page)
        modifies: list[dict[str, Any]] = []
        state = {"revision": 1, "detail_reads": 0}

        def detail(route: Any, request: Any) -> None:
            state["detail_reads"] += 1
            route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps(
                    _modify_detail(state["revision"], scopes=["SUBSCRIPTION"]), ensure_ascii=False,
                ),
            )

        def modify(route: Any, request: Any) -> None:
            assert request.method == "POST"
            body = json.loads(request.post_data or "{}")
            modifies.append(body)
            if len(modifies) == 1:
                # The record moved on while the modify was in flight.
                state["revision"] = 9
                route.fulfill(status=409, content_type="application/json", body=json.dumps({
                    "ok": False, "error_type": "tracking_management_state_conflict",
                    "error_message": "已有管理操作正在执行，请先恢复", "error_data": None,
                }, ensure_ascii=False))
                return
            assert body["expected_revision"] == 9, body
            assert body["idempotency_key"] != modifies[0]["idempotency_key"], modifies
            route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps(_modify_success_payload("已修改外部方案", 10), ensure_ascii=False),
            )

        page.route("**/api/v1/autobangumi/capabilities", _modify_probe)
        page.route("**/api/v1/tracking/items/tracking-a/modify", modify)
        page.route("**/api/v1/tracking/items/tracking-a", detail)
        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        page.wait_for_selector("#tracking-overview")
        page.locator("#tracking-connect").click()
        page.locator("#tracking-ab-base-url").fill("https://private.invalid")
        page.locator("#tracking-ab-username").fill("user")
        page.locator("#tracking-ab-password").fill("secret-password")
        page.locator("#tracking-ab-probe").click()
        page.wait_for_selector("#tracking-modify-subscription-submit")

        page.locator("#tracking-modify-title-enabled").check()
        page.locator("#tracking-modify-title").fill("冲突修改")
        page.locator("#tracking-modify-subscription-submit").click()
        page.locator(".confirm-dialog-actions button").filter(has_text="确认修改订阅").click()
        page.wait_for_selector("#tracking-modify-result")

        expect(page.locator("#tracking-modify-result")).to_contain_text("未提交到 Auto Bangumi")
        expect(page.locator("#tracking-modify-result")).to_contain_text("先完成恢复")
        expect(page.locator("body")).not_to_contain_text("tracking_management_state_conflict")
        # Nothing was silently resent; the stale intent forced fresh reads.
        assert len(modifies) == 1, modifies
        assert state["detail_reads"] >= 2, state

        # The conflict released the intent, so the next confirmation against the
        # fresh revision mints a brand new key.
        page.locator("#tracking-modify-title-enabled").check()
        page.locator("#tracking-modify-title").fill("重试修改")
        page.locator("#tracking-modify-subscription-submit").click()
        page.locator(".confirm-dialog-actions button").filter(has_text="确认修改订阅").click()
        page.wait_for_selector("#tracking-modify-result:has-text('已应用本次修改')")
        assert len(modifies) == 2, modifies
        expect(page.locator(".tracking-list-item").first).to_contain_text("已修改外部方案")

    def test_modify_capability_degradation_hides_the_scope(
        self, page: Page, live_server_url: str
    ) -> None:
        _require_dist()
        _mock_list(page)

        def probe(route: Any, request: Any) -> None:
            assert request.method == "POST"
            payload = _probe_capabilities()
            payload["rss_modify"] = "UNSUPPORTED"
            route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps({"ok": True, "result": payload}, ensure_ascii=False),
            )

        def detail(route: Any, request: Any) -> None:
            route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps(_modify_detail(1), ensure_ascii=False),
            )

        page.route("**/api/v1/autobangumi/capabilities", probe)
        page.route("**/api/v1/tracking/items/tracking-a", detail)
        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        page.wait_for_selector("#tracking-overview")
        page.locator("#tracking-connect").click()
        page.locator("#tracking-ab-base-url").fill("https://private.invalid")
        page.locator("#tracking-ab-username").fill("user")
        page.locator("#tracking-ab-password").fill("secret-password")
        page.locator("#tracking-ab-probe").click()
        page.wait_for_selector("#tracking-modify-subscription-submit")
        # Only the scope whose capability is proven is offered at all.
        expect(page.locator("#tracking-modify-rss-submit")).to_have_count(0)
        expect(page.locator(".tracking-modify-scope")).to_have_count(1)
        expect(page.locator(".tracking-modify-scope")).to_have_text("外部番剧订阅")
        # The remaining form still works: selecting a field makes it submittable.
        expect(page.locator("#tracking-modify-subscription-submit")).to_be_disabled()
        page.locator("#tracking-modify-title-enabled").check()
        page.locator("#tracking-modify-title").fill("降级下仍可修改")
        expect(page.locator("#tracking-modify-subscription-submit")).to_be_enabled()


def _modify_actions(scopes: list[str] | None = None) -> list[dict[str, Any]]:
    return [{
        "code": "MODIFY", "label": "修改外部方案", "style": "SECONDARY",
        "requires_confirmation": True,
        "target_scopes": scopes if scopes is not None else ["SUBSCRIPTION", "ASSOCIATED_RSS"],
    }]


def _modify_detail(revision: int, scopes: list[str] | None = None) -> dict[str, Any]:
    """The full ``getTrackingItemDetail`` envelope for one modify revision."""
    return {"ok": True, "result": {
        **_item("tracking-a", "葬送的芙莉莲"),
        "available_actions": _modify_actions(scopes),
        "revision": revision,
        "origin": "single", "batch_id": None, "created_at": "2026-09-01T00:00:00+00:00",
        "updated_at": "2026-09-13T00:00:00+00:00", "last_synced_at": None,
        "safe_info": None, "current_operation": None, "revalidation_issues": [],
        "external_mapping": {"match_reason": "标题与季度匹配", "enabled": True, "external_deleted": False},
        "audit_events": [], "warnings": [],
    }}


def _modify_success_payload(status_label: str, revision: int) -> dict[str, Any]:
    return {"ok": True, "result": {
        "action": "MODIFY", "management_status": "SUCCEEDED", "needs_manual": False,
        "safe_message": "Auto Bangumi 管理操作已完成并通过回查", "operation_id": "operation-modify",
        "operation": None,
        "tracking": {
            **_item("tracking-a", "葬送的芙莉莲"), "status_label": status_label, "revision": revision,
        },
    }}


def _modify_probe(route: Any, request: Any) -> None:
    assert request.method == "POST"
    route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"ok": True, "result": _probe_capabilities()}, ensure_ascii=False),
    )

def _recovery_actions() -> list[dict[str, Any]]:
    return [
        {"code": "RECOVER_AUTO", "label": "自动恢复", "style": "SECONDARY",
         "requires_confirmation": False, "target_scopes": []},
        {"code": "MARK_SUCCEEDED", "label": "标记为成功", "style": "PRIMARY",
         "requires_confirmation": True, "target_scopes": []},
        {"code": "MARK_FAILED", "label": "标记为失败", "style": "DANGER",
         "requires_confirmation": True, "target_scopes": []},
    ]


def _recovery_item(tracking_id: str, title: str, **overrides: Any) -> dict[str, Any]:
    return {
        **_item(tracking_id, title, "ATTENTION"),
        "status": "RECOVERY_REQUIRED", "status_label": "需要恢复",
        "available_actions": _recovery_actions(), **overrides,
    }


def _detail_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **item, "origin": "single", "batch_id": None, "created_at": "2026-09-01T00:00:00+00:00",
        "updated_at": "2026-09-13T00:00:00+00:00", "last_synced_at": None, "safe_info": None,
        "current_operation": None, "revalidation_issues": [], "external_mapping": None,
        "audit_events": [], "warnings": [],
    }


def _probe_capabilities() -> dict[str, Any]:
    return {
        "probe_status": "VERIFIED", "version": "3.1.18", "adapter": "legacy_3_1",
        "subscription_list": "SUPPORTED", "subscription_detail": "SUPPORTED", "subscription_submit": "SUPPORTED",
        "subscription_modify": "SUPPORTED", "subscription_enable": "SUPPORTED", "subscription_disable": "SUPPORTED",
        "subscription_delete": "SUPPORTED", "rss_list": "SUPPORTED", "rss_modify": "SUPPORTED", "rss_enable": "SUPPORTED",
        "rss_disable": "SUPPORTED", "rss_delete": "SUPPORTED", "rss_refresh": "SUPPORTED", "external_verify": "SUPPORTED",
        "checked_at": None, "safe_message": "已完成安全探测",
    }


class TestAppTrackingRecovery:
    """US-312: unknown-result recovery in a real Chromium session."""

    def test_local_auto_and_manual_verdict_stay_separate_and_safe(
        self, page: Page, live_server_url: str
    ) -> None:
        _require_dist()
        recover_calls: list[dict[str, Any]] = []
        state = {"revision": 1}
        requests: list[str] = []
        page.on("request", lambda request: requests.append(request.url))

        def detail(route: Any, request: Any) -> None:
            route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps({"ok": True, "result": _detail_payload(
                    _recovery_item("tracking-a", "葬送的芙莉莲", revision=state["revision"]),
                )}, ensure_ascii=False),
            )

        def recover(route: Any, request: Any) -> None:
            assert request.method == "POST"
            body = json.loads(request.post_data or "{}")
            recover_calls.append(body)
            if body["action"] == "AUTO":
                # No local evidence: only a human verdict can progress.
                state["revision"] = 2
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "result": {
                    "tracking_id": "tracking-a", "action": "AUTO", "outcome": "RECOVERY_REQUIRED",
                    "checked_revision": 1, "next_revision": 2, "checked_at": "2026-09-13T06:00:00+00:00",
                    "operation_id": "operation-1", "needs_manual": True,
                    "tracking": _recovery_item("tracking-a", "葬送的芙莉莲", revision=2),
                }}, ensure_ascii=False))
                return
            state["revision"] = 3
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "result": {
                "tracking_id": "tracking-a", "action": "MARK_SUCCEEDED", "outcome": "ACTIVE",
                "checked_revision": 2, "next_revision": 3, "checked_at": "2026-09-13T06:05:00+00:00",
                "operation_id": "operation-1", "needs_manual": False,
                "tracking": {
                    **_item("tracking-a", "葬送的芙莉莲"), "status_label": "已恢复",
                    "revision": 3, "available_actions": [],
                },
            }}, ensure_ascii=False))

        _mock_list(page)
        # Registered after the broader tracking routes: later routes win.
        page.route("**/api/v1/tracking/items/tracking-a/recover", recover)
        page.route("**/api/v1/tracking/items/tracking-a", detail)
        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        page.wait_for_selector("#tracking-overview")

        # The three local recovery actions need no page session at all; the
        # read-only external check is not offered without one.
        expect(page.locator("#tracking-recover-auto")).to_be_visible()
        expect(page.locator("#tracking-recover-succeeded")).to_be_visible()
        expect(page.locator("#tracking-recover-failed")).to_be_visible()
        expect(page.locator("#tracking-recover-verify")).to_have_count(0)

        page.locator("#tracking-recover-auto").click()
        page.wait_for_selector("#tracking-recovery-result")
        # AUTO is pure local: no confirmation dialog and a credential-free body.
        expect(page.locator(".confirm-dialog")).to_have_count(0)
        assert recover_calls == [{"expected_revision": 1, "action": "AUTO"}], recover_calls
        notice = page.locator("#tracking-recovery-manual-notice")
        expect(notice).to_contain_text("先在 Auto Bangumi 中独立核对")
        expect(page.locator("#tracking-recovery-result")).not_to_contain_text("RECOVERY_REQUIRED")

        # A manual verdict is always confirmed again, and the default focus is
        # the cancel button so a stray Enter cannot assert a verdict.
        page.locator("#tracking-recover-succeeded").click()
        expect(page.locator(".confirm-dialog")).to_be_visible()
        expect(page.locator(".confirm-dialog-message")).to_contain_text("独立核对")
        assert page.evaluate("document.activeElement.textContent") == "取消", "default focus must be cancel"
        page.locator(".confirm-dialog-actions button").filter(has_text="取消").click()
        expect(page.locator(".confirm-dialog")).to_have_count(0)
        assert len(recover_calls) == 1, recover_calls

        page.locator("#tracking-recover-succeeded").click()
        page.locator(".confirm-dialog-actions button").filter(has_text="确认标记成功").click()
        page.wait_for_selector("#tracking-recovery-result:has-text('恢复完成')")
        assert recover_calls == [
            {"expected_revision": 1, "action": "AUTO"},
            {"expected_revision": 2, "action": "MARK_SUCCEEDED", "confirm": True},
        ], recover_calls
        expect(page.locator(".tracking-list-item").first).to_contain_text("已恢复")
        expect(page).to_have_url(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        # Recovery never touches a submit/retry endpoint and leaks nothing.
        assert not [url for url in requests if "/submit" in url or "/retry" in url], requests
        assert "MARK_SUCCEEDED" not in page.locator("body").inner_text()

    def test_read_only_external_verification_needs_the_live_page_session(
        self, page: Page, live_server_url: str
    ) -> None:
        _require_dist()
        recover_calls: list[dict[str, Any]] = []
        requests: list[str] = []
        page.on("request", lambda request: requests.append(request.url))

        def detail(route: Any, request: Any) -> None:
            route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps({"ok": True, "result": _detail_payload(
                    _recovery_item("tracking-a", "葬送的芙莉莲", revision=4),
                )}, ensure_ascii=False),
            )

        def probe(route: Any, request: Any) -> None:
            assert request.method == "POST"
            route.fulfill(status=200, content_type="application/json", body=json.dumps(
                {"ok": True, "result": _probe_capabilities()}, ensure_ascii=False,
            ))

        def recover(route: Any, request: Any) -> None:
            assert request.method == "POST"
            recover_calls.append(json.loads(request.post_data or "{}"))
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "result": {
                "tracking_id": "tracking-a", "action": "VERIFY_EXTERNAL", "outcome": "RECOVERY_REQUIRED",
                "checked_revision": 4, "next_revision": 4, "checked_at": "2026-09-13T06:10:00+00:00",
                "operation_id": "operation-1", "needs_manual": True,
                "tracking": _recovery_item("tracking-a", "葬送的芙莉莲", revision=4),
            }}, ensure_ascii=False))

        _mock_list(page)
        page.route("**/api/v1/autobangumi/capabilities", probe)
        page.route("**/api/v1/tracking/items/tracking-a/recover", recover)
        page.route("**/api/v1/tracking/items/tracking-a", detail)
        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        page.wait_for_selector("#tracking-overview")
        expect(page.locator("#tracking-recover-verify")).to_have_count(0)

        page.locator("#tracking-connect").click()
        page.locator("#tracking-ab-base-url").fill("https://private.invalid")
        page.locator("#tracking-ab-username").fill("secret-user")
        page.locator("#tracking-ab-password").fill("secret-password")
        page.locator("#tracking-ab-probe").click()
        page.wait_for_selector("#tracking-recover-verify")
        assert not recover_calls, recover_calls

        page.locator("#tracking-recover-verify").click()
        expect(page.locator(".confirm-dialog-message")).to_contain_text("只读核对")
        page.locator(".confirm-dialog-actions button").filter(has_text="确认只读核验").click()
        page.wait_for_selector("#tracking-recovery-result")

        assert len(recover_calls) == 1, recover_calls
        body = recover_calls[0]
        # The read-only check spends the page credential and asserts no verdict.
        assert body["action"] == "VERIFY_EXTERNAL", body
        assert "confirm" not in body, body
        assert "external_id" not in body and "note" not in body, body
        assert body["ab_config"]["password"] == "secret-password", body
        assert body["ab_config"]["base_url"] == "https://private.invalid", body
        expect(page.locator("#tracking-recovery-manual-notice")).to_contain_text("独立核对")
        # The credential stays in the single request body: not in the page or URL.
        assert not [url for url in requests if "/submit" in url or "/retry" in url], requests
        expect(page).to_have_url(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        expect(page.locator("body")).not_to_contain_text("secret-password")
        expect(page.locator("body")).not_to_contain_text("secret-user")
        expect(page.locator("body")).not_to_contain_text("VERIFY_EXTERNAL")


def _management_actions(status: str = "ACTIVE") -> list[dict[str, Any]]:
    """The server-computed actions a US-314 record offers for its own status."""
    enabled = status == "DISABLED"
    return [
        {"code": "SET_ENABLED", "label": "启用外部订阅" if enabled else "停用外部订阅",
         "style": "PRIMARY" if enabled else "SECONDARY", "requires_confirmation": True,
         "target_scopes": ["SUBSCRIPTION", "ASSOCIATED_RSS"]},
        {"code": "REFRESH_RSS", "label": "刷新关联 RSS", "style": "SECONDARY",
         "requires_confirmation": True, "target_scopes": ["ASSOCIATED_RSS"]},
        # The server offers the per-record external delete here too; wiring it is
        # its own story, so this page must never render or send it (US-314).
        {"code": "DELETE_EXTERNAL", "label": "删除外部订阅", "style": "DANGER",
         "requires_confirmation": True, "target_scopes": ["SUBSCRIPTION", "ASSOCIATED_RSS"]},
    ]


def _action_detail(revision: int, status: str = "ACTIVE") -> dict[str, Any]:
    """The full ``getTrackingItemDetail`` envelope for one US-314 revision."""
    return {"ok": True, "result": {
        **_item("tracking-a", "葬送的芙莉莲"),
        "status": status,
        "status_label": "已停用" if status == "DISABLED" else "追番中",
        "available_actions": _management_actions(status),
        "revision": revision,
        "origin": "single", "batch_id": None, "created_at": "2026-09-01T00:00:00+00:00",
        "updated_at": "2026-09-13T00:00:00+00:00", "last_synced_at": None,
        "safe_info": None, "current_operation": None, "revalidation_issues": [],
        "external_mapping": {"match_reason": "标题与季度匹配", "enabled": status != "DISABLED",
                             "external_deleted": False},
        "audit_events": [], "warnings": [],
    }}


def _action_success_payload(action: str, status_label: str, revision: int) -> dict[str, Any]:
    return {"ok": True, "result": {
        "action": action, "management_status": "SUCCEEDED", "needs_manual": False,
        "safe_message": "Auto Bangumi 管理操作已完成并通过回查", "operation_id": "operation-actions",
        "operation": None,
        "tracking": {
            **_item("tracking-a", "葬送的芙莉莲"), "status_label": status_label, "revision": revision,
        },
    }}


class TestAppTrackingManagementActions:
    """US-314: enable/disable and associated-RSS refresh in a real Chromium session."""

    def test_explicit_enable_needs_a_chosen_target_and_sends_only_set_enabled(
        self, page: Page, live_server_url: str
    ) -> None:
        _require_dist()
        _mock_list(page)
        enables: list[dict[str, Any]] = []
        state = {"revision": 1}

        def detail(route: Any, request: Any) -> None:
            route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps(_action_detail(state["revision"]), ensure_ascii=False),
            )

        def set_enabled(route: Any, request: Any) -> None:
            assert request.method == "POST"
            enables.append(json.loads(request.post_data or "{}"))
            state["revision"] = 2
            route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps(_action_success_payload("SET_ENABLED", "已停用外部订阅", 2), ensure_ascii=False),
            )

        page.route("**/api/v1/autobangumi/capabilities", _modify_probe)
        # Registered after the broader tracking routes: later routes win.
        page.route("**/api/v1/tracking/items/tracking-a/set-enabled", set_enabled)
        page.route("**/api/v1/tracking/items/tracking-a", detail)
        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        page.wait_for_selector("#tracking-overview")
        # Server-computed and capability-gated: no session, no action at all.
        expect(page.locator("#tracking-set-enabled-submit")).to_have_count(0)
        expect(page.locator("#tracking-refresh-rss-submit")).to_have_count(0)
        expect(page.locator(".tracking-management-actions-section")).to_contain_text("需要先在页面连接")

        page.locator("#tracking-connect").click()
        page.locator("#tracking-ab-base-url").fill("https://private.invalid")
        page.locator("#tracking-ab-username").fill("secret-user")
        page.locator("#tracking-ab-password").fill("secret-password")
        page.locator("#tracking-ab-probe").click()
        page.wait_for_selector("#tracking-set-enabled-submit")
        # Both server-offered targets are named in user copy, never as raw enums.
        section = page.locator(".tracking-management-actions-section")
        expect(section).to_contain_text("外部番剧订阅")
        expect(section).to_contain_text("关联 RSS")
        expect(section).not_to_contain_text("SUBSCRIPTION")
        expect(section).not_to_contain_text("ASSOCIATED_RSS")
        assert not enables, enables
        # DELETE_EXTERNAL is server-offered but not wired by this page: it has
        # no control at all and never becomes a request.
        assert page.locator("[id*='delete-external']").count() == 0, "delete control rendered"
        assert section.locator("button.danger-button").count() == 0, section.inner_text()

        # The enable/disable target is the user's explicit choice: nothing is
        # pre-selected and nothing can be sent before one is picked.
        expect(page.locator("#tracking-set-enabled-submit")).to_be_disabled()
        expect(section).to_contain_text("请先明确选择启停目标")
        page.locator("#tracking-set-enabled-scope-SUBSCRIPTION").check()
        expect(page.locator("#tracking-set-enabled-submit")).to_be_enabled()

        page.locator("#tracking-set-enabled-submit").click()
        expect(page.locator(".confirm-dialog")).to_be_visible()
        expect(page.locator(".confirm-dialog-message")).to_contain_text("不修改 MiGuOrca 本地方案")
        assert not enables, enables
        page.locator(".confirm-dialog-actions button").filter(has_text="取消").click()
        assert not enables, enables

        page.locator("#tracking-set-enabled-submit").click()
        page.locator(".confirm-dialog-actions button").filter(has_text="确认停用订阅").click()
        page.wait_for_selector("#tracking-management-result")

        expect(page.locator("#tracking-management-result")).to_contain_text("外部启停已完成")
        expect(page.locator("#tracking-management-result")).not_to_contain_text("SUCCEEDED")
        assert len(enables) == 1, enables
        body = enables[0]
        assert body["target_scope"] == "SUBSCRIPTION", body
        # The direction comes from the record status, and the body carries no
        # patch, no external id and no second scope.
        assert body["enabled"] is False, body
        assert "patch" not in body, body
        assert body["confirm"] is True, body
        assert body["expected_revision"] == 1, body
        assert body["ab_config"]["password"] == "secret-password", body
        key = body["idempotency_key"]
        assert isinstance(key, str) and len(key) >= 8, body
        expect(page.locator(".tracking-list-item").first).to_contain_text("已停用外部订阅")
        expect(page.locator("body")).not_to_contain_text("secret-password")
        expect(page.locator("body")).not_to_contain_text("secret-user")
        expect(page.locator("body")).not_to_contain_text(key)
        assert not [url for url in page.url.split() if "modify" in url], page.url

    def test_explicit_refresh_only_touches_the_current_record(
        self, page: Page, live_server_url: str
    ) -> None:
        _require_dist()
        _mock_list(page)
        refreshes: list[dict[str, Any]] = []
        posted: list[str] = []
        page.on("request", lambda request: posted.append(request.url) if request.method == "POST" else None)
        state = {"revision": 1}

        def detail(route: Any, request: Any) -> None:
            route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps(_action_detail(state["revision"]), ensure_ascii=False),
            )

        def refresh(route: Any, request: Any) -> None:
            assert request.method == "POST"
            refreshes.append(json.loads(request.post_data or "{}"))
            route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps(_action_success_payload("REFRESH_RSS", "已刷新关联 RSS", 2), ensure_ascii=False),
            )

        page.route("**/api/v1/autobangumi/capabilities", _modify_probe)
        page.route("**/api/v1/tracking/items/tracking-a/refresh", refresh)
        page.route("**/api/v1/tracking/items/tracking-a", detail)
        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        page.wait_for_selector("#tracking-overview")
        page.locator("#tracking-connect").click()
        page.locator("#tracking-ab-base-url").fill("https://private.invalid")
        page.locator("#tracking-ab-username").fill("user")
        page.locator("#tracking-ab-password").fill("secret-password")
        page.locator("#tracking-ab-probe").click()
        page.wait_for_selector("#tracking-refresh-rss-submit")

        page.locator("#tracking-refresh-rss-submit").click()
        expect(page.locator(".confirm-dialog-message")).to_contain_text("不会刷新全局 RSS")
        assert not refreshes, refreshes
        page.locator(".confirm-dialog-actions button").filter(has_text="确认刷新关联 RSS").click()
        page.wait_for_selector("#tracking-management-result")

        expect(page.locator("#tracking-management-result")).to_contain_text("关联 RSS 刷新已完成")
        assert len(refreshes) == 1, refreshes
        body = refreshes[0]
        assert body["target_scope"] == "ASSOCIATED_RSS", body
        assert "patch" not in body and "enabled" not in body, body
        assert body["confirm"] is True, body
        # Only the current record's own refresh route was ever called: there is
        # no global refresh, and no subscription/modify/delete write happened.
        write_calls = [
            url for url in posted
            if "/api/v1/" in url and "/autobangumi/capabilities" not in url
        ]
        assert len(write_calls) == 1, write_calls
        assert write_calls[0].endswith("/api/v1/tracking/items/tracking-a/refresh"), write_calls
        assert not [url for url in posted if "refresh/all" in url or "/modify" in url], posted
        assert not [url for url in posted if "/delete-external" in url], posted
        # The batch record keeps its own tracking id in the deep link.
        expect(page).to_have_url(f"{live_server_url}/app/tracking?tracking_id=tracking-a")

    def test_partial_refresh_is_unresolved_and_only_read_back(
        self, page: Page, live_server_url: str
    ) -> None:
        _require_dist()
        _mock_list(page)
        refreshes: list[dict[str, Any]] = []
        state = {"revision": 1, "detail_reads": 0}

        def detail(route: Any, request: Any) -> None:
            state["detail_reads"] += 1
            route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps(_action_detail(state["revision"]), ensure_ascii=False),
            )

        def refresh(route: Any, request: Any) -> None:
            assert request.method == "POST"
            refreshes.append(json.loads(request.post_data or "{}"))
            if len(refreshes) == 1:
                # A batch with accepted and rejected upstream writes: the server
                # reports recovery required, never success.
                route.fulfill(
                    status=200, content_type="application/json",
                    body=json.dumps({"ok": True, "result": {
                        "action": "REFRESH_RSS", "management_status": "RECOVERY_REQUIRED",
                        "needs_manual": True, "safe_message": "外部管理结果未知，请人工恢复；不会自动重试",
                        "operation_id": "operation-actions", "operation": None,
                        "tracking": {**_item("tracking-a", "葬送的芙莉莲"),
                                     "status_label": "需要恢复", "revision": 2},
                    }}, ensure_ascii=False),
                )
                return
            route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps(_action_success_payload("REFRESH_RSS", "已刷新关联 RSS", 3), ensure_ascii=False),
            )

        page.route("**/api/v1/autobangumi/capabilities", _modify_probe)
        page.route("**/api/v1/tracking/items/tracking-a/refresh", refresh)
        page.route("**/api/v1/tracking/items/tracking-a", detail)
        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        page.wait_for_selector("#tracking-overview")
        page.locator("#tracking-connect").click()
        page.locator("#tracking-ab-base-url").fill("https://private.invalid")
        page.locator("#tracking-ab-username").fill("user")
        page.locator("#tracking-ab-password").fill("secret-password")
        page.locator("#tracking-ab-probe").click()
        page.wait_for_selector("#tracking-refresh-rss-submit")

        page.locator("#tracking-refresh-rss-submit").click()
        page.locator(".confirm-dialog-actions button").filter(has_text="确认刷新关联 RSS").click()
        page.wait_for_selector("#tracking-management-result")

        result = page.locator("#tracking-management-result")
        expect(result).to_contain_text("关联 RSS 刷新结果未知")
        expect(result).to_contain_text("只读回查")
        expect(result).not_to_contain_text("已完成")
        expect(page.locator("#tracking-management-manual-notice")).to_contain_text("独立核对")
        expect(page.locator("body")).not_to_contain_text("RECOVERY_REQUIRED")
        # Nothing was resent automatically; the page only re-read both views.
        assert len(refreshes) == 1, refreshes
        assert state["detail_reads"] >= 2, state

        # The user confirms again: the locked intent is replayed verbatim.
        page.locator("#tracking-refresh-rss-submit").click()
        page.locator(".confirm-dialog-actions button").filter(has_text="确认刷新关联 RSS").click()
        page.wait_for_selector("#tracking-management-result:has-text('关联 RSS 刷新已完成')")
        assert len(refreshes) == 2, refreshes
        assert refreshes[1]["idempotency_key"] == refreshes[0]["idempotency_key"], refreshes
        assert refreshes[1]["expected_revision"] == refreshes[0]["expected_revision"], refreshes

    def test_capability_degradation_hides_only_the_unproven_action(
        self, page: Page, live_server_url: str
    ) -> None:
        _require_dist()
        _mock_list(page)

        def probe(route: Any, request: Any) -> None:
            assert request.method == "POST"
            payload = _probe_capabilities()
            payload["rss_disable"] = "UNSUPPORTED"
            payload["rss_refresh"] = "UNKNOWN"
            route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps({"ok": True, "result": payload}, ensure_ascii=False),
            )

        def detail(route: Any, request: Any) -> None:
            route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps(_action_detail(1), ensure_ascii=False),
            )

        page.route("**/api/v1/autobangumi/capabilities", probe)
        page.route("**/api/v1/tracking/items/tracking-a", detail)
        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        page.wait_for_selector("#tracking-overview")
        page.locator("#tracking-connect").click()
        page.locator("#tracking-ab-base-url").fill("https://private.invalid")
        page.locator("#tracking-ab-username").fill("user")
        page.locator("#tracking-ab-password").fill("secret-password")
        page.locator("#tracking-ab-probe").click()
        page.wait_for_selector("#tracking-set-enabled-scope-SUBSCRIPTION")

        section = page.locator(".tracking-management-actions-section")
        # The RSS scope of the disable direction is dropped, and the unproven
        # refresh is not rendered at all — each with its own read-only reason.
        expect(page.locator("#tracking-set-enabled-scope-ASSOCIATED_RSS")).to_have_count(0)
        expect(page.locator("#tracking-refresh-rss-submit")).to_have_count(0)
        expect(section).to_contain_text("已降级为只读")
        # The remaining action still works: choosing the target enables it.
        expect(page.locator("#tracking-set-enabled-submit")).to_be_disabled()
        page.locator("#tracking-set-enabled-scope-SUBSCRIPTION").check()
        expect(page.locator("#tracking-set-enabled-submit")).to_be_enabled()
