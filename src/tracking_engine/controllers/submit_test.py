from __future__ import annotations

"""US-225: pure external-submit result classification tests."""

import pytest

from tracking_engine.controllers.revalidate import REVALIDATABLE_STATUSES
from tracking_engine.controllers.submit import (
    OPERATION_OUTCOME_TRACKING_STATUS,
    SUBMIT_FROM_STATUSES,
    classify_external_submit_result,
    external_submit_error_type,
    external_submit_result_id,
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
    TRACKING_STATUS_RECOVERY_REQUIRED,
    TRACKING_STATUS_SUBMIT_FAILED,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
)


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
