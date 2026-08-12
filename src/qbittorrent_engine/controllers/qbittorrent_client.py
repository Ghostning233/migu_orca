from __future__ import annotations

import ssl
from dataclasses import dataclass
from http.cookies import SimpleCookie
from collections.abc import Callable
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from qbittorrent_engine.controllers.qbittorrent_config import QBittorrentConfig
from shared.errors import Stage1Error


@dataclass(frozen=True)
class QBittorrentResponse:
    """Minimal HTTP response shape needed by the qBittorrent adapter."""

    status_code: int
    body: str
    headers: dict[str, str]


class QBittorrentTransport(Protocol):
    """Transport boundary for qBittorrent Web API calls."""

    def post_form(
        self,
        url: str,
        data: dict[str, str],
        *,
        timeout: float,
        verify_tls: bool,
    ) -> QBittorrentResponse:
        """POST form data to qBittorrent."""

    def get_text(
        self,
        url: str,
        *,
        timeout: float,
        verify_tls: bool,
        cookie: str | None = None,
    ) -> QBittorrentResponse:
        """GET text from qBittorrent."""


class UrlopenQBittorrentTransport:
    """urllib-backed transport for explicit qBittorrent Web API calls."""

    def post_form(
        self,
        url: str,
        data: dict[str, str],
        *,
        timeout: float,
        verify_tls: bool,
    ) -> QBittorrentResponse:
        body = urlencode(data).encode("utf-8")
        request = Request(
            url,
            data=body,
            headers={
                "Accept": "text/plain",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "migu-orca/0.1",
            },
            method="POST",
        )
        return _open_request(request, timeout=timeout, verify_tls=verify_tls)

    def get_text(
        self,
        url: str,
        *,
        timeout: float,
        verify_tls: bool,
        cookie: str | None = None,
    ) -> QBittorrentResponse:
        headers = {
            "Accept": "text/plain",
            "User-Agent": "migu-orca/0.1",
        }
        if cookie:
            headers["Cookie"] = cookie
        request = Request(url, headers=headers, method="GET")
        return _open_request(request, timeout=timeout, verify_tls=verify_tls)


class QBittorrentClient:
    """Explicit qBittorrent Web API adapter with in-memory session state."""

    def __init__(
        self,
        config: QBittorrentConfig,
        *,
        transport: QBittorrentTransport | None = None,
    ) -> None:
        _validate_endpoint(config.endpoint)
        self._config = config
        self._transport = transport or UrlopenQBittorrentTransport()
        self._session_cookie: str | None = None

    @property
    def config(self) -> QBittorrentConfig:
        return self._config

    @property
    def transport(self) -> QBittorrentTransport:
        return self._transport

    @property
    def session_cookie(self) -> str | None:
        """Return the current in-memory qBittorrent session cookie."""

        return self._session_cookie

    def login(self) -> None:
        response = _call_qbittorrent(
            lambda: self._transport.post_form(
                _api_url(self._config.endpoint, "auth/login"),
                {
                    "username": self._config.username,
                    "password": self._config.password,
                },
                timeout=self._config.timeout_seconds,
                verify_tls=self._config.verify_tls,
            ),
            failed_step="qbittorrent_login",
        )
        if response.status_code in {401, 403} or response.body.strip().lower() == "fails.":
            raise _auth_failed("qbittorrent_login")
        if response.status_code < 200 or response.status_code >= 300:
            raise _http_failed("qbittorrent_login", response.status_code)

        cookie = _extract_session_cookie(response.headers)
        if response.body.strip().lower() != "ok." or cookie is None:
            raise _unexpected_response("qbittorrent_login")

        self._session_cookie = cookie

    def get_app_version(self) -> str:
        if self._session_cookie is None:
            self.login()

        response = _call_qbittorrent(
            lambda: self._transport.get_text(
                _api_url(self._config.endpoint, "app/version"),
                timeout=self._config.timeout_seconds,
                verify_tls=self._config.verify_tls,
                cookie=self._session_cookie,
            ),
            failed_step="qbittorrent_get_app_version",
        )
        if response.status_code in {401, 403}:
            raise _auth_failed("qbittorrent_get_app_version")
        if response.status_code < 200 or response.status_code >= 300:
            raise _http_failed("qbittorrent_get_app_version", response.status_code)

        version = response.body.strip()
        if not version:
            raise _unexpected_response("qbittorrent_get_app_version")
        return version

    def test_connection(self) -> dict[str, object]:
        version = self.get_app_version()
        return {
            "status": "connected",
            "reachable": True,
            "version": version,
        }


