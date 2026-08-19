from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flask import Blueprint, redirect, render_template, url_for
from pydantic import BaseModel, Field, field_validator

from extensions.flask_api import class_route
from extensions.flask_api.api import sanitize_error_data
from extensions.flask_api.views import GetView, PostView
from ab_engine.controllers.ab_config import build_ab_config
from apps.migu_orca_entry.controllers.entry_controller import (
    apply_ab_submit_action,
    apply_confirmation_action,
    apply_modify_action,
    apply_request_save_action,
    generate_request,
    _build_history_event,
    _confirmation_history_details,
)
from batch_engine.controllers.anime_title_parser import (
    AnimeTitleParsingProvider,
    FakeAnimeTitleParsingProvider,
    parse_anime_title,
)
from batch_engine.controllers.batch_accept_controller import (
    AcceptOne,
    BatchAcceptItem,
    LoadRequest,
    accept_batch_items,
    serialize_batch_accept_result,
)
from batch_engine.controllers.batch_draft_controller import (
    create_batch_draft,
    update_batch_item_status,
)
from batch_engine.controllers.batch_queue_controller import serialize_queue
from batch_engine.controllers.batch_submit_controller import (
    compose_ab_submit_one,
    recover_batch_queue_item,
    retry_batch_queue_item,
    serialize_batch_submit_result,
    submit_batch_queue_items,
)
from batch_engine.models import (
    BATCH_ITEM_STATUS_FAILED,
    BATCH_ITEM_STATUS_PARSED,
    AnimeTitleParseResult,
    BatchDraftItem,
    BatchSubmissionQueue,
)
from mikan_engine.controllers import mikan_client as mikan_client_module
from mikan_engine.controllers.mikan_candidate_cache import (
    candidate_cache_key,
    candidate_search_cache,
)
from mikan_engine.controllers.mikan_candidate_recommendation import (
    candidate_recommendation_label,
)
from mikan_engine.controllers.mikan_client import MikanCandidate
from mikan_engine.controllers.mikan_config import MikanConfig, default_mikan_config
from qbittorrent_engine.controllers.qbittorrent_controller import (
    test_qbittorrent_connection,
)
from qbittorrent_engine.controllers.qbittorrent_config import build_qbittorrent_config
from request_engine.controllers.request_controller import (
    PENDING_CONFIRM,
    summarize_request,
)
from shared.errors import Stage1Error
from shared.models import EntryRequest
from storage_engine.controllers.request_repository import (
    delete_request_snapshot,
    list_request_snapshots,
    load_request_snapshot,
    save_request_snapshot,
)
from storage_engine.controllers.ab_result_repository import (
    load_ab_submit_result,
    save_ab_submit_result,
)
from storage_engine.controllers.history_repository import load_status_history
from storage_engine.controllers.queue_repository import (
    load_submission_queue,
    save_submission_queue,
)
from storage_engine.controllers.storage_config import StorageConfig, load_storage_config

api_blueprint = Blueprint("migu_orca_web_api", __name__)
web_blueprint = Blueprint(
    "migu_orca_web",
    __name__,
    static_folder="static",
    static_url_path="/migu-orca-static",
    template_folder="templates",
)


class RequestListQuery(BaseModel):
    storage_dir: str | None = None


class RequestDetailQuery(BaseModel):
    request_id: str
    storage_dir: str | None = None


class RequestMikanConfigPayload(BaseModel):
    search_endpoint: str
    timeout_seconds: float = Field(gt=0)

    @field_validator("search_endpoint")
    @classmethod
    def validate_search_endpoint(cls, value: str) -> str:
        endpoint = value.strip()
        if not endpoint:
            raise ValueError("search_endpoint cannot be empty")
        return endpoint


class MikanCandidateSearchPayload(BaseModel):
    query: str
    mikan_config: RequestMikanConfigPayload | None = Field(
        default=None,
        validate_default=True,
    )

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        query = value.strip()
        if not query:
            raise ValueError("query cannot be empty")
        return query


