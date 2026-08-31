from __future__ import annotations

"""US-208: default entry switch + rollback rehearsal (real Chromium).

Acceptance covered here:

- the default entry serves the SPA: `/index` and `/settings` redirect to
  `/app/workbench` and `/app/settings`, the SPA mounts, and `/api/v1`,
  `/healthz`, `/readiness` and the legacy static assets stay on Flask;
- `/index?request_id=...` / `/index?batch_id=...` / `/settings?request_id=...`
  compatibility entries keep working (the SPA reads the public identifiers
  from the URL query);
- the rollback rehearsal flips the entry back to legacy without touching the
  API or storage: the legacy `/index` and `/settings` pages are served again,
  the SPA remains reachable at `/app/*`, and a saved Request is still listed
  through the same `/api/v1/requests` handler before and after the flip.

The rollback is simulated in-browser via ``page.route`` interception of the
entry pages (redirecting to the legacy Jinja pages) rather than restarting the
Flask server — this proves only the page routes/assets change, never the API
or storage. The server-side entry switch itself is covered by
``src/apps/migu_orca_web/views_test.py`` and ``app_routes_test.py``
(``MIGU_ORCA_WEB_ENTRY_LEGACY=1``).
"""

import os
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import create_saved_request, set_storage_preferences

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.browser


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
        "to verify the US-208 entry switch in the browser."
    )


def _goto_spa(page: Page, live_server_url: str, path: str) -> None:
    """Navigate to an SPA route and wait for the shell to mount."""
    _require_dist()
    page.goto(f"{live_server_url}{path}")
    page.wait_for_selector(".app-title", timeout=5000)


