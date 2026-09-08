from __future__ import annotations

"""Historical-backfill migration runner (US-221).

This module is the coordinator that runs *before* any tracking API executes
(Stage 29 PRD §10.1).  It:

1. reads the durable migration manifest; when it is ``COMPLETE`` no full scan is
   performed (new data is tracked in real time by the accept/save-confirm
   handoff);
2. otherwise scans the local Request snapshots, batch pre-submission queues and
   saved Auto Bangumi results through the storage repositories (never touching
   an external system);
3. classifies each candidate Request with the pure §10.2 mapping and persists
   exactly one deterministic ``TrackingRecord`` per Request through
   ``ensure_tracking_record`` (create-if-absent, so re-runs never add records,
   change tracking ids/revisions or duplicate audit events);
4. writes a ``COMPLETE``/``PARTIAL`` manifest holding only the run window and
   safe counters (created / existing / recovery_required / unreadable).

Security: no Request id, batch id, file name, path, raw JSON, credential, URL,
magnet or upstream detail leaves this module through the public summary; the
manifest and the returned result carry only counts and the fixed state string.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from apps.migu_orca_web.save_confirm_service import compute_request_fingerprint
from storage_engine.controllers.ab_result_repository import (
    AbResultListResult,
    list_ab_submit_results_tolerant,
)
from storage_engine.controllers.migration_repository import (
    load_migration_manifest,
    save_migration_manifest,
)
from storage_engine.controllers.queue_repository import (
    QueueListResult,
    list_submission_queues_tolerant,
)
from storage_engine.controllers.request_repository import (
    RequestListResult,
    list_request_snapshots_tolerant,
)
from storage_engine.controllers.storage_config import (
    StorageConfig,
    load_storage_config,
)
from storage_engine.controllers.tracking_repository import ensure_tracking_record
from tracking_engine.controllers.migration import (
    AbMigrationEvidence,
    QueueMigrationEvidence,
    RequestBackfillEvidence,
    build_backfill_record,
    classify_backfill,
)
from tracking_engine.models.migration import (
    MIGRATION_STATE_COMPLETE,
    MIGRATION_STATE_PARTIAL,
    MigrationCounts,
    MigrationManifest,
)
from tracking_engine.models.tracking import (
    TRACKING_STATUS_RECOVERY_REQUIRED,
    utc_now,
)

#: Fixed warning string used by future tracking APIs when the migration
#: manifest is ``PARTIAL`` (Stage 29 PRD §10.1).  It never exposes which file or
#: request was damaged.
MIGRATION_PARTIAL_WARNING = "部分历史数据未能读取，将在后续访问时继续尝试迁移"


@dataclass(frozen=True)
class TrackingMigrationResult:
    """Safe public result of one migration attempt."""

    manifest: MigrationManifest
    replayed: bool = False

    @property
    def complete(self) -> bool:
        return self.manifest.state == MIGRATION_STATE_COMPLETE

    @property
    def partial(self) -> bool:
        return self.manifest.state == MIGRATION_STATE_PARTIAL

    def warning(self) -> str | None:
        """Return the fixed warning a tracking API may expose (or ``None``)."""
        if self.partial:
            return MIGRATION_PARTIAL_WARNING
        return None


def run_tracking_migration(
    *,
    storage_dir: Path | str | None = None,
    config: StorageConfig | None = None,
    now: str | None = None,
) -> TrackingMigrationResult:
    """Run the historical backfill once and return a safe summary.

    Pass exactly one of ``storage_dir`` or ``config``.  ``now`` is a test seam
    that fixes the manifest timestamps; when omitted the current UTC time is
    used.
    """
    resolved_config = config if config is not None else load_storage_config(storage_dir)

    existing = load_migration_manifest(resolved_config)
    if existing is not None and existing.state == MIGRATION_STATE_COMPLETE:
        return TrackingMigrationResult(manifest=existing, replayed=True)

    timestamp = now or utc_now()

    requests_result = list_request_snapshots_tolerant(resolved_config)
    queues_result = list_submission_queues_tolerant(resolved_config)
    ab_results_result = list_ab_submit_results_tolerant(resolved_config)

    requests_by_id = _requests_by_id(requests_result)
    queue_items_by_request = _queue_items_by_request(queues_result)
    ab_by_request = _ab_records_by_request(ab_results_result)
    ab_damaged_ids = set(ab_results_result.damaged_request_ids)
    request_damaged_ids = set(requests_result.damaged_request_ids)

    candidates = (
        set(requests_by_id)
        | set(queue_items_by_request)
        | set(ab_by_request)
        | ab_damaged_ids
    )

    created = 0
    existing_count = 0
    recovery_count = 0

    for request_id in sorted(candidates):
        # A damaged Request snapshot cannot be migrated safely; it stays a
        # PARTIAL/unreadable item and is retried on a later access.
        if request_id in request_damaged_ids:
            continue
        request = requests_by_id.get(request_id)
        evidence = RequestBackfillEvidence(
            request_id=request_id,
            request=request,
            queue_items=tuple(queue_items_by_request.get(request_id, ())),
            ab=_resolve_ab_evidence(request, ab_by_request, ab_damaged_ids, request_id),
        )
        decision = classify_backfill(evidence)
        if not decision.create or decision.status is None:
            continue
        if decision.status == TRACKING_STATUS_RECOVERY_REQUIRED:
            recovery_count += 1
        fingerprint = (
            compute_request_fingerprint(request) if isinstance(request, dict) else None
        )
        record = build_backfill_record(
            decision=decision,
            request=request,
            request_fingerprint=fingerprint,
            now=timestamp,
        )
        _, was_created = ensure_tracking_record(resolved_config, record)
        if was_created:
            created += 1
        else:
            existing_count += 1

    unreadable = (
        requests_result.unreadable_count
        + queues_result.unreadable_count
        + ab_results_result.unreadable_count
    )
    state = MIGRATION_STATE_COMPLETE if unreadable == 0 else MIGRATION_STATE_PARTIAL
    manifest = MigrationManifest(
        state=state,
        started_at=timestamp,
        finished_at=timestamp,
        counts=MigrationCounts(
            created=created,
            existing=existing_count,
            recovery_required=recovery_count,
            unreadable=unreadable,
        ),
    )
    save_migration_manifest(resolved_config, manifest)
    return TrackingMigrationResult(manifest=manifest, replayed=False)


# ---------------------------------------------------------------------------
# Internal scan helpers
# ---------------------------------------------------------------------------


def _requests_by_id(result: RequestListResult) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for request in result.requests:
        request_id = request.get("request_id")
        if isinstance(request_id, str) and request_id:
            by_id[request_id] = request
    return by_id


def _queue_items_by_request(result: QueueListResult) -> dict[str, list[QueueMigrationEvidence]]:
    by_request: dict[str, list[QueueMigrationEvidence]] = {}
    for queue in result.queues:
        for item in queue.items:
            request_id = item.request_id
            if not request_id:
                continue
            by_request.setdefault(request_id, []).append(
                QueueMigrationEvidence(
                    batch_id=queue.batch_id,
                    queue_id=queue.queue_id,
                    status=item.status,
                    created_at=queue.created_at,
                )
            )
    return by_request


def _ab_records_by_request(result: AbResultListResult) -> dict[str, AbMigrationEvidence]:
    by_request: dict[str, AbMigrationEvidence] = {}
    for record in result.records:
        request_id = record.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            continue
        inner = record.get("ab_submit_result")
        by_request[request_id] = _evidence_from_ab_result(inner)
    return by_request


def _resolve_ab_evidence(
    request: dict[str, Any] | None,
    ab_by_request: dict[str, AbMigrationEvidence],
    ab_damaged_ids: set[str],
    request_id: str,
) -> AbMigrationEvidence:
    """Resolve one Request's saved Auto Bangumi evidence.

    The durable ``ab_results/<request_id>.json`` record wins when readable; the
    Request snapshot's embedded ``ab_submit_result`` is the fallback.  A damaged
    result file is surfaced as ``damaged=True`` only when no readable evidence
    exists (so a corrupt file cannot silently downgrade a clear success).
    """
    file_evidence = ab_by_request.get(request_id)
    if file_evidence is not None:
        return file_evidence
    embedded_evidence = None
    if isinstance(request, dict):
        embedded = request.get("ab_submit_result")
        if isinstance(embedded, dict):
            embedded_evidence = _evidence_from_ab_result(embedded)
    if embedded_evidence is not None:
        return embedded_evidence
    if request_id in ab_damaged_ids:
        return AbMigrationEvidence(damaged=True)
    return AbMigrationEvidence()


def _evidence_from_ab_result(value: Any) -> AbMigrationEvidence:
    """Reduce a sanitized ``ab_submit_result`` to non-sensitive evidence."""
    if not isinstance(value, dict):
        return AbMigrationEvidence()
    success = value.get("success")
    if isinstance(success, bool):
        error_type = None
        error = value.get("error")
        if isinstance(error, dict) and isinstance(error.get("error_type"), str):
            error_type = error["error_type"]
        return AbMigrationEvidence(present=True, success=success, error_type=error_type)
    return AbMigrationEvidence(present=True, success=None)


__all__ = [
    "MIGRATION_PARTIAL_WARNING",
    "TrackingMigrationResult",
    "run_tracking_migration",
]
