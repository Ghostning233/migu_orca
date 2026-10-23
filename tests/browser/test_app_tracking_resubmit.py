from __future__ import annotations

"""Issue #184: the risk-confirmed single resubmission in real Chromium.

Real Chromium against the built SPA and the real Flask server; only the tracking
DTO boundary and the tracking endpoints are mocked, and the external Auto Bangumi
write is *always* a route mock.  The page must

* offer 重新提交 beside the read-only 核验 for a pending submission,
* run the read-only phase first and send no write-family request for it,
* state the proven duplication/resource risk before anything is written,
* send nothing at all when the user cancels,
* send the exact server-published binding once when the user confirms,
* never open the risk dialog when the server already refused the resubmit, and
* never offer the step while the original write may still be running.
"""

from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import set_storage_preferences
from tests.browser.saved_tracking_fixtures import _item, _status_groups_for, _summary

REPO_ROOT = Path(__file__).resolve().parents[2]
REF = "11111111-1111-4111-8111-111111111111"
RESUBMIT = "/tracking/items/tracking-a/resubmit"

pytestmark = pytest.mark.browser


def _open_disclosure(page: Page, disclosure_id: str) -> None:
    """Open one detail disclosure (issue #233: dangerous actions start folded)."""
    disclosure = page.locator(f"#{disclosure_id}")
    if disclosure.evaluate("el => el.open") is False:
        disclosure.locator("summary").first.click()
    assert disclosure.evaluate("el => el.open") is True


def _require_dist() -> None:
    if not (REPO_ROOT / "frontend" / "dist" / "index.html").is_file():
        pytest.skip("frontend/dist not built; run `npm run build` in frontend/")


def _pending_item(operation_state: str = "OUTCOME_UNKNOWN", revision: int = 4) -> dict[str, Any]:
    return {
        **_item("tracking-a", "葬送的芙莉莲", "PROCESSING"),
        "status": "VERIFYING_EXTERNAL",
        "status_label": "核验外部结果中",
        "status_group": "PROCESSING",
        "submission_mode": "CONTINUE_TRACKING",
        "revision": revision,
        # Issue #228: the read-only verification is a page flow, not a projected action.
        "available_actions": [],
        "current_operation": {
            "operation_id": "op-submit", "operation": "SUBMIT", "state": operation_state,
            "attempt": 1, "external_result_id": None, "error_type": None,
            "created_at": None, "updated_at": None, "completed_at": None,
        },
    }


def _detail(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **item,
        "origin": "single",
        "batch_id": None,
        "created_at": "2026-09-01T00:00:00Z",
        "last_synced_at": None,
        "safe_info": None,
        "revalidation_issues": [],
        "external_mapping": None,
        "audit_events": [],
        "warnings": [],
    }


def _offer(**overrides: Any) -> dict[str, Any]:
    return {
        "check_status": "UNRESOLVED", "outcome": "RECOVERY_REQUIRED",
        "requires_risk_confirmation": True, "blocked_reason": None,
        "verification_reason": "NOT_FOUND",
        "binding": {
            "expected_revision": 5,
            "previous_operation_id": "op-submit",
            "connection_ref": REF,
        },
        "previous_operation_id": None,
        **overrides,
    }


