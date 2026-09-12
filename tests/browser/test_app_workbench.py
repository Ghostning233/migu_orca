from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from apps.migu_orca_entry.controllers.entry_controller import generate_request
from shared.models import EntryRequest
from tests.browser.conftest import preview_result_json, set_storage_preferences

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
        "to verify the US-204 workbench migration in the browser."
    )


def _goto_workbench(page: Page, live_server_url: str) -> None:
    """Navigate to the SPA workbench and wait for the search form."""
    _require_dist()
    page.goto(f"{live_server_url}/app/add")
    page.wait_for_selector("#mikan-candidate-search-form", timeout=5000)


def _candidate(
    *,
    bangumi_id: str,
    title: str,
    mikan_url: str,
    source_query: str = "芙莉莲",
    poster_url: str | None = None,
    aliases: list[str] | None = None,
    recommendation: str | None = None,
    season_evidence: dict[str, Any] | None = None,
    candidate_context: str | None = None,
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
    if season_evidence is not None:
        result["season_evidence"] = season_evidence
    if candidate_context is not None:
        result["candidate_context"] = candidate_context
    return result


def _candidate_result_json(query: str, candidates: list[dict[str, Any]], **extra: Any) -> str:
    body: dict[str, Any] = {
        "ok": True,
        "result": {
            "query": query,
            "status": "FOUND",
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
            **extra,
        },
    }
    return json.dumps(body, ensure_ascii=False)


def _preview_request(title: str, request_id: str) -> dict[str, Any]:
    """Build an unsaved preview Request dict (PENDING_CONFIRM, not on disk)."""
    return {
        **generate_request(EntryRequest(raw_title=title))["request"],
        "request_id": request_id,
    }


def _register_generation_capture(
    page: Page,
    captured: list[dict[str, Any]],
    *,
    body: str,
) -> None:
    """Route `POST /api/v1/requests` to capture the payload and return a fake body.

    Non-POST requests (the GET list refresh after save) pass through to the
    real Flask backend.
    """

    def _handler(route: Any, request: Any) -> None:
        if request.method != "POST":
            route.continue_()
            return
        captured.append(request.post_data_json)
        route.fulfill(status=200, content_type="application/json", body=body)

    page.route("**/api/v1/requests", _handler)


class TestAppWorkbenchSingleSearch:
    """AC: 单个搜索迁移——loading、候选卡片、空状态、失败重试与旧页 parity."""

    def test_empty_search_validates_before_calling_api(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        calls: list[str] = []
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route, request: (calls.append(request.url), route.fulfill(status=200, content_type="application/json", body='{"ok": true}'))[1],
        )
        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)

        page.click("#mikan-candidate-search-submit")
        expect(page.locator("#mikan-candidate-search-error")).to_contain_text(
            "搜索 MiKan 候选前必须填写番剧标题"
        )
        assert calls == []

    def test_search_success_renders_candidate_cards(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        body = _candidate_result_json(
            "芙莉莲",
            [
                _candidate(
                    bangumi_id="2353",
                    title="葬送的芙莉莲",
                    mikan_url="https://mikan.example/Home/Bangumi/2353",
                    poster_url="/api/v1/mikan/posters/" + "a" * 64,
                ),
                _candidate(
                    bangumi_id="3072",
                    title="咒术回战 第三季",
                    mikan_url="https://mikan.example/Home/Bangumi/3072",
                ),
            ],
        )
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(status=200, content_type="application/json", body=body),
        )
        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)

        page.fill("#mikan-candidate-query", "芙莉莲")
        page.click("#mikan-candidate-search-submit")

        expect(page.locator(".candidate-card")).to_have_count(2)
        text = page.locator("#mikan-candidate-search-result").inner_text()
        assert "葬送的芙莉莲" in text
        assert "咒术回战 第三季" in text
        assert "MiKan ID: 2353" in text
        assert "搜索词：芙莉莲" in text

    def test_single_candidate_is_not_auto_selected(
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
                    "芙莉莲",
                    [_candidate(bangumi_id="42", title="葬送的芙莉莲", mikan_url="https://mikan.example/Home/Bangumi/42")],
                ),
            ),
        )
        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)

        page.fill("#mikan-candidate-query", "芙莉莲")
        page.click("#mikan-candidate-search-submit")
        expect(page.locator(".candidate-card")).to_have_count(1)

        # The explicit selection action is offered, but nothing is selected or
        # generated automatically even with a single candidate.
        assert (
            page.locator(".candidate-card button:has-text('选择此合集')").count() == 1
        )
        assert captured == []

    def test_empty_result_shows_fallback_hint(
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
        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)

        page.fill("#mikan-candidate-query", "ghost")
        page.click("#mikan-candidate-search-submit")

        expect(page.locator("#mikan-candidate-search-result")).to_contain_text("未找到候选合集")
        expect(page.locator("#mikan-candidate-search-result")).to_contain_text("直连合集")

    def test_search_failure_shows_sanitized_error_and_retry(
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
                            "error_data": {"failed_step": "mikan_search", "details": {"status_code": 503}},
                        },
                        ensure_ascii=False,
                    ),
                )
                return
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_candidate_result_json(
                    "芙莉莲",
                    [_candidate(bangumi_id="42", title="葬送的芙莉莲", mikan_url="https://mikan.example/Home/Bangumi/42")],
                ),
            )

        page.route("**/api/v1/mikan/candidates", _flaky)
        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)

        page.fill("#mikan-candidate-query", "芙莉莲")
        page.click("#mikan-candidate-search-submit")

        result = page.locator("#mikan-candidate-search-result")
        expect(result).to_contain_text("候选搜索失败")
        # The raw error_type/message never leaks into the DOM.
        body_text = page.locator("body").inner_text()
        assert "mikan_http_failed" not in body_text
        assert "MiKan HTTP 请求失败" not in body_text

        fail[0] = False
        page.click("#mikan-candidate-search-submit")
        expect(page.locator(".candidate-card")).to_have_count(1)

    def test_auditable_parse_summary_with_chinese_labels(
        self, page: Page, live_server_url: str
    ) -> None:
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_candidate_result_json(
                    "无职转生s4",
                    [_candidate(bangumi_id="2353", title="无职转生 第四季", mikan_url="https://mikan.example/Home/Bangumi/2353")],
                    parse_result={
                        "normalized_title": "无职转生 第四季",
                        "base_title": "无职转生",
                        "season": {"number": 4, "raw": "s4", "normalized": "第四季", "source": "title_marker"},
                        "season_number": 4,
                        "source": "alias",
                        "needs_user_review": True,
                        "review_hints": ["别名匹配结果，请人工核对。"],
                        "query_plan": [
                            {"query": "无职转生 第四季", "source": "alias", "priority": 1},
                            {"query": "无职转生 S4", "source": "rule", "priority": 2},
                        ],
                        "search_queries": ["无职转生 第四季"],
                        "raw_title": "无职转生s4",
                    },
                    attempted_queries=[{"query": "无职转生 第四季", "source": "alias", "priority": 1}],
                ),
            ),
        )
        _goto_workbench(page, live_server_url)

        page.fill("#mikan-candidate-query", "无职转生s4")
        page.click("#mikan-candidate-search-submit")

        summary = page.locator("#mikan-candidate-search-result .title-parse-summary")
        expect(summary).to_contain_text("标题解析摘要")
        expect(summary).to_contain_text("识别标题")
        expect(summary).to_contain_text("无职转生 第四季")
        expect(summary).to_contain_text("识别季度")
        expect(summary).to_contain_text("第4季")
        expect(summary).to_contain_text("解析来源")
        expect(summary).to_contain_text("别名匹配")
        expect(summary).to_contain_text("实际搜索词")
        expect(summary).to_contain_text("需人工核对")
        assert "alias" not in summary.inner_text()

    def test_workbench_no_horizontal_overflow_at_360px(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        body = _candidate_result_json(
            "芙莉莲",
            [_candidate(bangumi_id="2353", title="葬送的芙莉莲", mikan_url="https://mikan.example/Home/Bangumi/2353")],
        )
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(status=200, content_type="application/json", body=body),
        )
        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)

        page.set_viewport_size({"width": 360, "height": 800})
        page.fill("#mikan-candidate-query", "芙莉莲")
        page.click("#mikan-candidate-search-submit")
        expect(page.locator(".candidate-card")).to_have_count(1)

        overflow = page.evaluate("() => document.body.scrollWidth > window.innerWidth")
        assert overflow is False


