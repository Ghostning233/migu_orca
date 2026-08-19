from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, Request, expect

from tests.browser.conftest import (
    create_saved_request,
    open_dev_fixture_panel,
    set_storage_preferences,
)
from apps.migu_orca_entry.controllers.entry_controller import generate_request
from request_engine.controllers.request_controller import accept_request, summarize_request
from shared.models import EntryRequest
from storage_engine.controllers.request_repository import save_request_snapshot
from storage_engine.controllers.storage_config import load_storage_config


pytestmark = pytest.mark.browser


def _open_detail(
    page: Page, live_server_url: str, storage_dir: Path, request_id: str
) -> None:
    create_saved_request(storage_dir, "葬送的芙莉莲", request_id)
    set_storage_preferences(page, storage_dir)
    page.goto(f"{live_server_url}/index?request_id={request_id}")
    page.wait_for_selector("#request-detail-container .overview-section", timeout=5000)


def test_index_uses_stage14_visual_hierarchy_and_button_semantics(
    page: Page, live_server_url: str
) -> None:
    page.goto(f"{live_server_url}/index")
    open_dev_fixture_panel(page)

    expect(page.locator("#generate-panel")).to_be_visible()
    expect(page.locator("#request-list-panel")).to_be_visible()
    expect(page.locator("#request-detail-panel")).to_be_visible()
    expect(page.locator("#acceptance-panel")).to_have_count(0)
    expect(page.locator("#request-generate-submit.primary-button")).to_be_visible()
    expect(page.locator("#request-list-refresh.secondary-button")).to_be_visible()
    expect(page.locator("#request-list-container.empty-state")).to_be_visible()
    expect(page.locator("#request-detail-container.empty-state")).to_be_visible()


def test_settings_sections_use_boundaries_disclosure_and_button_semantics(
    page: Page, live_server_url: str
) -> None:
    page.goto(f"{live_server_url}/settings")

    for panel_id in (
        "storage-settings-panel",
        "data-source-settings-panel",
        "qbittorrent-settings-panel",
        "auto-bangumi-settings-panel",
    ):
        expect(page.locator(f"#{panel_id}.settings-panel")).to_be_visible()

    expect(page.locator("#qbittorrent-settings-details")).to_have_count(0)
    expect(page.locator("#qbittorrent-settings-panel details")).to_have_count(0)
    expect(page.locator("#qbittorrent-settings-panel summary")).to_have_count(0)
    expect(page.locator("#settings-qbittorrent-endpoint")).to_be_visible()
    expect(page.locator("#storage-preferences-save.primary-button")).to_be_visible()
    expect(page.locator("#storage-preferences-clear.danger-button")).to_be_visible()
    expect(page.locator("#settings-qbittorrent-test-submit.primary-button")).to_be_visible()
    expect(page.locator("#settings-qbittorrent-test-submit")).to_contain_text(
        "测试 qBittorrent 连接"
    )


def test_request_detail_sections_are_grouped_and_actions_are_near_heading(
    page: Page, live_server_url: str, storage_dir: Path
) -> None:
    _open_detail(page, live_server_url, storage_dir, "req-ui-detail")

    detail = page.locator("#request-detail-container")
    for section_class in (
        "overview-section",
        "source-section",
        "filter-section",
        "seeds-section",
        "audit-group-section",
    ):
        expect(detail.locator(f".detail-section.{section_class}")).to_be_visible()

    expect(detail.locator(".detail-actions .primary-button:has-text('确认')")).to_be_visible()
    expect(detail.locator(".detail-actions .secondary-button:has-text('修改')")).to_be_visible()
    expect(detail.locator(".detail-actions .danger-button:has-text('取消')")).to_be_visible()

    heading_box = detail.locator("h3").bounding_box()
    actions_box = detail.locator(".detail-actions").bounding_box()
    assert heading_box is not None
    assert actions_box is not None
    assert actions_box["y"] > heading_box["y"]
    assert actions_box["y"] - heading_box["y"] < 80


