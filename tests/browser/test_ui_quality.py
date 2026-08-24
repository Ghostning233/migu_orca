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
from batch_engine.controllers.batch_queue_controller import (
    complete_queue_item_submit,
    create_submission_queue,
    enqueue_item,
    start_queue_item_submit,
)
from batch_engine.models import BATCH_QUEUE_STATUS_FAILED
from request_engine.controllers.request_controller import accept_request, summarize_request
from shared.models import EntryRequest
from storage_engine.controllers.queue_repository import save_submission_queue
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


def test_disabled_controls_use_static_feedback_and_cannot_trigger_actions(
    page: Page, live_server_url: str
) -> None:
    """US-171: disabled controls never masquerade as in-flight work."""
    page.goto(f"{live_server_url}/index")

    # Candidate search, batch accept, queue, and a representative draft control.
    candidate = page.locator("#mikan-candidate-search-submit")
    candidate.evaluate("element => element.disabled = true")
    draft = page.locator("#batch-parse-submit")
    draft.evaluate("element => element.disabled = true")
    controls = [
        candidate,
        draft,
        page.locator("#batch-accept-submit"),
        page.locator("#batch-queue-refresh"),
    ]

    for control in controls:
        expect(control).to_be_disabled()
        expect(control).to_have_css("cursor", "default")
        assert control.evaluate(
            "element => window.getComputedStyle(element, '::before').animationName"
        ) == "none"
        assert control.evaluate(
            """element => {
                let calls = 0;
                element.addEventListener('click', () => { calls += 1; });
                element.click();
                return calls;
            }"""
        ) == 0

    page.goto(f"{live_server_url}/settings")
    settings_button = page.locator("#settings-qbittorrent-test-submit")
    settings_button.evaluate("element => element.disabled = true")
    expect(settings_button).to_be_disabled()
    expect(settings_button).to_have_css("cursor", "default")
    assert settings_button.evaluate(
        """element => {
            let calls = 0;
            element.addEventListener('click', () => { calls += 1; });
            element.click();
            return calls;
        }"""
    ) == 0

    aria_disabled = page.locator("#settings-qbittorrent-test-submit")
    aria_disabled.evaluate(
        "element => { element.disabled = false; element.setAttribute('aria-disabled', 'true'); }"
    )
    expect(aria_disabled).to_have_css("cursor", "default")


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
        # 标题必须命中 static fixture catalog（config/system/static_mikan_sources.json
        # 仅含「咒术回战 第三季」「葬送的芙莉莲」），否则 generate_request 返回 None。
        **generate_request(EntryRequest(raw_title="咒术回战"))["request"],
        "request_id": "req-stage19-sec",
    }
    second_preview = {
        **generate_request(EntryRequest(raw_title="葬送的芙莉莲"))["request"],
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
        # US-146：单卡接受与批量接受统一走批次接受 API（POST
        # /api/v1/batches/<batch_id>/accept）。响应只包含公开字段，绝不回传
        # endpoint/token/cookie/raw response 等敏感配置。
        accept_calls.append(json.loads(request.post_data or "{}"))
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "ok": True,
                    "result": {
                        "batch_id": "batch-stage19-sec",
                        "queue": {
                            "queue_id": "queue-stage19-sec",
                            "batch_id": "batch-stage19-sec",
                            "created_at": "2026-08-19T00:00:00+00:00",
                            "updated_at": "2026-08-19T00:00:00+00:00",
                            "items": [
                                {
                                    "queue_id": "queue-stage19-sec",
                                    "batch_id": "batch-stage19-sec",
                                    "item_id": "item-sec",
                                    "request_id": "req-stage19-sec",
                                    "title": "关于我转生变成史莱姆这档事 第四季",
                                    "status": "READY_TO_SUBMIT",
                                    "status_label": "待提交",
                                    "attempts": 0,
                                    "last_error": None,
                                    "ab_result_summary": None,
                                    "created_at": "2026-08-19T00:00:00+00:00",
                                    "updated_at": "2026-08-19T00:00:00+00:00",
                                }
                            ],
                        },
                        "items": [
                            {
                                "item_id": "item-sec",
                                "request_id": "req-stage19-sec",
                                "title": "关于我转生变成史莱姆这档事 第四季",
                                "status": "accepted",
                                "reason": None,
                                "error_type": None,
                                "queued": True,
                            }
                        ],
                        "summary": {
                            "accepted": 1,
                            "already_accepted": 0,
                            "unacceptable": 0,
                            "failed": 0,
                        },
                    },
                },
                ensure_ascii=False,
            ),
        )

    page.route("**/api/v1/batches/parse", _fulfill_batch)
    page.route("**/api/v1/requests/preview-save", _save_preview)
    # postBatchAccept 用 apiPath() 拼 URL，设置 storage 偏好后 URL 会带
    # ?storage_dir= query；Playwright glob 不匹配 query，必须加 * 通配。
    page.route("**/api/v1/batches/batch-stage19-sec/accept*", _accept)

    set_storage_preferences(page, storage_dir, save_request=False)
    page.goto(f"{live_server_url}/index")
    page.get_by_role("tab", name="批量搜索").click()
    page.fill("#batch-raw-input", "萌王S4\n路哥S4")
    page.click("#batch-parse-submit")
    expect(page.locator(".batch-draft-card")).to_have_count(2)
    page.locator(".batch-draft-card", has_text="萌王S4").locator(
        ".batch-card-expand"
    ).click()

    page.once("dialog", lambda dialog: dialog.accept())
    page.locator(".batch-detail-accept").click()
    page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

    first_card = page.locator(".batch-draft-card", has_text="萌王S4")
    second_card = page.locator(".batch-draft-card", has_text="路哥S4")
    expect(first_card.locator(".batch-card-status")).to_contain_text("已接受")
    expect(first_card.locator(".batch-card-delete")).to_be_hidden()
    expect(second_card.locator(".batch-card-status")).to_contain_text("草案")
    assert saved_calls and saved_calls[0]["request"]["request_id"] == "req-stage19-sec"
    # US-146：accept 请求体按 BatchAcceptPayload 契约携带 items（含
    # item_id/request_id/title，均为公开字段）与 storage_dir；设置了 storage
    # 偏好时 storage_dir 为路径值（URL query 经 apiPath 同样携带），属于功能
    # 参数，不属于 sensitive_values。
    assert accept_calls
    assert accept_calls[0]["items"][0]["item_id"] == "item-sec"
    assert accept_calls[0]["items"][0]["request_id"] == "req-stage19-sec"
    assert accept_calls[0]["storage_dir"] == str(storage_dir)

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


