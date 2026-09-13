from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import set_storage_preferences

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.browser

# US-316: the retired queue entry (Stage 20/27 `QueueView`, US-206).
#
# Stage 38 replaced `/app/tracking` with the formal tracking management screen,
# so the queue view left the default runtime: `/app/queue` is now a one-time
# compatibility redirect and no queue control renders anywhere.  The queue
# component and the backend queue endpoints deliberately stay in the repo for
# rollback (Stage 38 §10.2) — F-G owns their final removal.
#
# What the retired entry must still guarantee:
#   * the legacy route lands on the formal tracking screen,
#   * a legacy `batch_id` is resolved exactly once through the *public*
#     `request_id` projection of the old queue, and
#   * the tracking DTO remains the sole authority for state, actions and
#     selection; an unlocatable batch only gets a fixed next step.
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
                            "active": 0, "needs_attention": 0, "unreadable": 0,
                        },
                        "warnings": [],
                    },
                },
                ensure_ascii=False,
            ),
        )

    page.route("**/api/v1/tracking/items*", handler)
    page.route("**/api/v1/tracking/items/**", handler)


def _mock_legacy_queue(page: Page, batch_id: str, request_ids: list[str]) -> None:
    """Mock the retired queue projection: public request ids only."""
    page.route(
        f"**/api/v1/batches/{batch_id}/queue*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "ok": True,
                    "result": {
                        "batch_id": batch_id,
                        "queue": {
                            "queue_id": f"queue-{batch_id}",
                            "batch_id": batch_id,
                            "created_at": "2026-09-10T00:00:00+00:00",
                            "updated_at": "2026-09-10T00:00:00+00:00",
                            "items": [
                                {
                                    "queue_id": f"queue-{batch_id}",
                                    "batch_id": batch_id,
                                    "item_id": f"item-{index}",
                                    "request_id": request_id,
                                    # The retired projection's own status/title must
                                    # never be rendered as page state.
                                    "title": "旧队列标题不应出现",
                                    "status": "READY_TO_SUBMIT",
                                    "status_label": "等待提交",
                                    "attempts": 0,
                                    "last_error": None,
                                    "ab_result_summary": None,
                                    "created_at": "2026-09-10T00:00:00+00:00",
                                    "updated_at": "2026-09-10T00:00:00+00:00",
                                }
                                for index, request_id in enumerate(request_ids)
                            ],
                        },
                    },
                },
                ensure_ascii=False,
            ),
        ),
    )


class TestRetiredQueueEntry:
    """US-316: the legacy queue route is a redirect, never a mounted page."""

    def test_legacy_queue_route_redirects_to_the_formal_tracking_screen(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """`/app/queue` lands on the tracking screen with no queue controls."""
        _require_dist()
        set_storage_preferences(page, storage_dir)

        page.goto(f"{live_server_url}/app/queue?batch_id=batch-legacy")
        page.wait_for_selector("#tracking-overview")

        # The retired query is consumed by the one-time compat location; the
        # batch the real backend does not know about only gets a fixed notice.
        page.wait_for_selector("#tracking-compat-notice")
        assert page.url.endswith("/app/tracking")
        expect(page.locator("#tracking-compat-notice")).to_contain_text("旧的批量入口已退出")
        assert page.locator("#batch-queue-list").count() == 0
        assert page.locator("#batch-queue-count").count() == 0
        assert page.locator("#batch-queue-refresh").count() == 0
        assert page.locator("#batch-queue-submit-form").count() == 0
        assert page.locator("#tracking-refresh").count() == 1

    def test_legacy_batch_link_locates_once_and_tracking_stays_authoritative(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """The old queue is read for its public request_id only."""
        _require_dist()
        set_storage_preferences(page, storage_dir)
        _mock_tracking(page, [_tracking_item("tracking-legacy", "request-legacy", "葬送的芙莉莲")])
        _mock_legacy_queue(page, "batch-legacy", ["request-legacy"])

        page.goto(f"{live_server_url}/app/queue?batch_id=batch-legacy")
        page.wait_for_selector(".tracking-inspector-detail")

        # Exactly one location: the legacy identifier is replaced by the public
        # tracking_id and no longer drives anything.
        assert page.url.endswith("/app/tracking?tracking_id=tracking-legacy")
        expect(page.locator(".tracking-list-item")).to_contain_text("葬送的芙莉莲")
        expect(page.locator(".tracking-list-item")).to_contain_text("待提交")
        assert page.get_by_text("旧队列标题不应出现").count() == 0
        assert page.get_by_text("等待提交", exact=True).count() == 0
        assert page.locator("#tracking-compat-notice").count() == 0
        assert page.locator("#batch-queue-list").count() == 0

    def test_unlocatable_batch_link_states_a_fixed_next_step(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """A batch whose request ids match no local record only gets a notice."""
        _require_dist()
        set_storage_preferences(page, storage_dir)
        _mock_tracking(page, [_tracking_item("tracking-legacy", "request-legacy", "葬送的芙莉莲")])
        _mock_legacy_queue(page, "batch-legacy", ["request-missing"])

        page.goto(f"{live_server_url}/app/queue?batch_id=batch-legacy")
        page.wait_for_selector("#tracking-compat-notice")

        notice = page.locator("#tracking-compat-notice")
        expect(notice).to_have_attribute("role", "status")
        expect(notice).to_contain_text("旧的批量入口已退出")
        expect(notice).not_to_contain_text("batch-legacy")
        expect(notice).not_to_contain_text("request-missing")
        assert page.url.endswith("/app/tracking")
        assert page.locator('[aria-current="true"]').count() == 0
        # The list itself is untouched: nothing was selected on the user's behalf.
        expect(page.locator(".tracking-list-item")).to_contain_text("葬送的芙莉莲")

    def test_backend_queue_compatibility_endpoint_is_still_available(
        self, page: Page, live_server_url: str
    ) -> None:
        """Stage 38 retires the UI entry only — the compat endpoint stays."""
        _require_dist()

        response = page.request.get(
            f"{live_server_url}/api/v1/batches/batch-absent/queue",
            params={"storage_dir": "storage"},
        )
        assert response.status == 200
        payload = response.json()
        assert payload["ok"] is True
        # An unknown batch is still a safe, public projection — never an error.
        assert payload["result"] == {"batch_id": "batch-absent", "queue": None}
