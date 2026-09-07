from __future__ import annotations

"""US-194 + US-210: server-authoritative draft store unit tests.

The DraftStore is the bounded, expiring, one-time-save store that holds unsaved
preview requests. These tests pin its lifecycle (issue/get/consume/CAS),
capacity eviction, TTL expiry, replay protection, the monotonic revision /
compare-and-swap primitive and the reason codes routes map to stable 409
``draft_*`` errors.
"""

from typing import Any

from apps.migu_orca_web.drafts import (
    REASON_EVICTED,
    REASON_EXPIRED,
    REASON_OK,
    REASON_REPLAYED,
    REASON_REVISION_CONFLICT,
    REASON_UNKNOWN,
    DraftHandle,
    DraftRead,
    DraftStore,
)


def _request(request_id: str = "req-1") -> dict[str, Any]:
    return {
        "request_id": request_id,
        "status": "PENDING_CONFIRM",
        "input": {"raw_title": "示例"},
    }


def test_issue_returns_opaque_handle_with_revision_1() -> None:
    store = DraftStore()
    handle = store.issue(_request("req-a"))

    # The handle is opaque (URL-safe token, no request data) with revision 1.
    assert isinstance(handle, DraftHandle)
    assert isinstance(handle.draft_id, str)
    assert len(handle.draft_id) >= 16
    assert handle.draft_id.isalnum() or "-" in handle.draft_id or "_" in handle.draft_id
    assert handle.revision == 1


def test_issue_reads_back_payload_and_revision() -> None:
    store = DraftStore()
    handle = store.issue(_request("req-a"))

    draft_read, reason = store.get(handle.draft_id)
    assert reason == REASON_OK
    assert isinstance(draft_read, DraftRead)
    assert draft_read is not None
    assert draft_read.request["request_id"] == "req-a"
    assert draft_read.revision == 1


def test_get_does_not_consume_or_bump_revision() -> None:
    store = DraftStore()
    draft_id = store.issue(_request()).draft_id

    for _ in range(3):
        draft_read, reason = store.get(draft_id)
        assert reason == REASON_OK
        assert draft_read is not None
        assert draft_read.revision == 1

    request, reason = store.consume_for_save(draft_id)
    assert reason == REASON_OK
    assert request is not None


def test_compare_and_swap_bumps_revision_on_success() -> None:
    store = DraftStore()
    draft_id = store.issue(_request("req-original")).draft_id

    modified = {**_request("req-original"), "status": "PENDING_CONFIRM"}
    modified["confirmable_config"] = {"expected_folder_name": "自定义"}
    revision, reason = store.compare_and_swap(draft_id, 1, modified)

    assert reason == REASON_OK
    assert revision == 2

    draft_read, reason = store.get(draft_id)
    assert reason == REASON_OK
    assert draft_read is not None
    assert draft_read.revision == 2
    assert draft_read.request["confirmable_config"]["expected_folder_name"] == "自定义"


def test_compare_and_swap_supports_consecutive_updates() -> None:
    store = DraftStore()
    draft_id = store.issue(_request("req-original")).draft_id

    current = 1
    for step in range(3):
        updated = {**_request("req-original"), "step": step}
        revision, reason = store.compare_and_swap(draft_id, current, updated)
        assert reason == REASON_OK
        assert revision == current + 1
        current = revision

    draft_read, reason = store.get(draft_id)
    assert reason == REASON_OK
    assert draft_read is not None
    assert draft_read.revision == 4
    assert draft_read.request["step"] == 2


def test_compare_and_swap_stale_base_is_a_revision_conflict() -> None:
    """A stale base_revision leaves both payload and revision untouched."""
    store = DraftStore()
    draft_id = store.issue(_request("req-original")).draft_id

    # Two concurrent editors both read revision 1.
    _, reason = store.compare_and_swap(draft_id, 1, {**_request("req-a")})
    assert reason == REASON_OK

    # The stale writer still sends base_revision=1: it must not overwrite.
    revision, reason = store.compare_and_swap(draft_id, 1, {**_request("req-stale")})
    assert reason == REASON_REVISION_CONFLICT
    assert revision is None

    draft_read, _ = store.get(draft_id)
    assert draft_read is not None
    assert draft_read.request["request_id"] == "req-a"
    assert draft_read.revision == 2


def test_compare_and_swap_unknown_draft_returns_unknown() -> None:
    store = DraftStore()
    revision, reason = store.compare_and_swap("never-issued", 1, _request())
    assert revision is None
    assert reason == REASON_UNKNOWN


def test_compare_and_swap_consumed_draft_returns_replayed() -> None:
    store = DraftStore()
    draft_id = store.issue(_request()).draft_id
    store.consume_for_save(draft_id)

    revision, reason = store.compare_and_swap(draft_id, 1, _request())
    assert revision is None
    assert reason == REASON_REPLAYED


def test_update_replaces_payload_and_bumps_revision_for_next_save() -> None:
    store = DraftStore()
    draft_id = store.issue(_request("req-original")).draft_id

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
    draft_id = store.issue(_request()).draft_id
    assert len(store) == 1

    # 61s later the draft is expired.
    now[0] += 61.0
    draft_read, reason = store.get(draft_id)
    assert draft_read is None
    assert reason == REASON_EXPIRED
    assert len(store) == 0


def test_capacity_eviction_reports_evicted_for_oldest() -> None:
    now = [1_000.0]
    store = DraftStore(max_entries=2, now=lambda: now[0])
    first = store.issue(_request("req-first")).draft_id
    second = store.issue(_request("req-second")).draft_id
    # Touch the second so it is newer than the first.
    store.get(second)

    # Issuing a third evicts the oldest (first).
    third = store.issue(_request("req-third")).draft_id
    assert len(store) == 2

    draft_read, reason = store.get(first)
    assert draft_read is None
    assert reason == REASON_EVICTED

    for draft_id in (second, third):
        draft_read, reason = store.get(draft_id)
        assert reason == REASON_OK
        assert draft_read is not None


def test_clear_empties_store_and_tombstones() -> None:
    store = DraftStore()
    draft_id = store.issue(_request()).draft_id
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
