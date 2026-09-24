from __future__ import annotations

"""Application-service / orchestration helpers for the Web API (US-191 split).

These helpers were previously defined in ``views.py``. They reuse the existing
engine/repository seams (title parsing, candidate search, preferences,
corrections, request snapshots, batch queue) and never duplicate business
rules. Keeping the seams importable here is what lets API tests monkeypatch
external transports without touching real MiKan or AutoBangumi.
"""

import os
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from apps.migu_orca_entry.controllers.entry_controller import (
    _build_history_event,
    apply_confirmation_action,
    apply_request_save_action,
)
from apps.migu_orca_web.serializers import (
    _optional_error,
    _raise_result_error,
    _serialize_attempted_queries,
    _serialize_batch_parse_result,
    _serialize_candidate,
    _serialize_failed_batch_item,
    _serialize_preference_application,
    _with_candidate_season_evidence,
)
from batch_engine.controllers.anime_title_parser import (
    AnimeTitleParsingProvider,
    RuleAnimeTitleParsingProvider,
    parse_anime_title,
)
from batch_engine.controllers.batch_draft_controller import (
    create_batch_draft,
    split_batch_raw_input,
    update_batch_item_status,
)
from batch_engine.controllers.candidate_search_orchestrator import (
    CandidateSearchOutcome,
    search_parsed_candidates,
)
from batch_engine.controllers.preference_applicator import (
    AppliedBatchPreferences,
    apply_preferences_to_item,
    build_review_metadata,
)
from batch_engine.controllers.search_enhancer import enhance_search_queries
from batch_engine.models import (
    BATCH_ITEM_STATUS_EMPTY,
    BATCH_ITEM_STATUS_FAILED,
    BATCH_ITEM_STATUS_FOUND,
    MAX_BATCH_ITEMS,
    AnimeTitleParseResult,
)
from mikan_engine.controllers import mikan_client as mikan_client_module
from mikan_engine.controllers.mikan_candidate_cache import (
    candidate_cache_key,
    candidate_search_cache,
)
from mikan_engine.controllers.mikan_config import (
    MikanConfig,
    default_mikan_config,
)
from request_engine.controllers.request_controller import (
    ACCEPTED,
    PENDING_CONFIRM,
)
from shared.errors import Stage1Error
from shared.models import TitleCorrection, VersionedUserPreference
from storage_engine.controllers.ab_result_repository import load_ab_submit_result
from storage_engine.controllers.correction_repository import load_corrections
from storage_engine.controllers.history_repository import load_status_history
from storage_engine.controllers.preference_repository import load_user_preferences
from storage_engine.controllers.request_repository import load_request_snapshot
from storage_engine.controllers.storage_config import DEFAULT_STORAGE_DIR, StorageConfig, load_storage_config


def _storage_dir(value: str | None) -> Path | None:
    """Resolve a client-supplied ``storage_dir`` against the Web storage root.

    US-193: the browser may only select a *relative profile* under the
    server-controlled storage root (``_WEB_STORAGE_ROOT``). Empty means the root
    itself (the resolved ``_WEB_STORAGE_ROOT``, never ``None`` — ``None`` would
    make ``load_storage_config`` fall back to the CLI default
    ``DEFAULT_STORAGE_DIR`` and bypass the server root). Absolute paths, Windows
    drive paths, traversal (``..``) and symlink escapes are rejected with a
    stable ``invalid_storage_dir`` error (400); the error details never echo the
    raw value (which could be an absolute path).
    """
    if value is None or not value.strip():
        return _WEB_STORAGE_ROOT
    profile = value.strip()

    # Reject absolute paths up front (Unix absolute or Windows drive root) so
    # the raw value is never resolved against the server filesystem.
    if profile.startswith("/") or _WINDOWS_DRIVE_RE.match(profile):
        raise Stage1Error(
            "invalid_storage_dir",
            "storage_dir 必须是服务器允许根目录下的相对目录",
            "resolve_web_storage_dir",
            {"field": "storage_dir", "reason": "absolute_path_not_allowed"},
        )

    root = _WEB_STORAGE_ROOT
    candidate = (root / profile).resolve()
    if candidate != root and not candidate.is_relative_to(root):
        raise Stage1Error(
            "invalid_storage_dir",
            "storage_dir 必须位于服务器允许的存储根目录内",
            "resolve_web_storage_dir",
            {"field": "storage_dir", "reason": "escape_attempt"},
        )
    return candidate


