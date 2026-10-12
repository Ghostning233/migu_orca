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

from dataclasses import dataclass
from typing import Any

from tracking_engine.models.operation import (
    TRACKING_OPERATION_STATE_FAILED,
    TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
    TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
    TRACKING_OPERATION_STATE_SUCCEEDED,
)
from tracking_engine.models.tracking import (
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_ADDED_TO_DOWNLOAD,
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
#: Issue #98 AC 8: a failed one-time request is retryable by an explicit user
#: action, but Auto Bangumi 3.1.18 cannot prove a safe retry, so the wording
#: never promises one (ADR-0001).
SUBMIT_FAILED_MESSAGE = "提交失败，可重新提交"
#: A one-time "download existing resources" request Auto Bangumi accepted.
ADDED_TO_DOWNLOAD_MESSAGE = "已加入下载"
#: A write whose body was not a success, but whose exact read-back proved the
#: controlled subscription exists: the record is 追番中 with this fixed, safe
#: note about the current resources (issue #97).
SUBMIT_SUCCEEDED_RESOURCE_WARNING_MESSAGE = "订阅已建立，但 Auto Bangumi 的写响应未确认；已按精确回查确认为追番中，请留当前资源处理情况"
SUBMIT_OUTCOME_UNKNOWN_MESSAGE = "Auto Bangumi 结果待确认，请先恢复核验"
SUBMIT_PERSIST_FAILED_MESSAGE = "提交结果保存失败，请先恢复核验"


def classify_existing_resource_result(result: Any) -> str:
    """Classify one one-time "download existing resources" write (issue #98).

    Auto Bangumi 3.1.18 returns no per-torrent result and no idempotency handle,
    so HTTP 200 is 已加入下载 and every other response, timeout or connection
    failure is the same retryable 提交失败. Nothing is read back: this mode never
    creates a controlled external subscription.
    """
    if isinstance(result, dict) and result.get("success") is True:
        return TRACKING_STATUS_ADDED_TO_DOWNLOAD
    return TRACKING_STATUS_SUBMIT_FAILED


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
    "SUBMIT_SUCCEEDED_RESOURCE_WARNING_MESSAGE",
    "SUBMIT_SUCCEEDED_MESSAGE",
    "CONFIRM_REASON_AMBIGUOUS",
    "CONFIRM_REASON_AUTHENTICATION",
    "CONFIRM_REASON_CAPABILITY",
    "CONFIRM_REASON_CONFIRMED",
    "CONFIRM_REASON_CONNECTION",
    "CONFIRM_REASON_CONNECTION_CHANGED",
    "CONFIRM_REASON_NOT_FOUND",
    "CONFIRM_REASON_UNREADABLE",
    "CONFIRM_REASON_VERSION",
    "ConfirmedSubscriptionOutcome",
    "ExactRssMatch",
    "ADDED_TO_DOWNLOAD_MESSAGE",
    "classify_existing_resource_result",
    "classify_external_submit_result",
    "confirm_reason_for_error",
    "confirm_subscription_outcome",
    "external_submit_error_type",
    "external_submit_result_id",
    "match_subscription_by_exact_rss",
    "submit_failure_category",
    "tracking_status_for_operation_state",
]


#: Safe machine reasons for a confirmation that did not produce a subscription.
#: The UI renders its own fixed Chinese copy from these codes; none of them
#: carries an upstream response, URL, credential or path.
CONFIRM_REASON_CONFIRMED = "CONFIRMED"
CONFIRM_REASON_NOT_FOUND = "NOT_FOUND"
CONFIRM_REASON_AMBIGUOUS = "AMBIGUOUS"
CONFIRM_REASON_UNREADABLE = "UNREADABLE"
CONFIRM_REASON_CONNECTION = "CONNECTION"
CONFIRM_REASON_AUTHENTICATION = "AUTHENTICATION"
CONFIRM_REASON_VERSION = "VERSION"
CONFIRM_REASON_CAPABILITY = "CAPABILITY"
CONFIRM_REASON_CONNECTION_CHANGED = "CONNECTION_CHANGED"

#: Stable error_type -> published confirmation reason. Anything unlisted stays
#: UNREADABLE so an unproven cause is never presented as a specific one.
_CONFIRM_REASON_BY_ERROR_TYPE = {
    "ab_connection_failed": CONFIRM_REASON_CONNECTION,
    "ab_connection_failed_pre_write": CONFIRM_REASON_CONNECTION,
    "ab_timeout": CONFIRM_REASON_CONNECTION,
    "ab_timeout_pre_write": CONFIRM_REASON_CONNECTION,
    "ab_auth_failed": CONFIRM_REASON_AUTHENTICATION,
    "ab_unsupported_version": CONFIRM_REASON_VERSION,
    "ab_submit_unsupported": CONFIRM_REASON_VERSION,
    "ab_management_unsupported": CONFIRM_REASON_CAPABILITY,
    "invalid_ab_response": CONFIRM_REASON_UNREADABLE,
    "ab_management_failed": CONFIRM_REASON_UNREADABLE,
}


