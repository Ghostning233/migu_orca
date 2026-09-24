from __future__ import annotations

"""Issue #84: the tracking list and detail show one durable same-origin cover.

The browser journey is mocked at the tracking DTO boundary plus the poster
proxy, so this never touches MiKan or Auto Bangumi. What it proves:

* a record whose summary carries ``poster_path`` renders that same-origin image
  in both the list and the detail, and the image really loads,
* a missing cover and an unavailable cover both fall back to the stable
  placeholder without breaking selection or the rest of the page,
* an upstream image address is never requested or rendered, even if a broken
  response smuggles one in — the client fails closed on its own.
"""

import base64
import json
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import set_storage_preferences

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.browser

#: 1x1 opaque PNG; the poster proxy returns real image bytes, never HTML.
_COVER_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AAAwAB/AF/9v3lAAAAAElFTkSuQmCC"
)
_COVER_KEY = "a" * 64
_COVER_PATH = f"/api/v1/mikan/posters/{_COVER_KEY}"
#: Stands in for an upstream cover address that must never be requested.
_UPSTREAM_COVER = "https://mikan.example/secret-cover.jpg"


def _dist_built() -> bool:
    return (REPO_ROOT / "frontend" / "dist" / "index.html").is_file()


def _require_dist() -> None:
    if not _dist_built():
        pytest.skip("frontend/dist not built; run `npm run build` in frontend/")


def _item(poster_path: str | None) -> dict[str, Any]:
    return {
        "tracking_id": "tracking-cover",
        "request_id": "request-cover",
        "title": "葬送的芙莉莲",
        "season": 1,
        "subtitle_group": "喵萌奶茶屋",
        "poster_path": poster_path,
        "status": "ACTIVE",
        "status_label": "追番中",
        "status_group": "ACTIVE",
        "available_actions": [],
        "valid_resource_count": 1,
        "updated_episode": None,
        "updated_episode_status": "NOT_IMPLEMENTED",
        "total_episodes": None,
        "revision": 1,
        "updated_at": "2026-09-14T00:00:00Z",
    }


def _detail_payload(item: dict[str, Any]) -> dict[str, Any]:
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


def _mock_tracking(page: Page, item: dict[str, Any], *, poster_status: int = 200) -> None:
    """Mock the tracking DTO boundary and the poster proxy."""

    def handler(route: Any, request: Any) -> None:
        if request.method != "GET" or "/api/v1/tracking/items" not in request.url:
            route.continue_()
            return
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
                        "items": [item],
                        "summary": {
                            "total": 1,
                            "pending": 0,
                            "processing": 0,
                            "active": 1,
                            "inactive": 0, "needs_attention": 0,
                            "unreadable": 0,
                        },
                        "warnings": [],
                    },
                },
                ensure_ascii=False,
            ),
        )

    page.route("**/api/v1/tracking/items*", handler)
    page.route("**/api/v1/tracking/items/**", handler)

    def poster(route: Any) -> None:
        if poster_status != 200:
            route.fulfill(
                status=poster_status,
                content_type="application/json",
                body=json.dumps(
                    {"ok": False, "error_type": "poster_not_found"},
                    ensure_ascii=False,
                ),
            )
            return
        route.fulfill(status=200, content_type="image/png", body=_COVER_PNG)

    page.route("**/api/v1/mikan/posters/**", poster)


class TestTrackingCover:
    def test_list_and_detail_show_the_same_same_origin_cover(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _require_dist()
        set_storage_preferences(page, storage_dir)
        _mock_tracking(page, _item(_COVER_PATH))

        page.goto(f"{live_server_url}/app/tracking")
        page.wait_for_selector("#tracking-overview")

        list_image = page.locator(".tracking-list-item .tracking-poster img")
        list_image.wait_for()
        assert list_image.get_attribute("src") == _COVER_PATH
        page.wait_for_function(
            "() => { const img = document.querySelector('.tracking-list-item .tracking-poster img');"
            " return img && img.complete && img.naturalWidth > 0; }"
        )

        page.locator(".tracking-list-item").first.click()
        detail_image = page.locator(".tracking-inspector-identity .tracking-poster img")
        detail_image.wait_for()
        assert detail_image.get_attribute("src") == _COVER_PATH

        body = page.locator("body").inner_text()
        assert "mikan.example" not in body
        assert "mikan.example" not in page.url
        assert "mikan.example" not in page.evaluate("() => JSON.stringify(localStorage)")

    def test_missing_cover_uses_the_stable_placeholder(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _require_dist()
        set_storage_preferences(page, storage_dir)
        _mock_tracking(page, _item(None))

        page.goto(f"{live_server_url}/app/tracking")
        page.wait_for_selector("#tracking-overview")
        page.wait_for_selector(
            '.tracking-list-item .tracking-poster[data-poster-state="placeholder"]'
        )
        assert page.locator(".tracking-list-item .tracking-poster img").count() == 0

        page.locator(".tracking-list-item").first.click()
        page.wait_for_selector(
            '.tracking-inspector-identity .tracking-poster[data-poster-state="placeholder"]'
        )
        assert page.locator(".tracking-inspector-identity .tracking-poster img").count() == 0
        # The rest of the detail still renders and stays usable.
        assert "有效资源" in page.locator(".tracking-inspector-content").inner_text()

    def test_unavailable_cover_falls_back_without_breaking_the_row(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _require_dist()
        set_storage_preferences(page, storage_dir)
        _mock_tracking(page, _item(_COVER_PATH), poster_status=404)

        page.goto(f"{live_server_url}/app/tracking")
        page.wait_for_selector("#tracking-overview")
        page.wait_for_selector(
            '.tracking-list-item .tracking-poster[data-poster-state="placeholder"]'
        )
        assert page.locator(".tracking-list-item .tracking-poster img").count() == 0

        # Selection still works after the cover request failed. Safe-detail
        # loading is asynchronous: wait for the loaded text, not just the
        # container, so this cannot race the mocked detail response.
        page.locator(".tracking-list-item").first.click()
        expect(page.locator(".tracking-inspector-content")).to_contain_text("葬送的芙莉莲")

    def test_upstream_cover_address_is_never_requested_or_rendered(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _require_dist()
        set_storage_preferences(page, storage_dir)
        _mock_tracking(page, _item(_UPSTREAM_COVER))
        requested: list[str] = []
        page.on("request", lambda request: requested.append(request.url))

        page.goto(f"{live_server_url}/app/tracking")
        page.wait_for_selector("#tracking-overview")
        page.wait_for_selector(
            '.tracking-list-item .tracking-poster[data-poster-state="placeholder"]'
        )

        assert page.locator(".tracking-list-item .tracking-poster img").count() == 0
        assert not any("mikan.example" in url for url in requested)
        assert "mikan.example" not in page.locator("body").inner_text()
        assert "mikan.example" not in page.url
        assert "mikan.example" not in page.evaluate("() => JSON.stringify(localStorage)")
        assert "mikan.example" not in page.evaluate("() => JSON.stringify(sessionStorage)")
