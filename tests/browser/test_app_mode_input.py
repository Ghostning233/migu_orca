from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser


def test_add_mode_switch_preserves_local_inputs_and_hides_inactive_form(page: Page, live_server_url: str) -> None:
    page.goto(f"{live_server_url}/app/add")
    page.wait_for_selector("#anime-mode-switch")

    single = page.locator("#mikan-candidate-query")
    expect(single).to_be_visible()
    page.fill("#mikan-candidate-query", "葬送的芙莉莲")
    page.locator("#anime-mode-batch").click()

    expect(page.locator("#anime-mode-batch")).to_have_attribute("aria-selected", "true")
    expect(single).not_to_be_visible()
    batch = page.locator("#batch-raw-input")
    expect(batch).to_be_visible()
    page.fill("#batch-raw-input", "萌王S4\n路哥S4")
    assert "mode" not in page.url

    page.locator("#anime-mode-single").click()
    expect(page.locator("#mikan-candidate-query")).to_have_value("葬送的芙莉莲")
    expect(page.locator("#batch-raw-input")).not_to_be_visible()
    page.locator("#anime-mode-batch").click()
    expect(page.locator("#batch-raw-input")).to_have_value("萌王S4\n路哥S4")
