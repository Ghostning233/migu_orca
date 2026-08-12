from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shared.errors import Stage1Error


@dataclass(frozen=True)
class AutoBangumiConfig:
    endpoint: str
    token: str
    fallback_enabled: bool


def build_ab_config(data: dict[str, Any]) -> AutoBangumiConfig:
    """Build Auto Bangumi config from an explicit object."""

    endpoint = data.get("endpoint")
    token = data.get("token")
    fallback_enabled = data.get("fallback_enabled")

    if not isinstance(endpoint, str) or not endpoint.strip():
        raise Stage1Error(
            "config_error",
            "Auto Bangumi endpoint 必须是非空字符串",
            "load_ab_config",
            {"field": "endpoint"},
        )
    if not isinstance(token, str) or not token.strip():
        raise Stage1Error(
            "config_error",
            "Auto Bangumi token 必须是非空字符串",
            "load_ab_config",
            {"field": "token"},
        )
    if not isinstance(fallback_enabled, bool):
        raise Stage1Error(
            "config_error",
            "Auto Bangumi fallback_enabled 必须是布尔值",
            "load_ab_config",
            {"field": "fallback_enabled"},
        )

    return AutoBangumiConfig(
        endpoint=endpoint.strip(),
        token=token.strip(),
        fallback_enabled=fallback_enabled,
    )


def load_ab_config(path: Path) -> AutoBangumiConfig:
    """Load the minimal Auto Bangumi system config from an explicit JSON path."""

    data = _read_json(path)
    if not isinstance(data, dict):
        raise Stage1Error(
            "config_error",
            "Auto Bangumi 配置必须是 JSON 对象",
            "load_ab_config",
        )

    return build_ab_config(data)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise Stage1Error(
            "config_error",
            f"Auto Bangumi 配置文件不存在：{path}",
            "load_ab_config",
        ) from exc
    except json.JSONDecodeError as exc:
        raise Stage1Error(
            "config_error",
            f"Auto Bangumi 配置不是合法 JSON：{path}",
            "load_ab_config",
            {"reason": str(exc)},
        ) from exc
    except OSError as exc:
        raise Stage1Error(
            "config_error",
            f"无法读取 Auto Bangumi 配置：{path}",
            "load_ab_config",
            {"reason": str(exc)},
        ) from exc
