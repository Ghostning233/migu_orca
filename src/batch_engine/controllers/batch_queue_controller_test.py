from __future__ import annotations

from copy import deepcopy
import json

import pytest

from batch_engine.controllers.batch_queue_controller import (
    complete_queue_item_submit,
    create_submission_queue,
    enqueue_item,
    mark_queue_item_failed,
    mark_queue_item_retry_failed,
    sanitize_queue_summary,
    serialize_queue,
    serialize_queue_item,
    start_queue_item_submit,
)
from batch_engine.models import (
    BATCH_QUEUE_STATUS_FAILED,
    BATCH_QUEUE_STATUS_LABELS,
    BATCH_QUEUE_STATUS_READY_TO_SUBMIT,
    BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED,
    BATCH_QUEUE_STATUS_RETRYABLE,
    BATCH_QUEUE_STATUS_SUBMITTING,
    BATCH_QUEUE_STATUS_SUCCEEDED,
    BATCH_QUEUE_TRANSITIONS,
    BatchQueueItem,
    BatchSubmissionQueue,
)


def _id_factory(values: list[str]):
    ids = iter(values)
    return lambda: next(ids)


def _now_factory(values: list[str]):
    stamps = iter(values)
    return lambda: next(stamps)


def _queue(*, queue_id: str = "queue-1", batch_id: str = "batch-1") -> BatchSubmissionQueue:
    return BatchSubmissionQueue(
        queue_id=queue_id,
        batch_id=batch_id,
        items=[],
        created_at="2026-08-19T00:00:00+00:00",
        updated_at="2026-08-19T00:00:00+00:00",
    )


def _item(
    *,
    request_id: str,
    status: str = BATCH_QUEUE_STATUS_READY_TO_SUBMIT,
    attempts: int = 0,
    queue_id: str = "queue-1",
    batch_id: str = "batch-1",
    item_id: str = "item-1",
) -> BatchQueueItem:
    return BatchQueueItem(
        queue_id=queue_id,
        batch_id=batch_id,
        item_id=item_id,
        request_id=request_id,
        title="葬送的芙莉莲",
        status=status,
        attempts=attempts,
        created_at="2026-08-19T00:00:00+00:00",
        updated_at="2026-08-19T00:00:00+00:00",
    )


def _queue_with(item: BatchQueueItem) -> BatchSubmissionQueue:
    return BatchSubmissionQueue(
        queue_id=item.queue_id,
        batch_id=item.batch_id,
        items=[item],
        created_at="2026-08-19T00:00:00+00:00",
        updated_at="2026-08-19T00:00:00+00:00",
    )


class TestCreateSubmissionQueue:
    def test_creates_empty_queue_with_generated_id(self) -> None:
        queue = create_submission_queue(
            "batch-1",
            queue_id_factory=_id_factory(["queue-abc"]),
            now_factory=_now_factory(["2026-08-19T00:00:00+00:00"]),
        )

        assert queue.queue_id == "queue-abc"
        assert queue.batch_id == "batch-1"
        assert queue.items == []
        assert queue.created_at == "2026-08-19T00:00:00+00:00"
        assert queue.updated_at == "2026-08-19T00:00:00+00:00"

    def test_creates_default_uuid_queue_id(self) -> None:
        queue = create_submission_queue("batch-1")

        assert queue.queue_id.startswith("queue-")
        assert queue.items == []

    def test_rejects_empty_batch_id(self) -> None:
        with pytest.raises(ValueError, match="batch_id"):
            create_submission_queue("   ")


