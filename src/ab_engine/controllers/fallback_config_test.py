from __future__ import annotations

import json
from typing import Any

from ab_engine.controllers.fallback_config import build_ab_fallback_config
from shared.errors import Stage1Error


def _payload() -> dict[str, Any]:
    return {
        "title": "番剧",
        "rss_url": "https://example.invalid/rss.xml",
        "save_path": "番剧",
        "filter_rule": {"must_contain": "1080p", "must_not_contain": "SP"},
    }


def test_build_ab_fallback_config_contains_payload_and_failure_reason() -> None:
    error = Stage1Error(
        "ab_submit_failed",
        "Auto Bangumi 提交失败",
        "create_ab_subscription",
        {"status_code": 503},
    )

    fallback_config = build_ab_fallback_config(_payload(), error)

    assert fallback_config == {
        "title": "番剧",
        "rss_url": "https://example.invalid/rss.xml",
        "save_path": "番剧",
        "filter_rule": {"must_contain": "1080p", "must_not_contain": "SP"},
        "failure_reason": {
            "error_type": "ab_submit_failed",
            "error_message": "Auto Bangumi 提交失败",
            "failed_step": "create_ab_subscription",
            "details": {"status_code": 503},
        },
    }


def test_build_ab_fallback_config_is_json_serializable() -> None:
    fallback_config = build_ab_fallback_config(
        _payload(),
        {
            "error_type": "ab_submit_failed",
            "error_message": "Auto Bangumi 提交失败",
            "failed_step": "create_ab_subscription",
            "details": {},
        },
    )

    assert json.loads(json.dumps(fallback_config, ensure_ascii=False)) == fallback_config


def test_build_ab_fallback_config_does_not_retain_mutable_objects() -> None:
    payload = _payload()
    error = Stage1Error(
        "ab_submit_failed",
        "Auto Bangumi 提交失败",
        "create_ab_subscription",
        {"attempt": 1},
    )

    fallback_config = build_ab_fallback_config(payload, error)
    payload["filter_rule"]["must_contain"] = "changed"
    error.details["attempt"] = 2

    assert fallback_config["filter_rule"] == {
        "must_contain": "1080p",
        "must_not_contain": "SP",
    }
    assert fallback_config["failure_reason"]["details"] == {"attempt": 1}


def test_build_ab_fallback_config_supports_the_password_mode_legacy_31_body() -> None:
    fallback_config = build_ab_fallback_config(
        {
            "data": {
                "official_title": "番剧 标准标题",
                "rss_link": "https://example.invalid/rss.xml",
                "save_path": "番剧 标准标题",
                "filter": "SP",
            },
            "rss": {"url": "https://example.invalid/rss.xml"},
        },
        Stage1Error("ab_submit_failed", "Auto Bangumi 提交失败", "create_ab_subscription"),
    )

    assert fallback_config == {
        "title": "番剧 标准标题",
        "rss_url": "https://example.invalid/rss.xml",
        "save_path": "番剧 标准标题",
        "filter_rule": {"legacy_31_filter": "SP"},
        "failure_reason": {
            "error_type": "ab_submit_failed",
            "error_message": "Auto Bangumi 提交失败",
            "failed_step": "create_ab_subscription",
            "details": {},
        },
    }
