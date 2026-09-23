from __future__ import annotations

"""US-225: pure external-submit result classification tests."""

import pytest

from ab_engine.models.management import ExternalRss, ExternalSubscription
from tracking_engine.controllers.revalidate import REVALIDATABLE_STATUSES
from tracking_engine.controllers.submit import (
    OPERATION_OUTCOME_TRACKING_STATUS,
    SUBMIT_FAILURE_CATEGORIES,
    SUBMIT_FROM_STATUSES,
    classify_external_submit_result,
    confirm_subscription_outcome,
    external_submit_error_type,
    external_submit_result_id,
    submit_failure_category,
    tracking_status_for_operation_state,
)
from tracking_engine.models.operation import (
    TRACKING_OPERATION_STATE_FAILED,
    TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
    TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
    TRACKING_OPERATION_STATE_SUCCEEDED,
)
from tracking_engine.models.tracking import (
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_NEEDS_RECONFIRM,
    TRACKING_STATUS_RECOVERY_REQUIRED,
    TRACKING_STATUS_SUBMIT_FAILED,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
)


@pytest.mark.parametrize(
    ("outcome", "error_type", "expected"),
    [
        (TRACKING_STATUS_ACTIVE, None, None),
        (None, "ab_timeout", None),
        (TRACKING_STATUS_NEEDS_RECONFIRM, None, "VALIDATION"),
        (TRACKING_STATUS_VERIFYING_EXTERNAL, "ab_timeout", "OUTCOME_UNKNOWN"),
        (TRACKING_STATUS_RECOVERY_REQUIRED, None, "OUTCOME_UNKNOWN"),
        (TRACKING_STATUS_SUBMIT_FAILED, "ab_connection_failed_pre_write", "CONNECTION"),
        (TRACKING_STATUS_SUBMIT_FAILED, "ab_timeout_pre_write", "CONNECTION"),
        (TRACKING_STATUS_SUBMIT_FAILED, "ab_auth_failed", "AUTHENTICATION"),
        (TRACKING_STATUS_SUBMIT_FAILED, "ab_unsupported_version", "VERSION"),
        (TRACKING_STATUS_SUBMIT_FAILED, "ab_submit_unsupported", "VERSION"),
        (TRACKING_STATUS_SUBMIT_FAILED, "ab_duplicate_subscription", "DUPLICATE_SUBSCRIPTION"),
        (TRACKING_STATUS_SUBMIT_FAILED, "config_error", "VALIDATION"),
        (TRACKING_STATUS_SUBMIT_FAILED, "invalid_ab_payload", "VALIDATION"),
        (TRACKING_STATUS_SUBMIT_FAILED, "ab_submit_failed", "REJECTED"),
        (TRACKING_STATUS_SUBMIT_FAILED, "a_brand_new_code", "REJECTED"),
        (TRACKING_STATUS_SUBMIT_FAILED, None, "REJECTED"),
    ],
)
def test_submit_failure_category_is_stable(
    outcome: str | None, error_type: str | None, expected: str | None
) -> None:
    """Issue #86: one published, non-sensitive category per failed outcome."""
    category = submit_failure_category(outcome=outcome, error_type=error_type)

    assert category == expected
    if category is not None:
        assert category in SUBMIT_FAILURE_CATEGORIES


def test_submit_from_statuses_equal_revalidatable_statuses() -> None:
    assert SUBMIT_FROM_STATUSES == REVALIDATABLE_STATUSES


def test_success_true_classifies_succeeded() -> None:
    result = {"success": True, "ab_subscription_id": "ab-123", "error": None}
    assert classify_external_submit_result(result) == TRACKING_OPERATION_STATE_SUCCEEDED


def test_success_false_with_definite_error_classifies_failed() -> None:
    result = {
        "success": False,
        "error": {"error_type": "ab_auth_failed", "error_message": "auth"},
    }
    assert classify_external_submit_result(result) == TRACKING_OPERATION_STATE_FAILED


