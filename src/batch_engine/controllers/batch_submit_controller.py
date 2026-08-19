"""Stage 20 batch Auto Bangumi sequential submit service.

Pure orchestration that processes a batch pre-submission queue sequentially
with a request-scoped Auto Bangumi config. Each READY_TO_SUBMIT item is
validated (its Request must still be ACCEPTED), moved to SUBMITTING, submitted
through an injected ``submit_one`` callable, and finalized as
SUCCEEDED/FAILED/RETRYABLE with a sanitized one-line result/error summary.
Items that are already SUCCEEDED are never re-submitted, and one item's failure
never blocks the rest of the batch.

The service stays decoupled from the apps layer: ``submit_one(request,
ab_config)`` returns the existing sanitized ``ab_submit_result`` contract
(success, ab_subscription_id, ab_response, fallback_config, error).
``compose_ab_submit_one`` builds that callable from the existing Auto Bangumi
payload/client/submit primitives (the batch-domain equivalent of
``apply_ab_submit_action``'s AB portion) so later API/UI layers can wire the
real path without reimplementing payload or client logic. Auto Bangumi secrets
live only in the request-scoped ``ab_config`` and never reach the queue.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ab_engine.controllers import ab_http_client
from ab_engine.controllers.ab_client import submit_ab_subscription
from ab_engine.controllers.subscription_payload import build_ab_subscription_payload
from batch_engine.controllers.batch_queue_controller import (
    NowFactory,
    complete_queue_item_submit,
    mark_queue_item_failed,
    sanitize_queue_summary,
    serialize_queue,
    start_queue_item_submit,
)
from batch_engine.models.queue import (
    BATCH_QUEUE_STATUS_FAILED,
    BATCH_QUEUE_STATUS_READY_TO_SUBMIT,
    BATCH_QUEUE_STATUS_RETRYABLE,
    BATCH_QUEUE_STATUS_SUBMITTING,
    BATCH_QUEUE_STATUS_SUCCEEDED,
    BatchQueueItem,
    BatchSubmissionQueue,
)
from request_engine.controllers.request_controller import ACCEPTED, CANCELLED
from shared.errors import Stage1Error

#: Per-item outcome statuses returned by the batch submit orchestration.
SUBMIT_OUTCOME_SUCCEEDED = "succeeded"
SUBMIT_OUTCOME_FAILED = "failed"
SUBMIT_OUTCOME_RETRYABLE = "retryable"
SUBMIT_OUTCOME_SKIPPED = "skipped"

#: Transient Auto Bangumi errors that can be retried with the same config.
_RETRYABLE_SUBMIT_ERROR_TYPES = frozenset(
    {"ab_timeout", "ab_connection_failed"}
)

LoadRequest = Callable[[str], dict[str, Any] | None]
SubmitOne = Callable[[dict[str, Any], Any], dict[str, Any]]


@dataclass(frozen=True)
class BatchSubmitItemResult:
    """Outcome of submitting one queue item."""

    item_id: str
    request_id: str
    title: str | None
    status: str
    reason: str | None = None
    error_type: str | None = None
    attempts: int = 0


@dataclass(frozen=True)
class BatchSubmitResult:
    """The submitted batch plus the updated pre-submission queue."""

    batch_id: str
    queue: BatchSubmissionQueue
    items: list[BatchSubmitItemResult]


def submit_batch_queue_items(
    *,
    batch_id: str,
    queue: BatchSubmissionQueue,
    ab_config: Any,
    load_request: LoadRequest,
    submit_one: SubmitOne,
    now_factory: NowFactory | None = None,
) -> BatchSubmitResult:
    """Process READY_TO_SUBMIT queue items sequentially against Auto Bangumi.

    Already-SUCCEEDED items and items not in READY_TO_SUBMIT are skipped without
    any submit call; pre-submit validation (the Request must still be ACCEPTED)
    and per-item submit failures mark the item FAILED or RETRYABLE and never
    block the rest of the batch.
    """
    clean_batch_id = _non_empty("batch_id", batch_id)
    next_queue = queue
    results: list[BatchSubmitItemResult] = []
    for item in queue.items:
        item_result, next_queue = _submit_one_item(
            item,
            next_queue,
            ab_config=ab_config,
            load_request=load_request,
            submit_one=submit_one,
            now_factory=now_factory,
        )
        results.append(item_result)
    return BatchSubmitResult(
        batch_id=clean_batch_id,
        queue=next_queue,
        items=results,
    )


def compose_ab_submit_one() -> SubmitOne:
    """Build the standard ``submit_one`` from the existing AB primitives.

    Mirrors the AB portion of ``apply_ab_submit_action``: build the subscription
    payload from the ACCEPTED Request snapshot, create a request-scoped Auto
    Bangumi HTTP client from the config, and normalize the response through the
    existing sanitized ``ab_submit_result`` contract.
    """

    def submit_one(request: dict[str, Any], ab_config: Any) -> dict[str, Any]:
        payload = build_ab_subscription_payload(request)
        client = ab_http_client.create_auto_bangumi_http_client(ab_config)
        return submit_ab_subscription(
            client,
            payload,
            fallback_enabled=_fallback_enabled(ab_config),
        )

    return submit_one


def serialize_batch_submit_item(item: BatchSubmitItemResult) -> dict[str, Any]:
    return {
        "item_id": item.item_id,
        "request_id": item.request_id,
        "title": sanitize_queue_summary(item.title) or item.title,
        "status": item.status,
        "reason": item.reason,
        "error_type": item.error_type,
        "attempts": item.attempts,
    }


def serialize_batch_submit_result(result: BatchSubmitResult) -> dict[str, Any]:
    """Serialize a batch submit result with only non-sensitive, public fields.

    The queue is re-serialized through ``serialize_queue`` so even a directly
    constructed queue cannot leak secrets; per-item results carry only public
    metadata and Chinese/readable reasons.
    """
    summary: dict[str, int] = {}
    for item in result.items:
        summary[item.status] = summary.get(item.status, 0) + 1
    return {
        "batch_id": result.batch_id,
        "queue": serialize_queue(result.queue),
        "items": [serialize_batch_submit_item(item) for item in result.items],
        "summary": {
            SUBMIT_OUTCOME_SUCCEEDED: summary.get(SUBMIT_OUTCOME_SUCCEEDED, 0),
            SUBMIT_OUTCOME_FAILED: summary.get(SUBMIT_OUTCOME_FAILED, 0),
            SUBMIT_OUTCOME_RETRYABLE: summary.get(SUBMIT_OUTCOME_RETRYABLE, 0),
            SUBMIT_OUTCOME_SKIPPED: summary.get(SUBMIT_OUTCOME_SKIPPED, 0),
        },
    }


def _submit_one_item(
    item: BatchQueueItem,
    queue: BatchSubmissionQueue,
    *,
    ab_config: Any,
    load_request: LoadRequest,
    submit_one: SubmitOne,
    now_factory: NowFactory | None,
) -> tuple[BatchSubmitItemResult, BatchSubmissionQueue]:
    if item.status != BATCH_QUEUE_STATUS_READY_TO_SUBMIT:
        return (
            BatchSubmitItemResult(
                item_id=item.item_id,
                request_id=item.request_id,
                title=item.title,
                status=SUBMIT_OUTCOME_SKIPPED,
                reason=_skipped_reason(item.status),
                attempts=item.attempts,
            ),
            queue,
        )

    request = _safe_load_request(load_request, item.request_id)
    if request is None:
        return _reject_before_submit(
            item,
            queue,
            queue_status=BATCH_QUEUE_STATUS_FAILED,
            reason="订阅方案不存在或已删除，无法提交",
            error_type="request_not_found",
            now_factory=now_factory,
        )

    status = request.get("status")
    if status != ACCEPTED:
        cancelled = status == CANCELLED
        return _reject_before_submit(
            item,
            queue,
            queue_status=(
                BATCH_QUEUE_STATUS_FAILED
                if cancelled
                else BATCH_QUEUE_STATUS_RETRYABLE
            ),
            reason=(
                "订阅方案已取消，无法提交"
                if cancelled
                else "订阅方案尚未确认，无法提交"
            ),
            error_type="request_cancelled" if cancelled else "invalid_request_status",
            now_factory=now_factory,
        )

    next_queue = start_queue_item_submit(
        queue,
        item.request_id,
        now_factory=now_factory,
    )
    in_flight = _queue_item(next_queue, item.request_id)
    try:
        ab_result = submit_one(request, ab_config)
    except Stage1Error as exc:
        ab_result = _failure_result(exc.as_dict())
    except Exception:  # pragma: no cover - safety boundary
        ab_result = _failure_result(
            {
                "error_type": "unexpected_error",
                "error_message": "Auto Bangumi 提交发生未预期错误",
                "failed_step": "submit_batch_queue_items",
                "details": {},
            }
        )

    if _is_success(ab_result):
        next_queue = complete_queue_item_submit(
            next_queue,
            item.request_id,
            BATCH_QUEUE_STATUS_SUCCEEDED,
            ab_result_summary=_success_summary(ab_result),
            now_factory=now_factory,
        )
        return (
            BatchSubmitItemResult(
                item_id=item.item_id,
                request_id=item.request_id,
                title=item.title,
                status=SUBMIT_OUTCOME_SUCCEEDED,
                attempts=in_flight.attempts,
            ),
            next_queue,
        )

    error = _result_error(ab_result)
    error_type = str(error.get("error_type") or "ab_submit_failed")
    retryable = _is_retryable_error_type(error_type)
    queue_status = (
        BATCH_QUEUE_STATUS_RETRYABLE
        if retryable
        else BATCH_QUEUE_STATUS_FAILED
    )
    reason = str(error.get("error_message") or "Auto Bangumi 提交失败")
    next_queue = complete_queue_item_submit(
        next_queue,
        item.request_id,
        queue_status,
        last_error={"error_type": error_type, "error_message": reason},
        now_factory=now_factory,
    )
    return (
        BatchSubmitItemResult(
            item_id=item.item_id,
            request_id=item.request_id,
            title=item.title,
            status=(
                SUBMIT_OUTCOME_RETRYABLE if retryable else SUBMIT_OUTCOME_FAILED
            ),
            reason=reason,
            error_type=error_type,
            attempts=in_flight.attempts,
        ),
        next_queue,
    )


def _reject_before_submit(
    item: BatchQueueItem,
    queue: BatchSubmissionQueue,
    *,
    queue_status: str,
    reason: str,
    error_type: str,
    now_factory: NowFactory | None,
) -> tuple[BatchSubmitItemResult, BatchSubmissionQueue]:
    """Mark a READY item FAILED/RETRYABLE before any submit attempt."""
    next_queue = mark_queue_item_failed(
        queue,
        item.request_id,
        status=queue_status,
        last_error=reason,
        now_factory=now_factory,
    )
    return (
        BatchSubmitItemResult(
            item_id=item.item_id,
            request_id=item.request_id,
            title=item.title,
            status=(
                SUBMIT_OUTCOME_RETRYABLE
                if queue_status == BATCH_QUEUE_STATUS_RETRYABLE
                else SUBMIT_OUTCOME_FAILED
            ),
            reason=reason,
            error_type=error_type,
            attempts=item.attempts,
        ),
        next_queue,
    )


def _is_success(ab_result: dict[str, Any]) -> bool:
    return bool(ab_result.get("success"))


def _failure_result(error: dict[str, Any]) -> dict[str, Any]:
    return {"success": False, "error": error}


def _result_error(ab_result: dict[str, Any]) -> dict[str, Any]:
    error = ab_result.get("error")
    return error if isinstance(error, dict) else {}


def _is_retryable_error_type(error_type: str) -> bool:
    return error_type in _RETRYABLE_SUBMIT_ERROR_TYPES


def _success_summary(ab_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "success": True,
        "ab_subscription_id": ab_result.get("ab_subscription_id"),
    }


def _skipped_reason(status: str) -> str:
    reasons = {
        BATCH_QUEUE_STATUS_SUCCEEDED: "已提交成功，跳过重复提交",
        BATCH_QUEUE_STATUS_SUBMITTING: "提交中，跳过本次提交",
        BATCH_QUEUE_STATUS_FAILED: "已标记提交失败，请单独重试",
        BATCH_QUEUE_STATUS_RETRYABLE: "已标记可重试，请单独重试",
    }
    return reasons.get(status, "非待提交状态，跳过本次提交")


def _fallback_enabled(ab_config: Any) -> bool:
    return bool(getattr(ab_config, "fallback_enabled", False))


def _safe_load_request(
    load_request: LoadRequest,
    request_id: str,
) -> dict[str, Any] | None:
    try:
        return load_request(request_id)
    except Exception:  # pragma: no cover - safety boundary
        return None


def _queue_item(
    queue: BatchSubmissionQueue,
    request_id: str,
) -> BatchQueueItem:
    for item in queue.items:
        if item.request_id == request_id:
            return item
    raise ValueError("unknown request_id")


def _non_empty(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


__all__ = [
    "SUBMIT_OUTCOME_FAILED",
    "SUBMIT_OUTCOME_RETRYABLE",
    "SUBMIT_OUTCOME_SKIPPED",
    "SUBMIT_OUTCOME_SUCCEEDED",
    "BatchSubmitItemResult",
    "BatchSubmitResult",
    "SubmitOne",
    "compose_ab_submit_one",
    "serialize_batch_submit_item",
    "serialize_batch_submit_result",
    "submit_batch_queue_items",
]