def test_stage14_pages_remain_readable_on_narrow_viewports(
    page: Page, live_server_url: str, storage_dir: Path
) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    _open_detail(page, live_server_url, storage_dir, "req-ui-mobile")

    expect(page.locator(".app-layout")).to_have_css("grid-template-columns", "366px")
    expect(page.locator("#generate-panel")).to_be_visible()
    expect(page.locator("#request-detail-panel")).to_be_visible()
    assert page.locator("#request-detail-panel").bounding_box()["width"] <= 390

    page.goto(f"{live_server_url}/settings")
    expect(page.locator(".settings-layout")).to_have_css("grid-template-columns", "366px")
    assert page.locator("#storage-settings-panel").bounding_box()["width"] <= 390


def test_notifications_and_state_feedback_do_not_expose_sensitive_values(
    page: Page, live_server_url: str
) -> None:
    page.goto(f"{live_server_url}/index")
    open_dev_fixture_panel(page)
    page.fill("#request-title", " ")
    page.click("#request-generate-submit")

    notification = page.locator("#page-notification")
    expect(notification).to_be_visible()
    assert "notification-error" in (notification.get_attribute("class") or "")
    text = notification.inner_text().lower()
    for forbidden in (
        "http://",
        "https://",
        "token",
        "password",
        "cookie",
        "sid",
        "<rss",
    ):
        assert forbidden not in text


def test_stage14_sensitive_settings_values_do_not_persist_or_leak(
    page: Page, live_server_url: str, storage_dir: Path
) -> None:
    sensitive_values = (
        "http://private-qbt.stage14.local:8080",
        "stage14-qbt-user",
        "stage14-qbt-password",
        "stage14-cookie",
        "stage14-SID",
        "<rss version='2.0'>stage14 raw rss</rss>",
        "stage14 raw response body",
    )

    def _fulfill_qbittorrent(route, request: Request) -> None:
        route.fulfill(
            status=200,
            json={
                "ok": True,
                "result": {
                    "status": "ok",
                    "reachable": True,
                    "version": "4.6.5",
                    "endpoint": sensitive_values[0],
                    "username": sensitive_values[1],
                    "cookie": sensitive_values[3],
                    "SID": sensitive_values[4],
                    "raw_rss_xml": sensitive_values[5],
                    "raw_response_body": sensitive_values[6],
                },
            },
        )

    page.route("**/api/v1/qbittorrent/test-connection", _fulfill_qbittorrent)
    page.add_init_script("window.confirm = () => true")
    page.goto(f"{live_server_url}/settings")
    page.fill("#settings-qbittorrent-endpoint", sensitive_values[0])
    page.fill("#settings-qbittorrent-username", sensitive_values[1])
    page.fill("#settings-qbittorrent-password", sensitive_values[2])
    page.click("#settings-qbittorrent-test-submit")
    expect(page.locator("#settings-qbittorrent-result")).to_contain_text("status: ok")

    set_storage_preferences(page, storage_dir, save_request=True)
    page.goto(f"{live_server_url}/index")
    open_dev_fixture_panel(page)
    page.fill("#request-title", "咒术回战")
    page.click("#request-generate-submit")
    page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

    browser_state = page.evaluate(
        """() => ({
            url: window.location.href,
            localStorage: JSON.stringify(window.localStorage),
            sessionStorage: JSON.stringify(window.sessionStorage),
            bodyText: document.body.innerText,
        })"""
    )
    storage_json = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (storage_dir / "requests").glob("*.json")
    )

    assert "request_id=" in browser_state["url"]
    for value in sensitive_values:
        assert value not in browser_state["url"]
        assert value not in browser_state["localStorage"]
        assert value not in browser_state["sessionStorage"]
        assert value not in browser_state["bodyText"]
        assert value not in storage_json

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
    assert json.loads(storage_json)["source_info"]


