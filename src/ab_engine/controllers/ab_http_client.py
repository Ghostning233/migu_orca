from __future__ import annotations

import contextlib
import json
import re
import socket
import ssl
import time
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit

from ab_engine.controllers.ab_config import AutoBangumiConfig
from shared.errors import Stage1Error

if TYPE_CHECKING:
    # Type-only: this module owns the verified write contract that ``ab_client``
    # imports at runtime, so the client protocol must not be a runtime import
    # here (it would be a cycle).
    from ab_engine.controllers.ab_client import AutoBangumiClient


@dataclass(frozen=True, slots=True)
class AutoBangumiWriteResponse:
    """One Auto Bangumi write exchange exactly as the transport observed it.

    ``status_code`` is the exact HTTP status of the response, and ``payload`` is
    its body already decoded according to the endpoint contract: for an exact
    ``200`` that is the verified 3.1.18 write envelope — a top-level JSON object
    whose ``msg_en``/``msg_zh`` are strings (issue #216).  For any other status
    it is the best-effort decoded object, or ``{}`` when no usable body arrived,
    so a caller that can distinguish a documented business rejection (an equal
    subscription already exists) may do so without ever trusting that body as a
    success.

    Both facts travel together: the success criterion is *this* status plus this
    validated body, never a range of 2xx codes and never an upstream ``status``
    field (which the real 3.1.18 write endpoints do not send).
    """

    status_code: int
    payload: dict[str, Any]


class AutoBangumiHttpTransport(Protocol):
    """Transport boundary used by the API Token compatibility adapter."""

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

    def write_json(
        self,
        method: Literal["GET", "POST", "PATCH", "DELETE"],
        endpoint: str,
        headers: Mapping[str, str],
        payload: Any | None = None,
        *,
        timeout: float,
        step: str = "create_ab_subscription",
    ) -> AutoBangumiWriteResponse:
        """Perform one write and return its exact status plus decoded body."""


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

    def write_json(
        self,
        method: Literal["GET", "POST", "PATCH", "DELETE"],
        endpoint: str,
        headers: Mapping[str, str],
        payload: Any | None = None,
        *,
        timeout: float,
        step: str = "create_ab_subscription",
    ) -> AutoBangumiWriteResponse:
        """Perform one same-origin write without exposing session credentials."""


