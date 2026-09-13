from __future__ import annotations

"""US-247: route, lifecycle, inventory, and OpenAPI must remain one contract."""

import re
from pathlib import Path

from apps.base import create_app
from apps.migu_orca_web.endpoint_lifecycle import (
    ENDPOINT_LIFECYCLE,
    LIFECYCLE_VALUES,
)
from apps.migu_orca_web.openapi_gen import generate_openapi

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "docs" / "api" / "endpoint_inventory.md"


def _live() -> set[tuple[str, str]]:
    app = create_app("testing")
    return {
        (method, rule.rule)
        for rule in app.url_map.iter_rules()
        if rule.rule.startswith("/api/v1/")
        for method in rule.methods - {"HEAD", "OPTIONS"}
    }


def _normalized(value: str) -> str:
    return re.sub(r"<path:([^>]+)>", r"<\1>", value)


def _inventory_lifecycle() -> dict[tuple[str, str], tuple[str, str, str]]:
    text = INVENTORY.read_text(encoding="utf-8")
    section = text.split("## 2.1 端点生命周期", 1)[1].split("## 3.", 1)[0]
    result: dict[tuple[str, str], tuple[str, str, str]] = {}
    for line in section.splitlines():
        match = re.match(r"\|\s*(GET|POST|PUT|DELETE)\s*\|\s*`([^`]+)`\s*\|\s*(PRIMARY|RECOVERY|COMPATIBILITY)\s*\|\s*([^|]+)\|\s*([^|]+)\|", line)
        if match:
            result[(match.group(1), _normalized(match.group(2)))] = (
                match.group(3), match.group(4).strip(), match.group(5).strip()
            )
    return result


def test_lifecycle_registry_covers_live_routes_and_has_no_phantoms() -> None:
    live = {(method, _normalized(path)) for method, path in _live()}
    registered = {(method, _normalized(path)) for method, path in ENDPOINT_LIFECYCLE}
    assert registered == live
    assert all(entry["lifecycle"] in LIFECYCLE_VALUES for entry in ENDPOINT_LIFECYCLE.values())
    assert all(entry["relation"] and entry["authority"] for entry in ENDPOINT_LIFECYCLE.values())


def test_inventory_projects_lifecycle_registry() -> None:
    inventory = _inventory_lifecycle()
    expected = {
        (method, _normalized(path)): (entry["lifecycle"], entry["relation"], entry["authority"])
        for (method, path), entry in ENDPOINT_LIFECYCLE.items()
    }
    assert inventory == expected


def test_openapi_projects_lifecycle_registry() -> None:
    doc = generate_openapi()
    projected = {
        (method.upper(), path): operation["x-lifecycle"]
        for path, methods in doc["paths"].items()
        for method, operation in methods.items()
    }
    expected = {
        (method, re.sub(r"<(?:path:)?([^>]+)>", r"{\1}", path)): dict(entry)
        for (method, path), entry in ENDPOINT_LIFECYCLE.items()
    }
    assert projected == expected


def test_capabilities_relation_records_subscription_submit_probe_scope() -> None:
    """D38-02.4: subscription_submit 只由已验证的 3.1.18 password/legacy probe 支持。"""
    relation = ENDPOINT_LIFECYCLE[("POST", "/api/v1/autobangumi/capabilities")]["relation"]
    assert "subscription_submit" in relation
    assert "3.1.18" in relation


def test_legacy_routes_are_explicit_compatibility_and_tracking_is_authority() -> None:
    legacy = {
        ("POST", "/api/v1/requests/preview-save"),
        ("POST", "/api/v1/requests/<request_id>/submit-ab"),
        ("POST", "/api/v1/batches/<batch_id>/accept"),
        ("GET", "/api/v1/batches/<batch_id>/queue"),
        ("POST", "/api/v1/batches/<batch_id>/submit"),
        ("POST", "/api/v1/batches/<batch_id>/retry"),
        ("POST", "/api/v1/batches/<batch_id>/recover"),
    }
    for key in legacy:
        matching = [entry for (method, path), entry in ENDPOINT_LIFECYCLE.items() if (method, _normalized(path)) == key]
        assert matching and matching[0]["lifecycle"] == "COMPATIBILITY"
    assert all(
        "TrackingRecord" in entry["authority"]
        for (method, path), entry in ENDPOINT_LIFECYCLE.items()
        if (method, _normalized(path)) in legacy
    )
