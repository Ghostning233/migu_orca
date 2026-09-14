"""Stage 39 browser red tests for the retired credential boundary."""

import pytest


@pytest.mark.browser
def test_retired_capabilities_endpoint_is_not_reachable(page, live_server_url):
    response = page.request.post(f"{live_server_url}/api/v1/autobangumi/capabilities", data="{}")
    assert response.status == 404


@pytest.mark.browser
def test_tracking_page_has_no_legacy_credential_dialog(page, live_server_url):
    page.goto(f"{live_server_url}/app/tracking")
    page.wait_for_load_state("networkidle")
    assert page.locator("#tracking-connect").count() == 0
    assert page.locator("text=连接 Auto Bangumi").count() == 0