def test_stage20_batch_retry_does_not_leak_sensitive_values(
    page: Page, live_server_url: str, storage_dir: Path
) -> None:
    """US-148: failed-item single retry end-to-end security regression.

    Feeds endpoint / token / Authorization header / cookie / raw HTML / raw RSS
    XML / raw response body / full failed URL / local absolute path through a
    poisoned preview and a poisoned failed queue item, then runs the full
    parse -> accept -> submit-failure -> single-item retry flow. Asserts the
    values never reach the page, URL, browser storage, API request bodies, the
    persisted queue JSON, or the Request JSON.
    """
    sensitive_values = (
        "http://private-llm.stage20.local/v1/chat/completions",
        "stage20-provider-token",
        "Bearer stage20-authorization-token",
        "stage20-cookie",
        "<html>stage20 raw html</html>",
        "<rss version='2.0'>stage20 raw rss</rss>",
        "stage20 raw response body",
        "https://mikan.example/Home/Search?searchstr=stage20-secret",
        "/home/ghostning/stage20-secret.xml",
        "magnet:?xt=urn:btih:stage20sensitivehash",
    )
    first_preview = {
        # 标题必须命中 static fixture catalog（config/system/static_mikan_sources.json
        # 仅含「咒术回战 第三季」「葬送的芙莉莲」），否则 generate_request 返回 None。
        **generate_request(EntryRequest(raw_title="咒术回战"))["request"],
        "request_id": "req-stage20-sec",
    }
    second_preview = {
        **generate_request(EntryRequest(raw_title="葬送的芙莉莲"))["request"],
        "request_id": "req-stage20-other",
    }

    batch_body = json.dumps(
        {
            "ok": True,
            "result": {
                "batch_id": "batch-stage20-sec",
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
                                "raw_html": sensitive_values[4],
                                "raw_rss_xml": sensitive_values[5],
                                "cookie": sensitive_values[3],
                                "token": sensitive_values[1],
                                "magnet": sensitive_values[9],
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
                            "matched_bangumi": {
                                "title": "关于我转生变成史莱姆这档事 第四季"
                            },
                            "raw_html": sensitive_values[4],
                            "raw_rss_xml": sensitive_values[5],
                            "cookie": sensitive_values[3],
                            "token": sensitive_values[1],
                            "authorization": sensitive_values[2],
                            "raw_response_body": sensitive_values[6],
                            "local_path": sensitive_values[8],
                            "magnet": sensitive_values[9],
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
                        # provider_response 是 LLM 提供商的响应，包含全部敏感值；
                        # 它们只允许存在于预览/请求快照，绝不能进入任何响应边界。
                        "provider_response": {
                            "endpoint": sensitive_values[0],
                            "token": sensitive_values[1],
                            "authorization": sensitive_values[2],
                            "raw_response_body": sensitive_values[6],
                            "magnet": sensitive_values[9],
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

    # 真实的请求快照（retry 从磁盘重新读取它）；source_info/匹配数据来自
    # generate_request 的静态 fixture，不含上述敏感值。
    saved_request = create_saved_request(storage_dir, "咒术回战", "req-stage20-sec")
    save_request_snapshot(load_storage_config(storage_dir), saved_request)

    # 真实的队列 JSON 落盘：用真实控制器写入一个 FAILED 项，其 last_error 注入
    # 完整失败 URL 与 token —— 队列控制器必须在写盘前脱敏。
    queue = create_submission_queue(
        "batch-stage20-sec",
        queue_id_factory=lambda: "queue-stage20-sec",
        now_factory=lambda: "2026-08-19T00:00:00+00:00",
    )
    queue = enqueue_item(
        queue,
        item_id="item-sec",
        request_id="req-stage20-sec",
        title="关于我转生变成史莱姆这档事 第四季",
        now_factory=lambda: "2026-08-19T00:00:00+00:00",
    )
    queue = start_queue_item_submit(
        queue,
        "req-stage20-sec",
        now_factory=lambda: "2026-08-19T00:01:00+00:00",
    )
    queue = complete_queue_item_submit(
        queue,
        "req-stage20-sec",
        BATCH_QUEUE_STATUS_FAILED,
        last_error={
            "failed_url": sensitive_values[7],
            "token": sensitive_values[1],
            "error_message": "Auto Bangumi HTTP 提交失败",
        },
        now_factory=lambda: "2026-08-19T00:02:00+00:00",
    )
    save_submission_queue(load_storage_config(storage_dir), queue)

    saved_calls: list[dict[str, Any]] = []
    accept_calls: list[dict[str, Any]] = []
    submit_calls: list[dict[str, Any]] = []
    retry_calls: list[dict[str, Any]] = []

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

    def _queue_item_payload(
        *,
        status: str,
        attempts: int,
        title: str,
        last_error: str | None = None,
        ab_result_summary: str | None = None,
    ) -> dict[str, Any]:
        return {
            "queue_id": "queue-stage20-sec",
            "batch_id": "batch-stage20-sec",
            "item_id": "item-sec",
            "request_id": "req-stage20-sec",
            "title": title,
            "status": status,
            "status_label": {
                "READY_TO_SUBMIT": "待提交",
                "SUBMITTING": "提交中",
                "SUCCEEDED": "提交成功",
                "FAILED": "提交失败",
                "RETRYABLE": "可重试",
            }[status],
            "attempts": attempts,
            "last_error": last_error,
            "ab_result_summary": ab_result_summary,
            "created_at": "2026-08-19T00:00:00+00:00",
            "updated_at": "2026-08-19T00:02:00+00:00",
        }

    def _accept(route: Any, request: Request) -> None:
        accept_calls.append(json.loads(request.post_data or "{}"))
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "ok": True,
                    "result": {
                        "batch_id": "batch-stage20-sec",
                        "queue": {
                            "queue_id": "queue-stage20-sec",
                            "batch_id": "batch-stage20-sec",
                            "created_at": "2026-08-19T00:00:00+00:00",
                            "updated_at": "2026-08-19T00:00:00+00:00",
                            "items": [
                                _queue_item_payload(
                                    status="READY_TO_SUBMIT",
                                    attempts=0,
                                    title="关于我转生变成史莱姆这档事 第四季",
                                )
                            ],
                        },
                        "items": [
                            {
                                "item_id": "item-sec",
                                "request_id": "req-stage20-sec",
                                "title": "关于我转生变成史莱姆这档事 第四季",
                                "status": "accepted",
                                "reason": None,
                                "error_type": None,
                                "queued": True,
                            }
                        ],
                        "summary": {
                            "accepted": 1,
                            "already_accepted": 0,
                            "unacceptable": 0,
                            "failed": 0,
                        },
                    },
                },
                ensure_ascii=False,
            ),
        )

    def _submit(route: Any, request: Request) -> None:
        submit_calls.append(json.loads(request.post_data or "{}"))
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "ok": True,
                    "result": {
                        "batch_id": "batch-stage20-sec",
                        "queue": {
                            "queue_id": "queue-stage20-sec",
                            "batch_id": "batch-stage20-sec",
                            "created_at": "2026-08-19T00:00:00+00:00",
                            "updated_at": "2026-08-19T00:02:00+00:00",
                            "items": [
                                _queue_item_payload(
                                    status="FAILED",
                                    attempts=1,
                                    title="关于我转生变成史莱姆这档事 第四季",
                                    last_error="error_type=ab_submit_failed; error_message=Auto Bangumi HTTP 提交失败",
                                )
                            ],
                        },
                        "items": [
                            {
                                "item_id": "item-sec",
                                "request_id": "req-stage20-sec",
                                "title": "关于我转生变成史莱姆这档事 第四季",
                                "status": "failed",
                                "reason": "Auto Bangumi HTTP 提交失败",
                                "error_type": "ab_submit_failed",
                                "attempts": 1,
                            }
                        ],
                        "summary": {
                            "succeeded": 0,
                            "failed": 1,
                            "retryable": 0,
                            "skipped": 0,
                        },
                    },
                },
                ensure_ascii=False,
            ),
        )

    def _retry(route: Any, request: Request) -> None:
        retry_calls.append(json.loads(request.post_data or "{}"))
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "ok": True,
                    "result": {
                        "batch_id": "batch-stage20-sec",
                        "queue": {
                            "queue_id": "queue-stage20-sec",
                            "batch_id": "batch-stage20-sec",
                            "created_at": "2026-08-19T00:00:00+00:00",
                            "updated_at": "2026-08-19T00:05:00+00:00",
                            "items": [
                                _queue_item_payload(
                                    status="SUCCEEDED",
                                    attempts=2,
                                    title="关于我转生变成史莱姆这档事 第四季",
                                    ab_result_summary="ab_subscription_id=ab-stage20; success=True",
                                )
                            ],
                        },
                        "items": [
                            {
                                "item_id": "item-sec",
                                "request_id": "req-stage20-sec",
                                "title": "关于我转生变成史莱姆这档事 第四季",
                                "status": "succeeded",
                                "reason": None,
                                "error_type": None,
                                "attempts": 2,
                            }
                        ],
                        "summary": {
                            "succeeded": 1,
                            "failed": 0,
                            "retryable": 0,
                            "skipped": 0,
                        },
                    },
                },
                ensure_ascii=False,
            ),
        )

    page.route("**/api/v1/batches/parse", _fulfill_batch)
    page.route("**/api/v1/requests/preview-save", _save_preview)
    page.route("**/api/v1/batches/batch-stage20-sec/accept*", _accept)
    page.route("**/api/v1/batches/batch-stage20-sec/submit*", _submit)
    page.route("**/api/v1/batches/batch-stage20-sec/retry*", _retry)

    set_storage_preferences(page, storage_dir, save_request=False)
    page.goto(f"{live_server_url}/index")
    page.get_by_role("tab", name="批量搜索").click()
    page.fill("#batch-raw-input", "萌王S4\n路哥S4")
    page.click("#batch-parse-submit")
    expect(page.locator(".batch-draft-card")).to_have_count(2)
    page.locator(".batch-draft-card", has_text="萌王S4").locator(
        ".batch-card-expand"
    ).click()

    page.once("dialog", lambda dialog: dialog.accept())
    page.locator(".batch-detail-accept").click()
    page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)

    # 批量提交 → 单项失败，出现单项重试按钮
    page.select_option("#batch-queue-ab-auth-mode", "api_token")
    page.fill("#batch-queue-ab-endpoint", "https://ab.example.invalid/api")
    page.fill("#batch-queue-ab-token", "stage20-user-typed-token")
    page.check("#batch-queue-ab-confirm")
    page.click("#batch-queue-submit-button")
    page.wait_for_selector("#page-notification:not([hidden])", timeout=5000)
    item = page.locator('.batch-queue-item[data-item-id="item-sec"]')
    expect(item.locator(".batch-queue-status")).to_contain_text("提交失败")
    expect(item.locator(".batch-queue-item-retry")).to_have_count(1)

    # 单项重试成功 → SUCCEEDED，按钮消失，敏感输入清空。
    # 批量提交成功后敏感输入已被清空，重试前重新填写公开的 AB 配置。
    page.fill("#batch-queue-ab-endpoint", "https://ab.example.invalid/api")
    page.fill("#batch-queue-ab-token", "stage20-user-typed-token")
    page.check("#batch-queue-ab-confirm")
    page.click('.batch-queue-item[data-item-id="item-sec"] .batch-queue-item-retry')
    expect(item.locator(".batch-queue-status")).to_contain_text("提交成功")
    expect(item.locator(".batch-queue-item-retry")).to_have_count(0)
    expect(page.locator("#batch-queue-ab-endpoint")).to_have_value("")
    expect(page.locator("#batch-queue-ab-token")).to_have_value("")

    # 单项重试请求体只携带公开 request_id 与用户填写的 ab_config，绝不携带
    # 队列中复制的完整 RSS/token/cookie/magnet/原始响应。
    assert retry_calls
    retry_payload = retry_calls[0]
    assert retry_payload["request_id"] == "req-stage20-sec"
    assert retry_payload["ab_config"]["auth_mode"] == "api_token"
    assert retry_payload["ab_config"]["base_url"] == "https://ab.example.invalid/api"
    assert retry_payload["ab_config"]["token"] == "stage20-user-typed-token"
    assert retry_payload["confirm"] is True
    for value in sensitive_values:
        assert value not in json.dumps(retry_payload, ensure_ascii=False)

    browser_state = page.evaluate(
        """() => ({
            url: window.location.href,
            localStorage: JSON.stringify(window.localStorage),
            sessionStorage: JSON.stringify(window.sessionStorage),
            bodyText: document.body.innerText,
        })"""
    )
    serialized_calls = json.dumps(
        saved_calls + accept_calls + submit_calls + retry_calls,
        ensure_ascii=False,
    )
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

    # 真实队列 JSON 的 last_error 在写盘前已被脱敏，不包含失败 URL 与 token。
    queue_body = (storage_dir / "queue" / "batch-stage20-sec.json").read_text(
        encoding="utf-8"
    )
    assert "Auto Bangumi HTTP 提交失败" in queue_body
    assert sensitive_values[7] not in queue_body
    assert sensitive_values[1] not in queue_body
    assert "stage20-secret" not in queue_body


