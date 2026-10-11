"""Durable migration-manifest repository (US-221).

Persists exactly one file under ``<storage>/tracking_migrations``::

    <storage>/tracking_migrations/schema-v1.json

The manifest stores only version/state/timestamps/safe counts (Stage 29 PRD
§10.1) and never request ids, file names, paths or raw JSON.  Reads are
fail-closed (an unknown schema version or field maps to a stable
``storage_json_error``); writes use ``storage_primitives.write_text_atomic``
(temp file + ``os.replace``) so a crash can
never leave a half-written manifest.
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock

from shared.errors import Stage1Error
from storage_engine.controllers.storage_config import (
    StorageConfig,
    ensure_storage_layout,
)
from storage_engine.controllers.storage_primitives import (
    is_relative_to,
    write_text_atomic,
)
from tracking_engine.models.migration import (
    MigrationManifest,
    manifest_from_storage_dict,
    manifest_to_storage_dict,
)

#: The fixed manifest file name.  The version namespace is part of the storage
#: contract: a future schema bump introduces a new ``schema-vN.json`` rather
#: than silently reinterpreting this file.
MIGRATION_MANIFEST_FILENAME = "schema-v1.json"

#: Process-level lock serializing manifest writes.  The manifest is a single
#: fixed file with a fixed ``.tmp`` temp path, so concurrent in-process writers
#: (e.g. two tracking API requests racing the migration coordinator) must not
#: replace/unlink each other's temp file (the same pattern as the per-key locks
#: in the tracking/operation repositories).
_MANIFEST_LOCK: RLock = RLock()


def load_migration_manifest(config: StorageConfig) -> MigrationManifest | None:
    """Load the migration manifest, returning ``None`` when no run happened yet.

    A damaged/present-but-invalid manifest raises a stable ``storage_json_error``
    (never a raw JSON/path leak) so a poisoned manifest cannot be silently
    treated as "no migration happened".
    """
    manifest_path = _manifest_path(config, "load_migration_manifest")
    if not manifest_path.exists():
        return None

    try:
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise Stage1Error(
            "storage_json_error",
            "读取迁移清单 JSON 失败",
            "load_migration_manifest",
            {"directory": config.tracking_migrations_dir.name, "reason": exc.msg},
        ) from exc
    except OSError as exc:
        raise Stage1Error(
            "storage_error",
            "读取迁移清单失败",
            "load_migration_manifest",
            {"directory": config.tracking_migrations_dir.name},
        ) from exc

    try:
        return manifest_from_storage_dict(loaded)
    except ValueError as exc:
        raise Stage1Error(
            "storage_json_error",
            "迁移清单 JSON 格式无效",
            "load_migration_manifest",
            {"directory": config.tracking_migrations_dir.name, "reason": str(exc)},
        ) from exc


def save_migration_manifest(
    config: StorageConfig,
    manifest: MigrationManifest,
) -> MigrationManifest:
    """Atomically persist ``manifest`` and return the normalized copy."""
    ensure_storage_layout(config)
    with _MANIFEST_LOCK:
        manifest_path = _manifest_path(config, "save_migration_manifest")
        payload = (
            json.dumps(
                manifest_to_storage_dict(manifest),
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        try:
            write_text_atomic(manifest_path, payload)
        except OSError as exc:
            raise Stage1Error(
                "storage_error",
                "写入迁移清单失败",
                "save_migration_manifest",
                {"directory": config.tracking_migrations_dir.name},
            ) from exc
    try:
        return manifest_from_storage_dict(manifest_to_storage_dict(manifest))
    except ValueError as exc:  # pragma: no cover - model guards construction
        raise Stage1Error(
            "storage_json_error",
            "迁移清单结构无效",
            "save_migration_manifest",
            {"reason": str(exc)},
        ) from exc


def _manifest_path(config: StorageConfig, failed_step: str) -> Path:
    root = config.tracking_migrations_dir.resolve(strict=False)
    candidate = (config.tracking_migrations_dir / MIGRATION_MANIFEST_FILENAME).resolve(
        strict=False
    )
    if not is_relative_to(candidate, root):
        raise Stage1Error(
            "storage_error",
            "迁移清单路径不合法",
            failed_step,
            {"directory": config.tracking_migrations_dir.name},
        )
    return candidate


__all__ = [
    "MIGRATION_MANIFEST_FILENAME",
    "load_migration_manifest",
    "save_migration_manifest",
]
