"""Request-scoped, read-only AutoBangumi connection testing."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from ab_engine.controllers.ab_config import AutoBangumiConfig, build_ab_config
from ab_engine.controllers.ab_http_client import (
    create_auto_bangumi_http_client,
    create_legacy_3_1_auto_bangumi_client,
)
from extensions.flask_api.api import sanitize_error_data
from shared.errors import Stage1Error


class AutoBangumiConnectionClient(Protocol):
    def probe(self) -> dict[str, Any]: ...


AutoBangumiClientFactory = Callable[[AutoBangumiConfig], AutoBangumiConnectionClient]
_SUMMARY_FIELDS = {"reachable", "authenticated", "version", "adapter", "submit_supported"}


def test_ab_connection(
    *, ab_config: dict[str, Any] | AutoBangumiConfig | None = None,
    ab_client: AutoBangumiConnectionClient | None = None,
    client_factory: AutoBangumiClientFactory | None = None,
) -> dict[str, Any]:
    """Test explicit AB credentials without invoking a subscription write."""
    try:
        client, config = _resolve_client(ab_config, ab_client, client_factory)
        summary = _safe_summary(client.probe())
        summary["auth_mode"] = "账号密码" if config.auth_mode == "password" else "API Token"
        return {"success": True, "summary": summary, "error": None}
    except Stage1Error as exc:
        return {"success": False, "summary": None, "error": sanitize_error_data(exc.as_dict())}
    except TimeoutError:
        error = _failure("ab_timeout", "Auto Bangumi HTTP 请求超时", "timeout")
    except ConnectionError:
        error = _failure("ab_connection_failed", "Auto Bangumi HTTP 连接失败", "connection")
    except Exception:
        error = _failure("invalid_ab_response", "Auto Bangumi 响应无法识别", "protocol")
    return {"success": False, "summary": None, "error": sanitize_error_data(error.as_dict())}


def _resolve_client(
    ab_config: dict[str, Any] | AutoBangumiConfig | None,
    ab_client: AutoBangumiConnectionClient | None,
    client_factory: AutoBangumiClientFactory | None,
) -> tuple[AutoBangumiConnectionClient, AutoBangumiConfig]:
    if isinstance(ab_config, AutoBangumiConfig):
        config = ab_config
    elif isinstance(ab_config, dict):
        config = build_ab_config(ab_config)
    else:
        raise Stage1Error("config_error", "Auto Bangumi 配置无效", "test_ab_connection", {"field": "ab_config"})
    if ab_client is not None:
        return ab_client, config
    if client_factory is not None:
        return client_factory(config), config
    if config.auth_mode == "password":
        return create_legacy_3_1_auto_bangumi_client(config), config
    return create_auto_bangumi_http_client(config), config


def _safe_summary(summary: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(summary, dict) or not isinstance(summary.get("reachable"), bool):
        raise _failure("invalid_ab_response", "Auto Bangumi 响应无法识别", "protocol")
    return {field: summary[field] for field in _SUMMARY_FIELDS if field in summary}


def _failure(error_type: str, message: str, category: str) -> Stage1Error:
    return Stage1Error(error_type, message, "test_ab_connection", {"category": category})
