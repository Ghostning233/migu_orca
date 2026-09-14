from __future__ import annotations

from apps.migu_orca_web.openapi_gen import generate_openapi

TRACKING_OPS = {
    "submitTrackingItem", "retryTrackingItem", "syncTrackingItems",
    "modifyTrackingItem", "setTrackingItemEnabled", "refreshTrackingRss",
    "deleteExternalTrackingItem", "recoverTrackingItem",
}


def _strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def test_tracking_generated_source_has_no_legacy_credential_semantics() -> None:
    doc = generate_openapi()
    found = []
    for methods in doc["paths"].values():
        for operation in methods.values():
            if isinstance(operation, dict) and operation.get("operationId") in TRACKING_OPS:
                found.extend(_strings(operation.get("requestBody", {})))
                found.extend(_strings(operation.get("description", "")))
    text = "\n".join(found)
    assert "ab_config" not in text
    assert "legacy_credentials" not in text
    assert "request-scoped Auto Bangumi" not in text
