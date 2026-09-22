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
from tests.browser.saved_tracking_fixtures import _summary

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
                            "total": 9,
                            "pending": 4,
                            "processing": 2,
                            "active": 2,
                            "inactive": 1,
                            "needs_attention": 1,
                            "unreadable": 1,
                        },
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

        # Four fixed categories with the server's authoritative counts; the
        # summary claims 9 records although only two rows are loaded.
        cards = page.locator(".tracking-status-card")
        assert cards.count() == 4
        assert ["".join(text.split()) for text in cards.all_inner_texts()] == [
            "待提交4", "追番中2", "已停用1", "需处理1",
        ]
        assert "共 9 条追番记录" in page.locator(".tracking-status-total").inner_text()

        rows = page.locator(".tracking-list-item")
        assert rows.count() == 2
        assert "第 2 季" in rows.nth(0).inner_text()
        assert "2026" in rows.nth(0).inner_text()
        assert "已停用" in rows.nth(1).inner_text()

        # Selecting a row only switches the right-hand detail.
        rows.nth(1).click()
        page.wait_for_selector(".tracking-inspector-content")
        inspector = page.locator(".tracking-inspector")
        assert "追番详情" in inspector.inner_text()
        assert "咒术回战" in inspector.inner_text()
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
        page.wait_for_selector(".tracking-inspector-content")

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

        # The overview total and the list count are announced, not colour-only.
        assert page.locator(".tracking-status-total").get_attribute("role") == "status"
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
                route.fulfill(json={"ok": True, "result": {"items": [item], "summary": _summary(1, pending=1), "warnings": []}})
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
