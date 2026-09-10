from __future__ import annotations

import os
import zipfile
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from request_engine.controllers.request_controller import accept_request
from storage_engine.controllers.request_repository import save_request_snapshot
from storage_engine.controllers.storage_config import load_storage_config
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
        "to verify the US-203 Request detail migration in the browser."
    )


def _save_accepted_request(storage_dir: Path, title: str, request_id: str) -> dict[str, Any]:
    request = accept_request(create_saved_request(storage_dir, title, request_id))
    save_request_snapshot(load_storage_config(storage_dir), request)
    return request


def _goto_requests(page: Page, live_server_url: str, query: str = "") -> None:
    """Navigate to the SPA requests list and wait for it to load."""
    _require_dist()
    page.goto(f"{live_server_url}/app/plans{query}")
    page.wait_for_selector("#request-list-container", timeout=5000)
    page.wait_for_selector(".request-list-item", timeout=5000)


def _open_detail(page: Page, live_server_url: str, request_id: str) -> None:
    """Select a list item so the detail panel loads (or go direct via query)."""
    _goto_requests(page, live_server_url, query=f"?request_id={request_id}")
    page.wait_for_selector("#request-detail-container .overview-section", timeout=5000)


def _open_detail_or_error(page: Page, live_server_url: str, request_id: str) -> None:
    """Open the detail panel without assuming the load succeeds."""
    _require_dist()
    page.goto(f"{live_server_url}/app/plans?request_id={request_id}")
    page.wait_for_selector("#request-detail-container", timeout=5000)
    page.wait_for_selector("#request-detail-container .overview-section, #request-detail-container .error-state", timeout=5000)