class TestEnqueueItem:
    def test_adds_ready_item_to_queue(self) -> None:
        queue = enqueue_item(
            _queue(),
            item_id="item-1",
            request_id="req-1",
            title="  葬送的芙莉莲  ",
            now_factory=_now_factory(["2026-08-19T01:00:00+00:00"]),
        )

        assert len(queue.items) == 1
        item = queue.items[0]
        assert item.queue_id == "queue-1"
        assert item.batch_id == "batch-1"
        assert item.item_id == "item-1"
        assert item.request_id == "req-1"
        assert item.title == "葬送的芙莉莲"
        assert item.status == BATCH_QUEUE_STATUS_READY_TO_SUBMIT
        assert item.attempts == 0
        assert item.last_error is None
        assert item.ab_result_summary is None
        assert item.created_at == "2026-08-19T01:00:00+00:00"
        assert item.updated_at == "2026-08-19T01:00:00+00:00"
        assert queue.updated_at == "2026-08-19T01:00:00+00:00"

    def test_enqueue_is_idempotent_by_request_id(self) -> None:
        base = enqueue_item(
            _queue(),
            item_id="item-1",
            request_id="req-1",
            title="葬送的芙莉莲",
        )
        repeated = enqueue_item(
            base,
            item_id="item-1",
            request_id="req-1",
            title="葬送的芙莉莲",
        )

        assert len(repeated.items) == 1
        assert repeated == base

    def test_enqueue_adds_distinct_items_for_distinct_request_ids(self) -> None:
        queue = enqueue_item(
            _queue(),
            item_id="item-1",
            request_id="req-1",
            title="葬送的芙莉莲",
        )
        queue = enqueue_item(
            queue,
            item_id="item-2",
            request_id="req-2",
            title="咒术回战 第三季",
        )

        assert [item.request_id for item in queue.items] == ["req-1", "req-2"]

    def test_rejects_empty_item_id(self) -> None:
        with pytest.raises(ValueError, match="item_id"):
            enqueue_item(
                _queue(),
                item_id="  ",
                request_id="req-1",
                title="葬送的芙莉莲",
            )

    def test_rejects_empty_request_id(self) -> None:
        with pytest.raises(ValueError, match="request_id"):
            enqueue_item(
                _queue(),
                item_id="item-1",
                request_id=" ",
                title="葬送的芙莉莲",
            )

    def test_rejects_empty_title(self) -> None:
        with pytest.raises(ValueError, match="title"):
            enqueue_item(
                _queue(),
                item_id="item-1",
                request_id="req-1",
                title="  ",
            )


