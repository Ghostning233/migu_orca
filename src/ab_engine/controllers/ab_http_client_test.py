from __future__ import annotations

import json
from typing import Any, Mapping
from urllib.error import HTTPError, URLError

from ab_engine.controllers.ab_client import AutoBangumiClient, submit_ab_subscription
from ab_engine.controllers.ab_config import AutoBangumiConfig
from ab_engine.controllers.ab_http_client import (
    AutoBangumiHttpClient,
    create_auto_bangumi_http_client,
    create_legacy_3_1_auto_bangumi_client,
)
from ab_engine.controllers.subscription_payload import (
    build_ab_subscription_payload,
    build_legacy_31_subscription_payload,
)
from request_engine.controllers.request_controller import (
    accept_request,
    build_pending_request,
)
from shared.errors import Stage1Error
from shared.models import EntryRequest, FilterRule, MatchedBangumi, SubtitleGroupSelection


class _FakeHttpResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body

    def __enter__(self) -> _FakeHttpResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._body, ensure_ascii=False).encode("utf-8")


class _RawHttpResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _RawHttpResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class _RecordingTransport:
    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    def post_json(
        self,
        endpoint: str,
        headers: Mapping[str, str],
        payload: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "endpoint": endpoint,
                "headers": headers,
                "payload": payload,
                "timeout": timeout,
            }
        )
        return self._response


class _FailingTransport:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def post_json(
        self,
        endpoint: str,
        headers: Mapping[str, str],
        payload: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        raise self._error


class _LegacyRecordingTransport:
    def __init__(self, responses: list[dict[str, Any] | Exception]) -> None:
        self._responses = responses
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
        self.calls.append(
            {
                "method": method,
                "endpoint": endpoint,
                "headers": dict(headers),
                "payload": dict(payload) if payload is not None else None,
                "timeout": timeout,
            }
        )
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def post_json_same_origin(
        self,
        endpoint: str,
        headers: Mapping[str, str],
        payload: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "method": "POST",
                "endpoint": endpoint,
                "headers": dict(headers),
                "payload": payload,
                "timeout": timeout,
            }
        )
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class _ExplodingConfig:
    @property
    def endpoint(self) -> str:
        raise AssertionError("config endpoint should not be read for invalid payload")

    @property
    def token(self) -> str:
        raise AssertionError("config token should not be read for invalid payload")


def _config() -> AutoBangumiConfig:
    return AutoBangumiConfig(
        base_url="http://auto-bangumi.local",
        auth_mode="api_token",
        token="secret-token",
        fallback_enabled=False,
    )


def _password_config() -> AutoBangumiConfig:
    return AutoBangumiConfig(
        base_url="http://auto-bangumi.local",
        auth_mode="password",
        username="admin",
        password="secret-password",
        fallback_enabled=False,
    )


def _payload() -> dict[str, Any]:
    return {
        "title": "番剧",
        "rss_url": "https://example.invalid/rss.xml",
        "save_path": "番剧",
        "filter_rule": {"must_contain": "1080p"},
    }


def _accepted_request() -> dict[str, Any]:
    pending = build_pending_request(
        EntryRequest("番剧"),
        MatchedBangumi("番剧 标准标题", [], "https://example.invalid/bangumi", 1.0),
        [],
        SubtitleGroupSelection("Loli", "https://example.invalid/rss.xml", []),
        FilterRule(must_contain="1080p", must_not_contain="SP"),
        "番剧 标准标题",
    )
    return accept_request(pending)


def test_http_client_constructor_returns_protocol_compatible_client() -> None:
    client: AutoBangumiClient = create_auto_bangumi_http_client(_config())

    assert isinstance(client, AutoBangumiHttpClient)


