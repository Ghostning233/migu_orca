from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from functools import wraps
from typing import Any

from flask import Blueprint, Response, current_app, jsonify
from flask.views import MethodView
from pydantic import ValidationError

from extensions.flask_api.exceptions import APIException
from shared.errors import Stage1Error

_ABSOLUTE_PATH_RE = re.compile(r"(?<!\w)(?:/[^\s<>'\"]+)+")
_URL_RE = re.compile(r"https?://[^\s<>'\"]+")
_TOKEN_RE = re.compile(
    r"(?i)(token|secret|cookie|authorization|password|passwd|bearer|username|sid|session)"
)
# Redacts "key=value" / "key: value" pairs where the key names a sensitive
# value, so the secret value itself cannot survive inside a plain string.
_SENSITIVE_KEY_VALUE_RE = re.compile(
    r"(?i)\b(?:token|secret|cookie|authorization|password|passwd|bearer|"
    r"username|sid|session|endpoint|rss_url)\s*[=:]\s*[^\s,;]+"
)
# Redacts a sensitive keyword followed by a space-separated value (e.g.
# "Bearer abc123") — replacing only the keyword would leave the raw value.
_SENSITIVE_WORD_VALUE_RE = re.compile(
    r"(?i)\b(?:token|secret|cookie|authorization|password|passwd|bearer|"
    r"username|sid|session)\s+[^\s,;'\"<>]+"
)

# HTTP status classification for Stage1Error error types (US-192).
#
# The JSON envelope stays byte-for-byte compatible ({ok, error_type,
# error_message, error_data}); only the HTTP status becomes semantically
# meaningful. Classification is centralized here so the routes never hard-code
# status codes and the OpenAPI registry in openapi_gen.py stays the single
# documented source of truth.
#
# 400 — client input/state is unusable as sent (validation, unknown field,
#       unsupported value, bad request_id/batch_id, unknown queue item).
_HTTP_BAD_REQUEST_ERROR_TYPES = {
    "validation_error",
    "data_validation_errors",
    "invalid_modify_patch",
    "invalid_modify_patch_field",
    "invalid_ab_response",
    "invalid_ab_payload",
    "invalid_ab_submit_result",
    "invalid_batch_id",
    "invalid_confirmation_action",
    "invalid_input",
    "invalid_request_id",
    "invalid_seed_count",
    "invalid_poster",
    "invalid_poster_key",
    "invalid_cancel_reason",
    "invalid_storage_dir",
    "queue_not_found",
    "config_error",
}
# 404 — the addressed resource does not exist.
_HTTP_NOT_FOUND_ERROR_TYPES = {
    "request_not_found",
    "poster_not_found",
    "queue_item_not_found",
}
# 409 — the request conflicts with the current server state (replay/expired/
#       stale/status conflict). US-194 draft-store failures (draft_expired,
#       draft_evicted, draft_replayed, draft_mismatch) land here too; US-212
#       adds draft_reserved (a save-in-progress owns the draft).
_HTTP_CONFLICT_ERROR_TYPES = {
    "invalid_request_status",
    "request_cancelled",
    "season_evidence_conflict",
    "season_confirmation_required",
    "candidate_context_invalid",
    "draft_expired",
    "draft_evicted",
    "draft_replayed",
    "draft_mismatch",
    "draft_revision_conflict",
    "draft_reserved",
    "idempotency_conflict",
}
# 401 — authentication against the external service failed.
_HTTP_UNAUTHORIZED_ERROR_TYPES = {
    "ab_auth_failed",
    "qbittorrent_auth_failed",
}
# 502 — the upstream (MiKan/AutoBangumi/qBittorrent) is reachable but
#       unhealthy (connection refused, HTTP 5xx, bad gateway).
_HTTP_BAD_GATEWAY_ERROR_TYPES = {
    "mikan_http_failed",
    "mikan_connection_failed",
    "mikan_parse_failed",
    "mikan_search_failed",
    "poster_unavailable",
    "ab_connection_failed",
    "ab_http_failed",
    "ab_submit_failed",
    "qbittorrent_connection_failed",
    "qbittorrent_http_failed",
    "qbittorrent_unexpected_response",
}
# 503 — the upstream is unavailable or the client version is unsupported.
_HTTP_SERVICE_UNAVAILABLE_ERROR_TYPES = {
    "ab_unsupported_version",
    "ab_submit_unsupported",
    "ab_probe_unsupported",
}
# 504 — the upstream timed out (retryable, distinct from a permanent 502).
_HTTP_GATEWAY_TIMEOUT_ERROR_TYPES = {
    "mikan_timeout",
    "ab_timeout",
    "qbittorrent_timeout",
}


def _error_http_status(error_type: str) -> int:
    """Map a Stage1Error error_type to a stable HTTP status (default 400)."""
    if not error_type:
        return 400
    lowered = error_type.lower()
    if lowered in _HTTP_GATEWAY_TIMEOUT_ERROR_TYPES:
        return 504
    if lowered in _HTTP_SERVICE_UNAVAILABLE_ERROR_TYPES:
        return 503
    if lowered in _HTTP_BAD_GATEWAY_ERROR_TYPES:
        return 502
    if lowered in _HTTP_UNAUTHORIZED_ERROR_TYPES:
        return 401
    if lowered in _HTTP_CONFLICT_ERROR_TYPES:
        return 409
    if lowered in _HTTP_NOT_FOUND_ERROR_TYPES:
        return 404
    if lowered in _HTTP_BAD_REQUEST_ERROR_TYPES or lowered.startswith("invalid_"):
        return 400
    # Unknown error types default to 400 so a new Stage1Error still gets a
    # client-visible 4xx rather than an unexpected 500.
    if lowered in {
        "storage_error",
        "storage_json_error",
        "internal_server_error",
    }:
        return 500
    return 400