class TestStatusTransitions:
    def test_start_submit_moves_ready_item_to_submitting_and_increments_attempts(self) -> None:
        queue = start_queue_item_submit(
            _queue_with(_item(request_id="req-1")),
            "req-1",
            now_factory=_now_factory(["2026-08-19T02:00:00+00:00"]),
        )

        item = queue.items[0]
        assert item.status == BATCH_QUEUE_STATUS_SUBMITTING
        assert item.attempts == 1
        assert item.updated_at == "2026-08-19T02:00:00+00:00"

    def test_start_submit_retries_failed_and_retryable_items(self) -> None:
        for status in (BATCH_QUEUE_STATUS_FAILED, BATCH_QUEUE_STATUS_RETRYABLE):
            base = _queue_with(
                _item(request_id="req-1", status=status, attempts=1)
            )
            queue = start_queue_item_submit(base, "req-1")

            assert queue.items[0].status == BATCH_QUEUE_STATUS_SUBMITTING
            assert queue.items[0].attempts == 2

    def test_start_submit_rejects_succeeded_items(self) -> None:
        base = _queue_with(
            _item(request_id="req-1", status=BATCH_QUEUE_STATUS_SUCCEEDED)
        )

        with pytest.raises(ValueError, match="invalid queue transition"):
            start_queue_item_submit(base, "req-1")

    def test_start_submit_unknown_request_id_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown request_id"):
            start_queue_item_submit(_queue(), "req-missing")

    def test_complete_submit_success_stores_sanitized_summary(self) -> None:
        base = _queue_with(
            _item(request_id="req-1", status=BATCH_QUEUE_STATUS_SUBMITTING, attempts=1)
        )
        queue = complete_queue_item_submit(
            base,
            "req-1",
            BATCH_QUEUE_STATUS_SUCCEEDED,
            ab_result_summary={"ab_subscription_id": "sub-123", "note": "成功"},
            now_factory=_now_factory(["2026-08-19T03:00:00+00:00"]),
        )

        item = queue.items[0]
        assert item.status == BATCH_QUEUE_STATUS_SUCCEEDED
        assert item.attempts == 1
        assert item.ab_result_summary == "ab_subscription_id=sub-123; note=成功"
        assert item.last_error is None
        assert item.updated_at == "2026-08-19T03:00:00+00:00"

    def test_complete_submit_failure_stores_sanitized_error(self) -> None:
        for status in (BATCH_QUEUE_STATUS_FAILED, BATCH_QUEUE_STATUS_RETRYABLE):
            base = _queue_with(
                _item(request_id="req-1", status=BATCH_QUEUE_STATUS_SUBMITTING, attempts=1)
            )
            queue = complete_queue_item_submit(
                base,
                "req-1",
                status,
                last_error={"category": "timeout", "status_code": 504},
            )

            item = queue.items[0]
            assert item.status == status
            assert item.last_error == "category=timeout; status_code=504"
            assert item.ab_result_summary is None

    def test_complete_submit_rejects_invalid_result_status(self) -> None:
        base = _queue_with(
            _item(request_id="req-1", status=BATCH_QUEUE_STATUS_SUBMITTING)
        )

        with pytest.raises(ValueError, match="invalid queue result status"):
            complete_queue_item_submit(base, "req-1", BATCH_QUEUE_STATUS_READY_TO_SUBMIT)

    def test_complete_submit_rejects_non_submitting_item(self) -> None:
        base = _queue_with(_item(request_id="req-1"))

        with pytest.raises(ValueError, match="invalid queue transition"):
            complete_queue_item_submit(base, "req-1", BATCH_QUEUE_STATUS_SUCCEEDED)

    def test_complete_submit_rejects_succeeded_terminal_item(self) -> None:
        base = _queue_with(
            _item(request_id="req-1", status=BATCH_QUEUE_STATUS_SUCCEEDED)
        )

        with pytest.raises(ValueError, match="invalid queue transition"):
            complete_queue_item_submit(base, "req-1", BATCH_QUEUE_STATUS_SUCCEEDED)

    def test_mark_queue_item_failed_marks_ready_item_without_attempt(self) -> None:
        base = _queue_with(_item(request_id="req-1"))
        queue = mark_queue_item_failed(
            base,
            "req-1",
            status=BATCH_QUEUE_STATUS_RETRYABLE,
            last_error={"category": "not_accepted"},
        )

        item = queue.items[0]
        assert item.status == BATCH_QUEUE_STATUS_RETRYABLE
        assert item.attempts == 0
        assert item.last_error == "category=not_accepted"
        assert item.ab_result_summary is None

    def test_mark_queue_item_failed_defaults_to_failed_status(self) -> None:
        base = _queue_with(_item(request_id="req-1"))
        queue = mark_queue_item_failed(base, "req-1", last_error="已取消")

        assert queue.items[0].status == BATCH_QUEUE_STATUS_FAILED
        assert queue.items[0].last_error == "已取消"

    def test_mark_queue_item_failed_rejects_succeeded_items(self) -> None:
        base = _queue_with(
            _item(request_id="req-1", status=BATCH_QUEUE_STATUS_SUCCEEDED)
        )

        with pytest.raises(ValueError, match="only READY_TO_SUBMIT"):
            mark_queue_item_failed(base, "req-1")

    def test_mark_queue_item_failed_rejects_submitting_items(self) -> None:
        base = _queue_with(
            _item(request_id="req-1", status=BATCH_QUEUE_STATUS_SUBMITTING)
        )

        with pytest.raises(ValueError, match="only READY_TO_SUBMIT"):
            mark_queue_item_failed(base, "req-1")


