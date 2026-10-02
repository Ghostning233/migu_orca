"""#155：真实 Chromium 截图必须随附「同一最新构建」的证据清单。

本文件只证明取证链路本身：截图由真实 ``/app/add`` 与共享组件生成，页面实际加载的
``/app/assets/*`` 字节与 dist 构建产物逐一致，清单含 Git/指纹/产物/Chromium/viewport/
fixture/场景/操作步骤/截图摘要，且不含绝对路径、URL 或秘密。它不批准任何金样，也不
用截图代替点击行为验证。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from playwright.sync_api import Page

from tests.browser.evidence import (
    FixtureDescriptor,
    LoadedResourceRecorder,
    ScenarioDescriptor,
    assert_manifest_safe,
    capture_evidence,
    file_digest,
    is_asset_path,
    require_fresh_build,
    verify_build,
    write_manifest,
)
from tests.browser.visual_support import (
    capture_canvas,
    install_shell_status_routes,
    prepare_canvas,
    require_dist,
)

pytestmark = pytest.mark.browser

FIXTURE = FixtureDescriptor(
    fixture_id="add-anime-idle-safe",
    description="固定安全 fixture：未配置 AB 连接、空追番列表、无海报请求；不连接任何真实外部服务。",
    mock_routes=("/api/v1/settings/autobangumi", "/api/v1/tracking/items"),
)

SCENARIO = ScenarioDescriptor(
    scenario_id="add-anime-idle-1440x900",
    title="添加番剧单番搜索首屏（空闲态）",
    steps=(
        "以 1440×900、reduced-motion 打开 /app/add",
        "等待 #workbench-heading 可见",
        "等待字体/视口内图片与双帧稳定后截取视口",
    ),
)


def _open_add(page: Page, live_server_url: str) -> None:
    install_shell_status_routes(page)
    prepare_canvas(page)
    page.goto(f"{live_server_url}/app/add")
    page.wait_for_selector("#workbench-heading")


def test_screenshot_evidence_matches_the_built_artifact(
    page: Page, live_server_url: str, tmp_path: Path
) -> None:
    require_dist()
    recorder = LoadedResourceRecorder(live_server_url)
    recorder.attach(page)
    _open_add(page, live_server_url)
    capture = tmp_path / "add-anime-idle.png"
    capture_canvas(page, capture)

    manifest = capture_evidence(
        page,
        capture,
        base_url=live_server_url,
        scenario=SCENARIO,
        fixture=FIXTURE,
        resources=recorder.records(),
    )
    manifest_path = write_manifest(manifest, tmp_path, SCENARIO.scenario_id)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert payload["screenshot"]["sha256"] == file_digest(capture)
    assert payload["screenshot"]["file_name"] == "add-anime-idle.png"
    assert payload["scenario"] == {
        "id": SCENARIO.scenario_id,
        "title": SCENARIO.title,
        "steps": list(SCENARIO.steps),
    }
    assert payload["fixture"]["id"] == FIXTURE.fixture_id
    assert payload["runtime"]["chromium_version"]
    assert payload["runtime"]["viewport"] == {"width": 1440, "height": 900}
    assert payload["git"]["head"] == verify_build()["git"]["head"]
    assert payload["build"]["artifact_digest"] == verify_build()["artifact"]["digest"]
    assert payload["build"]["source_fingerprint"]["file_count"] > 0
    # 页面必须真的加载了本次构建的入口资源，否则截图不能算这次构建的证据。
    loaded = [resource for resource in payload["page"]["loaded_resources"] if is_asset_path(resource["path"])]
    assert loaded, "没有记录到任何 /app/assets/* 加载"
    assert all(resource["sha256"] for resource in loaded)
    assert_manifest_safe(payload)
    # 清单本身不得泄漏本地绝对路径。
    assert str(tmp_path) not in manifest_path.read_text(encoding="utf-8")


def test_stale_build_stamp_is_rejected_for_capture(tmp_path: Path) -> None:
    """源码在构建后变化 → 该 dist 不能作为最新证据（最小故障证明）。"""
    stamp = verify_build()
    assert stamp["source_fingerprint"]["digest"]

    from tests.browser import evidence

    original = evidence.source_fingerprint

    def _drift(frontend_dir: Path = evidence.FRONTEND_DIR) -> dict[str, object]:
        fingerprint = dict(original(frontend_dir))
        fingerprint["digest"] = "0" * 64
        return fingerprint

    evidence.source_fingerprint = _drift  # type: ignore[assignment]
    try:
        with pytest.raises(evidence.EvidenceError, match="构建戳已过期"):
            evidence.verify_build()
    finally:
        evidence.source_fingerprint = original  # type: ignore[assignment]
    # 恢复后仍然通过，证明上面的失败来自源码漂移而不是工具本身坏了。
    assert require_fresh_build()["artifact"]["digest"] == stamp["artifact"]["digest"]
