from __future__ import annotations

from pathlib import Path

import pytest

from storage_engine.controllers.rollback import (
    RollbackDisposition,
    RollbackFaultWindow,
    backup_storage,
    decide_rollback,
)


@pytest.mark.parametrize(
    ("fault_window", "disposition", "state", "action"),
    [
        (
            RollbackFaultWindow.BEFORE_EXTERNAL_CALL,
            RollbackDisposition.NO_EXTERNAL_CALL,
            "FAILED",
            None,
        ),
        (
            RollbackFaultWindow.EXTERNAL_MAY_HAVE_EXECUTED,
            RollbackDisposition.MANUAL_RECOVERY,
            "OUTCOME_UNKNOWN",
            "VERIFY_EXTERNAL",
        ),
        (
            RollbackFaultWindow.TERMINAL_OPERATION_RECORD_STALE,
            RollbackDisposition.MANUAL_RECOVERY,
            "RECOVERY_REQUIRED",
            "RECOVER",
        ),
        (
            RollbackFaultWindow.QUEUE_PROJECTION_FAILED,
            RollbackDisposition.MANUAL_RECOVERY,
            "RECOVERY_REQUIRED",
            "RECOVER",
        ),
        (
            RollbackFaultWindow.MIGRATION_INTERRUPTED,
            RollbackDisposition.RESUME_LOCAL_MIGRATION,
            "RECOVERY_REQUIRED",
            "RESUME_MIGRATION",
        ),
    ],
)
def test_rollback_fault_windows_never_replay_external_writes(
    fault_window: RollbackFaultWindow,
    disposition: RollbackDisposition,
    state: str,
    action: str | None,
) -> None:
    decision = decide_rollback(fault_window)

    assert decision.disposition == disposition
    assert decision.operation_state == state
    assert decision.recovery_action == action
    assert decision.automatic_external_replay is False


def test_storage_backup_preserves_every_artifact_and_source(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    (storage / "tracking").mkdir(parents=True)
    (storage / "tracking" / "record.json").write_bytes(b"tracking evidence\n")
    (storage / "queue.json").write_bytes(b"queue evidence\n")
    before = {
        path.relative_to(storage): path.read_bytes()
        for path in storage.rglob("*")
        if path.is_file()
    }

    summary = backup_storage(storage, tmp_path / "backup")

    after = {
        path.relative_to(storage): path.read_bytes()
        for path in storage.rglob("*")
        if path.is_file()
    }
    copied = {
        path.relative_to(tmp_path / "backup"): path.read_bytes()
        for path in (tmp_path / "backup").rglob("*")
        if path.is_file()
    }
    assert summary.file_count == 2
    assert summary.byte_count == sum(map(len, before.values()))
    assert after == before == copied


@pytest.mark.parametrize("bad_destination", ["storage/backup", "storage"])
def test_storage_backup_rejects_destination_inside_or_equal_to_source(
    tmp_path: Path, bad_destination: str
) -> None:
    storage = tmp_path / "storage"
    storage.mkdir()

    with pytest.raises(ValueError, match="outside"):
        backup_storage(storage, tmp_path / bad_destination)