def confirm_reason_for_error(error_type: str | None) -> str:
    """Return the proven reason class for one read-only check failure."""
    if not isinstance(error_type, str):
        return CONFIRM_REASON_UNREADABLE
    return _CONFIRM_REASON_BY_ERROR_TYPE.get(error_type, CONFIRM_REASON_UNREADABLE)


@dataclass(frozen=True)
class ConfirmedSubscriptionOutcome:
    """The externally *confirmed* outcome of one persistent-subscription write.

    ``classification`` is an operation terminal state; ``external_id`` is the
    exact controlled subscription the read-back proved, ``resource_warning`` is
    true when the write body disagreed with that proof, and ``reason`` is the
    stable safe reason class of the confirmation (``CONFIRMED`` when proven).
    """

    classification: str
    external_id: str | None
    resource_warning: bool = False
    reason: str = CONFIRM_REASON_CONFIRMED


@dataclass(frozen=True)
class ExactRssMatch:
    """The shared exact-RSS confirmation result for a persistent subscription.

    ``status`` is one of ``CONFIRMED``/``MISSING``/``AMBIGUOUS``/``UNREADABLE``;
    ``subscription`` is the single owning external object only when confirmed.
    """

    status: str
    subscription: Any | None = None
    rss_id: str | None = None


def match_subscription_by_exact_rss(expected_rss_url: Any, snapshot: Any) -> ExactRssMatch:
    """Apply the single confirmation rule for a persistent subscription (#182).

    Only the exact server-private RSS identity of the saved plan proves the
    controlled subscription: the snapshot must expose exactly one RSS object
    with that URL *and* exactly one subscription that owns it. Everything else —
    an unreadable snapshot, a missing object, repeated RSS objects or several
    owners — is *not* proof, so it can never be reported as created nor as a
    definite failure. Both the post-submit read-back and every later read-only
    check call this one rule so their conclusions cannot drift apart.
    """
    if snapshot is None:
        return ExactRssMatch(CONFIRM_REASON_UNREADABLE)
    try:
        _capabilities, subscriptions, rss_items = snapshot
    except (TypeError, ValueError):
        return ExactRssMatch(CONFIRM_REASON_UNREADABLE)
    if not isinstance(subscriptions, (list, tuple)) or not isinstance(rss_items, (list, tuple)):
        return ExactRssMatch(CONFIRM_REASON_UNREADABLE)
    if not isinstance(expected_rss_url, str) or not expected_rss_url.strip():
        return ExactRssMatch(CONFIRM_REASON_UNREADABLE)

    wanted = expected_rss_url.strip()
    matched_rss_ids = {
        str(getattr(item, "external_id", "") or "")
        for item in rss_items
        if str(getattr(item, "url", "") or "").strip() == wanted
    }
    matched_rss_ids.discard("")
    if not matched_rss_ids:
        return ExactRssMatch(CONFIRM_REASON_NOT_FOUND)
    if len(matched_rss_ids) != 1:
        return ExactRssMatch(CONFIRM_REASON_AMBIGUOUS)

    rss_id = next(iter(matched_rss_ids))
    owners = [
        subscription
        for subscription in subscriptions
        if rss_id in {
            str(value) for value in getattr(subscription, "rss_ids", ()) or ()
        }
        or wanted in {
            str(value).strip() for value in getattr(subscription, "rss_urls", ()) or ()
        }
    ]
    if len(owners) != 1:
        return ExactRssMatch(CONFIRM_REASON_AMBIGUOUS, rss_id=rss_id)

    external_id = str(getattr(owners[0], "external_id", "") or "")
    if not external_id:
        return ExactRssMatch(CONFIRM_REASON_AMBIGUOUS, rss_id=rss_id)
    return ExactRssMatch(CONFIRM_REASON_CONFIRMED, subscription=owners[0], rss_id=rss_id)


def confirm_subscription_outcome(
    *,
    ab_result: Any,
    expected_rss_url: str | None,
    snapshot: Any,
) -> ConfirmedSubscriptionOutcome:
    """Confirm one persistent-subscription write by exact read-back (issue #97).

    The Auto Bangumi write body alone never establishes ownership: the caller
    passes a read-only ``snapshot`` of ``(capabilities, subscriptions, rss)`` and
    the exact server-private RSS identity from the saved plan. Only an exact RSS
    URL match proves the controlled subscription; everything else — including a
    legally empty list — stays ``OUTCOME_UNKNOWN`` so a single miss is never
    mistaken for a safely retryable failure (issue #182).
    """
    match = match_subscription_by_exact_rss(expected_rss_url, snapshot)
    if match.status != CONFIRM_REASON_CONFIRMED or match.subscription is None:
        return ConfirmedSubscriptionOutcome(
            TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN, None, reason=match.status
        )
    external_id = str(getattr(match.subscription, "external_id", "") or "") or None
    body_success = isinstance(ab_result, dict) and ab_result.get("success") is True
    return ConfirmedSubscriptionOutcome(
        TRACKING_OPERATION_STATE_SUCCEEDED,
        external_id,
        resource_warning=not body_success,
        reason=CONFIRM_REASON_CONFIRMED,
    )
