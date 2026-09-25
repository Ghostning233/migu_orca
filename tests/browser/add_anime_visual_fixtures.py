"""#140～#144：添加番剧视觉验收的固定 fixture（测试期专用）。

父规格 #139 要求先以固定数据在真实 Chromium 里渲染，再由人工（本轮由具备读图能力的
Agent 代行并留痕）审核画面，批准后才入库为视觉回归基准。因此这里的每个场景：

- 使用固定 1440×900 画布、reduced-motion、隔离存储与 mock 外部依赖；
- 使用确定性文案与海报 fixture（海报按公开合集编号生成固定色块，不含任何真实资源）；
- 关闭搜索/批量完成后的全局提示，避免缓存型 toast 造成非确定性；
- 等字体与图片加载完成后截图，不做任意 sleep。

场景只描述「如何到达该状态」，不包含断言；截图、基准与硬门禁在
``tests/browser/test_app_add_anime_visual.py``。
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageDraw
from playwright.sync_api import Page, expect

from tests.browser.conftest import preview_result_json
from tests.browser.test_app_batch_workbench import (
    _batch_item,
    _goto_batch,
    _route_parse,
)
from tests.browser.test_app_batch_workbench import (
    _preview_request as _batch_preview_request,
)
from tests.browser.test_app_workbench import (
    _candidate_result_json,
    _goto_workbench,
)
from tests.browser.visual_support import (
    install_shell_status_routes,
    prepare_canvas,
)

CANVAS = (1440, 900)

SINGLE_QUERY = "星海旅途"

_CANDIDATE_TITLES: tuple[tuple[str, str, int, int], ...] = (
    ("2353", "星海旅途", 1, 12),
    ("3072", "星海旅途 第二季", 2, 13),
    ("3510", "星海旅途 外传", 0, 6),
    ("4096", "星海旅途 特别篇", 0, 4),
)

_BATCH_TITLES: tuple[str, ...] = (
    "星海旅途",
    "雨后书店",
    "春日列车",
    "夜航灯塔",
    "山间来信",
    "旧城信标",
    "云端牧场",
    "深海回声",
    "长夜书店",
    "纸上银河",
    "无人车站",
    "夏日回声",
)

_POSTER_COLOURS: tuple[tuple[int, int, int], ...] = (
    (36, 58, 102),
    (28, 84, 118),
    (54, 74, 128),
    (92, 62, 110),
    (40, 96, 96),
    (110, 74, 58),
)


def poster_png(bangumi_id: str) -> bytes:
    """确定性海报 fixture：按公开合集编号生成固定色块，不含真实图片或外部资源。"""
    index = sum(ord(character) for character in bangumi_id) % len(_POSTER_COLOURS)
    base = _POSTER_COLOURS[index]
    accent = _POSTER_COLOURS[(index + 3) % len(_POSTER_COLOURS)]
    image = Image.new("RGB", (640, 360), base)
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 200, 640, 360], fill=accent)
    draw.ellipse([420, 40, 560, 180], fill=(238, 240, 246))
    draw.polygon([(0, 250), (180, 160), (330, 250)], fill=(20, 28, 44))
    draw.polygon([(240, 260), (420, 150), (640, 260)], fill=(14, 20, 32))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def install_poster_route(page: Page) -> None:
    """同源 opaque 海报路径返回固定图片，避免真实网络与随机资源。"""
    page.route(
        "**/api/v1/mikan/posters/**",
        lambda route: route.fulfill(status=200, content_type="image/png", body=poster_png(route.request.url.rsplit("/", 1)[-1])),
    )


def _single_candidate(bangumi_id: str, title: str, season: int, total: int) -> dict[str, Any]:
    candidate: dict[str, Any] = {
        "bangumi_id": bangumi_id,
        "title": title,
        "mikan_url": f"https://mikan.example/Home/Bangumi/{bangumi_id}",
        "poster_url": f"/api/v1/mikan/posters/{bangumi_id}",
        "source_query": SINGLE_QUERY,
        "aliases": [],
        "recommendation": None,
        "total_episodes": total,
    }
    if season:
        candidate["season_evidence"] = {"status": "PROVEN", "season": season, "requires_review": False}
    else:
        candidate["season_evidence"] = {"status": "NEEDS_CONFIRMATION", "season": None, "requires_review": True}
    return candidate


def _batch_candidate(bangumi_id: str, title: str, season: int, total: int) -> dict[str, Any]:
    candidate = _single_candidate(bangumi_id, title, season, total)
    candidate["source_query"] = title
    return candidate


def close_notifications(page: Page) -> None:
    """关闭搜索/批量完成提示：toast 有自动关闭计时，不能作为截图的一部分。"""
    close = page.locator(".global-notification-close")
    if close.count():
        close.first.click()
        page.wait_for_selector(".global-notification", state="detached", timeout=5000)


def _open_single(page: Page, live_server_url: str) -> None:
    install_shell_status_routes(page)
    install_poster_route(page)
    prepare_canvas(page)
    _goto_workbench(page, live_server_url)


def _search_single(page: Page, count: int) -> None:
    candidates = [
        _single_candidate(bangumi_id, title, season, total)
        for bangumi_id, title, season, total in _CANDIDATE_TITLES[:count]
    ]
    page.route(
        "**/api/v1/mikan/candidates",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=_candidate_result_json(SINGLE_QUERY, candidates),
        ),
    )
    page.fill("#mikan-candidate-query", SINGLE_QUERY)
    page.click("#mikan-candidate-search-submit")
    expect(page.locator(".candidate-card")).to_have_count(count)
    close_notifications(page)


def search_first_screen(page: Page, live_server_url: str) -> None:
    """场景：单番搜索首屏（已认可的输入与加载入口）。"""
    _open_single(page, live_server_url)


def single_candidates_four(page: Page, live_server_url: str) -> None:
    """场景：单番搜索成功后的四张候选卡工作台。"""
    _open_single(page, live_server_url)
    _search_single(page, 4)


def single_draft_review(page: Page, live_server_url: str) -> None:
    """场景：单番未保存草案审核（长内容沿同一页面滚动轴）。"""
    _open_single(page, live_server_url)
    page.route(
        "**/api/v1/requests",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=preview_result_json(_batch_preview_request(SINGLE_QUERY, "req-visual-add")),
            # 单番草案用同一份固定 preview envelope（服务端 draft_store 签发 draft_id）。
        ),
    )
    _search_single(page, 4)
    page.locator(".candidate-card .candidate-select").first.click()
    expect(page.locator("#single-anime-review-step")).to_be_visible()
    close_notifications(page)


def _batch_items(*, count: int = 12, candidates: int = 3) -> list[dict[str, Any]]:
    """固定批量 fixture；``count`` 覆盖 1／12／36 部三档结构检查。"""
    items: list[dict[str, Any]] = []
    for index in range(count):
        title = _BATCH_TITLES[index % len(_BATCH_TITLES)]
        if count > len(_BATCH_TITLES):
            title = f"{title} {index + 1:02d}"
        items.append(
            _batch_item(
                f"item-{index:02d}",
                title,
                candidates=[
                    _batch_candidate(
                        bangumi_id=str(1000 + index * 10 + offset),
                        title=f"{title} 第{offset + 1}季",
                        season=offset + 1,
                        total=12 + offset,
                    )
                    for offset in range(candidates)
                ],
            )
        )
    return items


def _open_batch(page: Page, live_server_url: str, items: list[dict[str, Any]]) -> None:
    install_shell_status_routes(page)
    install_poster_route(page)
    _route_parse(page, items)
    prepare_canvas(page)
    _goto_batch(page, live_server_url)
    page.fill("#batch-raw-input", "\n".join(str(item["raw_title"]) for item in items))
    page.click("#batch-parse-submit")
    expect(page.locator(".batch-draft-card")).to_have_count(len(items))
    close_notifications(page)


def batch_candidates(page: Page, live_server_url: str) -> None:
    """场景：批量候选工作台（12 部，右栏横向合集候选卡）。"""
    _open_batch(page, live_server_url, _batch_items())


def batch_items_one(page: Page, live_server_url: str) -> None:
    """场景：批量工作台结构下限（1 部）。"""
    _open_batch(page, live_server_url, _batch_items(count=1))


def batch_items_thirty_six(page: Page, live_server_url: str) -> None:
    """场景：批量工作台结构上限（36 部）。"""
    _open_batch(page, live_server_url, _batch_items(count=36))


def batch_candidate_loading(page: Page, live_server_url: str) -> None:
    """场景：批量右栏当前候选加载（卡片几何不变）。"""
    held: list[Any] = []

    def hold_generation(route: Any, request: Any) -> None:
        if request.method != "POST":
            route.continue_()
            return
        held.append(route)

    page.route("**/api/v1/requests", hold_generation)
    _open_batch(page, live_server_url, _batch_items())
    page.locator("#batch-detail-pane .candidate-select").first.click()
    expect(page.locator("#batch-detail-pane .candidate-generating-status").first).to_be_visible()
    close_notifications(page)


@dataclass(frozen=True)
class VisualScenario:
    """一个可审核的页面状态。"""

    name: str
    description: str
    setup: Callable[[Page, str], None]
    anchors: tuple[str, ...]
    masks: tuple[tuple[str, int, int, int, int, str], ...] = ()
    """具名动态掩码 ``(name, x, y, width, height, purpose)``；总面积必须 ≤5%。"""


SCENARIOS: tuple[VisualScenario, ...] = (
    VisualScenario(
        "single-search",
        "单番搜索首屏",
        search_first_screen,
        (
            ".app-header",
            ".single-home-hero",
            "#mikan-candidate-search-form",
            "#mikan-candidate-query",
            "#mikan-candidate-search-submit",
        ),
    ),
    VisualScenario(
        "single-candidates-four",
        "单番四张候选卡工作台",
        single_candidates_four,
        (
            "#candidate-search-heading",
            "#mikan-back-to-search",
            ".candidate-card:nth-child(1)",
            ".candidate-card:nth-child(2)",
            ".candidate-card:nth-child(3)",
            ".candidate-card:nth-child(4)",
            ".candidate-card:nth-child(1) .candidate-select",
            ".candidate-card:nth-child(4) .candidate-select",
        ),
    ),
    VisualScenario(
        "single-draft-review",
        "单番未保存草案审核",
        single_draft_review,
        (
            "#single-anime-review-step",
            "#single-review-save-button",
            "#single-review-back-candidates",
        ),
    ),
    VisualScenario(
        "batch-candidates",
        "批量候选工作台（12 部）",
        batch_candidates,
        (
            ".batch-workbench-screen",
            ".batch-card-grid-wrapper",
            "#batch-detail-pane",
            "#batch-accept-toolbar",
            "#batch-detail-pane .candidate-card:nth-child(1)",
            "#batch-detail-pane .candidate-card:nth-child(2)",
            "#batch-detail-pane .candidate-card:nth-child(1) .candidate-select",
        ),
    ),
    VisualScenario(
        "batch-items-one",
        "批量工作台结构（1 部）",
        batch_items_one,
        (
            ".batch-workbench-screen",
            ".batch-card-grid-wrapper",
            "#batch-detail-pane",
            "#batch-accept-toolbar",
            ".batch-draft-card:nth-child(1)",
        ),
    ),
    VisualScenario(
        "batch-items-thirty-six",
        "批量工作台结构（36 部）",
        batch_items_thirty_six,
        (
            ".batch-workbench-screen",
            ".batch-card-grid-wrapper",
            "#batch-detail-pane",
            "#batch-accept-toolbar",
            ".batch-draft-card:nth-child(1)",
        ),
    ),
    VisualScenario(
        "batch-candidate-loading",
        "批量右栏当前候选加载",
        batch_candidate_loading,
        (
            ".batch-workbench-screen",
            "#batch-detail-pane",
            "#batch-detail-pane .candidate-card:nth-child(1)",
            "#batch-detail-pane .candidate-generating-status",
        ),
    ),
)

SCENARIO_BY_NAME = {scenario.name: scenario for scenario in SCENARIOS}


def anchor_values(page: Page, selectors: tuple[str, ...]) -> dict[str, dict[str, float] | None]:
    """采集锚点几何；缺失元素返回 None，由门禁用例判定失败。"""
    return page.evaluate(
        """(selectors) => {
          const result = {};
          for (const selector of selectors) {
            const element = document.querySelector(selector);
            if (!element) { result[selector] = null; continue; }
            const rect = element.getBoundingClientRect();
            result[selector] = {
              x: Math.round(rect.x * 100) / 100,
              y: Math.round(rect.y * 100) / 100,
              width: Math.round(rect.width * 100) / 100,
              height: Math.round(rect.height * 100) / 100,
            };
          }
          return result;
        }""",
        list(selectors),
    )


def anchors_json(payload: dict[str, dict[str, dict[str, float] | None]]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
