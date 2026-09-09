from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from ab_engine.controllers.ab_config import AutoBangumiConfig
from ab_engine.controllers.ab_management_client import create_legacy_31_management_client
from ab_engine.models.management import AutoBangumiCapabilities
from shared.errors import Stage1Error


class RecordingTransport:
    """Offline transport that makes every management request auditable."""

    def __init__(self, responses: list[dict[str, Any] | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def request_json(
        self,
        method: str,
        endpoint: str,
        headers: Mapping[str, str],
        payload: Mapping[str, str] | None = None,
        *,
        timeout: float,
    ) -> dict[str, Any]:
        self.calls.append({"method": method, "endpoint": endpoint, "headers": dict(headers), "payload": payload})
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def post_json_same_origin(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("management adapter must never use the write transport")


def _config(**overrides: str) -> AutoBangumiConfig:
    values: dict[str, Any] = {
        "base_url": "https://auto-bangumi.example",
        "auth_mode": "password",
        "fallback_enabled": False,
        "username": "operator",
        "password": "password-secret",
    }
    values.update(overrides)
    return AutoBangumiConfig(**values)


def test_snapshot_logs_one_login_and_only_same_origin_reads() -> None:
    transport = RecordingTransport([
        {"access_token": "session-secret"},
        {"version": "3.1.18"},
        {"data": [{"id": 42, "official_title": "示例番剧", "season": 2, "group_name": "字幕组", "rss_link": "https://rss.example/feed", "rss_ids": [7, 7]}]},
        {"data": [{"id": 9, "name": "订阅源", "url": "https://rss.example/feed", "aggregate": True, "parser": "rss", "enabled": True}]},
    ])

    capabilities, subscriptions, rss_items = create_legacy_31_management_client(
        _config(), transport=transport
    ).read_snapshot()

    assert isinstance(capabilities, AutoBangumiCapabilities)
    assert capabilities.probe_status == "VERIFIED"
    assert capabilities.subscription_list == "SUPPORTED"
    assert capabilities.subscription_detail == "SUPPORTED"
    assert capabilities.rss_list == "SUPPORTED"
    assert capabilities.external_verify == "SUPPORTED"
    assert capabilities.subscription_modify == "UNKNOWN"
    assert [call["method"] for call in transport.calls] == ["POST", "GET", "GET", "GET"]
    assert [call["endpoint"] for call in transport.calls] == [
        "https://auto-bangumi.example/api/v1/auth/login",
        "https://auto-bangumi.example/api/v1/status",
        "https://auto-bangumi.example/api/v1/bangumi/get/all",
        "https://auto-bangumi.example/api/v1/rss",
    ]
    assert transport.calls[0]["payload"] == {"username": "operator", "password": "password-secret"}
    assert transport.calls[1]["headers"]["Cookie"] == "token=session-secret"
    assert transport.calls[2]["headers"]["Cookie"] == "token=session-secret"
    assert transport.calls[3]["headers"]["Cookie"] == "token=session-secret"
    assert subscriptions[0].safe_projection().rss_count == 1
    assert "https://rss.example/feed" not in repr(rss_items[0])


def test_detail_uses_a_fresh_request_scoped_login_and_escapes_id() -> None:
    transport = RecordingTransport([
        {"access_token": "detail-secret"},
        {"data": {"id": "sub-42", "title_raw": "详情番剧", "deleted": False}},
    ])

    subscription = create_legacy_31_management_client(
        _config(), transport=transport
    ).get_subscription("sub-42")

    assert subscription.external_id == "sub-42"
    assert [call["endpoint"] for call in transport.calls] == [
        "https://auto-bangumi.example/api/v1/auth/login",
        "https://auto-bangumi.example/api/v1/bangumi/get/sub-42",
    ]
    assert transport.calls[1]["headers"]["Cookie"] == "token=detail-secret"


def test_unknown_version_stops_before_reading_lists_and_releases_token() -> None:
    transport = RecordingTransport([{"access_token": "secret"}, {"version": "3.1.17"}])
    client = create_legacy_31_management_client(_config(), transport=transport)

    with pytest.raises(Stage1Error) as error:
        client.read_snapshot()

    assert error.value.error_type == "ab_unsupported_version"
    assert [call["endpoint"] for call in transport.calls] == [
        "https://auto-bangumi.example/api/v1/auth/login",
        "https://auto-bangumi.example/api/v1/status",
    ]
    assert "secret" not in repr(error.value.as_dict())


@pytest.mark.parametrize(
    ("response", "field"),
    [
        ({"version": "3.1.18", "unexpected": "x"}, "subscriptions"),
        ({"version": "3.1.18"}, "subscriptions"),
    ],
)
def test_invalid_list_response_is_stable_and_does_not_echo_upstream(response: dict[str, Any], field: str) -> None:
    transport = RecordingTransport([{"access_token": "secret"}, {"version": "3.1.18"}, response])
    client = create_legacy_31_management_client(_config(), transport=transport)

    with pytest.raises(Stage1Error) as error:
        client.read_snapshot()

    assert error.value.error_type == "invalid_ab_response"
    assert error.value.details == {"field": field}
    assert "secret" not in repr(error.value.as_dict())
    assert "https://" not in repr(error.value.as_dict())


def test_api_token_management_is_fail_closed_without_transport_calls() -> None:
    transport = RecordingTransport([])
    config = _config(auth_mode="api_token", username=None, password=None, token="token-secret")
    client = create_legacy_31_management_client(config, transport=transport)

    with pytest.raises(Stage1Error) as error:
        client.read_snapshot()

    assert error.value.error_type == "ab_management_unsupported"
    assert transport.calls == []
    assert "token-secret" not in repr(error.value.as_dict())