def test_stage21_preferences_corrections_do_not_leak_sensitive_values(
    page: Page, live_server_url: str, storage_dir: Path
) -> None:
    """US-157: Stage 21 preference/correction end-to-end security regression.

    Feeds endpoint / token / Authorization header / cookie / raw HTML / raw RSS
    XML / raw response body / full failed URL / local absolute path through (a) a
    poisoned preference save on ``/settings``, (b) poisoned correction saves via
    the real corrections API, and (c) a poisoned batch parse response whose
    preference/review/search-source metadata carries the values as extra ignored
    keys. Asserts the values never reach the preference/correction JSON, the API
    responses, the page, the URL, browser storage, console logs, or the persisted
    storage JSON — while the public preference/review/search-source content still
    renders (proving the whitelist boundary works, not just that the values are
    absent).
    """
    sensitive_values = (
        "http://private-llm.stage21.local/v1/chat/completions",
        "stage21-provider-token",
        "Bearer stage21-authorization-token",
        "stage21-cookie",
        "<html>stage21 raw html</html>",
        "<rss version='2.0'>stage21 raw rss</rss>",
        "stage21 raw response body",
        "https://mikan.example/Home/Search?searchstr=stage21-secret",
        "/home/ghostning/stage21-secret.xml",
        "magnet:?xt=urn:btih:stage21sensitivehash",
    )

    console_messages: list[str] = []
    page.on("console", lambda msg: console_messages.append(msg.text))
    page.on("pageerror", lambda exc: console_messages.append(str(exc)))

    # ------------------------------------------------------------------
    # Part A: /settings 偏好保存流程（真实后端）。被拒绝的敏感输入回退到
    # 上次有效值且不回显；合法非敏感偏好可保存、持久化并重新渲染。
    # ------------------------------------------------------------------
    set_storage_preferences(page, storage_dir)
    page.goto(f"{live_server_url}/settings")
    expect(page.locator("#preference-settings-status")).to_contain_text(
        "已读取偏好默认值", timeout=5000
    )

    page.fill("#preference-preferred-groups", sensitive_values[0])
    page.click("#preference-settings-save")
    expect(page.locator("#preference-settings-error")).to_contain_text(
        "敏感内容", timeout=5000
    )
    expect(page.locator("#preference-settings-status")).to_contain_text(
        "保存偏好默认值失败", timeout=5000
    )
    # 被拒绝的敏感输入不会残留在表单控件中。
    assert page.locator("#preference-preferred-groups").input_value() == ""

    page.fill("#preference-preferred-groups", "喵萌字幕组\nLoli字幕组")
    page.fill("#preference-excluded-groups", "其他")
    page.fill("#preference-filter-must-contain", "1080p")
    page.fill("#preference-filter-must-not-contain", "V2")
    page.locator("#preference-naming-template").fill("[{title}]")
    page.click("#preference-settings-save")
    expect(page.locator("#preference-settings-status")).to_contain_text(
        "偏好默认值已保存", timeout=5000
    )
    assert page.locator("#preference-preferred-groups").input_value() == (
        "喵萌字幕组\nLoli字幕组"
    )

    preferences_json = (storage_dir / "preferences" / "user_preferences.json")
    assert preferences_json.exists()
    preferences_body = preferences_json.read_text(encoding="utf-8")
    assert "喵萌字幕组" in preferences_body
    assert "[{title}]" in preferences_body

    # ------------------------------------------------------------------
    # Part B: 修正 API 流程（真实后端）。被拒绝的敏感修正不回显、不落盘；
    # 合法非敏感修正保存后可通过 GET 读取，且只含公开非敏感字段。
    # ------------------------------------------------------------------
    def _post_corrections(correction: dict[str, Any]):
        return page.request.post(
            f"{live_server_url}/api/v1/corrections",
            data=json.dumps(
                {"storage_dir": str(storage_dir), "correction": correction},
                ensure_ascii=False,
            ),
            headers={"Content-Type": "application/json"},
        )

    poisoned = _post_corrections(
        {
            "raw_title": sensitive_values[0],
            "canonical_title": "关于我转生变成史莱姆这档事 第四季",
            "query_correction": "转生史莱姆 第四季",
        }
    )
    poisoned_body = poisoned.text()
    # 业务错误统一走 HTTP 200 + ok:false envelope，被拒绝的敏感修正不回显。
    assert json.loads(poisoned_body)["ok"] is False
    assert "validation_error" in poisoned_body
    for value in sensitive_values:
        assert value not in poisoned_body

    ok = _post_corrections(
        {
            "raw_title": "萌王S4",
            "canonical_title": "关于我转生变成史莱姆这档事 第四季",
            "season_hint": "S4",
            "query_correction": "转生史莱姆 第四季",
        }
    )
    assert ok.status == 200
    ok_body = ok.text()
    ok_corrections = json.loads(ok_body)["result"]["corrections"]
    assert ok_corrections[0]["raw_title"] == "萌王S4"
    assert ok_corrections[0]["query_correction"] == "转生史莱姆 第四季"
    for value in sensitive_values:
        assert value not in ok_body

    get_body = page.request.get(
        f"{live_server_url}/api/v1/corrections",
        params={"storage_dir": str(storage_dir)},
    ).text()
    get_corrections = json.loads(get_body)["result"]["corrections"]
    assert get_corrections[0]["raw_title"] == "萌王S4"
    assert get_corrections[0]["query_correction"] == "转生史莱姆 第四季"
    for value in sensitive_values:
        assert value not in get_body

    corrections_json = storage_dir / "corrections" / "corrections.json"
    assert corrections_json.exists()
    corrections_body = corrections_json.read_text(encoding="utf-8")
    assert "萌王S4" in corrections_body
    for value in sensitive_values:
        assert value not in corrections_body

    # ------------------------------------------------------------------
    # Part C: 批量解析渲染边界（前端渲染器 + 真实后端，parse 端点 mock）。
    # 中毒的 preference/review/search-source 元数据把全部敏感值作为额外被
    # 忽略的键携带，前端渲染器必须只渲染白名单公开字段。
    # ------------------------------------------------------------------
    first_preview = {
        # 标题必须命中 static fixture catalog（config/system/static_mikan_sources.json
        # 仅含「咒术回战 第三季」「葬送的芙莉莲」），否则 generate_request 返回 None。
        **generate_request(EntryRequest(raw_title="咒术回战"))["request"],
        "request_id": "req-stage21-sec",
    }
    second_preview = {
        **generate_request(EntryRequest(raw_title="葬送的芙莉莲"))["request"],
        "request_id": "req-stage21-other",
    }

    batch_body = json.dumps(
        {
            "ok": True,
            "result": {
                "batch_id": "batch-stage21-sec",
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
                        "confidence": 0.6,
                        "needs_user_review": True,
                        "source": "fake",
                        # 公开命中摘要正常渲染，敏感值作为额外被忽略的键。
                        "preference_hits": [
                            {
                                "field": "subtitle_groups",
                                "applied": True,
                                "summary": "字幕组偏好已作为可编辑默认值",
                                "token": sensitive_values[1],
                            },
                            {
                                "field": "filter_rule",
                                "applied": True,
                                "summary": "筛选默认值已作为可编辑默认规则",
                            },
                            {
                                "field": "naming",
                                "applied": True,
                                "summary": "命名偏好已作为可编辑默认值",
                            },
                        ],
                        "preference_warnings": ["字幕组偏好未命中，使用默认流程"],
                        "review_hints": [
                            "低置信度，请核对候选标题",
                            "存在多个候选，请确认选择",
                        ],
                        "enhanced_search_queries": [
                            {
                                "query": "转生史莱姆 第四季",
                                "original_query": "转生史莱姆",
                                "source": "correction:canonical",
                                "token": sensitive_values[1],
                            }
                        ],
                        # 公开默认配置字段渲染；endpoint/token/cookie/raw 等
                        # 额外键必须被渲染器忽略。
                        "applied_preferences": {
                            "subtitle_groups": {
                                "preferred": ["喵萌字幕组"],
                                "excluded": [],
                                "fallback": "next_preferred",
                                "endpoint": sensitive_values[0],
                            },
                            "filter_rule": {
                                "must_contain": "1080p",
                                "must_not_contain": "V2",
                                "use_regex": False,
                                "case_sensitive": False,
                                "token": sensitive_values[1],
                            },
                            "naming": {
                                "strategy": "official_title_season",
                                "template": "[{title}]",
                                "raw_rss_xml": sensitive_values[5],
                            },
                            "expected_folder_name": "关于我转生变成史莱姆这档事 第四季",
                            "authorization": sensitive_values[2],
                            "raw_html": sensitive_values[4],
                            "cookie": sensitive_values[3],
                            "magnet": sensitive_values[9],
                            "failed_url": sensitive_values[7],
                            "local_path": sensitive_values[8],
                            "raw_response_body": sensitive_values[6],
                        },
                        "candidates": [
                            {
                                "bangumi_id": "42",
                                "title": "关于我转生变成史莱姆这档事 第四季",
                                "mikan_url": "https://mikan.example/Home/Bangumi/42",
                                "poster_url": None,
                                "source_query": "转生史莱姆 第四季",
                                "aliases": [],
                                "recommendation": None,
                                "raw_html": sensitive_values[4],
                                "raw_rss_xml": sensitive_values[5],
                                "cookie": sensitive_values[3],
                                "token": sensitive_values[1],
                                "magnet": sensitive_values[9],
                                "failed_url": sensitive_values[7],
                            }
                        ],
                        "confirmable_config": {
                            "selected_subtitle_group": "喵萌字幕组",
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
                            "matched_bangumi": {
                                "title": "关于我转生变成史莱姆这档事 第四季"
                            },
                            "raw_html": sensitive_values[4],
                            "raw_rss_xml": sensitive_values[5],
                            "cookie": sensitive_values[3],
                            "token": sensitive_values[1],
                            "authorization": sensitive_values[2],
                            "raw_response_body": sensitive_values[6],
                            "local_path": sensitive_values[8],
                            "magnet": sensitive_values[9],
                            "rss_sources": [
                                {
                                    "subtitle_group": "喵萌字幕组",
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
                        # provider_response 是 LLM 提供商的响应，包含全部敏感值；
                        # 它们只允许存在于预览/请求快照，绝不能进入任何响应边界。
                        "provider_response": {
                            "endpoint": sensitive_values[0],
                            "token": sensitive_values[1],
                            "authorization": sensitive_values[2],
                            "raw_response_body": sensitive_values[6],
                            "magnet": sensitive_values[9],
                        },
                    },
                    {
                        # 无偏好/偏好读取失败场景：applied_preferences 与
                        # preference_hits 为 null，警告提示回退默认流程。
                        "item_id": "item-other",
                        "raw_title": "路哥S4",
                        "status": "DRAFT",
                        "canonical_title_candidates": ["实力至上主义教室 第四季"],
                        "season_hint": "S4",
                        "search_queries": ["实力至上主义教室 第四季"],
                        "confidence": 0.8,
                        "needs_user_review": True,
                        "source": "fake",
                        "preference_hits": None,
                        "preference_warnings": ["偏好读取失败，已回退默认流程"],
                        "review_hints": ["偏好不可用，请使用默认流程核对"],
                        "enhanced_search_queries": [],
                        "applied_preferences": None,
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

    parse_calls: list[dict[str, Any]] = []

    def _fulfill_batch(route: Any, request: Request) -> None:
        parse_calls.append(json.loads(request.post_data or "{}"))
        route.fulfill(status=200, content_type="application/json", body=batch_body)

    page.route("**/api/v1/batches/parse", _fulfill_batch)

    page.goto(f"{live_server_url}/index")
    page.get_by_role("tab", name="批量搜索").click()
    page.fill("#batch-raw-input", "萌王S4\n路哥S4")
    page.click("#batch-parse-submit")
    expect(page.locator(".batch-draft-card")).to_have_count(2, timeout=5000)

    first_card = page.locator(".batch-draft-card", has_text="萌王S4")
    second_card = page.locator(".batch-draft-card", has_text="路哥S4")
    # 公开偏好命中摘要与回退提示正常渲染（白名单边界生效，而非只做断言）。
    expect(first_card.locator(".batch-card-preference")).to_contain_text(
        "偏好命中：字幕组、筛选、命名"
    )
    expect(first_card.locator(".batch-card-review-status")).to_contain_text(
        "需人工核对"
    )
    expect(second_card.locator(".batch-card-preference")).to_contain_text(
        "偏好不可用，已回退默认流程"
    )

    # 通过共享详情查看偏好与审核、当前默认配置和搜索词来源。
    first_card.locator(".batch-card-expand").click()
    review_text = page.locator("#request-detail-container").inner_text()
    assert "偏好与审核" in review_text
    assert "偏好命中摘要" in review_text
    assert "字幕组偏好已作为可编辑默认值" in review_text
    assert "当前默认配置" in review_text
    assert "喵萌字幕组" in review_text
    assert "[{title}]" in review_text
    assert "搜索词来源" in review_text
    assert "修正增强搜索词" in review_text
    assert "转生史莱姆 第四季（来源：correction:canonical）" in review_text
    assert "原始搜索词" in review_text

    # parse 请求体只携带用户输入与 storage 上下文，绝不携带敏感值。
    assert parse_calls and parse_calls[0]["raw_input"] == "萌王S4\n路哥S4"
    for value in sensitive_values:
        assert value not in json.dumps(parse_calls, ensure_ascii=False)

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
        for path in storage_dir.rglob("*.json")
    )
    serialized_api = "\n".join(
        [poisoned_body, ok_body, get_body, batch_body]
    )
    for value in sensitive_values:
        assert value not in browser_state["url"]
        assert value not in browser_state["localStorage"]
        assert value not in browser_state["sessionStorage"]
        assert value not in browser_state["bodyText"]
        assert value not in storage_json
        assert value not in preferences_body
        assert value not in corrections_body
    # 浏览器 console / pageerror 也不得包含敏感值（日志/trace 表面）。
    for message in console_messages:
        for value in sensitive_values:
            assert value not in message
    # 中毒 batch 响应只在 mock 层出现（serialized_api 是测试自身的输入），
    # 但它证明前端渲染器没有把任何敏感值带进页面/存储表面。
    assert sensitive_values[0] in serialized_api
