from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page

from tests.browser.conftest import set_storage_preferences

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.browser

# US-316: the retired queue entry (Stage 20/27 `QueueView`, US-206).
#
# Stage 38 replaced `/app/tracking` with the formal tracking management screen,
# so the queue view left the default runtime: `/app/queue` is now a one-time
# compatibility redirect and no queue control renders anywhere. Queue runtime
# components and write/projection endpoints are removed; historical storage is
# exercised only through read-only migration tests.
#
# What the retired entry must still guarantee:
#   * the legacy route lands on the formal tracking screen,
#   * legacy query values are consumed once without selecting tracking state,
#   * the tracking DTO remains the sole authority for state and actions.
#
# The retired queue workflows themselves (submit / retry / recover / sensitive
# credential boundary) are covered against the new page in
# `tests/browser/test_app_tracking.py` — this file must not re-test them.


def _dist_built() -> bool:
    """True when the Vite production build exists (frontend/dist/index.html)."""
    return (REPO_ROOT / "frontend" / "dist" / "index.html").is_file()


def _require_dist() -> None:
    """The SPA build is a hard prerequisite for these browser tests."""
    if _dist_built():
        return
    if os.environ.get("MIGU_ORCA_CI") == "1":
        raise RuntimeError(
            "frontend/dist missing in CI — run `npm ci && npm run build` "
            "in frontend/ before the browser suite."
        )
    pytest.skip(
        "frontend/dist not built — run `cd frontend && npm ci && npm run build` "
        "to verify the retired queue entry in the browser."
    )


def _tracking_item(tracking_id: str, request_id: str, title: str) -> dict[str, Any]:
    return {
        "tracking_id": tracking_id,
        "request_id": request_id,
        "title": title,
        "season": 1,
        "subtitle_group": "喵萌奶茶屋",
        "poster_path": None,
        "status": "PENDING_SUBMIT",
        "status_label": "待提交",
        "status_group": "PENDING",
        "available_actions": [],
        "valid_resource_count": 1,
        "updated_episode": None,
        "updated_episode_status": "NOT_IMPLEMENTED",
        "total_episodes": 28,
        "revision": 2,
        "updated_at": "2026-09-13T00:00:00+00:00",
    }


def _mock_tracking(page: Page, items: list[dict[str, Any]]) -> None:
    """Serve the tracking list/detail projections (the authority for the page)."""
    detail = {
        **items[0],
        "origin": "batch",
        "batch_id": "batch-legacy",
        "created_at": "2026-09-12T00:00:00+00:00",
        "last_synced_at": None,
        "safe_info": None,
        "current_operation": None,
        "revalidation_issues": [],
        "external_mapping": None,
        "audit_events": [],
        "warnings": [],
    }

    def handler(route: Any, request: Any) -> None:
        if request.method != "GET" or "/api/v1/tracking/items" not in request.url:
            route.continue_()
            return
        if f"/api/v1/tracking/items/{items[0]['tracking_id']}" in request.url:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"ok": True, "result": detail}, ensure_ascii=False),
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
                            "total": len(items), "pending": len(items), "processing": 0,
                            "active": 0, "inactive": 0, "needs_attention": 0, "unreadable": 0,
                        },
                        "warnings": [],
                    },
                },
                ensure_ascii=False,
            ),
        )

    page.route("**/api/v1/tracking/items*", handler)
    page.route("**/api/v1/tracking/items/**", handler)




class TestRetiredQueueEntry:
    """US-316: the legacy queue route is a redirect, never a mounted page."""

    def test_legacy_queue_route_redirects_to_the_formal_tracking_screen(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """`/app/queue` lands on the tracking screen with no queue controls."""
        _require_dist()
        set_storage_preferences(page, storage_dir)
        requests: list[str] = []
        page.on("request", lambda request: requests.append(request.url))

        page.goto(f"{live_server_url}/app/queue?batch_id=batch-legacy&token=canary")
        page.wait_for_selector("#tracking-overview")

        # The retired query is consumed by a safe redirect; tracking remains
        # authoritative and no queue projection API is consulted.
        assert page.url.endswith("/app/tracking")
        assert "batch-legacy" not in page.url
        assert "canary" not in page.url
        assert not any("/api/v1/batches/" in url and "/queue" in url for url in requests)
        assert "canary" not in page.locator("body").inner_text()
        assert "canary" not in page.evaluate("() => JSON.stringify(localStorage)")
        assert page.locator("#batch-queue-list").count() == 0
        assert page.locator("#batch-queue-count").count() == 0
        assert page.locator("#batch-queue-refresh").count() == 0
        assert page.locator("#batch-queue-submit-form").count() == 0
        assert page.locator("#tracking-refresh").count() == 1