def test_stage15_accepted_modify_delete_do_not_leak_sensitive_values(
    page: Page, live_server_url: str, storage_dir: Path
) -> None:
    """US-109: ACCEPTED modify/delete and filter flows must not leak secrets.

    Endpoint, token, username, password, cookie, SID, raw HTML, raw RSS XML, and
    raw response body must never enter storage JSON, browser storage, URL, logs,
    screenshots, or traces. This test feeds the values through a mocked external
    response, then runs the Stage 15 ACCEPTED modify + delete flow and checks every
    sensitive surface.
    """
    sensitive_values = (
        "http://private-ab.stage15.local:8080",
        "stage15-ab-token",
        "stage15-qbt-user",
        "stage15-qbt-password",
        "stage15-cookie",
        "stage15-SID",
        "<html>stage15 raw html</html>",
        "<rss version='2.0'>stage15 raw rss</rss>",
        "stage15 raw response body",
    )

    def _fulfill_qbittorrent(route: object, request: Request) -> None:
        getattr(route, "fulfill")(
            status=200,
            json={
                "ok": True,
                "result": {
                    "status": "ok",
                    "reachable": True,
                    "version": "4.6.5",
                    "endpoint": sensitive_values[0],
                    "token": sensitive_values[1],
                    "username": sensitive_values[2],
                    "cookie": sensitive_values[4],
                    "SID": sensitive_values[5],
                    "raw_html": sensitive_values[6],
                    "raw_rss_xml": sensitive_values[7],
                    "raw_response_body": sensitive_values[8],
                },
            },
        )

    page.route("**/api/v1/qbittorrent/test-connection", _fulfill_qbittorrent)
    page.add_init_script("window.confirm = () => true")
    page.goto(f"{live_server_url}/settings")
    page.fill("#settings-qbittorrent-endpoint", sensitive_values[0])
    page.fill("#settings-qbittorrent-username", sensitive_values[2])
    page.fill("#settings-qbittorrent-password", sensitive_values[3])
    page.click("#settings-qbittorrent-test-submit")
    expect(page.locator("#settings-qbittorrent-result")).to_contain_text("status: ok")

    # Build a saved ACCEPTED request so the modify/delete actions are available.
    request = accept_request(create_saved_request(storage_dir, "葬送的芙莉莲", "req-stage15-sec"))
    save_request_snapshot(load_storage_config(storage_dir), request)

    set_storage_preferences(page, storage_dir)
    page.goto(f"{live_server_url}/index")
    page.click("#request-list-refresh")
    page.wait_for_timeout(800)
    page.locator("[data-request-id='req-stage15-sec']").click()
    page.wait_for_timeout(500)

    # 1) Modify the ACCEPTED request (folder + literal filter) and refresh.
    page.locator(".detail-actions button:has-text('修改')").click()
    page.wait_for_timeout(300)
    page.locator("#modify-must-contain").fill("1080p")
    page.locator("#modify-folder-name").fill("Stage15 脱敏目录")
    page.locator("#detail-modify-form button:has-text('提交修改')").click()
    page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
    assert "修改成功" in page.locator("#page-notification").inner_text()

    detail_text = page.locator("#request-detail-container").inner_text()
    assert "已确认" in detail_text
    assert "Stage15 脱敏目录" in detail_text
    # RSS is shown only as "已选择"; the raw endpoint URL must never render.
    assert "已选择" in detail_text

    # The snapshot rewritten by modify must stay clean of the sensitive values.
    modified_snapshot = (storage_dir / "requests" / "req-stage15-sec.json").read_text(
        encoding="utf-8"
    )
    for value in sensitive_values:
        assert value not in modified_snapshot

    browser_state = page.evaluate(
        """() => ({
            url: window.location.href,
            localStorage: JSON.stringify(window.localStorage),
            sessionStorage: JSON.stringify(window.sessionStorage),
            bodyText: document.body.innerText,
        })"""
    )
    assert "request_id=req-stage15-sec" in browser_state["url"]

    # 2) Delete the ACCEPTED request (confirm already stubbed to accept).
    page.locator(".detail-actions button:has-text('删除')").click()
    page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
    assert "删除成功" in page.locator("#page-notification").inner_text()

    post_delete_state = page.evaluate(
        """() => ({
            url: window.location.href,
            localStorage: JSON.stringify(window.localStorage),
            sessionStorage: JSON.stringify(window.sessionStorage),
            bodyText: document.body.innerText,
        })"""
    )

    assert not (storage_dir / "requests" / "req-stage15-sec.json").exists()
    assert page.locator("[data-request-id='req-stage15-sec']").count() == 0
    assert "订阅方案已删除" in post_delete_state["bodyText"]
    assert "request_id=" not in post_delete_state["url"]

    for state in (browser_state, post_delete_state):
        for value in sensitive_values:
            assert value not in state["url"]
            assert value not in state["localStorage"]
            assert value not in state["sessionStorage"]
            assert value not in state["bodyText"]

    remaining_storage_json = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (storage_dir / "requests").glob("*.json")
    )
    for value in sensitive_values:
        assert value not in remaining_storage_json

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
        "miguOrca.web.saveRequest": "false",
    }


