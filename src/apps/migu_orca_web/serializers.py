from __future__ import annotations

"""Response serialization helpers for the Web API (US-191 split).

These helpers were previously defined in ``views.py``. They convert engine
models / Stage1Error results into the public, sanitized API representation.
They are also the seams the API contract tests monkeypatch to simulate
failures without touching real external services.
"""

import re
from typing import Any

from flask import url_for

from apps.migu_orca_web.contexts import candidate_selection_contexts
from batch_engine.controllers.candidate_search_orchestrator import (
    CandidateSearchOutcome,
)
from batch_engine.controllers.preference_applicator import (
    AppliedBatchPreferences,
    build_preference_hits,
)
from batch_engine.models import (
    AnimeTitleParseResult,
    BatchDraftItem,
)
from extensions.flask_api.api import sanitize_error_data
from mikan_engine.controllers.mikan_candidate_recommendation import (
    candidate_recommendation_label,
)
from mikan_engine.controllers.mikan_client import MikanCandidate
from mikan_engine.controllers.mikan_poster_service import MikanPosterService
from shared.errors import Stage1Error
from shared.season_evidence import candidate_season_evidence

poster_service = MikanPosterService()


def _serialize_batch_parse_result(
    item: BatchDraftItem,
    parse_result: AnimeTitleParseResult,
    *,
    candidates: list[dict[str, object]] | None = None,
    error: Stage1Error | None = None,
    applied_preferences: dict[str, object] | None = None,
    preference_hits: list[dict[str, object]] | None = None,
    preference_warnings: list[str] | None = None,
    needs_user_review: bool | None = None,
    review_hints: list[str] | None = None,
    enhanced_search_queries: list[dict[str, object]] | None = None,
    preview_request: dict[str, object] | None = None,
    attempted_queries: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "item_id": item.item_id,
        "raw_title": item.raw_title,
        "status": item.status,
        "canonical_title_candidates": list(parse_result.canonical_title_candidates),
        "season_hint": parse_result.season_hint,
        "search_queries": list(parse_result.search_queries),
        "confidence": parse_result.confidence,
        "needs_user_review": (
            parse_result.needs_user_review
            if needs_user_review is None
            else needs_user_review
        ),
        "source": parse_result.source,
        # The nested contract is the shared API representation.  The older
        # top-level fields remain for existing clients during the migration.
        "parse_result": _serialize_parse_summary(parse_result),
        "attempted_queries": list(attempted_queries or []),
        "candidates": candidates or [],
        "applied_preferences": applied_preferences,
        "preference_hits": preference_hits,
        "preference_warnings": list(preference_warnings or []),
        "review_hints": list(review_hints or []),
        "enhanced_search_queries": list(enhanced_search_queries or []),
        "preview_request": preview_request,
    }
    if error is not None:
        result["error"] = _serialize_title_search_error(error)
    return result


def _serialize_failed_batch_item(
    item: BatchDraftItem,
    error: Stage1Error,
    *,
    applied_preferences: dict[str, object] | None = None,
    preference_hits: list[dict[str, object]] | None = None,
    preference_warnings: list[str] | None = None,
    review_hints: list[str] | None = None,
    enhanced_search_queries: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "item_id": item.item_id,
        "raw_title": item.raw_title,
        "status": item.status,
        "canonical_title_candidates": [],
        "season_hint": None,
        "search_queries": [],
        "confidence": 0.0,
        "needs_user_review": True,
        "source": "unknown",
        "parse_result": None,
        "attempted_queries": [],
        "candidates": [],
        "applied_preferences": applied_preferences,
        "preference_hits": preference_hits,
        "preference_warnings": list(preference_warnings or []),
        "review_hints": list(review_hints or []),
        "enhanced_search_queries": list(enhanced_search_queries or []),
        "error": _serialize_title_search_error(error),
    }


def _serialize_parse_summary(parse_result: AnimeTitleParseResult) -> dict[str, object]:
    """Expose the immutable parse model through its whitelist serializer."""

    return parse_result.to_dict()


def _serialize_attempted_queries(
    parse_result: AnimeTitleParseResult,
    outcome: CandidateSearchOutcome[object],
) -> list[dict[str, object]]:
    """Return only plan-backed, publicly reviewable queries actually run."""

    attempted = set(outcome.attempted_queries)
    return [entry.to_dict() for entry in parse_result.query_plan if entry.query in attempted]


