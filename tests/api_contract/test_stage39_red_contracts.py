from __future__ import annotations

"""Stage 39 red tests: retired credential API and request-scoped secrets.

These assertions intentionally describe the US-330 target contract.  They are
kept separate from the legacy tests so a migration cannot make the old flow
look like coverage of the saved-connection flow.
"""

from pathlib import Path

from apps.base import create_app
from apps.migu_orca_web.openapi_gen import generate_openapi

ROOT = Path(__file__).resolve().parents[2]
GENERATED = ROOT / "frontend" / "src" / "api" / "generated" / "api.ts"


def test_retired_capabilities_route_is_404_and_absent_from_openapi() -> None:
    app = create_app("testing")
    client = app.test_client()

    response = client.post("/api/v1/autobangumi/capabilities", json={})
    assert response.status_code == 404

    assert all(
        rule.rule != "/api/v1/autobangumi/capabilities"
        for rule in app.url_map.iter_rules()
    )
    doc = generate_openapi()
    assert "/api/v1/autobangumi/capabilities" not in doc["paths"]
    assert all(
        operation.get("operationId") != "probeAutoBangumiCapabilities"
        for methods in doc["paths"].values()
        for operation in methods.values()
        if isinstance(operation, dict)
    )


def test_generated_client_has_no_retired_capability_operation_or_path() -> None:
    generated = GENERATED.read_text(encoding="utf-8")
    assert '"/api/v1/autobangumi/capabilities"' not in generated
    assert "probeAutoBangumiCapabilities" not in generated
    assert "CredentialSessionDialog" not in generated


def test_openapi_tracking_request_bodies_use_saved_connection_reference_only() -> None:
    doc = generate_openapi()
    serialized = repr(doc)
    assert "_retired_ab_config" not in serialized

    for path, methods in doc["paths"].items():
        if "/tracking/" not in path:
            continue
        for operation in methods.values():
            if not isinstance(operation, dict):
                continue
            body = operation.get("requestBody", {})
            text = repr(body)
            if operation.get("operationId") in {
                "submitTrackingItem",
                "retryTrackingItem",
                "syncTrackingItems",
                "modifyTrackingItem",
                "setTrackingItemEnabled",
                "refreshTrackingRss",
                "deleteExternalTrackingItem",
                "recoverTrackingItem",
            }:
                assert "ab_config" not in text
                assert "request-scoped" not in text
