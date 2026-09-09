"""Read-only Auto Bangumi 3.1.18 management adapter."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from urllib.parse import quote, urlsplit

from ab_engine.controllers.ab_config import AutoBangumiConfig
from ab_engine.controllers.ab_http_client import AutoBangumiLegacyTransport, _api_endpoint
from ab_engine.models.management import (
    AutoBangumiCapabilities,
    ExternalRss,
    ExternalSubscription,
)
from shared.errors import Stage1Error

_MAX_TEXT = 512
_MAX_ITEMS = 2000
_MAX_RSS_PER_SUBSCRIPTION = 100


class AutoBangumiManagementClient(Protocol):
    def read_snapshot(self) -> tuple[AutoBangumiCapabilities, list[ExternalSubscription], list[ExternalRss]]: ...


class Legacy31ManagementClient:
    """One-request session adapter; no credential is retained after read_snapshot."""

    def __init__(self, config: AutoBangumiConfig, *, transport: AutoBangumiLegacyTransport, timeout: float = 30) -> None:
        self._config = config
        self._transport = transport
        self._timeout = timeout
        self._token: str | None = None

    def read_snapshot(self) -> tuple[AutoBangumiCapabilities, list[ExternalSubscription], list[ExternalRss]]:
        if self._config.auth_mode != "password":
            raise Stage1Error("ab_management_unsupported", "当前 Auto Bangumi 认证模式不支持管理读取", "ab_management")
        try:
            self._authenticate()
            headers = {"Accept": "application/json", "Cookie": self._cookie()}
            status = self._request("GET", "/api/v1/status", headers)
            version = _version(status)
            if version != "3.1.18":
                raise Stage1Error("ab_unsupported_version", "当前 Auto Bangumi 版本暂不受支持", "ab_management")
            subscriptions = _subscriptions(self._request("GET", "/api/v1/bangumi/get/all", headers))
            rss = _rss_items(self._request("GET", "/api/v1/rss", headers))
            capabilities = AutoBangumiCapabilities(
                probe_status="VERIFIED", version=version, adapter="legacy_3_1",
                subscription_list="SUPPORTED", subscription_detail="SUPPORTED",
                subscription_modify="SUPPORTED", subscription_enable="SUPPORTED",
                subscription_disable="SUPPORTED", subscription_delete="SUPPORTED",
                rss_list="SUPPORTED", external_verify="SUPPORTED",
                safe_message="已验证 Auto Bangumi 3.1.18 管理能力",
            )
            return capabilities, subscriptions, rss
        finally:
            self._token = None

    def probe_capabilities(self) -> AutoBangumiCapabilities:
        """Authenticate and inspect only status for the public capability probe."""
        try:
            self._authenticate()
            status = self._request("GET", "/api/v1/status", {
                "Accept": "application/json", "Cookie": self._cookie()
            })
            version = _version(status)
            if version != "3.1.18":
                return _unknown_capabilities("legacy_3_1", version)
            return _verified_legacy_capabilities(version)
        finally:
            self._token = None

    def get_subscription(self, external_id: str) -> ExternalSubscription:
        """Read one detail using a fresh request-scoped session."""
        if self._config.auth_mode != "password":
            raise Stage1Error("ab_management_unsupported", "当前 Auto Bangumi 认证模式不支持管理读取", "ab_management")
        try:
            self._authenticate()
            safe_external_id = quote(_opaque(external_id, "external_id"), safe="-._~")
            response = self._request("GET", f"/api/v1/bangumi/get/{safe_external_id}", {
                "Accept": "application/json", "Cookie": self._cookie()
            })
            return _subscription(_unwrap(response, "subscription"))
        finally:
            self._token = None

    def update_subscription(self, external_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Update one subscription through the fixed 3.1.18 route."""
        return self._subscription_action(
            "PATCH", f"/api/v1/bangumi/update/{_path_id(external_id)}", payload
        )

    def set_subscription_enabled(self, external_id: str, enabled: bool) -> dict[str, Any]:
        """Enable or disable one subscription without exposing the file option."""
        if type(enabled) is not bool:
            raise Stage1Error("invalid_ab_payload", "启用状态必须是布尔值", "ab_management")
        if enabled:
            method = "GET"
            path = f"/api/v1/bangumi/enable/{_path_id(external_id)}"
        else:
            method = "DELETE"
            path = f"/api/v1/bangumi/disable/{_path_id(external_id)}?file=false"
        return self._subscription_action(method, path, None)

    def delete_subscription(self, external_id: str) -> dict[str, Any]:
        """Delete the external subscription while retaining its files."""
        return self._subscription_action(
            "DELETE", f"/api/v1/bangumi/delete/{_path_id(external_id)}?file=false", None
        )

    def _subscription_action(
        self,
        method: Literal["GET", "PATCH", "DELETE"],
        path: str,
        payload: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        if self._config.auth_mode != "password":
            raise Stage1Error("ab_management_unsupported", "当前 Auto Bangumi 认证模式不支持管理写入", "ab_management")
        try:
            self._authenticate()
            headers = {"Accept": "application/json", "Cookie": self._cookie()}
            status = _version(self._request("GET", "/api/v1/status", headers))
            if status != "3.1.18":
                raise Stage1Error("ab_unsupported_version", "当前 Auto Bangumi 版本暂不受支持", "ab_management")
            if method == "PATCH":
                headers = {**headers, "Content-Type": "application/json"}
            response = self._request(method, path, headers, payload)
            return _action_response(response)
        finally:
            self._token = None

    def _authenticate(self) -> None:
        response = self._request("POST", "/api/v1/auth/login", {
            "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"
        }, {"username": self._config.username or "", "password": self._config.password or ""})
        token = response.get("access_token")
        if not isinstance(token, str) or not token.strip() or len(token) > _MAX_TEXT:
            raise Stage1Error("invalid_ab_response", "Auto Bangumi 登录响应无有效令牌", "ab_management")
        self._token = token.strip()

    def _cookie(self) -> str:
        if self._token is None:
            raise Stage1Error("ab_auth_failed", "Auto Bangumi 认证失败", "ab_management")
        return f"token={self._token}"

    def _request(
        self,
        method: Literal["GET", "POST", "PATCH", "DELETE"],
        path: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            return self._transport.request_json(method, _api_endpoint(self._config.base_url, path), headers, payload, timeout=self._timeout)
        except Stage1Error:
            raise
        except Exception as exc:
            raise Stage1Error("ab_management_failed", "Auto Bangumi 管理请求失败", "ab_management", {"reason": exc.__class__.__name__}) from exc


def create_legacy_31_management_client(config: AutoBangumiConfig, *, transport: AutoBangumiLegacyTransport) -> Legacy31ManagementClient:
    return Legacy31ManagementClient(config, transport=transport)


def _unknown_capabilities(adapter: Literal["legacy_3_1", "api_token"], version: str | None) -> AutoBangumiCapabilities:
    return AutoBangumiCapabilities(
        probe_status="VERIFIED", version=version, adapter=adapter,
        subscription_list="UNKNOWN", subscription_detail="UNKNOWN",
        rss_list="UNKNOWN", external_verify="UNKNOWN",
        safe_message="已完成连接探测，但未验证可用的管理能力",
    )


def _verified_legacy_capabilities(version: str) -> AutoBangumiCapabilities:
    return AutoBangumiCapabilities(
        probe_status="VERIFIED", version=version, adapter="legacy_3_1",
        subscription_list="SUPPORTED", subscription_detail="SUPPORTED",
        subscription_modify="SUPPORTED", subscription_enable="SUPPORTED",
        subscription_disable="SUPPORTED", subscription_delete="SUPPORTED",
        rss_list="SUPPORTED", external_verify="SUPPORTED",
        safe_message="已验证 Auto Bangumi 3.1.18 管理能力",
    )


def failed_capabilities(*, adapter: Literal["legacy_3_1", "api_token"] | None = None) -> AutoBangumiCapabilities:
    """Build the fail-closed result used when probing cannot be completed."""
    return AutoBangumiCapabilities(
        probe_status="FAILED", version=None, adapter=adapter,
        subscription_list="UNKNOWN", subscription_detail="UNKNOWN",
        rss_list="UNKNOWN", external_verify="UNKNOWN",
        safe_message="Auto Bangumi 能力探测失败，已安全关闭未验证能力",
    )


def checked_capabilities(capabilities: AutoBangumiCapabilities) -> AutoBangumiCapabilities:
    return AutoBangumiCapabilities(
        **{**capabilities.__dict__, "checked_at": datetime.now(UTC).isoformat()}
    )


def _unwrap(response: Mapping[str, Any], step: str) -> Any:
    value = response.get("data", response)
    if isinstance(value, Mapping) and "data" in value:
        value = value["data"]
    return value


def _items(response: Mapping[str, Any], step: str) -> list[Any]:
    value = _unwrap(response, step)
    if not isinstance(value, list) or len(value) > _MAX_ITEMS:
        raise Stage1Error("invalid_ab_response", "Auto Bangumi 列表响应无效", "ab_management", {"field": step})
    return value


def _subscriptions(response: Mapping[str, Any]) -> list[ExternalSubscription]:
    return [_subscription(item) for item in _items(response, "subscriptions")]


def _subscription(value: Any) -> ExternalSubscription:
    if not isinstance(value, Mapping):
        raise Stage1Error("invalid_ab_response", "Auto Bangumi 番剧响应无效", "ab_management")
    external_id = _opaque(value.get("id"), "subscription_id")
    title = _text(value.get("official_title") or value.get("title_raw") or value.get("title"), "title", required=True)
    season_value = value.get("season")
    season = season_value if isinstance(season_value, int) and not isinstance(season_value, bool) and 0 <= season_value <= 100 else None
    if season_value is not None and season is None:
        raise Stage1Error("invalid_ab_response", "Auto Bangumi 番剧响应字段无效", "ab_management", {"field": "season"})
    group = _text(value.get("group_name"), "group_name") if value.get("group_name") is not None else None
    rss_link = value.get("rss_link")
    if rss_link is not None and (not isinstance(rss_link, str) or len(rss_link) > _MAX_TEXT):
        raise Stage1Error("invalid_ab_response", "Auto Bangumi 番剧响应字段无效", "ab_management", {"field": "rss_link"})
    rss_ids = value.get("rss_ids", ())
    if not isinstance(rss_ids, (list, tuple)) or len(rss_ids) > _MAX_RSS_PER_SUBSCRIPTION:
        raise Stage1Error("invalid_ab_response", "Auto Bangumi 番剧响应字段无效", "ab_management", {"field": "rss_ids"})
    ids = tuple(dict.fromkeys(_opaque(item, "rss_id") for item in rss_ids))
    deleted = value.get("deleted", False)
    if not isinstance(deleted, bool):
        raise Stage1Error("invalid_ab_response", "Auto Bangumi 番剧响应字段无效", "ab_management", {"field": "deleted"})
    return ExternalSubscription(external_id, title, season, group, ((rss_link,) if isinstance(rss_link, str) else ()), ids, deleted)


def _rss_items(response: Mapping[str, Any]) -> list[ExternalRss]:
    result: list[ExternalRss] = []
    for value in _items(response, "rss"):
        if not isinstance(value, Mapping):
            raise Stage1Error("invalid_ab_response", "Auto Bangumi RSS 响应无效", "ab_management")
        result.append(ExternalRss(
            _opaque(value.get("id"), "rss_id"),
            _text(value.get("name"), "name") if value.get("name") is not None else None,
            _url(value.get("url")),
            _bool(value.get("aggregate", False), "aggregate"),
            _text(value.get("parser"), "parser") if value.get("parser") is not None else None,
            _bool(value.get("enabled", True), "enabled"),
        ))
    return result


def _opaque(value: Any, field: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise Stage1Error("invalid_ab_response", "Auto Bangumi 响应字段无效", "ab_management", {"field": field})
    result = str(value).strip()
    if not result or len(result) > 128 or any(ord(char) < 32 for char in result):
        raise Stage1Error("invalid_ab_response", "Auto Bangumi 响应字段无效", "ab_management", {"field": field})
    return result


def _path_id(value: str) -> str:
    return quote(_opaque(value, "external_id"), safe="-._~")


def _action_response(response: Mapping[str, Any]) -> dict[str, Any]:
    """Keep action results bounded and reject malformed upstream responses."""
    if not isinstance(response, Mapping) or len(response) > 32:
        raise Stage1Error("invalid_ab_response", "Auto Bangumi 管理响应无效", "ab_management")
    result: dict[str, Any] = {}
    for key, value in response.items():
        if not isinstance(key, str) or len(key) > 64:
            raise Stage1Error("invalid_ab_response", "Auto Bangumi 管理响应无效", "ab_management")
        if key.lower() in {"token", "access_token", "cookie", "password", "authorization"}:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[key] = value
    return result


def _text(value: Any, field: str, *, required: bool = False) -> str:
    if not isinstance(value, str) or len(value.strip()) > _MAX_TEXT or (required and not value.strip()):
        raise Stage1Error("invalid_ab_response", "Auto Bangumi 响应字段无效", "ab_management", {"field": field})
    return value.strip()


def _url(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) > _MAX_TEXT
        or any(ord(char) < 32 for char in value)
        or urlsplit(value).scheme not in {"http", "https"}
        or not urlsplit(value).netloc
    ):
        raise Stage1Error("invalid_ab_response", "Auto Bangumi 响应字段无效", "ab_management", {"field": "url"})
    return value


def _bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise Stage1Error("invalid_ab_response", "Auto Bangumi 响应字段无效", "ab_management", {"field": field})
    return value


def _version(response: Mapping[str, Any]) -> str:
    value = response.get("version")
    if value is None and isinstance(response.get("data"), Mapping):
        value = response["data"].get("version")
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        raise Stage1Error("invalid_ab_response", "Auto Bangumi 状态响应缺少版本", "ab_management")
    return value.strip()