def test_success_false_with_4xx_submit_failed_is_failed() -> None:
    result = {
        "success": False,
        "error": {
            "error_type": "ab_submit_failed",
            "details": {"status_code": 400},
        },
    }
    assert classify_external_submit_result(result) == TRACKING_OPERATION_STATE_FAILED


def test_success_false_with_timeout_is_outcome_unknown() -> None:
    result = {
        "success": False,
        "error": {"error_type": "ab_timeout", "details": {"category": "timeout"}},
    }
    assert classify_external_submit_result(result) == TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN


def test_success_false_with_connection_failed_is_outcome_unknown() -> None:
    result = {
        "success": False,
        "error": {"error_type": "ab_connection_failed"},
    }
    assert classify_external_submit_result(result) == TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN


def test_success_false_with_5xx_submit_failed_is_outcome_unknown() -> None:
    result = {
        "success": False,
        "error": {
            "error_type": "ab_submit_failed",
            "details": {"status_code": 500},
        },
    }
    assert classify_external_submit_result(result) == TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN


def test_success_false_with_unexpected_error_is_outcome_unknown() -> None:
    result = {
        "success": False,
        "error": {"error_type": "unexpected_error"},
    }
    assert classify_external_submit_result(result) == TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN


def test_success_false_with_unknown_error_type_is_outcome_unknown() -> None:
    # An unclassified upstream code must never become a blindly-retried FAILED.
    result = {"success": False, "error": {"error_type": "mystery_upstream_code"}}
    assert classify_external_submit_result(result) == TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN


def test_missing_success_flag_is_outcome_unknown() -> None:
    assert classify_external_submit_result({}) == TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN
    assert classify_external_submit_result(None) == TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN
    assert classify_external_submit_result("raw") == TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN
    assert (
        classify_external_submit_result({"success": None})
        == TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN
    )


def test_error_type_extraction_is_stable() -> None:
    assert external_submit_error_type({"success": False, "error": {"error_type": "ab_timeout"}}) == "ab_timeout"
    assert external_submit_error_type({"success": False, "error": None}) == "ab_submit_failed"
    assert external_submit_error_type({"success": True}) is None
    assert external_submit_error_type(None) is None


def test_result_id_extraction() -> None:
    assert external_submit_result_id({"success": True, "ab_subscription_id": "ab-1"}) == "ab-1"
    assert external_submit_result_id({"success": True, "ab_subscription_id": ""}) is None
    assert external_submit_result_id({"success": False}) is None
    assert external_submit_result_id(None) is None


def test_operation_state_to_tracking_status_mapping() -> None:
    assert OPERATION_OUTCOME_TRACKING_STATUS == {
        TRACKING_OPERATION_STATE_SUCCEEDED: TRACKING_STATUS_ACTIVE,
        TRACKING_OPERATION_STATE_FAILED: TRACKING_STATUS_SUBMIT_FAILED,
        TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN: TRACKING_STATUS_VERIFYING_EXTERNAL,
        TRACKING_OPERATION_STATE_RECOVERY_REQUIRED: TRACKING_STATUS_RECOVERY_REQUIRED,
    }
    assert tracking_status_for_operation_state(TRACKING_OPERATION_STATE_SUCCEEDED) == TRACKING_STATUS_ACTIVE


def test_unknown_operation_state_raises() -> None:
    with pytest.raises(ValueError):
        tracking_status_for_operation_state("PREPARED")
    with pytest.raises(ValueError):
        tracking_status_for_operation_state("not-a-state")

# -- issue #97: confirm a persistent-subscription write by exact read-back -----

RSS_URL = "https://mikanani.me/RSS/Bangumi?bangumiId=1234&subgroupid=567"


