from __future__ import annotations

"""Issue #85: the unified "我的追番" list–detail workbench.

Real Chromium over a mocked tracking DTO boundary. It proves the workbench host:

* states the product title/subtitle and the four fixed overview categories with
  the server's authoritative counts (never a recount of visible rows),
* lists cover/title/season/status/last-update, where selecting a row only
  switches the right-hand "追番详情",
* keeps 操作记录 / 技术诊断 collapsed until the user asks for them,
* stacks vertically (instead of squeezing two columns) at a narrow viewport and
  at the 200%-zoom equivalent, without horizontal overflow.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import set_storage_preferences
from tests.browser.saved_tracking_fixtures import _status_groups_for, _summary

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.browser


def _dist_built() -> bool:
    return (REPO_ROOT / "frontend" / "dist" / "index.html").is_file()


def _require_dist() -> None:
    if not _dist_built():
        pytest.skip("frontend/dist not built; run `npm run build` in frontend/")


def _item(
    tracking_id: str,
    title: str,
    *,
    season: int = 1,
    status: str = "ACTIVE",
    status_label: str = "追番中",
    status_group: str = "ACTIVE",
    poster_path: str | None = None,
    updated_at: str = "2026-09-14T00:00:00Z",
) -> dict[str, Any]:
    return {
        "tracking_id": tracking_id,
        "request_id": f"request-{tracking_id}",
        "title": title,
        "season": season,
        "subtitle_group": "喵萌奶茶屋",
        "poster_path": poster_path,
        "status": status,
        "status_label": status_label,
        "status_group": status_group,
        "available_actions": [],
        "valid_resource_count": 1,
        "updated_episode": None,
        "updated_episode_status": "NOT_IMPLEMENTED",
        "total_episodes": None,
        "revision": 1,
        "updated_at": updated_at,
    }


def _detail_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **item,
        "origin": "single",
        "batch_id": None,
        "created_at": "2026-09-01T00:00:00Z",
        "last_synced_at": None,
        "safe_info": None,
        "current_operation": {"operation_id": "op-1", "state": "UNKNOWN", "operation": "SUBMIT", "attempt": 1},
        "revalidation_issues": [],
        "external_mapping": {"match_reason": "标题", "enabled": True, "external_deleted": False},
        "audit_events": [{"action": "SUBMIT", "safe_message": "已提交", "created_at": "2026-09-13T00:00:00Z"}],
        "warnings": [],
    }


def _mock_workbench(page: Page, items: list[dict[str, Any]]) -> None:
    """Mock the list/detail DTOs; the summary claims more rows than are loaded."""

    def handler(route: Any, request: Any) -> None:
        if request.method != "GET" or "/api/v1/tracking/items" not in request.url:
            route.continue_()
            return
        for item in items:
            if f"/api/v1/tracking/items/{item['tracking_id']}" in request.url:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {"ok": True, "result": _detail_payload(item)}, ensure_ascii=False
                    ),
                )
                return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "ok": True,
                    "result": {
                        "items": items,
                        "summary": {
                            # Group counts sum to this total (追番中 is active +
                            # added_to_download), so the fixture is self-consistent.
                            "total": 9,
                            "pending": 3,
                            "processing": 1,
                            "active": 2,
                            "inactive": 1,
                            "needs_attention": 1,
                            "added_to_download": 1,
                            "unreadable": 1,
                        },
                        # Issue #224 A2/A7: four server-owned cards; 追番中 is
                        # 追番中 + 已加入下载 and 处理中 has no card.
                        "status_groups": [
                            {"group": "PENDING", "label": "待处理", "count": 3, "has_overview_card": True},
                            {"group": "PROCESSING", "label": "处理中", "count": 1, "has_overview_card": False},
                            {"group": "ACTIVE", "label": "追番中", "count": 3, "has_overview_card": True},
                            {"group": "ATTENTION", "label": "需处理", "count": 1, "has_overview_card": True},
                            {"group": "INACTIVE", "label": "已停用", "count": 1, "has_overview_card": True},
                        ],
                        "warnings": [],
                    },
                },
                ensure_ascii=False,
            ),
        )

    page.route("**/api/v1/tracking/items*", handler)
    page.route("**/api/v1/tracking/items/**", handler)


def _open_workbench(page: Page, live_server_url: str, storage_dir: Path, items: list[dict[str, Any]]) -> None:
    _require_dist()
    set_storage_preferences(page, storage_dir)
    _mock_workbench(page, items)
    page.goto(f"{live_server_url}/app/tracking")
    page.wait_for_selector("#tracking-overview")


class TestTrackingWorkbench:
    def test_overview_uses_server_counts_and_selection_switches_detail(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _open_workbench(
            page,
            live_server_url,
            storage_dir,
            [
                _item("tracking-frieren", "葬送的芙莉莲", season=2),
                _item(
                    "tracking-jjk",
                    "咒术回战",
                    season=3,
                    status="DISABLED",
                    status_label="已停用",
                    status_group="INACTIVE",
                    updated_at="2026-09-13T00:00:00Z",
                ),
            ],
        )

        header = page.locator(".tracking-header")
        assert "我的追番" in header.inner_text()
        assert "管理待提交任务和正在运行的追番" in header.inner_text()

        # Issue #224: four server-owned cards with the authoritative counts; the
        # summary claims 9 records although only two rows are loaded.
        cards = page.locator(".tracking-status-card")
        assert cards.count() == 4
        assert ["".join(text.split()) for text in cards.all_inner_texts()] == [
            "待处理3", "追番中3", "需处理1", "已停用1",
        ]
        # The count moved to the list bottom and states the whole-library total.
        assert "共 9 部" in page.locator(".tracking-list-count").inner_text()
        assert "正在追番" not in page.content()

        rows = page.locator(".tracking-list-item")
        assert rows.count() == 2
        assert "第 2 季" in rows.nth(0).inner_text()
        assert "2026" in rows.nth(0).inner_text()
        assert "已停用" in rows.nth(1).inner_text()

        # Selecting a row only switches the right-hand detail. Safe-detail
        # loading is asynchronous, so wait for the loaded text rather than the
        # container (which also renders the「正在读取安全详情…」state); a bare
        # container wait races the mocked detail response on slower CI runners.
        rows.nth(1).click()
        inspector = page.locator(".tracking-inspector")
        expect(inspector).to_contain_text("追番详情")
        expect(inspector).to_contain_text("咒术回战")
        # Selection stays on the tracking route and only records the safe id.
        assert "/app/tracking" in page.url
        assert "tracking_id=tracking-jjk" in page.url

        rows.nth(0).click()
        page.wait_for_function(
            "() => document.querySelector('.tracking-inspector')?.innerText.includes('葬送的芙莉莲')"
        )
        assert "咒术回战" not in page.locator(".tracking-inspector").inner_text()

    def test_activity_and_diagnostics_stay_collapsed_by_default(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _open_workbench(
            page, live_server_url, storage_dir, [_item("tracking-frieren", "葬送的芙莉莲")]
        )
        page.locator(".tracking-list-item").first.click()
        # Wait for the loaded safe detail before asserting the collapsed
        # sections exist; the container alone renders while the detail request
        # is still in flight.
        expect(page.locator(".tracking-inspector")).to_contain_text("葬送的芙莉莲")

        activity = page.locator("#tracking-activity-log")
        diagnostics = page.locator("#tracking-tech-diagnostics")
        assert activity.count() == 1 and diagnostics.count() == 1
        assert activity.evaluate("el => el.open") is False
        assert diagnostics.evaluate("el => el.open") is False

        # Everyday summary data is visible without expanding anything.
        assert "有效资源" in page.locator(".tracking-inspector-summary").inner_text()

        # Operator detail is reachable on demand.
        activity.locator("summary").click()
        assert activity.evaluate("el => el.open") is True
        assert "安全审计" in activity.inner_text()

        diagnostics.locator("summary").click()
        assert diagnostics.evaluate("el => el.open") is True
        assert "外部安全摘要" in diagnostics.inner_text()

    @pytest.mark.parametrize(
        ("width", "height"),
        [(1440, 900), (720, 450)],
    )
    def test_workspace_layout_stacks_instead_of_squeezing(
        self, page: Page, live_server_url: str, storage_dir: Path, width: int, height: int
    ) -> None:
        _require_dist()
        set_storage_preferences(page, storage_dir)
        _mock_workbench(page, [_item("tracking-frieren", "葬送的芙莉莲")])
        page.set_viewport_size({"width": width, "height": height})
        page.goto(f"{live_server_url}/app/tracking")
        page.wait_for_selector("#tracking-overview")
        page.locator(".tracking-list-item").first.click()
        page.wait_for_selector(".tracking-inspector-content")

        list_box = page.locator(".tracking-list-panel").bounding_box()
        detail_box = page.locator(".tracking-inspector").bounding_box()
        assert list_box is not None and detail_box is not None
        assert page.evaluate("() => document.body.scrollWidth") <= width + 1

        if width > 800:
            # Desktop keeps the ~60/40 list–detail split.
            assert detail_box["x"] >= list_box["x"] + list_box["width"] - 1
        else:
            # 200%-zoom equivalent: the columns stack vertically.
            assert detail_box["y"] >= list_box["y"] + list_box["height"] - 1
            assert abs(detail_box["x"] - list_box["x"]) <= 1

    def test_keyboard_focus_and_status_live_region(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _open_workbench(
            page, live_server_url, storage_dir, [_item("tracking-frieren", "葬送的芙莉莲")]
        )

        # The list count is announced, not colour-only.
        assert page.locator(".tracking-list-count").get_attribute("role") == "status"
        assert page.locator("#tracking-list-container").get_attribute("aria-label") == "追番记录列表"

        # A row is a real button and can be selected with the keyboard.
        row = page.locator(".tracking-list-item").first
        row.focus()
        page.keyboard.press("Enter")
        page.wait_for_selector(".tracking-inspector-content")
        assert row.get_attribute("aria-current") == "true"

def _plan_snapshot(folder: str) -> dict[str, Any]:
    return {
        "request": {
            "request_id": "request-plan",
            "status": "ACCEPTED",
            "input": {"raw_title": "芙莉莲"},
            "source_info": {
                "matched_bangumi": {"title": "葬送的芙莉莲", "season": 1, "aliases": [], "mikan_url": None, "match_score": 1},
                "rss_sources": [{
                    "subtitle_group": "喵萌奶茶屋", "rss_url": None, "source_type": "rss",
                    "valid_seed_names": ["第一集.mkv"], "excluded_seed_names": [],
                }],
            },
            "confirmable_config": {
                "selected_subtitle_group": "喵萌奶茶屋",
                "selected_rss_url": None,
                "filter_rule": {"must_contain": "", "must_not_contain": "", "use_regex": False, "case_sensitive": False},
                "effective_seed_names": ["第一集.mkv"],
                "expected_folder_name": folder,
                "warnings": [],
            },
            "ab_submit_result": None,
            "created_at": "2026-09-01T00:00:00Z",
            "updated_at": "2026-09-01T00:00:00Z",
        },
    }


class TestPendingPlanEditing:
    """Issue #90: a pending plan is edited in place with the shared core."""

    def test_pending_plan_edits_in_place_and_saves_only_a_patch(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _require_dist()
        set_storage_preferences(page, storage_dir)
        item = {
            **_item("tracking-a", "葬送的芙莉莲"),
            "request_id": "request-plan",
            "status": "PENDING_SUBMIT",
            "status_label": "待提交",
            "status_group": "PENDING",
            "available_actions": [],
        }
        state = {"folder": "芙莉莲"}
        modifies: list[dict[str, Any]] = []

        def handler(route: Any, request: Any) -> None:
            path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
            if request.method == "GET" and path == "/settings/autobangumi":
                route.fulfill(json={"ok": True, "result": {
                    "configured": True, "credential_present": True,
                    "connection_ref": "11111111-1111-4111-8111-111111111111",
                    "configuration_revision": 1, "connection_status": "CONFIGURED",
                }})
                return
            if request.method == "GET" and path == "/tracking/items":
                route.fulfill(json={"ok": True, "result": {"items": [item], "summary": _summary(1, pending=1), "status_groups": _status_groups_for([item]), "warnings": []}})
                return
            if request.method == "GET" and path == "/tracking/items/tracking-a":
                route.fulfill(json={"ok": True, "result": {**item, "origin": "single", "batch_id": None,
                    "created_at": "2026-09-01T00:00:00Z", "last_synced_at": None, "safe_info": None,
                    "current_operation": None, "revalidation_issues": [], "external_mapping": None,
                    "audit_events": [], "warnings": []}})
                return
            if request.method == "GET" and path == "/requests/request-plan":
                route.fulfill(json={"ok": True, "result": _plan_snapshot(state["folder"])})
                return
            if request.method == "POST" and path == "/requests/request-plan/modify":
                body = request.post_data_json or {}
                modifies.append(body)
                patch = body.get("patch") or {}
                if "expected_folder_name" in patch:
                    state["folder"] = patch["expected_folder_name"]
                route.fulfill(json={"ok": True, "result": {"applied": True, "warnings": []}})
                return
            route.continue_()

        page.route("**/api/v1/**", handler)
        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        page.wait_for_selector("#tracking-edit-plan")

        # The entry point names the business action and stays collapsed.
        expect(page.locator("#tracking-edit-plan")).to_have_text("修改追番方案")
        assert page.locator("#tracking-plan-editor").count() == 0

        page.locator("#tracking-edit-plan").click()
        page.wait_for_selector("#tracking-plan-editor")

        # The editable fields live in the editor's own disclosure; open it.
        page.evaluate(
            "() => document.querySelectorAll('#tracking-plan-editor details')"
            ".forEach((el) => { el.open = true; })"
        )
        # Identity fields stay read-only; the editable fields are the plan's own.
        page.locator("#tracking-plan-folder-name").fill("新目录")
        page.locator("#tracking-plan-apply-button").click()
        page.wait_for_timeout(300)

        assert len(modifies) == 1
        body = modifies[0]
        assert body["patch"] == {"expected_folder_name": "新目录"}
        assert "storage_dir" in body
        # The browser never sends a whole Request, a credential or a secret.
        rendered = json.dumps(body, ensure_ascii=False)
        for forbidden in ("confirmable_config", "rss_url", "password", "token"):
            assert forbidden not in rendered
        # A confirmed save collapses the editor again.
        assert page.locator("#tracking-plan-editor").count() == 0

class TestActivePlanApply:
    """Issue #91: an active plan raises local and external only on confirmation."""

    def test_active_plan_applies_editable_fields_with_the_local_plan(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _require_dist()
        set_storage_preferences(page, storage_dir)
        item = {
            **_item("tracking-a", "葬送的芙莉莲"),
            "request_id": "request-plan",
            "status": "ACTIVE",
            "status_label": "追番中",
            "status_group": "ACTIVE",
            "available_actions": [{
                "code": "MODIFY", "label": "修改外部订阅", "style": "SECONDARY",
                "requires_confirmation": True, "target_scopes": ["SUBSCRIPTION", "ASSOCIATED_RSS"],
            }],
        }
        state = {"folder": "芙莉莲"}
        modifies: list[dict[str, Any]] = []

        def handler(route: Any, request: Any) -> None:
            path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
            if request.method == "GET" and path == "/settings/autobangumi":
                route.fulfill(json={"ok": True, "result": {
                    "configured": True, "credential_present": True,
                    "connection_ref": "11111111-1111-4111-8111-111111111111",
                    "configuration_revision": 1, "connection_status": "CONFIGURED",
                }})
                return
            if request.method == "GET" and path == "/tracking/items":
                route.fulfill(json={"ok": True, "result": {"items": [item], "summary": _summary(1, active=1), "status_groups": _status_groups_for([item]), "warnings": []}})
                return
            if request.method == "GET" and path == "/tracking/items/tracking-a":
                route.fulfill(json={"ok": True, "result": {
                    **item, "origin": "single", "batch_id": None, "created_at": "2026-09-01T00:00:00Z",
                    "last_synced_at": None, "safe_info": None, "current_operation": None,
                    "revalidation_issues": [], "audit_events": [], "warnings": [],
                    "external_mapping": {"match_reason": "标题", "enabled": True, "external_deleted": False},
                }})
                return
            if request.method == "GET" and path == "/requests/request-plan":
                route.fulfill(json={"ok": True, "result": _plan_snapshot(state["folder"])})
                return
            if request.method == "POST" and path == "/tracking/items/tracking-a/modify":
                body = request.post_data_json or {}
                modifies.append(body)
                patch = body.get("patch") or {}
                if "expected_folder_name" in patch:
                    state["folder"] = patch["expected_folder_name"]
                route.fulfill(json={"ok": True, "result": {
                    "operation_id": "op-plan", "management_status": "SUCCEEDED",
                    "outcome": "SUCCESS", "needs_manual": False, "created": True,
                }})
                return
            route.continue_()

        page.route("**/api/v1/**", handler)
        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        page.wait_for_selector("#tracking-apply-plan")
        expect(page.locator("#tracking-apply-plan")).to_have_text("保存并应用到 Auto Bangumi")

        page.locator("#tracking-apply-plan").click()
        page.wait_for_selector("#tracking-apply-editor")
        # Identity stays read-only: the subtitle group control is disabled.
        expect(page.locator("#tracking-apply-subtitle-group")).to_be_disabled()

        page.evaluate(
            "() => document.querySelectorAll('#tracking-apply-editor details')"
            ".forEach((el) => { el.open = true; })"
        )
        page.locator("#tracking-apply-folder-name").fill("新目录")
        page.locator("#tracking-apply-apply-button").click()
        page.wait_for_selector(".confirm-dialog", timeout=10_000)
        page.locator(".confirm-dialog .primary-button").click()
        page.wait_for_timeout(400)

        assert len(modifies) == 1
        body = modifies[0]
        assert body["target_scope"] == "SUBSCRIPTION"
        assert body["confirm"] is True
        assert body["patch"] == {"expected_folder_name": "新目录"}
        # The local plan travels alongside, so the server raises both sides.
        assert body["local_plan"] == {"expected_folder_name": "新目录"}
        rendered = json.dumps(body, ensure_ascii=False)
        for forbidden in ("subtitle_group", "password", "token", "rss_url"):
            assert forbidden not in rendered

class TestPlanDelete:
    """Issue #92: the unified delete removes local data and keeps media."""

    def test_delete_plan_defaults_to_keeping_the_external_subscription(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _require_dist()
        set_storage_preferences(page, storage_dir)
        item = {
            **_item("tracking-a", "葬送的芙莉莲"),
            "request_id": "request-plan",
            "status": "ACTIVE",
            "status_label": "追番中",
            "status_group": "ACTIVE",
            "available_actions": [],
        }
        deletes: list[dict[str, Any]] = []
        state = {"deleted": False}

        def handler(route: Any, request: Any) -> None:
            path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
            if request.method == "GET" and path == "/settings/autobangumi":
                route.fulfill(json={"ok": True, "result": {
                    "configured": True, "credential_present": True,
                    "connection_ref": "11111111-1111-4111-8111-111111111111",
                    "configuration_revision": 1, "connection_status": "CONFIGURED",
                }})
                return
            if request.method == "GET" and path == "/tracking/items":
                items = [] if state["deleted"] else [item]
                route.fulfill(json={"ok": True, "result": {
                    "items": items, "summary": _summary(len(items), active=len(items)), "status_groups": _status_groups_for(items), "warnings": [],
                }})
                return
            if request.method == "GET" and path == "/tracking/items/tracking-a":
                route.fulfill(json={"ok": True, "result": {
                    **item, "origin": "single", "batch_id": None, "created_at": "2026-09-01T00:00:00Z",
                    "last_synced_at": None, "safe_info": None, "current_operation": None,
                    "revalidation_issues": [], "audit_events": [], "warnings": [],
                    "external_mapping": {"match_reason": "标题", "enabled": True, "external_deleted": False},
                }})
                return
            if request.method == "POST" and path == "/tracking/items/tracking-a/delete-plan":
                body = request.post_data_json or {}
                deletes.append(body)
                state["deleted"] = True
                route.fulfill(json={"ok": True, "result": {
                    "tracking_id": "tracking-a", "outcome": "DELETED", "external_deleted": False,
                }})
                return
            route.continue_()

        page.route("**/api/v1/**", handler)
        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        page.wait_for_selector("#tracking-delete-plan")

        page.locator("#tracking-delete-plan").click()
        # The option is present but off by default, and the confirm label is fixed.
        expect(page.locator("#tracking-delete-plan-external")).not_to_be_checked()
        expect(page.locator("#tracking-delete-plan-confirm")).to_have_text("删除追番方案")

        page.locator("#tracking-delete-plan-confirm").click()
        page.wait_for_timeout(400)

        assert len(deletes) == 1
        body = deletes[0]
        assert body["confirm"] is True
        assert body["delete_external"] is False
        rendered = json.dumps(body, ensure_ascii=False)
        for forbidden in ("file", "delete_files", "password", "token"):
            assert forbidden not in rendered
        # The deleted plan leaves the list and the page states the outcome.
        expect(page.locator(".tracking-list-item")).to_have_count(0)

    def test_cancelling_the_delete_asks_for_nothing(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _require_dist()
        set_storage_preferences(page, storage_dir)
        item = {
            **_item("tracking-a", "葬送的芙莉莲"),
            "request_id": "request-plan",
            "status": "ACTIVE",
            "status_label": "追番中",
            "status_group": "ACTIVE",
            "available_actions": [],
        }
        deletes: list[dict[str, Any]] = []

        def handler(route: Any, request: Any) -> None:
            path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
            if request.method == "GET" and path == "/settings/autobangumi":
                route.fulfill(json={"ok": True, "result": {
                    "configured": True, "credential_present": True,
                    "connection_ref": "11111111-1111-4111-8111-111111111111",
                    "configuration_revision": 1, "connection_status": "CONFIGURED",
                }})
                return
            if request.method == "GET" and path == "/tracking/items":
                route.fulfill(json={"ok": True, "result": {"items": [item], "summary": _summary(1, active=1), "status_groups": _status_groups_for([item]), "warnings": []}})
                return
            if request.method == "GET" and path == "/tracking/items/tracking-a":
                route.fulfill(json={"ok": True, "result": {
                    **item, "origin": "single", "batch_id": None, "created_at": "2026-09-01T00:00:00Z",
                    "last_synced_at": None, "safe_info": None, "current_operation": None,
                    "revalidation_issues": [], "audit_events": [], "warnings": [],
                    "external_mapping": {"match_reason": "标题", "enabled": True, "external_deleted": False},
                }})
                return
            if request.method == "POST" and path.endswith("/delete-plan"):
                deletes.append(request.post_data_json or {})
                route.continue_()
                return
            route.continue_()

        page.route("**/api/v1/**", handler)
        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        page.wait_for_selector("#tracking-delete-plan")

        page.locator("#tracking-delete-plan").click()
        page.locator("#tracking-delete-plan-cancel").click()
        page.wait_for_timeout(200)

        assert deletes == []
        # Back to the idle entry point, with the record still listed.
        expect(page.locator("#tracking-delete-plan")).to_be_visible()
        expect(page.locator(".tracking-list-item")).to_have_count(1)

    def test_unresolved_record_is_abandoned_with_a_bound_risk_confirmation(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """Issue #230 / ADR-0006: the last exit is local-only and bound.

        The panel offers the read-only verification first and the abandon after
        it, states that Auto Bangumi may still be downloading, offers no external
        scope, and posts the record revision + current operation it showed.
        """
        _require_dist()
        set_storage_preferences(page, storage_dir)
        item = {
            **_item("tracking-a", "葬送的芙莉莲"),
            "request_id": "request-plan",
            "status": "RECOVERY_REQUIRED",
            "status_label": "需要恢复",
            "status_group": "ATTENTION",
            "revision": 7,
            "available_actions": [],
        }
        detail = {
            **item, "origin": "single", "batch_id": None, "created_at": "2026-09-01T00:00:00Z",
            "last_synced_at": None, "safe_info": None,
            "current_operation": {
                "operation_id": "op-unresolved", "operation": "REFRESH_RSS",
                "state": "OUTCOME_UNKNOWN", "attempt": 1, "external_result_id": None,
                "error_type": None, "created_at": None, "updated_at": None, "completed_at": None,
            },
            "revalidation_issues": [], "audit_events": [], "warnings": [],
            "external_mapping": {"match_reason": "标题", "enabled": True, "external_deleted": False},
        }
        deletes: list[dict[str, Any]] = []
        state = {"deleted": False}

        def handler(route: Any, request: Any) -> None:
            path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
            if request.method == "GET" and path == "/settings/autobangumi":
                route.fulfill(json={"ok": True, "result": {
                    "configured": True, "credential_present": True,
                    "connection_ref": "11111111-1111-4111-8111-111111111111",
                    "configuration_revision": 1, "connection_status": "CONFIGURED",
                }})
                return
            if request.method == "POST" and path == "/settings/autobangumi/probe":
                route.fulfill(json={"ok": True, "result": {
                    "probe_status": "VERIFIED", "version": "3.1.18", "adapter": "legacy_3_1",
                    "subscription_list": "SUPPORTED", "subscription_detail": "SUPPORTED",
                    "subscription_submit": "SUPPORTED", "subscription_modify": "SUPPORTED",
                    "subscription_enable": "SUPPORTED", "subscription_disable": "SUPPORTED",
                    "subscription_delete": "SUPPORTED", "rss_list": "SUPPORTED",
                    "rss_modify": "SUPPORTED", "rss_enable": "SUPPORTED",
                    "rss_disable": "SUPPORTED", "rss_delete": "SUPPORTED",
                    "rss_refresh": "SUPPORTED", "external_verify": "SUPPORTED",
                    "checked_at": None, "safe_message": "ok",
                }})
                return
            if request.method == "GET" and path == "/tracking/items":
                items = [] if state["deleted"] else [item]
                route.fulfill(json={"ok": True, "result": {
                    "items": items, "summary": _summary(len(items), needs_attention=len(items)),
                    "status_groups": _status_groups_for(items), "warnings": [],
                }})
                return
            if request.method == "GET" and path == "/tracking/items/tracking-a":
                route.fulfill(json={"ok": True, "result": detail})
                return
            if request.method == "POST" and path == "/tracking/items/tracking-a/delete-plan":
                body = request.post_data_json or {}
                deletes.append(body)
                state["deleted"] = True
                route.fulfill(json={"ok": True, "result": {
                    "tracking_id": "tracking-a", "outcome": "DELETED", "external_deleted": False,
                }})
                return
            route.continue_()

        page.route("**/api/v1/**", handler)
        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        page.wait_for_selector("#tracking-abandon-plan")

        # E8: the read-only verification comes first.
        expect(page.locator("#tracking-probe-saved")).to_be_visible()
        page.locator("#tracking-probe-saved").click()
        page.wait_for_selector("#tracking-recover-verify")
        verify_box = page.locator("#tracking-recover-verify").bounding_box()
        abandon_box = page.locator("#tracking-abandon-plan").bounding_box()
        assert verify_box and abandon_box and verify_box["y"] < abandon_box["y"]

        page.locator("#tracking-abandon-plan").click()
        risk = page.locator("#tracking-abandon-risk").inner_text()
        assert "可能已经建立了订阅并会继续下载" in risk
        assert "不再跟踪" in risk
        assert "确定失败" not in risk and "可安全重试" not in risk
        # The abandon never offers the external scope.
        expect(page.locator("#tracking-delete-plan-external")).to_have_count(0)
        expect(page.locator("#tracking-abandon-confirm")).to_have_text("确认放弃并删除")

        page.locator("#tracking-abandon-confirm").click()
        page.wait_for_timeout(400)

        assert len(deletes) == 1
        body = deletes[0]
        assert body["confirm"] is True
        assert body["delete_external"] is False
        assert body["expected_revision"] == 7
        assert body["expected_operation_id"] == "op-unresolved"
        rendered = json.dumps(body, ensure_ascii=False)
        for forbidden in ("file", "password", "token", "connection_ref"):
            assert forbidden not in rendered
        expect(page.locator(".tracking-list-item")).to_have_count(0)

class TestPlanReuse:
    """Issue #93: "复制并重新添加" lives in the tracking detail."""

    def test_reuse_returns_to_the_add_journey_with_a_safe_suggestion(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _require_dist()
        set_storage_preferences(page, storage_dir)
        item = {**_item("tracking-a", "葬送的芙莉莲"), "request_id": "request-plan", "available_actions": []}
        safe_info = {
            "request_id": "request-plan", "status": "ACCEPTED", "raw_title": "安全标题",
            "title": "葬送的芙莉莲", "aliases": [], "season": 1, "season_raw": None,
            "season_evidence": None, "subtitle_groups": [], "selected_subtitle_group": "喵萌奶茶屋",
            "mikan_collection": {"bangumi_id": "mikan-1234", "title": "葬送的芙莉莲", "season": 1},
            "filter_rule": {"must_contain": "", "must_not_contain": "", "use_regex": False, "case_sensitive": False},
            "resources": {"selected_subtitle_group": "喵萌奶茶屋", "valid_resource_count": 1,
                          "invalid_resource_count": 0, "complete_resource_count": 1,
                          "valid_file_names": ["第一集.mkv"], "excluded_file_names": []},
            "folder_name": "安全文件夹", "storage_profile": "profile", "total_episodes": None,
            "updated_episode": None, "updated_episode_status": "NOT_IMPLEMENTED",
            "history_summary": [], "ab_status": None,
        }

        def handler(route: Any, request: Any) -> None:
            path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
            if request.method == "GET" and path == "/settings/autobangumi":
                route.fulfill(json={"ok": True, "result": {
                    "configured": True, "credential_present": True,
                    "connection_ref": "11111111-1111-4111-8111-111111111111",
                    "configuration_revision": 1, "connection_status": "CONFIGURED",
                }})
                return
            if request.method == "GET" and path == "/tracking/items":
                route.fulfill(json={"ok": True, "result": {"items": [item], "summary": _summary(1, pending=1), "status_groups": _status_groups_for([item]), "warnings": []}})
                return
            if request.method == "GET" and path == "/tracking/items/tracking-a":
                route.fulfill(json={"ok": True, "result": {
                    **item, "origin": "single", "batch_id": None, "created_at": "2026-09-01T00:00:00Z",
                    "last_synced_at": None, "current_operation": None, "revalidation_issues": [],
                    "external_mapping": None, "audit_events": [], "warnings": [], "safe_info": safe_info,
                }})
                return
            route.continue_()

        page.route("**/api/v1/**", handler)
        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        page.wait_for_selector("#tracking-reuse-plan")

        expect(page.locator("#tracking-reuse-plan")).to_have_text("复制并重新添加")
        page.locator("#tracking-reuse-plan").click()
        page.wait_for_url("**/app/add**", timeout=10_000)

        assert "/app/add" in page.url
        # The suggestion is in memory only: the URL carries no plan data.
        for forbidden in ("rss", "token", "password", "mikan-1234"):
            assert forbidden not in page.url

    def test_settled_failed_record_can_delete_without_a_connection(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """Issue #96: a finished operation is history, not a delete lock."""
        _require_dist()
        set_storage_preferences(page, storage_dir)
        item = {
            **_item("tracking-a", "葬送的芙莉莲"),
            "request_id": "request-plan",
            "status": "SUBMIT_FAILED",
            "status_label": "提交失败",
            "status_group": "ATTENTION",
            "available_actions": [],
        }
        deletes: list[dict[str, Any]] = []
        state = {"deleted": False}

        def handler(route: Any, request: Any) -> None:
            path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
            if request.method == "GET" and path == "/settings/autobangumi":
                # No Auto Bangumi connection is configured at all.
                route.fulfill(json={"ok": True, "result": {
                    "configured": False, "credential_present": False,
                    "connection_ref": None, "configuration_revision": 0,
                    "connection_status": "UNCONFIGURED",
                }})
                return
            if request.method == "GET" and path == "/tracking/items":
                items = [] if state["deleted"] else [item]
                route.fulfill(json={"ok": True, "result": {
                    "items": items, "summary": _summary(len(items), needs_attention=len(items)), "status_groups": _status_groups_for(items), "warnings": [],
                }})
                return
            if request.method == "GET" and path == "/tracking/items/tracking-a":
                route.fulfill(json={"ok": True, "result": {
                    **item, "origin": "single", "batch_id": None, "created_at": "2026-09-01T00:00:00Z",
                    "last_synced_at": None, "safe_info": None, "revalidation_issues": [],
                    "external_mapping": None, "audit_events": [], "warnings": [],
                    "current_operation": {
                        "operation_id": "op-settled", "operation": "SUBMIT", "state": "FAILED", "attempt": 1,
                    },
                }})
                return
            if request.method == "POST" and path == "/tracking/items/tracking-a/delete-plan":
                body = request.post_data_json or {}
                deletes.append(body)
                state["deleted"] = True
                route.fulfill(json={"ok": True, "result": {
                    "tracking_id": "tracking-a", "outcome": "DELETED", "external_deleted": False,
                }})
                return
            route.continue_()

        page.route("**/api/v1/**", handler)
        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        page.wait_for_selector("#tracking-delete-plan")

        page.locator("#tracking-delete-plan").click()
        page.locator("#tracking-delete-plan-cancel").click()
        page.wait_for_timeout(200)
        assert deletes == []

        page.locator("#tracking-delete-plan").click()
        page.locator("#tracking-delete-plan-confirm").click()
        page.wait_for_timeout(400)

        assert len(deletes) == 1
        body = deletes[0]
        assert body["delete_external"] is False
        # A purely local delete carries no connection material at all.
        assert "connection_ref" not in body
        assert "configuration_revision" not in body
        expect(page.locator(".tracking-list-item")).to_have_count(0)

class TestSubmissionModeLabels:
    """Issue #99 AC 6/7: only a real attempt shows its mode, fail closed."""

    def test_list_shows_the_mode_only_where_one_exists(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _require_dist()
        set_storage_preferences(page, storage_dir)
        pending = {
            **_item("tracking-pending", "待提交番剧"),
            "status": "PENDING_SUBMIT", "status_label": "待提交", "status_group": "PENDING",
            "available_actions": [],
            # 待提交 never fabricates a mode.
            "submission_mode": None,
        }
        active = {
            **_item("tracking-active", "追番中番剧"),
            "status": "ACTIVE", "status_label": "追番中", "status_group": "ACTIVE",
            "available_actions": [],
            "submission_mode": "CONTINUE_TRACKING",
        }

        def handler(route: Any, request: Any) -> None:
            path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
            if request.method == "GET" and path == "/settings/autobangumi":
                route.fulfill(json={"ok": True, "result": {
                    "configured": False, "credential_present": False,
                    "connection_ref": None, "configuration_revision": 0,
                    "connection_status": "UNCONFIGURED",
                }})
                return
            if request.method == "GET" and path == "/tracking/items":
                route.fulfill(json={"ok": True, "result": {
                    "items": [pending, active],
                    "summary": _summary(2, pending=1, active=1),
                    "status_groups": _status_groups_for([pending, active]),
                    "warnings": [],
                }})
                return
            if request.method == "GET" and path.startswith("/tracking/items/"):
                tracking_id = path.rsplit("/", 1)[-1]
                item = pending if tracking_id == "tracking-pending" else active
                route.fulfill(json={"ok": True, "result": {
                    **item, "origin": "single", "batch_id": None,
                    "created_at": "2026-09-01T00:00:00Z", "last_synced_at": None,
                    "safe_info": None, "current_operation": None, "revalidation_issues": [],
                    "external_mapping": None, "audit_events": [], "warnings": [],
                }})
                return
            route.continue_()

        page.route("**/api/v1/**", handler)
        page.goto(f"{live_server_url}/app/tracking")
        page.wait_for_selector(".tracking-list-item")

        labels = page.locator(".tracking-list-mode")
        assert labels.count() == 1
        assert labels.first.inner_text().strip() == "持续追番"
        # The 待提交 row carries no fabricated mode.
        pending_row = page.locator('[data-tracking-id="tracking-pending"]')
        assert pending_row.locator(".tracking-list-mode").count() == 0
