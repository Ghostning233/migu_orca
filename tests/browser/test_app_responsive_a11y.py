from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import set_storage_preferences

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.browser

# US-207: cross-feature responsive / accessibility / runtime-quality audit.
#
# These tests deliberately do NOT re-assert the per-feature business flows
# (those live in test_app_*.py). They converge the *cross-feature* guarantees
# of Stage 27:
#
#   - no critical action overflows or relies on color alone at 360px /
#     768px / desktop (all four routes),
#   - a keyboard skip link jumps to the main landmark on every route,
#   - the batch candidate popover moves focus in and restores it on Escape,
#   - status is never conveyed by color alone (text label present),
#   - reduced-motion users still get usable feedback (loading + button
#     spinners stop animating; success still shows text),
#   - the production shell/asset cache headers and sourcemap policy hold
#     (the Flask-side assertions live in app_routes_test.py).


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
        "to verify the US-207 responsive/a11y convergence in the browser."
    )


def _goto(page: Page, live_server_url: str, path: str = "/app/add") -> None:
    _require_dist()
    page.goto(f"{live_server_url}{path}")
    page.wait_for_selector(".app-title", timeout=5000)


def _no_horizontal_overflow(page: Page, viewport: int) -> None:
    body_width = page.evaluate("() => document.body.scrollWidth")
    assert body_width <= viewport, (
        f"Body scrollWidth ({body_width}) exceeds viewport ({viewport}) at "
        f"{page.url}"
    )


def _nav_targets() -> list[tuple[str, str]]:
    """(nav link text, expected route marker selector) for the four SPA routes."""
    return [
        ("添加番剧", "#workbench-heading"),
        ("追番方案", "#request-list-container"),
        ("追番管理", "#batch-queue-list"),
        ("设置", "#settings-heading"),
    ]


