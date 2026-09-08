"""Pure recovery classification and recover-state contract (US-226).

Stage 29 PRD §11.8: a tracking record whose external outcome is *unknown*
(``VERIFYING_EXTERNAL``) or whose local result could not be made durable
(``RECOVERY_REQUIRED``) must never be blindly retried — only an explicit
recovery may resolve it.  This module owns the **pure** decision logic for that
recovery:

- the fixed action codes (``AUTO``/``MARK_SUCCEEDED``/``MARK_FAILED``) and the
  record statuses a recover may start from;
- :func:`classify_auto_recovery`, which turns the **local** evidence the web
  service gathered (the current operation's terminal state plus the Request's
  persisted safe AB result) into a concrete recovery outcome.

The module is deliberately **pure** — it performs no I/O and imports no storage
repository.  ``AUTO`` recovery never contacts Auto Bangumi (D29-12); the web
recovery service loads the local evidence, hands it to
:func:`classify_auto_recovery` and persists the resulting TrackingRecord /
TrackingOperation transitions.  Manual actions are validated/guarded by the
service (``confirm=true`` + USER audit); the classifier never accepts an
external id/URL/raw result (MARK_SUCCEEDED never takes external evidence).

Only stable non-sensitive codes are consumed/returned here: no AB config, raw
upstream response, URL, magnet, credential or path is accepted or produced.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tracking_engine.controllers.submit import (
    OPERATION_OUTCOME_TRACKING_STATUS,
    classify_external_submit_result,
)
from tracking_engine.models.operation import (
    TRACKING_OPERATION_STATE_FAILED,
    TRACKING_OPERATION_STATE_SUCCEEDED,
    TRACKING_OPERATION_TERMINAL_STATES,
)
from tracking_engine.models.tracking import (
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_RECOVERY_REQUIRED,
    TRACKING_STATUS_SUBMIT_FAILED,
    TRACKING_STATUS_UNKNOWN,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
)

# -- recovery actions (Stage 29 PRD §11.8) ------------------------------------
RECOVERY_ACTION_AUTO = "AUTO"
RECOVERY_ACTION_MARK_SUCCEEDED = "MARK_SUCCEEDED"
RECOVERY_ACTION_MARK_FAILED = "MARK_FAILED"
RECOVERY_ACTION_VERIFY_EXTERNAL = "VERIFY_EXTERNAL"
RECOVERY_ACTIONS = frozenset(
    {
        RECOVERY_ACTION_AUTO,
        RECOVERY_ACTION_MARK_SUCCEEDED,
        RECOVERY_ACTION_MARK_FAILED,
        RECOVERY_ACTION_VERIFY_EXTERNAL,
    }
)

#: The tracking statuses a user may recover.  Every other state resolves
#: through submit/retry or is already stable (Stage 29 PRD §8.3/§11.8).
RECOVERABLE_STATUSES = frozenset(
    {
        TRACKING_STATUS_VERIFYING_EXTERNAL,
        TRACKING_STATUS_RECOVERY_REQUIRED,
        TRACKING_STATUS_UNKNOWN,
    }
)

#: The terminal outcomes a recovery may produce.
RECOVERY_OUTCOME_ACTIVE = TRACKING_STATUS_ACTIVE
RECOVERY_OUTCOME_SUBMIT_FAILED = TRACKING_STATUS_SUBMIT_FAILED
RECOVERY_OUTCOME_RECOVERY_REQUIRED = TRACKING_STATUS_RECOVERY_REQUIRED
RECOVERY_OUTCOMES = frozenset(
    {
        RECOVERY_OUTCOME_ACTIVE,
        RECOVERY_OUTCOME_SUBMIT_FAILED,
        RECOVERY_OUTCOME_RECOVERY_REQUIRED,
    }
)

# -- fixed safe audit copy (Stage 29 §9: never upstream raw text) -------------
RECOVERY_AUTO_SUCCEEDED_MESSAGE = "已根据本地提交结果自动恢复为追番成功"
RECOVERY_AUTO_FAILED_MESSAGE = "已根据本地提交结果确认提交失败，可安全重试"
RECOVERY_NEEDS_MANUAL_MESSAGE = "未找到可自动核验的本地证据，需要人工确认 Auto Bangumi 状态"
RECOVERY_MANUAL_SUCCEEDED_MESSAGE = "人工核验确认 Auto Bangumi 已创建追番，标记为成功"
RECOVERY_MANUAL_FAILED_MESSAGE = "人工核验确认 Auto Bangumi 未创建追番，标记为可重试失败"


@dataclass(frozen=True)
class RecoveryEvidence:
    """Everything the pure AUTO classifier needs about local recovery evidence.

    ``operation_state`` is the current operation's terminal state, or ``None``
    when there is no operation / the operation is still ``IN_PROGRESS`` /
    ``PREPARED`` / cannot be read.  ``ab_result`` is the sanitized safe AB
    result persisted on the local Request, or ``None`` when there is none.
    """

    operation_state: str | None = None
    ab_result: dict[str, Any] | None = None


@dataclass(frozen=True)
class AutoRecoveryDecision:
    """The pure AUTO recovery verdict.

    ``outcome`` is one of ``ACTIVE``/``SUBMIT_FAILED``/``RECOVERY_REQUIRED``.
    ``resolved`` is True only when AUTO produced a *clear* terminal outcome from
    local evidence (a definitive success or failure).  When ``resolved`` is
    False the record must stay/enter ``RECOVERY_REQUIRED`` for manual action.
    """

    outcome: str
    resolved: bool


def classify_auto_recovery(evidence: RecoveryEvidence) -> AutoRecoveryDecision:
    """Classify the local evidence into an AUTO recovery outcome.

    Order of evidence (Stage 29 PRD §11.8 AUTO = pure local):

    1. a terminal operation whose state *proves* success (``SUCCEEDED``) or a
       clear failure (``FAILED``) resolves immediately — never blindly retried;
    2. otherwise the Request's persisted safe AB result decides through the same
       classifier the submit path uses (``classify_external_submit_result``):
       a clear success/failure resolves, anything ambiguous falls to manual;
    3. no operation / no readable evidence → ``RECOVERY_REQUIRED`` (unresolved).

    ``AUTO`` never contacts an external system and never accepts an external
    id/URL/raw result.
    """
    if evidence.operation_state in TRACKING_OPERATION_TERMINAL_STATES:
        if evidence.operation_state == TRACKING_OPERATION_STATE_SUCCEEDED:
            return AutoRecoveryDecision(
                outcome=RECOVERY_OUTCOME_ACTIVE,
                resolved=True,
            )
        if evidence.operation_state == TRACKING_OPERATION_STATE_FAILED:
            return AutoRecoveryDecision(
                outcome=RECOVERY_OUTCOME_SUBMIT_FAILED,
                resolved=True,
            )
        # OUTCOME_UNKNOWN / RECOVERY_REQUIRED terminal operations still defer to
        # the persisted local AB result below.

    if evidence.ab_result is not None:
        operation_state = classify_external_submit_result(evidence.ab_result)
        resolved = operation_state in {
            TRACKING_OPERATION_STATE_SUCCEEDED,
            TRACKING_OPERATION_STATE_FAILED,
        }
        if resolved:
            outcome = OPERATION_OUTCOME_TRACKING_STATUS[operation_state]
            return AutoRecoveryDecision(outcome=outcome, resolved=True)
        # OUTCOME_UNKNOWN AB result is not clear enough to auto-resolve.
        return AutoRecoveryDecision(
            outcome=RECOVERY_OUTCOME_RECOVERY_REQUIRED,
            resolved=False,
        )

    return AutoRecoveryDecision(
        outcome=RECOVERY_OUTCOME_RECOVERY_REQUIRED,
        resolved=False,
    )


def recovery_outcome_for_manual(action: str) -> str:
    """Return the record outcome a manual action produces.

    ``MARK_SUCCEEDED`` -> ``ACTIVE``; ``MARK_FAILED`` -> ``SUBMIT_FAILED``.
    Raises ``ValueError`` for AUTO or an unknown action so the service surfaces
    a programming error instead of silently guessing an outcome.
    """
    if action == RECOVERY_ACTION_MARK_SUCCEEDED:
        return RECOVERY_OUTCOME_ACTIVE
    if action == RECOVERY_ACTION_MARK_FAILED:
        return RECOVERY_OUTCOME_SUBMIT_FAILED
    raise ValueError(f"manual recovery action expected, got: {action}")


__all__ = [
    "AutoRecoveryDecision",
    "RECOVERY_ACTIONS",
    "RECOVERY_ACTION_AUTO",
    "RECOVERY_ACTION_MARK_FAILED",
    "RECOVERY_ACTION_VERIFY_EXTERNAL",
    "RECOVERY_ACTION_MARK_SUCCEEDED",
    "RECOVERY_AUTO_FAILED_MESSAGE",
    "RECOVERY_AUTO_SUCCEEDED_MESSAGE",
    "RECOVERY_MANUAL_FAILED_MESSAGE",
    "RECOVERY_MANUAL_SUCCEEDED_MESSAGE",
    "RECOVERY_NEEDS_MANUAL_MESSAGE",
    "RECOVERY_OUTCOMES",
    "RECOVERY_OUTCOME_ACTIVE",
    "RECOVERY_OUTCOME_RECOVERY_REQUIRED",
    "RECOVERY_OUTCOME_SUBMIT_FAILED",
    "RECOVERABLE_STATUSES",
    "RecoveryEvidence",
    "classify_auto_recovery",
    "recovery_outcome_for_manual",
]
