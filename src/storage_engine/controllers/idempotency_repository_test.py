from __future__ import annotations

"""US-213: durable save-confirm idempotency repository tests.

These exercise ``storage_engine.controllers.idempotency_repository`` against a
``tmp_path`` storage profile: atomic writes, damage/missing-record handling,
key path-traversal rejection, and the guarantee that a record never carries
sensitive content (the repository only ever persists the whitelisted fields).
"""

from pathlib import Path
from typing import Any

import pytest

from shared.errors import Stage1Error
from storage_engine.controllers.idempotency_repository import (
    IDEMPOTENCY_OPERATION_SAVE_CONFIRM,
    IDEMPOTENCY_STATE_CONFIRMED,
    IDEMPOTENCY_STATE_IN_PROGRESS,
    IDEMPOTENCY_STATE_SAVED_CONFIRM_FAILED,
    create_idempotency_record,
    load_idempotency_record,
    save_idempotency_record,
)
from storage_engine.controllers.storage_config import load_storage_config


def _config(tmp_path: Path):
    return load_storage_config(tmp_path / "migu-state")


def _record(key: str = "key-1", state: str = IDEMPOTENCY_STATE_IN_PROGRESS) -> dict[str, Any]:
    return create_idempotency_record(
        idempotency_key=key,
        operation=IDEMPOTENCY_OPERATION_SAVE_CONFIRM,
        request_fingerprint="a" * 64,
        request_id=None if state == IDEMPOTENCY_STATE_IN_PROGRESS else "request-1",
        state=state,
        now="2026-09-08T00:00:00+00:00",
    )


def test_save_then_load_round_trips_all_public_fields(tmp_path: Path) -> None:
    config = _config(tmp_path)
    record = _record("opaque-key", IDEMPOTENCY_STATE_SAVED_CONFIRM_FAILED)
    record["request_id"] = "request-abc"

    save_idempotency_record(config, record)
    loaded = load_idempotency_record(config, "opaque-key")

    assert loaded == record
    assert loaded is not record
    assert (config.idempotency_dir / "opaque-key.json").exists()


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path: Path) -> None:
    config = _config(tmp_path)
    record = _record("atomic-key")

    save_idempotency_record(config, record)

    files = [path.name for path in config.idempotency_dir.iterdir()]
    assert files == ["atomic-key.json"]
    assert not (config.idempotency_dir / "atomic-key.json.tmp").exists()


def test_load_missing_key_returns_none(tmp_path: Path) -> None:
    assert load_idempotency_record(_config(tmp_path), "never-bound") is None


def test_load_damaged_record_returns_stable_error_without_leaking_bytes(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    config.idempotency_dir.mkdir(parents=True)
    (config.idempotency_dir / "broken.json").write_text("{", encoding="utf-8")

    with pytest.raises(Stage1Error) as error:
        load_idempotency_record(config, "broken")

    assert error.value.as_dict()["error_type"] == "storage_json_error"
    assert error.value.failed_step == "load_idempotency_record"
    assert error.value.details["idempotency_key"] == "broken"
    assert str(tmp_path) not in str(error.value.as_dict())


def test_load_non_object_record_returns_stable_error(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.idempotency_dir.mkdir(parents=True)
    (config.idempotency_dir / "array.json").write_text("[]", encoding="utf-8")

    with pytest.raises(Stage1Error) as error:
        load_idempotency_record(config, "array")

    assert error.value.error_type == "storage_json_error"
    assert "必须是对象" in error.value.message


def test_save_write_failure_returns_stable_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(tmp_path)
    record = _record("fail-write")

    def fail_write_text(
        self: Path,
        data: str,
        *,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        raise OSError("permission denied: /sensitive/idempotency/path")

    monkeypatch.setattr(Path, "write_text", fail_write_text)

    with pytest.raises(Stage1Error) as error:
        save_idempotency_record(config, record)

    assert error.value.as_dict()["error_type"] == "storage_error"
    assert error.value.failed_step == "save_idempotency_record"
    assert error.value.details["directory"] == "idempotency"
    assert str(tmp_path) not in str(error.value.as_dict())


def test_rejects_path_traversal_key(tmp_path: Path) -> None:
    config = _config(tmp_path)

    with pytest.raises(Stage1Error) as error:
        save_idempotency_record(config, _record("../outside"))

    assert error.value.error_type == "invalid_idempotency_key"
    assert error.value.failed_step == "save_idempotency_record"
    assert not (config.idempotency_dir.parent / "outside.json").exists()


def test_rejects_nested_key(tmp_path: Path) -> None:
    config = _config(tmp_path)

    with pytest.raises(Stage1Error) as error:
        load_idempotency_record(config, "nested/key")

    assert error.value.error_type == "invalid_idempotency_key"
    assert error.value.failed_step == "load_idempotency_record"


def test_persisted_file_never_contains_draft_or_sensitive_values(tmp_path: Path) -> None:
    """US-213 security: only the whitelisted fields are ever written."""
    config = _config(tmp_path)
    record = create_idempotency_record(
        idempotency_key="safe-key",
        operation=IDEMPOTENCY_OPERATION_SAVE_CONFIRM,
        request_fingerprint="a" * 64,
        request_id="request-1",
        state=IDEMPOTENCY_STATE_CONFIRMED,
        now="2026-09-08T00:00:00+00:00",
    )
    # Even if a caller accidentally attached a wider dict, save must drop it.
    record["draft_id"] = "secret-draft"
    record["request"] = {"raw_title": "芙莉莲", "status": "PENDING_CONFIRM"}
    record["rss_url"] = "https://example.invalid/RSS?token=secret"

    save_idempotency_record(config, record)

    written = (config.idempotency_dir / "safe-key.json").read_text(encoding="utf-8")
    assert "draft_id" not in written
    assert "raw_title" not in written
    assert "芙莉莲" not in written
    assert "secret" not in written
    assert "example.invalid" not in written
    assert "https://" not in written
    assert "request_fingerprint" in written
    assert "state" in written
    assert "operation" in written
