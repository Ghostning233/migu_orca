from __future__ import annotations

"""US-251: persistence-version and historical-migration rehearsal.

The fixtures in this module are deliberately written as sanitized JSON.  The
test is a storage contract check: migration must consume old local evidence,
leave already-versioned records byte-for-byte untouched, and fail closed on a
future version without deleting the evidence or contacting an external client.
"""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from apps.migu_orca_entry.controllers.entry_controller import generate_request
from apps.migu_orca_web.tracking_migration_service import run_tracking_migration
from request_engine.controllers.request_controller import accept_request
from shared.errors import Stage1Error
from shared.models import EntryRequest
from storage_engine.controllers.ab_result_repository import save_ab_submit_result
from storage_engine.controllers.migration_repository import (
    MIGRATION_MANIFEST_FILENAME,
    load_migration_manifest,
)
from storage_engine.controllers.operation_repository import load_tracking_operation
from storage_engine.controllers.request_repository import save_request_snapshot
from storage_engine.controllers.storage_config import load_storage_config
from storage_engine.controllers.tracking_repository import (
    list_tracking_records,
    load_tracking_record,
)
from tracking_engine.models.operation import tracking_operation_id_for_idempotency_key
from tracking_engine.models.tracking import (
    TRACKING_STATUS_ACTIVE,
    create_tracking_record,
    tracking_id_for_request,
    tracking_to_storage_dict,
)

NOW = "2026-09-10T00:00:00+00:00"
REQUEST_ID = "stage32-request"
TRACKING_ID = tracking_id_for_request(REQUEST_ID)
OPERATION_KEY = "stage32-operation"
OPERATION_ID = tracking_operation_id_for_idempotency_key(OPERATION_KEY)


def _config(tmp_path: Path):
    return load_storage_config(tmp_path / "storage")


def _request() -> dict[str, object]:
    request = accept_request(
        {
            **generate_request(EntryRequest(raw_title="芙莉莲"))["request"],
            "request_id": REQUEST_ID,
        }
    )
    return request


def test_migration_rehearses_versioned_artifacts_without_rewriting_or_external_calls(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    request = _request()
    save_request_snapshot(config, request)
    save_ab_submit_result(
        config,
        {
            "request_id": REQUEST_ID,
            "ab_submit_result": {"success": True, "ab_subscription_id": "sub-safe"},
        },
    )

    # TrackingRecord v1 with an ExternalMapping v1 is already the current
    # format; it must be treated as evidence, not rewritten by a migration run.
    tracking = replace(
        create_tracking_record(
            request_id=REQUEST_ID,
            status=TRACKING_STATUS_ACTIVE,
            plan_summary={"title": "芙莉莲", "season": 1, "subtitle_group": "字幕组"},
            now=NOW,
        ),
        external_mapping={
            "schema_version": 1,
            "adapter": "legacy_3_1",
            "subscription_id": "sub-safe",
            "rss_ids": ["rss-safe"],
            "match_reason": "EXTERNAL_ID",
            "external_deleted": False,
            "enabled": True,
            "missing_sync_count": 0,
            "last_verified_at": NOW,
        },
    )
    config.tracking_dir.mkdir(parents=True, exist_ok=True)
    tracking_path = config.tracking_dir / f"{TRACKING_ID}.json"
    tracking_path.write_text(
        json.dumps(tracking_to_storage_dict(tracking), indent=2) + "\n",
        encoding="utf-8",
    )
    tracking_before = tracking_path.read_bytes()

    # Hand-written v1 operation fixture: loading v1 must not upgrade it to v2.
    operation_path = config.tracking_operations_dir / f"{OPERATION_ID}.json"
    operation_path.parent.mkdir(parents=True, exist_ok=True)
    operation_v1 = {
        "schema_version": 1,
        "operation_id": OPERATION_ID,
        "tracking_id": TRACKING_ID,
        "operation": "SUBMIT",
        "idempotency_key": OPERATION_KEY,
        "expected_revision": 1,
        "request_fingerprint": "sha256:stage32",
        "state": "SUCCEEDED",
        "attempt": 1,
        "external_result_id": "sub-safe",
        "error_type": None,
        "created_at": NOW,
        "updated_at": NOW,
        "completed_at": NOW,
    }
    operation_path.write_text(json.dumps(operation_v1, indent=2) + "\n", encoding="utf-8")
    operation_before = operation_path.read_bytes()

    result = run_tracking_migration(config=config, now=NOW)

    assert result.complete
    assert load_tracking_record(config, TRACKING_ID).status == TRACKING_STATUS_ACTIVE
    assert load_tracking_operation(config, OPERATION_ID).schema_version == 1
    assert tracking_path.read_bytes() == tracking_before
    assert operation_path.read_bytes() == operation_before


@pytest.mark.parametrize("kind", ["tracking", "operation", "manifest"])
def test_future_schema_fails_closed_and_preserves_original_evidence(
    tmp_path: Path, kind: str
) -> None:
    config = _config(tmp_path)
    if kind == "tracking":
        path = config.tracking_dir / f"{TRACKING_ID}.json"
        loader = lambda: load_tracking_record(config, TRACKING_ID)
        payload = {"schema_version": 99}
    elif kind == "operation":
        path = config.tracking_operations_dir / f"{OPERATION_ID}.json"
        loader = lambda: load_tracking_operation(config, OPERATION_ID)
        payload = {"schema_version": 99}
    else:
        path = config.tracking_migrations_dir / MIGRATION_MANIFEST_FILENAME
        loader = lambda: load_migration_manifest(config)
        payload = {"schema_version": 99}
    path.parent.mkdir(parents=True, exist_ok=True)
    original = (json.dumps(payload) + "\n").encode()
    path.write_bytes(original)

    with pytest.raises(Stage1Error) as error:
        loader()

    assert error.value.error_type == "storage_json_error"
    assert path.read_bytes() == original


def test_damaged_tracking_record_is_isolated_and_never_deleted(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.tracking_dir.mkdir(parents=True, exist_ok=True)
    path = config.tracking_dir / f"{TRACKING_ID}.json"
    path.write_text("{damaged", encoding="utf-8")

    listed = list_tracking_records(config)

    assert listed.records == []
    assert listed.unreadable_count == 1
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "{damaged"
