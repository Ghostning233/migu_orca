from __future__ import annotations

import json
from typing import Any, Mapping
from urllib.error import HTTPError

from ab_engine.controllers.ab_client import AutoBangumiClient
from ab_engine.controllers.ab_config import AutoBangumiConfig
from ab_engine.controllers.ab_http_client import (
    AutoBangumiHttpClient,
    create_auto_bangumi_http_client,
)
from shared.errors import Stage1Error


class _FakeHttpResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body

    def __enter__(self) -> _FakeHttpResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._body, ensure_ascii=False).encode("utf-8")


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


def _config() -> AutoBangumiConfig:
    return AutoBangumiConfig(
        endpoint="http://auto-bangumi.local/api/subscribe",
        token="secret-token",
        fallback_enabled=False,
    )


def _payload() -> dict[str, Any]:
    return {
        "title": "番剧",
        "rss_url": "https://example.invalid/rss.xml",
        "save_path": "番剧",
        "filter_rule": {"must_contain": "1080p"},
    }


def test_http_client_constructor_returns_protocol_compatible_client() -> None:
    client: AutoBangumiClient = create_auto_bangumi_http_client(_config())

    assert isinstance(client, AutoBangumiHttpClient)


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
    assert request.full_url == "http://auto-bangumi.local/api/subscribe"
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
            "endpoint": "http://auto-bangumi.local/api/subscribe",
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
