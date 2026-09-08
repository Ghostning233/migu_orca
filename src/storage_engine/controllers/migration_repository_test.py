from __future__ import annotations

"""US-221: migration manifest repository tests."""

import json
from pathlib import Path

import pytest

from shared.errors import Stage1Error
from storage_engine.controllers.migration_repository import (
    MIGRATION_MANIFEST_FILENAME,
    load_migration_manifest,
    save_migration_manifest,
)
from storage_engine.controllers.storage_config import load_storage_config
from tracking_engine.models.migration import (
    MIGRATION_STATE_COMPLETE,
    MIGRATION_STATE_PARTIAL,
    MigrationCounts,
    MigrationManifest,
)

NOW = "2026-09-08T00:00:00+00:00"


def _manifest(*, partial: bool = False) -> MigrationManifest:
    return MigrationManifest(
        state=MIGRATION_STATE_PARTIAL if partial else MIGRATION_STATE_COMPLETE,
        started_at=NOW,
        finished_at=NOW,
        counts=MigrationCounts(
            created=2 if not partial else 1,
            existing=1,
            recovery_required=1,
            unreadable=0 if not partial else 1,
        ),
    )


def _config(tmp_path: Path):
    return load_storage_config(tmp_path / "migu-state")


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    config = _config(tmp_path)
    manifest = _manifest()

    save_migration_manifest(config, manifest)

    assert load_migration_manifest(config) == manifest
    assert (config.tracking_migrations_dir / MIGRATION_MANIFEST_FILENAME).exists()


def test_load_missing_returns_none(tmp_path: Path) -> None:
    assert load_migration_manifest(_config(tmp_path)) is None


def test_save_is_atomic_and_leaves_no_temp(tmp_path: Path) -> None:
    config = _config(tmp_path)
    save_migration_manifest(config, _manifest())

    files = [path.name for path in config.tracking_migrations_dir.iterdir()]
    assert files == [MIGRATION_MANIFEST_FILENAME]
    assert not (config.tracking_migrations_dir / f"{MIGRATION_MANIFEST_FILENAME}.tmp").exists()


def test_load_damaged_manifest_raises_stable_error_without_leaking_bytes(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    config.tracking_migrations_dir.mkdir(parents=True)
    (config.tracking_migrations_dir / MIGRATION_MANIFEST_FILENAME).write_text(
        '{"schema_version": "secret', encoding="utf-8"
    )

    with pytest.raises(Stage1Error) as error:
        load_migration_manifest(config)
    assert error.value.error_type == "storage_json_error"
    assert error.value.failed_step == "load_migration_manifest"
    assert "secret" not in str(error.value.as_dict())


def test_load_poisoned_manifest_fails_closed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.tracking_migrations_dir.mkdir(parents=True)
    poisoned = {
        "schema_version": 1,
        "state": MIGRATION_STATE_COMPLETE,
        "started_at": NOW,
        "finished_at": NOW,
        "counts": {"created": 1, "existing": 0, "recovery_required": 0, "unreadable": 0},
        "token": "secret",
    }
    (config.tracking_migrations_dir / MIGRATION_MANIFEST_FILENAME).write_text(
        json.dumps(poisoned), encoding="utf-8"
    )

    with pytest.raises(Stage1Error) as error:
        load_migration_manifest(config)
    assert error.value.error_type == "storage_json_error"
    assert "unknown migration manifest fields" in error.value.details["reason"]


def test_persisted_manifest_never_contains_sensitive_fields(tmp_path: Path) -> None:
    config = _config(tmp_path)
    save_migration_manifest(config, _manifest())

    written = (config.tracking_migrations_dir / MIGRATION_MANIFEST_FILENAME).read_text(
        encoding="utf-8"
    )
    assert "secret" not in written
    assert "request_id" not in written
    assert written.strip().startswith("{")