class TestMarkQueueItemRetryFailed:
    def test_updates_failed_item_without_incrementing_attempts(self) -> None:
        base = _queue_with(
            _item(request_id="req-1", status=BATCH_QUEUE_STATUS_FAILED, attempts=2)
        )
        queue = mark_queue_item_retry_failed(
            base,
            "req-1",
            status=BATCH_QUEUE_STATUS_RETRYABLE,
            last_error={"category": "request_not_found"},
            now_factory=_now_factory(["2026-08-19T04:00:00+00:00"]),
        )

        item = queue.items[0]
        assert item.status == BATCH_QUEUE_STATUS_RETRYABLE
        assert item.attempts == 2
        assert item.last_error == "category=request_not_found"
        assert item.ab_result_summary is None
        assert item.updated_at == "2026-08-19T04:00:00+00:00"

    def test_updates_retryable_item_defaulting_to_failed(self) -> None:
        base = _queue_with(
            _item(request_id="req-1", status=BATCH_QUEUE_STATUS_RETRYABLE, attempts=1)
        )
        queue = mark_queue_item_retry_failed(base, "req-1", last_error="已取消")

        assert queue.items[0].status == BATCH_QUEUE_STATUS_FAILED
        assert queue.items[0].attempts == 1
        assert queue.items[0].last_error == "已取消"

    def test_sanitizes_sensitive_error_values(self) -> None:
        base = _queue_with(
            _item(request_id="req-1", status=BATCH_QUEUE_STATUS_FAILED, attempts=1)
        )
        queue = mark_queue_item_retry_failed(
            base,
            "req-1",
            last_error={
                "token": "super-secret-token",
                "cookie": "sid=abc123",
                "category": "request_cancelled",
            },
        )

        assert queue.items[0].last_error == "category=request_cancelled"
        assert "super-secret-token" not in (queue.items[0].last_error or "")
        assert "sid=abc123" not in (queue.items[0].last_error or "")

    def test_rejects_ready_items(self) -> None:
        base = _queue_with(_item(request_id="req-1"))

        with pytest.raises(ValueError, match="only FAILED/RETRYABLE"):
            mark_queue_item_retry_failed(base, "req-1")

    def test_rejects_submitting_items(self) -> None:
        base = _queue_with(
            _item(request_id="req-1", status=BATCH_QUEUE_STATUS_SUBMITTING)
        )

        with pytest.raises(ValueError, match="only FAILED/RETRYABLE"):
            mark_queue_item_retry_failed(base, "req-1")

    def test_rejects_succeeded_items(self) -> None:
        base = _queue_with(
            _item(request_id="req-1", status=BATCH_QUEUE_STATUS_SUCCEEDED)
        )

        with pytest.raises(ValueError, match="only FAILED/RETRYABLE"):
            mark_queue_item_retry_failed(base, "req-1")

    def test_rejects_invalid_target_status(self) -> None:
        base = _queue_with(
            _item(request_id="req-1", status=BATCH_QUEUE_STATUS_FAILED)
        )

        with pytest.raises(ValueError, match="invalid retry failure status"):
            mark_queue_item_retry_failed(base, "req-1", status=BATCH_QUEUE_STATUS_SUCCEEDED)

    def test_unknown_request_id_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown request_id"):
            mark_queue_item_retry_failed(_queue(), "req-missing")

    def test_only_target_item_changes(self) -> None:
        base = enqueue_item(
            _queue(),
            item_id="item-1",
            request_id="req-1",
            title="葬送的芙莉莲",
        )
        base = enqueue_item(
            base,
            item_id="item-2",
            request_id="req-2",
            title="咒术回战 第三季",
        )
        base = start_queue_item_submit(base, "req-1")
        base = complete_queue_item_submit(
            base,
            "req-1",
            BATCH_QUEUE_STATUS_FAILED,
            last_error={"category": "timeout"},
        )

        queue = mark_queue_item_retry_failed(base, "req-1", last_error="request_not_found")

        assert queue.items[0].status == BATCH_QUEUE_STATUS_FAILED
        assert queue.items[0].last_error == "request_not_found"
        assert queue.items[1].status == BATCH_QUEUE_STATUS_READY_TO_SUBMIT
        assert queue.items[1].last_error is None


