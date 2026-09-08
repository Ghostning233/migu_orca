"""Historical-backfill migration manifest contract (US-221).

The manifest is the *only* file that lives under
``<storage>/tracking_migrations/`` and it is written after every migration
scan.  It deliberately stores no request ids, file names, paths or raw JSON —
only the run window, the ``COMPLETE``/``PARTIAL`` state and safe counts:

- ``created`` — tracking records newly created by the run;
- ``existing`` — candidate requests that already had a tracking record
  (so a repeated run never adds records or bumps revisions);
- ``recovery_required`` — requests whose local evidence forces a
  ``RECOVERY_REQUIRED`` outcome;
- ``unreadable`` — source files (Request snapshot / batch queue / saved Auto
  Bangumi result) that could not be parsed.

State rules (Stage 29 PRD §10.1):

- ``PARTIAL`` is written whenever at least one source file was unreadable;
  later API access keeps retrying the scan until a run reports no unreadable
  items, at which point ``COMPLETE`` is written.
- A ``COMPLETE`` manifest makes the coordinator skip further full scans; new
  data is tracked in real time by the accept/save-confirm handoff instead.

The module owns the *content* contract only; durable JSON persistence lives in
``storage_engine.controllers.migration_repository``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MIGRATION_MANIFEST_SCHEMA_VERSION = 1

#: A completed migration run with no unreadable items.
MIGRATION_STATE_COMPLETE = "COMPLETE"
#: A migration run that hit at least one unreadable source file.
MIGRATION_STATE_PARTIAL = "PARTIAL"
MIGRATION_STATES = frozenset({MIGRATION_STATE_COMPLETE, MIGRATION_STATE_PARTIAL})

_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "state",
        "started_at",
        "finished_at",
        "counts",
    }
)
_COUNT_FIELDS = frozenset(
    {
        "created",
        "existing",
        "recovery_required",
        "unreadable",
    }
)


@dataclass(frozen=True)
class MigrationCounts:
    """Safe counters recorded by one migration run (§10.1)."""

    created: int = 0
    existing: int = 0
    recovery_required: int = 0
    unreadable: int = 0

    def __post_init__(self) -> None:
        for name, value in (
            ("created", self.created),
            ("existing", self.existing),
            ("recovery_required", self.recovery_required),
            ("unreadable", self.unreadable),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"migration {name} count must be a non-negative integer")

    def as_dict(self) -> dict[str, int]:
        return {
            "created": self.created,
            "existing": self.existing,
            "recovery_required": self.recovery_required,
            "unreadable": self.unreadable,
        }


@dataclass(frozen=True)
class MigrationManifest:
    """Result of one historical-backfill run (§10.1)."""

    schema_version: int = MIGRATION_MANIFEST_SCHEMA_VERSION
    state: str = MIGRATION_STATE_PARTIAL
    started_at: str | None = None
    finished_at: str | None = None
    counts: MigrationCounts = field(default_factory=MigrationCounts)

    def __post_init__(self) -> None:
        if self.schema_version != MIGRATION_MANIFEST_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported migration manifest schema_version: {self.schema_version!r}"
            )
        if self.state not in MIGRATION_STATES:
            raise ValueError(f"invalid migration manifest state: {self.state!r}")


def migration_counts_from_storage_dict(data: Any) -> MigrationCounts:
    """Reconstruct ``MigrationCounts`` from a strict storage dict.

    Unknown fields, negative/non-int counts and non-object shapes raise
    ``ValueError`` so the repository maps them to a stable storage error.
    """
    if not isinstance(data, dict):
        raise ValueError("migration counts must be an object")
    unknown = sorted(set(data) - _COUNT_FIELDS)
    if unknown:
        raise ValueError(f"unknown migration counts fields: {', '.join(unknown)}")
    return MigrationCounts(
        created=_count(data, "created"),
        existing=_count(data, "existing"),
        recovery_required=_count(data, "recovery_required"),
        unreadable=_count(data, "unreadable"),
    )


def manifest_to_storage_dict(manifest: MigrationManifest) -> dict[str, Any]:
    """Serialize a manifest with exactly the fixed whitelist fields."""
    return {
        "schema_version": MIGRATION_MANIFEST_SCHEMA_VERSION,
        "state": manifest.state,
        "started_at": manifest.started_at,
        "finished_at": manifest.finished_at,
        "counts": manifest.counts.as_dict(),
    }


def manifest_from_storage_dict(data: Any) -> MigrationManifest:
    """Reconstruct a manifest from a strict storage dict (fail-closed)."""
    if not isinstance(data, dict):
        raise ValueError("migration manifest JSON must be an object")
    unknown = sorted(set(data) - _MANIFEST_FIELDS)
    if unknown:
        raise ValueError(f"unknown migration manifest fields: {', '.join(unknown)}")

    schema_version = data.get("schema_version")
    if schema_version != MIGRATION_MANIFEST_SCHEMA_VERSION:
        raise ValueError(f"unsupported migration manifest schema_version: {schema_version!r}")
    state = data.get("state")
    if state not in MIGRATION_STATES:
        raise ValueError(f"invalid migration manifest state: {state!r}")

    return MigrationManifest(
        schema_version=MIGRATION_MANIFEST_SCHEMA_VERSION,
        state=state,
        started_at=_optional_str(data.get("started_at"), "started_at"),
        finished_at=_optional_str(data.get("finished_at"), "finished_at"),
        counts=migration_counts_from_storage_dict(data.get("counts")),
    )


def _count(data: dict[str, Any], name: str) -> int:
    value = data.get(name, 0)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"migration {name} count must be a non-negative integer")
    return value


def _optional_str(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string or null")
    return value


__all__ = [
    "MIGRATION_MANIFEST_SCHEMA_VERSION",
    "MIGRATION_STATES",
    "MIGRATION_STATE_COMPLETE",
    "MIGRATION_STATE_PARTIAL",
    "MigrationCounts",
    "MigrationManifest",
    "manifest_from_storage_dict",
    "manifest_to_storage_dict",
    "migration_counts_from_storage_dict",
]
