from __future__ import annotations

"""US-221: migration runner service end-to-end tests.

These exercise ``run_tracking_migration`` against a real ``tmp_path`` storage
profile: pure-local backfill, §10.2 classification through the repository seam,
idempotency (no new records / no revision change / no duplicate audit), the
PARTIAL/COMPLETE manifest lifecycle and damaged-file safety.
"""

from pathlib import Path
from typing import Any

from apps.migu_orca_web.tracking_migration_service import (
    MIGRATION_PARTIAL_WARNING,
    run_tracking_migration,
)
from batch_engine.models.queue import (
    BATCH_QUEUE_STATUS_FAILED,
    BATCH_QUEUE_STATUS_READY_TO_SUBMIT,
    BATCH_QUEUE_STATUS_SUBMITTING,
    BATCH_QUEUE_STATUS_SUCCEEDED,
    BatchQueueItem,
    BatchSubmissionQueue,
)
from request_engine.controllers.request_controller import ACCEPTED, PENDING_CONFIRM
from storage_engine.controllers.ab_result_repository import save_ab_submit_result
from storage_engine.controllers.queue_repository import save_submission_queue
from storage_engine.controllers.request_repository import save_request_snapshot
from storage_engine.controllers.storage_config import (
    StorageConfig,
    load_storage_config,
)
from storage_engine.controllers.tracking_repository import (
    list_tracking_records,
    load_tracking_record,
)
from tracking_engine.controllers.migration import MIGRATION_REASON_MULTIPLE_QUEUE_SOURCES
from tracking_engine.models.migration import MIGRATION_STATE_COMPLETE, MIGRATION_STATE_PARTIAL
from tracking_engine.models.tracking import (
    TRACKING_AUDIT_ACTOR_MIGRATION,
    TRACKING_ORIGIN_LEGACY_ACCEPT,
    TRACKING_ORIGIN_MIGRATED_QUEUE,
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_PENDING_SUBMIT,
    TRACKING_STATUS_RECOVERY_REQUIRED,
    TRACKING_STATUS_SUBMIT_FAILED,
    TrackingRecord,
    tracking_id_for_request,
)

NOW = "2026-09-08T00:00:00+00:00"


def _config(tmp_path: Path) -> StorageConfig:
    return load_storage_config(tmp_path / "migu-state")


def _accepted_request(request_id: str, *, title: str = "葬送的芙莉莲") -> dict[str, Any]:
    return {
        "request_id": request_id,
        "status": ACCEPTED,
        "input": {"raw_title": title},
        "source_info": {
            "matched_bangumi": {"title": title, "season": 2, "aliases": []},
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
            "expected_folder_name": title,
            "effective_seed_names": [],
        },
        "created_at": NOW,
        "updated_at": NOW,
    }


def _pending_request(request_id: str) -> dict[str, Any]:
    return {**_accepted_request(request_id), "status": PENDING_CONFIRM}


def _save_request(config: StorageConfig, request: dict[str, Any]) -> None:
    save_request_snapshot(config, request)


def _save_queue(
    config: StorageConfig,
    batch_id: str,
    entries: list[tuple[str, str]],
) -> None:
    items = [
        BatchQueueItem(
            queue_id=f"queue-{batch_id}",
            batch_id=batch_id,
            item_id=f"item-{index}",
            request_id=request_id,
            title="占位标题",
            status=status,
            created_at=NOW,
            updated_at=NOW,
        )
        for index, (request_id, status) in enumerate(entries)
    ]
    save_submission_queue(
        config,
        BatchSubmissionQueue(
            queue_id=f"queue-{batch_id}",
            batch_id=batch_id,
            items=items,
            created_at=NOW,
            updated_at=NOW,
        ),
    )


def _save_ab(config: StorageConfig, request_id: str, *, success: bool) -> None:
    save_ab_submit_result(
        config,
        {
            "request_id": request_id,
            "ab_submit_result": {
                "success": success,
                "ab_subscription_id": "ab-123" if success else None,
                "error": None if success else {"error_type": "ab_rejected"},
            },
        },
    )


def _tracking(config: StorageConfig, request_id: str) -> TrackingRecord:
    return load_tracking_record(config, tracking_id_for_request(request_id))


def _manifest_path(config: StorageConfig) -> Path:
    return config.tracking_migrations_dir / "schema-v1.json"


# -- happy paths -------------------------------------------------------------


def test_empty_storage_writes_complete_manifest_and_replays(tmp_path: Path) -> None:
    config = _config(tmp_path)

    first = run_tracking_migration(config=config, now=NOW)
    second = run_tracking_migration(config=config, now=NOW)

    assert first.manifest.state == MIGRATION_STATE_COMPLETE
    assert first.manifest.counts.created == 0
    assert second.replayed is True
    assert first.warning() is None
    assert _manifest_path(config).exists()


