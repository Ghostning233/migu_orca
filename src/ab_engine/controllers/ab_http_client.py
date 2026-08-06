from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ab_engine.controllers.ab_config import AutoBangumiConfig
from shared.errors import Stage1Error


class AutoBangumiHttpTransport(Protocol):
    """Transport boundary used by the real Auto Bangumi HTTP client."""

    def post_json(
        self,
        endpoint: str,
        headers: Mapping[str, str],
        payload: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        """POST a JSON payload and return the decoded response object."""


class UrlopenAutoBangumiHttpTransport:
    """urllib-backed HTTP transport for Auto Bangumi JSON requests."""

    def post_json(
        self,
        endpoint: str,
        headers: Mapping[str, str],
        payload: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        request = Request(
            endpoint,
            data=json.dumps(deepcopy(payload), ensure_ascii=False).encode("utf-8"),
            headers=dict(headers),
            method="POST",
        )

        try:
            with urlopen(request, timeout=timeout) as response:
                response_body = response.read().decode("utf-8")
        except HTTPError as exc:
            raise Stage1Error(
                "ab_submit_failed",
                "Auto Bangumi HTTP 提交失败",
                "create_ab_subscription",
                {"status_code": exc.code},
            ) from exc
        except URLError as exc:
            raise Stage1Error(
                "ab_submit_failed",
                "Auto Bangumi HTTP 请求失败",
                "create_ab_subscription",
                {"reason": str(exc.reason)},
            ) from exc

        try:
            ab_response = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise Stage1Error(
                "invalid_ab_response",
                "Auto Bangumi 响应不是合法 JSON",
                "create_ab_subscription",
            ) from exc

        if not isinstance(ab_response, dict):
            raise Stage1Error(
                "invalid_ab_response",
                "Auto Bangumi 响应必须是 JSON 对象",
                "create_ab_subscription",
            )
        return ab_response


class AutoBangumiHttpClient:
    """Real Auto Bangumi HTTP adapter for creating subscriptions."""

    def __init__(
        self,
        config: AutoBangumiConfig,
        *,
        transport: AutoBangumiHttpTransport | None = None,
        timeout: float = 30,
    ) -> None:
        self._config = config
        self._transport = transport or UrlopenAutoBangumiHttpTransport()
        self._timeout = timeout

    def create_subscription(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a subscription from an already prepared AB payload."""

        validated_payload = _validate_subscription_payload(payload)
        return self._transport.post_json(
            self._config.endpoint,
            {
                "Authorization": f"Bearer {self._config.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            validated_payload,
            timeout=self._timeout,
        )


def create_auto_bangumi_http_client(
    config: AutoBangumiConfig,
    *,
    transport: AutoBangumiHttpTransport | None = None,
) -> AutoBangumiHttpClient:
    """Build the real Auto Bangumi HTTP client from explicit AB config."""

    return AutoBangumiHttpClient(config, transport=transport)


def _validate_subscription_payload(payload: dict[str, Any]) -> dict[str, Any]:
    validated: dict[str, Any] = {}
    for field in ("title", "rss_url", "save_path"):
        validated[field] = _required_payload_string(payload.get(field), field)
    filter_rule = payload.get("filter_rule")
    if not isinstance(filter_rule, dict):
        raise Stage1Error(
            "invalid_ab_payload",
            "Auto Bangumi payload 字段类型错误",
            "validate_ab_subscription_payload",
            {"field": "filter_rule", "expected_type": "object"},
        )
    validated["filter_rule"] = deepcopy(filter_rule)
    return validated


def _required_payload_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Stage1Error(
            "invalid_ab_payload",
            "Auto Bangumi payload 缺少必填字符串字段",
            "validate_ab_subscription_payload",
            {"field": field, "expected_type": "string"},
        )
    return value.strip()
