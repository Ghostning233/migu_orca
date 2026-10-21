from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import set_storage_preferences
from tests.browser.saved_tracking_fixtures import _status_groups_for
from tests.browser.screen_support import wait_for_screen_scroll
from tests.browser.test_app_batch_workbench import (
    _batch_item,
    _preview_request,
    _route_parse,
)

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
        # US-316: 我的追番 mounts the formal tracking screen, not the retired queue.
        ("我的追番", "#tracking-overview"),
        ("设置", "#settings-heading"),
    ]


def _mock_tracking_list(page: Page, items: list[dict[str, Any]]) -> None:
    """Serve the generated tracking list projection (US-316 viewport/a11y work)."""
    def handler(route: Any, request: Any) -> None:
        if request.method != "GET" or "/api/v1/tracking/items" not in request.url:
            route.continue_()
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
                            # Self-consistent with status_groups below: the two
                            # rows are one 追番中 and one 需处理.
                            "total": len(items), "pending": 0, "processing": 0,
                            "active": 1, "inactive": 0, "needs_attention": 1,
                            "unreadable": 0,
                        },
                        # Issue #224 A7: the four cards render from this
                        # server-owned metadata, never from a client label table.
                        "status_groups": [
                            {"group": "PENDING", "label": "待处理", "count": 0, "has_overview_card": True},
                            {"group": "PROCESSING", "label": "处理中", "count": 0, "has_overview_card": False},
                            {"group": "ACTIVE", "label": "追番中", "count": 1, "has_overview_card": True},
                            {"group": "ATTENTION", "label": "需处理", "count": 1, "has_overview_card": True},
                            {"group": "INACTIVE", "label": "已停用", "count": 0, "has_overview_card": True},
                        ],
                        "warnings": [],
                    },
                },
                ensure_ascii=False,
            ),
        )

    page.route("**/api/v1/tracking/items*", handler)


def _tracking_item(tracking_id: str, title: str, status: str, status_label: str,
                   status_group: str) -> dict[str, Any]:
    return {
        "tracking_id": tracking_id,
        "request_id": f"request-{tracking_id}",
        "title": title,
        "season": 1,
        "subtitle_group": "喵萌奶茶屋",
        "poster_path": None,
        "status": status,
        "status_label": status_label,
        "status_group": status_group,
        "available_actions": [],
        "valid_resource_count": 2,
        "updated_episode": None,
        "updated_episode_status": "NOT_IMPLEMENTED",
        "total_episodes": 28,
        "revision": 1,
        "updated_at": "2026-09-13T00:00:00+00:00",
    }


