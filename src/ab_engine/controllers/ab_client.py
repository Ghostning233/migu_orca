from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, Protocol

from ab_engine.controllers.ab_http_client import is_verified_write_envelope
from ab_engine.controllers.fallback_config import build_ab_fallback_config
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
    *,
    fallback_enabled: bool = False,
) -> dict[str, Any]:
    """Submit a prepared AB payload through a client and normalize the result."""

    try:
        ab_response = client.create_subscription(deepcopy(payload))
        return ab_submit_success(_subscription_id(ab_response, payload), ab_response)
    except Stage1Error as error:
        fallback_config = (
            build_ab_fallback_config(payload, error) if fallback_enabled else None
        )
        return ab_submit_failure(error, fallback_config=fallback_config)


def _subscription_id(ab_response: dict[str, Any], payload: Any) -> str | None:
    """Return the optional external id of one already-verified write response.

    The verified 3.1.18 write envelope is ``{"msg_en": ..., "msg_zh": ...}`` and
    carries no id at all (issue #216), so a missing id is normal for a
    *subscription* write: the exact read-back is what binds the external object
    (issues #97/#182).  That is only true for the write that was actually
    requested, so the no-id envelope is accepted only for the legacy
    subscription body (``{data: Bangumi, rss: RSSItem}``); any other payload
    shape — for example the bare ``Bangumi`` one-time collection body, which
    creates no controlled subscription — keeps failing closed with
    ``invalid_ab_submit_result`` (issue #217 must normalize that case itself).
    """
    for field in ("id", "subscription_id", "ab_subscription_id"):
        value = ab_response.get(field)
        if isinstance(value, str) and value.strip():
            return value
    if _is_legacy_subscription_payload(payload) and is_verified_write_envelope(ab_response):
        return None
    raise Stage1Error(
        "invalid_ab_submit_result",
        "Auto Bangumi 响应缺少订阅 ID",
        "submit_ab_subscription",
        {"fields": ["id", "subscription_id", "ab_subscription_id"]},
    )


def _is_legacy_subscription_payload(payload: Any) -> bool:
    """True only for the 3.1 ``{data: Bangumi, rss: RSSItem}`` subscribe body."""
    return (
        isinstance(payload, Mapping)
        and isinstance(payload.get("data"), Mapping)
        and isinstance(payload.get("rss"), Mapping)
    )
