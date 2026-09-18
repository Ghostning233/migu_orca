from __future__ import annotations

import json
import os
import time
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
    total_episodes: int | None = None,
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
    if total_episodes is not None:
        result["total_episodes"] = total_episodes
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

    def test_single_entry_has_one_task_heading_steps_and_search_summary(
        self, page: Page, live_server_url: str
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
        _goto_workbench(page, live_server_url)

        expect(page.locator("#workbench-heading")).to_have_text("添加番剧")
        expect(page.locator(".journey-steps")).to_contain_text("输入名称")
        expect(page.locator(".journey-steps")).to_contain_text("选择真实合集")
        expect(page.locator(".journey-steps")).to_contain_text("审核并保存确认")
        expect(page.locator("#mikan-candidate-search-submit")).to_contain_text("搜索候选合集")
        assert "外部提交" not in page.locator("body").inner_text()

        page.fill("#mikan-candidate-query", "芙莉莲")
        page.click("#mikan-candidate-search-submit")
        expect(page.locator(".search-summary-actions")).to_contain_text("搜索摘要")
        expect(page.locator("#mikan-edit-search")).to_be_visible()
        expect(page.locator("#mikan-candidate-query")).to_have_count(0)
        page.click("#mikan-edit-search")
        expect(page.locator("#mikan-candidate-query")).to_be_focused()

    def test_shell_focuses_single_anime_input_on_entry(self, page: Page, live_server_url: str) -> None:
        _goto_workbench(page, live_server_url)
        expect(page.locator("#mikan-candidate-query")).to_be_focused()

    def test_empty_search_is_disabled_before_calling_api(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        calls: list[str] = []
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route, request: (calls.append(request.url), route.fulfill(status=200, content_type="application/json", body='{"ok": true}'))[1],
        )
        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)

        expect(page.locator("#mikan-candidate-search-submit")).to_be_disabled()
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
                    total_episodes=28,
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
        # F4/US-345: 默认层只放公开决策证据（封面/标题/季度证据/总集数与选择
        # 动作）；合集编号与解析搜索词是诊断信息，折叠在「高级信息」内。
        assert "季度证据" in text
        # 候选默认层只放公开决策证据：封面、标题、季度证据、总集数与选择动作。
        assert "总集数：28 集" in text
        assert "选择此合集" in text
        expect(page.locator(".candidate-card").first.locator(".candidate-poster")).to_have_count(1)
        assert "MiKan ID: 2353" not in text
        assert "匹配搜索词" not in text

        second_card = page.locator(".candidate-card").nth(1)
        assert "3072" not in second_card.inner_text()
        second_card.locator("details.candidate-advanced summary").click()
        expect(second_card.locator("details.candidate-advanced")).to_have_attribute("open", "")
        assert "3072" in second_card.inner_text()

    def test_initial_page_has_no_empty_result_panel_or_fallback_entry(
        self, page: Page, live_server_url: str
    ) -> None:
        """F4/US-345: 初始页只聚焦名称输入与模式切换."""
        _goto_workbench(page, live_server_url)

        expect(page.locator("#mikan-candidate-search-form")).to_be_visible()
        expect(page.locator("#mikan-candidate-search-result")).to_have_count(0)
        expect(page.locator("#mikan-fallback-enabled")).to_have_count(0)
        expect(page.locator("#mikan-fallback-form")).to_have_count(0)
        assert "输入番剧标题后搜索候选合集" not in page.locator("body").inner_text()
        expect(page.locator("#mikan-candidate-search-submit")).to_be_disabled()
        expect(page.locator("#mikan-candidate-query")).to_be_focused()

    def test_fallback_entry_appears_only_after_a_candidate_less_search(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """F4/US-345: 直连合集是无结果后的次级救援入口，人工选择合集不变."""
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

        expect(page.locator("#mikan-fallback-enabled")).to_have_count(0)
        page.fill("#mikan-candidate-query", "芙莉莲")
        page.click("#mikan-candidate-search-submit")
        expect(page.locator(".candidate-card")).to_have_count(1)
        # 有候选时不提供直连救援入口，人工选择路径保持原样。
        expect(page.locator("#mikan-fallback-enabled")).to_have_count(0)

        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_candidate_result_json("ghost", []),
            ),
        )
        page.click("#mikan-edit-search")
        page.fill("#mikan-candidate-query", "ghost")
        page.click("#mikan-candidate-search-submit")
        expect(page.locator("#mikan-candidate-search-result")).to_contain_text("未找到候选合集")
        expect(page.locator("#mikan-fallback-enabled")).to_be_visible()
        expect(page.locator("#mikan-fallback-form")).to_be_hidden()

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

    def test_generated_failed_result_is_not_mislabeled_as_empty(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        console_messages: list[str] = []
        page.on("console", lambda message: console_messages.append(message.text))
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_candidate_result_json(
                    "芙莉莲",
                    [],
                    status="FAILED",
                    error={
                        "error_type": "mikan_timeout",
                        "error_message": "raw https://secret.example/rss?password=password-canary",
                        "details": {"category": "mikan_search"},
                    },
                ),
            ),
        )
        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)

        page.fill("#mikan-candidate-query", "芙莉莲")
        page.click("#mikan-candidate-search-submit")

        result = page.locator("#mikan-candidate-search-result")
        expect(result).to_contain_text("MiKan 上游响应超时")
        expect(result).not_to_contain_text("未找到候选合集")
        body_text = page.locator("body").inner_text()
        assert "secret.example" not in body_text
        assert "password-canary" not in body_text
        assert "secret.example" not in page.url
        assert "password-canary" not in str(page.evaluate("() => history.state"))
        assert "secret.example" not in str(page.evaluate("() => JSON.stringify(localStorage) + JSON.stringify(sessionStorage)"))
        assert all("secret.example" not in message and "password-canary" not in message for message in console_messages)

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
        # F4/US-345: 解析诊断默认折叠（不在默认层），展开后仍完整可读。
        assert summary.evaluate("el => el.open") is False
        expect(summary.locator("summary")).to_contain_text("标题解析摘要")
        assert "识别标题" not in page.locator("#mikan-candidate-search-result").inner_text()
        summary.locator("summary").click()
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
        assert payload["mikan_bangumi"] == "https://mikan.example/Home/Bangumi/2353"
        assert payload["title"] == "葬送的芙莉莲"
        assert "mikan_config" not in payload

        # The editable preview form and atomic save-confirm action are offered.
        detail = page.locator("#request-detail-container")
        assert "订阅草案（未保存）" in detail.inner_text()
        expect(detail.locator("#single-review-save-button")).to_be_enabled()
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
        # Settings initialization may create storage files, but this journey
        # must never persist MiKan configuration or the search query.
        stored = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in storage_dir.rglob("*")
            if path.is_file()
        ) if storage_dir.exists() else ""
        assert "mikan_config" not in stored
        assert "咒术回战" not in stored

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

    def test_held_preview_modify_restores_save_confirm_with_new_revision(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """US-341 (FE-01): after a successful preview-modify the save action and
        its in-place reason recover together from one reactive source, and the
        next save-confirm carries the same draft capability at revision 2."""
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_candidate_result_json(
                    "芙莉莲",
                    [
                        _candidate(
                            bangumi_id="2353", title="葬送的芙莉莲", mikan_url="https://mikan.example/Home/Bangumi/2353"
                        )
                    ],
                ),
            ),
        )
        preview = _preview_request("芙莉莲", "req-wb-341")
        generation_body = preview_result_json(preview)
        draft_id = json.loads(generation_body)["result"]["draft_id"]
        _register_generation_capture(page, [], body=generation_body)

        held: list[Any] = []
        modify_bodies: list[dict[str, Any]] = []

        def _hold_modify(route: Any, request: Any) -> None:
            if request.url.endswith("/api/v1/requests/preview-modify"):
                # Store the route and assert the in-flight UI first. Sleeping in
                # this handler would block Playwright's dispatcher thread and
                # hide the very loading state under test.
                modify_bodies.append(request.post_data_json)
                held.append(route)
                return
            route.continue_()

        save_bodies: list[dict[str, Any]] = []

        def _save(route: Any, request: Any) -> None:
            if request.url.endswith("/api/v1/requests/save-confirm"):
                save_bodies.append(request.post_data_json)
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "ok": True,
                            "result": {
                                "outcome": "CONFIRMED",
                                "request": {"request_id": "req-wb-341"},
                                "summary": {"request_id": "req-wb-341", "status": "ACCEPTED"},
                                "handoff": {
                                    "request_id": "req-wb-341",
                                    "status": "CONFIRMED",
                                    "next_action": "TRACKING",
                                    "tracking_id": "tracking-wb-341",
                                    "tracking_status": "PENDING_SUBMIT",
                                    "tracking_ready": True,
                                    "safe_message": None,
                                },
                            },
                        },
                        ensure_ascii=False,
                    ),
                )
                return
            route.continue_()

        page.route("**/api/v1/requests/preview-modify", _hold_modify)
        page.route("**/api/v1/requests/save-confirm", _save)
        page.route(
            "**/api/v1/tracking/items*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": True,
                        "result": {
                            "items": [],
                            "summary": {
                                "total": 0,
                                "pending": 0,
                                "processing": 0,
                                "active": 0,
                                "needs_attention": 0,
                                "unreadable": 0,
                            },
                            "warnings": [],
                        },
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        console_messages: list[str] = []
        page.on("console", lambda message: console_messages.append(message.text))

        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)
        page.fill("#mikan-candidate-query", "芙莉莲")
        page.click("#mikan-candidate-search-submit")
        expect(page.locator(".candidate-card")).to_have_count(1)
        page.locator(".candidate-card button:has-text('选择此合集')").click()
        page.wait_for_selector("#detail-preview-edit-form", timeout=5000)

        save_button = page.locator("#single-review-save-button")
        note = page.locator("#single-review-save-blockers")
        expect(save_button).to_be_enabled()
        expect(note).to_contain_text("保存并确认可用")

        # A pending form edit blocks the save with its own reason.
        page.fill("#preview-must-not-contain", "V2")
        expect(save_button).to_be_disabled()
        expect(note).to_contain_text("有尚未应用的编辑")
        expect(note).not_to_contain_text("保存并确认可用")

        page.click("#preview-apply-button")
        deadline = time.time() + 5.0
        while not held and time.time() < deadline:
            page.wait_for_timeout(50)
        assert held, "held preview-modify route was not reached"

        # In flight: still blocked, and the button never claims availability.
        expect(save_button).to_be_disabled()
        expect(note).to_contain_text("正在重新计算订阅方案")
        expect(note).not_to_contain_text("保存并确认可用")

        # Fulfil against the real backend: revision 2 with the applied rule.
        held[0].continue_()
        expect(note).to_contain_text("保存并确认可用", timeout=5000)
        expect(save_button).to_be_enabled()
        expect(note).not_to_contain_text("正在重新计算订阅方案")
        expect(note).not_to_contain_text("有尚未应用的编辑")

        assert modify_bodies and modify_bodies[0]["base_revision"] == 1
        assert modify_bodies[0]["draft_id"] == draft_id

        save_button.click()
        deadline = time.time() + 5.0
        while not save_bodies and time.time() < deadline:
            page.wait_for_timeout(50)
        assert save_bodies, "save-confirm was not called"
        body = save_bodies[0]
        # Same server-issued draft capability, latest revision, in-memory key.
        assert body["draft_id"] == draft_id
        assert body["base_revision"] == 2
        assert body["idempotency_key"]
        assert "request" not in body
        assert "summary" not in body

        # Sensitive canary: the draft capability, revision and draft payload
        # stay out of the URL, browser storage, DOM and console.
        page.wait_for_url("**/app/tracking?tracking_id=tracking-wb-341", timeout=5000)
        browser_state = page.evaluate(
            """() => ({
                url: window.location.href,
                localStorage: JSON.stringify(window.localStorage),
                sessionStorage: JSON.stringify(window.sessionStorage),
                bodyText: document.body.innerText,
            })"""
        )
        for value in (draft_id, "base_revision", "draft_revision", "idempotency_key"):
            assert value not in browser_state["url"]
            assert value not in browser_state["localStorage"]
            assert value not in browser_state["sessionStorage"]
            assert value not in browser_state["bodyText"]
        assert all(draft_id not in message for message in console_messages)

    def test_preview_modify_zero_effective_resources_blocks_save_with_reason(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """US-341: a modify that leaves no effective resource blocks the save
        with a specific reason instead of a grey button that claims 可用."""
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
        preview = _preview_request("咒术回战", "req-wb-341-zero")
        generation_body = preview_result_json(preview)
        draft_id = json.loads(generation_body)["result"]["draft_id"]
        summary = json.loads(generation_body)["result"]["summary"]
        _register_generation_capture(page, [], body=generation_body)

        empty_request = json.loads(json.dumps(preview))
        empty_request["source_info"]["rss_sources"] = []
        empty_request["confirmable_config"]["effective_seed_names"] = []
        empty_request["confirmable_config"]["filter_rule"]["must_not_contain"] = "V2"

        def _empty(route: Any, request: Any) -> None:
            if request.url.endswith("/api/v1/requests/preview-modify"):
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "ok": True,
                            "result": {
                                "request": empty_request,
                                "summary": summary,
                                "draft_id": draft_id,
                                "draft_revision": 2,
                            },
                        },
                        ensure_ascii=False,
                    ),
                )
                return
            route.continue_()

        page.route("**/api/v1/requests/preview-modify", _empty)
        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)
        page.fill("#mikan-candidate-query", "咒术回战")
        page.click("#mikan-candidate-search-submit")
        expect(page.locator(".candidate-card")).to_have_count(1)
        page.locator(".candidate-card button:has-text('选择此合集')").click()
        page.wait_for_selector("#detail-preview-edit-form", timeout=5000)

        save_button = page.locator("#single-review-save-button")
        note = page.locator("#single-review-save-blockers")
        page.fill("#preview-must-not-contain", "V2")
        page.click("#preview-apply-button")

        expect(note).to_contain_text("没有有效资源", timeout=5000)
        expect(save_button).to_be_disabled()
        expect(note).not_to_contain_text("保存并确认可用")

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
        page.route(
            "**/api/v1/requests/save-confirm",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "ok": True,
                    "result": {
                        "outcome": "CONFIRMED",
                        "request": {"request_id": "req-wb-save"},
                        "summary": {"request_id": "req-wb-save", "status": "ACCEPTED"},
                        "handoff": {
                            "request_id": "req-wb-save",
                            "status": "CONFIRMED",
                            "next_action": "TRACKING",
                            "tracking_id": "tracking-wb-save",
                            "tracking_status": "PENDING_SUBMIT",
                            "tracking_ready": True,
                            "safe_message": None,
                        },
                    },
                }, ensure_ascii=False),
            ),
        )
        page.route(
            "**/api/v1/tracking/items/tracking-wb-save*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "ok": True,
                    "result": {
                        "tracking_id": "tracking-wb-save", "request_id": "req-wb-save",
                        "title": "葬送的芙莉莲", "season": 1, "subtitle_group": "喵萌奶茶屋",
                        "poster_path": None, "status": "PENDING_SUBMIT", "status_label": "待提交",
                        "status_group": "PENDING", "available_actions": [], "valid_resource_count": 1,
                        "updated_episode": None, "updated_episode_status": "NOT_IMPLEMENTED",
                        "total_episodes": 28, "revision": 1, "origin": "single", "batch_id": None,
                        "created_at": "2026-09-12T00:00:00Z", "updated_at": None, "last_synced_at": None,
                        "safe_info": None, "current_operation": None, "revalidation_issues": [],
                        "external_mapping": None, "audit_events": [], "warnings": [],
                    },
                }, ensure_ascii=False),
            ),
        )
        # US-316: the handoff lands on the formal tracking screen, whose list is
        # the authority for the selection it just made.
        page.route(
            "**/api/v1/tracking/items*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "ok": True,
                    "result": {
                        "items": [{
                            "tracking_id": "tracking-wb-save", "request_id": "req-wb-save",
                            "title": "葬送的芙莉莲", "season": 1, "subtitle_group": "喵萌奶茶屋",
                            "poster_path": None, "status": "PENDING_SUBMIT", "status_label": "待提交",
                            "status_group": "PENDING", "available_actions": [], "valid_resource_count": 1,
                            "updated_episode": None, "updated_episode_status": "NOT_IMPLEMENTED",
                            "total_episodes": 28, "revision": 1,
                            "updated_at": "2026-09-13T00:00:00+00:00",
                        }],
                        "summary": {
                            "total": 1, "pending": 1, "processing": 0,
                            "active": 0, "needs_attention": 0, "unreadable": 0,
                        },
                        "warnings": [],
                    },
                }, ensure_ascii=False),
            ),
        )

        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)
        page.fill("#mikan-candidate-query", "芙莉莲")
        page.click("#mikan-candidate-search-submit")
        expect(page.locator(".candidate-card")).to_have_count(1)
        page.locator(".candidate-card button:has-text('选择此合集')").click()
        page.wait_for_selector("#detail-preview-edit-form", timeout=5000)

        # The review step owns the atomic save-confirm action.
        expect(page.locator("#single-review-save-button")).to_be_enabled()
        page.locator("#single-review-save-button").click()
        page.wait_for_url("**/app/tracking?tracking_id=tracking-wb-save")
        # US-316: the handoff opens the formal tracking inspector (read-only —
        # saving a draft never creates an external Auto Bangumi subscription).
        inspector = page.locator(".tracking-inspector-detail")
        expect(inspector).to_contain_text("葬送的芙莉莲", timeout=5000)
        expect(inspector).to_contain_text("待提交")
        assert page.locator("#batch-queue-list").count() == 0
        assert page.url.endswith("/app/tracking?tracking_id=tracking-wb-save")
        assert not list((storage_dir / "requests").glob("*.json"))

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
        # Candidate list is preserved; the collapsed search summary exposes
        # an explicit edit action before the input is shown again.
        expect(page.locator(".candidate-card")).to_have_count(1)
        page.locator("#mikan-edit-search").click()
        assert page.locator("#mikan-candidate-query").input_value() == "芙莉莲"


