"""Best-effort legacy batch-queue <-> unified-tracking projection (US-226).

Stage 29 PRD §13 keeps the old batch pre-submission queue as a *compat
projection* for one release cycle: the unified TrackingRecord is the new
process authority, while the old queue endpoint family still exists.  This
module owns the two best-effort projection directions so neither route layer
duplicates the mapping:

- :func:`reflect_queue_outcome_into_tracking` mirrors one legacy queue item's
  final state into its unified TrackingRecord (used after the old batch
  submit/retry/recover and single submit-ab entry points);
- :func:`sync_queue_projection_for_tracking` mirrors a unified tracking state
  back into any legacy queue item bound to the same Request (used by the new
  submit/retry/recover endpoints so the old queue stays a faithful projection).

Both functions are deliberately *tolerant*: a projection failure never rolls
back the authoritative operation, never blocks a healthy sibling, and never
downgrades a durable success.  A queue item that is already ``SUCCEEDED`` is
never overwritten (post-call failure never overwrites success, §13.3); an
``ACTIVE`` TrackingRecord is never downgraded by a stale queue projection.
"""

from __future__ import annotations

from typing import Any

from batch_engine.controllers.batch_queue_controller import (
    complete_queue_item_submit,
    start_queue_item_submit,
)
from batch_engine.models import (
    BATCH_QUEUE_STATUS_FAILED,
    BATCH_QUEUE_STATUS_READY_TO_SUBMIT,
    BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED,
    BATCH_QUEUE_STATUS_RETRYABLE,
    BATCH_QUEUE_STATUS_SUBMITTING,
    BATCH_QUEUE_STATUS_SUCCEEDED,
    BatchSubmissionQueue,
)
from request_engine.controllers.request_controller import ACCEPTED
from shared.errors import Stage1Error
from storage_engine.controllers.queue_repository import (
    list_submission_queues_tolerant,
    save_submission_queue,
)
from storage_engine.controllers.request_repository import load_request_snapshot
from storage_engine.controllers.storage_config import StorageConfig
from storage_engine.controllers.tracking_repository import (
    compare_and_swap_tracking_record,
    load_tracking_record,
)
from tracking_engine.models.tracking import (
    TRACKING_AUDIT_ACTOR_SYSTEM,
    TRACKING_AUDIT_COMPAT_QUEUE_UPDATED,
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_NEEDS_RECONFIRM,
    TRACKING_STATUS_PENDING_SUBMIT,
    TRACKING_STATUS_RECOVERY_REQUIRED,
    TRACKING_STATUS_SUBMIT_FAILED,
    TRACKING_STATUS_SUBMITTING,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
    TrackingRecord,
    tracking_id_for_request,
    transition_record,
    utc_now,
)

#: Legacy queue item terminal/submitted state -> unified tracking status
#: (the §10.2 migration mapping, reused live for the compat projection).
_QUEUE_OUTCOME_TO_TRACKING: dict[str, str] = {
    BATCH_QUEUE_STATUS_READY_TO_SUBMIT: TRACKING_STATUS_PENDING_SUBMIT,
    BATCH_QUEUE_STATUS_SUBMITTING: TRACKING_STATUS_VERIFYING_EXTERNAL,
    BATCH_QUEUE_STATUS_SUCCEEDED: TRACKING_STATUS_ACTIVE,
    BATCH_QUEUE_STATUS_FAILED: TRACKING_STATUS_SUBMIT_FAILED,
    BATCH_QUEUE_STATUS_RETRYABLE: TRACKING_STATUS_SUBMIT_FAILED,
    BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED: TRACKING_STATUS_RECOVERY_REQUIRED,
}

#: Unified tracking states whose queue projection is meaningful.  Non-terminal
#: tracking states (e.g. NEEDS_RECONFIRM) never write the queue.
_TRACKING_TO_QUEUE: dict[str, str] = {
    TRACKING_STATUS_SUBMITTING: BATCH_QUEUE_STATUS_SUBMITTING,
    TRACKING_STATUS_ACTIVE: BATCH_QUEUE_STATUS_SUCCEEDED,
    TRACKING_STATUS_SUBMIT_FAILED: BATCH_QUEUE_STATUS_FAILED,
    TRACKING_STATUS_VERIFYING_EXTERNAL: BATCH_QUEUE_STATUS_SUBMITTING,
    TRACKING_STATUS_RECOVERY_REQUIRED: BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED,
}