class BatchParsePayload(BaseModel):
    raw_input: str
    mikan_config: RequestMikanConfigPayload | None = Field(
        default=None,
        validate_default=True,
    )


class BatchItemDescriptorPayload(BaseModel):
    """One batch card descriptor for the accept endpoint.

    ``request_id`` is present only when the card already has a saved Request
    (unsaved preview drafts are persisted through preview-save before accept).
    """

    item_id: str
    request_id: str | None = None
    title: str | None = None

    @field_validator("item_id")
    @classmethod
    def validate_item_id(cls, value: str) -> str:
        item_id = value.strip()
        if not item_id:
            raise ValueError("item_id cannot be empty")
        return item_id

    @field_validator("request_id")
    @classmethod
    def validate_request_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        request_id = value.strip()
        if not request_id:
            raise ValueError("request_id cannot be empty")
        return request_id


class BatchAcceptPayload(BaseModel):
    """Accept selected or all batch cards into the pre-submission queue.

    ``batch_id`` comes from the URL path; ``items`` describes the batch cards
    (the server never persists the parsed batch, so the client sends the cards
    it currently holds). ``item_ids`` optionally filters which cards are
    accepted (omit for accept-all, preserving batch order).
    """

    batch_id: str
    items: list[BatchItemDescriptorPayload]
    item_ids: list[str] | None = None
    storage_dir: str | None = None


class BatchQueueQuery(BaseModel):
    """Read a batch pre-submission queue (URL path + query args only)."""

    batch_id: str
    storage_dir: str | None = None


class BatchSubmitPayload(BaseModel):
    """Submit a batch queue to Auto Bangumi with explicit request-scoped config.

    ``ab_config`` is optional in the payload so the view can raise a Chinese
    ``validation_error`` envelope when it is missing (instead of the default
    English pydantic envelope); ``confirm`` is the explicit user confirmation
    field. Neither value is ever persisted into the queue storage.
    """

    batch_id: str
    ab_config: RequestAbConfigPayload | None = Field(default=None)
    confirm: bool = False
    storage_dir: str | None = None


class BatchRetryPayload(BatchSubmitPayload):
    """Retry a single FAILED/RETRYABLE queue item with explicit AB config.

    ``request_id`` selects the queue item to retry; only FAILED/RETRYABLE items
    are retried (already-SUCCEEDED items are skipped server-side). The request-
    scoped ``ab_config``/``confirm`` contract matches ``BatchSubmitPayload`` and
    is never persisted into the queue storage.
    """

    request_id: str


class BatchRecoverPayload(BaseModel):
    """Recover a stuck queue item (SUBMITTING / RESULT_PERSIST_FAILED).

    ``action`` selects the recovery mode: ``auto`` (only for SUBMITTING, uses a
    previously persisted AB result to finalize SUCCEEDED), ``succeeded``
    (manual confirmation that Auto Bangumi created the subscription), or
    ``failed`` (manual confirmation that it did not, turning the item into a
    normal retryable FAILED). Manual actions require ``confirm=True`` so a
    wrong click cannot silently mark a subscription as created.
    """

    batch_id: str
    request_id: str
    action: str
    confirm: bool = False
    storage_dir: str | None = None


class RequestCreatePayload(BaseModel):
    title: str
    source: str = "static-fixture"
    mikan_config: RequestMikanConfigPayload | None = Field(
        default=None,
        validate_default=True,
    )
    mikan_bangumi: str | None = None
    storage_dir: str | None = None
    save_request: bool = False

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("title cannot be empty")
        return title

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        source = value.strip()
        if source not in {"static-fixture", "mikan"}:
            raise ValueError("source must be static-fixture or mikan")
        return source

    @field_validator("mikan_bangumi")
    @classmethod
    def validate_mikan_bangumi(cls, value: str | None) -> str | None:
        if value is None:
            return None
        direct_entry = value.strip()
        if not direct_entry:
            raise ValueError("mikan_bangumi cannot be empty")
        return direct_entry