class TestAppWorkbenchDirectFallback:
    """AC: 直连 fallback——门控、校验、生成草案、敏感边界."""

    @staticmethod
    def _reach_fallback_entry(page: Page, query: str = "芙莉莲") -> None:
        """F4/US-345: 直连合集只在搜索无结果后出现，先做一次空候选搜索."""
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_candidate_result_json(query, []),
            ),
        )
        page.fill("#mikan-candidate-query", query)
        page.click("#mikan-candidate-search-submit")
        expect(page.locator("#mikan-fallback-enabled")).to_be_visible()

    def test_fallback_checkbox_hidden_by_default(
        self, page: Page, live_server_url: str
    ) -> None:
        _goto_workbench(page, live_server_url)

        # F4/US-345: 未搜索时没有直连入口，也没有空结果大面板。
        expect(page.locator("#mikan-fallback-enabled")).to_have_count(0)
        expect(page.locator("#mikan-candidate-search-result")).to_have_count(0)

        self._reach_fallback_entry(page)

        checkbox = page.locator("#mikan-fallback-enabled")
        expect(checkbox).to_be_visible()
        assert not checkbox.is_checked()
        expect(page.locator("#mikan-fallback-form")).to_be_hidden()

    def test_fallback_checkbox_reveals_form(
        self, page: Page, live_server_url: str
    ) -> None:
        _goto_workbench(page, live_server_url)
        self._reach_fallback_entry(page)

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
        self._reach_fallback_entry(page)
        page.check("#mikan-fallback-enabled")
        page.fill("#mikan-fallback-bangumi", "https://mikan.example/Home/Bangumi/2353")
        page.click("#mikan-fallback-generate")
        page.wait_for_selector("#detail-preview-edit-form", timeout=5000)

        assert captured
        payload = captured[0]
        assert payload["mikan_bangumi"] == "https://mikan.example/Home/Bangumi/2353"
        assert payload["title"] == "芙莉莲"
        assert "mikan_config" not in payload
        # F4/US-345: 草案替换整个搜索区，直连输入不会残留到审核步骤，
        # URL 里也不会带上任何编号。
        expect(page.locator("#mikan-fallback-bangumi")).to_have_count(0)
        expect(page.locator("#mikan-candidate-search-result")).to_have_count(0)
        assert "request_id=" not in page.url

    def test_invalid_fallback_value_shows_validation_without_api_call(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        captured: list[dict[str, Any]] = []
        _register_generation_capture(page, captured, body='{"ok": true}')

        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)
        self._reach_fallback_entry(page)
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
        self._reach_fallback_entry(page)
        page.check("#mikan-fallback-enabled")
        page.fill("#mikan-fallback-bangumi", sensitive_values[0])
        page.click("#mikan-fallback-generate")
        page.wait_for_selector("#detail-preview-edit-form", timeout=5000)

        assert captured
        assert captured[0]["mikan_bangumi"] == sensitive_values[0]
        assert "mikan_config" not in captured[0]
        expect(page.locator("#mikan-fallback-bangumi")).to_have_count(0)
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