def _install(
    page: Page,
    item: dict[str, Any],
    *,
    offer: dict[str, Any] | None = None,
    write_outcome: str = "ACTIVE",
) -> dict[str, list[dict[str, Any]]]:
    """Mock settings/list/detail/check/resubmit; no write ever leaves the page."""
    item = dict(item)
    calls: dict[str, list[dict[str, Any]]] = {"check": [], "offer": [], "write": []}

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
                "items": [item], "summary": _summary(1, processing=1), "status_groups": _status_groups_for([item]), "warnings": [],
            }})
            return
        if request.method == "GET" and path.startswith("/tracking/items/"):
            route.fulfill(json={"ok": True, "result": _detail(item)})
            return
        if request.method == "POST" and path.endswith("/check"):
            calls["check"].append(request.post_data_json or {})
            route.fulfill(json={"ok": True, "result": {
                "tracking_id": "tracking-a", "action": "VERIFY_EXTERNAL",
                "outcome": "RECOVERY_REQUIRED", "checked_revision": item["revision"],
                "next_revision": item["revision"] + 1, "checked_at": "2026-10-11T00:00:00Z",
                "operation_id": "op-submit", "needs_manual": True,
                "verification_reason": "NOT_FOUND", "tracking": item,
            }})
            return
        if request.method == "POST" and path == RESUBMIT:
            body = request.post_data_json or {}
            if body.get("confirm") is True:
                calls["write"].append(body)
                item.update({
                    "status": "ACTIVE", "status_label": "追番中", "status_group": "ACTIVE",
                    "revision": item["revision"] + 1,
                    "current_operation": {**item["current_operation"], "operation_id": "op-resubmit",
                                          "state": "SUCCEEDED"},
                })
                route.fulfill(json={"ok": True, "result": {
                    "tracking_id": "tracking-a", "confirm": True, "check_status": "UNRESOLVED",
                    "outcome": write_outcome, "requires_risk_confirmation": False,
                    "blocked_reason": None, "verification_reason": None, "binding": None,
                    "checked_revision": 5, "next_revision": item["revision"],
                    "checked_at": "2026-10-11T00:01:00Z", "operation_id": "op-resubmit",
                    "previous_operation_id": "op-submit", "failure_category": None,
                    "diagnostics": {}, "issues": [], "tracking": item,
                }})
                return
            calls["offer"].append(body)
            if (offer or {}).get("check_status") == "CONFIRMED":
                # The read-only phase proved the object: the record converges
                # without any write-family request.
                item.update({
                    "status": "ACTIVE", "status_label": "追番中", "status_group": "ACTIVE",
                    "revision": item["revision"] + 1,
                })
            route.fulfill(json={"ok": True, "result": {
                "tracking_id": "tracking-a", "confirm": False,
                "checked_revision": item["revision"], "next_revision": item["revision"] + 1,
                "checked_at": "2026-10-11T00:00:00Z", "operation_id": "op-submit",
                "failure_category": None, "diagnostics": {}, "issues": [],
                "tracking": item, **(offer if offer is not None else _offer()),
            }})
            return
        route.continue_()

    page.route("**/api/v1/**", handler)
    return calls


def _open(page: Page, live_server_url: str, storage_dir: Path) -> None:
    _require_dist()
    set_storage_preferences(page, storage_dir)
    page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")


def _assert_read_only_offer_body(body: dict[str, Any]) -> None:
    """The read-only phase carries the revision and nothing else."""
    assert body.get("confirm") is False, body
    for forbidden in ("previous_operation_id", "connection_ref", "idempotency_key",
                      "configuration_revision", "ab_config", "token", "password"):
        assert forbidden not in body, body
    assert set(body) <= {"expected_revision", "confirm", "storage_dir"}, body


