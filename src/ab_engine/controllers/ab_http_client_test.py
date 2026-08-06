from __future__ import annotations

import json
from typing import Any

from ab_engine.controllers.ab_client import AutoBangumiClient
from ab_engine.controllers.ab_config import AutoBangumiConfig
from ab_engine.controllers.ab_http_client import (
    AutoBangumiHttpClient,
    create_auto_bangumi_http_client,
)


class _FakeHttpResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body

    def __enter__(self) -> _FakeHttpResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._body, ensure_ascii=False).encode("utf-8")


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
