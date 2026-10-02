"""#155：人工交互预览必须用固定安全 fixture，并且真的隔离运行数据与外部服务。

本文件证明 ``tests/browser/preview_fixtures.py`` 的预览入口：

- storage/config 指向本次预览的临时目录（不读写真实运行数据与部署配置）；
- ``/api/v1`` 只应答固定 fixture（AB 未配置、追番为空、固定批量草案、候选与海报），
  其余接口在本地 fail closed，不转发给真实 handler；
- 真实 Chromium 能用同一份已校验 dist + 同一固定 fixture 重现截图里的批量草案现场，
  并把截图与清单一起写进 ``tmp_path``。
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest
import requests
from playwright.sync_api import Page, expect
from werkzeug.serving import make_server

from apps.migu_orca_web import services
from tests.browser.conftest import _find_free_port
from tests.browser.evidence import (
    FixtureDescriptor,
    LoadedResourceRecorder,
    ScenarioDescriptor,
    capture_evidence,
    write_manifest,
)
from tests.browser.preview_fixtures import PREVIEW_BATCH_ID, create_preview_app
from tests.browser.visual_support import capture_canvas, prepare_canvas, require_dist

pytestmark = pytest.mark.browser


@pytest.fixture
def preview_server() -> object:
    """启动隔离预览服务；结束后恢复调用方的 config root。"""
    previous_config = os.environ.get("MIGU_ORCA_WEB_CONFIG_ROOT")
    app, temp_root = create_preview_app()
    port = _find_free_port()
    server = make_server("127.0.0.1", port, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", temp_root
    finally:
        server.shutdown()
        thread.join(timeout=5)
        if previous_config is None:
            os.environ.pop("MIGU_ORCA_WEB_CONFIG_ROOT", None)
        else:
            os.environ["MIGU_ORCA_WEB_CONFIG_ROOT"] = previous_config


def test_preview_isolates_runtime_data_and_fails_closed(preview_server) -> None:
    url, temp_root = preview_server

    # 隔离：本次预览的 Web storage root 就是新临时目录，不是真实运行数据目录。
    preview_storage_root = services._WEB_STORAGE_ROOT  # noqa: SLF001 - 断言隔离边界
    assert preview_storage_root is not None
    assert str(preview_storage_root) == str(temp_root / "storage")
    assert temp_root.is_dir() and (temp_root / "config").is_dir()
    assert "migu-orca-preview-" in temp_root.name

    connection = requests.get(f"{url}/api/v1/settings/autobangumi", timeout=10).json()
    assert connection["result"]["configured"] is False
    assert connection["result"]["connection_status"] == "UNCONFIGURED"

    tracking = requests.get(f"{url}/api/v1/tracking/items", timeout=10).json()
    assert tracking["result"]["items"] == []

    batch = requests.post(f"{url}/api/v1/batches/parse", json={"raw_input": "任意"}, timeout=10).json()
    assert batch["result"]["batch_id"]
    assert len(batch["result"]["items"]) == 5, batch["result"]["items"]

    poster = requests.get(f"{url}/api/v1/mikan/posters/2353", timeout=10)
    assert poster.status_code == 200
    assert poster.content[:8] == b"\x89PNG\r\n\x1a\n"

    # 未覆盖的写路径在本地 fail closed：不转发给真实 handler，也不产生外部调用。
    for path, method in (("/api/v1/requests/save-confirm", "post"), ("/api/v1/requests", "delete")):
        response = getattr(requests, method)(f"{url}{path}", json={"confirm": True}, timeout=10)
        assert response.status_code == 409, (path, response.status_code)
        error = response.json()["error"]
        assert error["code"] == "preview_read_only"
        assert "外部写" in error["message"]


def test_preview_reproduces_the_fixed_batch_draft_scene(preview_server, page: Page, tmp_path: Path) -> None:
    url, _temp_root = preview_server
    require_dist()
    prepare_canvas(page)
    recorder = LoadedResourceRecorder(url)
    recorder.attach(page)

    page.goto(f"{url}/app/workbench?batch_id={PREVIEW_BATCH_ID}")
    page.wait_for_selector("#anime-mode-switch", timeout=10_000)
    page.click("#anime-mode-batch")
    page.wait_for_selector("#batch-parse-form", timeout=10_000)
    page.fill("#batch-raw-input", "葬送的芙莉莲\n迷宫饭")
    page.click("#batch-parse-submit")

    # fixture 固定批次（含待选、失败与未确认草案三种状态）直接出现在真实页面。
    expect(page.locator(".batch-draft-card")).to_have_count(5)
    expect(page.locator('.batch-draft-card[data-item-id="item-04"]')).to_contain_text("搜索失败")
    expect(page.locator('.batch-draft-card[data-item-id="item-05"]')).to_contain_text("草案")

    # 真实人工选择路径：点开待选条目 → 选择候选 → 固定草案（含安全资源样例）出现。
    page.locator('.batch-draft-card[data-item-id="item-01"]').click()
    page.locator("#batch-detail-pane .candidate-select").first.click()
    expect(page.locator("#batch-detail-pane .batch-resource-box")).to_be_visible()

    # 截图 + 证据清单：证明预览现场与截图使用同一份已校验构建。
    screenshot = tmp_path / "preview-batch-draft.png"
    capture_canvas(page, screenshot)
    manifest = capture_evidence(
        page,
        screenshot,
        base_url=url,
        scenario=ScenarioDescriptor(
            "preview-batch-draft-1440x900",
            "隔离预览中的固定批量草案现场",
            ("打开预览 /app/workbench?batch_id=…", "切批量并提交任意输入", "点选登记候选生成固定草案"),
        ),
        fixture=FixtureDescriptor(
            fixture_id="preview-safe-batch-draft",
            description="预览进程内固定安全 fixture：AB 未配置、追番为空、固定批量草案与安全资源样例。",
            mock_routes=("/api/v1/settings/autobangumi", "/api/v1/tracking/items", "/api/v1/batches/parse", "/api/v1/requests"),
        ),
        resources=recorder.records(),
        route="/app/add",
    )
    write_manifest(manifest, tmp_path, "preview-batch-draft")
    payload = json.loads((tmp_path / "preview-batch-draft.evidence.json").read_text(encoding="utf-8"))
    assert payload["screenshot"]["sha256"]
    assert payload["build"]["artifact_digest"]
    assert any(
        resource["path"].startswith("/app/assets/") for resource in payload["page"]["loaded_resources"]
    )
