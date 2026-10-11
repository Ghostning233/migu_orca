"""TrackingRecord data contract and deterministic tracking IDs (US-219).

The unified tracking list replaces the two-stage mental model ("batch vs
request") with one record per accepted subscription plan.  This module owns the
**content** contract only — durable JSON persistence lives in
``storage_engine.controllers.tracking_repository``.

Deterministic ID
----------------
A Request-backed record's ``tracking_id`` is derived only from the public
``request_id`` through a frozen, versioned namespace::

    tracking_id = "trk_" + sha256("migu-orca/tracking/v1\\x00" + request_id)[:32]

The namespace and digest length are test-pinned so the same Request always
converges to the same record across concurrent ``ensure``, restarts, terminal
replays and migration (D29-03).  Upgrading the algorithm must not silently
change existing IDs — introduce a new namespace/prefix instead.

Security
--------
- The record stores only non-sensitive whitelisted fields.  It never holds the
  full Request, AB config, upstream responses, raw titles, RSS URLs, magnets,
  credentials, absolute paths or tracebacks.
- ``plan_summary`` keeps only display fields (title/season/subtitle_group/
  poster_path); ``poster_path`` may only be an opaque same-origin poster route.
- ``audit_events`` keep a fixed safe shape; ``last_error`` keeps only a stable
  ``error_type``/``reason_code``/``safe_message`` summary.
- ``external_mapping`` is a strict v1/v2 object and ``recovery`` remains a
  future (B-C) opaque object; both are deep-cleaned on write so an accidental
  sensitive value cannot persist.
- Unknown top-level schema fields fail closed on read (never guessed).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from typing import Any
from uuid import UUID, uuid4

from shared.sensitive_values import redact_sensitive_text
from shared.timestamps import utc_now

TRACKING_SCHEMA_VERSION = 1
EXTERNAL_MAPPING_SCHEMA_VERSION = 2
EXTERNAL_MAPPING_LEGACY_SCHEMA_VERSION = 1
EXTERNAL_MAPPING_MAX_RSS_IDS = 128
EXTERNAL_OPAQUE_TOKEN_MAX_LENGTH = 128

# -- origins -----------------------------------------------------------------
#: A record created through the Stage 28/29 single-plan save-confirm handoff.
TRACKING_ORIGIN_SAVE_CONFIRM = "SAVE_CONFIRM"
#: A record created from a legacy single-plan accept entry point.
TRACKING_ORIGIN_LEGACY_ACCEPT = "LEGACY_ACCEPT"
#: A record backfilled from an old batch pre-submission queue.
TRACKING_ORIGIN_MIGRATED_QUEUE = "MIGRATED_QUEUE"
#: A record backfilled from a saved Auto Bangumi submit result.
TRACKING_ORIGIN_MIGRATED_AB_RESULT = "MIGRATED_AB_RESULT"
TRACKING_ORIGIN_EXTERNAL_SYNC = "EXTERNAL_SYNC"
TRACKING_ORIGINS = frozenset(
    {
        TRACKING_ORIGIN_SAVE_CONFIRM,
        TRACKING_ORIGIN_LEGACY_ACCEPT,
        TRACKING_ORIGIN_MIGRATED_QUEUE,
        TRACKING_ORIGIN_MIGRATED_AB_RESULT,
        TRACKING_ORIGIN_EXTERNAL_SYNC,
    }
)

# -- statuses ----------------------------------------------------------------
TRACKING_STATUS_PENDING_SUBMIT = "PENDING_SUBMIT"
TRACKING_STATUS_REVALIDATING = "REVALIDATING"
TRACKING_STATUS_NEEDS_RECONFIRM = "NEEDS_RECONFIRM"
TRACKING_STATUS_SUBMITTING = "SUBMITTING"
TRACKING_STATUS_VERIFYING_EXTERNAL = "VERIFYING_EXTERNAL"
TRACKING_STATUS_ACTIVE = "ACTIVE"
#: Issue #98/#99: a one-time "download existing resources" request was accepted
#: by Auto Bangumi.  It is a local terminal fact — not an external subscription.
TRACKING_STATUS_ADDED_TO_DOWNLOAD = "ADDED_TO_DOWNLOAD"
TRACKING_STATUS_SUBMIT_FAILED = "SUBMIT_FAILED"
TRACKING_STATUS_RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
TRACKING_STATUS_UNKNOWN = "UNKNOWN"
# B-C reserved statuses (Stage 29 must never produce them).
TRACKING_STATUS_DISABLED = "DISABLED"
TRACKING_STATUS_EXTERNAL_DELETED = "EXTERNAL_DELETED"
TRACKING_STATUS_EXTERNAL_ONLY = "EXTERNAL_ONLY"

#: The nine statuses Stage 29 B-B may actively produce (Stage 29 PRD §8.1).
B_B_TRACKING_STATUSES = frozenset(
    {
        TRACKING_STATUS_PENDING_SUBMIT,
        TRACKING_STATUS_REVALIDATING,
        TRACKING_STATUS_NEEDS_RECONFIRM,
        TRACKING_STATUS_SUBMITTING,
        TRACKING_STATUS_VERIFYING_EXTERNAL,
        TRACKING_STATUS_ACTIVE,
        TRACKING_STATUS_SUBMIT_FAILED,
        TRACKING_STATUS_RECOVERY_REQUIRED,
        TRACKING_STATUS_UNKNOWN,
    }
)

#: Every status the schema accepts (B-B nine + B-C reserved three).
TRACKING_STATUSES = B_B_TRACKING_STATUSES | frozenset(
    {
        TRACKING_STATUS_DISABLED,
        TRACKING_STATUS_EXTERNAL_DELETED,
        TRACKING_STATUS_EXTERNAL_ONLY,
        TRACKING_STATUS_ADDED_TO_DOWNLOAD,
    }
)

# -- user-visible status groups (Stage 29 PRD §8.2) --------------------------
TRACKING_STATUS_GROUP_PENDING = "PENDING"
TRACKING_STATUS_GROUP_PROCESSING = "PROCESSING"
TRACKING_STATUS_GROUP_ACTIVE = "ACTIVE"
TRACKING_STATUS_GROUP_ATTENTION = "ATTENTION"
TRACKING_STATUS_GROUP_INACTIVE = "INACTIVE"

#: Backend status -> user status group.  ``EXTERNAL_ONLY`` is grouped only for
#: schema completeness; B-C owns its display semantics.
TRACKING_STATUS_GROUPS: dict[str, str] = {
    TRACKING_STATUS_PENDING_SUBMIT: TRACKING_STATUS_GROUP_PENDING,
    TRACKING_STATUS_REVALIDATING: TRACKING_STATUS_GROUP_PROCESSING,
    TRACKING_STATUS_NEEDS_RECONFIRM: TRACKING_STATUS_GROUP_PENDING,
    TRACKING_STATUS_SUBMITTING: TRACKING_STATUS_GROUP_PROCESSING,
    TRACKING_STATUS_VERIFYING_EXTERNAL: TRACKING_STATUS_GROUP_PROCESSING,
    TRACKING_STATUS_ACTIVE: TRACKING_STATUS_GROUP_ACTIVE,
    TRACKING_STATUS_ADDED_TO_DOWNLOAD: TRACKING_STATUS_GROUP_ACTIVE,
    TRACKING_STATUS_SUBMIT_FAILED: TRACKING_STATUS_GROUP_ATTENTION,
    TRACKING_STATUS_RECOVERY_REQUIRED: TRACKING_STATUS_GROUP_ATTENTION,
    TRACKING_STATUS_UNKNOWN: TRACKING_STATUS_GROUP_ATTENTION,
    TRACKING_STATUS_DISABLED: TRACKING_STATUS_GROUP_INACTIVE,
    TRACKING_STATUS_EXTERNAL_DELETED: TRACKING_STATUS_GROUP_INACTIVE,
    TRACKING_STATUS_EXTERNAL_ONLY: TRACKING_STATUS_GROUP_INACTIVE,
}

#: Chinese display labels for every accepted backend status (§8.2).
TRACKING_STATUS_LABELS: dict[str, str] = {
    TRACKING_STATUS_PENDING_SUBMIT: "待提交",
    TRACKING_STATUS_REVALIDATING: "复核中",
    TRACKING_STATUS_NEEDS_RECONFIRM: "待重新确认",
    TRACKING_STATUS_SUBMITTING: "提交中",
    TRACKING_STATUS_VERIFYING_EXTERNAL: "核验外部结果中",
    TRACKING_STATUS_ACTIVE: "正在追番",
    TRACKING_STATUS_ADDED_TO_DOWNLOAD: "已加入下载",
    TRACKING_STATUS_SUBMIT_FAILED: "提交失败",
    TRACKING_STATUS_RECOVERY_REQUIRED: "需要恢复",
    TRACKING_STATUS_UNKNOWN: "状态未知",
    TRACKING_STATUS_DISABLED: "已停用",
    TRACKING_STATUS_EXTERNAL_DELETED: "外部已删除",
    TRACKING_STATUS_EXTERNAL_ONLY: "仅外部",
}

#: Chinese display labels for the user status groups (§8.2).
TRACKING_STATUS_GROUP_LABELS: dict[str, str] = {
    TRACKING_STATUS_GROUP_PENDING: "待处理",
    TRACKING_STATUS_GROUP_PROCESSING: "处理中",
    TRACKING_STATUS_GROUP_ACTIVE: "正在追番",
    TRACKING_STATUS_GROUP_ATTENTION: "需要处理",
    TRACKING_STATUS_GROUP_INACTIVE: "已停用/已删除",
}

# -- audit actors & actions --------------------------------------------------
TRACKING_AUDIT_ACTOR_SYSTEM = "SYSTEM"
TRACKING_AUDIT_ACTOR_USER = "USER"
TRACKING_AUDIT_ACTOR_MIGRATION = "MIGRATION"
TRACKING_AUDIT_ACTORS = frozenset(
    {
        TRACKING_AUDIT_ACTOR_SYSTEM,
        TRACKING_AUDIT_ACTOR_USER,
        TRACKING_AUDIT_ACTOR_MIGRATION,
    }
)

TRACKING_AUDIT_TRACKING_CREATED = "TRACKING_CREATED"
TRACKING_AUDIT_TRACKING_BACKFILLED = "TRACKING_BACKFILLED"
TRACKING_AUDIT_PLAN_CHANGE_DETECTED = "PLAN_CHANGE_DETECTED"
TRACKING_AUDIT_REVALIDATION_PASSED = "REVALIDATION_PASSED"
TRACKING_AUDIT_REVALIDATION_FAILED = "REVALIDATION_FAILED"
TRACKING_AUDIT_SUBMIT_STARTED = "SUBMIT_STARTED"
TRACKING_AUDIT_SUBMIT_SUCCEEDED = "SUBMIT_SUCCEEDED"
TRACKING_AUDIT_SUBMIT_FAILED = "SUBMIT_FAILED"
TRACKING_AUDIT_SUBMIT_OUTCOME_UNKNOWN = "SUBMIT_OUTCOME_UNKNOWN"
TRACKING_AUDIT_MANAGEMENT_STARTED = "MANAGEMENT_STARTED"
TRACKING_AUDIT_MANAGEMENT_SUCCEEDED = "MANAGEMENT_SUCCEEDED"
TRACKING_AUDIT_MANAGEMENT_FAILED = "MANAGEMENT_FAILED"
TRACKING_AUDIT_MANAGEMENT_UNKNOWN = "MANAGEMENT_UNKNOWN"
TRACKING_AUDIT_RESULT_PERSIST_FAILED = "RESULT_PERSIST_FAILED"
TRACKING_AUDIT_RECOVERY_AUTO_SUCCEEDED = "RECOVERY_AUTO_SUCCEEDED"
TRACKING_AUDIT_RECOVERY_AUTO_FAILED = "RECOVERY_AUTO_FAILED"
TRACKING_AUDIT_RECOVERY_NEEDS_MANUAL = "RECOVERY_NEEDS_MANUAL"
TRACKING_AUDIT_RECOVERY_MANUAL_SUCCEEDED = "RECOVERY_MANUAL_SUCCEEDED"
TRACKING_AUDIT_RECOVERY_MANUAL_FAILED = "RECOVERY_MANUAL_FAILED"
TRACKING_AUDIT_RECOVERY_EXTERNAL_VERIFIED = "RECOVERY_EXTERNAL_VERIFIED"
TRACKING_AUDIT_COMPAT_QUEUE_UPDATED = "COMPAT_QUEUE_UPDATED"
TRACKING_AUDIT_COMPAT_QUEUE_UPDATE_FAILED = "COMPAT_QUEUE_UPDATE_FAILED"
TRACKING_AUDIT_ACTIONS = frozenset(
    {
        TRACKING_AUDIT_TRACKING_CREATED,
        TRACKING_AUDIT_TRACKING_BACKFILLED,
        TRACKING_AUDIT_PLAN_CHANGE_DETECTED,
        TRACKING_AUDIT_REVALIDATION_PASSED,
        TRACKING_AUDIT_REVALIDATION_FAILED,
        TRACKING_AUDIT_SUBMIT_STARTED,
        TRACKING_AUDIT_SUBMIT_SUCCEEDED,
        TRACKING_AUDIT_SUBMIT_FAILED,
        TRACKING_AUDIT_SUBMIT_OUTCOME_UNKNOWN,
        TRACKING_AUDIT_MANAGEMENT_STARTED,
        TRACKING_AUDIT_MANAGEMENT_SUCCEEDED,
        TRACKING_AUDIT_MANAGEMENT_FAILED,
        TRACKING_AUDIT_MANAGEMENT_UNKNOWN,
        TRACKING_AUDIT_RESULT_PERSIST_FAILED,
        TRACKING_AUDIT_RECOVERY_AUTO_SUCCEEDED,
        TRACKING_AUDIT_RECOVERY_AUTO_FAILED,
        TRACKING_AUDIT_RECOVERY_NEEDS_MANUAL,
        TRACKING_AUDIT_RECOVERY_MANUAL_SUCCEEDED,
        TRACKING_AUDIT_RECOVERY_MANUAL_FAILED,
        TRACKING_AUDIT_RECOVERY_EXTERNAL_VERIFIED,
        TRACKING_AUDIT_COMPAT_QUEUE_UPDATED,
        TRACKING_AUDIT_COMPAT_QUEUE_UPDATE_FAILED,
    }
)

# -- schema whitelists -------------------------------------------------------
_TRACKING_RECORD_FIELDS = frozenset(
    {
        "schema_version",
        "tracking_id",
        "request_id",
        "batch_id",
        "origin",
        "status",
        "revision",
        "request_fingerprint",
        "plan_summary",
        "external_mapping",
        "current_operation_id",
        "last_error",
        "recovery",
        "audit_events",
        "created_at",
        "updated_at",
        "last_synced_at",
    }
)
_PLAN_SUMMARY_FIELDS = frozenset(
    {"title", "season", "subtitle_group", "poster_path"}
)
#: Tuple keeps last_error serialization order deterministic.
_LAST_ERROR_FIELDS = ("error_type", "reason_code", "safe_message")
_AUDIT_EVENT_FIELDS = frozenset(
    {
        "event_id",
        "action",
        "actor",
        "from_status",
        "to_status",
        "tracking_revision",
        "operation_id",
        "reason_code",
        "safe_message",
        "created_at",
    }
)
_EXTERNAL_MAPPING_FIELDS = frozenset(
    {
        "schema_version",
        "adapter",
        "subscription_id",
        "rss_ids",
        "match_reason",
        "external_deleted",
        "enabled",
        "missing_sync_count",
        "last_verified_at",
        "connection_ref",
    }
)
_EXTERNAL_MAPPING_LEGACY_FIELDS = frozenset(
    _EXTERNAL_MAPPING_FIELDS - {"connection_ref"}
)
_EXTERNAL_MATCH_REASONS = frozenset(
    {"EXTERNAL_ID", "EXACT_FIELDS", "EXTERNAL_ONLY"}
)
_OPAQUE_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~-]{0,127}$")

# Sensitive-key terms for the deep cleaner applied to future opaque objects.
_SENSITIVE_KEYS = frozenset(
    {
        "token",
        "secret",
        "cookie",
        "authorization",
        "password",
        "passwd",
        "bearer",
        "username",
        "sid",
        "session",
        "endpoint",
        "api_key",
        "apikey",
        "rss_url",
        "magnet",
        "response_body",
        "request_body",
        "raw",
        "credential",
        "headers",
    }
)
def tracking_id_for_request(request_id: str) -> str:
    """Return the deterministic opaque ``tracking_id`` for one ``request_id``.

    The namespace + digest algorithm is part of the storage contract and is
    frozen by tests: the same Request must always produce the same id across
    restarts, concurrent ``ensure``, terminal replays and migration.
    """
    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("request_id must be a non-empty string")
    clean = request_id.strip()
    digest = hashlib.sha256(f"migu-orca/tracking/v1\x00{clean}".encode()).hexdigest()
    return f"trk_{digest[:32]}"


def tracking_id_for_external(
    adapter: str, object_kind: str, external_id: str, connection_ref: str | UUID | None = None
) -> str:
    """Return the stable opaque id for one external object (D30-09)."""
    adapter = _require_opaque_token(adapter, "adapter")
    object_kind = _require_opaque_token(object_kind, "object_kind")
    external_id = _require_opaque_token(external_id, "external_id")
    clean_ref = _optional_connection_ref(connection_ref)
    if clean_ref is None:
        seed = f"migu-orca/tracking/external/v1\x00{adapter}\x00{object_kind}\x00{external_id}"
    else:
        seed = f"migu-orca/tracking/external/v2\x00connection\x00{clean_ref}\x00{adapter}\x00{object_kind}\x00{external_id}"
    digest = hashlib.sha256(seed.encode()).hexdigest()
    return f"trk_{digest[:32]}"


def tracking_status_group(status: str) -> str:
    """Return the user status group for a backend ``status`` (Stage 29 PRD §8.2)."""
    try:
        return TRACKING_STATUS_GROUPS[status]
    except KeyError as exc:
        raise ValueError(f"unknown tracking status: {status}") from exc


@dataclass(frozen=True)
class TrackingRecord:
    """One unified tracking record (Stage 29 PRD §7.2).

    Every value is non-sensitive and whitelisted.  ``plan_summary`` holds only
    public display fields; ``external_mapping``/``recovery`` are future opaque
    objects that are deep-cleaned before they are ever persisted.
    """

    schema_version: int = TRACKING_SCHEMA_VERSION
    tracking_id: str = ""
    request_id: str | None = None
    batch_id: str | None = None
    origin: str = TRACKING_ORIGIN_SAVE_CONFIRM
    status: str = TRACKING_STATUS_PENDING_SUBMIT
    revision: int = 1
    request_fingerprint: str | None = None
    plan_summary: dict[str, Any] = field(default_factory=dict)
    external_mapping: dict[str, Any] | None = None
    current_operation_id: str | None = None
    last_error: dict[str, Any] | None = None
    recovery: dict[str, Any] | None = None
    audit_events: list[dict[str, Any]] = field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None
    last_synced_at: str | None = None


def build_audit_event(
    *,
    action: str,
    actor: str,
    from_status: str | None,
    to_status: str | None,
    tracking_revision: int,
    operation_id: str | None = None,
    reason_code: str | None = None,
    safe_message: str | None = None,
    event_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build one safe audit event (Stage 29 PRD §9).

    ``safe_message`` must already be a sanitized one-line message; the event
    never stores AB config, endpoint, credentials, request/response bodies,
    full URLs, magnets, absolute paths or upstream raw error text.
    """
    if action not in TRACKING_AUDIT_ACTIONS:
        raise ValueError(f"unknown tracking audit action: {action}")
    if actor not in TRACKING_AUDIT_ACTORS:
        raise ValueError(f"unknown tracking audit actor: {actor}")
    if not isinstance(tracking_revision, int) or tracking_revision < 1:
        raise ValueError("audit tracking_revision must be a positive integer")
    return {
        "event_id": event_id or f"evt_{uuid4().hex}",
        "action": action,
        "actor": actor,
        "from_status": from_status,
        "to_status": to_status,
        "tracking_revision": tracking_revision,
        "operation_id": operation_id,
        "reason_code": reason_code,
        "safe_message": safe_message,
        "created_at": created_at or utc_now(),
    }


