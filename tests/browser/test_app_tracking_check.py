from __future__ import annotations

"""Issue #183: a 结果待确认 persistent submission confirms itself read-only.

Real Chromium against the built SPA and the real Flask server; only the tracking
DTO boundary and the two tracking endpoints are mocked.  The page must

* keep the confirmation inside the submit area and never show the retired
  standalone recovery panel for a submit result,
* check automatically when the pending item is opened — with only the revision,
  never a connection, and never a write-family request,
* explain an unresolved check from the server's proven reason class.
"""

from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import set_storage_preferences
from tests.browser.saved_tracking_fixtures import _item, _status_groups_for, _summary

REPO_ROOT = Path(__file__).resolve().parents[2]
REF = "11111111-1111-4111-8111-111111111111"

pytestmark = pytest.mark.browser


def _require_dist() -> None:
    if not (REPO_ROOT / "frontend" / "dist" / "index.html").is_file():
        pytest.skip("frontend/dist not built; run `npm run build` in frontend/")


def _pending_item(revision: int = 4) -> dict[str, Any]:
    return {
        **_item("tracking-a", "葬送的芙莉莲", "PROCESSING"),
        "status": "VERIFYING_EXTERNAL",
        "status_label": "核验外部结果中",
        "status_group": "PROCESSING",
        "submission_mode": "CONTINUE_TRACKING",
        "revision": revision,
        "available_actions": [
            {
                "code": "RECOVER_AUTO", "label": "自动恢复", "style": "SECONDARY",
                "requires_confirmation": False, "target_scopes": [],
            },
            {
                "code": "MARK_SUCCEEDED", "label": "标记为成功", "style": "PRIMARY",
                "requires_confirmation": True, "target_scopes": [],
            },
        ],
    }


def _detail(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **item,
        "origin": "single",
        "batch_id": None,
        "created_at": "2026-09-01T00:00:00Z",
        "last_synced_at": None,
        "safe_info": None,
        "current_operation": {
            "operation_id": "op-submit", "operation": "SUBMIT", "state": "OUTCOME_UNKNOWN",
            "attempt": 1, "external_result_id": None, "error_type": None,
            "created_at": None, "updated_at": None, "completed_at": None,
        },
        "revalidation_issues": [],
        "external_mapping": None,
        "audit_events": [],
        "warnings": [],
    }


def _install(page: Page, item: dict[str, Any], check_result: dict[str, Any]) -> list[dict[str, Any]]:
    """Mock settings/list/detail/check; the item mutates on a confirmed check."""
    state: dict[str, Any] = {"item": dict(item)}
    posts: list[dict[str, Any]] = []

    def handler(route: Any, request: Any) -> None:
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
            route.fulfill(json={"ok": True, "result": {
                "configured": True, "credential_present": True, "connection_ref": REF,
                "configuration_revision": 3, "connection_status": "CONFIGURED",
            }})
            return
        if request.method == "GET" and path == "/tracking/items":
            route.fulfill(json={"ok": True, "result": {
                "items": [state["item"]], "summary": _summary(1, processing=1), "status_groups": _status_groups_for([state["item"]]), "warnings": [],
            }})
            return
        if request.method == "GET" and path.startswith("/tracking/items/"):
            route.fulfill(json={"ok": True, "result": _detail(state["item"])})
            return
        if request.method == "POST" and path.endswith("/check"):
            posts.append(request.post_data_json or {})
            result = dict(check_result)
            if result.get("outcome") in ("ACTIVE", "DISABLED"):
                state["item"] = {**state["item"], "status": "ACTIVE", "status_label": "追番中",
                                 "status_group": "ACTIVE", "revision": state["item"]["revision"] + 1}
            route.fulfill(json={"ok": True, "result": {
                "tracking_id": "tracking-a", "action": "VERIFY_EXTERNAL",
                "checked_revision": state["item"]["revision"],
                "next_revision": state["item"]["revision"],
                "checked_at": "2026-10-11T00:00:00Z", "operation_id": "op-submit",
                "needs_manual": True, "verification_reason": None,
                **result, "tracking": state["item"],
            }})
            return
        route.continue_()

    page.route("**/api/v1/**", handler)
    return posts


def _open(page: Page, live_server_url: str, storage_dir: Path) -> None:
    _require_dist()
    set_storage_preferences(page, storage_dir)
    page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")


def _assert_read_only_check_body(body: dict[str, Any]) -> None:
    """A check carries the revision (and the storage profile) and nothing else."""
    assert body.get("expected_revision") == 4, body
    for forbidden in ("connection_ref", "configuration_revision", "idempotency_key", "confirm",
                      "submission_mode", "ab_config", "token", "password"):
        assert forbidden not in body, body
    assert set(body) <= {"expected_revision", "storage_dir"}, body