def _subscription(external_id: str = "sub-1", rss_ids: tuple[str, ...] = ("rss-1",)) -> ExternalSubscription:
    return ExternalSubscription(external_id, "葬送的芙莉莲", 1, "喵萌奶茶屋", rss_ids=rss_ids)


def _snapshot(rss_items, subscriptions):
    return (None, list(subscriptions), list(rss_items))


def test_confirm_read_back_proves_the_exact_controlled_subscription() -> None:
    outcome = confirm_subscription_outcome(
        ab_result={"success": True},
        expected_rss_url=RSS_URL,
        snapshot=_snapshot([ExternalRss("rss-1", "芙莉莲", RSS_URL)], [_subscription()]),
    )

    assert outcome.classification == TRACKING_OPERATION_STATE_SUCCEEDED
    assert outcome.external_id == "sub-1"
    assert outcome.resource_warning is False


def test_confirm_read_back_overrides_a_non_success_write_with_a_safe_warning() -> None:
    """Issue #97 AC 4: a non-success body plus exact read-back is still 追番中."""
    outcome = confirm_subscription_outcome(
        ab_result={"success": False, "error_type": "ab_http_error"},
        expected_rss_url=RSS_URL,
        snapshot=_snapshot([ExternalRss("rss-1", "芙莉莲", RSS_URL)], [_subscription()]),
    )

    assert outcome.classification == TRACKING_OPERATION_STATE_SUCCEEDED
    assert outcome.external_id == "sub-1"
    assert outcome.resource_warning is True


def test_confirm_read_back_without_the_expected_rss_is_a_definite_failure() -> None:
    outcome = confirm_subscription_outcome(
        ab_result={"success": False},
        expected_rss_url=RSS_URL,
        snapshot=_snapshot([ExternalRss("rss-1", "别的", "https://mikanani.me/RSS/Other")], [_subscription()]),
    )

    assert outcome.classification == TRACKING_OPERATION_STATE_FAILED
    assert outcome.external_id is None


@pytest.mark.parametrize(
    ("snapshot", "reason"),
    [
        (None, "回查不可读"),
        (
            _snapshot([ExternalRss("rss-1", "a", RSS_URL), ExternalRss("rss-2", "b", RSS_URL)], [_subscription()]),
            "多个同 URL 的 RSS",
        ),
        (
            _snapshot(
                [ExternalRss("rss-1", "a", RSS_URL)],
                [_subscription("sub-1"), _subscription("sub-2")],
            ),
            "多个归属订阅",
        ),
        (("not", "a", "snapshot"), "结构非法"),
    ],
)
def test_confirm_read_back_stays_unresolved_when_it_cannot_prove(
    snapshot, reason: str  # noqa: ARG001 - the reason documents each case
) -> None:
    outcome = confirm_subscription_outcome(
        ab_result={"success": True},
        expected_rss_url=RSS_URL,
        snapshot=snapshot,
    )

    assert outcome.classification == TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN
    assert outcome.external_id is None


@pytest.mark.parametrize("expected", [None, "", "   "])
def test_confirm_without_an_exact_identity_is_unresolved(expected) -> None:
    outcome = confirm_subscription_outcome(
        ab_result={"success": True},
        expected_rss_url=expected,
        snapshot=_snapshot([ExternalRss("rss-1", "a", RSS_URL)], [_subscription()]),
    )

    assert outcome.classification == TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN


def test_confirm_matches_the_subscription_by_exact_rss_url_too() -> None:
    owner = ExternalSubscription("sub-9", "葬送的芙莉莲", 1, "喵萌奶茶屋", rss_urls=(RSS_URL,))
    outcome = confirm_subscription_outcome(
        ab_result={"success": True},
        expected_rss_url=RSS_URL,
        snapshot=_snapshot([ExternalRss("rss-1", "a", RSS_URL)], [owner]),
    )

    assert outcome.classification == TRACKING_OPERATION_STATE_SUCCEEDED
    assert outcome.external_id == "sub-9"