def _storage_profile(storage_dir: Path | None) -> str | None:
    """Return a safe, displayable relative profile for a resolved storage dir.

    When ``storage_dir`` is the server-side root itself (the ``None``/empty
    fallback) this is ``None`` so the safe-info DTO renders "默认"; otherwise it
    is the resolved directory's ``name`` (a single relative profile segment,
    never an absolute path). Used only for safe-info display — never for
    resolving another path.
    """
    if storage_dir is None:
        return None
    resolved = storage_dir.expanduser().resolve()
    root = _WEB_STORAGE_ROOT
    if resolved == root:
        return None
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        return None
    name = relative.parts[0] if relative.parts else None
    if not name or name in {"", ".", ".."} or "/" in name or "\\" in name:
        return None
    return name


# ---------------------------------------------------------------------------
# Web storage root (US-193)
# ---------------------------------------------------------------------------
# The Web API must never let the browser select an arbitrary server path. All
# requests resolve ``storage_dir`` against a server-side storage root; the
# client may only choose a *relative profile* under that root. The default root
# is the same local storage directory the CLI uses. Deployments may override it
# with ``MIGU_ORCA_WEB_STORAGE_ROOT`` (server-side environment only — never
# client-controlled, never reflected into API responses, logs or browser
# storage).
_WINDOWS_DRIVE_RE = re.compile(r"^[a-zA-Z]:[\\/]")

_DEFAULT_WEB_STORAGE_ROOT = os.environ.get("MIGU_ORCA_WEB_STORAGE_ROOT", "").strip()

_WEB_STORAGE_ROOT: Path = (
    Path(_DEFAULT_WEB_STORAGE_ROOT).expanduser().resolve()
    if _DEFAULT_WEB_STORAGE_ROOT
    else DEFAULT_STORAGE_DIR
)


def set_web_storage_root(root: Path | None) -> None:
    """Override the server-side Web storage root (test seam / runtime config).

    Server-side only: the browser never controls this value. ``None`` restores
    the default root.
    """
    global _WEB_STORAGE_ROOT
    if root is None:
        _WEB_STORAGE_ROOT = (
            Path(_DEFAULT_WEB_STORAGE_ROOT).expanduser().resolve()
            if _DEFAULT_WEB_STORAGE_ROOT
            else DEFAULT_STORAGE_DIR
        )
        return
    _WEB_STORAGE_ROOT = root.expanduser().resolve()


def _web_storage_root() -> Path:
    """Return the resolved server-side Web storage root (for docs/tests)."""
    return _WEB_STORAGE_ROOT


def _batch_title_parsing_provider() -> AnimeTitleParsingProvider:
    return RuleAnimeTitleParsingProvider()


def _search_mikan_candidates(
    query: str,
    mikan_config: MikanConfig,
) -> list[dict[str, object]]:
    """Search real MiKan candidates through the existing transport seam.

    Repeated searches for the same query against the same MiKan identity are
    served from the in-process candidate cache so the transport is not called on
    a cache hit. Returns (and caches) only sanitized public candidate metadata:
    bangumi id, title, normalized bangumi URL, optional poster URL, the source
    query, and aliases. Raw HTML, raw RSS XML, cookies, tokens, and full failed
    URLs never appear in the response or the cache.
    """
    cache_key = candidate_cache_key(query, mikan_config)
    cached = candidate_search_cache.get(cache_key)
    if cached is not None:
        return [_serialize_candidate(candidate, query) for candidate in cached]

    client = mikan_client_module.create_mikan_client(mikan_config)
    candidates = client.search_candidates(query)
    candidate_search_cache.set(cache_key, candidates)
    return [_serialize_candidate(candidate, query) for candidate in candidates]


def _search_batch_item_candidates(
    search_queries: list[str],
    mikan_config: MikanConfig,
) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    seen: set[tuple[object, object]] = set()
    for query in search_queries:
        for candidate in _search_mikan_candidates(query, mikan_config):
            key = (candidate.get("bangumi_id"), candidate.get("mikan_url"))
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)
    return candidates


