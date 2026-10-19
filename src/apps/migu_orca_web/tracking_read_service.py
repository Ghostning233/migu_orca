from __future__ import annotations

"""Read-model orchestration for the unified tracking list/detail (US-223).

This module is the Web-service layer between the tracking routes and the
storage/engine repositories.  Every read goes through the historical-backfill
coordinator first (Stage 29 PRD §10.1: any tracking API access re-runs the
migration until its manifest is COMPLETE), then builds the public safe DTO
payloads through the tracking serializers.

Security rules enforced here:
- a single damaged tracking record never blocks the healthy list — the list
  reports only a fixed warning plus the ``unreadable`` summary count, never a
  file name/path/raw JSON;
- free-text labels and resource counts come from the Request safe-info
  producer; a missing/damaged backing Request degrades the item to the record's
  own safe ``plan_summary`` with ``valid_resource_count`` 0 — it never fails
  the list or detail;
- the detail reuses ``serialize_request_safe_info`` unchanged and adds only the
  current operation's safe summary, revalidation issues, external mapping
  summary and the most recent audit events.
"""

from typing import Any

from apps.migu_orca_web.serializers import serialize_request_safe_info
from apps.migu_orca_web.services import (
    _load_ab_result_section,
    _load_history_section,
    _storage_profile,
)
from apps.migu_orca_web.tracking_migration_service import run_tracking_migration
from apps.migu_orca_web.tracking_serializers import (
    serialize_tracking_audit_events,
    serialize_tracking_external_summary,
    serialize_tracking_operation_summary,
    tracking_summary_fields,
)
from shared.errors import Stage1Error
from storage_engine.controllers.operation_repository import load_tracking_operation
from storage_engine.controllers.request_repository import (
    list_request_snapshots_tolerant,
    load_request_snapshot,
)
from storage_engine.controllers.storage_config import StorageConfig
from storage_engine.controllers.tracking_repository import (
    list_tracking_records,
    load_tracking_record,
)
from tracking_engine.models.operation import TRACKING_SUBMISSION_MODES_SET
from tracking_engine.models.tracking import (
    TRACKING_OVERVIEW_CARD_GROUPS,
    TRACKING_STATUS_ADDED_TO_DOWNLOAD,
    TRACKING_STATUS_EXTERNAL_ONLY,
    TRACKING_STATUS_GROUP_ACTIVE,
    TRACKING_STATUS_GROUP_ATTENTION,
    TRACKING_STATUS_GROUP_INACTIVE,
    TRACKING_STATUS_GROUP_LABELS,
    TRACKING_STATUS_GROUP_ORDER,
    TRACKING_STATUS_GROUP_PENDING,
    TRACKING_STATUS_GROUP_PROCESSING,
    TrackingRecord,
    tracking_status_group,
)

#: Fixed warning returned when one or more tracking JSON files cannot be read.
#: Never exposes which file/path or any raw content (Stage 29 PRD §11.2).
TRACKING_LIST_UNREADABLE_WARNING = "部分追番记录暂时无法读取，已从列表跳过"

#: Fixed warning when the detail's backing Request is absent/unreadable.
TRACKING_DETAIL_REQUEST_UNAVAILABLE_WARNING = "该订阅方案不存在或暂时不可读"

#: Fixed warning when the record references an operation that cannot be read.
TRACKING_DETAIL_OPERATION_UNAVAILABLE_WARNING = "当前提交操作记录暂不可读"

#: Default sort is newest ``updated_at`` first (local list, stable tie-break).
_DEFAULT_SORT = "updated_at"

#: Sorting by these keys is stable thanks to the tracking_id tie-break.
_SORT_KEYS = ("updated_at", "title", "status")


