"""Pure submit-outcome classification and submit-state contract (US-225).

This module turns one Auto Bangumi submit result into the operation terminal
state the unified tracking submission service persists, and owns the tracking
statuses a submit may start from.  It is deliberately **pure** — it performs no
I/O and imports no storage repository.  The web submission service loads the
record/Request, runs the AB create seam and hands the normalized
``ab_submit_result`` to :func:`classify_external_submit_result`; the service
persists the resulting TrackingOperation/TrackingRecord transitions and never
lets a route duplicate the classification.

Classification rules (Stage 29 PRD §8.3)
----------------------------------------
- An external result with ``success: true`` is a clear success (``SUCCEEDED``).
- A result that proves the subscription was *not* created is a definite failure
  (``FAILED``) — safe to retry through ``retry``.
- A result where the request *may* have reached Auto Bangumi but the outcome is
  unknown (timeouts, connection resets, 5xx, unparseable responses, an
  unexpected safety-boundary error, or a missing/non-boolean ``success`` flag)
  is ``OUTCOME_UNKNOWN`` — it must never be blindly retried, only recovered.
- Any ``error`` whose ``error_type`` is not known is treated conservatively as
  ``OUTCOME_UNKNOWN`` so an ambiguous upstream never becomes a blindly-retried
  failure.

Only stable non-sensitive codes are consumed/returned here: no AB config, raw
upstream response, URL, magnet, credential or path is accepted or produced.
"""

from __future__ import annotations

from typing import Any

from tracking_engine.models.operation import (
    TRACKING_OPERATION_STATE_FAILED,
    TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
    TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
    TRACKING_OPERATION_STATE_SUCCEEDED,
)
from tracking_engine.models.tracking import (
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_NEEDS_RECONFIRM,
    TRACKING_STATUS_PENDING_SUBMIT,
    TRACKING_STATUS_RECOVERY_REQUIRED,
    TRACKING_STATUS_SUBMIT_FAILED,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
)

#: The tracking statuses a user-initiated submit may start from.  ``SUBMITTING``
#: / ``VERIFYING_EXTERNAL`` / ``RECOVERY_REQUIRED`` and the B-C reserved states
#: are resolved through submit replay or the retry/recover endpoints instead.
SUBMIT_FROM_STATUSES = frozenset(
    {
        TRACKING_STATUS_PENDING_SUBMIT,
        TRACKING_STATUS_NEEDS_RECONFIRM,
        TRACKING_STATUS_SUBMIT_FAILED,
    }
)

#: Error types that prove the external subscription was *not* created (safe to
#: classify as a definite FAILED without a recovery pass).
_DEFINITE_FAILURE_ERROR_TYPES = frozenset(
    {
        # Rejected before/without creating a subscription.
        "config_error",
        "invalid_ab_payload",
        "ab_auth_failed",  # 401/403 — the write was rejected before creation.
        "ab_submit_unsupported",
        "ab_unsupported_version",
        "ab_duplicate_subscription",
        # Provably raised before the write boundary (issue #86): authentication
        # and the exact-version pre-check happen before the create request, so
        # nothing was written and a retry is safe.
        "ab_connection_failed_pre_write",
        "ab_timeout_pre_write",
    }
)

#: Stable, non-sensitive failure categories published by the Web API (issue
#: #86).  They tell the user what to do next — fix the connection, sign in,
#: change the Auto Bangumi version, look at the existing subscription, fix the
#: plan, read the rejection or recover an unknown result — and never carry an
#: upstream response, endpoint, credential or path.
SUBMIT_FAILURE_CATEGORIES = (
    "CONNECTION",
    "AUTHENTICATION",
    "VERSION",
    "DUPLICATE_SUBSCRIPTION",
    "VALIDATION",
    "REJECTED",
    "OUTCOME_UNKNOWN",
)

#: Stable error_type -> published category.  Anything not listed is a definite
#: external rejection (``REJECTED``) when the outcome is FAILED; the ambiguous
#: codes never reach this map because their outcome is OUTCOME_UNKNOWN.
_FAILURE_CATEGORY_BY_ERROR_TYPE = {
    "ab_connection_failed": "CONNECTION",
    "ab_connection_failed_pre_write": "CONNECTION",
    "ab_timeout": "CONNECTION",
    "ab_timeout_pre_write": "CONNECTION",
    "ab_auth_failed": "AUTHENTICATION",
    "ab_unsupported_version": "VERSION",
    "ab_submit_unsupported": "VERSION",
    "ab_duplicate_subscription": "DUPLICATE_SUBSCRIPTION",
    "config_error": "VALIDATION",
    "invalid_ab_payload": "VALIDATION",
}

#: Error types where the request may have reached Auto Bangumi (or the create
#: outcome cannot be proven), so the operation must be OUTCOME_UNKNOWN and only
#: recovery may resolve it — never a blind retry.  (The classifier treats these
#: plus any unknown code as OUTCOME_UNKNOWN.)
_AMBIGUOUS_ERROR_TYPES = frozenset(
    {
        "ab_timeout",
        "ab_connection_failed",
        "invalid_ab_response",
        "invalid_ab_submit_result",
        "unexpected_error",
    }
)

#: Operation terminal state -> the TrackingRecord status that publicly
#: represents the same outcome (used for same-key terminal replays and by the
#: future recover orchestration).
OPERATION_OUTCOME_TRACKING_STATUS: dict[str, str] = {
    TRACKING_OPERATION_STATE_SUCCEEDED: TRACKING_STATUS_ACTIVE,
    TRACKING_OPERATION_STATE_FAILED: TRACKING_STATUS_SUBMIT_FAILED,
    TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN: TRACKING_STATUS_VERIFYING_EXTERNAL,
    TRACKING_OPERATION_STATE_RECOVERY_REQUIRED: TRACKING_STATUS_RECOVERY_REQUIRED,
}

