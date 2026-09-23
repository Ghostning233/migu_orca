from __future__ import annotations

"""US-221: pure historical-backfill classifier tests (Stage 29 PRD §10.2)."""

import pytest

from batch_engine.models.queue import (
    BATCH_QUEUE_STATUS_FAILED,
    BATCH_QUEUE_STATUS_READY_TO_SUBMIT,
    BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED,
    BATCH_QUEUE_STATUS_RETRYABLE,
    BATCH_QUEUE_STATUS_SUBMITTING,
    BATCH_QUEUE_STATUS_SUCCEEDED,
)
from request_engine.controllers.request_controller import ACCEPTED, CANCELLED, PENDING_CONFIRM
from tracking_engine.controllers.migration import (
    MIGRATION_REASON_AB_FAILED,
    MIGRATION_REASON_AB_OUTCOME_UNKNOWN,
    MIGRATION_REASON_AB_SUCCESS_REQUEST_ABNORMAL,
    MIGRATION_REASON_AB_UNREADABLE,
    MIGRATION_REASON_EVIDENCE_CONFLICT,
    MIGRATION_REASON_QUEUE_CONFLICT,
    MIGRATION_REASON_QUEUE_FAILED,
    MIGRATION_REASON_QUEUE_SUCCESS_WITHOUT_AB,
    MIGRATION_REASON_RESULT_PERSIST_FAILED,
    MIGRATION_REASON_SUBMIT_EVIDENCE_REQUEST_ABNORMAL,
    AbMigrationEvidence,
    QueueMigrationEvidence,
    RequestBackfillEvidence,
    build_backfill_record,
    classify_backfill,
    plan_summary_from_request,
)
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
)

NOW = "2026-09-08T00:00:00+00:00"


def _request(request_id: str = "req-1", status: str = ACCEPTED) -> dict[str, object]:
    return {
        "request_id": request_id,
        "status": status,
        "input": {"raw_title": "芙莉莲"},
        "source_info": {
            "matched_bangumi": {"title": "葬送的芙莉莲", "season": 2, "aliases": []},
            "rss_sources": [],
        },
        "confirmable_config": {
            "selected_subtitle_group": "喵萌奶茶屋",
            "filter_rule": {
                "must_contain": "",
                "must_not_contain": "",
                "use_regex": False,
                "case_sensitive": False,
            },
            "expected_folder_name": "芙莉莲",
            "effective_seed_names": [],
        },
    }


def _evidence(
    request_id: str = "req-1",
    request: dict[str, object] | None = None,
    queue: tuple[QueueMigrationEvidence, ...] = (),
    ab: AbMigrationEvidence | None = None,
) -> RequestBackfillEvidence:
    return RequestBackfillEvidence(
        request_id=request_id,
        request=request,
        queue_items=queue,
        ab=ab or AbMigrationEvidence(),
    )


def _queue(batch_id: str, status: str, *, created_at: str | None = None) -> QueueMigrationEvidence:
    return QueueMigrationEvidence(
        batch_id=batch_id,
        queue_id=f"queue-{batch_id}",
        status=status,
        created_at=created_at,
    )


def _ab(success: bool | None = None, *, present: bool = True, damaged: bool = False) -> AbMigrationEvidence:
    return AbMigrationEvidence(present=present, success=success, damaged=damaged)


# -- §10.2 row coverage ------------------------------------------------------


def test_accepted_request_without_evidence_becomes_pending_submit() -> None:
    decision = classify_backfill(_evidence(request=_request()))

    assert decision.create is True
    assert decision.status == TRACKING_STATUS_PENDING_SUBMIT
    assert decision.origin == TRACKING_ORIGIN_LEGACY_ACCEPT
    assert decision.batch_id is None