def list_tracking_items(
    config: StorageConfig,
    *,
    q: str | None = None,
    status_group: str | None = None,
    sort: str | None = None,
) -> dict[str, Any]:
    """Build the safe public tracking list payload (Stage 29 PRD §11.2).

    The ``summary`` counts are computed over all healthy records (independent of
    the current filter), so group tabs stay stable while ``items`` reflects the
    ``q``/``status_group`` filter and ``sort`` order.
    """
    migration_result = run_tracking_migration(config=config)
    warnings: list[str] = []
    migration_warning = migration_result.warning()
    if migration_warning:
        warnings.append(migration_warning)

    listing = list_tracking_records(config)
    healthy_records = [record for record in listing.records if not _is_merged_alias(record)]
    unreadable = listing.unreadable_count
    if unreadable:
        warnings.append(TRACKING_LIST_UNREADABLE_WARNING)

    requests_by_id = _requests_by_id(list_request_snapshots_tolerant(config))
    summary = _summary_counts(
        healthy_records,
        added_to_download=_count_added_to_download(healthy_records),
        unreadable=unreadable,
    )
    visible = _filter_records(healthy_records, q=q, status_group=status_group)
    visible = _sort_records(visible, sort=sort)

    items: list[dict[str, Any]] = []
    for record in visible:
        request = requests_by_id.get(record.request_id) if record.request_id else None
        valid_count = _request_valid_resource_count(request)
        items.append(
            {
                **_product_summary_fields(record, valid_resource_count=valid_count),
                "submission_mode": _submission_mode_for(config, record),
            }
        )

    return {
        "items": items,
        "summary": summary,
        # Issue #224 A7: list-level group metadata, so the client renders
        # server-owned labels and authoritative counts — including for an empty
        # list and for zero-count groups — and keeps no label table of its own.
        "status_groups": _status_group_metadata(healthy_records),
        "warnings": warnings,
    }


