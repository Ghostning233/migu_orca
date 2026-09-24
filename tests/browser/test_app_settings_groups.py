"""Issue 117：设置三分组顺序、数据档案语义与切换旅程的真实 Chromium 门禁。

覆盖：

- 分组顺序固定为「默认偏好 → MiGuOrca 本地数据 → Auto Bangumi 连接」，
  默认偏好按字幕组／过滤规则／命名方式分段；
- 移除没有明确用途的独立「高级诊断」区；
- 数据档案明确是当前浏览器选用的 MiGuOrca 业务数据 profile，不是媒体下载路径；
  切换提示「不会移动原有数据、可切回」；选择由当前浏览器记住；
- 1280／1440／1920 无横向溢出、分组可达。
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import set_storage_preferences

pytestmark = pytest.mark.browser


def _goto_settings(page: Page, live_server_url: str) -> None:
    page.goto(f"{live_server_url}/app/settings")
    page.wait_for_selector("#settings-heading", timeout=5000)


def _group_order(page: Page) -> list[str]:
    return page.evaluate(
        """() => Array.from(document.querySelectorAll('.settings-view .panel-section h2'))
            .map((heading) => heading.textContent.trim())"""
    )


def test_settings_groups_keep_the_approved_order_and_segments(
    page: Page, live_server_url: str
) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    _goto_settings(page, live_server_url)

    groups = _group_order(page)
    assert groups[:3] == ["默认偏好", "MiGuOrca 本地数据", "Auto Bangumi 连接"], groups
    # 默认偏好按字幕组／过滤规则／命名方式分段。
    sub_headings = page.evaluate(
        """() => Array.from(document.querySelectorAll('#preference-settings-form .settings-group-title'))
            .map((element) => element.textContent.trim())"""
    )
    assert sub_headings == ["字幕组", "过滤规则", "命名方式"], sub_headings

    # 没有明确用途的独立高级诊断区已移除。
    expect(page.locator("#settings-advanced-diagnostics")).to_have_count(0)
    assert "高级诊断" not in page.locator("body").inner_text()


def test_data_profile_copy_states_business_profile_not_media_path(
    page: Page, live_server_url: str
) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    _goto_settings(page, live_server_url)

    panel = page.locator(".settings-view .panel-section").nth(1)
    text = panel.inner_text()
    assert "MiGuOrca 本地数据" in text
    assert "当前浏览器选用的 MiGuOrca 业务数据 profile" in text
    assert "不是下载媒体的位置" in text
    expect(page.locator("#settings-storage-dir")).to_be_visible()
    # 不提供 AB 下载路径编辑。
    assert "downloader.path" not in page.locator("body").inner_text()


def test_switching_data_profile_never_moves_existing_data(
    page: Page, live_server_url: str
) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    _goto_settings(page, live_server_url)

    page.locator("#settings-storage-dir").fill("archive-a")
    page.locator("#storage-preferences-save").click()
    alert = page.locator("#storage-preferences-form .status-alert-success")
    expect(alert).to_be_visible()
    expect(alert).to_contain_text("数据档案已保存")
    expect(alert).to_contain_text("切换数据档案不会移动原有数据")
    expect(alert).to_contain_text("可切回原档案查看")

    # 当前浏览器记住选择：切换到另一个档案后再切回，原档案仍可用。
    page.locator("#settings-storage-dir").fill("archive-b")
    page.locator("#storage-preferences-save").click()
    expect(alert).to_contain_text("数据档案已保存")
    stored = page.evaluate("() => localStorage.getItem('miguOrca.web.storageDir')")
    assert stored == "archive-b"

    page.reload()
    page.wait_for_selector("#settings-heading")
    expect(page.locator("#settings-storage-dir")).to_have_value("archive-b")
    page.locator("#settings-storage-dir").fill("archive-a")
    page.locator("#storage-preferences-save").click()
    expect(page.locator("#settings-storage-dir")).to_have_value("archive-a")

    # 清除选择只影响当前浏览器选择，不删除任何数据。
    page.locator("#storage-preferences-clear").click()
    expect(page.locator("#storage-preferences-form .status-alert-info")).to_contain_text(
        "原有数据不会被移动"
    )


def test_saved_connection_state_is_separate_from_probe_state(
    page: Page, live_server_url: str
) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.route(
        "**/api/v1/settings/autobangumi",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=(
                '{"ok": true, "result": {"configured": true, "credential_present": true, '
                '"connection_ref": "11111111-1111-4111-8111-111111111111", '
                '"configuration_revision": 2, "connection_status": "UNKNOWN", "capabilities": null}}'
            ),
        ),
    )
    _goto_settings(page, live_server_url)

    connection_panel = page.locator(".settings-view .panel-section").nth(2)
    expect(connection_panel).to_contain_text("Auto Bangumi 连接")
    # 已保存配置与最近探测状态分开呈现，秘密不回显。
    assert "11111111-1111-4111-8111-111111111111" not in page.locator("body").inner_text()
    expect(page.locator("#settings-ab-configuration-revision")).to_have_count(0)


@pytest.mark.parametrize("width", [1280, 1920])
def test_settings_groups_stay_reachable_at_desktop_widths(
    page: Page, live_server_url: str, storage_dir, width: int
) -> None:
    set_storage_preferences(page, storage_dir)
    page.set_viewport_size({"width": width, "height": 900})
    _goto_settings(page, live_server_url)

    for group in ("默认偏好", "MiGuOrca 本地数据", "Auto Bangumi 连接"):
        expect(page.get_by_role("heading", name=group)).to_be_visible()
    metrics = page.evaluate(
        "() => ({body: document.body.scrollWidth, viewport: window.innerWidth})"
    )
    assert metrics["body"] <= metrics["viewport"] + 1
