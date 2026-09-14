from __future__ import annotations

"""Minimal HTTP red tests for the post-US-328 public request shapes."""

from uuid import uuid4

from flask.testing import FlaskClient


def _saved_ref_body(*, revision: int = 1) -> dict[str, object]:
    return {
        "connection_ref": str(uuid4()),
        "configuration_revision": revision,
        "confirm": True,
        "expected_revision": 1,
        "idempotency_key": "stage39-red-key",
    }


def test_submit_saved_connection_shape_reaches_saved_service(client: FlaskClient) -> None:
    response = client.post(
        "/api/v1/tracking/items/tracking-red/submit",
        json=_saved_ref_body(),
    )
    # A missing tracking/ref may safely be rejected, but the legacy payload
    # validator must not reject this public shape for missing ``ab_config``.
    assert response.status_code != 400
    assert "ab_config" not in response.get_data(as_text=True)


def test_retry_sync_management_and_verify_shapes_never_accept_credentials(
    client: FlaskClient,
) -> None:
    body = _saved_ref_body()
    endpoints = [
        "/api/v1/tracking/items/tracking-red/retry",
        "/api/v1/tracking/sync",
        "/api/v1/tracking/items/tracking-red/management",
        "/api/v1/tracking/items/tracking-red/recover",
    ]
    for endpoint in endpoints:
        response = client.post(endpoint, json=body | {"action": "VERIFY_EXTERNAL"})
        assert "ab_config" not in response.get_data(as_text=True)
        assert "legacy_credentials" not in response.get_data(as_text=True)