class TestStatusLabels:
    def test_chinese_labels_cover_every_supported_status(self) -> None:
        assert BATCH_QUEUE_STATUS_LABELS == {
            BATCH_QUEUE_STATUS_READY_TO_SUBMIT: "待提交",
            BATCH_QUEUE_STATUS_SUBMITTING: "提交中",
            BATCH_QUEUE_STATUS_SUCCEEDED: "提交成功",
            BATCH_QUEUE_STATUS_FAILED: "提交失败",
            BATCH_QUEUE_STATUS_RETRYABLE: "可重试",
            BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED: "结果保存失败",
        }

    def test_transition_table_allows_retry_and_blocks_succeeded(self) -> None:
        assert BATCH_QUEUE_STATUS_SUBMITTING in BATCH_QUEUE_TRANSITIONS[
            BATCH_QUEUE_STATUS_READY_TO_SUBMIT
        ]
        assert BATCH_QUEUE_STATUS_FAILED in BATCH_QUEUE_TRANSITIONS[
            BATCH_QUEUE_STATUS_SUBMITTING
        ]
        assert BATCH_QUEUE_STATUS_RETRYABLE in BATCH_QUEUE_TRANSITIONS[
            BATCH_QUEUE_STATUS_SUBMITTING
        ]
        assert BATCH_QUEUE_STATUS_SUCCEEDED in BATCH_QUEUE_TRANSITIONS[
            BATCH_QUEUE_STATUS_SUBMITTING
        ]
        assert BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED in BATCH_QUEUE_TRANSITIONS[
            BATCH_QUEUE_STATUS_SUBMITTING
        ]
        assert BATCH_QUEUE_STATUS_SUBMITTING in BATCH_QUEUE_TRANSITIONS[
            BATCH_QUEUE_STATUS_FAILED
        ]
        assert BATCH_QUEUE_STATUS_SUBMITTING in BATCH_QUEUE_TRANSITIONS[
            BATCH_QUEUE_STATUS_RETRYABLE
        ]
        # RESULT_PERSIST_FAILED is never auto-retried; it can only be resolved
        # through explicit recovery (SUCCEEDED after manual verification, FAILED
        # when Auto Bangumi did not create the subscription).
        assert BATCH_QUEUE_STATUS_SUBMITTING not in BATCH_QUEUE_TRANSITIONS[
            BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED
        ]
        assert BATCH_QUEUE_STATUS_SUCCEEDED in BATCH_QUEUE_TRANSITIONS[
            BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED
        ]
        assert BATCH_QUEUE_STATUS_FAILED in BATCH_QUEUE_TRANSITIONS[
            BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED
        ]
        assert BATCH_QUEUE_TRANSITIONS[BATCH_QUEUE_STATUS_SUCCEEDED] == frozenset()


class TestSanitizeQueueSummary:
    def test_redacts_endpoint_token_cookie_authorization_and_magnet(self) -> None:
        summary = sanitize_queue_summary(
            {
                "endpoint": "https://ab.example.com/api",
                "token": "super-secret-token",
                "cookie": "sid=abc123",
                "authorization": "Bearer abc.def",
                "category": "http_failed",
            }
        )

        assert summary is not None
        assert summary == "category=http_failed"
        assert "https://" not in summary
        assert "super-secret-token" not in summary
        assert "sid=abc123" not in summary
        assert "Bearer" not in summary
        assert "endpoint" not in summary
        assert "token" not in summary
        assert "cookie" not in summary
        assert "authorization" not in summary

    def test_redacts_full_rss_url_and_raw_response_body(self) -> None:
        summary = sanitize_queue_summary(
            {
                "error": "parse failed",
                "rss_url": "https://mikanani.me/RSS/Search?searchstr=%E8%8A%99%E8%8E%89",
                "raw_response_body": "<rss version='2.0'><channel>secret</channel></rss>",
            }
        )

        assert summary == "error=parse failed"
        assert "mikanani" not in summary
        assert "<rss" not in summary
        assert "channel" not in summary

    def test_redacts_local_absolute_paths(self) -> None:
        summary = sanitize_queue_summary(
            "读取本地文件失败 /home/ghostning/storage/requests/req-1.json"
        )

        assert "ghostning" not in summary
        assert "storage" not in summary

    def test_redacts_magnet_uri_string(self) -> None:
        summary = sanitize_queue_summary("magnet:?xt=urn:btih:deadbeef&dn=secret")

        assert summary is not None
        assert "deadbeef" not in summary
        assert "magnet" not in summary
        assert "urn:btih" not in summary

    def test_returns_fallback_for_none_and_empty_values(self) -> None:
        assert sanitize_queue_summary(None, fallback="Auto Bangumi 提交失败") == (
            "Auto Bangumi 提交失败"
        )
        assert sanitize_queue_summary("", fallback="Auto Bangumi 提交失败") == (
            "Auto Bangumi 提交失败"
        )
        assert sanitize_queue_summary({"token": "secret"}) is None

    def test_keeps_readable_non_sensitive_summary(self) -> None:
        summary = sanitize_queue_summary(
            {"error_type": "ab_http_failed", "status_code": 500}
        )

        assert summary == "error_type=ab_http_failed; status_code=500"


