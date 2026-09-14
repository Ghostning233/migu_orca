"""Auto Bangumi adapter used by the authoritative Tracking submit flow."""

from typing import Any

from ab_engine.controllers import ab_http_client
from ab_engine.controllers.ab_client import submit_ab_subscription
from ab_engine.controllers.subscription_payload import build_ab_submit_payload


def compose_tracking_submit_one():
    """Create the single-item external submit seam for Tracking."""

    def submit_one(request: dict[str, Any], ab_config: Any) -> dict[str, Any]:
        payload = build_ab_submit_payload(request, ab_config.auth_mode)
        client = ab_http_client.create_auto_bangumi_submit_client(ab_config)
        return submit_ab_subscription(
            client,
            payload,
            fallback_enabled=bool(getattr(ab_config, "fallback_enabled", False)),
        )

    return submit_one
