from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError

import pytest

from ab_engine.controllers.ab_config import AutoBangumiConfig
from ab_engine.controllers.ab_http_client import (
    AutoBangumiHttpClient,
    UrlopenAutoBangumiHttpTransport,
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
    def __init__(self, bodies: list[bytes | Exception]) -> None:
        self._bodies = list(bodies)
        self.requests: list[Any] = []

    def open(self, request: Any, timeout: float) -> _FakeResponse:
        self.requests.append(request)
        body = self._bodies.pop(0)
        if isinstance(body, Exception):
            raise body
        return _FakeResponse(body)


def _stub_urlopen(monkeypatch: pytest.MonkeyPatch, bodies: list[bytes | Exception]) -> _FakeOpener:
    opener = _FakeOpener(bodies)
    monkeypatch.setattr(
        "ab_engine.controllers.ab_http_client.build_opener",
        lambda *handlers: opener,
    )
    return opener


def test_legacy_transport_decodes_a_bare_json_array(monkeypatch: pytest.MonkeyPatch) -> None:
    """Issue #182: verified 3.1.18 list endpoints answer with a bare array."""
    _stub_urlopen(monkeypatch, [b'[{"id": 9, "name": "\\u8ba2\\u9605\\u6e90"}]'])

    result = UrlopenAutoBangumiHttpTransport().request_json(
        "GET", "https://auto-bangumi.example/api/v1/rss",
        {"Accept": "application/json"}, timeout=5,
    )

    assert result == [{"id": 9, "name": "订阅源"}]


def test_legacy_transport_rejects_non_json_and_keeps_the_stable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_urlopen(monkeypatch, [b"<html>not json</html>"])

    with pytest.raises(Stage1Error) as error:
        UrlopenAutoBangumiHttpTransport().request_json(
            "GET", "https://auto-bangumi.example/api/v1/rss", {}, timeout=5
        )

    assert error.value.error_type == "invalid_ab_response"


def test_write_transport_still_requires_a_json_object(monkeypatch: pytest.MonkeyPatch) -> None:
    """A write response is never shape-agnostic: only the read seam is relaxed."""
    _stub_urlopen(monkeypatch, [b"[]"])

    with pytest.raises(Stage1Error) as error:
        UrlopenAutoBangumiHttpTransport().post_json_same_origin(
            "https://auto-bangumi.example/api/v1/rss/subscribe", {}, {}, timeout=5
        )

    assert error.value.error_type == "invalid_ab_response"


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
    transport = _RecordingTransport([
        {"access_token": "secret-cookie"}, {"version": "3.1.18"},
        {"access_token": "secret-cookie"}, {"version": "3.1.18"},
        {"status": True},
    ])
    client = create_legacy_3_1_auto_bangumi_client(_password_config(), transport=transport)
    assert client.probe()["submit_supported"] is True
    assert client.create_subscription(_legacy_payload()) == {"status": True}
    assert all("Authorization" not in call["headers"] for call in transport.calls)
    assert all(call["endpoint"].startswith("http://auto-bangumi.local/") for call in transport.calls)


def test_submit_client_factory_dispatches_password_mode_to_legacy_adapter() -> None:
    transport = _RecordingTransport([
        {"access_token": "secret-cookie"},
        {"version": "3.1.18"},
        {"status": True},
    ])

    response = create_auto_bangumi_submit_client(
        _password_config(), transport=transport
    ).create_subscription(_legacy_payload())

    assert response == {"status": True}
    assert [call["endpoint"] for call in transport.calls] == [
        "http://auto-bangumi.local/api/v1/auth/login",
        "http://auto-bangumi.local/api/v1/status",
        "http://auto-bangumi.local/api/v1/rss/subscribe",
    ]
    assert transport.calls[2]["headers"]["Cookie"] == "token=secret-cookie"


def test_submit_checks_connection_credentials_and_version_before_writing() -> None:
    """Issue #86: the pre-write check fails closed before any subscribe POST."""
    unreachable = _RecordingTransport([URLError("connection refused")])
    with pytest.raises(Stage1Error) as failure:
        create_auto_bangumi_submit_client(
            _password_config(), transport=unreachable
        ).create_subscription(_legacy_payload())
    assert failure.value.error_type == "ab_connection_failed_pre_write"
    assert not any("rss/subscribe" in call["endpoint"] for call in unreachable.calls)

    unsupported = _RecordingTransport([
        {"access_token": "secret-cookie"}, {"version": "2.6.0"},
    ])
    with pytest.raises(Stage1Error) as unsupported_failure:
        create_auto_bangumi_submit_client(
            _password_config(), transport=unsupported
        ).create_subscription(_legacy_payload())
    assert unsupported_failure.value.error_type == "ab_unsupported_version"
    assert not any("rss/subscribe" in call["endpoint"] for call in unsupported.calls)


def test_submit_classifies_a_duplicate_subscription_with_bounded_upstream_reason() -> None:
    """Issue #101 AC 3/4: the reason is kept for diagnostics, never wholesale.

    The upstream ``msg`` reaches only the sanitized, bounded diagnostics; the
    fixed error message, step and any secret stay untouched.
    """
    canary = "订阅《番剧》已经存在，请勿重复添加"
    secret = "secret-cookie"
    transport = _RecordingTransport([
        {"access_token": secret},
        {"version": "3.1.18"},
        {"status": False, "msg": canary},
    ])

    with pytest.raises(Stage1Error) as failure:
        create_auto_bangumi_submit_client(
            _password_config(), transport=transport
        ).create_subscription(_legacy_payload())

    assert failure.value.error_type == "ab_duplicate_subscription"
    # The fixed, safe message never echoes upstream text.
    assert canary not in failure.value.message
    assert canary not in failure.value.failed_step
    assert secret not in str(failure.value.details or {})
    # The bounded reason is available to the diagnostics layer only.
    assert failure.value.details == {"message_zh": canary}


class _TricklingResponse:
    """A body that keeps arriving until the strict deadline closes it."""

    def __init__(self) -> None:
        self.closed = threading.Event()

    def read(self) -> bytes:
        # Simulate a peer that never stops sending: the read only returns when
        # the watchdog closes the response, which must happen at the deadline.
        self.closed.wait(5.0)
        raise OSError("response closed at the deadline")

    def close(self) -> None:
        self.closed.set()

    def __enter__(self) -> _TricklingResponse:
        return self

    def __exit__(self, *args: Any) -> None:
        return None


def test_a_trickling_body_cannot_outlive_the_strict_read_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #183 review: the *total* time is bounded, not one socket recv."""
    response = _TricklingResponse()
    monkeypatch.setattr(
        "ab_engine.controllers.ab_http_client.build_opener",
        lambda *handlers: _AlwaysOpener(response),
    )

    started = time.monotonic()
    with pytest.raises(Stage1Error) as error:
        UrlopenAutoBangumiHttpTransport().request_json(
            "GET", "https://auto-bangumi.example/api/v1/rss", {}, timeout=0.05
        )
    elapsed = time.monotonic() - started

    assert error.value.error_type == "ab_timeout"
    assert elapsed < 1.0, elapsed


class _AlwaysOpener:
    def __init__(self, response: Any) -> None:
        self._response = response

    def open(self, request: Any, timeout: float) -> Any:
        return self._response
