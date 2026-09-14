from __future__ import annotations

import json
from pathlib import Path

from apps.base import create_app
from storage_engine.controllers.autobangumi_config_repository import AutoBangumiConfigRepository


def _client(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MIGU_ORCA_WEB_CONFIG_ROOT", str(tmp_path / "config"))
    return create_app("testing").test_client()


def test_settings_summary_is_exactly_safe_and_uncached(monkeypatch, tmp_path: Path) -> None:
    response = _client(monkeypatch, tmp_path).get("/api/v1/settings/autobangumi")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert set(response.get_json()["result"]) == {
        "configured", "configuration_revision", "connection_ref", "auth_mode",
        "credential_present", "connection_status", "checked_at", "capabilities",
    }
    assert response.get_json()["result"]["connection_status"] == "UNCONFIGURED"


def test_settings_rejects_untrusted_host_origin_form_and_non_strict_confirm(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    assert client.get("/api/v1/settings/autobangumi", headers={"Host": "evil.invalid"}).status_code == 400
    assert client.get("/api/v1/settings/autobangumi", headers={"Origin": "http://evil.invalid"}).status_code == 400
    assert client.put("/api/v1/settings/autobangumi", data="confirm=true", content_type="application/x-www-form-urlencoded").status_code == 400
    response = client.put(
        "/api/v1/settings/autobangumi",
        json={"confirm": 1, "expected_configuration_revision": 0, "config": {}},
    )
    assert response.status_code == 400


def test_settings_put_restart_get_delete_and_cas(tmp_path: Path, monkeypatch) -> None:
    client = _client(monkeypatch, tmp_path)
    config = {"auth_mode": "password", "base_url": "ab.example.invalid:8080", "username": "canary-user", "password": "canary-secret"}
    saved = client.put("/api/v1/settings/autobangumi", json={"confirm": True, "expected_configuration_revision": 0, "config": config}).get_json()["result"]
    assert set(saved) == {"configured", "configuration_revision", "connection_ref", "auth_mode", "credential_present", "connection_status", "checked_at", "capabilities"}
    assert saved["configuration_revision"] == 1 and saved["connection_status"] == "CONFIGURED" and saved["checked_at"] is None and saved["capabilities"] is None
    assert all(secret not in json.dumps(saved) for secret in ("canary-user", "canary-secret", "ab.example.invalid"))
    restarted = create_app("testing").test_client().get("/api/v1/settings/autobangumi").get_json()["result"]
    assert restarted["connection_ref"] == saved["connection_ref"] and restarted["configuration_revision"] == 1
    deleted = client.delete("/api/v1/settings/autobangumi", json={"confirm": True, "expected_configuration_revision": 1}).get_json()["result"]
    assert deleted["configured"] is False and deleted["configuration_revision"] == 2 and deleted["connection_status"] == "UNCONFIGURED"
    stale = client.put("/api/v1/settings/autobangumi", json={"confirm": True, "expected_configuration_revision": 0, "config": config})
    assert stale.status_code == 409


def test_us338_saved_connection_survives_real_app_rebuild_and_cross_page_reads(tmp_path: Path, monkeypatch) -> None:
    """US-338: exercise real Flask routes across pages and an actual app rebuild."""
    config_root = tmp_path / "deployment-config"
    monkeypatch.setenv("MIGU_ORCA_WEB_CONFIG_ROOT", str(config_root))
    client = create_app("testing").test_client()
    secret_values = ("cross-page-user", "cross-page-password", "cross-page-token", "ab.private.invalid")
    config = {
        "auth_mode": "password", "base_url": "ab.private.invalid:8080",
        "username": "cross-page-user", "password": "cross-page-password",
    }
    saved = client.put("/api/v1/settings/autobangumi", json={
        "confirm": True, "expected_configuration_revision": 0, "config": config,
    })
    assert saved.status_code == 200
    ref = saved.get_json()["result"]["connection_ref"]

    # Rebuild the Flask app/repository, then read each real page/API boundary.
    rebuilt = create_app("testing").test_client()
    responses = [
        rebuilt.get("/api/v1/settings/autobangumi"),
        rebuilt.get("/api/v1/requests"),
        rebuilt.get("/api/v1/tracking/items"),
    ]
    assert all(response.status_code == 200 for response in responses)
    assert responses[0].get_json()["result"]["connection_ref"] == ref
    body = "\n".join(response.get_data(as_text=True) for response in responses)
    assert all(secret not in body for secret in secret_values)
    assert str(config_root) not in body


def test_settings_lease_blocks_both_api_mutations_and_releases(tmp_path: Path, monkeypatch) -> None:
    client = _client(monkeypatch, tmp_path)
    config = {"auth_mode": "api_token", "base_url": "localhost:8080", "token": "canary-token"}
    client.put("/api/v1/settings/autobangumi", json={"confirm": True, "expected_configuration_revision": 0, "config": config})
    repo = AutoBangumiConfigRepository(tmp_path / "config")
    with repo.acquire_lease(configuration_revision=1):
        for method in ("put", "delete"):
            response = getattr(client, method)("/api/v1/settings/autobangumi", json={"confirm": True, "expected_configuration_revision": 1, **({"config": config} if method == "put" else {})})
            assert response.status_code == 409 and response.get_json()["error_type"] == "connection_in_use"
    assert repo.load().configuration_revision == 1


def test_corrupt_get_is_fixed_error_and_no_secret_or_path(tmp_path: Path, monkeypatch) -> None:
    client = _client(monkeypatch, tmp_path)
    root = tmp_path / "config"
    root.mkdir(mode=0o700)
    path = root / "autobangumi.json"
    path.write_text('{"canary-secret": "bad"}', encoding="utf-8")
    path.chmod(0o600)
    response = client.get("/api/v1/settings/autobangumi")
    assert response.status_code == 500
    body = response.get_data(as_text=True)
    assert "canary-secret" not in body and str(tmp_path) not in body


def test_origins_canonical_default_port_and_explicit_vite(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MIGU_ORCA_TRUSTED_ORIGINS", "http://localhost:5173,https://vite.example.invalid")
    client = _client(monkeypatch, tmp_path)
    assert client.get("/api/v1/settings/autobangumi", headers={"Origin": "http://localhost"}).status_code == 200
    assert client.get("/api/v1/settings/autobangumi", headers={"Origin": "http://localhost:5173"}).status_code == 200
    assert client.get("/api/v1/settings/autobangumi", headers={"Origin": "https://vite.example.invalid"}).status_code == 200
    for origin in ("https://localhost", "http://localhost:5174", "http://localhost/path", "http://user@localhost"):
        response = client.get("/api/v1/settings/autobangumi", headers={"Origin": origin})
        assert response.status_code == 400 and response.get_json()["error_type"] == "untrusted_origin"
    assert "Access-Control-Allow-Origin" not in client.get("/api/v1/settings/autobangumi").headers


def test_ipv6_loopback_and_explicit_trusted_host(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    assert client.get("/api/v1/settings/autobangumi", headers={"Host": "[::1]"}).status_code == 200
    assert client.get("/api/v1/settings/autobangumi", headers={"Host": "[::1]:5000"}).status_code == 200
    assert client.get("/api/v1/settings/autobangumi", headers={"Host": "localhost:5000"}).status_code == 200
    assert client.get("/api/v1/settings/autobangumi", headers={"Host": "[fd00::1]"}).status_code == 400
    monkeypatch.setenv("MIGU_ORCA_TRUSTED_HOSTS", "[fd00::1]")
    client = _client(monkeypatch, tmp_path)
    assert client.get("/api/v1/settings/autobangumi", headers={"Host": "[fd00::1]"}).status_code == 200
    assert client.get("/api/v1/settings/autobangumi", headers={"Host": "[fd00::1]:5000"}).status_code == 200
    rejected = client.get("/api/v1/settings/autobangumi", headers={"Host": "[fd00::2]"})
    assert rejected.status_code == 400 and rejected.get_json()["error_type"] == "untrusted_host"