class TestRiskConfirmedResubmission:
    def test_risk_is_stated_before_anything_is_written_and_cancel_writes_nothing(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        calls = _install(page, _pending_item())
        _open(page, live_server_url, storage_dir)
        # The ordinary automatic read-only check already ran.
        page.wait_for_selector("#tracking-check-result", timeout=10_000)
        _open_disclosure(page, "tracking-more-actions")
        page.wait_for_selector("#tracking-resubmit", timeout=10_000)

        page.locator("#tracking-resubmit").click()
        page.wait_for_selector(".confirm-dialog", timeout=10_000)

        # Only the read-only phase ran: no binding, no key, no write.
        assert len(calls["offer"]) == 1, calls
        _assert_read_only_offer_body(calls["offer"][0])
        assert calls["write"] == []

        # The dialog states the proven duplication/resource risk, in fixed copy.
        dialog = page.locator(".confirm-dialog")
        expect(dialog).to_contain_text("重复订阅")
        expect(dialog).not_to_contain_text("NOT_FOUND")

        page.locator(".confirm-dialog .secondary-button").click()
        page.wait_for_selector("#tracking-resubmit-result", timeout=10_000)
        expect(page.locator("#tracking-resubmit-result")).to_contain_text("已取消重新提交")
        assert calls["write"] == [], "cancelling must send no write request"
        assert len(calls["offer"]) == 1

        # Nothing sensitive leaked into the page, URL or history.
        for forbidden in ("secret-password", "another-password", "token", "ab_config"):
            assert forbidden not in page.url
            assert forbidden not in page.content().lower()
        assert REF not in page.url

    def test_confirming_sends_the_exact_binding_once_and_reports_the_outcome(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        calls = _install(page, _pending_item())
        _open(page, live_server_url, storage_dir)
        _open_disclosure(page, "tracking-more-actions")
        page.wait_for_selector("#tracking-resubmit", timeout=10_000)

        page.locator("#tracking-resubmit").click()
        page.wait_for_selector(".confirm-dialog", timeout=10_000)
        page.locator(".confirm-dialog .primary-button").click()

        page.wait_for_selector("#tracking-submit-result", timeout=10_000)
        expect(page.locator("#tracking-submit-result")).to_contain_text("提交成功")

        assert len(calls["write"]) == 1, calls
        body = calls["write"][0]
        assert {
            key: body[key] for key in (
                "expected_revision", "confirm", "previous_operation_id", "connection_ref",
            )
        } == {
            "expected_revision": 5,
            "confirm": True,
            "previous_operation_id": "op-submit",
            "connection_ref": REF,
        }, body
        # No client-chosen operation key: the server derives it from this binding.
        assert set(body) <= {
            "expected_revision", "confirm", "previous_operation_id", "connection_ref", "storage_dir",
        }, body
        # One new operation, traceable to the pending one, and the list converged.
        expect(page.locator(".tracking-list-panel")).to_contain_text("追番中")
        for forbidden in ("secret-password", "token", "ab_config"):
            assert forbidden not in page.content().lower()

    def test_a_server_refusal_never_opens_the_risk_dialog(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        calls = _install(
            page,
            _pending_item(),
            offer=_offer(
                check_status="BLOCKED", requires_risk_confirmation=False,
                binding=None, blocked_reason="PLAN_NOT_SUBMITTABLE",
            ),
        )
        _open(page, live_server_url, storage_dir)
        _open_disclosure(page, "tracking-more-actions")
        page.wait_for_selector("#tracking-resubmit", timeout=10_000)

        page.locator("#tracking-resubmit").click()
        page.wait_for_selector("#tracking-resubmit-result", timeout=10_000)

        expect(page.locator("#tracking-resubmit-result")).to_contain_text("未通过提交前检查")
        expect(page.locator(".confirm-dialog")).to_have_count(0)
        assert calls["write"] == []
        assert len(calls["offer"]) == 1

    def test_no_resubmit_is_offered_while_the_original_write_may_still_be_running(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _install(page, _pending_item(operation_state="IN_PROGRESS"))
        _open(page, live_server_url, storage_dir)
        page.wait_for_selector("#tracking-check-result", timeout=10_000)

        expect(page.locator("#tracking-resubmit")).to_have_count(0)
        expect(page.locator("#tracking-resubmit-hint")).to_contain_text("可能仍在执行")
        expect(page.locator(".confirm-dialog")).to_have_count(0)


    def test_a_confirmed_read_only_offer_keeps_its_message_after_convergence(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        calls = _install(
            page,
            _pending_item(),
            offer=_offer(
                check_status="CONFIRMED", outcome="ACTIVE",
                requires_risk_confirmation=False, binding=None, verification_reason=None,
            ),
        )
        _open(page, live_server_url, storage_dir)
        _open_disclosure(page, "tracking-more-actions")
        page.wait_for_selector("#tracking-resubmit", timeout=10_000)

        page.locator("#tracking-resubmit").click()
        page.wait_for_selector("#tracking-resubmit-result", timeout=10_000)

        expect(page.locator("#tracking-resubmit-result")).to_contain_text("已确认订阅存在")
        expect(page.locator(".tracking-list-panel")).to_contain_text("追番中")
        expect(page.locator(".confirm-dialog")).to_have_count(0)
        assert calls["write"] == []
        assert len(calls["offer"]) == 1