def test_accepted_request_backfills_legacy_pending_submit(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _save_request(config, _accepted_request("req-accepted"))

    result = run_tracking_migration(config=config, now=NOW)

    assert result.manifest.state == MIGRATION_STATE_COMPLETE
    assert result.manifest.counts.created == 1
    record = _tracking(config, "req-accepted")
    assert record.status == TRACKING_STATUS_PENDING_SUBMIT
    assert record.origin == TRACKING_ORIGIN_LEGACY_ACCEPT
    assert record.plan_summary["title"] == "葬送的芙莉莲"
    assert record.revision == 1
    assert len(record.audit_events) == 1


def test_complete_manifest_skips_future_full_scan(tmp_path: Path) -> None:
    config = _config(tmp_path)
    first = run_tracking_migration(config=config, now=NOW)
    assert first.complete

    # A legacy request added after COMPLETE is only tracked in real time by the
    # accept/save-confirm handoff; the migration must not create it.
    _save_request(config, _accepted_request("req-late"))
    second = run_tracking_migration(config=config, now=NOW)

    assert second.replayed is True
    assert list_tracking_records(config).records == []


def test_queue_ready_backfills_migrated_queue_pending(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _save_request(config, _accepted_request("req-1"))
    _save_queue(config, "batch-1", [("req-1", BATCH_QUEUE_STATUS_READY_TO_SUBMIT)])

    run_tracking_migration(config=config, now=NOW)

    record = _tracking(config, "req-1")
    assert record.status == TRACKING_STATUS_PENDING_SUBMIT
    assert record.origin == TRACKING_ORIGIN_MIGRATED_QUEUE
    assert record.batch_id == "batch-1"


def test_queue_failed_backfills_submit_failed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _save_request(config, _accepted_request("req-1"))
    _save_queue(config, "batch-1", [("req-1", BATCH_QUEUE_STATUS_FAILED)])

    run_tracking_migration(config=config, now=NOW)

    record = _tracking(config, "req-1")
    assert record.status == TRACKING_STATUS_SUBMIT_FAILED
    assert record.last_error is not None
    assert record.last_error["reason_code"] == "queue_failed"


def test_queue_submitting_backfills_verifying_external(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _save_request(config, _accepted_request("req-1"))
    _save_queue(config, "batch-1", [("req-1", BATCH_QUEUE_STATUS_SUBMITTING)])

    run_tracking_migration(config=config, now=NOW)

    assert _tracking(config, "req-1").status == "VERIFYING_EXTERNAL"


def test_ab_success_backfills_active(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _save_request(config, _accepted_request("req-1"))
    _save_ab(config, "req-1", success=True)

    run_tracking_migration(config=config, now=NOW)

    assert _tracking(config, "req-1").status == TRACKING_STATUS_ACTIVE


def test_queue_succeeded_without_ab_backfills_recovery(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _save_request(config, _accepted_request("req-1"))
    _save_queue(config, "batch-1", [("req-1", BATCH_QUEUE_STATUS_SUCCEEDED)])

    result = run_tracking_migration(config=config, now=NOW)

    record = _tracking(config, "req-1")
    assert record.status == TRACKING_STATUS_RECOVERY_REQUIRED
    assert result.manifest.counts.recovery_required == 1


def test_pending_request_without_evidence_is_not_migrated(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _save_request(config, _pending_request("req-pending"))

    result = run_tracking_migration(config=config, now=NOW)

    assert result.complete
    assert result.manifest.counts.created == 0
    assert list_tracking_records(config).records == []


def test_orphan_ab_success_backfills_recovery_without_request(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _save_ab(config, "req-orphan", success=True)

    result = run_tracking_migration(config=config, now=NOW)

    assert result.manifest.counts.created == 1
    assert result.manifest.counts.recovery_required == 1
    record = _tracking(config, "req-orphan")
    assert record.status == TRACKING_STATUS_RECOVERY_REQUIRED
    assert record.request_fingerprint is None


# -- idempotency & multi-queue convergence -----------------------------------


def test_repeat_run_adds_no_records_and_keeps_revision(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _save_request(config, _accepted_request("req-1"))
    _save_queue(config, "batch-1", [("req-1", BATCH_QUEUE_STATUS_READY_TO_SUBMIT)])

    first = run_tracking_migration(config=config, now=NOW)
    assert first.manifest.counts.created == 1
    record_before = _tracking(config, "req-1")
    tracking_id = record_before.tracking_id

    # Force another full scan by resetting the manifest (as a PARTIAL retry would).

    config.tracking_migrations_dir.mkdir(parents=True, exist_ok=True)
    _manifest_path(config).unlink()
    second = run_tracking_migration(config=config, now=NOW)

    assert second.manifest.counts.created == 0
    assert second.manifest.counts.existing == 1
    record_after = _tracking(config, "req-1")
    assert record_after.tracking_id == tracking_id
    assert record_after.revision == record_before.revision
    assert len(record_after.audit_events) == len(record_before.audit_events)


def test_consistent_multiple_queues_create_one_record_with_audit(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _save_request(config, _accepted_request("req-1"))
    _save_queue(config, "batch-b", [("req-1", BATCH_QUEUE_STATUS_READY_TO_SUBMIT)])
    _save_queue(config, "batch-a", [("req-1", BATCH_QUEUE_STATUS_READY_TO_SUBMIT)])

    result = run_tracking_migration(config=config, now=NOW)

    assert result.manifest.counts.created == 1
    records = list_tracking_records(config).records
    assert len(records) == 1
    record = records[0]
    # Lexicographically earliest batch wins for two created_at-equal sources.
    assert record.batch_id == "batch-a"
    assert len(record.audit_events) == 2
    assert any(
        event["reason_code"] == MIGRATION_REASON_MULTIPLE_QUEUE_SOURCES
        for event in record.audit_events
    )
    assert all(event["actor"] == TRACKING_AUDIT_ACTOR_MIGRATION for event in record.audit_events)


def test_conflicting_queues_backfill_recovery_and_one_record(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _save_request(config, _accepted_request("req-1"))
    _save_queue(config, "batch-a", [("req-1", BATCH_QUEUE_STATUS_READY_TO_SUBMIT)])
    _save_queue(config, "batch-b", [("req-1", BATCH_QUEUE_STATUS_FAILED)])

    result = run_tracking_migration(config=config, now=NOW)

    assert result.manifest.counts.recovery_required == 1
    records = list_tracking_records(config).records
    assert len(records) == 1
    assert records[0].status == TRACKING_STATUS_RECOVERY_REQUIRED


# -- damaged-file safety ------------------------------------------------------


def test_damaged_request_does_not_block_healthy_and_yields_partial(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _save_request(config, _accepted_request("req-healthy"))
    # A damaged request snapshot: JSON parse failure.
    config.requests_dir.mkdir(parents=True, exist_ok=True)
    (config.requests_dir / "req-broken.json").write_text("{bad json", encoding="utf-8")

    result = run_tracking_migration(config=config, now=NOW)

    assert result.manifest.state == MIGRATION_STATE_PARTIAL
    assert result.manifest.counts.unreadable == 1
    assert result.warning() == MIGRATION_PARTIAL_WARNING
    assert _tracking(config, "req-healthy").status == TRACKING_STATUS_PENDING_SUBMIT
    # The damaged request must not have produced a record from weaker evidence.
    assert len(list_tracking_records(config).records) == 1


def test_partial_retry_after_repair_completes_without_duplicates(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _save_request(config, _accepted_request("req-1"))
    config.requests_dir.mkdir(parents=True, exist_ok=True)
    (config.requests_dir / "req-broken.json").write_text("{bad", encoding="utf-8")

    first = run_tracking_migration(config=config, now=NOW)
    assert first.partial

    # Repair the damaged request, then retry: healthy stays existing (1), the
    # repaired request is now created (1), unreadable drops to 0 -> COMPLETE.
    (config.requests_dir / "req-broken.json").unlink()
    _save_request(config, _accepted_request("req-broken"))
    second = run_tracking_migration(config=config, now=NOW)

    assert second.complete
    assert second.manifest.counts.created == 1
    assert second.manifest.counts.existing == 1
    assert second.manifest.counts.unreadable == 0
    assert len(list_tracking_records(config).records) == 2


def test_damaged_queue_file_is_counted_without_blocking_healthy(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _save_request(config, _accepted_request("req-1"))
    _save_queue(config, "batch-good", [("req-1", BATCH_QUEUE_STATUS_READY_TO_SUBMIT)])
    config.queue_dir.mkdir(parents=True, exist_ok=True)
    (config.queue_dir / "batch-broken.json").write_text("{broken", encoding="utf-8")

    result = run_tracking_migration(config=config, now=NOW)

    assert result.partial
    assert result.manifest.counts.unreadable == 1
    # The healthy queue still migrates req-1 through the readable source.
    assert _tracking(config, "req-1").status == TRACKING_STATUS_PENDING_SUBMIT


def test_damaged_ab_file_makes_queue_success_recovery_and_partial(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _save_request(config, _accepted_request("req-1"))
    _save_queue(config, "batch-1", [("req-1", BATCH_QUEUE_STATUS_SUCCEEDED)])
    config.ab_results_dir.mkdir(parents=True, exist_ok=True)
    (config.ab_results_dir / "req-1.json").write_text("{broken", encoding="utf-8")

    result = run_tracking_migration(config=config, now=NOW)

    assert result.partial
    assert result.manifest.counts.unreadable == 1
    record = _tracking(config, "req-1")
    assert record.status == TRACKING_STATUS_RECOVERY_REQUIRED
    assert record.last_error is not None
    assert record.last_error["reason_code"] == "queue_success_without_ab_result"


def test_unreadable_files_are_never_exposed_in_manifest(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.requests_dir.mkdir(parents=True, exist_ok=True)
    (config.requests_dir / "req-broken.json").write_text("{bad", encoding="utf-8")
    config.queue_dir.mkdir(parents=True, exist_ok=True)
    (config.queue_dir / "batch-broken.json").write_text("{bad", encoding="utf-8")

    result = run_tracking_migration(config=config, now=NOW)

    assert result.partial
    assert result.manifest.counts.unreadable == 2
    written = _manifest_path(config).read_text(encoding="utf-8")
    assert "req-broken" not in written
    assert "batch-broken" not in written