def _serialize_title_search_error(error: Stage1Error) -> dict[str, object]:
    """Keep parser/search errors useful without reflecting provider details."""

    error_type = error.error_type
    category = (
        "title_parse" if error_type.startswith("ai_title_parse") else "mikan_search"
        if error_type.startswith("mikan_") else "validation"
        if error_type.startswith("invalid_") else "processing"
    )
    details: dict[str, object] = {
        "category": category,
        "recoverable": category != "validation",
    }
    raw_details = error.details or {}
    field = raw_details.get("field")
    length = raw_details.get("length", raw_details.get("raw_title_length"))
    if isinstance(field, str) and field:
        details["field"] = field
    if isinstance(length, int) and length >= 0:
        details["length"] = length
    return {
        "error_type": error_type,
        "error_message": (
            "AI 名称解析失败，请检查该条目后重试"
            if category == "title_parse"
            else "MiKan 候选搜索失败"
        ),
        "failed_step": error.failed_step,
        "details": details,
    }


def _raise_result_error(result: dict[str, Any]) -> None:
    error = result.get("error")
    if not isinstance(error, dict):
        raise Stage1Error(
            "unexpected_error",
            "订阅方案 API 操作失败",
            "migu_orca_web_api",
        )
    details = error.get("details")
    raise Stage1Error(
        str(error.get("error_type") or "unexpected_error"),
        str(error.get("error_message") or "订阅方案 API 操作失败"),
        str(error.get("failed_step") or "migu_orca_web_api"),
        details if isinstance(details, dict) else None,
    )


def _optional_error(error: Stage1Error) -> dict[str, object]:
    details = _strip_sensitive_result_fields(sanitize_error_data(error.details or {}))
    assert isinstance(details, dict)
    return {
        "error_type": error.error_type,
        "error_message": error.message,
        "failed_step": error.failed_step,
        "details": details,
    }


def _serialize_candidate(candidate: MikanCandidate, query: str) -> dict[str, object]:
    poster_key = poster_service.register(candidate.poster_url)
    serialized: dict[str, object] = {
        "bangumi_id": candidate.bangumi_id,
        "title": candidate.title,
        "mikan_url": candidate.mikan_url,
        "poster_url": (
            url_for("migu_orca_web_api.mikan_poster", key=poster_key)
            if poster_key is not None
            else None
        ),
        "source_query": candidate.source_query,
        "aliases": list(candidate.aliases),
        # Display-only recommendation label derived from the search query and
        # public candidate metadata; never selects a candidate or triggers
        # generation. Contains no raw HTML, RSS XML, cookies, or tokens.
        "recommendation": candidate_recommendation_label(
            query,
            candidate.title,
            candidate.aliases,
        ),
    }
    if candidate.total_episodes is not None:
        serialized["total_episodes"] = candidate.total_episodes
    return serialized


def _with_candidate_season_evidence(
    candidate: dict[str, object], parse_result: AnimeTitleParseResult
) -> dict[str, object]:
    """Add a public review summary without treating parser output as fact."""
    result = dict(candidate)
    if parse_result.season.number is None:
        return result
    title = result.get("title")
    aliases = result.get("aliases")
    evidence = candidate_season_evidence(
        title if isinstance(title, str) else "",
        aliases if isinstance(aliases, list) else (),
        parse_result.season.number,
    )
    result["season_evidence"] = evidence
    mikan_url = result.get("mikan_url")
    if isinstance(mikan_url, str) and evidence["status"] == "NEEDS_CONFIRMATION":
        # This opaque, bounded, one-time context is the only path by which a
        # parser hint can reach a selected request. Browser-display fields are
        # never trusted as season evidence.
        result["candidate_context"] = candidate_selection_contexts.issue(
            mikan_url, parse_result.season.number
        )
    return result


def _serialize_preference_application(
    applied: AppliedBatchPreferences | None,
    warnings: list[str],
) -> tuple[dict[str, object] | None, list[dict[str, object]] | None, list[str]]:
    """Split an applied-preference result into the three public API fields.

    Returns ``(applied_preferences, preference_hits, preference_warnings)``;
    the first two are ``None`` when preferences were unavailable, while the
    fallback warning list is always present so the UI can explain the default
    flow. Only public rule summaries leave this function.
    """
    if applied is None:
        return None, None, list(warnings)
    return (
        applied.to_dict(),
        build_preference_hits(applied),
        list(warnings),
    )


def _sanitize_ab_submit_result(result: dict[str, Any]) -> dict[str, Any]:
    sanitized = _strip_sensitive_result_fields(sanitize_error_data(result))
    assert isinstance(sanitized, dict)
    return sanitized


def _sanitize_qbittorrent_connection_summary(summary: dict[str, Any]) -> dict[str, Any]:
    allowed_fields = {"status", "reachable", "version"}
    sanitized = sanitize_error_data(
        {
            key: value
            for key, value in summary.items()
            if key in allowed_fields
        }
    )
    assert isinstance(sanitized, dict)
    return sanitized


