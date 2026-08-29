from __future__ import annotations

"""US-194: server-authoritative draft store unit tests.

The DraftStore is the bounded, expiring, one-time-save store that holds unsaved
preview requests. These tests pin its lifecycle (issue/get/consume/update),
capacity eviction, TTL expiry, replay protection and the reason codes routes
map to stable 409 ``draft_*`` errors.
"""

from typing import Any

from apps.migu_orca_web.drafts import (
    REASON_EVICTED,
    REASON_EXPIRED,
    REASON_OK,
    REASON_REPLAYED,
    REASON_UNKNOWN,
    DraftStore,
)


def _request(request_id: str = "req-1") -> dict[str, Any]:
    return {
        "request_id": request_id,
        "status": "PENDING_CONFIRM",
        "input": {"raw_title": "示例"},
    }


def test_issue_returns_opaque_id_and_get_reads_it_back() -> None:
    store = DraftStore()
    draft_id = store.issue(_request("req-a"))

    # The id is opaque (URL-safe token, no request data).
    assert isinstance(draft_id, str)
    assert len(draft_id) >= 16
    assert draft_id.isalnum() or "-" in draft_id or "_" in draft_id

    request, reason = store.get(draft_id)
    assert reason == REASON_OK
    assert request is not None
    assert request["request_id"] == "req-a"


def test_get_does_not_consume() -> None:
    store = DraftStore()
    draft_id = store.issue(_request())

    for _ in range(3):
        request, reason = store.get(draft_id)
        assert reason == REASON_OK
        assert request is not None

    request, reason = store.consume_for_save(draft_id)
    assert reason == REASON_OK
    assert request is not None


def test_consume_is_one_shot_and_replay_is_detected() -> None:
    store = DraftStore()
    draft_id = store.issue(_request())

    request, reason = store.consume_for_save(draft_id)
    assert reason == REASON_OK
    assert request is not None

    # The same id is now a replay (tombstone), not "unknown".
    missing, reason = store.consume_for_save(draft_id)
    assert missing is None
    assert reason == REASON_REPLAYED


def test_update_replaces_payload_for_next_save() -> None:
    store = DraftStore()
    draft_id = store.issue(_request("req-original"))

    modified = {**_request("req-original"), "status": "PENDING_CONFIRM"}
    modified["confirmable_config"] = {"expected_folder_name": "自定义"}
    assert store.update(draft_id, modified) is True

    saved, reason = store.consume_for_save(draft_id)
    assert reason == REASON_OK
    assert saved is not None
    assert saved["confirmable_config"]["expected_folder_name"] == "自定义"


def test_update_unknown_draft_returns_false() -> None:
    store = DraftStore()
    assert store.update("never-issued", _request()) is False


def test_ttl_expiry_reports_expired() -> None:
    now = [1_000.0]
    store = DraftStore(ttl_seconds=60.0, now=lambda: now[0])
    draft_id = store.issue(_request())
    assert len(store) == 1

    # 61s later the draft is expired.
    now[0] += 61.0
    request, reason = store.get(draft_id)
    assert request is None
    assert reason == REASON_EXPIRED
    assert len(store) == 0


def test_capacity_eviction_reports_evicted_for_oldest() -> None:
    now = [1_000.0]
    store = DraftStore(max_entries=2, now=lambda: now[0])
    first = store.issue(_request("req-first"))
    second = store.issue(_request("req-second"))
    # Touch the second so it is newer than the first.
    store.get(second)

    # Issuing a third evicts the oldest (first).
    third = store.issue(_request("req-third"))
    assert len(store) == 2

    request, reason = store.get(first)
    assert request is None
    assert reason == REASON_EVICTED

    for draft_id in (second, third):
        request, reason = store.get(draft_id)
        assert reason == REASON_OK
        assert request is not None


def test_clear_empties_store_and_tombstones() -> None:
    store = DraftStore()
    draft_id = store.issue(_request())
    store.consume_for_save(draft_id)
    store.clear()

    assert len(store) == 0
    # After clear, the consumed tombstone is gone too.
    missing, reason = store.consume_for_save(draft_id)
    assert missing is None
    assert reason != REASON_REPLAYED


def test_unknown_id_reports_unknown() -> None:
    store = DraftStore()
    missing, reason = store.get("never-issued")
    assert missing is None
    assert reason == REASON_UNKNOWN  # routes map unknown -> draft_expired
