from __future__ import annotations

"""US-221: migration manifest model tests."""

import pytest

from tracking_engine.models.migration import (
    MIGRATION_MANIFEST_SCHEMA_VERSION,
    MIGRATION_STATE_COMPLETE,
    MIGRATION_STATE_PARTIAL,
    MigrationCounts,
    MigrationManifest,
    manifest_from_storage_dict,
    manifest_to_storage_dict,
    migration_counts_from_storage_dict,
)

NOW = "2026-09-08T00:00:00+00:00"


def _manifest() -> MigrationManifest:
    return MigrationManifest(
        state=MIGRATION_STATE_COMPLETE,
        started_at=NOW,
        finished_at=NOW,
        counts=MigrationCounts(created=3, existing=2, recovery_required=1, unreadable=0),
    )


def test_manifest_round_trips_through_storage_dict() -> None:
    manifest = _manifest()

    assert manifest_from_storage_dict(manifest_to_storage_dict(manifest)) == manifest


def test_counts_reject_negative_and_non_int() -> None:
    with pytest.raises(ValueError):
        MigrationCounts(created=-1)
    with pytest.raises(ValueError):
        MigrationCounts(existing="2")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        migration_counts_from_storage_dict({"recovery_required": -2})
    with pytest.raises(ValueError):
        migration_counts_from_storage_dict({"unreadable": True})


def test_counts_from_storage_dict_rejects_unknown_and_non_object() -> None:
    with pytest.raises(ValueError, match="unknown migration counts fields"):
        migration_counts_from_storage_dict({"created": 1, "url": "https://x.invalid"})
    with pytest.raises(ValueError, match="must be an object"):
        migration_counts_from_storage_dict([])


def test_manifest_rejects_invalid_state_and_schema() -> None:
    with pytest.raises(ValueError):
        MigrationManifest(state="DONE")
    storage = manifest_to_storage_dict(_manifest())
    storage["schema_version"] = 99
    with pytest.raises(ValueError, match="schema_version"):
        manifest_from_storage_dict(storage)
    storage = manifest_to_storage_dict(_manifest())
    storage["state"] = "BOGUS"
    with pytest.raises(ValueError, match="state"):
        manifest_from_storage_dict(storage)


def test_manifest_from_storage_dict_is_fail_closed() -> None:
    storage = manifest_to_storage_dict(_manifest())
    storage["counts"]["raw"] = {"token": "secret"}
    with pytest.raises(ValueError, match="unknown migration counts fields"):
        manifest_from_storage_dict(storage)
    storage = manifest_to_storage_dict(_manifest())
    storage["ab_config"] = {"token": "secret"}
    with pytest.raises(ValueError, match="unknown migration manifest fields"):
        manifest_from_storage_dict(storage)
    with pytest.raises(ValueError, match="must be an object"):
        manifest_from_storage_dict([])


def test_manifest_partial_state_is_supported() -> None:
    manifest = MigrationManifest(
        state=MIGRATION_STATE_PARTIAL,
        started_at=NOW,
        finished_at=NOW,
        counts=MigrationCounts(created=1, existing=0, recovery_required=0, unreadable=1),
    )
    assert manifest_from_storage_dict(manifest_to_storage_dict(manifest)) == manifest
    assert manifest.schema_version == MIGRATION_MANIFEST_SCHEMA_VERSION