def _search_candidates_from_parse_result(
    parse_result: AnimeTitleParseResult,
    mikan_config: MikanConfig,
    *,
    search_one: Callable[[str], list[dict[str, object]]] | None = None,
) -> CandidateSearchOutcome[dict[str, object]]:
    """Use the one shared parsed-plan fallback policy for both API flows."""

    run_query = search_one or (lambda query: _search_mikan_candidates(query, mikan_config))
    return search_parsed_candidates(
        parse_result,
        run_query,
        lambda candidate: (candidate.get("bangumi_id"), candidate.get("mikan_url")),
    )


def _search_batch_item_candidates_enhanced(
    enhanced_queries: list[dict[str, object]],
    original_queries: list[str],
    mikan_config: MikanConfig,
) -> list[dict[str, object]]:
    """Search enhanced queries first, falling back to the original queries.

    When no correction matched (``enhanced_queries`` is empty), this delegates
    directly to ``_search_batch_item_candidates`` so the default flow is
    byte-for-byte unchanged. Otherwise the enhanced queries are searched with
    per-query tolerance (a single bad variant never blocks the rest); if none of
    them yield candidates, the original queries are searched exactly as today.
    """
    if not enhanced_queries:
        return _search_batch_item_candidates(original_queries, mikan_config)

    candidates: list[dict[str, object]] = []
    seen: set[tuple[object, object]] = set()
    for entry in enhanced_queries:
        query = str(entry.get("query") or "").strip()
        if not query:
            continue
        try:
            for candidate in _search_mikan_candidates(query, mikan_config):
                key = (candidate.get("bangumi_id"), candidate.get("mikan_url"))
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(candidate)
        except Stage1Error:
            # One enhanced variant failing never blocks the remaining variants.
            continue
    if candidates:
        return candidates
    return _search_batch_item_candidates(original_queries, mikan_config)


def _load_preferences_for_batch(
    config: StorageConfig,
) -> VersionedUserPreference | None:
    """Load saved user preferences for batch parsing.

    Returns ``None`` when the preference file is damaged or unreadable, so batch
    parsing falls back to the Stage 19 default flow and one item's missing
    preferences never block the rest of the batch.
    """
    try:
        return load_user_preferences(config)
    except Stage1Error:
        return None


def _load_corrections_for_batch(
    config: StorageConfig,
) -> list[TitleCorrection]:
    """Load saved title corrections for batch parsing.

    Returns ``[]`` when the correction file is damaged or unreadable, so batch
    parsing falls back to the original ``search_queries`` and one item's missing
    corrections never block the rest of the batch.
    """
    try:
        return load_corrections(config)
    except Stage1Error:
        return []


def _enhanced_entries_for_item(
    raw_title: str,
    parse_result: AnimeTitleParseResult | None,
    corrections: list[TitleCorrection],
) -> list[dict[str, object]]:
    """Build the reviewable enhanced-query metadata for one batch item.

    Each entry retains the original parse query, the enhanced query, and its
    ``correction:query``/``correction:canonical`` source marker so the user can
    review exactly what changed. When no correction matches (or the correction
    store is damaged/unavailable), this is ``[]`` and the original
    ``search_queries`` are used unchanged.
    """
    search_queries = list(parse_result.search_queries) if parse_result is not None else []
    return [
        {
            "query": entry["query"],
            "original_query": entry["original_query"],
            "source": entry["source"],
        }
        for entry in enhance_search_queries(raw_title, search_queries, corrections)
    ]


def _preference_application_for_item(
    raw_title: str,
    parse_result: AnimeTitleParseResult | None,
    preferences: VersionedUserPreference | None,
) -> tuple[AppliedBatchPreferences | None, list[str]]:
    """Build the per-item applied-preferences metadata for a batch draft.

    Returns ``(None, [fallback warning])`` when preferences are unavailable or
    application fails, keeping the Stage 19 default flow intact for that item
    while every other item is unaffected.
    """
    if preferences is None:
        return None, ["偏好读取失败，已回退默认流程"]
    try:
        applied = apply_preferences_to_item(raw_title, parse_result, preferences)
    except Exception:
        return None, ["偏好应用失败，已回退默认流程"]
    return applied, list(applied.warnings)


