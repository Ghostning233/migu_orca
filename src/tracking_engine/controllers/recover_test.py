from __future__ import annotations

"""US-226: pure AUTO recovery classification tests."""

import pytest

from tracking_engine.controllers.recover import (
    RECOVERABLE_STATUSES,
    RECOVERY_ACTION_AUTO,
    RECOVERY_ACTION_MARK_FAILED,
    RECOVERY_ACTION_MARK_SUCCEEDED,
    RECOVERY_ACTIONS,
    AutoRecoveryDecision,
    RecoveryEvidence,
    classify_auto_recovery,
    recovery_outcome_for_manual,
)
from tracking_engine.models.operation import (
    TRACKING_OPERATION_STATE_FAILED,
    TRACKING_OPERATION_STATE_IN_PROGRESS,
    TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
    TRACKING_OPERATION_STATE_PREPARED,
    TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
    TRACKING_OPERATION_STATE_SUCCEEDED,
)
from tracking_engine.models.tracking import (
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_RECOVERY_REQUIRED,
    TRACKING_STATUS_SUBMIT_FAILED,
    TRACKING_STATUS_UNKNOWN,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
)


def test_recoverable_statuses_cover_unknown_outcome_and_recovery() -> None:
    assert {
        TRACKING_STATUS_VERIFYING_EXTERNAL,
        TRACKING_STATUS_RECOVERY_REQUIRED,
        TRACKING_STATUS_UNKNOWN,
    } == RECOVERABLE_STATUSES


def test_recovery_actions_fixed_enum() -> None:
    assert {
        RECOVERY_ACTION_AUTO,
        RECOVERY_ACTION_MARK_SUCCEEDED,
        RECOVERY_ACTION_MARK_FAILED,
    } == RECOVERY_ACTIONS


def _ab_success() -> dict:
    return {"success": True, "ab_subscription_id": "ab-1", "error": None}


def _ab_definite_failure() -> dict:
    return {
        "success": False,
        "error": {
            "error_type": "ab_auth_failed",
            "error_message": "Auto Bangumi 认证失败",
            "details": {"status_code": 401},
        },
    }


def _ab_unknown() -> dict:
    return {
        "success": False,
        "error": {
            "error_type": "ab_timeout",
            "error_message": "Auto Bangumi HTTP 请求超时",
            "details": {"category": "timeout"},
        },
    }


# -- terminal operation state resolves ----------------------------------------


def test_terminal_succeeded_operation_resolves_active() -> None:
    decision = classify_auto_recovery(
        RecoveryEvidence(
            operation_state=TRACKING_OPERATION_STATE_SUCCEEDED,
            ab_result=None,
        )
    )
    assert decision == AutoRecoveryDecision(
        outcome=TRACKING_STATUS_ACTIVE,
        resolved=True,
    )


def test_terminal_failed_operation_resolves_submit_failed() -> None:
    decision = classify_auto_recovery(
        RecoveryEvidence(
            operation_state=TRACKING_OPERATION_STATE_FAILED,
            ab_result=None,
        )
    )
    assert decision == AutoRecoveryDecision(
        outcome=TRACKING_STATUS_SUBMIT_FAILED,
        resolved=True,
    )


def test_terminal_outcome_unknown_falls_back_to_ab_result() -> None:
    # A terminal OUTCOME_UNKNOWN operation with a persisted success result
    # resolves to ACTIVE from the local AB evidence.
    decision = classify_auto_recovery(
        RecoveryEvidence(
            operation_state=TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
            ab_result=_ab_success(),
        )
    )
    assert decision.outcome == TRACKING_STATUS_ACTIVE
    assert decision.resolved is True


def test_terminal_outcome_unknown_with_ambiguous_ab_needs_manual() -> None:
    decision = classify_auto_recovery(
        RecoveryEvidence(
            operation_state=TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
            ab_result=_ab_unknown(),
        )
    )
    assert decision == AutoRecoveryDecision(
        outcome=TRACKING_STATUS_RECOVERY_REQUIRED,
        resolved=False,
    )