def build_tracking_detail(
    config: StorageConfig,
    tracking_id: str,
) -> dict[str, Any]:
    """Build the safe public tracking detail payload (Stage 29 PRD §11.3).

    Reuses the Request safe-info producer and adds only the current operation's
    safe summary, revalidation issues, external mapping summary and the most
    recent 20 audit events.  A missing/damaged backing Request or operation
    degrades to the safe summary plus a fixed warning — never a failure.
    """
    migration_result = run_tracking_migration(config=config)
    record = load_tracking_record(config, tracking_id)

    warnings: list[str] = []
    migration_warning = migration_result.warning()
    if migration_warning:
        warnings.append(migration_warning)

    request_id = record.request_id
    safe_info: dict[str, Any] | None = None
    valid_count = 0
    if request_id:
        request = _tolerant_load_request(config, request_id)
        if isinstance(request, dict):
            history_events = _request_history_events(config, request_id)
            ab_result = _request_ab_result(config, request_id)
            safe_info = serialize_request_safe_info(
                request,
                history_events=history_events,
                ab_submit_result=ab_result,
                storage_profile=_storage_profile(config.storage_dir),
            )
            resources = safe_info.get("resources")
            if isinstance(resources, dict):
                count = resources.get("valid_resource_count")
                valid_count = count if isinstance(count, int) and count >= 0 else 0
        else:
            warnings.append(TRACKING_DETAIL_REQUEST_UNAVAILABLE_WARNING)

    current_operation = None
    operation_id = record.current_operation_id
    if operation_id:
        operation = _tolerant_load_operation(config, operation_id)
        if operation is not None:
            current_operation = serialize_tracking_operation_summary(operation)
        else:
            warnings.append(TRACKING_DETAIL_OPERATION_UNAVAILABLE_WARNING)

    base = _product_summary_fields(record, valid_resource_count=valid_count)
    return {
        **base,
        "submission_mode": _submission_mode_for(config, record),
        "origin": record.origin,
        "batch_id": record.batch_id,
        "created_at": record.created_at,
        "last_synced_at": record.last_synced_at,
        "safe_info": safe_info,
        "current_operation": current_operation,
        "revalidation_issues": [],
        "external_mapping": serialize_tracking_external_summary(record.external_mapping),
        "audit_events": serialize_tracking_audit_events(record.audit_events),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _requests_by_id(result: Any) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for request in result.requests if hasattr(result, "requests") else []:
        if not isinstance(request, dict):
            continue
        request_id = request.get("request_id")
        if isinstance(request_id, str) and request_id:
            by_id[request_id] = request
    return by_id


def _is_merged_alias(record: TrackingRecord) -> bool:
    recovery = record.recovery if isinstance(record.recovery, dict) else {}
    return isinstance(recovery.get("merged_into_tracking_id"), str)


def _submission_mode_for(config: StorageConfig, record: TrackingRecord) -> str | None:
    """The submission mode to display for one record (issue #99 AC 6/7).

    Only a record whose operation actually exists may show a mode, so a fresh
    待提交/需修改 plan never fabricates one. An unreadable operation or an
    unknown value fails closed to ``None`` (never guessed from the status).
    """
    operation_id = record.current_operation_id
    if not operation_id:
        return None
    operation = _tolerant_load_operation(config, operation_id)
    if operation is None:
        return None
    mode = operation.submission_mode
    return mode if mode in TRACKING_SUBMISSION_MODES_SET else None


def _summary_counts(
    records: list[TrackingRecord],
    *,
    added_to_download: int,
    unreadable: int,
) -> dict[str, int]:
    """Whole-library, card-aligned counts for the list summary (issue #224).

    Every count is derived from the same group projection the ``status_groups``
    metadata publishes, so the two can never disagree.  ``EXTERNAL_ONLY`` is
    excluded from every group count (A4) but still counted in ``total`` because
    全部 keeps it visible.
    """
    group_counts = _status_group_counts(records)
    return {
        "total": len(records),
        "pending": group_counts[TRACKING_STATUS_GROUP_PENDING],
        "processing": group_counts[TRACKING_STATUS_GROUP_PROCESSING],
        # 追番中 + 已加入下载 are one card; the two raw views stay separate so a
        # client that still knows the older contract keeps its meaning.
        "active": group_counts[TRACKING_STATUS_GROUP_ACTIVE] - added_to_download,
        "added_to_download": added_to_download,
        "inactive": group_counts[TRACKING_STATUS_GROUP_INACTIVE],
        "needs_attention": group_counts[TRACKING_STATUS_GROUP_ATTENTION],
        "unreadable": unreadable,
    }


def _status_group_counts(records: list[TrackingRecord]) -> dict[str, int]:
    """Count every status group once, excluding the retired read-only state.

    Issue #224 A4: ``EXTERNAL_ONLY`` archives stay loadable but never join a
    card count.  ADR-0005 retired the state's product semantics, so counting it
    in 已停用 would misstate a historical fact as a MiGuOrca retirement.
    """
    counts = {group: 0 for group in TRACKING_STATUS_GROUP_ORDER}
    for record in records:
        if record.status == TRACKING_STATUS_EXTERNAL_ONLY:
            continue
        counts[tracking_status_group(record.status)] += 1
    return counts


def _count_added_to_download(records: list[TrackingRecord]) -> int:
    return sum(
        1 for record in records if record.status == TRACKING_STATUS_ADDED_TO_DOWNLOAD
    )


def _status_group_metadata(records: list[TrackingRecord]) -> list[dict[str, Any]]:
    """Publish the five-group vocabulary with authoritative counts (#224 A7).

    The list is always complete: an empty list still publishes all five groups
    with ``count`` 0, so the client can render the four cards without inventing
    a label or a zero itself.
    """
    counts = _status_group_counts(records)
    return [
        {
            "group": group,
            "label": TRACKING_STATUS_GROUP_LABELS[group],
            "count": counts[group],
            "has_overview_card": group in TRACKING_OVERVIEW_CARD_GROUPS,
        }
        for group in TRACKING_STATUS_GROUP_ORDER
    ]


def _product_summary_fields(
    record: TrackingRecord,
    *,
    valid_resource_count: int,
) -> dict[str, Any]:
    """Serialize one safe summary plus the product rules for retired states.

    The serializer stays the generic projection; the retired read-only
    ``EXTERNAL_ONLY`` state is a product decision (ADR-0005, issue #224 A4), so
    it keeps its real label but is offered no management action.  The page-level
    删除追番方案 / 复制并重新添加 entries are not part of ``available_actions``.
    """
    fields = tracking_summary_fields(record, valid_resource_count=valid_resource_count)
    if record.status == TRACKING_STATUS_EXTERNAL_ONLY:
        fields["available_actions"] = []
    return fields


def _filter_records(
    records: list[TrackingRecord],
    *,
    q: str | None,
    status_group: str | None,
) -> list[TrackingRecord]:
    filtered = records
    if status_group is not None:
        filtered = [
            record
            for record in filtered
            # Issue #224 A4: a retired archive is visible only in 全部, so no
            # card/group filter may return it even though it maps to INACTIVE.
            if record.status != TRACKING_STATUS_EXTERNAL_ONLY
            and tracking_status_group(record.status) == status_group
        ]
    if q:
        needle = q.casefold()
        filtered = [
            record
            for record in filtered
            if _matches_query(record, needle)
        ]
    return filtered


def _matches_query(record: TrackingRecord, needle: str) -> bool:
    plan = record.plan_summary if isinstance(record.plan_summary, dict) else {}
    for value in (plan.get("title"), plan.get("subtitle_group")):
        if isinstance(value, str) and needle in value.casefold():
            return True
    request_id = record.request_id
    return isinstance(request_id, str) and needle in request_id.casefold()


def _sort_records(
    records: list[TrackingRecord],
    sort: str | None,
) -> list[TrackingRecord]:
    key = (sort or _DEFAULT_SORT).strip().lower()
    if key not in _SORT_KEYS:
        key = _DEFAULT_SORT
    if key == "updated_at":
        return sorted(
            records,
            key=lambda record: (_sort_timestamp(record.updated_at), record.tracking_id),
            reverse=True,
        )
    if key == "title":
        return sorted(
            records,
            key=lambda record: (_sort_title(record), record.tracking_id),
        )
    return sorted(
        records,
        key=lambda record: (record.status, record.tracking_id),
    )


def _sort_timestamp(value: str | None) -> str:
    return value or ""


def _sort_title(record: TrackingRecord) -> str:
    plan = record.plan_summary if isinstance(record.plan_summary, dict) else {}
    title = plan.get("title")
    return title.casefold() if isinstance(title, str) else ""


def _request_valid_resource_count(request: dict[str, Any] | None) -> int:
    if not isinstance(request, dict):
        return 0
    safe = serialize_request_safe_info(request, storage_profile=None)
    resources = safe.get("resources")
    if not isinstance(resources, dict):
        return 0
    count = resources.get("valid_resource_count")
    return count if isinstance(count, int) and count >= 0 else 0


def _tolerant_load_request(
    config: StorageConfig,
    request_id: str,
) -> dict[str, Any] | None:
    try:
        loaded = load_request_snapshot(config, request_id)
        return loaded if isinstance(loaded, dict) else None
    except Stage1Error:
        return None


def _tolerant_load_operation(config: StorageConfig, operation_id: str) -> Any | None:
    try:
        return load_tracking_operation(config, operation_id)
    except Stage1Error:
        return None


def _request_history_events(config: StorageConfig, request_id: str) -> list[dict[str, Any]]:
    section = _load_history_section(config, request_id)
    if section.get("available") is not True:
        return []
    events = section.get("events")
    return [event for event in events if isinstance(event, dict)] if isinstance(events, list) else []


def _request_ab_result(config: StorageConfig, request_id: str) -> dict[str, Any] | None:
    section = _load_ab_result_section(config, request_id)
    if section.get("available") is not True:
        return None
    record = section.get("record")
    if not isinstance(record, dict):
        return None
    inner = record.get("ab_submit_result")
    return inner if isinstance(inner, dict) else None


__all__ = [
    "TRACKING_DETAIL_OPERATION_UNAVAILABLE_WARNING",
    "TRACKING_DETAIL_REQUEST_UNAVAILABLE_WARNING",
    "TRACKING_LIST_UNREADABLE_WARNING",
    "build_tracking_detail",
    "list_tracking_items",
]
