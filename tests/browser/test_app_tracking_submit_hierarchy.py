"""Issue 116：追番详情里外部写的连接门控与操作层级的真实 Chromium 门禁。

覆盖：

- 缺少已保存 Auto Bangumi 连接时，「提交方案」「重试提交」、批量提交与外部管理操作
  可见但禁用，并在原处提示先去设置连接；点击不会产生任何外部写请求；
- 已保存连接时，即使最近探测失败（连接状态未知、能力为空）也不在前端预先禁用，
  由服务端在请求内复核。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import set_storage_preferences

pytestmark = pytest.mark.browser

CONNECTION_REF = "11111111-1111-4111-8111-111111111111"


def _unconfigured_summary() -> dict[str, Any]:
    return {
        "ok": True,
        "result": {
            "configured": False,
            "credential_present": False,
            "connection_status": "UNCONFIGURED",
            "capabilities": None,
        },
    }


def _configured_probe_failed_summary() -> dict[str, Any]:
    return {
        "ok": True,
        "result": {
            "configured": True,
            "credential_present": True,
            "connection_ref": CONNECTION_REF,
            "configuration_revision": 2,
            "connection_status": "UNKNOWN",
            "capabilities": None,
        },
    }


SUBMIT_ACTION = {
    "code": "SUBMIT",
    "label": "提交方案",
    "style": "PRIMARY",
    "requires_confirmation": True,
    "target_scopes": [],
}
RETRY_ACTION = {
    "code": "RETRY",
    "label": "重试提交",
    "style": "PRIMARY",
    "requires_confirmation": True,
    "target_scopes": [],
}
MODIFY_ACTION = {
    "code": "MODIFY",
    "label": "修改外部订阅",
    "style": "SECONDARY",
    "requires_confirmation": True,
    "target_scopes": ["SUBSCRIPTION"],
}


def _item(*, status: str, status_label: str, status_group: str, actions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "tracking_id": "tracking-116",
        "request_id": "request-116",
        "title": "葬送的芙莉莲",
        "season": 1,
        "subtitle_group": "喵萌奶茶屋",
        "poster_path": None,
        "status": status,
        "status_label": status_label,
        "status_group": status_group,
        "available_actions": actions,
        "valid_resource_count": 3,
        "updated_episode": None,
        "updated_episode_status": "NOT_IMPLEMENTED",
        "total_episodes": 28,
        "revision": 1,
        "updated_at": "2026-09-13T00:00:00+00:00",
    }


def _detail(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **item,
        "origin": "single",
        "batch_id": None,
        "created_at": "2026-09-01T00:00:00+00:00",
        "last_synced_at": None,
        "safe_info": None,
        "current_operation": None,
        "revalidation_issues": [],
        "external_mapping": {"match_reason": "标题", "enabled": True, "external_deleted": False},
        "audit_events": [],
        "warnings": [],
    }


def _open(page: Page, live_server_url: str, storage_dir, item: dict[str, Any], summary: dict[str, Any]) -> None:
    page.route(
        "**/api/v1/settings/autobangumi",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(summary, ensure_ascii=False)
        ),
    )

    def handler(route: Any, request: Any) -> None:
        if request.method != "GET" or "/api/v1/tracking/items" not in request.url:
            route.continue_()
            return
        if f"/api/v1/tracking/items/{item['tracking_id']}" in request.url:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"ok": True, "result": _detail(item)}, ensure_ascii=False),
            )
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "ok": True,
                    "result": {
                        "items": [item],
                        "summary": {
                            "total": 1,
                            "pending": 1 if item["status_group"] == "PENDING" else 0,
                            "processing": 0,
                            "active": 1 if item["status_group"] == "ACTIVE" else 0,
                            "inactive": 0,
                            "needs_attention": 0,
                            "added_to_download": 0,
                            "unreadable": 0,
                        },
                        "warnings": [],
                    },
                },
                ensure_ascii=False,
            ),
        )

    page.route("**/api/v1/tracking/items*", handler)
    page.route("**/api/v1/tracking/items/**", handler)
    set_storage_preferences(page, storage_dir)
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{live_server_url}/app/tracking")
    page.wait_for_selector("#tracking-overview")
    page.locator(".tracking-list-item").first.click()
    page.wait_for_selector(".tracking-inspector-content")


def test_pending_record_without_saved_connection_keeps_submit_visible_but_disabled(
    page: Page, live_server_url: str, storage_dir
) -> None:
    item = _item(status="PENDING_SUBMIT", status_label="待提交", status_group="PENDING", actions=[SUBMIT_ACTION, RETRY_ACTION])
    _open(page, live_server_url, storage_dir, item, _unconfigured_summary())

    submit = page.locator("#tracking-submit")
    expect(submit).to_be_visible()
    expect(submit).to_be_disabled()
    hint = page.locator("#tracking-submit-connection-required")
    expect(hint).to_be_visible()
    expect(hint).to_contain_text("先在设置中连接 Auto Bangumi")

    # 缺少连接时不弹确认、不发外部写请求。
    submitted: list[str] = []
    page.on("request", lambda request: submitted.append(request.url))
    submit.click(force=True)
    page.wait_for_timeout(200)
    assert not [url for url in submitted if "tracking" in url and url.endswith("/submit")]


def test_saved_connection_enables_submit_even_when_probe_failed(
    page: Page, live_server_url: str, storage_dir
) -> None:
    item = _item(status="PENDING_SUBMIT", status_label="待提交", status_group="PENDING", actions=[SUBMIT_ACTION])
    _open(page, live_server_url, storage_dir, item, _configured_probe_failed_summary())

    submit = page.locator("#tracking-submit")
    expect(submit).to_be_visible()
    expect(submit).to_be_enabled()
    expect(page.locator("#tracking-submit-connection-required")).to_have_count(0)
    # AC2：探测失败只影响诊断展示，不是前端准入门槛。
    expect(page.locator(".tracking-inspector")).not_to_contain_text("先在设置中连接 Auto Bangumi")


def test_active_record_management_actions_are_disabled_without_connection(
    page: Page, live_server_url: str, storage_dir
) -> None:
    item = _item(status="ACTIVE", status_label="追番中", status_group="ACTIVE", actions=[MODIFY_ACTION])
    _open(page, live_server_url, storage_dir, item, _unconfigured_summary())

    expect(page.locator("#tracking-modify-heading")).to_be_visible()
    expect(page.locator("#tracking-modify-connection-required")).to_be_visible()
    expect(page.locator("#tracking-modify-connection-required")).to_contain_text(
        "先在设置中连接 Auto Bangumi"
    )
