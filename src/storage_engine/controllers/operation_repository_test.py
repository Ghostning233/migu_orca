from __future__ import annotations

"""US-220: durable TrackingOperation repository tests.

These exercise ``storage_engine.controllers.operation_repository`` against a
``tmp_path`` storage profile: deterministic bind/replay, idempotency binding
conflicts, per-key concurrency, state compare-and-swap, restart readability of
``IN_PROGRESS``/terminal results, damaged JSON, path-traversal rejection, atomic
writes, and the guarantee that persisted operation files never carry sensitive
content.
"""

import json
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from shared.errors import Stage1Error
from storage_engine.controllers.operation_repository import (
    bind_tracking_operation,
    compare_and_swap_tracking_operation,
    load_tracking_operation,
)
from storage_engine.controllers.storage_config import load_storage_config
from tracking_engine.models.operation import (
    TRACKING_OPERATION_KIND_SUBMIT,
    TRACKING_OPERATION_STATE_FAILED,
    TRACKING_OPERATION_STATE_IN_PROGRESS,
    TRACKING_OPERATION_STATE_PREPARED,
    TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
    TRACKING_OPERATION_STATE_SUCCEEDED,
    TrackingOperation,
    create_tracking_operation,
    operation_to_storage_dict,
    tracking_operation_id_for_idempotency_key,
    transition_tracking_operation,
)

IDEMPOTENCY_KEY = "client-op-key-20260908-a1"
SECOND_KEY = "client-op-key-20260908-b2"
OPERATION_ID = tracking_operation_id_for_idempotency_key(IDEMPOTENCY_KEY)
SECOND_OPERATION_ID = tracking_operation_id_for_idempotency_key(SECOND_KEY)

TRACKING_ID = "trk_ba8abbe28fb5345ceccabd82850ee091"
SECOND_TRACKING_ID = "trk_0f8fad5bd9cb469fa16570867728950e"
FINGERPRINT = "sha256:abc123"
SECOND_FINGERPRINT = "sha256:def456"


def _config(tmp_path: Path):
    return load_storage_config(tmp_path / "migu-state")


def _bind(
    config,
    *,
    tracking_id: str = TRACKING_ID,
    idempotency_key: str = IDEMPOTENCY_KEY,
    expected_revision: int = 5,
    request_fingerprint: str = FINGERPRINT,
    operation: str = TRACKING_OPERATION_KIND_SUBMIT,
    now: str = "2026-09-08T00:00:00+00:00",
) -> tuple[TrackingOperation, bool]:
    return bind_tracking_operation(
        config,
        tracking_id=tracking_id,
        operation=operation,
        idempotency_key=idempotency_key,
        expected_revision=expected_revision,
        request_fingerprint=request_fingerprint,
        now=now,
    )


def test_bind_creates_prepared_operation_and_round_trips(tmp_path: Path) -> None:
    config = _config(tmp_path)

    operation, created = _bind(config)

    assert created is True
    assert operation.operation_id == OPERATION_ID
    assert operation.state == TRACKING_OPERATION_STATE_PREPARED
    assert operation.tracking_id == TRACKING_ID
    assert operation.idempotency_key == IDEMPOTENCY_KEY
    loaded = load_tracking_operation(config, operation.operation_id)
    assert loaded == operation
    assert (config.tracking_operations_dir / f"{OPERATION_ID}.json").exists()


def test_same_key_same_binding_replays_stored_operation(tmp_path: Path) -> None:
    config = _config(tmp_path)
    first, created_first = _bind(config)

    replay, created_again = _bind(config)

    assert created_first is True
    assert created_again is False
    assert replay == first
    # Only one operation file exists for the key.
    assert len(list(config.tracking_operations_dir.glob("*.json"))) == 1