def test_stage18_mikan_primary_flow_does_not_leak_sensitive_values(
    page: Page, live_server_url: str, storage_dir: Path
) -> None:
    """US-131: The Stage 18 MiKan primary workflow must not leak secrets.

    MiKan endpoint, raw HTML, raw RSS XML, cookie, token, raw response body, and
    magnet must never enter storage JSON, history, browser storage, URL, logs,
    screenshots, or traces. The values are fed through a mocked candidate search
    response, then the flow searches, selects a candidate, edits the preview
    draft, and saves it through the real preview-save backend so every sensitive
    surface is checked against the persisted snapshot.
    """
    sensitive_values = (
        "http://private-mikan.stage18.local/Home/Search",
        "stage18-mikan-cookie",
        "stage18-mikan-token",
        "<html>stage18 raw html</html>",
        "<rss version='2.0'>stage18 raw rss</rss>",
        "stage18 raw response body",
        "magnet:?xt=urn:btih:stage18sensitivehash",
    )

    def _fulfill_candidates(route: object, request: Request) -> None:
        getattr(route, "fulfill")(
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
                                "recommendation": None,
                                # Extra fields a malicious/buggy source could add:
                                "search_endpoint": sensitive_values[0],
                                "cookie": sensitive_values[1],
                                "token": sensitive_values[2],
                                "raw_html": sensitive_values[3],
                                "raw_rss_xml": sensitive_values[4],
                                "raw_response_body": sensitive_values[5],
                                "magnet": sensitive_values[6],
                            }
                        ],
                    },
                },
                ensure_ascii=False,
            ),
        )

    page.route("**/api/v1/mikan/candidates", _fulfill_candidates)

    # Return an unsaved static-fixture preview draft for the generation POST so
    # the flow renders the editable preview without any live MiKan network read.
    preview = {
        **generate_request(EntryRequest(raw_title="葬送的芙莉莲"))["request"],
        "request_id": "req-stage18-sec",
    }
    preview_body = json.dumps(
        {
            "ok": True,
            "result": {
                "request": preview,
                "summary": summarize_request(preview),
            },
        },
        ensure_ascii=False,
    )

    def _fulfill_generation(route: object, request: Request) -> None:
        if getattr(request, "method") != "POST":
            getattr(route, "continue_")()
            return
        getattr(route, "fulfill")(
            status=200, content_type="application/json", body=preview_body
        )

    page.route("**/api/v1/requests", _fulfill_generation)

    set_storage_preferences(page, storage_dir, save_request=False)
    page.goto(f"{live_server_url}/index")
    page.fill("#mikan-candidate-query", "芙莉莲")
    page.click("#mikan-candidate-search-submit")
    expect(page.locator(".candidate-card")).to_have_count(1)

    # The card renderer must only expose public candidate metadata.
    card_text = page.locator(".candidate-card").inner_text()
    for value in sensitive_values:
        assert value not in card_text

    # Manual selection -> editable preview draft (save_request=false).
    page.locator("button:has-text('选择此合集')").click()
    page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
    assert "预览已生成" in page.locator("#page-notification").inner_text()
    assert "request_id=" not in page.url

    # Edit the preview draft, recompute seeds, then persist via the real
    # preview-save backend so the snapshot reflects the full Stage 18 flow.
    page.fill("#preview-folder-name", "Stage18 脱敏目录")
    page.fill("#preview-must-not-contain", "V2")
    page.click("button:has-text('应用修改')")
    page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
    page.locator("#request-detail-container button:has-text('保存草案')").click()
    page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
    assert "request_id=req-stage18-sec" in page.url

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

    saved_path = storage_dir / "requests" / "req-stage18-sec.json"
    assert saved_path.exists()
    saved_json = json.loads(saved_path.read_text(encoding="utf-8"))
    saved_text = json.dumps(saved_json, ensure_ascii=False)
    for value in sensitive_values:
        assert value not in saved_text
    assert saved_json["status"] == "PENDING_CONFIRM"

    # history/ must also stay free of the sensitive values (empty or clean).
    history_root = storage_dir / "history"
    if history_root.is_dir():
        for path in history_root.glob("*.json"):
            for value in sensitive_values:
                assert value not in path.read_text(encoding="utf-8")

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
        "miguOrca.web.saveRequest": "false",
    }


