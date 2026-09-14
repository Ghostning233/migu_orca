from __future__ import annotations

import json
from copy import deepcopy

from batch_engine.controllers.batch_accept_controller import (
    ACCEPT_OUTCOME_ACCEPTED,
    ACCEPT_OUTCOME_ALREADY_ACCEPTED,
    ACCEPT_OUTCOME_FAILED,
    ACCEPT_OUTCOME_UNACCEPTABLE,
    BatchAcceptItem,
    retired_accept_items,
    serialize_batch_accept_result,
)
from batch_engine.controllers.batch_queue_controller import (
    create_submission_queue,
    enqueue_item,
)
from batch_engine.models import (
    BATCH_QUEUE_STATUS_READY_TO_SUBMIT,
    BatchQueueItem,
    BatchSubmissionQueue,
)
from shared.errors import Stage1Error


def _request(
    *,
    request_id: str = "req-1",
    status: str = "PENDING_CONFIRM",
    title: str = "葬送的芙莉莲",
) -> dict:
    return {
        "request_id": request_id,
        "status": status,
        "input": {"raw_title": title},
        "source_info": {"matched_bangumi": {"title": title}},
        "confirmable_config": {},
    }


def _now_factory(values: list[str]):
    stamps = iter(values)
    return lambda: next(stamps)


class FakeRequestStore:
    """In-memory request store simulating the request snapshot repository."""

    def __init__(self, requests: list[dict]) -> None:
        self._requests = {
            request["request_id"]: deepcopy(request) for request in requests
        }
        self.accept_calls: list[str] = []

    def load(self, request_id: str) -> dict | None:
        request = self._requests.get(request_id)
        return deepcopy(request) if request is not None else None

    def accept_one(self, request_id: str) -> dict:
        self.accept_calls.append(request_id)
        request = self._requests[request_id]
        accepted = deepcopy(request)
        accepted["status"] = "ACCEPTED"
        accepted["user_action"] = {"action": "ACCEPT", "reason": None}
        self._requests[request_id] = accepted
        return accepted


def _run(
    items: list[BatchAcceptItem],
    store: FakeRequestStore,
    *,
    item_ids: list[str] | None = None,
    queue: BatchSubmissionQueue | None = None,
    now: list[str] | None = None,
):
    return retired_accept_items(
        batch_id="batch-1",
        items=items,
        load_request=store.load,
        accept_one=store.accept_one,
        item_ids=item_ids,
        queue=queue,
        now_factory=_now_factory(now) if now else None,
    )


def _ready_item(
    request_id: str = "req-1",
    *,
    item_id: str = "item-1",
    batch_id: str = "batch-1",
) -> BatchQueueItem:
    """Build a READY_TO_SUBMIT queue item exactly as an accept would enqueue it."""
    queue = create_submission_queue(
        batch_id,
        queue_id_factory=lambda: "queue-1",
        now_factory=lambda: "2026-08-19T00:00:00+00:00",
    )
    queue = enqueue_item(
        queue,
        item_id=item_id,
        request_id=request_id,
        title="标题",
        now_factory=lambda: "2026-08-19T00:00:00+00:00",
    )
    return queue.items[0]


def _queue_with_item(item: BatchQueueItem) -> BatchSubmissionQueue:
    return BatchSubmissionQueue(
        queue_id=item.queue_id,
        batch_id=item.batch_id,
        items=[item],
        created_at="2026-08-19T00:00:00+00:00",
        updated_at="2026-08-19T00:00:00+00:00",
    )