# ---------------------------------------------------------------------------
# Batch parse orchestration (Issue 133)
# ---------------------------------------------------------------------------
# The name parsing / MiKan candidate search / preference application / status
# update pipeline lives here; ``routes_batches`` only adapts input, selects the
# representation and frames the response.

def validate_batch_raw_input(raw_input: str) -> None:
    """US-215: 1..36 normalized non-empty lines.

    The same splitter the engine uses counts the lines, so a 37+ batch is
    rejected before the title parser, MiKan search or any persistence seam —
    with only the field/limit/actual summary (never echoing the raw input).
    Both the synchronous and the streaming view call this before doing work.
    """
    non_empty_lines = split_batch_raw_input(raw_input)
    if not non_empty_lines:
        raise Stage1Error(
            "validation_error",
            "请至少输入一个番剧名称",
            "batch_parse",
            {"field": "raw_input"},
        )
    if len(non_empty_lines) > MAX_BATCH_ITEMS:
        raise Stage1Error(
            "batch_limit_exceeded",
            f"单批最多支持 {MAX_BATCH_ITEMS} 部，当前输入 {len(non_empty_lines)} 部",
            "batch_parse",
            {
                "field": "raw_input",
                "limit": MAX_BATCH_ITEMS,
                "actual": len(non_empty_lines),
            },
        )


def batch_parse_item_event(
    item: dict[str, object], completed: int, total: int
) -> dict[str, object]:
    return {"kind": "item", "completed": completed, "total": total, "item": item}


