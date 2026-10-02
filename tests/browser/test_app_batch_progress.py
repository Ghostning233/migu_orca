"""Issue 112：批量逐部进度与「整批完成后才切屏」的真实 Chromium 门禁。

覆盖：

- 搜索期间停留在批量首屏，按实际完成部数分段显示进度，不提前出现可审核条目；
- 进度只来自服务端逐部完成事件，不做时间估算；刷新/关闭不续接的文案在首屏可见；
- 整批拿到稳定结果后才进入工作台；
- 中途断流不会把半批结果当作完成。
"""

from __future__ import annotations

import json
import threading
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import set_storage_preferences
from tests.browser.screen_support import wait_for_screen_scroll
from tests.browser.test_app_batch_workbench import _batch_item, _candidate, _goto_batch

pytestmark = pytest.mark.browser

MEASURE_SCREEN_POSITION = """
() => {
  const padding = Number.parseFloat(
    getComputedStyle(document.documentElement).scrollPaddingTop) || 0
  const screen = document.querySelector('.batch-workbench-screen')
  const top = screen ? screen.getBoundingClientRect().top + window.scrollY - padding : null
  return {
    scrollY: window.scrollY,
    workbenchTop: top,
    documentHeight: document.documentElement.scrollHeight,
  }
}
"""


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


def test_workbench_stays_on_the_second_screen_after_the_batch_settles(
    page: Page, live_server_url: str, storage_dir
) -> None:
    """缺陷回归：整批完成自动进入工作台后，无手势时不得自己跳回搜索首屏。

    用户实际复现：批量搜索结束先进入候选工作台，几秒后自动跳回搜索首屏，必须手动再
    向下滚动才能回到工作台。这里不产生任何滚轮、触控板、键盘、点击或路由变化，持续
    采样文档位置与第二屏顶位，覆盖提示条自动关闭的整个时间窗（success 为 10s），
    之后仍必须停在第二屏真实顶部。
    """
    set_storage_preferences(page, storage_dir)
    page.set_viewport_size({"width": 1440, "height": 900})
    held = _held_parse(page)
    _goto_batch(page, live_server_url)
    page.fill("#batch-raw-input", "甲\n乙")
    page.click("#batch-parse-submit")

    items = _two_items()
    held[0].fulfill(status=200, content_type="text/event-stream", body=_sse_body(items, 2))

    expect(page.locator(".batch-draft-card")).to_have_count(2)
    wait_for_screen_scroll(page)
    expect(page.locator("#panel-section-批量工作台")).to_be_in_viewport()
    # 整批完成的汇总提示条确实出现过：它是本回归的关键上下文。
    expect(page.locator(".global-notification")).to_have_count(1)
    settled = page.evaluate(MEASURE_SCREEN_POSITION)
    assert settled["workbenchTop"] is not None
    assert abs(settled["scrollY"] - settled["workbenchTop"]) <= 2, settled

    # 只观察、不交互：13 秒内每 250ms 采样一次位置（覆盖 10s 自动关闭 + 动画兜底）。
    samples: list[dict[str, float | None]] = []
    for _ in range(52):
        page.wait_for_timeout(250)
        samples.append(page.evaluate(MEASURE_SCREEN_POSITION))
    expect(page.locator(".global-notification")).to_have_count(0)

    offsets = [
        round(float(sample["scrollY"]) - float(sample["workbenchTop"]), 1)
        for sample in samples
    ]
    drifted = [
        (round(index * 0.25, 2), offset)
        for index, offset in enumerate(offsets)
        if abs(offset) > 2
    ]
    assert not drifted, (
        "整批完成后文档位置自行漂移（秒, 相对工作台顶部的偏移）",
        drifted[:6],
        settled,
        samples[-1],
    )
    # 工作台标题仍在视口内，没有回到搜索首屏。
    expect(page.locator("#panel-section-批量工作台")).to_be_in_viewport()
    assert page.evaluate("() => window.scrollY") > 100