def reflect_queue_outcome_into_tracking(
    config: StorageConfig,
    *,
    request_id: str,
    queue_status: str,
    now: str | None = None,
) -> None:
    """Mirror one legacy queue item's outcome into its unified TrackingRecord.

    Best-effort and never raising.  The Request must still be ACCEPTED (a
    cancelled/missing plan keeps its own tracking semantics); an existing
    ``ACTIVE`` TrackingRecord is never downgraded by a stale queue projection,
    and a queue ``READY_TO_SUBMIT`` item never resets an already-submitted
    record.
    """
    target = _QUEUE_OUTCOME_TO_TRACKING.get(queue_status)
    if target is None:
        return
    record = _load_tracking_record_for_request(config, request_id)
    if record is None:
        return
    if record.status == target:
        return
    if record.status in {
        TRACKING_STATUS_VERIFYING_EXTERNAL,
        TRACKING_STATUS_RECOVERY_REQUIRED,
    }:
        # An ambiguous external boundary is authoritative until the tracking
        # recovery flow resolves it.  A late legacy queue/AB response is only
        # compatibility evidence and must not turn OUTCOME_UNKNOWN or
        # RECOVERY_REQUIRED into a blindly actionable result.
        return
    if target != TRACKING_STATUS_ACTIVE and record.status == TRACKING_STATUS_ACTIVE:
        # A durable success is never downgraded by a stale/desynced queue.
        return
    if target == TRACKING_STATUS_PENDING_SUBMIT and record.status not in {
        TRACKING_STATUS_PENDING_SUBMIT,
        TRACKING_STATUS_NEEDS_RECONFIRM,
    }:
        # A READY queue item never resets an already-advanced tracking record.
        return

    next_record = transition_record(
        record,
        status=target,
        audit_action=TRACKING_AUDIT_COMPAT_QUEUE_UPDATED,
        audit_actor=TRACKING_AUDIT_ACTOR_SYSTEM,
        reason_code=f"legacy_queue_{queue_status.lower()}",
        safe_message=_projection_message(queue_status, target),
        now=now or utc_now(),
    )
    try:
        compare_and_swap_tracking_record(
            config,
            record.tracking_id,
            base_revision=record.revision,
            record=next_record,
        )
    except Stage1Error:
        return


def reflect_ab_result_into_tracking(
    config: StorageConfig,
    *,
    request_id: str,
    ab_result: Any,
    now: str | None = None,
) -> None:
    """Mirror one legacy single-plan submit-ab outcome into its TrackingRecord.

    The old ``submit-ab`` route persists a sanitized AB result; this function
    reuses the unified classification (``classify_external_submit_result``) to
    derive the tracking terminal state and advances the record through the same
    compat projection as a queue outcome.  Best-effort and never raising.
    """
    from tracking_engine.controllers.submit import classify_external_submit_result
    from tracking_engine.models.operation import (
        TRACKING_OPERATION_STATE_FAILED,
        TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
        TRACKING_OPERATION_STATE_SUCCEEDED,
    )

    operation_state = classify_external_submit_result(ab_result)
    if operation_state == TRACKING_OPERATION_STATE_SUCCEEDED:
        queue_status = BATCH_QUEUE_STATUS_SUCCEEDED
    elif operation_state == TRACKING_OPERATION_STATE_FAILED:
        queue_status = BATCH_QUEUE_STATUS_FAILED
    elif operation_state == TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN:
        queue_status = BATCH_QUEUE_STATUS_SUBMITTING
    else:  # pragma: no cover - classifier returns one of the three states above
        return
    reflect_queue_outcome_into_tracking(
        config,
        request_id=request_id,
        queue_status=queue_status,
        now=now,
    )


