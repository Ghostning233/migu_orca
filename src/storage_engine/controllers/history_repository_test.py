from __future__ import annotations

from pathlib import Path

import pytest

from shared.errors import Stage1Error
from storage_engine.controllers.history_repository import append_status_history
from storage_engine.controllers.storage_config import load_storage_config


def test_append_status_history_creates_request_history_file(tmp_path: Path) -> None:
    config = load_storage_config(tmp_path / "migu-state")
    event = {
        "request_id": "request-1",
        "previous_status": "PENDING_CONFIRM",
        "next_status": "ACCEPTED",
        "action": "ACCEPT",
        "timestamp": "2026-08-06T12:00:00+00:00",
    }

    saved = append_status_history(config, event)

    assert saved == {
        "request_id": "request-1",
        "storage": "local_json",
        "directory": "history",
        "filename": "request-1.json",
        "event_count": 1,
    }
    assert (config.history_dir / "request-1.json").read_text(encoding="utf-8")


def test_append_status_history_appends_to_existing_history(tmp_path: Path) -> None:
    config = load_storage_config(tmp_path / "migu-state")
    first = {
        "request_id": "request-1",
        "previous_status": "PENDING_CONFIRM",
        "next_status": "PENDING_CONFIRM",
        "action": "MODIFY",
        "timestamp": "2026-08-06T12:00:00+00:00",
        "details": {"patch": {"selected_subtitle_group": "Loli"}},
    }
    second = {
        "request_id": "request-1",
        "previous_status": "PENDING_CONFIRM",
        "next_status": "ACCEPTED",
        "action": "ACCEPT",
        "timestamp": "2026-08-06T12:01:00+00:00",
    }

    append_status_history(config, first)
    saved = append_status_history(config, second)

    assert saved["event_count"] == 2


def test_append_status_history_rejects_path_traversal_request_id(
    tmp_path: Path,
) -> None:
    config = load_storage_config(tmp_path / "migu-state")

    with pytest.raises(Stage1Error) as error:
        append_status_history(
            config,
            {
                "request_id": "../outside",
                "previous_status": "PENDING_CONFIRM",
                "next_status": "ACCEPTED",
                "action": "ACCEPT",
                "timestamp": "2026-08-06T12:00:00+00:00",
            },
        )

    assert error.value.error_type == "invalid_request_id"
    assert not (tmp_path / "outside.json").exists()


def test_append_status_history_returns_stable_error_for_invalid_json(
    tmp_path: Path,
) -> None:
    config = load_storage_config(tmp_path / "migu-state")
    config.history_dir.mkdir(parents=True)
    (config.history_dir / "broken.json").write_text("{", encoding="utf-8")

    with pytest.raises(Stage1Error) as error:
        append_status_history(
            config,
            {
                "request_id": "broken",
                "previous_status": "PENDING_CONFIRM",
                "next_status": "ACCEPTED",
                "action": "ACCEPT",
                "timestamp": "2026-08-06T12:00:00+00:00",
            },
        )

    error_dict = error.value.as_dict()
    assert error_dict["error_type"] == "storage_json_error"
    assert error_dict["failed_step"] == "append_status_history"
    assert error_dict["details"]["request_id"] == "broken"
    assert str(tmp_path) not in str(error_dict)