def test_switch_target_comes_from_the_final_settled_layout(
    page: Page, live_server_url: str, storage_dir
) -> None:
    """#145 A：批量解析完成后，滚动位置必须稳定落在工作台顶部。

    搜索收尾（进度条撤掉）会改变第一屏高度，第二屏的相对文档 top 随之变化；这里在
    切屏前记录第一屏高度、切屏后记录第二屏文档 top，并逐帧确认「切屏开始时目标已经
    稳定」——只按第二屏高度判断稳定性的实现会取到过期坐标。
    """
    set_storage_preferences(page, storage_dir)
    # 视口高度取小一些，让进度条真的把首屏撑高，切屏前后的 top 差异足够大。
    page.set_viewport_size({"width": 1280, "height": 600})
    held = _held_parse(page)
    _goto_batch(page, live_server_url)
    page.fill("#batch-raw-input", "甲\n乙")
    page.click("#batch-parse-submit")

    progress = page.locator("#batch-search-progress")
    expect(progress).to_be_visible()
    before = page.evaluate(
        """() => {
          const first = document.querySelector('.batch-search-screen')
          return { firstHeight: first.getBoundingClientRect().height, progress: true }
        }"""
    )
    assert before["progress"] is True

    # 逐帧记录：切屏开始时第二屏的文档 top 与最终 top 必须一致。
    page.evaluate(
        """() => {
          window.__frames = []
          const sample = () => {
            const screen = document.querySelector('.batch-workbench-screen')
            const first = document.querySelector('.batch-search-screen')
            const padding = Number.parseFloat(
              getComputedStyle(document.documentElement).scrollPaddingTop) || 0
            window.__frames.push({
              t: Math.round(performance.now()),
              y: Math.round(window.scrollY),
              top: screen ? Math.round(screen.getBoundingClientRect().top + window.scrollY - padding) : null,
              firstHeight: first ? Math.round(first.getBoundingClientRect().height) : null,
              progress: Boolean(document.querySelector('#batch-search-progress')),
            })
          }
          window.__frameTimer = setInterval(sample, 16)
          sample()
        }"""
    )

    held[0].fulfill(status=200, content_type="text/event-stream", body=_sse_body(_two_items(), 2))
    expect(page.locator(".batch-draft-card")).to_have_count(2)
    wait_for_screen_scroll(page)
    frames = page.evaluate("() => { clearInterval(window.__frameTimer); return window.__frames }")

    final = page.evaluate(MEASURE_SCREEN_POSITION)
    assert final["workbenchTop"] is not None
    assert abs(final["scrollY"] - final["workbenchTop"]) <= 2, (final, frames[-1])
    # 工作台标题真的在视口里。
    expect(page.locator("#panel-section-批量工作台")).to_be_in_viewport()

    # 收尾确实改变了第一屏高度：只按高度判断稳定的实现会在这里取到过期 top。
    first_heights = [frame["firstHeight"] for frame in frames if frame["firstHeight"] is not None]
    assert min(first_heights) < max(first_heights) - 20, (before, min(first_heights), max(first_heights))

    # 切屏开始（scrollY 第一次离开 0）之后，第二屏 top 不得再变化。
    started = next((frame for frame in frames if frame["y"] > 2), None)
    assert started is not None, frames[:5]
    tops_after_start = [
        frame["top"] for frame in frames
        if frame["y"] >= started["y"] and frame["top"] is not None
    ]
    assert tops_after_start, frames[-5:]
    assert max(tops_after_start) - min(tops_after_start) <= 2, tops_after_start


def test_mode_switch_is_disabled_while_the_batch_search_is_running(
    page: Page, live_server_url: str, storage_dir
) -> None:
    """#145 B：批量搜索进行中禁止模式切换，避免结果在没有 batch 屏时完成并被隐藏。"""
    set_storage_preferences(page, storage_dir)
    held = _held_parse(page)
    _goto_batch(page, live_server_url)
    page.fill("#batch-raw-input", "甲\n乙")
    page.click("#batch-parse-submit")
    expect(page.locator("#batch-search-progress")).to_be_visible()

    # 可见的切换控件（单番 hero 与批量 hero 各一个）都必须禁用。
    state = page.evaluate(
        """() => {
          const switches = Array.from(document.querySelectorAll('#anime-mode-switch'))
          const visible = switches.filter((node) => node.getClientRects().length > 0)
          return {
            visible: visible.length,
            buttons: visible.flatMap((node) => Array.from(node.querySelectorAll('button'))).map((b) => ({
              id: b.id,
              disabled: b.disabled,
            })),
          }
        }"""
    )
    assert state["visible"] >= 1, state
    assert state["buttons"], state
    assert all(button["disabled"] for button in state["buttons"]), state

    # 强制点击也不能切换：搜索仍在进行，页面还是批量搜索首屏。
    page.locator("#anime-mode-single").first.click(force=True)
    expect(page.locator("#batch-search-progress")).to_be_visible()
    assert page.locator("#batch-raw-input").count() == 1

    # 整批完成后仍能正常自动进入批量工作台。
    held[0].fulfill(status=200, content_type="text/event-stream", body=_sse_body(_two_items(), 2))
    expect(page.locator(".batch-draft-card")).to_have_count(2)
    wait_for_screen_scroll(page)
    expect(page.locator("#panel-section-批量工作台")).to_be_in_viewport()
    assert page.evaluate("() => window.scrollY") > 100