def _sanitize_ab_connection_summary(summary: dict[str, Any]) -> dict[str, Any]:
    allowed_fields = {
        "reachable",
        "authenticated",
        "version",
        "auth_mode",
        "adapter",
        "submit_supported",
    }
    sanitized = sanitize_error_data(
        {key: value for key, value in summary.items() if key in allowed_fields}
    )
    assert isinstance(sanitized, dict)
    return sanitized


# ---------------------------------------------------------------------------
# Request safe-info serializer (US-217)
# ---------------------------------------------------------------------------
# ``serialize_request_safe_info`` is the *only* producer for the
# ``GET /api/v1/requests/{request_id}/safe-info`` result. It follows the
# default-deny rule (D28-10): it reads only the whitelisted public fields
# below and never returns the snapshot unchanged. Full collection/RSS URLs,
# magnet links, endpoints, credentials, raw upstream responses and local
# absolute paths are omitted at the field level; free-text labels are still
# scrubbed so a poisoned value that *looks* like a URL/magnet/path cannot pass.

_SAFE_ABSOLUTE_LABEL_RE = re.compile(r"^[a-zA-Z]:[\\/]")


def _safe_label(value: Any) -> str | None:
    """Return a public display label or ``[redacted]`` for URL/magnet/path text.

    ``None``/non-string values become ``None`` so the DTO can render them as
    "未设置"; a string that carries a scheme, magnet marker or absolute path is
    replaced with the stable ``[redacted]`` marker.
    """
    if value is None:
        return None
    text = str(value).strip()
    lowered = text.lower()
    if (
        "magnet:?" in lowered
        or lowered.startswith("http://")
        or lowered.startswith("https://")
        or text.startswith("/")
        or _SAFE_ABSOLUTE_LABEL_RE.match(text)
    ):
        return "[redacted]"
    return text


