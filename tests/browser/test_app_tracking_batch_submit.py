from __future__ import annotations

"""Issue #87: explicit batch submit in real Chromium.

A batch is a user-visible selection of independent reliable submissions. This
journey proves the page rules over a mocked tracking/batch boundary:

* bulk controls exist only in an explicit batch mode,
* checking a box never changes which detail is shown, and clicking a row never
  changes the selection,
* "全选当前结果" selects only submittable rows and states what it skipped,
* one confirmation sends exactly one entry per selected row, each with its own
  revision and opaque key,
* a partial success converges the successful rows, keeps the failed ones
  selected and never resends on its own.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import set_storage_preferences
from tests.browser.saved_tracking_fixtures import _item, _summary

REPO_ROOT = Path(__file__).resolve().parents[2]
REF = "11111111-1111-4111-8111-111111111111"

pytestmark = pytest.mark.browser


def _dist_built() -> bool:
    return (REPO_ROOT / "frontend" / "dist" / "index.html").is_file()


def _require_dist() -> None:
    if not _dist_built():
        pytest.skip("frontend/dist not built; run `npm run build` in frontend/")


def _submit_action() -> dict[str, Any]:
    return {
        "code": "SUBMIT",
        "label": "提交到 Auto Bangumi",
        "style": "PRIMARY",
        "requires_confirmation": True,
        "target_scopes": [],
    }


def _pending(tracking_id: str, title: str) -> dict[str, Any]:
    return {
        **_item(tracking_id, title, "PENDING"),
        "status": "PENDING_SUBMIT",
        "status_label": "待提交",
        "status_group": "PENDING",
        "available_actions": [_submit_action()],
    }


def _processing(tracking_id: str, title: str) -> dict[str, Any]:
    return {
        **_item(tracking_id, title, "PENDING"),
        "status": "SUBMITTING",
        "status_label": "提交中",
        "status_group": "PROCESSING",
        "available_actions": [_submit_action()],
    }


def _detail(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **item,
        "origin": "single",
        "batch_id": None,
        "created_at": "2026-09-01T00:00:00Z",
        "last_synced_at": None,
        "safe_info": None,
        "current_operation": None,
        "revalidation_issues": [],
        "external_mapping": None,
        "audit_events": [],
        "warnings": [],
    }


def _install(page: Page, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mock settings/list/detail plus the batch endpoint; return posted bodies."""
    bodies: list[dict[str, Any]] = []
    state = {"items": [dict(item) for item in items]}

    def handler(route: Any, request: Any) -> None:
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "configured": True,
                        "credential_present": True,
                        "connection_ref": REF,
                        "configuration_revision": 3,
                        "connection_status": "CONFIGURED",
                    },
                }
            )
            return
        if request.method == "GET" and path == "/tracking/items":
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "items": state["items"],
                        "summary": _summary(len(state["items"]), pending=2, processing=1),
                        "warnings": [],
                    },
                }
            )
            return
        if request.method == "GET" and path.startswith("/tracking/items/"):
            tracking_id = path.rsplit("/", 1)[-1]
            match = next(
                (item for item in state["items"] if item["tracking_id"] == tracking_id),
                state["items"][0],
            )
            route.fulfill(json={"ok": True, "result": _detail(match)})
            return
        if request.method == "POST" and path == "/tracking/batch-submit":
            body = request.post_data_json or {}
            bodies.append(body)
            results = []
            for index, entry in enumerate(body.get("items", [])):
                tracking_id = entry["tracking_id"]
                if index == 0:
                    results.append(
                        {
                            "tracking_id": tracking_id,
                            "ok": True,
                            "error_type": None,
                            "result": {
                                "tracking_id": tracking_id,
                                "outcome": "ACTIVE",
                                "checked_revision": entry["expected_revision"],
                                "next_revision": entry["expected_revision"] + 1,
                                "checked_at": "2026-09-14T00:00:00Z",
                                "operation_id": f"op-{tracking_id}",
                                "failure_category": None,
                                "issues": [],
                                "tracking": {
                                    **next(
                                        item for item in state["items"] if item["tracking_id"] == tracking_id
                                    ),
                                    "status": "ACTIVE",
                                    "status_label": "追番中",
                                    "status_group": "ACTIVE",
                                    "available_actions": [],
                                },
                            },
                        }
                    )
                    state["items"] = [
                        {**item, "status": "ACTIVE", "status_label": "追番中", "status_group": "ACTIVE", "available_actions": []}
                        if item["tracking_id"] == tracking_id
                        else item
                        for item in state["items"]
                    ]
                    continue
                results.append(
                    {
                        "tracking_id": tracking_id,
                        "ok": False,
                        "error_type": None,
                        "result": {
                            "tracking_id": tracking_id,
                            "outcome": "SUBMIT_FAILED",
                            "checked_revision": entry["expected_revision"],
                            "next_revision": entry["expected_revision"] + 1,
                            "checked_at": "2026-09-14T00:00:00Z",
                            "operation_id": f"op-{tracking_id}",
                            "failure_category": "AUTHENTICATION",
                            "issues": [],
                            "tracking": next(
                                item for item in state["items"] if item["tracking_id"] == tracking_id
                            ),
                        },
                    }
                )
            succeeded = sum(1 for entry in results if entry["ok"])
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "items": results,
                        "summary": {
                            "total": len(results),
                            "succeeded": succeeded,
                            "failed": len(results) - succeeded,
                            "unknown": 0,
                            "blocked": 0,
                        },
                    },
                }
            )
            return
        route.continue_()

    page.route("**/api/v1/**", handler)
    return bodies