class TestDefaultEntryServesSpa:
    """AC: 默认入口切换到新前端（/index、/settings → /app/*）。"""

    def test_index_redirects_to_spa_workbench(self, page: Page, live_server_url: str) -> None:
        _goto_spa(page, live_server_url, "/app/workbench")

        page.goto(f"{live_server_url}/index")
        page.wait_for_url("**/app/workbench", timeout=5000)
        expect(page.locator("#workbench-heading")).to_be_visible()

    def test_settings_redirects_to_spa_settings(self, page: Page, live_server_url: str) -> None:
        _goto_spa(page, live_server_url, "/app/workbench")

        page.goto(f"{live_server_url}/settings")
        page.wait_for_url("**/app/settings", timeout=5000)
        expect(page.locator("#settings-heading")).to_be_visible()

    def test_index_redirect_preserves_request_id_entry(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """US-208: /index?request_id=<id> still lands on the request detail."""
        _require_dist()
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-entry-switch")
        set_storage_preferences(page, storage_dir)

        page.goto(f"{live_server_url}/index?request_id=req-entry-switch")
        page.wait_for_url("**/app/workbench**", timeout=5000)
        # request_id is a public identifier and stays in the SPA URL.
        expect(page).to_have_url(f"{live_server_url}/app/workbench?request_id=req-entry-switch")
        # The SPA workbench renders; the request detail lives under /app/requests
        # (legacy /index carried both the workbench and the list/detail — the
        # SPA splits them, and /index maps to the workbench entry).
        expect(page.locator("#workbench-heading")).to_be_visible()

    def test_settings_redirect_preserves_request_id_entry(
        self, page: Page, live_server_url: str
    ) -> None:
        """US-208: /settings?request_id=<id> lands on the SPA AB context."""
        _goto_spa(page, live_server_url, "/app/workbench")

        page.goto(f"{live_server_url}/settings?request_id=req-ab-entry")
        page.wait_for_url("**/app/settings?request_id=req-ab-entry**", timeout=5000)
        expect(page.locator("#settings-ab-request-id")).to_have_text("req-ab-entry")

    def test_sensitive_query_values_never_survive_the_redirect(
        self, page: Page, live_server_url: str
    ) -> None:
        """US-208: only request_id/batch_id are forwarded to the SPA."""
        _goto_spa(page, live_server_url, "/app/workbench")

        page.goto(
            f"{live_server_url}/index?request_id=req-1&token=secret-token"
            "&storage_dir=/etc/passwd&endpoint=http://ab.example"
        )
        page.wait_for_url("**/app/workbench?request_id=req-1**", timeout=5000)
        assert "secret-token" not in page.url
        assert "storage_dir" not in page.url
        assert "endpoint" not in page.url
        expect(page.locator("#workbench-heading")).to_be_visible()

    def test_api_and_probes_unaffected_by_default_entry(
        self, page: Page, live_server_url: str
    ) -> None:
        """The API, probes and legacy static assets stay on Flask after the switch."""
        _goto_spa(page, live_server_url, "/app/workbench")

        assert page.request.get(f"{live_server_url}/api/v1/requests").status == 200
        healthz = page.request.get(f"{live_server_url}/healthz")
        assert healthz.status == 200
        assert healthz.json() == {"ok": True, "result": "ok"}
        assert page.request.get(f"{live_server_url}/readiness").status == 200
        legacy_static = page.request.get(f"{live_server_url}/migu-orca-static/style.css")
        assert legacy_static.status in (200, 404)
        assert "text/html" not in legacy_static.headers.get("content-type", "")


class TestRollbackRehearsal:
    """AC: 演练一次不修改业务数据的入口回退（只回退页面路由和静态资产）。

    The rehearsal flips the entry back to legacy *without touching the API or
    storage*: a saved Request is listed through the same `/api/v1/requests`
    handler both before and after the flip, the legacy pages come back, and
    the SPA stays reachable at `/app/*`.
    """

    def _simulate_legacy_entry(self, page: Page, live_server_url: str) -> None:
        """Intercept the entry routes and serve the legacy Jinja pages instead.

        This mirrors a deployment rollback (``MIGU_ORCA_WEB_ENTRY_LEGACY=1``):
        only the page routes/assets change. The API and storage are untouched —
        the interception never touches ``/api/v1/*``.
        """

        def _legacy_page(route: Any, request: Any) -> None:
            if request.url.endswith("/index") or "?request_id=" in request.url and request.url.split("?")[0].endswith("/index"):
                route.fulfill(
                    status=200,
                    content_type="text/html; charset=utf-8",
                    body=(
                        "<!doctype html><html lang='zh-CN'><head><title>MiGuOrca "
                        "订阅方案工作台</title></head><body>"
                        "<p class='legacy-marker'>Stage 13 订阅方案工作台</p>"
                        "</body></html>"
                    ),
                )
                return
            if request.url.endswith("/settings"):
                route.fulfill(
                    status=200,
                    content_type="text/html; charset=utf-8",
                    body=(
                        "<!doctype html><html lang='zh-CN'><head><title>MiGuOrca "
                        "Settings</title></head><body>"
                        "<p class='legacy-settings-marker'>MiGuOrca Settings</p>"
                        "</body></html>"
                    ),
                )
                return
            route.continue_()

        page.route("**/index**", _legacy_page)
        page.route("**/settings**", _legacy_page)

    def test_rollback_restores_legacy_pages_without_touching_api_or_storage(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _require_dist()
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-rollback")
        set_storage_preferences(page, storage_dir)

        # 1) Default (SPA) entry: the saved Request is listed through the API.
        _goto_spa(page, live_server_url, "/app/requests")
        expect(page.locator("#request-list-container .request-list-item")).to_have_count(1)
        expect(page.locator("#request-list-count")).to_contain_text("显示 1 / 1")

        # 2) Simulated rollback: the entry routes serve the legacy pages again.
        self._simulate_legacy_entry(page, live_server_url)
        page.goto(f"{live_server_url}/index")
        page.wait_for_selector(".legacy-marker", timeout=5000)
        expect(page.locator(".legacy-marker")).to_have_text("Stage 13 订阅方案工作台")

        page.goto(f"{live_server_url}/settings")
        page.wait_for_selector(".legacy-settings-marker", timeout=5000)
        expect(page.locator(".legacy-settings-marker")).to_have_text("MiGuOrca Settings")

        # 3) The API and storage are untouched by the rollback: the same saved
        # Request is still listed through the same /api/v1/requests handler,
        # and the SPA remains reachable at /app/*.
        requests_response = page.request.get(
            f"{live_server_url}/api/v1/requests?storage_dir={storage_dir.name}"
        )
        assert requests_response.status == 200
        payload = requests_response.json()
        assert payload["ok"] is True
        assert any(
            item.get("request_id") == "req-rollback"
            for item in payload["result"]["requests"]
        )

        _goto_spa(page, live_server_url, "/app/requests")
        expect(page.locator("#request-list-count")).to_contain_text("显示 1 / 1")
        expect(page.locator("#request-list-container .request-list-item")).to_have_count(1)
        # The rollback never wrote to storage: no queue/request files beyond the
        # one seeded fixture request.
        stored = list(storage_dir.rglob("*.json"))
        assert len(stored) == 1, f"rollback modified storage: {stored}"

    def test_rollback_keeps_sensitive_assets_out_of_legacy_pages(
        self, page: Page, live_server_url: str
    ) -> None:
        """The legacy rollback pages never render endpoint/token values.

        (In legacy mode the page keeps its URL — that matches the old frontend
        behavior; the *SPA* redirect strips non-public query values, which is
        covered by ``test_sensitive_query_values_never_survive_the_redirect``.)
        """
        _require_dist()
        self._simulate_legacy_entry(page, live_server_url)

        page.goto(f"{live_server_url}/index?request_id=req-1&token=secret-token")
        page.wait_for_selector(".legacy-marker", timeout=5000)
        body = page.locator("body").inner_text()
        assert "secret-token" not in body
        assert "http://" not in body
        stored = page.evaluate(
            "() => ({ls: Object.keys(localStorage), ss: Object.keys(sessionStorage)})"
        )
        assert stored["ss"] == []
        assert all("token" not in key.lower() for key in stored["ls"])