# -- fixed safe audit copy (Stage 29 §9: never upstream raw text) --------------
SUBMIT_STARTED_MESSAGE = "正在提交到 Auto Bangumi"
SUBMIT_ADOPTED_MESSAGE = "已确认最新方案并继续提交"
SUBMIT_SUCCEEDED_MESSAGE = "已成功提交到 Auto Bangumi"
SUBMIT_FAILED_MESSAGE = "Auto Bangumi 提交失败，可安全重试"
SUBMIT_OUTCOME_UNKNOWN_MESSAGE = "Auto Bangumi 结果未知，请先恢复核验"
SUBMIT_PERSIST_FAILED_MESSAGE = "提交结果保存失败，请先恢复核验"


def classify_external_submit_result(result: Any) -> str:
    """Classify one normalized ``ab_submit_result`` into an operation state.

    Returns one of ``SUCCEEDED``/``FAILED``/``OUTCOME_UNKNOWN`` (the
    TrackingOperation terminal-state names), so the caller can persist the
    operation transition and the matching TrackingRecord status without
    re-deriving the upstream ambiguity rules.  A missing/non-dict result, a
    missing/non-boolean ``success`` flag and every unknown error type are
    conservatively ``OUTCOME_UNKNOWN``.
    """
    if not isinstance(result, dict):
        return TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN
    if result.get("success") is True:
        return TRACKING_OPERATION_STATE_SUCCEEDED
    if result.get("success") is not False:
        return TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN

    error = result.get("error")
    error_type = str(error.get("error_type") or "ab_submit_failed")
    if error_type in _DEFINITE_FAILURE_ERROR_TYPES:
        return TRACKING_OPERATION_STATE_FAILED
    if error_type == "ab_submit_failed" and not _http_status_ge_500(error):
        # A <500 rejection provably did not create the subscription; a 5xx may
        # have been processed upstream and stays OUTCOME_UNKNOWN below.
        return TRACKING_OPERATION_STATE_FAILED
    # Every ambiguous/unknown code stays OUTCOME_UNKNOWN so an upstream result
    # that cannot be proven safe-to-retry is never blindly retried.
    return TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN


def external_submit_error_type(result: Any) -> str | None:
    """Return the stable non-sensitive ``error_type`` of a failed result."""
    if not isinstance(result, dict):
        return None
    if result.get("success") is not False:
        return None
    error = result.get("error")
    if not isinstance(error, dict):
        return "ab_submit_failed"
    error_type = error.get("error_type")
    return str(error_type) if isinstance(error_type, str) and error_type.strip() else None


def external_submit_result_id(result: Any) -> str | None:
    """Return the safe opaque external subscription id of a successful result."""
    if not isinstance(result, dict) or result.get("success") is not True:
        return None
    value = result.get("ab_subscription_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def submit_failure_category(
    *,
    outcome: str | None,
    error_type: str | None,
) -> str | None:
    """Return the published failure category for one persisted submit outcome.

    ``outcome`` is the persisted TrackingRecord status.  A successful submit has
    no failure category; a definite ``SUBMIT_FAILED`` maps its stable
    ``error_type`` (an unlisted but definite rejection is ``REJECTED``); a local
    pre-write block is ``VALIDATION``; and every indeterminate result is
    ``OUTCOME_UNKNOWN`` so the client never offers a blind retry.
    """
    if outcome is None or outcome == TRACKING_STATUS_ACTIVE:
        return None
    if outcome == TRACKING_STATUS_SUBMIT_FAILED:
        return _FAILURE_CATEGORY_BY_ERROR_TYPE.get(error_type or "", "REJECTED")
    if outcome == TRACKING_STATUS_NEEDS_RECONFIRM:
        return "VALIDATION"
    return "OUTCOME_UNKNOWN"


def tracking_status_for_operation_state(operation_state: str) -> str:
    """Map a terminal operation state to its public TrackingRecord status.

    Raises ``ValueError`` for a non-terminal state so callers surface a
    programming error instead of silently guessing a status.
    """
    try:
        return OPERATION_OUTCOME_TRACKING_STATUS[operation_state]
    except KeyError as exc:
        raise ValueError(f"no tracking status for operation state: {operation_state}") from exc


def _http_status_ge_500(error: Any) -> bool:
    details = error.get("details") if isinstance(error, dict) else None
    if not isinstance(details, dict):
        return False
    status_code = details.get("status_code")
    return isinstance(status_code, int) and not isinstance(status_code, bool) and status_code >= 500


__all__ = [
    "OPERATION_OUTCOME_TRACKING_STATUS",
    "SUBMIT_ADOPTED_MESSAGE",
    "SUBMIT_FAILED_MESSAGE",
    "SUBMIT_FAILURE_CATEGORIES",
    "SUBMIT_FROM_STATUSES",
    "SUBMIT_OUTCOME_UNKNOWN_MESSAGE",
    "SUBMIT_PERSIST_FAILED_MESSAGE",
    "SUBMIT_STARTED_MESSAGE",
    "SUBMIT_SUCCEEDED_MESSAGE",
    "classify_external_submit_result",
    "external_submit_error_type",
    "external_submit_result_id",
    "submit_failure_category",
    "tracking_status_for_operation_state",
]