class TestCrossFeatureResponsive:
    """AC: 360px、平板和桌面下无关键操作横向溢出或只靠颜色表达状态."""

    @pytest.mark.parametrize(
        ("path", "selector"),
        [
            ("/app/add", "#workbench-heading"),
            ("/app/tracking", "#tracking-overview"),
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
        """Tracking status is carried by a text label, never by color alone."""
        set_storage_preferences(page, storage_dir)
        _mock_tracking_list(page, [
            _tracking_item("tracking-active", "葬送的芙莉莲", "ACTIVE", "追番中", "ACTIVE"),
            _tracking_item("tracking-failed", "咒术回战", "SUBMIT_FAILED", "提交失败", "ATTENTION"),
        ])
        _goto(page, live_server_url, "/app/tracking")

        rows = page.locator(".tracking-list-item")
        expect(rows).to_have_count(2)
        expect(rows.nth(0)).to_contain_text("追番中")
        expect(rows.nth(1)).to_contain_text("提交失败")
        # The status overview states every card category in text as well.
        # Issue #224: four fixed categories; PROCESSING stays a per-row state.
        overview = page.locator("#tracking-status-heading").locator("..")
        for label in ("待处理", "追番中", "已停用", "需处理"):
            expect(overview).to_contain_text(label)
        # The decorative background layer is not a control and carries no text:
        # the text label is the state signal, not the colour.
        background = page.locator(".tracking-row-background").first
        assert background.inner_text() == ""
        assert background.evaluate("el => getComputedStyle(el).pointerEvents") == "none"
        assert page.locator('input[type="checkbox"]').count() == 0
        # Selection is announced through aria-current, not only through color.
        expect(page.locator("#tracking-list-container")).to_have_attribute("aria-label", "追番记录列表")

    @pytest.mark.parametrize(
        "path, selector",
        [
            ("/app/add", "#workbench-heading"),
            ("/app/tracking", "#tracking-overview"),
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

    def test_skip_link_focuses_main_content(
        self, page: Page, live_server_url: str
    ) -> None:
        """Tab lands on the skip link first and it jumps to the main landmark."""
        _goto(page, live_server_url, "/app/settings")

        page.keyboard.press("Tab")
        expect(page.locator("#skip-link")).to_be_focused()

        # Focused skip links are visible (they are only visually hidden until
        # focused) and navigate to the main landmark.
        skip = page.locator(".skip-link")
        expect(skip).to_be_visible()
        skip.press("Enter")
        expect(page.locator("main#app-main")).to_have_attribute("tabindex", "-1")
        expect(page.locator("main#app-main")).to_be_focused()

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
        expect(page.locator("#skip-link")).to_be_focused()

        # This loop reads document.activeElement after each synchronous Tab key
        # press (the browser updates focus as part of that key event), so a
        # per-step read is deterministic here; only the focus moves that are
        # scheduled after a click/navigation need polling assertions.
        focused_labels: list[str] = []
        for _ in range(12):
            page.keyboard.press("Tab")
            label = page.evaluate(
                """() => document.activeElement?.getAttribute('aria-label') ||
                document.activeElement?.textContent?.trim() || ''"""
            )
            for expected in ("添加番剧", "我的追番", "设置"):
                if expected in label and expected not in focused_labels:
                    focused_labels.append(expected)

        assert focused_labels == ["添加番剧", "我的追番", "设置"]

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
        # #145：卡片本体是查看入口（不再有独立的「查看候选」按钮）。
        trigger = page.locator(".batch-draft-card").first
        expect(trigger).to_be_visible()
        trigger.click()

        choices = page.locator("#batch-detail-pane")
        expect(choices).to_be_visible()
        expect(page.locator("#batch-candidate-choices")).to_have_count(0)
        expect(choices.locator(".candidate-select")).to_be_visible()

    def _enter_batch_draft(self, page: Page, live_server_url: str, storage_dir: Path) -> None:
        """Enter the batch draft workbench with one real DRAFT card."""
        _route_parse(
            page,
            [
                _batch_item(
                    "item-1",
                    "番剧一",
                    status="DRAFT",
                    canonical_title="番剧一 第一季",
                    preview_request=_preview_request("番剧一", "req-a11y-1"),
                )
            ],
        )
        set_storage_preferences(page, storage_dir)
        _goto(page, live_server_url, "/app/add")
        page.wait_for_selector("#anime-mode-switch", timeout=5000)
        page.click("#anime-mode-batch")
        page.wait_for_selector("#batch-parse-form", timeout=5000)
        page.set_viewport_size({"width": 1440, "height": 900})
        page.fill("#batch-raw-input", "番剧一")
        page.click("#batch-parse-submit")
        expect(page.locator(".batch-draft-card")).to_have_count(1)
        wait_for_screen_scroll(page)

    def test_title_search_popover_keeps_a_visible_focus_indicator(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """缺陷回归：浮层输入框去掉 outline 后必须仍有等价可见的焦点指示。

        断言的是「聚焦后浮层本身出现可见变化」，因此旧实现（只写 `outline: none`、
        不给任何替代指示）会失败。
        """
        self._enter_batch_draft(page, live_server_url, storage_dir)

        page.click("#batch-review-search-toggle")
        popover = page.locator("#batch-review-search-popover")
        expect(popover).to_be_visible()

        style = """() => {
            const popover = document.querySelector('#batch-review-search-popover')
            const input = document.querySelector('#batch-review-search')
            const computed = getComputedStyle(popover)
            return {
                inputFocused: document.activeElement === input,
                borderColor: computed.borderColor,
                boxShadow: computed.boxShadow,
                inputOutlineWidth: getComputedStyle(input).outlineWidth,
            }
        }"""

        page.evaluate("() => { const input = document.querySelector('#batch-review-search'); if (input) input.blur() }")
        blurred = page.evaluate(style)
        expect(popover).to_be_visible()
        page.locator("#batch-review-search").focus()
        focused = page.evaluate(style)

        assert focused["inputFocused"] is True, focused
        # 输入框自身不画内框，但容器必须给出可见的焦点指示（边框或焦点环变化）。
        assert (focused["borderColor"], focused["boxShadow"]) != (
            blurred["borderColor"],
            blurred["boxShadow"],
        ), (blurred, focused)
        assert focused["boxShadow"] != "none", focused

    def test_batch_draft_editor_keeps_a_resolvable_accessible_name(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """缺陷回归：批量编辑器视觉隐藏面板标题后，aria-labelledby 不得指向
        display:none 的元素，编辑区域必须仍有可解析的可访问名称。"""
        self._enter_batch_draft(page, live_server_url, storage_dir)
        page.locator(".batch-draft-card").first.click()
        editor = page.locator(".batch-draft-editor")
        expect(editor).to_be_visible()
        expect(editor).to_contain_text("字幕与筛选")

        labelled = page.evaluate(
            """() => {
                const editor = document.querySelector('.batch-draft-editor')
                const id = editor.getAttribute('aria-labelledby')
                const heading = id ? document.getElementById(id) : null
                return {
                    id,
                    exists: Boolean(heading),
                    text: heading ? heading.textContent.trim() : '',
                    display: heading ? getComputedStyle(heading).display : null,
                    visibility: heading ? getComputedStyle(heading).visibility : null,
                    inAccessibilityTree: Boolean(heading) && heading.closest('[aria-hidden="true"]') === null,
                }
            }"""
        )
        assert labelled["id"], labelled
        assert labelled["exists"] is True, labelled
        assert labelled["text"], labelled
        assert labelled["display"] != "none", labelled
        assert labelled["visibility"] != "hidden", labelled
        assert labelled["inAccessibilityTree"] is True, labelled


class TestReducedMotionAndFeedback:
    """AC: reduced motion 用户仍获得可用反馈（加载与按钮状态不只靠动画）.

    The tracking list read is held open by the route handler itself, so the
    loading state is observable without a server-side delay route (a
    ``time.sleep`` inside a route handler would block Playwright's dispatcher
    thread and hide the state again).  Nothing external is contacted.
    """

    def _hold_tracking_list(self, page: Page) -> list[Any]:
        """Hold the tracking list request open; return the pending routes."""
        held: list[Any] = []

        def handler(route: Any, _request: Any) -> None:
            held.append(route)

        page.route("**/api/v1/tracking/items*", handler)
        return held

    def test_reduced_motion_loading_state_still_readable(
        self, page: Page, live_server_url: str
    ) -> None:
        """With prefers-reduced-motion, the loading spinner stops animating but
        the text message remains (aria-busy + visible copy)."""
        _require_dist()
        page.emulate_media(reduced_motion="reduce")
        held = self._hold_tracking_list(page)

        page.goto(f"{live_server_url}/app/tracking")
        loading = page.locator(".loading-state", has_text="正在读取追番列表")
        expect(loading).to_be_visible()
        expect(loading).to_have_attribute("aria-busy", "true")
        expect(loading).to_contain_text("正在读取追番列表")
        # The spinner is suppressed, not the state: the copy is the signal.
        assert page.evaluate(
            "() => getComputedStyle(document.querySelector('.loading-spinner')).animationName"
        ) == "none"

        assert held, "the tracking list request was never issued"
        held[0].fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"ok": True, "result": {"items": [], "summary": {}, "status_groups": _status_groups_for([]), "warnings": []}}),
        )
        page.wait_for_selector(".empty-state")

    def test_reduced_motion_sync_button_spinner_still_disabled(
        self, page: Page, live_server_url: str
    ) -> None:
        """A loading button shows aria-busy + disabled text even when the
        spinner animation is suppressed by reduced-motion (#225 retires the
        refresh entry; the sync button is the remaining loading control)."""
        _require_dist()
        page.emulate_media(reduced_motion="reduce")
        held: list[Any] = []

        def handler(route: Any, request: Any) -> None:
            path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
            if request.method == "POST" and path == "/tracking/sync":
                held.append(route)
                return
            if request.method == "GET" and path == "/settings/autobangumi":
                route.fulfill(json={"ok": True, "result": {
                    "configured": True, "credential_present": True,
                    "connection_ref": "11111111-1111-4111-8111-111111111111",
                    "configuration_revision": 3, "connection_status": "CONFIGURED",
                }})
                return
            if request.method == "POST" and path == "/settings/autobangumi/probe":
                route.fulfill(json={"ok": True, "result": {
                    "probe_status": "VERIFIED", "version": "3.1.18", "adapter": "legacy_3_1",
                    "subscription_list": "SUPPORTED", "subscription_detail": "SUPPORTED",
                    "subscription_submit": "SUPPORTED", "subscription_modify": "SUPPORTED",
                    "subscription_enable": "SUPPORTED", "subscription_disable": "SUPPORTED",
                    "subscription_delete": "SUPPORTED", "rss_list": "SUPPORTED",
                    "rss_modify": "SUPPORTED", "rss_enable": "SUPPORTED",
                    "rss_disable": "SUPPORTED", "rss_delete": "SUPPORTED",
                    "rss_refresh": "SUPPORTED", "external_verify": "SUPPORTED",
                    "checked_at": None, "safe_message": "ok",
                }})
                return
            if request.method == "GET" and path == "/tracking/items":
                route.fulfill(json={"ok": True, "result": {
                    "items": [], "summary": {"total": 0},
                    "status_groups": _status_groups_for([]), "warnings": [],
                }})
                return
            route.continue_()

        page.route("**/api/v1/**", handler)
        page.goto(f"{live_server_url}/app/tracking")
        page.wait_for_selector("#tracking-sync")
        page.locator("#tracking-sync").click()
        page.locator(".confirm-dialog .danger-button, .confirm-dialog .primary-button").last.click()
        page.wait_for_timeout(100)

        sync = page.locator("#tracking-sync")
        expect(sync).to_be_disabled()
        expect(sync).to_have_attribute("aria-busy", "true")
        assert sync.inner_text().strip() != ""
        # The shared reduced-motion rule zeroes the spinner's duration; the
        # loading text stays the signal.
        assert page.evaluate(
            "() => getComputedStyle(document.querySelector('.base-button-spinner')).animationDuration"
        ) in {"0s", "0ms"}

        assert held, "the sync request was never issued"
        held[0].fulfill(json={"ok": True, "result": {
            "sync_status": "COMPLETE", "checked_at": "2026-10-21T00:00:00Z",
            "capabilities": {
                "probe_status": "VERIFIED", "version": "3.1.18", "adapter": "legacy_3_1",
                "subscription_list": "SUPPORTED", "subscription_detail": "SUPPORTED",
                "subscription_submit": "SUPPORTED", "subscription_modify": "SUPPORTED",
                "subscription_enable": "SUPPORTED", "subscription_disable": "SUPPORTED",
                "subscription_delete": "SUPPORTED", "rss_list": "SUPPORTED",
                "rss_modify": "SUPPORTED", "rss_enable": "SUPPORTED",
                "rss_disable": "SUPPORTED", "rss_delete": "SUPPORTED",
                "rss_refresh": "SUPPORTED", "external_verify": "SUPPORTED",
                "checked_at": None, "safe_message": "ok",
            },
            "summary": {"checked": 0, "created": 0, "updated": 0, "unchanged": 0,
                        "ignored": 0, "failed": 0, "unreadable": 0},
            "warnings": [], "items": [],
        }})
        expect(sync).to_be_enabled()


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
