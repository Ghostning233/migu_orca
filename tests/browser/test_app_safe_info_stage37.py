from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import create_saved_request, set_storage_preferences

pytestmark = pytest.mark.browser


def _safe_info() -> dict[str, Any]:
    return {
        "request_id": "req-safe-stage37",
        "status": "ACCEPTED",
        "raw_title": "葬送的芙莉莲",
        "title": "葬送的芙莉莲",
        "aliases": ["Frieren"],
        "season": 1,
        "season_raw": "S1",
        "season_evidence": "用户确认",
        "mikan_collection": {"title": "真实 MiKan 合集", "bangumi_id": "12345"},
        "subtitle_groups": [
            {
                "subtitle_group": "喵萌奶茶屋",
                "total_resource_count": 2,
                "valid_resource_count": 1,
                "invalid_resource_count": 1,
                "warnings": [],
            }
        ],
        "selected_subtitle_group": "喵萌奶茶屋",
        "filter_rule": {
            "must_contain": "1080p",
            "must_not_contain": "SP",
            "use_regex": False,
            "case_sensitive": False,
        },
        "resources": {
            "selected_subtitle_group": "喵萌奶茶屋",
            "valid_resource_count": 1,
            "invalid_resource_count": 1,
            "complete_resource_count": 2,
            "valid_file_names": ["episode-01.mkv"],
            "excluded_file_names": [{"name": "episode-SP.mkv", "reason": "排除规则"}],
        },
        "folder_name": "葬送的芙莉莲",
        "storage_profile": "storage",
        "total_episodes": None,
        "updated_episode": None,
        "updated_episode_status": "NOT_IMPLEMENTED",
        "history_summary": [
            {
                "action": "ACCEPT",
                "previous_status": "PENDING_CONFIRM",
                "next_status": "ACCEPTED",
                "timestamp": "2026-09-01T00:00:00+00:00",
            }
        ],
        "ab_status": {
            "submitted": False,
            "success": None,
            "ab_subscription_id": None,
            "error_type": None,
        },
    }


def test_safe_info_dialog_uses_safe_endpoint_and_restores_focus(
    page: Page, live_server_url: str, storage_dir: Path
) -> None:
    create_saved_request(storage_dir, "葬送的芙莉莲", "req-safe-stage37")
    set_storage_preferences(page, storage_dir)

    def safe_info_route(route: Any, request: Any) -> None:
        if request.method == "GET" and "/safe-info" in request.url:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"ok": True, "result": {"safe_info": _safe_info()}}, ensure_ascii=False),
            )
        else:
            route.continue_()

    page.route("**/api/v1/requests/*/safe-info*", safe_info_route)
    page.goto(f"{live_server_url}/app/plans?request_id=req-safe-stage37")
    page.wait_for_selector("#detail-safe-info-button", timeout=5000)

    page.locator("#detail-safe-info-button").click()
    dialog = page.locator(".safe-info-dialog")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("真实 MiKan 合集")
    expect(dialog).to_contain_text("公开编号")
    expect(dialog).to_contain_text("episode-01.mkv")
    expect(dialog).to_contain_text("已更新集数")
    expect(dialog).to_contain_text("待开发")
    expect(dialog).not_to_contain_text("https://")

    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    expect(page.locator("#detail-safe-info-button")).to_be_focused()


def test_safe_info_reuse_is_one_shot_and_requires_explicit_search(
    page: Page, live_server_url: str, storage_dir: Path
) -> None:
    create_saved_request(storage_dir, "葬送的芙莉莲", "req-safe-stage37-reuse")
    set_storage_preferences(page, storage_dir)
    calls: list[str] = []

    def safe_info_route(route: Any, request: Any) -> None:
        if request.method == "GET" and "/safe-info" in request.url:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"ok": True, "result": {"safe_info": _safe_info()}}, ensure_ascii=False),
            )
        else:
            route.continue_()

    def mutation_guard(route: Any, request: Any) -> None:
        if request.method == "POST":
            calls.append(request.url)
        route.continue_()

    page.route("**/api/v1/requests/*/safe-info*", safe_info_route)
    page.route("**/api/v1/requests", mutation_guard)
    page.goto(f"{live_server_url}/app/plans?request_id=req-safe-stage37-reuse")
    page.wait_for_selector("#detail-safe-info-button", timeout=5000)
    page.locator("#detail-safe-info-button").click()
    page.locator(".safe-info-reuse").click()

    page.wait_for_url("**/app/add", timeout=5000)
    page.wait_for_selector("#mikan-candidate-search-form", timeout=5000)
    expect(page.locator("#mikan-candidate-query")).to_have_value("葬送的芙莉莲")
    expect(page.locator("#reuse-handoff-summary")).to_contain_text("公开合集编号 12345")
    assert calls == []

    page.reload()
    page.wait_for_selector("#mikan-candidate-search-form", timeout=5000)
    expect(page.locator("#reuse-handoff-summary")).to_have_count(0)


def test_safe_info_ignores_sensitive_unknown_fields_in_browser_observables(
    page: Page, live_server_url: str, storage_dir: Path
) -> None:
    create_saved_request(storage_dir, "葬送的芙莉莲", "req-safe-stage37-canary")
    set_storage_preferences(page, storage_dir)
    canary = "stage37-us301-secret-endpoint-token"
    injected = {**_safe_info(), "ignored_sensitive": canary, "raw_response_body": canary}

    def safe_info_route(route: Any, request: Any) -> None:
        if request.method == "GET" and "/safe-info" in request.url:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"ok": True, "result": {"safe_info": injected}}, ensure_ascii=False),
            )
        else:
            route.continue_()

    page.route("**/api/v1/requests/*/safe-info*", safe_info_route)
    page.goto(f"{live_server_url}/app/plans?request_id=req-safe-stage37-canary")
    page.wait_for_selector("#detail-safe-info-button", timeout=5000)
    page.locator("#detail-safe-info-button").click()
    page.wait_for_selector(".safe-info-dialog", timeout=5000)
    state = page.evaluate(
        """() => ({
          url: window.location.href,
          history: JSON.stringify(window.history.state),
          local: JSON.stringify(window.localStorage),
          session: JSON.stringify(window.sessionStorage),
          body: document.body.innerText,
        })"""
    )
    assert all(canary not in value for value in state.values())