def sync_queue_projection_for_tracking(
    config: StorageConfig,
    *,
    request_id: str,
    tracking_status: str,
    now: str | None = None,
) -> None:
    """Mirror a unified tracking state into any legacy queue bound to the Request.

    Best-effort and never raising.  Every queue item whose ``request_id``
    matches is moved towards the projection status with the pure queue
    transitions (READY/FAILED/RETRYABLE -> SUBMITTING -> terminal).  A queue
    item already ``SUCCEEDED`` is never overwritten (§13.3 post-call failure
    never overwrites success), and damaged queue files are skipped as opaque
    ids so one damaged batch never blocks the authoritative tracking operation.
    """
    timestamp = now or utc_now()
    queue_status = _TRACKING_TO_QUEUE.get(tracking_status)
    if queue_status is None:
        return
    try:
        listed = list_submission_queues_tolerant(config)
    except Stage1Error:
        return

    for queue in listed.queues:
        updated = _apply_projection_to_queue(queue, request_id, queue_status, timestamp)
        if updated is not None and updated != queue:
            try:
                save_submission_queue(config, updated)
            except Stage1Error:
                return


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apply_projection_to_queue(
    queue: BatchSubmissionQueue,
    request_id: str,
    queue_status: str,
    timestamp: str,
) -> BatchSubmissionQueue | None:
    """Return ``queue`` with the matching item projected, or None when absent."""
    matched = [item for item in queue.items if item.request_id == request_id]
    if not matched:
        return None
    item = matched[0]
    if item.status == BATCH_QUEUE_STATUS_SUCCEEDED:
        return queue  # never overwrite a durable success
    try:
        if queue_status == BATCH_QUEUE_STATUS_SUBMITTING:
            if item.status not in {
                BATCH_QUEUE_STATUS_READY_TO_SUBMIT,
                BATCH_QUEUE_STATUS_FAILED,
                BATCH_QUEUE_STATUS_RETRYABLE,
            }:
                return queue
            return start_queue_item_submit(queue, request_id, now_factory=lambda: timestamp)
        if item.status != BATCH_QUEUE_STATUS_SUBMITTING:
            # To reach a terminal projection the item must pass through
            # SUBMITTING (the queue transition table has no READY -> terminal).
            queue = start_queue_item_submit(
                queue, request_id, now_factory=lambda: timestamp
            )
        return complete_queue_item_submit(
            queue,
            request_id,
            queue_status,
            ab_result_summary=_summary_for_success(queue_status),
            last_error=_last_error_for(queue_status),
            now_factory=lambda: timestamp,
        )
    except ValueError:
        return queue


def _load_tracking_record_for_request(
    config: StorageConfig,
    request_id: str,
) -> TrackingRecord | None:
    """Load the ACCEPTED Request's tracking record, or None when unreadable."""
    try:
        request = load_request_snapshot(config, request_id)
    except Stage1Error:
        return None
    if not isinstance(request, dict) or request.get("status") != ACCEPTED:
        return None
    tracking_id = tracking_id_for_request(request_id)
    try:
        return load_tracking_record(config, tracking_id)
    except Stage1Error:
        return None


def _summary_for_success(queue_status: str) -> dict[str, Any] | None:
    if queue_status == BATCH_QUEUE_STATUS_SUCCEEDED:
        return {"success": True}
    return None


def _last_error_for(queue_status: str) -> dict[str, Any] | None:
    if queue_status == BATCH_QUEUE_STATUS_SUCCEEDED:
        return None
    if queue_status == BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED:
        return {
            "error_type": "result_persist_failed",
            "error_message": "提交结果保存失败，需人工核验后恢复",
        }
    if queue_status == BATCH_QUEUE_STATUS_SUBMITTING:
        return None
    return {
        "error_type": "projected_submit_failed",
        "error_message": "统一追番记录反映为可重试提交失败",
    }


def _projection_message(queue_status: str, target: str) -> str:
    return {
        TRACKING_STATUS_ACTIVE: "旧队列反映该方案已提交成功",
        TRACKING_STATUS_SUBMIT_FAILED: "旧队列反映该方案提交失败，可安全重试",
        TRACKING_STATUS_RECOVERY_REQUIRED: "旧队列反映该方案需要恢复核验",
        TRACKING_STATUS_VERIFYING_EXTERNAL: "旧队列反映该方案外部结果待核验",
        TRACKING_STATUS_PENDING_SUBMIT: "旧队列反映该方案待提交",
    }.get(target, "已同步旧队列兼容状态")


__all__ = [
    "reflect_ab_result_into_tracking",
    "reflect_queue_outcome_into_tracking",
    "sync_queue_projection_for_tracking",
]
