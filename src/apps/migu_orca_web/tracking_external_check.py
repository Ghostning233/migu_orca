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

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from shared.errors import Stage1Error
from tracking_engine.controllers.submit import (
    CONFIRM_REASON_AUTHENTICATION,
    CONFIRM_REASON_CAPABILITY,
    CONFIRM_REASON_CONNECTION,
    CONFIRM_REASON_UNREADABLE,
    CONFIRM_REASON_VERSION,
    confirm_reason_for_error,
)

#: Upper bound of read attempts for one check (including the first one).
CHECK_MAX_ATTEMPTS = 3
#: Hard wall-clock budget for one check, retries, backoff and the reads
#: themselves included. It must stay strictly below the browser's default
#: request budget (``frontend/src/api/client.ts`` ``DEFAULT_TIMEOUT_MS`` =
#: 15_000) so a legal, slow check is never cut by the page and reported as an
#: unproven result; ``test_budget_stays_inside_the_browser_request_budget``
#: guards that relation.
CHECK_TOTAL_BUDGET_SECONDS = 12.0
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


#: Process-level single-flight registry: one effective check per tracking record.
_CHECK_REGISTRY_GUARD = threading.Lock()
_ACTIVE_CHECKS: set[str] = set()


@contextmanager
def single_flight_check(tracking_id: str) -> Iterator[None]:
    """Allow at most one effective check per tracking record in this process.

    Concurrent requests for the same record are refused instead of all reading
    Auto Bangumi: the CAS at the end only prevents a duplicate *write*, while
    this guard prevents duplicate *reads* and duplicate read-only work
    (issue #183 review). The page is single-flight on its own; this covers a
    refresh, a second tab or a replay that arrives while the first check runs.
    """
    with _CHECK_REGISTRY_GUARD:
        if tracking_id in _ACTIVE_CHECKS:
            raise Stage1Error(
                "tracking_check_in_progress",
                "该追番记录的只读检查正在进行",
                "tracking_check",
                {"field": "tracking_id"},
            )
        _ACTIVE_CHECKS.add(tracking_id)
    try:
        yield
    finally:
        with _CHECK_REGISTRY_GUARD:
            _ACTIVE_CHECKS.discard(tracking_id)


def attempt_timeout_seconds(policy: CheckPolicy = DEFAULT_CHECK_POLICY) -> float:
    """The per-attempt read timeout derived from the endpoint budget.

    One read may never outlive the whole check: capping each attempt at
    ``budget / max_attempts`` keeps ``max_attempts`` attempts inside the
    endpoint budget instead of letting a single slow read consume it.
    """
    return max(policy.budget_seconds / max(policy.max_attempts, 1), 0.1)


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
    read_snapshot: Callable[..., Any],
    *,
    policy: CheckPolicy = DEFAULT_CHECK_POLICY,
) -> BoundedSnapshotRead:
    """Read one snapshot with bounded retries and never write anything.

    ``read_snapshot`` must accept ``deadline=<absolute monotonic time>`` so an
    attempt can pass the still-remaining time into each of its sub-requests.

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
    # One absolute deadline shared by every attempt *and* by every sub-request
    # inside an attempt: a read may only use the time that is actually left
    # (issue #183 review), instead of each request getting a fresh slice.
    deadline = started + policy.budget_seconds
    while attempts < policy.max_attempts:
        attempts += 1
        try:
            snapshot = read_snapshot(deadline=deadline)
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
        else:
            # A read that only answered *after* the deadline is not evidence
            # inside the budget: it is discarded, never accepted late.
            if policy.monotonic() > deadline:
                return BoundedSnapshotRead(
                    error=last_error,
                    reason=CONFIRM_REASON_CONNECTION,
                    attempts=attempts,
                    timed_out=True,
                )
            return BoundedSnapshotRead(snapshot=snapshot, attempts=attempts)
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
    "attempt_timeout_seconds",
    "single_flight_check",
    "CHECK_RETRY_BACKOFF_SECONDS",
    "CHECK_TOTAL_BUDGET_SECONDS",
    "NON_RETRIABLE_REASONS",
    "BoundedSnapshotRead",
    "CheckPolicy",
    "DEFAULT_CHECK_POLICY",
    "read_snapshot_bounded",
]
