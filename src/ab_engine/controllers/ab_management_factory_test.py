"""Factory-level contract for the request-scoped AB management client (#175).

These tests pin the *composition* seam, not the adapter behaviour already
covered by ``ab_management_client_test.py``:

* ``transport=None`` must select the production transport inside the factory,
  so no application caller has to name a transport;
* an injected transport must be used verbatim, never replaced by a default;
* ``timeout`` and the resolved config must reach the adapter unchanged;
* ``monotonic`` must still be forwarded, because the endpoint-level deadline
  budget (issue #183) is the caller's guarantee, not the factory's.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

import ab_engine.controllers.ab_management_factory as ab_management_factory
from ab_engine.controllers.ab_config import AutoBangumiConfig
from ab_engine.controllers.ab_http_client import UrlopenAutoBangumiHttpTransport
from ab_engine.controllers.ab_management_client import Legacy31ManagementClient
from ab_engine.controllers.ab_management_factory import create_management_client
from shared.errors import Stage1Error


class RecordingTransport:
    """Offline transport that records every request it is asked to make."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def request_json(
        self,
        method: str,
        endpoint: str,
        headers: Mapping[str, str],
        payload: Any | None = None,
        *,
        timeout: float,
    ) -> Any:
        self.calls.append({"method": method, "endpoint": endpoint, "timeout": timeout})
        if endpoint.endswith("/auth/login"):
            return {"access_token": "session-secret"}
        if endpoint.endswith("/status"):
            return {"version": "3.1.18"}
        return []

    def write_json(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the read-only factory must never build a write transport")


def _config(**overrides: Any) -> AutoBangumiConfig:
    values: dict[str, Any] = {
        "base_url": "https://auto-bangumi.example",
        "auth_mode": "password",
        "fallback_enabled": False,
        "username": "operator",
        "password": "password-secret",
    }
    values.update(overrides)
    return AutoBangumiConfig(**values)


def test_the_production_default_is_the_urlopen_transport() -> None:
    """``transport=None`` resolves to the real stdlib transport, not ``None``."""
    client = create_management_client(_config())

    assert isinstance(client, Legacy31ManagementClient)
    assert isinstance(client._transport, UrlopenAutoBangumiHttpTransport)


def test_default_transport_is_chosen_inside_the_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default is constructed *here*: no caller passes a transport at all."""
    created: list[Any] = []
    endpoints: list[str] = []

    class _DefaultTransport:
        def __init__(self) -> None:
            created.append(self)

        def request_json(
            self,
            method: str,
            endpoint: str,
            headers: Mapping[str, str],
            payload: Any | None = None,
            *,
            timeout: float,
        ) -> Any:
            endpoints.append(endpoint)
            if endpoint.endswith("/auth/login"):
                return {"access_token": "session-secret"}
            return {"version": "3.1.18"}

        def write_json(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("the read-only factory must never build a write transport")

    monkeypatch.setattr(
        "ab_engine.controllers.ab_management_factory.UrlopenAutoBangumiHttpTransport",
        _DefaultTransport,
    )

    capabilities = create_management_client(_config()).probe_capabilities()

    assert capabilities.version == "3.1.18"
    assert endpoints == [
        "https://auto-bangumi.example/api/v1/auth/login",
        "https://auto-bangumi.example/api/v1/status",
    ]
    assert len(created) == 1, "the default transport must be built exactly once"


def test_injected_transport_is_used_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    """An injected transport is never replaced by the production default."""

    class _ForbiddenDefault:
        def __init__(self) -> None:
            raise AssertionError("an injected transport must not be replaced by the default")

    monkeypatch.setattr(
        "ab_engine.controllers.ab_management_factory.UrlopenAutoBangumiHttpTransport",
        _ForbiddenDefault,
    )
    transport = RecordingTransport()

    client = create_management_client(_config(), transport=transport)

    assert client.probe_capabilities().version == "3.1.18"
    assert [call["endpoint"] for call in transport.calls] == [
        "https://auto-bangumi.example/api/v1/auth/login",
        "https://auto-bangumi.example/api/v1/status",
    ]


def test_timeout_and_config_reach_the_adapter_unmodified() -> None:
    """The default timeout lives in the implementation; an explicit one passes through."""
    transport = RecordingTransport()

    client = create_management_client(
        _config(base_url="https://ab.internal.example:8443"),
        transport=transport,
        timeout=1.5,
    )

    assert client.probe_capabilities().version == "3.1.18"
    assert [call["endpoint"] for call in transport.calls] == [
        "https://ab.internal.example:8443/api/v1/auth/login",
        "https://ab.internal.example:8443/api/v1/status",
    ]
    assert [call["timeout"] for call in transport.calls] == [1.5, 1.5]


def test_the_implicit_default_timeout_reaches_the_adapter() -> None:
    """Issue #207: omitting ``timeout`` bounds each call at 30 seconds.

    The neighbouring test only pins an *explicit* ``timeout=1.5``; this one pins
    the effective bound a caller gets when it omits ``timeout`` entirely, by
    observing the transport call.  Because the adapter's own default is also 30,
    this observation alone cannot tell whether the factory forwarded the keyword
    at all -- see the mandatory-keyword spy below for that claim.
    """
    transport = RecordingTransport()

    client = create_management_client(_config(), transport=transport)

    assert client.probe_capabilities().version == "3.1.18"
    assert [call["timeout"] for call in transport.calls] == [30.0, 30.0]


def test_the_factory_forwards_its_default_timeout_to_the_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #207: the omitted ``timeout`` is not dropped before the delegation.

    The transport observation above stays green even if the factory stops
    passing ``timeout`` through, because the adapter defaults to 30 as well.  So
    this spy makes ``timeout`` a *mandatory* keyword at the delegation boundary:
    a dropped forward raises ``TypeError`` instead of silently falling back to
    the adapter default, and the recorded keyword proves the factory's literal.
    """
    real_factory = ab_management_factory.create_legacy_31_management_client
    forwarded: list[float] = []

    def spy(
        config: AutoBangumiConfig,
        *,
        transport: Any,
        timeout: float,
        monotonic: Any = None,
    ) -> Legacy31ManagementClient:
        forwarded.append(timeout)
        return real_factory(config, transport=transport, timeout=timeout, monotonic=monotonic)

    monkeypatch.setattr(ab_management_factory, "create_legacy_31_management_client", spy)

    client = create_management_client(_config(), transport=RecordingTransport())

    assert forwarded == [30.0]
    assert isinstance(client, Legacy31ManagementClient)


def test_monotonic_is_forwarded_so_one_deadline_still_bounds_every_sub_request() -> None:
    """Issue #183: the shared read deadline keeps shrinking through the factory."""
    clock = {"now": 0.0}
    timeouts: list[float] = []

    class _SlowTransport:
        def request_json(
            self,
            method: str,
            endpoint: str,
            headers: Mapping[str, str],
            payload: Any | None = None,
            *,
            timeout: float,
        ) -> Any:
            timeouts.append(timeout)
            clock["now"] += 4.0
            if endpoint.endswith("/auth/login"):
                return {"access_token": "session-secret"}
            if endpoint.endswith("/status"):
                return {"version": "3.1.18"}
            return []

        def write_json(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("the read-only factory must never build a write transport")

    client = create_management_client(
        _config(), transport=_SlowTransport(), monotonic=lambda: clock["now"]
    )

    with pytest.raises(Stage1Error) as error:
        client.read_snapshot(deadline=12.0)

    assert error.value.error_type == "ab_timeout"
    # 12 / 4 = three requests fit; the fourth would exceed the endpoint budget.
    assert timeouts == [12.0, 8.0, 4.0]
