from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import (
    create_saved_request,
    open_dev_fixture_panel,
    set_storage_preferences,
)
from apps.migu_orca_entry.controllers.entry_controller import generate_request
from request_engine.controllers.request_controller import summarize_request
from shared.models import EntryRequest


pytestmark = pytest.mark.browser


def _open_candidate_search(page: Page, live_server_url: str) -> None:
    """Load /index; the real MiKan candidate search is the main generation flow."""
    page.goto(f"{live_server_url}/index")


def _fill_candidate_search(
    page: Page,
    *,
    query: str,
) -> None:
    page.fill("#mikan-candidate-query", query)


def _enable_candidate_fallback(page: Page) -> None:
    """Check the direct-collection fallback gate and wait for the form to show."""
    page.check("#mikan-fallback-enabled")
    expect(page.locator("#mikan-fallback-form")).to_be_visible()


def _candidate_result_json(query: str, candidates: list[dict[str, Any]]) -> str:
    return json.dumps(
        {"ok": True, "result": {"query": query, "candidates": candidates}},
        ensure_ascii=False,
    )


class TestDefaultFixtureDoesNotUseRealMikan:
    """AC: /index 主流程是真实 MiKan 候选搜索；fixture 生成保留在开发/离线测试区域."""

    def test_candidate_search_is_the_main_flow(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/index")

        # The default tab exposes the real candidate-search form directly (no
        # hidden disclosure); the workbench retains a general creation title.
        expect(page.locator("#mikan-candidate-search-form")).to_be_visible()
        expect(page.locator("#mikan-candidate-query")).to_be_visible()
        assert page.locator("#mikan-candidate-search").count() == 0
        heading = page.locator("#generate-heading").inner_text()
        assert "创建订阅方案" in heading

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
        open_dev_fixture_panel(page)
        # The fixture generation form lives in the dev/offline-test area.
        page.fill('input[name="title"]', "葬送的芙莉莲")
        page.click("#request-generate-submit")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert "保存成功" in page.locator("#page-notification").inner_text()
        assert calls == []


class TestCandidateSearchStates:
    """AC: 主搜索 loading、成功、空结果、失败和重试状态均使用中文文案."""

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
        _fill_candidate_search(page, query="芙莉莲")
        page.click("#mikan-candidate-search-submit")

        expect(page.locator(".candidate-card")).to_have_count(2)
        text = page.locator("#mikan-candidate-search-result").inner_text()
        assert "葬送的芙莉莲" in text
        assert "咒术回战 第三季" in text
        assert "MiKan ID: 2353" in text
        assert "MiKan ID: 3072" in text
        assert "搜索词：芙莉莲" in text
        expect(
            page.locator(".candidate-card").nth(0).locator("img.candidate-poster")
        ).to_have_attribute(
            "src", "https://mikan.example/assets/cover/2353.jpg"
        )
        expect(
            page.locator(".candidate-card").nth(1).locator("img.candidate-poster")
        ).to_have_count(0)

        # The query input is preserved after a successful search.
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
        _fill_candidate_search(page, query="ghost")
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
        _fill_candidate_search(page, query="芙莉莲")
        page.click("#mikan-candidate-search-submit")

        result = page.locator("#mikan-candidate-search-result")
        expect(result).to_contain_text("候选搜索失败")
        assert "error-state" in (result.get_attribute("class") or "")

        # Failure preserves the query so the user can retry.
        assert page.locator("#mikan-candidate-query").input_value() == "芙莉莲"

        fail[0] = False
        page.click("#mikan-candidate-search-submit")
        expect(page.locator(".candidate-card")).to_have_count(1)
        assert "葬送的芙莉莲" in result.inner_text()


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
        _fill_candidate_search(page, query="芙莉莲")
        page.click("#mikan-candidate-search-submit")

        expect(page.locator(".candidate-card")).to_have_count(1)
        # The explicit selection action is offered, but nothing is selected or
        # generated automatically even with a single candidate.
        assert (
            page.locator(".candidate-card button:has-text('选择此合集')").count()
            == 1
        )
        assert "request_id=" not in page.url
        assert not storage_dir.exists() or not any(storage_dir.iterdir())


class TestCandidateSearchSensitiveBoundary:
    """AC: 候选搜索不把 raw HTML、raw RSS、cookie、token 写入 browser storage、URL 或 Request snapshot."""

    def test_candidate_search_does_not_persist_or_leak_sensitive_values(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        sensitive_values = (
            "stage18-candidate-token",
            "stage18-candidate-cookie",
            "<html>stage18 raw html</html>",
            "<rss version='2.0'>stage18 raw rss</rss>",
            "stage18 raw response body",
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
                                    "token": sensitive_values[0],
                                    "cookie": sensitive_values[1],
                                    "raw_html": sensitive_values[2],
                                    "raw_rss_xml": sensitive_values[3],
                                    "raw_response_body": sensitive_values[4],
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
        _fill_candidate_search(page, query="芙莉莲")
        page.click("#mikan-candidate-search-submit")
        expect(page.locator(".candidate-card")).to_have_count(1)

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


def _candidate(  # type: ignore[no-untyped-def]
    *,
    bangumi_id: str,
    title: str,
    mikan_url: str,
    source_query: str = "芙莉莲",
    poster_url: str | None = None,
    aliases: list[str] | None = None,
    recommendation: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "bangumi_id": bangumi_id,
        "title": title,
        "mikan_url": mikan_url,
        "poster_url": poster_url,
        "source_query": source_query,
        "aliases": aliases or [],
    }
    if recommendation is not None:
        result["recommendation"] = recommendation
    return result


def _generation_result_json(saved_request: dict[str, Any]) -> str:
    """Build a successful `POST /api/v1/requests` response body from a saved request."""
    return json.dumps(
        {
            "ok": True,
            "result": {
                "request": saved_request,
                "summary": summarize_request(saved_request),
                "saved_request": saved_request,
            }
        },
        ensure_ascii=False,
    )


def _preview_request(title: str, request_id: str) -> dict[str, Any]:
    """Build an unsaved preview Request dict (PENDING_CONFIRM, not on disk)."""
    return {
        **generate_request(EntryRequest(raw_title=title))["request"],
        "request_id": request_id,
    }


def _preview_result_json(request: dict[str, Any]) -> str:
    """Build a `POST /api/v1/requests` response body for an unsaved preview draft."""
    return json.dumps(
        {
            "ok": True,
            "result": {
                "request": request,
                "summary": summarize_request(request),
            }
        },
        ensure_ascii=False,
    )


def _register_generation_capture(
    page: Page,
    captured: list[dict[str, Any]],
    *,
    body: str,
) -> None:
    """Route `POST /api/v1/requests` to capture the payload and return a fake body.

    Non-POST requests (the GET list refresh after generation) pass through to the
    real Flask backend.
    """

    def _handler(route: Any, request: Any) -> None:
        if request.method != "POST":
            route.continue_()
            return
        captured.append(request.post_data_json)
        route.fulfill(status=200, content_type="application/json", body=body)

    page.route("**/api/v1/requests", _handler)


class TestCandidateRecommendationLabels:
    """AC: 候选卡片可显示 display-only 推荐标签，标签不自动选择候选或生成 Request."""

    def test_recommendation_label_renders_on_cards(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_candidate_result_json(
                    "芙莉莲 第二季",
                    [
                        _candidate(
                            bangumi_id="3072",
                            title="葬送的芙莉莲 第二季",
                            mikan_url="https://mikan.example/Home/Bangumi/3072",
                            recommendation="推荐：第 2 季",
                        ),
                        _candidate(
                            bangumi_id="2353",
                            title="葬送的芙莉莲",
                            mikan_url="https://mikan.example/Home/Bangumi/2353",
                            recommendation="可能匹配",
                        ),
                    ],
                ),
            ),
        )
        _open_candidate_search(page, live_server_url)
        _fill_candidate_search(page, query="芙莉莲 第二季")
        page.click("#mikan-candidate-search-submit")

        expect(page.locator(".candidate-card")).to_have_count(2)
        expect(page.locator(".candidate-recommendation").nth(0)).to_have_text(
            "推荐：第 2 季"
        )
        expect(page.locator(".candidate-recommendation").nth(1)).to_have_text(
            "可能匹配"
        )
        # The label does not reorder the cards: MiKan page order is preserved.
        assert (
            page.locator(".candidate-card").nth(0).locator("strong").inner_text()
            == "葬送的芙莉莲 第二季"
        )

    def test_no_recommendation_field_renders_no_badge(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_candidate_result_json(
                    "芙莉莲",
                    [
                        _candidate(
                            bangumi_id="2353",
                            title="葬送的芙莉莲",
                            mikan_url="https://mikan.example/Home/Bangumi/2353",
                        ),
                    ],
                ),
            ),
        )
        _open_candidate_search(page, live_server_url)
        _fill_candidate_search(page, query="芙莉莲")
        page.click("#mikan-candidate-search-submit")

        expect(page.locator(".candidate-card")).to_have_count(1)
        expect(page.locator(".candidate-recommendation")).to_have_count(0)

    def test_conflicting_season_shows_no_strong_copy_and_no_auto_generation(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        captured: list[dict[str, Any]] = []
        _register_generation_capture(page, captured, body='{"ok": true}')
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_candidate_result_json(
                    "芙莉莲 第二季",
                    [
                        _candidate(
                            bangumi_id="2353",
                            title="葬送的芙莉莲 第一季",
                            mikan_url="https://mikan.example/Home/Bangumi/2353",
                            recommendation="季数不符",
                        ),
                    ],
                ),
            ),
        )
        set_storage_preferences(page, storage_dir, save_request=True)
        _open_candidate_search(page, live_server_url)
        _fill_candidate_search(page, query="芙莉莲 第二季")
        page.click("#mikan-candidate-search-submit")

        expect(page.locator(".candidate-card")).to_have_count(1)
        expect(page.locator(".candidate-recommendation")).to_have_text("季数不符")
        # A conflicting season must not show strong recommendation copy.
        assert (
            "推荐：第"
            not in page.locator("#mikan-candidate-search-result").inner_text()
        )
        # Single candidate still requires an explicit manual selection.
        assert captured == []
        assert "request_id=" not in page.url

    def test_single_candidate_with_strong_label_still_requires_manual_selection(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_candidate_result_json(
                    "芙莉莲 第二季",
                    [
                        _candidate(
                            bangumi_id="3072",
                            title="葬送的芙莉莲 第二季",
                            mikan_url="https://mikan.example/Home/Bangumi/3072",
                            recommendation="推荐：第 2 季",
                        ),
                    ],
                ),
            ),
        )
        preview = _preview_request("葬送的芙莉莲 第二季", "req-rec-1")
        captured: list[dict[str, Any]] = []
        _register_generation_capture(
            page, captured, body=_preview_result_json(preview)
        )

        set_storage_preferences(page, storage_dir, save_request=False)
        _open_candidate_search(page, live_server_url)
        _fill_candidate_search(page, query="芙莉莲 第二季")
        page.click("#mikan-candidate-search-submit")

        expect(page.locator(".candidate-card")).to_have_count(1)
        expect(page.locator(".candidate-recommendation")).to_have_text(
            "推荐：第 2 季"
        )
        # The label must not auto-select the candidate or auto-generate.
        assert captured == []
        assert "request_id=" not in page.url

        page.locator("button:has-text('选择此合集')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
        assert captured
        assert captured[0]["mikan_bangumi"] == "https://mikan.example/Home/Bangumi/3072"
        assert captured[0]["title"] == "葬送的芙莉莲 第二季"
        assert captured[0]["save_request"] is False
        # The main flow relies on the server-side default MiKan config.
        assert "mikan_config" not in captured[0]


class TestCandidateManualSelection:
    """AC: 每个候选卡片提供显式「选择此合集」动作，选择后复用 mikan_bangumi 生成 Request."""

    def test_multi_candidate_manual_selection_generates_request(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_candidate_result_json(
                    "芙莉莲",
                    [
                        _candidate(
                            bangumi_id="2353",
                            title="葬送的芙莉莲",
                            mikan_url="https://mikan.example/Home/Bangumi/2353",
                        ),
                        _candidate(
                            bangumi_id="3072",
                            title="咒术回战 第三季",
                            mikan_url="https://mikan.example/Home/Bangumi/3072",
                        ),
                    ],
                ),
            ),
        )
        preview = _preview_request("葬送的芙莉莲", "req-cand-1")
        captured: list[dict[str, Any]] = []
        _register_generation_capture(
            page, captured, body=_preview_result_json(preview)
        )

        set_storage_preferences(page, storage_dir, save_request=False)
        _open_candidate_search(page, live_server_url)
        _fill_candidate_search(page, query="芙莉莲")
        page.click("#mikan-candidate-search-submit")
        expect(page.locator(".candidate-card")).to_have_count(2)

        # Click the explicit selection action on the first candidate only.
        page.locator(".candidate-card").nth(0).locator(
            "button:has-text('选择此合集')"
        ).click()

        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
        assert captured
        payload = captured[0]
        assert payload["source"] == "mikan"
        assert payload["mikan_bangumi"] == "https://mikan.example/Home/Bangumi/2353"
        assert payload["title"] == "葬送的芙莉莲"
        # Candidate selection always produces an editable preview draft.
        assert payload["save_request"] is False
        # The main flow relies on the server-side default MiKan config.
        assert "mikan_config" not in payload

        # The generated preview draft is not saved and never sets a URL request_id.
        assert "预览已生成" in page.locator("#page-notification").inner_text()
        assert "request_id=" not in page.url
        detail_text = page.locator("#request-detail-container").inner_text()
        assert "订阅草案（未保存）" in detail_text
        # The editable preview form is offered directly.
        expect(page.locator("#detail-preview-edit-form")).to_be_visible()

    def test_single_candidate_still_requires_click_then_generates(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_candidate_result_json(
                    "芙莉莲",
                    [
                        _candidate(
                            bangumi_id="42",
                            title="葬送的芙莉莲",
                            mikan_url="https://mikan.example/Home/Bangumi/42",
                        ),
                    ],
                ),
            ),
        )
        preview = _preview_request("葬送的芙莉莲", "req-cand-single")
        captured: list[dict[str, Any]] = []
        _register_generation_capture(
            page, captured, body=_preview_result_json(preview)
        )

        set_storage_preferences(page, storage_dir, save_request=False)
        _open_candidate_search(page, live_server_url)
        _fill_candidate_search(page, query="芙莉莲")
        page.click("#mikan-candidate-search-submit")
        expect(page.locator(".candidate-card")).to_have_count(1)

        # Nothing is generated until the explicit click.
        assert captured == []
        assert "request_id=" not in page.url

        page.locator("button:has-text('选择此合集')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
        assert captured
        assert captured[0]["mikan_bangumi"] == "https://mikan.example/Home/Bangumi/42"
        assert captured[0]["save_request"] is False
        assert "mikan_config" not in captured[0]

    def test_generation_failure_preserves_candidates_and_inputs(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_candidate_result_json(
                    "芙莉莲",
                    [
                        _candidate(
                            bangumi_id="42",
                            title="葬送的芙莉莲",
                            mikan_url="https://mikan.example/Home/Bangumi/42",
                        ),
                    ],
                ),
            ),
        )

        def _fail_generation(route: Any, request: Any) -> None:
            if request.method != "POST":
                route.continue_()
                return
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": False,
                        "error_type": "mikan_parse_failed",
                        "error_message": "MiKan 番剧页解析失败",
                        "error_data": {
                            "failed_step": "mikan_bangumi_detail",
                            "details": {"category": "parse"},
                        },
                    }
                ),
            )

        page.route("**/api/v1/requests", _fail_generation)
        set_storage_preferences(page, storage_dir, save_request=True)
        _open_candidate_search(page, live_server_url)
        _fill_candidate_search(page, query="芙莉莲")
        page.click("#mikan-candidate-search-submit")
        expect(page.locator(".candidate-card")).to_have_count(1)

        page.locator("button:has-text('选择此合集')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        # Unified sanitized error is shown.
        notif = page.locator("#page-notification").inner_text()
        assert "生成失败" in notif
        assert "MiKan 番剧页解析失败" in notif

        # Candidate list and the search input are preserved for retry.
        expect(page.locator(".candidate-card")).to_have_count(1)
        assert page.locator("#mikan-candidate-query").input_value() == "芙莉莲"


class TestCandidateSelectionSensitiveBoundary:
    """AC: 候选选择不得把 raw HTML、raw RSS、cookie、token 写入任何持久面."""

    def test_candidate_selection_does_not_leak_sensitive_values(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        sensitive_values = (
            "stage18-select-token",
            "stage18-select-cookie",
            "<html>stage18 select raw html</html>",
            "<rss version='2.0'>stage18 select raw rss</rss>",
            "stage18 select raw response body",
        )

        def _fulfill_candidates(route: Any, request: Any) -> None:
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
                                    **_candidate(
                                        bangumi_id="42",
                                        title="葬送的芙莉莲",
                                        mikan_url="https://mikan.example/Home/Bangumi/42",
                                    ),
                                    "token": sensitive_values[0],
                                    "cookie": sensitive_values[1],
                                    "raw_html": sensitive_values[2],
                                    "raw_rss_xml": sensitive_values[3],
                                    "raw_response_body": sensitive_values[4],
                                }
                            ],
                        },
                    },
                    ensure_ascii=False,
                ),
            )

        page.route("**/api/v1/mikan/candidates", _fulfill_candidates)
        preview = _preview_request("葬送的芙莉莲", "req-cand-sec")
        captured: list[dict[str, Any]] = []
        _register_generation_capture(
            page, captured, body=_preview_result_json(preview)
        )

        set_storage_preferences(page, storage_dir, save_request=False)
        _open_candidate_search(page, live_server_url)
        _fill_candidate_search(page, query="芙莉莲")
        page.click("#mikan-candidate-search-submit")
        expect(page.locator(".candidate-card")).to_have_count(1)

        page.locator("button:has-text('选择此合集')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
        assert captured

        # No request-scoped MiKan config is sent; the server applies defaults.
        assert "mikan_config" not in captured[0]
        # The preview draft is not saved by itself and never sets a URL id.
        assert "request_id=" not in page.url

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

        # Saving the draft through the real preview-save backend must persist a
        # clean static-fixture snapshot with no MiKan config, raw HTML/RSS,
        # cookies, or tokens.
        page.locator(
            "#request-detail-container button:has-text('保存草案')"
        ).click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
        saved_path = storage_dir / "requests" / "req-cand-sec.json"
        assert saved_path.exists()
        saved_json = json.loads(saved_path.read_text(encoding="utf-8"))
        for value in sensitive_values:
            assert value not in json.dumps(saved_json, ensure_ascii=False)
        # The saved draft enters the PENDING_CONFIRM confirmation flow.
        assert saved_json["status"] == "PENDING_CONFIRM"
        assert "request_id=req-cand-sec" in page.url


def _register_generation_failure(page: Page) -> None:
    """Route `POST /api/v1/requests` to a sanitized MiKan parse failure."""

    def _handler(route: Any, request: Any) -> None:
        if request.method != "POST":
            route.continue_()
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "ok": False,
                    "error_type": "mikan_parse_failed",
                    "error_message": "MiKan 番剧页解析失败",
                    "error_data": {
                        "failed_step": "mikan_bangumi_detail",
                        "details": {"category": "parse"},
                    },
                }
            ),
        )

    page.route("**/api/v1/requests", _handler)


