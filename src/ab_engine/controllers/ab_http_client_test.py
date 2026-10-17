from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError

import pytest

from ab_engine.controllers.ab_config import AutoBangumiConfig
from ab_engine.controllers.ab_http_client import (
    AutoBangumiHttpClient,
    AutoBangumiWriteResponse,
    UrlopenAutoBangumiHttpTransport,
    create_auto_bangumi_http_client,
    create_auto_bangumi_submit_client,
    create_legacy_3_1_auto_bangumi_client,
    write_failure,
)
from ab_engine.controllers.subscription_payload import build_legacy_31_subscription_payload
from request_engine.controllers.request_controller import accept_request, build_pending_request
from shared.errors import Stage1Error
from shared.models import EntryRequest, FilterRule, MatchedBangumi, SubtitleGroupSelection

#: Shape-exact 3.1.18 write envelope (issue #216).  The provenance-labelled
#: recordings shared with the API contract suite live in
#: ``tests/api_contract/ab_write_envelopes.py``; this unit module keeps its own
#: literal so a ``src`` test never depends on the ``tests`` package.
SOURCE_DERIVED_SUBSCRIBE_ENVELOPE = {
    "msg_en": "Subscribe successfully.",
    "msg_zh": "订阅成功。",
}


class _RecordingTransport:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    def request_json(self, method: str, endpoint: str, headers: Mapping[str, str], payload: Mapping[str, str] | None = None, *, timeout: float) -> dict[str, Any]:
        self.calls.append({"method": method, "endpoint": endpoint, "headers": dict(headers), "payload": payload, "timeout": timeout})
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def write_json(self, method: str, endpoint: str, headers: Mapping[str, str], payload: Any | None = None, *, timeout: float, step: str = "create_ab_subscription") -> AutoBangumiWriteResponse:
        self.calls.append({"method": method, "endpoint": endpoint, "headers": dict(headers), "payload": payload, "timeout": timeout, "step": step})
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


def _stub_exchange(
    monkeypatch: pytest.MonkeyPatch, bodies: list[Any]
) -> list[str]:
    """Serve canned raw responses through the one-exchange seam.

    One entry is either ``bytes`` (an HTTP 200), an ``Exception`` to raise, or a
    ``(status, bytes)`` pair, so a test can prove the exact-status criterion.
    """
    queue = list(bodies)
    calls: list[str] = []

    def _exchange(
        method: str,
        endpoint: str,
        headers: Mapping[str, str],
        body: Any,
        *,
        timeout: float,
        step: str,
        inspect_error_body: bool = False,
        monotonic: Any = None,
    ) -> tuple[int, dict[str, str], bytes]:
        calls.append(f"{method} {endpoint}")
        result = queue.pop(0)
        if isinstance(result, Exception):
            raise result
        if isinstance(result, tuple):
            status, raw = result
            return status, {}, raw
        return 200, {}, result

    monkeypatch.setattr("ab_engine.controllers.ab_http_client._exchange", _exchange)
    return calls


def test_legacy_transport_decodes_a_bare_json_array(monkeypatch: pytest.MonkeyPatch) -> None:
    """Issue #182: verified 3.1.18 list endpoints answer with a bare array."""
    _stub_exchange(monkeypatch, [b'[{"id": 9, "name": "\\u8ba2\\u9605\\u6e90"}]'])

    result = UrlopenAutoBangumiHttpTransport().request_json(
        "GET", "https://auto-bangumi.example/api/v1/rss",
        {"Accept": "application/json"}, timeout=5,
    )

    assert result == [{"id": 9, "name": "订阅源"}]


def test_legacy_transport_rejects_non_json_and_keeps_the_stable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_exchange(monkeypatch, [b"<html>not json</html>"])

    with pytest.raises(Stage1Error) as error:
        UrlopenAutoBangumiHttpTransport().request_json(
            "GET", "https://auto-bangumi.example/api/v1/rss", {}, timeout=5
        )

    assert error.value.error_type == "invalid_ab_response"


def _write(
    monkeypatch: pytest.MonkeyPatch,
    *responses: Any,
    step: str = "create_ab_subscription",
) -> AutoBangumiWriteResponse:
    _stub_exchange(monkeypatch, list(responses))
    return UrlopenAutoBangumiHttpTransport().write_json(
        "POST", "https://auto-bangumi.example/api/v1/rss/subscribe", {}, {}, timeout=5, step=step
    )


def test_write_transport_returns_the_exact_status_with_the_verified_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #216 AC2: the exact status and the contract-checked body travel together."""
    import json

    response = _write(
        monkeypatch, (200, json.dumps(SOURCE_DERIVED_SUBSCRIBE_ENVELOPE).encode("utf-8"))
    )

    assert response == AutoBangumiWriteResponse(200, SOURCE_DERIVED_SUBSCRIBE_ENVELOPE)


