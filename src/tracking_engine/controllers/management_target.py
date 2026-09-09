"""Pure target resolution and safe patch construction for management writes.

The functions in this module deliberately accept an already-read external
snapshot.  They do not know about HTTP, storage, or web DTOs; callers keep the
resolved IDs and complete upstream objects request-scoped and persist only the
fingerprints returned by :func:`build_management_binding`.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from ab_engine.models.management import ExternalRss, ExternalSubscription
from shared.errors import Stage1Error
from tracking_engine.controllers.management_operation import canonical_management_fingerprint
from tracking_engine.models.tracking import TrackingRecord

TargetScope = Literal["SUBSCRIPTION", "ASSOCIATED_RSS"]

SUBSCRIPTION_PATCH_FIELDS = frozenset(
    {"title", "season", "subtitle_group", "filter_rule", "offset", "expected_folder_name"}
)
RSS_PATCH_FIELDS = frozenset({"name", "aggregate", "parser"})
_FILTER_FIELDS = frozenset({"must_contain", "must_not_contain", "use_regex", "case_sensitive"})
_TEXT_FIELDS = frozenset({"title", "subtitle_group", "expected_folder_name", "name", "parser"})
_URL_RE = re.compile(r"(?:https?|ftp|file):[/\\/]|(?:^|\s)www\.", re.IGNORECASE)
_ABSOLUTE_PATH_RE = re.compile(r"^(?:/|[A-Za-z]:[\\/]|\\\\)")


@dataclass(frozen=True, repr=False)
class ResolvedManagementTarget:
    """A request-scoped target; its representation never includes external IDs."""

    scope: TargetScope
    subscription: ExternalSubscription | None = None
    rss: tuple[ExternalRss, ...] = ()

    def __repr__(self) -> str:
        return f"ResolvedManagementTarget(scope={self.scope!r}, rss_count={len(self.rss)!r})"


@dataclass(frozen=True)
class ManagementBinding:
    """Only safe digests cross the durable-operation boundary."""

    action_fingerprint: str
    expected_external_fingerprint: str


def resolve_management_target(
    record: TrackingRecord,
    scope: str,
    subscriptions: Sequence[ExternalSubscription],
    rss_items: Sequence[ExternalRss],
) -> ResolvedManagementTarget:
    """Resolve a public scope through the record's current mapping exactly once."""
    if scope not in {"SUBSCRIPTION", "ASSOCIATED_RSS"}:
        raise _invalid("invalid_management_scope")
    mapping = record.external_mapping
    if not isinstance(mapping, Mapping):
        raise _invalid("tracking_mapping_missing")

    if scope == "SUBSCRIPTION":
        external_id = mapping.get("subscription_id")
        if not isinstance(external_id, str) or not external_id:
            raise _invalid("tracking_target_missing")
        matches = [item for item in subscriptions if item.external_id == external_id and not item.deleted]
        if len(matches) != 1:
            raise _invalid("tracking_target_ambiguous" if len(matches) > 1 else "tracking_target_drift")
        return ResolvedManagementTarget(scope="SUBSCRIPTION", subscription=matches[0])

    raw_ids = mapping.get("rss_ids")
    if not isinstance(raw_ids, (list, tuple)) or not raw_ids:
        raise _invalid("tracking_target_missing")
    ids = tuple(item for item in raw_ids if isinstance(item, str) and item)
    if len(ids) != len(raw_ids) or len(set(ids)) != len(ids):
        raise _invalid("tracking_target_drift")
    matches = [item for item in rss_items if item.external_id in ids]
    if len(matches) != len(ids) or len({item.external_id for item in matches}) != len(ids):
        raise _invalid("tracking_target_drift")
    ordered = tuple(sorted(matches, key=lambda item: _rss_sort_key(item.external_id)))
    return ResolvedManagementTarget(scope="ASSOCIATED_RSS", rss=ordered)


def build_management_patch(scope: str, patch: Any) -> dict[str, Any]:
    """Validate and deep-normalize the public business patch."""
    if scope not in {"SUBSCRIPTION", "ASSOCIATED_RSS"} or not isinstance(patch, Mapping):
        raise _invalid("invalid_management_patch")
    if not patch:
        raise _invalid("empty_management_patch")
    allowed = SUBSCRIPTION_PATCH_FIELDS if scope == "SUBSCRIPTION" else RSS_PATCH_FIELDS
    if set(patch) - allowed:
        raise _invalid("invalid_management_patch_field")
    normalized = {str(key): _validate_patch_value(str(key), value) for key, value in patch.items()}
    if scope == "SUBSCRIPTION" and "filter_rule" in normalized:
        rule = normalized["filter_rule"]
        if not isinstance(rule, Mapping) or not rule or set(rule) - _FILTER_FIELDS:
            raise _invalid("invalid_management_filter")
        normalized["filter_rule"] = {
            str(key): _validate_patch_value(f"filter_rule.{key}", value)
            for key, value in rule.items()
        }
    return normalized


