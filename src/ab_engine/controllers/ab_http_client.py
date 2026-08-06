from __future__ import annotations

from copy import deepcopy
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ab_engine.controllers.ab_config import AutoBangumiConfig
from shared.errors import Stage1Error


class AutoBangumiHttpClient:
    """Real Auto Bangumi HTTP adapter for creating subscriptions."""

    def __init__(self, config: AutoBangumiConfig) -> None:
        self._config = config

    def create_subscription(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a subscription from an already prepared AB payload."""

        request = Request(
            self._config.endpoint,
            data=json.dumps(deepcopy(payload), ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._config.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=30) as response:
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


def create_auto_bangumi_http_client(
    config: AutoBangumiConfig,
) -> AutoBangumiHttpClient:
    """Build the real Auto Bangumi HTTP client from explicit AB config."""

    return AutoBangumiHttpClient(config)