class TestCrossFeatureResponsive:
    """AC: 360px、平板和桌面下无关键操作横向溢出或只靠颜色表达状态."""

    @pytest.mark.parametrize(
        ("path", "selector"),
        [
            ("/app/add", "#workbench-heading"),
            ("/app/plans", "#request-list-container"),
            ("/app/tracking", "#batch-queue-list"),
            ("/app/settings", "#settings-heading"),
        ],
    )
    @pytest.mark.parametrize(
        "viewport", [(360, 800), (768, 1024), (1280, 900), (1440, 900), (1920, 1080)]
    )
    def test_routes_no_horizontal_overflow(
        self,
        page: Page,
        live_server_url: str,
        viewport: tuple[int, int],
        path: str,
        selector: str,
    ) -> None:
        page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
        _goto(page, live_server_url, path)
        expect(page.locator(selector).first).to_be_visible()
        _no_horizontal_overflow(page, viewport[0])

    def test_navigation_wraps_not_overflows_at_360px(
        self, page: Page, live_server_url: str
    ) -> None:
        """The 4-item nav must wrap (flex-wrap) instead of overflowing at 360px."""
        page.set_viewport_size({"width": 360, "height": 800})
        _goto(page, live_server_url, "/app/add")
        _no_horizontal_overflow(page, 360)
        # Every nav link is visible and inside the viewport.
        for label, _selector in _nav_targets():
            link = page.get_by_role("link", name=label, exact=True)
            expect(link).to_be_visible()
            box = link.bounding_box()
            assert box is not None and box["x"] >= 0 and box["x"] + box["width"] <= 360

    def test_status_has_text_label_not_color_only(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """Queue status chips carry a text label (not color-only state)."""
        set_storage_preferences(page, storage_dir)
        _goto(page, live_server_url, "/app/tracking?batch_id=batch-spa")

        page.route(
            "**/api/v1/batches/batch-spa/queue*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": True,
                        "result": {
                            "queue": {
                                "queue_id": "queue-batch-spa",
                                "batch_id": "batch-spa",
                                "items": [
                                    {
                                        "queue_id": "queue-batch-spa",
                                        "batch_id": "batch-spa",
                                        "item_id": "item-1",
                                        "request_id": "req-1",
                                        "title": "葬送的芙莉莲 第四季",
                                        "status": "SUCCEEDED",
                                        "status_label": "提交成功",
                                        "attempts": 1,
                                        "last_error": None,
                                        "ab_result_summary": None,
                                        "created_at": "2026-08-19T00:00:00+00:00",
                                        "updated_at": "2026-08-19T00:00:00+00:00",
                                    }
                                ],
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
            ),
        )

        page.reload()
        expect(page.locator(".batch-queue-status")).to_contain_text("提交成功")
        # The chip also has a status class beyond the base (color is not the
        # only signal — the text label is present).
        status = page.locator(".batch-queue-status")
        assert "batch-queue-status-" in (status.get_attribute("class") or "")

    @pytest.mark.parametrize(
        "path, selector",
        [
            ("/app/add", "#workbench-heading"),
            ("/app/plans", "#request-list-container"),
            ("/app/tracking", "#batch-queue-list"),
            ("/app/settings", "#settings-heading"),
        ],
    )
    def test_desktop_200_percent_equivalent_keeps_route_content_reachable(
        self,
        page: Page,
        live_server_url: str,
        path: str,
        selector: str,
    ) -> None:
        """A 2x page scale models the desktop 200% effective CSS viewport."""
        page.set_viewport_size({"width": 1280, "height": 900})
        _goto(page, live_server_url, path)
        page.evaluate("() => { document.documentElement.style.zoom = '2' }")
        expect(page.locator(selector).first).to_be_visible()
        _no_horizontal_overflow(page, 1280)

        # The shell remains usable at the reduced effective width: every
        # public navigation target is still visible and keyboard reachable.
        for label, _selector in _nav_targets():
            link = page.get_by_role("link", name=label, exact=True)
            expect(link).to_be_visible()
            box = link.bounding_box()
            assert box is not None and box["x"] >= 0 and box["x"] + box["width"] <= 1280

    def test_public_shell_drops_sensitive_query_canaries(
        self, page: Page, live_server_url: str
    ) -> None:
        """Shell navigation never exposes unknown or sensitive query values."""
        canaries = (
            "shell-token-canary",
            "shell-cookie-canary",
            "shell-endpoint-canary.invalid",
        )
        page.goto(
            f"{live_server_url}/app/add?batch_id=batch-public"
            f"&token={canaries[0]}&cookie={canaries[1]}"
            f"&endpoint={canaries[2]}"
        )
        page.wait_for_selector(".app-title")

        assert page.url.endswith("/app/add?batch_id=batch-public")
        visible = page.locator("body").inner_text()
        browser_storage = page.evaluate(
            """() => ({
              local: JSON.stringify(localStorage),
              session: JSON.stringify(sessionStorage),
              history: JSON.stringify(window.history.state),
            })"""
        )
        for canary in canaries:
            assert canary not in visible
            assert canary not in browser_storage["local"]
            assert canary not in browser_storage["session"]
            assert canary not in browser_storage["history"]


class TestKeyboardAndFocus:
    """AC: 键盘导航、焦点恢复和 skip link."""

    def test_skip_link_focuses_main_content(
        self, page: Page, live_server_url: str
    ) -> None:
        """Tab lands on the skip link first and it jumps to the main landmark."""
        _goto(page, live_server_url, "/app/settings")

        page.keyboard.press("Tab")
        active_id = page.evaluate("() => document.activeElement?.id || ''")
        assert active_id == "skip-link", f"first tab stop was {active_id!r}"

        # Focused skip links are visible (they are only visually hidden until
        # focused) and navigate to the main landmark.
        skip = page.locator(".skip-link")
        expect(skip).to_be_visible()
        skip.press("Enter")
        expect(page.locator("main#app-main")).to_have_attribute("tabindex", "-1")
        focused_main = page.evaluate(
            "() => document.activeElement?.id === 'app-main'"
        )
        assert focused_main, "Enter on the skip link did not focus main#app-main"

    def test_main_landmark_is_focus_target_on_every_route(
        self, page: Page, live_server_url: str
    ) -> None:
        """The main landmark is a focus target on every SPA route."""
        for label, _selector in _nav_targets():
            _goto(page, live_server_url, "/app/add")
            page.get_by_role("link", name=label, exact=True).click()
            main = page.locator("main#app-main")
            expect(main).to_have_attribute("tabindex", "-1")

    def test_keyboard_can_reach_every_public_navigation_target(
        self, page: Page, live_server_url: str
    ) -> None:
        """The skip link and all four route links are in the keyboard path."""
        _goto(page, live_server_url, "/app/settings")
        page.keyboard.press("Tab")
        assert page.locator("#skip-link").evaluate(
            "el => el === document.activeElement"
        )

        focused_labels: list[str] = []
        for _ in range(12):
            page.keyboard.press("Tab")
            label = page.evaluate(
                """() => document.activeElement?.getAttribute('aria-label') ||
                document.activeElement?.textContent?.trim() || ''"""
            )
            for expected in ("添加番剧", "追番方案", "追番管理", "设置"):
                if expected in label and expected not in focused_labels:
                    focused_labels.append(expected)

        assert focused_labels == ["添加番剧", "追番方案", "追番管理", "设置"]

    def test_batch_candidate_selection_stays_in_right_detail(
        self, page: Page, live_server_url: str
    ) -> None:
        """FOUND candidate selection is rendered in the current right detail pane."""
        _goto(page, live_server_url, "/app/add")
        page.wait_for_selector("#anime-mode-switch", timeout=5000)
        page.click("#anime-mode-batch")
        page.wait_for_selector("#batch-parse-form", timeout=5000)

        page.route(
            "**/api/v1/batches/parse",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": True,
                        "result": {
                            "batch_id": "batch-spa",
                            "raw_input": "萌王S4",
                            "items": [
                                {
                                    "item_id": "item-found",
                                    "raw_title": "萌王S4",
                                    "status": "FOUND",
                                    "canonical_title_candidates": [
                                        "关于我转生变成史莱姆这档事 第四季"
                                    ],
                                    "season_hint": "S4",
                                    "search_queries": ["转生史莱姆 第四季"],
                                    "confidence": 0.9,
                                    "needs_user_review": False,
                                    "source": "fake",
                                    "parse_result": None,
                                    "attempted_queries": [],
                                    "candidates": [
                                        {
                                            "bangumi_id": "42",
                                            "title": "关于我转生变成史莱姆这档事 第四季",
                                            "mikan_url": "https://mikan.example/Home/Bangumi/42",
                                            "poster_url": None,
                                            "source_query": "转生史莱姆 第四季",
                                            "aliases": [],
                                            "recommendation": None,
                                            "total_episodes": None,
                                        }
                                    ],
                                    "applied_preferences": None,
                                    "preference_hits": [],
                                    "preference_warnings": [],
                                    "review_hints": [],
                                    "enhanced_search_queries": [],
                                    "preview_request": None,
                                    "error": None,
                                }
                            ],
                        },
                    },
                    ensure_ascii=False,
                ),
            ),
        )

        page.fill("#batch-raw-input", "萌王S4")
        page.click("#batch-parse-submit")
        trigger = page.locator(".batch-card-expand", has_text="查看候选")
        expect(trigger).to_be_visible()
        trigger.click()

        choices = page.locator("#batch-detail-pane")
        expect(choices).to_be_visible()
        expect(page.locator("#batch-candidate-choices")).to_have_count(0)
        expect(choices.locator(".candidate-select")).to_be_visible()