def test_legacy_31_probe_logs_in_then_reads_status_with_in_memory_cookie() -> None:
    transport = _LegacyRecordingTransport(
        [{"access_token": "secret-token"}, {"version": "3.1.18"}]
    )
    client = create_legacy_3_1_auto_bangumi_client(
        _password_config(), transport=transport
    )

    assert client.probe() == {
        "reachable": True,
        "authenticated": True,
        "version": "3.1.18",
        "adapter": "legacy_3_1",
        "submit_supported": True,
    }
    assert transport.calls == [
        {
            "method": "POST",
            "endpoint": "http://auto-bangumi.local/api/v1/auth/login",
            "headers": {
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            "payload": {"username": "admin", "password": "secret-password"},
            "timeout": 30,
        },
        {
            "method": "GET",
            "endpoint": "http://auto-bangumi.local/api/v1/status",
            "headers": {"Accept": "application/json", "Cookie": "token=secret-token"},
            "payload": None,
            "timeout": 30,
        },
    ]


def test_legacy_31_probe_normalizes_auth_and_transport_failures_without_secrets() -> None:
    for error, expected in [
        (HTTPError("http://auto-bangumi.local/login", 401, "admin", {}, None), "ab_auth_failed"),
        (TimeoutError("secret-password"), "ab_timeout"),
        (URLError("secret-token"), "ab_connection_failed"),
    ]:
        client = create_legacy_3_1_auto_bangumi_client(
            _password_config(), transport=_LegacyRecordingTransport([error])
        )
        try:
            client.probe()
        except Stage1Error as exc:
            result = exc.as_dict()
        else:
            raise AssertionError("expected Stage1Error")
        assert result["error_type"] == expected
        assert result["failed_step"] == "probe_ab_connection"
        assert "admin" not in repr(result)
        assert "secret" not in repr(result)


def test_legacy_31_probe_rejects_missing_token_and_unknown_version_without_leaking() -> None:
    for responses, expected in [
        ([{}], "invalid_ab_response"),
        ([{"access_token": "secret-token"}, {"version": "4.0.0"}], "ab_unsupported_version"),
    ]:
        client = create_legacy_3_1_auto_bangumi_client(
            _password_config(), transport=_LegacyRecordingTransport(responses)
        )
        try:
            client.probe()
        except Stage1Error as exc:
            result = exc.as_dict()
        else:
            raise AssertionError("expected Stage1Error")
        assert result["error_type"] == expected
        assert "secret-token" not in repr(result)


def test_legacy_31_client_submits_contract_body_with_in_memory_cookie() -> None:
    transport = _LegacyRecordingTransport(
        [{"access_token": "secret-token"}, {"status": True}]
    )
    client = create_legacy_3_1_auto_bangumi_client(
        _password_config(), transport=transport
    )
    payload = build_legacy_31_subscription_payload(_accepted_request())

    assert client.create_subscription(payload) == {"status": True}
    assert transport.calls == [
        {
            "method": "POST",
            "endpoint": "http://auto-bangumi.local/api/v1/auth/login",
            "headers": {
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            "payload": {"username": "admin", "password": "secret-password"},
            "timeout": 30,
        },
        {
            "method": "POST",
            "endpoint": "http://auto-bangumi.local/api/v1/rss/subscribe",
            "headers": {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Cookie": "token=secret-token",
            },
            "payload": payload,
            "timeout": 30,
        },
    ]


def test_legacy_31_client_rejects_failed_or_malformed_submit_response_without_secrets() -> None:
    for response in ({"status": False}, {}, {"status": "true"}):
        client = create_legacy_3_1_auto_bangumi_client(
            _password_config(),
            transport=_LegacyRecordingTransport([{"access_token": "secret-token"}, response]),
        )
        try:
            client.create_subscription(build_legacy_31_subscription_payload(_accepted_request()))
        except Stage1Error as exc:
            result = exc.as_dict()
        else:
            raise AssertionError("expected Stage1Error")
        assert result["error_type"] == "ab_submit_failed"
        assert result["failed_step"] == "create_ab_subscription"
        assert "secret" not in repr(result)


def test_http_client_posts_prepared_payload_without_mutating_it(monkeypatch) -> None:
    sent_requests = []

    def fake_urlopen(request, timeout):  # type: ignore[no-untyped-def]
        sent_requests.append((request, timeout))
        return _FakeHttpResponse({"id": "sub-123", "status": "created"})

    monkeypatch.setattr("ab_engine.controllers.ab_http_client.urlopen", fake_urlopen)
    payload = _payload()
    client = create_auto_bangumi_http_client(_config())

    response = client.create_subscription(payload)
    payload["filter_rule"]["must_contain"] = "changed"

    request, timeout = sent_requests[0]
    assert response == {"id": "sub-123", "status": "created"}
    assert request.full_url == "http://auto-bangumi.local"
    assert request.get_method() == "POST"
    assert request.headers["Authorization"] == "Bearer secret-token"
    assert request.headers["Content-type"] == "application/json"
    assert request.headers["Accept"] == "application/json"
    assert timeout == 30
    assert json.loads(request.data.decode("utf-8")) == {
        "title": "番剧",
        "rss_url": "https://example.invalid/rss.xml",
        "save_path": "番剧",
        "filter_rule": {"must_contain": "1080p"},
    }


def test_http_client_uses_injected_transport_without_network() -> None:
    transport = _RecordingTransport({"id": "sub-123", "status": "created"})
    payload = _payload()
    client = create_auto_bangumi_http_client(_config(), transport=transport)

    response = client.create_subscription(payload)
    payload["filter_rule"]["must_contain"] = "changed"

    assert response == {"id": "sub-123", "status": "created"}
    assert transport.calls == [
        {
            "endpoint": "http://auto-bangumi.local",
            "headers": {
                "Authorization": "Bearer secret-token",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            "payload": {
                "title": "番剧",
                "rss_url": "https://example.invalid/rss.xml",
                "save_path": "番剧",
                "filter_rule": {"must_contain": "1080p"},
            },
            "timeout": 30,
        }
    ]


def test_http_client_accepts_stage3_payload_mapper_output() -> None:
    transport = _RecordingTransport({"id": "sub-123", "status": "created"})
    client = create_auto_bangumi_http_client(_config(), transport=transport)

    response = client.create_subscription(
        build_ab_subscription_payload(_accepted_request())
    )

    assert response == {"id": "sub-123", "status": "created"}
    assert transport.calls[0]["payload"] == {
        "title": "番剧 标准标题",
        "rss_url": "https://example.invalid/rss.xml",
        "save_path": "番剧 标准标题",
        "filter_rule": {
            "must_contain": "1080p",
            "must_not_contain": "SP",
            "use_regex": False,
            "case_sensitive": False,
        },
    }


def test_http_client_trims_core_payload_strings_before_transport() -> None:
    transport = _RecordingTransport({"id": "sub-123", "status": "created"})
    client = create_auto_bangumi_http_client(_config(), transport=transport)
    payload = {
        "title": " 番剧 ",
        "rss_url": " https://example.invalid/rss.xml ",
        "save_path": " 番剧 ",
        "filter_rule": {"must_contain": "1080p"},
    }

    client.create_subscription(payload)

    assert transport.calls[0]["payload"] == {
        "title": "番剧",
        "rss_url": "https://example.invalid/rss.xml",
        "save_path": "番剧",
        "filter_rule": {"must_contain": "1080p"},
    }


def test_http_client_copies_validated_filter_rule_before_transport() -> None:
    transport = _RecordingTransport({"id": "sub-123", "status": "created"})
    payload = _payload()
    client = create_auto_bangumi_http_client(_config(), transport=transport)

    client.create_subscription(payload)
    payload["filter_rule"]["must_contain"] = "changed"

    assert transport.calls[0]["payload"]["filter_rule"] == {"must_contain": "1080p"}


def test_http_client_rejects_invalid_payload_before_config_or_transport() -> None:
    transport = _RecordingTransport({"id": "sub-123", "status": "created"})
    client = AutoBangumiHttpClient(_ExplodingConfig(), transport=transport)  # type: ignore[arg-type]

    try:
        client.create_subscription({"rss_url": "https://example.invalid/rss.xml"})
    except Stage1Error as error:
        error_dict = error.as_dict()
    else:
        raise AssertionError("expected Stage1Error")

    assert error_dict == {
        "error_type": "invalid_ab_payload",
        "error_message": "Auto Bangumi payload 缺少必填字符串字段",
        "failed_step": "validate_ab_subscription_payload",
        "details": {"field": "title", "expected_type": "string"},
    }
    assert transport.calls == []


def test_http_client_rejects_invalid_filter_rule_before_transport() -> None:
    transport = _RecordingTransport({"id": "sub-123", "status": "created"})
    client = create_auto_bangumi_http_client(_config(), transport=transport)
    payload = _payload()
    payload["filter_rule"] = []

    try:
        client.create_subscription(payload)
    except Stage1Error as error:
        error_dict = error.as_dict()
    else:
        raise AssertionError("expected Stage1Error")

    assert error_dict == {
        "error_type": "invalid_ab_payload",
        "error_message": "Auto Bangumi payload 字段类型错误",
        "failed_step": "validate_ab_subscription_payload",
        "details": {"field": "filter_rule", "expected_type": "object"},
    }
    assert transport.calls == []


def test_http_non_success_response_becomes_structured_error_without_token(
    monkeypatch,
) -> None:
    def fake_urlopen(request, timeout):  # type: ignore[no-untyped-def]
        raise HTTPError(
            request.full_url,
            503,
            "Service Unavailable secret-token",
            {},
            None,
        )

    monkeypatch.setattr("ab_engine.controllers.ab_http_client.urlopen", fake_urlopen)
    client = create_auto_bangumi_http_client(_config())

    try:
        client.create_subscription(_payload())
    except Stage1Error as error:
        error_dict = error.as_dict()
    else:
        raise AssertionError("expected Stage1Error")

    assert error_dict == {
        "error_type": "ab_submit_failed",
        "error_message": "Auto Bangumi HTTP 提交失败",
        "failed_step": "create_ab_subscription",
        "details": {"status_code": 503},
    }
    assert "secret-token" not in repr(error_dict)


def test_http_auth_failure_becomes_stable_error_without_token(monkeypatch) -> None:
    def fake_urlopen(request, timeout):  # type: ignore[no-untyped-def]
        raise HTTPError(request.full_url, 401, "bad secret-token", {}, None)

    monkeypatch.setattr("ab_engine.controllers.ab_http_client.urlopen", fake_urlopen)
    client = create_auto_bangumi_http_client(_config())

    try:
        client.create_subscription(_payload())
    except Stage1Error as error:
        error_dict = error.as_dict()
    else:
        raise AssertionError("expected Stage1Error")

    assert error_dict == {
        "error_type": "ab_auth_failed",
        "error_message": "Auto Bangumi 认证失败",
        "failed_step": "create_ab_subscription",
        "details": {"status_code": 401},
    }
    assert "secret-token" not in repr(error_dict)


def test_http_connection_failure_becomes_stable_error_without_reason(
    monkeypatch,
) -> None:
    def fake_urlopen(request, timeout):  # type: ignore[no-untyped-def]
        raise URLError("connection refused secret-token")

    monkeypatch.setattr("ab_engine.controllers.ab_http_client.urlopen", fake_urlopen)
    client = create_auto_bangumi_http_client(_config())

    try:
        client.create_subscription(_payload())
    except Stage1Error as error:
        error_dict = error.as_dict()
    else:
        raise AssertionError("expected Stage1Error")

    assert error_dict == {
        "error_type": "ab_connection_failed",
        "error_message": "Auto Bangumi HTTP 连接失败",
        "failed_step": "create_ab_subscription",
        "details": {"category": "connection"},
    }
    assert "secret-token" not in repr(error_dict)


def test_http_timeout_becomes_stable_error_without_reason(monkeypatch) -> None:
    def fake_urlopen(request, timeout):  # type: ignore[no-untyped-def]
        raise TimeoutError("timed out secret-token")

    monkeypatch.setattr("ab_engine.controllers.ab_http_client.urlopen", fake_urlopen)
    client = create_auto_bangumi_http_client(_config())

    try:
        client.create_subscription(_payload())
    except Stage1Error as error:
        error_dict = error.as_dict()
    else:
        raise AssertionError("expected Stage1Error")

    assert error_dict == {
        "error_type": "ab_timeout",
        "error_message": "Auto Bangumi HTTP 请求超时",
        "failed_step": "create_ab_subscription",
        "details": {"category": "timeout"},
    }
    assert "secret-token" not in repr(error_dict)


def test_injected_transport_timeout_is_normalized() -> None:
    client = create_auto_bangumi_http_client(
        _config(),
        transport=_FailingTransport(TimeoutError("secret-token")),
    )

    try:
        client.create_subscription(_payload())
    except Stage1Error as error:
        error_dict = error.as_dict()
    else:
        raise AssertionError("expected Stage1Error")

    assert error_dict["error_type"] == "ab_timeout"
    assert error_dict["failed_step"] == "create_ab_subscription"
    assert "secret-token" not in repr(error_dict)


def test_injected_stage_error_preserves_failed_step() -> None:
    client = create_auto_bangumi_http_client(
        _config(),
        transport=_FailingTransport(
            Stage1Error(
                "invalid_ab_payload",
                "业务错误",
                "validate_ab_subscription_payload",
            )
        ),
    )

    try:
        client.create_subscription(_payload())
    except Stage1Error as error:
        error_dict = error.as_dict()
    else:
        raise AssertionError("expected Stage1Error")

    assert error_dict["error_type"] == "invalid_ab_payload"
    assert error_dict["failed_step"] == "validate_ab_subscription_payload"


def test_non_json_response_becomes_invalid_ab_response(monkeypatch) -> None:
    def fake_urlopen(request, timeout):  # type: ignore[no-untyped-def]
        return _RawHttpResponse(b"not-json")

    monkeypatch.setattr("ab_engine.controllers.ab_http_client.urlopen", fake_urlopen)
    client = create_auto_bangumi_http_client(_config())

    try:
        client.create_subscription(_payload())
    except Stage1Error as error:
        error_dict = error.as_dict()
    else:
        raise AssertionError("expected Stage1Error")

    assert error_dict == {
        "error_type": "invalid_ab_response",
        "error_message": "Auto Bangumi 响应不是合法 JSON",
        "failed_step": "create_ab_subscription",
        "details": {},
    }


def test_non_object_response_becomes_invalid_ab_response(monkeypatch) -> None:
    def fake_urlopen(request, timeout):  # type: ignore[no-untyped-def]
        return _RawHttpResponse(b'["sub-123"]')

    monkeypatch.setattr("ab_engine.controllers.ab_http_client.urlopen", fake_urlopen)
    client = create_auto_bangumi_http_client(_config())

    try:
        client.create_subscription(_payload())
    except Stage1Error as error:
        error_dict = error.as_dict()
    else:
        raise AssertionError("expected Stage1Error")

    assert error_dict == {
        "error_type": "invalid_ab_response",
        "error_message": "Auto Bangumi 响应必须是 JSON 对象",
        "failed_step": "create_ab_subscription",
        "details": {},
    }


def test_missing_subscription_id_builds_json_serializable_fallback_config() -> None:
    client = create_auto_bangumi_http_client(
        _config(),
        transport=_RecordingTransport({"status": "created"}),
    )

    result = submit_ab_subscription(client, _payload(), fallback_enabled=True)

    assert result["success"] is False
    assert result["error"] == {
        "error_type": "invalid_ab_response",
        "error_message": "Auto Bangumi 响应缺少订阅 ID",
        "failed_step": "create_ab_subscription",
        "details": {"fields": ["id", "subscription_id", "ab_subscription_id"]},
    }
    assert result["fallback_config"]["failure_reason"] == result["error"]
    assert json.loads(json.dumps(result["fallback_config"], ensure_ascii=False)) == result[
        "fallback_config"
    ]
