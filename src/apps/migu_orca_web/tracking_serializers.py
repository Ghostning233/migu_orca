from __future__ import annotations

"""Safe read serializers for the unified tracking list/detail (US-223).

This module owns the *public representation* of a TrackingRecord.  Every value
is whitelisted and scrubbed at the boundary:

- free-text display labels (title / subtitle group) go through the same safe
  label scrubber the Request safe-info serializer uses, so a poisoned stored
  value cannot smuggle a URL/magnet/path into the response;
- ``poster_path`` is echoed only when it is a strict same-origin opaque poster
  route (``/api/v1/mikan/posters/<opaque-key>``), never an arbitrary string;
- ``available_actions`` is computed server-side from the tracking status and
  only ever contains currently-executable actions (Stage 29 PRD §11.4) — the
  frontend never infers action permissions.
"""

import re
from typing import Any

from apps.migu_orca_web.serializers import _safe_label
from tracking_engine.models.operation import TrackingOperation
from tracking_engine.models.tracking import (
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_DISABLED,
    TRACKING_STATUS_LABELS,
    TRACKING_STATUS_NEEDS_RECONFIRM,
    TRACKING_STATUS_PENDING_SUBMIT,
    TRACKING_STATUS_RECOVERY_REQUIRED,
    TRACKING_STATUS_SUBMIT_FAILED,
    TRACKING_STATUS_UNKNOWN,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
    TrackingRecord,
    tracking_status_group,
)

#: Strict same-origin opaque poster route the record may reference.
_POSTER_PATH_RE = re.compile(r"^/api/v1/mikan/posters/[A-Za-z0-9_.-]+$")

#: Action styles (Stage 29 PRD §11.4).
_STYLE_PRIMARY = "PRIMARY"
_STYLE_SECONDARY = "SECONDARY"
_STYLE_DANGER = "DANGER"


def tracking_available_actions(status: str) -> list[dict[str, Any]]:
    """Return the currently-executable action objects for ``status``.

    Only actions the unified submit/retry/recover endpoints can actually
    execute for the state are returned (Stage 29 PRD §8.2/§11.4).  The
    frontend must never infer these itself; a state with no executable action
    (``REVALIDATING``/``SUBMITTING``/``ACTIVE`` and the B-C reserved inactive
    states) returns an empty list.
    """
    actions: list[dict[str, Any]] = []
    if status in {TRACKING_STATUS_PENDING_SUBMIT, TRACKING_STATUS_NEEDS_RECONFIRM}:
        actions.append(
            _action("REVALIDATE", "重新复核", _STYLE_SECONDARY, requires_confirmation=False)
        )
        actions.append(_action("SUBMIT", "提交追番", _STYLE_PRIMARY, requires_confirmation=True))
    elif status == TRACKING_STATUS_SUBMIT_FAILED:
        actions.append(
            _action("REVALIDATE", "重新复核", _STYLE_SECONDARY, requires_confirmation=False)
        )
        actions.append(_action("RETRY", "重试提交", _STYLE_PRIMARY, requires_confirmation=True))
    elif status in {
        TRACKING_STATUS_VERIFYING_EXTERNAL,
        TRACKING_STATUS_RECOVERY_REQUIRED,
        TRACKING_STATUS_UNKNOWN,
    }:
        actions.append(
            _action("RECOVER_AUTO", "自动恢复", _STYLE_SECONDARY, requires_confirmation=False)
        )
        actions.append(
            _action("MARK_SUCCEEDED", "标记为成功", _STYLE_PRIMARY, requires_confirmation=True)
        )
        actions.append(
            _action("MARK_FAILED", "标记为失败", _STYLE_DANGER, requires_confirmation=True)
        )
    elif status == TRACKING_STATUS_ACTIVE:
        actions.extend([
            _action("MODIFY", "修改外部订阅", _STYLE_SECONDARY, requires_confirmation=True),
            _action("SET_ENABLED", "停用外部订阅", _STYLE_SECONDARY, requires_confirmation=True),
            _action("REFRESH_RSS", "刷新关联 RSS", _STYLE_SECONDARY, requires_confirmation=True),
            _action("DELETE_EXTERNAL", "删除外部订阅", _STYLE_DANGER, requires_confirmation=True),
        ])
    elif status == TRACKING_STATUS_DISABLED:
        actions.extend([
            _action("SET_ENABLED", "启用外部订阅", _STYLE_PRIMARY, requires_confirmation=True),
            _action("DELETE_EXTERNAL", "删除外部订阅", _STYLE_DANGER, requires_confirmation=True),
        ])
    # REVALIDATING / SUBMITTING / EXTERNAL_DELETED / EXTERNAL_ONLY have no
    # currently-executable state-changing action.
    return actions


