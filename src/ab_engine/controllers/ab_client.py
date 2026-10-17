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


class AutoBangumiCollectClient(Protocol):
    """Minimal Auto Bangumi one-time collection interface (issue #217)."""

    def create_collection(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run one one-time collection and return its verified write envelope."""


class FakeAutoBangumiClient:
    """Offline Auto Bangumi client for controller tests."""

    def __init__(
        self,
        *,
        response: dict[str, Any] | None = None,
        error: Stage1Error | None = None,
        collection_response: dict[str, Any] | None = None,
        collection_error: Stage1Error | None = None,
    ) -> None:
        if response is not None and error is not None:
            raise ValueError("response and error are mutually exclusive")
        if collection_response is not None and collection_error is not None:
            raise ValueError("collection_response and collection_error are mutually exclusive")
        self._response = deepcopy(response) if response is not None else {
            "id": "fake-ab-subscription",
            "status": "created",
        }
        self._error = error
        # A collection answers with the verified 3.1.18 write envelope: two
        # message strings and no id at all (issues #216/#217).
        self._collection_response = (
            deepcopy(collection_response)
            if collection_response is not None
            else {"msg_en": "Collections completed.", "msg_zh": "收集完成。"}
        )
        self._collection_error = collection_error
        self.calls: list[dict[str, Any]] = []
        self.collection_calls: list[dict[str, Any]] = []

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

    def create_collection(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.collection_calls.append(deepcopy(payload))
        if self._collection_error is not None:
            raise Stage1Error(
                self._collection_error.error_type,
                self._collection_error.message,
                self._collection_error.failed_step,
                deepcopy(self._collection_error.details),
            )
        return deepcopy(self._collection_response)


def collect_ab_resources(
    client: AutoBangumiCollectClient,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Run one one-time "download existing resources" request and normalize it.

    A collection establishes no controlled external subscription and Auto
    Bangumi reports no per-torrent result, so the normalized success carries no
    external id and no fallback plan: ADR-0001's at-least-once semantics are the
    whole contract, every failure is the same retryable 提交失败, and nothing is
    read back to upgrade or downgrade that verdict (issue #98/#217).
    """

    try:
        ab_response = client.create_collection(deepcopy(payload))
    except Stage1Error as error:
        return ab_submit_failure(error)
    return ab_submit_success(None, ab_response)


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
