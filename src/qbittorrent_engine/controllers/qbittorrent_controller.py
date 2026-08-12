from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from extensions.flask_api.api import sanitize_error_data
from qbittorrent_engine.controllers.qbittorrent_client import create_qbittorrent_client
from qbittorrent_engine.controllers.qbittorrent_config import (
    QBittorrentConfig,
    build_qbittorrent_config,
    load_qbittorrent_config,
)
from shared.errors import Stage1Error


class QBittorrentConnectionClient(Protocol):
    """Minimal client surface required for explicit connection tests."""

    def test_connection(self) -> dict[str, object]:
        """Return the qBittorrent connection summary."""


QBittorrentClientFactory = Callable[[QBittorrentConfig], QBittorrentConnectionClient]

_SUMMARY_FIELDS = {"status", "reachable", "version"}


def test_qbittorrent_connection(
    *,
    qbittorrent_config: dict[str, Any] | QBittorrentConfig | None = None,
    qbittorrent_config_path: Path | str | None = None,
    qbittorrent_client: QBittorrentConnectionClient | None = None,
    client_factory: QBittorrentClientFactory | None = None,
) -> dict[str, Any]:
    """Run an explicit qBittorrent connection test with safe summary output."""

    try:
        client = _resolve_qbittorrent_client(
            qbittorrent_config=qbittorrent_config,
            qbittorrent_config_path=qbittorrent_config_path,
            qbittorrent_client=qbittorrent_client,
            client_factory=client_factory or create_qbittorrent_client,
        )
        summary = _safe_connection_summary(client.test_connection())
        return {"success": True, "summary": summary, "error": None}
    except Stage1Error as exc:
        return {
            "success": False,
            "summary": None,
            "error": sanitize_error_data(exc.as_dict()),
        }
    except TimeoutError:
        error = _safe_failure(
            "qbittorrent_timeout",
            "qBittorrent HTTP 请求超时",
            "timeout",
        )
    except ConnectionError:
        error = _safe_failure(
            "qbittorrent_connection_failed",
            "qBittorrent HTTP 连接失败",
            "connection",
        )
    except Exception:  # pragma: no cover - defensive boundary
        error = _safe_failure(
            "qbittorrent_unexpected_response",
            "qBittorrent 响应无法识别",
            "unexpected_response",
        )
    return {
        "success": False,
        "summary": None,
        "error": sanitize_error_data(error.as_dict()),
    }


def _safe_connection_summary(summary: dict[str, object]) -> dict[str, object]:
    if not isinstance(summary, dict):
        raise _safe_failure(
            "qbittorrent_unexpected_response",
            "qBittorrent 响应无法识别",
            "unexpected_response",
        )
    safe_summary = {
        field: summary[field]
        for field in _SUMMARY_FIELDS
        if field in summary
    }
    if "reachable" not in safe_summary:
        safe_summary["reachable"] = True
    return safe_summary


def _safe_failure(error_type: str, message: str, category: str) -> Stage1Error:
    return Stage1Error(
        error_type,
        message,
        "test_qbittorrent_connection",
        {"category": category},
    )


def _resolve_qbittorrent_client(
    *,
    qbittorrent_config: dict[str, Any] | QBittorrentConfig | None,
    qbittorrent_config_path: Path | str | None,
    qbittorrent_client: QBittorrentConnectionClient | None,
    client_factory: QBittorrentClientFactory,
) -> QBittorrentConnectionClient:
    if qbittorrent_client is not None:
        return qbittorrent_client

    if qbittorrent_config is not None and qbittorrent_config_path is not None:
        raise Stage1Error(
            "config_error",
            "qBittorrent 连接测试只能显式提供一套配置输入",
            "test_qbittorrent_connection",
        )

    if isinstance(qbittorrent_config, QBittorrentConfig):
        config = qbittorrent_config
    elif isinstance(qbittorrent_config, dict):
        config = build_qbittorrent_config(qbittorrent_config)
    elif qbittorrent_config_path is not None:
        config = load_qbittorrent_config(Path(qbittorrent_config_path))
    else:
        raise Stage1Error(
            "config_error",
            "qBittorrent 连接测试必须显式提供配置对象或配置文件路径",
            "test_qbittorrent_connection",
            {"field": "qbittorrent_config"},
        )

    return client_factory(config)
