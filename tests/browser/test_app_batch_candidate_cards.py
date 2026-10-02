"""#144：批量工作台右栏横向合集候选卡复刻的真实 Chromium 门禁。

父规格 #139 已确认的目标：

- 1440×900 下右栏至少完整显示两张横向合集候选卡；更多候选在右栏内部滚动；
- 封面、季数证据、标题与「选择此合集」按钮占比协调，不再沿用 128px 方形小封面，
  也不是「一张纵向卡占满整栏却留下大片异常空白」的旧样式；
- 一项／多项候选、当前候选加载以及选择后的反馈都保持卡片几何稳定；内部滚动不推动
  整屏切换，底部操作区不遮末卡；
- 右栏不出现「高级信息」入口或替代浮层；季数证据、总集数与选择按钮可见可用；
- 右栏的「批量合集候选卡」与左栏「批量条目卡」在视觉与业务上明确不同。

本文件对旧实现（小封面 + 纵向排版的紧凑候选卡）是红测。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import set_storage_preferences
from tests.browser.screen_support import wait_for_screen_scroll, wait_for_scroll_idle, wheel_at
from tests.browser.test_app_batch_workbench import (
    _batch_item,
    _goto_batch,
    _preview_request,
    _route_parse,
)

pytestmark = pytest.mark.browser


def _right_candidate(bangumi_id: str, title: str, *, total_episodes: int | None = 12, season: int | None = 1) -> dict[str, Any]:
    """右栏合集候选（公开字段；封面走同源 opaque 海报路径）。"""
    candidate: dict[str, Any] = {
        "bangumi_id": bangumi_id,
        "title": title,
        "mikan_url": f"https://mikan.example/Home/Bangumi/{bangumi_id}",
        "poster_url": f"/api/v1/mikan/posters/{bangumi_id}",
        "source_query": title,
        "aliases": [],
        "recommendation": None,
        "total_episodes": total_episodes,
    }
    if season is not None:
        candidate["season_evidence"] = {"status": "PROVEN", "season": season, "requires_review": False}
    return candidate


def _candidate_items(count: int, *, candidates: int = 3, prefix: str = "番剧") -> list[dict[str, Any]]:
    return [
        _batch_item(
            f"item-{index:02d}",
            f"{prefix}{index:02d}",
            candidates=[
                _right_candidate(
                    bangumi_id=str(100 + index * 10 + offset),
                    title=f"{prefix}{index:02d} 合集{offset + 1}",
                    total_episodes=12 + offset,
                    season=offset + 1,
                )
                for offset in range(candidates)
            ],
        )
        for index in range(count)
    ]


def _open(page: Page, live_server_url: str, storage_dir, items: list[dict[str, Any]]) -> None:
    _route_parse(page, items)
    set_storage_preferences(page, storage_dir)
    _goto_batch(page, live_server_url)
    page.set_viewport_size({"width": 1440, "height": 900})
    page.fill("#batch-raw-input", "\n".join(str(item["raw_title"]) for item in items))
    page.click("#batch-parse-submit")
    expect(page.locator(".batch-draft-card")).to_have_count(len(items))
    wait_for_screen_scroll(page)


def _pane_geometry(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          const pane = document.querySelector('#batch-detail-pane')
          const paneBox = pane.getBoundingClientRect()
          const cards = Array.from(pane.querySelectorAll('.candidate-card')).map((card) => {
            const box = card.getBoundingClientRect()
            const cover = card.querySelector('.candidate-card-poster').getBoundingClientRect()
            const title = card.querySelector('.candidate-title').getBoundingClientRect()
            const button = card.querySelector('.candidate-select').getBoundingClientRect()
            const facts = card.querySelector('.candidate-card-facts').getBoundingClientRect()
            return {
              x: box.x, y: box.y, width: box.width, height: box.height,
              docY: box.y + window.scrollY,
              coverLeft: cover.left, coverTop: cover.top, coverWidth: cover.width, coverHeight: cover.height,
              titleLeft: title.left, titleRight: title.right, titleTop: title.top,
              factsLeft: facts.left, factsRight: facts.right,
              buttonLeft: button.left, buttonRight: button.right, buttonTop: button.top,
              fullyVisible: box.top >= paneBox.top - 0.5 && box.bottom <= paneBox.bottom + 0.5,
            }
          })
          return {
            paneTop: paneBox.top, paneBottom: paneBox.bottom,
            paneScrollTop: pane.scrollTop, paneScrollHeight: pane.scrollHeight, paneClientHeight: pane.clientHeight,
            cards,
          }
        }"""
    )


def test_right_column_shows_two_complete_horizontal_candidate_cards_at_1440x900(
    page: Page, live_server_url: str, storage_dir
) -> None:
    _open(page, live_server_url, storage_dir, _candidate_items(1, candidates=3))
    geometry = _pane_geometry(page)

    fully = [card for card in geometry["cards"] if card["fullyVisible"]]
    assert len(fully) >= 2, geometry
    # 横向卡：封面在左且明显是横向比例；信息在中；按钮在右。
    for card in fully[:2]:
        assert card["coverWidth"] > card["coverHeight"], card
        assert card["coverWidth"] >= 160, card
        assert card["coverLeft"] < card["titleLeft"], card
        assert card["buttonLeft"] > card["titleRight"], card
        assert card["buttonLeft"] > card["factsRight"], card
        # 卡片填充协调：封面与按钮占卡片宽度的合理比例，没有大片异常空白。
        assert 0.15 <= card["coverWidth"] / card["width"] <= 0.45, card
        # 按钮右缘落在卡片内边距之内，卡片右侧没有异常留白。
        assert card["x"] + card["width"] - card["buttonRight"] >= 8, card
        assert card["x"] + card["width"] - card["buttonRight"] <= card["width"] * 0.2, card


