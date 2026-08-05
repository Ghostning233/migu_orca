from __future__ import annotations

import pytest

from ab_engine.controllers.submit_result import ab_submit_failure, ab_submit_success
from shared.errors import Stage1Error


def test_ab_submit_success_result_has_stable_contract() -> None:
    ab_response = {"id": "sub-123", "status": "created"}

    result = ab_submit_success(" sub-123 ", ab_response)

    assert result == {
        "success": True,
        "ab_subscription_id": "sub-123",
        "ab_response": {"id": "sub-123", "status": "created"},
        "fallback_config": None,
        "error": None,
    }


def test_ab_submit_success_defensively_copies_response() -> None:
    ab_response = {"data": {"id": "sub-123"}}

    result = ab_submit_success("sub-123", ab_response)
    ab_response["data"]["id"] = "changed"

    assert result["ab_response"] == {"data": {"id": "sub-123"}}


def test_ab_submit_success_requires_subscription_id() -> None:
    with pytest.raises(Stage1Error) as error:
        ab_submit_success("  ", {"id": ""})

    assert error.value.as_dict() == {
        "error_type": "invalid_ab_submit_result",
        "error_message": "Auto Bangumi subscription id 不能为空",
        "failed_step": "build_ab_submit_success",
        "details": {},
    }


def test_ab_submit_failure_result_has_structured_error_and_optional_fallback() -> None:
    error = Stage1Error(
        "ab_submit_failed",
        "Auto Bangumi 提交失败",
        "submit_ab_subscription",
        {"status_code": 503},
    )
    fallback_config = {
        "title": "番剧",
        "rss_url": "https://example.invalid/rss.xml",
    }

    result = ab_submit_failure(
        error,
        fallback_config=fallback_config,
        ab_response={"status_code": 503},
    )

    assert result == {
        "success": False,
        "ab_subscription_id": None,
        "ab_response": {"status_code": 503},
        "fallback_config": {
            "title": "番剧",
            "rss_url": "https://example.invalid/rss.xml",
        },
        "error": {
            "error_type": "ab_submit_failed",
            "error_message": "Auto Bangumi 提交失败",
            "failed_step": "submit_ab_subscription",
            "details": {"status_code": 503},
        },
    }


def test_ab_submit_failure_allows_no_fallback_config() -> None:
    result = ab_submit_failure(
        {
            "error_type": "ab_submit_failed",
            "error_message": "Auto Bangumi 提交失败",
            "failed_step": "submit_ab_subscription",
            "details": {},
        }
    )

    assert result["success"] is False
    assert result["fallback_config"] is None
    assert result["error"]["error_type"] == "ab_submit_failed"


def test_ab_submit_failure_defensively_copies_objects() -> None:
    error = {"error_type": "failed", "details": {"reason": "timeout"}}
    fallback_config = {"manual": {"rss_url": "https://example.invalid/rss.xml"}}

    result = ab_submit_failure(error, fallback_config=fallback_config)
    error["details"]["reason"] = "changed"
    fallback_config["manual"]["rss_url"] = "changed"

    assert result["error"] == {
        "error_type": "failed",
        "details": {"reason": "timeout"},
    }
    assert result["fallback_config"] == {
        "manual": {"rss_url": "https://example.invalid/rss.xml"},
    }


def test_ab_submit_failure_defensively_copies_stage_error_details() -> None:
    error = Stage1Error(
        "failed",
        "failed",
        "submit_ab_subscription",
        {"reason": "timeout"},
    )

    result = ab_submit_failure(error)
    error.details["reason"] = "changed"

    assert result["error"]["details"] == {"reason": "timeout"}
