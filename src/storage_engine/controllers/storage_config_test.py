from __future__ import annotations

from pathlib import Path

import pytest

from apps.migu_orca_entry.controllers.entry_controller import generate_request
from shared.errors import Stage1Error
from shared.models import EntryRequest
from storage_engine.controllers.storage_config import (
    DEFAULT_STORAGE_DIR,
    ensure_storage_layout,
    load_storage_config,
)


def test_load_storage_config_uses_predictable_default_layout() -> None:
    config = load_storage_config()

    assert config.storage_dir == DEFAULT_STORAGE_DIR
    assert config.requests_dir == DEFAULT_STORAGE_DIR / "requests"
    assert config.history_dir == DEFAULT_STORAGE_DIR / "history"
    assert config.ab_results_dir == DEFAULT_STORAGE_DIR / "ab_results"
    assert config.queue_dir == DEFAULT_STORAGE_DIR / "queue"
    assert config.preferences_dir == DEFAULT_STORAGE_DIR / "preferences"
    assert config.corrections_dir == DEFAULT_STORAGE_DIR / "corrections"
    assert config.idempotency_dir == DEFAULT_STORAGE_DIR / "idempotency"


def test_load_storage_config_allows_caller_override(tmp_path: Path) -> None:
    storage_dir = tmp_path / "runtime-state"

    config = load_storage_config(storage_dir)

    assert config.storage_dir == storage_dir
    assert config.requests_dir == storage_dir / "requests"
    assert config.history_dir == storage_dir / "history"
    assert config.ab_results_dir == storage_dir / "ab_results"
    assert config.queue_dir == storage_dir / "queue"
    assert config.preferences_dir == storage_dir / "preferences"
    assert config.corrections_dir == storage_dir / "corrections"
    assert config.idempotency_dir == storage_dir / "idempotency"


def test_ensure_storage_layout_creates_json_storage_directories(tmp_path: Path) -> None:
    config = load_storage_config(tmp_path / "migu-state")

    ensured = ensure_storage_layout(config)

    assert ensured == config
    assert config.storage_dir.is_dir()
    assert config.requests_dir.is_dir()
    assert config.history_dir.is_dir()
    assert config.ab_results_dir.is_dir()
    assert config.queue_dir.is_dir()
    assert config.preferences_dir.is_dir()
    assert config.corrections_dir.is_dir()
    assert config.idempotency_dir.is_dir()


def test_ensure_storage_layout_returns_stable_error_for_file_path(
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "migu-state"
    storage_dir.write_text("not a directory", encoding="utf-8")

    with pytest.raises(Stage1Error) as error:
        ensure_storage_layout(load_storage_config(storage_dir))

    assert error.value.error_type == "storage_error"
    assert error.value.failed_step == "ensure_storage_layout"


def test_generate_request_default_path_does_not_create_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_dir = tmp_path / "unused-storage"
    monkeypatch.setattr(
        "storage_engine.controllers.storage_config.DEFAULT_STORAGE_DIR",
        storage_dir,
    )

    result = generate_request(EntryRequest(raw_title="芙莉莲"))

    assert result["success"] is True
    assert not storage_dir.exists()