def iter_batch_parse_events(
    raw_input: str, storage_dir: str | None
) -> Iterator[dict[str, object]]:
    """Issue 112: 逐部完成事件 + 最终批次结果。

    FOUND、EMPTY、FAILED 都在该部真正完成时产出一个 ``item`` 事件并让
    ``completed`` 前进一格；最后的 ``result`` 事件给出与同步端点完全一致的
    批次结果。事件只存在于本次请求的生命周期内：没有持久任务、没有取消、
    刷新或关闭后不续接。
    """
    validate_batch_raw_input(raw_input)
    batch = create_batch_draft(raw_input)
    total = len(batch.items)

    mikan_config = default_mikan_config()
    config = load_storage_config(
        _storage_dir(storage_dir)
    )
    preferences = _load_preferences_for_batch(config)
    corrections = _load_corrections_for_batch(config)
    # Keep the explicit provider seam used by batch tests. Saved corrections
    # are part of the same rule-provider query plan rather than a second
    # search fallback implementation.
    provider = (
        RuleAnimeTitleParsingProvider(corrections=corrections)
        if corrections
        else _batch_title_parsing_provider()
    )
    serialized_items: list[dict[str, object]] = []
    for item in batch.items:
        try:
            parse_result = parse_anime_title(item.raw_title, provider)
        except Stage1Error as exc:
            failed_batch = update_batch_item_status(
                batch,
                item.item_id,
                BATCH_ITEM_STATUS_FAILED,
            )
            failed_item = next(
                updated
                for updated in failed_batch.items
                if updated.item_id == item.item_id
            )
            applied_obj, warnings = _preference_application_for_item(
                item.raw_title, None, preferences
            )
            applied, hits, warnings = _serialize_preference_application(
                applied_obj, warnings
            )
            review = build_review_metadata(
                raw_title=item.raw_title,
                parse_result=None,
                candidates=[],
                preference_warnings=warnings,
                status=BATCH_ITEM_STATUS_FAILED,
            )
            serialized = _serialize_failed_batch_item(
                failed_item,
                exc,
                applied_preferences=applied,
                preference_hits=hits,
                preference_warnings=warnings,
                review_hints=review.review_hints,
                enhanced_search_queries=_enhanced_entries_for_item(
                    item.raw_title, None, corrections
                ),
            )
            serialized_items.append(serialized)
            yield batch_parse_item_event(serialized, len(serialized_items), total)
            continue

        enhanced_queries = _enhanced_entries_for_item(
            item.raw_title, parse_result, corrections
        )
        searched = _search_candidates_from_parse_result(
            parse_result,
            mikan_config,
            search_one=lambda query: _search_batch_item_candidates([query], mikan_config),
        )
        if searched.status == BATCH_ITEM_STATUS_FAILED:
            exc = searched.error or Stage1Error(
                "mikan_search_failed", "MiKan 候选搜索失败", "mikan_search"
            )
            failed_batch = update_batch_item_status(
                batch,
                item.item_id,
                BATCH_ITEM_STATUS_FAILED,
            )
            failed_item = next(
                updated
                for updated in failed_batch.items
                if updated.item_id == item.item_id
            )
            applied_obj, warnings = _preference_application_for_item(
                item.raw_title, parse_result, preferences
            )
            applied, hits, warnings = _serialize_preference_application(
                applied_obj, warnings
            )
            review = build_review_metadata(
                raw_title=item.raw_title,
                parse_result=parse_result,
                candidates=[],
                preference_warnings=warnings,
                search_failed=True,
                status=BATCH_ITEM_STATUS_FAILED,
            )
            serialized = _serialize_batch_parse_result(
                failed_item,
                parse_result,
                candidates=[],
                error=exc,
                applied_preferences=applied,
                preference_hits=hits,
                preference_warnings=warnings,
                needs_user_review=review.needs_user_review,
                review_hints=review.review_hints,
                enhanced_search_queries=enhanced_queries,
                attempted_queries=_serialize_attempted_queries(parse_result, searched),
            )
            serialized_items.append(serialized)
            yield batch_parse_item_event(serialized, len(serialized_items), total)
            continue

        candidates = [
            _with_candidate_season_evidence(candidate, parse_result)
            for candidate in searched.candidates
        ]

        candidate_status = (
            BATCH_ITEM_STATUS_FOUND
            if candidates
            else BATCH_ITEM_STATUS_EMPTY
        )
        searched_batch = update_batch_item_status(
            batch,
            item.item_id,
            candidate_status,
        )
        searched_item = next(
            updated
            for updated in searched_batch.items
            if updated.item_id == item.item_id
        )
        applied_obj, warnings = _preference_application_for_item(
            item.raw_title, parse_result, preferences
        )
        applied, hits, warnings = _serialize_preference_application(
            applied_obj, warnings
        )
        review = build_review_metadata(
            raw_title=item.raw_title,
            parse_result=parse_result,
            candidates=candidates,
            preference_warnings=warnings,
            status=candidate_status,
        )
        serialized = _serialize_batch_parse_result(
            searched_item,
            parse_result,
            candidates=candidates,
            applied_preferences=applied,
            preference_hits=hits,
            preference_warnings=warnings,
            needs_user_review=review.needs_user_review,
            review_hints=review.review_hints,
            enhanced_search_queries=enhanced_queries,
            attempted_queries=_serialize_attempted_queries(parse_result, searched),
        )
        serialized_items.append(serialized)
        yield batch_parse_item_event(serialized, len(serialized_items), total)

    yield {
        "kind": "result",
        "result": {
            "batch_id": batch.batch_id,
            "raw_input": batch.raw_input,
            "items": serialized_items,
        },
    }



def _build_batch_preview_request(
    *,
    batch_id: str,
    item_id: str,
    raw_title: str,
    parse_result: AnimeTitleParseResult,
    applied: AppliedBatchPreferences | None,
) -> dict[str, object]:
    """Build the editable in-memory draft (``preview_request``) for a parsed
    batch item so the card can enter the existing preview-modify /
    save-confirm flow.

    The draft is a PENDING_CONFIRM skeleton whose editable defaults come from
    the user preferences: the first preferred subtitle group, the default
    filter rule (with explicit ``use_regex``/``case_sensitive`` booleans), and
    the preferred folder name. RSS/seed data is intentionally absent — it is
    only available after a MiKan collection is chosen — so seeds start empty.
    Only non-sensitive public fields are included; the request-scoped
    ``request_id`` is derived from the batch/item identity so save-confirm can
    persist it without colliding across batches.
    """
    config = applied.to_dict() if applied is not None else None
    subtitle_groups = (config or {}).get("subtitle_groups") or {}
    preferred = subtitle_groups.get("preferred") or []
    filter_rule = (config or {}).get("filter_rule") or {
        "must_contain": "",
        "must_not_contain": "",
        "use_regex": False,
        "case_sensitive": False,
    }
    canonical = (
        list(parse_result.canonical_title_candidates)[0]
        if parse_result.canonical_title_candidates
        else raw_title
    )
    return {
        "request_id": f"{batch_id}-{item_id}",
        "status": PENDING_CONFIRM,
        "input": {"raw_title": raw_title},
        "source_info": {
            "matched_bangumi": {
                "title": canonical,
                "aliases": list(parse_result.canonical_title_candidates),
            },
            "rss_sources": [],
        },
        "confirmable_config": {
            "selected_subtitle_group": (
                str(preferred[0]) if preferred else None
            ),
            "selected_rss_url": None,
            "filter_rule": {
                "must_contain": str(filter_rule.get("must_contain") or ""),
                "must_not_contain": str(filter_rule.get("must_not_contain") or ""),
                "use_regex": bool(filter_rule.get("use_regex")),
                "case_sensitive": bool(filter_rule.get("case_sensitive")),
            },
            "effective_seed_names": [],
            "expected_folder_name": (
                applied.expected_folder_name if applied is not None else None
            ),
            "warnings": [],
        },
    }












