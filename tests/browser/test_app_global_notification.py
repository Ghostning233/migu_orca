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
        "to verify the Stage 42 floating notification in the browser."
    )


def _goto_workbench(page: Page, live_server_url: str) -> None:
    _require_dist()
    page.goto(f"{live_server_url}/app/add")
    page.wait_for_selector("#mikan-candidate-search-form", timeout=5000)


def _search(page: Page, query: str = "芙莉莲") -> None:
    page.fill("#mikan-candidate-query", query)
    page.click("#mikan-candidate-search-submit")


def _candidate_result_json(query: str, candidates: list[dict[str, Any]]) -> str:
    return json.dumps(
        {
            "ok": True,
            "result": {
                "query": query,
                "status": "FOUND" if candidates else "EMPTY",
                "parse_result": {
                    "normalized_title": query,
                    "base_title": query,
                    "season": {"number": None, "raw": None, "normalized": None, "source": "none"},
                    "season_number": None,
                    "season_hint": None,
                    "query_plan": [{"query": query, "source": "rule", "priority": 1}],
                    "search_queries": [query],
                    "source": "rule",
                    "confidence": 0.8,
                    "needs_user_review": False,
                    "review_hints": [],
                    "raw_title": query,
                },
                "attempted_queries": [{"query": query, "source": "rule", "priority": 1}],
                "candidates": candidates,
                "error": None,
            },
        },
        ensure_ascii=False,
    )


def _one_candidate_json(query: str = "芙莉莲") -> str:
    return _candidate_result_json(
        query,
        [
            {
                "bangumi_id": "2353",
                "title": "葬送的芙莉莲",
                "mikan_url": "https://mikan.example/Home/Bangumi/2353",
                "poster_url": None,
                "source_query": query,
                "aliases": [],
            }
        ],
    )


def _candidate_failure_json(**detail: Any) -> str:
    """An upstream failure envelope; `detail` lands in the raw (unsafe) payload."""
    return json.dumps(
        {
            "ok": False,
            "error_type": "mikan_http_failed",
            "error_message": "MiKan HTTP 请求失败",
            "error_data": {"failed_step": "mikan_search", "details": detail},
        },
        ensure_ascii=False,
    )


def _assert_same_box(before: dict[str, Any], after: dict[str, Any], tolerance: float = 0.5) -> None:
    for key in ("x", "y", "width", "height"):
        assert abs(float(after[key]) - float(before[key])) <= tolerance, (
            f"{key} moved when the toast left: {before[key]} -> {after[key]}"
        )


