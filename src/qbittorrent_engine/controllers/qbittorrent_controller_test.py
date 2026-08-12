from __future__ import annotations

from pathlib import Path

import pytest

from qbittorrent_engine.controllers.qbittorrent_config import QBittorrentConfig
from qbittorrent_engine.controllers.qbittorrent_controller import (
    test_qbittorrent_connection as run_qbittorrent_connection_test,
)
from shared.errors import Stage1Error


class FakeClient:
    def __init__(
        self,
        response: dict[str, object] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response or {
            "status": "connected",
            "reachable": True,
            "version": "v4.6.7",
            "endpoint": "https://qb.example.invalid/gui/",
            "username": "private-user",
            "password": "private-password",
            "cookie": "SID=secret-session",
        }
        self.error = error
        self.calls = 0

    def test_connection(self) -> dict[str, object]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.response


def test_qbittorrent_connection_uses_inline_config_and_returns_safe_summary() -> None:
    captured: dict[str, object] = {}

    def fake_create_qbittorrent_client(
        config: QBittorrentConfig,
        *,
        transport: object | None = None,
    ) -> FakeClient:
        captured["config"] = config
        captured["transport"] = transport
        return FakeClient()

    result = run_qbittorrent_connection_test(
        qbittorrent_config={
            "endpoint": "https://qb.example.invalid/gui/",
            "username": "private-user",
            "password": "private-password",
            "timeout_seconds": 7,
            "verify_tls": False,
        },
        client_factory=fake_create_qbittorrent_client,
    )

    assert result == {
        "success": True,
        "summary": {
            "status": "connected",
            "reachable": True,
            "version": "v4.6.7",
        },
        "error": None,
    }
    assert "private-user" not in str(result)
    assert "private-password" not in str(result)
    assert "SID=secret-session" not in str(result)
    assert isinstance(captured["config"], QBittorrentConfig)
    assert captured["config"].endpoint == "https://qb.example.invalid/gui/"
    assert captured["config"].username == "private-user"
    assert captured["config"].password == "private-password"
    assert captured["transport"] is None


def test_qbittorrent_connection_uses_config_file_path(tmp_path: Path) -> None:
    path = tmp_path / "qbittorrent.json"
    path.write_text(
        """
        {
          "endpoint": "https://qb.example.invalid/gui/",
          "username": "private-user",
          "password": "private-password",
          "timeout_seconds": 6,
          "verify_tls": true
        }
        """,
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    def fake_create_qbittorrent_client(
        config: QBittorrentConfig,
        *,
        transport: object | None = None,
    ) -> FakeClient:
        captured["config"] = config
        return FakeClient()

    result = run_qbittorrent_connection_test(
        qbittorrent_config_path=path,
        client_factory=fake_create_qbittorrent_client,
    )

    assert result["success"] is True
    assert result["summary"]["status"] == "connected"
    assert captured["config"].timeout_seconds == 6.0
    assert captured["config"].verify_tls is True


def test_qbittorrent_connection_sanitizes_failures() -> None:
    client = FakeClient(
        error=Stage1Error(
            "qbittorrent_timeout",
            "qBittorrent HTTP 请求超时 from https://qb.example.invalid/gui/?token=secret",
            "qbittorrent_login",
            {
                "endpoint": "https://qb.example.invalid/gui/?token=secret",
                "cookie": "SID=secret-session",
            },
        )
    )

    result = run_qbittorrent_connection_test(qbittorrent_client=client)

    assert result == {
        "success": False,
        "summary": None,
        "error": {
            "error_type": "qbittorrent_timeout",
            "error_message": "qBittorrent HTTP 请求超时 from [redacted-url]",
            "failed_step": "qbittorrent_login",
            "details": {
                "endpoint": "[redacted-url]",
                "cookie": "[redacted]",
            },
        },
    }


@pytest.mark.parametrize(
    ("error", "error_type", "category"),
    [
        (
            TimeoutError("timed out with SID=secret-session"),
            "qbittorrent_timeout",
            "timeout",
        ),
        (
            ConnectionError("refused private-password"),
            "qbittorrent_connection_failed",
            "connection",
        ),
        (
            ValueError("<html>raw private-user response</html>"),
            "qbittorrent_unexpected_response",
            "unexpected_response",
        ),
    ],
)
def test_qbittorrent_connection_classifies_unexpected_client_failures(
    error: Exception,
    error_type: str,
    category: str,
) -> None:
    result = run_qbittorrent_connection_test(
        qbittorrent_client=FakeClient(error=error)
    )

    assert result == {
        "success": False,
        "summary": None,
        "error": {
            "error_type": error_type,
            "error_message": result["error"]["error_message"],
            "failed_step": "test_qbittorrent_connection",
            "details": {"category": category},
        },
    }
    assert "private-user" not in str(result)
    assert "private-password" not in str(result)
    assert "SID=secret-session" not in str(result)
    assert "<html>raw private-user response</html>" not in str(result)


def test_qbittorrent_connection_rejects_missing_explicit_input() -> None:
    result = run_qbittorrent_connection_test()

    assert result["success"] is False
    assert result["error"]["error_type"] == "config_error"
    assert result["error"]["failed_step"] == "test_qbittorrent_connection"


def test_qbittorrent_connection_rejects_ambiguous_config_inputs() -> None:
    result = run_qbittorrent_connection_test(
        qbittorrent_config=QBittorrentConfig(
            endpoint="https://qb.example.invalid/gui/",
            username="private-user",
            password="private-password",
            timeout_seconds=7.0,
            verify_tls=True,
        ),
        qbittorrent_config_path="/private/qbittorrent.json",
    )

    assert result["success"] is False
    assert result["error"]["error_type"] == "config_error"
    assert "/private/qbittorrent.json" not in str(result)
