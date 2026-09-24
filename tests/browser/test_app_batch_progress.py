"""Issue 112：批量逐部进度与「整批完成后才切屏」的真实 Chromium 门禁。

覆盖：

- 搜索期间停留在批量首屏，按实际完成部数分段显示进度，不提前出现可审核条目；
- 进度只来自服务端逐部完成事件，不做时间估算；刷新/关闭不续接的文案在首屏可见；
- 整批拿到稳定结果后才进入工作台；
- 中途断流不会把半批结果当作完成。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import set_storage_preferences
from tests.browser.test_app_batch_workbench import _batch_item, _candidate, _goto_batch

pytestmark = pytest.mark.browser


def _sse_body(items: list[dict[str, Any]], total: int) -> str:
    frames: list[str] = []
    for index, item in enumerate(items, start=1):
        frames.append(
            "event: item\ndata: "
            + json.dumps(
                {"completed": index, "total": total, "item": item}, ensure_ascii=False
            )
            + "\n\n"
        )
    frames.append(
        "event: result\ndata: "
        + json.dumps(
            {
                "ok": True,
                "result": {
                    "batch_id": "batch-progress",
                    "raw_input": "甲\n乙",
                    "items": items,
                },
            },
            ensure_ascii=False,
        )
        + "\n\n"
    )
    return "".join(frames)


def _held_parse(page: Page) -> list[Any]:
    held: list[Any] = []

    def handler(route: Any, request: Any) -> None:
        if request.method != "POST":
            route.continue_()
            return
        held.append(route)

    page.route("**/api/v1/batches/parse", handler)
    return held


def _two_items() -> list[dict[str, Any]]:
    return [
        _batch_item(
            "item-a",
            "甲",
            candidates=[
                _candidate(
                    bangumi_id="42",
                    title="甲合集",
                    mikan_url="https://mikan.example/Home/Bangumi/42",
                )
            ],
        ),
        _batch_item(
            "item-b",
            "乙",
            candidates=[
                _candidate(
                    bangumi_id="43",
                    title="乙合集",
                    mikan_url="https://mikan.example/Home/Bangumi/43",
                )
            ],
        ),
    ]


def test_progress_stays_on_the_first_screen_until_the_batch_completes(
    page: Page, live_server_url: str, storage_dir
) -> None:
    set_storage_preferences(page, storage_dir)
    held = _held_parse(page)
    _goto_batch(page, live_server_url)
    page.fill("#batch-raw-input", "甲\n乙")
    page.click("#batch-parse-submit")

    progress = page.locator("#batch-search-progress")
    expect(progress).to_be_visible()
    # 分段按输入部数；未完成时没有一段被点亮，也不会提前出现条目。
    expect(progress).to_contain_text("已完成 0 / 2 部")
    expect(page.locator(".batch-progress-segment")).to_have_count(2)
    expect(page.locator(".batch-progress-segment.is-complete")).to_have_count(0)
    expect(page.locator(".batch-draft-card")).to_have_count(0)
    expect(page.locator("#batch-progress-note")).to_contain_text("刷新或关闭后需要重新搜索")
    expect(page.locator("#batch-progress-note")).to_contain_text("不因此被取消")

    assert held, "批量解析请求没有发出"
    items = _two_items()
    held[0].fulfill(status=200, content_type="text/event-stream", body=_sse_body(items, 2))

    # 整批完成后才出现工作台条目，进度条随之消失。
    expect(page.locator(".batch-draft-card")).to_have_count(2)
    expect(progress).to_have_count(0)
    # 整批完成后把工作台带入视野并移焦点。
    expect(page.locator("#panel-section-批量工作台")).to_be_in_viewport()
    expect(page.locator("#panel-section-批量工作台")).to_be_focused()


def test_partial_stream_never_enters_the_workbench(
    page: Page, live_server_url: str, storage_dir
) -> None:
    set_storage_preferences(page, storage_dir)
    held = _held_parse(page)
    _goto_batch(page, live_server_url)
    page.fill("#batch-raw-input", "甲\n乙")
    page.click("#batch-parse-submit")

    assert held, "批量解析请求没有发出"
    # 只推送第一部完成，随后断流：不能把半批当成完成。
    partial = (
        "event: item\ndata: "
        + json.dumps(
            {"completed": 1, "total": 2, "item": _two_items()[0]}, ensure_ascii=False
        )
        + "\n\n"
    )
    held[0].fulfill(status=200, content_type="text/event-stream", body=partial)

    expect(page.locator(".batch-draft-card")).to_have_count(0)
    # 失败就地呈现在工作台区域，不进入可审核状态。
    expect(page.locator(".batch-workbench-panel")).to_contain_text("批量草案获取失败")
    expect(page.locator("#batch-search-progress")).to_have_count(0)
    # 半批数据不渲染，也不泄露候选地址等原始值。
    assert "mikan.example" not in page.locator("body").inner_text()