def build_complete_subscription_update(
    target: ResolvedManagementTarget, patch: Mapping[str, Any]
) -> dict[str, Any]:
    """Build an update body from the fresh target plus the safe public patch."""
    if target.scope != "SUBSCRIPTION" or target.subscription is None:
        raise _invalid("invalid_management_target")
    safe_patch = build_management_patch("SUBSCRIPTION", patch)
    current = target.subscription
    if current.upstream_fields:
        body = dict(current.upstream_fields)
        aliases = {"title": "official_title", "subtitle_group": "group_name",
                   "filter_rule": "filter", "expected_folder_name": "save_path"}
        body.update({aliases.get(key, key): value for key, value in safe_patch.items()})
    else:
        body = {"title": current.title, "season": current.season, "subtitle_group": current.subtitle_group}
        body.update(safe_patch)
    return body


def build_complete_rss_update(
    target: ResolvedManagementTarget, patch: Mapping[str, Any]
) -> tuple[dict[str, Any], ...]:
    """Build one URL-preserving update body per associated RSS item."""
    if target.scope != "ASSOCIATED_RSS" or not target.rss:
        raise _invalid("invalid_management_target")
    safe_patch = build_management_patch("ASSOCIATED_RSS", patch)
    bodies = []
    for item in target.rss:
        if item.upstream_fields:
            body = dict(item.upstream_fields)
            body.update(safe_patch)
        else:
            body = {"name": item.name, "aggregate": item.aggregate, "parser": item.parser, **safe_patch}
        bodies.append(body)
    return tuple(bodies)


def build_management_binding(
    *, action: str, scope: str, patch: Mapping[str, Any] | None = None, enabled: bool | None = None
) -> ManagementBinding:
    """Return deterministic action and expected-projection SHA-256 summaries."""
    if action not in {"MODIFY", "SET_ENABLED", "DELETE_EXTERNAL", "REFRESH_RSS"}:
        raise _invalid("invalid_management_action")
    if scope not in {"SUBSCRIPTION", "ASSOCIATED_RSS"}:
        raise _invalid("invalid_management_scope")
    if action == "MODIFY":
        if patch is None:
            raise _invalid("invalid_management_patch")
        projection: Any = build_management_patch(scope, patch)
    elif action == "SET_ENABLED":
        if type(enabled) is not bool:
            raise _invalid("invalid_enabled")
        projection = {"enabled": enabled}
    elif action == "DELETE_EXTERNAL":
        projection = {"deleted": True}
    else:
        projection = {"scope": scope}
    action_digest = canonical_management_fingerprint(
        action=action, target_scope=scope, expected_projection=projection
    )
    encoded = json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return ManagementBinding(
        action_fingerprint=action_digest,
        expected_external_fingerprint=f"sha256:{hashlib.sha256(encoded).hexdigest()}",
    )


def _validate_patch_value(field: str, value: Any) -> Any:
    if field in {"filter_rule"}:
        return value
    if isinstance(value, Mapping):
        return {str(key): _validate_patch_value(f"{field}.{key}", item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_validate_patch_value(field, item) for item in value]
    if isinstance(value, str):
        if _URL_RE.search(value) or _ABSOLUTE_PATH_RE.search(value) or ".." in value.replace("\\", "/").split("/"):
            raise _invalid("unsafe_management_patch")
        return value.strip() if field in _TEXT_FIELDS else value
    if field == "season" and (not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100):
        raise _invalid("invalid_management_patch")
    if field == "offset" and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
        raise _invalid("invalid_management_patch")
    if field in {"aggregate", "use_regex", "case_sensitive"} and type(value) is not bool:
        raise _invalid("invalid_management_patch")
    if value is None and field in _TEXT_FIELDS:
        return None
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    raise _invalid("invalid_management_patch")


def _rss_sort_key(value: str) -> tuple[int, str]:
    try:
        return (0, f"{int(value):020d}")
    except ValueError:
        return (1, value)


def _invalid(reason: str) -> Stage1Error:
    return Stage1Error(reason, "管理目标或修改内容无效", "management_target")


__all__ = [
    "ManagementBinding",
    "ResolvedManagementTarget",
    "SUBSCRIPTION_PATCH_FIELDS",
    "RSS_PATCH_FIELDS",
    "build_complete_rss_update",
    "build_complete_subscription_update",
    "build_management_binding",
    "build_management_patch",
    "resolve_management_target",
]