def test_queue_ready_to_submit_becomes_pending_submit() -> None:
    decision = classify_backfill(
        _evidence(
            request=_request(),
            queue=(_queue("batch-a", BATCH_QUEUE_STATUS_READY_TO_SUBMIT),),
        )
    )

    assert decision.status == TRACKING_STATUS_PENDING_SUBMIT
    assert decision.origin == TRACKING_ORIGIN_MIGRATED_QUEUE
    assert decision.batch_id == "batch-a"


def test_queue_submitting_becomes_verifying_external() -> None:
    decision = classify_backfill(
        _evidence(
            request=_request(),
            queue=(_queue("batch-a", BATCH_QUEUE_STATUS_SUBMITTING),),
        )
    )

    assert decision.status == TRACKING_STATUS_VERIFYING_EXTERNAL
    assert decision.origin == TRACKING_ORIGIN_MIGRATED_QUEUE


def test_queue_failed_and_retryable_become_submit_failed() -> None:
    for status in (BATCH_QUEUE_STATUS_FAILED, BATCH_QUEUE_STATUS_RETRYABLE):
        decision = classify_backfill(
            _evidence(
                request=_request(),
                queue=(_queue("batch-a", status),),
            )
        )
        assert decision.status == TRACKING_STATUS_SUBMIT_FAILED
        assert decision.origin == TRACKING_ORIGIN_MIGRATED_QUEUE
        assert decision.reason_code == MIGRATION_REASON_QUEUE_FAILED


def test_queue_result_persist_failed_becomes_recovery_required() -> None:
    decision = classify_backfill(
        _evidence(
            request=_request(),
            queue=(_queue("batch-a", BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED),),
        )
    )

    assert decision.status == TRACKING_STATUS_RECOVERY_REQUIRED
    assert decision.reason_code == MIGRATION_REASON_RESULT_PERSIST_FAILED


def test_queue_succeeded_with_ab_success_becomes_active() -> None:
    decision = classify_backfill(
        _evidence(
            request=_request(),
            queue=(_queue("batch-a", BATCH_QUEUE_STATUS_SUCCEEDED),),
            ab=_ab(True),
        )
    )

    assert decision.status == TRACKING_STATUS_ACTIVE


def test_queue_succeeded_without_ab_becomes_recovery_required() -> None:
    decision = classify_backfill(
        _evidence(
            request=_request(),
            queue=(_queue("batch-a", BATCH_QUEUE_STATUS_SUCCEEDED),),
        )
    )

    assert decision.status == TRACKING_STATUS_RECOVERY_REQUIRED
    assert decision.reason_code == MIGRATION_REASON_QUEUE_SUCCESS_WITHOUT_AB


def test_queue_succeeded_with_failed_ab_becomes_recovery_required() -> None:
    decision = classify_backfill(
        _evidence(
            request=_request(),
            queue=(_queue("batch-a", BATCH_QUEUE_STATUS_SUCCEEDED),),
            ab=_ab(False),
        )
    )

    assert decision.status == TRACKING_STATUS_RECOVERY_REQUIRED
    assert decision.reason_code == MIGRATION_REASON_QUEUE_SUCCESS_WITHOUT_AB


def test_ab_success_with_accepted_request_becomes_active() -> None:
    decision = classify_backfill(_evidence(request=_request(), ab=_ab(True)))

    assert decision.status == TRACKING_STATUS_ACTIVE
    assert decision.origin == TRACKING_ORIGIN_MIGRATED_AB_RESULT


def test_ab_success_with_missing_request_becomes_recovery_required() -> None:
    decision = classify_backfill(_evidence(request=None, ab=_ab(True)))

    assert decision.status == TRACKING_STATUS_RECOVERY_REQUIRED
    assert decision.reason_code == MIGRATION_REASON_AB_SUCCESS_REQUEST_ABNORMAL


def test_ab_failure_with_accepted_request_becomes_submit_failed() -> None:
    decision = classify_backfill(_evidence(request=_request(), ab=_ab(False)))

    assert decision.status == TRACKING_STATUS_SUBMIT_FAILED
    assert decision.origin == TRACKING_ORIGIN_MIGRATED_AB_RESULT
    assert decision.reason_code == MIGRATION_REASON_AB_FAILED


