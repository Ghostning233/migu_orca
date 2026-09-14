from __future__ import annotations

import ipaddress
import os
import re
from urllib.parse import urlsplit

from flask import Flask, Response, current_app, request
from werkzeug.exceptions import SecurityError

from apps.registry import ALL_BLUEPRINTS
from extensions.flask_api.api import failed_response


def _canonical_origin(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except (AttributeError, ValueError):
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not host or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        return None
    try:
        valid = bool(ipaddress.ip_address(host))
    except ValueError:
        valid = bool(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*", host))
    if not valid:
        return None
    scheme = parsed.scheme.lower()
    effective_port = port or (443 if scheme == "https" else 80)
    if not 1 <= effective_port <= 65535:
        return None
    host_text = host.lower()
    if ":" in host_text:
        host_text = f"[{host_text}]"
    return f"{scheme}://{host_text}:{effective_port}"


def _canonical_host(value: str) -> str | None:
    if not value or any(ch.isspace() for ch in value) or "@" in value or "/" in value or "://" in value or value == "*":
        return None
    if value.startswith("["):
        candidate = f"http://{value}"
    elif value.count(":") > 1:
        candidate = f"http://[{value}]"
    else:
        candidate = f"http://{value}"
    try:
        parsed = urlsplit(candidate)
        host = parsed.hostname
        _ = parsed.port
    except (AttributeError, ValueError):
        return None
    if not host:
        return None
    try:
        valid = bool(ipaddress.ip_address(host))
    except ValueError:
        valid = bool(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*", host))
    if not valid:
        return None
    return f"[{host.lower()}]" if ":" in host else host.lower()


def create_app(config_name: str | None = None) -> Flask:
    """Create the MiGuOrca Flask application."""

    app = Flask("migu_orca")
    app.config["CONFIG_NAME"] = config_name
    trusted_hosts = ["localhost", "127.0.0.1", "[::1]"]
    for candidate in os.environ.get("MIGU_ORCA_TRUSTED_HOSTS", "").split(","):
        candidate = candidate.strip()
        if candidate and _canonical_host(candidate):
            trusted_hosts.append(candidate)
    canonical_trusted_hosts = {_canonical_host(host) for host in trusted_hosts}
    app.config["TRUSTED_HOSTS"] = list(dict.fromkeys(trusted_hosts))
    app.config["MIGU_ORCA_CANONICAL_TRUSTED_HOSTS"] = {host for host in canonical_trusted_hosts if host}
    trusted_origins: set[str] = set()
    for candidate in os.environ.get("MIGU_ORCA_TRUSTED_ORIGINS", "").split(","):
        candidate = _canonical_origin(candidate.strip())
        if candidate:
            trusted_origins.add(candidate)
    app.config["MIGU_ORCA_TRUSTED_ORIGINS"] = trusted_origins
    if config_name in {"test", "testing"}:
        app.config["TESTING"] = True

    @app.before_request
    def _protect_settings_io() -> object | None:
        if request.path.startswith("/api/v1/") and _canonical_host(request.host) not in current_app.config["MIGU_ORCA_CANONICAL_TRUSTED_HOSTS"]:
            return failed_response("untrusted_host", "请求主机不受信任")
        if not request.path.startswith("/api/v1/settings/autobangumi"):
            return None
        origin = request.headers.get("Origin")
        if origin:
            try:
                request_origin = _canonical_origin(f"{request.scheme}://{request.host}")
                normalized_origin = _canonical_origin(origin)
                same_origin = normalized_origin is not None and normalized_origin == request_origin
                explicit_origin = normalized_origin in current_app.config["MIGU_ORCA_TRUSTED_ORIGINS"]
                if normalized_origin is None or not (same_origin or explicit_origin):
                    return failed_response("untrusted_origin", "请求来源不受信任")
            except ValueError:
                return failed_response("untrusted_origin", "请求来源不受信任")
        if request.method in {"PUT", "DELETE"} and request.mimetype != "application/json":
            return failed_response("validation_error", "请求必须使用 application/json")
        return None

    @app.errorhandler(SecurityError)
    def _settings_security_error(error: SecurityError) -> Response:
        # Flask's trusted-host check runs before ``before_request`` and would
        # otherwise emit an HTML error containing the attacker-controlled Host.
        if request.path.startswith("/api/v1/"):
            return failed_response("untrusted_host", "请求主机不受信任")
        return error

    @app.errorhandler(405)
    @app.errorhandler(400)
    def _api_method_not_found(error: object) -> Response | object:
        # API retirement and path readers must not expose method capabilities.
        # Treat unsupported methods as unknown resources at the HTTP boundary.
        if request.path.startswith("/api/v1/") and request.path.endswith("/submit-ab"):
            return Response(status=404)
        return error

    @app.after_request
    def _settings_no_store(response: Response) -> Response:
        if request.path.startswith("/api/v1/settings/autobangumi"):
            response.headers["Cache-Control"] = "no-store"
        return response

    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint)

    return app