class TestCandidateFallbackCheckbox:
    """AC: 主生成区有「搜索无结果时使用直连合集」复选框，默认不勾选并隐藏直连输入."""

    def test_fallback_checkbox_hidden_by_default(
        self, page: Page, live_server_url: str
    ) -> None:
        _open_candidate_search(page, live_server_url)

        # The gate checkbox is visible but unchecked; the fallback form is hidden.
        checkbox = page.locator("#mikan-fallback-enabled")
        expect(checkbox).to_be_visible()
        assert not checkbox.is_checked()
        expect(page.locator("#mikan-fallback-form")).to_be_hidden()
        assert (
            page.locator("#mikan-fallback-form").get_attribute("hidden")
            is not None
        )

    def test_fallback_checkbox_reveals_and_hides_form(
        self, page: Page, live_server_url: str
    ) -> None:
        _open_candidate_search(page, live_server_url)

        page.check("#mikan-fallback-enabled")
        expect(page.locator("#mikan-fallback-form")).to_be_visible()
        expect(page.locator("#mikan-fallback-bangumi")).to_be_visible()
        expect(page.locator("#mikan-fallback-generate")).to_be_visible()

        # Unchecking hides the direct-entry area again.
        page.uncheck("#mikan-fallback-enabled")
        expect(page.locator("#mikan-fallback-form")).to_be_hidden()

    def test_fallback_uncheck_clears_error_state(
        self, page: Page, live_server_url: str
    ) -> None:
        _open_candidate_search(page, live_server_url)
        page.check("#mikan-fallback-enabled")
        # Trigger a local validation error so the error paragraph is visible.
        page.click("#mikan-fallback-generate")
        expect(page.locator("#mikan-fallback-error")).not_to_be_hidden()
        page.uncheck("#mikan-fallback-enabled")
        expect(page.locator("#mikan-fallback-error")).to_be_hidden()


