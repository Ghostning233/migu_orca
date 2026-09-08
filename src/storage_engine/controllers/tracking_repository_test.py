from __future__ import annotations

"""US-219: durable TrackingRecord repository tests.

These exercise ``storage_engine.controllers.tracking_repository`` against a
``tmp_path`` storage profile: deterministic convergence, concurrent ``ensure``,
revision compare-and-swap, damaged JSON/poisoned files, path-traversal
rejection, atomic writes, and the guarantee that the persisted file never
carries sensitive content.
"""

import json
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from shared.errors import Stage1Error
from storage_engine.controllers.storage_config import load_storage_config
from storage_engine.controllers.tracking_repository import (
    TrackingListResult,
    compare_and_swap_tracking_record,
    ensure_tracking_record,
    list_tracking_records,
    load_tracking_record,
)
from tracking_engine.models.tracking import (
    TRACKING_AUDIT_REVALIDATION_PASSED,
    TRACKING_STATUS_PENDING_SUBMIT,
    TRACKING_STATUS_REVALIDATING,
    TrackingRecord,
    create_tracking_record,
    tracking_id_for_request,
    tracking_to_storage_dict,
    transition_record,
)

REQUEST_ID = "0f8fad5b-d9cb-469f-a165-70867728950e"
SECOND_REQUEST_ID = "7d444840-9dc0-11d1-b245-5ffdce74fad2"


def _config(tmp_path: Path):
    return load_storage_config(tmp_path / "migu-state")


def _record(
    request_id: str = REQUEST_ID,
    *,
    title: str = "葬送的芙莉莲",
    now: str = "2026-09-08T00:00:00+00:00",
) -> TrackingRecord:
    return create_tracking_record(
        request_id=request_id,
        status=TRACKING_STATUS_PENDING_SUBMIT,
        plan_summary={
            "title": title,
            "season": 2,
            "subtitle_group": "喵萌奶茶屋",
            "poster_path": "/api/v1/mikan/posters/opaque-key",
        },
        now=now,
    )


def test_ensure_then_load_round_trips_all_public_fields(tmp_path: Path) -> None:
    config = _config(tmp_path)
    record = _record()

    saved, created = ensure_tracking_record(config, record)
    loaded = load_tracking_record(config, record.tracking_id)

    assert created is True
    assert saved == record
    assert loaded == record
    assert (config.tracking_dir / f"{record.tracking_id}.json").exists()


def test_ensure_is_create_if_absent_and_never_overwrites(tmp_path: Path) -> None:
    config = _config(tmp_path)
    first = _record(title="第一版")
    second = _record(title="第二版")

    saved_first, created_first = ensure_tracking_record(config, first)
    saved_second, created_second = ensure_tracking_record(config, second)

    assert created_first is True
    assert created_second is False
    assert saved_first == saved_second
    assert saved_second.plan_summary["title"] == "第一版"
    # Only one file exists for the request.
    assert len(list(config.tracking_dir.glob("*.json"))) == 1


def test_ensure_requires_revision_one_and_matching_tracking_id(tmp_path: Path) -> None:
    config = _config(tmp_path)
    record = _record()
    moved = transition_record(
        record,
        status=TRACKING_STATUS_REVALIDATING,
        audit_action=TRACKING_AUDIT_REVALIDATION_PASSED,
        now="2026-09-08T00:01:00+00:00",
    )
    with pytest.raises(Stage1Error) as error:
        ensure_tracking_record(config, moved)
    assert error.value.error_type == "invalid_tracking_record"

    tampered = replace(record, tracking_id="trk_" + "a" * 32)
    with pytest.raises(Stage1Error) as error:
        ensure_tracking_record(config, tampered)
    assert error.value.error_type == "invalid_tracking_record"

    no_request = replace(record, request_id=None)
    with pytest.raises(Stage1Error) as error:
        ensure_tracking_record(config, no_request)
    assert error.value.error_type == "invalid_tracking_record"


def test_concurrent_ensure_converges_to_single_record(tmp_path: Path) -> None:
    config = _config(tmp_path)
    barrier = threading.Barrier(8)
    results: list[tuple[TrackingRecord, bool]] = [None] * 8  # type: ignore[list-item]
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            record = _record(title=f"并发-{index}")
            barrier.wait()
            results[index] = ensure_tracking_record(config, record)
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
    tracking_ids = {record.tracking_id for record, _ in results}
    assert tracking_ids == {tracking_id_for_request(REQUEST_ID)}
    assert len(list(config.tracking_dir.glob("*.json"))) == 1


def test_different_requests_produce_distinct_records(tmp_path: Path) -> None:
    config = _config(tmp_path)
    first, _ = ensure_tracking_record(config, _record(REQUEST_ID))
    second, _ = ensure_tracking_record(config, _record(SECOND_REQUEST_ID))

    assert first.tracking_id != second.tracking_id
    assert len(list_tracking_records(config).records) == 2


