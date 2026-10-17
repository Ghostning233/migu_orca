"""Auto Bangumi adapter used by the authoritative Tracking submit flow."""

from typing import Any

from ab_engine.controllers import ab_http_client
from ab_engine.controllers.ab_client import collect_ab_resources, submit_ab_subscription
from ab_engine.controllers.subscription_payload import (
    build_ab_submit_payload,
    build_legacy_31_collection_payload,
)


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


def collect_existing_resources(
    request: dict[str, Any],
    ab_config: Any,
) -> dict[str, Any]:
    """Run the one-time "download existing resources" request (issue #217).

    The verified 3.1.18 collection body is built from the accepted Request and
    sent through the same password-only write adapter as every other 3.1.18
    write, so the exact-200 write envelope criterion of issue #216 applies here
    too.  Nothing is read back and no fallback plan is built: a one-time request
    creates no controlled external subscription (ADR-0001).
    """

    payload = build_legacy_31_collection_payload(request)
    client = ab_http_client.create_auto_bangumi_submit_client(ab_config)
    return collect_ab_resources(client, payload)
