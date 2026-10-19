"""Pure historical-backfill classification (US-221).

This module turns one Request's local evidence into a backfill decision for a
``TrackingRecord``.  It implements the evidence priority and mapping table of
Stage 29 PRD §10.2:

    existing TrackingRecord > clear AB success > batch queue > ACCEPTED Request
    > other Request states

The module is deliberately **pure** — it performs no I/O and imports no storage
repository.  The migration runner (web layer) scans local Request snapshots,
batch pre-submission queues and saved Auto Bangumi results, feeds one
``RequestBackfillEvidence`` per request id to :func:`classify_backfill`, and
persists the resulting record through ``ensure_tracking_record``.

Security
--------
Only non-sensitive conclusions leave this module.  Reason codes are fixed
enums, safe messages are fixed one-line Chinese strings, and titles/queue text
are never treated as association or deduplication evidence (Stage 29 PRD
§10.2).  No file name, path, raw JSON, credential, URL or magnet is accepted
or returned here.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from batch_engine.models.queue import (
    BATCH_QUEUE_STATUS_FAILED,
    BATCH_QUEUE_STATUS_READY_TO_SUBMIT,
    BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED,
    BATCH_QUEUE_STATUS_RETRYABLE,
    BATCH_QUEUE_STATUS_SUBMITTING,
    BATCH_QUEUE_STATUS_SUCCEEDED,
)
from request_engine.controllers.request_controller import ACCEPTED, CANCELLED, PENDING_CONFIRM
from tracking_engine.models.tracking import (
    TRACKING_AUDIT_ACTOR_MIGRATION,
    TRACKING_AUDIT_TRACKING_BACKFILLED,
    TRACKING_ORIGIN_LEGACY_ACCEPT,
    TRACKING_ORIGIN_MIGRATED_AB_RESULT,
    TRACKING_ORIGIN_MIGRATED_QUEUE,
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_PENDING_SUBMIT,
    TRACKING_STATUS_RECOVERY_REQUIRED,
    TRACKING_STATUS_SUBMIT_FAILED,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
    TrackingRecord,
    append_audit_event,
    build_audit_event,
    create_tracking_record,
    safe_poster_path,
)

# -- fixed, safe reason codes ------------------------------------------------
#: Multiple queue files disagree about one Request's outcome.
MIGRATION_REASON_QUEUE_CONFLICT = "queue_conflict"
#: The queue claims success but no readable Auto Bangumi success backs it.
MIGRATION_REASON_QUEUE_SUCCESS_WITHOUT_AB = "queue_success_without_ab_result"
#: A clear Auto Bangumi success exists while the Request is missing/abnormal.
MIGRATION_REASON_AB_SUCCESS_REQUEST_ABNORMAL = "ab_success_request_abnormal"
#: Submit evidence exists while the Request is missing/cancelled/not accepted.
MIGRATION_REASON_SUBMIT_EVIDENCE_REQUEST_ABNORMAL = "submit_evidence_request_abnormal"
#: An Auto Bangumi result object exists but its outcome is not a boolean.
MIGRATION_REASON_AB_OUTCOME_UNKNOWN = "ab_outcome_unknown"
#: A saved Auto Bangumi result file exists but could not be read.
MIGRATION_REASON_AB_UNREADABLE = "ab_result_unreadable"
#: Queue and saved-result evidence contradict each other.
MIGRATION_REASON_EVIDENCE_CONFLICT = "evidence_conflict"
#: A request appears in more than one consistent queue file.
MIGRATION_REASON_MULTIPLE_QUEUE_SOURCES = "multiple_queue_sources"
#: The queue's local result persistence failed (ambiguous submit outcome).
MIGRATION_REASON_RESULT_PERSIST_FAILED = "result_persist_failed"
#: A legacy queue/result records a clear submit failure (safe to retry).
MIGRATION_REASON_QUEUE_FAILED = "queue_failed"
MIGRATION_REASON_AB_FAILED = "ab_failed"

#: Outcome groups used for queue-conflict detection.  FAILED and RETRYABLE are
#: the same migration outcome (both mean a clear failure); every other status is
#: its own group.
_QUEUE_OUTCOME_READY = "ready"
_QUEUE_OUTCOME_SUBMITTING = "submitting"
_QUEUE_OUTCOME_SUCCEEDED = "succeeded"
_QUEUE_OUTCOME_FAILED = "failed"
_QUEUE_OUTCOME_RESULT_PERSIST_FAILED = "result_persist_failed"

_QUEUE_OUTCOME_MAP: dict[str, str] = {
    BATCH_QUEUE_STATUS_READY_TO_SUBMIT: _QUEUE_OUTCOME_READY,
    BATCH_QUEUE_STATUS_SUBMITTING: _QUEUE_OUTCOME_SUBMITTING,
    BATCH_QUEUE_STATUS_SUCCEEDED: _QUEUE_OUTCOME_SUCCEEDED,
    BATCH_QUEUE_STATUS_FAILED: _QUEUE_OUTCOME_FAILED,
    BATCH_QUEUE_STATUS_RETRYABLE: _QUEUE_OUTCOME_FAILED,
    BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED: _QUEUE_OUTCOME_RESULT_PERSIST_FAILED,
}

#: Queue outcomes that prove an Auto Bangumi submit was attempted.
_SUBMIT_EVIDENCE_OUTCOMES = frozenset(
    {
        _QUEUE_OUTCOME_SUBMITTING,
        _QUEUE_OUTCOME_SUCCEEDED,
        _QUEUE_OUTCOME_FAILED,
        _QUEUE_OUTCOME_RESULT_PERSIST_FAILED,
    }
)

_REQUEST_STATE_ACCEPTED = "accepted"
_REQUEST_STATE_PENDING = "pending"
_REQUEST_STATE_CANCELLED = "cancelled"
_REQUEST_STATE_MISSING = "missing"
_REQUEST_STATE_OTHER = "other"


@dataclass(frozen=True)
class QueueMigrationEvidence:
    """One batch pre-submission queue item referencing a Request."""

    batch_id: str
    queue_id: str
    status: str
    created_at: str | None = None


@dataclass(frozen=True)
class AbMigrationEvidence:
    """Readable outcome of a saved Auto Bangumi submit result (if any).

    ``present`` is True only when a readable ``ab_submit_result`` object exists;
    ``damaged`` is True when a saved-result file exists but could not be parsed
    (used only to make the queue-success case require human recovery).
    """

    present: bool = False
    success: bool | None = None
    error_type: str | None = None
    damaged: bool = False


@dataclass(frozen=True)
class RequestBackfillEvidence:
    """All local evidence for one candidate ``request_id``."""

    request_id: str
    #: The readable Request snapshot, or None when the Request is missing.
    request: dict[str, Any] | None = None
    queue_items: tuple[QueueMigrationEvidence, ...] = ()
    ab: AbMigrationEvidence = field(default_factory=AbMigrationEvidence)


@dataclass(frozen=True)
class BackfillDecision:
    """A safe migration conclusion for one Request.

    ``create=False`` means the evidence does not justify creating a tracking
    record (e.g. a PENDING_CONFIRM/CANCELLED Request with no submit evidence).
    """

    request_id: str
    create: bool = False
    status: str | None = None
    origin: str | None = None
    reason_code: str | None = None
    safe_message: str | None = None
    batch_id: str | None = None
    #: Additional consistent queue sources beyond the one whose batch_id was
    #: kept.  The runner writes one safe audit event per extra source.
    extra_queue_source_count: int = 0


def classify_backfill(evidence: RequestBackfillEvidence) -> BackfillDecision:
    """Return the backfill decision for one Request (§10.2 mapping)."""
    request_id = evidence.request_id
    request = evidence.request
    ab = evidence.ab
    req_state = _request_state(request)

    outcomes = tuple(
        _QUEUE_OUTCOME_MAP.get(item.status)
        for item in evidence.queue_items
        if _QUEUE_OUTCOME_MAP.get(item.status) is not None
    )
    distinct_outcomes = frozenset(outcomes)
    outcome = next(iter(distinct_outcomes)) if len(distinct_outcomes) == 1 else None
    # An unknown queue status is treated as invalid storage by the repository,
    # so the runner should never hand us one; defensively ignore it.

    batch_id, extra_count = _pick_batch(evidence.queue_items)

    # 1. Clear Auto Bangumi success is the strongest evidence and blocks
    #    duplicate submission.
    if ab.present and ab.success is True:
        if req_state == _REQUEST_STATE_ACCEPTED:
            return _decision(
                request_id,
                status=TRACKING_STATUS_ACTIVE,
                origin=_origin_for(evidence, ab_present=True),
                batch_id=batch_id,
                extra_queue_source_count=extra_count,
                # Issue #224 A1: the backfill audit text uses the one status
                # vocabulary, so it can never re-introduce「正在追番」.
                safe_message="历史 Auto Bangumi 结果已确认成功，记录为追番中",
            )
        return _decision(
            request_id,
            status=TRACKING_STATUS_RECOVERY_REQUIRED,
            origin=_origin_for(evidence, ab_present=True),
            reason_code=MIGRATION_REASON_AB_SUCCESS_REQUEST_ABNORMAL,
            batch_id=batch_id,
            extra_queue_source_count=extra_count,
            safe_message="存在成功提交证据但本地方案缺失或已取消，需要人工恢复",
        )

    # 2. Conflicting queue outcomes force recovery.
    if len(distinct_outcomes) > 1:
        return _decision(
            request_id,
            status=TRACKING_STATUS_RECOVERY_REQUIRED,
            origin=TRACKING_ORIGIN_MIGRATED_QUEUE,
            reason_code=MIGRATION_REASON_QUEUE_CONFLICT,
            safe_message="多个历史队列记录对该方案的状态不一致，需要人工恢复",
        )

    # 3. A queue that claims success requires a readable AB success.
    if outcome == _QUEUE_OUTCOME_SUCCEEDED and not (ab.present and ab.success is True):
        return _decision(
            request_id,
            status=TRACKING_STATUS_RECOVERY_REQUIRED,
            origin=TRACKING_ORIGIN_MIGRATED_QUEUE,
            reason_code=MIGRATION_REASON_QUEUE_SUCCESS_WITHOUT_AB,
            batch_id=batch_id,
            extra_queue_source_count=extra_count,
            safe_message="历史队列标记为成功但缺少可确认的 Auto Bangumi 结果，需要人工恢复",
        )

    # 3b. An ACCEPTED Request whose only saved result file is unreadable has an
    #     unknown submit outcome.  Never silently downgrade it to PENDING_SUBMIT
    #     (which would allow a duplicate external submission).
    if (
        not ab.present
        and ab.damaged
        and req_state == _REQUEST_STATE_ACCEPTED
        and outcome in (None, _QUEUE_OUTCOME_READY)
    ):
        return _decision(
            request_id,
            status=TRACKING_STATUS_RECOVERY_REQUIRED,
            origin=_origin_for(evidence, ab_present=False),
            reason_code=MIGRATION_REASON_AB_UNREADABLE,
            batch_id=batch_id,
            extra_queue_source_count=extra_count,
            safe_message="已保存的 Auto Bangumi 提交结果无法读取，需要人工恢复",
        )

    # 4. Submit evidence on a missing/cancelled/not-accepted Request.
    if req_state != _REQUEST_STATE_ACCEPTED:
        submit_evidence = outcome in _SUBMIT_EVIDENCE_OUTCOMES or ab.present or ab.damaged
        if submit_evidence:
            return _decision(
                request_id,
                status=TRACKING_STATUS_RECOVERY_REQUIRED,
                origin=_origin_for(evidence, ab_present=ab.present),
                reason_code=MIGRATION_REASON_SUBMIT_EVIDENCE_REQUEST_ABNORMAL,
                batch_id=batch_id,
                extra_queue_source_count=extra_count,
                safe_message="存在提交证据但本地方案缺失或状态异常，需要人工恢复",
            )
        # PENDING_CONFIRM / CANCELLED / missing with no submit evidence: no record.
        return BackfillDecision(request_id=request_id, create=False)

    # 5. ACCEPTED Request with a single queue outcome.
    if outcome == _QUEUE_OUTCOME_READY:
        if ab.present and ab.success is not None:
            return _decision(
                request_id,
                status=TRACKING_STATUS_RECOVERY_REQUIRED,
                origin=TRACKING_ORIGIN_MIGRATED_QUEUE,
                reason_code=MIGRATION_REASON_EVIDENCE_CONFLICT,
                batch_id=batch_id,
                extra_queue_source_count=extra_count,
                safe_message="历史队列显示尚未提交但存在已保存的提交结果，需要人工恢复",
            )
        return _decision(
            request_id,
            status=TRACKING_STATUS_PENDING_SUBMIT,
            origin=TRACKING_ORIGIN_MIGRATED_QUEUE,
            batch_id=batch_id,
            extra_queue_source_count=extra_count,
            safe_message="历史队列记录显示方案待提交",
        )
    if outcome == _QUEUE_OUTCOME_SUBMITTING:
        if ab.present and ab.success is False:
            return _decision(
                request_id,
                status=TRACKING_STATUS_RECOVERY_REQUIRED,
                origin=TRACKING_ORIGIN_MIGRATED_QUEUE,
                reason_code=MIGRATION_REASON_EVIDENCE_CONFLICT,
                batch_id=batch_id,
                extra_queue_source_count=extra_count,
                safe_message="历史队列停留在提交中但结果已保存为失败，需要人工恢复",
            )
        return _decision(
            request_id,
            status=TRACKING_STATUS_VERIFYING_EXTERNAL,
            origin=TRACKING_ORIGIN_MIGRATED_QUEUE,
            batch_id=batch_id,
            extra_queue_source_count=extra_count,
            safe_message="历史队列显示提交中断，需要核验外部结果",
        )
    if outcome == _QUEUE_OUTCOME_FAILED:
        return _decision(
            request_id,
            status=TRACKING_STATUS_SUBMIT_FAILED,
            origin=TRACKING_ORIGIN_MIGRATED_QUEUE,
            reason_code=MIGRATION_REASON_QUEUE_FAILED,
            batch_id=batch_id,
            extra_queue_source_count=extra_count,
            safe_message="历史队列记录显示提交失败，可安全重试",
        )
    if outcome == _QUEUE_OUTCOME_RESULT_PERSIST_FAILED:
        return _decision(
            request_id,
            status=TRACKING_STATUS_RECOVERY_REQUIRED,
            origin=TRACKING_ORIGIN_MIGRATED_QUEUE,
            reason_code=MIGRATION_REASON_RESULT_PERSIST_FAILED,
            batch_id=batch_id,
            extra_queue_source_count=extra_count,
            safe_message="历史队列结果保存失败，需要人工恢复",
        )

    # 6. ACCEPTED Request with no queue evidence.
    if ab.present and ab.success is False:
        return _decision(
            request_id,
            status=TRACKING_STATUS_SUBMIT_FAILED,
            origin=TRACKING_ORIGIN_MIGRATED_AB_RESULT,
            reason_code=MIGRATION_REASON_AB_FAILED,
            safe_message="历史提交结果明确失败，可安全重试",
        )
    if ab.present and ab.success is None:
        return _decision(
            request_id,
            status=TRACKING_STATUS_RECOVERY_REQUIRED,
            origin=TRACKING_ORIGIN_MIGRATED_AB_RESULT,
            reason_code=MIGRATION_REASON_AB_OUTCOME_UNKNOWN,
            safe_message="历史提交结果无法确认成败，需要人工恢复",
        )
    # ACCEPTED Request alone (a legacy single-plan accept): PENDING_SUBMIT.
    return _decision(
        request_id,
        status=TRACKING_STATUS_PENDING_SUBMIT,
        origin=TRACKING_ORIGIN_LEGACY_ACCEPT,
        safe_message="本地已确认方案尚未提交，记录为待提交",
    )


def plan_summary_from_request(
    request: dict[str, Any] | None,
    *,
    poster_path: str | None = None,
) -> dict[str, Any]:
    """Return a safe display ``plan_summary`` for a Request snapshot.

    Only public display fields participate (matched title, integer season,
    selected subtitle group).  ``poster_path`` is supplied by the adapter that
    owns the poster cache — it must already be a same-origin opaque route, and
    anything else (an upstream image URL, an absolute path, traversal) is
    dropped rather than persisted.  Legacy requests carry no poster reference,
    so the summary simply omits the field.
    """
    if not isinstance(request, dict):
        return {}
    source_info = request.get("source_info")
    matched = source_info.get("matched_bangumi") if isinstance(source_info, dict) else None
    confirmable = request.get("confirmable_config")
    summary: dict[str, Any] = {}

    if isinstance(matched, dict):
        title = matched.get("title")
        if isinstance(title, str) and title.strip():
            summary["title"] = title.strip()
        season = matched.get("season")
        if isinstance(season, int) and not isinstance(season, bool):
            summary["season"] = season
    if isinstance(confirmable, dict):
        subtitle_group = confirmable.get("selected_subtitle_group")
        if isinstance(subtitle_group, str) and subtitle_group.strip():
            summary["subtitle_group"] = subtitle_group.strip()
    safe_poster = safe_poster_path(poster_path)
    if safe_poster is not None:
        summary["poster_path"] = safe_poster
    return summary


def build_backfill_record(
    *,
    decision: BackfillDecision,
    request: dict[str, Any] | None,
    request_fingerprint: str | None,
    now: str,
    poster_path: str | None = None,
) -> TrackingRecord:
    """Build the revision-1 ``TrackingRecord`` for a create decision.

    The returned record embeds its ``TRACKING_BACKFILLED`` audit event (plus one
    safe audit event per extra consistent queue source) and a sanitized
    ``last_error`` on failed/recovery outcomes.  The runner persists it through
    ``ensure_tracking_record`` which never overwrites an existing record.
    ``poster_path`` is the adapter-resolved same-origin cover reference.
    """
    if not decision.create or decision.status is None or decision.origin is None:
        raise ValueError("cannot build a backfill record for a non-create decision")

    record = create_tracking_record(
        request_id=decision.request_id,
        status=decision.status,
        plan_summary=plan_summary_from_request(request, poster_path=poster_path),
        origin=decision.origin,
        batch_id=decision.batch_id,
        request_fingerprint=request_fingerprint,
        audit_action=TRACKING_AUDIT_TRACKING_BACKFILLED,
        audit_actor=TRACKING_AUDIT_ACTOR_MIGRATION,
        audit_message=decision.safe_message,
        now=now,
    )

    if decision.status in {
        TRACKING_STATUS_SUBMIT_FAILED,
        TRACKING_STATUS_RECOVERY_REQUIRED,
    }:
        record = replace(
            record,
            last_error={
                "error_type": "migration",
                "reason_code": decision.reason_code or "migrated",
                "safe_message": decision.safe_message or "历史数据迁移需要处理",
            },
        )

    for _ in range(decision.extra_queue_source_count):
        record = append_audit_event(
            record,
            build_audit_event(
                action=TRACKING_AUDIT_TRACKING_BACKFILLED,
                actor=TRACKING_AUDIT_ACTOR_MIGRATION,
                from_status=None,
                to_status=decision.status,
                tracking_revision=record.revision,
                reason_code=MIGRATION_REASON_MULTIPLE_QUEUE_SOURCES,
                safe_message="同一方案出现在多个一致的历史队列，已保留最早批次",
                created_at=now,
            ),
        )
    return record


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _request_state(request: dict[str, Any] | None) -> str:
    if request is None:
        return _REQUEST_STATE_MISSING
    status = request.get("status")
    if status == ACCEPTED:
        return _REQUEST_STATE_ACCEPTED
    if status == PENDING_CONFIRM:
        return _REQUEST_STATE_PENDING
    if status == CANCELLED:
        return _REQUEST_STATE_CANCELLED
    return _REQUEST_STATE_OTHER


def _origin_for(evidence: RequestBackfillEvidence, *, ab_present: bool) -> str:
    if evidence.queue_items:
        return TRACKING_ORIGIN_MIGRATED_QUEUE
    if ab_present:
        return TRACKING_ORIGIN_MIGRATED_AB_RESULT
    return TRACKING_ORIGIN_LEGACY_ACCEPT


def _pick_batch(
    queue_items: tuple[QueueMigrationEvidence, ...],
) -> tuple[str | None, int]:
    """Pick the earliest consistent batch and count extra consistent sources."""
    if not queue_items:
        return None, 0
    ordered = sorted(
        queue_items,
        key=lambda item: (item.created_at is not None, item.created_at or "", item.batch_id),
    )
    return ordered[0].batch_id, len(ordered) - 1


def _decision(
    request_id: str,
    *,
    status: str,
    origin: str,
    reason_code: str | None = None,
    safe_message: str | None,
    batch_id: str | None = None,
    extra_queue_source_count: int = 0,
) -> BackfillDecision:
    return BackfillDecision(
        request_id=request_id,
        create=True,
        status=status,
        origin=origin,
        reason_code=reason_code,
        safe_message=safe_message,
        batch_id=batch_id,
        extra_queue_source_count=extra_queue_source_count,
    )


__all__ = [
    "MIGRATION_REASON_AB_FAILED",
    "MIGRATION_REASON_AB_OUTCOME_UNKNOWN",
    "MIGRATION_REASON_AB_SUCCESS_REQUEST_ABNORMAL",
    "MIGRATION_REASON_AB_UNREADABLE",
    "MIGRATION_REASON_EVIDENCE_CONFLICT",
    "MIGRATION_REASON_MULTIPLE_QUEUE_SOURCES",
    "MIGRATION_REASON_QUEUE_CONFLICT",
    "MIGRATION_REASON_QUEUE_FAILED",
    "MIGRATION_REASON_QUEUE_SUCCESS_WITHOUT_AB",
    "MIGRATION_REASON_RESULT_PERSIST_FAILED",
    "MIGRATION_REASON_SUBMIT_EVIDENCE_REQUEST_ABNORMAL",
    "AbMigrationEvidence",
    "BackfillDecision",
    "QueueMigrationEvidence",
    "RequestBackfillEvidence",
    "build_backfill_record",
    "classify_backfill",
    "plan_summary_from_request",
]