def create_qbittorrent_client(
    config: QBittorrentConfig,
    *,
    transport: QBittorrentTransport | None = None,
) -> QBittorrentClient:
    """Build the qBittorrent client from explicit qBittorrent config."""

    return QBittorrentClient(config, transport=transport)


def _open_request(
    request: Request,
    *,
    timeout: float,
    verify_tls: bool,
) -> QBittorrentResponse:
    context = None
    if request.full_url.lower().startswith("https://") and not verify_tls:
        context = ssl._create_unverified_context()
    try:
        with urlopen(request, timeout=timeout, context=context) as response:
            body = response.read().decode("utf-8")
            headers = {key: value for key, value in response.headers.items()}
            return QBittorrentResponse(response.status, body, headers)
    except HTTPError as exc:
        try:
            body = exc.read().decode("utf-8")
        except Exception:
            body = ""
        headers = {key: value for key, value in exc.headers.items()}
        return QBittorrentResponse(exc.code, body, headers)


def _call_qbittorrent(
    call: Callable[[], QBittorrentResponse],
    *,
    failed_step: str,
) -> QBittorrentResponse:
    try:
        response = call()
    except Stage1Error as exc:
        raise _sanitize_qbittorrent_stage_error(exc, failed_step) from exc
    except URLError as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, TimeoutError):
            raise _timeout(failed_step) from exc
        raise _connection_failed(failed_step) from exc
    except TimeoutError as exc:
        raise _timeout(failed_step) from exc
    except ConnectionError as exc:
        raise _connection_failed(failed_step) from exc

    if not isinstance(response, QBittorrentResponse):
        raise _unexpected_response(failed_step)
    return response


def _sanitize_qbittorrent_stage_error(
    error: Stage1Error,
    failed_step: str,
) -> Stage1Error:
    if error.error_type == "qbittorrent_auth_failed":
        return _auth_failed(failed_step)
    if error.error_type == "qbittorrent_timeout":
        return _timeout(failed_step)
    if error.error_type == "qbittorrent_connection_failed":
        return _connection_failed(failed_step)
    if error.error_type == "qbittorrent_http_failed":
        status_code = error.details.get("status_code")
        return _http_failed(
            failed_step,
            status_code if isinstance(status_code, int) else None,
        )
    if error.error_type == "qbittorrent_unexpected_response":
        return _unexpected_response(failed_step)
    return _unexpected_response(failed_step)


def _api_url(endpoint: str, api_path: str) -> str:
    return urljoin(endpoint.rstrip("/") + "/", f"api/v2/{api_path}")


def _validate_endpoint(endpoint: str) -> None:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise Stage1Error(
            "config_error",
            "qBittorrent endpoint 必须是 http(s) URL",
            "load_qbittorrent_config",
            {"field": "endpoint"},
        )


def _extract_session_cookie(headers: dict[str, str]) -> str | None:
    cookie_header = _header_value(headers, "set-cookie")
    if not cookie_header:
        return None
    cookie = SimpleCookie()
    cookie.load(cookie_header)
    sid = cookie.get("SID")
    if sid is None or not sid.value:
        return None
    return f"SID={sid.value}"


def _header_value(headers: dict[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return None


def _auth_failed(failed_step: str) -> Stage1Error:
    return Stage1Error(
        "qbittorrent_auth_failed",
        "qBittorrent 认证失败",
        failed_step,
        {"category": "auth"},
    )


def _http_failed(failed_step: str, status_code: int | None) -> Stage1Error:
    details = {"status_code": status_code} if status_code is not None else {}
    return Stage1Error(
        "qbittorrent_http_failed",
        "qBittorrent HTTP 请求失败",
        failed_step,
        details,
    )


def _connection_failed(failed_step: str) -> Stage1Error:
    return Stage1Error(
        "qbittorrent_connection_failed",
        "qBittorrent HTTP 连接失败",
        failed_step,
        {"category": "connection"},
    )


def _timeout(failed_step: str) -> Stage1Error:
    return Stage1Error(
        "qbittorrent_timeout",
        "qBittorrent HTTP 请求超时",
        failed_step,
        {"category": "timeout"},
    )


def _unexpected_response(failed_step: str) -> Stage1Error:
    return Stage1Error(
        "qbittorrent_unexpected_response",
        "qBittorrent 响应无法识别",
        failed_step,
        {"category": "unexpected_response"},
    )
