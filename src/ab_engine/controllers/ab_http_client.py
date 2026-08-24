from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Literal, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from ab_engine.controllers.ab_config import AutoBangumiConfig
from shared.errors import Stage1Error


class AutoBangumiHttpTransport(Protocol):
    """Transport boundary used by the API Token compatibility adapter."""

    def post_json(
        self,
        endpoint: str,
        headers: Mapping[str, str],
        payload: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        """POST a JSON payload and return the decoded response object."""

    def request_json(
        self,
        method: Literal["GET", "POST"],
        endpoint: str,
        headers: Mapping[str, str],
        payload: Mapping[str, str] | None = None,
        *,
        timeout: float,
    ) -> dict[str, Any]:
        """Make one JSON request without following credentialed redirects."""


class AutoBangumiLegacyTransport(Protocol):
    """Request boundary for the 3.1 password-login adapter."""

    def request_json(
        self,
        method: Literal["GET", "POST"],
        endpoint: str,
        headers: Mapping[str, str],
        payload: Mapping[str, str] | None = None,
        *,
        timeout: float,
    ) -> dict[str, Any]:
        """Make one JSON API request without following redirects."""

    def post_json_same_origin(
        self,
        endpoint: str,
        headers: Mapping[str, str],
        payload: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        """POST a JSON request without exposing session credentials."""


class UrlopenAutoBangumiHttpTransport:
    """urllib-backed HTTP transport for Auto Bangumi JSON requests."""

    def post_json(
        self,
        endpoint: str,
        headers: Mapping[str, str],
        payload: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        request = Request(
            endpoint,
            data=json.dumps(deepcopy(payload), ensure_ascii=False).encode("utf-8"),
            headers=dict(headers),
            method="POST",
        )

        try:
            with urlopen(request, timeout=timeout) as response:
                response_body = response.read()
        except HTTPError as exc:
            raise _http_error_to_stage1_error(exc) from exc
        except URLError as exc:
            raise _network_error_to_stage1_error(exc) from exc
        except TimeoutError as exc:
            raise _timeout_error() from exc

        try:
            ab_response = json.loads(response_body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise Stage1Error(
                "invalid_ab_response",
                "Auto Bangumi 响应不是合法 JSON",
                "create_ab_subscription",
            ) from exc

        if not isinstance(ab_response, dict):
            raise Stage1Error(
                "invalid_ab_response",
                "Auto Bangumi 响应必须是 JSON 对象",
                "create_ab_subscription",
            )
        return ab_response

    def request_json(
        self,
        method: Literal["GET", "POST"],
        endpoint: str,
        headers: Mapping[str, str],
        payload: Mapping[str, str] | None = None,
        *,
        timeout: float,
    ) -> dict[str, Any]:
        data = None
        if payload is not None:
            data = urlencode(dict(payload)).encode("utf-8")
        request = Request(endpoint, data=data, headers=dict(headers), method=method)
        try:
            # Never follow redirects: a token Cookie must not leave the service origin.
            with build_opener(_RejectRedirects()).open(request, timeout=timeout) as response:
                response_body = response.read()
        except HTTPError as exc:
            raise _http_error_to_stage1_error(exc, step="probe_ab_connection") from exc
        except URLError as exc:
            raise _network_error_to_stage1_error(exc, step="probe_ab_connection") from exc
        except TimeoutError as exc:
            raise _timeout_error("probe_ab_connection") from exc
        return _decode_response(response_body, step="probe_ab_connection")

    def post_json_same_origin(
        self,
        endpoint: str,
        headers: Mapping[str, str],
        payload: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        request = Request(
            endpoint,
            data=json.dumps(deepcopy(payload), ensure_ascii=False).encode("utf-8"),
            headers=dict(headers),
            method="POST",
        )
        try:
            # A session Cookie must never be forwarded by a redirect.
            with build_opener(_RejectRedirects()).open(request, timeout=timeout) as response:
                response_body = response.read()
        except HTTPError as exc:
            raise _http_error_to_stage1_error(exc) from exc
        except URLError as exc:
            raise _network_error_to_stage1_error(exc) from exc
        except TimeoutError as exc:
            raise _timeout_error() from exc
        return _decode_response(response_body, step="create_ab_subscription")


class _RejectRedirects(HTTPRedirectHandler):
    """Fail closed on redirects so request-scoped credentials stay same-origin."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> Request | None:
        return None


class AutoBangumiHttpClient:
    """API Token compatibility adapter with read-only, fail-closed capability probing.

    No current Token API write contract is verified.  In particular, this adapter
    must never reinterpret the legacy 3.1 RSS body as a Token API request.
    """

    def __init__(
        self,
        config: AutoBangumiConfig,
        *,
        transport: AutoBangumiHttpTransport | None = None,
        timeout: float = 30,
    ) -> None:
        self._config = config
        self._transport = transport or UrlopenAutoBangumiHttpTransport()
        self._timeout = timeout

    def create_subscription(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Reject writes until a version-specific Token API contract is covered."""

        # Validate the public call shape before returning the compatibility error;
        # this retains the existing input-validation contract without ever sending
        # a request with the Bearer credential.
        _validate_subscription_payload(payload)
        if self._config.auth_mode != "api_token" or not self._config.token:
            raise Stage1Error(
                "ab_submit_unsupported",
                "当前 Auto Bangumi 认证模式暂不支持提交",
                "create_ab_subscription",
            )
        raise Stage1Error(
            "ab_submit_unsupported",
            "当前 Auto Bangumi 版本暂不支持提交",
            "create_ab_subscription",
        )

    def probe(self) -> dict[str, Any]:
        """Probe a Token-authenticated service without attempting any write."""

        if self._config.auth_mode != "api_token" or not self._config.token:
            raise Stage1Error(
                "ab_probe_unsupported",
                "当前 Auto Bangumi 认证模式暂不支持此探测方式",
                "probe_ab_connection",
            )
        try:
            status = self._transport.request_json(
                "GET",
                _api_endpoint(self._config.base_url, "/api/v1/status"),
                {
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self._config.token}",
                },
                timeout=self._timeout,
            )
        except Stage1Error:
            raise
        except HTTPError as exc:
            raise _http_error_to_stage1_error(exc, step="probe_ab_connection") from exc
        except URLError as exc:
            raise _network_error_to_stage1_error(exc, step="probe_ab_connection") from exc
        except (TimeoutError, ConnectionError) as exc:
            if isinstance(exc, TimeoutError):
                raise _timeout_error("probe_ab_connection") from exc
            raise Stage1Error(
                "ab_connection_failed",
                "Auto Bangumi HTTP 连接失败",
                "probe_ab_connection",
                {"category": "connection"},
            ) from exc
        return {
            "reachable": True,
            "authenticated": True,
            "version": _status_version(status),
            "adapter": "api_token",
            "submit_supported": False,
        }


class LegacyAutoBangumi31Client:
    """3.1.x password-login client with one in-memory, same-origin token session."""

    def __init__(
        self,
        config: AutoBangumiConfig,
        *,
        transport: AutoBangumiLegacyTransport | None = None,
        timeout: float = 30,
    ) -> None:
        self._config = config
        self._transport = transport or UrlopenAutoBangumiHttpTransport()
        self._timeout = timeout
        self._token: str | None = None

    def probe(self) -> dict[str, Any]:
        """Login then read the public 3.1 status summary without persisting credentials."""
        if self._config.auth_mode != "password":
            raise Stage1Error(
                "ab_probe_unsupported",
                "当前 Auto Bangumi 认证模式暂不支持此探测方式",
                "probe_ab_connection",
            )
        self._authenticate()
        status = self._request_json(
            "GET",
            _api_endpoint(self._config.base_url, "/api/v1/status"),
            {"Accept": "application/json", "Cookie": self._session_cookie()},
        )
        version = _status_version(status)
        if not version.startswith("3.1."):
            raise Stage1Error(
                "ab_unsupported_version",
                "当前 Auto Bangumi 版本暂不受支持",
                "probe_ab_connection",
            )
        return {
            "reachable": True,
            "authenticated": True,
            "version": version,
            "adapter": "legacy_3_1",
            "submit_supported": True,
        }

    def create_subscription(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Submit a prepared 3.1 ``{data: Bangumi, rss: RSSItem}`` body."""
        self._validate_legacy_subscription_payload(payload)
        self._authenticate()
        response = self._post_json(
            _api_endpoint(self._config.base_url, "/api/v1/rss/subscribe"),
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Cookie": self._session_cookie(),
            },
            payload,
        )
        if response.get("status") is True:
            return deepcopy(response)
        raise Stage1Error(
            "ab_submit_failed",
            "Auto Bangumi 提交失败",
            "create_ab_subscription",
        )

    def _authenticate(self) -> None:
        login = self._request_json(
            "POST",
            _api_endpoint(self._config.base_url, "/api/v1/auth/login"),
            {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
            {"username": self._config.username or "", "password": self._config.password or ""},
        )
        token = login.get("access_token")
        if not isinstance(token, str) or not token.strip():
            raise Stage1Error(
                "invalid_ab_response",
                "Auto Bangumi 登录响应无有效令牌",
                "probe_ab_connection",
            )
        self._token = token.strip()

    def _session_cookie(self) -> str:
        if self._token is None:
            raise Stage1Error("ab_auth_failed", "Auto Bangumi 认证失败", "create_ab_subscription")
        return f"token={self._token}"

    def _request_json(
        self,
        method: Literal["GET", "POST"],
        endpoint: str,
        headers: Mapping[str, str],
        payload: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            return self._transport.request_json(
                method, endpoint, headers, payload, timeout=self._timeout
            )
        except Stage1Error:
            raise
        except HTTPError as exc:
            raise _http_error_to_stage1_error(exc, step="probe_ab_connection") from exc
        except URLError as exc:
            raise _network_error_to_stage1_error(exc, step="probe_ab_connection") from exc
        except (TimeoutError, ConnectionError) as exc:
            if isinstance(exc, TimeoutError):
                raise _timeout_error("probe_ab_connection") from exc
            raise Stage1Error(
                "ab_connection_failed",
                "Auto Bangumi HTTP 连接失败",
                "probe_ab_connection",
                {"category": "connection"},
            ) from exc

    def _post_json(
        self,
        endpoint: str,
        headers: Mapping[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            return self._transport.post_json_same_origin(
                endpoint, headers, deepcopy(payload), timeout=self._timeout
            )
        except Stage1Error:
            raise
        except HTTPError as exc:
            raise _http_error_to_stage1_error(exc) from exc
        except URLError as exc:
            raise _network_error_to_stage1_error(exc) from exc
        except (TimeoutError, ConnectionError) as exc:
            raise _network_exception_to_stage1_error(exc) from exc

    @staticmethod
    def _validate_legacy_subscription_payload(payload: dict[str, Any]) -> None:
        if not isinstance(payload.get("data"), dict) or not isinstance(
            payload.get("rss"), dict
        ):
            raise Stage1Error(
                "invalid_ab_payload",
                "Auto Bangumi 3.1 payload 必须包含 data 和 rss 对象",
                "create_ab_subscription",
            )


def create_auto_bangumi_http_client(
    config: AutoBangumiConfig,
    *,
    transport: AutoBangumiHttpTransport | None = None,
) -> AutoBangumiHttpClient:
    """Build the real Auto Bangumi HTTP client from explicit AB config."""

    return AutoBangumiHttpClient(config, transport=transport)


def create_legacy_3_1_auto_bangumi_client(
    config: AutoBangumiConfig,
    *,
    transport: AutoBangumiLegacyTransport | None = None,
) -> LegacyAutoBangumi31Client:
    """Build the request-scoped password-login adapter for AutoBangumi 3.1.x."""
    return LegacyAutoBangumi31Client(config, transport=transport)


def _api_endpoint(base_url: str, path: str) -> str:
    """Append a fixed API path after re-checking the configured service origin."""
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise Stage1Error("config_error", "Auto Bangumi 配置无效", "probe_ab_connection")
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _status_version(status: Mapping[str, Any]) -> str:
    value = status.get("version")
    if value is None and isinstance(status.get("data"), Mapping):
        value = status["data"].get("version")
    if not isinstance(value, str) or not value.strip():
        raise Stage1Error(
            "invalid_ab_response",
            "Auto Bangumi 状态响应缺少版本",
            "probe_ab_connection",
        )
    return value.strip()


def _decode_response(response_body: bytes, *, step: str) -> dict[str, Any]:
    try:
        ab_response = json.loads(response_body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise Stage1Error("invalid_ab_response", "Auto Bangumi 响应不是合法 JSON", step) from exc
    if not isinstance(ab_response, dict):
        raise Stage1Error("invalid_ab_response", "Auto Bangumi 响应必须是 JSON 对象", step)
    return ab_response


def _validate_subscription_payload(payload: dict[str, Any]) -> dict[str, Any]:
    validated: dict[str, Any] = {}
    for field in ("title", "rss_url", "save_path"):
        validated[field] = _required_payload_string(payload.get(field), field)
    filter_rule = payload.get("filter_rule")
    if not isinstance(filter_rule, dict):
        raise Stage1Error(
            "invalid_ab_payload",
            "Auto Bangumi payload 字段类型错误",
            "validate_ab_subscription_payload",
            {"field": "filter_rule", "expected_type": "object"},
        )
    validated["filter_rule"] = deepcopy(filter_rule)
    return validated


def _validate_ab_response(ab_response: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(ab_response, dict):
        raise Stage1Error(
            "invalid_ab_response",
            "Auto Bangumi 响应必须是 JSON 对象",
            "create_ab_subscription",
        )

    if not _has_subscription_id(ab_response):
        raise Stage1Error(
            "invalid_ab_response",
            "Auto Bangumi 响应缺少订阅 ID",
            "create_ab_subscription",
            {"fields": ["id", "subscription_id", "ab_subscription_id"]},
        )
    return deepcopy(ab_response)


def _has_subscription_id(ab_response: Mapping[str, Any]) -> bool:
    for field in ("id", "subscription_id", "ab_subscription_id"):
        value = ab_response.get(field)
        if isinstance(value, str) and value.strip():
            return True
    return False


def _required_payload_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Stage1Error(
            "invalid_ab_payload",
            "Auto Bangumi payload 缺少必填字符串字段",
            "validate_ab_subscription_payload",
            {"field": field, "expected_type": "string"},
        )
    return value.strip()


def _http_error_to_stage1_error(error: HTTPError, *, step: str = "create_ab_subscription") -> Stage1Error:
    if error.code in (401, 403):
        return Stage1Error(
            "ab_auth_failed",
            "Auto Bangumi 认证失败",
            step,
            {"status_code": error.code},
        )
    return Stage1Error(
        "ab_submit_failed",
        "Auto Bangumi HTTP 提交失败",
        step,
        {"status_code": error.code},
    )


def _network_error_to_stage1_error(error: URLError, *, step: str = "create_ab_subscription") -> Stage1Error:
    reason = getattr(error, "reason", None)
    if isinstance(reason, TimeoutError):
        return _timeout_error(step)
    return Stage1Error(
        "ab_connection_failed",
        "Auto Bangumi HTTP 连接失败",
        step,
        {"category": "connection"},
    )


def _network_exception_to_stage1_error(error: TimeoutError | ConnectionError) -> Stage1Error:
    if isinstance(error, TimeoutError):
        return _timeout_error()
    return Stage1Error(
        "ab_connection_failed",
        "Auto Bangumi HTTP 连接失败",
        "create_ab_subscription",
        {"category": "connection"},
    )


def _timeout_error(step: str = "create_ab_subscription") -> Stage1Error:
    return Stage1Error(
        "ab_timeout",
        "Auto Bangumi HTTP 请求超时",
        step,
        {"category": "timeout"},
    )
