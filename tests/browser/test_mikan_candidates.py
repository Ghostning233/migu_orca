from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import set_storage_preferences


pytestmark = pytest.mark.browser


def _open_candidate_search(page: Page, live_server_url: str) -> None:
    """Load /index and expand the explicit real MiKan candidate search section."""
    page.goto(f"{live_server_url}/index")
    page.locator("#mikan-candidate-search summary").click()
    page.wait_for_selector("#mikan-candidate-search-form", timeout=5000)


def _fill_candidate_search(
    page: Page,
    *,
    query: str,
    endpoint: str,
    timeout_seconds: str = "5",
) -> None:
    page.fill("#mikan-candidate-query", query)
    page.fill("#mikan-candidate-search-endpoint", endpoint)
    page.fill("#mikan-candidate-timeout-seconds", timeout_seconds)


def _candidate_result_json(query: str, candidates: list[dict[str, Any]]) -> str:
    return json.dumps(
        {"ok": True, "result": {"query": query, "candidates": candidates}},
        ensure_ascii=False,
    )


class TestDefaultFixtureDoesNotUseRealMikan:
    """AC: /index 默认 fixture 生成流程不展示或触发真实 MiKan 候选搜索."""

    def test_candidate_search_collapsed_by_default(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/index")

        details = page.locator("#mikan-candidate-search")
        expect(details).to_be_visible()
        # Closed by default: no `open` attribute and the form fields are hidden.
        assert details.get_attribute("open") is None
        expect(page.locator("#mikan-candidate-query")).to_be_hidden()

    def test_default_generation_never_calls_candidate_search(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        calls: list[str] = []

        def _capture(route: Any, request: Any) -> None:
            calls.append(request.url)
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"ok": false, "error_message": "should not be called"}',
            )

        page.route("**/api/v1/mikan/candidates", _capture)
        set_storage_preferences(page, storage_dir, save_request=True)
        page.goto(f"{live_server_url}/index")
        page.fill('input[name="title"]', "葬送的芙莉莲")
        page.click("#request-generate-submit")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert "保存成功" in page.locator("#page-notification").inner_text()
        assert calls == []


class TestCandidateSearchStates:
    """AC: 候选搜索 loading、成功、空结果、失败和重试状态."""

    def test_candidate_search_success_renders_cards(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        body = _candidate_result_json(
            "芙莉莲",
            [
                {
                    "bangumi_id": "2353",
                    "title": "葬送的芙莉莲",
                    "mikan_url": "https://mikan.example/Home/Bangumi/2353",
                    "poster_url": "https://mikan.example/assets/cover/2353.jpg",
                    "source_query": "芙莉莲",
                    "aliases": ["Frieren EN"],
                },
                {
                    "bangumi_id": "3072",
                    "title": "咒术回战 第三季",
                    "mikan_url": "https://mikan.example/Home/Bangumi/3072",
                    "poster_url": None,
                    "source_query": "芙莉莲",
                    "aliases": [],
                },
            ],
        )

        def _fulfill(route: Any, request: Any) -> None:
            route.fulfill(status=200, content_type="application/json", body=body)

        page.route("**/api/v1/mikan/candidates", _fulfill)
        _open_candidate_search(page, live_server_url)
        _fill_candidate_search(
            page,
            query="芙莉莲",
            endpoint="https://mikan.example/Home/Search",
        )
        page.click("#mikan-candidate-search-submit")

        expect(page.locator(".candidate-card")).to_have_count(2)
        text = page.locator("#mikan-candidate-search-result").inner_text()
        assert "葬送的芙莉莲" in text
        assert "咒术回战 第三季" in text
        assert "MiKan ID: 2353" in text
        assert "MiKan ID: 3072" in text
        assert "来源 query: 芙莉莲" in text
        expect(
            page.locator(".candidate-card").nth(0).locator("img.candidate-poster")
        ).to_have_attribute(
            "src", "https://mikan.example/assets/cover/2353.jpg"
        )
        expect(
            page.locator(".candidate-card").nth(1).locator("img.candidate-poster")
        ).to_have_count(0)

        # The sensitive search_endpoint is cleared after success; query is kept.
        assert page.locator("#mikan-candidate-search-endpoint").input_value() == ""
        assert page.locator("#mikan-candidate-query").input_value() == "芙莉莲"

    def test_candidate_search_empty_result(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        def _fulfill(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_candidate_result_json("ghost", []),
            )

        page.route("**/api/v1/mikan/candidates", _fulfill)
        _open_candidate_search(page, live_server_url)
        _fill_candidate_search(
            page,
            query="ghost",
            endpoint="https://mikan.example/Home/Search",
        )
        page.click("#mikan-candidate-search-submit")

        result = page.locator("#mikan-candidate-search-result")
        expect(result).to_contain_text("未找到候选合集")
        assert "empty-state" in (result.get_attribute("class") or "")

    def test_candidate_search_failure_then_retry(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        fail: list[bool] = [True]

        def _flaky(route: Any, request: Any) -> None:
            if fail[0]:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "ok": False,
                            "error_type": "mikan_http_failed",
                            "error_message": "MiKan HTTP 请求失败",
                            "error_data": {
                                "failed_step": "mikan_search",
                                "details": {"status_code": 503},
                            },
                        }
                    ),
                )
                return
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_candidate_result_json(
                    "芙莉莲",
                    [
                        {
                            "bangumi_id": "42",
                            "title": "葬送的芙莉莲",
                            "mikan_url": "https://mikan.example/Home/Bangumi/42",
                            "poster_url": None,
                            "source_query": "芙莉莲",
                            "aliases": [],
                        }
                    ],
                ),
            )

        page.route("**/api/v1/mikan/candidates", _flaky)
        _open_candidate_search(page, live_server_url)
        _fill_candidate_search(
            page,
            query="芙莉莲",
            endpoint="https://mikan.example/Home/Search",
        )
        page.click("#mikan-candidate-search-submit")

        result = page.locator("#mikan-candidate-search-result")
        expect(result).to_contain_text("候选搜索失败")
        assert "error-state" in (result.get_attribute("class") or "")

        # Failure preserves inputs so the user can retry.
        assert (
            page.locator("#mikan-candidate-search-endpoint").input_value()
            == "https://mikan.example/Home/Search"
        )

        fail[0] = False
        page.click("#mikan-candidate-search-submit")
        expect(page.locator(".candidate-card")).to_have_count(1)
        assert "葬送的芙莉莲" in result.inner_text()
        assert (
            page.locator("#mikan-candidate-search-endpoint").input_value() == ""
        )


