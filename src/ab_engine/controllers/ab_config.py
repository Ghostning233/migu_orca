from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from shared.errors import Stage1Error


@dataclass(frozen=True, repr=False)
class AutoBangumiConfig:
    """Request-scoped AutoBangumi credentials and service root."""

    base_url: str
    auth_mode: Literal["password", "api_token"]
    fallback_enabled: bool
    username: str | None = None
    password: str | None = None
    token: str | None = None

    def __repr__(self) -> str:
        """Never put credentials (or the service root) in debug output."""

        return (
            "AutoBangumiConfig("
            f"auth_mode={self.auth_mode!r}, fallback_enabled={self.fallback_enabled!r}, "
            f"credential_present={self.username is not None or self.token is not None}"
            ")"
        )


def build_ab_config(data: dict[str, Any]) -> AutoBangumiConfig:
    """Validate an explicit request-scoped AutoBangumi configuration object."""

    auth_mode = data.get("auth_mode", "password")
    if auth_mode not in ("password", "api_token"):
        _config_error("auth_mode")
    base_url = _service_root(data.get("base_url"))
    fallback_enabled = data.get("fallback_enabled")
    if not isinstance(fallback_enabled, bool):
        _config_error("fallback_enabled")

    common_fields = {"auth_mode", "base_url", "fallback_enabled"}
    mode_fields = {"username", "password"} if auth_mode == "password" else {"token"}
    if set(data) - common_fields - mode_fields:
        _config_error("auth_mode")

    if auth_mode == "password":
        return AutoBangumiConfig(
            base_url=base_url,
            auth_mode="password",
            username=_required_secret_string(data.get("username"), "username"),
            password=_required_secret_string(data.get("password"), "password"),
            fallback_enabled=fallback_enabled,
        )
    return AutoBangumiConfig(
        base_url=base_url,
        auth_mode="api_token",
        token=_required_secret_string(data.get("token"), "token"),
        fallback_enabled=fallback_enabled,
    )


def load_ab_config(path: Path) -> AutoBangumiConfig:
    """Load AutoBangumi config from an explicit JSON path (CLI only)."""

    data = _read_json(path)
    if not isinstance(data, dict):
        raise Stage1Error(
            "config_error",
            "Auto Bangumi 配置必须是 JSON 对象",
            "load_ab_config",
        )

    return build_ab_config(data)


def normalize_service_root(value: Any, *, failed_step: str = "load_ab_config") -> str:
    if not isinstance(value, str) or not value.strip():
        _config_error("base_url", failed_step)
    raw = value.strip()
    if len(raw) > 2048:
        _config_error("base_url", failed_step)
    if any(ord(character) < 32 or ord(character) == 127 for character in raw) or any(character.isspace() or character == "\\" for character in raw):
        _config_error("base_url", failed_step)

    # The Web settings form accepts the convenient LAN form ``host:port``.
    # It is deliberately not allowed to omit the port when the scheme is also
    # omitted: accepting a bare hostname makes a typo look like a service root.
    bare_host_port = re.fullmatch(r"(?:\[[0-9A-Fa-f:]+\]|[A-Za-z0-9.-]+):[0-9]+", raw)
    # A URI-like ``scheme:value`` is not a bare host/port.  In particular,
    # values such as ``mailto:80`` and ``ftp:80`` must not be reinterpreted as
    # an HTTP service merely because the port happens to be numeric.
    if bare_host_port and raw.split(":", 1)[0].lower() in {"ftp", "ftps", "mailto", "file", "javascript"}:
        _config_error("base_url", failed_step)
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", raw) and "://" not in raw and not bare_host_port:
        _config_error("base_url", failed_step)
    has_scheme = "://" in raw
    candidate = raw if has_scheme else f"http://{raw}"
    try:
        parsed = urlsplit(candidate)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        _config_error("base_url", failed_step)
    if not has_scheme and port is None:
        _config_error("base_url", failed_step)
    if hostname is None or not hostname.strip():
        _config_error("base_url", failed_step)
    try:
        ipaddress.ip_address(hostname.strip("[]"))
        valid_host = True
    except ValueError:
        valid_host = bool(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*", hostname))
    if not valid_host:
        _config_error("base_url", failed_step)
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or hostname is None
        or not hostname.strip()
        or (port is not None and not 1 <= port <= 65535)
    ):
        _config_error("base_url", failed_step)

    normalized_host = hostname.lower()
    if ":" in normalized_host and not normalized_host.startswith("["):
        normalized_host = f"[{normalized_host}]"
    normalized_netloc = normalized_host
    if port is not None:
        normalized_netloc += f":{port}"
    return urlunsplit((parsed.scheme.lower(), normalized_netloc, "", "", ""))


def _service_root(value: Any) -> str:
    return normalize_service_root(value)


def _required_secret_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _config_error(field)
    return value.strip()


def _config_error(field: str, failed_step: str = "load_ab_config") -> None:
    raise Stage1Error(
        "config_error", "Auto Bangumi 配置无效", failed_step, {"field": field}
    )


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise Stage1Error(
            "config_error",
            "Auto Bangumi 配置文件不存在",
            "load_ab_config",
        ) from exc
    except json.JSONDecodeError as exc:
        raise Stage1Error(
            "config_error",
            "Auto Bangumi 配置不是合法 JSON",
            "load_ab_config",
        ) from exc
    except OSError as exc:
        raise Stage1Error(
            "config_error",
            "无法读取 Auto Bangumi 配置",
            "load_ab_config",
        ) from exc