def test_same_key_different_tracking_id_raises_idempotency_conflict(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    _bind(config)

    with pytest.raises(Stage1Error) as error:
        _bind(config, tracking_id=SECOND_TRACKING_ID)

    assert error.value.error_type == "tracking_idempotency_conflict"
    assert error.value.details["field"] == "idempotency_key"
    # The original operation is untouched.
    assert load_tracking_operation(config, OPERATION_ID).tracking_id == TRACKING_ID


def test_same_key_different_expected_revision_raises_conflict(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _bind(config)

    with pytest.raises(Stage1Error) as error:
        _bind(config, expected_revision=9)

    assert error.value.error_type == "tracking_idempotency_conflict"
    assert load_tracking_operation(config, OPERATION_ID).expected_revision == 5


def test_same_key_different_fingerprint_raises_conflict(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _bind(config)

    with pytest.raises(Stage1Error) as error:
        _bind(config, request_fingerprint=SECOND_FINGERPRINT)

    assert error.value.error_type == "tracking_idempotency_conflict"
    assert (
        load_tracking_operation(config, OPERATION_ID).request_fingerprint
        == FINGERPRINT
    )


def test_same_key_different_operation_kind_raises_conflict(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _bind(config)

    with pytest.raises(Stage1Error) as error:
        _bind(config, operation="MODIFY")

    assert error.value.error_type == "tracking_idempotency_conflict"
    assert load_tracking_operation(config, OPERATION_ID).operation == "SUBMIT"


def test_unknown_operation_kind_with_fresh_key_is_rejected(tmp_path: Path) -> None:
    config = _config(tmp_path)

    with pytest.raises(Stage1Error) as error:
        _bind(config, idempotency_key=SECOND_KEY, operation="MODIFY")

    assert error.value.error_type == "invalid_tracking_operation"


def test_different_keys_produce_distinct_operations(tmp_path: Path) -> None:
    config = _config(tmp_path)
    first, _ = _bind(config)
    second, _ = _bind(config, idempotency_key=SECOND_KEY)

    assert first.operation_id == OPERATION_ID
    assert second.operation_id == SECOND_OPERATION_ID
    assert first != second
    assert len(list(config.tracking_operations_dir.glob("*.json"))) == 2


def test_concurrent_bind_same_key_converges_to_single_operation(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    barrier = threading.Barrier(8)
    results: list[tuple[TrackingOperation, bool]] = [None] * 8  # type: ignore[list-item]
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            barrier.wait()
            # Every worker replays the same idempotency binding, so the group
            # must converge to one operation with exactly one creator.
            results[index] = _bind(config)
        except BaseException as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    created_flags = [created for _, created in results]
    assert sum(created_flags) == 1
    operation_ids = {operation.operation_id for operation, _ in results}
    assert operation_ids == {OPERATION_ID}
    assert len(list(config.tracking_operations_dir.glob("*.json"))) == 1


def test_compare_and_swap_transitions_prepared_to_in_progress(tmp_path: Path) -> None:
    config = _config(tmp_path)
    prepared, _ = _bind(config)
    in_progress = transition_tracking_operation(
        prepared,
        state=TRACKING_OPERATION_STATE_IN_PROGRESS,
        now="2026-09-08T00:01:00+00:00",
    )

    result = compare_and_swap_tracking_operation(
        config, prepared.operation_id, expected_state=prepared.state, record=in_progress
    )

    assert result.state == TRACKING_OPERATION_STATE_IN_PROGRESS
    assert load_tracking_operation(config, OPERATION_ID).state == (
        TRACKING_OPERATION_STATE_IN_PROGRESS
    )


def test_restart_reads_in_progress_and_terminal_results(tmp_path: Path) -> None:
    """A crash boundary written before the external call survives a restart."""
    config = _config(tmp_path)
    prepared, _ = _bind(config)
    in_progress = transition_tracking_operation(
        prepared,
        state=TRACKING_OPERATION_STATE_IN_PROGRESS,
        now="2026-09-08T00:01:00+00:00",
    )
    compare_and_swap_tracking_operation(
        config, prepared.operation_id, prepared.state, in_progress
    )

    # A "restart" simply re-reads the last atomically written state.
    restarted = load_tracking_operation(config, OPERATION_ID)
    assert restarted.state == TRACKING_OPERATION_STATE_IN_PROGRESS
    assert restarted.created_at == "2026-09-08T00:00:00+00:00"
    assert restarted.updated_at == "2026-09-08T00:01:00+00:00"

    succeeded = transition_tracking_operation(
        restarted,
        state=TRACKING_OPERATION_STATE_SUCCEEDED,
        external_result_id="ab-123",
        now="2026-09-08T00:02:00+00:00",
    )
    compare_and_swap_tracking_operation(
        config, OPERATION_ID, restarted.state, succeeded
    )
    terminal = load_tracking_operation(config, OPERATION_ID)
    assert terminal.state == TRACKING_OPERATION_STATE_SUCCEEDED
    assert terminal.external_result_id == "ab-123"
    assert terminal.completed_at == "2026-09-08T00:02:00+00:00"


def test_compare_and_swap_stale_expected_state_raises_state_conflict(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    prepared, _ = _bind(config)
    in_progress = transition_tracking_operation(
        prepared,
        state=TRACKING_OPERATION_STATE_IN_PROGRESS,
        now="2026-09-08T00:01:00+00:00",
    )
    compare_and_swap_tracking_operation(
        config, OPERATION_ID, prepared.state, in_progress
    )

    stale = transition_tracking_operation(
        prepared,
        state=TRACKING_OPERATION_STATE_IN_PROGRESS,
        now="2026-09-08T00:02:00+00:00",
    )
    with pytest.raises(Stage1Error) as error:
        compare_and_swap_tracking_operation(
            config, OPERATION_ID, expected_state=prepared.state, record=stale
        )

    assert error.value.error_type == "tracking_operation_state_conflict"
    assert error.value.details["current_state"] == TRACKING_OPERATION_STATE_IN_PROGRESS
    assert load_tracking_operation(config, OPERATION_ID).state == (
        TRACKING_OPERATION_STATE_IN_PROGRESS
    )


def test_compare_and_swap_rejects_illegal_transition(tmp_path: Path) -> None:
    config = _config(tmp_path)
    prepared, _ = _bind(config)
    # SUCCEEDED is not reachable directly from PREPARED.
    illegal = replace(prepared, state=TRACKING_OPERATION_STATE_SUCCEEDED)

    with pytest.raises(Stage1Error) as error:
        compare_and_swap_tracking_operation(
            config, OPERATION_ID, prepared.state, illegal
        )

    assert error.value.error_type == "invalid_tracking_operation"
    assert error.value.details["from_state"] == TRACKING_OPERATION_STATE_PREPARED
    assert error.value.details["to_state"] == TRACKING_OPERATION_STATE_SUCCEEDED


def test_compare_and_swap_rejects_immutable_binding_change(tmp_path: Path) -> None:
    config = _config(tmp_path)
    prepared, _ = _bind(config)
    in_progress = transition_tracking_operation(
        prepared,
        state=TRACKING_OPERATION_STATE_IN_PROGRESS,
        now="2026-09-08T00:01:00+00:00",
    )
    tampered = replace(in_progress, tracking_id=SECOND_TRACKING_ID)

    with pytest.raises(Stage1Error) as error:
        compare_and_swap_tracking_operation(
            config, OPERATION_ID, prepared.state, tampered
        )

    assert error.value.error_type == "invalid_tracking_operation"
    assert error.value.details["field"] == "tracking_id"


def test_compare_and_swap_rejects_operation_id_mismatch(tmp_path: Path) -> None:
    config = _config(tmp_path)
    prepared, _ = _bind(config)
    in_progress = transition_tracking_operation(
        prepared,
        state=TRACKING_OPERATION_STATE_IN_PROGRESS,
        now="2026-09-08T00:01:00+00:00",
    )
    mismatched = replace(in_progress, operation_id=SECOND_OPERATION_ID)

    with pytest.raises(Stage1Error) as error:
        compare_and_swap_tracking_operation(
            config, OPERATION_ID, prepared.state, mismatched
        )

    assert error.value.error_type == "invalid_tracking_operation"
    assert error.value.details["field"] == "operation_id"


def test_compare_and_swap_missing_operation_raises_not_found(tmp_path: Path) -> None:
    config = _config(tmp_path)
    # Build a record whose deterministic id has never been bound on disk.
    missing = transition_tracking_operation(
        create_tracking_operation(
            tracking_id=TRACKING_ID,
            idempotency_key=SECOND_KEY,
            expected_revision=5,
            request_fingerprint=FINGERPRINT,
            now="2026-09-08T00:00:00+00:00",
        ),
        state=TRACKING_OPERATION_STATE_IN_PROGRESS,
        now="2026-09-08T00:01:00+00:00",
    )

    with pytest.raises(Stage1Error) as error:
        compare_and_swap_tracking_operation(
            config,
            SECOND_OPERATION_ID,
            expected_state=TRACKING_OPERATION_STATE_PREPARED,
            record=missing,
        )

    assert error.value.error_type == "tracking_operation_not_found"


def test_load_missing_operation_raises_not_found(tmp_path: Path) -> None:
    with pytest.raises(Stage1Error) as error:
        load_tracking_operation(_config(tmp_path), OPERATION_ID)
    assert error.value.error_type == "tracking_operation_not_found"
    assert error.value.failed_step == "load_tracking_operation"


def test_load_damaged_operation_returns_stable_error_without_leaking_bytes(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    config.tracking_operations_dir.mkdir(parents=True)
    (config.tracking_operations_dir / f"{OPERATION_ID}.json").write_text(
        "{", encoding="utf-8"
    )

    with pytest.raises(Stage1Error) as error:
        load_tracking_operation(config, OPERATION_ID)

    assert error.value.as_dict()["error_type"] == "storage_json_error"
    assert error.value.failed_step == "load_tracking_operation"
    assert error.value.details["operation_id"] == OPERATION_ID
    assert str(tmp_path) not in str(error.value.as_dict())


def test_load_unknown_schema_field_fails_closed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.tracking_operations_dir.mkdir(parents=True)
    operation, _ = _bind(config, now="2026-09-08T00:00:00+00:00")
    poisoned = operation_to_storage_dict(operation)
    poisoned["ab_config"] = {"token": "secret"}
    (config.tracking_operations_dir / f"{OPERATION_ID}.json").write_text(
        json.dumps(poisoned, ensure_ascii=False), encoding="utf-8"
    )

    with pytest.raises(Stage1Error) as error:
        load_tracking_operation(config, OPERATION_ID)
    assert error.value.error_type == "storage_json_error"
    assert "unknown tracking operation fields" in error.value.details["reason"]


def test_load_poisoned_operation_id_mismatch_fails_closed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.tracking_operations_dir.mkdir(parents=True)
    operation, _ = _bind(config, now="2026-09-08T00:00:00+00:00")
    poisoned = operation_to_storage_dict(operation)
    poisoned["operation_id"] = SECOND_OPERATION_ID
    (config.tracking_operations_dir / f"{OPERATION_ID}.json").write_text(
        json.dumps(poisoned, ensure_ascii=False), encoding="utf-8"
    )

    with pytest.raises(Stage1Error) as error:
        load_tracking_operation(config, OPERATION_ID)
    assert error.value.error_type == "storage_json_error"
    assert "does not match idempotency-key-derived id" in error.value.details["reason"]


def test_rejects_path_traversal_operation_id(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with pytest.raises(Stage1Error) as error:
        load_tracking_operation(config, "../outside")
    assert error.value.error_type == "invalid_operation_id"
    assert not (config.tracking_operations_dir.parent / "outside.json").exists()


def test_rejects_nested_operation_id(tmp_path: Path) -> None:
    with pytest.raises(Stage1Error) as error:
        load_tracking_operation(_config(tmp_path), "nested/key")
    assert error.value.error_type == "invalid_operation_id"
    assert error.value.failed_step == "load_tracking_operation"


def test_rejects_operation_id_with_illegal_characters(tmp_path: Path) -> None:
    with pytest.raises(Stage1Error) as error:
        load_tracking_operation(_config(tmp_path), "op_bad!id")
    assert error.value.error_type == "invalid_operation_id"


@pytest.mark.parametrize(
    "bad_key",
    ["", "   ", "has/slash", "back\\slash", "magnet:?xt=urn:btih:abc", "http://x/"],
)
def test_bind_rejects_unsafe_idempotency_keys(tmp_path: Path, bad_key: str) -> None:
    config = _config(tmp_path)
    with pytest.raises(Stage1Error) as error:
        _bind(config, idempotency_key=bad_key)
    assert error.value.error_type == "invalid_idempotency_key"
    assert list(config.tracking_operations_dir.glob("*.json")) == []


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _bind(config)

    files = [path.name for path in config.tracking_operations_dir.iterdir()]
    assert files == [f"{OPERATION_ID}.json"]
    assert not (config.tracking_operations_dir / f"{OPERATION_ID}.json.tmp").exists()


def test_write_failure_returns_stable_error_without_leaking_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)

    def fail_replace(src: Any, dst: Any) -> None:
        raise OSError("permission denied: /sensitive/operations/path")

    monkeypatch.setattr("os.replace", fail_replace)

    with pytest.raises(Stage1Error) as error:
        _bind(config)
    assert error.value.error_type == "storage_error"
    assert error.value.failed_step == "bind_tracking_operation"
    assert error.value.details["directory"] == "tracking_operations"
    assert "/sensitive" not in str(error.value.as_dict())


def test_persisted_operation_never_contains_sensitive_values(tmp_path: Path) -> None:
    config = _config(tmp_path)
    prepared, _ = _bind(config)
    in_progress = transition_tracking_operation(
        prepared,
        state=TRACKING_OPERATION_STATE_IN_PROGRESS,
        now="2026-09-08T00:01:00+00:00",
    )
    compare_and_swap_tracking_operation(
        config, OPERATION_ID, prepared.state, in_progress
    )

    written = (config.tracking_operations_dir / f"{OPERATION_ID}.json").read_text(
        encoding="utf-8"
    )
    for sensitive in (
        "ab_config",
        "request_body",
        "title",
        "magnet",
        "http://",
        "https://",
        "/home/",
        "token",
        "password",
        "rss",
    ):
        assert sensitive not in written
    # Every persisted key is a strict-whitelist top-level field.
    assert set(json.loads(written)) == {
        "schema_version",
        "operation_id",
        "tracking_id",
        "operation",
        "idempotency_key",
        "expected_revision",
        "request_fingerprint",
        "state",
        "attempt",
        "external_result_id",
        "error_type",
        "created_at",
        "updated_at",
        "completed_at",
    }


def test_failed_pre_external_operation_proves_external_was_never_called(
    tmp_path: Path,
) -> None:
    """PREPARED -> FAILED is the durable evidence that no external call happened."""
    config = _config(tmp_path)
    prepared, _ = _bind(config)
    failed = transition_tracking_operation(
        prepared,
        state=TRACKING_OPERATION_STATE_FAILED,
        error_type="PRESIST_PREPARE_FAILED",
        now="2026-09-08T00:01:00+00:00",
    )
    compare_and_swap_tracking_operation(
        config, OPERATION_ID, prepared.state, failed
    )

    loaded = load_tracking_operation(config, OPERATION_ID)
    assert loaded.state == TRACKING_OPERATION_STATE_FAILED
    assert loaded.error_type == "PRESIST_PREPARE_FAILED"
    assert loaded.completed_at == "2026-09-08T00:01:00+00:00"


def test_recovery_required_is_a_readable_terminal_state(tmp_path: Path) -> None:
    config = _config(tmp_path)
    prepared, _ = _bind(config)
    in_progress = transition_tracking_operation(
        prepared,
        state=TRACKING_OPERATION_STATE_IN_PROGRESS,
        now="2026-09-08T00:01:00+00:00",
    )
    compare_and_swap_tracking_operation(
        config, OPERATION_ID, prepared.state, in_progress
    )
    recovery = transition_tracking_operation(
        in_progress,
        state=TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
        error_type="RESULT_PERSIST_FAILED",
        now="2026-09-08T00:02:00+00:00",
    )
    compare_and_swap_tracking_operation(
        config, OPERATION_ID, in_progress.state, recovery
    )

    loaded = load_tracking_operation(config, OPERATION_ID)
    assert loaded.state == TRACKING_OPERATION_STATE_RECOVERY_REQUIRED
    assert loaded.error_type == "RESULT_PERSIST_FAILED"