def test_write_transport_keeps_a_rejection_status_and_its_bounded_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #216 AC2/AC3: a 406 is returned, not raised, so the caller can classify it."""
    import json

    missing_id = {"msg_en": "Can't find id 999999", "msg_zh": "无法找到 id 999999"}

    response = _write(monkeypatch, (406, json.dumps(missing_id).encode("utf-8")))

    assert response.status_code == 406
    assert response.payload == missing_id


@pytest.mark.parametrize("status", [201, 204, 302])
def test_write_transport_keeps_every_non_200_status_for_its_caller(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    """Issue #216 AC1: only an exact 200 may ever be read as a write success.

    The transport reports the status it observed (201/204/3xx included) so the
    client classifies it as a failure with the existing error types instead of
    ``_raise_for_status`` accepting any 2xx as the success criterion.
    """
    import json

    response = _write(
        monkeypatch, (status, json.dumps(SOURCE_DERIVED_SUBSCRIBE_ENVELOPE).encode("utf-8"))
    )

    assert response.status_code == status
    assert write_failure(response, step="create_ab_subscription").error_type == "ab_submit_failed"


@pytest.mark.parametrize(
    "raw",
    [
        b"[]",
        b"<html>not json</html>",
        # The disproved legacy assumption: no 3.1.18 write endpoint sends this.
        b'{"status": true}',
        b'{"msg_en": "only one"}',
        b'{"msg_en": 1, "msg_zh": "\\u6210\\u529f"}',
        b'{"msg_en": null, "msg_zh": "\\u6210\\u529f"}',
    ],
)
def test_write_transport_rejects_a_200_that_is_not_the_verified_envelope(
    monkeypatch: pytest.MonkeyPatch, raw: bytes
) -> None:
    """Issue #216 AC1: an exact 200 still has to carry two string messages."""
    with pytest.raises(Stage1Error) as error:
        _write(monkeypatch, (200, raw))

    assert error.value.error_type == "invalid_ab_response"


def test_write_failure_classifies_the_exact_status_without_leaking_the_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #216 AC1/AC4: 401/403 authentication, everything else a failed write."""
    import json

    missing_id = {"msg_en": "Can't find id 999999", "msg_zh": "无法找到 id 999999"}

    unauthorized = _write(monkeypatch, (401, b'{"detail": "Unauthorized"}'))
    failure = write_failure(unauthorized, step="create_ab_subscription")
    assert failure.error_type == "ab_auth_failed"
    assert failure.details == {"status_code": 401}

    rejected = _write(monkeypatch, (406, json.dumps(missing_id).encode("utf-8")))
    rejection = write_failure(rejected, step="ab_management")
    assert rejection.error_type == "ab_submit_failed"
    assert rejection.failed_step == "ab_management"
    # Only the bounded, already-whitelisted diagnostics ever leave the adapter.
    assert rejection.details == {
        # Both status keys are deliberate: engine classifiers read
        # ``status_code`` and the published diagnostics DTO reads ``http_status``.
        "status_code": 406,
        "http_status": 406,
        "message_zh": missing_id["msg_zh"],
        "message_en": missing_id["msg_en"],
    }


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
        AutoBangumiWriteResponse(200, SOURCE_DERIVED_SUBSCRIBE_ENVELOPE),
    ])
    client = create_legacy_3_1_auto_bangumi_client(_password_config(), transport=transport)
    assert client.probe()["submit_supported"] is True
    assert client.create_subscription(_legacy_payload()) == SOURCE_DERIVED_SUBSCRIBE_ENVELOPE
    assert all("Authorization" not in call["headers"] for call in transport.calls)
    assert all(call["endpoint"].startswith("http://auto-bangumi.local/") for call in transport.calls)


def test_submit_client_factory_dispatches_password_mode_to_legacy_adapter() -> None:
    transport = _RecordingTransport([
        {"access_token": "secret-cookie"},
        {"version": "3.1.18"},
        AutoBangumiWriteResponse(200, SOURCE_DERIVED_SUBSCRIBE_ENVELOPE),
    ])

    response = create_auto_bangumi_submit_client(
        _password_config(), transport=transport
    ).create_subscription(_legacy_payload())

    assert response == SOURCE_DERIVED_SUBSCRIBE_ENVELOPE
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
    """Issue #101 AC 3/4 + #216 AC3: the real rejection envelope carries the reason.

    A duplicate subscription is refused with a non-200 status whose *real*
    ``msg_zh``/``msg_en`` fields name the conflict; only the sanitized, bounded
    diagnostics keep that text, and the fixed error message, step and any secret
    stay untouched.
    """
    canary = "订阅《番剧》已经存在，请勿重复添加"
    secret = "secret-cookie"
    transport = _RecordingTransport([
        {"access_token": secret},
        {"version": "3.1.18"},
        AutoBangumiWriteResponse(406, {"msg_en": "Subscription already exists.", "msg_zh": canary}),
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
    # The bounded reason and the exact status reach the diagnostics layer only.
    assert failure.value.details == {
        "status_code": 406,
        "http_status": 406,
        "message_zh": canary,
        "message_en": "Subscription already exists.",
    }
