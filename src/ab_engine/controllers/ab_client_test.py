from __future__ import annotations

from typing import Any

from ab_engine.controllers.ab_client import (
    AutoBangumiClient,
    AutoBangumiCollectClient,
    FakeAutoBangumiClient,
    collect_ab_resources,
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


def _legacy_payload() -> dict[str, Any]:
    """The 3.1 ``{data: Bangumi, rss: RSSItem}`` subscription body."""
    return {
        "data": {"official_title": "番剧", "season": 1, "rss_link": "https://example.invalid/rss.xml"},
        "rss": {"name": "番剧", "url": "https://example.invalid/rss.xml", "aggregate": False, "parser": "mikan"},
    }


def _collection_payload() -> dict[str, Any]:
    """The 3.1.18 one-time collection body: a bare ``Bangumi`` model (issue #217)."""
    return {
        "official_title": "番剧",
        "title_raw": "番剧",
        "season": 1,
        "group_name": "Loli",
        "filter": "(?!)",
        "rss_link": "https://example.invalid/rss.xml",
        "save_path": "番剧",
        "poster_link": None,
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


def test_submit_ab_subscription_accepts_the_verified_write_envelope_without_id() -> None:
    """Issue #216: the real 3.1.18 write envelope has no id and no status field.

    The envelope proves the write itself; ownership is established by the exact
    read-back, so a missing id stays a clean success rather than a false failure.
    """
    envelope = {"msg_en": "Subscribe successfully.", "msg_zh": "订阅成功。"}
    result = submit_ab_subscription(FakeAutoBangumiClient(response=envelope), _legacy_payload())

    assert result == {
        "success": True,
        "ab_subscription_id": None,
        "ab_response": envelope,
        "fallback_config": None,
        "error": None,
    }


def test_submit_ab_subscription_refuses_the_envelope_for_a_non_subscription_body() -> None:
    """Issue #216/#217: only the subscription body may own the no-id envelope.

    The bare ``Bangumi`` one-time collection body creates no controlled
    subscription, so the shared subscribe normalizer must keep failing closed
    instead of reporting a clean subscription success for it.
    """
    from ab_engine.controllers.subscription_payload import (
        build_legacy_31_collection_payload,
    )
    from request_engine.controllers.request_controller import (
        accept_request,
        build_pending_request,
    )
    from shared.models import (
        EntryRequest,
        FilterRule,
        MatchedBangumi,
        SubtitleGroupSelection,
    )

    pending = build_pending_request(
        EntryRequest("番剧"),
        MatchedBangumi("番剧", [], "https://example.invalid/bangumi", 1.0),
        [],
        SubtitleGroupSelection("Loli", "https://example.invalid/rss.xml", []),
        FilterRule(must_not_contain="SP"),
        "番剧",
    )
    collection = build_legacy_31_collection_payload(accept_request(pending))
    envelope = {"msg_en": "Collections completed.", "msg_zh": "收集完成。"}

    result = submit_ab_subscription(FakeAutoBangumiClient(response=envelope), collection)

    assert result["success"] is False
    assert result["error"]["error_type"] == "invalid_ab_submit_result"


def test_submit_ab_subscription_fails_closed_on_an_unrecognized_success_body() -> None:
    """The disproved ``{"status": true}`` body is neither an id nor the envelope."""
    result = submit_ab_subscription(
        FakeAutoBangumiClient(response={"status": True}), _payload()
    )

    assert result["success"] is False
    assert result["ab_response"] is None
    assert result["error"]["error_type"] == "invalid_ab_submit_result"


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


# -- issue #217: the one-time collection normalizer ---------------------------


def test_fake_client_matches_the_collection_protocol() -> None:
    client: AutoBangumiCollectClient = FakeAutoBangumiClient()
    assert client.create_collection(_collection_payload()) == {
        "msg_en": "Collections completed.",
        "msg_zh": "收集完成。",
    }


def test_collect_ab_resources_normalizes_a_verified_success_without_an_id() -> None:
    """A collection creates no controlled subscription, so it has no external id.

    The verified 3.1.18 write envelope proves the request itself; nothing is read
    back and no fallback plan is built (ADR-0001).
    """
    envelope = {"msg_en": "Collections completed.", "msg_zh": "收集完成。"}
    payload = _collection_payload()
    client = FakeAutoBangumiClient(collection_response=envelope)

    result = collect_ab_resources(client, payload)

    assert result == {
        "success": True,
        "ab_subscription_id": None,
        "ab_response": envelope,
        "fallback_config": None,
        "error": None,
    }
    assert client.collection_calls == [payload]
    # The subscription seam is never touched by a collection.
    assert client.calls == []


def test_collect_ab_resources_converts_a_controlled_failure() -> None:
    error = Stage1Error(
        "ab_submit_failed",
        "Auto Bangumi HTTP 提交失败",
        "collect_existing_resources",
        {"http_status": 406, "status_code": 406},
    )
    client = FakeAutoBangumiClient(collection_error=error)

    result = collect_ab_resources(client, _collection_payload())

    assert result == {
        "success": False,
        "ab_subscription_id": None,
        "ab_response": None,
        "fallback_config": None,
        "error": {
            "error_type": "ab_submit_failed",
            "error_message": "Auto Bangumi HTTP 提交失败",
            "failed_step": "collect_existing_resources",
            "details": {"http_status": 406, "status_code": 406},
        },
    }
    assert len(client.collection_calls) == 1


def test_collect_ab_resources_never_builds_a_fallback_subscription_plan() -> None:
    """A one-time request must not fall back into creating an RSS subscription."""
    client = FakeAutoBangumiClient(
        collection_error=Stage1Error(
            "ab_timeout", "Auto Bangumi HTTP 请求超时", "collect_existing_resources",
            {"category": "timeout"},
        )
    )

    result = collect_ab_resources(client, _collection_payload())

    assert result["success"] is False
    assert result["fallback_config"] is None
    assert result["error"]["error_type"] == "ab_timeout"


def test_fake_client_deep_copies_collection_payloads_and_responses() -> None:
    payload = _collection_payload()
    response = {"msg_en": "Collections completed.", "msg_zh": "收集完成。"}
    client = FakeAutoBangumiClient(collection_response=response)

    result = collect_ab_resources(client, payload)
    payload["save_path"] = "changed"
    response["msg_zh"] = "changed"

    assert client.collection_calls == [_collection_payload()]
    assert result["ab_response"]["msg_zh"] == "收集完成。"
