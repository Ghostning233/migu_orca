from __future__ import annotations

"""Issue #183: the bounded read-only check contract (no real sleeping)."""

import pytest

from apps.migu_orca_web.tracking_external_check import (
    CHECK_MAX_ATTEMPTS,
    BoundedSnapshotRead,
    CheckPolicy,
    read_snapshot_bounded,
)
from shared.errors import Stage1Error
from tracking_engine.controllers.submit import (
    CONFIRM_REASON_AUTHENTICATION,
    CONFIRM_REASON_CONNECTION,
    CONFIRM_REASON_UNREADABLE,
)


class _Clock:
    """Deterministic clock: sleeping only advances virtual time."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _policy(clock: _Clock, **overrides) -> CheckPolicy:
    values = {
        "max_attempts": 3,
        "budget_seconds": 10.0,
        "backoff_seconds": 1.0,
        "monotonic": clock.monotonic,
        "sleep": clock.sleep,
    }
    values.update(overrides)
    return CheckPolicy(**values)


def test_transient_failure_is_retried_then_succeeds() -> None:
    clock = _Clock()
    calls: list[int] = []

    def read() -> tuple[str]:
        calls.append(len(calls) + 1)
        if len(calls) < 3:
            raise Stage1Error("ab_connection_failed", "连接失败", "check", {"category": "connection"})
        return ("snapshot",)

    result = read_snapshot_bounded(read, policy=_policy(clock))

    assert result == BoundedSnapshotRead(snapshot=("snapshot",), attempts=3)
    assert calls == [1, 2, 3]
    assert clock.slept == [1.0, 1.0]


def test_attempt_cap_stops_the_reads() -> None:
    clock = _Clock()

    def read() -> tuple[str]:
        raise Stage1Error("ab_connection_failed", "连接失败", "check", {"category": "connection"})

    result = read_snapshot_bounded(read, policy=_policy(clock, max_attempts=2))

    assert result.snapshot is None
    assert result.attempts == 2
    assert result.reason == CONFIRM_REASON_CONNECTION
    assert result.error is not None
    assert len(clock.slept) == 1


def test_total_budget_stops_before_the_backoff_would_exceed_it() -> None:
    clock = _Clock()

    def read() -> tuple[str]:
        raise Stage1Error("ab_timeout", "超时", "check", {"category": "timeout"})

    result = read_snapshot_bounded(
        read, policy=_policy(clock, max_attempts=10, budget_seconds=1.5, backoff_seconds=1.0)
    )

    assert result.attempts == 2
    assert result.timed_out is True
    assert clock.slept == [1.0]
    assert clock.now == 1.0


@pytest.mark.parametrize(
    ("error_type", "reason"),
    [
        ("ab_auth_failed", CONFIRM_REASON_AUTHENTICATION),
        ("ab_unsupported_version", "VERSION"),
    ],
)
def test_a_proven_failure_is_not_retried(error_type: str, reason: str) -> None:
    clock = _Clock()
    calls: list[int] = []

    def read() -> tuple[str]:
        calls.append(1)
        raise Stage1Error(error_type, "已证实失败", "check", {})

    result = read_snapshot_bounded(read, policy=_policy(clock))

    assert result.attempts == 1
    assert result.reason == reason
    assert calls == [1]
    assert clock.slept == []


def test_an_unexpected_error_stays_unreadable_and_is_retried_but_bounded() -> None:
    clock = _Clock()

    def read() -> tuple[str]:
        raise RuntimeError("boom")

    result = read_snapshot_bounded(read, policy=_policy(clock, max_attempts=2))

    assert result.snapshot is None
    assert result.error is None
    assert result.attempts == 2
    assert result.reason == CONFIRM_REASON_UNREADABLE


def test_default_policy_keeps_a_small_fixed_bound() -> None:
    assert CHECK_MAX_ATTEMPTS == 3
    assert CheckPolicy().max_attempts == CHECK_MAX_ATTEMPTS
