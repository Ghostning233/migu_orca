"""Fail-closed, request-scoped Auto Bangumi capability probing."""
from __future__ import annotations

from ab_engine.controllers.ab_config import AutoBangumiConfig
from ab_engine.controllers.ab_http_client import (
    AutoBangumiHttpTransport,
    AutoBangumiLegacyTransport,
    create_auto_bangumi_http_client,
)
from ab_engine.controllers.ab_management_client import (
    Legacy31ManagementClient,
    checked_capabilities,
    failed_capabilities,
)
from ab_engine.models.management import AutoBangumiCapabilities
from shared.errors import Stage1Error


def probe_capabilities(
    config: AutoBangumiConfig,
    *,
    transport: AutoBangumiLegacyTransport | AutoBangumiHttpTransport | None = None,
) -> AutoBangumiCapabilities:
    """Probe status and return only safe capability fields.

    API-token status is intentionally not treated as management access: the
    B-C1 management contract is only verified for password + 3.1.18.
    """
    try:
        if config.auth_mode == "password":
            if transport is None:
                client = Legacy31ManagementClient(config, transport=_default_legacy_transport())
            else:
                client = Legacy31ManagementClient(config, transport=transport)
            return checked_capabilities(client.probe_capabilities())

        client = create_auto_bangumi_http_client(config, transport=transport)  # type: ignore[arg-type]
        summary = client.probe()
        version = summary.get("version") if isinstance(summary.get("version"), str) else None
        return checked_capabilities(
            AutoBangumiCapabilities(
                probe_status="PARTIAL", version=version, adapter="api_token",
                subscription_list="UNKNOWN", subscription_detail="UNKNOWN",
                subscription_submit="UNSUPPORTED",
                rss_list="UNKNOWN", external_verify="UNKNOWN",
                safe_message="API Token 仅验证连接状态，管理读取能力保持未知",
            )
        )
    except Stage1Error:
        raise
    except Exception as exc:
        raise Stage1Error("ab_management_failed", "Auto Bangumi 能力探测失败", "probe_capabilities", {"reason": exc.__class__.__name__}) from exc


def _default_legacy_transport() -> AutoBangumiLegacyTransport:
    from ab_engine.controllers.ab_http_client import UrlopenAutoBangumiHttpTransport
    return UrlopenAutoBangumiHttpTransport()


def safe_failed_capabilities(config: AutoBangumiConfig, error: Stage1Error) -> AutoBangumiCapabilities:
    """Convert upstream probe failures to a safe DTO without leaking details."""
    del error
    return checked_capabilities(failed_capabilities(adapter="legacy_3_1" if config.auth_mode == "password" else "api_token"))
