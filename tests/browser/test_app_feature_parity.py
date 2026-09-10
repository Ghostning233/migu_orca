from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import Page

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
        ("/app/tracking", "#batch-queue-list", "#batch-queue-refresh"),
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
    """US-263: every public shell route mounts its existing workflow UI."""
    _require_dist()

    page.goto(f"{live_server_url}{path}")
    page.wait_for_selector(".app-title")
    page.wait_for_selector(feature_root)

    assert page.locator(feature_control).count() == 1
    assert page.locator(".shell-route").count() == 0


def test_tracking_route_is_the_queue_workflow_not_a_mock_page(
    page: Page, live_server_url: str
) -> None:
    """US-263: tracking keeps the established queue read/submit/recover surface."""
    _require_dist()

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
                                    "title": "示例订阅方案",
                                    "status": "READY_TO_SUBMIT",
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
    page.wait_for_selector("#batch-queue-list")

    assert page.locator("#batch-queue-refresh").count() == 1
    assert page.locator("#batch-queue-submit-form").count() == 1
    assert page.get_by_text("提交到 Auto Bangumi", exact=True).count() == 1
    assert page.get_by_text("追番管理", exact=True).count() == 1