def append_audit_event(record: TrackingRecord, event: dict[str, Any]) -> TrackingRecord:
    """Return ``record`` with ``event`` appended (the audit list is immutable)."""
    return replace(record, audit_events=[*record.audit_events, _clean_audit_event(event)])


def create_tracking_record(
    *,
    request_id: str,
    status: str,
    plan_summary: dict[str, Any],
    origin: str = TRACKING_ORIGIN_SAVE_CONFIRM,
    batch_id: str | None = None,
    request_fingerprint: str | None = None,
    audit_action: str = TRACKING_AUDIT_TRACKING_CREATED,
    audit_actor: str = TRACKING_AUDIT_ACTOR_USER,
    audit_message: str | None = None,
    now: str | None = None,
) -> TrackingRecord:
    """Create a fresh revision-1 record with its initial audit event embedded.

    ``request_id`` must be a non-empty public Request id; the ``tracking_id``
    is derived deterministically (D29-02/D29-03).  The initial audit event is
    written atomically with the record on the first ``ensure``.
    """
    clean_request_id = _require_request_id(request_id)
    if status not in TRACKING_STATUSES:
        raise ValueError(f"unknown tracking status: {status}")
    if origin not in TRACKING_ORIGINS:
        raise ValueError(f"unknown tracking origin: {origin}")
    timestamp = now or utc_now()
    record = TrackingRecord(
        schema_version=TRACKING_SCHEMA_VERSION,
        tracking_id=tracking_id_for_request(clean_request_id),
        request_id=clean_request_id,
        batch_id=batch_id,
        origin=origin,
        status=status,
        revision=1,
        request_fingerprint=request_fingerprint,
        plan_summary=_clean_plan_summary(plan_summary),
        created_at=timestamp,
        updated_at=timestamp,
    )
    event = build_audit_event(
        action=audit_action,
        actor=audit_actor,
        from_status=None,
        to_status=status,
        tracking_revision=1,
        safe_message=audit_message,
        created_at=timestamp,
    )
    return append_audit_event(record, event)


