from __future__ import annotations

"""Application-service / orchestration helpers for the Web API (US-191 split).

These helpers were previously defined in ``views.py``. They reuse the existing
engine/repository seams (title parsing, candidate search, preferences,
corrections, request snapshots, batch queue) and never duplicate business
rules. Keeping the seams importable here is what lets API tests monkeypatch
external transports without touching real MiKan/AutoBangumi/qBittorrent.
"""

import os
import re
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apps.migu_orca_entry.controllers.entry_controller import (
    _build_history_event,
    apply_confirmation_action,
    apply_request_save_action,
)
from apps.migu_orca_web.schemas import RequestMikanConfigPayload
from apps.migu_orca_web.serializers import (
    _optional_error,
    _raise_result_error,
    _sanitize_ab_submit_result,
    _serialize_candidate,
)
from batch_engine.controllers.anime_title_parser import (
    AnimeTitleParsingProvider,
    RuleAnimeTitleParsingProvider,
)
from batch_engine.controllers.batch_accept_controller import (
    AcceptOne,
    LoadRequest,
)
from batch_engine.controllers.candidate_search_orchestrator import (
    CandidateSearchOutcome,
    search_parsed_candidates,
)
from batch_engine.controllers.preference_applicator import (
    AppliedBatchPreferences,
    apply_preferences_to_item,
)
from batch_engine.controllers.search_enhancer import enhance_search_queries
from batch_engine.models import (
    AnimeTitleParseResult,
    BatchSubmissionQueue,
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
from storage_engine.controllers.ab_result_repository import (
    load_ab_submit_result,
    save_ab_submit_result,
)
from storage_engine.controllers.correction_repository import load_corrections
from storage_engine.controllers.history_repository import load_status_history
from storage_engine.controllers.preference_repository import load_user_preferences
from storage_engine.controllers.queue_repository import (
    load_submission_queue,
    save_submission_queue,
)
from storage_engine.controllers.request_repository import (
    load_request_snapshot,
    save_request_snapshot,
)
from storage_engine.controllers.storage_config import (
    DEFAULT_STORAGE_DIR,
    StorageConfig,
    load_storage_config,
)


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


def _resolve_mikan_config(explicit: RequestMikanConfigPayload | None) -> MikanConfig:
    """Build the MiKan config for a request, falling back to system defaults.

    An explicit request-scoped ``mikan_config`` overrides the system default as a
    test seam or for advanced callers. The resolved config is request-scoped only:
    it is never written to browser storage, URL state, history, or Request
    snapshots, and it contains no secrets.
    """
    if explicit is not None:
        return MikanConfig(
            search_endpoint=explicit.search_endpoint,
            timeout_seconds=explicit.timeout_seconds,
        )
    return default_mikan_config()


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
    preview-save / accept flow.

    The draft is a PENDING_CONFIRM skeleton whose editable defaults come from
    the user preferences: the first preferred subtitle group, the default
    filter rule (with explicit ``use_regex``/``case_sensitive`` booleans), and
    the preferred folder name. RSS/seed data is intentionally absent — it is
    only available after a MiKan collection is chosen — so seeds start empty.
    Only non-sensitive public fields are included; the request-scoped
    ``request_id`` is derived from the batch/item identity so preview-save can
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


def _load_batch_queue_or_none(
    config: StorageConfig,
    batch_id: str,
) -> BatchSubmissionQueue | None:
    """Load a batch pre-submission queue, returning None when absent.

    Only ``queue_not_found`` is mapped to None; storage/invalid-id errors
    propagate so the caller never silently ignores a real read failure.
    """
    try:
        return load_submission_queue(config, batch_id)
    except Stage1Error as exc:
        if exc.error_type == "queue_not_found":
            return None
        raise


def _build_batch_load_request(storage_dir: Path | None) -> LoadRequest:
    """Build the injected ``load_request`` for batch accept/submit services.

    Resolves a request_id to its current snapshot, or None when the snapshot is
    missing/deleted, so the batch services can classify items without coupling
    to the storage layer.
    """
    config = load_storage_config(storage_dir)

    def load_request(request_id: str) -> dict[str, Any] | None:
        try:
            return load_request_snapshot(config, request_id)
        except Stage1Error:
            return None

    return load_request


def _build_batch_accept_one(storage_dir: Path | None) -> AcceptOne:
    """Build the injected ``accept_one`` for the batch accept service.

    Mirrors the single-request accept view: load the PENDING_CONFIRM snapshot,
    apply the shared accept action, record an ACCEPT history event, and persist
    the updated ACCEPTED request. Auto Bangumi secrets never pass through here.
    """
    config = load_storage_config(storage_dir)

    def accept_one(request_id: str) -> dict[str, Any]:
        request = load_request_snapshot(config, request_id)
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

    return accept_one


def _build_batch_persist_submit_result(storage_dir: Path | None):
    """Build the injected per-item AB-result persister for batch submit/retry.

    Mirrors the single-item submit-ab storage contract: sanitize the AB result,
    attach it to the Request snapshot, persist the snapshot, and write
    ``ab_results/<request_id>.json`` so the Request detail API can read and show
    the result. Auto Bangumi secrets (endpoint/token/cookie/raw response) never
    reach the persisted data because the result was already normalized by the AB
    submit contract and is sanitized again here.
    """
    config = load_storage_config(storage_dir)

    def persist_submit_result(
        request: dict[str, Any],
        ab_submit_result: dict[str, Any],
    ) -> dict[str, Any]:
        sanitized = _sanitize_ab_submit_result(ab_submit_result)
        updated = deepcopy(request)
        updated["ab_submit_result"] = sanitized
        updated["updated_at"] = datetime.now(UTC).isoformat()
        save_request_snapshot(config, updated)
        save_ab_submit_result(config, updated)
        return updated

    return persist_submit_result


def _build_batch_persist_queue(config: StorageConfig):
    """Build the injected per-item queue persister for batch submit/retry.

    The submit service flushes each item's SUBMITTING status before the Auto
    Bangumi call and its final status after the attempt; persisting through the
    existing queue repository means an interruption between the external submit
    and the final queue save can never leave READY_TO_SUBMIT on disk for an item
    that already reached Auto Bangumi. The queue only holds non-sensitive public
    fields, so writing it never stores Auto Bangumi secrets.
    """

    def persist_queue(queue: BatchSubmissionQueue) -> None:
        save_submission_queue(config, queue)

    return persist_queue


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

    Mirrors ``preview-save``: only a PENDING_CONFIRM draft may enter the saved
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