def test_successful_but_empty_batch_result_stays_on_the_search_screen(
    page: Page, live_server_url: str, storage_dir
) -> None:
    """#145 F：HTTP 200 但 items=[] 时留在搜索首屏就地说明，不进入空工作台。"""
    set_storage_preferences(page, storage_dir)
    held = _held_parse(page)
    _goto_batch(page, live_server_url)
    page.fill("#batch-raw-input", "甲\n乙")
    page.click("#batch-parse-submit")

    held[0].fulfill(status=200, content_type="text/event-stream", body=_sse_body([], 2))

    empty = page.locator("#batch-empty-result")
    expect(empty).to_be_visible(timeout=8000)
    expect(empty).to_contain_text("服务端没有返回任何条目")
    # 不能说成 MiKan 故障；也不进入空工作台。
    expect(empty).not_to_contain_text("故障")
    expect(empty).not_to_contain_text("失败")
    assert page.evaluate("() => window.scrollY") <= 2
    assert page.locator(".batch-draft-card").count() == 0
    assert page.locator(".batch-workbench-screen").is_visible() is False
    expect(page.locator("#batch-parse-submit")).to_be_enabled()

    # 重新搜索会清掉这条就地说明。
    page.fill("#batch-raw-input", "甲\n乙")
    page.click("#batch-parse-submit")
    expect(page.locator("#batch-empty-result")).to_have_count(0)


def test_all_items_empty_or_failed_still_enter_the_workbench(
    page: Page, live_server_url: str, storage_dir
) -> None:
    """#145 F：全部条目 EMPTY/FAILED 仍有条目，必须进入工作台逐项处理。"""
    set_storage_preferences(page, storage_dir)
    held = _held_parse(page)
    _goto_batch(page, live_server_url)
    page.fill("#batch-raw-input", "甲\n乙")
    page.click("#batch-parse-submit")

    items = [
        _batch_item("item-a", "甲", status="EMPTY"),
        _batch_item("item-b", "乙", status="FAILED", error={"error_type": "mikan_unavailable", "error_message": "MiKan 候选搜索暂时不可用"}),
    ]
    held[0].fulfill(status=200, content_type="text/event-stream", body=_sse_body(items, 2))

    expect(page.locator(".batch-draft-card")).to_have_count(2)
    wait_for_screen_scroll(page)
    expect(page.locator("#panel-section-批量工作台")).to_be_in_viewport()
    assert page.evaluate("() => window.scrollY") > 100
    # 失败与未找到候选的真实状态仍留在卡片内（顺序由既有异常置顶规则决定）。
    statuses = page.locator(".batch-draft-card .batch-card-status").all_inner_texts()
    assert any("搜索失败" in status for status in statuses), statuses
    assert any("未找到候选" in status for status in statuses), statuses
    assert page.locator("#batch-empty-result").count() == 0


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


def test_real_stream_shows_intermediate_progress_before_the_batch_finishes(
    page: Page,
    live_server_url: str,
    storage_dir,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue 132：真实端点上第一部完成、第二部仍在搜索时就显示 1/2。

    用服务端搜索 seam 上的 `threading.Event` 分阶段释放（不是在 route handler
    里 sleep，也不一次送完全部事件）：第一部事件先到达，断言进度与「仍在首屏、
    无可审核条目」；释放第二部后才出现终态结果与切屏焦点。
    """
    from apps.migu_orca_web import services

    second_release = threading.Event()
    second_started = threading.Event()

    def gated_search(search_queries: list[str], mikan_config: Any) -> list[dict[str, object]]:
        query = search_queries[0] if search_queries else ""
        if "乙" in query:
            second_started.set()
            second_release.wait(timeout=15)
        return []

    # Issue 133：批量解析编排在服务层，seam 也在服务层模块命名空间。
    monkeypatch.setattr(services, "_search_batch_item_candidates", gated_search)

    try:
        set_storage_preferences(page, storage_dir)
        page.set_viewport_size({"width": 1440, "height": 900})
        page.goto(f"{live_server_url}/app/add")
        page.wait_for_selector("#anime-mode-switch", timeout=10_000)
        page.click("#anime-mode-batch")
        page.wait_for_selector("#batch-parse-form", timeout=10_000)
        page.fill("#batch-raw-input", "甲\n乙")
        page.click("#batch-parse-submit")

        # 第一部真实完成：进度推进到 1/2，但仍留在搜索首屏且没有可审核条目。
        progress = page.locator("#batch-search-progress")
        expect(progress).to_contain_text("已完成 1 / 2 部", timeout=15_000)
        expect(page.locator(".batch-progress-segment.is-complete")).to_have_count(1)
        expect(page.locator(".batch-draft-card")).to_have_count(0)
        expect(page.locator("#panel-section-批量工作台")).not_to_be_in_viewport()
        assert page.evaluate("() => document.querySelector('.add-anime-screens').scrollTop") <= 100
        assert second_started.is_set(), "第二部搜索尚未开始"

        # 释放第二部：终态 result 到达后才切屏。
        second_release.set()
        expect(page.locator(".batch-draft-card")).to_have_count(2, timeout=15_000)
        expect(progress).to_have_count(0)
        expect(page.locator("#panel-section-批量工作台")).to_be_focused()
    finally:
        second_release.set()
