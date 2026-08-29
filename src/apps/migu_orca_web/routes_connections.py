from __future__ import annotations

"""External-connection test routes (US-191 split).

Migrated from ``views.py`` without behavior change. Both endpoints keep
request-scoped credentials out of every response through whitelist
serialization; failures are mapped through the shared sanitized error helpers.
"""

from typing import Any

from extensions.flask_api import class_route
from extensions.flask_api.views import PostView
from ab_engine.controllers.ab_config import build_ab_config
from ab_engine.controllers.ab_connection_controller import test_ab_connection
from qbittorrent_engine.controllers.qbittorrent_controller import (
    test_qbittorrent_connection,
)
from qbittorrent_engine.controllers.qbittorrent_config import build_qbittorrent_config
from shared.errors import Stage1Error

from apps.migu_orca_web.blueprints import api_blueprint
from apps.migu_orca_web.schemas import (
    AutoBangumiTestConnectionPayload,
    QbittorrentTestConnectionPayload,
)
from apps.migu_orca_web.serializers import (
    _sanitize_ab_connection_summary,
    _sanitize_qbittorrent_connection_summary,
)


def _raise_qbittorrent_result_error(result: dict[str, Any]) -> None:
    error = result.get("error")
    if not isinstance(error, dict):
        raise Stage1Error(
            "qbittorrent_unexpected_response",
            "qBittorrent 响应无法识别",
            "test_qbittorrent_connection",
        )

    error_type = str(error.get("error_type") or "qbittorrent_unexpected_response")
    failed_step = str(error.get("failed_step") or "test_qbittorrent_connection")
    details = error.get("details")
    safe_details = (
        {
            key: value
            for key, value in details.items()
            if key in {"category", "field", "status_code"}
        }
        if isinstance(details, dict)
        else None
    )
    raise Stage1Error(
        error_type,
        _qbittorrent_error_message(error_type, str(error.get("error_message") or "")),
        failed_step,
        safe_details,
    )


def _raise_ab_connection_result_error(result: dict[str, Any]) -> None:
    error = result.get("error")
    if not isinstance(error, dict):
        raise Stage1Error(
            "invalid_ab_response",
            "Auto Bangumi 响应无法识别",
            "test_ab_connection",
        )
    error_type = str(error.get("error_type") or "invalid_ab_response")
    failed_step = str(error.get("failed_step") or "test_ab_connection")
    details = error.get("details")
    safe_details = (
        {
            key: value
            for key, value in details.items()
            if key in {"category", "field", "status_code"}
        }
        if isinstance(details, dict)
        else None
    )
    messages = {
        "config_error": "Auto Bangumi 配置无效",
        "ab_auth_failed": "Auto Bangumi 认证失败",
        "ab_connection_failed": "Auto Bangumi HTTP 连接失败",
        "ab_timeout": "Auto Bangumi HTTP 请求超时",
        "ab_unsupported_version": "当前 Auto Bangumi 版本暂不受支持",
        "invalid_ab_response": "Auto Bangumi 响应无法识别",
    }
    raise Stage1Error(
        error_type,
        messages.get(error_type, "Auto Bangumi 连接测试失败"),
        failed_step,
        safe_details,
    )


def _qbittorrent_error_message(error_type: str, fallback: str) -> str:
    messages = {
        "config_error": fallback or "qBittorrent 配置无效",
        "qbittorrent_auth_failed": "qBittorrent 认证失败",
        "qbittorrent_timeout": "qBittorrent HTTP 请求超时",
        "qbittorrent_connection_failed": "qBittorrent HTTP 连接失败",
        "qbittorrent_http_failed": "qBittorrent HTTP 请求失败",
        "qbittorrent_unexpected_response": "qBittorrent 响应无法识别",
    }
    return messages.get(error_type, "qBittorrent 连接测试失败")


@class_route(api_blueprint, "/api/v1/qbittorrent/test-connection", methods=["POST"])
class QbittorrentTestConnectionView(PostView):
    request_validator_model = QbittorrentTestConnectionPayload

    def save(self) -> dict[str, object]:
        assert isinstance(
            self.request_validator_model,
            QbittorrentTestConnectionPayload,
        )
        qbittorrent_config = build_qbittorrent_config(
            self.request_validator_model.qbittorrent_config.model_dump()
        )
        result = test_qbittorrent_connection(qbittorrent_config=qbittorrent_config)
        if not result["success"]:
            _raise_qbittorrent_result_error(result)
        summary = result["summary"]
        assert isinstance(summary, dict)
        return _sanitize_qbittorrent_connection_summary(summary)


@class_route(api_blueprint, "/api/v1/autobangumi/test-connection", methods=["POST"])
class AutoBangumiTestConnectionView(PostView):
    request_validator_model = AutoBangumiTestConnectionPayload

    def save(self) -> dict[str, object]:
        assert isinstance(
            self.request_validator_model,
            AutoBangumiTestConnectionPayload,
        )
        ab_config = build_ab_config(
            self.request_validator_model.ab_config.model_dump(exclude_none=True)
        )
        result = test_ab_connection(ab_config=ab_config)
        if not result["success"]:
            _raise_ab_connection_result_error(result)
        summary = result["summary"]
        assert isinstance(summary, dict)
        return _sanitize_ab_connection_summary(summary)