def _safe_count(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _extract_public_bangumi_id(mikan_url: Any) -> str | None:
    """Extract the public MiKan collection id from a ``/Home/Bangumi/<id>`` URL.

    Only the numeric/public id is returned — the full collection URL never
    leaves the serializer.
    """
    if not isinstance(mikan_url, str):
        return None
    marker = "/Home/Bangumi/"
    if marker not in mikan_url:
        return None
    remainder = mikan_url.split(marker, 1)[1].split("?", 1)[0].split("#", 1)[0]
    candidate = remainder.strip("/")
    if not candidate or any(ch in candidate for ch in "/\\"):
        return None
    return candidate


def _rss_source_dicts(source_info: Any) -> list[dict[str, Any]]:
    if not isinstance(source_info, dict):
        return []
    sources = source_info.get("rss_sources")
    return [s for s in sources if isinstance(s, dict)] if isinstance(sources, list) else []


def _combined_source_seed_count(source: dict[str, Any]) -> int:
    names: list[str] = []
    for name in source.get("valid_seed_names", []):
        if isinstance(name, str) and name not in names:
            names.append(name)
    for entry in source.get("excluded_seed_names", []):
        name = entry.get("name") if isinstance(entry, dict) else None
        if isinstance(name, str) and name not in names:
            names.append(name)
    return len(names)


def serialize_request_safe_info(
    request: dict[str, Any],
    *,
    history_events: list[dict[str, Any]] | None = None,
    ab_submit_result: dict[str, Any] | None = None,
    storage_profile: str | None = None,
) -> dict[str, Any]:
    """Build the strict safe-info whitelist for one saved Request (US-217).

    Every value is explicitly read from the snapshot's public display fields;
    the raw snapshot's ``mikan_url``/``rss_url``/``poster_url``/
    ``selected_rss_url`` and any credential/upstream-response/absolute-path
    field never appear. The result is meant to feed ``RequestSafeInfoDTO``
    (``extra="forbid"``), so an unknown/leaked key fails the boundary tests.
    """
    matched: dict[str, Any] = {}
    raw_input: dict[str, Any] = {}
    confirmable: dict[str, Any] = {}
    source_info = request.get("source_info")
    if isinstance(source_info, dict):
        matched = source_info.get("matched_bangumi")
        matched = matched if isinstance(matched, dict) else {}
    request_input = request.get("input")
    if isinstance(request_input, dict):
        raw_input = request_input
    request_config = request.get("confirmable_config")
    if isinstance(request_config, dict):
        confirmable = request_config

    rss_sources = _rss_source_dicts(source_info)
    selected_group = confirmable.get("selected_subtitle_group")
    selected_group_label = _safe_label(selected_group)
    selected_source = next(
        (source for source in rss_sources if source.get("subtitle_group") == selected_group),
        None,
    )

    # Resources (sanitized file names only — never magnet/download URLs/RSS).
    valid_names = _safe_string_list(
        (selected_source or {}).get("valid_seed_names")
        or confirmable.get("effective_seed_names")
    )
    excluded_entries = (selected_source or {}).get("excluded_seed_names", [])
    excluded_files: list[dict[str, Any]] = []
    for entry in excluded_entries if isinstance(excluded_entries, list) else []:
        if not isinstance(entry, dict):
            continue
        excluded_files.append(
            {
                "name": _safe_label(entry.get("name")) or "",
                "reason": _safe_label(entry.get("reason")) or "",
            }
        )
    complete_count = sum(
        _combined_source_seed_count(source) for source in rss_sources
    )
    resources: dict[str, Any] = {
        "selected_subtitle_group": selected_group_label,
        "valid_resource_count": len(valid_names),
        "invalid_resource_count": len(excluded_files),
        "complete_resource_count": complete_count,
        "valid_file_names": valid_names,
        "excluded_file_names": excluded_files,
    }

    filter_rule = confirmable.get("filter_rule")
    filter_rule = filter_rule if isinstance(filter_rule, dict) else {}

    subtitle_groups = [
        {
            "subtitle_group": _safe_label(source.get("subtitle_group")),
            "total_resource_count": _safe_count(source.get("total_seed_count")),
            "valid_resource_count": _safe_count(source.get("valid_seed_count")),
            "invalid_resource_count": _safe_count(source.get("invalid_seed_count")),
            "warnings": [
                _safe_label(warning) or ""
                for warning in source.get("warnings", [])
                if isinstance(warning, str)
            ],
        }
        for source in rss_sources
    ]

    title = _safe_label(matched.get("title"))
    mikan_collection: dict[str, Any] = {
        "title": title,
        "bangumi_id": _extract_public_bangumi_id(matched.get("mikan_url")),
    }

    history_summary: list[dict[str, Any]] = []
    for event in history_events or []:
        if not isinstance(event, dict):
            continue
        history_summary.append(
            {
                "action": _safe_label(event.get("action")),
                "previous_status": _safe_label(event.get("previous_status")),
                "next_status": _safe_label(event.get("next_status")),
                "timestamp": _safe_label(event.get("timestamp")),
            }
        )

    ab_status: dict[str, Any] = {
        "submitted": False,
        "success": None,
        "ab_subscription_id": None,
        "error_type": None,
    }
    if isinstance(ab_submit_result, dict):
        ab_status["submitted"] = True
        ab_status["success"] = ab_submit_result.get("success")
        ab_subscription_id = ab_submit_result.get("ab_subscription_id")
        ab_status["ab_subscription_id"] = _safe_label(ab_subscription_id)
        if ab_status["success"] is False:
            error = ab_submit_result.get("error")
            if isinstance(error, dict):
                ab_status["error_type"] = _safe_label(error.get("error_type"))

    return {
        "request_id": _safe_label(request.get("request_id")),
        "status": _safe_label(request.get("status")),
        "raw_title": _safe_label(raw_input.get("raw_title")),
        "title": title,
        "aliases": _safe_string_list(matched.get("aliases")),
        "season": matched.get("season") if isinstance(matched.get("season"), int) else None,
        "season_raw": _safe_label(matched.get("season_raw")),
        "season_evidence": _safe_label(matched.get("season_evidence")),
        "mikan_collection": mikan_collection,
        "subtitle_groups": subtitle_groups,
        "selected_subtitle_group": selected_group_label,
        "filter_rule": {
            "must_contain": _safe_label(filter_rule.get("must_contain")) or "",
            "must_not_contain": _safe_label(filter_rule.get("must_not_contain")) or "",
            "use_regex": bool(filter_rule.get("use_regex")),
            "case_sensitive": bool(filter_rule.get("case_sensitive")),
        },
        "resources": resources,
        "folder_name": _safe_label(confirmable.get("expected_folder_name")),
        "storage_profile": storage_profile,
        "total_episodes": None,
        "updated_episode": None,
        "updated_episode_status": "NOT_IMPLEMENTED",
        "history_summary": history_summary,
        "ab_status": ab_status,
    }


def _safe_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        label = _safe_label(item)
        if label is not None:
            cleaned.append(label)
    return cleaned


def _strip_sensitive_result_fields(value: Any) -> Any:
    blocked = (
        "token",
        "secret",
        "cookie",
        "authorization",
        "password",
        "passwd",
        "bearer",
        "magnet",
    )
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if any(term in key_text.lower() for term in blocked):
                sanitized["[redacted]"] = "[redacted]"
            else:
                sanitized[key_text] = _strip_sensitive_result_fields(item)
        return sanitized
    if isinstance(value, list):
        return [_strip_sensitive_result_fields(item) for item in value]
    if isinstance(value, str) and "magnet:?" in value.lower():
        return "[redacted]"
    return value