def test_stage19_batch_workbench_does_not_leak_sensitive_values(
    page: Page, live_server_url: str, storage_dir: Path
) -> None:
    """US-141: Batch parse, card display, and single-card accept stay sanitized."""

    sensitive_values = (
        "http://private-llm.stage19.local/v1/chat/completions",
        "stage19-provider-token",
        "stage19-cookie",
        "<html>stage19 raw html</html>",
        "<rss version='2.0'>stage19 raw rss</rss>",
        "stage19 raw response body",
        "magnet:?xt=urn:btih:stage19sensitivehash",
        "https://mikan.example/Home/Search?searchstr=secret-token",
        "/home/ghostning/stage19-secret.xml",
    )
    first_preview = {
        **generate_request(EntryRequest(raw_title="关于我转生变成史莱姆这档事"))[
            "request"
        ],
        "request_id": "req-stage19-sec",
    }
    second_preview = {
        **generate_request(EntryRequest(raw_title="实力至上主义教室"))["request"],
        "request_id": "req-stage19-other",
    }

    batch_body = json.dumps(
        {
            "ok": True,
            "result": {
                "batch_id": "batch-stage19-sec",
                "raw_input": "萌王S4\n路哥S4",
                "items": [
                    {
                        "item_id": "item-sec",
                        "raw_title": "萌王S4",
                        "status": "DRAFT",
                        "canonical_title_candidates": [
                            "关于我转生变成史莱姆这档事 第四季"
                        ],
                        "season_hint": "S4",
                        "search_queries": ["转生史莱姆 第四季"],
                        "confidence": 0.9,
                        "needs_user_review": False,
                        "source": "fake",
                        "candidates": [
                            {
                                "bangumi_id": "42",
                                "title": "关于我转生变成史莱姆这档事 第四季",
                                "mikan_url": "https://mikan.example/Home/Bangumi/42",
                                "poster_url": None,
                                "source_query": "转生史莱姆 第四季",
                                "aliases": [],
                                "recommendation": None,
                                "raw_html": sensitive_values[3],
                                "raw_rss_xml": sensitive_values[4],
                                "cookie": sensitive_values[2],
                                "token": sensitive_values[1],
                                "magnet": sensitive_values[6],
                                "failed_url": sensitive_values[7],
                            }
                        ],
                        "confirmable_config": {
                            "selected_subtitle_group": "桜都字幕组",
                            "selected_rss_url": sensitive_values[7],
                            "filter_rule": {
                                "must_contain": "1080p",
                                "must_not_contain": "V2",
                                "use_regex": False,
                                "case_sensitive": False,
                            },
                            "effective_seed_names": ["史莱姆 S4 01 [1080p]"],
                        },
                        "source_info": {
                            "raw_html": sensitive_values[3],
                            "raw_rss_xml": sensitive_values[4],
                            "cookie": sensitive_values[2],
                            "token": sensitive_values[1],
                            "raw_response_body": sensitive_values[5],
                            "local_path": sensitive_values[8],
                            "rss_sources": [
                                {
                                    "subtitle_group": "桜都字幕组",
                                    "rss_url": sensitive_values[7],
                                    "seed_names": [
                                        "史莱姆 S4 01 [1080p]",
                                        "史莱姆 S4 01 V2 [1080p]",
                                    ],
                                    "valid_seed_names": ["史莱姆 S4 01 [1080p]"],
                                    "excluded_seed_names": [
                                        {
                                            "name": "史莱姆 S4 01 V2 [1080p]",
                                            "reason": "命中排除规则：V2",
                                        }
                                    ],
                                }
                            ],
                        },
                        "preview_request": first_preview,
                        "provider_response": {
                            "endpoint": sensitive_values[0],
                            "token": sensitive_values[1],
                            "raw_response_body": sensitive_values[5],
                        },
                    },
                    {
                        "item_id": "item-other",
                        "raw_title": "路哥S4",
                        "status": "DRAFT",
                        "canonical_title_candidates": ["实力至上主义教室 第四季"],
                        "season_hint": "S4",
                        "search_queries": ["实力至上主义教室 第四季"],
                        "confidence": 0.8,
                        "needs_user_review": False,
                        "source": "fake",
                        "candidates": [],
                        "confirmable_config": None,
                        "source_info": None,
                        "preview_request": second_preview,
                    },
                ],
            },
        },
        ensure_ascii=False,
    )

    saved_calls: list[dict[str, Any]] = []
    accept_calls: list[dict[str, Any]] = []

    def _fulfill_batch(route: Any, request: Request) -> None:
        route.fulfill(status=200, content_type="application/json", body=batch_body)

    def _save_preview(route: Any, request: Request) -> None:
        payload = json.loads(request.post_data or "{}")
        saved_calls.append(payload)
        saved = dict(payload["request"])
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "ok": True,
                    "result": {
                        "request": saved,
                        "summary": {"request_id": saved["request_id"]},
                    },
                },
                ensure_ascii=False,
            ),
        )

    def _accept(route: Any, request: Request) -> None:
        accept_calls.append(json.loads(request.post_data or "{}"))
        accepted = dict(first_preview)
        accepted["status"] = "ACCEPTED"
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "ok": True,
                    "result": {
                        "request": accepted,
                        "summary": {"request_id": accepted["request_id"]},
                    },
                },
                ensure_ascii=False,
            ),
        )

    page.route("**/api/v1/batches/parse", _fulfill_batch)
    page.route("**/api/v1/requests/preview-save", _save_preview)
    page.route("**/api/v1/requests/req-stage19-sec/accept", _accept)

    set_storage_preferences(page, storage_dir, save_request=False)
    page.goto(f"{live_server_url}/index")
    page.fill("#batch-raw-input", "萌王S4\n路哥S4")
    page.click("#batch-parse-submit")
    expect(page.locator(".batch-draft-card")).to_have_count(2)
    page.locator(".batch-draft-card", has_text="萌王S4").locator(
        ".batch-card-expand"
    ).click()

    page.once("dialog", lambda dialog: dialog.accept())
    page.locator(".batch-draft-card", has_text="萌王S4").locator(
        ".batch-card-accept"
    ).click()
    page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

    first_card = page.locator(".batch-draft-card", has_text="萌王S4")
    second_card = page.locator(".batch-draft-card", has_text="路哥S4")
    expect(first_card.locator(".batch-card-status")).to_contain_text("已接受")
    expect(first_card.locator(".batch-card-delete")).to_be_hidden()
    expect(second_card.locator(".batch-card-status")).to_contain_text("草案")
    assert saved_calls and saved_calls[0]["request"]["request_id"] == "req-stage19-sec"
    assert accept_calls and accept_calls[0]["storage_dir"] is None

    browser_state = page.evaluate(
        """() => ({
            url: window.location.href,
            localStorage: JSON.stringify(window.localStorage),
            sessionStorage: JSON.stringify(window.sessionStorage),
            bodyText: document.body.innerText,
        })"""
    )
    serialized_calls = json.dumps(saved_calls + accept_calls, ensure_ascii=False)
    storage_json = "\n".join(
        path.read_text(encoding="utf-8")
        for path in storage_dir.rglob("*.json")
    )
    for value in sensitive_values:
        assert value not in browser_state["url"]
        assert value not in browser_state["localStorage"]
        assert value not in browser_state["sessionStorage"]
        assert value not in browser_state["bodyText"]
        assert value not in serialized_calls
        assert value not in storage_json

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
        "miguOrca.web.saveRequest": "false",
    }