def _batch_found_item(
    item_id: str, raw_title: str, candidates: list[dict[str, Any]]
) -> dict[str, Any]:
    """A FOUND batch item carrying its candidate list (no draft yet)."""
    return {
        "item_id": item_id,
        "raw_title": raw_title,
        "status": "FOUND",
        "canonical_title_candidates": [],
        "season_hint": None,
        "search_queries": [raw_title],
        "confidence": 0.9,
        "needs_user_review": False,
        "source": "fake",
        "parse_result": None,
        "attempted_queries": [],
        "candidates": candidates,
        "applied_preferences": None,
        "preference_hits": [],
        "preference_warnings": [],
        "review_hints": [],
        "enhanced_search_queries": [],
        "preview_request": None,
        "error": None,
    }


def _batch_parse_json(items: list[dict[str, Any]]) -> str:
    return json.dumps(
        {"ok": True, "result": {"batch_id": "batch-f2", "raw_input": "甲\n乙", "items": items}},
        ensure_ascii=False,
    )


class TestAppWorkbenchCandidateLoadingFeedback:
    """AC (US-343): 候选生成的加载/失败反馈就地、可恢复、按候选（或按批量 item）隔离.

    Every MiKan and draft call is mocked with a Playwright route; the draft
    creation route is held open (never ``time.sleep``), so the loading state is
    observed while the request is genuinely in flight.  Nothing external is
    contacted.
    """

    def _candidates_route(self, page: Page, candidates: list[dict[str, Any]]) -> None:
        body = _candidate_result_json("芙莉莲", candidates)
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(status=200, content_type="application/json", body=body),
        )

    def _hold_draft_creation(self, page: Page) -> list[Any]:
        """Hold ``POST /api/v1/requests`` open; return the pending routes."""
        held: list[Any] = []

        def handler(route: Any, request: Any) -> None:
            if request.method != "POST":
                route.continue_()
                return
            held.append(route)

        # Registered after the narrower candidate route so it wins for the
        # write endpoint only.
        page.route("**/api/v1/requests", handler)
        return held

    @staticmethod
    def _wait_for_held(page: Page, held: list[Any], expected: int = 1) -> None:
        deadline = time.time() + 10
        while len(held) < expected and time.time() < deadline:
            page.wait_for_timeout(50)
        assert len(held) >= expected, (
            f"expected {expected} in-flight draft request(s), captured {len(held)}"
        )

    @staticmethod
    def _search_and_get_cards(page: Page) -> Any:
        page.fill("#mikan-candidate-query", "芙莉莲")
        page.click("#mikan-candidate-search-submit")
        cards = page.locator(".candidate-card")
        expect(cards).to_have_count(2)
        return cards

    def test_loading_stays_on_the_clicked_candidate(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """One candidate loads in place; the others are suspended, not loading."""
        self._candidates_route(
            page,
            [
                _candidate(
                    bangumi_id="2353",
                    title="葬送的芙莉莲",
                    mikan_url="https://mikan.example/Home/Bangumi/2353",
                    candidate_context="opaque-candidate-context",
                ),
                _candidate(bangumi_id="3072", title="葬送的芙莉莲 第二季", mikan_url="https://mikan.example/Home/Bangumi/3072"),
            ],
        )
        held = self._hold_draft_creation(page)
        console_messages: list[str] = []
        page.on("console", lambda message: console_messages.append(message.text))
        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)

        cards = self._search_and_get_cards(page)
        clicked = cards.nth(0).locator(".candidate-select")
        clicked.click()
        self._wait_for_held(page, held)

        # In place: the clicked candidate's own button states the work in progress.
        expect(clicked).to_be_disabled()
        expect(clicked).to_have_attribute("aria-busy", "true")
        expect(clicked).to_contain_text("正在生成草案")
        expect(cards.nth(0)).to_contain_text("正在生成订阅草案")
        # Normal motion keeps the spinner animating continuously.
        spinner = page.evaluate(
            """() => {
                const el = document.querySelector('.candidate-card .base-button-spinner')
                if (!el) return null
                const style = getComputedStyle(el)
                return {
                    display: style.display,
                    name: style.animationName,
                    iterations: style.animationIterationCount,
                    duration: style.animationDuration,
                }
            }"""
        )
        assert spinner is not None, "the loading spinner is missing"
        assert spinner["display"] != "none"
        assert spinner["name"] != "none"
        assert spinner["iterations"] == "infinite"
        assert spinner["duration"] != "0s"

        # A second generation cannot start, but the other candidate is merely
        # suspended: it keeps its idle label and is never marked as loading.
        other = cards.nth(1).locator(".candidate-select")
        expect(other).to_be_disabled()
        expect(other).to_contain_text("选择此合集")
        assert other.get_attribute("aria-busy") is None
        expect(cards.nth(1)).not_to_contain_text("正在生成草案")
        assert page.evaluate("() => document.querySelectorAll('.base-button-spinner').length") == 1

        preview = _preview_request("葬送的芙莉莲", "req-f2-single")
        draft_body = preview_result_json(preview)
        draft_id = json.loads(draft_body)["result"]["draft_id"]
        held[0].fulfill(status=200, content_type="application/json", body=draft_body)
        page.wait_for_selector("#detail-preview-edit-form", timeout=5000)
        expect(page.locator(".candidate-card")).to_have_count(0)

        # Canary: the opaque draft capability, the candidate context and the
        # draft-id parameter stay out of the URL/history/storage, the visible
        # DOM and the console. The public request_id is not treated as a secret.
        state = page.evaluate(
            """() => ({
                url: window.location.href,
                historyState: JSON.stringify(window.history.state),
                localStorage: JSON.stringify(window.localStorage),
                sessionStorage: JSON.stringify(window.sessionStorage),
                bodyText: document.body.innerText,
            })"""
        )
        assert "request_id=" not in state["url"]
        assert "draft_id" not in state["url"]
        # The history surface is real (the SPA pushes router state); this keeps
        # the canary below from passing vacuously.
        assert state["historyState"] not in ("", "null")
        for value in (draft_id, "opaque-candidate-context"):
            assert value not in state["url"]
            assert value not in state["historyState"]
            assert value not in state["localStorage"]
            assert value not in state["sessionStorage"]
            assert value not in state["bodyText"]
            assert all(value not in message for message in console_messages)

    def test_reduced_motion_shows_text_not_a_frozen_arc(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """With prefers-reduced-motion the arc is suppressed; text + aria-busy remain."""
        page.emulate_media(reduced_motion="reduce")
        self._candidates_route(
            page,
            [_candidate(bangumi_id="2353", title="葬送的芙莉莲", mikan_url="https://mikan.example/Home/Bangumi/2353")],
        )
        held = self._hold_draft_creation(page)
        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)

        page.fill("#mikan-candidate-query", "芙莉莲")
        page.click("#mikan-candidate-search-submit")
        cards = page.locator(".candidate-card")
        expect(cards).to_have_count(1)
        clicked = cards.nth(0).locator(".candidate-select")
        clicked.click()
        self._wait_for_held(page, held)

        expect(clicked).to_have_attribute("aria-busy", "true")
        expect(clicked).to_contain_text("正在生成草案")
        expect(cards.nth(0)).to_contain_text("正在生成订阅草案")
        # The frozen arc would be meaningless, so it is not drawn at all.
        assert (
            page.evaluate(
                """() => {
                    const el = document.querySelector('.candidate-card .base-button-spinner')
                    return el ? getComputedStyle(el).display : 'missing'
                }"""
            )
            == "none"
        )

        preview = _preview_request("葬送的芙莉莲", "req-f2-reduced")
        held[0].fulfill(
            status=200,
            content_type="application/json",
            body=preview_result_json(preview),
        )
        page.wait_for_selector("#detail-preview-edit-form", timeout=5000)

    def test_failure_stays_beside_the_candidate_and_retries(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """A MiKan failure is reported beside the candidate and can be retried."""
        self._candidates_route(
            page,
            [_candidate(bangumi_id="2353", title="葬送的芙莉莲", mikan_url="https://mikan.example/Home/Bangumi/2353")],
        )
        attempts: list[dict[str, Any]] = []

        def _draft(route: Any, request: Any) -> None:
            if request.method != "POST":
                route.continue_()
                return
            attempts.append(request.post_data_json or {})
            if len(attempts) == 1:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "ok": False,
                            "error_type": "mikan_parse_failed",
                            "error_message": "MiKan 番剧页解析失败",
                            "error_data": {"failed_steps": ["mikan_bangumi_detail"]},
                        },
                        ensure_ascii=False,
                    ),
                )
                return
            route.fulfill(
                status=200,
                content_type="application/json",
                body=preview_result_json(_preview_request("葬送的芙莉莲", "req-f2-retry")),
            )

        page.route("**/api/v1/requests", _draft)
        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)

        page.fill("#mikan-candidate-query", "芙莉莲")
        page.click("#mikan-candidate-search-submit")
        card = page.locator(".candidate-card")
        expect(card).to_have_count(1)
        card.locator(".candidate-select").click()

        # The sanitized reason stays in the card; raw server text never reaches it.
        expect(card.locator(".candidate-generate-error")).to_contain_text(
            "从 MiKan 合集生成订阅草案失败：MiKan 页面格式异常，请稍后重试。"
        )
        expect(card).not_to_contain_text("MiKan 番剧页解析失败")
        retry = card.locator(".candidate-select")
        expect(retry).to_contain_text("重试生成草案")
        expect(retry).to_be_enabled()
        assert retry.get_attribute("aria-busy") is None

        retry.click()
        page.wait_for_selector("#detail-preview-edit-form", timeout=5000)
        assert len(attempts) == 2

    def test_batch_loading_locks_only_that_item(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """One batch item generating keeps every other item usable."""
        page.route(
            "**/api/v1/batches/parse",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_json(
                    [
                        _batch_found_item(
                            "item-a",
                            "甲",
                            [
                                _candidate(bangumi_id="42", title="候选甲一", mikan_url="https://mikan.example/Home/Bangumi/42"),
                                _candidate(bangumi_id="43", title="候选甲二", mikan_url="https://mikan.example/Home/Bangumi/43"),
                            ],
                        ),
                        _batch_found_item(
                            "item-b",
                            "乙",
                            [
                                _candidate(bangumi_id="77", title="候选乙一", mikan_url="https://mikan.example/Home/Bangumi/77"),
                                _candidate(bangumi_id="78", title="候选乙二", mikan_url="https://mikan.example/Home/Bangumi/78"),
                            ],
                        ),
                    ]
                ),
            ),
        )
        held = self._hold_draft_creation(page)
        set_storage_preferences(page, storage_dir)

        _require_dist()
        page.goto(f"{live_server_url}/app/add")
        page.wait_for_selector("#anime-mode-switch", timeout=5000)
        page.click("#anime-mode-batch")
        page.fill("#batch-raw-input", "甲\n乙")
        page.click("#batch-parse-submit")

        card_a = page.locator('.batch-draft-card[data-item-id="item-a"]')
        card_b = page.locator('.batch-draft-card[data-item-id="item-b"]')
        expect(card_a).to_be_visible()
        expect(card_b).to_be_visible()
        # Candidate stage: no effective-resource count is displayed yet.
        expect(card_a).not_to_contain_text("有效种子数")

        card_a.locator(".batch-card-expand").click()
        detail = page.locator("#batch-detail-pane")
        expect(detail).to_contain_text("候选合集")
        clicked = detail.locator(".candidate-select").nth(0)
        clicked.click()
        self._wait_for_held(page, held)

        expect(clicked).to_be_disabled()
        expect(clicked).to_have_attribute("aria-busy", "true")
        expect(clicked).to_contain_text("正在生成草案")
        expect(card_a).to_contain_text("正在生成订阅草案")
        # Sibling candidate of the same item: suspended, not loading.
        sibling = detail.locator(".candidate-select").nth(1)
        expect(sibling).to_be_disabled()
        expect(sibling).to_contain_text("选择此合集")
        assert sibling.get_attribute("aria-busy") is None

        # The other item stays fully usable: open its candidates and generate
        # from one of them while item-a is still in flight.
        expect(card_b).not_to_contain_text("正在生成订阅草案")
        expand_b = card_b.locator(".batch-card-expand")
        expect(expand_b).to_be_enabled()
        expand_b.click()
        expect(detail).to_contain_text("候选乙一")
        idle = detail.locator(".candidate-select").nth(0)
        idle_sibling = detail.locator(".candidate-select").nth(1)
        expect(idle).to_be_enabled()
        expect(idle).to_contain_text("选择此合集")
        assert idle.get_attribute("aria-busy") is None
        expect(detail).not_to_contain_text("正在生成草案")

        idle.click()
        self._wait_for_held(page, held, expected=2)

        # item-b now owns its own loading state, in its own detail pane...
        expect(idle).to_be_disabled()
        expect(idle).to_have_attribute("aria-busy", "true")
        expect(idle).to_contain_text("正在生成草案")
        expect(card_b).to_contain_text("正在生成订阅草案")
        # ...while its own sibling is suspended rather than loading...
        expect(idle_sibling).to_be_disabled()
        expect(idle_sibling).to_contain_text("选择此合集")
        assert idle_sibling.get_attribute("aria-busy") is None
        # ...and item-a's in-flight generation is untouched (neither cancelled
        # nor relabelled) and the two cards never swap states.
        expect(card_a).to_contain_text("正在生成订阅草案")
        expect(card_a.locator(".batch-card-status")).not_to_contain_text("草案")

        # Switch the detail pane back to item-a while both are generating: its
        # own list still shows item-a's clicked candidate as loading, its
        # sibling as suspended, and exactly one candidate button is busy.
        card_a.locator(".batch-card-expand").click()
        expect(detail).to_contain_text("候选甲一")
        clicked_a = detail.locator(".candidate-select").nth(0)
        expect(clicked_a).to_have_attribute("aria-busy", "true")
        expect(clicked_a).to_contain_text("正在生成草案")
        assert detail.locator(".candidate-select").nth(1).get_attribute("aria-busy") is None
        assert page.locator(".candidate-select[aria-busy='true']").count() == 1

        # Both requests are held: fulfil them in click order, one item at a time.
        body_a = preview_result_json(_preview_request("葬送的芙莉莲", "req-f2-batch-a"))
        body_b = preview_result_json(_preview_request("葬送的芙莉莲", "req-f2-batch-b"))
        draft_a = json.loads(body_a)["result"]["draft_id"]
        draft_b = json.loads(body_b)["result"]["draft_id"]
        assert draft_a != draft_b, "each item must own its own draft capability"

        held[0].fulfill(status=200, content_type="application/json", body=body_a)
        expect(card_a.locator(".batch-card-status")).to_contain_text("草案")
        expect(card_a).not_to_contain_text("正在生成订阅草案")
        # item-b is still generating: no cross-item release.
        expect(card_b).to_contain_text("正在生成订阅草案")
        expect(card_b.locator(".batch-card-status")).not_to_contain_text("草案")

        held[1].fulfill(status=200, content_type="application/json", body=body_b)
        expect(card_b.locator(".batch-card-status")).to_contain_text("草案")
        expect(card_a.locator(".batch-card-status")).to_contain_text("草案")
        expect(card_a).not_to_contain_text("正在生成订阅草案")
        expect(card_b).not_to_contain_text("正在生成订阅草案")
        # Both items left the candidate step: no candidate loading state remains.
        assert page.locator("#batch-detail-pane .candidate-select").count() == 0
        assert "req-f2-batch" not in page.url
        assert "draft_id" not in page.url
        for value in (draft_a, draft_b):
            assert value not in page.url


