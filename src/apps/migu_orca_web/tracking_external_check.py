"""Bounded, read-only Auto Bangumi snapshot reads (issue #183).

Every automatic or user-triggered confirmation of a persistent subscription
performs *only* a read: one bounded ``read_snapshot`` sequence that never
creates, modifies, deletes or resubmits anything. A transient read failure is
retried a small, fixed number of times inside one endpoint-level total budget;
a proven failure (authentication / version / capability) stops immediately
because repeating it cannot change the answer.

The budget and the attempt cap are the product contract: the page must never
wait unboundedly, and the counters stay testable through an injected clock so
no test has to sleep for real.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from shared.errors import Stage1Error
from tracking_engine.controllers.submit import (
    CONFIRM_REASON_AUTHENTICATION,
    CONFIRM_REASON_CAPABILITY,
    CONFIRM_REASON_UNREADABLE,
    CONFIRM_REASON_VERSION,
    confirm_reason_for_error,
)

#: Upper bound of read attempts for one check (including the first one).
CHECK_MAX_ATTEMPTS = 3
#: Total wall-clock budget for one check, retries and backoff included.
CHECK_TOTAL_BUDGET_SECONDS = 20.0
#: Pause between two read attempts; never sleeps past the remaining budget.
CHECK_RETRY_BACKOFF_SECONDS = 0.5

#: Proven reasons that repeating the identical read cannot change.
NON_RETRIABLE_REASONS = frozenset(
    {
        CONFIRM_REASON_AUTHENTICATION,
        CONFIRM_REASON_VERSION,
        CONFIRM_REASON_CAPABILITY,
    }
)


@dataclass(frozen=True)
class CheckPolicy:
    """The bounded-check contract; tests inject a fake clock instead of sleeping."""

    max_attempts: int = CHECK_MAX_ATTEMPTS
    budget_seconds: float = CHECK_TOTAL_BUDGET_SECONDS
    backoff_seconds: float = CHECK_RETRY_BACKOFF_SECONDS
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep


DEFAULT_CHECK_POLICY = CheckPolicy()


@dataclass(frozen=True)
class BoundedSnapshotRead:
    """One bounded read-only snapshot attempt sequence.

    Exactly one of ``snapshot`` / ``error`` explains the result. ``reason`` is
    the proven failure class when no snapshot could be read; ``attempts`` is the
    number of reads actually performed so a caller never guesses.
    """

    snapshot: Any | None = None
    error: Stage1Error | None = None
    reason: str | None = None
    attempts: int = 0
    timed_out: bool = False


def read_snapshot_bounded(
    read_snapshot: Callable[[], Any],
    *,
    policy: CheckPolicy = DEFAULT_CHECK_POLICY,
) -> BoundedSnapshotRead:
    """Read one snapshot with bounded retries and never write anything.

    Retries cover transient read failures only; an authentication, version or
    capability failure is returned immediately so the caller can state the
    proven reason instead of waiting out the budget for an answer that cannot
    change. When the budget or the attempt cap runs out, the last failure is
    returned as-is — it is never converted into a failure claim about the
    external object.
    """
    attempts = 0
    last_error: Stage1Error | None = None
    last_reason = CONFIRM_REASON_UNREADABLE
    started = policy.monotonic()
    deadline = started + policy.budget_seconds
    while attempts < policy.max_attempts:
        attempts += 1
        try:
            return BoundedSnapshotRead(snapshot=read_snapshot(), attempts=attempts)
        except Stage1Error as exc:
            last_error = exc
            last_reason = confirm_reason_for_error(exc.error_type)
            if last_reason in NON_RETRIABLE_REASONS:
                return BoundedSnapshotRead(
                    error=exc, reason=last_reason, attempts=attempts
                )
        except Exception:  # noqa: BLE001 - any unreadable transport stays unresolved
            last_error = None
            last_reason = CONFIRM_REASON_UNREADABLE
        if attempts >= policy.max_attempts:
            break
        if policy.monotonic() + policy.backoff_seconds >= deadline:
            return BoundedSnapshotRead(
                error=last_error, reason=last_reason, attempts=attempts, timed_out=True
            )
        policy.sleep(policy.backoff_seconds)
    return BoundedSnapshotRead(error=last_error, reason=last_reason, attempts=attempts)


__all__ = [
    "CHECK_MAX_ATTEMPTS",
    "CHECK_RETRY_BACKOFF_SECONDS",
    "CHECK_TOTAL_BUDGET_SECONDS",
    "NON_RETRIABLE_REASONS",
    "BoundedSnapshotRead",
    "CheckPolicy",
    "DEFAULT_CHECK_POLICY",
    "read_snapshot_bounded",
]
