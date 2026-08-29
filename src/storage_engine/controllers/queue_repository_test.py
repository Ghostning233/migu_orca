from __future__ import annotations

from pathlib import Path

import pytest

from batch_engine.controllers.batch_queue_controller import (
    create_submission_queue,
    enqueue_item,
)
from batch_engine.models import (
    BATCH_QUEUE_STATUS_READY_TO_SUBMIT,
    BATCH_QUEUE_STATUS_SUCCEEDED,
    BatchSubmissionQueue,
)
from shared.errors import Stage1Error
from storage_engine.controllers.queue_repository import (
    load_submission_queue,
    save_submission_queue,
)
from storage_engine.controllers.storage_config import load_storage_config


def _queue(batch_id: str = "batch-1") -> BatchSubmissionQueue:
    queue = create_submission_queue(
        batch_id,
        queue_id_factory=lambda: "queue-1",
        now_factory=lambda: "2026-08-19T00:00:00+00:00",
    )
    queue = enqueue_item(
        queue,
        item_id="item-1",
        request_id="req-1",
        title="葬送的芙莉莲",
        now_factory=lambda: "2026-08-19T00:00:00+00:00",
    )
    return queue


def test_save_and_load_submission_queue_round_trip(tmp_path: Path) -> None:
    config = load_storage_config(tmp_path / "migu-state")
    queue = _queue()

    saved = save_submission_queue(config, queue)
    loaded = load_submission_queue(config, "batch-1")

    assert saved == {
        "batch_id": "batch-1",
        "storage": "local_json",
        "directory": "queue",
        "filename": "batch-1.json",
    }
    assert loaded == queue
    assert loaded is not queue
    assert loaded.queue_id == "queue-1"
    assert loaded.batch_id == "batch-1"
    assert len(loaded.items) == 1
    assert loaded.items[0].item_id == "item-1"
    assert loaded.items[0].request_id == "req-1"
    assert loaded.items[0].title == "葬送的芙莉莲"
    assert loaded.items[0].status == BATCH_QUEUE_STATUS_READY_TO_SUBMIT
    assert loaded.items[0].attempts == 0
    assert loaded.items[0].last_error is None
    assert loaded.items[0].ab_result_summary is None


def test_load_submission_queue_missing_returns_stable_error(tmp_path: Path) -> None:
    config = load_storage_config(tmp_path / "migu-state")

    with pytest.raises(Stage1Error) as error:
        load_submission_queue(config, "batch-missing")

    assert error.value.error_type == "queue_not_found"
    assert error.value.message == "未找到该批次的提交队列"
    assert error.value.failed_step == "load_submission_queue"


def test_load_submission_queue_rejects_path_traversal_batch_id(
    tmp_path: Path,
) -> None:
    config = load_storage_config(tmp_path / "migu-state")

    with pytest.raises(Stage1Error) as error:
        load_submission_queue(config, "../outside")

    assert error.value.error_type == "invalid_batch_id"
    assert "路径片段" in error.value.message


def test_save_submission_queue_rejects_empty_batch_id(tmp_path: Path) -> None:
    config = load_storage_config(tmp_path / "migu-state")
    empty = BatchSubmissionQueue(queue_id="queue-1", batch_id="  ", items=[])

    with pytest.raises(Stage1Error) as error:
        save_submission_queue(config, empty)

    assert error.value.error_type == "invalid_batch_id"
    assert error.value.failed_step == "save_submission_queue"


def test_load_submission_queue_preserves_status_and_sanitized_summaries(
    tmp_path: Path,
) -> None:
    from batch_engine.controllers.batch_queue_controller import (
        complete_queue_item_submit,
        start_queue_item_submit,
    )

    config = load_storage_config(tmp_path / "migu-state")
    queue = _queue()
    queue = start_queue_item_submit(
        queue,
        "req-1",
        now_factory=lambda: "2026-08-19T00:01:00+00:00",
    )
    queue = complete_queue_item_submit(
        queue,
        "req-1",
        BATCH_QUEUE_STATUS_SUCCEEDED,
        ab_result_summary={"success": True, "ab_subscription_id": "ab-1"},
        now_factory=lambda: "2026-08-19T00:02:00+00:00",
    )
    save_submission_queue(config, queue)

    loaded = load_submission_queue(config, "batch-1")

    assert loaded.items[0].status == BATCH_QUEUE_STATUS_SUCCEEDED
    assert loaded.items[0].attempts == 1
    assert loaded.items[0].last_error is None
    assert loaded.items[0].ab_result_summary == "ab_subscription_id=ab-1; success=True"


def test_load_submission_queue_invalid_json_returns_storage_error(
    tmp_path: Path,
) -> None:
    config = load_storage_config(tmp_path / "migu-state")
    queue_path = config.queue_dir / "batch-1.json"
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text("not json", encoding="utf-8")

    with pytest.raises(Stage1Error) as error:
        load_submission_queue(config, "batch-1")

    assert error.value.error_type == "storage_json_error"
    assert error.value.failed_step == "load_submission_queue"


def test_load_submission_queue_invalid_shape_returns_storage_error(
    tmp_path: Path,
) -> None:
    config = load_storage_config(tmp_path / "migu-state")
    queue_path = config.queue_dir / "batch-1.json"
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text('{"items": "not-a-list"}', encoding="utf-8")

    with pytest.raises(Stage1Error) as error:
        load_submission_queue(config, "batch-1")

    assert error.value.error_type == "storage_json_error"
    assert "格式无效" in error.value.message


def test_persisted_queue_serializes_without_sensitive_fields(tmp_path: Path) -> None:
    from batch_engine.controllers.batch_queue_controller import (
        complete_queue_item_submit,
        start_queue_item_submit,
    )

    config = load_storage_config(tmp_path / "migu-state")
    queue = create_submission_queue(
        "batch-1",
        queue_id_factory=lambda: "queue-1",
        now_factory=lambda: "2026-08-19T00:00:00+00:00",
    )
    queue = enqueue_item(
        queue,
        item_id="item-1",
        request_id="req-1",
        title="葬送的芙莉莲",
        now_factory=lambda: "2026-08-19T00:00:00+00:00",
    )
    queue = start_queue_item_submit(
        queue,
        "req-1",
        now_factory=lambda: "2026-08-19T00:01:00+00:00",
    )
    queue = complete_queue_item_submit(
        queue,
        "req-1",
        BATCH_QUEUE_STATUS_SUCCEEDED,
        ab_result_summary={
            "success": True,
            "ab_subscription_id": "ab-1",
            "endpoint": "https://ab.example.com/api",
            "token": "secret-token",
        },
        now_factory=lambda: "2026-08-19T00:02:00+00:00",
    )
    save_submission_queue(config, queue)

    body = (config.queue_dir / "batch-1.json").read_text(encoding="utf-8")
    loaded = load_submission_queue(config, "batch-1")

    assert "ab.example.com" not in body
    assert "secret-token" not in body
    assert "endpoint" not in body
    assert "token" not in body
    assert loaded.items[0].ab_result_summary == "ab_subscription_id=ab-1; success=True"
    assert "ab.example.com" not in loaded.items[0].ab_result_summary
    assert "secret-token" not in loaded.items[0].ab_result_summary