def create_external_tracking_record(
    *,
    adapter: str,
    object_kind: str,
    external_id: str,
    title: str | None = None,
    season: int | None = None,
    subtitle_group: str | None = None,
    subscription_id: str | None = None,
    rss_ids: list[str] | tuple[str, ...] = (),
    match_reason: str = "EXTERNAL_ONLY",
    external_deleted: bool = False,
    enabled: bool = True,
    missing_sync_count: int = 0,
    last_verified_at: str | None = None,
    connection_ref: str | UUID | None = None,
    now: str | None = None,
) -> TrackingRecord:
    """Create an external-only record without fabricating a Request.

    ``external_id`` is used only to derive the deterministic record id and is
    intentionally not persisted separately; the mapping stores the opaque
    subscription id and RSS ids supplied by the read adapter.
    """
    adapter = _require_opaque_token(adapter, "adapter")
    object_kind = _require_opaque_token(object_kind, "object_kind")
    external_id = _require_opaque_token(external_id, "external_id")
    clean_connection_ref = _optional_connection_ref(connection_ref)
    mapping_payload: dict[str, Any] = {
        "schema_version": (
            EXTERNAL_MAPPING_SCHEMA_VERSION
            if clean_connection_ref is not None
            else EXTERNAL_MAPPING_LEGACY_SCHEMA_VERSION
        ),
        "adapter": adapter,
        "subscription_id": subscription_id,
        "rss_ids": list(rss_ids),
        "match_reason": match_reason,
        "external_deleted": external_deleted,
        "enabled": enabled,
        "missing_sync_count": missing_sync_count,
        "last_verified_at": last_verified_at,
    }
    if clean_connection_ref is not None:
        mapping_payload["connection_ref"] = clean_connection_ref
    mapping = _clean_external_mapping(mapping_payload)
    timestamp = now or utc_now()
    status = TRACKING_STATUS_EXTERNAL_DELETED if external_deleted else TRACKING_STATUS_EXTERNAL_ONLY
    record = TrackingRecord(
        tracking_id=tracking_id_for_external(adapter, object_kind, external_id, clean_connection_ref),
        request_id=None,
        origin=TRACKING_ORIGIN_EXTERNAL_SYNC,
        status=status,
        plan_summary=_clean_external_plan_summary(title, season, subtitle_group),
        external_mapping=mapping,
        created_at=timestamp,
        updated_at=timestamp,
        last_synced_at=last_verified_at,
    )
    return append_audit_event(
        record,
        build_audit_event(
            action=TRACKING_AUDIT_TRACKING_CREATED,
            actor=TRACKING_AUDIT_ACTOR_SYSTEM,
            from_status=None,
            to_status=status,
            tracking_revision=1,
            safe_message="外部同步创建追番记录",
            created_at=timestamp,
        ),
    )


