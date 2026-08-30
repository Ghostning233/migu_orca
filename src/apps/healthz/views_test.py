from __future__ import annotations

from pathlib import Path

import pytest

from apps.base import create_app
from shared.errors import Stage1Error


def _client_with_storage_root(tmp_path: Path):
    """Create a test client with the Web storage root pointed at tmp.

    Readiness probes the server-side Web storage root; pointing it at tmp keeps
    the probe from creating the repo-level default ``.migu_orca/storage``
    (which would break browser tests).
    """
    from apps.migu_orca_web.services import set_web_storage_root

    set_web_storage_root(tmp_path)
    return create_app("testing").test_client()


def _reset_storage_root() -> None:
    from apps.migu_orca_web.services import set_web_storage_root

    set_web_storage_root(None)


def test_healthz_returns_success_response() -> None:
    """Liveness only proves the process is up — no storage work."""
    client = create_app("testing").test_client()

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "result": "ok"}


def test_readiness_returns_success_response(tmp_path: Path) -> None:
    """Readiness is 200 when the server-side Web storage root is usable."""
    client = _client_with_storage_root(tmp_path)
    try:
        response = client.get("/readiness")

        assert response.status_code == 200
        assert response.get_json() == {"ok": True, "result": "ok"}
        # The probe created the default storage layout under the tmp root.
        assert (tmp_path / "requests").is_dir()
    finally:
        _reset_storage_root()


def test_readiness_never_constructs_external_clients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Readiness must not probe MiKan/AutoBangumi/qBittorrent (US-195).

    We prove it by making every external client factory raise: if readiness
    tried to reach a real external system, the request would fail with that
    exception instead of returning 200.
    """
    from mikan_engine.controllers import mikan_client as mikan_client_module

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("readiness must not construct an external client")

    monkeypatch.setattr(mikan_client_module, "create_mikan_client", _forbidden)
    monkeypatch.setattr(
        "ab_engine.controllers.ab_http_client.create_auto_bangumi_http_client",
        _forbidden,
    )
    monkeypatch.setattr(
        "ab_engine.controllers.ab_http_client.create_auto_bangumi_submit_client",
        _forbidden,
    )
    monkeypatch.setattr(
        "qbittorrent_engine.controllers.qbittorrent_controller"
        ".test_qbittorrent_connection",
        _forbidden,
    )

    client = _client_with_storage_root(tmp_path)
    try:
        response = client.get("/readiness")
        assert response.status_code == 200
        assert response.get_json() == {"ok": True, "result": "ok"}
    finally:
        _reset_storage_root()


def test_readiness_returns_503_when_storage_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Readiness returns 503 when the storage root cannot be prepared.

    The failure envelope is stable ({ok: false, result: storage_unavailable})
    and contains no absolute path or sensitive value.
    """
    from apps.healthz import views as healthz_views

    def _storage_unavailable(*args: object, **kwargs: object) -> None:
        raise Stage1Error(
            "storage_error",
            "无法创建本地存储目录",
            "ensure_storage_layout",
            {"reason": "disk full"},
        )

    # Patch where the readiness view looks the symbol up (module namespace).
    monkeypatch.setattr(
        healthz_views, "ensure_storage_layout", _storage_unavailable
    )
    client = create_app("testing").test_client()
    response = client.get("/readiness")

    assert response.status_code == 503
    body = response.get_json()
    assert body == {"ok": False, "result": "storage_unavailable"}
    assert "tmp" not in str(body)