def test_right_column_scrolls_internally_without_switching_screens(
    page: Page, live_server_url: str, storage_dir
) -> None:
    _open(page, live_server_url, storage_dir, _candidate_items(1, candidates=6))

    before = page.evaluate("() => window.scrollY")
    state = page.evaluate(
        """() => {
          const pane = document.querySelector('#batch-detail-pane')
          pane.scrollTop = pane.scrollHeight
          return {
            scrollable: pane.scrollHeight > pane.clientHeight + 1,
            atBottom: pane.scrollTop + pane.clientHeight >= pane.scrollHeight - 1,
          }
        }"""
    )
    assert state["scrollable"] is True
    assert state["atBottom"] is True

    # 栏内滚到边界后继续滚动：真实滚轮不切屏，末卡完整可达且不被底部操作区遮挡。
    wheel_at(page, 1180, 400, 900)
    wait_for_scroll_idle(page)
    assert page.evaluate("() => window.scrollY") == before

    reachable = page.evaluate(
        """() => {
          const pane = document.querySelector('#batch-detail-pane')
          const cards = pane.querySelectorAll('.candidate-card')
          const last = cards[cards.length - 1]
          pane.scrollTop = pane.scrollHeight
          const paneBox = pane.getBoundingClientRect()
          const lastBox = last.getBoundingClientRect()
          const toolbar = document.querySelector('#batch-accept-toolbar').getBoundingClientRect()
          return {
            lastBottom: lastBox.bottom,
            paneBottom: paneBox.bottom,
            toolbarTop: toolbar.top,
          }
        }"""
    )
    assert reachable["lastBottom"] <= reachable["paneBottom"] + 0.5, reachable
    assert reachable["lastBottom"] <= reachable["toolbarTop"] + 0.5, reachable


def test_candidate_card_geometry_is_stable_while_the_current_candidate_loads(
    page: Page, live_server_url: str, storage_dir
) -> None:
    held: list[Any] = []

    def hold_generation(route: Any, request: Any) -> None:
        if request.method != "POST":
            route.continue_()
            return
        held.append(route)

    page.route("**/api/v1/requests", hold_generation)
    _open(page, live_server_url, storage_dir, _candidate_items(1, candidates=3))
    before = _pane_geometry(page)

    page.locator("#batch-detail-pane .candidate-select").first.click()
    expect(page.locator("#batch-detail-pane .candidate-generating-status")).to_be_visible()
    during = _pane_geometry(page)

    # 当前候选加载不改变任何候选卡的几何（封面、标题、按钮都不跳位）。
    assert len(during["cards"]) == len(before["cards"])
    for index, card in enumerate(during["cards"]):
        assert abs(card["height"] - before["cards"][index]["height"]) <= 1, (index, card, before["cards"][index])
        assert abs(card["coverWidth"] - before["cards"][index]["coverWidth"]) <= 1, index
        assert abs(card["buttonTop"] - before["cards"][index]["buttonTop"]) <= 1, index
        assert abs(card["docY"] - before["cards"][index]["docY"]) <= 1, index

    assert len(held) == 1
    held[0].fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps(
            {
                "ok": True,
                "result": {
                    "draft_id": "draft-144",
                    "draft_revision": 1,
                    "request": _preview_request("番剧00", "draft-144"),
                },
            },
            ensure_ascii=False,
        ),
    )
    # 选择真实合集后进入草案审核，右栏从候选切换为草案；选择语义没有被视觉改动破坏。
    expect(page.locator("#request-detail-container")).to_be_visible()


def test_right_column_has_no_advanced_information_entry_and_keeps_decision_evidence(
    page: Page, live_server_url: str, storage_dir
) -> None:
    _open(page, live_server_url, storage_dir, _candidate_items(1, candidates=3))
    pane = page.locator("#batch-detail-pane")

    assert page.locator("#batch-detail-pane details.candidate-advanced").count() == 0
    assert "高级信息" not in pane.inner_text()
    # 季数证据、总集数与选择按钮可见可用。
    expect(pane.locator(".candidate-season-evidence").first).to_be_visible()
    expect(pane.locator(".candidate-progress").first).to_contain_text("总集数")
    expect(pane.locator(".candidate-select").first).to_be_enabled()


def test_right_candidate_cards_differ_from_left_batch_item_cards(
    page: Page, live_server_url: str, storage_dir
) -> None:
    _open(page, live_server_url, storage_dir, _candidate_items(1, candidates=1))

    left_poster = page.evaluate(
        "() => document.querySelector('.batch-draft-card .batch-card-poster').getBoundingClientRect().width"
    )
    right_cover = page.evaluate(
        "() => { const r = document.querySelector('#batch-detail-pane .candidate-card-poster').getBoundingClientRect(); return {w: r.width, h: r.height} }"
    )
    # 左栏「批量条目卡」是设计图里的紧凑缩略封面（约 88×64），右栏「批量合集
    # 候选卡」是明显更大的横向封面；两者不是同一套尺寸规则。旧的 ≤64 上限只反映
    # 上一版紧凑占位，与 2026-09-25 设计目标冲突，改为设计比例区间。
    assert 76 <= left_poster <= 108, left_poster
    assert right_cover["w"] >= 160, right_cover
    assert right_cover["w"] > right_cover["h"], right_cover
    assert right_cover["w"] > left_poster + 40, (left_poster, right_cover)
    # 左栏条目卡不是合集卡：它的文本里没有真实合集的选择动作。
    left_card = page.locator(".batch-draft-card").first
    assert left_card.locator(".candidate-select").count() == 0
