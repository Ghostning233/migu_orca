from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError

from ab_engine.controllers.ab_config import AutoBangumiConfig
from ab_engine.controllers.ab_http_client import (
    AutoBangumiHttpClient,
    create_auto_bangumi_http_client,
    create_auto_bangumi_submit_client,
    create_legacy_3_1_auto_bangumi_client,
)
from ab_engine.controllers.subscription_payload import build_legacy_31_subscription_payload
from request_engine.controllers.request_controller import accept_request, build_pending_request
from shared.errors import Stage1Error
from shared.models import EntryRequest, FilterRule, MatchedBangumi, SubtitleGroupSelection


class _RecordingTransport:
    def __init__(self, responses: list[dict[str, Any] | Exception]) -> None:
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    def request_json(self, method: str, endpoint: str, headers: Mapping[str, str], payload: Mapping[str, str] | None = None, *, timeout: float) -> dict[str, Any]:
        self.calls.append({"method": method, "endpoint": endpoint, "headers": dict(headers), "payload": payload, "timeout": timeout})
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def post_json(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("the Token compatibility adapter must not write")

    def post_json_same_origin(self, endpoint: str, headers: Mapping[str, str], payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        self.calls.append({"method": "POST", "endpoint": endpoint, "headers": dict(headers), "payload": payload, "timeout": timeout})
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _token_config() -> AutoBangumiConfig:
    return AutoBangumiConfig("http://auto-bangumi.local", "api_token", False, token="secret-token")


def _password_config() -> AutoBangumiConfig:
    return AutoBangumiConfig("http://auto-bangumi.local", "password", False, username="admin", password="secret-password")


def _legacy_payload() -> dict[str, Any]:
    request = accept_request(build_pending_request(
        EntryRequest("番剧"), MatchedBangumi("番剧", [], "https://example.invalid/bangumi", 1.0), [],
        SubtitleGroupSelection("Loli", "https://example.invalid/rss.xml", []), FilterRule(must_not_contain="SP"), "番剧",
    ))
    return build_legacy_31_subscription_payload(request)


def test_token_client_is_protocol_compatible() -> None:
    assert isinstance(create_auto_bangumi_http_client(_token_config()), AutoBangumiHttpClient)


def test_token_probe_uses_bearer_only_for_same_origin_read() -> None:
    transport = _RecordingTransport([{"version": "4.2.0"}])
    summary = create_auto_bangumi_http_client(_token_config(), transport=transport).probe()
    assert summary == {"reachable": True, "authenticated": True, "version": "4.2.0", "adapter": "api_token", "submit_supported": False}
    assert transport.calls == [{"method": "GET", "endpoint": "http://auto-bangumi.local/api/v1/status", "headers": {"Accept": "application/json", "Authorization": "Bearer secret-token"}, "payload": None, "timeout": 30}]


def test_token_probe_normalizes_auth_failure_without_credentials() -> None:
    client = create_auto_bangumi_http_client(_token_config(), transport=_RecordingTransport([HTTPError("http://auto-bangumi.local/status", 401, "secret-token", {}, None)]))
    try:
        client.probe()
    except Stage1Error as error:
        result = error.as_dict()
    else:
        raise AssertionError("expected Stage1Error")
    assert result == {"error_type": "ab_auth_failed", "error_message": "Auto Bangumi 认证失败", "failed_step": "probe_ab_connection", "details": {"status_code": 401}}
    assert "secret-token" not in repr(result)


def test_token_submit_fails_closed_without_a_write_request() -> None:
    transport = _RecordingTransport([])
    client = create_auto_bangumi_http_client(_token_config(), transport=transport)
    payload = {"title": "番剧", "rss_url": "https://example.invalid/rss.xml", "save_path": "番剧", "filter_rule": {}}
    try:
        client.create_subscription(payload)
    except Stage1Error as error:
        result = error.as_dict()
    else:
        raise AssertionError("expected Stage1Error")
    assert result == {"error_type": "ab_submit_unsupported", "error_message": "当前 Auto Bangumi 版本暂不支持提交", "failed_step": "create_ab_subscription", "details": {}}
    assert transport.calls == []


def test_legacy_31_probe_and_submit_stay_cookie_isolated() -> None:
    transport = _RecordingTransport([{"access_token": "secret-cookie"}, {"version": "3.1.18"}, {"access_token": "secret-cookie"}, {"status": True}])
    client = create_legacy_3_1_auto_bangumi_client(_password_config(), transport=transport)
    assert client.probe()["submit_supported"] is True
    assert client.create_subscription(_legacy_payload()) == {"status": True}
    assert all("Authorization" not in call["headers"] for call in transport.calls)
    assert all(call["endpoint"].startswith("http://auto-bangumi.local/") for call in transport.calls)


def test_submit_client_factory_dispatches_password_mode_to_legacy_adapter() -> None:
    transport = _RecordingTransport([
        {"access_token": "secret-cookie"},
        {"status": True},
    ])

    response = create_auto_bangumi_submit_client(
        _password_config(), transport=transport
    ).create_subscription(_legacy_payload())

    assert response == {"status": True}
    assert [call["endpoint"] for call in transport.calls] == [
        "http://auto-bangumi.local/api/v1/auth/login",
        "http://auto-bangumi.local/api/v1/rss/subscribe",
    ]
    assert transport.calls[1]["headers"]["Cookie"] == "token=secret-cookie"