def tracking_summary_fields(
    record: TrackingRecord,
    *,
    valid_resource_count: int = 0,
) -> dict[str, Any]:
    """Build the shared safe summary fields for a list item / detail.

    Reads only the record's whitelisted non-sensitive display fields; free-text
    labels are scrubbed and ``poster_path`` must match the same-origin poster
    route.  ``updated_episode`` is always null and ``updated_episode_status``
    always NOT_IMPLEMENTED (BL-020 out of scope).
    """
    plan = record.plan_summary if isinstance(record.plan_summary, dict) else {}
    season = plan.get("season")
    if not isinstance(season, int) or isinstance(season, bool):
        season = None
    return {
        "tracking_id": record.tracking_id,
        "request_id": record.request_id,
        "title": _safe_label(plan.get("title")),
        "season": season,
        "subtitle_group": _safe_label(plan.get("subtitle_group")),
        "poster_path": _safe_poster_path(plan.get("poster_path")),
        "status": record.status,
        "status_label": TRACKING_STATUS_LABELS.get(record.status, record.status),
        "status_group": tracking_status_group(record.status),
        "available_actions": tracking_available_actions(record.status),
        "valid_resource_count": _non_negative_count(valid_resource_count),
        "updated_episode": None,
        "updated_episode_status": "NOT_IMPLEMENTED",
        "total_episodes": None,
        "revision": record.revision,
        "updated_at": record.updated_at,
    }


def serialize_tracking_external_summary(mapping: dict[str, Any] | None) -> dict[str, Any] | None:
    """Project ExternalMapping v1 without exposing opaque external IDs."""
    if not isinstance(mapping, dict):
        return None
    missing = mapping.get("missing_sync_count", 0)
    return {
        "match_reason": mapping.get("match_reason") if isinstance(mapping.get("match_reason"), str) else None,
        "external_deleted": mapping.get("external_deleted") is True,
        "enabled": mapping.get("enabled") is True,
        "missing_sync_count": missing if isinstance(missing, int) and not isinstance(missing, bool) and missing >= 0 else 0,
        "last_verified_at": mapping.get("last_verified_at") if isinstance(mapping.get("last_verified_at"), str) else None,
    }


def serialize_tracking_operation_summary(
    operation: TrackingOperation,
) -> dict[str, Any]:
    """Return the safe public summary of one TrackingOperation.

    Never exposes the idempotency binding, expected revision, request
    fingerprint, request body, AB config or upstream response.
    """
    return {
        "operation_id": operation.operation_id,
        "operation": operation.operation,
        "state": operation.state,
        "attempt": operation.attempt,
        "external_result_id": operation.external_result_id,
        "error_type": operation.error_type,
        "created_at": operation.created_at,
        "updated_at": operation.updated_at,
        "completed_at": operation.completed_at,
    }


def serialize_tracking_audit_events(
    events: list[dict[str, Any]],
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return the most recent ``limit`` audit events in chronological order.

    The stored events are already the fixed safe §9 shape; only the last
    ``limit`` events are serialized (Stage 29 never truncates the record but the
    detail view exposes the recent window).
    """
    if not isinstance(events, list):
        return []
    recent = events[-limit:]
    serialized: list[dict[str, Any]] = []
    for event in recent:
        if not isinstance(event, dict):
            continue
        serialized.append(
            {
                "event_id": _optional_str(event.get("event_id")),
                "action": _optional_str(event.get("action")),
                "actor": _optional_str(event.get("actor")),
                "from_status": _optional_str(event.get("from_status")),
                "to_status": _optional_str(event.get("to_status")),
                "tracking_revision": (
                    event.get("tracking_revision")
                    if isinstance(event.get("tracking_revision"), int)
                    and not isinstance(event.get("tracking_revision"), bool)
                    else 0
                ),
                "operation_id": _optional_str(event.get("operation_id")),
                "reason_code": _optional_str(event.get("reason_code")),
                "safe_message": _optional_str(event.get("safe_message")),
                "created_at": _optional_str(event.get("created_at")),
            }
        )
    return serialized


def _action(code: str, label: str, style: str, *, requires_confirmation: bool) -> dict[str, Any]:
    return {
        "code": code,
        "label": label,
        "style": style,
        "requires_confirmation": requires_confirmation,
    }


def _safe_poster_path(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or not _POSTER_PATH_RE.fullmatch(candidate):
        return None
    return candidate


def _optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _non_negative_count(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


__all__ = [
    "serialize_tracking_audit_events",
    "serialize_tracking_external_summary",
    "serialize_tracking_operation_summary",
    "tracking_available_actions",
    "tracking_summary_fields",
]