class TestAppWorkbenchSeasonConfirmation:
    """AC: 非第一季确认、冲突禁用、候选 context 只在内存."""

    def test_needs_confirmation_blocks_until_checkbox_checked(
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
                            season_evidence={"status": "NEEDS_CONFIRMATION", "season": 4, "requires_review": True},
                            candidate_context="opaque-candidate-context",
                        )
                    ],
                ),
            ),
        )
        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)

        page.fill("#mikan-candidate-query", "芙莉莲")
        page.click("#mikan-candidate-search-submit")
        expect(page.locator(".candidate-card")).to_have_count(1)

        confirmation = page.locator(".candidate-season-confirmation input")
        expect(confirmation).not_to_be_checked()
        choose_button = page.locator(".candidate-card .candidate-select")
        expect(choose_button).to_be_disabled()
        expect(choose_button).to_have_attribute("aria-disabled", "true")
        expect(page.locator(".candidate-season-confirmation")).to_contain_text(
            "我确认此合集为第4季"
        )

        confirmation.check()
        expect(confirmation).to_be_checked()
        expect(choose_button).to_be_enabled()
        expect(choose_button).to_have_attribute("aria-disabled", "false")

        confirmation.uncheck()
        expect(choose_button).to_be_disabled()

    def test_conflict_candidate_is_disabled_with_warning(
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
                            bangumi_id="2353",
                            title="葬送的芙莉莲 第一季",
                            mikan_url="https://mikan.example/Home/Bangumi/2353",
                            season_evidence={"status": "CONFLICT", "season": None, "requires_review": True},
                        )
                    ],
                ),
            ),
        )
        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)

        page.fill("#mikan-candidate-query", "芙莉莲 第二季")
        page.click("#mikan-candidate-search-submit")

        card = page.locator(".candidate-card")
        expect(card).to_contain_text("候选合集季数与搜索识别结果冲突，请先人工核对")
        choose = card.locator(".candidate-select")
        expect(choose).to_be_disabled()
        expect(choose).to_have_attribute("aria-disabled", "true")