class RequestActionPayload(BaseModel):
    """Base payload for confirm/cancel/modify operations. `request_id` comes from URL path."""

    request_id: str
    storage_dir: str | None = None


class RequestCancelPayload(RequestActionPayload):
    cancel_reason: str | None = None


class RequestModifyPayload(RequestActionPayload):
    patch: dict[str, Any]


class RequestPreviewModifyPayload(BaseModel):
    """Recompute an unsaved preview request in memory (no persistence)."""

    request: dict[str, Any]
    patch: dict[str, Any]
    storage_dir: str | None = None


class RequestPreviewSavePayload(BaseModel):
    """Persist an unsaved, already-modified preview draft."""

    request: dict[str, Any]
    storage_dir: str | None = None


class RequestAbConfigPayload(BaseModel):
    endpoint: str
    token: str
    fallback_enabled: bool

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        endpoint = value.strip()
        if not endpoint:
            raise ValueError("endpoint cannot be empty")
        return endpoint

    @field_validator("token")
    @classmethod
    def validate_token(cls, value: str) -> str:
        token = value.strip()
        if not token:
            raise ValueError("token cannot be empty")
        return token


class RequestAbSubmitPayload(RequestActionPayload):
    ab_config: RequestAbConfigPayload


class QbittorrentConfigPayload(BaseModel):
    endpoint: str
    username: str
    password: str
    timeout_seconds: float = Field(gt=0)
    verify_tls: bool = True

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        endpoint = value.strip()
        if not endpoint:
            raise ValueError("endpoint cannot be empty")
        return endpoint

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        username = value.strip()
        if not username:
            raise ValueError("username cannot be empty")
        return username

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        password = value.strip()
        if not password:
            raise ValueError("password cannot be empty")
        return password


class QbittorrentTestConnectionPayload(BaseModel):
    qbittorrent_config: QbittorrentConfigPayload


def _storage_dir(value: str | None) -> Path | None:
    if value is None or not value.strip():
        return None
    return Path(value.strip())


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
    return FakeAnimeTitleParsingProvider()


def _serialize_batch_parse_result(
    item: BatchDraftItem,
    parse_result: AnimeTitleParseResult,
    *,
    candidates: list[dict[str, object]] | None = None,
    error: Stage1Error | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "item_id": item.item_id,
        "raw_title": item.raw_title,
        "status": item.status,
        "canonical_title_candidates": list(parse_result.canonical_title_candidates),
        "season_hint": parse_result.season_hint,
        "search_queries": list(parse_result.search_queries),
        "confidence": parse_result.confidence,
        "needs_user_review": parse_result.needs_user_review,
        "source": parse_result.source,
        "candidates": candidates or [],
    }
    if error is not None:
        result["error"] = _optional_error(error)
    return result


