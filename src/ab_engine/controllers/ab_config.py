from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from shared.errors import Stage1Error


@dataclass(frozen=True)
class AutoBangumiConfig:
    """Request-scoped AutoBangumi credentials and service root."""

    base_url: str
    auth_mode: Literal["password", "api_token"]
    fallback_enabled: bool
    username: str | None = None
    password: str | None = None
    token: str | None = None


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


def _service_root(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        _config_error("base_url")
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        _config_error("base_url")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def _required_secret_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _config_error(field)
    return value.strip()


def _config_error(field: str) -> None:
    raise Stage1Error(
        "config_error", "Auto Bangumi 配置无效", "load_ab_config", {"field": field}
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
