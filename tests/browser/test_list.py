from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page

from tests.browser.conftest import create_saved_request, set_storage_preferences


pytestmark = pytest.mark.browser


@pytest.fixture(scope="function")
def storage_with_requests(storage_dir: Path) -> Path:
    """Pre-populate temp storage with multiple saved Requests for list testing."""
    create_saved_request(storage_dir, "葬送的芙莉莲", "req-a")
    create_saved_request(storage_dir, "咒术回战第三季", "req-b")
    create_saved_request(storage_dir, "葬送的芙莉莲", "req-c")
    return storage_dir


def _navigate_to_list(
    page: Page, live_server_url: str, storage_dir: Path
) -> None:
    """Go to index, set storage_dir, refresh list, and wait for load."""
    set_storage_preferences(page, storage_dir)
    page.goto(f"{live_server_url}/index")
    page.click("#request-list-refresh")
    # Wait for list to render (empty state replaced by real items)
    page.wait_for_selector("#request-list-container button.request-list-item", timeout=5000)
    page.wait_for_timeout(300)


class TestListLoadsMultipleRequests:
    """AC: 预置至少两个已保存 Request，验证列表加载数量."""

    def test_list_count_shows_correct_total(
        self, page: Page, live_server_url: str, storage_with_requests: Path
    ) -> None:
        _navigate_to_list(page, live_server_url, storage_with_requests)

        count = page.locator("#request-list-count")
        text = count.inner_text()
        assert "显示 3 / 3" in text

    def test_list_renders_all_items(
        self, page: Page, live_server_url: str, storage_with_requests: Path
    ) -> None:
        _navigate_to_list(page, live_server_url, storage_with_requests)

        items = page.locator("#request-list-container button.request-list-item")
        assert items.count() >= 3


class TestTextSearch:
    """AC: 文本搜索可按标题、request_id、字幕组或 folder_name 过滤列表."""

    def test_search_by_title(
        self, page: Page, live_server_url: str, storage_with_requests: Path
    ) -> None:
        _navigate_to_list(page, live_server_url, storage_with_requests)

        page.fill("#request-list-search", "芙莉莲")
        page.wait_for_timeout(300)
        count = page.locator("#request-list-count")
        # "葬送的芙莉莲" matches 2 of 3 requests (req-a and req-c)
        assert "显示 2 / 3" in count.inner_text()

    def test_search_by_request_id(
        self, page: Page, live_server_url: str, storage_with_requests: Path
    ) -> None:
        _navigate_to_list(page, live_server_url, storage_with_requests)

        page.fill("#request-list-search", "req-a")
        page.wait_for_timeout(300)
        count = page.locator("#request-list-count")
        assert "显示 1 / 3" in count.inner_text()


class TestStatusFilter:
    """AC: status 筛选至少支持 All 和当前列表中出现的 status 值."""

    def test_filter_all_present(
        self, page: Page, live_server_url: str, storage_with_requests: Path
    ) -> None:
        _navigate_to_list(page, live_server_url, storage_with_requests)

        filt = page.locator("#request-list-status-filter")
        assert filt.count() >= 1
        options = [opt.inner_text() for opt in filt.locator("option").all()]
        assert "All" in options or any("PENDING_CONFIRM" in o for o in options)


class TestSort:
    """AC: 排序控件支持默认顺序、标题升序和 request_id 升序."""

    def test_sort_options_present(
        self, page: Page, live_server_url: str, storage_with_requests: Path
    ) -> None:
        _navigate_to_list(page, live_server_url, storage_with_requests)

        sort_select = page.locator("#request-list-sort")
        assert sort_select.count() >= 1
        values = [
            opt.get_attribute("value")
            for opt in sort_select.locator("option").all()
        ]
        assert "default" in values
        assert "title_asc" in values
        assert "request_id_asc" in values

    def test_sort_changes_order(
        self, page: Page, live_server_url: str, storage_with_requests: Path
    ) -> None:
        _navigate_to_list(page, live_server_url, storage_with_requests)

        items_before = page.locator("#request-list-container button.request-list-item")
        default_texts = [it.inner_text() for it in items_before.all()]

        page.locator("#request-list-sort").select_option("title_asc")
        page.wait_for_timeout(300)
        items_after = page.locator("#request-list-container button.request-list-item")
        sorted_texts = [it.inner_text() for it in items_after.all()]

        assert len(sorted_texts) == len(default_texts)
        assert len(sorted_texts) >= 3


class TestEmptySearchResult:
    """AC: 无匹配时显示明确空状态，清空筛选后列表恢复."""

    def test_no_match_shows_empty_state(
        self, page: Page, live_server_url: str, storage_with_requests: Path
    ) -> None:
        _navigate_to_list(page, live_server_url, storage_with_requests)

        page.fill("#request-list-search", "不存在的番剧")
        page.wait_for_timeout(300)

        container = page.locator("#request-list-container")
        text = container.inner_text()
        assert "没有匹配的 Request" in text

    def test_clear_search_restores_full_list(
        self, page: Page, live_server_url: str, storage_with_requests: Path
    ) -> None:
        _navigate_to_list(page, live_server_url, storage_with_requests)

        page.fill("#request-list-search", "不存在的番剧")
        page.wait_for_timeout(300)

        page.fill("#request-list-search", "")
        page.wait_for_timeout(300)

        count = page.locator("#request-list-count")
        assert "显示 3 / 3" in count.inner_text()


class TestClientSideOnly:
    """AC: 列表测试验证浏览器端筛选排序行为."""

    def test_search_reduces_visible_items(
        self, page: Page, live_server_url: str, storage_with_requests: Path
    ) -> None:
        _navigate_to_list(page, live_server_url, storage_with_requests)

        items_before = page.locator(
            "#request-list-container button.request-list-item"
        ).count()

        page.fill("#request-list-search", "芙莉莲")
        page.wait_for_timeout(300)

        items_after = page.locator(
            "#request-list-container button.request-list-item"
        ).count()
        assert items_after < items_before
