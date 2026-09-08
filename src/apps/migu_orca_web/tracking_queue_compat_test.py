from __future__ import annotations

"""US-226: legacy batch-queue <-> unified-tracking projection tests."""

from pathlib import Path

from apps.migu_orca_entry.controllers.entry_controller import generate_request
from apps.migu_orca_web.tracking_handoff import ensure_confirmed_request_tracking
from apps.migu_orca_web.tracking_queue_compat import (
    reflect_ab_result_into_tracking,
    reflect_queue_outcome_into_tracking,
    sync_queue_projection_for_tracking,
)
from batch_engine.controllers.batch_queue_controller import (
    create_submission_queue,
    enqueue_item,
)
from batch_engine.models import (
    BATCH_QUEUE_STATUS_FAILED,
    BATCH_QUEUE_STATUS_SUBMITTING,
    BATCH_QUEUE_STATUS_SUCCEEDED,
)
from request_engine.controllers.request_controller import accept_request
from shared.models import EntryRequest
from storage_engine.controllers.queue_repository import (
    load_submission_queue,
    save_submission_queue,
)
from storage_engine.controllers.request_repository import (
    load_request_snapshot,
    save_request_snapshot,
)
from storage_engine.controllers.storage_config import (
    StorageConfig,
    load_storage_config,
)
from storage_engine.controllers.tracking_repository import load_tracking_record
from tracking_engine.models.tracking import (
    TRACKING_ORIGIN_SAVE_CONFIRM,
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_PENDING_SUBMIT,
    TRACKING_STATUS_SUBMIT_FAILED,
    TRACKING_STATUS_SUBMITTING,
)

NOW = "2026-09-08T00:00:00+00:00"


def _config(tmp_path: Path) -> StorageConfig:
    return load_storage_config(tmp_path / "storage")


def _accepted_request(tmp_path: Path, request_id: str = "request-1"):
    config = _config(tmp_path)
    request = accept_request(
        {
            **generate_request(EntryRequest(raw_title="芙莉莲"))["request"],
            "request_id": request_id,
        }
    )
    save_request_snapshot(config, request)
    return request


def _seed_tracking(tmp_path: Path, request_id: str = "request-1"):
    config = _config(tmp_path)
    request = load_request_snapshot(config, request_id)
    handoff = ensure_confirmed_request_tracking(
        config=config,
        request=request,
        origin=TRACKING_ORIGIN_SAVE_CONFIRM,
        now=NOW,
    )
    assert handoff.tracking_id is not None
    return load_tracking_record(config, handoff.tracking_id)


def _seed_queue(tmp_path: Path, request_id: str = "request-1"):
    config = _config(tmp_path)
    queue = create_submission_queue("batch-1", now_factory=lambda: NOW)
    queue = enqueue_item(
        queue,
        item_id="item-1",
        request_id=request_id,
        title="芙莉莲",
        now_factory=lambda: NOW,
    )
    save_submission_queue(config, queue)
    return queue


# ---------------------------------------------------------------------------
# Queue -> tracking projection
# ---------------------------------------------------------------------------


def test_reflect_queue_succeeded_advances_pending_record_to_active(
    tmp_path: Path,
) -> None:
    _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path)
    assert record.status == TRACKING_STATUS_PENDING_SUBMIT
    _seed_queue(tmp_path)

    reflect_queue_outcome_into_tracking(
        _config(tmp_path),
        request_id="request-1",
        queue_status=BATCH_QUEUE_STATUS_SUCCEEDED,
        now=NOW,
    )

    after = load_tracking_record(_config(tmp_path), record.tracking_id)
    assert after.status == TRACKING_STATUS_ACTIVE


def test_reflect_queue_failed_advances_pending_record_to_submit_failed(
    tmp_path: Path,
) -> None:
    _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path)
    _seed_queue(tmp_path)

    reflect_queue_outcome_into_tracking(
        _config(tmp_path),
        request_id="request-1",
        queue_status=BATCH_QUEUE_STATUS_FAILED,
        now=NOW,
    )

    after = load_tracking_record(_config(tmp_path), record.tracking_id)
    assert after.status == TRACKING_STATUS_SUBMIT_FAILED


