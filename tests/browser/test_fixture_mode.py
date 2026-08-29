from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from apps.migu_orca_entry.controllers.entry_controller import generate_request
from shared.models import EntryRequest
from tests.browser.conftest import open_dev_fixture_panel, preview_result_json, set_storage_preferences

pytestmark = pytest.mark.browser


def _candidate_result_json(query: str, candidates: list[dict[str, Any]]) -> str:
    return json.dumps(
        {"ok": True, "result": {"query": query, "candidates": candidates}},
        ensure_ascii=False,
    )


def _candidate(
    *,
    bangumi_id: str,
    title: str,
    mikan_url: str,
    source_query: str = "芙莉莲",
    poster_url: str | None = None,
    aliases: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "bangumi_id": bangumi_id,
        "title": title,
        "mikan_url": mikan_url,
        "poster_url": poster_url,
        "source_query": source_query,
        "aliases": aliases or [],
    }


def _preview_request(title: str, request_id: str) -> dict[str, Any]:
    """Build an unsaved preview Request dict (PENDING_CONFIRM, not on disk)."""
    return {
        **generate_request(EntryRequest(raw_title=title))["request"],
        "request_id": request_id,
    }


def _preview_result_json(request: dict[str, Any]) -> str:
    """Build a `POST /api/v1/requests` response body for an unsaved preview draft.

    US-194: the mock issues the draft into the in-process draft store and
    returns the opaque ``draft_id`` the real backend would, so the real
    preview-modify/preview-save backend works.
    """
    return preview_result_json(request)


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


class TestDevFixturePanelDefaultHidden:
    """AC: /index 开发/离线 fixture 入口默认收起，普通用户不会误以为它是主流程."""

    def test_dev_fixture_disclosure_collapsed_by_default(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/index")

        disclosure = page.locator("#dev-fixture-disclosure")
        assert disclosure.count() == 1
        # No `open` attribute on the details element => collapsed by default.
        assert disclosure.get_attribute("open") is None
        # The fixture form is present in the DOM but not actionable/visible.
        expect(page.locator("#request-generate-form")).to_be_hidden()
        expect(page.locator('input[name="title"]')).to_be_hidden()
        expect(page.locator("#request-generate-submit")).to_be_hidden()

    def test_dev_fixture_panel_is_last_panel(
        self, page: Page, live_server_url: str
    ) -> None:
        page.goto(f"{live_server_url}/index")

        detail = page.locator("#request-detail-panel")
        fixture = page.locator("#dev-fixture-panel")
        assert detail.count() == 1
        assert fixture.count() == 1
        # The dev fixture panel sits after the detail panel (lowest priority).
        assert page.locator(".panel").count() >= 4
        detail_box = detail.bounding_box()
        fixture_box = fixture.bounding_box()
        assert detail_box is not None
        assert fixture_box is not None
        assert fixture_box["y"] >= detail_box["y"]

    def test_page_load_triggers_no_fixture_generation(
        self, page: Page, live_server_url: str
    ) -> None:
        post_calls: list[str] = []

        def _capture(route: Any, request: Any) -> None:
            # The initial page load does a GET list refresh; only POSTing to
            # /api/v1/requests would mean a generation action. Any POST here is
            # failed loudly to prove the normal path never triggers one.
            if request.method != "POST":
                route.continue_()
                return
            post_calls.append(request.url)
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"ok": false, "error_message": "should not be called"}',
            )

        page.route("**/api/v1/requests", _capture)
        page.goto(f"{live_server_url}/index")
        page.wait_for_timeout(500)

        # Simply loading the workbench never generates a fixture Request.
        assert post_calls == []


class TestNormalPathDoesNotUseFixture:
    """AC: 普通用户路径（候选搜索 -> 手动选择）使用真实 MiKan，不触发 fixture 生成."""

    def test_candidate_selection_generates_mikan_not_fixture(
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
        preview = _preview_request("葬送的芙莉莲", "req-main-path")
        captured: list[dict[str, Any]] = []
        _register_generation_capture(
            page, captured, body=_preview_result_json(preview)
        )

        set_storage_preferences(page, storage_dir, save_request=False)
        page.goto(f"{live_server_url}/index")
        page.fill("#mikan-candidate-query", "芙莉莲")
        page.click("#mikan-candidate-search-submit")
        expect(page.locator(".candidate-card")).to_have_count(1)

        # Nothing is generated until the explicit manual selection.
        assert captured == []

        page.locator("button:has-text('选择此合集')").click()
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert captured
        # The normal path sends source=mikan through the existing mikan_bangumi
        # chain — never the static-fixture source used by the dev/offline panel.
        assert captured[0]["source"] == "mikan"
        assert captured[0]["source"] != "static-fixture"
        assert "预览已生成" in page.locator("#page-notification").inner_text()
        assert "request_id=" not in page.url


class TestDevFixtureEntryWorksOffline:
    """AC: 开发入口仍可用于离线测试：展开后 fixture 生成不依赖真实 MiKan 网络."""

    def test_dev_entry_generates_offline_without_mikan(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        mikan_calls: list[str] = []

        def _abort_mikan(route: Any, request: Any) -> None:
            mikan_calls.append(request.url)
            route.abort()

        page.route("**/api/v1/mikan/candidates", _abort_mikan)
        set_storage_preferences(page, storage_dir, save_request=False)
        page.goto(f"{live_server_url}/index")

        # The dev/offline-test entry is collapsed by default; expand it first.
        open_dev_fixture_panel(page)
        page.fill('input[name="title"]', "葬送的芙莉莲")
        page.click("#request-generate-submit")
        page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

        assert "预览已生成" in page.locator("#page-notification").inner_text()
        assert "订阅草案（未保存）" in page.locator(
            "#request-detail-container"
        ).inner_text()
        # Fixture generation is fully offline: real MiKan is never contacted.
        assert mikan_calls == []
        assert not storage_dir.exists() or not any(storage_dir.iterdir())
