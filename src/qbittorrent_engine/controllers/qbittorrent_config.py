from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shared.errors import Stage1Error


@dataclass(frozen=True)
class QBittorrentConfig:
    """Explicit config required before testing a qBittorrent connection."""

    endpoint: str
    username: str
    password: str
    timeout_seconds: float
    verify_tls: bool = True


def build_qbittorrent_config(data: dict[str, Any]) -> QBittorrentConfig:
    """Build qBittorrent config from an explicit object."""

    endpoint = data.get("endpoint")
    username = data.get("username")
    password = data.get("password")
    timeout_seconds = data.get("timeout_seconds")
    verify_tls = data.get("verify_tls", True)

    if not isinstance(endpoint, str) or not endpoint.strip():
        raise _field_error("endpoint", "qBittorrent endpoint 必须是非空字符串")
    if not isinstance(username, str) or not username.strip():
        raise _field_error("username", "qBittorrent username 必须是非空字符串")
    if not isinstance(password, str) or not password.strip():
        raise _field_error("password", "qBittorrent password 必须是非空字符串")
    if not isinstance(timeout_seconds, int | float) or timeout_seconds <= 0:
        raise _field_error("timeout_seconds", "qBittorrent timeout_seconds 必须是正数")
    if not isinstance(verify_tls, bool):
        raise _field_error("verify_tls", "qBittorrent verify_tls 必须是布尔值")

    return QBittorrentConfig(
        endpoint=endpoint.strip(),
        username=username.strip(),
        password=password.strip(),
        timeout_seconds=float(timeout_seconds),
        verify_tls=verify_tls,
    )


def load_qbittorrent_config(path: Path) -> QBittorrentConfig:
    """Load qBittorrent config from a caller-provided JSON path."""

    data = _read_json(path)
    if not isinstance(data, dict):
        raise Stage1Error(
            "config_error",
            "qBittorrent 配置必须是 JSON 对象",
            "load_qbittorrent_config",
        )

    return build_qbittorrent_config(data)


def _field_error(field: str, message: str) -> Stage1Error:
    return Stage1Error(
        "config_error",
        message,
        "load_qbittorrent_config",
        {"field": field},
    )


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise Stage1Error(
            "config_error",
            "qBittorrent 配置文件不存在",
            "load_qbittorrent_config",
        ) from exc
    except json.JSONDecodeError as exc:
        raise Stage1Error(
            "config_error",
            "qBittorrent 配置不是合法 JSON",
            "load_qbittorrent_config",
            {"reason": str(exc)},
        ) from exc
    except OSError as exc:
        raise Stage1Error(
            "config_error",
            "无法读取 qBittorrent 配置",
            "load_qbittorrent_config",
            {"reason": str(exc)},
        ) from exc
