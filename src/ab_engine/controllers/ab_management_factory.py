"""Composition root for the request-scoped Auto Bangumi management client.

Issue #175: transport selection used to leak into every application caller,
which each assembled ``UrlopenAutoBangumiHttpTransport()`` itself (six call
sites) and one of which built ``Legacy31ManagementClient`` directly.  The
choice of transport, its construction and the default timeout now live here;
callers only depend on this interface plus the already-resolved
``AutoBangumiConfig``.

The lower-level ``create_legacy_31_management_client`` remains public and
unchanged: tests that inject a transport keep using it.
"""
from __future__ import annotations

from collections.abc import Callable

from ab_engine.controllers.ab_config import AutoBangumiConfig
from ab_engine.controllers.ab_http_client import (
    AutoBangumiLegacyTransport,
    UrlopenAutoBangumiHttpTransport,
)
from ab_engine.controllers.ab_management_client import (
    Legacy31ManagementClient,
    create_legacy_31_management_client,
)

__all__ = ["create_management_client"]


def create_management_client(
    config: AutoBangumiConfig,
    *,
    transport: AutoBangumiLegacyTransport | None = None,
    timeout: float = 30,
    monotonic: Callable[[], float] | None = None,
) -> Legacy31ManagementClient:
    """Build one request-scoped management client for an already-resolved config.

    ``transport=None`` selects the production stdlib transport *inside this
    implementation*, so no caller has to know which transport exists.  Tests can
    still inject a transport here (or call
    ``create_legacy_31_management_client`` directly), and services keep their
    injectable-client seam; ``timeout`` stays a single-call bound, so a caller
    inside an endpoint-level budget (issue #183) passes its derived per-attempt
    value instead of widening any global default.
    """
    if transport is None:
        transport = UrlopenAutoBangumiHttpTransport()
    return create_legacy_31_management_client(
        config, transport=transport, timeout=timeout, monotonic=monotonic
    )
