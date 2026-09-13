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
        ("/app/plans", "#request-list-container", "#request-list-search"),
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
                            "active": 1, "needs_attention": 0, "unreadable": 0,
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
    expect(page.locator("#tracking-heading")).to_contain_text("查看本地追番状态")


def test_legacy_batch_deep_link_is_located_once_through_the_queue_request_id(
    page: Page, live_server_url: str
) -> None:
    """US-316: a retired `batch_id` link resolves once; tracking stays the authority.

    The legacy queue projection is allowed to hand over the public `request_id`
    only.  Its own status/title projection must never reach the page: the record
    that renders is the tracking DTO's.
    """
    _require_dist()
    _mock_tracking(page, "request-parity")
    page.route(
        "**/api/v1/batches/batch-parity/queue*",
        lambda route: route.fulfill(
            content_type="application/json",
            body=json.dumps(
                {
                    "ok": True,
                    "result": {
                        "batch_id": "batch-parity",
                        "queue": {
                            "queue_id": "queue-batch-parity",
                            "batch_id": "batch-parity",
                            "items": [
                                {
                                    "item_id": "item-parity",
                                    "request_id": "request-parity",
                                    "title": "旧队列标题不应出现",
                                    "status": "READY_TO_SUBMIT",
                                    "status_label": "待提交",
                                    "attempts": 0,
                                    "created_at": "2026-09-10T00:00:00+00:00",
                                    "updated_at": "2026-09-10T00:00:00+00:00",
                                }
                            ],
                        },
                    },
                },
                ensure_ascii=False,
            ),
        ),
    )

    page.goto(f"{live_server_url}/app/tracking?batch_id=batch-parity")
    page.wait_for_selector(".tracking-inspector-detail")

    # The legacy identifier is consumed: only the public tracking_id remains.
    assert page.url.endswith("/app/tracking?tracking_id=tracking-parity")
    expect(page.locator(".tracking-list-item")).to_contain_text("葬送的芙莉莲")
    expect(page.locator(".tracking-inspector-detail")).to_contain_text("追番中")
    # Nothing from the retired queue projection is rendered as state.
    assert page.get_by_text("旧队列标题不应出现").count() == 0
    assert page.get_by_text("待提交", exact=True).count() == 0
    assert page.locator("#tracking-compat-notice").count() == 0
    assert page.locator("#batch-queue-list").count() == 0


def test_unlocatable_legacy_batch_link_states_a_safe_next_step(
    page: Page, live_server_url: str
) -> None:
    """US-316: a batch that cannot be located shows a fixed next step, no ids."""
    _require_dist()
    _mock_tracking(page, "request-parity")
    page.route(
        "**/api/v1/batches/batch-gone/queue*",
        lambda route: route.fulfill(
            content_type="application/json",
            body=json.dumps(
                {
                    "ok": True,
                    "result": {"batch_id": "batch-gone", "queue": None},
                },
                ensure_ascii=False,
            ),
        ),
    )

    page.goto(f"{live_server_url}/app/tracking?batch_id=batch-gone")
    page.wait_for_selector("#tracking-compat-notice")

    notice = page.locator("#tracking-compat-notice")
    expect(notice).to_contain_text("旧的批量入口已退出")
    expect(notice).not_to_contain_text("batch-gone")
    assert page.url.endswith("/app/tracking")
    expect(page.locator(".tracking-list-item")).to_contain_text("葬送的芙莉莲")
