from __future__ import annotations

import pytest

from batch_engine.controllers.batch_draft_controller import (
    create_batch_draft,
    update_batch_item_status,
)


def _id_factory(values: list[str]):
    ids = iter(values)
    return lambda: next(ids)


def test_create_batch_draft_splits_multiline_input_into_items() -> None:
    draft = create_batch_draft(
        "萌王S4\n路哥S4\n杖剑谭S2",
        batch_id_factory=_id_factory(["batch-1"]),
        item_id_factory=_id_factory(["item-1", "item-2", "item-3"]),
    )

    assert draft.batch_id == "batch-1"
    assert draft.raw_input == "萌王S4\n路哥S4\n杖剑谭S2"
    assert [item.raw_title for item in draft.items] == [
        "萌王S4",
        "路哥S4",
        "杖剑谭S2",
    ]
    assert [item.status for item in draft.items] == ["RAW", "RAW", "RAW"]


def test_create_batch_draft_ignores_empty_and_whitespace_only_lines() -> None:
    draft = create_batch_draft(
        "\n萌王S4\n   \n\t\n路哥S4\n",
        batch_id_factory=_id_factory(["batch-1"]),
        item_id_factory=_id_factory(["item-1", "item-2"]),
    )

    assert [item.raw_title for item in draft.items] == ["萌王S4", "路哥S4"]


def test_create_batch_draft_preserves_non_empty_line_raw_text() -> None:
    draft = create_batch_draft(
        "  萌王S4  \n路哥S4\t",
        batch_id_factory=_id_factory(["batch-1"]),
        item_id_factory=_id_factory(["item-1", "item-2"]),
    )

    assert [item.raw_title for item in draft.items] == [
        "  萌王S4  ",
        "路哥S4\t",
    ]


def test_create_batch_draft_assigns_unique_item_ids() -> None:
    draft = create_batch_draft("萌王S4\n路哥S4\n杖剑谭S2\n邻家天使S2")

    item_ids = [item.item_id for item in draft.items]
    assert len(item_ids) == 4
    assert len(set(item_ids)) == 4
    assert all(item_id.startswith("item-") for item_id in item_ids)


def test_updating_one_item_status_does_not_affect_other_items() -> None:
    draft = create_batch_draft(
        "萌王S4\n路哥S4",
        batch_id_factory=_id_factory(["batch-1"]),
        item_id_factory=_id_factory(["item-1", "item-2"]),
    )

    updated = update_batch_item_status(draft, "item-1", "DRAFT")

    assert [item.status for item in updated.items] == ["DRAFT", "RAW"]
    assert [item.status for item in draft.items] == ["RAW", "RAW"]
    assert updated.items[1] == draft.items[1]


def test_updating_unknown_item_status_fails_without_mutating_batch() -> None:
    draft = create_batch_draft(
        "萌王S4",
        batch_id_factory=_id_factory(["batch-1"]),
        item_id_factory=_id_factory(["item-1"]),
    )

    with pytest.raises(ValueError, match="unknown item_id"):
        update_batch_item_status(draft, "item-missing", "DRAFT")

    assert draft.items[0].status == "RAW"


def test_updating_item_to_existing_status_still_finds_item() -> None:
    draft = create_batch_draft(
        "萌王S4",
        batch_id_factory=_id_factory(["batch-1"]),
        item_id_factory=_id_factory(["item-1"]),
    )

    updated = update_batch_item_status(draft, "item-1", "RAW")

    assert updated == draft
