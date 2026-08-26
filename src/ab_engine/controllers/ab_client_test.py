from __future__ import annotations

from typing import Any

from ab_engine.controllers.ab_client import (
    AutoBangumiClient,
    FakeAutoBangumiClient,
    submit_ab_subscription,
)
from shared.errors import Stage1Error


def _payload() -> dict[str, Any]:
    return {
        "title": "番剧",
        "rss_url": "https://example.invalid/rss.xml",
        "save_path": "番剧",
        "filter_rule": {"must_contain": "1080p"},
    }


def test_fake_client_matches_auto_bangumi_client_protocol() -> None:
    client: AutoBangumiClient = FakeAutoBangumiClient()

    response = client.create_subscription(_payload())

    assert response == {"id": "fake-ab-subscription", "status": "created"}


def test_submit_ab_subscription_converts_success_response_to_submit_result() -> None:
    client = FakeAutoBangumiClient(
        response={"id": "sub-123", "status": "created", "title": "番剧"}
    )

    result = submit_ab_subscription(client, _payload())

    assert result == {
        "success": True,
        "ab_subscription_id": "sub-123",
        "ab_response": {"id": "sub-123", "status": "created", "title": "番剧"},
        "fallback_config": None,
        "error": None,
    }


def test_submit_ab_subscription_accepts_alternate_subscription_id_field() -> None:
    client = FakeAutoBangumiClient(response={"subscription_id": "sub-123"})

    result = submit_ab_subscription(client, _payload())

    assert result["success"] is True
    assert result["ab_subscription_id"] == "sub-123"


def test_submit_ab_subscription_accepts_legacy_status_success_without_id() -> None:
    result = submit_ab_subscription(FakeAutoBangumiClient(response={"status": True}), _payload())

    assert result == {
        "success": True,
        "ab_subscription_id": None,
        "ab_response": {"status": True},
        "fallback_config": None,
        "error": None,
    }


def test_submit_ab_subscription_converts_controlled_failure_to_submit_result() -> None:
    client = FakeAutoBangumiClient(
        error=Stage1Error(
            "ab_submit_failed",
            "Auto Bangumi 提交失败",
            "create_ab_subscription",
            {"status_code": 503},
        )
    )

    result = submit_ab_subscription(client, _payload())

    assert result == {
        "success": False,
        "ab_subscription_id": None,
        "ab_response": None,
        "fallback_config": None,
        "error": {
            "error_type": "ab_submit_failed",
            "error_message": "Auto Bangumi 提交失败",
            "failed_step": "create_ab_subscription",
            "details": {"status_code": 503},
        },
    }


def test_submit_ab_subscription_adds_fallback_config_when_enabled() -> None:
    client = FakeAutoBangumiClient(
        error=Stage1Error(
            "ab_submit_failed",
            "Auto Bangumi 提交失败",
            "create_ab_subscription",
            {"status_code": 503},
        )
    )

    result = submit_ab_subscription(client, _payload(), fallback_enabled=True)

    assert result["success"] is False
    assert result["fallback_config"] == {
        "title": "番剧",
        "rss_url": "https://example.invalid/rss.xml",
        "save_path": "番剧",
        "filter_rule": {"must_contain": "1080p"},
        "failure_reason": {
            "error_type": "ab_submit_failed",
            "error_message": "Auto Bangumi 提交失败",
            "failed_step": "create_ab_subscription",
            "details": {"status_code": 503},
        },
    }


def test_submit_ab_subscription_keeps_fallback_config_disabled_by_default() -> None:
    client = FakeAutoBangumiClient(
        error=Stage1Error(
            "ab_submit_failed",
            "Auto Bangumi 提交失败",
            "create_ab_subscription",
        )
    )

    result = submit_ab_subscription(client, _payload())

    assert result["success"] is False
    assert result["fallback_config"] is None


def test_fake_client_records_payload_calls_without_retaining_mutable_objects() -> None:
    payload = _payload()
    client = FakeAutoBangumiClient(response={"id": "sub-123"})

    submit_ab_subscription(client, payload)
    payload["filter_rule"]["must_contain"] = "changed"

    assert client.calls == [
        {
            "title": "番剧",
            "rss_url": "https://example.invalid/rss.xml",
            "save_path": "番剧",
            "filter_rule": {"must_contain": "1080p"},
        }
    ]


def test_fake_client_returns_response_without_retaining_mutable_objects() -> None:
    response = {"id": "sub-123", "data": {"status": "created"}}
    client = FakeAutoBangumiClient(response=response)

    result = submit_ab_subscription(client, _payload())
    response["data"]["status"] = "changed"

    assert result["ab_response"] == {
        "id": "sub-123",
        "data": {"status": "created"},
    }
