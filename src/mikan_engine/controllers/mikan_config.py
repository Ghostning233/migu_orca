from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shared.errors import Stage1Error


@dataclass(frozen=True)
class MikanConfig:
    """Explicit config required before enabling the real MiKan source."""

    search_endpoint: str
    timeout_seconds: float


# System-default MiKan Web config. The default endpoint is MiKanProject's public
# search page; callers append ``searchstr=<title>`` when searching. The default is
# server-side only, contains no secrets, and is never written to browser storage,
# URL state, history, or Request snapshots.
DEFAULT_MIKAN_SEARCH_ENDPOINT = "https://mikanani.me/Home/Search"
DEFAULT_MIKAN_TIMEOUT_SECONDS = 15.0


def default_mikan_config() -> MikanConfig:
    """Return the system-default MiKan config for the Web primary flow.

    Used when a request carries no request-scoped ``mikan_config`` (candidate
    search and direct URL/ID fallback). An explicit ``mikan_config`` still
    overrides the default as a test seam or for advanced callers.
    """
    return MikanConfig(
        search_endpoint=DEFAULT_MIKAN_SEARCH_ENDPOINT,
        timeout_seconds=DEFAULT_MIKAN_TIMEOUT_SECONDS,
    )


def load_mikan_config(path: Path) -> MikanConfig:
    """Load real MiKan source config from a caller-provided JSON path."""

    data = _read_json(path)
    if not isinstance(data, dict):
        raise Stage1Error(
            "config_error",
            "MiKan 配置必须是 JSON 对象",
            "load_mikan_config",
        )

    search_endpoint = data.get("search_endpoint")
    timeout_seconds = data.get("timeout_seconds")

    if not isinstance(search_endpoint, str) or not search_endpoint.strip():
        raise Stage1Error(
            "config_error",
            "MiKan search_endpoint 必须是非空字符串",
            "load_mikan_config",
            {"field": "search_endpoint"},
        )
    if not isinstance(timeout_seconds, int | float) or timeout_seconds <= 0:
        raise Stage1Error(
            "config_error",
            "MiKan timeout_seconds 必须是正数",
            "load_mikan_config",
            {"field": "timeout_seconds"},
        )

    return MikanConfig(
        search_endpoint=search_endpoint.strip(),
        timeout_seconds=float(timeout_seconds),
    )


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise Stage1Error(
            "config_error",
            f"MiKan 配置文件不存在：{path}",
            "load_mikan_config",
        ) from exc
    except json.JSONDecodeError as exc:
        raise Stage1Error(
            "config_error",
            f"MiKan 配置不是合法 JSON：{path}",
            "load_mikan_config",
            {"reason": str(exc)},
        ) from exc
    except OSError as exc:
        raise Stage1Error(
            "config_error",
            f"无法读取 MiKan 配置：{path}",
            "load_mikan_config",
            {"reason": str(exc)},
        ) from exc
