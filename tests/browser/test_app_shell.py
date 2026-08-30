from __future__ import annotations

import os
from pathlib import Path

import pytest
from playwright.sync_api import Page

from tests.browser.conftest import is_browser_available

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.browser


def _dist_built() -> bool:
    """True when the Vite production build exists (frontend/dist/index.html)."""
    return (REPO_ROOT / "frontend" / "dist" / "index.html").is_file()


def _require_dist() -> None:
    """The SPA build is a hard prerequisite for these browser tests.

    US-197 requires the real SPA to be verified in Chromium; a silent skip is
    not a pass. Locally the test skips with an explicit message when
    ``frontend/dist`` is absent (the placeholder path is covered by the
    non-build test above), but in CI (``MIGU_ORCA_CI=1``) a missing build is
    a loud failure — CI runs ``npm ci && npm run build`` before the suite.
    """
    if _dist_built():
        return
    if os.environ.get("MIGU_ORCA_CI") == "1":
        raise RuntimeError(
            "frontend/dist missing in CI — run `npm ci && npm run build` "
            "in frontend/ before the browser suite."
        )
    pytest.skip(
        "frontend/dist not built — run `cd frontend && npm ci && npm run build` "
        "to verify the real SPA in the browser."
    )


def test_app_shell_loads_and_mounts_spa(page: Page, live_server_url: str) -> None:
    """/app/ serves the SPA shell; with a build the Vue app mounts and routes.

    US-197 acceptance: "最小 /app/ 页面可由 Flask 同源加载". Without a build
    the dependency-free placeholder is served (asserted here too), but CI and
    local verification build the frontend first so the real SPA is exercised.
    """
    page.goto(f"{live_server_url}/app/")
    page.wait_for_selector("#app", state="attached")

    if not _dist_built():
        assert "frontend/dist" in page.locator("body").inner_text()
        return

    # Router base is '/app/': the root route redirects to the workbench.
    page.wait_for_url("**/app/workbench", timeout=5000)
    assert page.locator(".app-title").inner_text() == "MiGuOrca"
    nav = page.locator(".top-nav .nav-link")
    assert nav.count() == 4
    assert nav.nth(0).inner_text().strip() == "订阅方案工作台"
    assert nav.nth(1).inner_text().strip() == "订阅方案"
    assert nav.nth(2).inner_text().strip() == "提交队列"
    assert nav.nth(3).inner_text().strip() == "Settings"
    # The lazy-loaded workbench view mounted.
    assert page.locator("#workbench-heading").count() >= 1
    # The placeholder must not leak into a built SPA.
    assert "frontend/dist" not in page.content()


def test_app_spa_navigation_between_routes(page: Page, live_server_url: str) -> None:
    """Client-side navigation between all four shell routes works."""
    _require_dist()

    page.goto(f"{live_server_url}/app/workbench")
    page.wait_for_selector(".app-title")

    page.get_by_role("link", name="订阅方案", exact=True).click()
    page.wait_for_url("**/app/requests", timeout=5000)
    assert page.locator("#requests-heading").count() >= 1
    assert page.locator(".requests-panel .empty-state").count() >= 1

    page.get_by_role("link", name="提交队列", exact=True).click()
    page.wait_for_url("**/app/queue", timeout=5000)
    assert page.locator("#queue-heading").count() >= 1
    assert page.locator(".queue-panel .empty-state").count() >= 1

    page.locator(".top-nav .nav-link", has_text="Settings").click()
    page.wait_for_url("**/app/settings", timeout=5000)
    assert page.locator("#settings-heading").count() >= 1

    page.locator(".top-nav .nav-link", has_text="订阅方案工作台").click()
    page.wait_for_url("**/app/workbench", timeout=5000)
    assert page.locator("#workbench-heading").count() >= 1


def test_app_shell_no_console_errors(page: Page, live_server_url: str) -> None:
    """The built SPA loads without console errors (asset URLs resolve)."""
    _require_dist()

    console_errors: list[str] = []

    def _on_console(msg: object) -> None:
        mtype = getattr(msg, "type", "")
        if mtype == "error":
            console_errors.append(str(getattr(msg, "text", "")))

    page.on("console", _on_console)
    page.goto(f"{live_server_url}/app/")
    page.wait_for_url("**/app/workbench", timeout=5000)
    page.wait_for_timeout(600)

    critical = [e for e in console_errors if "favicon" not in e.lower()]
    assert not critical, f"Unexpected console errors: {critical}"


def test_spa_fallback_never_intercepts_api_or_probes(
    page: Page, live_server_url: str
) -> None:
    """/api/v1, /healthz and /readiness keep their handlers after visiting /app."""
    _require_dist()

    page.goto(f"{live_server_url}/app/workbench")
    page.wait_for_selector(".app-title")

    requests_response = page.request.get(f"{live_server_url}/api/v1/requests")
    assert requests_response.status == 200
    assert requests_response.json()["ok"] is True

    healthz = page.request.get(f"{live_server_url}/healthz")
    assert healthz.status == 200
    assert healthz.json() == {"ok": True, "result": "ok"}

    readiness = page.request.get(f"{live_server_url}/readiness")
    assert readiness.status == 200


def test_legacy_pages_still_served_alongside_app(
    page: Page, live_server_url: str
) -> None:
    """Legacy /index and /settings remain available during the migration window."""
    _require_dist()

    page.goto(f"{live_server_url}/app/workbench")
    page.wait_for_selector(".app-title")

    page.goto(f"{live_server_url}/index")
    assert page.title().startswith("MiGuOrca")
    assert page.locator("text=Stage 13 订阅方案工作台").count() >= 1

    page.goto(f"{live_server_url}/settings")
    assert page.title() == "MiGuOrca Settings"


def test_browser_availability_sanity() -> None:
    """Guard: this file must only run when Chromium is actually available."""
    assert is_browser_available(), "browser suite ran without a Chromium binary"