def transition_record(
    record: TrackingRecord,
    *,
    status: str,
    audit_action: str,
    audit_actor: str = TRACKING_AUDIT_ACTOR_SYSTEM,
    operation_id: str | None = None,
    reason_code: str | None = None,
    safe_message: str | None = None,
    now: str | None = None,
) -> TrackingRecord:
    """Return a new record for a status change with ``revision + 1``.

    The audit event is embedded in the same returned record so the caller can
    persist status + audit + revision atomically through one CAS write
    (D29-05).  Every status change must increment ``revision`` by exactly one.
    """
    if status not in TRACKING_STATUSES:
        raise ValueError(f"unknown tracking status: {status}")
    next_revision = record.revision + 1
    timestamp = now or utc_now()
    updated = replace(
        record,
        status=status,
        revision=next_revision,
        updated_at=timestamp,
    )
    event = build_audit_event(
        action=audit_action,
        actor=audit_actor,
        from_status=record.status,
        to_status=status,
        tracking_revision=next_revision,
        operation_id=operation_id,
        reason_code=reason_code,
        safe_message=safe_message,
        created_at=timestamp,
    )
    return append_audit_event(updated, event)


def tracking_to_storage_dict(record: TrackingRecord) -> dict[str, Any]:
    """Serialize a record for persistence.

    The writer emits exactly the top-level whitelist and normalizes every
    nested object, so an accidental sensitive field (or an unknown nested key)
    can never reach disk.
    """
    return {
        "schema_version": TRACKING_SCHEMA_VERSION,
        "tracking_id": record.tracking_id,
        "request_id": record.request_id,
        "batch_id": record.batch_id,
        "origin": record.origin,
        "status": record.status,
        "revision": record.revision,
        "request_fingerprint": record.request_fingerprint,
        "plan_summary": _clean_plan_summary(record.plan_summary),
        "external_mapping": _serialize_external_mapping(record.external_mapping),
        "current_operation_id": record.current_operation_id,
        "last_error": _clean_last_error(record.last_error),
        "recovery": _clean_opaque_value(record.recovery),
        "audit_events": [_clean_audit_event(event) for event in record.audit_events],
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "last_synced_at": record.last_synced_at,
    }