def _batch_draft_item(
    item_id: str, raw_title: str, request: dict[str, Any], draft_id: str
) -> dict[str, Any]:
    """A DRAFT batch item that already carries its server-authoritative draft."""
    return {
        **_batch_found_item(item_id, raw_title, []),
        "status": "DRAFT",
        "preview_request": request,
        "draft_id": draft_id,
        "draft_revision": 1,
    }


class TestAppWorkbenchDraftAutoRecompute:
    """AC (US-344): 字幕组即时提交、过滤规则 1.5 秒防抖、目录名只由「保存修改」提交；
    revision/CAS 由调度器独占，失败保留最后一致结果，草案能力绝不进入 DOM/URL/storage/console.

    Every MiKan, draft and preview-modify call is a Playwright route mock that
    follows the real public envelope; routes under test are held open instead of
    sleeping in the handler, and nothing external is contacted.
    """

    SECOND_GROUP = "桜都字幕组"

    @staticmethod
    def _seeds(title: str) -> list[str]:
        """The two effective resources the second subtitle group offers."""
        return [f"[桜都] {title} - 01 [1080p].mkv", f"[桜都] {title} - 02 [1080p].mkv"]

    def _preview(self, title: str = "葬送的芙莉莲", request_id: str = "req-344") -> dict[str, Any]:
        """An unsaved draft whose snapshot offers a second real subtitle group."""
        preview = _preview_request(title, request_id)
        seeds = self._seeds(title)
        preview["source_info"]["rss_sources"].append(
            {
                "subtitle_group": self.SECOND_GROUP,
                "rss_url": None,
                "source_type": "mikan",
                "total_seed_count": 2,
                "seed_names": seeds,
                "valid_seed_count": 2,
                "invalid_seed_count": 0,
                "valid_seed_names": seeds,
                "excluded_seed_names": [],
                "warnings": [],
            }
        )
        return preview

    @staticmethod
    def _envelope(preview: dict[str, Any], draft_id: str, revision: int, **config: Any) -> str:
        """A preview-modify 200 result carrying the modified public snapshot."""
        request = json.loads(json.dumps(preview))
        request["confirmable_config"] = {**preview["confirmable_config"], **config}
        return json.dumps(
            {
                "ok": True,
                "result": {
                    "request": request,
                    "summary": {},
                    "draft_id": draft_id,
                    "draft_revision": revision,
                },
            },
            ensure_ascii=False,
        )

    def _open_review(
        self, page: Page, live_server_url: str, storage_dir: Path, title: str = "葬送的芙莉莲"
    ) -> tuple[dict[str, Any], str]:
        """Search → select the only candidate → open the draft review step."""
        preview = self._preview(title)
        generation_body = preview_result_json(preview)
        draft_id = json.loads(generation_body)["result"]["draft_id"]
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_candidate_result_json(
                    "芙莉莲",
                    [_candidate(bangumi_id="2353", title=title, mikan_url="https://mikan.example/Home/Bangumi/2353")],
                ),
            ),
        )
        _register_generation_capture(page, [], body=generation_body)
        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)
        page.fill("#mikan-candidate-query", "芙莉莲")
        page.click("#mikan-candidate-search-submit")
        expect(page.locator(".candidate-card")).to_have_count(1)
        page.locator(".candidate-card button:has-text('选择此合集')").click()
        page.wait_for_selector("#detail-preview-edit-form", timeout=5000)
        return preview, draft_id

    @staticmethod
    def _capture_modify(page: Page, bodies: list[dict[str, Any]], responder: Any) -> Any:
        """Route preview-modify: record the body, then let the test answer it."""

        def handler(route: Any, request: Any) -> None:
            if not request.url.endswith("/api/v1/requests/preview-modify"):
                route.continue_()
                return
            bodies.append(request.post_data_json)
            responder(route, len(bodies) - 1)

        page.route("**/api/v1/requests/preview-modify", handler)
        return handler

    def test_subtitle_group_recomputes_immediately_and_atomically(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """The subtitle group is sent without waiting, and one success replaces
        the snapshot, the resource summary and the revision together."""
        preview, draft_id = self._open_review(page, live_server_url, storage_dir)
        bodies: list[dict[str, Any]] = []

        def responder(route: Any, _index: int) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=self._envelope(
                    preview,
                    draft_id,
                    2,
                    selected_subtitle_group=self.SECOND_GROUP,
                    effective_seed_names=self._seeds("葬送的芙莉莲"),
                ),
            )

        self._capture_modify(page, bodies, responder)
        detail = page.locator("#request-detail-container")
        save_button = page.locator("#single-review-save-button")
        note = page.locator("#single-review-save-blockers")
        seed_count = detail.locator(".detail-row", has_text="有效种子数").locator("dd")
        expect(seed_count).to_have_text("1")
        expect(save_button).to_be_enabled()

        started = time.time()
        page.select_option("#preview-subtitle-group", self.SECOND_GROUP)
        deadline = started + 1.0
        while not bodies and time.time() < deadline:
            page.wait_for_timeout(20)
        assert bodies, "字幕组修改必须立即发送服务端权威 preview-modify"
        assert time.time() - started < 1.5, "字幕组修改不得落入过滤规则的 1.5 秒防抖"

        assert bodies[0]["draft_id"] == draft_id
        assert bodies[0]["base_revision"] == 1
        assert bodies[0]["patch"] == {"selected_subtitle_group": self.SECOND_GROUP}
        assert "request" not in bodies[0]
        assert "summary" not in bodies[0]

        # Atomic replacement: new configuration with the new resource summary.
        expect(seed_count).to_have_text("2", timeout=5000)
        expect(save_button).to_be_enabled()
        expect(note).to_contain_text("保存并确认可用")

    def test_filter_rule_debounces_continuous_input_and_flushes_on_save_modify(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """The filter rule is debounced 1.5s from the last input; 保存修改 flushes
        the not-yet-due input immediately, with no follow-up send."""
        preview, draft_id = self._open_review(page, live_server_url, storage_dir)
        bodies: list[dict[str, Any]] = []
        responses = [
            self._envelope(
                preview,
                draft_id,
                2,
                filter_rule={"must_contain": "", "must_not_contain": "108", "use_regex": False, "case_sensitive": False},
            ),
            self._envelope(
                preview,
                draft_id,
                3,
                filter_rule={"must_contain": "", "must_not_contain": "1080p", "use_regex": False, "case_sensitive": False},
            ),
        ]

        def responder(route: Any, index: int) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=responses[min(index, len(responses) - 1)],
            )

        self._capture_modify(page, bodies, responder)
        save_button = page.locator("#single-review-save-button")
        note = page.locator("#single-review-save-blockers")

        # Continuous typing restarts the window: nothing leaves the browser and
        # the primary action never claims it is available.
        for value in ("1", "10", "108"):
            page.fill("#preview-must-not-contain", value)
            page.wait_for_timeout(300)
        page.wait_for_timeout(600)
        assert bodies == [], "过滤规则在 1.5 秒防抖窗口内不得发送"
        expect(note).to_contain_text("正在等待过滤规则自动更新")
        expect(save_button).to_be_disabled()
        expect(note).not_to_contain_text("保存并确认可用")

        deadline = time.time() + 4.0
        while not bodies and time.time() < deadline:
            page.wait_for_timeout(50)
        assert len(bodies) == 1, f"防抖只允许一次规整请求，实际 {len(bodies)}"
        assert bodies[0]["base_revision"] == 1
        assert bodies[0]["patch"] == {
            "filter_rule": {"must_not_contain": "108", "use_regex": False, "case_sensitive": False}
        }
        expect(note).to_contain_text("保存并确认可用", timeout=5000)

        # 保存修改 submits the pending filter now instead of waiting.
        page.fill("#preview-must-not-contain", "1080p")
        expect(save_button).to_be_disabled()
        page.click("#preview-apply-button")
        deadline = time.time() + 4.0
        while len(bodies) < 2 and time.time() < deadline:
            page.wait_for_timeout(50)
        assert len(bodies) == 2, "保存修改必须立即 flush 尚未到期的过滤输入"
        assert bodies[1]["base_revision"] == 2
        assert bodies[1]["patch"] == {
            "filter_rule": {"must_not_contain": "1080p", "use_regex": False, "case_sensitive": False}
        }
        expect(note).to_contain_text("保存并确认可用", timeout=5000)

        # The cancelled debounce never fires a third request.
        page.wait_for_timeout(2000)
        assert len(bodies) == 2

    def test_folder_name_waits_for_save_modify_and_blocks_confirm(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """The folder name never triggers a resource recompute on its own."""
        preview, draft_id = self._open_review(page, live_server_url, storage_dir)
        bodies: list[dict[str, Any]] = []

        def responder(route: Any, _index: int) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=self._envelope(preview, draft_id, 2, expected_folder_name="自定义目录"),
            )

        self._capture_modify(page, bodies, responder)
        save_button = page.locator("#single-review-save-button")
        note = page.locator("#single-review-save-blockers")
        page.evaluate(
            "() => { const d = document.querySelector('#request-detail-container .advanced-settings'); if (d) d.open = true }"
        )

        page.fill("#preview-folder-name", "自定义目录")
        page.wait_for_timeout(2000)
        assert bodies == [], "目录名不得自动发送 preview-modify"
        expect(note).to_contain_text("等待提交目录名")
        expect(save_button).to_be_disabled()

        page.click("#preview-apply-button")
        deadline = time.time() + 4.0
        while not bodies and time.time() < deadline:
            page.wait_for_timeout(50)
        assert len(bodies) == 1
        assert bodies[0]["patch"] == {"expected_folder_name": "自定义目录"}
        assert bodies[0]["base_revision"] == 1
        expect(note).to_contain_text("保存并确认可用", timeout=5000)
        expect(save_button).to_be_enabled()

    def test_held_modify_queues_latest_intent_without_reusing_revision(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """A second intent typed while a CAS is in flight waits for that CAS and
        is sent with the revision it returned — never with the same revision."""
        preview, draft_id = self._open_review(page, live_server_url, storage_dir)
        bodies: list[dict[str, Any]] = []
        held: list[Any] = []

        def responder(route: Any, index: int) -> None:
            if index == 0:
                held.append(route)
                return
            route.fulfill(
                status=200,
                content_type="application/json",
                body=self._envelope(
                    preview,
                    draft_id,
                    3,
                    selected_subtitle_group=self.SECOND_GROUP,
                    effective_seed_names=self._seeds("葬送的芙莉莲"),
                    filter_rule={
                        "must_contain": "",
                        "must_not_contain": "1080p",
                        "use_regex": False,
                        "case_sensitive": False,
                    },
                ),
            )

        self._capture_modify(page, bodies, responder)
        save_button = page.locator("#single-review-save-button")
        note = page.locator("#single-review-save-blockers")

        page.select_option("#preview-subtitle-group", self.SECOND_GROUP)
        deadline = time.time() + 5.0
        while not held and time.time() < deadline:
            page.wait_for_timeout(50)
        assert held, "held preview-modify route was not reached"
        assert bodies[0]["base_revision"] == 1

        # While that CAS owns the revision the user keeps typing the filter
        # rule. The debounce expires mid-flight, so the intent must wait for the
        # in-flight request instead of issuing a second CAS at revision 1.
        page.fill("#preview-must-not-contain", "1080p")
        page.wait_for_timeout(1700)
        assert len(bodies) == 1, "在途时不得复用同一 revision 发出第二个 CAS"
        expect(save_button).to_be_disabled()
        expect(note).to_contain_text("正在重新计算订阅方案")

        held[0].fulfill(
            status=200,
            content_type="application/json",
            body=self._envelope(
                preview,
                draft_id,
                2,
                selected_subtitle_group=self.SECOND_GROUP,
                effective_seed_names=self._seeds("葬送的芙莉莲"),
            ),
        )
        deadline = time.time() + 5.0
        while len(bodies) < 2 and time.time() < deadline:
            page.wait_for_timeout(50)
        assert len(bodies) == 2, "在途结束后必须只对仍最新的意图继续调度"
        assert bodies[1]["base_revision"] == 2
        # Only the still-unsent intent is replayed: the confirmed group is gone.
        assert bodies[1]["patch"] == {
            "filter_rule": {"must_not_contain": "1080p", "use_regex": False, "case_sensitive": False}
        }
        expect(note).to_contain_text("保存并确认可用", timeout=5000)
        expect(save_button).to_be_enabled()

    def test_failed_modify_keeps_last_consistent_result_and_recovers(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """A recoverable failure keeps the last server-consistent result, marks
        the intent as unapplied and offers retry / restore."""
        preview, draft_id = self._open_review(page, live_server_url, storage_dir)
        bodies: list[dict[str, Any]] = []
        detail = page.locator("#request-detail-container")
        seed_count = detail.locator(".detail-row", has_text="有效种子数").locator("dd")
        save_button = page.locator("#single-review-save-button")
        note = page.locator("#single-review-save-blockers")

        def responder(route: Any, index: int) -> None:
            if index == 0:
                route.fulfill(
                    status=500,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "ok": False,
                            "error_type": "internal_error",
                            "error_message": "private backend detail",
                            "error_data": {"trace": "/srv/secret/path"},
                        },
                        ensure_ascii=False,
                    ),
                )
                return
            route.fulfill(
                status=200,
                content_type="application/json",
                body=self._envelope(
                    preview,
                    draft_id,
                    2,
                    selected_subtitle_group=self.SECOND_GROUP,
                    effective_seed_names=self._seeds("葬送的芙莉莲"),
                ),
            )

        self._capture_modify(page, bodies, responder)
        console_messages: list[str] = []
        page.on("console", lambda message: console_messages.append(message.text))

        page.select_option("#preview-subtitle-group", self.SECOND_GROUP)
        expect(note).to_contain_text("存在未恢复的字段修改失败", timeout=5000)
        expect(save_button).to_be_disabled()
        # The last consistent result stays authoritative: the old group and its
        # resource summary are still what the server confirmed.
        expect(seed_count).to_have_text("1")
        expect(detail.locator("#preview-subtitle-group")).to_have_value(self.SECOND_GROUP)

        # 恢复上次结果 returns to the confirmed state without a new request.
        page.wait_for_timeout(200)
        assert len(bodies) == 1
        page.click("#preview-reset-button")
        expect(note).to_contain_text("保存并确认可用", timeout=5000)
        expect(detail.locator("#preview-subtitle-group")).to_have_value("喵萌")
        assert len(bodies) == 1, "恢复上次结果不得发送 preview-modify"

        # Retry carries the unapplied intent with the same base revision.
        page.select_option("#preview-subtitle-group", self.SECOND_GROUP)
        deadline = time.time() + 5.0
        while len(bodies) < 2 and time.time() < deadline:
            page.wait_for_timeout(50)
        assert len(bodies) == 2
        assert bodies[1]["base_revision"] == 1
        assert bodies[1]["patch"] == {"selected_subtitle_group": self.SECOND_GROUP}
        expect(note).to_contain_text("保存并确认可用", timeout=5000)
        expect(seed_count).to_have_text("2")

        # The raw internal error never reaches the DOM or the console.
        body_text = page.locator("body").inner_text()
        assert "private backend detail" not in body_text
        assert "/srv/secret/path" not in body_text
        assert "internal_error" not in body_text
        assert all("private backend detail" not in message for message in console_messages)

    def test_revision_conflict_returns_to_regeneration_without_leaking(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """An automatic recompute that conflicts restarts from candidate
        selection and never leaks the draft capability."""
        preview, draft_id = self._open_review(page, live_server_url, storage_dir)
        bodies: list[dict[str, Any]] = []

        def responder(route: Any, _index: int) -> None:
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

        self._capture_modify(page, bodies, responder)
        console_messages: list[str] = []
        page.on("console", lambda message: console_messages.append(message.text))

        page.select_option("#preview-subtitle-group", self.SECOND_GROUP)
        expect(page.locator(".global-notification")).to_contain_text("订阅草案已失效", timeout=5000)
        # The draft panel is dismissed and the candidate list is preserved.
        expect(page.locator("#detail-preview-edit-form")).to_have_count(0)
        expect(page.locator(".candidate-card")).to_have_count(1)
        assert len(bodies) == 1

        browser_state = page.evaluate(
            """() => ({
                url: window.location.href,
                history: JSON.stringify(window.history.state),
                localStorage: JSON.stringify(window.localStorage),
                sessionStorage: JSON.stringify(window.sessionStorage),
                bodyText: document.body.innerText,
            })"""
        )
        assert browser_state["history"] not in ("", "null")
        for value in (draft_id, "draft_revision", "base_revision"):
            assert value not in browser_state["url"]
            assert value not in browser_state["history"]
            assert value not in browser_state["localStorage"]
            assert value not in browser_state["sessionStorage"]
            assert value not in browser_state["bodyText"]
        for text in ("draft_revision_conflict", "compare_and_swap_draft", "current_revision"):
            assert text not in browser_state["bodyText"]
        assert all(draft_id not in message for message in console_messages)

    def test_zero_effective_resources_blocks_confirm_after_recompute(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """An automatic recompute that leaves no resource becomes a hard block;
        the previous resources are no longer presented as current."""
        preview, draft_id = self._open_review(page, live_server_url, storage_dir)
        bodies: list[dict[str, Any]] = []
        empty = json.loads(json.dumps(preview))
        empty["source_info"]["rss_sources"] = []
        empty["confirmable_config"]["effective_seed_names"] = []

        def responder(route: Any, _index: int) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": True,
                        "result": {
                            "request": empty,
                            "summary": {},
                            "draft_id": draft_id,
                            "draft_revision": 2,
                        },
                    },
                    ensure_ascii=False,
                ),
            )

        self._capture_modify(page, bodies, responder)
        detail = page.locator("#request-detail-container")
        seed_count = detail.locator(".detail-row", has_text="有效种子数").locator("dd")
        save_button = page.locator("#single-review-save-button")
        note = page.locator("#single-review-save-blockers")

        page.select_option("#preview-subtitle-group", self.SECOND_GROUP)
        expect(note).to_contain_text("没有有效资源", timeout=5000)
        expect(save_button).to_be_disabled()
        expect(note).not_to_contain_text("保存并确认可用")
        # The old effective resources are no longer reported as current.
        expect(seed_count).to_have_text("0")
        assert len(bodies) == 1
        assert bodies[0]["patch"] == {"selected_subtitle_group": self.SECOND_GROUP}

    def test_batch_detail_switch_cancels_timer_and_old_response_cannot_overwrite(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """Switching the batch detail cancels the debounce window, and a late
        response for the previous item never overwrites the newly selected one."""
        preview_a = self._preview("葬送的芙莉莲", "req-344-a")
        preview_b = self._preview("咒术回战", "req-344-b")
        page.route(
            "**/api/v1/batches/parse",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_batch_parse_json(
                    [
                        _batch_draft_item("item-a", "葬送的芙莉莲", preview_a, "draft-344-a"),
                        _batch_draft_item("item-b", "咒术回战", preview_b, "draft-344-b"),
                    ]
                ),
            ),
        )
        bodies: list[dict[str, Any]] = []
        held: list[Any] = []

        def responder(route: Any, index: int) -> None:
            if index == 0:
                held.append(route)
                return
            route.fulfill(
                status=200,
                content_type="application/json",
                body=self._envelope(preview_b, "draft-344-b", 2, selected_subtitle_group=self.SECOND_GROUP),
            )

        self._capture_modify(page, bodies, responder)
        console_messages: list[str] = []
        page.on("console", lambda message: console_messages.append(message.text))
        page_errors: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)
        page.click("#anime-mode-batch")
        page.fill("#batch-raw-input", "葬送的芙莉莲\n咒术回战")
        page.click("#batch-parse-submit")
        expect(page.locator(".batch-draft-card")).to_have_count(2)
        expect(page.locator("#batch-detail-pane")).to_contain_text("葬送的芙莉莲")

        # A filter edit opens its debounce window, then the subtitle group is
        # changed: that CAS must go out at once and carry only the group.
        page.fill("#batch-preview-must-not-contain", "1080p")
        page.select_option("#batch-preview-subtitle-group", self.SECOND_GROUP)
        deadline = time.time() + 5.0
        while not held and time.time() < deadline:
            page.wait_for_timeout(50)
        assert held, "held batch preview-modify route was not reached"
        assert bodies[0]["draft_id"] == "draft-344-a"
        assert bodies[0]["patch"] == {"selected_subtitle_group": self.SECOND_GROUP}

        # Switch the detail to item-b: item-a's pending debounce window dies
        # with the surface the user left.
        page.locator(".batch-draft-card[data-item-id='item-b'] .batch-card-title").click()
        expect(page.locator("#batch-detail-pane")).to_contain_text("咒术回战")
        page.wait_for_timeout(2000)
        assert len(bodies) == 1, "切换批量详情必须取消待发送的防抖窗口"

        # Fulfilling the late item-a response must not touch the item-b detail
        # that replaced it, and must update item-a's own card atomically.
        seeds_before = page.locator(".batch-draft-card[data-item-id='item-a'] .batch-card-seeds").inner_text()
        held[0].fulfill(
            status=200,
            content_type="application/json",
            body=self._envelope(
                preview_a,
                "draft-344-a",
                2,
                selected_subtitle_group=self.SECOND_GROUP,
                effective_seed_names=self._seeds("葬送的芙莉莲"),
            ),
        )
        page.wait_for_timeout(500)
        expect(page.locator("#batch-detail-pane")).to_contain_text("咒术回战")
        expect(page.locator("#batch-detail-pane")).not_to_contain_text("葬送的芙莉莲")
        card_group = page.locator(".batch-draft-card[data-item-id='item-a'] .batch-card-subtitle-group select")
        assert card_group.input_value() == self.SECOND_GROUP
        seeds_after = page.locator(".batch-draft-card[data-item-id='item-a'] .batch-card-seeds").inner_text()
        assert seeds_after != seeds_before, "item-a card resource summary did not refresh with its new group"
        # The dropped debounce never turns into a follow-up CAS.
        assert len(bodies) == 1
        assert "draft-344-a" not in page.url
        assert "draft-344-b" not in page.url
        assert all("draft-344" not in message for message in console_messages)
        assert page_errors == [], "the late response must not surface an uncaught error"


