from __future__ import annotations

from urllib.error import URLError

import pytest

from extensions.flask_api.api import sanitize_error_data
from qbittorrent_engine.controllers.qbittorrent_client import (
    QBittorrentResponse,
    create_qbittorrent_client,
)
from qbittorrent_engine.controllers.qbittorrent_config import QBittorrentConfig
from shared.errors import Stage1Error


class FakeTransport:
    def __init__(
        self,
        *,
        login_response: QBittorrentResponse | None = None,
        version_response: QBittorrentResponse | None = None,
    ) -> None:
        self.login_response = login_response or QBittorrentResponse(
            200,
            "Ok.",
            {"Set-Cookie": "SID=fake-session; HttpOnly; path=/"},
        )
        self.version_response = version_response or QBittorrentResponse(
            200,
            "v4.6.7",
            {},
        )
        self.post_requests: list[tuple[str, dict[str, str], float, bool]] = []
        self.get_requests: list[tuple[str, float, bool, str | None]] = []

    def post_form(
        self,
        url: str,
        data: dict[str, str],
        *,
        timeout: float,
        verify_tls: bool,
    ) -> QBittorrentResponse:
        self.post_requests.append((url, data, timeout, verify_tls))
        return self.login_response

    def get_text(
        self,
        url: str,
        *,
        timeout: float,
        verify_tls: bool,
        cookie: str | None = None,
    ) -> QBittorrentResponse:
        self.get_requests.append((url, timeout, verify_tls, cookie))
        return self.version_response


class ErrorTransport:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.post_requests: list[str] = []
        self.get_requests: list[str] = []

    def post_form(
        self,
        url: str,
        data: dict[str, str],
        *,
        timeout: float,
        verify_tls: bool,
    ) -> QBittorrentResponse:
        self.post_requests.append(url)
        raise self.error

    def get_text(
        self,
        url: str,
        *,
        timeout: float,
        verify_tls: bool,
        cookie: str | None = None,
    ) -> QBittorrentResponse:
        self.get_requests.append(url)
        raise self.error


def _config() -> QBittorrentConfig:
    return QBittorrentConfig(
        endpoint="https://qb.example.invalid/gui/",
        username="private-user",
        password="private-password",
        timeout_seconds=7.0,
        verify_tls=False,
    )


def test_create_qbittorrent_client_keeps_explicit_config_and_transport() -> None:
    config = _config()
    transport = FakeTransport()

    client = create_qbittorrent_client(config, transport=transport)

    assert client.config is config
    assert client.transport is transport
    assert client.session_cookie is None


def test_qbittorrent_client_logs_in_and_reads_app_version_with_fake_transport() -> None:
    transport = FakeTransport()
    client = create_qbittorrent_client(_config(), transport=transport)

    result = client.test_connection()

    assert result == {
        "status": "connected",
        "reachable": True,
        "version": "v4.6.7",
    }
    assert transport.post_requests == [
        (
            "https://qb.example.invalid/gui/api/v2/auth/login",
            {"username": "private-user", "password": "private-password"},
            7.0,
            False,
        )
    ]
    assert transport.get_requests == [
        (
            "https://qb.example.invalid/gui/api/v2/app/version",
            7.0,
            False,
            "SID=fake-session",
        )
    ]
    assert client.session_cookie == "SID=fake-session"


@pytest.mark.parametrize(
    "login_response",
    [
        QBittorrentResponse(403, "Fails.", {}),
        QBittorrentResponse(200, "Fails.", {"Set-Cookie": "SID=fake-session"}),
    ],
)
def test_qbittorrent_client_normalizes_auth_failure(
    login_response: QBittorrentResponse,
) -> None:
    transport = FakeTransport(login_response=login_response)
    client = create_qbittorrent_client(_config(), transport=transport)

    with pytest.raises(Stage1Error) as error:
        client.test_connection()

    assert error.value.as_dict() == {
        "error_type": "qbittorrent_auth_failed",
        "error_message": "qBittorrent 认证失败",
        "failed_step": "qbittorrent_login",
        "details": {"category": "auth"},
    }
    assert transport.get_requests == []


