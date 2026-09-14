from __future__ import annotations

"""US-338: the browser reaches the real Flask deployment-config API."""

import json

import pytest
from playwright.sync_api import expect


@pytest.mark.browser
def test_saved_connection_real_api_survives_pages_and_reload(page, live_server_url):
    canary = ("cross-page-user", "cross-page-password", "127.0.0.1")
    page.goto(f"{live_server_url}/app/settings")
    saved = page.request.put(
        f"{live_server_url}/api/v1/settings/autobangumi",
        data={"confirm": True, "expected_configuration_revision": 0,
              "config": {"auth_mode": "password", "base_url": "127.0.0.1:8080",
                          "username": canary[0], "password": canary[1]}},
    )
    assert saved.ok
    page.reload()
    expect(page.locator("body")).to_contain_text("已保存连接：已配置")

    # The config PUT/GET above is real Flask; only external AB transport is
    # absent because this journey intentionally does not probe or write AB.
    for route in ("add", "plans", "tracking"):
        page.goto(f"{live_server_url}/app/{route}")
        expect(page.locator("body")).to_be_visible()
    page.reload()
    response = page.request.get(f"{live_server_url}/api/v1/settings/autobangumi")
    assert response.ok
    payload = response.json()
    assert payload["result"]["configured"] is True
    assert payload["result"]["credential_present"] is True
    assert all(value not in json.dumps(payload) for value in canary)
    assert all(value not in page.locator("body").inner_text() for value in canary)
    assert all(value not in page.evaluate("() => document.cookie") for value in canary)
    assert all(value not in page.evaluate("() => JSON.stringify(localStorage)") for value in canary)
    assert all(value not in page.evaluate("() => JSON.stringify(sessionStorage)") for value in canary)
