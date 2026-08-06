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
_TOKEN_RE = re.compile(r"(?i)(token|secret|cookie|authorization|password|passwd|bearer)")


def ok_response(result: Any) -> Response:
    """Return the shared successful API envelope."""

    return jsonify({"ok": True, "result": result})


def failed_response(
    error_type: str,
    error_message: str,
    error_data: dict[str, Any] | list[Any] | None = None,
) -> Response:
    """Return the shared failed API envelope."""

    body: dict[str, Any] = {
        "ok": False,
        "error_type": error_type,
        "error_message": _sanitize_string(error_message),
    }
    if error_data is not None:
        body["error_data"] = sanitize_error_data(error_data)
    return jsonify(body)


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
    """Convert expected API exceptions into the shared JSON envelope."""

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
        )

    if isinstance(exception, Stage1Error):
        error_data: dict[str, Any] = {"failed_step": exception.failed_step}
        if exception.details:
            error_data["details"] = exception.details
        return failed_response(exception.error_type, exception.message, error_data)

    if isinstance(exception, APIException):
        return failed_response(
            exception.error_type,
            exception.error_message,
            exception.error_data,
        )

    if current_app.config.get("TESTING") or current_app.config.get("DEBUG"):
        raise exception

    current_app.logger.exception("Unhandled API error in %s", view_name)
    return failed_response("internal_server_error", "A server error occurred.")


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
    if "<rss" in sanitized.lower() or "<html" in sanitized.lower():
        return "[redacted-content]"
    if _TOKEN_RE.search(sanitized):
        return _TOKEN_RE.sub("[redacted]", sanitized)
    return sanitized
