from __future__ import annotations

from apps.base import create_app


def test_healthz_returns_success_response() -> None:
    client = create_app("testing").test_client()

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "result": "ok"}


def test_readiness_returns_success_response() -> None:
    client = create_app("testing").test_client()

    response = client.get("/readiness")

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "result": "ok"}