def _load_history_section(config: StorageConfig, request_id: str) -> dict[str, object]:
    try:
        return {
            "available": True,
            "events": load_status_history(config, request_id),
            "error": None,
        }
    except Stage1Error as exc:
        return {"available": False, "events": [], "error": _optional_error(exc)}


def _load_ab_result_section(config: StorageConfig, request_id: str) -> dict[str, object]:
    try:
        return {
            "available": True,
            "record": load_ab_submit_result(config, request_id),
            "error": None,
        }
    except Stage1Error as exc:
        if exc.error_type == "ab_result_not_found":
            return {"available": False, "record": None, "error": None}
        return {"available": False, "record": None, "error": _optional_error(exc)}


# ---------------------------------------------------------------------------
# Save-confirm application seams (US-214)
# ---------------------------------------------------------------------------
# These builders wire the real DraftStore + entry-controller flow into the
# durable ``run_save_confirm`` coordinator (US-213). US-216 reuses the exact
# same per-draft seams for every batch item, so they live in services.py and
# stay independent of the single-item request schema.

def _build_save_confirm_persist_pending(storage_dir: Path | None):
    """Build the seam that durably persists a PENDING_CONFIRM snapshot.

    Mirrors ``save-confirm``: only a PENDING_CONFIRM draft may enter the saved
    confirmation flow (accept/cancel/modify/delete). The draft content is the
    authoritative server-side snapshot returned by ``reserve_for_save`` — never
    a client-supplied Request.
    """

    def persist_pending(request: dict[str, Any]) -> dict[str, Any]:
        if request.get("status") != PENDING_CONFIRM:
            raise Stage1Error(
                "invalid_request_status",
                "只有待确认的订阅草案可以保存",
                "save_confirm_persist",
                {"status": request.get("status")},
            )
        result = apply_request_save_action(
            {"success": True, "request": request, "error": None},
            True,
            storage_dir=storage_dir,
        )
        if not result["success"]:
            _raise_result_error(result)
        return result["request"]

    return persist_pending


def _build_save_confirm_confirm_saved(storage_dir: Path | None):
    """Build the seam that idempotently accepts a saved PENDING_CONFIRM Request.

    Mirrors the single-request accept view: load the snapshot, apply the shared
    accept action, record an ACCEPT history event, and persist the updated
    ACCEPTED Request. An already-ACCEPTED request is a success (the outcome is
    already CONFIRMED), never a failure, so a repeated confirm converges.
    """
    config = load_storage_config(storage_dir)

    def confirm_saved(request_id: str) -> dict[str, Any]:
        request = load_request_snapshot(config, request_id)
        if request.get("status") == ACCEPTED:
            return request
        result = apply_confirmation_action(
            {"success": True, "request": request, "error": None},
            "accept",
        )
        if not result["success"]:
            _raise_result_error(result)
        history_event = _build_history_event(
            request,
            result["request"],
            action="ACCEPT",
        )
        result = apply_request_save_action(
            result,
            True,
            storage_dir=storage_dir,
            history_events=[history_event],
        )
        if not result["success"]:
            _raise_result_error(result)
        return result["request"]

    return confirm_saved