def ok_response(result: Any) -> Response:
    """Return the shared successful API envelope."""

    return jsonify({"ok": True, "result": result})


def failed_response(
    error_type: str,
    error_message: str,
    error_data: dict[str, Any] | list[Any] | None = None,
    status: int | None = None,
) -> Response:
    """Return the shared failed API envelope.

    ``status`` defaults to the US-192 HTTP classification for ``error_type``;
    pass an explicit status (e.g. 404 for the binary poster endpoint) only when
    the error type alone cannot express the semantic. The returned Response
    always carries the mapped status code.
    """

    body: dict[str, Any] = {
        "ok": False,
        "error_type": error_type,
        "error_message": _sanitize_string(error_message),
    }
    if error_data is not None:
        body["error_data"] = sanitize_error_data(error_data)
    response = jsonify(body)
    response.status_code = status if status is not None else _error_http_status(error_type)
    return response


def route(
    blueprint: Blueprint,
    rule: str,
    **options: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a function view that returns the shared API envelope."""

    def wrapper(view: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view)
        def decorator(*args: Any, **kwargs: Any) -> Response:
            try:
                result = view(*args, **kwargs)
            except Exception as exception:
                return handle_exception(view.__name__, exception)
            if isinstance(result, Response):
                return result
            return ok_response(result)

        endpoint = options.pop("endpoint", decorator.__name__)
        blueprint.add_url_rule(rule, endpoint, view_func=decorator, **options)
        return decorator

    return wrapper


def class_route(
    blueprint: Blueprint,
    rule: str,
    **options: Any,
) -> Callable[[type[MethodView]], type[MethodView]]:
    """Register a class-based view."""

    def decorator(view: type[MethodView]) -> type[MethodView]:
        view_func = view.as_view(view.__name__)
        blueprint.add_url_rule(rule, view.__name__, view_func=view_func, **options)
        return view

    return decorator


def handle_exception(view_name: str, exception: Exception) -> Response:
    """Convert expected API exceptions into the shared JSON envelope.

    The envelope shape is unchanged (US-189 golden contract); US-192 makes the
    HTTP status carry the stable failure semantics:
    400 validation/client error, 404 missing resource, 409 conflict/replay,
    401 external auth failure, 502 upstream bad gateway, 503 upstream
    unavailable/unsupported, 504 upstream timeout, 500 unknown error.
    """

    if isinstance(exception, ValidationError):
        errors = [
            {
                "error_type": "validation_error",
                "field": ".".join(str(part) for part in error["loc"]) or "_schema",
                "message": _sanitize_string(error["msg"]),
            }
            for error in exception.errors()
        ]
        return failed_response(
            "data_validation_errors",
            "Data has validation errors",
            {"errors": errors},
            status=400,
        )

    if isinstance(exception, Stage1Error):
        error_data: dict[str, Any] = {"failed_step": exception.failed_step}
        if exception.details:
            error_data["details"] = exception.details
        return failed_response(
            exception.error_type,
            exception.message,
            error_data,
            status=_error_http_status(exception.error_type),
        )

    if isinstance(exception, APIException):
        return failed_response(
            exception.error_type,
            exception.error_message,
            exception.error_data,
            status=_error_http_status(exception.error_type),
        )

    if current_app.config.get("TESTING") or current_app.config.get("DEBUG"):
        raise exception

    current_app.logger.exception("Unhandled API error in %s", view_name)
    return failed_response("internal_server_error", "A server error occurred.", status=500)


class APIBaseView(MethodView):
    """MethodView base that converts exceptions into the shared API envelope."""

    def dispatch_request(self, *args: Any, **kwargs: Any) -> Response:
        try:
            result = super().dispatch_request(*args, **kwargs)
        except Exception as exception:
            return handle_exception(self.__class__.__name__, exception)
        if isinstance(result, Response):
            return result
        return ok_response(result)


def sanitize_error_data(value: Any) -> Any:
    """Remove sensitive or overly specific values before returning errors."""

    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _TOKEN_RE.search(key_text):
                sanitized[key_text] = "[redacted]"
            else:
                sanitized[key_text] = sanitize_error_data(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_error_data(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_error_data(item) for item in value]
    if isinstance(value, str):
        return _sanitize_string(value)
    return value


def _sanitize_string(value: str) -> str:
    sanitized = _URL_RE.sub("[redacted-url]", value)
    sanitized = _ABSOLUTE_PATH_RE.sub("[redacted-path]", sanitized)
    # Keyword + space-separated value FIRST (so "Bearer abc123" is swallowed as
    # one unit), then "key=value"/"key: value" pairs — the reverse order would
    # let the pair regex consume the keyword and leave the raw value behind.
    sanitized = _SENSITIVE_WORD_VALUE_RE.sub("[redacted]", sanitized)
    sanitized = _SENSITIVE_KEY_VALUE_RE.sub("[redacted]", sanitized)
    if "<rss" in sanitized.lower() or "<html" in sanitized.lower():
        return "[redacted-content]"
    if _TOKEN_RE.search(sanitized):
        return _TOKEN_RE.sub("[redacted]", sanitized)
    return sanitized
