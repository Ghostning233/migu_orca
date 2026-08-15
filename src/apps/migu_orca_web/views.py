from __future__ import annotations

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
)
from storage_engine.controllers.ab_result_repository import load_ab_submit_result
from storage_engine.controllers.history_repository import load_status_history
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


def _raise_result_error(result: dict[str, Any]) -> None:
    error = result.get("error")
    if not isinstance(error, dict):
        raise Stage1Error(
            "unexpected_error",
            "Request API 操作失败",
            "migu_orca_web_api",
        )
    details = error.get("details")
    raise Stage1Error(
        str(error.get("error_type") or "unexpected_error"),
        str(error.get("error_message") or "Request API 操作失败"),
        str(error.get("failed_step") or "migu_orca_web_api"),
        details if isinstance(details, dict) else None,
    )


def _optional_error(error: Stage1Error) -> dict[str, object]:
    return {
        "error_type": error.error_type,
        "error_message": error.message,
        "failed_step": error.failed_step,
        "details": error.details or {},
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
    blocked = ("token", "secret", "cookie", "authorization", "password", "passwd", "bearer")
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