class TestAppRequestDetailSections:
    """AC: Overview / Source / Filter / Seeds / Audit 分区与旧详情 parity."""

    def test_all_sections_present(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-detail-1")
        set_storage_preferences(page, storage_dir)
        _open_detail(page, live_server_url, "req-detail-1")

        text = page.locator("#request-detail-container").inner_text()
        for section in ("Overview", "Source", "Filter", "Seeds", "Audit"):
            assert section in text, f"Missing detail section: {section}"

    def test_overview_shows_key_fields(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-detail-2")
        set_storage_preferences(page, storage_dir)
        _open_detail(page, live_server_url, "req-detail-2")

        text = page.locator("#request-detail-container").inner_text()
        assert "原始标题" in text
        assert "葬送的芙莉莲" in text
        assert "req-detail-2" in text

    def test_seeds_sections_present(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "咒术回战第三季", "req-detail-seeds")
        set_storage_preferences(page, storage_dir)
        _open_detail(page, live_server_url, "req-detail-seeds")

        detail = page.locator("#request-detail-container")
        assert detail.locator(".effective-seed-group").count() == 1
        assert detail.locator(".complete-seed-details").count() == 1
        assert detail.locator(".excluded-seed-details").count() == 1
        effective_text = detail.locator(".effective-seed-group").inner_text()
        assert "有效种子（当前选中字幕组：Loli）(2)" in effective_text
        assert "[Loli] 咒术回战 第三季 - 01 [1080p][CHS].mkv" in effective_text

    def test_missing_history_and_ab_placeholders(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-detail-empty")
        set_storage_preferences(page, storage_dir)
        _open_detail(page, live_server_url, "req-detail-empty")

        text = page.locator("#request-detail-container").inner_text()
        assert "暂无状态历史" in text
        assert "暂无 Auto Bangumi 提交结果" in text


class TestAppRequestDetailUrlState:
    """AC: 详情选择状态可通过 URL 恢复；缺失 request_id 显示安全错误."""

    def test_direct_request_id_query_loads_detail(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-url-direct")
        set_storage_preferences(page, storage_dir)
        _open_detail(page, live_server_url, "req-url-direct")

        detail = page.locator("#request-detail-container")
        assert "req-url-direct" in detail.inner_text()
        assert page.locator("[data-request-id='req-url-direct']").get_attribute(
            "aria-current"
        ) == "true"

    def test_clicking_list_item_loads_detail(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-url-click")
        set_storage_preferences(page, storage_dir)
        _goto_requests(page, live_server_url)

        page.locator("[data-request-id='req-url-click']").click()
        page.wait_for_url("**/app/plans?request_id=req-url-click", timeout=5000)
        page.wait_for_selector("#request-detail-container .overview-section", timeout=5000)

        assert "req-url-click" in page.locator("#request-detail-container").inner_text()

    def test_refresh_restores_detail(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-url-refresh")
        set_storage_preferences(page, storage_dir)
        _open_detail(page, live_server_url, "req-url-refresh")

        page.reload()
        page.wait_for_selector("#request-detail-container .overview-section", timeout=5000)

        assert "req-url-refresh" in page.locator("#request-detail-container").inner_text()

    def test_missing_request_id_shows_safe_error(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-url-existing")
        set_storage_preferences(page, storage_dir)
        _open_detail_or_error(page, live_server_url, "req-url-missing")

        detail = page.locator("#request-detail-container")
        detail_text = detail.inner_text()
        assert "订阅方案详情加载失败" in detail_text
        # The raw 404 error_type/message never leaks; the request_id itself is a
        # public identifier so it may appear as the selected list item, but not
        # in the error body.
        assert "request_not_found" not in detail_text
        page.wait_for_selector("[data-request-id='req-url-existing']", timeout=5000)


class TestAppRequestDetailActions:
    """AC: PENDING_CONFIRM 显示确认/取消/修改；ACCEPTED 显示修改/删除/AB 入口."""

    def test_pending_actions_present(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-act-1")
        set_storage_preferences(page, storage_dir)
        _open_detail(page, live_server_url, "req-act-1")

        container = page.locator("#request-detail-container")
        assert container.locator("#detail-accept-button").count() >= 1
        assert container.locator("#detail-cancel-toggle").count() >= 1
        assert container.locator("#detail-modify-toggle").count() >= 1
        assert container.locator("#detail-delete-button").count() == 0

    def test_accepted_actions_present(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _save_accepted_request(storage_dir, "葬送的芙莉莲", "req-accepted-1")
        set_storage_preferences(page, storage_dir)
        _open_detail(page, live_server_url, "req-accepted-1")

        container = page.locator("#request-detail-container")
        assert container.locator("#detail-delete-button").count() >= 1
        assert container.locator("#detail-ab-submit-entry").count() >= 1
        assert container.locator("#detail-accept-button").count() == 0

    def test_confirm_flow_updates_detail_status(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-act-confirm")
        set_storage_preferences(page, storage_dir)
        _open_detail(page, live_server_url, "req-act-confirm")

        page.locator("#detail-accept-button").click()
        dialog = page.locator(".confirm-dialog")
        dialog.wait_for(state="visible")
        expect(dialog).to_contain_text("确认接受此订阅方案")
        dialog.locator(".primary-button").click()

        # The panel reloads the server-authoritative snapshot; the confirm
        # action button disappears and the AB entry appears.
        page.wait_for_selector("#detail-ab-submit-entry", timeout=5000)
        detail_text = page.locator("#request-detail-container").inner_text()
        assert "已确认" in detail_text
        assert page.locator("#detail-accept-button").count() == 0

    def test_cancel_flow_with_reason(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-act-cancel")
        set_storage_preferences(page, storage_dir)
        _open_detail(page, live_server_url, "req-act-cancel")

        page.locator("#detail-cancel-toggle").click()
        assert page.locator("#detail-cancel-form").is_visible()
        page.locator("#cancel-reason").fill("不需要这个番剧")
        page.locator("#detail-cancel-submit").click()
        dialog = page.locator(".confirm-dialog")
        dialog.wait_for(state="visible")
        expect(dialog).to_contain_text("确认取消此订阅方案")
        dialog.locator(".danger-button").click()

        # Wait for the reloaded panel to show the cancelled state (the status
        # label in the Overview section), not the stale pre-action panel.
        page.wait_for_selector("#request-detail-container .overview-section", timeout=5000)
        expect(page.locator("#request-detail-container")).to_contain_text(
            "已取消", timeout=5000
        )
        detail_text = page.locator("#request-detail-container").inner_text()
        assert "不可操作" in detail_text
        assert page.locator("#detail-cancel-toggle").count() == 0

    def test_delete_flow_removes_item_and_clears_url(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _save_accepted_request(storage_dir, "葬送的芙莉莲", "req-act-delete")
        set_storage_preferences(page, storage_dir)
        _open_detail(page, live_server_url, "req-act-delete")

        page.locator("#detail-delete-button").click()
        dialog = page.locator(".confirm-dialog")
        dialog.wait_for(state="visible")
        expect(dialog).to_contain_text("确认删除此订阅方案")
        dialog.locator(".danger-button").click()

        # After deletion the selection is cleared and the detail panel unmounts.
        page.wait_for_timeout(800)
        assert page.locator("[data-request-id='req-act-delete']").count() == 0
        assert "request_id=" not in page.url
        assert page.locator("#request-detail-container").count() == 0
        assert not (storage_dir / "requests" / "req-act-delete.json").exists()

    def test_delete_cancelled_keeps_item(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _save_accepted_request(storage_dir, "葬送的芙莉莲", "req-act-delete-cancel")
        set_storage_preferences(page, storage_dir)
        _open_detail(page, live_server_url, "req-act-delete-cancel")

        page.locator("#detail-delete-button").click()
        dialog = page.locator(".confirm-dialog")
        dialog.wait_for(state="visible")
        dialog.locator(".secondary-button").click()
        dialog.wait_for(state="hidden")

        assert page.locator("[data-request-id='req-act-delete-cancel']").count() >= 1
        assert "req-act-delete-cancel" in page.locator("#request-detail-container").inner_text()
        assert "request_id=req-act-delete-cancel" in page.url


class TestAppRequestDetailModify:
    """AC: 修改表单可编辑并提交 patch；空 patch 被拦截；失败保持表单."""

    def test_modify_form_toggles_and_submits_patch(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-mod-1")
        set_storage_preferences(page, storage_dir)
        _open_detail(page, live_server_url, "req-mod-1")

        page.locator("#detail-modify-toggle").click()
        form = page.locator("#detail-modify-form")
        assert form.is_visible()
        assert page.locator("#modify-subtitle-group").count() >= 1
        assert page.locator("#modify-must-contain").count() >= 1
        assert page.locator("#modify-must-not-contain").count() >= 1
        assert page.locator("#modify-folder-name").count() >= 1

        page.locator("#modify-folder-name").fill("自定义目录名")
        page.locator("#detail-modify-submit").click()
        page.wait_for_selector(".global-notification", timeout=5000)

        notif = page.locator(".global-notification")
        expect(notif).to_contain_text("修改成功", timeout=5000)
        detail_text = page.locator("#request-detail-container").inner_text()
        assert "待确认" in detail_text
        assert "自定义目录名" in detail_text

    def test_modify_empty_patch_is_blocked(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-mod-empty")
        set_storage_preferences(page, storage_dir)
        _open_detail(page, live_server_url, "req-mod-empty")

        page.locator("#detail-modify-toggle").click()
        page.locator("#detail-modify-submit").click()
        page.wait_for_selector("#detail-modify-error", timeout=5000)

        assert "请至少修改或清空一个字段" in page.locator("#detail-modify-error").inner_text()

    def test_modify_clear_fields_sends_explicit_empty_values(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-mod-clear")
        set_storage_preferences(page, storage_dir)
        _open_detail(page, live_server_url, "req-mod-clear")

        captured: dict[str, Any] = {}

        def handle_modify(route: Any, request: Any) -> None:
            if request.method == "POST":
                captured["payload"] = request.post_data_json
                route.fulfill(
                    json={
                        "ok": True,
                        "result": {
                            "request": {
                                "request_id": "req-mod-clear",
                                "status": "PENDING_CONFIRM",
                                "input": {"raw_title": "葬送的芙莉莲"},
                                "source_info": {},
                                "confirmable_config": {},
                            },
                            "summary": {
                                "request_id": "req-mod-clear",
                                "status": "PENDING_CONFIRM",
                            },
                        },
                    }
                )
            else:
                route.continue_()

        page.route("**/api/v1/requests/req-mod-clear/modify**", handle_modify)
        page.locator("#detail-modify-toggle").click()
        page.locator("#modify-clear-must-contain").check()
        page.locator("#modify-clear-must-not-contain").check()
        page.locator("#modify-clear-folder-name").check()
        page.locator("#detail-modify-submit").click()
        page.wait_for_selector(".global-notification", timeout=5000)

        assert captured["payload"]["patch"]["filter_rule"] == {
            "must_contain": "",
            "must_not_contain": "",
            "use_regex": False,
            "case_sensitive": False,
        }
        assert captured["payload"]["patch"]["expected_folder_name"] == ""

    def test_modify_failure_keeps_form_and_detail(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-mod-fail")

        def handle_modify(route: Any, request: Any) -> None:
            if request.method == "POST":
                route.fulfill(
                    status=500,
                    json={
                        "ok": False,
                        "error_type": "invalid_modify_patch",
                        "error_message": "修改失败",
                    },
                )
            else:
                route.continue_()

        page.route("**/api/v1/requests/req-mod-fail/modify**", handle_modify)
        set_storage_preferences(page, storage_dir)
        _open_detail(page, live_server_url, "req-mod-fail")

        page.locator("#detail-modify-toggle").click()
        page.locator("#modify-folder-name").fill("失败后仍保留")
        page.locator("#detail-modify-submit").click()
        page.wait_for_selector(".global-notification", timeout=5000)

        expect(page.locator(".global-notification")).to_contain_text("操作失败")
        assert page.locator("#detail-modify-form").is_visible()
        assert page.locator("#modify-folder-name").input_value() == "失败后仍保留"
        assert "待确认" in page.locator("#request-detail-container").inner_text()


class TestAppRequestDetailSensitive:
    """AC: 敏感值不进 DOM；错误只显示固定中文；RSS URL 被脱敏."""

    def test_detail_does_not_render_raw_urls(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        request = create_saved_request(storage_dir, "葬送的芙莉莲", "req-sec-url")
        selected_source = request["source_info"]["rss_sources"][0]
        selected_source["rss_url"] = "https://secret.example.invalid/rss.xml?token=hidden-token"
        selected_source["raw_response_body"] = "<rss><channel>hidden-token</channel></rss>"
        save_request_snapshot(load_storage_config(storage_dir), request)
        set_storage_preferences(page, storage_dir)
        _open_detail(page, live_server_url, "req-sec-url")

        detail_text = page.locator("#request-detail-container").inner_text()
        assert "hidden-token" not in detail_text
        assert "<rss" not in detail_text
        assert "https://secret.example.invalid" not in detail_text
        # RSS 来源 only shows 已选择/未选择, never the URL.
        assert "已选择" in detail_text or "未选择" in detail_text
        assert ".xml" not in detail_text.lower()

    def test_load_failure_shows_safe_error(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _require_dist()
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-sec-ok")
        set_storage_preferences(page, storage_dir)

        def _fail(route: Any, request: Any) -> None:
            # The detail endpoint is /api/v1/requests/<id> (a path segment after
            # /requests/), unlike the bare list endpoint /api/v1/requests.
            if "/api/v1/requests/" in request.url and request.method == "GET":
                route.fulfill(
                    status=404,
                    content_type="application/json",
                    body=(
                        '{"ok": false, "error_type": "request_not_found", '
                        '"error_message": "订阅方案不存在", '
                        '"error_data": {"failed_step": "load_request_snapshot"}}'
                    ),
                )
            else:
                route.continue_()

        page.route("**/api/v1/requests/**", _fail)
        _goto_requests(page, live_server_url, query="?request_id=req-sec-ok")

        error = page.locator("#request-detail-container .error-state")
        error.wait_for(state="visible", timeout=5000)
        error_text = error.inner_text()
        assert "订阅方案详情加载失败" in error_text
        # The raw error_type/message never leaks into the DOM.
        assert "request_not_found" not in error_text
        assert "load_request_snapshot" not in error_text
        # role=alert for the detail error.
        assert error.get_attribute("role") == "alert"

    def test_stage32_canary_stays_out_of_browser_observables(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """US-253: upstream failure evidence is not visible or persisted in SPA."""
        _require_dist()
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-stage32-canary")
        set_storage_preferences(page, storage_dir)
        canaries = (
            "stage32-browser-token",
            "stage32-browser-cookie",
            "stage32-browser-endpoint",
            "stage32-browser-rss",
            "stage32-browser-magnet",
            "stage32-browser-body",
            "stage32-browser-id",
            str(storage_dir),
        )

        def _poisoned_detail(route: Any, request: Any) -> None:
            assert "stage32-browser" not in request.url
            route.fulfill(
                status=502,
                content_type="application/json",
                body=(
                    '{"ok": false, "error_type": "mikan_http_failed", '
                    '"error_message": "upstream https://stage32-browser-endpoint.invalid/api", '
                    '"error_data": {"token": "stage32-browser-token", '
                    '"raw_response_body": "stage32-browser-body", '
                    '"external_id": "stage32-browser-id", '
                    '"magnet": "stage32-browser-magnet", '
                    '"rss_url": "stage32-browser-rss", '
                    '"cookie": "stage32-browser-cookie"}}'
                ),
            )

        page.route("**/api/v1/requests/req-stage32-canary**", _poisoned_detail)
        page.goto(
            f"{live_server_url}/app/plans?request_id=req-stage32-canary"
        )
        page.wait_for_selector("#request-detail-container .error-state", timeout=5000)
        browser_state = page.evaluate(
            """() => ({
                url: window.location.href,
                history: JSON.stringify(window.history.state),
                localStorage: JSON.stringify(window.localStorage),
                sessionStorage: JSON.stringify(window.sessionStorage),
                bodyText: document.body.innerText,
            })"""
        )
        persisted = "\n".join(
            path.read_text(encoding="utf-8")
            for path in storage_dir.rglob("*.json")
        )
        for value in canaries:
            assert value not in browser_state["url"]
            assert value not in browser_state["history"]
            assert value not in browser_state["localStorage"]
            assert value not in browser_state["sessionStorage"]
            assert value not in browser_state["bodyText"]
            assert value not in persisted

    def test_stage32_canary_stays_out_of_screenshot_and_trace(
        self, page: Page, live_server_url: str, storage_dir: Path, tmp_path: Path
    ) -> None:
        """US-253: actual screenshot/trace artifacts do not retain canaries."""
        _require_dist()
        request = create_saved_request(storage_dir, "葬送的芙莉莲", "req-stage32-artifacts")
        selected_source = request["source_info"]["rss_sources"][0]
        selected_source.update(
            {
                "rss_url": "https://stage32-d32-rss.invalid/rss.xml",
                "raw_response_body": "stage32-d32-raw-response",
                "token": "stage32-d32-token",
                "cookie": "stage32-d32-cookie",
                "authorization": "stage32-d32-authorization",
                "password": "stage32-d32-password",
                "endpoint": "stage32-d32-endpoint.invalid",
                "magnet": "stage32-d32-magnet",
                "external_id": "stage32-d32-external-id",
                "patch": "stage32-d32-patch-body",
                "traceback": "stage32-d32-traceback",
                "absolute_path": "/stage32/d32/private/path",
            }
        )
        request["source_info"]["matched_bangumi"]["mikan_url"] = (
            "https://stage32-d32-mikan.invalid/Home/Bangumi/32032"
        )
        request["confirmable_config"]["selected_rss_url"] = (
            "https://stage32-d32-rss.invalid/rss.xml"
        )
        save_request_snapshot(load_storage_config(storage_dir), request)
        set_storage_preferences(page, storage_dir)
        canaries = (
            "stage32-d32-password",
            "stage32-d32-token",
            "stage32-d32-cookie",
            "stage32-d32-authorization",
            "stage32-d32-endpoint.invalid",
            "stage32-d32-rss.invalid/rss.xml",
            "stage32-d32-mikan.invalid/Home/Bangumi/32032",
            "stage32-d32-magnet",
            "stage32-d32-external-id",
            "stage32-d32-raw-response",
            "stage32-d32-patch-body",
            "stage32-d32-traceback",
            "/stage32/d32/private/path",
        )
        screenshot_path = tmp_path / "request-detail.png"
        trace_path = tmp_path / "request-detail-trace.zip"

        def _safe_request_list(route: Any, _request: Any) -> None:
            # Keep the list prerequisite deterministic and non-sensitive; the
            # detail request below still goes through the real Flask server.
            route.fulfill(
                status=200,
                content_type="application/json",
                body=(
                    '{"ok":true,"result":{"requests":[{"request_id":'
                    '"req-stage32-artifacts","status":"PENDING_CONFIRM",'
                    '"bangumi_title":"葬送的芙莉莲",'
                    '"candidate_subtitle_groups":[],"selected_subtitle_group":null,'
                    '"effective_seed_count":0,"expected_folder_name":null,'
                    '"warnings":[]}]}}'
                ),
            )

        page.route("**/api/v1/requests?storage_dir=storage", _safe_request_list)
        # Trace from before navigation so the assertion covers the real Flask
        # detail serializer and the Vue detail flow consumes its safe projection.
        page.context.tracing.start(screenshots=True, snapshots=True, sources=False)
        try:
            page.goto(
            f"{live_server_url}/app/plans?request_id=req-stage32-artifacts"
            )
            page.wait_for_selector(
                "#request-detail-container .overview-section", timeout=5000
            )
            dom = page.locator("body")
            observable_texts = (
                dom.inner_text(),
                dom.text_content() or "",
                dom.evaluate("element => element.innerHTML"),
                dom.aria_snapshot(),
            )
            for canary in canaries:
                assert all(canary not in text for text in observable_texts)
            page.screenshot(path=str(screenshot_path), full_page=True)
        finally:
            page.context.tracing.stop(path=str(trace_path))

        # The DOM/accessible-text assertions above are the primary screenshot
        # safety proof; the binary scan is only an additional artifact check.
        screenshot_bytes = screenshot_path.read_bytes()
        for canary in canaries:
            assert canary.encode() not in screenshot_bytes
        with zipfile.ZipFile(trace_path) as trace:
            for member in trace.infolist():
                artifact = trace.read(member)
                for canary in canaries:
                    assert canary.encode() not in artifact


class TestAppRequestDetailResponsiveA11y:
    """AC: 360px 无横向溢出；中文状态码不暴露内部代码."""

    def test_360px_no_horizontal_overflow(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-360")
        set_storage_preferences(page, storage_dir)
        _open_detail(page, live_server_url, "req-360")

        page.set_viewport_size({"width": 360, "height": 780})
        body_width = page.locator("body").evaluate("el => el.scrollWidth")
        viewport_width = page.evaluate("() => window.innerWidth")
        assert body_width <= viewport_width, (
            f"Body scrollWidth ({body_width}) exceeds viewport ({viewport_width})"
        )

    def test_chinese_status_labels_only(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        create_saved_request(storage_dir, "葬送的芙莉莲", "req-status-pending")
        set_storage_preferences(page, storage_dir)
        _open_detail(page, live_server_url, "req-status-pending")

        body = page.locator("body").inner_text()
        assert "待确认" in body
        assert "PENDING_CONFIRM" not in body

    def test_ab_submit_entry_links_to_settings(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _save_accepted_request(storage_dir, "葬送的芙莉莲", "req-ab-entry")
        set_storage_preferences(page, storage_dir)
        _open_detail(page, live_server_url, "req-ab-entry")

        entry = page.locator("#detail-ab-submit-entry")
        assert entry.count() >= 1
        assert entry.get_attribute("href") == "/app/settings?request_id=req-ab-entry"

        entry.click()
        page.wait_for_url(
            f"{live_server_url}/app/settings?request_id=req-ab-entry", timeout=5000
        )
        assert page.url == f"{live_server_url}/app/settings?request_id=req-ab-entry"
        expect(page.locator("#settings-ab-request-id")).to_have_text("req-ab-entry")