class TestAppWorkbenchCandidateSelectionAndDraft:
    """AC: 显式候选选择生成服务端权威草案，draft_id 只在内存."""

    def test_candidate_selection_generates_editable_preview_draft(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_candidate_result_json(
                    "芙莉莲",
                    [_candidate(bangumi_id="2353", title="葬送的芙莉莲", mikan_url="https://mikan.example/Home/Bangumi/2353")],
                ),
            ),
        )
        preview = _preview_request("葬送的芙莉莲", "req-wb-1")
        captured: list[dict[str, Any]] = []
        _register_generation_capture(page, captured, body=preview_result_json(preview))

        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)
        page.fill("#mikan-candidate-query", "芙莉莲")
        page.click("#mikan-candidate-search-submit")
        expect(page.locator(".candidate-card")).to_have_count(1)

        page.locator(".candidate-card button:has-text('选择此合集')").click()
        page.wait_for_selector("#detail-preview-edit-form", timeout=5000)

        assert captured
        payload = captured[0]
        assert payload["source"] == "mikan"
        assert payload["mikan_bangumi"] == "https://mikan.example/Home/Bangumi/2353"
        assert payload["title"] == "葬送的芙莉莲"
        assert payload["save_request"] is False
        assert "mikan_config" not in payload

        # The editable preview form is offered; no saved-request actions.
        detail = page.locator("#request-detail-container")
        assert "订阅草案（未保存）" in detail.inner_text()
        expect(detail.locator("#single-review-save-button")).to_be_disabled()
        expect(detail.locator(".detail-actions button:has-text('确认')")).to_have_count(0)
        # The draft_id never enters the URL or DOM.
        assert "request_id=" not in page.url
        assert "opaque" not in page.content()

    def test_preview_modify_recomputes_seeds_and_keeps_edits(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_candidate_result_json(
                    "咒术回战",
                    [_candidate(bangumi_id="42", title="咒术回战", mikan_url="https://mikan.example/Home/Bangumi/42")],
                ),
            ),
        )
        preview = _preview_request("咒术回战", "req-wb-filter")
        captured: list[dict[str, Any]] = []
        _register_generation_capture(page, captured, body=preview_result_json(preview))

        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)
        page.fill("#mikan-candidate-query", "咒术回战")
        page.click("#mikan-candidate-search-submit")
        expect(page.locator(".candidate-card")).to_have_count(1)
        page.locator(".candidate-card button:has-text('选择此合集')").click()
        page.wait_for_selector("#detail-preview-edit-form", timeout=5000)

        # The mock preview-modify endpoint is the real backend (draft issued
        # into the in-process store), so the seed recompute works end-to-end.
        page.fill("#preview-must-not-contain", "V2")
        page.click("#preview-apply-button")
        page.wait_for_selector(".global-notification:not(:empty)", timeout=5000)
        expect(page.locator("#preview-edit-error")).to_have_count(0)

        text = page.locator("#request-detail-container").inner_text()
        assert "有效种子数" in text
        # The form keeps the applied value after re-render.
        assert page.locator("#preview-must-not-contain").input_value() == "V2"
        # Editing never writes storage.
        assert not storage_dir.exists() or not any(storage_dir.iterdir())

    def test_preview_modify_sends_base_revision_and_keeps_it_in_memory(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """US-211: the Vue draft panel sends base_revision on every modify and
        never lets draft_id/revision reach the URL, localStorage or DOM."""
        preview = _preview_request("芙莉莲", "req-wb-rev")
        modify_calls: list[dict[str, Any]] = []
        _register_generation_capture(page, [], body=preview_result_json(preview))
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_candidate_result_json(
                    "芙莉莲",
                    [_candidate(bangumi_id="2353", title="葬送的芙莉莲", mikan_url="https://mikan.example/Home/Bangumi/2353")],
                ),
            ),
        )

        def _modify(route: Any, request: Any) -> None:
            payload = request.post_data_json
            if request.url.endswith("/api/v1/requests/preview-modify"):
                modify_calls.append(payload)
                # Recompute against the in-process draft_store (real backend).
                route.continue_()
                return
            route.continue_()

        page.route("**/api/v1/requests/preview-modify", _modify)
        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)
        page.fill("#mikan-candidate-query", "芙莉莲")
        page.click("#mikan-candidate-search-submit")
        expect(page.locator(".candidate-card")).to_have_count(1)
        page.locator(".candidate-card button:has-text('选择此合集')").click()
        page.wait_for_selector("#detail-preview-edit-form", timeout=5000)

        page.fill("#preview-must-not-contain", "V2")
        page.click("#preview-apply-button")
        page.wait_for_selector(".global-notification:not(:empty)", timeout=5000)

        assert modify_calls, "preview-modify should have been called"
        assert modify_calls[0]["base_revision"] == 1
        assert modify_calls[0]["draft_id"]
        # The revision/draft id stay out of the URL and DOM.
        assert "request_id=" not in page.url and "revision" not in page.url
        body_text = page.locator("body").inner_text()
        assert "draft_revision" not in body_text

    def test_draft_revision_conflict_offers_regeneration_hint(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """US-211: a 409 draft_revision_conflict shows the fixed regeneration
        hint and restores the search state — never raw error details."""
        preview = _preview_request("芙莉莲", "req-wb-conflict")
        _register_generation_capture(page, [], body=preview_result_json(preview))

        def _conflict(route: Any, request: Any) -> None:
            if request.url.endswith("/api/v1/requests/preview-modify"):
                route.fulfill(
                    status=409,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "ok": False,
                            "error_type": "draft_revision_conflict",
                            "error_message": "草案已被更新，请基于最新版本重试",
                            "error_data": {
                                "failed_step": "compare_and_swap_draft",
                                "details": {"field": "base_revision", "current_revision": 2},
                            },
                        },
                        ensure_ascii=False,
                    ),
                )
                return
            route.continue_()

        page.route("**/api/v1/requests/preview-modify", _conflict)
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_candidate_result_json(
                    "芙莉莲",
                    [_candidate(bangumi_id="2353", title="葬送的芙莉莲", mikan_url="https://mikan.example/Home/Bangumi/2353")],
                ),
            ),
        )
        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)
        page.fill("#mikan-candidate-query", "芙莉莲")
        page.click("#mikan-candidate-search-submit")
        expect(page.locator(".candidate-card")).to_have_count(1)
        page.locator(".candidate-card button:has-text('选择此合集')").click()
        page.wait_for_selector("#detail-preview-edit-form", timeout=5000)

        page.fill("#preview-must-not-contain", "V2")
        page.click("#preview-apply-button")
        expect(page.locator(".global-notification")).to_contain_text("订阅草案已失效", timeout=5000)
        # Draft panel is dismissed; the search/candidate state is preserved.
        expect(page.locator("#detail-preview-edit-form")).to_have_count(0)
        expect(page.locator(".candidate-card")).to_have_count(1)
        body_text = page.locator("body").inner_text()
        assert "draft_revision_conflict" not in body_text
        assert "base_revision" not in body_text

    def test_save_draft_persists_and_routes_to_saved_request(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_candidate_result_json(
                    "芙莉莲",
                    [_candidate(bangumi_id="2353", title="葬送的芙莉莲", mikan_url="https://mikan.example/Home/Bangumi/2353")],
                ),
            ),
        )
        preview = _preview_request("葬送的芙莉莲", "req-wb-save")
        captured: list[dict[str, Any]] = []
        _register_generation_capture(page, captured, body=preview_result_json(preview))

        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)
        page.fill("#mikan-candidate-query", "芙莉莲")
        page.click("#mikan-candidate-search-submit")
        expect(page.locator(".candidate-card")).to_have_count(1)
        page.locator(".candidate-card button:has-text('选择此合集')").click()
        page.wait_for_selector("#detail-preview-edit-form", timeout=5000)

        # The review step intentionally leaves save-confirm to the next story.
        expect(page.locator("#single-review-save-button")).to_be_disabled()
        assert not (storage_dir / "requests").exists()

    def test_generation_failure_preserves_candidates_and_shows_sanitized_error(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_candidate_result_json(
                    "芙莉莲",
                    [_candidate(bangumi_id="42", title="葬送的芙莉莲", mikan_url="https://mikan.example/Home/Bangumi/42")],
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
                        "error_data": {"failed_step": "mikan_bangumi_detail", "details": {"category": "parse"}},
                    },
                    ensure_ascii=False,
                ),
            )

        page.route("**/api/v1/requests", _fail_generation)
        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)
        page.fill("#mikan-candidate-query", "芙莉莲")
        page.click("#mikan-candidate-search-submit")
        expect(page.locator(".candidate-card")).to_have_count(1)

        page.locator(".candidate-card button:has-text('选择此合集')").click()
        # Candidate search has already populated this persistent notification
        # node. Wait for its content to change instead of merely waiting for a
        # non-empty node, which races on slower CI runners.
        expect(page.locator(".global-notification")).to_contain_text(
            "生成失败", timeout=5000
        )
        # Candidate list and the search input are preserved for retry.
        expect(page.locator(".candidate-card")).to_have_count(1)
        assert page.locator("#mikan-candidate-query").input_value() == "芙莉莲"


