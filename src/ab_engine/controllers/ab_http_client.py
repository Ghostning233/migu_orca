from __future__ import annotations

import json
import re
from collections.abc import Mapping
from copy import deepcopy
from typing import Any, Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from ab_engine.controllers.ab_client import AutoBangumiClient
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
        method: Literal["GET", "POST", "PATCH", "DELETE"],
        endpoint: str,
        headers: Mapping[str, str],
        payload: Any | None = None,
        *,
        timeout: float,
    ) -> Any:
        """Make one JSON request without following credentialed redirects.

        The decoded top-level shape is intentionally not constrained here: the
        endpoint that knows its contract validates it (issue #182)."""


class AutoBangumiLegacyTransport(Protocol):
    """Request boundary for the 3.1 password-login adapter."""

    def request_json(
        self,
        method: Literal["GET", "POST", "PATCH", "DELETE"],
        endpoint: str,
        headers: Mapping[str, str],
        payload: Any | None = None,
        *,
        timeout: float,
    ) -> Any:
        """Make one JSON API request without following redirects.

        The decoded top-level shape is intentionally not constrained here: the
        endpoint that knows its contract validates it (issue #182)."""

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
        method: Literal["GET", "POST", "PATCH", "DELETE"],
        endpoint: str,
        headers: Mapping[str, str],
        payload: Any | None = None,
        *,
        timeout: float,
    ) -> Any:
        data = None
        request_headers = dict(headers)
        if payload is not None:
            if method == "PATCH" or isinstance(payload, list):
                data = json.dumps(deepcopy(payload), ensure_ascii=False).encode("utf-8")
                request_headers.setdefault("Content-Type", "application/json")
            else:
                data = urlencode(dict(payload)).encode("utf-8")
        request = Request(endpoint, data=data, headers=request_headers, method=method)
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
        return _decode_json(response_body, step="probe_ab_connection")

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
        return _decode_object(response_body, step="create_ab_subscription")


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
        # Issue #86: everything that can fail *before* the write boundary is
        # checked here, so a bad connection / credential / version is a definite,
        # safely-retryable failure instead of an ambiguous external outcome.
        self._pre_write_check()
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
        if _looks_like_duplicate_subscription(response):
            # A distinguishable business rejection: an equal subscription already
            # exists upstream.  Only the category is derived here — the upstream
            # text is never returned, logged or persisted.
            raise Stage1Error(
                "ab_duplicate_subscription",
                "Auto Bangumi 中已存在相同订阅",
                "create_ab_subscription",
                upstream_diagnostics(response),
            )
        raise Stage1Error(
            "ab_submit_failed",
            "Auto Bangumi 提交失败",
            "create_ab_subscription",
            upstream_diagnostics(response),
        )

    def _pre_write_check(self) -> None:
        """Authenticate and verify the exact supported version before writing.

        Raises a *pre-write* connection/version error, so the submit classifier
        can report a definite, user-actionable category (fix the connection /
        credentials / Auto Bangumi version) rather than an unknown outcome.
        """
        try:
            self._authenticate()
            status = self._request_json(
                "GET",
                _api_endpoint(self._config.base_url, "/api/v1/status"),
                {"Accept": "application/json", "Cookie": self._session_cookie()},
            )
        except Stage1Error as exc:
            raise _as_pre_write_error(exc) from exc
        version = _status_version(status)
        if not version.startswith("3.1."):
            raise Stage1Error(
                "ab_unsupported_version",
                "当前 Auto Bangumi 版本暂不受支持",
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
            response = self._transport.request_json(
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
        if not isinstance(response, dict):
            raise Stage1Error(
                "invalid_ab_response",
                "Auto Bangumi 响应必须是 JSON 对象",
                "probe_ab_connection",
            )
        return response

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


def create_auto_bangumi_submit_client(
    config: AutoBangumiConfig,
    *,
    transport: AutoBangumiHttpTransport | AutoBangumiLegacyTransport | None = None,
) -> AutoBangumiClient:
    """Build the write adapter matching the explicit authentication mode.

    Password credentials are exclusively for the verified 3.1 login/Cookie
    flow; Token credentials retain their fail-closed compatibility adapter.
    Keeping this choice at the shared seam prevents single and batch submits
    from drifting into different payload or credential contracts.
    """

    if config.auth_mode == "password":
        if transport is None:
            return create_legacy_3_1_auto_bangumi_client(config)
        return create_legacy_3_1_auto_bangumi_client(config, transport=transport)
    if transport is None:
        return create_auto_bangumi_http_client(config)
    return create_auto_bangumi_http_client(config, transport=transport)


def _api_endpoint(base_url: str, path: str) -> str:
    """Append a fixed API path after re-checking the configured service origin."""
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise Stage1Error("config_error", "Auto Bangumi 配置无效", "probe_ab_connection")
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _status_version(status: Any) -> str:
    if not isinstance(status, Mapping):
        raise Stage1Error(
            "invalid_ab_response",
            "Auto Bangumi 状态响应必须是 JSON 对象",
            "probe_ab_connection",
        )
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


def _decode_json(response_body: bytes, *, step: str) -> Any:
    """Decode one bounded JSON body without assuming its top-level shape.

    The verified 3.1.18 list endpoints answer with a bare JSON array while
    every other endpoint answers with an object, so the *shape* contract is
    enforced by the endpoint that knows it (``_decode_object`` here and the
    management adapter for lists) instead of globally here (issue #182).
    """
    try:
        return json.loads(response_body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise Stage1Error("invalid_ab_response", "Auto Bangumi 响应不是合法 JSON", step) from exc


def _decode_object(response_body: bytes, *, step: str) -> dict[str, Any]:
    ab_response = _decode_json(response_body, step=step)
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


#: Conservative markers for "this subscription already exists" in the public
#: message fields Auto Bangumi can return.  Only a boolean ever escapes this
#: check: the upstream text is never returned, logged or persisted (issue #86).
_DUPLICATE_SUBSCRIPTION_MARKERS = (
    "已存在",
    "已经存在",
    "重复订阅",
    "duplicate",
    "already exists",
    "already subscribed",
)


#: Issue #101: the only upstream failure fields ever surfaced, bounded in length.
_UPSTREAM_DIAGNOSTIC_FIELDS = ("msg_zh", "msg_en", "msg", "message", "detail")
_DIAGNOSTIC_MAX_CHARS = 200
#: Anything that could carry a secret, a full feed URL, a magnet or a local path.
_DIAGNOSTIC_REDACTIONS = (
    re.compile(r"https?://\S+", re.IGNORECASE),
    re.compile(r"magnet:\S+", re.IGNORECASE),
    re.compile(r"(?:/(?:home|users|var|tmp|mnt|opt)/\S+)", re.IGNORECASE),
    re.compile(r"[A-Za-z]:\\\\\S+"),
    re.compile(r"\b(?:password|passwd|token|secret|cookie|authorization)\b\s*[:=]?\s*\S*", re.IGNORECASE),
    re.compile(r"\b[0-9a-fA-F]{32,}\b"),
)


def _safe_diagnostic_text(value: Any) -> str | None:
    """One bounded, redacted upstream message or ``None`` (never raw text)."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text:
        return None
    for pattern in _DIAGNOSTIC_REDACTIONS:
        text = pattern.sub("[已隐藏]", text)
    text = text.strip()
    if not text:
        return None
    return text[:_DIAGNOSTIC_MAX_CHARS]


def upstream_diagnostics(response: Any) -> dict[str, Any]:
    """Whitelisted, bounded diagnostics from one Auto Bangumi write response.

    Only a stable HTTP category and the bounded ``msg_zh``/``msg_en`` (or their
    documented aliases) ever leave the adapter; unknown fields, raw bodies,
    URLs, magnets and local paths are dropped. A response without any usable
    reason yields no reason at all, so the client can honestly say 未提供具体原因.
    """
    diagnostics: dict[str, Any] = {}
    if not isinstance(response, Mapping):
        return diagnostics
    status = response.get("status_code", response.get("http_status"))
    if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599:
        diagnostics["http_status"] = status
    elif isinstance(status, str) and status.isdigit() and 100 <= int(status) <= 599:
        diagnostics["http_status"] = int(status)
    for field in _UPSTREAM_DIAGNOSTIC_FIELDS:
        safe = _safe_diagnostic_text(response.get(field))
        if safe is not None:
            key = "message_zh" if field in ("msg_zh", "msg", "message", "detail") else "message_en"
            diagnostics.setdefault(key, safe)
    return diagnostics


def _looks_like_duplicate_subscription(response: Mapping[str, Any]) -> bool:
    for field in ("msg", "message", "detail", "error"):
        value = response.get(field)
        if not isinstance(value, str):
            continue
        folded = value.casefold()
        if any(marker in folded for marker in _DUPLICATE_SUBSCRIPTION_MARKERS):
            return True
    return False


#: Pre-write failures that prove nothing was written, so the submit classifier
#: may report a definite (safely retryable) category.  The same network error
#: *during* the write stays ambiguous and must go through recovery.
_PRE_WRITE_ERROR_TYPES = {
    "ab_connection_failed": "ab_connection_failed_pre_write",
    "ab_timeout": "ab_timeout_pre_write",
}


def _as_pre_write_error(error: Stage1Error) -> Stage1Error:
    """Relabel a failure raised before the write boundary, keeping it safe."""
    replacement = _PRE_WRITE_ERROR_TYPES.get(error.error_type)
    if replacement is None:
        return error
    return Stage1Error(replacement, error.message, error.failed_step, error.details)


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
