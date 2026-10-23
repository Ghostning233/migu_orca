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
import re
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import set_storage_preferences
from tests.browser.saved_tracking_fixtures import _item, _status_groups_for, _summary

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


def _install(
    page: Page,
    items: list[dict[str, Any]],
    *,
    refuse_single_submit: bool = False,
) -> list[dict[str, Any]]:
    """Mock settings/list/detail plus the batch endpoint; return posted bodies.

    ``refuse_single_submit`` answers a single submit with the batch-exclusion
    409 (issue #248) so the page's "批量操作进行中" copy can be asserted.
    """
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
                        "status_groups": _status_groups_for(state["items"]),
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
        if (
            refuse_single_submit
            and request.method == "POST"
            and path.startswith("/tracking/items/")
            and path.endswith("/submit")
        ):
            route.fulfill(
                status=409,
                json={
                    "ok": False,
                    "error_type": "connection_in_use",
                    "error_message": "批量操作进行中：请等待批次结束后再操作该记录",
                    "error_data": {"failed_step": "tracking_batch_exclusion"},
                },
            )
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

        # No checkbox or selection column exists, in browse or in multi-select.
        assert page.locator(".tracking-list-checkbox").count() == 0
        assert page.locator('input[type="checkbox"]').count() == 0

        page.locator("#tracking-batch-mode").click()
        assert page.locator(".tracking-list-checkbox").count() == 0
        rows = page.locator(".tracking-list-row")
        # A transient row cannot be selected: its row body is disabled.
        expect(rows.nth(2).locator(".tracking-list-item")).to_be_disabled()

        # The row body toggles the batch selection only (background, not detail).
        rows.nth(0).locator(".tracking-list-item").click()
        expect(page.locator("#tracking-batch-count")).to_contain_text("已选 1 部")
        assert "is-batch-selected" in (rows.nth(0).get_attribute("class") or "")
        assert page.locator(".tracking-list-row.is-selected").count() == 0

        # The arrow opens the detail and leaves the selection alone.
        rows.nth(1).locator(".tracking-list-arrow").click()
        page.wait_for_selector(".tracking-inspector-content")
        expect(page.locator(".tracking-list-row.is-selected")).to_have_attribute(
            "data-tracking-id", "tracking-b"
        )
        expect(page.locator("#tracking-batch-count")).to_contain_text("已选 1 部")

        # Select-all covers only the submittable rows and states the rest.
        page.locator("#tracking-batch-select-all").click()
        expect(page.locator("#tracking-batch-count")).to_contain_text("已选 2 部")
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
        expect(page.locator("#tracking-batch-count")).to_contain_text("已选 2 部")

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

        # B5: the batch result lives inside the list module (bounded), not as a
        # workspace sibling that could grow the page.
        assert page.evaluate(
            "() => !!document.querySelector('.tracking-list-panel #tracking-batch-result')"
        )

        # The succeeded row leaves the selection; the failed one stays selected.
        expect(page.locator("#tracking-batch-count")).to_contain_text("已选 1 部")
        expect(page.locator("#tracking-batch-result")).to_contain_text("番 B")
        expect(page.locator(".tracking-list-row").nth(0)).to_contain_text("追番中")

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
        expect(page.locator("#tracking-batch-count")).to_contain_text("已选 0 部")
        expect(page.locator("#tracking-batch-submit")).to_be_disabled()
        assert bodies == [], "nothing submittable must never reach Auto Bangumi"

    def test_only_the_submittable_plans_are_sent(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """#223: deletable ACTIVE rows are selectable, but submit stays narrow."""
        bodies = _open(
            page,
            live_server_url,
            storage_dir,
            [
                _pending("tracking-a", "可提交 A"),
                _processing("tracking-b", "处理中 B"),
                _deletable("tracking-c", "追番中 C", "ACTIVE"),
            ],
        )

        page.locator("#tracking-batch-mode").click()
        page.locator("#tracking-batch-select-all").click()
        # A + the ACTIVE row (deletable) are selected; the in-flight row is not.
        expect(page.locator("#tracking-batch-count")).to_contain_text("已选 2 部")
        expect(page.locator("#tracking-batch-skipped")).to_contain_text("正在处理中")
        page.locator("#tracking-batch-submit").click()
        page.wait_for_selector("#tracking-mode-continue", timeout=10_000)
        page.locator("#tracking-mode-continue").click()

        # Submit eligibility did not widen: the ACTIVE row is reported as a
        # pre-check skip and never reaches the batch request.
        page.wait_for_selector(".confirm-dialog", timeout=10_000)
        expect(page.locator(".confirm-dialog")).to_contain_text("追番中 C")
        expect(page.locator(".confirm-dialog")).to_contain_text("当前状态不可提交")
        page.locator(".confirm-dialog .primary-button").click()

        page.wait_for_selector("#tracking-batch-result", timeout=10_000)
        assert len(bodies) == 1
        assert [entry["tracking_id"] for entry in bodies[0]["items"]] == ["tracking-a"]


# -- Issue #223: explicit batch delete ---------------------------------------

def _deletable(tracking_id: str, title: str, status: str = "PENDING") -> dict[str, Any]:
    """A row the local pre-check can delete (no unresolved operation)."""
    item = _item(tracking_id, title, "PENDING")
    if status == "ACTIVE":
        return {
            **item,
            "status": "ACTIVE",
            "status_label": "追番中",
            "status_group": "ACTIVE",
            "available_actions": [],
        }
    return {
        **item,
        "status": "PENDING_SUBMIT",
        "status_label": "待提交",
        "status_group": "PENDING",
        "available_actions": [_submit_action()],
    }


def _install_batch_delete(
    page: Page,
    items: list[dict[str, Any]],
    outcomes: list[str],
) -> list[dict[str, Any]]:
    """Mock the list/detail, both batch-delete endpoints and the status read.

    ``outcomes`` drives the per-entry server result; DELETED rows are removed
    from the mocked list so the post-batch refresh converges like the server.
    """
    bodies: list[dict[str, Any]] = []
    state = {"items": [dict(item) for item in items]}

    def handler(route: Any, request: Any) -> None:
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "POST" and path == "/tracking/sync":
            # #229: the page syncs once on entry; answer it locally.
            route.fulfill(json={"ok": True, "result": {
                "sync_status": "PARTIAL", "checked_at": "2026-10-21T00:00:00Z",
                "capabilities": {}, "summary": {}, "warnings": [],
            }})
            return
        if request.method == "GET" and path == "/settings/autobangumi":
            route.fulfill(json={"ok": True, "result": {
                "configured": True, "credential_present": True, "connection_ref": REF,
                "configuration_revision": 3, "connection_status": "CONFIGURED",
            }})
            return
        if request.method == "GET" and path == "/tracking/items":
            route.fulfill(json={"ok": True, "result": {
                "items": state["items"],
                "summary": _summary(len(state["items"])),
                "status_groups": _status_groups_for(state["items"]),
                "warnings": [],
            }})
            return
        if request.method == "GET" and path.startswith("/tracking/items/"):
            tracking_id = path.rsplit("/", 1)[-1]
            match = next(
                (item for item in state["items"] if item["tracking_id"] == tracking_id),
                state["items"][0],
            )
            route.fulfill(json={"ok": True, "result": _detail(match)})
            return
        if request.method == "POST" and path in (
            "/tracking/batch-delete-plan", "/tracking/batch-delete-plan-external"
        ):
            body = request.post_data_json or {}
            bodies.append({"path": path, **body})
            results = []
            deleted: list[str] = []
            for index, entry in enumerate(body.get("items", [])):
                tracking_id = entry["tracking_id"]
                outcome = outcomes[index] if index < len(outcomes) else "DELETED"
                if outcome == "DELETED":
                    deleted.append(tracking_id)
                results.append({
                    "tracking_id": tracking_id,
                    "outcome": outcome,
                    "external_deleted": outcome == "DELETED" and path.endswith("-external"),
                    "skip_reason": "UNRESOLVED" if outcome == "SKIPPED" else None,
                    "error_type": None,
                })
            state["items"] = [item for item in state["items"] if item["tracking_id"] not in deleted]
            route.fulfill(json={"ok": True, "result": {
                "batch_key": body.get("idempotency_key", ""),
                "kind": "LOCAL_AND_EXTERNAL" if path.endswith("-external") else "LOCAL_ONLY",
                "state": "COMPLETED",
                "items": results,
                "summary": {
                    "total": len(results),
                    "deleted": sum(1 for item in results if item["outcome"] == "DELETED"),
                    "external_deleted": sum(1 for item in results if item["external_deleted"]),
                    "skipped": sum(1 for item in results if item["outcome"] == "SKIPPED"),
                    "failed": sum(1 for item in results if item["outcome"] == "EXTERNAL_FAILED"),
                    "unknown": sum(1 for item in results if item["outcome"] == "EXTERNAL_UNKNOWN"),
                },
            }})
            return
        route.continue_()

    page.route("**/api/v1/**", handler)
    return bodies


class TestBatchDeleteJourney:
    """#223 AC1-AC8: one explicit batch delete in real Chromium."""

    def _open(self, page: Page, live_server_url: str, storage_dir: Path, items, outcomes):
        bodies = _install_batch_delete(page, items, outcomes)
        set_storage_preferences(page, storage_dir)
        page.goto(f"{live_server_url}/app/tracking")
        page.wait_for_selector("#tracking-batch-mode")
        return bodies

    def test_toolbar_offers_exactly_the_four_batch_actions(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _require_dist()
        self._open(page, live_server_url, storage_dir, [_deletable("tracking-a", "番 A")], ["DELETED"])

        page.locator("#tracking-batch-mode").click()

        assert page.locator(".tracking-batch-toolbar button").evaluate_all(
            "(nodes) => nodes.map((node) => node.id)"
        ) == [
            "tracking-batch-select-all",
            "tracking-batch-clear",
            "tracking-batch-delete",
            "tracking-batch-submit",
        ]
        expect(page.locator("#tracking-batch-delete")).to_have_text("删除选中")
        expect(page.locator("#tracking-batch-delete")).to_be_disabled()

    def test_local_delete_defaults_to_local_only_and_reports_each_entry(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """AC1/AC2/AC3: default scope is local, results are per entry."""
        _require_dist()
        bodies = self._open(
            page,
            live_server_url,
            storage_dir,
            [_deletable("tracking-a", "番 A"), _deletable("tracking-b", "番 B")],
            ["DELETED", "DELETED"],
        )

        page.locator("#tracking-batch-mode").click()
        page.locator("#tracking-batch-select-all").click()
        page.locator("#tracking-batch-delete").click()
        page.wait_for_selector("#tracking-batch-delete-confirm", timeout=10_000)

        dialog = page.locator(".tracking-batch-delete-dialog")
        expect(dialog).to_contain_text("本次将删除 2 条追番方案的本地记录与方案快照")
        expect(dialog).to_contain_text("Auto Bangumi 中的订阅会继续运行，MiGuOrca 不再管理它们")
        expect(page.locator("#tracking-batch-delete-external")).not_to_be_checked()
        # The confirmation starts on 取消, so Enter alone never deletes.
        assert page.evaluate("() => document.activeElement && document.activeElement.id") == "tracking-batch-delete-cancel"

        page.locator("#tracking-batch-delete-confirm").click()
        page.wait_for_selector("#tracking-batch-delete-result", timeout=10_000)

        assert len(bodies) == 1
        body = bodies[0]
        assert body["path"] == "/tracking/batch-delete-plan"
        assert body["confirm"] is True
        assert "connection_ref" not in body
        assert [entry["tracking_id"] for entry in body["items"]] == ["tracking-a", "tracking-b"]
        assert all(entry["expected_revision"] >= 1 for entry in body["items"])

        expect(page.locator("#tracking-batch-delete-summary")).to_contain_text("已删除 2 条")
        entries = page.locator("#tracking-batch-delete-result .tracking-batch-entries li")
        expect(entries).to_have_count(2)
        # AC3: the deleted entry keeps its title after the refresh removed the row.
        expect(entries.first).to_contain_text("番 A：已删除本地记录")
        # AC6: no retry-all entry exists in the result panel.
        assert page.locator("#tracking-batch-delete-result button").count() == 0
        # Deleted rows leave the list on the post-batch refresh.
        expect(page.locator(".tracking-list-item")).to_have_count(0)

    def test_external_scope_is_opt_in_and_keeps_a_failed_entry(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """AC2/AC3: ticking the box adds the external leg; failures keep local data."""
        _require_dist()
        bodies = self._open(
            page,
            live_server_url,
            storage_dir,
            [_deletable("tracking-a", "番 A", "ACTIVE"), _deletable("tracking-b", "番 B", "ACTIVE")],
            ["DELETED", "EXTERNAL_FAILED"],
        )

        page.locator("#tracking-batch-mode").click()
        page.locator("#tracking-batch-select-all").click()
        page.locator("#tracking-batch-delete").click()
        page.wait_for_selector("#tracking-batch-delete-external", timeout=10_000)
        page.locator("#tracking-batch-delete-external").check()
        expect(page.locator(".tracking-batch-delete-dialog")).to_contain_text(
            "先删除这 2 条在 Auto Bangumi 中的受控外部订阅"
        )
        page.locator("#tracking-batch-delete-confirm").click()
        page.wait_for_selector("#tracking-batch-delete-result", timeout=10_000)

        assert len(bodies) == 1
        body = bodies[0]
        assert body["path"] == "/tracking/batch-delete-plan-external"
        assert body["connection_ref"] == REF
        assert body["configuration_revision"] == 3

        summary = page.locator("#tracking-batch-delete-summary")
        expect(summary).to_contain_text("已删除 1 条")
        expect(summary).to_contain_text("其中 1 条同时删除了受控外部订阅")
        expect(summary).to_contain_text("外部删除失败 1 条")
        entries = page.locator("#tracking-batch-delete-result .tracking-batch-entries li")
        expect(entries.nth(1)).to_contain_text("外部订阅删除失败：本地方案与记录已保留")
        # The failed entry stays selected for single handling (AC6: no retry-all).
        expect(page.locator('.tracking-list-row[data-tracking-id="tracking-b"]')).to_have_class(
            re.compile("is-batch-selected")
        )

    def test_unresolved_entry_is_skipped_and_explained(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """AC4/AC8: the server's execution-time skip is visible, nothing is deleted."""
        _require_dist()
        bodies = self._open(
            page,
            live_server_url,
            storage_dir,
            [_deletable("tracking-a", "番 A"), _deletable("tracking-b", "番 B")],
            ["DELETED", "SKIPPED"],
        )

        page.locator("#tracking-batch-mode").click()
        page.locator("#tracking-batch-select-all").click()
        page.locator("#tracking-batch-delete").click()
        page.wait_for_selector("#tracking-batch-delete-confirm", timeout=10_000)
        page.locator("#tracking-batch-delete-confirm").click()
        page.wait_for_selector("#tracking-batch-delete-result", timeout=10_000)

        assert len(bodies) == 1
        entries = page.locator("#tracking-batch-delete-result .tracking-batch-entries li")
        expect(entries.nth(1)).to_contain_text("本次跳过，需要逐条处理")
        expect(page.locator("#tracking-batch-delete-summary")).to_contain_text("跳过 1 条")
        # The skipped row is still there and still selected.
        expect(page.locator('.tracking-list-row[data-tracking-id="tracking-b"]')).to_have_class(
            re.compile("is-batch-selected")
        )


class TestSingleWriteDuringABatch:
    """Issue #248: a refused single write states the running batch explicitly."""

    def test_a_refused_single_submit_shows_the_batch_in_progress_copy(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _require_dist()
        set_storage_preferences(page, storage_dir)
        _install(page, [_pending("trk_a", "番 A")], refuse_single_submit=True)
        page.goto(f"{live_server_url}/app/tracking?tracking_id=trk_a")
        page.wait_for_selector("#tracking-submit")

        page.locator("#tracking-submit").click()
        page.wait_for_selector("#tracking-mode-continue")
        page.locator("#tracking-mode-continue").click()

        expect(page.locator("#tracking-batch-busy")).to_contain_text("批量操作进行中")
        expect(page.locator("#tracking-batch-busy")).to_contain_text("等批次结束后再试")
        # The generic failure copy must not be the only thing the user sees.
        expect(page.locator("#tracking-submit-result")).not_to_contain_text("批量操作进行中")