class TestSerializationBoundary:
    def test_serialize_queue_contains_only_safe_fields(self) -> None:
        queue = enqueue_item(
            _queue(),
            item_id="item-1",
            request_id="req-1",
            title="葬送的芙莉莲",
        )
        queue = start_queue_item_submit(queue, "req-1")
        queue = complete_queue_item_submit(
            queue,
            "req-1",
            BATCH_QUEUE_STATUS_SUCCEEDED,
            ab_result_summary={"ab_subscription_id": "sub-1"},
        )

        serialized = serialize_queue(queue)

        assert set(serialized) == {
            "queue_id",
            "batch_id",
            "created_at",
            "updated_at",
            "items",
        }
        item = serialized["items"][0]
        assert set(item) == {
            "queue_id",
            "batch_id",
            "item_id",
            "request_id",
            "title",
            "status",
            "status_label",
            "attempts",
            "last_error",
            "ab_result_summary",
            "created_at",
            "updated_at",
        }
        assert item["status"] == BATCH_QUEUE_STATUS_SUCCEEDED
        assert item["status_label"] == "提交成功"
        assert item["ab_result_summary"] == "ab_subscription_id=sub-1"

    def test_serialize_queue_item_status_label_uses_chinese(self) -> None:
        item = _item(request_id="req-1", status=BATCH_QUEUE_STATUS_RETRYABLE)

        serialized = serialize_queue_item(item)

        assert serialized["status"] == BATCH_QUEUE_STATUS_RETRYABLE
        assert serialized["status_label"] == "可重试"

    def test_serialization_defensively_redacts_directly_constructed_items(self) -> None:
        # A directly constructed item with raw values must still serialize safe,
        # including a poisoned title carrying a copied RSS URL and token.
        raw_item = BatchQueueItem(
            queue_id="queue-1",
            batch_id="batch-1",
            item_id="item-1",
            request_id="req-1",
            title="https://mikanani.me/RSS/Search?searchstr=x token=abc123",
            status=BATCH_QUEUE_STATUS_FAILED,
            attempts=1,
            last_error=(
                "token=abc123 endpoint=https://ab.example.com "
                "magnet:?xt=urn:btih:deadbeef"
            ),
            ab_result_summary="https://mikanani.me/RSS/Search?searchstr=x",
        )

        serialized = serialize_queue_item(raw_item)
        joined = " ".join(
            f"{key}={value}"
            for key, value in serialized.items()
            if value is not None
        )

        assert "abc123" not in joined
        assert "ab.example.com" not in joined
        assert "deadbeef" not in joined
        assert "mikanani" not in joined
        assert "https://" not in joined
        assert "magnet" not in joined

    def test_serialized_item_never_contains_sensitive_keywords(self) -> None:
        queue = enqueue_item(
            _queue(),
            item_id="item-1",
            request_id="req-1",
            title="葬送的芙莉莲",
        )

        serialized = json.dumps(serialize_queue(queue), ensure_ascii=False)

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
        ):
            assert keyword not in serialized

    def test_original_queue_item_is_unchanged_by_transitions(self) -> None:
        base = _queue_with(_item(request_id="req-1"))
        started = start_queue_item_submit(base, "req-1")

        assert base.items[0].status == BATCH_QUEUE_STATUS_READY_TO_SUBMIT
        assert started.items[0].status == BATCH_QUEUE_STATUS_SUBMITTING

    def test_deep_copy_helpers_do_not_share_mutable_items(self) -> None:
        queue = enqueue_item(
            _queue(),
            item_id="item-1",
            request_id="req-1",
            title="葬送的芙莉莲",
        )
        copied = deepcopy(queue)

        assert copied == queue
        assert copied.items[0] is not queue.items[0]