class TestCandidateFallbackDirectEntry:
    """AC: 搜索无结果时可用 MiKan 合集 URL 或 ID fallback 直连生成 Request."""

    def test_url_fallback_generates_request(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        preview = _preview_request("葬送的芙莉莲", "req-fb-url")
        captured: list[dict[str, Any]] = []
        _register_generation_capture(
            page, captured, body=_preview_result_json(preview)
        )

        set_storage_preferences(page, storage_dir, save_request=False)
        _open_candidate_search(page, live_server_url)
        _fill_candidate_search(page, query="芙莉莲")
        _enable_candidate_fallback(page)
        page.fill(
            "#mikan-fallback-bangumi",
            "https://mikan.example/Home/Bangumi/2353",
        )
        page.click("#mikan-fallback-generate")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert captured
        payload = captured[0]
        assert payload["source"] == "mikan"
        assert payload["mikan_bangumi"] == "https://mikan.example/Home/Bangumi/2353"
        assert payload["title"] == "芙莉莲"
        # Direct fallback also produces an editable preview draft.
        assert payload["save_request"] is False
        # The fallback works without a user-supplied endpoint (server default).
        assert "mikan_config" not in payload

        # The fallback preview draft is not saved and never sets a URL id.
        assert "预览已生成" in page.locator("#page-notification").inner_text()
        assert "request_id=" not in page.url
        detail_text = page.locator("#request-detail-container").inner_text()
        assert "订阅草案（未保存）" in detail_text

        # The fallback value is cleared after success.
        assert page.locator("#mikan-fallback-bangumi").input_value() == ""

    def test_id_fallback_generates_request(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        preview = _preview_request("葬送的芙莉莲", "req-fb-id")
        captured: list[dict[str, Any]] = []
        _register_generation_capture(
            page, captured, body=_preview_result_json(preview)
        )

        set_storage_preferences(page, storage_dir, save_request=False)
        _open_candidate_search(page, live_server_url)
        _fill_candidate_search(page, query="芙莉莲")
        _enable_candidate_fallback(page)
        page.fill("#mikan-fallback-bangumi", "2353")
        page.click("#mikan-fallback-generate")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert captured
        payload = captured[0]
        assert payload["source"] == "mikan"
        assert payload["mikan_bangumi"] == "2353"
        assert payload["save_request"] is False
        assert "mikan_config" not in payload
        assert "request_id=" not in page.url

    def test_empty_fallback_shows_validation_error_without_calling_api(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        captured: list[dict[str, Any]] = []
        _register_generation_capture(page, captured, body='{"ok": true}')

        set_storage_preferences(page, storage_dir, save_request=True)
        _open_candidate_search(page, live_server_url)
        _fill_candidate_search(page, query="芙莉莲")
        _enable_candidate_fallback(page)
        page.click("#mikan-fallback-generate")

        expect(page.locator("#mikan-fallback-error")).to_contain_text(
            "生成前必须填写 MiKan 合集 URL 或 ID"
        )
        assert captured == []
        assert "request_id=" not in page.url

    def test_invalid_fallback_value_shows_validation_error_without_calling_api(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        captured: list[dict[str, Any]] = []
        _register_generation_capture(page, captured, body='{"ok": true}')

        set_storage_preferences(page, storage_dir, save_request=True)
        _open_candidate_search(page, live_server_url)
        _fill_candidate_search(page, query="芙莉莲")
        _enable_candidate_fallback(page)
        page.fill("#mikan-fallback-bangumi", "not a url or id")
        page.click("#mikan-fallback-generate")

        expect(page.locator("#mikan-fallback-error")).to_contain_text(
            "必须是数字 ID 或 HTTP(S) URL"
        )
        assert captured == []
        assert "request_id=" not in page.url

    def test_search_no_results_then_fallback_generates_request(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_candidate_result_json("ghost", []),
            ),
        )
        preview = _preview_request("葬送的芙莉莲", "req-fb-empty")
        captured: list[dict[str, Any]] = []
        _register_generation_capture(
            page, captured, body=_preview_result_json(preview)
        )

        set_storage_preferences(page, storage_dir, save_request=False)
        _open_candidate_search(page, live_server_url)
        _fill_candidate_search(page, query="ghost")
        page.click("#mikan-candidate-search-submit")
        expect(page.locator("#mikan-candidate-search-result")).to_contain_text(
            "未找到候选合集"
        )

        _enable_candidate_fallback(page)
        page.fill("#mikan-fallback-bangumi", "https://mikan.example/Home/Bangumi/42")
        page.click("#mikan-fallback-generate")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert captured
        payload = captured[0]
        assert payload["mikan_bangumi"] == "https://mikan.example/Home/Bangumi/42"
        assert payload["save_request"] is False
        assert "mikan_config" not in payload
        assert "request_id=" not in page.url

    def test_fallback_failure_preserves_inputs_and_shows_sanitized_error(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _register_generation_failure(page)
        set_storage_preferences(page, storage_dir, save_request=True)
        _open_candidate_search(page, live_server_url)
        _fill_candidate_search(page, query="芙莉莲")
        _enable_candidate_fallback(page)
        page.fill("#mikan-fallback-bangumi", "https://mikan.example/Home/Bangumi/42")
        page.click("#mikan-fallback-generate")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        notif = page.locator("#page-notification").inner_text()
        assert "生成失败" in notif
        assert "MiKan 番剧页解析失败" in notif

        # Inputs are preserved on failure so the user can retry.
        assert (
            page.locator("#mikan-fallback-bangumi").input_value()
            == "https://mikan.example/Home/Bangumi/42"
        )
        assert page.locator("#mikan-candidate-query").input_value() == "芙莉莲"


class TestCandidateFallbackSensitiveBoundary:
    """AC: fallback 输入不得写入 browser storage、URL、Request snapshot、history 或日志."""

    def test_fallback_does_not_persist_or_leak_sensitive_values(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        sensitive_values = (
            "https://private-mikan.stage18.local/Home/Bangumi/42",
        )
        preview = _preview_request("葬送的芙莉莲", "req-fb-sec")
        captured: list[dict[str, Any]] = []
        _register_generation_capture(
            page, captured, body=_preview_result_json(preview)
        )

        set_storage_preferences(page, storage_dir, save_request=False)
        _open_candidate_search(page, live_server_url)
        _fill_candidate_search(page, query="芙莉莲")
        _enable_candidate_fallback(page)
        page.fill("#mikan-fallback-bangumi", sensitive_values[0])
        page.click("#mikan-fallback-generate")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert captured
        assert captured[0]["mikan_bangumi"] == sensitive_values[0]
        assert captured[0]["save_request"] is False
        assert "mikan_config" not in captured[0]

        # The fallback input is cleared after success and no URL id is set.
        assert page.locator("#mikan-fallback-bangumi").input_value() == ""
        assert "request_id=" not in page.url

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

        # Saving the draft through the real preview-save backend persists a
        # clean static-fixture snapshot with no MiKan endpoint or fallback URL.
        page.locator(
            "#request-detail-container button:has-text('保存草案')"
        ).click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
        saved_path = storage_dir / "requests" / "req-fb-sec.json"
        assert saved_path.exists()
        saved_json = json.loads(saved_path.read_text(encoding="utf-8"))
        for value in sensitive_values:
            assert value not in json.dumps(saved_json, ensure_ascii=False)


def _open_preview_draft(
    page: Page,
    live_server_url: str,
    storage_dir: Path,
    *,
    title: str = "咒术回战",
    request_id: str = "req-preview-1",
) -> dict[str, Any]:
    """Route candidate search + generation and open an editable preview draft."""
    page.route(
        "**/api/v1/mikan/candidates",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=_candidate_result_json(
                title,
                [
                    _candidate(
                        bangumi_id="42",
                        title=title,
                        mikan_url="https://mikan.example/Home/Bangumi/42",
                    )
                ],
            ),
        ),
    )
    preview = _preview_request(title, request_id)
    captured: list[dict[str, Any]] = []
    _register_generation_capture(
        page, captured, body=_preview_result_json(preview)
    )
    set_storage_preferences(page, storage_dir, save_request=False)
    _open_candidate_search(page, live_server_url)
    _fill_candidate_search(page, query=title)
    page.click("#mikan-candidate-search-submit")
    expect(page.locator(".candidate-card")).to_have_count(1)
    page.locator("button:has-text('选择此合集')").click()
    page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
    return preview


class TestEditablePreviewDraft:
    """AC: 候选选择默认生成可编辑预览订阅草案，保存后才进入待确认流程."""

    def test_preview_shows_editable_form_without_saved_actions(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _open_preview_draft(
            page, live_server_url, storage_dir,
            title="咒术回战", request_id="req-preview-form",
        )

        detail = page.locator("#request-detail-container")
        text = detail.inner_text()
        assert "订阅草案（未保存）" in text
        # The editable form is shown directly with every required control.
        expect(detail.locator("#detail-preview-edit-form")).to_be_visible()
        expect(detail.locator("#preview-subtitle-group")).to_be_visible()
        expect(detail.locator("#preview-must-contain")).to_be_visible()
        expect(detail.locator("#preview-must-not-contain")).to_be_visible()
        expect(detail.locator("#preview-filter-use-regex")).to_be_visible()
        expect(detail.locator("#preview-filter-case-sensitive")).to_be_visible()
        expect(detail.locator("#preview-folder-name")).to_be_visible()
        expect(detail.locator("button:has-text('应用修改')")).to_be_visible()
        expect(detail.locator("button:has-text('保存草案')")).to_be_visible()
        # No saved-request actions are offered.
        expect(detail.locator(".detail-actions button:has-text('确认')")).to_have_count(0)
        expect(detail.locator(".detail-actions button:has-text('取消')")).to_have_count(0)
        expect(detail.locator(".detail-actions button:has-text('删除')")).to_have_count(0)
        expect(detail.locator("text=去 Settings 提交 Auto Bangumi")).to_have_count(0)
        expect(detail.locator("#detail-modify-form")).to_have_count(0)
        expect(detail.locator("#detail-cancel-form")).to_have_count(0)
        assert "request_id=" not in page.url

    def test_preview_edit_never_calls_saved_action_endpoints(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        blocked_calls: list[str] = []

        def _capture_saved_action(route: Any, request: Any) -> None:
            blocked_calls.append(request.url)
            route.fulfill(
                status=500,
                content_type="application/json",
                body='{"ok": false, "error_message": "unexpected saved action"}',
            )

        page.route("**/api/v1/requests/*/accept**", _capture_saved_action)
        page.route("**/api/v1/requests/*/cancel**", _capture_saved_action)
        page.route("**/api/v1/requests/*/modify**", _capture_saved_action)
        page.route("**/api/v1/requests/*/delete**", _capture_saved_action)
        page.route("**/api/v1/requests/*/submit-ab**", _capture_saved_action)

        _open_preview_draft(
            page, live_server_url, storage_dir,
            title="咒术回战", request_id="req-preview-blocked",
        )
        # Editing the preview uses the dry-run preview-modify endpoint, not the
        # saved-request modify API.
        page.fill("#preview-must-not-contain", "V2")
        page.click("button:has-text('应用修改')")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
        text = page.locator("#request-detail-container").inner_text()
        # The recompute is visible without expanding the collapsed seed list.
        assert "有效种子数" in text
        assert "排除种子数\n1" in text
        assert blocked_calls == []

    def test_preview_modify_filter_rule_recomputes_seeds(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _open_preview_draft(
            page, live_server_url, storage_dir,
            title="咒术回战", request_id="req-preview-filter",
        )
        detail = page.locator("#request-detail-container")
        # Default fixture filter is empty: the selected Loli source has 2 seeds.
        initial = detail.inner_text()
        assert "有效种子数" in initial

        page.fill("#preview-must-not-contain", "V2")
        page.click("button:has-text('应用修改')")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        text = detail.inner_text()
        # The Filter section and the grouped Seeds display reflect the
        # recomputed counts: effective 1, complete 3, excluded 1.
        assert "有效种子数\n1" in text
        assert "排除种子数\n1" in text
        assert "有效种子（当前选中字幕组：Loli）(1)" in text
        assert "完整种子（按字幕组分组）(3)" in text
        assert "排除种子 (1)" in text
        # Expand the collapsed excluded seed list to verify the Chinese
        # exclusion reason.
        detail.locator(".excluded-seed-details").evaluate("element => element.open = true")
        text = detail.inner_text()
        assert "命中排除规则：V2" in text
        # The form keeps the applied value after re-render.
        assert page.locator("#preview-must-not-contain").input_value() == "V2"
        # Editing never writes storage.
        assert not storage_dir.exists() or not any(storage_dir.iterdir())

    def test_preview_modify_subtitle_group_updates_seeds(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _open_preview_draft(
            page, live_server_url, storage_dir,
            title="咒术回战", request_id="req-preview-group",
        )
        detail = page.locator("#request-detail-container")
        # The default selected group is Loli (priority order), so the Filter
        # section shows its effective seed count.
        assert "有效种子数" in detail.inner_text()

        page.select_option("#preview-subtitle-group", value="喵萌")
        page.click("button:has-text('应用修改')")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        text = detail.inner_text()
        # Source section reflects the newly selected subtitle group.
        assert "喵萌" in text
        # The edit form keeps the newly selected group.
        assert page.locator("#preview-subtitle-group").input_value() == "喵萌"

    def test_preview_modify_folder_name(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _open_preview_draft(
            page, live_server_url, storage_dir,
            title="咒术回战", request_id="req-preview-folder",
        )
        detail = page.locator("#request-detail-container")

        page.fill("#preview-folder-name", "MyCustomFolder")
        page.click("button:has-text('应用修改')")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        text = detail.inner_text()
        assert "MyCustomFolder" in text
        assert page.locator("#preview-folder-name").input_value() == "MyCustomFolder"

    def test_preview_save_preserves_modifications(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _open_preview_draft(
            page, live_server_url, storage_dir,
            title="咒术回战", request_id="req-preview-save",
        )
        detail = page.locator("#request-detail-container")

        # Edit folder name and filter rule, then apply to recompute seeds.
        page.fill("#preview-folder-name", "MyCustomFolder")
        page.fill("#preview-must-not-contain", "V2")
        page.click("button:has-text('应用修改')")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
        assert "排除种子数\n1" in detail.inner_text()
        assert "MyCustomFolder" in detail.inner_text()

        # Save the draft through the real preview-save backend.
        page.locator(
            "#request-detail-container button:has-text('保存草案')"
        ).click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        # The saved Request JSON preserves the modifications and enters the
        # existing PENDING_CONFIRM confirmation flow.
        saved_path = storage_dir / "requests" / "req-preview-save.json"
        saved_json = json.loads(saved_path.read_text(encoding="utf-8"))
        assert saved_json["status"] == "PENDING_CONFIRM"
        assert (
            saved_json["confirmable_config"]["expected_folder_name"]
            == "MyCustomFolder"
        )
        assert (
            saved_json["confirmable_config"]["filter_rule"]["must_not_contain"]
            == "V2"
        )
        assert "request_id=req-preview-save" in page.url
        expect(
            page.locator("[data-request-id='req-preview-save']")
        ).to_be_visible()
        saved_detail = detail.inner_text()
        assert "已保存" in saved_detail
        expect(
            detail.locator(".detail-actions button:has-text('确认')")
        ).to_be_visible()
        expect(
            detail.locator(".detail-actions button:has-text('取消')")
        ).to_be_visible()
        expect(
            detail.locator(".detail-actions button:has-text('修改')")
        ).to_be_visible()
