"""Explicit batch deletes for 我的追番 (issue #223, ADR-0007).

Two actions, two contracts:

* ``POST /api/v1/tracking/batch-delete-plan`` deletes local plans/records only.
  Its body has no connection fields, so it can never reach Auto Bangumi: the
  external subscription keeps running and MiGuOrca stops managing it.
* ``POST /api/v1/tracking/batch-delete-plan-external`` runs the same local
  delete **after** a confirmed controlled external delete for that entry.  An
  external failure or an unknown outcome removes nothing for that entry (the
  plan, record, mapping and recovery evidence stay), exactly like the single
  composite delete in :mod:`tracking_plan_delete_service`.

Execution rules (ADR-0007):

* **Sequential**: entries run one after another, never concurrently.
* **Batch-level exclusion**: the whole batch holds the tracking-store batch
  lease, so another batch (submit or delete) and every single tracking write
  are refused while it runs (``connection_in_use`` → 409).
* **Eligibility re-verified per entry**: every entry goes through the single
  composite-delete service, which re-reads the record and its current operation
  and applies the ADR-0006 guard.  An entry that became unresolved after the
  user ticked it is **skipped with a reason** — never converted into an abandon,
  which is a separate risk-confirmed single action.
* **Idempotent and queryable**: the client's ``idempotency_key`` identifies the
  batch.  The per-entry outcome is persisted after every entry, so a client
  timeout can be followed by a status query or a same-key replay: completed
  entries are never executed again and each external delete keeps its derived
  per-entry idempotency key.  A key bound to different entries is a 409.

Security: the persisted batch record holds only the tracking ids, the outcome,
the skip reason and a one-way request fingerprint — never titles, URLs, magnets,
credentials, error text or absolute paths.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apps.migu_orca_web.schemas import (
    SavedTrackingBatchDeleteExternalInput,
    SavedTrackingBatchDeleteInput,
    SavedTrackingBatchDeleteItem,
    SavedTrackingPlanDeleteInput,
)
from apps.migu_orca_web.tracking_plan_delete_service import run_saved_tracking_plan_delete
from shared.errors import Stage1Error
from storage_engine.controllers.operation_repository import load_tracking_operation
from storage_engine.controllers.storage_config import (
    StorageConfig,
    ensure_storage_layout,
)
from storage_engine.controllers.storage_primitives import write_text_atomic
from storage_engine.controllers.tracking_repository import (
    load_tracking_record,
    tracking_batch_lease,
)
from tracking_engine.models.operation import (
    TRACKING_OPERATION_STATE_FAILED,
    TRACKING_OPERATION_STATE_IN_PROGRESS,
    TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
    TRACKING_OPERATION_STATE_PREPARED,
    TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
    TRACKING_OPERATION_STATE_SUCCEEDED,
)
from tracking_engine.models.tracking import (
    TRACKING_STATUS_RECOVERY_REQUIRED,
    TRACKING_STATUS_REVALIDATING,
    TRACKING_STATUS_SUBMITTING,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
)

_STEP = "run_saved_tracking_batch_delete"

KIND_LOCAL_ONLY = "LOCAL_ONLY"
KIND_LOCAL_AND_EXTERNAL = "LOCAL_AND_EXTERNAL"

STATE_IN_PROGRESS = "IN_PROGRESS"
STATE_COMPLETED = "COMPLETED"

SKIP_UNRESOLVED = "UNRESOLVED"
SKIP_REVISION_CHANGED = "REVISION_CHANGED"
SKIP_NOT_FOUND = "NOT_FOUND"

OUTCOME_DELETED = "DELETED"
OUTCOME_EXTERNAL_FAILED = "EXTERNAL_FAILED"
OUTCOME_EXTERNAL_UNKNOWN = "EXTERNAL_UNKNOWN"
OUTCOME_SKIPPED = "SKIPPED"

#: The single delete service is the eligibility authority; its stable refusal
#: codes become per-entry skip reasons instead of aborting the batch.
_SKIP_BY_ERROR = {
    "tracking_state_conflict": SKIP_UNRESOLVED,
    "tracking_revision_conflict": SKIP_REVISION_CHANGED,
    "tracking_not_found": SKIP_NOT_FOUND,
}

#: ADR-0006/ADR-0007: an entry in one of these states may still own an external
#: write (or an undecidable outcome), so a batch must not touch it.  The verdict
#: is re-derived from the current operation at execution time; this set only
#: classifies the skip reason *before* the authoritative single-delete call.
_UNRESOLVED_OPERATION_STATES = frozenset(
    {
        TRACKING_OPERATION_STATE_PREPARED,
        TRACKING_OPERATION_STATE_IN_PROGRESS,
        TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
        TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
    }
)

#: Finished history: shown in the operation log but never a delete lock.
_SETTLED_OPERATION_STATES = frozenset(
    {TRACKING_OPERATION_STATE_SUCCEEDED, TRACKING_OPERATION_STATE_FAILED}
)

#: Statuses that lock a delete when the record has no operation pointer.
_LOCKED_STATUSES = frozenset(
    {
        TRACKING_STATUS_SUBMITTING,
        TRACKING_STATUS_REVALIDATING,
        TRACKING_STATUS_VERIFYING_EXTERNAL,
        TRACKING_STATUS_RECOVERY_REQUIRED,
    }
)

#: Same shape the request schemas accept; kept here so a query/replay of a
#: hand-crafted key can never become a path segment.
_BATCH_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-:=]{0,199}$")
_RECORD_VERSION = 1
_RECORD_FILENAME_PREFIX = "tracking_batch_delete_"
_MAX_RECORD_BYTES = 256 * 1024


def _now(now: str | None) -> str:
    return now or datetime.now(UTC).isoformat()


def _validated_batch_key(batch_key: str, step: str = _STEP) -> str:
    key = batch_key.strip()
    if not _BATCH_KEY_RE.fullmatch(key):
        raise Stage1Error(
            "validation_error",
            "批量删除的幂等键不合法",
            step,
            {"field": "idempotency_key"},
        )
    return key


def _record_path(config: StorageConfig, batch_key: str) -> Path:
    return config.idempotency_dir / f"{_RECORD_FILENAME_PREFIX}{batch_key}.json"


def _read_record(config: StorageConfig, batch_key: str) -> dict[str, Any] | None:
    path = _record_path(config, batch_key)
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise Stage1Error(
            "storage_error",
            "读取批量删除记录失败",
            _STEP,
        ) from exc
    if len(raw.encode("utf-8")) > _MAX_RECORD_BYTES:
        raise Stage1Error("storage_json_error", "批量删除记录无法识别", _STEP)
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise Stage1Error(
            "storage_json_error",
            "批量删除记录无法识别",
            _STEP,
        ) from exc
    if not isinstance(data, dict) or data.get("version") != _RECORD_VERSION:
        raise Stage1Error("storage_json_error", "批量删除记录无法识别", _STEP)
    return data


def _write_record(config: StorageConfig, batch_key: str, record: dict[str, Any]) -> None:
    ensure_storage_layout(config)
    payload = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        write_text_atomic(_record_path(config, batch_key), payload)
    except OSError as exc:
        raise Stage1Error(
            "storage_error",
            "写入批量删除记录失败",
            _STEP,
        ) from exc


def _fingerprint(kind: str, items: list[SavedTrackingBatchDeleteItem]) -> str:
    """One-way digest of the batch identity (kind + entries + revisions)."""
    canonical = {
        "kind": kind,
        "items": sorted([item.tracking_id, item.expected_revision] for item in items),
    }
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _item_key(batch_key: str, tracking_id: str) -> str:
    """Deterministic per-entry idempotency key, so a replay never re-writes."""
    return f"{batch_key[:120]}-{tracking_id}"


def _summary(total: int, items: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": total,
        "deleted": sum(1 for item in items if item.get("outcome") == OUTCOME_DELETED),
        "external_deleted": sum(1 for item in items if item.get("external_deleted") is True),
        "skipped": sum(1 for item in items if item.get("outcome") == OUTCOME_SKIPPED),
        "failed": sum(1 for item in items if item.get("outcome") == OUTCOME_EXTERNAL_FAILED),
        "unknown": sum(1 for item in items if item.get("outcome") == OUTCOME_EXTERNAL_UNKNOWN),
    }


def _public(record: dict[str, Any]) -> dict[str, Any]:
    items = [dict(item) for item in record.get("items", [])]
    total = record.get("total")
    return {
        "batch_key": record["batch_key"],
        "kind": record["kind"],
        "state": record["state"],
        "items": items,
        "summary": _summary(total if isinstance(total, int) else len(items), items),
    }


def run_saved_tracking_batch_delete(
    config: StorageConfig,
    *,
    payload: SavedTrackingBatchDeleteInput,
    delete_external: bool,
    now: str | None = None,
) -> dict[str, Any]:
    """Run one explicit batch delete; replay-safe and mutually exclusive.

    ``delete_external=False`` never touches Auto Bangumi.  ``delete_external=
    True`` requires the external payload subclass (the saved connection), and
    each entry runs the single composite delete so an external failure leaves
    that entry's local data untouched.
    """
    kind = KIND_LOCAL_AND_EXTERNAL if delete_external else KIND_LOCAL_ONLY
    if delete_external and not isinstance(payload, SavedTrackingBatchDeleteExternalInput):
        raise Stage1Error(
            "validation_error",
            "批量外部删除需要已保存的 Auto Bangumi 连接",
            _STEP,
            {"field": "connection_ref"},
        )
    batch_key = payload.idempotency_key
    fingerprint = _fingerprint(kind, payload.items)
    total = len(payload.items)

    existing = _read_record(config, batch_key)
    if existing is not None:
        _require_same_batch(existing, fingerprint)
        if existing.get("state") == STATE_COMPLETED:
            # Same key + same entries: return the stored outcome, write nothing.
            return _public(existing)

    # ADR-0007 decision 3: the whole batch owns the tracking store while it
    # runs.  A concurrent batch or single external write fails closed here.
    with tracking_batch_lease(batch_key=batch_key, step=_STEP):
        existing = _read_record(config, batch_key)
        if existing is not None:
            _require_same_batch(existing, fingerprint)
            if existing.get("state") == STATE_COMPLETED:
                return _public(existing)
        record = existing if existing is not None else {
            "version": _RECORD_VERSION,
            "batch_key": batch_key,
            "kind": kind,
            "fingerprint": fingerprint,
            "total": total,
            "state": STATE_IN_PROGRESS,
            "items": [],
            "created_at": _now(now),
        }
        record["total"] = total
        record["state"] = STATE_IN_PROGRESS
        record["updated_at"] = _now(now)
        # A resumed batch keeps every entry that already reached a terminal
        # outcome; only unfinished entries run again (with the same per-entry
        # idempotency key, so no external write is repeated).
        completed = {
            item["tracking_id"]: item
            for item in record.get("items", [])
            if isinstance(item, dict) and isinstance(item.get("tracking_id"), str)
        }
        _write_record(config, batch_key, record)
        for entry in payload.items:
            if entry.tracking_id in completed:
                continue
            completed[entry.tracking_id] = _delete_one(
                config,
                entry,
                payload=payload,
                delete_external=delete_external,
                batch_key=batch_key,
            )
            record["items"] = [
                completed[item.tracking_id]
                for item in payload.items
                if item.tracking_id in completed
            ]
            record["updated_at"] = _now(now)
            _write_record(config, batch_key, record)
        record["state"] = STATE_COMPLETED
        record["updated_at"] = _now(now)
        _write_record(config, batch_key, record)
        return _public(record)


def _require_same_batch(existing: dict[str, Any], fingerprint: str) -> None:
    if existing.get("fingerprint") != fingerprint:
        raise Stage1Error(
            "idempotency_conflict",
            "该幂等键已绑定到另一批删除，请重新确认后重试",
            _STEP,
        )


def _delete_one(
    config: StorageConfig,
    entry: SavedTrackingBatchDeleteItem,
    *,
    payload: SavedTrackingBatchDeleteInput,
    delete_external: bool,
    batch_key: str,
) -> dict[str, Any]:
    """Delete one entry through the single composite-delete service.

    That service *is* the execution-time revalidation: it re-reads the record and
    its current operation, applies the ADR-0006 unresolved guard and, for the
    external kind, only deletes local data after a confirmed external success.
    Its stable refusals become per-entry skip reasons.
    """
    skip_reason = _skip_reason(config, entry)
    if skip_reason is not None:
        return {
            "tracking_id": entry.tracking_id,
            "outcome": OUTCOME_SKIPPED,
            "external_deleted": False,
            "skip_reason": skip_reason,
        }
    single = SavedTrackingPlanDeleteInput(
        tracking_id=entry.tracking_id,
        confirm=True,
        delete_external=delete_external,
        idempotency_key=_item_key(batch_key, entry.tracking_id),
        # The single delete contract takes the canonical string form.
        connection_ref=(
            str(payload.connection_ref)
            if isinstance(payload, SavedTrackingBatchDeleteExternalInput)
            else None
        ),
        configuration_revision=(
            payload.configuration_revision
            if isinstance(payload, SavedTrackingBatchDeleteExternalInput)
            else None
        ),
        storage_dir=payload.storage_dir,
        # NOT the single-delete risk-confirmation pair: the batch already
        # re-read the revision and the current operation in `_skip_reason`, and
        # the batch lease makes that read authoritative until the delete runs.
    )
    try:
        result = run_saved_tracking_plan_delete(config, payload=single)
    except Stage1Error as exc:
        skip_reason = _SKIP_BY_ERROR.get(exc.error_type)
        item: dict[str, Any] = {
            "tracking_id": entry.tracking_id,
            "outcome": OUTCOME_SKIPPED,
            "external_deleted": False,
            "skip_reason": skip_reason,
        }
        if skip_reason is None:
            # Any other refusal still leaves this entry untouched and the rest
            # of the batch keeps running; the stable code is the reason.
            item["error_type"] = exc.error_type
        return item
    return {
        "tracking_id": entry.tracking_id,
        "outcome": result.get("outcome", OUTCOME_SKIPPED),
        "external_deleted": bool(result.get("external_deleted")),
        "skip_reason": None,
    }


def _skip_reason(
    config: StorageConfig,
    entry: SavedTrackingBatchDeleteItem,
) -> str | None:
    """Classify why one entry must not be deleted right now, or ``None``.

    Read-only: the authoritative guard is still the single composite-delete
    service, which re-reads everything again right before it acts.  This only
    turns the same ADR-0006 states into an explicit per-entry reason instead of
    an opaque validation refusal.
    """
    try:
        record = load_tracking_record(config, entry.tracking_id)
    except Stage1Error as exc:
        return SKIP_NOT_FOUND if exc.error_type == "tracking_not_found" else SKIP_UNRESOLVED
    if record.revision != entry.expected_revision:
        return SKIP_REVISION_CHANGED
    if not record.current_operation_id:
        return SKIP_UNRESOLVED if record.status in _LOCKED_STATUSES else None
    try:
        operation = load_tracking_operation(config, record.current_operation_id)
    except Stage1Error:
        # Unreadable operation evidence fails closed (ADR-0006).
        return SKIP_UNRESOLVED
    if getattr(operation, "tracking_id", None) != record.tracking_id:
        return SKIP_UNRESOLVED
    state = getattr(operation, "state", None)
    if state in _UNRESOLVED_OPERATION_STATES:
        return SKIP_UNRESOLVED
    if state not in _SETTLED_OPERATION_STATES:
        # Anything that is not provably finished history — including unknown
        # values — fails closed instead of being deleted by a batch.
        return SKIP_UNRESOLVED
    return None


def get_saved_tracking_batch_delete(
    config: StorageConfig,
    *,
    batch_key: str,
) -> dict[str, Any]:
    """Return the persisted status of one batch (partial while IN_PROGRESS)."""
    key = _validated_batch_key(batch_key, "get_saved_tracking_batch_delete")
    record = _read_record(config, key)
    if record is None:
        raise Stage1Error(
            "tracking_not_found",
            "未找到该批量删除批次",
            "get_saved_tracking_batch_delete",
        )
    return _public(record)


__all__ = [
    "KIND_LOCAL_AND_EXTERNAL",
    "KIND_LOCAL_ONLY",
    "STATE_COMPLETED",
    "STATE_IN_PROGRESS",
    "SKIP_NOT_FOUND",
    "SKIP_REVISION_CHANGED",
    "SKIP_UNRESOLVED",
    "get_saved_tracking_batch_delete",
    "run_saved_tracking_batch_delete",
]
