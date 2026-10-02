"""#159：单番／批量首屏共用居中任务区与切换连续性（真实 Chromium）。

主画布 1440×900。本文件验证：

- 两个首屏共用标题层级、水平中心轴、模式切换锚点与相邻间距（输入形态允许自然差异）；
- 切换模式不丢输入、不把页面跳进工作台或页面中间、无横向溢出；
- 逐部进度与空结果出现时任务区仍可读可达；
- reduced-motion 下几何与默认动效一致。

几何口径：标题/说明/模式切换/表单元件在两个模式下都居中于内容轴（1440 下 x=720），
且标题→说明 8px、说明→模式切换 24px、模式切换→表单 32px 的 Token 间距一致；
批量多行文本框按任务保留自然高度，不要求与单番单行输入等高。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.evidence import (
    FixtureDescriptor,
    LoadedResourceRecorder,
    ScenarioDescriptor,
    capture_evidence,
    file_digest,
    write_manifest,
)
from tests.browser.visual_support import (
    capture_canvas,
    install_shell_status_routes,
    prepare_canvas,
    require_dist,
)

pytestmark = pytest.mark.browser

TOLERANCE = 2.0
CANVAS = (1440, 900)

_MEASURE = """
() => {
  const read = (selector) => {
    const element = document.querySelector(selector)
    if (!element) return null
    const rect = element.getBoundingClientRect()
    return {
      x: rect.x, y: rect.y, width: rect.width, height: rect.height,
      centerX: rect.x + rect.width / 2, bottom: rect.y + rect.height,
    }
  }
  return {
    title: read('#workbench-heading'),
    subtitle: read('.single-home-subtitle, .batch-search-subtitle'),
    mode: read('#anime-mode-switch'),
    form: read('#mikan-candidate-search-form, #batch-parse-form'),
    input: read('#mikan-candidate-query, #batch-raw-input'),
    submit: read('#mikan-candidate-search-submit, #batch-parse-submit'),
    steps: read('.journey-steps'),
    isSearching: Boolean(document.querySelector('.batch-search-screen.is-searching')),
    scrollY: window.scrollY,
    viewportWidth: window.innerWidth,
    bodyScrollWidth: document.body.scrollWidth,
  }
}
"""


def _open_single(page: Page, live_server_url: str) -> None:
    require_dist()
    install_shell_status_routes(page)
    prepare_canvas(page)
    page.goto(f"{live_server_url}/app/add")
    page.wait_for_selector(".single-home-hero", timeout=10_000)


def _switch_to_batch(page: Page) -> dict[str, Any]:
    page.locator("#anime-mode-batch").click()
    page.wait_for_selector("#batch-parse-form", timeout=10_000)
    return page.evaluate(_MEASURE)


def _centered_problems(label: str, metrics: dict[str, Any], center_x: float) -> list[str]:
    problems: list[str] = []
    for name in ("title", "subtitle", "mode", "form", "steps"):
        box = metrics.get(name)
        if box is None:
            problems.append(f"{label}.{name}: missing")
            continue
        if abs(box["centerX"] - center_x) > TOLERANCE:
            problems.append(f"{label}.{name}: centerX {box['centerX']} != {center_x}")
    return problems


def _gap(metrics: dict[str, Any], first: str, second: str) -> float | None:
    top, bottom = metrics.get(first), metrics.get(second)
    if top is None or bottom is None:
        return None
    return bottom["y"] - top["bottom"]


def _assert_shared_task_geometry(single: dict[str, Any], batch: dict[str, Any], center_x: float) -> None:
    problems = _centered_problems("single", single, center_x) + _centered_problems("batch", batch, center_x)
    # 相同标题层级：标题 48、说明 24、模式切换 62（两个模式一致）。
    for name, expected in (("title", 48.0), ("subtitle", 24.0), ("mode", 62.0)):
        for label, metrics in (("single", single), ("batch", batch)):
            box = metrics.get(name)
            if box is None or abs(box["height"] - expected) > TOLERANCE:
                problems.append(f"{label}.{name}: height {box and box['height']} != {expected}")
    # 相同 Token 间距：标题→说明 8、说明→模式切换 24、模式切换→表单 32。
    for first, second, expected in (("title", "subtitle", 8.0), ("subtitle", "mode", 24.0), ("mode", "form", 32.0)):
        for label, metrics in (("single", single), ("batch", batch)):
            actual = _gap(metrics, first, second)
            if actual is None or abs(actual - expected) > TOLERANCE:
                problems.append(f"{label}: {first}->{second} gap {actual} != {expected}")
    # #159：公共标题、说明与模式切换在切换模式后停在同一个位置（≤2 CSS px），
    # 批量多出来的内容自然向下延伸，不把任务区整体上移。
    for name in ("title", "subtitle", "mode"):
        before, after = single.get(name), batch.get(name)
        if before is None or after is None:
            problems.append(f"{name}: missing for vertical parity")
            continue
        if abs(before["y"] - after["y"]) > TOLERANCE:
            problems.append(f"{name}: y {after['y']} != {before['y']}")
    assert not problems, json.dumps(problems, ensure_ascii=False, indent=2)


def _assert_batch_submit_centred(metrics: dict[str, Any], center_x: float) -> None:
    """批量首屏的主搜索操作与输入区、说明共用一条中心轴（不再贴表单左缘）。"""
    submit = metrics.get("submit")
    assert submit is not None, "batch submit missing"
    assert abs(submit["centerX"] - center_x) <= TOLERANCE, submit


def _assert_input_shapes(single: dict[str, Any], batch: dict[str, Any]) -> None:
    """输入形态允许自然高度差异，但批量文本框必须保留多行高度。"""
    single_input = single.get("input")
    batch_input = batch.get("input")
    problems: list[str] = []
    if not single_input or not batch_input:
        problems.append("input box missing")
    else:
        if abs(single_input["height"] - 52.0) > TOLERANCE:
            problems.append(f"single input height {single_input['height']} != 52")
        if batch_input["height"] < 72.0:
            problems.append(f"batch textarea height {batch_input['height']} < 72")
    assert not problems, json.dumps(problems, ensure_ascii=False, indent=2)


def test_single_and_batch_first_screens_share_the_centred_task_axis(
    page: Page, live_server_url: str
) -> None:
    _open_single(page, live_server_url)
    single = page.evaluate(_MEASURE)
    assert page.evaluate("() => window.scrollY") == 0

    batch = _switch_to_batch(page)
    _assert_shared_task_geometry(single, batch, CANVAS[0] / 2)
    _assert_input_shapes(single, batch)
    _assert_batch_submit_centred(batch, CANVAS[0] / 2)
    # 空闲态不套用搜索态；切换模式不把页面跳走。
    assert batch["isSearching"] is False
    assert batch["scrollY"] == 0
    assert batch["bodyScrollWidth"] <= batch["viewportWidth"] + 1

    # 切回单番：单番输入现场仍在，几何回到同一中心轴；再切回批量保留批量输入。
    page.fill("#batch-raw-input", "甲\n乙")
    page.locator("#anime-mode-single").click()
    page.wait_for_selector("#mikan-candidate-search-form", timeout=10_000)
    expect(page.locator(".single-home-hero")).to_be_visible()
    back = page.evaluate(_MEASURE)
    _assert_shared_task_geometry(single, back, CANVAS[0] / 2)
    batch_again = _switch_to_batch(page)
    assert page.input_value("#batch-raw-input") == "甲\n乙"
    _assert_shared_task_geometry(single, batch_again, CANVAS[0] / 2)
    _assert_input_shapes(single, batch_again)
    _assert_batch_submit_centred(batch_again, CANVAS[0] / 2)


@pytest.mark.parametrize(("width", "height"), [(1280, 800), (1920, 1080)])
def test_batch_first_screen_centres_without_horizontal_overflow(
    page: Page, live_server_url: str, width: int, height: int
) -> None:
    require_dist()
    install_shell_status_routes(page)
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{live_server_url}/app/add")
    page.wait_for_selector(".single-home-hero", timeout=10_000)
    single = page.evaluate(_MEASURE)
    batch = _switch_to_batch(page)
    assert _centered_problems("batch", batch, width / 2) == []
    _assert_shared_task_geometry(single, batch, width / 2)
    _assert_input_shapes(single, batch)
    _assert_batch_submit_centred(batch, width / 2)
    assert batch["bodyScrollWidth"] <= batch["viewportWidth"] + 1
    expect(page.locator("#batch-parse-submit")).to_be_visible()


def test_batch_first_screen_holds_under_two_hundred_percent_zoom(
    page: Page, live_server_url: str
) -> None:
    """720 CSS 视口等效 1440 桌面 200% 缩放：任务区仍居中且可达。"""
    require_dist()
    install_shell_status_routes(page)
    page.set_viewport_size({"width": 720, "height": 450})
    page.goto(f"{live_server_url}/app/add")
    page.wait_for_selector(".single-home-hero", timeout=10_000)
    batch = _switch_to_batch(page)
    assert batch["bodyScrollWidth"] <= batch["viewportWidth"] + 1
    assert batch["title"] is not None and batch["title"]["x"] >= 0
    _assert_batch_submit_centred(batch, 720 / 2)
    expect(page.locator("#batch-parse-submit")).to_be_visible()
    expect(page.locator("#batch-raw-input")).to_be_visible()


def test_batch_progress_and_empty_result_keep_the_first_screen_reachable(
    page: Page, live_server_url: str
) -> None:
    held: list[Any] = []
    page.route(
        "**/api/v1/batches/parse",
        lambda route, request: held.append(route) if request.method == "POST" else route.continue_(),
    )
    _open_single(page, live_server_url)
    _switch_to_batch(page)
    page.fill("#batch-raw-input", "甲\n乙")
    page.click("#batch-parse-submit")

    expect(page.locator("#batch-search-progress")).to_be_visible()
    searching = page.evaluate(_MEASURE)
    # 搜索态回到文档流顶部，任务区仍完全可达，且没有把用户留在「页面中间」。
    assert searching["isSearching"] is True
    assert searching["title"]["y"] >= 0
    assert searching["bodyScrollWidth"] <= searching["viewportWidth"] + 1
    expect(page.locator("#batch-parse-submit")).to_be_visible()

    assert held, "batch parse was not held"
    held[0].fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps({"ok": True, "result": {"batch_id": "batch-empty-continuity", "raw_input": "甲\n乙", "items": []}}, ensure_ascii=False),
    )
    expect(page.locator("#batch-empty-result")).to_be_visible()
    # 空结果留在首屏：工作台屏保持隐藏（挂载但不可见），任务区仍可读可达。
    workbench = page.locator(".batch-workbench-screen")
    assert workbench.count() in (0, 1)
    if workbench.count():
        expect(workbench.first).not_to_be_visible()
    empty = page.evaluate(_MEASURE)
    assert empty["title"]["y"] >= 0
    assert empty["bodyScrollWidth"] <= empty["viewportWidth"] + 1
    expect(page.locator("#batch-parse-submit")).to_be_visible()

    # 关闭全局通知后不把首屏拉回「页面中间」，也不改变任务区位置。
    close = page.locator(".global-notification-close")
    if close.count():
        close.first.click()
        page.wait_for_selector(".global-notification", state="detached", timeout=5_000)
    after_close = page.evaluate(_MEASURE)
    assert abs(after_close["title"]["y"] - empty["title"]["y"]) <= TOLERANCE


def test_mode_switch_geometry_is_identical_under_reduced_motion(
    page: Page, live_server_url: str
) -> None:
    _open_single(page, live_server_url)
    single_default = page.evaluate(_MEASURE)
    batch_default = _switch_to_batch(page)
    _assert_batch_submit_centred(batch_default, CANVAS[0] / 2)

    page.emulate_media(reduced_motion="reduce")
    page.locator("#anime-mode-single").click()
    page.wait_for_selector("#mikan-candidate-search-form", timeout=10_000)
    single_reduced = page.evaluate(_MEASURE)
    batch_reduced = _switch_to_batch(page)
    _assert_batch_submit_centred(batch_reduced, CANVAS[0] / 2)

    for name in ("title", "subtitle", "mode", "form", "steps"):
        for key in ("centerX", "y", "height"):
            default_value = batch_default[name][key]
            reduced_value = batch_reduced[name][key]
            assert abs(default_value - reduced_value) <= TOLERANCE, (name, key, default_value, reduced_value)
    assert abs(single_default["title"]["centerX"] - single_reduced["title"]["centerX"]) <= TOLERANCE

FIXTURE = FixtureDescriptor(
    fixture_id="add-anime-first-screen-safe",
    description="固定安全 fixture：未配置 AB 连接、空追番列表、离线批量解析 mock；不访问真实外部服务。",
    mock_routes=("/api/v1/settings/autobangumi", "/api/v1/tracking/items", "/api/v1/batches/parse"),
)


def _capture(
    page: Page,
    recorder: LoadedResourceRecorder,
    tmp_path: Path,
    live_server_url: str,
    scenario_id: str,
    title: str,
    steps: tuple[str, ...],
    route: str,
) -> dict[str, Any]:
    screenshot = tmp_path / f"{scenario_id}.png"
    capture_canvas(page, screenshot)
    manifest = capture_evidence(
        page,
        screenshot,
        base_url=live_server_url,
        scenario=ScenarioDescriptor(scenario_id, title, steps),
        fixture=FIXTURE,
        resources=recorder.records(),
        route=route,
    )
    write_manifest(manifest, tmp_path, scenario_id)
    return json.loads((tmp_path / f"{scenario_id}.evidence.json").read_text(encoding="utf-8"))


def test_single_batch_and_progress_captures_ship_with_evidence_manifests(
    page: Page, live_server_url: str, tmp_path: Path
) -> None:
    """#159／#155：单番空闲 → 批量空闲 → 逐部进度 → 空结果，四张图各随附证据清单。"""
    held: list[Any] = []
    page.route(
        "**/api/v1/batches/parse",
        lambda route, request: held.append(route) if request.method == "POST" else route.continue_(),
    )
    require_dist()
    recorder = LoadedResourceRecorder(live_server_url)
    recorder.attach(page)
    install_shell_status_routes(page)
    prepare_canvas(page)
    page.goto(f"{live_server_url}/app/add")
    page.wait_for_selector(".single-home-hero", timeout=10_000)

    payloads: dict[str, dict[str, Any]] = {}
    payloads["single"] = _capture(
        page, recorder, tmp_path, live_server_url, "single-first-screen-idle-1440x900",
        "单番搜索首屏空闲态", ("1440×900 打开 /app/add", "等待英雄区与模式切换渲染"), "/app/add",
    )

    page.locator("#anime-mode-batch").click()
    page.wait_for_selector("#batch-parse-form", timeout=10_000)
    payloads["batch"] = _capture(
        page, recorder, tmp_path, live_server_url, "batch-first-screen-idle-1440x900",
        "批量搜索首屏空闲态", ("切到批量模式", "等待任务区与旅程步骤渲染"), "/app/add",
    )

    page.fill("#batch-raw-input", "甲\n乙")
    page.click("#batch-parse-submit")
    expect(page.locator("#batch-search-progress")).to_be_visible()
    payloads["progress"] = _capture(
        page, recorder, tmp_path, live_server_url, "batch-first-screen-progress-1440x900",
        "批量逐部搜索进度", ("提交批量搜索", "服务端请求保持未完成，截图进度与任务区"), "/app/add",
    )

    assert held, "batch parse was not held"
    held[0].fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps({"ok": True, "result": {"batch_id": "batch-evidence", "raw_input": "甲\n乙", "items": []}}, ensure_ascii=False),
    )
    expect(page.locator("#batch-empty-result")).to_be_visible()
    payloads["empty"] = _capture(
        page, recorder, tmp_path, live_server_url, "batch-first-screen-empty-1440x900",
        "批量零条目留在首屏", ("服务端返回空条目", "确认仍在搜索首屏并截图"), "/app/add",
    )

    digests = set()
    for name, payload in payloads.items():
        assert payload["screenshot"]["sha256"], name
        assert payload["runtime"]["viewport"] == {"width": 1440, "height": 900}, name
        assert payload["page"]["route"] == "/app/add", name
        assert any(resource["path"].startswith("/app/assets/") for resource in payload["page"]["loaded_resources"]), name
        digests.add(payload["screenshot"]["sha256"])
    assert len(digests) == len(payloads), sorted(digests)
    assert file_digest(tmp_path / "single-first-screen-idle-1440x900.png") == payloads["single"]["screenshot"]["sha256"]