def _serialize_failed_batch_item(
    item: BatchDraftItem,
    error: Stage1Error,
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
        "candidates": [],
        "error": _optional_error(error),
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
    return {
        "bangumi_id": candidate.bangumi_id,
        "title": candidate.title,
        "mikan_url": candidate.mikan_url,
        "poster_url": candidate.poster_url,
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

    Mirrors ``RequestAcceptView.save``: load the PENDING_CONFIRM snapshot,
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

    Mirrors the single-item submit-ab storage contract
    (``RequestAbSubmitView.save`` + ``apply_request_save_action``): sanitize the
    AB result, attach it to the Request snapshot, persist the snapshot, and
    write ``ab_results/<request_id>.json`` so the Request detail API can read
    and show the result. Auto Bangumi secrets (endpoint/token/cookie/raw
    response) never reach the persisted data because the result was already
    normalized by the AB submit contract and is sanitized again here.
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
    and the final queue save can never leave READY_TO_SUBMIT on disk for an
    item that already reached Auto Bangumi. The queue only holds non-sensitive
    public fields, so writing it never stores Auto Bangumi secrets.
    """

    def persist_queue(queue: BatchSubmissionQueue) -> None:
        save_submission_queue(config, queue)

    return persist_queue


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


def _raise_qbittorrent_result_error(result: dict[str, Any]) -> None:
    error = result.get("error")
    if not isinstance(error, dict):
        raise Stage1Error(
            "qbittorrent_unexpected_response",
            "qBittorrent 响应无法识别",
            "test_qbittorrent_connection",
        )

    error_type = str(error.get("error_type") or "qbittorrent_unexpected_response")
    failed_step = str(error.get("failed_step") or "test_qbittorrent_connection")
    details = error.get("details")
    safe_details = (
        {
            key: value
            for key, value in details.items()
            if key in {"category", "field", "status_code"}
        }
        if isinstance(details, dict)
        else None
    )
    raise Stage1Error(
        error_type,
        _qbittorrent_error_message(error_type, str(error.get("error_message") or "")),
        failed_step,
        safe_details,
    )


def _qbittorrent_error_message(error_type: str, fallback: str) -> str:
    messages = {
        "config_error": fallback or "qBittorrent 配置无效",
        "qbittorrent_auth_failed": "qBittorrent 认证失败",
        "qbittorrent_timeout": "qBittorrent HTTP 请求超时",
        "qbittorrent_connection_failed": "qBittorrent HTTP 连接失败",
        "qbittorrent_http_failed": "qBittorrent HTTP 请求失败",
        "qbittorrent_unexpected_response": "qBittorrent 响应无法识别",
    }
    return messages.get(error_type, "qBittorrent 连接测试失败")


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


@web_blueprint.get("/")
def index_redirect() -> object:
    return redirect(url_for("migu_orca_web.index"))


@web_blueprint.get("/index")
def index() -> str:
    return render_template("migu_orca_web/index.html", active_page="index")


@web_blueprint.get("/Settings")
def settings_case_redirect() -> object:
    return redirect(url_for("migu_orca_web.settings"))


@web_blueprint.get("/settings")
def settings() -> str:
    return render_template("migu_orca_web/settings.html", active_page="settings")


@class_route(api_blueprint, "/api/v1/requests", methods=["GET"])
class RequestListView(GetView):
    request_validator_model = RequestListQuery

    def get_object(self) -> dict[str, list[dict[str, object]]]:
        assert isinstance(self.request_validator_model, RequestListQuery)
        config = load_storage_config(_storage_dir(self.request_validator_model.storage_dir))
        requests = [
            summarize_request(snapshot) for snapshot in list_request_snapshots(config)
        ]
        return {"requests": requests}


@class_route(api_blueprint, "/api/v1/requests/<path:request_id>", methods=["GET"])
class RequestDetailView(GetView):
    request_validator_model = RequestDetailQuery

    def get_object(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, RequestDetailQuery)
        config = load_storage_config(_storage_dir(self.request_validator_model.storage_dir))
        request_id = self.request_validator_model.request_id
        request = load_request_snapshot(config, request_id)
        return {
            "request": request,
            "history": _load_history_section(config, request_id),
            "ab_result": _load_ab_result_section(config, request_id),
        }


@class_route(api_blueprint, "/api/v1/requests", methods=["POST"])
class RequestCreateView(PostView):
    request_validator_model = RequestCreatePayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, RequestCreatePayload)
        payload = self.request_validator_model
        mikan_config = None
        if payload.source == "mikan":
            mikan_config = _resolve_mikan_config(payload.mikan_config)
        result = generate_request(
            EntryRequest(raw_title=payload.title),
            source_mode="mikan_http" if payload.source == "mikan" else "static_fixture",
            mikan_config=mikan_config,
            mikan_bangumi=payload.mikan_bangumi,
        )
        if not result["success"]:
            _raise_result_error(result)

        result = apply_request_save_action(
            result,
            payload.save_request,
            storage_dir=_storage_dir(payload.storage_dir),
        )
        if not result["success"]:
            _raise_result_error(result)

        request = result["request"]
        response: dict[str, object] = {
            "request": request,
            "summary": summarize_request(request),
        }
        if "saved_request" in result:
            response["saved_request"] = result["saved_request"]
        return response


@class_route(api_blueprint, "/api/v1/requests/preview-modify", methods=["POST"])
class RequestPreviewModifyView(PostView):
    request_validator_model = RequestPreviewModifyPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, RequestPreviewModifyPayload)
        payload = self.request_validator_model
        # The preview request is an in-memory generated draft (status
        # PENDING_CONFIRM but never written to storage). modify_request
        # recomputes per-source seed filters and the selected group's effective
        # seeds without saving, so the UI can show live seed updates before the
        # user decides to persist the draft.
        result = apply_modify_action(
            {"success": True, "request": payload.request, "error": None},
            payload.patch,
        )
        if not result["success"]:
            _raise_result_error(result)
        req = result["request"]
        return {"request": req, "summary": summarize_request(req)}


@class_route(api_blueprint, "/api/v1/requests/preview-save", methods=["POST"])
class RequestPreviewSaveView(PostView):
    request_validator_model = RequestPreviewSavePayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, RequestPreviewSavePayload)
        payload = self.request_validator_model
        request = payload.request
        # Only a PENDING_CONFIRM draft may be saved; this keeps the saved object
        # entering the existing confirmation flow (accept/cancel/modify/delete).
        if request.get("status") != PENDING_CONFIRM:
            raise Stage1Error(
                "invalid_request_status",
                "只有待确认的订阅草案可以保存",
                "save_preview_request",
                {"status": request.get("status")},
            )
        result = apply_request_save_action(
            {"success": True, "request": request, "error": None},
            True,
            storage_dir=_storage_dir(payload.storage_dir),
        )
        if not result["success"]:
            _raise_result_error(result)
        req = result["request"]
        response: dict[str, object] = {
            "request": req,
            "summary": summarize_request(req),
        }
        if "saved_request" in result:
            response["saved_request"] = result["saved_request"]
        return response


@class_route(api_blueprint, "/api/v1/mikan/candidates", methods=["POST"])
class MikanCandidateSearchView(PostView):
    request_validator_model = MikanCandidateSearchPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, MikanCandidateSearchPayload)
        payload = self.request_validator_model
        mikan_config = _resolve_mikan_config(payload.mikan_config)
        candidates = _search_mikan_candidates(payload.query, mikan_config)
        return {
            "query": payload.query,
            "candidates": candidates,
        }


@class_route(api_blueprint, "/api/v1/batches/parse", methods=["POST"])
class BatchParseView(PostView):
    request_validator_model = BatchParsePayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, BatchParsePayload)
        batch = create_batch_draft(self.request_validator_model.raw_input)
        if not batch.items:
            raise Stage1Error(
                "validation_error",
                "请至少输入一个番剧名称",
                "batch_parse",
                {"field": "raw_input"},
            )

        provider = _batch_title_parsing_provider()
        mikan_config = _resolve_mikan_config(self.request_validator_model.mikan_config)
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
                serialized_items.append(_serialize_failed_batch_item(failed_item, exc))
                continue

            try:
                candidates = _search_batch_item_candidates(
                    parse_result.search_queries,
                    mikan_config,
                )
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
                serialized_items.append(
                    _serialize_batch_parse_result(
                        failed_item,
                        parse_result,
                        candidates=[],
                        error=exc,
                    )
                )
                continue

            parsed_batch = update_batch_item_status(
                batch,
                item.item_id,
                BATCH_ITEM_STATUS_PARSED,
            )
            parsed_item = next(
                updated
                for updated in parsed_batch.items
                if updated.item_id == item.item_id
            )
            serialized_items.append(
                _serialize_batch_parse_result(
                    parsed_item,
                    parse_result,
                    candidates=candidates,
                )
            )

        return {
            "batch_id": batch.batch_id,
            "raw_input": batch.raw_input,
            "items": serialized_items,
        }


@class_route(api_blueprint, "/api/v1/batches/<batch_id>/accept", methods=["POST"])
class BatchAcceptView(PostView):
    request_validator_model = BatchAcceptPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, BatchAcceptPayload)
        payload = self.request_validator_model
        storage_dir = _storage_dir(payload.storage_dir)
        config = load_storage_config(storage_dir)

        existing_queue = _load_batch_queue_or_none(config, payload.batch_id)
        items = [
            BatchAcceptItem(
                item_id=item.item_id,
                request_id=item.request_id,
                title=item.title,
            )
            for item in payload.items
        ]
        result = accept_batch_items(
            batch_id=payload.batch_id,
            items=items,
            load_request=_build_batch_load_request(storage_dir),
            accept_one=_build_batch_accept_one(storage_dir),
            item_ids=payload.item_ids,
            queue=existing_queue,
        )
        # Persist the (possibly extended) queue so later queue-read/submit calls
        # observe the same items. The queue only holds non-sensitive public
        # fields, so writing it never stores Auto Bangumi secrets.
        save_submission_queue(config, result.queue)
        return serialize_batch_accept_result(result)


@class_route(api_blueprint, "/api/v1/batches/<batch_id>/queue", methods=["GET"])
class BatchQueueView(GetView):
    request_validator_model = BatchQueueQuery

    def get_object(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, BatchQueueQuery)
        payload = self.request_validator_model
        config = load_storage_config(_storage_dir(payload.storage_dir))
        queue = _load_batch_queue_or_none(config, payload.batch_id)
        return {
            "batch_id": payload.batch_id,
            "queue": serialize_queue(queue) if queue is not None else None,
        }


@class_route(api_blueprint, "/api/v1/batches/<batch_id>/submit", methods=["POST"])
class BatchSubmitView(PostView):
    request_validator_model = BatchSubmitPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, BatchSubmitPayload)
        payload = self.request_validator_model
        if payload.ab_config is None:
            raise Stage1Error(
                "validation_error",
                "请提供 Auto Bangumi 配置",
                "batch_submit",
                {"field": "ab_config"},
            )
        if not payload.confirm:
            raise Stage1Error(
                "validation_error",
                "请确认提交到 Auto Bangumi",
                "batch_submit",
                {"field": "confirm"},
            )

        storage_dir = _storage_dir(payload.storage_dir)
        config = load_storage_config(storage_dir)
        queue = load_submission_queue(config, payload.batch_id)
        ab_config = build_ab_config(payload.ab_config.model_dump())
        result = submit_batch_queue_items(
            batch_id=payload.batch_id,
            queue=queue,
            ab_config=ab_config,
            load_request=_build_batch_load_request(storage_dir),
            submit_one=compose_ab_submit_one(),
            persist_queue=_build_batch_persist_queue(config),
            persist_submit_result=_build_batch_persist_submit_result(storage_dir),
        )
        # Persist the updated queue so retries and queue reads observe the new
        # statuses/summaries. The request-scoped ab_config is never stored; the
        # service already flushed each item's SUBMITTING and final status before
        # returning, so a crash mid-batch cannot resurrect READY_TO_SUBMIT.
        save_submission_queue(config, result.queue)
        return serialize_batch_submit_result(result)


@class_route(api_blueprint, "/api/v1/batches/<batch_id>/retry", methods=["POST"])
class BatchRetryView(PostView):
    request_validator_model = BatchRetryPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, BatchRetryPayload)
        payload = self.request_validator_model
        if payload.ab_config is None:
            raise Stage1Error(
                "validation_error",
                "请提供 Auto Bangumi 配置",
                "batch_retry",
                {"field": "ab_config"},
            )
        if not payload.confirm:
            raise Stage1Error(
                "validation_error",
                "请确认提交到 Auto Bangumi",
                "batch_retry",
                {"field": "confirm"},
            )

        storage_dir = _storage_dir(payload.storage_dir)
        config = load_storage_config(storage_dir)
        queue = load_submission_queue(config, payload.batch_id)
        ab_config = build_ab_config(payload.ab_config.model_dump())
        try:
            result = retry_batch_queue_item(
                batch_id=payload.batch_id,
                queue=queue,
                request_id=payload.request_id,
                ab_config=ab_config,
                load_request=_build_batch_load_request(storage_dir),
                submit_one=compose_ab_submit_one(),
                persist_queue=_build_batch_persist_queue(config),
                persist_submit_result=_build_batch_persist_submit_result(storage_dir),
            )
        except ValueError as exc:
            raise Stage1Error(
                "queue_item_not_found",
                "队列中不存在该订阅方案项目",
                "batch_retry",
                {"field": "request_id", "batch_id": payload.batch_id},
            ) from exc
        # Persist the updated queue so queue reads observe the retried status.
        # The request-scoped ab_config is never stored.
        save_submission_queue(config, result.queue)
        return serialize_batch_submit_result(result)


@class_route(api_blueprint, "/api/v1/batches/<batch_id>/recover", methods=["POST"])
class BatchRecoverView(PostView):
    request_validator_model = BatchRecoverPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, BatchRecoverPayload)
        payload = self.request_validator_model
        if payload.action not in {"auto", "succeeded", "failed"}:
            raise Stage1Error(
                "validation_error",
                "恢复动作必须是 auto、succeeded 或 failed",
                "batch_recover",
                {"field": "action"},
            )
        if payload.action != "auto" and not payload.confirm:
            raise Stage1Error(
                "validation_error",
                "请确认人工核验结果后再恢复",
                "batch_recover",
                {"field": "confirm"},
            )

        storage_dir = _storage_dir(payload.storage_dir)
        config = load_storage_config(storage_dir)
        queue = load_submission_queue(config, payload.batch_id)
        try:
            result = recover_batch_queue_item(
                batch_id=payload.batch_id,
                queue=queue,
                request_id=payload.request_id,
                action=payload.action,
                load_request=_build_batch_load_request(storage_dir),
                persist_queue=_build_batch_persist_queue(config),
            )
        except ValueError as exc:
            raise Stage1Error(
                "queue_item_not_found",
                "队列中不存在该订阅方案项目",
                "batch_recover",
                {"field": "request_id", "batch_id": payload.batch_id},
            ) from exc
        # Persist the recovered queue so queue reads observe the new status.
        save_submission_queue(config, result.queue)
        return serialize_batch_submit_result(result)


@class_route(api_blueprint, "/api/v1/requests/<path:request_id>/accept", methods=["POST"])
class RequestAcceptView(PostView):
    request_validator_model = RequestActionPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, RequestActionPayload)
        payload = self.request_validator_model
        config = load_storage_config(_storage_dir(payload.storage_dir))
        request = load_request_snapshot(config, payload.request_id)

        result = apply_confirmation_action(
            {"success": True, "request": request, "error": None},
            "accept",
        )
        if not result["success"]:
            _raise_result_error(result)

        history_event = _build_history_event(
            request, result["request"], action="ACCEPT",
        )
        result = apply_request_save_action(
            result,
            True,
            storage_dir=_storage_dir(payload.storage_dir),
            history_events=[history_event],
        )
        if not result["success"]:
            _raise_result_error(result)

        req = result["request"]
        response: dict[str, object] = {
            "request": req,
            "summary": summarize_request(req),
        }
        if "saved_request" in result:
            response["saved_request"] = result["saved_request"]
        return response


@class_route(api_blueprint, "/api/v1/requests/<path:request_id>/cancel", methods=["POST"])
class RequestCancelView(PostView):
    request_validator_model = RequestCancelPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, RequestCancelPayload)
        payload = self.request_validator_model
        config = load_storage_config(_storage_dir(payload.storage_dir))
        request = load_request_snapshot(config, payload.request_id)

        cancel_reason = payload.cancel_reason or "用户取消"
        result = apply_confirmation_action(
            {"success": True, "request": request, "error": None},
            "cancel",
            cancel_reason=cancel_reason,
        )
        if not result["success"]:
            _raise_result_error(result)

        history_event = _build_history_event(
            request, result["request"],
            action="CANCEL",
            details=_confirmation_history_details("cancel", cancel_reason),
        )
        result = apply_request_save_action(
            result,
            True,
            storage_dir=_storage_dir(payload.storage_dir),
            history_events=[history_event],
        )
        if not result["success"]:
            _raise_result_error(result)

        req = result["request"]
        response: dict[str, object] = {
            "request": req,
            "summary": summarize_request(req),
        }
        if "saved_request" in result:
            response["saved_request"] = result["saved_request"]
        return response


@class_route(api_blueprint, "/api/v1/requests/<path:request_id>/modify", methods=["POST"])
class RequestModifyView(PostView):
    request_validator_model = RequestModifyPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, RequestModifyPayload)
        payload = self.request_validator_model
        config = load_storage_config(_storage_dir(payload.storage_dir))
        request = load_request_snapshot(config, payload.request_id)

        result = apply_modify_action(
            {"success": True, "request": request, "error": None},
            payload.patch,
        )
        if not result["success"]:
            _raise_result_error(result)

        history_event = _build_history_event(
            request, result["request"],
            action="MODIFY",
            details={"patch": payload.patch},
        )
        result = apply_request_save_action(
            result,
            True,
            storage_dir=_storage_dir(payload.storage_dir),
            history_events=[history_event],
        )
        if not result["success"]:
            _raise_result_error(result)

        req = result["request"]
        response: dict[str, object] = {
            "request": req,
            "summary": summarize_request(req),
        }
        if "saved_request" in result:
            response["saved_request"] = result["saved_request"]
        return response


@class_route(api_blueprint, "/api/v1/requests/<path:request_id>/delete", methods=["POST"])
class RequestDeleteView(PostView):
    request_validator_model = RequestActionPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, RequestActionPayload)
        payload = self.request_validator_model
        config = load_storage_config(_storage_dir(payload.storage_dir))
        return delete_request_snapshot(config, payload.request_id)


@class_route(api_blueprint, "/api/v1/requests/<path:request_id>/submit-ab", methods=["POST"])
class RequestAbSubmitView(PostView):
    request_validator_model = RequestAbSubmitPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, RequestAbSubmitPayload)
        payload = self.request_validator_model
        storage_dir = _storage_dir(payload.storage_dir)
        config = load_storage_config(storage_dir)
        request = load_request_snapshot(config, payload.request_id)
        ab_config = build_ab_config(payload.ab_config.model_dump())

        result = apply_ab_submit_action(
            {"success": True, "request": request, "error": None},
            True,
            ab_config=ab_config,
        )
        if not result["success"]:
            _raise_result_error(result)

        result["ab_submit_result"] = _sanitize_ab_submit_result(
            result["ab_submit_result"]
        )
        result["request"]["ab_submit_result"] = result["ab_submit_result"]
        result = apply_request_save_action(
            result,
            True,
            storage_dir=storage_dir,
        )
        if not result["success"]:
            _raise_result_error(result)

        req = result["request"]
        response: dict[str, object] = {
            "request": req,
            "summary": summarize_request(req),
            "ab_submit_result": result["ab_submit_result"],
        }
        if "saved_request" in result:
            response["saved_request"] = result["saved_request"]
        if "saved_ab_result" in result:
            response["saved_ab_result"] = result["saved_ab_result"]
        return response


@class_route(api_blueprint, "/api/v1/qbittorrent/test-connection", methods=["POST"])
class QbittorrentTestConnectionView(PostView):
    request_validator_model = QbittorrentTestConnectionPayload

    def save(self) -> dict[str, object]:
        assert isinstance(
            self.request_validator_model,
            QbittorrentTestConnectionPayload,
        )
        qbittorrent_config = build_qbittorrent_config(
            self.request_validator_model.qbittorrent_config.model_dump()
        )
        result = test_qbittorrent_connection(qbittorrent_config=qbittorrent_config)
        if not result["success"]:
            _raise_qbittorrent_result_error(result)
        summary = result["summary"]
        assert isinstance(summary, dict)
        return _sanitize_qbittorrent_connection_summary(summary)
