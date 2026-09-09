"""Local-only release rollback policy and storage backup helpers.

Rollback changes the application version, never the business evidence.  This
module deliberately has no imports from external clients: taking a backup and
classifying a fault window must not contact Auto Bangumi, MiKan, or qBittorrent.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class RollbackFaultWindow(StrEnum):
    """Fault boundaries that need explicit release rehearsal."""

    BEFORE_EXTERNAL_CALL = "before_external_call"
    EXTERNAL_MAY_HAVE_EXECUTED = "external_may_have_executed"
    TERMINAL_OPERATION_RECORD_STALE = "terminal_operation_record_stale"
    QUEUE_PROJECTION_FAILED = "queue_projection_failed"
    MIGRATION_INTERRUPTED = "migration_interrupted"


class RollbackDisposition(StrEnum):
    """Safe local disposition after an application rollback."""

    NO_EXTERNAL_CALL = "no_external_call"
    MANUAL_RECOVERY = "manual_recovery"
    RESUME_LOCAL_MIGRATION = "resume_local_migration"


@dataclass(frozen=True)
class RollbackDecision:
    """A safe, non-sensitive decision for one fault window."""

    disposition: RollbackDisposition
    operation_state: str
    recovery_action: str | None
    automatic_external_replay: bool = False


@dataclass(frozen=True)
class StorageBackup:
    """Safe summary of a copied storage tree; paths are intentionally omitted."""

    file_count: int
    byte_count: int


def decide_rollback(fault_window: RollbackFaultWindow) -> RollbackDecision:
    """Return the conservative post-rollback action for a known fault window."""

    decisions = {
        RollbackFaultWindow.BEFORE_EXTERNAL_CALL: RollbackDecision(
            RollbackDisposition.NO_EXTERNAL_CALL,
            "FAILED",
            None,
        ),
        RollbackFaultWindow.EXTERNAL_MAY_HAVE_EXECUTED: RollbackDecision(
            RollbackDisposition.MANUAL_RECOVERY,
            "OUTCOME_UNKNOWN",
            "VERIFY_EXTERNAL",
        ),
        RollbackFaultWindow.TERMINAL_OPERATION_RECORD_STALE: RollbackDecision(
            RollbackDisposition.MANUAL_RECOVERY,
            "RECOVERY_REQUIRED",
            "RECOVER",
        ),
        RollbackFaultWindow.QUEUE_PROJECTION_FAILED: RollbackDecision(
            RollbackDisposition.MANUAL_RECOVERY,
            "RECOVERY_REQUIRED",
            "RECOVER",
        ),
        RollbackFaultWindow.MIGRATION_INTERRUPTED: RollbackDecision(
            RollbackDisposition.RESUME_LOCAL_MIGRATION,
            "RECOVERY_REQUIRED",
            "RESUME_MIGRATION",
        ),
    }
    return decisions[fault_window]


def backup_storage(storage_dir: Path, backup_dir: Path) -> StorageBackup:
    """Copy a storage tree without changing or deleting its source.

    The destination must not exist and must not be inside the source.  This
    prevents an accidental recursive copy and makes the operation suitable for
    a release runbook.  Only aggregate counts are returned to callers.
    """

    source = storage_dir.resolve(strict=False)
    destination = backup_dir.resolve(strict=False)
    if not source.is_dir():
        raise ValueError("storage source must be an existing directory")
    if destination == source or source in destination.parents:
        raise ValueError("storage backup destination must be outside the source")
    if destination.exists():
        raise ValueError("storage backup destination must not already exist")

    shutil.copytree(source, destination, symlinks=True)
    files = tuple(path for path in destination.rglob("*") if path.is_file())
    return StorageBackup(
        file_count=len(files),
        byte_count=sum(path.stat().st_size for path in files),
    )


__all__ = [
    "RollbackDecision",
    "RollbackDisposition",
    "RollbackFaultWindow",
    "StorageBackup",
    "backup_storage",
    "decide_rollback",
]
