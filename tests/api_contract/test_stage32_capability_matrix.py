"""US-252: the management capability/action matrix fails closed."""
from __future__ import annotations

import pytest

from ab_engine.models.management import AutoBangumiCapabilities
from tracking_engine.controllers.management_state import (
    management_action_allowed,
    management_baseline_verified,
    management_capability_allowed,
    management_capability_field,
)


def _capabilities(**overrides: object) -> AutoBangumiCapabilities:
    values: dict[str, object] = {
        "probe_status": "VERIFIED",
        "version": "3.1.18",
        "adapter": "legacy_3_1",
        "subscription_list": "SUPPORTED",
        "subscription_detail": "SUPPORTED",
        "subscription_modify": "SUPPORTED",
        "subscription_enable": "SUPPORTED",
        "subscription_disable": "SUPPORTED",
        "subscription_delete": "SUPPORTED",
        "rss_list": "SUPPORTED",
        "rss_modify": "SUPPORTED",
        "rss_enable": "SUPPORTED",
        "rss_disable": "SUPPORTED",
        "rss_delete": "SUPPORTED",
        "rss_refresh": "SUPPORTED",
    }
    values.update(overrides)
    return AutoBangumiCapabilities(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("action", "scope", "enabled", "field"),
    [
        ("MODIFY", "SUBSCRIPTION", None, "subscription_modify"),
        ("MODIFY", "ASSOCIATED_RSS", None, "rss_modify"),
        ("SET_ENABLED", "SUBSCRIPTION", True, "subscription_enable"),
        ("SET_ENABLED", "SUBSCRIPTION", False, "subscription_disable"),
        ("SET_ENABLED", "ASSOCIATED_RSS", True, "rss_enable"),
        ("SET_ENABLED", "ASSOCIATED_RSS", False, "rss_disable"),
        ("DELETE_EXTERNAL", "SUBSCRIPTION", None, "subscription_delete"),
        ("DELETE_EXTERNAL", "ASSOCIATED_RSS", None, "rss_delete"),
        ("REFRESH_RSS", "ASSOCIATED_RSS", None, "rss_refresh"),
    ],
)
def test_every_action_scope_and_direction_has_one_capability(
    action: str, scope: str, enabled: bool | None, field: str,
) -> None:
    capabilities = _capabilities()
    assert management_capability_field(action, scope, enabled) == field
    assert management_capability_allowed(capabilities, action, scope, enabled=enabled)


@pytest.mark.parametrize(
    ("overrides", "action", "scope"),
    [
        ({"probe_status": "PARTIAL"}, "MODIFY", "SUBSCRIPTION"),
        ({"probe_status": "FAILED"}, "MODIFY", "SUBSCRIPTION"),
        ({"version": "3.1.17"}, "MODIFY", "SUBSCRIPTION"),
        ({"version": None}, "MODIFY", "SUBSCRIPTION"),
        ({"adapter": "api_token"}, "MODIFY", "SUBSCRIPTION"),
        ({"subscription_modify": "UNKNOWN"}, "MODIFY", "SUBSCRIPTION"),
        ({"rss_refresh": "UNSUPPORTED"}, "REFRESH_RSS", "ASSOCIATED_RSS"),
    ],
)
def test_unproven_baseline_or_action_capability_is_fail_closed(
    overrides: dict[str, object], action: str, scope: str,
) -> None:
    capabilities = _capabilities(**overrides)
    assert not management_capability_allowed(capabilities, action, scope, enabled=None)


def test_scope_and_set_enabled_direction_are_strict() -> None:
    capabilities = _capabilities()
    assert management_baseline_verified(capabilities)
    assert management_capability_field("REFRESH_RSS", "SUBSCRIPTION") is None
    assert management_capability_field("SET_ENABLED", "SUBSCRIPTION", None) is None
    assert not management_capability_allowed(capabilities, "REFRESH_RSS", "SUBSCRIPTION")
    assert not management_capability_allowed(capabilities, "SET_ENABLED", "SUBSCRIPTION")


def test_disabled_record_can_only_reenable() -> None:
    """Issue #228 retired the standalone public DELETE_EXTERNAL entry.

    The delete stays reachable only through the composite plan-delete leg, which
    passes ``include_internal=True`` (see management_state_test.py).
    """
    assert management_action_allowed("DISABLED", "SET_ENABLED", enabled=True)
    assert not management_action_allowed("DISABLED", "SET_ENABLED", enabled=False)
    assert not management_action_allowed("DISABLED", "DELETE_EXTERNAL")
    assert management_action_allowed("DISABLED", "DELETE_EXTERNAL", include_internal=True)