def test_ab_unknown_outcome_with_accepted_request_becomes_recovery_required() -> None:
    decision = classify_backfill(_evidence(request=_request(), ab=_ab(None)))

    assert decision.status == TRACKING_STATUS_RECOVERY_REQUIRED
    assert decision.reason_code == MIGRATION_REASON_AB_OUTCOME_UNKNOWN


def test_unreadable_ab_with_accepted_request_becomes_recovery_required() -> None:
    decision = classify_backfill(
        _evidence(request=_request(), ab=AbMigrationEvidence(present=False, damaged=True))
    )

    assert decision.status == TRACKING_STATUS_RECOVERY_REQUIRED
    assert decision.reason_code == MIGRATION_REASON_AB_UNREADABLE


def test_conflicting_queue_statuses_become_recovery_required() -> None:
    decision = classify_backfill(
        _evidence(
            request=_request(),
            queue=(
                _queue("batch-a", BATCH_QUEUE_STATUS_FAILED),
                _queue("batch-b", BATCH_QUEUE_STATUS_SUCCEEDED),
            ),
        )
    )

    assert decision.status == TRACKING_STATUS_RECOVERY_REQUIRED
    assert decision.reason_code == MIGRATION_REASON_QUEUE_CONFLICT


def test_consistent_multiple_queue_sources_keep_earliest_batch() -> None:
    decision = classify_backfill(
        _evidence(
            request=_request(),
            queue=(
                _queue("batch-b", BATCH_QUEUE_STATUS_READY_TO_SUBMIT, created_at="2026-09-08T00:02:00+00:00"),
                _queue("batch-a", BATCH_QUEUE_STATUS_READY_TO_SUBMIT, created_at="2026-09-08T00:01:00+00:00"),
            ),
        )
    )

    assert decision.status == TRACKING_STATUS_PENDING_SUBMIT
    assert decision.batch_id == "batch-a"
    assert decision.extra_queue_source_count == 1


def test_pending_request_without_evidence_is_not_created() -> None:
    decision = classify_backfill(
        _evidence(request=_request(status=PENDING_CONFIRM))
    )

    assert decision.create is False


def test_cancelled_request_with_queue_ready_is_not_created() -> None:
    decision = classify_backfill(
        _evidence(
            request=_request(status=CANCELLED),
            queue=(_queue("batch-a", BATCH_QUEUE_STATUS_READY_TO_SUBMIT),),
        )
    )

    assert decision.create is False


def test_missing_request_with_queue_ready_is_not_created() -> None:
    decision = classify_backfill(
        _evidence(
            request=None,
            queue=(_queue("batch-a", BATCH_QUEUE_STATUS_READY_TO_SUBMIT),),
        )
    )

    assert decision.create is False


def test_non_accepted_request_with_submit_evidence_becomes_recovery_required() -> None:
    for status in (CANCELLED, PENDING_CONFIRM):
        for queue_status in (
            BATCH_QUEUE_STATUS_FAILED,
            BATCH_QUEUE_STATUS_SUBMITTING,
            BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED,
        ):
            decision = classify_backfill(
                _evidence(
                    request=_request(status=status),
                    queue=(_queue("batch-a", queue_status),),
                )
            )
            assert decision.status == TRACKING_STATUS_RECOVERY_REQUIRED
            assert decision.reason_code == MIGRATION_REASON_SUBMIT_EVIDENCE_REQUEST_ABNORMAL


def test_queue_ready_with_saved_ab_failure_is_conflict_recovery() -> None:
    decision = classify_backfill(
        _evidence(
            request=_request(),
            queue=(_queue("batch-a", BATCH_QUEUE_STATUS_READY_TO_SUBMIT),),
            ab=_ab(False),
        )
    )

    assert decision.status == TRACKING_STATUS_RECOVERY_REQUIRED
    assert decision.reason_code == MIGRATION_REASON_EVIDENCE_CONFLICT


