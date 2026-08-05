from __future__ import annotations

from copy import deepcopy
from typing import Any, Protocol

from ab_engine.controllers.submit_result import ab_submit_failure, ab_submit_success
from shared.errors import Stage1Error


class AutoBangumiClient(Protocol):
    """Minimal Auto Bangumi subscription creation interface."""

    def create_subscription(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a subscription and return the Auto Bangumi response."""


class FakeAutoBangumiClient:
    """Offline Auto Bangumi client for controller tests."""

    def __init__(
        self,
        *,
        response: dict[str, Any] | None = None,
        error: Stage1Error | None = None,
    ) -> None:
        if response is not None and error is not None:
            raise ValueError("response and error are mutually exclusive")
        self._response = deepcopy(response) if response is not None else {
            "id": "fake-ab-subscription",
            "status": "created",
        }
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def create_subscription(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(deepcopy(payload))
        if self._error is not None:
            raise Stage1Error(
                self._error.error_type,
                self._error.message,
                self._error.failed_step,
                deepcopy(self._error.details),
            )
        return deepcopy(self._response)


def submit_ab_subscription(
    client: AutoBangumiClient,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Submit a prepared AB payload through a client and normalize the result."""

    try:
        ab_response = client.create_subscription(deepcopy(payload))
        return ab_submit_success(_subscription_id(ab_response), ab_response)
    except Stage1Error as error:
        return ab_submit_failure(error)


def _subscription_id(ab_response: dict[str, Any]) -> str:
    for field in ("id", "subscription_id", "ab_subscription_id"):
        value = ab_response.get(field)
        if isinstance(value, str) and value.strip():
            return value
    raise Stage1Error(
        "invalid_ab_submit_result",
        "Auto Bangumi 响应缺少订阅 ID",
        "submit_ab_subscription",
        {"fields": ["id", "subscription_id", "ab_subscription_id"]},
    )
