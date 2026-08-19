from __future__ import annotations

from dataclasses import dataclass, field


BATCH_ITEM_STATUS_RAW = "RAW"


@dataclass(frozen=True)
class BatchDraftItem:
    item_id: str
    raw_title: str
    status: str = BATCH_ITEM_STATUS_RAW


@dataclass(frozen=True)
class BatchDraft:
    batch_id: str
    raw_input: str
    items: list[BatchDraftItem] = field(default_factory=list)


__all__ = [
    "BATCH_ITEM_STATUS_RAW",
    "BatchDraft",
    "BatchDraftItem",
]
