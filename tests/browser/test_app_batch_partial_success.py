"""Issue 114：批量保存部分成功与按真实原因恢复的真实 Chromium 门禁。

覆盖：

- HTTP 200 的逐条业务结果：成功项保持成功、取消勾选、不再参与保存，并可打开追番记录；
- 失败项按真实原因只显示一种最小安全恢复动作：草案失效 → 重新生成草案、
  普通可重试失败 → 重试保存、已保存但确认未完成 → 重试确认；
- 不存在统一「重试失败项」，错误摘要脱敏。
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import set_storage_preferences
from tests.browser.test_app_batch_workbench import (
    _batch_item,
    _goto_batch,
    _preview_request,
    _route_parse,
)

pytestmark = pytest.mark.browser

CANARY = "raw-canary https://private.invalid/secret"


def _draft_items() -> list[dict[str, Any]]:
    return [
        _batch_item(
            "item-1",
            "甲S1",
            status="DRAFT",
            canonical_title="甲 第一季",
            preview_request=_preview_request("甲", "req-114-a"),
        ),
        _batch_item(
            "item-2",
            "乙S1",
            status="DRAFT",
            canonical_title="乙 第一季",
            preview_request=_preview_request("乙", "req-114-b"),
        ),
        _batch_item(
            "item-3",
            "丙S1",
            status="DRAFT",
            canonical_title="丙 第一季",
            preview_request=_preview_request("丙", "req-114-c"),
        ),
    ]


def _save_confirm_body() -> str:
    return json.dumps(
        {
            "ok": True,
            "result": {
                "batch_id": "batch-114",
                "results": [
                    {
                        "item_id": "item-1",
                        "outcome": "CONFIRMED",
                        "request_id": "req-114-a",
                        "status": "CONFIRMED",
                        "error_type": None,
                        "error_message": None,
                        "tracking_id": "tracking-114-a",
                        "tracking_ready": True,
                    },
                    {
                        "item_id": "item-2",
                        "outcome": "failed",
                        "request_id": None,
                        "status": None,
                        "error_type": "draft_expired",
                        "error_message": CANARY,
                        "tracking_id": None,
                        "tracking_ready": None,
                    },
                    {
                        "item_id": "item-3",
                        "outcome": "failed",
                        "request_id": None,
                        "status": None,
                        "error_type": "idempotency_conflict",
                        "error_message": CANARY,
                        "tracking_id": None,
                        "tracking_ready": None,
                    },
                ],
                "summary": {"requested": 3, "confirmed": 1, "failed": 2},
            },
        },
        ensure_ascii=False,
    )


def _open_partial_success(page: Page, live_server_url: str, storage_dir) -> None:
    items = _draft_items()
    _route_parse(page, items)
    page.route(
        "**/api/v1/batches/*/save-confirm",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=_save_confirm_body()
        ),
    )
    set_storage_preferences(page, storage_dir)
    _goto_batch(page, live_server_url)
    page.set_viewport_size({"width": 1440, "height": 900})
    page.fill("#batch-raw-input", "甲S1\n乙S1\n丙S1")
    page.click("#batch-parse-submit")
    expect(page.locator(".batch-draft-card")).to_have_count(3)

    for item_id in ("item-1", "item-2", "item-3"):
        page.locator(
            f'.batch-draft-card[data-item-id="{item_id}"] input[type="checkbox"]'
        ).set_checked(True)
    page.click("#batch-accept-submit")
    dialog = page.locator(".confirm-dialog")
    expect(dialog).to_be_visible()
    dialog.locator(".primary-button").click()
    expect(page.locator("#batch-save-summary")).to_be_visible()


def test_partial_success_keeps_successes_and_shows_one_action_per_reason(
    page: Page, live_server_url: str, storage_dir
) -> None:
    _open_partial_success(page, live_server_url, storage_dir)

    success = page.locator('.batch-draft-card[data-item-id="item-1"]')
    # 成功项：已确认、取消勾选、不再提供任何重试保存入口。
    expect(success.locator(".batch-card-status")).to_contain_text("已确认")
    expect(success.locator('input[type="checkbox"]')).not_to_be_checked()
    expect(success.locator("#batch-retry-save-item-1")).to_have_count(0)
    expect(success.locator("#batch-regenerate-draft-item-1")).to_have_count(0)

    # 草案失效 → 重新生成草案；普通失败 → 重试保存。
    expect(page.locator("#batch-regenerate-draft-item-2")).to_have_text("重新生成草案")
    expect(page.locator("#batch-retry-save-item-2")).to_have_count(0)
    expect(page.locator("#batch-retry-save-item-3")).to_have_text("重试保存")
    expect(page.locator("#batch-regenerate-draft-item-3")).to_have_count(0)

    # 部分成功结果常驻可见，且没有统一「重试失败项」。
    expect(page.locator("#batch-save-summary")).to_contain_text("1")
    body = page.locator("body").inner_text()
    assert "重试失败" not in body
    # 错误摘要脱敏：原始 error_message 与地址不进入 DOM。
    assert CANARY not in body
    assert "private.invalid" not in body

    # 成功项可定位到追番：打开追番记录带着公开的 tracking_id 跳转。
    # 仍有失败项未处理，离开工作台先经过既有的离开保护确认。
    success.locator("#batch-open-tracking-item-1").click()
    dialog = page.locator(".confirm-dialog")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("离开批量审核")
    dialog.get_by_role("button", name="确认离开").click()
    expect(page).to_have_url(re.compile(r"tracking_id=tracking-114-a"))


def test_retry_save_uses_a_new_key_and_never_replays_the_failed_one(
    page: Page, live_server_url: str, storage_dir
) -> None:
    bodies: list[dict[str, Any]] = []

    def handler(route: Any, request: Any) -> None:
        bodies.append(request.post_data_json)
        if len(bodies) == 1:
            route.fulfill(
                status=200, content_type="application/json", body=_save_confirm_body()
            )
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "ok": True,
                    "result": {
                        "batch_id": "batch-114",
                        "results": [
                            {
                                "item_id": "item-3",
                                "outcome": "CONFIRMED",
                                "request_id": "req-114-c",
                                "status": "CONFIRMED",
                                "error_type": None,
                                "error_message": None,
                                "tracking_id": "tracking-114-c",
                                "tracking_ready": True,
                            }
                        ],
                        "summary": {"requested": 1, "confirmed": 1, "failed": 0},
                    },
                },
                ensure_ascii=False,
            ),
        )

    items = _draft_items()
    _route_parse(page, items)
    page.route("**/api/v1/batches/*/save-confirm", handler)
    set_storage_preferences(page, storage_dir)
    _goto_batch(page, live_server_url)
    page.set_viewport_size({"width": 1440, "height": 900})
    page.fill("#batch-raw-input", "甲S1\n乙S1\n丙S1")
    page.click("#batch-parse-submit")
    expect(page.locator(".batch-draft-card")).to_have_count(3)
    for item_id in ("item-1", "item-2", "item-3"):
        page.locator(
            f'.batch-draft-card[data-item-id="{item_id}"] input[type="checkbox"]'
        ).set_checked(True)
    page.click("#batch-accept-submit")
    page.locator(".confirm-dialog .primary-button").click()
    expect(page.locator("#batch-save-summary")).to_be_visible()

    page.locator("#batch-retry-save-item-3").click()
    expect(page.locator("#batch-save-summary")).to_contain_text("确认 1")

    assert len(bodies) == 2
    first_keys = {item["item_id"]: item["idempotency_key"] for item in bodies[0]["items"]}
    retry_items = bodies[1]["items"]
    # 重试只提交该条目，且使用新的幂等键（失败那次是确定失败，不复用旧键）。
    assert [item["item_id"] for item in retry_items] == ["item-3"]
    assert retry_items[0]["idempotency_key"]
    assert retry_items[0]["idempotency_key"] != first_keys["item-3"]
