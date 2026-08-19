from __future__ import annotations

from copy import deepcopy
import json

import pytest

from ab_engine.controllers.ab_client import FakeAutoBangumiClient
from ab_engine.controllers.ab_config import AutoBangumiConfig
from batch_engine.controllers.batch_queue_controller import (
    complete_queue_item_submit,
    create_submission_queue,
    enqueue_item,
    start_queue_item_submit,
)
from batch_engine.controllers.batch_submit_controller import (
    RECOVER_ACTION_AUTO,
    RECOVER_ACTION_FAILED,
    RECOVER_ACTION_SUCCEEDED,
    RECOVER_OUTCOME_FAILED,
    RECOVER_OUTCOME_NEEDS_MANUAL,
    RECOVER_OUTCOME_SKIPPED,
    RECOVER_OUTCOME_SUCCEEDED,
    SUBMIT_OUTCOME_FAILED,
    SUBMIT_OUTCOME_RETRYABLE,
    SUBMIT_OUTCOME_SKIPPED,
    SUBMIT_OUTCOME_SUCCEEDED,
    SUBMIT_PERSIST_ERROR_TYPE,
    BatchSubmitItemResult,
    compose_ab_submit_one,
    recover_batch_queue_item,
    retry_batch_queue_item,
    serialize_batch_submit_result,
    submit_batch_queue_items,
)
from batch_engine.models import (
    BATCH_QUEUE_STATUS_FAILED,
    BATCH_QUEUE_STATUS_READY_TO_SUBMIT,
    BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED,
    BATCH_QUEUE_STATUS_RETRYABLE,
    BATCH_QUEUE_STATUS_SUBMITTING,
    BATCH_QUEUE_STATUS_SUCCEEDED,
    BatchQueueItem,
    BatchSubmissionQueue,
)
from shared.errors import Stage1Error


def _accepted_request(
    *,
    request_id: str = "req-1",
    title: str = "葬送的芙莉莲",
    status: str = "ACCEPTED",
) -> dict:
    return {
        "request_id": request_id,
        "status": status,
        "input": {"raw_title": title},
        "source_info": {"matched_bangumi": {"title": title}},
        "confirmable_config": {
            "selected_rss_url": "https://mikan.example.com/rss/sub",
            "expected_folder_name": title,
            "filter_rule": {},
        },
    }


class FakeRequestStore:
    """In-memory request snapshot store for the batch submit service."""

    def __init__(self, requests: list[dict]) -> None:
        self._requests = {
            request["request_id"]: deepcopy(request) for request in requests
        }

    def load(self, request_id: str) -> dict | None:
        request = self._requests.get(request_id)
        return deepcopy(request) if request is not None else None


def _now_factory(values: list[str]):
    stamps = iter(values)
    return lambda: next(stamps)


def _queue(*, request_ids: list[str], batch_id: str = "batch-1") -> BatchSubmissionQueue:
    queue = create_submission_queue(
        batch_id,
        queue_id_factory=lambda: "queue-1",
        now_factory=lambda: "2026-08-19T00:00:00+00:00",
    )
    for index, request_id in enumerate(request_ids, start=1):
        queue = enqueue_item(
            queue,
            item_id=f"item-{index}",
            request_id=request_id,
            title=f"标题-{request_id}",
            now_factory=lambda: "2026-08-19T00:00:00+00:00",
        )
    return queue


def _succeeded_queue_item(request_id: str = "req-1") -> BatchQueueItem:
    queue = _queue(request_ids=[request_id])
    queue = start_queue_item_submit(
        queue,
        request_id,
        now_factory=lambda: "2026-08-19T00:01:00+00:00",
    )
    queue = complete_queue_item_submit(
        queue,
        request_id,
        BATCH_QUEUE_STATUS_SUCCEEDED,
        ab_result_summary={"success": True, "ab_subscription_id": "ab-1"},
        now_factory=lambda: "2026-08-19T00:02:00+00:00",
    )
    return queue.items[0]


def _success_submit(request: dict, ab_config) -> dict:
    return {
        "success": True,
        "ab_subscription_id": f"ab-{request['request_id']}",
        "ab_response": {"id": f"ab-{request['request_id']}"},
        "fallback_config": None,
        "error": None,
    }


def _retried_queue_item(
    request_id: str = "req-1",
    *,
    status: str = BATCH_QUEUE_STATUS_FAILED,
    attempts: int = 1,
    batch_id: str = "batch-1",
) -> BatchQueueItem:
    """Build a FAILED/RETRYABLE queue item after one failed submit attempt."""
    queue = _queue(request_ids=[request_id], batch_id=batch_id)
    queue = start_queue_item_submit(
        queue,
        request_id,
        now_factory=lambda: "2026-08-19T00:01:00+00:00",
    )
    queue = complete_queue_item_submit(
        queue,
        request_id,
        status,
        last_error={"error_type": "ab_submit_failed", "error_message": "初次提交失败"},
        now_factory=lambda: "2026-08-19T00:02:00+00:00",
    )
    assert queue.items[0].attempts == attempts
    return queue.items[0]


def _queue_with_item(item: BatchQueueItem) -> BatchSubmissionQueue:
    return _queue_with_items([item])


def _queue_with_items(items: list[BatchQueueItem]) -> BatchSubmissionQueue:
    first = items[0]
    return BatchSubmissionQueue(
        queue_id=first.queue_id,
        batch_id=first.batch_id,
        items=items,
        created_at="2026-08-19T00:00:00+00:00",
        updated_at="2026-08-19T00:02:00+00:00",
    )


def _ab_config(**overrides) -> AutoBangumiConfig:
    values = {
        "endpoint": "https://ab.example.com/api/subscription",
        "token": "secret-token",
        "fallback_enabled": False,
    }
    values.update(overrides)
    return AutoBangumiConfig(**values)