class TestAcceptSelectedAndAll:
    def test_accept_all_enqueues_every_pending_item_as_ready_to_submit(self) -> None:
        store = FakeRequestStore(
            [
                _request(request_id="req-1", title="葬送的芙莉莲"),
                _request(request_id="req-2", title="咒术回战 第三季"),
            ]
        )
        items = [
            BatchAcceptItem(item_id="item-1", request_id="req-1"),
            BatchAcceptItem(item_id="item-2", request_id="req-2"),
        ]

        result = _run(items, store)

        assert store.accept_calls == ["req-1", "req-2"]
        assert [item.status for item in result.items] == [
            ACCEPT_OUTCOME_ACCEPTED,
            ACCEPT_OUTCOME_ACCEPTED,
        ]
        assert all(item.queued for item in result.items)
        queue_items = result.queue.items
        assert [item.item_id for item in queue_items] == ["item-1", "item-2"]
        assert [item.request_id for item in queue_items] == ["req-1", "req-2"]
        assert all(
            item.status == BATCH_QUEUE_STATUS_READY_TO_SUBMIT for item in queue_items
        )
        assert all(item.attempts == 0 for item in queue_items)
        assert [item.title for item in queue_items] == ["葬送的芙莉莲", "咒术回战 第三季"]

    def test_item_ids_filters_to_selected_subset_in_batch_order(self) -> None:
        store = FakeRequestStore(
            [
                _request(request_id="req-1"),
                _request(request_id="req-2"),
                _request(request_id="req-3"),
            ]
        )
        items = [
            BatchAcceptItem(item_id="item-1", request_id="req-1"),
            BatchAcceptItem(item_id="item-2", request_id="req-2"),
            BatchAcceptItem(item_id="item-3", request_id="req-3"),
        ]

        result = _run(items, store, item_ids=["item-3", "item-1"])

        # Selection preserves batch order; item_ids is a filter, not an ordering.
        assert store.accept_calls == ["req-1", "req-3"]
        assert [item.item_id for item in result.items] == ["item-1", "item-3"]
        assert [item.request_id for item in result.queue.items] == ["req-1", "req-3"]

    def test_unknown_item_ids_are_ignored(self) -> None:
        store = FakeRequestStore([_request(request_id="req-1")])

        result = _run(
            [BatchAcceptItem(item_id="item-1", request_id="req-1")],
            store,
            item_ids=["item-1", "item-unknown"],
        )

        assert store.accept_calls == ["req-1"]
        assert [item.item_id for item in result.items] == ["item-1"]

    def test_reuses_existing_queue_and_appends_new_items(self) -> None:
        store = FakeRequestStore([_request(request_id="req-2")])
        existing = create_submission_queue("batch-1", queue_id_factory=lambda: "queue-1")
        existing = enqueue_item(
            existing,
            item_id="item-1",
            request_id="req-1",
            title="葬送的芙莉莲",
        )

        result = _run(
            [BatchAcceptItem(item_id="item-2", request_id="req-2")],
            store,
            queue=existing,
        )

        assert result.queue.queue_id == "queue-1"
        assert [item.item_id for item in result.queue.items] == ["item-1", "item-2"]

    def test_rejects_empty_batch_id(self) -> None:
        store = FakeRequestStore([_request(request_id="req-1")])

        try:
            retired_accept_items(
                batch_id="  ",
                items=[BatchAcceptItem(item_id="item-1", request_id="req-1")],
                load_request=store.load,
                accept_one=store.accept_one,
            )
        except ValueError as exc:
            assert "batch_id" in str(exc)
        else:  # pragma: no cover - safety boundary
            raise AssertionError("empty batch_id must be rejected")