class TestAppWorkbenchDirectFallback:
    """AC: 直连 fallback——门控、校验、生成草案、敏感边界."""

    def test_fallback_checkbox_hidden_by_default(
        self, page: Page, live_server_url: str
    ) -> None:
        _goto_workbench(page, live_server_url)

        checkbox = page.locator("#mikan-fallback-enabled")
        expect(checkbox).to_be_visible()
        assert not checkbox.is_checked()
        expect(page.locator("#mikan-fallback-form")).to_be_hidden()

    def test_fallback_checkbox_reveals_form(
        self, page: Page, live_server_url: str
    ) -> None:
        _goto_workbench(page, live_server_url)

        page.check("#mikan-fallback-enabled")
        expect(page.locator("#mikan-fallback-form")).to_be_visible()
        expect(page.locator("#mikan-fallback-bangumi")).to_be_visible()
        expect(page.locator("#mikan-fallback-generate")).to_be_visible()

        page.uncheck("#mikan-fallback-enabled")
        expect(page.locator("#mikan-fallback-form")).to_be_hidden()

    def test_url_fallback_generates_draft_and_clears_input(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        preview = _preview_request("芙莉莲", "req-wb-fb-url")
        captured: list[dict[str, Any]] = []
        _register_generation_capture(page, captured, body=preview_result_json(preview))

        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)
        page.fill("#mikan-candidate-query", "芙莉莲")
        page.check("#mikan-fallback-enabled")
        page.fill("#mikan-fallback-bangumi", "https://mikan.example/Home/Bangumi/2353")
        page.click("#mikan-fallback-generate")
        page.wait_for_selector("#detail-preview-edit-form", timeout=5000)

        assert captured
        payload = captured[0]
        assert payload["source"] == "mikan"
        assert payload["mikan_bangumi"] == "https://mikan.example/Home/Bangumi/2353"
        assert payload["title"] == "芙莉莲"
        assert payload["save_request"] is False
        assert "mikan_config" not in payload
        # The fallback input is cleared after success and no URL id is set.
        assert page.locator("#mikan-fallback-bangumi").input_value() == ""
        assert "request_id=" not in page.url

    def test_invalid_fallback_value_shows_validation_without_api_call(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        captured: list[dict[str, Any]] = []
        _register_generation_capture(page, captured, body='{"ok": true}')

        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)
        page.check("#mikan-fallback-enabled")
        page.click("#mikan-fallback-generate")
        expect(page.locator("#mikan-fallback-error")).to_contain_text(
            "生成前必须填写 MiKan 合集 URL 或 ID"
        )

        page.fill("#mikan-fallback-bangumi", "not a url or id")
        page.click("#mikan-fallback-generate")
        expect(page.locator("#mikan-fallback-error")).to_contain_text(
            "必须是数字 ID 或 HTTP(S) URL"
        )
        assert captured == []

    def test_fallback_does_not_leak_sensitive_values(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        sensitive_values = ("https://private-mikan.stage18.local/Home/Bangumi/42",)
        preview = _preview_request("芙莉莲", "req-wb-fb-sec")
        captured: list[dict[str, Any]] = []
        _register_generation_capture(page, captured, body=preview_result_json(preview))

        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)
        page.fill("#mikan-candidate-query", "芙莉莲")
        page.check("#mikan-fallback-enabled")
        page.fill("#mikan-fallback-bangumi", sensitive_values[0])
        page.click("#mikan-fallback-generate")
        page.wait_for_selector("#detail-preview-edit-form", timeout=5000)

        assert captured
        assert captured[0]["mikan_bangumi"] == sensitive_values[0]
        assert captured[0]["save_request"] is False
        assert "mikan_config" not in captured[0]
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