def test_ab_success_wins_over_failed_queue() -> None:
    decision = classify_backfill(
        _evidence(
            request=_request(),
            queue=(_queue("batch-a", BATCH_QUEUE_STATUS_FAILED),),
            ab=_ab(True),
        )
    )

    assert decision.status == TRACKING_STATUS_ACTIVE


# -- plan summary & record building ------------------------------------------


def test_plan_summary_from_request_uses_only_public_display_fields() -> None:
    summary = plan_summary_from_request(_request())

    assert summary == {"title": "葬送的芙莉莲", "season": 2, "subtitle_group": "喵萌奶茶屋"}
    assert "poster_path" not in summary


def test_plan_summary_keeps_only_a_same_origin_opaque_poster_path() -> None:
    poster_path = f"/api/v1/mikan/posters/{'a' * 64}"

    summary = plan_summary_from_request(_request(), poster_path=poster_path)

    assert summary["poster_path"] == poster_path


@pytest.mark.parametrize(
    "unsafe",
    [
        "https://mikan.example/cover.jpg",
        "//mikan.example/cover.jpg",
        "/api/v1/mikan/posters/../escape",
        "/api/v1/mikan/posters/",
        "/api/v1/mikan/posters/a b",
        "/etc/passwd",
        "",
    ],
)
def test_plan_summary_rejects_unsafe_poster_references(unsafe: str) -> None:
    assert "poster_path" not in plan_summary_from_request(_request(), poster_path=unsafe)


def test_plan_summary_from_non_request_is_empty() -> None:
    assert plan_summary_from_request(None) == {}
    assert plan_summary_from_request({"request_id": "x"}) == {}


def test_build_backfill_record_keeps_revision_one_and_embedds_audit() -> None:
    decision = classify_backfill(_evidence(request=_request()))
    record = build_backfill_record(
        decision=decision,
        request=_request(),
        request_fingerprint="fp",
        now=NOW,
    )

    assert record.revision == 1
    assert record.tracking_id.startswith("trk_")
    assert record.status == TRACKING_STATUS_PENDING_SUBMIT
    assert record.request_fingerprint == "fp"
    assert record.plan_summary["title"] == "葬送的芙莉莲"
    assert len(record.audit_events) == 1
    assert record.audit_events[0]["actor"] == TRACKING_AUDIT_ACTOR_MIGRATION
    assert record.audit_events[0]["action"] == TRACKING_AUDIT_TRACKING_BACKFILLED
    assert record.last_error is None


def test_build_backfill_record_adds_last_error_for_recovery() -> None:
    decision = classify_backfill(
        _evidence(
            request=_request(),
            queue=(_queue("batch-a", BATCH_QUEUE_STATUS_SUCCEEDED),),
        )
    )
    record = build_backfill_record(
        decision=decision,
        request=_request(),
        request_fingerprint=None,
        now=NOW,
    )

    assert record.status == TRACKING_STATUS_RECOVERY_REQUIRED
    assert record.last_error is not None
    assert record.last_error["reason_code"] == MIGRATION_REASON_QUEUE_SUCCESS_WITHOUT_AB
    assert record.last_error["error_type"] == "migration"


def test_build_backfill_record_adds_extra_source_audit_events() -> None:
    decision = classify_backfill(
        _evidence(
            request=_request(),
            queue=(
                _queue("batch-b", BATCH_QUEUE_STATUS_READY_TO_SUBMIT, created_at="2026-09-08T00:02:00+00:00"),
                _queue("batch-a", BATCH_QUEUE_STATUS_READY_TO_SUBMIT, created_at="2026-09-08T00:01:00+00:00"),
            ),
        )
    )
    record = build_backfill_record(
        decision=decision,
        request=_request(),
        request_fingerprint=None,
        now=NOW,
    )

    assert record.revision == 1
    assert len(record.audit_events) == 2
    assert all(event["actor"] == TRACKING_AUDIT_ACTOR_MIGRATION for event in record.audit_events)