class TestUnacceptableItems:
    def test_items_without_request_id_return_reason(self) -> None:
        store = FakeRequestStore([])
        items = [
            BatchAcceptItem(item_id="item-failed"),
            BatchAcceptItem(item_id="item-deleted"),
        ]

        result = _run(items, store)

        assert store.accept_calls == []
        assert result.queue.items == []
        for item in result.items:
            assert item.status == ACCEPT_OUTCOME_UNACCEPTABLE
            assert item.reason == "卡片缺少订阅草案，无法接受"
            assert item.error_type is None

    def test_missing_request_snapshot_returns_deleted_reason(self) -> None:
        store = FakeRequestStore([_request(request_id="req-1")])

        result = _run(
            [
                BatchAcceptItem(item_id="item-1", request_id="req-1"),
                BatchAcceptItem(item_id="item-2", request_id="req-missing"),
            ],
            store,
        )

        assert store.accept_calls == ["req-1"]
        assert result.items[1].status == ACCEPT_OUTCOME_UNACCEPTABLE
        assert result.items[1].reason == "订阅方案不存在或已删除"
        assert [item.request_id for item in result.queue.items] == ["req-1"]

    def test_cancelled_request_returns_reason(self) -> None:
        store = FakeRequestStore([_request(request_id="req-1", status="CANCELLED")])

        result = _run([BatchAcceptItem(item_id="item-1", request_id="req-1")], store)

        assert store.accept_calls == []
        item = result.items[0]
        assert item.status == ACCEPT_OUTCOME_UNACCEPTABLE
        assert item.reason == "订阅方案已取消，无法接受"
        assert item.error_type == "request_cancelled"
        assert result.queue.items == []

    def test_unknown_status_returns_reason(self) -> None:
        store = FakeRequestStore([_request(request_id="req-1", status="SOMETHING")])

        result = _run([BatchAcceptItem(item_id="item-1", request_id="req-1")], store)

        item = result.items[0]
        assert item.status == ACCEPT_OUTCOME_UNACCEPTABLE
        assert item.reason == "订阅方案状态不支持接受"
        assert item.error_type == "invalid_request_status"


class TestIdempotentRepeat:
    def test_already_accepted_items_are_idempotent(self) -> None:
        store = FakeRequestStore([_request(request_id="req-1", status="ACCEPTED")])

        result = _run([BatchAcceptItem(item_id="item-1", request_id="req-1")], store)

        assert store.accept_calls == []
        item = result.items[0]
        assert item.status == ACCEPT_OUTCOME_ALREADY_ACCEPTED
        assert item.reason == "该订阅方案已确认，已补建提交队列"
        assert item.queued is True
        # The ACCEPTED Request had no queue item, so one READY_TO_SUBMIT item is
        # rebuilt so the accepted Request can still be submitted.
        assert len(result.queue.items) == 1
        assert result.queue.items[0].request_id == "req-1"
        assert result.queue.items[0].status == BATCH_QUEUE_STATUS_READY_TO_SUBMIT

    def test_repeat_batch_accept_does_not_duplicate_queue_items(self) -> None:
        store = FakeRequestStore([_request(request_id="req-1")])
        first = _run([BatchAcceptItem(item_id="item-1", request_id="req-1")], store)
        assert len(first.queue.items) == 1

        repeated = _run(
            [BatchAcceptItem(item_id="item-1", request_id="req-1")],
            store,
            queue=first.queue,
        )

        assert store.accept_calls == ["req-1"]
        assert repeated.items[0].status == ACCEPT_OUTCOME_ALREADY_ACCEPTED
        assert len(repeated.queue.items) == 1
        assert repeated.queue == first.queue

    def test_accepted_request_with_existing_queue_item_is_idempotent(self) -> None:
        """ACCEPTED + the queue already holds the request_id: stay idempotent."""
        store = FakeRequestStore([_request(request_id="req-1", status="ACCEPTED")])
        existing = _queue_with_item(_ready_item("req-1"))

        result = _run(
            [BatchAcceptItem(item_id="item-1", request_id="req-1")],
            store,
            queue=existing,
        )

        assert store.accept_calls == []
        item = result.items[0]
        assert item.status == ACCEPT_OUTCOME_ALREADY_ACCEPTED
        assert item.reason == "该订阅方案已确认，跳过重复接受"
        assert item.queued is False
        assert result.queue == existing
        assert len(result.queue.items) == 1

    def test_accepted_request_with_missing_queue_item_is_re_enqueued(self) -> None:
        """ACCEPTED but the queue lost the item: rebuild READY_TO_SUBMIT."""
        store = FakeRequestStore([_request(request_id="req-1", status="ACCEPTED")])

        result = _run(
            [BatchAcceptItem(item_id="item-1", request_id="req-1")],
            store,
            queue=create_submission_queue("batch-1"),
        )

        assert store.accept_calls == []
        item = result.items[0]
        assert item.status == ACCEPT_OUTCOME_ALREADY_ACCEPTED
        assert item.reason == "该订阅方案已确认，已补建提交队列"
        assert item.queued is True
        assert len(result.queue.items) == 1
        assert result.queue.items[0].request_id == "req-1"
        assert result.queue.items[0].status == BATCH_QUEUE_STATUS_READY_TO_SUBMIT

    def test_accepted_request_with_successful_result_is_never_re_enqueued(
        self,
    ) -> None:
        """Regression: an ACCEPTED Request whose AB submit already SUCCEEDED must
        never be re-enqueued — rebuilding READY_TO_SUBMIT would let a later
        submit re-create the subscription on Auto Bangumi."""
        request = _request(request_id="req-1", status="ACCEPTED")
        request["ab_submit_result"] = {
            "success": True,
            "ab_subscription_id": "ab-req-1",
            "ab_response": {"id": "ab-req-1"},
            "fallback_config": None,
            "error": None,
        }
        store = FakeRequestStore([request])

        result = _run(
            [BatchAcceptItem(item_id="item-1", request_id="req-1")],
            store,
            queue=create_submission_queue("batch-1"),
        )

        assert store.accept_calls == []
        item = result.items[0]
        assert item.status == ACCEPT_OUTCOME_ALREADY_ACCEPTED
        assert item.reason == "该订阅方案已提交成功，跳过重复入队"
        assert item.queued is False
        assert result.queue.items == []

    def test_accepted_request_with_failed_result_is_re_enqueued(self) -> None:
        """A persisted FAILED result means Auto Bangumi did not create the
        subscription, so the missing queue item may still be rebuilt."""
        request = _request(request_id="req-1", status="ACCEPTED")
        request["ab_submit_result"] = {
            "success": False,
            "ab_subscription_id": None,
            "ab_response": None,
            "fallback_config": None,
            "error": {"error_type": "ab_auth_failed", "error_message": "认证失败"},
        }
        store = FakeRequestStore([request])

        result = _run(
            [BatchAcceptItem(item_id="item-1", request_id="req-1")],
            store,
            queue=create_submission_queue("batch-1"),
        )

        item = result.items[0]
        assert item.status == ACCEPT_OUTCOME_ALREADY_ACCEPTED
        assert item.queued is True
        assert len(result.queue.items) == 1