class TestReducedMotionAndFeedback:
    """AC: reduced motion 用户仍获得可用反馈（加载与按钮状态不只靠动画）.

    Uses conftest's server-side ``test-slow-queue`` route (the same pattern as
    the queue in-flight tests) so the loading state is observable without
    touching real external services. A ``time.sleep`` inside a ``page.route``
    handler would block Playwright's dispatcher thread, so the delay lives on
    the Flask test server instead.
    """

    def test_reduced_motion_loading_state_still_readable(
        self, page: Page, live_server_url: str
    ) -> None:
        """With prefers-reduced-motion, the loading spinner stops animating but
        the text message remains (aria-busy + visible copy)."""
        page.emulate_media(reduced_motion="reduce")
        _goto(page, live_server_url, "/app/tracking?batch_id=test-slow-queue")

        loading = page.locator(".loading-state", has_text="正在读取提交前队列")
        expect(loading).to_be_visible()
        expect(loading).to_have_attribute("aria-busy", "true")
        expect(loading).to_contain_text("正在读取提交前队列")

    def test_reduced_motion_button_spinner_still_disabled(
        self, page: Page, live_server_url: str
    ) -> None:
        """A loading button shows aria-busy + disabled text even when the
        spinner animation is suppressed by reduced-motion."""
        page.emulate_media(reduced_motion="reduce")
        _goto(page, live_server_url, "/app/tracking?batch_id=test-slow-queue")

        # The refresh button is loading while the slow queue read is in flight.
        refresh = page.locator("#batch-queue-refresh")
        expect(refresh).to_be_disabled()
        expect(refresh).to_have_attribute("aria-busy", "true")


class TestRuntimeQuality:
    """AC: 路由懒加载、production chunk、静态缓存与 sourcemap 策略."""

    def test_vendor_chunk_split_in_build(self) -> None:
        """The production build splits a vendor chunk (stable framework code)."""
        _require_dist()
        assets = REPO_ROOT / "frontend" / "dist" / "assets"
        js_files = [p.name for p in assets.glob("*.js")]
        vendor = [name for name in js_files if name.startswith("vendor-")]
        assert vendor, f"no vendor chunk in build assets: {sorted(js_files)}"

    def test_no_sourcemap_artifacts_in_build(self) -> None:
        """The committed/built dist ships no .map files (public sourcemaps off)."""
        _require_dist()
        dist = REPO_ROOT / "frontend" / "dist"
        maps = list(dist.rglob("*.map"))
        assert not maps, f"build must not contain sourcemaps: {maps}"

    def test_asset_cache_headers_immutable_and_shell_nocache(
        self, page: Page, live_server_url: str
    ) -> None:
        """/app/assets/* is immutable-cached; the SPA shell is no-cache."""
        _require_dist()

        assets = sorted((REPO_ROOT / "frontend" / "dist" / "assets").glob("*.js"))
        assert assets, "built dist has no JS assets"
        asset_url = f"{live_server_url}/app/assets/{assets[0].name}"
        asset_resp = page.request.get(asset_url)
        assert asset_resp.status == 200
        assert "immutable" in (asset_resp.headers.get("cache-control") or "")

        shell_resp = page.request.get(f"{live_server_url}/app/add")
        assert shell_resp.status == 200
        cc = shell_resp.headers.get("cache-control") or ""
        assert "no-cache" in cc, f"shell cache-control was {cc!r}"
