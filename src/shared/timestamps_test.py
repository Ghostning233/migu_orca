from __future__ import annotations

from datetime import UTC, datetime

import pytest

from shared import timestamps

FROZEN = datetime(2026, 10, 11, 7, 30, 0, 123456, tzinfo=UTC)


class _FrozenDatetime(datetime):
    """冻结时钟：``now()`` 恒返回同一时刻，用于证明输出与旧表达式逐字节一致。"""

    @classmethod
    def now(cls, tz: object = None) -> datetime:  # type: ignore[override]
        return FROZEN.astimezone(tz) if tz is not None else FROZEN


@pytest.fixture()
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(timestamps, "datetime", _FrozenDatetime)


def test_utc_now_matches_the_legacy_expression_byte_for_byte(
    frozen_clock: None,
) -> None:
    # 旧实现就是 `datetime.now(UTC).isoformat()`；冻结同一时刻后必须逐字节相同，
    # 否则已有 JSON 里的时间戳排序与比较会漂移（#170）。
    assert timestamps.utc_now() == FROZEN.isoformat()
    assert timestamps.utc_now() == "2026-10-11T07:30:00.123456+00:00"


def test_models_re_expose_the_single_implementation(frozen_clock: None) -> None:
    from tracking_engine.models import operation, tracking

    assert tracking.utc_now is timestamps.utc_now
    assert operation.utc_now is timestamps.utc_now
    assert tracking.utc_now() == timestamps.utc_now()
