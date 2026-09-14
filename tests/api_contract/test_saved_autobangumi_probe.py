from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from ab_engine.models.management import AutoBangumiCapabilities
from apps.base import create_app
from apps.migu_orca_web import autobangumi_probe_service
from shared.errors import Stage1Error


def _client(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MIGU_ORCA_WEB_CONFIG_ROOT", str(tmp_path / "config"))
    return create_app("testing").test_client()


def _save(client, *, auth_mode: str = "password") -> dict[str, object]:
    config: dict[str, object]
    if auth_mode == "password":
        config = {
            "auth_mode": "password",
            "base_url": "ab.example.invalid:8080",
            "username": "probe-user",
            "password": "probe-secret",
        }
    else:
        config = {
            "auth_mode": "api_token",
            "base_url": "ab.example.invalid:8080",
            "token": "probe-token",
        }
    response = client.put(
        "/api/v1/settings/autobangumi",
        json={"confirm": True, "expected_configuration_revision": 0, "config": config},
    )
    assert response.status_code == 200
    return response.get_json()["result"]


def _verified_capabilities(*, status: str = "VERIFIED") -> AutoBangumiCapabilities:
    return AutoBangumiCapabilities(
        probe_status=status, version="3.1.18", adapter="legacy_3_1",
        subscription_list="SUPPORTED", subscription_detail="SUPPORTED",
        subscription_submit="SUPPORTED" if status == "VERIFIED" else "UNKNOWN",
        subscription_modify="SUPPORTED" if status == "VERIFIED" else "UNKNOWN",
        subscription_enable="SUPPORTED" if status == "VERIFIED" else "UNKNOWN",
        subscription_disable="SUPPORTED" if status == "VERIFIED" else "UNKNOWN",
        subscription_delete="SUPPORTED" if status == "VERIFIED" else "UNKNOWN",
        rss_list="SUPPORTED" if status == "VERIFIED" else "UNKNOWN",
        rss_modify="SUPPORTED" if status == "VERIFIED" else "UNKNOWN",
        rss_enable="SUPPORTED" if status == "VERIFIED" else "UNKNOWN",
        rss_disable="SUPPORTED" if status == "VERIFIED" else "UNKNOWN",
        rss_delete="SUPPORTED" if status == "VERIFIED" else "UNKNOWN",
        rss_refresh="SUPPORTED" if status == "VERIFIED" else "UNKNOWN",
        external_verify="SUPPORTED" if status == "VERIFIED" else "UNKNOWN",
        checked_at="2026-09-13T00:00:00+00:00",
        safe_message="fake probe",
    )


def test_saved_probe_uses_snapshot_and_updates_only_current_summary(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    saved = _save(client)
    calls: list[object] = []

    def fake_probe(config):
        calls.append(config)
        return _verified_capabilities()

    monkeypatch.setattr(autobangumi_probe_service, "probe_capabilities", fake_probe)
    response = client.post(
        "/api/v1/settings/autobangumi/probe",
        json={
            "connection_ref": saved["connection_ref"],
            "configuration_revision": saved["configuration_revision"],
        },
    )
    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["probe_status"] == "VERIFIED"
    assert len(calls) == 1
    assert "probe-secret" not in repr(calls[0])
    assert "ab.example.invalid" not in repr(calls[0])

    summary = client.get("/api/v1/settings/autobangumi").get_json()["result"]
    assert summary["connection_status"] == "VERIFIED"
    assert summary["capabilities"]["probe_status"] == "VERIFIED"
    assert "probe-secret" not in json.dumps(summary)
    assert "ab.example.invalid" not in json.dumps(summary)

    replaced = client.put(
        "/api/v1/settings/autobangumi",
        json={
            "confirm": True,
            "expected_configuration_revision": saved["configuration_revision"],
            "config": {
                "auth_mode": "password",
                "base_url": "new.example.invalid:8080",
                "username": "new-user",
                "password": "new-secret",
            },
        },
    )
    assert replaced.status_code == 200
    assert replaced.get_json()["result"]["connection_status"] == "CONFIGURED"
    assert replaced.get_json()["result"]["capabilities"] is None

    deleted = client.delete(
        "/api/v1/settings/autobangumi",
        json={"confirm": True, "expected_configuration_revision": 2},
    )
    assert deleted.status_code == 200
    assert client.get("/api/v1/settings/autobangumi").get_json()["result"]["connection_status"] == "UNCONFIGURED"


def test_saved_probe_fail_closed_for_partial_and_rejects_stale_generation(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    saved = _save(client, auth_mode="api_token")
    monkeypatch.setattr(
        autobangumi_probe_service,
        "probe_capabilities",
        lambda _config: _verified_capabilities(status="PARTIAL"),
    )
    response = client.post(
        "/api/v1/settings/autobangumi/probe",
        json={"connection_ref": saved["connection_ref"], "configuration_revision": saved["configuration_revision"]},
    )
    assert response.status_code == 200
    assert response.get_json()["result"]["probe_status"] == "PARTIAL"
    summary = client.get("/api/v1/settings/autobangumi").get_json()["result"]
    assert summary["connection_status"] == "ERROR"

    stale = client.post(
        "/api/v1/settings/autobangumi/probe",
        json={"connection_ref": saved["connection_ref"], "configuration_revision": 0},
    )
    assert stale.status_code == 409
    assert stale.get_json()["error_type"] == "configuration_revision_conflict"


def test_saved_probe_rejects_credentials_extra_fields_and_non_json(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    saved = _save(client)
    body = {"connection_ref": saved["connection_ref"], "configuration_revision": 1, "ab_config": {"password": "secret"}}
    response = client.post("/api/v1/settings/autobangumi/probe", json=body)
    assert response.status_code == 400
    assert "secret" not in response.get_data(as_text=True)
    form = client.post(
        "/api/v1/settings/autobangumi/probe",
        data="connection_ref=" + str(uuid4()),
        content_type="application/x-www-form-urlencoded",
    )
    assert form.status_code == 400


def test_saved_probe_rejects_unconfigured_stale_and_noncanonical_inputs(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    missing = client.post("/api/v1/settings/autobangumi/probe", json={"connection_ref": str(uuid4()), "configuration_revision": 0})
    assert missing.status_code == 400
    saved = _save(client)
    stale_ref = client.post("/api/v1/settings/autobangumi/probe", json={"connection_ref": str(uuid4()), "configuration_revision": 1})
    assert stale_ref.status_code == 409
    for body in (
        {"connection_ref": saved["connection_ref"].upper(), "configuration_revision": 1},
        {"connection_ref": saved["connection_ref"], "configuration_revision": True},
    ):
        response = client.post("/api/v1/settings/autobangumi/probe", json=body)
        assert response.status_code == 400
    stale = client.post("/api/v1/settings/autobangumi/probe", json={"connection_ref": saved["connection_ref"], "configuration_revision": 0})
    assert stale.status_code == 409


def test_saved_probe_failures_are_safe_and_release_lease(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    saved = _save(client)

    def fail_probe(_config):
        raise Stage1Error("ab_connection_failed", "upstream failed", "probe")

    monkeypatch.setattr(autobangumi_probe_service, "probe_capabilities", fail_probe)
    response = client.post("/api/v1/settings/autobangumi/probe", json={"connection_ref": saved["connection_ref"], "configuration_revision": 1})
    assert response.status_code == 200 and response.get_json()["result"]["probe_status"] == "FAILED"
    assert "upstream failed" not in response.get_data(as_text=True)

    def crash_probe(_config):
        raise RuntimeError("secret endpoint crash")

    monkeypatch.setattr(autobangumi_probe_service, "probe_capabilities", crash_probe)
    response = client.post("/api/v1/settings/autobangumi/probe", json={"connection_ref": saved["connection_ref"], "configuration_revision": 1})
    assert response.status_code == 200 and response.get_json()["result"]["probe_status"] == "FAILED"
    assert "secret endpoint crash" not in response.get_data(as_text=True)
    replaced = client.put("/api/v1/settings/autobangumi", json={"confirm": True, "expected_configuration_revision": 1, "config": {"auth_mode": "api_token", "base_url": "new.example.invalid:8080", "token": "new-token"}})
    assert replaced.status_code == 200


def test_saved_probe_failed_and_partial_never_verified_and_corrupt_is_safe(monkeypatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    saved = _save(client)
    for status in ("PARTIAL", "FAILED"):
        monkeypatch.setattr(autobangumi_probe_service, "probe_capabilities", lambda _config, status=status: _verified_capabilities(status=status))
        result = client.post("/api/v1/settings/autobangumi/probe", json={"connection_ref": saved["connection_ref"], "configuration_revision": 1}).get_json()["result"]
        assert result["probe_status"] == status
        assert client.get("/api/v1/settings/autobangumi").get_json()["result"]["connection_status"] == "ERROR"
    root = tmp_path / "config"
    path = root / "autobangumi.json"
    path.write_text('{"secret": "canary"}', encoding="utf-8")
    path.chmod(0o600)
    corrupt = client.post("/api/v1/settings/autobangumi/probe", json={"connection_ref": saved["connection_ref"], "configuration_revision": 1})
    assert corrupt.status_code == 500 and "canary" not in corrupt.get_data(as_text=True)