class TestAppGlobalNotificationFloating:
    """AC (US-346): 提示固定悬浮、不参与正文布局、不横向溢出."""

    def test_toast_is_fixed_and_leaves_the_page_layout_alone(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        page.set_viewport_size({"width": 1280, "height": 900})
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(
                status=200, content_type="application/json", body=_one_candidate_json()
            ),
        )
        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)
        _search(page)

        toast = page.locator(".global-notification")
        expect(toast).to_contain_text("候选搜索完成", timeout=5000)
        expect(toast).to_have_attribute("role", "status")
        expect(toast).to_have_attribute("aria-live", "polite")
        expect(toast).to_have_attribute("aria-atomic", "true")

        assert page.evaluate(
            "() => getComputedStyle(document.querySelector('.global-notification')).position"
        ) == "fixed"

        header = page.locator(".app-header").bounding_box()
        viewport = page.viewport_size
        assert header is not None and viewport is not None
        box = toast.bounding_box()
        assert box is not None
        # Floats under the shell header, fully inside the viewport.
        assert box["y"] >= header["y"] + header["height"] - 1
        assert box["x"] >= 0
        assert box["x"] + box["width"] <= viewport["width"] + 1
        assert page.evaluate(
            "() => document.documentElement.scrollWidth <= window.innerWidth + 1"
        )

        # A toast inside the document flow would shift the page up by its own
        # height when it leaves; a fixed layer must leave geometry untouched.
        anchor = page.locator("#mikan-candidate-search-result").bounding_box()
        assert anchor is not None
        close = page.locator(".global-notification-close")
        close.focus()
        expect(close).to_be_focused()
        page.keyboard.press("Enter")
        expect(toast).to_have_count(0)

        after = page.locator("#mikan-candidate-search-result").bounding_box()
        assert after is not None
        _assert_same_box(anchor, after)

    def test_mouse_click_on_the_close_control_dismisses_the_toast(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        page.set_viewport_size({"width": 1280, "height": 900})
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(
                status=200, content_type="application/json", body=_one_candidate_json()
            ),
        )
        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)
        _search(page)

        toast = page.locator(".global-notification")
        expect(toast).to_contain_text("候选搜索完成", timeout=5000)

        # The floating layer is click-through, so the close control has to opt
        # back in; without that a real mouse click would land on whatever the
        # toast happens to cover instead of dismissing it.
        assert page.evaluate(
            "() => getComputedStyle(document.querySelector('.global-notification-close')).pointerEvents"
        ) == "auto"
        assert page.evaluate(
            """() => {
                const toast = document.querySelector('.global-notification')
                const box = toast.getBoundingClientRect()
                const hit = document.elementFromPoint(box.left + 6, box.bottom - 6)
                return hit !== null && !toast.contains(hit)
            }"""
        )

        page.locator(".global-notification-close").click()
        expect(toast).to_have_count(0)
        # Dismissing the summary leaves the page it summarised fully usable.
        expect(page.locator(".candidate-card")).to_have_count(1)

    @pytest.mark.parametrize("width", [1280, 1440, 1920])
    def test_toast_never_causes_horizontal_overflow(
        self, page: Page, live_server_url: str, storage_dir: Path, width: int
    ) -> None:
        page.set_viewport_size({"width": width, "height": 900})
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_candidate_result_json("芙莉莲", []),
            ),
        )
        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)
        _search(page)

        toast = page.locator(".global-notification")
        expect(toast).to_contain_text("未找到候选合集", timeout=5000)

        assert page.evaluate(
            "() => document.documentElement.scrollWidth <= window.innerWidth + 1"
        )
        assert page.evaluate("() => document.body.scrollWidth <= window.innerWidth + 1")
        box = toast.bounding_box()
        assert box is not None
        assert box["x"] + box["width"] <= width + 1