def tracking_from_storage_dict(data: Any) -> TrackingRecord:
    """Reconstruct a record from a storage dict (fail-closed schema validation).

    Unknown top-level fields, an unknown ``schema_version``, invalid status/
    origin/enum values, missing required fields, and type mismatches all raise
    ``ValueError`` so the repository maps them to a stable storage error.  A
    Request-backed record must have ``tracking_id`` equal to the deterministic
    id derived from its ``request_id``.
    """
    if not isinstance(data, dict):
        raise ValueError("tracking record JSON must be an object")
    unknown = sorted(set(data) - _TRACKING_RECORD_FIELDS)
    if unknown:
        raise ValueError(f"unknown tracking record fields: {', '.join(unknown)}")

    schema_version = data.get("schema_version")
    if schema_version != TRACKING_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported tracking schema_version: {schema_version!r}"
        )

    tracking_id = _require_non_empty_str(data.get("tracking_id"), "tracking_id")
    request_id = _optional_str(data.get("request_id"), "request_id")
    if request_id is not None:
        expected = tracking_id_for_request(request_id)
        if tracking_id != expected:
            raise ValueError(
                f"tracking_id does not match request_id-derived id: {tracking_id}"
            )

    origin = data.get("origin")
    if origin not in TRACKING_ORIGINS:
        raise ValueError(f"invalid tracking origin: {origin!r}")
    status = data.get("status")
    if status not in TRACKING_STATUSES:
        raise ValueError(f"invalid tracking status: {status!r}")
    revision = data.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ValueError("tracking revision must be a positive integer")

    created_at = _require_non_empty_str(data.get("created_at"), "created_at")
    updated_at = _require_non_empty_str(data.get("updated_at"), "updated_at")

    return TrackingRecord(
        schema_version=TRACKING_SCHEMA_VERSION,
        tracking_id=tracking_id,
        request_id=request_id,
        batch_id=_optional_str(data.get("batch_id"), "batch_id"),
        origin=origin,
        status=status,
        revision=revision,
        request_fingerprint=_optional_str(
            data.get("request_fingerprint"), "request_fingerprint"
        ),
        plan_summary=_clean_plan_summary(_require_dict(data.get("plan_summary"), "plan_summary")),
        external_mapping=_read_external_mapping(data.get("external_mapping")),
        current_operation_id=_optional_str(
            data.get("current_operation_id"), "current_operation_id"
        ),
        last_error=_clean_last_error(_optional_dict(data.get("last_error"), "last_error")),
        recovery=_optional_dict(data.get("recovery"), "recovery"),
        audit_events=_clean_audit_events(data.get("audit_events")),
        created_at=created_at,
        updated_at=updated_at,
        last_synced_at=_optional_str(data.get("last_synced_at"), "last_synced_at"),
    )