def test_qbittorrent_client_normalizes_timeout() -> None:
    transport = ErrorTransport(TimeoutError("timed out with SID=secret-session"))
    client = create_qbittorrent_client(_config(), transport=transport)

    with pytest.raises(Stage1Error) as error:
        client.test_connection()

    assert error.value.as_dict() == {
        "error_type": "qbittorrent_timeout",
        "error_message": "qBittorrent HTTP 请求超时",
        "failed_step": "qbittorrent_login",
        "details": {"category": "timeout"},
    }


def test_qbittorrent_client_normalizes_url_error_timeout() -> None:
    transport = ErrorTransport(URLError(TimeoutError("timed out secret-password")))
    client = create_qbittorrent_client(_config(), transport=transport)

    with pytest.raises(Stage1Error) as error:
        client.test_connection()

    assert error.value.error_type == "qbittorrent_timeout"
    assert error.value.failed_step == "qbittorrent_login"


@pytest.mark.parametrize(
    "login_response",
    [
        QBittorrentResponse(200, "<html>private response</html>", {}),
        QBittorrentResponse(200, "Ok.", {}),
    ],
)
def test_qbittorrent_client_normalizes_unexpected_login_response(
    login_response: QBittorrentResponse,
) -> None:
    transport = FakeTransport(login_response=login_response)
    client = create_qbittorrent_client(_config(), transport=transport)

    with pytest.raises(Stage1Error) as error:
        client.test_connection()

    assert error.value.as_dict() == {
        "error_type": "qbittorrent_unexpected_response",
        "error_message": "qBittorrent 响应无法识别",
        "failed_step": "qbittorrent_login",
        "details": {"category": "unexpected_response"},
    }
    assert "<html>private response</html>" not in error.value.message


def test_qbittorrent_client_normalizes_empty_version_response() -> None:
    transport = FakeTransport(version_response=QBittorrentResponse(200, "", {}))
    client = create_qbittorrent_client(_config(), transport=transport)

    with pytest.raises(Stage1Error) as error:
        client.test_connection()

    assert error.value.error_type == "qbittorrent_unexpected_response"
    assert error.value.failed_step == "qbittorrent_get_app_version"


def test_qbittorrent_client_sanitizes_injected_stage_error() -> None:
    sensitive_endpoint = "https://private-user:private-password@qb.example.invalid:8080"
    injected = Stage1Error(
        "qbittorrent_connection_failed",
        f"failed {sensitive_endpoint} SID=secret-session <html>raw</html>",
        "transport",
        {
            "endpoint": sensitive_endpoint,
            "username": "private-user",
            "password": "private-password",
            "cookie": "SID=secret-session",
            "raw_body": "<html>raw</html>",
        },
    )
    transport = ErrorTransport(injected)
    client = create_qbittorrent_client(_config(), transport=transport)

    with pytest.raises(Stage1Error) as error:
        client.test_connection()

    sanitized = sanitize_error_data(error.value.as_dict())
    assert sensitive_endpoint not in str(sanitized)
    assert "private-user" not in str(sanitized)
    assert "private-password" not in str(sanitized)
    assert "SID=secret-session" not in str(sanitized)
    assert "<html>raw</html>" not in str(sanitized)
    assert sanitized == {
        "error_type": "qbittorrent_connection_failed",
        "error_message": "qBittorrent HTTP 连接失败",
        "failed_step": "qbittorrent_login",
        "details": {"category": "connection"},
    }


def test_qbittorrent_client_rejects_invalid_endpoint_before_transport() -> None:
    transport = FakeTransport()
    config = QBittorrentConfig(
        endpoint="qb.example.invalid/gui",
        username="private-user",
        password="private-password",
        timeout_seconds=7.0,
        verify_tls=True,
    )

    with pytest.raises(Stage1Error) as error:
        create_qbittorrent_client(config, transport=transport)

    assert error.value.as_dict() == {
        "error_type": "config_error",
        "error_message": "qBittorrent endpoint 必须是 http(s) URL",
        "failed_step": "load_qbittorrent_config",
        "details": {"field": "endpoint"},
    }
    assert transport.post_requests == []