def _pending_check_result(**overrides: Any) -> dict[str, Any]:
    return {
        "outcome": "RECOVERY_REQUIRED",
        "verification_reason": "NOT_FOUND",
        **overrides,
    }


class TestPendingSubmissionCheck:
    def test_pending_submit_confirms_in_place_and_never_opens_the_recovery_panel(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        posts = _install(page, _pending_item(), _pending_check_result())
        _open(page, live_server_url, storage_dir)
        page.wait_for_selector("#tracking-check", timeout=10_000)

        # The automatic check ran with only the revision — no connection, no write.
        page.wait_for_selector("#tracking-check-result", timeout=10_000)
        expect(page.locator("#tracking-check-result")).to_contain_text("暂时没有在 Auto Bangumi 中找到该订阅")
        assert len(posts) == 1, posts
        _assert_read_only_check_body(posts[0])

        # Issue #181: no standalone recovery panel and no manual verdicts here.
        expect(page.locator("#tracking-recovery-heading")).to_have_count(0)
        expect(page.locator("#tracking-recover-auto")).to_have_count(0)
        expect(page.locator("#tracking-recover-succeeded")).to_have_count(0)
        expect(page.locator("body")).not_to_contain_text("结果待确认恢复")

        # Nothing sensitive leaks, and no history/state is written for the check.
        for forbidden in (REF, "auto-bangumi", "token"):
            assert forbidden not in page.url
            assert forbidden not in page.content().lower()
        assert page.evaluate("() => JSON.stringify(window.localStorage)") not in ("", "{}")

    def test_confirmed_check_converges_the_record_to_追番中(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        posts = _install(page, _pending_item(), {"outcome": "ACTIVE", "verification_reason": None})
        _open(page, live_server_url, storage_dir)
        page.wait_for_selector("#tracking-check-result", timeout=10_000)

        expect(page.locator("#tracking-check-result")).to_contain_text("已确认订阅存在")
        expect(page.locator(".tracking-list-panel")).to_contain_text("追番中")
        assert len(posts) == 1
        _assert_read_only_check_body(posts[0])

    def test_manual_recheck_sends_exactly_one_more_read_only_request(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        posts = _install(page, _pending_item(), _pending_check_result(verification_reason="CONNECTION_CHANGED"))
        _open(page, live_server_url, storage_dir)
        page.wait_for_selector("#tracking-check-result", timeout=10_000)
        expect(page.locator("#tracking-check-result")).to_contain_text("保存的连接已被更换")
        assert len(posts) == 1

        page.locator("#tracking-check").click()
        expect(page.locator("#tracking-check-result")).to_contain_text("保存的连接已被更换")
        page.wait_for_timeout(200)
        assert len(posts) == 2, posts
        for post in posts:
            _assert_read_only_check_body(post)


def _submittable_item(tracking_id: str, title: str, revision: int = 1) -> dict[str, Any]:
    return {
        **_item(tracking_id, title, "PENDING"),
        "request_id": f"request-{tracking_id}",
        "revision": revision,
        "available_actions": [
            {
                "code": "SUBMIT", "label": "提交到 Auto Bangumi", "style": "PRIMARY",
                "requires_confirmation": True, "target_scopes": [],
            },
        ],
    }


def _install_journey(
    page: Page,
    items: list[dict[str, Any]],
    *,
    check_results: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Mock settings/list/detail/submit/check for a multi-record journey."""
    state: dict[str, Any] = {"items": {item["tracking_id"]: dict(item) for item in items}}
    calls: dict[str, list[dict[str, Any]]] = {"submit": [], "check": []}
    pending_checks = list(check_results)

    def handler(route: Any, request: Any) -> None:
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
            route.fulfill(json={"ok": True, "result": {
                "configured": True, "credential_present": True, "connection_ref": REF,
                "configuration_revision": 3, "connection_status": "CONFIGURED",
            }})
            return
        if request.method == "GET" and path == "/tracking/items":
            rows = list(state["items"].values())
            route.fulfill(json={"ok": True, "result": {
                "items": rows, "summary": _summary(len(rows), pending=len(rows)), "status_groups": _status_groups_for(rows), "warnings": [],
            }})
            return
        if request.method == "GET" and path.startswith("/tracking/items/"):
            tracking_id = path.rsplit("/", 1)[-1]
            route.fulfill(json={"ok": True, "result": _detail(state["items"][tracking_id])})
            return
        if request.method == "POST" and path.endswith("/submit"):
            body = request.post_data_json or {}
            calls["submit"].append(body)
            tracking_id = path.split("/tracking/items/", 1)[1].split("/", 1)[0]
            item = state["items"][tracking_id]
            state["items"][tracking_id] = {
                **item, "status": "VERIFYING_EXTERNAL", "status_label": "核验外部结果中",
                "status_group": "PROCESSING", "submission_mode": "CONTINUE_TRACKING",
                "revision": item["revision"] + 1,
            }
            route.fulfill(json={"ok": True, "result": {
                "tracking_id": tracking_id, "outcome": "VERIFYING_EXTERNAL",
                "checked_revision": item["revision"], "next_revision": state["items"][tracking_id]["revision"],
                "checked_at": "2026-10-11T00:00:00Z", "operation_id": "op-submit",
                "failure_category": "OUTCOME_UNKNOWN", "verification_reason": "NOT_FOUND",
                "diagnostics": {}, "issues": [], "tracking": state["items"][tracking_id],
            }})
            return
        if request.method == "POST" and path.endswith("/check"):
            body = request.post_data_json or {}
            calls["check"].append(body)
            tracking_id = path.split("/tracking/items/", 1)[1].split("/", 1)[0]
            item = state["items"][tracking_id]
            result = pending_checks.pop(0) if pending_checks else {
                "outcome": "RECOVERY_REQUIRED", "verification_reason": "NOT_FOUND",
            }
            if result.get("outcome") in ("ACTIVE", "DISABLED"):
                state["items"][tracking_id] = {
                    **item, "status": "ACTIVE", "status_label": "追番中",
                    "status_group": "ACTIVE", "revision": item["revision"] + 1,
                }
            route.fulfill(json={"ok": True, "result": {
                "tracking_id": tracking_id, "action": "VERIFY_EXTERNAL",
                "checked_revision": item["revision"],
                "next_revision": state["items"][tracking_id]["revision"],
                "checked_at": "2026-10-11T00:00:00Z", "operation_id": "op-submit",
                "needs_manual": result.get("outcome") != "ACTIVE",
                **result, "tracking": state["items"][tracking_id],
            }})
            return
        route.continue_()

    page.route("**/api/v1/**", handler)
    return calls


class TestPendingSubmissionJourney:
    def test_reopening_the_record_checks_again(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        calls = _install_journey(
            page, [_pending_item()],
            check_results=[
                {"outcome": "RECOVERY_REQUIRED", "verification_reason": "NOT_FOUND"},
                {"outcome": "ACTIVE", "verification_reason": None},
            ],
        )
        _open(page, live_server_url, storage_dir)
        page.wait_for_selector("#tracking-check-result", timeout=10_000)
        expect(page.locator("#tracking-check-result")).to_contain_text("暂时没有在 Auto Bangumi 中找到该订阅")
        assert len(calls["check"]) == 1

        # Refreshing the pending record owes exactly one more bounded check.
        page.reload()
        page.wait_for_selector("#tracking-check-result", timeout=10_000)
        expect(page.locator("#tracking-check-result")).to_contain_text("已确认订阅存在")
        assert len(calls["check"]) == 2, calls["check"]
        for body in calls["check"]:
            _assert_read_only_check_body(body)

    def test_a_transient_failure_recovers_on_the_next_manual_check(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        calls = _install_journey(
            page, [_pending_item()],
            check_results=[
                {"outcome": "RECOVERY_REQUIRED", "verification_reason": "CONNECTION"},
                {"outcome": "ACTIVE", "verification_reason": None},
            ],
        )
        _open(page, live_server_url, storage_dir)
        page.wait_for_selector("#tracking-check-result", timeout=10_000)
        expect(page.locator("#tracking-check-result")).to_contain_text("保存的 Auto Bangumi 连接当前无法访问")

        page.locator("#tracking-check").click()
        expect(page.locator("#tracking-check-result")).to_contain_text("已确认订阅存在")
        expect(page.locator(".tracking-list-panel")).to_contain_text("追番中")
        assert len(calls["check"]) == 2

    def test_a_confirmed_check_releases_the_pending_submit_intent(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        calls = _install_journey(
            page,
            [_submittable_item("tracking-a", "葬送的芙莉莲"), _submittable_item("tracking-b", "另一部番剧")],
            check_results=[{"outcome": "ACTIVE", "verification_reason": None}],
        )
        _open(page, live_server_url, storage_dir)
        page.wait_for_selector("#tracking-submit", timeout=10_000)
        page.locator("#tracking-submit").click()
        page.wait_for_selector("#tracking-mode-continue", timeout=10_000)
        page.locator("#tracking-mode-continue").click()

        # The submit answers 结果待确认 and the page checks it automatically.
        page.wait_for_selector("#tracking-check-result", timeout=10_000)
        expect(page.locator("#tracking-check-result")).to_contain_text("已确认订阅存在")
        assert len(calls["submit"]) == 1
        assert len(calls["check"]) == 1

        # Issue #183 review: the settled intent no longer blocks another record.
        page.locator('[data-tracking-id="tracking-b"]').click()
        page.wait_for_selector("#tracking-submit", timeout=10_000)
        expect(page.locator("#tracking-submit")).to_be_enabled()
        expect(page.locator("body")).not_to_contain_text("存在尚未完成的外部写意图")