def test_terminal_recovery_required_with_no_ab_needs_manual() -> None:
    decision = classify_auto_recovery(
        RecoveryEvidence(
            operation_state=TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
            ab_result=None,
        )
    )
    assert decision == AutoRecoveryDecision(
        outcome=TRACKING_STATUS_RECOVERY_REQUIRED,
        resolved=False,
    )


# -- AB result evidence resolves ----------------------------------------------


def test_ab_success_resolves_active() -> None:
    decision = classify_auto_recovery(
        RecoveryEvidence(operation_state=None, ab_result=_ab_success())
    )
    assert decision.outcome == TRACKING_STATUS_ACTIVE
    assert decision.resolved is True


def test_ab_definite_failure_resolves_submit_failed() -> None:
    decision = classify_auto_recovery(
        RecoveryEvidence(operation_state=None, ab_result=_ab_definite_failure())
    )
    assert decision.outcome == TRACKING_STATUS_SUBMIT_FAILED
    assert decision.resolved is True


def test_ab_ambiguous_failure_needs_manual() -> None:
    decision = classify_auto_recovery(
        RecoveryEvidence(operation_state=None, ab_result=_ab_unknown())
    )
    assert decision == AutoRecoveryDecision(
        outcome=TRACKING_STATUS_RECOVERY_REQUIRED,
        resolved=False,
    )


def test_non_dict_ab_result_needs_manual() -> None:
    for bad in ("raw", 123, [], None):
        decision = classify_auto_recovery(
            RecoveryEvidence(operation_state=None, ab_result=bad)  # type: ignore[arg-type]
        )
        assert decision == AutoRecoveryDecision(
            outcome=TRACKING_STATUS_RECOVERY_REQUIRED,
            resolved=False,
        )


# -- in-flight / prepared / missing operation --------------------------------


def test_in_progress_operation_with_success_ab_resolves_active() -> None:
    decision = classify_auto_recovery(
        RecoveryEvidence(
            operation_state=TRACKING_OPERATION_STATE_IN_PROGRESS,
            ab_result=_ab_success(),
        )
    )
    assert decision.outcome == TRACKING_STATUS_ACTIVE
    assert decision.resolved is True


def test_prepared_operation_with_definite_failure_resolves_submit_failed() -> None:
    # A PREPARED operation proves the external was never called; the persisted
    # failure still resolves to a safe-to-retry SUBMIT_FAILED.
    decision = classify_auto_recovery(
        RecoveryEvidence(
            operation_state=TRACKING_OPERATION_STATE_PREPARED,
            ab_result=_ab_definite_failure(),
        )
    )
    assert decision.outcome == TRACKING_STATUS_SUBMIT_FAILED
    assert decision.resolved is True


def test_no_operation_no_ab_needs_manual() -> None:
    decision = classify_auto_recovery(RecoveryEvidence())
    assert decision == AutoRecoveryDecision(
        outcome=TRACKING_STATUS_RECOVERY_REQUIRED,
        resolved=False,
    )


# -- manual outcomes ----------------------------------------------------------


def test_manual_outcome_mapping() -> None:
    assert (
        recovery_outcome_for_manual(RECOVERY_ACTION_MARK_SUCCEEDED)
        == TRACKING_STATUS_ACTIVE
    )
    assert (
        recovery_outcome_for_manual(RECOVERY_ACTION_MARK_FAILED)
        == TRACKING_STATUS_SUBMIT_FAILED
    )


def test_manual_outcome_rejects_auto_and_unknown() -> None:
    with pytest.raises(ValueError):
        recovery_outcome_for_manual(RECOVERY_ACTION_AUTO)
    with pytest.raises(ValueError):
        recovery_outcome_for_manual("VERIFY_EXTERNAL")