class TestAllSuccesses:
    def test_multiple_read_items_all_succeed_in_order(self) -> None:
        store = FakeRequestStore(
            [
                _accepted_request(request_id="req-1"),
                _accepted_request(request_id="req-2"),
            ]
        )
        queue = _queue(request_ids=["req-1", "req-2"])
        calls: list[str] = []

        def submit_one(request, ab_config) -> dict:
            calls.append(request["request_id"])
            return _success_submit(request, ab_config)

        result = submit_batch_queue_items(
            batch_id="batch-1",
            queue=queue,
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=submit_one,
            now_factory=_now_factory(
                [
                    "2026-08-19T00:01:00+00:00",
                    "2026-08-19T00:02:00+00:00",
                    "2026-08-19T00:03:00+00:00",
                    "2026-08-19T00:04:00+00:00",
                ]
            ),
        )

        assert calls == ["req-1", "req-2"]
        assert [item.status for item in result.items] == [
            SUBMIT_OUTCOME_SUCCEEDED,
            SUBMIT_OUTCOME_SUCCEEDED,
        ]
        queue_items = result.queue.items
        assert all(item.status == BATCH_QUEUE_STATUS_SUCCEEDED for item in queue_items)
        assert all(item.attempts == 1 for item in queue_items)
        assert all(
            "ab_subscription_id=ab-" in (item.ab_result_summary or "")
            for item in queue_items
        )
        assert all(item.last_error is None for item in queue_items)

    def test_success_summary_never_contains_ab_config(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        queue = _queue(request_ids=["req-1"])

        result = submit_batch_queue_items(
            batch_id="batch-1",
            queue=queue,
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=_success_submit,
        )

        serialized = json.dumps(serialize_batch_submit_result(result), ensure_ascii=False)
        for keyword in (
            "endpoint",
            "token",
            "secret-token",
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
            assert keyword not in serialized


class TestSingleFailureContinues:
    def test_one_submit_failure_does_not_block_the_rest(self) -> None:
        store = FakeRequestStore(
            [
                _accepted_request(request_id="req-1"),
                _accepted_request(request_id="req-2"),
            ]
        )
        queue = _queue(request_ids=["req-1", "req-2"])

        def submit_one(request, ab_config) -> dict:
            if request["request_id"] == "req-1":
                return {
                    "success": False,
                    "ab_subscription_id": None,
                    "ab_response": None,
                    "fallback_config": None,
                    "error": {
                        "error_type": "ab_submit_failed",
                        "error_message": "Auto Bangumi HTTP 提交失败",
                        "failed_step": "create_ab_subscription",
                        "details": {"status_code": 503},
                    },
                }
            return _success_submit(request, ab_config)

        result = submit_batch_queue_items(
            batch_id="batch-1",
            queue=queue,
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=submit_one,
        )

        assert result.items[0].status == SUBMIT_OUTCOME_FAILED
        assert result.items[0].reason == "Auto Bangumi HTTP 提交失败"
        assert result.items[0].error_type == "ab_submit_failed"
        assert result.items[1].status == SUBMIT_OUTCOME_SUCCEEDED

        queue_items = result.queue.items
        assert queue_items[0].status == BATCH_QUEUE_STATUS_FAILED
        assert "error_type=ab_submit_failed" in (queue_items[0].last_error or "")
        assert queue_items[0].ab_result_summary is None
        assert queue_items[1].status == BATCH_QUEUE_STATUS_SUCCEEDED

    def test_stage1_error_from_submit_one_is_sanitized(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        queue = _queue(request_ids=["req-1"])

        def raising_submit_one(request, ab_config) -> dict:
            raise Stage1Error(
                "ab_submit_failed",
                "离线模拟失败",
                "create_ab_subscription",
                {"status_code": 503},
            )

        result = submit_batch_queue_items(
            batch_id="batch-1",
            queue=queue,
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=raising_submit_one,
        )

        assert result.items[0].status == SUBMIT_OUTCOME_FAILED
        assert result.items[0].reason == "离线模拟失败"
        assert result.items[0].error_type == "ab_submit_failed"
        assert result.queue.items[0].status == BATCH_QUEUE_STATUS_FAILED

    def test_unexpected_exception_is_sanitized(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        queue = _queue(request_ids=["req-1"])

        def exploding_submit_one(request, ab_config) -> dict:
            raise RuntimeError(
                "token=secret endpoint=https://ab.example.com path=/home/ghostning"
            )

        result = submit_batch_queue_items(
            batch_id="batch-1",
            queue=queue,
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=exploding_submit_one,
        )

        item = result.items[0]
        assert item.status == SUBMIT_OUTCOME_FAILED
        assert item.error_type == "unexpected_error"
        assert "secret" not in (item.reason or "")
        assert "ab.example.com" not in (item.reason or "")
        last_error = result.queue.items[0].last_error or ""
        assert "secret" not in last_error
        assert "ab.example.com" not in last_error
        assert "/home/ghostning" not in last_error


class TestRetryableClassification:
    def test_timeout_error_is_retryable(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        queue = _queue(request_ids=["req-1"])

        def timeout_submit(request, ab_config) -> dict:
            return {
                "success": False,
                "error": {
                    "error_type": "ab_timeout",
                    "error_message": "Auto Bangumi HTTP 请求超时",
                    "failed_step": "create_ab_subscription",
                    "details": {"category": "timeout"},
                },
            }

        result = submit_batch_queue_items(
            batch_id="batch-1",
            queue=queue,
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=timeout_submit,
        )

        assert result.items[0].status == SUBMIT_OUTCOME_RETRYABLE
        assert result.items[0].error_type == "ab_timeout"
        assert result.queue.items[0].status == BATCH_QUEUE_STATUS_RETRYABLE
        assert result.queue.items[0].attempts == 1

    def test_connection_error_is_retryable(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        queue = _queue(request_ids=["req-1"])

        def connection_submit(request, ab_config) -> dict:
            return {
                "success": False,
                "error": {
                    "error_type": "ab_connection_failed",
                    "error_message": "Auto Bangumi HTTP 连接失败",
                    "failed_step": "create_ab_subscription",
                    "details": {"category": "connection"},
                },
            }

        result = submit_batch_queue_items(
            batch_id="batch-1",
            queue=queue,
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=connection_submit,
        )

        assert result.items[0].status == SUBMIT_OUTCOME_RETRYABLE

    def test_auth_failure_is_terminal_failed(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        queue = _queue(request_ids=["req-1"])

        def auth_submit(request, ab_config) -> dict:
            return {
                "success": False,
                "error": {
                    "error_type": "ab_auth_failed",
                    "error_message": "Auto Bangumi 认证失败",
                    "failed_step": "create_ab_subscription",
                    "details": {"status_code": 401},
                },
            }

        result = submit_batch_queue_items(
            batch_id="batch-1",
            queue=queue,
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=auth_submit,
        )

        assert result.items[0].status == SUBMIT_OUTCOME_FAILED
        assert result.queue.items[0].status == BATCH_QUEUE_STATUS_FAILED


class TestNonAcceptedPreSubmit:
    def test_missing_request_snapshot_marks_failed_and_continues(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-2")])
        queue = _queue(request_ids=["req-1", "req-2"])
        calls: list[str] = []

        def submit_one(request, ab_config) -> dict:
            calls.append(request["request_id"])
            return _success_submit(request, ab_config)

        result = submit_batch_queue_items(
            batch_id="batch-1",
            queue=queue,
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=submit_one,
        )

        first = result.items[0]
        assert first.status == SUBMIT_OUTCOME_FAILED
        assert first.reason == "订阅方案不存在或已删除，无法提交"
        assert first.error_type == "request_not_found"
        assert first.attempts == 0
        assert result.queue.items[0].status == BATCH_QUEUE_STATUS_FAILED
        # The rest of the batch still processed.
        assert calls == ["req-2"]
        assert result.items[1].status == SUBMIT_OUTCOME_SUCCEEDED

    def test_cancelled_request_marks_failed(self) -> None:
        store = FakeRequestStore(
            [_accepted_request(request_id="req-1", status="CANCELLED")]
        )
        queue = _queue(request_ids=["req-1"])
        called = False

        def submit_one(request, ab_config) -> dict:
            nonlocal called
            called = True
            return _success_submit(request, ab_config)

        result = submit_batch_queue_items(
            batch_id="batch-1",
            queue=queue,
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=submit_one,
        )

        item = result.items[0]
        assert item.status == SUBMIT_OUTCOME_FAILED
        assert item.reason == "订阅方案已取消，无法提交"
        assert item.error_type == "request_cancelled"
        assert result.queue.items[0].status == BATCH_QUEUE_STATUS_FAILED
        assert called is False

    def test_not_yet_accepted_request_marks_retryable(self) -> None:
        store = FakeRequestStore(
            [_accepted_request(request_id="req-1", status="PENDING_CONFIRM")]
        )
        queue = _queue(request_ids=["req-1"])

        result = submit_batch_queue_items(
            batch_id="batch-1",
            queue=queue,
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=_success_submit,
        )

        item = result.items[0]
        assert item.status == SUBMIT_OUTCOME_RETRYABLE
        assert item.reason == "订阅方案尚未确认，无法提交"
        assert item.error_type == "invalid_request_status"
        assert result.queue.items[0].status == BATCH_QUEUE_STATUS_RETRYABLE
        assert result.queue.items[0].last_error == "订阅方案尚未确认，无法提交"

    def test_unknown_status_marks_retryable(self) -> None:
        store = FakeRequestStore(
            [_accepted_request(request_id="req-1", status="SOMETHING")]
        )
        queue = _queue(request_ids=["req-1"])

        result = submit_batch_queue_items(
            batch_id="batch-1",
            queue=queue,
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=_success_submit,
        )

        assert result.items[0].status == SUBMIT_OUTCOME_RETRYABLE
        assert result.queue.items[0].status == BATCH_QUEUE_STATUS_RETRYABLE


class TestAlreadySucceededSkipped:
    def test_succeeded_items_are_never_resubmitted(self) -> None:
        store = FakeRequestStore(
            [
                _accepted_request(request_id="req-1"),
                _accepted_request(request_id="req-2"),
            ]
        )
        succeeded = _succeeded_queue_item("req-1")
        queue = _queue(request_ids=["req-1", "req-2"])
        queue = BatchSubmissionQueue(
            queue_id=queue.queue_id,
            batch_id=queue.batch_id,
            items=[succeeded, queue.items[1]],
            created_at=queue.created_at,
            updated_at=queue.updated_at,
        )
        calls: list[str] = []

        def submit_one(request, ab_config) -> dict:
            calls.append(request["request_id"])
            return _success_submit(request, ab_config)

        result = submit_batch_queue_items(
            batch_id="batch-1",
            queue=queue,
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=submit_one,
        )

        assert calls == ["req-2"]
        assert result.items[0].status == SUBMIT_OUTCOME_SKIPPED
        assert result.items[0].reason == "已提交成功，跳过重复提交"
        assert result.items[0].attempts == 1
        assert result.queue.items[0].status == BATCH_QUEUE_STATUS_SUCCEEDED
        assert result.queue.items[0].attempts == 1
        assert result.items[1].status == SUBMIT_OUTCOME_SUCCEEDED

    def test_non_ready_items_are_skipped_without_submit_call(self) -> None:
        store = FakeRequestStore(
            [
                _accepted_request(request_id="req-1"),
                _accepted_request(request_id="req-2"),
                _accepted_request(request_id="req-3"),
            ]
        )
        queue = _queue(request_ids=["req-1", "req-2", "req-3"])
        in_flight = start_queue_item_submit(
            queue,
            "req-1",
            now_factory=lambda: "2026-08-19T00:01:00+00:00",
        )
        queue = BatchSubmissionQueue(
            queue_id=queue.queue_id,
            batch_id=queue.batch_id,
            items=[
                in_flight.items[0],
                queue.items[1],
                queue.items[2],
            ],
            created_at=queue.created_at,
            updated_at=in_flight.updated_at,
        )
        calls: list[str] = []

        def submit_one(request, ab_config) -> dict:
            calls.append(request["request_id"])
            return _success_submit(request, ab_config)

        result = submit_batch_queue_items(
            batch_id="batch-1",
            queue=queue,
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=submit_one,
        )

        assert calls == ["req-2", "req-3"]
        assert result.items[0].status == SUBMIT_OUTCOME_SKIPPED
        assert result.items[0].reason == "提交中，跳过本次提交"
        assert result.queue.items[0].status == BATCH_QUEUE_STATUS_SUBMITTING
        assert result.queue.items[0].attempts == 1


def _submitting_queue_item(request_id: str = "req-1") -> BatchQueueItem:
    """Build a SUBMITTING queue item as if a previous run persisted it and then
    crashed after the Auto Bangumi call (before the final status was saved)."""
    queue = _queue(request_ids=[request_id])
    queue = start_queue_item_submit(
        queue,
        request_id,
        now_factory=lambda: "2026-08-19T00:01:00+00:00",
    )
    return queue.items[0]


def _result_persist_failed_item(request_id: str = "req-1") -> BatchQueueItem:
    """Build a RESULT_PERSIST_FAILED queue item (AB call happened, local result
    persistence failed — the ambiguous, non-retryable state)."""
    queue = _queue(request_ids=[request_id])
    queue = start_queue_item_submit(
        queue,
        request_id,
        now_factory=lambda: "2026-08-19T00:01:00+00:00",
    )
    queue = complete_queue_item_submit(
        queue,
        request_id,
        BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED,
        last_error={
            "error_type": SUBMIT_PERSIST_ERROR_TYPE,
            "error_message": "保存 Auto Bangumi 提交结果失败",
        },
        now_factory=lambda: "2026-08-19T00:02:00+00:00",
    )
    return queue.items[0]


class TestPersistHooks:
    """Reliability hooks: SUBMITTING flush before submit, final status after,
    and per-item AB-result persistence into Request/ab_results."""

    def test_persist_queue_flushes_submitting_before_submit(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        queue = _queue(request_ids=["req-1"])
        snapshots: list[BatchSubmissionQueue] = []

        def persist_queue(q: BatchSubmissionQueue) -> None:
            snapshots.append(deepcopy(q))

        submit_batch_queue_items(
            batch_id="batch-1",
            queue=queue,
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=_success_submit,
            persist_queue=persist_queue,
        )

        # First flush is the SUBMITTING snapshot taken before submit_one; the
        # last flush is the final SUCCEEDED state.
        assert len(snapshots) >= 2
        assert snapshots[0].items[0].status == BATCH_QUEUE_STATUS_SUBMITTING
        assert snapshots[0].items[0].attempts == 1
        assert snapshots[-1].items[0].status == BATCH_QUEUE_STATUS_SUCCEEDED

    def test_submit_one_called_after_submitting_is_persisted(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        queue = _queue(request_ids=["req-1"])
        events: list[str] = []

        def persist_queue(q: BatchSubmissionQueue) -> None:
            events.append("persist:" + q.items[0].status)

        def submit_one(request, ab_config) -> dict:
            events.append("submit")
            return _success_submit(request, ab_config)

        submit_batch_queue_items(
            batch_id="batch-1",
            queue=queue,
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=submit_one,
            persist_queue=persist_queue,
        )

        assert events[0] == f"persist:{BATCH_QUEUE_STATUS_SUBMITTING}"
        assert events[1] == "submit"
        assert events[-1] == f"persist:{BATCH_QUEUE_STATUS_SUCCEEDED}"

    def test_persist_submit_result_receives_request_and_success_result(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        queue = _queue(request_ids=["req-1"])
        calls: list[tuple[str, dict]] = []

        def persist_submit_result(request, ab_result) -> dict:
            calls.append((request["request_id"], deepcopy(ab_result)))
            return request

        result = submit_batch_queue_items(
            batch_id="batch-1",
            queue=queue,
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=_success_submit,
            persist_submit_result=persist_submit_result,
        )

        assert result.items[0].status == SUBMIT_OUTCOME_SUCCEEDED
        assert len(calls) == 1
        assert calls[0][0] == "req-1"
        assert calls[0][1]["success"] is True
        assert calls[0][1]["ab_subscription_id"] == "ab-req-1"
        assert calls[0][1]["ab_response"] == {"id": "ab-req-1"}

    def test_persist_submit_result_receives_failure_result(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        queue = _queue(request_ids=["req-1"])
        calls: list[dict] = []

        def failing_submit(request, ab_config) -> dict:
            return {
                "success": False,
                "ab_subscription_id": None,
                "ab_response": None,
                "fallback_config": None,
                "error": {
                    "error_type": "ab_submit_failed",
                    "error_message": "Auto Bangumi 提交失败",
                    "failed_step": "submit_ab_subscription",
                    "details": {},
                },
            }

        def persist_submit_result(request, ab_result) -> dict:
            calls.append(deepcopy(ab_result))
            return request

        result = submit_batch_queue_items(
            batch_id="batch-1",
            queue=queue,
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=failing_submit,
            persist_submit_result=persist_submit_result,
        )

        assert result.items[0].status == SUBMIT_OUTCOME_FAILED
        assert len(calls) == 1
        assert calls[0]["success"] is False
        assert calls[0]["error"]["error_type"] == "ab_submit_failed"

    def test_persist_submit_result_failure_marks_item_failed_and_continues(
        self,
    ) -> None:
        store = FakeRequestStore(
            [
                _accepted_request(request_id="req-1"),
                _accepted_request(
                    request_id="req-2", title="咒术回战 第三季"
                ),
            ]
        )
        queue = _queue(request_ids=["req-1", "req-2"])

        def persist_submit_result(request, ab_result) -> dict:
            if request["request_id"] == "req-1":
                raise Stage1Error(
                    "storage_error",
                    "保存 Auto Bangumi 提交结果失败",
                    "persist_batch_submit_result",
                    {"request_id": "req-1"},
                )
            return request

        result = submit_batch_queue_items(
            batch_id="batch-1",
            queue=queue,
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=_success_submit,
            persist_submit_result=persist_submit_result,
        )

        # req-1: AB succeeded but persistence failed -> RESULT_PERSIST_FAILED,
        # a dedicated non-retryable state (never a normal FAILED that can be
        # blindly retried into a duplicate subscription).
        assert result.items[0].status == SUBMIT_OUTCOME_FAILED
        assert result.items[0].error_type == SUBMIT_PERSIST_ERROR_TYPE
        assert result.items[0].reason == "保存 Auto Bangumi 提交结果失败"
        assert (
            result.queue.items[0].status
            == BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED
        )
        # req-2 keeps processing and succeeds.
        assert result.items[1].status == SUBMIT_OUTCOME_SUCCEEDED
        assert result.queue.items[1].status == BATCH_QUEUE_STATUS_SUCCEEDED

    def test_retry_persists_submitting_before_submit_and_result(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        failed_item = _retried_queue_item("req-1", status=BATCH_QUEUE_STATUS_FAILED)
        queue = _queue_with_item(failed_item)
        snapshots: list[BatchSubmissionQueue] = []
        calls: list[tuple[str, dict]] = []

        def persist_queue(q: BatchSubmissionQueue) -> None:
            snapshots.append(deepcopy(q))

        def persist_submit_result(request, ab_result) -> dict:
            calls.append((request["request_id"], deepcopy(ab_result)))
            return request

        result = retry_batch_queue_item(
            batch_id="batch-1",
            queue=queue,
            request_id="req-1",
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=_success_submit,
            persist_queue=persist_queue,
            persist_submit_result=persist_submit_result,
        )

        assert result.items[0].status == SUBMIT_OUTCOME_SUCCEEDED
        assert len(snapshots) >= 2
        assert snapshots[0].items[0].status == BATCH_QUEUE_STATUS_SUBMITTING
        assert snapshots[-1].items[0].status == BATCH_QUEUE_STATUS_SUCCEEDED
        assert len(calls) == 1
        assert calls[0][0] == "req-1"
        assert calls[0][1]["success"] is True

    def test_interrupted_submitting_item_is_skipped_not_resubmitted(self) -> None:
        """Regression: a SUBMITTING item persisted by a crashed run is skipped on
        the next submit, so Auto Bangumi is never called twice for it."""
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        queue = _queue_with_item(_submitting_queue_item("req-1"))
        submit_calls: list[str] = []

        def submit_one(request, ab_config) -> dict:
            submit_calls.append(request["request_id"])
            return _success_submit(request, ab_config)

        result = submit_batch_queue_items(
            batch_id="batch-1",
            queue=queue,
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=submit_one,
        )

        assert submit_calls == []
        assert result.items[0].status == SUBMIT_OUTCOME_SKIPPED
        assert result.items[0].reason == "提交中，跳过本次提交"
        assert result.queue.items[0].status == BATCH_QUEUE_STATUS_SUBMITTING


class TestRecoverBatchQueueItem:
    """Explicit recovery for stuck states (SUBMITTING / RESULT_PERSIST_FAILED)."""

    def _recover(
        self,
        queue,
        store,
        request_id: str = "req-1",
        action: str = "auto",
    ):
        return recover_batch_queue_item(
            batch_id="batch-1",
            queue=queue,
            request_id=request_id,
            action=action,
            load_request=store.load,
        )

    def test_auto_recovers_submitting_with_persisted_result(self) -> None:
        request = _accepted_request(request_id="req-1")
        request["ab_submit_result"] = {
            "success": True,
            "ab_subscription_id": "ab-req-1",
            "ab_response": {"id": "ab-req-1"},
            "fallback_config": None,
            "error": None,
        }
        store = FakeRequestStore([request])
        queue = _queue_with_item(_submitting_queue_item("req-1"))

        result = self._recover(queue, store, action=RECOVER_ACTION_AUTO)

        assert result.items[0].status == RECOVER_OUTCOME_SUCCEEDED
        assert result.items[0].reason == "已根据保存的提交结果恢复为提交成功"
        assert result.queue.items[0].status == BATCH_QUEUE_STATUS_SUCCEEDED
        assert "ab_subscription_id=ab-req-1" in (
            result.queue.items[0].ab_result_summary or ""
        )

    def test_auto_needs_manual_without_persisted_result(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        queue = _queue_with_item(_submitting_queue_item("req-1"))

        result = self._recover(queue, store, action=RECOVER_ACTION_AUTO)

        assert result.items[0].status == RECOVER_OUTCOME_NEEDS_MANUAL
        assert result.items[0].error_type == "requires_manual_recovery"
        # The queue is unchanged and stays SUBMITTING.
        assert result.queue.items[0].status == BATCH_QUEUE_STATUS_SUBMITTING

    def test_manual_succeeded_resolves_result_persist_failed(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        queue = _queue_with_item(_result_persist_failed_item("req-1"))

        result = self._recover(queue, store, action=RECOVER_ACTION_SUCCEEDED)

        assert result.items[0].status == RECOVER_OUTCOME_SUCCEEDED
        assert result.items[0].reason == "人工核验确认 Auto Bangumi 已创建订阅，标记为提交成功"
        assert result.queue.items[0].status == BATCH_QUEUE_STATUS_SUCCEEDED

    def test_manual_failed_resolves_submitting_to_retryable_failed(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        queue = _queue_with_item(_submitting_queue_item("req-1"))

        result = self._recover(queue, store, action=RECOVER_ACTION_FAILED)

        assert result.items[0].status == RECOVER_OUTCOME_FAILED
        assert result.queue.items[0].status == BATCH_QUEUE_STATUS_FAILED
        assert result.queue.items[0].last_error == (
            "error_message=人工核验：Auto Bangumi 未创建订阅，标记为可重试失败; "
            "error_type=manual_recovery_failed"
        )

    def test_recover_skips_non_stuck_statuses(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        queue = _queue_with_item(_succeeded_queue_item("req-1"))

        result = self._recover(queue, store, action=RECOVER_ACTION_SUCCEEDED)

        assert result.items[0].status == RECOVER_OUTCOME_SKIPPED
        assert result.items[0].reason == "已提交成功，无需恢复"
        assert result.queue.items[0].status == BATCH_QUEUE_STATUS_SUCCEEDED

    def test_recover_unknown_request_raises(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        queue = _queue(request_ids=["req-1"])

        with pytest.raises(ValueError):
            self._recover(queue, store, request_id="req-unknown")

    def test_recover_invalid_action_raises(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        queue = _queue_with_item(_submitting_queue_item("req-1"))

        with pytest.raises(ValueError):
            self._recover(queue, store, action="invalid")

    def test_result_persist_failed_cannot_be_retried(self) -> None:
        """High-priority regression: RESULT_PERSIST_FAILED must never share the
        normal FAILED retry path (a retry could re-create the subscription)."""
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        queue = _queue_with_item(_result_persist_failed_item("req-1"))
        submit_calls: list[str] = []

        def submit_one(request, ab_config) -> dict:
            submit_calls.append(request["request_id"])
            return _success_submit(request, ab_config)

        result = retry_batch_queue_item(
            batch_id="batch-1",
            queue=queue,
            request_id="req-1",
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=submit_one,
        )

        assert submit_calls == []
        assert result.items[0].status == SUBMIT_OUTCOME_SKIPPED
        assert (
            result.items[0].reason
            == "结果保存失败，需人工核验后恢复，不可直接重试"
        )
        assert (
            result.queue.items[0].status == BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED
        )

    def test_result_persist_failed_item_skipped_in_batch_submit(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        queue = _queue_with_item(_result_persist_failed_item("req-1"))
        submit_calls: list[str] = []

        def submit_one(request, ab_config) -> dict:
            submit_calls.append(request["request_id"])
            return _success_submit(request, ab_config)

        result = submit_batch_queue_items(
            batch_id="batch-1",
            queue=queue,
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=submit_one,
        )

        assert submit_calls == []
        assert result.items[0].status == SUBMIT_OUTCOME_SKIPPED
        assert (
            result.items[0].reason == "结果保存失败，跳过本次提交，请先恢复"
        )
        assert (
            result.queue.items[0].status == BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED
        )


class TestEmptyAndValidation:
    def test_empty_queue_returns_empty_result(self) -> None:
        store = FakeRequestStore([])
        queue = _queue(request_ids=[])

        result = submit_batch_queue_items(
            batch_id="batch-1",
            queue=queue,
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=_success_submit,
        )

        assert result.items == []
        assert result.queue.items == []
        serialized = serialize_batch_submit_result(result)
        assert serialized["summary"] == {
            SUBMIT_OUTCOME_SUCCEEDED: 0,
            SUBMIT_OUTCOME_FAILED: 0,
            SUBMIT_OUTCOME_RETRYABLE: 0,
            SUBMIT_OUTCOME_SKIPPED: 0,
        }

    def test_rejects_empty_batch_id(self) -> None:
        store = FakeRequestStore([])
        queue = _queue(request_ids=[])

        try:
            submit_batch_queue_items(
                batch_id="  ",
                queue=queue,
                ab_config=_ab_config(),
                load_request=store.load,
                submit_one=_success_submit,
            )
        except ValueError as exc:
            assert "batch_id" in str(exc)
        else:  # pragma: no cover - safety boundary
            raise AssertionError("empty batch_id must be rejected")


class TestSerialization:
    def test_serialization_contains_only_safe_fields(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        queue = _queue(request_ids=["req-1"])

        def failing_submit(request, ab_config) -> dict:
            return {
                "success": False,
                "error": {
                    "error_type": "ab_submit_failed",
                    "error_message": "Auto Bangumi HTTP 提交失败",
                    "failed_step": "create_ab_subscription",
                    "details": {"status_code": 503},
                },
            }

        result = submit_batch_queue_items(
            batch_id="batch-1",
            queue=queue,
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=failing_submit,
        )

        serialized = serialize_batch_submit_result(result)
        body = json.dumps(serialized, ensure_ascii=False)

        assert set(serialized) == {"batch_id", "queue", "items", "summary"}
        assert serialized["summary"] == {
            SUBMIT_OUTCOME_SUCCEEDED: 0,
            SUBMIT_OUTCOME_FAILED: 1,
            SUBMIT_OUTCOME_RETRYABLE: 0,
            SUBMIT_OUTCOME_SKIPPED: 0,
        }
        item = serialized["items"][0]
        assert set(item) == {
            "item_id",
            "request_id",
            "title",
            "status",
            "reason",
            "error_type",
            "attempts",
        }
        assert item["status"] == SUBMIT_OUTCOME_FAILED
        assert item["reason"] == "Auto Bangumi HTTP 提交失败"
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
            "ab.example.com",
        ):
            assert keyword not in body
        assert "ab.example.com" not in (result.queue.items[0].last_error or "")


class TestComposeAbSubmitOne:
    def test_composed_submit_one_reuses_existing_ab_contract(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from batch_engine.controllers import batch_submit_controller

        client = FakeAutoBangumiClient()
        monkeypatch.setattr(
            batch_submit_controller.ab_http_client,
            "create_auto_bangumi_http_client",
            lambda config: client,
        )

        submit_one = compose_ab_submit_one()
        ab_config = _ab_config(fallback_enabled=False)
        ab_result = submit_one(
            _accepted_request(request_id="req-1", title="葬送的芙莉莲"),
            ab_config,
        )

        # The existing sanitized result contract is returned unchanged.
        assert ab_result == {
            "success": True,
            "ab_subscription_id": "fake-ab-subscription",
            "ab_response": {"id": "fake-ab-subscription", "status": "created"},
            "fallback_config": None,
            "error": None,
        }
        # The payload came from build_ab_subscription_payload on the ACCEPTED
        # request snapshot.
        assert client.calls == [
            {
                "title": "葬送的芙莉莲",
                "rss_url": "https://mikan.example.com/rss/sub",
                "save_path": "葬送的芙莉莲",
                "filter_rule": {},
            }
        ]
        assert "secret-token" not in json.dumps(ab_result)
        assert "ab.example.com" not in json.dumps(ab_result)

    def test_composed_submit_one_propagates_fallback_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from batch_engine.controllers import batch_submit_controller

        client = FakeAutoBangumiClient(
            error=Stage1Error(
                "ab_submit_failed",
                "离线模拟失败",
                "create_ab_subscription",
                {"status_code": 503},
            )
        )
        monkeypatch.setattr(
            batch_submit_controller.ab_http_client,
            "create_auto_bangumi_http_client",
            lambda config: client,
        )

        submit_one = compose_ab_submit_one()
        ab_result = submit_one(
            _accepted_request(request_id="req-1", title="葬送的芙莉莲"),
            _ab_config(fallback_enabled=True),
        )

        assert ab_result["success"] is False
        assert ab_result["error"]["error_type"] == "ab_submit_failed"
        assert ab_result["fallback_config"] is not None
        assert ab_result["fallback_config"]["title"] == "葬送的芙莉莲"


class TestRetryBatchQueueItem:
    def test_retry_failed_item_succeeds_and_increments_attempts(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        item = _retried_queue_item(
            "req-1", status=BATCH_QUEUE_STATUS_FAILED, attempts=1
        )
        queue = _queue_with_item(item)

        result = retry_batch_queue_item(
            batch_id="batch-1",
            queue=queue,
            request_id="req-1",
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=_success_submit,
            now_factory=_now_factory(
                [
                    "2026-08-19T00:03:00+00:00",
                    "2026-08-19T00:04:00+00:00",
                ]
            ),
        )

        item_result = result.items[0]
        assert item_result.status == SUBMIT_OUTCOME_SUCCEEDED
        assert item_result.attempts == 2
        assert item_result.reason is None
        queue_item = result.queue.items[0]
        assert queue_item.status == BATCH_QUEUE_STATUS_SUCCEEDED
        assert queue_item.attempts == 2
        assert "ab_subscription_id=ab-req-1" in (queue_item.ab_result_summary or "")
        assert queue_item.last_error is None

    def test_retry_retryable_item_succeeds(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        item = _retried_queue_item(
            "req-1", status=BATCH_QUEUE_STATUS_RETRYABLE, attempts=1
        )
        queue = _queue_with_item(item)

        result = retry_batch_queue_item(
            batch_id="batch-1",
            queue=queue,
            request_id="req-1",
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=_success_submit,
        )

        assert result.items[0].status == SUBMIT_OUTCOME_SUCCEEDED
        assert result.queue.items[0].status == BATCH_QUEUE_STATUS_SUCCEEDED
        assert result.queue.items[0].attempts == 2

    def test_retry_timeout_keeps_retryable_and_increments_attempts(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        item = _retried_queue_item(
            "req-1", status=BATCH_QUEUE_STATUS_RETRYABLE, attempts=1
        )
        queue = _queue_with_item(item)

        def timeout_submit(request, ab_config) -> dict:
            return {
                "success": False,
                "error": {
                    "error_type": "ab_timeout",
                    "error_message": "Auto Bangumi HTTP 请求超时",
                    "failed_step": "create_ab_subscription",
                    "details": {"category": "timeout"},
                },
            }

        result = retry_batch_queue_item(
            batch_id="batch-1",
            queue=queue,
            request_id="req-1",
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=timeout_submit,
        )

        item_result = result.items[0]
        assert item_result.status == SUBMIT_OUTCOME_RETRYABLE
        assert item_result.error_type == "ab_timeout"
        assert item_result.attempts == 2
        queue_item = result.queue.items[0]
        assert queue_item.status == BATCH_QUEUE_STATUS_RETRYABLE
        assert queue_item.attempts == 2
        assert "error_type=ab_timeout" in (queue_item.last_error or "")
        assert queue_item.ab_result_summary is None

    def test_retry_terminal_failure_keeps_failed_and_increments_attempts(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        item = _retried_queue_item(
            "req-1", status=BATCH_QUEUE_STATUS_FAILED, attempts=1
        )
        queue = _queue_with_item(item)

        def auth_submit(request, ab_config) -> dict:
            return {
                "success": False,
                "error": {
                    "error_type": "ab_auth_failed",
                    "error_message": "Auto Bangumi 认证失败",
                    "failed_step": "create_ab_subscription",
                    "details": {"status_code": 401},
                },
            }

        result = retry_batch_queue_item(
            batch_id="batch-1",
            queue=queue,
            request_id="req-1",
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=auth_submit,
        )

        item_result = result.items[0]
        assert item_result.status == SUBMIT_OUTCOME_FAILED
        assert item_result.error_type == "ab_auth_failed"
        assert item_result.attempts == 2
        assert result.queue.items[0].status == BATCH_QUEUE_STATUS_FAILED
        assert result.queue.items[0].attempts == 2

    def test_retry_increments_attempts_from_current_count(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        item = _retried_queue_item(
            "req-1", status=BATCH_QUEUE_STATUS_FAILED, attempts=1
        )
        queue = _queue_with_item(item)
        queue = start_queue_item_submit(
            queue, "req-1", now_factory=lambda: "2026-08-19T00:02:00+00:00"
        )
        queue = complete_queue_item_submit(
            queue,
            "req-1",
            BATCH_QUEUE_STATUS_FAILED,
            last_error="再次失败",
            now_factory=lambda: "2026-08-19T00:03:00+00:00",
        )
        assert queue.items[0].attempts == 2

        result = retry_batch_queue_item(
            batch_id="batch-1",
            queue=queue,
            request_id="req-1",
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=_success_submit,
        )

        assert result.items[0].status == SUBMIT_OUTCOME_SUCCEEDED
        assert result.items[0].attempts == 3
        assert result.queue.items[0].attempts == 3

    def test_retry_succeeded_item_is_skipped_without_submit_call(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        succeeded = _succeeded_queue_item("req-1")
        queue = _queue_with_item(succeeded)
        calls: list[str] = []

        def submit_one(request, ab_config) -> dict:
            calls.append(request["request_id"])
            return _success_submit(request, ab_config)

        result = retry_batch_queue_item(
            batch_id="batch-1",
            queue=queue,
            request_id="req-1",
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=submit_one,
        )

        assert calls == []
        assert result.items[0].status == SUBMIT_OUTCOME_SKIPPED
        assert result.items[0].reason == "已提交成功，不可重复提交"
        assert result.items[0].attempts == 1
        assert result.queue.items[0].status == BATCH_QUEUE_STATUS_SUCCEEDED
        assert result.queue.items[0].attempts == 1

    def test_retry_ready_item_is_skipped(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        queue = _queue(request_ids=["req-1"])

        result = retry_batch_queue_item(
            batch_id="batch-1",
            queue=queue,
            request_id="req-1",
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=_success_submit,
        )

        assert result.items[0].status == SUBMIT_OUTCOME_SKIPPED
        assert result.items[0].reason == "尚未提交，无需重试"
        assert result.queue.items[0].status == BATCH_QUEUE_STATUS_READY_TO_SUBMIT
        assert result.queue.items[0].attempts == 0

    def test_retry_submitting_item_is_skipped(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        queue = _queue(request_ids=["req-1"])
        queue = start_queue_item_submit(
            queue, "req-1", now_factory=lambda: "2026-08-19T00:01:00+00:00"
        )

        result = retry_batch_queue_item(
            batch_id="batch-1",
            queue=queue,
            request_id="req-1",
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=_success_submit,
        )

        assert result.items[0].status == SUBMIT_OUTCOME_SKIPPED
        assert result.items[0].reason == "提交中，请先恢复或稍后再试"
        assert result.queue.items[0].status == BATCH_QUEUE_STATUS_SUBMITTING

    def test_retry_missing_request_marks_failed_without_attempt_increment(self) -> None:
        store = FakeRequestStore([])
        item = _retried_queue_item(
            "req-1", status=BATCH_QUEUE_STATUS_FAILED, attempts=1
        )
        queue = _queue_with_item(item)
        called = False

        def submit_one(request, ab_config) -> dict:
            nonlocal called
            called = True
            return _success_submit(request, ab_config)

        result = retry_batch_queue_item(
            batch_id="batch-1",
            queue=queue,
            request_id="req-1",
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=submit_one,
        )

        item_result = result.items[0]
        assert item_result.status == SUBMIT_OUTCOME_FAILED
        assert item_result.reason == "订阅方案不存在或已删除，无法提交"
        assert item_result.error_type == "request_not_found"
        assert item_result.attempts == 1
        assert called is False
        queue_item = result.queue.items[0]
        assert queue_item.status == BATCH_QUEUE_STATUS_FAILED
        assert queue_item.attempts == 1
        assert queue_item.last_error == "订阅方案不存在或已删除，无法提交"

    def test_retry_cancelled_request_marks_failed_without_attempt_increment(self) -> None:
        store = FakeRequestStore(
            [_accepted_request(request_id="req-1", status="CANCELLED")]
        )
        item = _retried_queue_item(
            "req-1", status=BATCH_QUEUE_STATUS_FAILED, attempts=1
        )
        queue = _queue_with_item(item)
        called = False

        def submit_one(request, ab_config) -> dict:
            nonlocal called
            called = True
            return _success_submit(request, ab_config)

        result = retry_batch_queue_item(
            batch_id="batch-1",
            queue=queue,
            request_id="req-1",
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=submit_one,
        )

        assert result.items[0].status == SUBMIT_OUTCOME_FAILED
        assert result.items[0].reason == "订阅方案已取消，无法提交"
        assert result.items[0].error_type == "request_cancelled"
        assert result.items[0].attempts == 1
        assert called is False
        assert result.queue.items[0].status == BATCH_QUEUE_STATUS_FAILED
        assert result.queue.items[0].attempts == 1

    def test_retry_not_accepted_request_marks_retryable_without_attempt_increment(
        self,
    ) -> None:
        store = FakeRequestStore(
            [_accepted_request(request_id="req-1", status="PENDING_CONFIRM")]
        )
        item = _retried_queue_item(
            "req-1", status=BATCH_QUEUE_STATUS_RETRYABLE, attempts=1
        )
        queue = _queue_with_item(item)

        result = retry_batch_queue_item(
            batch_id="batch-1",
            queue=queue,
            request_id="req-1",
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=_success_submit,
        )

        assert result.items[0].status == SUBMIT_OUTCOME_RETRYABLE
        assert result.items[0].reason == "订阅方案尚未确认，无法提交"
        assert result.items[0].error_type == "invalid_request_status"
        assert result.items[0].attempts == 1
        assert result.queue.items[0].status == BATCH_QUEUE_STATUS_RETRYABLE
        assert result.queue.items[0].attempts == 1

    def test_retry_unknown_request_id_raises(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        queue = _queue_with_item(
            _retried_queue_item("req-1", status=BATCH_QUEUE_STATUS_FAILED)
        )

        with pytest.raises(ValueError, match="unknown request_id"):
            retry_batch_queue_item(
                batch_id="batch-1",
                queue=queue,
                request_id="req-missing",
                ab_config=_ab_config(),
                load_request=store.load,
                submit_one=_success_submit,
            )

    def test_retry_stage1_error_is_sanitized(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        item = _retried_queue_item(
            "req-1", status=BATCH_QUEUE_STATUS_RETRYABLE, attempts=1
        )
        queue = _queue_with_item(item)

        def raising_submit_one(request, ab_config) -> dict:
            raise Stage1Error(
                "ab_submit_failed",
                "离线模拟失败",
                "create_ab_subscription",
                {"status_code": 503},
            )

        result = retry_batch_queue_item(
            batch_id="batch-1",
            queue=queue,
            request_id="req-1",
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=raising_submit_one,
        )

        assert result.items[0].status == SUBMIT_OUTCOME_FAILED
        assert result.items[0].reason == "离线模拟失败"
        assert result.items[0].error_type == "ab_submit_failed"
        assert result.items[0].attempts == 2
        assert result.queue.items[0].status == BATCH_QUEUE_STATUS_FAILED

    def test_retry_unexpected_exception_is_sanitized(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        item = _retried_queue_item(
            "req-1", status=BATCH_QUEUE_STATUS_RETRYABLE, attempts=1
        )
        queue = _queue_with_item(item)

        def exploding_submit_one(request, ab_config) -> dict:
            raise RuntimeError(
                "token=secret endpoint=https://ab.example.com path=/home/ghostning"
            )

        result = retry_batch_queue_item(
            batch_id="batch-1",
            queue=queue,
            request_id="req-1",
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=exploding_submit_one,
        )

        item_result = result.items[0]
        assert item_result.status == SUBMIT_OUTCOME_FAILED
        assert item_result.error_type == "unexpected_error"
        assert "secret" not in (item_result.reason or "")
        assert "ab.example.com" not in (item_result.reason or "")
        last_error = result.queue.items[0].last_error or ""
        assert "secret" not in last_error
        assert "ab.example.com" not in last_error
        assert "/home/ghostning" not in last_error

    def test_retry_uses_latest_saved_request_snapshot(self) -> None:
        # The queue still references the original title, but the retry must
        # re-load the latest saved ACCEPTED Request snapshot instead.
        store = FakeRequestStore(
            [_accepted_request(request_id="req-1", title="葬送的芙莉莲·新版")]
        )
        item = _retried_queue_item(
            "req-1", status=BATCH_QUEUE_STATUS_FAILED, attempts=1
        )
        queue = _queue_with_item(item)
        submitted: list[str] = []

        def submit_one(request, ab_config) -> dict:
            submitted.append(request["input"]["raw_title"])
            return _success_submit(request, ab_config)

        result = retry_batch_queue_item(
            batch_id="batch-1",
            queue=queue,
            request_id="req-1",
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=submit_one,
        )

        assert submitted == ["葬送的芙莉莲·新版"]
        assert "葬送的芙莉莲·新版" not in (queue.items[0].title or "")
        assert result.queue.items[0].title == "标题-req-1"

    def test_retry_never_uses_queue_copied_secrets(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        # Simulate a maliciously populated queue item carrying copied secrets.
        poisoned = _retried_queue_item(
            "req-1", status=BATCH_QUEUE_STATUS_FAILED, attempts=1
        )
        poisoned = BatchQueueItem(
            queue_id=poisoned.queue_id,
            batch_id=poisoned.batch_id,
            item_id=poisoned.item_id,
            request_id=poisoned.request_id,
            title=(
                "https://mikan.example.com/rss/secret token=leaked "
                "cookie=sid=abc magnet:?xt=urn:btih:deadbeef"
            ),
            status=poisoned.status,
            attempts=poisoned.attempts,
            last_error=(
                "endpoint=https://ab.example.com token=leaked raw_rss=<rss>secret"
            ),
            ab_result_summary=None,
            created_at=poisoned.created_at,
            updated_at=poisoned.updated_at,
        )
        queue = _queue_with_item(poisoned)
        submitted_titles: list[str] = []

        def submit_one(request, ab_config) -> dict:
            submitted_titles.append(request["input"]["raw_title"])
            return _success_submit(request, ab_config)

        result = retry_batch_queue_item(
            batch_id="batch-1",
            queue=queue,
            request_id="req-1",
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=submit_one,
        )

        # The retry submits from the fresh Request snapshot, never the
        # queue-copied title/summary, and never leaks the copied secrets through
        # the queue/result serialization boundary.
        assert submitted_titles == ["葬送的芙莉莲"]
        serialized = json.dumps(serialize_batch_submit_result(result), ensure_ascii=False)
        for keyword in (
            "endpoint",
            "token",
            "cookie",
            "authorization",
            "password",
            "passwd",
            "bearer",
            "raw_html",
            "raw_rss",
            "response_body",
            "magnet",
            "mikan.example.com",
            "ab.example.com",
            "leaked",
            "deadbeef",
            "sid=abc",
        ):
            assert keyword not in serialized
        assert result.items[0].reason is None

    def test_retry_leaves_sibling_items_unchanged(self) -> None:
        store = FakeRequestStore(
            [
                _accepted_request(request_id="req-1"),
                _accepted_request(request_id="req-2"),
            ]
        )
        failed = _retried_queue_item(
            "req-1", status=BATCH_QUEUE_STATUS_FAILED, attempts=1
        )
        succeeded = _succeeded_queue_item("req-2")
        queue = _queue_with_items([failed, succeeded])

        result = retry_batch_queue_item(
            batch_id="batch-1",
            queue=queue,
            request_id="req-1",
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=_success_submit,
        )

        assert result.items[0].status == SUBMIT_OUTCOME_SUCCEEDED
        # The retried item changed.
        assert result.queue.items[0].status == BATCH_QUEUE_STATUS_SUCCEEDED
        assert result.queue.items[0].attempts == 2
        # The succeeded sibling is untouched.
        assert result.queue.items[1].status == BATCH_QUEUE_STATUS_SUCCEEDED
        assert result.queue.items[1].attempts == 1
        assert "ab_subscription_id=ab-1" in (
            result.queue.items[1].ab_result_summary or ""
        )

    def test_retry_serialization_contains_only_safe_fields(self) -> None:
        store = FakeRequestStore([_accepted_request(request_id="req-1")])
        item = _retried_queue_item(
            "req-1", status=BATCH_QUEUE_STATUS_RETRYABLE, attempts=1
        )
        queue = _queue_with_item(item)

        def timeout_submit(request, ab_config) -> dict:
            return {
                "success": False,
                "error": {
                    "error_type": "ab_timeout",
                    "error_message": "Auto Bangumi HTTP 请求超时",
                    "failed_step": "create_ab_subscription",
                    "details": {"category": "timeout"},
                },
            }

        result = retry_batch_queue_item(
            batch_id="batch-1",
            queue=queue,
            request_id="req-1",
            ab_config=_ab_config(),
            load_request=store.load,
            submit_one=timeout_submit,
        )

        serialized = serialize_batch_submit_result(result)
        body = json.dumps(serialized, ensure_ascii=False)
        assert set(serialized) == {"batch_id", "queue", "items", "summary"}
        assert serialized["summary"] == {
            SUBMIT_OUTCOME_SUCCEEDED: 0,
            SUBMIT_OUTCOME_FAILED: 0,
            SUBMIT_OUTCOME_RETRYABLE: 1,
            SUBMIT_OUTCOME_SKIPPED: 0,
        }
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
            "ab.example.com",
            "secret-token",
        ):
            assert keyword not in body
        assert "ab.example.com" not in (result.queue.items[0].last_error or "")
