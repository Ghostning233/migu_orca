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
``compose_legacy_submit_one`` builds that callable from the existing Auto Bangumi
payload/client/submit primitives (the batch-domain equivalent of
``apply_ab_submit_action``'s AB portion) so later API/UI layers can wire the
real path without reimplementing payload or client logic. Auto Bangumi secrets
live only in the request-scoped ``ab_config`` and never reach the queue.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ab_engine.controllers import ab_http_client
from ab_engine.controllers.ab_client import submit_ab_subscription
from ab_engine.controllers.subscription_payload import build_ab_submit_payload
from batch_engine.controllers.batch_queue_controller import (
    NowFactory,
    complete_queue_item_submit,
    mark_queue_item_failed,
    mark_queue_item_retry_failed,
    sanitize_queue_summary,
    serialize_queue,
    start_queue_item_submit,
)
from batch_engine.models.queue import (
    BATCH_QUEUE_STATUS_FAILED,
    BATCH_QUEUE_STATUS_READY_TO_SUBMIT,
    BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED,
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

#: Per-item outcome statuses returned by the batch recovery orchestration.
RECOVER_OUTCOME_SUCCEEDED = "succeeded"
RECOVER_OUTCOME_FAILED = "failed"
RECOVER_OUTCOME_RETRYABLE = "retryable"
RECOVER_OUTCOME_SKIPPED = "skipped"
RECOVER_OUTCOME_NEEDS_MANUAL = "needs_manual"

#: Recovery actions for stuck queue items (SUBMITTING / RESULT_PERSIST_FAILED).
RECOVER_ACTION_AUTO = "auto"
RECOVER_ACTION_SUCCEEDED = "succeeded"
RECOVER_ACTION_FAILED = "failed"

#: Error type used when persisting an AB submit result (Request snapshot +
#: ab_results/<request_id>.json) fails for one item. Kept non-retryable so the
#: item is never blindly re-submitted after an ambiguous persistence failure.
SUBMIT_PERSIST_ERROR_TYPE = "result_persist_failed"

#: Transient Auto Bangumi errors that can be retried with the same config.
_RETRYABLE_SUBMIT_ERROR_TYPES = frozenset(
    {"ab_timeout", "ab_connection_failed"}
)

LoadRequest = Callable[[str], dict[str, Any] | None]
SubmitOne = Callable[[dict[str, Any], Any], dict[str, Any]]
#: Persists the in-memory queue after a per-item status transition (used to
#: flush SUBMITTING before any Auto Bangumi call and the final item status
#: after the attempt, so an interruption can never leave READY_TO_SUBMIT on
#: disk for an item that already reached Auto Bangumi).
PersistQueue = Callable[[BatchSubmissionQueue], None]
#: Persists one item's sanitized AB submit result into the Request snapshot and
#: ab_results/<request_id>.json, mirroring the single-item submit-ab contract.
#: Receives (request, ab_submit_result) and must raise Stage1Error on failure.
PersistSubmitResult = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


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


def retired_submit_queue_items(
    *,
    batch_id: str,
    queue: BatchSubmissionQueue,
    ab_config: Any,
    load_request: LoadRequest,
    submit_one: SubmitOne,
    now_factory: NowFactory | None = None,
    persist_queue: PersistQueue | None = None,
    persist_submit_result: PersistSubmitResult | None = None,
) -> BatchSubmitResult:
    """Process READY_TO_SUBMIT queue items sequentially against Auto Bangumi.

    Already-SUCCEEDED items and items not in READY_TO_SUBMIT are skipped without
    any submit call; pre-submit validation (the Request must still be ACCEPTED)
    and per-item submit failures mark the item FAILED or RETRYABLE and never
    block the rest of the batch.

    Reliability contract (interruption safety): when ``persist_queue`` is
    provided, the item is flushed to disk as SUBMITTING *before* the Auto
    Bangumi call, and the final SUCCEEDED/FAILED/RETRYABLE status is flushed
    after the attempt, so a crash between the external submit and the final
    queue save can never leave READY_TO_SUBMIT on disk for an item that already
    reached Auto Bangumi. When ``persist_submit_result`` is provided, every
    item's sanitized AB result (success or failure) is written into the Request
    snapshot and ``ab_results/<request_id>.json``; a per-item persistence
    failure marks that item FAILED with ``result_persist_failed`` and never
    blocks the rest of the batch.
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
            persist_queue=persist_queue,
            persist_submit_result=persist_submit_result,
        )
        results.append(item_result)
    return BatchSubmitResult(
        batch_id=clean_batch_id,
        queue=next_queue,
        items=results,
    )


def retired_retry_queue_item(
    *,
    batch_id: str,
    queue: BatchSubmissionQueue,
    request_id: str,
    ab_config: Any,
    load_request: LoadRequest,
    submit_one: SubmitOne,
    now_factory: NowFactory | None = None,
    persist_queue: PersistQueue | None = None,
    persist_submit_result: PersistSubmitResult | None = None,
) -> BatchSubmitResult:
    """Retry a single FAILED/RETRYABLE queue item against Auto Bangumi.

    Only FAILED/RETRYABLE items are retried: already-SUCCEEDED and other
    non-retryable items return a ``skipped`` outcome without any submit call, so
    a successful subscription can never be re-submitted. The retry re-loads the
    latest saved Request snapshot via ``load_request`` (never a copy held in the
    queue), re-validates that it is still ACCEPTED, then starts a new submit
    attempt (increments ``attempts``) and finalizes it exactly like a first
    submit. A single retry never affects sibling items, and one retry failure
    leaves the item FAILED/RETRYABLE with an incremented attempt count.

    The same reliability contract as ``retired_submit_queue_items`` applies:
    ``persist_queue`` flushes SUBMITTING before the Auto Bangumi call and the
    final status after it; ``persist_submit_result`` writes the sanitized AB
    result into the Request snapshot and ``ab_results/<request_id>.json``.
    """
    clean_batch_id = _non_empty("batch_id", batch_id)
    clean_request_id = _non_empty("request_id", request_id)
    item = _find_queue_item(queue, clean_request_id)
    if item is None:
        raise ValueError("unknown request_id")

    if item.status not in {
        BATCH_QUEUE_STATUS_FAILED,
        BATCH_QUEUE_STATUS_RETRYABLE,
    }:
        return BatchSubmitResult(
            batch_id=clean_batch_id,
            queue=queue,
            items=[
                BatchSubmitItemResult(
                    item_id=item.item_id,
                    request_id=item.request_id,
                    title=item.title,
                    status=SUBMIT_OUTCOME_SKIPPED,
                    reason=_not_retryable_reason(item.status),
                    attempts=item.attempts,
                )
            ],
        )

    request = _safe_load_request(load_request, clean_request_id)
    if request is None:
        return _reject_retry_before_submit(
            clean_batch_id,
            queue,
            item,
            queue_status=BATCH_QUEUE_STATUS_FAILED,
            reason="订阅方案不存在或已删除，无法提交",
            error_type="request_not_found",
            now_factory=now_factory,
        )

    status = request.get("status")
    if status != ACCEPTED:
        cancelled = status == CANCELLED
        return _reject_retry_before_submit(
            clean_batch_id,
            queue,
            item,
            queue_status=(
                BATCH_QUEUE_STATUS_FAILED if cancelled else BATCH_QUEUE_STATUS_RETRYABLE
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
        clean_request_id,
        now_factory=now_factory,
    )
    if persist_queue is not None:
        # Flush SUBMITTING before the Auto Bangumi call (same interruption
        # safety as a first submit: the disk never keeps READY_TO_SUBMIT for
        # an item that already reached Auto Bangumi).
        persist_queue(next_queue)
    in_flight = _queue_item(next_queue, clean_request_id)
    try:
        ab_result = submit_one(request, ab_config)
    except Stage1Error as exc:
        ab_result = _failure_result(exc.as_dict())
    except Exception:  # pragma: no cover - safety boundary
        ab_result = _failure_result(
            {
                "error_type": "unexpected_error",
                "error_message": "Auto Bangumi 提交发生未预期错误",
                "failed_step": "retired_retry_queue_item",
                "details": {},
            }
        )

    persist_error = _persist_submit_result_safely(
        persist_submit_result,
        request,
        ab_result,
    )

    if _is_success(ab_result) and persist_error is None:
        next_queue = complete_queue_item_submit(
            next_queue,
            clean_request_id,
            BATCH_QUEUE_STATUS_SUCCEEDED,
            ab_result_summary=_success_summary(ab_result),
            now_factory=now_factory,
        )
        if persist_queue is not None:
            persist_queue(next_queue)
        return BatchSubmitResult(
            batch_id=clean_batch_id,
            queue=next_queue,
            items=[
                BatchSubmitItemResult(
                    item_id=item.item_id,
                    request_id=item.request_id,
                    title=item.title,
                    status=SUBMIT_OUTCOME_SUCCEEDED,
                    attempts=in_flight.attempts,
                )
            ],
        )

    if persist_error is not None:
        # Same ambiguous state as a first submit: the Auto Bangumi call
        # happened but the local result could not be persisted. Enter the
        # dedicated RESULT_PERSIST_FAILED state (never blindly retried).
        reason = str(
            getattr(persist_error, "message", None) or "保存 Auto Bangumi 提交结果失败"
        )
        next_queue = complete_queue_item_submit(
            next_queue,
            clean_request_id,
            BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED,
            last_error={
                "error_type": SUBMIT_PERSIST_ERROR_TYPE,
                "error_message": reason,
            },
            now_factory=now_factory,
        )
        if persist_queue is not None:
            persist_queue(next_queue)
        return BatchSubmitResult(
            batch_id=clean_batch_id,
            queue=next_queue,
            items=[
                BatchSubmitItemResult(
                    item_id=item.item_id,
                    request_id=item.request_id,
                    title=item.title,
                    status=SUBMIT_OUTCOME_FAILED,
                    reason=reason,
                    error_type=SUBMIT_PERSIST_ERROR_TYPE,
                    attempts=in_flight.attempts,
                )
            ],
        )

    error = _result_error(ab_result)
    error_type = str(error.get("error_type") or "ab_submit_failed")
    retryable = _is_retryable_error_type(error_type)
    reason = str(error.get("error_message") or "Auto Bangumi 提交失败")
    queue_status = (
        BATCH_QUEUE_STATUS_RETRYABLE if retryable else BATCH_QUEUE_STATUS_FAILED
    )
    next_queue = complete_queue_item_submit(
        next_queue,
        clean_request_id,
        queue_status,
        last_error={"error_type": error_type, "error_message": reason},
        now_factory=now_factory,
    )
    if persist_queue is not None:
        persist_queue(next_queue)
    return BatchSubmitResult(
        batch_id=clean_batch_id,
        queue=next_queue,
        items=[
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
            )
        ],
    )


def retired_recover_queue_item(
    *,
    batch_id: str,
    queue: BatchSubmissionQueue,
    request_id: str,
    action: str,
    load_request: LoadRequest,
    now_factory: NowFactory | None = None,
    persist_queue: PersistQueue | None = None,
) -> BatchSubmitResult:
    """Resolve a stuck queue item (SUBMITTING / RESULT_PERSIST_FAILED).

    Stuck states are never auto-retried (a retry could re-create a subscription
    Auto Bangumi already made), so they need an explicit recovery path:

    - ``action=auto``: only meaningful for SUBMITTING. The persisted
      ``ab_submit_result`` decides the outcome: a ``success: true`` result
      finalizes the item as SUCCEEDED; a ``success: false`` result finalizes
      it as RETRYABLE (transient AB errors) or FAILED (terminal errors) with
      the sanitized error summary kept on the item; a missing/invalid result
      (non-dict or no ``success`` key) returns ``needs_manual`` so the caller
      asks the user to verify Auto Bangumi. A persisted failure is never
      auto-marked SUCCEEDED.
    - ``action=succeeded``: manual confirmation that Auto Bangumi created the
      subscription -> SUCCEEDED (with a sanitized summary when a result exists).
    - ``action=failed``: manual confirmation that Auto Bangumi did NOT create
      the subscription -> FAILED (a normal retryable failure; retrying is safe).

    Non-stuck items (READY/SUCCEEDED/FAILED/RETRYABLE) return ``skipped`` and
    never change. One recovery never affects sibling items.
    """
    clean_batch_id = _non_empty("batch_id", batch_id)
    clean_request_id = _non_empty("request_id", request_id)
    clean_action = _non_empty("action", action)
    if clean_action not in {
        RECOVER_ACTION_AUTO,
        RECOVER_ACTION_SUCCEEDED,
        RECOVER_ACTION_FAILED,
    }:
        raise ValueError(f"invalid recovery action: {action}")

    item = _find_queue_item(queue, clean_request_id)
    if item is None:
        raise ValueError("unknown request_id")

    if item.status not in {
        BATCH_QUEUE_STATUS_SUBMITTING,
        BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED,
    }:
        return BatchSubmitResult(
            batch_id=clean_batch_id,
            queue=queue,
            items=[
                BatchSubmitItemResult(
                    item_id=item.item_id,
                    request_id=item.request_id,
                    title=item.title,
                    status=RECOVER_OUTCOME_SKIPPED,
                    reason=_not_recoverable_reason(item.status),
                    attempts=item.attempts,
                )
            ],
        )

    if clean_action == RECOVER_ACTION_AUTO:
        return _recover_auto(
            clean_batch_id,
            queue,
            item,
            load_request=load_request,
            now_factory=now_factory,
            persist_queue=persist_queue,
        )
    if clean_action == RECOVER_ACTION_SUCCEEDED:
        return _recover_manual_succeeded(
            clean_batch_id,
            queue,
            item,
            load_request=load_request,
            now_factory=now_factory,
            persist_queue=persist_queue,
        )
    return _recover_manual_failed(
        clean_batch_id,
        queue,
        item,
        now_factory=now_factory,
        persist_queue=persist_queue,
    )


def _recover_auto(
    batch_id: str,
    queue: BatchSubmissionQueue,
    item: BatchQueueItem,
    *,
    load_request: LoadRequest,
    now_factory: NowFactory | None,
    persist_queue: PersistQueue | None,
) -> BatchSubmitResult:
    """Auto-recover a SUBMITTING item whose AB result was already persisted.

    The persisted result decides the recovery: a ``success: true`` result is
    finalized as SUCCEEDED; a ``success: false`` result is finalized as
    RETRYABLE (transient AB errors) or FAILED (terminal errors) using the same
    retryable classification as a live submit, keeping the sanitized error
    summary. Anything without a clear result (missing, non-dict, or lacking a
    ``success`` key) falls back to manual verification — a failure result must
    never be auto-marked SUCCEEDED.
    """
    if item.status != BATCH_QUEUE_STATUS_SUBMITTING:
        return _recover_needs_manual(
            batch_id,
            queue,
            item,
            "该状态没有已持久化的结果可自动恢复，请人工核验 Auto Bangumi 是否已创建订阅",
            "auto_recovery_not_applicable",
        )

    request = _safe_load_request(load_request, item.request_id)
    ab_result = (request or {}).get("ab_submit_result")
    if not isinstance(ab_result, dict) or not isinstance(
        ab_result.get("success"), bool
    ):
        # A missing, non-dict, or non-boolean success flag is not a legal
        # result object: fall back to manual verification (e.g. a persisted
        # ``success: null`` must never be silently turned into a terminal
        # FAILED, because a later retry assumes Auto Bangumi did NOT create
        # the subscription — which we cannot know).
        return _recover_needs_manual(
            batch_id,
            queue,
            item,
            "未找到明确的提交结果，请人工核验 Auto Bangumi 是否已创建订阅",
            "requires_manual_recovery",
        )

    if _is_success(ab_result):
        next_queue = complete_queue_item_submit(
            queue,
            item.request_id,
            BATCH_QUEUE_STATUS_SUCCEEDED,
            ab_result_summary=_success_summary(ab_result),
            now_factory=now_factory,
        )
        if persist_queue is not None:
            persist_queue(next_queue)
        return BatchSubmitResult(
            batch_id=batch_id,
            queue=next_queue,
            items=[
                BatchSubmitItemResult(
                    item_id=item.item_id,
                    request_id=item.request_id,
                    title=item.title,
                    status=RECOVER_OUTCOME_SUCCEEDED,
                    reason="已根据保存的提交结果恢复为提交成功",
                    attempts=item.attempts,
                )
            ],
        )

    # A persisted failure result: never mark it SUCCEEDED. Recover to
    # RETRYABLE for transient AB errors, otherwise FAILED, keeping the
    # sanitized one-line error summary on the queue item.
    error = _result_error(ab_result)
    error_type = str(error.get("error_type") or "ab_submit_failed")
    retryable = _is_retryable_error_type(error_type)
    queue_status = (
        BATCH_QUEUE_STATUS_RETRYABLE if retryable else BATCH_QUEUE_STATUS_FAILED
    )
    reason = str(error.get("error_message") or "Auto Bangumi 提交失败")
    next_queue = complete_queue_item_submit(
        queue,
        item.request_id,
        queue_status,
        last_error={"error_type": error_type, "error_message": reason},
        now_factory=now_factory,
    )
    if persist_queue is not None:
        persist_queue(next_queue)
    return BatchSubmitResult(
        batch_id=batch_id,
        queue=next_queue,
        items=[
            BatchSubmitItemResult(
                item_id=item.item_id,
                request_id=item.request_id,
                title=item.title,
                status=(
                    RECOVER_OUTCOME_RETRYABLE if retryable else RECOVER_OUTCOME_FAILED
                ),
                reason=reason,
                error_type=error_type,
                attempts=item.attempts,
            )
        ],
    )


def _recover_manual_succeeded(
    batch_id: str,
    queue: BatchSubmissionQueue,
    item: BatchQueueItem,
    *,
    load_request: LoadRequest,
    now_factory: NowFactory | None,
    persist_queue: PersistQueue | None,
) -> BatchSubmitResult:
    """Manual confirmation that Auto Bangumi created the subscription."""
    request = _safe_load_request(load_request, item.request_id)
    ab_result = (request or {}).get("ab_submit_result")
    summary = (
        _success_summary(ab_result)
        if isinstance(ab_result, dict) and _is_success(ab_result)
        else {"success": True}
    )
    next_queue = complete_queue_item_submit(
        queue,
        item.request_id,
        BATCH_QUEUE_STATUS_SUCCEEDED,
        ab_result_summary=summary,
        now_factory=now_factory,
    )
    if persist_queue is not None:
        persist_queue(next_queue)
    return BatchSubmitResult(
        batch_id=batch_id,
        queue=next_queue,
        items=[
            BatchSubmitItemResult(
                item_id=item.item_id,
                request_id=item.request_id,
                title=item.title,
                status=RECOVER_OUTCOME_SUCCEEDED,
                reason="人工核验确认 Auto Bangumi 已创建订阅，标记为提交成功",
                attempts=item.attempts,
            )
        ],
    )


def _recover_manual_failed(
    batch_id: str,
    queue: BatchSubmissionQueue,
    item: BatchQueueItem,
    *,
    now_factory: NowFactory | None,
    persist_queue: PersistQueue | None,
) -> BatchSubmitResult:
    """Manual confirmation that Auto Bangumi did NOT create the subscription."""
    next_queue = complete_queue_item_submit(
        queue,
        item.request_id,
        BATCH_QUEUE_STATUS_FAILED,
        last_error={
            "error_type": "manual_recovery_failed",
            "error_message": "人工核验：Auto Bangumi 未创建订阅，标记为可重试失败",
        },
        now_factory=now_factory,
    )
    if persist_queue is not None:
        persist_queue(next_queue)
    return BatchSubmitResult(
        batch_id=batch_id,
        queue=next_queue,
        items=[
            BatchSubmitItemResult(
                item_id=item.item_id,
                request_id=item.request_id,
                title=item.title,
                status=RECOVER_OUTCOME_FAILED,
                reason="人工核验确认 Auto Bangumi 未创建订阅，标记为可重试失败",
                attempts=item.attempts,
            )
        ],
    )


def _recover_needs_manual(
    batch_id: str,
    queue: BatchSubmissionQueue,
    item: BatchQueueItem,
    reason: str,
    error_type: str,
) -> BatchSubmitResult:
    return BatchSubmitResult(
        batch_id=batch_id,
        queue=queue,
        items=[
            BatchSubmitItemResult(
                item_id=item.item_id,
                request_id=item.request_id,
                title=item.title,
                status=RECOVER_OUTCOME_NEEDS_MANUAL,
                reason=reason,
                error_type=error_type,
                attempts=item.attempts,
            )
        ],
    )


def _not_recoverable_reason(status: str) -> str:
    reasons = {
        BATCH_QUEUE_STATUS_SUCCEEDED: "已提交成功，无需恢复",
        BATCH_QUEUE_STATUS_READY_TO_SUBMIT: "待提交状态，无需恢复",
        BATCH_QUEUE_STATUS_FAILED: "已标记提交失败，可直接重试",
        BATCH_QUEUE_STATUS_RETRYABLE: "已标记可重试，可直接重试",
    }
    return reasons.get(status, "该状态无需恢复")


def compose_legacy_submit_one() -> SubmitOne:
    """Build the standard ``submit_one`` from the existing AB primitives.

    Mirrors the AB portion of ``apply_ab_submit_action``: build the subscription
    payload from the ACCEPTED Request snapshot, create a request-scoped Auto
    Bangumi HTTP client from the config, and normalize the response through the
    existing sanitized ``ab_submit_result`` contract.
    """

    def submit_one(request: dict[str, Any], ab_config: Any) -> dict[str, Any]:
        payload = build_ab_submit_payload(request, ab_config.auth_mode)
        client = ab_http_client.create_auto_bangumi_submit_client(ab_config)
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
        # Reasons are re-sanitized defensively on the way out, so even an
        # injected custom reason can never leak secrets through the API.
        "reason": sanitize_queue_summary(item.reason),
        "error_type": item.error_type,
        "attempts": item.attempts,
    }


def serialize_batch_submit_result(result: BatchSubmitResult) -> dict[str, Any]:
    """Serialize a batch submit result with only non-sensitive, public fields.

    The queue is re-serialized through ``serialize_queue`` so even a directly
    constructed queue cannot leak secrets; per-item results carry only public
    metadata and Chinese/readable reasons. The summary counts every outcome,
    including the recovery ``needs_manual`` outcome (always 0 for submit/retry).
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
            RECOVER_OUTCOME_NEEDS_MANUAL: summary.get(
                RECOVER_OUTCOME_NEEDS_MANUAL,
                0,
            ),
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
    persist_queue: PersistQueue | None,
    persist_submit_result: PersistSubmitResult | None,
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

    # Defense in depth: if the Request already carries a SUCCESSFUL AB submit
    # result, the subscription was already created on Auto Bangumi. Never call
    # Auto Bangumi again — finalize the item as SUCCEEDED with the persisted
    # result summary instead (this can happen when a queue item was rebuilt
    # manually or a queue file was restored from before the submit).
    persisted_result = request.get("ab_submit_result")
    if isinstance(persisted_result, dict) and persisted_result.get("success") is True:
        next_queue = start_queue_item_submit(
            queue,
            item.request_id,
            now_factory=now_factory,
        )
        in_flight = _queue_item(next_queue, item.request_id)
        next_queue = complete_queue_item_submit(
            next_queue,
            item.request_id,
            BATCH_QUEUE_STATUS_SUCCEEDED,
            ab_result_summary=_success_summary(persisted_result),
            now_factory=now_factory,
        )
        if persist_queue is not None:
            persist_queue(next_queue)
        return (
            BatchSubmitItemResult(
                item_id=item.item_id,
                request_id=item.request_id,
                title=item.title,
                status=SUBMIT_OUTCOME_SUCCEEDED,
                reason="该订阅方案已提交成功，跳过重复提交",
                attempts=in_flight.attempts,
            ),
            next_queue,
        )

    next_queue = start_queue_item_submit(
        queue,
        item.request_id,
        now_factory=now_factory,
    )
    if persist_queue is not None:
        # Flush SUBMITTING before any Auto Bangumi call: if the process dies
        # after the external submit but before the final status is persisted,
        # the disk queue holds SUBMITTING (never READY_TO_SUBMIT), so a later
        # submit/retry skips it instead of re-creating the subscription.
        persist_queue(next_queue)
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
                "failed_step": "retired_submit_queue_items",
                "details": {},
            }
        )

    # Persist the sanitized AB result (success or failure) into the Request
    # snapshot and ab_results/<request_id>.json, mirroring the single-item
    # submit-ab contract. A per-item persistence failure is recorded on this
    # item and never blocks the rest of the batch.
    persist_error = _persist_submit_result_safely(
        persist_submit_result,
        request,
        ab_result,
    )

    if _is_success(ab_result) and persist_error is None:
        next_queue = complete_queue_item_submit(
            next_queue,
            item.request_id,
            BATCH_QUEUE_STATUS_SUCCEEDED,
            ab_result_summary=_success_summary(ab_result),
            now_factory=now_factory,
        )
        if persist_queue is not None:
            persist_queue(next_queue)
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

    if persist_error is not None:
        # Ambiguous state: the Auto Bangumi call happened (it may have created
        # the subscription) but the local result could not be persisted. This
        # is NOT a normal FAILED that can be blindly retried — retrying could
        # create a duplicate subscription — so the item enters the dedicated
        # RESULT_PERSIST_FAILED state and can only be resolved via explicit
        # recovery (manual verification that Auto Bangumi created it or not).
        reason = str(
            getattr(persist_error, "message", None) or "保存 Auto Bangumi 提交结果失败"
        )
        next_queue = complete_queue_item_submit(
            next_queue,
            item.request_id,
            BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED,
            last_error={
                "error_type": SUBMIT_PERSIST_ERROR_TYPE,
                "error_message": reason,
            },
            now_factory=now_factory,
        )
        if persist_queue is not None:
            persist_queue(next_queue)
        return (
            BatchSubmitItemResult(
                item_id=item.item_id,
                request_id=item.request_id,
                title=item.title,
                status=SUBMIT_OUTCOME_FAILED,
                reason=reason,
                error_type=SUBMIT_PERSIST_ERROR_TYPE,
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
    if persist_queue is not None:
        persist_queue(next_queue)
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


def _reject_retry_before_submit(
    batch_id: str,
    queue: BatchSubmissionQueue,
    item: BatchQueueItem,
    *,
    queue_status: str,
    reason: str,
    error_type: str,
    now_factory: NowFactory | None,
) -> BatchSubmitResult:
    """Update a retried item FAILED/RETRYABLE before any submit attempt.

    Unlike a first-submit rejection (``mark_queue_item_failed``, READY-only),
    the item is already FAILED/RETRYABLE, so this uses the retry-specific queue
    helper which keeps the item FAILED/RETRYABLE with a fresh sanitized error and
    does NOT increment ``attempts`` (no Auto Bangumi submit was attempted).
    """
    next_queue = mark_queue_item_retry_failed(
        queue,
        item.request_id,
        status=queue_status,
        last_error=reason,
        now_factory=now_factory,
    )
    return BatchSubmitResult(
        batch_id=batch_id,
        queue=next_queue,
        items=[
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
            )
        ],
    )


def _not_retryable_reason(status: str) -> str:
    reasons = {
        BATCH_QUEUE_STATUS_SUCCEEDED: "已提交成功，不可重复提交",
        BATCH_QUEUE_STATUS_READY_TO_SUBMIT: "尚未提交，无需重试",
        BATCH_QUEUE_STATUS_SUBMITTING: "提交中，请先恢复或稍后再试",
        BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED: "结果保存失败，需人工核验后恢复，不可直接重试",
    }
    return reasons.get(status, "非失败项目，不可单独重试")


def _is_success(ab_result: dict[str, Any]) -> bool:
    return bool(ab_result.get("success"))


def _failure_result(error: dict[str, Any]) -> dict[str, Any]:
    return {"success": False, "error": error}


def _persist_submit_result_safely(
    persist_submit_result: PersistSubmitResult | None,
    request: dict[str, Any],
    ab_result: dict[str, Any],
) -> Stage1Error | None:
    """Persist one item's AB result, returning a sanitized error on failure.

    ``persist_submit_result`` is the Web-layer injected writer that mirrors the
    single-item submit-ab storage contract (Request snapshot + ab_results file).
    Any failure is normalized to a stable sanitized ``Stage1Error`` so the item
    can be marked FAILED with ``result_persist_failed`` and the rest of the
    batch keeps processing.
    """
    if persist_submit_result is None:
        return None
    try:
        persist_submit_result(request, ab_result)
        return None
    except Stage1Error as exc:
        return exc
    except Exception:  # pragma: no cover - safety boundary
        return Stage1Error(
            SUBMIT_PERSIST_ERROR_TYPE,
            "保存 Auto Bangumi 提交结果失败",
            "persist_batch_submit_result",
            {"request_id": str(request.get("request_id") or "")},
        )


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
        BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED: "结果保存失败，跳过本次提交，请先恢复",
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
    item = _find_queue_item(queue, request_id)
    if item is None:
        raise ValueError("unknown request_id")
    return item


def _find_queue_item(
    queue: BatchSubmissionQueue,
    request_id: str,
) -> BatchQueueItem | None:
    for item in queue.items:
        if item.request_id == request_id:
            return item
    return None


def _non_empty(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


__all__ = [
    "RECOVER_ACTION_AUTO",
    "RECOVER_ACTION_FAILED",
    "RECOVER_ACTION_SUCCEEDED",
    "RECOVER_OUTCOME_FAILED",
    "RECOVER_OUTCOME_NEEDS_MANUAL",
    "RECOVER_OUTCOME_RETRYABLE",
    "RECOVER_OUTCOME_SKIPPED",
    "RECOVER_OUTCOME_SUCCEEDED",
    "SUBMIT_OUTCOME_FAILED",
    "SUBMIT_OUTCOME_RETRYABLE",
    "SUBMIT_OUTCOME_SKIPPED",
    "SUBMIT_OUTCOME_SUCCEEDED",
    "SUBMIT_PERSIST_ERROR_TYPE",
    "BatchSubmitItemResult",
    "BatchSubmitResult",
    "PersistQueue",
    "PersistSubmitResult",
    "SubmitOne",
    "compose_legacy_submit_one",
    "retired_recover_queue_item",
    "retired_retry_queue_item",
    "serialize_batch_submit_item",
    "serialize_batch_submit_result",
    "retired_submit_queue_items",
]