def test_reflect_never_downgrades_active_record(tmp_path: Path) -> None:
    _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path)
    _seed_queue(tmp_path)
    # First a success moves the record to ACTIVE.
    reflect_queue_outcome_into_tracking(
        _config(tmp_path),
        request_id="request-1",
        queue_status=BATCH_QUEUE_STATUS_SUCCEEDED,
        now=NOW,
    )
    # A stale FAILED queue item must never downgrade the durable success.
    reflect_queue_outcome_into_tracking(
        _config(tmp_path),
        request_id="request-1",
        queue_status=BATCH_QUEUE_STATUS_FAILED,
        now=NOW,
    )
    after = load_tracking_record(_config(tmp_path), record.tracking_id)
    assert after.status == TRACKING_STATUS_ACTIVE


# ---------------------------------------------------------------------------
# Tracking -> queue projection
# ---------------------------------------------------------------------------


def test_sync_submitting_projects_ready_item_to_submitting(tmp_path: Path) -> None:
    _accepted_request(tmp_path)
    _seed_tracking(tmp_path)
    _seed_queue(tmp_path)
    config = _config(tmp_path)

    sync_queue_projection_for_tracking(
        config,
        request_id="request-1",
        tracking_status=TRACKING_STATUS_SUBMITTING,
        now=NOW,
    )

    queue = load_submission_queue(config, "batch-1")
    assert queue.items[0].status == BATCH_QUEUE_STATUS_SUBMITTING


def test_sync_active_projects_submitting_item_to_succeeded(tmp_path: Path) -> None:
    _accepted_request(tmp_path)
    _seed_tracking(tmp_path)
    _seed_queue(tmp_path)
    config = _config(tmp_path)

    sync_queue_projection_for_tracking(
        config,
        request_id="request-1",
        tracking_status=TRACKING_STATUS_ACTIVE,
        now=NOW,
    )

    queue = load_submission_queue(config, "batch-1")
    assert queue.items[0].status == BATCH_QUEUE_STATUS_SUCCEEDED


def test_sync_active_never_overwrites_already_succeeded_item(tmp_path: Path) -> None:
    _accepted_request(tmp_path)
    _seed_tracking(tmp_path)
    _seed_queue(tmp_path)
    config = _config(tmp_path)
    # First project the item to a durable SUCCEEDED.
    sync_queue_projection_for_tracking(
        config,
        request_id="request-1",
        tracking_status=TRACKING_STATUS_ACTIVE,
        now=NOW,
    )
    assert load_submission_queue(config, "batch-1").items[0].status == BATCH_QUEUE_STATUS_SUCCEEDED

    # A later "failed" projection must not overwrite the durable success.
    sync_queue_projection_for_tracking(
        config,
        request_id="request-1",
        tracking_status=TRACKING_STATUS_SUBMIT_FAILED,
        now=NOW,
    )

    loaded = load_submission_queue(config, "batch-1")
    assert loaded.items[0].status == BATCH_QUEUE_STATUS_SUCCEEDED


def test_reflect_ab_result_success_maps_active(tmp_path: Path) -> None:
    _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path)
    config = _config(tmp_path)

    reflect_ab_result_into_tracking(
        config,
        request_id="request-1",
        ab_result={"success": True, "ab_subscription_id": "ab-1", "error": None},
        now=NOW,
    )

    after = load_tracking_record(config, record.tracking_id)
    assert after.status == TRACKING_STATUS_ACTIVE


def test_reflect_ab_result_timeout_maps_verifying_external(tmp_path: Path) -> None:
    _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path)
    config = _config(tmp_path)

    reflect_ab_result_into_tracking(
        config,
        request_id="request-1",
        ab_result={
            "success": False,
            "error": {"error_type": "ab_timeout", "details": {"category": "timeout"}},
        },
        now=NOW,
    )

    from tracking_engine.models.tracking import TRACKING_STATUS_VERIFYING_EXTERNAL

    after = load_tracking_record(config, record.tracking_id)
    assert after.status == TRACKING_STATUS_VERIFYING_EXTERNAL


def test_sync_skips_missing_queue_without_error(tmp_path: Path) -> None:
    _accepted_request(tmp_path)
    _seed_tracking(tmp_path)
    config = _config(tmp_path)

    sync_queue_projection_for_tracking(
        config,
        request_id="request-1",
        tracking_status=TRACKING_STATUS_ACTIVE,
        now=NOW,
    )  # no queue exists -> no-op, never raises