class TestCandidateSearchNoAutoSelection:
    """AC: 候选搜索结果展示不得自动选择候选，即使只有一个候选."""

    def test_single_candidate_is_not_auto_selected(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        def _fulfill(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_candidate_result_json(
                    "芙莉莲",
                    [
                        {
                            "bangumi_id": "42",
                            "title": "葬送的芙莉莲",
                            "mikan_url": "https://mikan.example/Home/Bangumi/42",
                            "poster_url": None,
                            "source_query": "芙莉莲",
                            "aliases": [],
                        }
                    ],
                ),
            )

        page.route("**/api/v1/mikan/candidates", _fulfill)
        set_storage_preferences(page, storage_dir, save_request=True)
        _open_candidate_search(page, live_server_url)
        _fill_candidate_search(
            page,
            query="芙莉莲",
            endpoint="https://mikan.example/Home/Search",
        )
        page.click("#mikan-candidate-search-submit")

        expect(page.locator(".candidate-card")).to_have_count(1)
        # No selection action is offered and no Request is generated or saved.
        assert (
            page.locator(".candidate-card button:has-text('选择此合集')").count()
            == 0
        )
        assert "request_id=" not in page.url
        assert not storage_dir.exists() or not any(storage_dir.iterdir())


class TestCandidateSearchSensitiveBoundary:
    """AC: 敏感字段提交成功后不得写入 browser storage、URL、Request snapshot 或 history."""

    def test_candidate_search_does_not_persist_or_leak_sensitive_values(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        sensitive_values = (
            "http://private-mikan.stage17.local/Home/Search",
            "stage17-candidate-token",
            "stage17-candidate-cookie",
            "<html>stage17 raw html</html>",
            "<rss version='2.0'>stage17 raw rss</rss>",
            "stage17 raw response body",
        )

        def _fulfill(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": True,
                        "result": {
                            "query": "芙莉莲",
                            "candidates": [
                                {
                                    "bangumi_id": "42",
                                    "title": "葬送的芙莉莲",
                                    "mikan_url": "https://mikan.example/Home/Bangumi/42",
                                    "poster_url": None,
                                    "source_query": "芙莉莲",
                                    "aliases": [],
                                    "token": sensitive_values[1],
                                    "cookie": sensitive_values[2],
                                    "raw_html": sensitive_values[3],
                                    "raw_rss_xml": sensitive_values[4],
                                    "raw_response_body": sensitive_values[5],
                                }
                            ],
                        },
                    },
                    ensure_ascii=False,
                ),
            )

        page.route("**/api/v1/mikan/candidates", _fulfill)
        set_storage_preferences(page, storage_dir, save_request=True)
        _open_candidate_search(page, live_server_url)
        _fill_candidate_search(
            page,
            query="芙莉莲",
            endpoint=sensitive_values[0],
        )
        page.click("#mikan-candidate-search-submit")
        expect(page.locator(".candidate-card")).to_have_count(1)

        # The sensitive endpoint input is cleared after success.
        assert page.locator("#mikan-candidate-search-endpoint").input_value() == ""

        browser_state = page.evaluate(
            """() => ({
                url: window.location.href,
                localStorage: JSON.stringify(window.localStorage),
                sessionStorage: JSON.stringify(window.sessionStorage),
                bodyText: document.body.innerText,
            })"""
        )
        for value in sensitive_values:
            assert value not in browser_state["url"]
            assert value not in browser_state["localStorage"]
            assert value not in browser_state["sessionStorage"]
            assert value not in browser_state["bodyText"]

        # No Request snapshot was created by candidate search.
        assert not storage_dir.exists() or not any(storage_dir.iterdir())

        local_storage = page.evaluate(
            """() => Object.fromEntries(
                Array.from({ length: window.localStorage.length }, (_, index) => {
                    const key = window.localStorage.key(index);
                    return [key, window.localStorage.getItem(key)];
                })
            )"""
        )
        assert local_storage == {
            "miguOrca.web.storageDir": str(storage_dir),
            "miguOrca.web.saveRequest": "true",
        }
