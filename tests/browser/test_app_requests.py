from __future__ import annotations

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
        "to verify the US-202 Requests migration in the browser."
    )


@pytest.fixture(scope="function")
def storage_with_requests(storage_dir: Path) -> Path:
    """Pre-populate temp storage with multiple saved Requests for list testing."""
    create_saved_request(storage_dir, "葬送的芙莉莲", "req-a")
    create_saved_request(storage_dir, "咒术回战第三季", "req-b")
    create_saved_request(storage_dir, "葬送的芙莉莲", "req-c")
    return storage_dir


def _goto_requests(page: Page, live_server_url: str, query: str = "") -> None:
    """Navigate to the SPA requests list and wait for it to load."""
    _require_dist()
    page.goto(f"{live_server_url}/app/requests{query}")
    page.wait_for_selector("#request-list-container", timeout=5000)
    page.wait_for_selector(".request-list-item", timeout=5000)


class TestAppRequestsLoadsList:
    """AC: 迁移列表加载、计数和渲染，与旧列表同一 API."""

    def test_list_count_shows_correct_total(
        self, page: Page, live_server_url: str, storage_with_requests: Path
    ) -> None:
        set_storage_preferences(page, storage_with_requests)
        _goto_requests(page, live_server_url)

        count = page.locator("#request-list-count")
        expect(count).to_contain_text("显示 3 / 3")

    def test_list_renders_all_items(
        self, page: Page, live_server_url: str, storage_with_requests: Path
    ) -> None:
        set_storage_preferences(page, storage_with_requests)
        _goto_requests(page, live_server_url)

        items = page.locator("#request-list-container .request-list-item")
        assert items.count() >= 3

    def test_empty_state_when_no_requests(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        set_storage_preferences(page, storage_dir)
        _require_dist()
        page.goto(f"{live_server_url}/app/requests")
        page.wait_for_selector("#request-list-container", timeout=5000)

        container = page.locator("#request-list-container")
        expect(container).to_contain_text("暂无已保存的订阅方案")
        count = page.locator("#request-list-count")
        expect(count).to_contain_text("显示 0 / 0")


class TestAppRequestsSearchFilterSort:
    """AC: 搜索、状态筛选、排序与旧列表 parity."""

    def test_search_by_title(
        self, page: Page, live_server_url: str, storage_with_requests: Path
    ) -> None:
        set_storage_preferences(page, storage_with_requests)
        _goto_requests(page, live_server_url)

        page.fill("#request-list-search", "芙莉莲")
        page.wait_for_timeout(300)
        expect(page.locator("#request-list-count")).to_contain_text("显示 2 / 3")

    def test_search_by_request_id(
        self, page: Page, live_server_url: str, storage_with_requests: Path
    ) -> None:
        set_storage_preferences(page, storage_with_requests)
        _goto_requests(page, live_server_url)

        page.fill("#request-list-search", "req-a")
        page.wait_for_timeout(300)
        expect(page.locator("#request-list-count")).to_contain_text("显示 1 / 3")

    def test_status_filter_options_include_business_labels(
        self, page: Page, live_server_url: str, storage_with_requests: Path
    ) -> None:
        set_storage_preferences(page, storage_with_requests)
        _goto_requests(page, live_server_url)

        options = [
            opt.inner_text()
            for opt in page.locator("#request-list-status-filter option").all()
        ]
        assert "全部" in options
        assert any(label in options for label in ("待确认", "已确认", "已取消"))

    def test_sort_options_present(
        self, page: Page, live_server_url: str, storage_with_requests: Path
    ) -> None:
        set_storage_preferences(page, storage_with_requests)
        _goto_requests(page, live_server_url)

        values = [
            opt.get_attribute("value")
            for opt in page.locator("#request-list-sort option").all()
        ]
        assert "default" in values
        assert "title_asc" in values
        assert "request_id_asc" in values

    def test_no_match_shows_empty_state_and_clears(
        self, page: Page, live_server_url: str, storage_with_requests: Path
    ) -> None:
        set_storage_preferences(page, storage_with_requests)
        _goto_requests(page, live_server_url)

        page.fill("#request-list-search", "不存在的番剧")
        page.wait_for_timeout(300)
        expect(page.locator("#request-list-container")).to_contain_text(
            "没有匹配的订阅方案"
        )

        page.fill("#request-list-search", "")
        page.wait_for_timeout(300)
        expect(page.locator("#request-list-count")).to_contain_text("显示 3 / 3")


class TestAppRequestsSelection:
    """AC: request_id 可复制和刷新恢复，storage 只使用相对 profile."""

    def test_clicking_item_pushes_request_id_query(
        self, page: Page, live_server_url: str, storage_with_requests: Path
    ) -> None:
        set_storage_preferences(page, storage_with_requests)
        _goto_requests(page, live_server_url)

        page.locator("[data-request-id='req-b']").click()
        page.wait_for_url("**/app/requests?request_id=req-b", timeout=5000)
        selected = page.locator(".request-list-item.is-selected")
        expect(selected).to_have_attribute("data-request-id", "req-b")
        expect(selected).to_have_attribute("aria-current", "true")

    def test_refresh_restores_selected_item(
        self, page: Page, live_server_url: str, storage_with_requests: Path
    ) -> None:
        set_storage_preferences(page, storage_with_requests)
        _goto_requests(page, live_server_url, query="?request_id=req-c")

        selected = page.locator(".request-list-item.is-selected")
        expect(selected).to_have_attribute("data-request-id", "req-c")

    def test_copy_request_id_button_uses_public_identifier(
        self, page: Page, live_server_url: str, storage_with_requests: Path
    ) -> None:
        set_storage_preferences(page, storage_with_requests)
        _goto_requests(page, live_server_url)

        copy_btn = page.locator(".copy-request-id").first
        expect(copy_btn).to_be_visible()
        expect(copy_btn).to_contain_text("复制")

    def test_no_absolute_paths_in_url_or_storage(
        self, page: Page, live_server_url: str, storage_with_requests: Path
    ) -> None:
        """The relative profile is used; absolute paths never reach URL/localStorage."""
        set_storage_preferences(page, storage_with_requests)
        _goto_requests(page, live_server_url)

        current_url = page.url
        assert "storage_dir" not in current_url or "storage" in current_url
        stored = page.evaluate(
            "() => localStorage.getItem('miguOrca.web.storageDir')"
        )
        assert stored == "storage"
        assert not stored.startswith("/")
        assert not stored.startswith("C:")


class TestAppRequestsResponsiveAndA11y:
    """AC: 窄屏无横向溢出；错误状态用 role=alert."""

    def test_360px_no_horizontal_overflow(
        self, page: Page, live_server_url: str, storage_with_requests: Path
    ) -> None:
        set_storage_preferences(page, storage_with_requests)
        _goto_requests(page, live_server_url)
        page.set_viewport_size({"width": 360, "height": 780})
        body = page.locator("body")
        body_width = body.evaluate("el => el.scrollWidth")
        viewport_width = page.evaluate("() => window.innerWidth")
        assert body_width <= viewport_width, (
            f"Body scrollWidth ({body_width}) exceeds viewport ({viewport_width})"
        )

    def test_error_state_carries_assertive_aria(
        self, page: Page, live_server_url: str
    ) -> None:
        _require_dist()
        set_storage_preferences(page, "storage")

        def _fail(route: Any, request: Any) -> None:
            if request.method == "GET" and "storage_dir=storage" in request.url:
                route.fulfill(
                    status=500,
                    content_type="application/json",
                    body='{"ok": false, "error_type": "storage_error", "error_message": "读取订阅方案失败"}',
                )
            else:
                route.continue_()

        page.route("**/api/v1/requests**", _fail)
        page.goto(f"{live_server_url}/app/requests")
        page.wait_for_selector("#request-list-container .error-state", timeout=5000)

        error = page.locator("#request-list-container .error-state")
        # ErrorState renders role=alert (assertive by default per ARIA).
        assert error.get_attribute("role") == "alert"


class TestAppRequestsErrorState:
    """AC: 400/500 失败有类型化中文安全反馈（错误内容脱敏）."""

    def test_load_failure_shows_safe_error_with_retry(
        self, page: Page, live_server_url: str
    ) -> None:
        _require_dist()
        set_storage_preferences(page, "storage")

        def _fail(route: Any, request: Any) -> None:
            if request.method == "GET" and "storage_dir=storage" in request.url:
                route.fulfill(
                    status=500,
                    content_type="application/json",
                    body=(
                        '{"ok": false, "error_type": "storage_error", '
                        '"error_message": "读取订阅方案失败", '
                        '"error_data": {"failed_step": "load_request_snapshots"}}'
                    ),
                )
            else:
                route.continue_()

        page.route("**/api/v1/requests**", _fail)
        page.goto(f"{live_server_url}/app/requests")
        page.wait_for_selector("#request-list-container", timeout=5000)

        error = page.locator("#request-list-container .error-state")
        expect(error).to_be_visible()
        expect(error).to_contain_text("订阅方案列表加载失败")
        # The raw server error_type/message never leaks into the DOM.
        assert "storage_error" not in (error.inner_text() or "")
        assert "load_request_snapshots" not in (error.inner_text() or "")

        # Retry after unroute reloads the real (empty) list.
        page.unroute("**/api/v1/requests**")
        page.locator("#request-list-container .error-state .secondary-button").click()
        page.wait_for_selector("#request-list-container .empty-state", timeout=5000)
        expect(page.locator("#request-list-count")).to_contain_text("显示 0 / 0")