def test_compare_and_swap_succeeds_with_exact_revision_bump(tmp_path: Path) -> None:
    config = _config(tmp_path)
    saved, _ = ensure_tracking_record(config, _record())
    next_record = transition_record(
        saved,
        status=TRACKING_STATUS_REVALIDATING,
        audit_action=TRACKING_AUDIT_REVALIDATION_PASSED,
        now="2026-09-08T00:01:00+00:00",
    )

    result = compare_and_swap_tracking_record(
        config, saved.tracking_id, base_revision=saved.revision, record=next_record
    )

    assert result.revision == 2
    assert result.status == TRACKING_STATUS_REVALIDATING
    assert len(result.audit_events) == 2
    loaded = load_tracking_record(config, saved.tracking_id)
    assert loaded.revision == 2


def test_compare_and_swap_stale_base_raises_revision_conflict(tmp_path: Path) -> None:
    config = _config(tmp_path)
    saved, _ = ensure_tracking_record(config, _record())
    # Advance the record once.
    first_next = transition_record(
        saved,
        status=TRACKING_STATUS_REVALIDATING,
        audit_action=TRACKING_AUDIT_REVALIDATION_PASSED,
        now="2026-09-08T00:01:00+00:00",
    )
    compare_and_swap_tracking_record(config, saved.tracking_id, saved.revision, first_next)

    # A stale CAS from revision 1 must now conflict.
    stale = transition_record(
        saved,
        status=TRACKING_STATUS_REVALIDATING,
        audit_action=TRACKING_AUDIT_REVALIDATION_PASSED,
        now="2026-09-08T00:02:00+00:00",
    )
    with pytest.raises(Stage1Error) as error:
        compare_and_swap_tracking_record(config, saved.tracking_id, 1, stale)

    assert error.value.error_type == "tracking_revision_conflict"
    assert error.value.details["current_revision"] == 2
    assert load_tracking_record(config, saved.tracking_id).revision == 2


def test_compare_and_swap_rejects_wrong_next_revision(tmp_path: Path) -> None:
    config = _config(tmp_path)
    saved, _ = ensure_tracking_record(config, _record())
    bad = replace(saved, revision=saved.revision + 2)

    with pytest.raises(Stage1Error) as error:
        compare_and_swap_tracking_record(config, saved.tracking_id, saved.revision, bad)
    assert error.value.error_type == "invalid_tracking_record"


def test_compare_and_swap_missing_record_raises_tracking_not_found(tmp_path: Path) -> None:
    config = _config(tmp_path)
    missing_id = tracking_id_for_request(SECOND_REQUEST_ID)

    with pytest.raises(Stage1Error) as error:
        compare_and_swap_tracking_record(
            config,
            missing_id,
            base_revision=1,
            record=_record(SECOND_REQUEST_ID),
        )
    assert error.value.error_type == "tracking_not_found"


def test_load_missing_record_raises_tracking_not_found(tmp_path: Path) -> None:
    missing_id = tracking_id_for_request(SECOND_REQUEST_ID)

    with pytest.raises(Stage1Error) as error:
        load_tracking_record(_config(tmp_path), missing_id)
    assert error.value.error_type == "tracking_not_found"
    assert error.value.failed_step == "load_tracking_record"