class TestAppGlobalNotificationRecovery:
    """AC (US-346): 关键就地错误/重试不被悬浮提示取代或遮挡."""

    @staticmethod
    def _flaky_candidates_route(page: Page) -> dict[str, bool]:
        state = {"fail": True}

        def _handler(route: Any, request: Any) -> None:
            if state["fail"]:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=_candidate_failure_json(status_code=503),
                )
                return
            route.fulfill(
                status=200, content_type="application/json", body=_one_candidate_json()
            )

        page.route("**/api/v1/mikan/candidates", _handler)
        return state

    def test_toast_never_blocks_the_in_place_retry(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        page.set_viewport_size({"width": 1280, "height": 900})
        candidates = self._flaky_candidates_route(page)
        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)
        _search(page)

        toast = page.locator(".global-notification")
        expect(toast).to_contain_text("候选搜索失败", timeout=5000)
        expect(toast).to_have_attribute("role", "alert")
        expect(toast).to_have_attribute("aria-live", "assertive")
        # The floating layer is click-through, so no page control can be
        # swallowed while a summary happens to sit on top of it.
        assert page.evaluate(
            "() => getComputedStyle(document.querySelector('.global-notification')).pointerEvents"
        ) == "none"

        in_place = page.locator("#mikan-candidate-search-result .error-state")
        expect(in_place).to_contain_text("候选搜索失败")
        retry = in_place.locator("button:has-text('重试')")
        expect(retry).to_be_enabled()

        # Clicking the in-place retry while the error summary is still up must
        # reach the page, and the newer result must replace the stale summary.
        candidates["fail"] = False
        retry.click()
        expect(page.locator(".candidate-card")).to_have_count(1)
        expect(toast).to_contain_text("候选搜索完成", timeout=5000)
        assert "候选搜索失败" not in toast.inner_text()

    def test_keyboard_close_keeps_the_in_place_error_and_retry(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        page.set_viewport_size({"width": 1280, "height": 900})
        candidates = self._flaky_candidates_route(page)
        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)
        page.fill("#mikan-candidate-query", "芙莉莲")

        # Park focus on an unrelated shell control and start the search without
        # touching it, so "did the toast steal focus" is the only variable.
        nav_link = page.locator(".top-nav .nav-link").first
        nav_link.focus()
        focused_before = page.evaluate("() => document.activeElement?.outerHTML ?? ''")
        assert "nav-link" in focused_before

        page.evaluate(
            "() => document.querySelector('#mikan-candidate-search-form').requestSubmit()"
        )
        toast = page.locator(".global-notification")
        expect(toast).to_contain_text("候选搜索失败", timeout=5000)
        assert page.evaluate("() => document.activeElement?.outerHTML ?? ''") == focused_before

        in_place = page.locator("#mikan-candidate-search-result .error-state")
        expect(in_place).to_contain_text("候选搜索失败")

        # A replacement summary must not move focus either.
        page.evaluate(
            "() => document.querySelector('#mikan-candidate-search-form').requestSubmit()"
        )
        expect(in_place).to_contain_text("候选搜索失败")
        assert page.evaluate("() => document.activeElement?.outerHTML ?? ''") == focused_before

        close = page.locator(".global-notification-close")
        expect(close).to_have_text("关闭")
        close.focus()
        expect(close).to_be_focused()
        page.keyboard.press("Enter")
        expect(toast).to_have_count(0)

        # Closing the summary never removes the recovery path it summarised.
        expect(in_place).to_contain_text("候选搜索失败")
        retry = in_place.locator("button:has-text('重试')")
        candidates["fail"] = False
        retry.click()
        expect(page.locator(".candidate-card")).to_have_count(1)


class TestAppGlobalNotificationSensitiveBoundary:
    """AC (US-346): 悬浮提示不泄露也不持久化敏感值."""

    def test_toast_keeps_sensitive_values_out_of_every_surface(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        page.set_viewport_size({"width": 1280, "height": 900})
        canaries = (
            "https://private-mikan.canary.local/Home/Bangumi/42?token=CANARY-TOKEN",
            "session=CANARY-COOKIE",
            "magnet:?xt=urn:btih:CANARY-MAGNET",
            "/srv/private/CANARY-ABSOLUTE-PATH",
            "CANARY-RAW-RESPONSE-BODY",
        )
        console_messages: list[str] = []
        page.on("console", lambda message: console_messages.append(message.text))

        body = _candidate_failure_json(
            status_code=503,
            endpoint=canaries[0],
            cookie_header=canaries[1],
            magnet=canaries[2],
            storage_path=canaries[3],
            raw_response_body=canaries[4],
        )
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(
                status=200, content_type="application/json", body=body
            ),
        )
        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)
        history_before = page.evaluate("() => window.history.length")
        _search(page)

        toast = page.locator(".global-notification")
        expect(toast).to_contain_text("候选搜索失败", timeout=5000)

        surfaces = page.evaluate(
            """() => ({
                url: window.location.href,
                html: document.documentElement.outerHTML,
                bodyText: document.body.innerText,
                toastText: document.querySelector('.global-notification').innerText,
                toastHtml: document.querySelector('.global-notification').outerHTML,
                localStorage: JSON.stringify(window.localStorage),
                sessionStorage: JSON.stringify(window.sessionStorage),
                historyState: JSON.stringify(window.history.state),
            })"""
        )
        for value in canaries:
            for name, content in surfaces.items():
                assert value not in content, f"{value!r} leaked into {name}"
            for message in console_messages:
                assert value not in message, f"{value!r} leaked into the console"

        # The summary is shown, but never becomes a navigation entry.
        assert page.evaluate("() => window.history.length") == history_before
        assert "CANARY" not in page.url
