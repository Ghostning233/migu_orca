"""共享的 UTC 时间戳（#170）。

`tracking_engine` 与 `storage_engine` 都需要同一个 UTC RFC3339 时间戳，此前
`tracking_engine/models/tracking.py` 与 `operation.py` 各有一份逐字相同的实现。
这里只保留一份；两个模型模块继续对外暴露同名符号（facade），调用方导入路径不变。

输出必须与旧实现**逐字节相同**：`datetime.now(UTC).isoformat()`。已有 JSON 里的
时间戳按原格式写入，格式变化会让排序与比较漂移。
"""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> str:
    """当前 UTC RFC3339 时间戳（微秒精度、``+00:00`` 偏移），与旧实现逐字节一致。"""
    return datetime.now(UTC).isoformat()