def _open(page: Page, live_server_url: str, storage_dir: Path, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    _require_dist()
    set_storage_preferences(page, storage_dir)
    bodies = _install(page, items)
    page.goto(f"{live_server_url}/app/tracking")
    page.wait_for_selector("#tracking-overview")
    return bodies


class TestBatchSubmit:
    def test_batch_mode_selection_is_separate_and_skips_unsubmittable_rows(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _open(
            page,
            live_server_url,
            storage_dir,
            [
                _pending("tracking-a", "番 A"),
                _pending("tracking-b", "番 B"),
                _processing("tracking-c", "番 C"),
            ],
        )

        # Ordinary browsing has no bulk controls.
        assert page.locator(".tracking-list-checkbox").count() == 0

        page.locator("#tracking-batch-mode").click()
        checkboxes = page.locator(".tracking-list-checkbox")
        expect(checkboxes).to_have_count(3)
        # A transient row cannot be selected.
        expect(checkboxes.nth(2)).to_be_disabled()

        # Checking a box changes the batch selection only.
        checkboxes.nth(0).check()
        expect(page.locator("#tracking-batch-count")).to_contain_text("已选 1 条")
        assert page.locator(".tracking-list-item.is-selected").count() == 0

        # Clicking a row body switches the detail and leaves the selection alone.
        page.locator(".tracking-list-item").nth(1).click()
        page.wait_for_selector(".tracking-inspector-content")
        expect(page.locator(".tracking-list-item.is-selected")).to_have_attribute(
            "data-tracking-id", "tracking-b"
        )
        expect(page.locator("#tracking-batch-count")).to_contain_text("已选 1 条")

        # Select-all covers only the submittable rows and states the rest.
        page.locator("#tracking-batch-select-all").click()
        expect(page.locator("#tracking-batch-count")).to_contain_text("已选 2 条")
        expect(page.locator("#tracking-batch-skipped")).to_contain_text("已跳过 1 条")
        expect(page.locator("#tracking-batch-skipped")).to_contain_text("正在处理中")

    def test_partial_success_converges_successes_and_keeps_failures_selected(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        bodies = _open(
            page,
            live_server_url,
            storage_dir,
            [_pending("tracking-a", "番 A"), _pending("tracking-b", "番 B")],
        )

        page.locator("#tracking-batch-mode").click()
        page.locator("#tracking-batch-select-all").click()
        expect(page.locator("#tracking-batch-count")).to_contain_text("已选 2 条")

        page.locator("#tracking-batch-submit").click()
        # Issue #100: one mode choice for the whole batch, with the count stated.
        page.wait_for_selector("#tracking-mode-continue", timeout=10_000)
        expect(page.locator(".tracking-mode-dialog .confirm-dialog-title")).to_contain_text("选择提交方式")
        expect(page.locator(".tracking-mode-dialog")).to_contain_text("所选 2 条追番方案")
        page.locator("#tracking-mode-continue").click()

        page.wait_for_selector("#tracking-batch-result")
        expect(page.locator("#tracking-batch-result")).to_contain_text("成功 1 条")

        # Exactly one entry per selected row, each with its own revision and key.
        assert len(bodies) == 1
        entries = bodies[0]["items"]
        assert [entry["tracking_id"] for entry in entries] == ["tracking-a", "tracking-b"]
        assert all(entry["expected_revision"] >= 1 for entry in entries)
        assert len({entry["idempotency_key"] for entry in entries}) == 2
        assert bodies[0]["confirm"] is True
        assert bodies[0]["submission_mode"] == "CONTINUE_TRACKING"
        assert bodies[0]["connection_ref"] == REF
        # No credential or endpoint ever leaves the page.
        assert "secret-password" not in json.dumps(bodies, ensure_ascii=False)

        # The succeeded row leaves the selection; the failed one stays selected.
        expect(page.locator("#tracking-batch-count")).to_contain_text("已选 1 条")
        expect(page.locator("#tracking-batch-result")).to_contain_text("番 B")
        expect(page.locator(".tracking-list-item").nth(0)).to_contain_text("追番中")

        # Nothing is resent on its own.
        page.wait_for_timeout(300)
        assert len(bodies) == 1

class TestBatchLocalPreCheck:
    """Issue #100 AC 5/6/8: the local pre-check result never reaches Auto Bangumi."""

    def test_a_fully_unsubmittable_list_can_select_nothing_and_sends_nothing(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        bodies = _open(
            page,
            live_server_url,
            storage_dir,
            [_processing("tracking-a", "处理中 A"), _processing("tracking-b", "处理中 B")],
        )

        page.locator("#tracking-batch-mode").click()
        page.locator("#tracking-batch-select-all").click()

        # AC 8: 全选只依赖服务端广告的可提交动作 —— 处理中的条目根本选不上。
        expect(page.locator("#tracking-batch-count")).to_contain_text("已选 0 条")
        expect(page.locator("#tracking-batch-submit")).to_be_disabled()
        assert bodies == [], "nothing submittable must never reach Auto Bangumi"

    def test_only_the_submittable_plans_are_sent(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        bodies = _open(
            page,
            live_server_url,
            storage_dir,
            [_pending("tracking-a", "可提交 A"), _processing("tracking-b", "处理中 B")],
        )

        page.locator("#tracking-batch-mode").click()
        page.locator("#tracking-batch-select-all").click()
        expect(page.locator("#tracking-batch-count")).to_contain_text("已选 1 条")
        page.locator("#tracking-batch-submit").click()
        page.wait_for_selector("#tracking-mode-continue", timeout=10_000)
        page.locator("#tracking-mode-continue").click()

        page.wait_for_selector("#tracking-batch-result", timeout=10_000)
        assert len(bodies) == 1
        # The skipped plan is never part of the batch request.
        assert [entry["tracking_id"] for entry in bodies[0]["items"]] == ["tracking-a"]
