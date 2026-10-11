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


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: Any) -> None:
        return None


class _FakeOpener:
    """Serves the raw bytes of one verified 3.1.18 session in request order."""

    def __init__(self, bodies: list[bytes]) -> None:
        self._bodies = list(bodies)
        self.requests: list[Any] = []

    def open(self, request: Any, timeout: float) -> _FakeResponse:
        self.requests.append(request)
        return _FakeResponse(self._bodies.pop(0))


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
    assert capabilities.subscription_modify == "SUPPORTED"
    assert capabilities.rss_modify == "SUPPORTED"
    assert capabilities.rss_enable == "SUPPORTED"
    assert capabilities.rss_disable == "SUPPORTED"
    assert capabilities.rss_delete == "SUPPORTED"
    assert capabilities.rss_refresh == "SUPPORTED"
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


def test_real_bare_array_lists_pass_the_decoder_and_management_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Issue #182: the verified 3.1.18 list shape is a bare JSON array.

    This goes through the *real* urllib JSON decoder and the real management
    adapter, so a wrapper-only fake can no longer hide the transport defect.
    """
    bodies = [
        b'{"access_token": "session-secret"}',
        b'{"version": "3.1.18"}',
        b'[{"id": 42, "official_title": "\\u793a\\u4f8b\\u756a\\u5267", "season": 2, "group_name": "\\u5b57\\u5e55\\u7ec4", "rss_ids": [7]}]',
        b'[{"id": 7, "name": "\\u8ba2\\u9605\\u6e90", "url": "https://rss.example/feed", "aggregate": false, "parser": "rss", "enabled": true}]',
    ]
    opener = _FakeOpener(bodies)
    monkeypatch.setattr(
        "ab_engine.controllers.ab_http_client.build_opener", lambda *handlers: opener
    )
    from ab_engine.controllers.ab_http_client import UrlopenAutoBangumiHttpTransport

    capabilities, subscriptions, rss_items = create_legacy_31_management_client(
        _config(), transport=UrlopenAutoBangumiHttpTransport()
    ).read_snapshot()

    assert capabilities.subscription_list == "SUPPORTED"
    assert [item.external_id for item in subscriptions] == ["42"]
    assert subscriptions[0].season == 2
    assert subscriptions[0].rss_ids == ("7",)
    assert [item.external_id for item in rss_items] == ["7"]
    assert rss_items[0].url == "https://rss.example/feed"


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


def test_subscription_enabled_is_derived_from_31_18_deleted_not_response_enabled() -> None:
    transport = RecordingTransport([
        {"access_token": "detail-secret"},
        {"data": {"id": "sub-42", "title_raw": "详情番剧", "deleted": True, "enabled": True}},
    ])
    subscription = create_legacy_31_management_client(_config(), transport=transport).get_subscription("sub-42")
    assert subscription.deleted is True
    assert subscription.enabled is False


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


def test_subscription_write_actions_use_exact_routes_and_clear_session() -> None:
    transport = RecordingTransport([
        {"access_token": "write-secret"}, {"version": "3.1.18"}, {"status": True},
        {"access_token": "enable-secret"}, {"version": "3.1.18"}, {"status": True},
        {"access_token": "disable-secret"}, {"version": "3.1.18"}, {"status": True},
        {"access_token": "delete-secret"}, {"version": "3.1.18"}, {"status": True},
    ])
    client = create_legacy_31_management_client(_config(), transport=transport)

    client.update_subscription("sub/42", {"title": "新标题"})
    client.set_subscription_enabled("sub/42", True)
    client.set_subscription_enabled("sub/42", False)
    client.delete_subscription("sub/42")

    assert [(call["method"], call["endpoint"]) for call in transport.calls] == [
        ("POST", "https://auto-bangumi.example/api/v1/auth/login"),
        ("GET", "https://auto-bangumi.example/api/v1/status"),
        ("PATCH", "https://auto-bangumi.example/api/v1/bangumi/update/sub%2F42"),
        ("POST", "https://auto-bangumi.example/api/v1/auth/login"),
        ("GET", "https://auto-bangumi.example/api/v1/status"),
        ("GET", "https://auto-bangumi.example/api/v1/bangumi/enable/sub%2F42"),
        ("POST", "https://auto-bangumi.example/api/v1/auth/login"),
        ("GET", "https://auto-bangumi.example/api/v1/status"),
        ("DELETE", "https://auto-bangumi.example/api/v1/bangumi/disable/sub%2F42?file=false"),
        ("POST", "https://auto-bangumi.example/api/v1/auth/login"),
        ("GET", "https://auto-bangumi.example/api/v1/status"),
        ("DELETE", "https://auto-bangumi.example/api/v1/bangumi/delete/sub%2F42?file=false"),
    ]
    assert transport.calls[2]["payload"] == {"title": "新标题"}
    assert transport.calls[8]["endpoint"].endswith("?file=false")
    assert transport.calls[11]["endpoint"].endswith("?file=false")
    assert all("write-secret" not in repr(call) for call in transport.calls[3:])


def test_write_capability_is_unknown_for_non_exact_version() -> None:
    transport = RecordingTransport([{"access_token": "secret"}, {"version": "3.1.19"}])
    capabilities = create_legacy_31_management_client(_config(), transport=transport).probe_capabilities()
    assert capabilities.subscription_modify == "UNKNOWN"
    assert capabilities.subscription_enable == "UNKNOWN"
    assert capabilities.subscription_disable == "UNKNOWN"
    assert capabilities.subscription_delete == "UNKNOWN"


def test_rss_write_actions_use_bounded_routes_and_preserve_snapshot_url() -> None:
    transport = RecordingTransport([
        {"access_token": "update-secret"}, {"version": "3.1.18"}, {"status": True},
        {"access_token": "enable-secret"}, {"version": "3.1.18"}, {"status": True},
        {"access_token": "disable-secret"}, {"version": "3.1.18"}, {"status": True},
        {"access_token": "delete-secret"}, {"version": "3.1.18"}, {"status": True},
        {"access_token": "refresh-secret"}, {"version": "3.1.18"}, {"status": True},
    ])
    client = create_legacy_31_management_client(_config(), transport=transport)

    client.update_rss("7", {"name": "新 RSS", "aggregate": False}, "https://rss.example/feed")
    client.enable_rss(["9", "7", "9"])
    client.disable_rss("7")
    client.delete_rss("9")
    client.refresh_rss("7")

    assert [(call["method"], call["endpoint"]) for call in transport.calls if call["method"] not in {"POST"} or "auth/login" not in call["endpoint"]] == [
        ("GET", "https://auto-bangumi.example/api/v1/status"),
        ("PATCH", "https://auto-bangumi.example/api/v1/rss/update/7"),
        ("GET", "https://auto-bangumi.example/api/v1/status"),
        ("POST", "https://auto-bangumi.example/api/v1/rss/enable/many"),
        ("GET", "https://auto-bangumi.example/api/v1/status"),
        ("PATCH", "https://auto-bangumi.example/api/v1/rss/disable/7"),
        ("GET", "https://auto-bangumi.example/api/v1/status"),
        ("DELETE", "https://auto-bangumi.example/api/v1/rss/delete/9"),
        ("GET", "https://auto-bangumi.example/api/v1/status"),
        ("GET", "https://auto-bangumi.example/api/v1/rss/refresh/7"),
    ]
    assert transport.calls[2]["payload"] == {"name": "新 RSS", "aggregate": False, "url": "https://rss.example/feed"}
    assert transport.calls[5]["payload"] == [7, 9]
    assert all("file" not in call["endpoint"] for call in transport.calls)
    assert client._token is None


def test_rss_update_cannot_replace_url_and_rss_targets_are_numeric() -> None:
    transport = RecordingTransport([])
    client = create_legacy_31_management_client(_config(), transport=transport)

    with pytest.raises(Stage1Error):
        client.update_rss("7", {"url": "https://attacker.example"}, "https://rss.example/feed")
    with pytest.raises(Stage1Error):
        client.enable_rss(["rss-not-numeric"])
    assert transport.calls == []


def test_snapshot_deadline_bounds_every_sub_request_together() -> None:
    """Issue #183 review: four serial requests share one remaining budget.

    Each sub-request gets only the time that is actually left, so a 12s endpoint
    budget is never extended into four fresh per-request timeouts.
    """
    clock = {"now": 0.0}
    timeouts: list[float] = []

    class _Transport:
        def request_json(self, method, endpoint, headers, payload=None, *, timeout):
            timeouts.append(timeout)
            clock["now"] += 4.0  # every request is slow but "successful"
            if endpoint.endswith("/auth/login"):
                return {"access_token": "session-secret"}
            if endpoint.endswith("/status"):
                return {"version": "3.1.18"}
            return []

        def post_json_same_origin(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("management adapter must never write")

    client = create_legacy_31_management_client(
        _config(), transport=_Transport(), monotonic=lambda: clock["now"]
    )

    with pytest.raises(Stage1Error) as error:
        client.read_snapshot(deadline=12.0)

    assert error.value.error_type == "ab_timeout"
    # 12 / 4 = three requests fit; the fourth would exceed the deadline.
    assert len(timeouts) == 3, timeouts
    assert timeouts == [12.0, 8.0, 4.0]
    assert clock["now"] == 12.0