class UrlopenAutoBangumiHttpTransport:
    """Stdlib HTTP/1.1 transport for Auto Bangumi JSON requests.

    The class name is kept for the historical seam, but the exchange is
    performed here rather than through ``urllib.request``: ``urlopen(timeout=)``
    bounds one socket operation, so a peer that keeps trickling headers or a
    body can hold the read open well past the budget, and closing a response
    from another thread does not interrupt the blocked read (issue #183
    review). One absolute deadline now covers connect, request send, response
    headers and response body, and the connection is always closed on exit.
    Redirects are never followed: a 3xx is an error, so a session Cookie can
    never leave the configured origin.
    """

    def request_json(
        self,
        method: Literal["GET", "POST", "PATCH", "DELETE"],
        endpoint: str,
        headers: Mapping[str, str],
        payload: Any | None = None,
        *,
        timeout: float,
    ) -> Any:
        request_headers = dict(headers)
        body = _encode_request_payload(method, request_headers, payload)
        _status, _headers, raw = _exchange(
            method, endpoint, request_headers, body, timeout=timeout, step="probe_ab_connection"
        )
        _raise_for_status(_status, step="probe_ab_connection")
        return _decode_json(raw, step="probe_ab_connection")

    def post_json_same_origin(
        self,
        endpoint: str,
        headers: Mapping[str, str],
        payload: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        """The historical POST seam, kept for the merged #217 collect contract.

        It predates :meth:`write_json` and exists only because the already-merged
        ``tests/api_contract/test_tracking_collect_contract_source_derived.py``
        pins this name as its single transport seam (that file belongs to #217
        and is not edited here).  It applies the *same* verified criterion — exact
        ``200`` plus the write envelope — and returns the decoded object, so it
        can never accept a 2xx range or an upstream ``status`` field as success.
        Production writes go through ``write_json`` (issue #216 AC2).
        """
        response = self.write_json("POST", endpoint, headers, payload, timeout=timeout)
        if response.status_code != 200:
            # Its historical contract is a status-only classification: the #101
            # bounded message diagnostics belong to the subscription write seam
            # (``write_json`` + ``create_subscription``), and the merged #217
            # collect contract keeps every upstream message text inside the
            # adapter, so this wrapper must not surface it either.
            raise _status_only_failure(response.status_code, step="create_ab_subscription")
        return response.payload

    def write_json(
        self,
        method: Literal["GET", "POST", "PATCH", "DELETE"],
        endpoint: str,
        headers: Mapping[str, str],
        payload: Any | None = None,
        *,
        timeout: float,
        step: str = "create_ab_subscription",
    ) -> AutoBangumiWriteResponse:
        """Perform one same-origin Auto Bangumi write (issue #216).

        The exchange returns the exact HTTP status together with the body that
        the write contract validates, and a non-2xx status does **not** raise:
        the endpoint that knows its contract classifies it (an equal
        subscription already exists, authentication failed, a business
        rejection).  No redirect is ever followed, so a session Cookie can never
        leave the configured origin.
        """
        request_headers = dict(headers)
        body = _encode_write_payload(request_headers, payload)
        status, _headers, raw = _exchange(
            method,
            endpoint,
            request_headers,
            body,
            timeout=timeout,
            step=step,
            inspect_error_body=True,
        )
        return _write_response(status, raw, step=step)


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

    def create_collection(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Reject a one-time collection until a Token write contract is verified.

        Issue #217 keeps the collection capability on the same verified basis as
        every other write: 3.1.18 password only.  The public call shape is still
        validated first, so an invalid payload stays a validation failure and the
        Bearer credential is never sent.
        """

        _validate_collection_payload(payload)
        if self._config.auth_mode != "api_token" or not self._config.token:
            raise Stage1Error(
                "ab_submit_unsupported",
                "当前 Auto Bangumi 认证模式暂不支持“下载现有资源”",
                "collect_existing_resources",
            )
        raise Stage1Error(
            "ab_submit_unsupported",
            "当前 Auto Bangumi 版本暂不支持“下载现有资源”",
            "collect_existing_resources",
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
                api_endpoint(self._config.base_url, "/api/v1/status"),
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


#: The verified one-time collection endpoint (issue #217): ``POST
#: /api/v1/rss/collect`` takes a *bare* ``Bangumi`` body and never creates an RSS
#: subscription, unlike ``/api/v1/rss/subscribe``.
_COLLECT_PATH = "/api/v1/rss/collect"

#: The only Auto Bangumi version whose collection contract is verified.  Unlike
#: the ``3.1.*`` subscribe family, collect is gated on this exact version: its
#: upstream body shape, success envelope and dual-semantics 406 were established
#: for 3.1.18 only (issue #217).
_COLLECT_VERIFIED_VERSION = "3.1.18"


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
            api_endpoint(self._config.base_url, "/api/v1/status"),
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
        response = self._write_json(
            "POST",
            api_endpoint(self._config.base_url, "/api/v1/rss/subscribe"),
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Cookie": self._session_cookie(),
            },
            payload,
        )
        if response.status_code == 200:
            # The transport proved the exact 200 and the verified 3.1.18 write
            # envelope ``{"msg_en": str, "msg_zh": str}``; there is no ``status``
            # field to look for and no id to require (issue #216).
            return deepcopy(response.payload)
        # Only a 4xx that is *not* an authentication failure can be the
        # distinguishable business rejection: a 401/403 body that happens to
        # mention an existing subscription is still a rejected credential, and a
        # 5xx (or any other status) may already have been processed upstream, so
        # neither may be published as the definite "an equal subscription
        # already exists".  Only the category is derived here — the upstream text
        # is never returned, logged or persisted (issue #86).
        if (
            response.status_code not in (401, 403)
            and 400 <= response.status_code < 500
            and _looks_like_duplicate_subscription(response.payload)
        ):
            raise Stage1Error(
                "ab_duplicate_subscription",
                "Auto Bangumi 中已存在相同订阅",
                "create_ab_subscription",
                write_diagnostics(response),
            )
        raise write_failure(response, step="create_ab_subscription")

    def create_collection(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run one verified 3.1.18 one-time collection (issue #217).

        The body is the bare ``Bangumi`` model the real instance declares, and
        the result is judged by the very same channel as every other 3.1.18
        write: an exact HTTP 200 that carries the verified ``{msg_en, msg_zh}``
        envelope (issue #216).  Every other status — including the two
        indistinguishable 406 semantics "filtered to nothing" and "downloader
        already added / rejected" — becomes the stable definite failure, so a
        rejection is never guessed to be a success (ADR-0001).

        This is a *one-time* request: it creates no controlled external
        subscription, sends no ``id`` (an upstream rule id would route the body
        through Auto Bangumi's ``update`` path) and never reads anything back.
        """

        _validate_collection_payload(payload)
        # The write boundary is entered only after the credential and the exact
        # verified version are proven, so a bad connection/version is a definite,
        # safely-retryable failure instead of an ambiguous external outcome.
        self._pre_write_check(
            required_version=_COLLECT_VERIFIED_VERSION,
            step="collect_existing_resources",
        )
        response = self._write_json(
            "POST",
            api_endpoint(self._config.base_url, _COLLECT_PATH),
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Cookie": self._session_cookie(),
            },
            payload,
        )
        if response.status_code == 200:
            # The transport proved both facts: the exact 200 and the verified
            # 3.1.18 write envelope.  There is no subscription id to report.
            return deepcopy(response.payload)
        raise write_failure(response, step="collect_existing_resources")

    def _pre_write_check(
        self,
        *,
        required_version: str | None = None,
        step: str = "create_ab_subscription",
    ) -> None:
        """Authenticate and verify the supported version before writing.

        Raises a *pre-write* connection/version error, so the submit classifier
        can report a definite, user-actionable category (fix the connection /
        credentials / Auto Bangumi version) rather than an unknown outcome.
        ``required_version`` demands that exact version (one-time collection);
        without it the verified ``3.1.*`` family is accepted (subscribe).
        """
        try:
            self._authenticate()
            status = self._request_json(
                "GET",
                api_endpoint(self._config.base_url, "/api/v1/status"),
                {"Accept": "application/json", "Cookie": self._session_cookie()},
            )
        except Stage1Error as exc:
            raise _as_pre_write_error(exc) from exc
        version = _status_version(status)
        if required_version is not None and version != required_version:
            raise Stage1Error(
                "ab_unsupported_version",
                "当前 Auto Bangumi 版本暂不受支持",
                step,
            )
        if required_version is None and not version.startswith("3.1."):
            raise Stage1Error(
                "ab_unsupported_version",
                "当前 Auto Bangumi 版本暂不受支持",
                step,
            )


    def _authenticate(self) -> None:
        login = self._request_json(
            "POST",
            api_endpoint(self._config.base_url, "/api/v1/auth/login"),
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

    def _write_json(
        self,
        method: Literal["GET", "POST", "PATCH", "DELETE"],
        endpoint: str,
        headers: Mapping[str, str],
        payload: Any | None = None,
    ) -> AutoBangumiWriteResponse:
        try:
            return self._transport.write_json(
                method, endpoint, headers, deepcopy(payload), timeout=self._timeout
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


#: One blocking receive may never wait longer than this slice: a peer that keeps
#: trickling bytes cannot hold a read open past the absolute deadline, because
#: the loop re-checks the deadline between slices.
_READ_SLICE_SECONDS = 0.25
_READ_CHUNK_BYTES = 65536
_MAX_RESPONSE_HEADER_BYTES = 65536
_MAX_RESPONSE_BODY_BYTES = 8 * 1024 * 1024
_DEFAULT_PORTS = {"http": 80, "https": 443}

#: The complete verified 3.1.18 write envelope (issue #216).  There is no
#: ``status`` field: the real ``u_response`` helper answers every write with
#: exactly these two message strings, and the HTTP status carries the result.
#: Public because the submit-side normalizer must recognize the same envelope
#: instead of re-declaring it (``ab_client._subscription_id``).
WRITE_ENVELOPE_FIELDS = ("msg_en", "msg_zh")


def is_verified_write_envelope(payload: Any) -> bool:
    """True only for the verified 3.1.18 write envelope (two string messages)."""
    return isinstance(payload, Mapping) and all(
        isinstance(payload.get(field), str) for field in WRITE_ENVELOPE_FIELDS
    )


#: A rejected write still returns its bounded body when it arrives quickly, so
#: callers can tell one documented business rejection from another.  The wait is
#: deliberately short: the status already decided the exchange, and the body is
#: only extra detail (issue #216).
_ERROR_BODY_BUDGET_SECONDS = 1.0


class _Deadline:
    """One absolute wall-clock deadline shared by every phase of a request."""

    __slots__ = ("_end", "_monotonic")

    def __init__(self, budget: float, monotonic: Callable[[], float]) -> None:
        self._monotonic = monotonic
        self._end = monotonic() + max(float(budget), 0.0)

    def remaining(self) -> float:
        return self._end - self._monotonic()

    def expired(self) -> bool:
        return self.remaining() <= 0

    def slice(self) -> float:
        """The timeout for one blocking operation: never more than what is left."""
        return min(self.remaining(), _READ_SLICE_SECONDS)


def _exchange(
    method: str,
    endpoint: str,
    headers: Mapping[str, str],
    body: bytes | None,
    *,
    timeout: float,
    step: str,
    inspect_error_body: bool = False,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[int, dict[str, str], bytes]:
    """Perform exactly one HTTP/1.1 exchange under a single absolute deadline.

    Connect, request send, response headers and response body each use only the
    remaining time, and the connection is always closed before returning. No
    redirect is ever followed.

    On a read, a non-2xx status is classified from the header block before its
    body, so a stalled rejection body can never turn a proven
    authentication/HTTP failure into an unproven timeout (issue review).  A write
    exchange sets ``inspect_error_body`` because a documented business rejection —
    an equal subscription already exists — is only visible in that body (issue
    #216); only an exact 200 makes that body the decision, so every other status
    reads it under a short sub-budget and drops it if it never arrives.
    """
    parsed = urlsplit(endpoint)
    scheme = parsed.scheme.lower()
    if scheme not in _DEFAULT_PORTS or not parsed.hostname:
        raise Stage1Error("config_error", "Auto Bangumi 配置无效", step)
    deadline = _Deadline(timeout, monotonic)
    if deadline.expired():
        raise _timeout_error(step)
    port = parsed.port or _DEFAULT_PORTS[scheme]
    connection = _open_connection(scheme, parsed.hostname, port, deadline, step)
    try:
        target = parsed.path or "/"
        if parsed.query:
            target = f"{target}?{parsed.query}"
        request_bytes = _request_bytes(method, target, parsed, headers, body)
        _send_bounded(connection, request_bytes, deadline, step)
        status, response_headers, buffered = _read_headers(connection, deadline, step)
        rejected = not 200 <= status < 300
        if rejected and not inspect_error_body:
            _raise_for_status(status, step=step)
        # A write's body is the decision for an exact 200 and mere diagnostics for
        # every other status: only then does it get a short sub-budget and may it
        # be dropped, so a slow/oversized rejection body can never replace the
        # proven status with an unproven timeout (issue #216).  Reads keep the
        # previous behaviour exactly: a non-2xx is classified before its body and
        # an unreadable 2xx body still fails loudly.
        diagnostic_only = inspect_error_body and status != 200
        body_deadline = deadline if not diagnostic_only else _error_body_deadline(deadline, monotonic)
        try:
            payload = _read_body(
                connection, body_deadline, response_headers, status=status, method=method,
                buffered=buffered, step=step,
            )
        except Stage1Error:
            if not diagnostic_only:
                raise
            payload = b""
    finally:
        with contextlib.suppress(OSError):
            connection.close()
    return status, response_headers, payload


def _error_body_deadline(deadline: _Deadline, monotonic: Callable[[], float]) -> _Deadline:
    """A short sub-budget for one rejected write's optional diagnostic body."""
    return _Deadline(min(deadline.remaining(), _ERROR_BODY_BUDGET_SECONDS), monotonic)


def _encode_write_payload(headers: dict[str, str], payload: Any | None) -> bytes | None:
    """Encode one write body as JSON, the only verified 3.1.18 write encoding.

    ``headers`` is the caller's private copy, matching the read seam: a write
    with a body declares its own ``Content-Type``.
    """
    if payload is None:
        return None
    headers.setdefault("Content-Type", "application/json")
    return json.dumps(deepcopy(payload), ensure_ascii=False).encode("utf-8")


def _write_response(status: int, raw: bytes, *, step: str) -> AutoBangumiWriteResponse:
    """Validate one write exchange into its exact status plus decoded body.

    An exact ``200`` must carry the verified 3.1.18 write envelope; 201/204/3xx
    and every other status keep their body as bounded diagnostics only, so no
    caller can read success out of them (issue #216).
    """
    if status == 200:
        return AutoBangumiWriteResponse(200, _write_envelope(raw, step=step))
    return AutoBangumiWriteResponse(status, _decode_error_object(raw))


def _write_envelope(raw: bytes, *, step: str) -> dict[str, Any]:
    """The verified 3.1.18 write envelope: an object with two string messages."""
    payload = _decode_object(raw, step=step)
    if not is_verified_write_envelope(payload):
        raise Stage1Error(
            "invalid_ab_response",
            "Auto Bangumi 写响应缺少成功字段",
            step,
            {"fields": list(WRITE_ENVELOPE_FIELDS)},
        )
    return payload


def _decode_error_object(raw: bytes) -> dict[str, Any]:
    """Best-effort bounded JSON object of a rejected write; never a verdict."""
    if not raw:
        return {}
    try:
        value = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _status_only_failure(status_code: int, *, step: str) -> Stage1Error:
    """The historical status-only write failure, without upstream message text."""
    if status_code in (401, 403):
        return Stage1Error(
            "ab_auth_failed", "Auto Bangumi 认证失败", step,
            {"status_code": status_code, "http_status": status_code},
        )
    return Stage1Error(
        "ab_submit_failed", "Auto Bangumi HTTP 提交失败", step,
        {"status_code": status_code, "http_status": status_code},
    )


def write_failure(response: AutoBangumiWriteResponse, *, step: str) -> Stage1Error:
    """The stable failure for one write that was not an exact verified 200.

    ``401``/``403`` prove the credential was rejected; every other status is a
    failed write.  Only bounded, already-sanitized upstream diagnostics travel
    with it (issue #101), never the raw body.
    """
    if response.status_code in (401, 403):
        return Stage1Error(
            "ab_auth_failed",
            "Auto Bangumi 认证失败",
            step,
            # Both status keys are deliberate: engine classifiers read
            # ``status_code`` and the published diagnostics DTO reads
            # ``http_status`` (issue #101/#216).
            {"status_code": response.status_code, "http_status": response.status_code},
        )
    return Stage1Error(
        "ab_submit_failed",
        "Auto Bangumi HTTP 提交失败",
        step,
        write_diagnostics(response),
    )


def write_diagnostics(response: AutoBangumiWriteResponse) -> dict[str, Any]:
    """Bounded diagnostics of one write response, including its exact status.

    ``status_code`` is the key the engine classifiers read (submit outcome and
    the management coordinator) and ``http_status`` the one the public
    diagnostics DTO publishes (issue #101); both carry the same exact status, and
    ``msg_zh``/``msg_en`` are the already sanitized, bounded upstream reasons.
    """
    diagnostics = upstream_diagnostics({**response.payload, "status_code": response.status_code})
    diagnostics["status_code"] = response.status_code
    return diagnostics


def _open_connection(scheme: str, host: str, port: int, deadline: _Deadline, step: str) -> Any:
    """Connect (and, for https, handshake) inside the deadline.

    The socket is created here and owned by the caller, so a failed connect or
    a failed TLS handshake is always cleaned up by this function (issue review):
    nothing is left half-open when a later phase never starts.
    """
    if deadline.expired():
        raise _timeout_error(step)
    sock: Any = None
    try:
        sock = _connect_bounded(
            _resolved_addresses(host, port), timeout=max(deadline.remaining(), 0.001)
        )
        if deadline.expired():
            raise _timeout_error(step)
        if scheme == "https":
            # TCP and TLS share one budget: the handshake gets what is left, not
            # the original timeout (issue review).
            sock.settimeout(max(deadline.remaining(), 0.001))
            context = ssl.create_default_context()
            sock = context.wrap_socket(sock, server_hostname=host)
            if deadline.expired():
                raise _timeout_error(step)
        sock.settimeout(max(deadline.remaining(), 0.001))
    except TimeoutError as exc:
        _close_quietly(sock)
        raise _timeout_error(step) from exc
    except (ssl.SSLError, OSError) as exc:
        _close_quietly(sock)
        raise _network_error_to_stage1_error(exc, step=step) from exc
    except BaseException:
        _close_quietly(sock)
        raise
    return sock


def _connect_bounded(addresses: list[Any], *, timeout: float) -> Any:
    """Connect to one of the already-resolved addresses (never re-resolving)."""
    last_error: OSError | None = None
    for family, socktype, proto, _canonical, sockaddr in addresses:
        candidate: Any = None
        try:
            candidate = socket.socket(family, socktype, proto)
            candidate.settimeout(timeout)
            candidate.connect(sockaddr)
            return candidate
        except OSError as exc:
            last_error = exc
            _close_quietly(candidate)
    raise last_error or OSError("Auto Bangumi 地址不可达")


def _close_quietly(sock: Any) -> None:
    if sock is None:
        return
    with contextlib.suppress(OSError):
        sock.close()


def _resolved_addresses(host: str, port: int) -> list[Any]:
    """Addresses for one connect, skipping DNS whenever the host is literal.

    ``socket.getaddrinfo`` has no timeout parameter in the standard library, so
    a *hostname* resolves only as fast as the operating system resolver allows.
    Literal IPv4/IPv6 addresses and ``localhost`` never reach it, which is the
    common Auto Bangumi deployment (a LAN address or the local machine).
    """
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            socket.inet_pton(family, host)
        except OSError:
            continue
        if family == socket.AF_INET:
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (host, port))]
        return [(socket.AF_INET6, socket.SOCK_STREAM, 0, "", (host, port, 0, 0))]
    if host.rstrip(".").lower() == "localhost":
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", port))]
    return socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)


def _request_bytes(
    method: str,
    target: str,
    parsed: Any,
    headers: Mapping[str, str],
    body: bytes | None,
) -> bytes:
    """Build one HTTP/1.1 request; the caller's headers stay authoritative."""
    host_header = parsed.netloc.decode("ascii") if isinstance(parsed.netloc, bytes) else parsed.netloc
    lowered = {name.lower() for name in headers}
    lines = [f"{method} {target} HTTP/1.1", f"Host: {host_header}"]
    if body is not None and "content-length" not in lowered:
        lines.append(f"Content-Length: {len(body)}")
    if "connection" not in lowered:
        # One exchange per connection: the response may then be EOF delimited and
        # the socket is reclaimed by the caller no matter how the read ends.
        lines.append("Connection: close")
    lines.extend(f"{name}: {value}" for name, value in headers.items())
    raw = ("\r\n".join(lines) + "\r\n\r\n").encode("iso-8859-1")
    return raw + body if body else raw


def _send_bounded(connection: Any, data: bytes, deadline: _Deadline, step: str) -> None:
    """Send the request, re-checking the remaining time before every chunk."""
    view = memoryview(data)
    sent = 0
    while sent < len(view):
        if deadline.expired():
            raise _timeout_error(step)
        connection.settimeout(max(deadline.remaining(), 0.001))
        try:
            sent += connection.send(view[sent : sent + _READ_CHUNK_BYTES])
        except TimeoutError as exc:
            raise _timeout_error(step) from exc
        except OSError as exc:
            raise _network_error_to_stage1_error(exc, step=step) from exc


def _recv_bounded(connection: Any, deadline: _Deadline, step: str) -> bytes:
    """One receive that can never block past the deadline; b"" means EOF."""
    while True:
        if deadline.expired():
            raise _timeout_error(step)
        connection.settimeout(max(deadline.slice(), 0.001))
        try:
            return connection.recv(_READ_CHUNK_BYTES)
        except TimeoutError:
            # A quiet moment is not a failure: only the absolute deadline ends it.
            continue
        except OSError as exc:
            raise _network_error_to_stage1_error(exc, step=step) from exc


def _read_headers(
    connection: Any, deadline: _Deadline, step: str
) -> tuple[int, dict[str, str], bytes]:
    """Read and parse the status line and headers under the deadline."""
    buffer = b""
    while b"\r\n\r\n" not in buffer:
        chunk = _recv_bounded(connection, deadline, step)
        if not chunk:
            raise Stage1Error(
                "invalid_ab_response", "Auto Bangumi 响应头不完整", step
            )
        buffer += chunk
        if len(buffer) > _MAX_RESPONSE_HEADER_BYTES:
            raise Stage1Error("invalid_ab_response", "Auto Bangumi 响应头过大", step)
    head, buffered = buffer.split(b"\r\n\r\n", 1)
    lines = head.decode("iso-8859-1").split("\r\n")
    parts = lines[0].split(" ", 2)
    if len(parts) < 2 or not parts[1].isdigit():
        raise Stage1Error("invalid_ab_response", "Auto Bangumi 状态行无效", step)
    status = int(parts[1])
    response_headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line:
            continue
        name, separator, value = line.partition(":")
        if not separator:
            raise Stage1Error("invalid_ab_response", "Auto Bangumi 响应头无效", step)
        response_headers[name.strip().lower()] = value.strip()
    return status, response_headers, buffered


def _read_body(
    connection: Any,
    deadline: _Deadline,
    headers: Mapping[str, str],
    *,
    status: int,
    method: str,
    buffered: bytes,
    step: str,
) -> bytes:
    """Read the framed body (Content-Length / chunked / EOF) under the deadline."""
    if method.upper() == "HEAD" or status in (204, 304) or 100 <= status < 200:
        return b""
    if "chunked" in headers.get("transfer-encoding", "").lower():
        return _read_chunked(connection, deadline, buffered, step)
    declared = headers.get("content-length")
    if declared is not None:
        try:
            length = int(declared)
        except ValueError as exc:
            raise Stage1Error("invalid_ab_response", "Auto Bangumi 内容长度无效", step) from exc
        if length < 0 or length > _MAX_RESPONSE_BODY_BYTES:
            raise Stage1Error("invalid_ab_response", "Auto Bangumi 响应过大", step)
        return _read_exact(connection, deadline, buffered, length, step)
    return _read_until_eof(connection, deadline, buffered, step)


def _read_exact(
    connection: Any, deadline: _Deadline, buffered: bytes, length: int, step: str
) -> bytes:
    body = bytearray(buffered[:length])
    while len(body) < length:
        chunk = _recv_bounded(connection, deadline, step)
        if not chunk:
            raise Stage1Error("invalid_ab_response", "Auto Bangumi 响应正文不完整", step)
        body.extend(chunk)
    return bytes(body[:length])


def _read_chunked(
    connection: Any, deadline: _Deadline, buffered: bytes, step: str
) -> bytes:
    """Decode one ``Transfer-Encoding: chunked`` body under the deadline."""
    body = bytearray()
    pending = buffered
    while True:
        while b"\r\n" not in pending:
            chunk = _recv_bounded(connection, deadline, step)
            if not chunk:
                raise Stage1Error("invalid_ab_response", "Auto Bangumi 分块响应不完整", step)
            pending += chunk
        line, pending = pending.split(b"\r\n", 1)
        size_text = line.split(b";", 1)[0].strip()
        try:
            size = int(size_text, 16)
        except ValueError as exc:
            raise Stage1Error("invalid_ab_response", "Auto Bangumi 分块长度无效", step) from exc
        if size == 0:
            return bytes(body)
        if len(body) + size > _MAX_RESPONSE_BODY_BYTES:
            raise Stage1Error("invalid_ab_response", "Auto Bangumi 响应过大", step)
        while len(pending) < size + 2:
            chunk = _recv_bounded(connection, deadline, step)
            if not chunk:
                raise Stage1Error("invalid_ab_response", "Auto Bangumi 分块响应不完整", step)
            pending += chunk
        body.extend(pending[:size])
        pending = pending[size + 2 :]


def _read_until_eof(
    connection: Any, deadline: _Deadline, buffered: bytes, step: str
) -> bytes:
    body = bytearray(buffered)
    if len(body) > _MAX_RESPONSE_BODY_BYTES:
        raise Stage1Error("invalid_ab_response", "Auto Bangumi 响应过大", step)
    while True:
        chunk = _recv_bounded(connection, deadline, step)
        if not chunk:
            return bytes(body)
        body.extend(chunk)
        if len(body) > _MAX_RESPONSE_BODY_BYTES:
            raise Stage1Error("invalid_ab_response", "Auto Bangumi 响应过大", step)


def _encode_request_payload(
    method: str, headers: dict[str, str], payload: Any | None
) -> bytes | None:
    """Encode one request body exactly as the Auto Bangumi 3.1 contract needs.

    ``headers`` is the caller's private copy: a JSON body declares its own
    Content-Type, exactly like the previous urllib transport did.
    """
    if payload is None:
        return None
    if method == "PATCH" or isinstance(payload, list):
        headers.setdefault("Content-Type", "application/json")
        return json.dumps(deepcopy(payload), ensure_ascii=False).encode("utf-8")
    return urlencode(dict(payload)).encode("utf-8")


def _raise_for_status(status: int, *, step: str) -> None:
    """Map a non-2xx status exactly like the previous HTTPError classification."""
    if 200 <= status < 300:
        return
    if status in (401, 403):
        raise Stage1Error(
            "ab_auth_failed", "Auto Bangumi 认证失败", step, {"status_code": status}
        )
    raise Stage1Error(
        "ab_submit_failed", "Auto Bangumi HTTP 提交失败", step, {"status_code": status}
    )


def api_endpoint(base_url: str, path: str) -> str:
    """Append a fixed API path after re-checking the configured service origin.

    Public seam: the legacy management adapter shares it (issue #175), so the
    origin check cannot diverge between the transport and its callers.
    """
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


def _validate_collection_payload(payload: dict[str, Any]) -> None:
    """Validate one bare ``Bangumi`` collection body before any external write.

    Issue #217 refuses three shapes instead of repairing them:

    - a non-object body (the endpoint takes the model, not a scalar/list);
    - the ``{data, rss}`` subscribe wrapper (collect must never create an RSS
      subscription);
    - a body carrying ``id``: upstream routes an id-ed ``Bangumi`` through its
      ``update`` path, so a one-time collection could silently modify an existing
      rule — it is refused rather than dropped.

    ``rss_link`` is required because an empty one makes Auto Bangumi fall back to
    its own site search, which this product does not support.
    """

    if not isinstance(payload, Mapping):
        raise Stage1Error(
            "invalid_ab_payload",
            "Auto Bangumi 3.1 一次性收集 payload 必须是对象",
            "collect_existing_resources",
        )
    if "data" in payload or "rss" in payload:
        raise Stage1Error(
            "invalid_ab_payload",
            "Auto Bangumi 3.1 一次性收集 payload 不能是订阅包装体",
            "collect_existing_resources",
        )
    if "id" in payload:
        raise Stage1Error(
            "invalid_ab_payload",
            "Auto Bangumi 3.1 一次性收集 payload 不得包含 id",
            "collect_existing_resources",
        )
    rss_link = payload.get("rss_link")
    if not isinstance(rss_link, str) or not rss_link.strip():
        raise Stage1Error(
            "invalid_ab_payload",
            "Auto Bangumi 3.1 一次性收集 payload 缺少 rss_link",
            "collect_existing_resources",
            {"field": "rss_link"},
        )


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
#: message fields Auto Bangumi can return.  The verified 3.1.18 write envelope
#: uses ``msg_zh``/``msg_en`` (issue #216); the shorter historical aliases are
#: kept because already-adapted shapes may still carry them.  Only a boolean ever
#: escapes this check: the upstream text is never returned, logged or persisted
#: (issue #86).
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
    for field in ("msg_zh", "msg_en", "msg", "message", "detail", "error"):
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


def _network_error_to_stage1_error(error: BaseException, *, step: str = "create_ab_subscription") -> Stage1Error:
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