class TestSingleItemFailureDoesNotBlock:
    def test_one_failure_does_not_block_others(self) -> None:
        store = FakeRequestStore(
            [
                _request(request_id="req-1"),
                _request(request_id="req-2"),
            ]
        )

        def failing_accept_one(request_id: str) -> dict:
            if request_id == "req-1":
                raise Stage1Error(
                    "storage_error",
                    "保存订阅方案 JSON 失败",
                    "retired_accept_items",
                )
            return store.accept_one(request_id)

        result = retired_accept_items(
            batch_id="batch-1",
            items=[
                BatchAcceptItem(item_id="item-1", request_id="req-1"),
                BatchAcceptItem(item_id="item-2", request_id="req-2"),
            ],
            load_request=store.load,
            accept_one=failing_accept_one,
        )

        assert result.items[0].status == ACCEPT_OUTCOME_FAILED
        assert result.items[0].reason == "保存订阅方案 JSON 失败"
        assert result.items[0].error_type == "storage_error"
        assert result.items[0].queued is False
        assert result.items[1].status == ACCEPT_OUTCOME_ACCEPTED
        assert [item.request_id for item in result.queue.items] == ["req-2"]

    def test_unexpected_exception_is_sanitized(self) -> None:
        store = FakeRequestStore([_request(request_id="req-1")])

        def exploding_accept_one(request_id: str) -> dict:
            raise RuntimeError(
                "token=secret endpoint=https://ab.example.com path=/home/ghostning"
            )

        result = retired_accept_items(
            batch_id="batch-1",
            items=[BatchAcceptItem(item_id="item-1", request_id="req-1")],
            load_request=store.load,
            accept_one=exploding_accept_one,
        )

        item = result.items[0]
        assert item.status == ACCEPT_OUTCOME_FAILED
        assert item.reason == "接受失败发生未预期错误"
        assert item.error_type == "unexpected_error"
        assert "secret" not in item.reason
        assert "ab.example.com" not in item.reason
        assert result.queue.items == []