def test_load_damaged_record_returns_stable_error_without_leaking_bytes(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    config.tracking_dir.mkdir(parents=True)
    tracking_id = tracking_id_for_request(REQUEST_ID)
    (config.tracking_dir / f"{tracking_id}.json").write_text("{", encoding="utf-8")

    with pytest.raises(Stage1Error) as error:
        load_tracking_record(config, tracking_id)

    assert error.value.as_dict()["error_type"] == "storage_json_error"
    assert error.value.failed_step == "load_tracking_record"
    assert error.value.details["tracking_id"] == tracking_id
    assert str(tmp_path) not in str(error.value.as_dict())


def test_load_unknown_schema_field_fails_closed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.tracking_dir.mkdir(parents=True)
    tracking_id = tracking_id_for_request(REQUEST_ID)
    record = _record()
    poisoned = tracking_to_storage_dict(record)
    poisoned["ab_config"] = {"token": "secret"}
    (config.tracking_dir / f"{tracking_id}.json").write_text(
        json.dumps(poisoned, ensure_ascii=False), encoding="utf-8"
    )

    with pytest.raises(Stage1Error) as error:
        load_tracking_record(config, tracking_id)
    assert error.value.error_type == "storage_json_error"
    # Unknown fields fail closed rather than being silently accepted.
    assert "unknown tracking record fields" in error.value.details["reason"]


def test_list_skips_damaged_files_and_reports_unreadable_count(tmp_path: Path) -> None:
    config = _config(tmp_path)
    ensure_tracking_record(config, _record(REQUEST_ID))
    config.tracking_dir.mkdir(parents=True, exist_ok=True)
    broken_id = tracking_id_for_request(SECOND_REQUEST_ID)
    (config.tracking_dir / f"{broken_id}.json").write_text("{bad json", encoding="utf-8")
    # A stray non-JSON file is ignored.
    (config.tracking_dir / "notes.txt").write_text("hello", encoding="utf-8")

    result = list_tracking_records(config)

    assert isinstance(result, TrackingListResult)
    assert len(result.records) == 1
    assert result.unreadable_count == 1
    assert result.damaged_tracking_ids == (broken_id,)
    assert result.records[0].tracking_id == tracking_id_for_request(REQUEST_ID)


def test_list_empty_and_missing_directory(tmp_path: Path) -> None:
    config = _config(tmp_path)
    result = list_tracking_records(config)
    assert result.records == []
    assert result.damaged_tracking_ids == ()
    assert result.unreadable_count == 0


def test_rejects_path_traversal_tracking_id(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with pytest.raises(Stage1Error) as error:
        load_tracking_record(config, "../outside")
    assert error.value.error_type == "invalid_tracking_id"
    assert not (config.tracking_dir.parent / "outside.json").exists()


def test_rejects_nested_tracking_id(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with pytest.raises(Stage1Error) as error:
        load_tracking_record(config, "nested/key")
    assert error.value.error_type == "invalid_tracking_id"
    assert error.value.failed_step == "load_tracking_record"


def test_rejects_tracking_id_with_illegal_characters(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with pytest.raises(Stage1Error) as error:
        load_tracking_record(config, "trk_bad!id")
    assert error.value.error_type == "invalid_tracking_id"


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path: Path) -> None:
    config = _config(tmp_path)
    record = _record()

    ensure_tracking_record(config, record)

    files = [path.name for path in config.tracking_dir.iterdir()]
    assert files == [f"{record.tracking_id}.json"]
    assert not (config.tracking_dir / f"{record.tracking_id}.json.tmp").exists()


def test_write_failure_returns_stable_error_without_leaking_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)

    def fail_replace(src: Any, dst: Any) -> None:
        raise OSError("permission denied: /sensitive/tracking/path")

    monkeypatch.setattr("os.replace", fail_replace)

    with pytest.raises(Stage1Error) as error:
        ensure_tracking_record(config, _record())
    assert error.value.error_type == "storage_error"
    assert error.value.failed_step == "ensure_tracking_record"
    assert error.value.details["directory"] == "tracking"
    assert "/sensitive" not in str(error.value.as_dict())


def test_persisted_file_never_contains_sensitive_values(tmp_path: Path) -> None:
    """US-219 security: only whitelisted normalized fields reach disk."""
    config = _config(tmp_path)
    saved, _ = ensure_tracking_record(config, _record())

    secret = "very-secret-token-value"
    next_record = replace(
        transition_record(
            saved,
            status=TRACKING_STATUS_REVALIDATING,
            audit_action=TRACKING_AUDIT_REVALIDATION_PASSED,
            now="2026-09-08T00:01:00+00:00",
        ),
        external_mapping={
            "external_id": "ab-123",
            "token": secret,
            "url": "https://example.invalid/RSS?token=secret",
            "magnet": "magnet:?xt=urn:btih:abc",
            "path": "/home/ghostning/.migu_orca/storage/requests/secret.json",
            "ok": "keep-me",
        },
        recovery={"raw": {"body": secret}},
    )
    compare_and_swap_tracking_record(
        config, saved.tracking_id, saved.revision, next_record
    )

    written = (config.tracking_dir / f"{saved.tracking_id}.json").read_text(
        encoding="utf-8"
    )
    assert "very-secret" not in written
    assert "example.invalid" not in written
    assert "magnet:?xt" not in written
    assert "/home/ghostning" not in written
    assert "external_id" in written
    assert "keep-me" in written


def test_ensure_and_cas_enforce_request_consistency(tmp_path: Path) -> None:
    """A record whose tracking_id does not match its request_id is rejected."""
    config = _config(tmp_path)
    other = _record(SECOND_REQUEST_ID)
    # Renaming a record to point at the wrong request is detected on load.
    mislabeled = tracking_to_storage_dict(_record(REQUEST_ID))
    mislabeled["request_id"] = SECOND_REQUEST_ID
    config.tracking_dir.mkdir(parents=True)
    tracking_id = tracking_id_for_request(SECOND_REQUEST_ID)
    (config.tracking_dir / f"{tracking_id}.json").write_text(
        json.dumps(mislabeled, ensure_ascii=False), encoding="utf-8"
    )

    with pytest.raises(Stage1Error) as error:
        load_tracking_record(config, tracking_id)
    assert error.value.error_type == "storage_json_error"
    assert "does not match request_id-derived id" in error.value.details["reason"]
    assert other.tracking_id != tracking_id_for_request(REQUEST_ID)
