from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.browser


def _require_dist() -> None:
    if (REPO_ROOT / "frontend" / "dist" / "index.html").is_file():
        return
    if os.environ.get("MIGU_ORCA_CI") == "1":
        raise RuntimeError("frontend/dist missing in CI — build the frontend before browser tests.")
    pytest.skip("frontend/dist not built — run `cd frontend && npm run build` first.")


@pytest.mark.parametrize(
    ("path", "feature_root", "feature_control"),
    [
        ("/app/add", "#workbench-heading", "#mikan-candidate-query"),
        ("/app/tracking", "#tracking-overview", "#tracking-refresh"),
        ("/app/settings", "#settings-heading", "#settings-storage-dir"),
    ],
)
def test_new_routes_mount_their_existing_feature_views(
    page: Page,
    live_server_url: str,
    path: str,
    feature_root: str,
    feature_control: str,
) -> None:
    """US-263/US-316: every public shell route mounts its current feature UI."""
    _require_dist()

    page.goto(f"{live_server_url}{path}")
    page.wait_for_selector(".app-title")
    page.wait_for_selector(feature_root)

    assert page.locator(feature_control).count() == 1
    assert page.locator(".shell-route").count() == 0


def _tracking_item(request_id: str) -> dict[str, Any]:
    """The tracking list projection — the authority for status and actions."""
    return {
        "tracking_id": "tracking-parity",
        "request_id": request_id,
        "title": "葬送的芙莉莲",
        "season": 1,
        "subtitle_group": "喵萌奶茶屋",
        "poster_path": None,
        "status": "ACTIVE",
        "status_label": "追番中",
        "status_group": "ACTIVE",
        "available_actions": [],
        "valid_resource_count": 3,
        "updated_episode": None,
        "updated_episode_status": "NOT_IMPLEMENTED",
        "total_episodes": 28,
        "revision": 4,
        "updated_at": "2026-09-13T00:00:00+00:00",
    }


def _mock_tracking(page: Page, request_id: str) -> None:
    item = _tracking_item(request_id)

    def handler(route: Any, request: Any) -> None:
        if request.method != "GET" or "/api/v1/tracking/items" not in request.url:
            route.continue_()
            return
        if "/api/v1/tracking/items/tracking-parity" in request.url:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": True,
                        "result": {
                            **item,
                            "origin": "batch",
                            "batch_id": "batch-parity",
                            "created_at": "2026-09-10T00:00:00+00:00",
                            "last_synced_at": None,
                            "safe_info": None,
                            "current_operation": None,
                            "revalidation_issues": [],
                            "external_mapping": None,
                            "audit_events": [],
                            "warnings": [],
                        },
                    },
                    ensure_ascii=False,
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
                        "items": [item],
                        "summary": {
                            "total": 1, "pending": 0, "processing": 0,
                            "active": 1, "inactive": 0, "needs_attention": 0, "unreadable": 0,
                        },
                        "warnings": [],
                    },
                },
                ensure_ascii=False,
            ),
        )

    # Playwright globs do not let `*` cross `/`, so the list and the detail need
    # their own patterns (a single `items*` route never sees `items/<id>`).
    page.route("**/api/v1/tracking/items*", handler)
    page.route("**/api/v1/tracking/items/**", handler)


def test_tracking_route_is_the_formal_tracking_screen_not_the_retired_queue(
    page: Page, live_server_url: str
) -> None:
    """US-316: `/app/tracking` is the formal tracking screen; the queue is gone."""
    _require_dist()
    _mock_tracking(page, "request-parity")

    page.goto(f"{live_server_url}/app/tracking")
    page.wait_for_selector("#tracking-overview")

    assert page.locator("#tracking-list-container").count() == 1
    expect(page.locator(".tracking-list-item")).to_contain_text("追番中")
    # The retired queue workflow has no runtime entry: none of its controls render.
    # (The old page owned its own credential form; the tracking screen has no
    # `batch-queue-*` identity anywhere.)
    for selector in ("#batch-queue-list", "#batch-queue-refresh", "#batch-queue-submit-form",
                     "#batch-queue-ab-auth-mode", "#batch-queue-ab-endpoint"):
        assert page.locator(selector).count() == 0, selector
    assert page.get_by_role("link", name="追番管理", exact=True).get_attribute("aria-current") == "page"
    expect(page.locator("#tracking-heading")).to_contain_text("管理待提交任务和正在运行的追番")
