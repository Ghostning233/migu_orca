"""#142：单番合集候选卡四卡同排、响应式与状态稳定的真实 Chromium 门禁。

父规格 #139 已确认的目标：

- 1280／1440／1920 常规桌面下 1～4 个候选同宽、同排、居中，封面、标题、季数证据、
  总集数与主按钮清楚有序，四卡主按钮对齐；卡宽随可用宽度协调变化，旧 332px 不再是
  产品硬要求；
- 更窄视口只能从四列切为两列再切单列，绝不出现 3+1 或水平溢出；超过四项只显示
  前四项与原有截断提示；200% 缩放下文字完整可读；
- 季数核对、草案生成中、生成失败等短反馈可见，且不拉长邻卡、不移动下方内容、
  不让主按钮跳位（不得以隐藏反馈换取几何稳定）；
- 单番与批量合集候选卡都不再有「高级信息」下拉框或替代浮层，页面级搜索诊断仍保留。

本文件对旧实现（固定 332px／最小 240px 造成的 3+1、卡片高级信息入口）是红测。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.screen_support import wait_for_screen_scroll
from tests.browser.test_app_workbench import (
    _candidate,
    _candidate_result_json,
    _goto_workbench,
    _preview_request,
)
from tests.browser.visual_support import browser_surface

pytestmark = pytest.mark.browser

# #177：主按钮底边是亚像素值，固定 Noto CJK 字体下同一状态的前后差值会抖动到
# 1.24px（实测 1.2406 / 1.2420，见 issue #177 的三次 CI 证据）。真正的「按钮跳位」
# 至少是一行文字高（约 20px），所以这里给亚像素度量留 2.0px 余量：既不会把可见
# 跳位放过去，也不会让同一棵代码树在 CI 上先绿后红。
BUTTON_BOTTOM_TOLERANCE_PX = 2.0

CANDIDATE_SPECS: tuple[tuple[str, str, int | None], ...] = (
    ("2353", "葬送的芙莉莲", 28),
    ("3072", "葬送的芙莉莲 第二季", 24),
    ("4096", "葬送的芙莉莲 特别篇", 2),
    ("5120", "葬送的芙莉莲 外传", 12),
    ("6144", "葬送的芙莉莲 剧场版", 1),
)


def _candidates(count: int) -> list[dict[str, Any]]:
    candidates = []
    for index in range(count):
        bangumi_id, title, total = CANDIDATE_SPECS[index]
        candidates.append(
            _candidate(
                bangumi_id=bangumi_id,
                title=title,
                mikan_url=f"https://mikan.example/Home/Bangumi/{bangumi_id}",
                total_episodes=total,
                poster_url=f"/api/v1/mikan/posters/{bangumi_id}" if index % 2 == 0 else None,
            )
        )
    return candidates


def _open_candidates(
    page: Page, live_server_url: str, *, count: int = 3, viewport: tuple[int, int] = (1440, 900)
) -> None:
    page.route(
        "**/api/v1/mikan/candidates",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=_candidate_result_json("芙莉莲", _candidates(count)),
        ),
    )
    _goto_workbench(page, live_server_url)
    page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
    page.fill("#mikan-candidate-query", "芙莉莲")
    page.click("#mikan-candidate-search-submit")
    expect(page.locator(".candidate-card")).to_have_count(min(count, 4))


def _card_boxes(page: Page) -> list[dict[str, float]]:
    """卡片几何；``docY`` 是文档坐标，滚动位置变化不影响「有没有位移」的判断。"""
    return page.evaluate(
        """() => Array.from(document.querySelectorAll('.candidate-card')).map((card) => {
             const box = card.getBoundingClientRect()
             const button = card.querySelector('.candidate-select').getBoundingClientRect()
             return {
               x: box.x, y: box.y, docY: box.y + window.scrollY, width: box.width,
               height: box.height, right: box.right, bottom: box.bottom,
               buttonTop: button.top, buttonBottom: button.bottom,
               buttonDocBottom: button.bottom + window.scrollY,
             }
           })"""
    )


def _row_counts(boxes: list[dict[str, float]]) -> list[int]:
    """按 y 分组统计每行卡片数量。"""
    counts: list[int] = []
    previous_top: float | None = None
    for box in sorted(boxes, key=lambda item: item["y"]):
        if previous_top is None or abs(box["y"] - previous_top) > 1:
            counts.append(1)
        else:
            counts[-1] += 1
        previous_top = box["y"]
    return counts


def _same_box(left: dict[str, float], right: dict[str, float], tolerance: float = 1.0) -> bool:
    return all(
        abs(left[key] - right[key]) <= tolerance
        for key in ("x", "docY", "width", "height")
    )


@pytest.mark.parametrize("count", [1, 2, 3, 4])
@pytest.mark.parametrize("viewport_width", [1280, 1440, 1920])
def test_candidate_row_keeps_one_centered_row_with_equal_buttons(
    page: Page, live_server_url: str, count: int, viewport_width: int
) -> None:
    _open_candidates(page, live_server_url, count=count, viewport=(viewport_width, 900))
    boxes = _card_boxes(page)

    # 一条同排行：所有卡片顶边一致。
    assert len({round(box["y"]) for box in boxes}) == 1, boxes
    # 同宽（允许亚像素舍入）。
    assert len({round(box["width"]) for box in boxes}) == 1, boxes
    # 行内容居中：左右留白对称。
    left = boxes[0]["x"]
    right = viewport_width - boxes[-1]["right"]
    assert abs(left - right) <= 1.5, (left, right)
    # 卡宽随可用宽度协调变化，而不是固定旧值。
    assert boxes[0]["width"] < viewport_width / 3, boxes[0]["width"]
    # 四卡主按钮对齐（同排同底）。
    assert len({round(box["buttonBottom"]) for box in boxes}) == 1, boxes
    assert page.evaluate("() => document.body.scrollWidth") <= viewport_width


@pytest.mark.parametrize(
    ("viewport_width", "expected_rows"),
    [
        (1280, [4]),
        (1000, [2, 2]),
        (760, [2, 2]),
        (520, [1, 1, 1, 1]),
    ],
)
def test_candidate_row_degrades_from_four_to_two_to_one_without_three_plus_one(
    page: Page, live_server_url: str, viewport_width: int, expected_rows: list[int]
) -> None:
    _open_candidates(page, live_server_url, count=4, viewport=(viewport_width, 900))
    rows = _row_counts(_card_boxes(page))
    assert rows == expected_rows, (viewport_width, rows)
    # 绝不出现 3+1。
    assert 3 not in rows
    assert page.evaluate("() => document.body.scrollWidth") <= viewport_width


def test_more_than_four_candidates_render_only_four_with_the_truncation_note(
    page: Page, live_server_url: str
) -> None:
    _open_candidates(page, live_server_url, count=5)
    expect(page.locator(".candidate-card")).to_have_count(4)
    expect(page.locator("#candidate-truncation-note")).to_be_visible()
    expect(page.locator("#candidate-truncation-note")).to_contain_text("仅显示前 4 个")


def test_two_hundred_percent_zoom_keeps_cards_readable_and_overflow_free(
    page: Page, live_server_url: str
) -> None:
    # 720 CSS 视口模拟 1440 桌面在 200% 缩放下的可用宽度。
    _open_candidates(page, live_server_url, count=3, viewport=(720, 450))
    boxes = _card_boxes(page)
    assert len(boxes) == 3
    assert all(box["width"] >= 240 for box in boxes), boxes
    assert page.evaluate("() => document.body.scrollWidth") <= 720
    # 文字完整可读：标题与按钮没有被裁掉。
    assert page.locator(".candidate-title").first.is_visible()
    assert page.locator(".candidate-select").first.is_visible()


def test_short_states_do_not_move_neighbour_cards_or_the_content_below(
    page: Page, live_server_url: str
) -> None:
    held: list[Any] = []

    def hold_generation(route: Any, request: Any) -> None:
        if request.method != "POST":
            route.continue_()
            return
        held.append(route)

    page.route("**/api/v1/requests", hold_generation)
    _open_candidates(page, live_server_url, count=4)
    wait_for_screen_scroll(page)
    before = _card_boxes(page)
    note_script = """() => {
      const anchor = document.querySelector('.title-parse-summary')
      return anchor ? anchor.getBoundingClientRect().top + window.scrollY : null
    }"""
    note_before = page.evaluate(note_script)

    # 第一张卡进入「生成中」短状态。
    page.locator(".candidate-card").first.locator(".candidate-select").click()
    expect(page.locator(".candidate-card").first.locator(".candidate-generating-status")).to_be_visible()
    during = _card_boxes(page)
    note_during = page.evaluate(note_script)
    # 邻卡（2～4）位置与尺寸不变，下方诊断不位移，主按钮不跳位。
    for index in range(1, 4):
        assert _same_box(during[index], before[index]), (index, before[index], during[index])
    assert abs(during[0]["buttonDocBottom"] - before[0]["buttonDocBottom"]) <= BUTTON_BOTTOM_TOLERANCE_PX
    assert note_during == note_before, (note_before, note_during)

    # 释放生成，进入真实草案屏。
    assert len(held) == 1
    held[0].fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps(
            {
                "ok": True,
                "result": {
                    "draft_id": "draft-142",
                    "draft_revision": 1,
                    "request": _preview_request("葬送的芙莉莲", "draft-142"),
                },
            },
            ensure_ascii=False,
        ),
    )
    expect(page.locator("#single-anime-review-step")).to_be_visible()


def test_candidate_generation_failure_stays_inside_the_reserved_feedback_area(
    page: Page, live_server_url: str
) -> None:
    page.route(
        "**/api/v1/requests",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {"ok": False, "error_type": "mikan_timeout", "error_message": "内部错误"},
                ensure_ascii=False,
            ),
        ),
    )
    _open_candidates(page, live_server_url, count=4)
    wait_for_screen_scroll(page)
    before = _card_boxes(page)

    page.locator(".candidate-card").first.locator(".candidate-select").click()
    expect(page.locator(".candidate-generate-error")).to_be_visible()
    after = _card_boxes(page)
    # 失败文案可见，邻卡与下方内容不位移，重试按钮不跳位。
    assert page.locator(".candidate-generate-error").first.inner_text().strip() != ""
    for index in range(1, 4):
        assert _same_box(after[index], before[index]), (index, before[index], after[index])
    assert abs(after[0]["buttonDocBottom"] - before[0]["buttonDocBottom"]) <= BUTTON_BOTTOM_TOLERANCE_PX


def test_candidate_cards_have_no_advanced_information_entry_but_page_diagnostics_remain(
    page: Page, live_server_url: str
) -> None:
    _open_candidates(page, live_server_url, count=3)

    # 卡片不再有「高级信息」入口或替代浮层，也不显示公开合集编号。
    assert page.locator("details.candidate-advanced").count() == 0
    card_text = page.locator(".candidate-list-wrapper").inner_text()
    assert "高级信息" not in card_text
    assert "2353" not in card_text
    # 页面级搜索诊断仍可按需查看。
    diagnostics = page.locator("details.title-parse-summary")
    expect(diagnostics).to_have_count(1)
    diagnostics.locator("summary").click()
    expect(diagnostics.locator("summary")).to_contain_text("标题解析摘要")


def test_long_title_keeps_full_accessible_name_and_hides_canary(
    page: Page, live_server_url: str
) -> None:
    long_title = "葬送的芙莉莲 第二季 超长合集标题用于验证两行截断"
    canary = "us364-candidate-context-canary"
    console_leaks: list[bool] = []
    page.on("console", lambda message: console_leaks.append(canary in message.text))
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
                        title=long_title,
                        mikan_url="https://mikan.example/Home/Bangumi/2353",
                        candidate_context=canary,
                        season_evidence={
                            "status": "NEEDS_CONFIRMATION",
                            "season": 2,
                            "requires_review": True,
                        },
                    )
                ],
            ),
        ),
    )
    _goto_workbench(page, live_server_url)
    page.fill("#mikan-candidate-query", "芙莉莲")
    page.click("#mikan-candidate-search-submit")

    title = page.locator(".candidate-title")
    expect(title).to_have_attribute("title", long_title)
    expect(page.locator(".candidate-select")).to_have_attribute("aria-label", f"选择此合集：{long_title}")
    assert title.evaluate("el => el.getBoundingClientRect().height") <= 48
    expect(page.locator(".candidate-season-confirmation")).to_be_visible()
    surface = browser_surface(page)
    assert all(canary not in value for value in surface.values())
    assert not any(console_leaks)


def test_reduced_motion_loading_has_textual_state_without_spinner(
    page: Page, live_server_url: str
) -> None:
    page.emulate_media(reduced_motion="reduce")
    held: list[Any] = []

    def hold_generation(route: Any, request: Any) -> None:
        if request.method == "POST":
            held.append(route)
        else:
            route.continue_()

    page.route("**/api/v1/requests", hold_generation)
    _open_candidates(page, live_server_url, count=3)
    page.locator(".candidate-select").first.click()
    expect(page.locator(".candidate-select").first).to_have_attribute("aria-busy", "true")
    expect(page.locator(".candidate-generating-status")).to_contain_text("正在生成订阅草案")
    assert (
        page.locator(".candidate-select .base-button-spinner").evaluate(
            "el => getComputedStyle(el).display"
        )
        == "none"
    )


def test_held_generation_marks_only_clicked_candidate_and_enters_review(
    page: Page, live_server_url: str
) -> None:
    held: list[Any] = []

    def hold_generation(route: Any, request: Any) -> None:
        if request.method != "POST":
            route.continue_()
            return
        held.append(route)

    page.route("**/api/v1/requests", hold_generation)
    _open_candidates(page, live_server_url, count=3)

    cards = page.locator(".candidate-card")
    cards.nth(0).locator(".candidate-select").click()
    expect(cards.nth(0).locator(".candidate-select")).to_have_attribute("aria-busy", "true")
    expect(cards.nth(1).locator(".candidate-select")).to_be_disabled()
    expect(cards.nth(2).locator(".candidate-select")).to_be_disabled()
    expect(cards.nth(1).locator(".candidate-select")).not_to_have_attribute("aria-busy", "true")
    expect(cards.nth(2).locator(".candidate-select")).not_to_have_attribute("aria-busy", "true")
    assert page.locator(".candidate-valid-resource-count").count() == 0
    assert page.locator(".candidate-excluded-resource-count").count() == 0
    expect(page.locator(".candidate-generating-status")).to_have_count(1)

    assert len(held) == 1
    held[0].fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps(
            {
                "ok": True,
                "result": {
                    "draft_id": "draft-us364",
                    "draft_revision": 1,
                    "request": _preview_request("葬送的芙莉莲", "draft-us364"),
                },
            },
            ensure_ascii=False,
        ),
    )
    expect(page.locator("#single-anime-review-step")).to_be_visible()
    expect(page.locator(".candidate-card")).to_have_count(0)