class TestTitleAndSerialization:
    def test_title_derived_from_accepted_request_when_item_has_none(self) -> None:
        store = FakeRequestStore([_request(request_id="req-1", title="葬送的芙莉莲")])

        result = _run([BatchAcceptItem(item_id="item-1", request_id="req-1")], store)

        assert result.queue.items[0].title == "葬送的芙莉莲"
        assert result.items[0].title == "葬送的芙莉莲"

    def test_item_title_prefers_descriptor_title(self) -> None:
        store = FakeRequestStore([_request(request_id="req-1", title="葬送的芙莉莲")])

        result = _run(
            [
                BatchAcceptItem(
                    item_id="item-1",
                    request_id="req-1",
                    title="自定义显示标题",
                )
            ],
            store,
        )

        assert result.queue.items[0].title == "自定义显示标题"

    def test_title_falls_back_to_placeholder(self) -> None:
        store = FakeRequestStore(
            [
                {
                    "request_id": "req-1",
                    "status": "PENDING_CONFIRM",
                    "input": {},
                    "source_info": {},
                    "confirmable_config": {},
                }
            ]
        )

        result = _run([BatchAcceptItem(item_id="item-1", request_id="req-1")], store)

        assert result.queue.items[0].title == "未命名订阅方案"

    def test_enqueued_title_is_sanitized(self) -> None:
        store = FakeRequestStore([_request(request_id="req-1")])

        result = _run(
            [
                BatchAcceptItem(
                    item_id="item-1",
                    request_id="req-1",
                    title="葬送的芙莉莲 https://ab.example.com/api token=secret123",
                )
            ],
            store,
        )

        queued_title = result.queue.items[0].title
        assert "ab.example.com" not in queued_title
        assert "secret123" not in queued_title
        assert "葬送的芙莉莲" in queued_title

    def test_serialization_contains_only_safe_fields_and_summary(self) -> None:
        store = FakeRequestStore(
            [
                _request(request_id="req-1"),
                _request(request_id="req-2"),
            ]
        )
        result = _run(
            [
                BatchAcceptItem(item_id="item-1", request_id="req-1"),
                BatchAcceptItem(item_id="item-2", request_id="req-2"),
            ],
            store,
        )

        serialized = serialize_batch_accept_result(result)
        body = json.dumps(serialized, ensure_ascii=False)

        assert set(serialized) == {"batch_id", "queue", "items", "summary"}
        assert serialized["summary"] == {
            ACCEPT_OUTCOME_ACCEPTED: 2,
            ACCEPT_OUTCOME_ALREADY_ACCEPTED: 0,
            ACCEPT_OUTCOME_UNACCEPTABLE: 0,
            ACCEPT_OUTCOME_FAILED: 0,
        }
        item = serialized["items"][0]
        assert set(item) == {
            "item_id",
            "request_id",
            "title",
            "status",
            "reason",
            "error_type",
            "queued",
        }
        assert item["status"] == ACCEPT_OUTCOME_ACCEPTED
        assert item["queued"] is True
        for keyword in (
            "endpoint",
            "token",
            "cookie",
            "authorization",
            "password",
            "passwd",
            "bearer",
            "magnet",
            "raw_html",
            "raw_rss",
            "response_body",
        ):
            assert keyword not in body

    def test_serialization_includes_unacceptable_reason(self) -> None:
        store = FakeRequestStore([])
        result = _run([BatchAcceptItem(item_id="item-1")], store)

        serialized = serialize_batch_accept_result(result)
        assert serialized["items"][0]["reason"] == "卡片缺少订阅草案，无法接受"
        assert serialized["summary"][ACCEPT_OUTCOME_UNACCEPTABLE] == 1