# -- nested cleaning ---------------------------------------------------------


#: The only poster reference a tracking summary may carry: a same-origin opaque
#: proxy route. Upstream image URLs, absolute paths and traversal shapes are
#: never valid references, whatever the source snapshot held.
TRACKING_POSTER_PATH_RE = re.compile(r"^/api/v1/mikan/posters/[A-Za-z0-9_.-]+$")


def safe_poster_path(value: Any) -> str | None:
    """Return a trimmed same-origin opaque poster route, otherwise ``None``."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or not TRACKING_POSTER_PATH_RE.fullmatch(candidate):
        return None
    return candidate


def _clean_plan_summary(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("plan_summary must be an object")
    unknown = sorted(set(value) - _PLAN_SUMMARY_FIELDS)
    if unknown:
        raise ValueError(f"unknown plan_summary fields: {', '.join(unknown)}")
    cleaned: dict[str, Any] = {}
    title = value.get("title")
    if title is not None:
        if not isinstance(title, str):
            raise ValueError("plan_summary.title must be a string")
        cleaned["title"] = title
    season = value.get("season")
    if season is not None:
        if not isinstance(season, int) or isinstance(season, bool):
            raise ValueError("plan_summary.season must be an integer or null")
        cleaned["season"] = season
    subtitle_group = value.get("subtitle_group")
    if subtitle_group is not None:
        if not isinstance(subtitle_group, str):
            raise ValueError("plan_summary.subtitle_group must be a string")
        cleaned["subtitle_group"] = subtitle_group
    poster_path = value.get("poster_path")
    if poster_path is not None:
        if not isinstance(poster_path, str):
            raise ValueError("plan_summary.poster_path must be a string")
        cleaned["poster_path"] = poster_path
    return cleaned


def _clean_external_plan_summary(
    title: str | None, season: int | None, subtitle_group: str | None
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, value in (("title", title), ("subtitle_group", subtitle_group)):
        if value is not None:
            if not isinstance(value, str):
                raise ValueError(f"{key} must be a string or null")
            safe = redact_sensitive_text(value).strip()[:256]
            if safe:
                values[key] = safe
    if season is not None:
        if not isinstance(season, int) or isinstance(season, bool):
            raise ValueError("season must be an integer or null")
        values["season"] = season
    values["poster_path"] = None
    return _clean_plan_summary(values)


def _require_opaque_token(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an opaque string")
    value = value.strip()
    if not _OPAQUE_TOKEN_RE.fullmatch(value) or len(value) > EXTERNAL_OPAQUE_TOKEN_MAX_LENGTH:
        raise ValueError(f"{name} must be a bounded opaque token")
    return value


def _optional_connection_ref(value: Any) -> str | None:
    """Normalize the deployment connection UUID without storing credentials."""
    if value is None:
        return None
    if isinstance(value, UUID):
        return str(value)
    if not isinstance(value, str):
        raise ValueError("connection_ref must be a canonical UUID")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        raise ValueError("connection_ref must be a canonical UUID") from None
    if str(parsed) != value:
        raise ValueError("connection_ref must be a canonical UUID")
    return value


def _clean_external_mapping(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("external_mapping must be an object or null")
    schema_version = value.get("schema_version")
    if type(schema_version) is not int:
        raise ValueError("external_mapping schema_version must be an integer")
    allowed_fields = (
        _EXTERNAL_MAPPING_LEGACY_FIELDS
        if schema_version == EXTERNAL_MAPPING_LEGACY_SCHEMA_VERSION
        else _EXTERNAL_MAPPING_FIELDS
    )
    unknown = sorted(set(value) - allowed_fields)
    if unknown:
        raise ValueError(f"unknown external_mapping fields: {', '.join(unknown)}")
    if schema_version not in {
        EXTERNAL_MAPPING_LEGACY_SCHEMA_VERSION,
        EXTERNAL_MAPPING_SCHEMA_VERSION,
    }:
        raise ValueError("unsupported external_mapping schema_version")
    connection_ref = (
        _optional_connection_ref(value.get("connection_ref"))
        if schema_version == EXTERNAL_MAPPING_SCHEMA_VERSION
        else None
    )
    if schema_version == EXTERNAL_MAPPING_SCHEMA_VERSION and connection_ref is None:
        raise ValueError("external_mapping.connection_ref is required")
    adapter = _require_opaque_token(value.get("adapter"), "external_mapping.adapter")
    subscription_id = value.get("subscription_id")
    if subscription_id is not None:
        subscription_id = _require_opaque_token(subscription_id, "external_mapping.subscription_id")
    rss_ids = value.get("rss_ids")
    if not isinstance(rss_ids, list) or len(rss_ids) > EXTERNAL_MAPPING_MAX_RSS_IDS:
        raise ValueError("external_mapping.rss_ids must be a bounded list")
    normalized_rss_ids: list[str] = []
    for item in rss_ids:
        item = _require_opaque_token(item, "external_mapping.rss_ids")
        if item not in normalized_rss_ids:
            normalized_rss_ids.append(item)
    match_reason = value.get("match_reason")
    if match_reason not in _EXTERNAL_MATCH_REASONS:
        raise ValueError("invalid external_mapping.match_reason")
    for key in ("external_deleted", "enabled"):
        if not isinstance(value.get(key), bool):
            raise ValueError(f"external_mapping.{key} must be boolean")
    missing = value.get("missing_sync_count")
    if not isinstance(missing, int) or isinstance(missing, bool) or not 0 <= missing <= 1_000_000:
        raise ValueError("external_mapping.missing_sync_count must be bounded")
    verified = _optional_str(value.get("last_verified_at"), "external_mapping.last_verified_at")
    cleaned = {
        "schema_version": schema_version,
        "adapter": adapter,
        "subscription_id": subscription_id,
        "rss_ids": normalized_rss_ids,
        "match_reason": match_reason,
        "external_deleted": value["external_deleted"],
        "enabled": value["enabled"],
        "missing_sync_count": missing,
        "last_verified_at": verified,
    }
    if connection_ref is not None:
        cleaned["connection_ref"] = connection_ref
    return cleaned


def _read_external_mapping(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("external_mapping must be an object or null")
    # Stage 29 allowed an opaque future object. Preserve it safely until a
    # sync operation has enough evidence to replace it with mapping v1.
    if "schema_version" not in value:
        return _clean_opaque_value(value)
    return _clean_external_mapping(value)


def _serialize_external_mapping(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict) and "schema_version" in value:
        return _clean_external_mapping(value)
    return _clean_opaque_value(value)


def _clean_last_error(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("last_error must be an object or null")
    unknown = sorted(set(value) - set(_LAST_ERROR_FIELDS))
    if unknown:
        raise ValueError(f"unknown last_error fields: {', '.join(unknown)}")
    return {key: value[key] for key in _LAST_ERROR_FIELDS if value.get(key) is not None}


def _clean_audit_events(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("audit_events must be a list")
    return [_clean_audit_event(event) for event in value]


def _clean_audit_event(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("audit event must be an object")
    unknown = sorted(set(value) - _AUDIT_EVENT_FIELDS)
    if unknown:
        raise ValueError(f"unknown audit event fields: {', '.join(unknown)}")
    action = value.get("action")
    if action not in TRACKING_AUDIT_ACTIONS:
        raise ValueError(f"invalid audit action: {action!r}")
    actor = value.get("actor")
    if actor not in TRACKING_AUDIT_ACTORS:
        raise ValueError(f"invalid audit actor: {actor!r}")
    revision = value.get("tracking_revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ValueError("audit tracking_revision must be a positive integer")
    event_id = _require_non_empty_str(value.get("event_id"), "event_id")
    created_at = _require_non_empty_str(value.get("created_at"), "created_at")
    return {
        "event_id": event_id,
        "action": action,
        "actor": actor,
        "from_status": _optional_str(value.get("from_status"), "from_status"),
        "to_status": _optional_str(value.get("to_status"), "to_status"),
        "tracking_revision": revision,
        "operation_id": _optional_str(value.get("operation_id"), "operation_id"),
        "reason_code": _optional_str(value.get("reason_code"), "reason_code"),
        "safe_message": _optional_str(value.get("safe_message"), "safe_message"),
        "created_at": created_at,
    }


def _clean_opaque_value(value: Any) -> Any:
    """Deep-clean a future opaque object (external_mapping/recovery).

    Drops dict keys whose names look sensitive and redacts URL/magnet/
    absolute-path/token-like strings so an accidental sensitive value can never
    persist even inside a B-C-shaped object.
    """
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if any(term in key_text.lower() for term in _SENSITIVE_KEYS):
                continue
            cleaned_value = _clean_opaque_value(item)
            if cleaned_value is not None:
                cleaned[key_text] = cleaned_value
        return cleaned or None
    if isinstance(value, list):
        items = [_clean_opaque_value(item) for item in value]
        items = [item for item in items if item is not None]
        return items or None
    if isinstance(value, str):
        return redact_sensitive_text(value) or None
    return value


def _require_request_id(request_id: str) -> str:
    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("request_id must be a non-empty string")
    return request_id.strip()


def _require_non_empty_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _optional_str(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string or null")
    return value


def _optional_dict(value: Any, name: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object or null")
    return dict(value)


def _require_dict(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


__all__ = [
    "B_B_TRACKING_STATUSES",
    "TRACKING_AUDIT_ACTIONS",
    "TRACKING_AUDIT_ACTOR_MIGRATION",
    "TRACKING_AUDIT_ACTOR_SYSTEM",
    "TRACKING_AUDIT_ACTOR_USER",
    "TRACKING_AUDIT_ACTORS",
    "TRACKING_AUDIT_COMPAT_QUEUE_UPDATED",
    "TRACKING_AUDIT_COMPAT_QUEUE_UPDATE_FAILED",
    "TRACKING_AUDIT_PLAN_CHANGE_DETECTED",
    "TRACKING_AUDIT_RECOVERY_AUTO_FAILED",
    "TRACKING_AUDIT_RECOVERY_AUTO_SUCCEEDED",
    "TRACKING_AUDIT_RECOVERY_MANUAL_FAILED",
    "TRACKING_AUDIT_RECOVERY_EXTERNAL_VERIFIED",
    "TRACKING_AUDIT_RECOVERY_MANUAL_SUCCEEDED",
    "TRACKING_AUDIT_RECOVERY_NEEDS_MANUAL",
    "TRACKING_AUDIT_REVALIDATION_FAILED",
    "TRACKING_AUDIT_REVALIDATION_PASSED",
    "TRACKING_AUDIT_RESULT_PERSIST_FAILED",
    "TRACKING_AUDIT_SUBMIT_FAILED",
    "TRACKING_AUDIT_SUBMIT_OUTCOME_UNKNOWN",
    "TRACKING_AUDIT_SUBMIT_STARTED",
    "TRACKING_AUDIT_SUBMIT_SUCCEEDED",
    "TRACKING_AUDIT_TRACKING_BACKFILLED",
    "TRACKING_AUDIT_TRACKING_CREATED",
    "TRACKING_ORIGINS",
    "TRACKING_ORIGIN_LEGACY_ACCEPT",
    "TRACKING_ORIGIN_MIGRATED_AB_RESULT",
    "TRACKING_ORIGIN_EXTERNAL_SYNC",
    "EXTERNAL_MAPPING_SCHEMA_VERSION",
    "EXTERNAL_MAPPING_LEGACY_SCHEMA_VERSION",
    "EXTERNAL_MAPPING_MAX_RSS_IDS",
    "tracking_id_for_external",
    "create_external_tracking_record",
    "TRACKING_ORIGIN_MIGRATED_QUEUE",
    "TRACKING_ORIGIN_SAVE_CONFIRM",
    "TRACKING_SCHEMA_VERSION",
    "TRACKING_STATUSES",
    "TRACKING_STATUS_GROUPS",
    "TRACKING_STATUS_GROUP_ACTIVE",
    "TRACKING_STATUS_GROUP_ATTENTION",
    "TRACKING_STATUS_GROUP_INACTIVE",
    "TRACKING_STATUS_GROUP_LABELS",
    "TRACKING_STATUS_GROUP_PENDING",
    "TRACKING_STATUS_GROUP_PROCESSING",
    "TRACKING_STATUS_ACTIVE",
    "TRACKING_STATUS_ADDED_TO_DOWNLOAD",
    "TRACKING_STATUS_DISABLED",
    "TRACKING_STATUS_EXTERNAL_DELETED",
    "TRACKING_STATUS_EXTERNAL_ONLY",
    "TRACKING_STATUS_LABELS",
    "TRACKING_STATUS_NEEDS_RECONFIRM",
    "TRACKING_STATUS_PENDING_SUBMIT",
    "TRACKING_STATUS_RECOVERY_REQUIRED",
    "TRACKING_STATUS_REVALIDATING",
    "TRACKING_STATUS_SUBMIT_FAILED",
    "TRACKING_STATUS_SUBMITTING",
    "TRACKING_STATUS_UNKNOWN",
    "TRACKING_STATUS_VERIFYING_EXTERNAL",
    "TRACKING_POSTER_PATH_RE",
    "TrackingRecord",
    "append_audit_event",
    "build_audit_event",
    "create_tracking_record",
    "safe_poster_path",
    "tracking_from_storage_dict",
    "tracking_id_for_request",
    "tracking_status_group",
    "tracking_to_storage_dict",
    "transition_record",
    "utc_now",
]