class TestAppWorkbenchReviewHierarchy:
    """AC (US-345 / F4)：单番审核默认层回答「已选哪部/哪一季、筛后有什么、能否确认」，
    技术 ID、原始标题、RSS 选择与英文区名默认折叠，资源摘要按字幕组一级、组内资源
    二级展示；未保存草案不得调用 safe-info，也不得把合集/来源信息带进
    DOM、URL、history、localStorage 或 console。

    所有 MiKan 与生成调用都是 Playwright route mock（真实公开 envelope），
    storage 使用每个测试独立的 tmp 目录，不访问真实 MiKan / AB / qB。
    """

    QUERY = "芙莉莲"
    RAW_TITLE = "芙莉莲S2"
    CANDIDATE_TITLE = "葬送的芙莉莲 第二季"
    SECOND_GROUP = "桜都字幕组"
    MIKAN_URL = "https://mikan.example/Home/Bangumi/2353"

    @classmethod
    def _preview(cls, request_id: str = "req-wb-f4") -> dict[str, Any]:
        """未保存草案快照：原始标题与合集标题不同，且有第二个真实字幕组。"""
        preview = _preview_request(cls.RAW_TITLE, request_id)
        seeds = [f"[桜都] {cls.CANDIDATE_TITLE} - 01 [1080p].mkv"]
        preview["source_info"]["rss_sources"].append(
            {
                "subtitle_group": cls.SECOND_GROUP,
                "rss_url": None,
                "source_type": "mikan",
                "total_seed_count": 1,
                "seed_names": seeds,
                "valid_seed_count": 1,
                "invalid_seed_count": 0,
                "valid_seed_names": seeds,
                "excluded_seed_names": [],
                "warnings": [],
            }
        )
        return preview

    def _open_review(
        self,
        page: Page,
        live_server_url: str,
        storage_dir: Path,
        *,
        candidate_title: str | None = None,
    ) -> tuple[dict[str, Any], str]:
        """搜索 → 选择唯一候选（第 2 季、28 集）→ 打开草案审核步骤。"""
        preview = self._preview()
        generation_body = preview_result_json(preview)
        draft_id = json.loads(generation_body)["result"]["draft_id"]
        page.route(
            "**/api/v1/mikan/candidates",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=_candidate_result_json(
                    self.QUERY,
                    [
                        _candidate(
                            bangumi_id="2353",
                            title=candidate_title or self.CANDIDATE_TITLE,
                            mikan_url=self.MIKAN_URL,
                            recommendation="高度匹配",
                            season_evidence={"status": "PROVEN", "season": 2, "requires_review": False},
                            total_episodes=28,
                        )
                    ],
                ),
            ),
        )
        _register_generation_capture(page, [], body=generation_body)
        set_storage_preferences(page, storage_dir)
        _goto_workbench(page, live_server_url)
        page.fill("#mikan-candidate-query", self.QUERY)
        page.click("#mikan-candidate-search-submit")
        expect(page.locator(".candidate-card")).to_have_count(1)
        page.locator(".candidate-card button:has-text('选择此合集')").click()
        page.wait_for_selector("#detail-preview-edit-form", timeout=5000)
        return preview, draft_id

    def test_review_default_layer_answers_the_four_questions(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """默认层直接回答「已选哪部/哪一季、筛后有什么、能否确认」。"""
        self._open_review(page, live_server_url, storage_dir)

        detail = page.locator("#request-detail-container")
        summary = detail.locator(".draft-review-summary")
        expect(summary).to_be_visible()
        summary_text = summary.inner_text()
        assert "已选合集" in summary_text
        assert self.CANDIDATE_TITLE in summary_text
        assert "第 2 季" in summary_text
        assert "28 集" in summary_text
        assert "喵萌" in summary_text
        assert "筛选规则" in summary_text

        # 未保存草案没有服务端季度/总集数字段：显示真实投影而不是伪造值。
        assert "未提供" not in summary_text
        assert "未知" not in summary_text

        # 资源摘要留在默认层，「筛后有什么」无需展开技术层。
        expect(detail.locator(".resource-summary")).to_be_visible()
        default_text = detail.inner_text()
        assert "资源摘要" in default_text
        assert "有效资源数" in default_text

    def test_review_technical_details_stay_collapsed_until_expanded(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """技术 ID、原始标题、RSS 选择与英文区名默认折叠，按需展开后完整可读。"""
        self._open_review(page, live_server_url, storage_dir)

        technical = page.locator("#request-detail-container details.advanced-detail")
        expect(technical).to_have_count(1)
        assert technical.evaluate("el => el.open") is False
        assert "全部信息" in technical.locator("summary").inner_text()

        default_text = page.locator("#request-detail-container").inner_text()
        for hidden in ("Overview", "Source", "request_id", "原始标题", "RSS 来源", self.RAW_TITLE):
            assert hidden not in default_text, f"技术层内容泄漏到默认层：{hidden}"

        technical.locator("summary").click()
        expanded = technical.inner_text()
        assert "Overview" in expanded
        assert "request_id" in expanded
        assert "原始标题" in expanded
        assert self.RAW_TITLE in expanded
        assert "Source" in expanded
        assert "RSS 来源" in expanded

        # 中文区名：默认层用中文标题，英文区名只存在于技术层。
        assert "筛选规则" in page.locator("#request-detail-container").inner_text()
        for english in ("Filter", "Seeds"):
            assert english not in default_text

    def test_review_default_layer_has_exactly_one_primary_action(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """「能否确认」只有一个主入口：保存并确认；表单的保存修改是次要动作。"""
        self._open_review(page, live_server_url, storage_dir)

        detail = page.locator("#request-detail-container")
        expect(detail.locator(".primary-button")).to_have_count(1)
        expect(page.locator("#single-review-save-button")).to_be_visible()
        save_class = page.locator("#single-review-save-button").get_attribute("class") or ""
        apply_class = page.locator("#preview-apply-button").get_attribute("class") or ""
        assert "primary-button" in save_class
        assert "secondary-button" in apply_class

    def test_review_never_calls_safe_info_for_an_unsaved_draft(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """D40-01：未保存草案的审核信息全部来自快照与内存投影，不得调用 safe-info。"""
        safe_info_calls: list[str] = []
        page.on(
            "request",
            lambda request: safe_info_calls.append(request.url) if "safe-info" in request.url else None,
        )
        # 一旦被调用就立刻失败，避免静默通过。
        page.route(
            "**/api/v1/requests/*/safe-info**",
            lambda route: route.fulfill(
                status=500, content_type="application/json", body='{"ok": false, "error": {"message": "unsaved"}}'
            ),
        )

        self._open_review(page, live_server_url, storage_dir)
        expect(page.locator(".draft-review-summary")).to_be_visible()
        assert safe_info_calls == [], "未保存草案不得调用 safe-info"

    def test_review_nests_in_group_resources_under_their_subtitle_group(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """完整种子按字幕组分层：字幕组是一级条目，组内资源缩进为二级。"""
        self._open_review(page, live_server_url, storage_dir)

        page.locator(".complete-seed-details > summary").click()
        groups = page.locator(".complete-seed-groups > .subgroup-seed-group")
        expect(groups).to_have_count(2)
        expect(page.locator(".complete-seed-groups > .seed-list")).to_have_count(0)
        summaries = page.locator(".complete-seed-groups > .subgroup-seed-group > summary").all_inner_texts()
        assert any("喵萌" in text for text in summaries)
        assert any(self.SECOND_GROUP in text for text in summaries)
        assert page.locator(".subgroup-seed-group .seed-list > li").count() == 2

    def test_review_technical_details_toggle_from_the_keyboard(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """键盘可展开/收起技术层，不需要指针。"""
        self._open_review(page, live_server_url, storage_dir)

        summary = page.locator("#request-detail-container details.advanced-detail > summary")
        summary.focus()
        assert summary.evaluate("el => el === document.activeElement")
        page.keyboard.press("Enter")
        assert summary.evaluate("el => el.parentElement.open") is True
        page.keyboard.press("Space")
        assert summary.evaluate("el => el.parentElement.open") is False

    def test_review_keeps_long_titles_readable_without_horizontal_overflow(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """长标题在 1280 与宽桌面下不撑破布局，且公开信息不进入 URL/存储/控制台。"""
        long_title = f"{self.CANDIDATE_TITLE} " + "超长标题片段" * 12
        console_messages: list[str] = []
        page.on("console", lambda message: console_messages.append(message.text))
        page_errors: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))

        preview, draft_id = self._open_review(
            page, live_server_url, storage_dir, candidate_title=long_title
        )
        assert preview["input"]["raw_title"] == self.RAW_TITLE

        for width, height in ((1280, 900), (1440, 900), (1920, 1080)):
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_timeout(100)
            overflow = page.evaluate("() => document.body.scrollWidth > window.innerWidth")
            assert overflow is False, f"{width}px 下出现横向滚动"

        state = page.evaluate(
            """() => ({
                url: window.location.href,
                history: JSON.stringify(window.history.state),
                local: JSON.stringify(window.localStorage),
                session: JSON.stringify(window.sessionStorage),
            })"""
        )
        for value in (self.MIKAN_URL, draft_id):
            assert value not in state["url"]
            assert value not in state["history"]
            assert value not in state["local"]
            assert value not in state["session"]
        assert self.MIKAN_URL not in page.locator("#request-detail-container").inner_text()
        assert all(self.MIKAN_URL not in message for message in console_messages)
        assert all(draft_id not in message for message in console_messages)
        assert page_errors == []
