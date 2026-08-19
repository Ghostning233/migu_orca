from __future__ import annotations

from dataclasses import replace
from typing import Callable
from uuid import uuid4

from batch_engine.models import BatchDraft, BatchDraftItem


IdFactory = Callable[[], str]


def create_batch_draft(
    raw_input: str,
    *,
    batch_id_factory: IdFactory | None = None,
    item_id_factory: IdFactory | None = None,
) -> BatchDraft:
    batch_id = _next_id("batch", batch_id_factory)
    items = [
        BatchDraftItem(
            item_id=_next_id("item", item_id_factory),
            raw_title=line,
        )
        for line in raw_input.splitlines()
        if line.strip()
    ]
    return BatchDraft(batch_id=batch_id, raw_input=raw_input, items=items)


def update_batch_item_status(
    batch: BatchDraft,
    item_id: str,
    status: str,
) -> BatchDraft:
    found = False
    updated_items: list[BatchDraftItem] = []
    for item in batch.items:
        if item.item_id == item_id:
            found = True
            updated_items.append(replace(item, status=status))
        else:
            updated_items.append(item)
    if not found:
        raise ValueError("unknown item_id")
    return replace(batch, items=updated_items)


def _next_id(prefix: str, factory: IdFactory | None) -> str:
    if factory is None:
        return f"{prefix}-{uuid4()}"
    value = factory()
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{prefix}_id must be a non-empty string")
    return value.strip()
