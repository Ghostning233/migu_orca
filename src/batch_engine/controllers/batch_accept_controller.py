"""Stage 20 batch accept orchestration.

Pure orchestration that accepts selected or all batch items and enqueues each
successful accept into the batch's pre-submission queue as READY_TO_SUBMIT.

The service reuses the existing Request accept capability through two injected
callables: ``load_request`` (resolve a request_id to its current snapshot, or
None) and ``accept_one`` (accept + persist a PENDING_CONFIRM request and return
the updated ACCEPTED request). The Web layer wires these to the shared accept
flow (``apply_confirmation_action`` + history + ``apply_request_save_action``),
so batch_engine stays decoupled from the apps layer.

Queue boundary: the queue only ever receives public titles plus ids. Items that
are already ACCEPTED return idempotently (no history re-write, no queue
re-enqueue); items without a usable PENDING_CONFIRM Request get a per-item
Chinese reason; and one item's failure never blocks the rest of the batch.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from batch_engine.controllers.batch_queue_controller import (
    IdFactory,
    NowFactory,
    create_submission_queue,
    enqueue_item,
    sanitize_queue_summary,
    serialize_queue,
)
from batch_engine.models import BatchSubmissionQueue
from request_engine.controllers.request_controller import (
    ACCEPTED,
    CANCELLED,
    PENDING_CONFIRM,
)
from shared.errors import Stage1Error

#: Per-item outcome statuses returned by the batch accept orchestration.
ACCEPT_OUTCOME_ACCEPTED = "accepted"
ACCEPT_OUTCOME_ALREADY_ACCEPTED = "already_accepted"
ACCEPT_OUTCOME_UNACCEPTABLE = "unacceptable"
ACCEPT_OUTCOME_FAILED = "failed"

LoadRequest = Callable[[str], dict[str, Any] | None]
AcceptOne = Callable[[str], dict[str, Any]]


@dataclass(frozen=True)
class BatchAcceptItem:
    """One batch item to accept.

    ``request_id`` is present only when the item already has a saved Request
    (an unsaved preview draft is persisted via preview-save before this call).
    Items without one (FAILED parse, missing candidates, deleted cards) are
    rejected with a per-item reason.
    """

    item_id: str
    request_id: str | None = None
    title: str | None = None


@dataclass(frozen=True)
class BatchAcceptItemResult:
    """Outcome of accepting one batch item."""

    item_id: str
    status: str
    request_id: str | None = None
    title: str | None = None
    reason: str | None = None
    error_type: str | None = None
    queued: bool = False


@dataclass(frozen=True)
class BatchAcceptResult:
    """The accepted batch plus the updated pre-submission queue."""

    batch_id: str
    queue: BatchSubmissionQueue
    items: list[BatchAcceptItemResult]


def retired_accept_items(
    *,
    batch_id: str,
    items: Sequence[BatchAcceptItem],
    load_request: LoadRequest,
    accept_one: AcceptOne,
    item_ids: Sequence[str] | None = None,
    queue: BatchSubmissionQueue | None = None,
    now_factory: NowFactory | None = None,
    queue_id_factory: IdFactory | None = None,
) -> BatchAcceptResult:
    """Accept selected or all batch items and enqueue successful accepts.

    ``item_ids`` is an optional filter: when given, only items whose
    ``item_id`` is in the list are processed (preserving batch order); when
    omitted, every provided item is processed (accept-all). Successful accepts
    enter the queue as READY_TO_SUBMIT; already-ACCEPTED items are idempotent;
    unacceptable items and per-item failures never block the rest of the batch.
    """
    clean_batch_id = _non_empty("batch_id", batch_id)
    selected = _select_items(items, item_ids)
    next_queue = queue or create_submission_queue(
        clean_batch_id,
        queue_id_factory=queue_id_factory,
        now_factory=now_factory,
    )
    results: list[BatchAcceptItemResult] = []
    for item in selected:
        item_result, next_queue = _accept_one_item(
            item,
            next_queue,
            load_request=load_request,
            accept_one=accept_one,
            now_factory=now_factory,
        )
        results.append(item_result)
    return BatchAcceptResult(
        batch_id=clean_batch_id,
        queue=next_queue,
        items=results,
    )


def serialize_batch_accept_item(item: BatchAcceptItemResult) -> dict[str, Any]:
    return {
        "item_id": item.item_id,
        "request_id": item.request_id,
        "title": sanitize_queue_summary(item.title) or item.title,
        "status": item.status,
        "reason": item.reason,
        "error_type": item.error_type,
        "queued": item.queued,
    }


def serialize_batch_accept_result(result: BatchAcceptResult) -> dict[str, Any]:
    """Serialize a batch accept result with only non-sensitive, public fields.

    The queue is re-serialized through ``serialize_queue`` so even a directly
    constructed queue cannot leak secrets; per-item results carry only public
    metadata and Chinese reasons.
    """
    summary: dict[str, int] = {}
    for item in result.items:
        summary[item.status] = summary.get(item.status, 0) + 1
    return {
        "batch_id": result.batch_id,
        "queue": serialize_queue(result.queue),
        "items": [serialize_batch_accept_item(item) for item in result.items],
        "summary": {
            ACCEPT_OUTCOME_ACCEPTED: summary.get(ACCEPT_OUTCOME_ACCEPTED, 0),
            ACCEPT_OUTCOME_ALREADY_ACCEPTED: summary.get(
                ACCEPT_OUTCOME_ALREADY_ACCEPTED,
                0,
            ),
            ACCEPT_OUTCOME_UNACCEPTABLE: summary.get(
                ACCEPT_OUTCOME_UNACCEPTABLE,
                0,
            ),
            ACCEPT_OUTCOME_FAILED: summary.get(ACCEPT_OUTCOME_FAILED, 0),
        },
    }


def _accept_one_item(
    item: BatchAcceptItem,
    queue: BatchSubmissionQueue,
    *,
    load_request: LoadRequest,
    accept_one: AcceptOne,
    now_factory: NowFactory | None,
) -> tuple[BatchAcceptItemResult, BatchSubmissionQueue]:
    request_id = (item.request_id or "").strip() or None
    if request_id is None:
        return (
            BatchAcceptItemResult(
                item_id=item.item_id,
                status=ACCEPT_OUTCOME_UNACCEPTABLE,
                reason="卡片缺少订阅草案，无法接受",
            ),
            queue,
        )

    request = _safe_load_request(load_request, request_id)
    if request is None:
        return (
            BatchAcceptItemResult(
                item_id=item.item_id,
                request_id=request_id,
                status=ACCEPT_OUTCOME_UNACCEPTABLE,
                reason="订阅方案不存在或已删除",
            ),
            queue,
        )

    status = request.get("status")
    fallback_title = item.title or _request_title(request)
    if status == ACCEPTED:
        if _queue_has_item(queue, request_id):
            # Idempotent repeat: the queue already holds this request, so never
            # re-accept, never re-write confirmation history, and never
            # duplicate the queue item.
            return (
                BatchAcceptItemResult(
                    item_id=item.item_id,
                    request_id=request_id,
                    title=fallback_title,
                    status=ACCEPT_OUTCOME_ALREADY_ACCEPTED,
                    reason="该订阅方案已确认，跳过重复接受",
                ),
                queue,
            )
        # The Request is already ACCEPTED but its queue item is missing (the
        # queue save failed, was deleted, or is corrupted). If the Request
        # already carries a SUCCESSFUL AB submit result, the subscription was
        # already created on Auto Bangumi: rebuilding a READY_TO_SUBMIT item
        # would let a later submit re-create it (duplicate subscription), so we
        # never re-enqueue it.
        persisted_result = request.get("ab_submit_result")
        if (
            isinstance(persisted_result, dict)
            and persisted_result.get("success") is True
        ):
            return (
                BatchAcceptItemResult(
                    item_id=item.item_id,
                    request_id=request_id,
                    title=fallback_title,
                    status=ACCEPT_OUTCOME_ALREADY_ACCEPTED,
                    reason="该订阅方案已提交成功，跳过重复入队",
                ),
                queue,
            )
        # Otherwise rebuild the READY_TO_SUBMIT item so the accepted Request can
        # be submitted again.
        title = fallback_title or "未命名订阅方案"
        next_queue = enqueue_item(
            queue,
            item_id=item.item_id,
            request_id=request_id,
            title=sanitize_queue_summary(title) or title,
            now_factory=now_factory,
        )
        return (
            BatchAcceptItemResult(
                item_id=item.item_id,
                request_id=request_id,
                title=fallback_title,
                status=ACCEPT_OUTCOME_ALREADY_ACCEPTED,
                reason="该订阅方案已确认，已补建提交队列",
                queued=True,
            ),
            next_queue,
        )

    if status != PENDING_CONFIRM:
        cancelled = status == CANCELLED
        return (
            BatchAcceptItemResult(
                item_id=item.item_id,
                request_id=request_id,
                title=fallback_title,
                status=ACCEPT_OUTCOME_UNACCEPTABLE,
                reason=(
                    "订阅方案已取消，无法接受"
                    if cancelled
                    else "订阅方案状态不支持接受"
                ),
                error_type="request_cancelled" if cancelled else "invalid_request_status",
            ),
            queue,
        )

    try:
        accepted_request = accept_one(request_id)
    except Stage1Error as exc:
        return (
            BatchAcceptItemResult(
                item_id=item.item_id,
                request_id=request_id,
                title=fallback_title,
                status=ACCEPT_OUTCOME_FAILED,
                reason=exc.message,
                error_type=exc.error_type,
            ),
            queue,
        )
    except Exception:  # pragma: no cover - safety boundary
        return (
            BatchAcceptItemResult(
                item_id=item.item_id,
                request_id=request_id,
                title=fallback_title,
                status=ACCEPT_OUTCOME_FAILED,
                reason="接受失败发生未预期错误",
                error_type="unexpected_error",
            ),
            queue,
        )

    title = (
        item.title
        or _request_title(accepted_request)
        or "未命名订阅方案"
    )
    next_queue = enqueue_item(
        queue,
        item_id=item.item_id,
        request_id=request_id,
        title=sanitize_queue_summary(title) or title,
        now_factory=now_factory,
    )
    return (
        BatchAcceptItemResult(
            item_id=item.item_id,
            request_id=request_id,
            title=title,
            status=ACCEPT_OUTCOME_ACCEPTED,
            queued=True,
        ),
        next_queue,
    )


def _safe_load_request(
    load_request: LoadRequest,
    request_id: str,
) -> dict[str, Any] | None:
    try:
        return load_request(request_id)
    except Exception:  # pragma: no cover - safety boundary
        return None


def _queue_has_item(queue: BatchSubmissionQueue, request_id: str) -> bool:
    return any(item.request_id == request_id for item in queue.items)


def _select_items(
    items: Sequence[BatchAcceptItem],
    item_ids: Sequence[str] | None,
) -> list[BatchAcceptItem]:
    if item_ids is None:
        return list(items)
    wanted = {str(item_id) for item_id in item_ids}
    return [item for item in items if item.item_id in wanted]


def _request_title(request: dict[str, Any]) -> str | None:
    source_info = request.get("source_info") or {}
    matched = source_info.get("matched_bangumi") or {}
    if matched.get("title"):
        return str(matched["title"])
    raw_input = (request.get("input") or {}).get("raw_title")
    if raw_input:
        return str(raw_input)
    return None


def _non_empty(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


__all__ = [
    "ACCEPT_OUTCOME_ACCEPTED",
    "ACCEPT_OUTCOME_ALREADY_ACCEPTED",
    "ACCEPT_OUTCOME_FAILED",
    "ACCEPT_OUTCOME_UNACCEPTABLE",
    "AcceptOne",
    "BatchAcceptItem",
    "BatchAcceptItemResult",
    "BatchAcceptResult",
    "LoadRequest",
    "retired_accept_items",
    "serialize_batch_accept_item",
    "serialize_batch_accept_result",
]
