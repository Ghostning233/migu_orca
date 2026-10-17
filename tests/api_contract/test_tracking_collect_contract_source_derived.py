from __future__ import annotations

"""Issue #217: the ``POST /api/v1/rss/collect`` judgement, source-derived.

**These fixtures are source-derived, not real-machine recordings.**  Every
status line and envelope is reconstructed from the evidence fixed for #216/#217:

* the real Auto Bangumi 3.1.18 instance's ``GET /api/v1/status`` (``3.1.18``);
* that instance's ``openapi.json``, which declares ``POST /api/v1/rss/collect``
  ``requestBody`` as ``$ref #/components/schemas/Bangumi`` — a *bare* model —
  while ``/rss/subscribe`` declares its own ``Body_subscribe_...`` wrapper;
* upstream tag ``3.1.18``: ``backend/src/module/api/rss.py:185-191`` (the route
  and its ``Bangumi`` argument), ``backend/src/module/manager/collector.py:11-46``
  (the write, ``filter.replace(",", "|")`` and the two 406 semantics) and
  ``backend/src/module/api/response.py:7-14`` (``u_response`` folds
  ``ResponseModel.status`` into the HTTP status code and returns only
  ``msg_en``/``msg_zh`` — the body never carries ``status``).

Every request goes to a **localhost-only raw-byte stand-in** that answers with
those exact bytes, and the whole chain is production code: the real
``UrlopenAutoBangumiHttpTransport`` (login, status, no redirects, bounded
deadline), the real 3.1.18 adapter (payload validation, exact-version gate,
exact-200 write envelope of issue #216), the real ``collect_ab_resources``
normalizer and the real "download existing resources" classifier.  Nothing here
talks to a real Auto Bangumi, and the only credential is the obviously fake
``ab-session`` cookie the stand-in never validates.

Issue #217's remaining work — replacing the default ``compose_tracking_collect_one``
seam and the route-level contract tests — lives in
``tests/api_contract/test_tracking_submit_api.py`` and
``test_tracking_batch_submit_api.py``.
"""

import contextlib
import json
import socket
import threading
from dataclasses import dataclass, field
from typing import Any

import pytest

from ab_engine.controllers.ab_client import collect_ab_resources
from ab_engine.controllers.ab_config import AutoBangumiConfig
from ab_engine.controllers.ab_http_client import (
    LegacyAutoBangumi31Client,
    UrlopenAutoBangumiHttpTransport,
)
from ab_engine.controllers.subscription_payload import build_legacy_31_collection_payload
from request_engine.controllers.request_controller import (
    accept_request,
    build_pending_request,
)
from shared.models import (
    EntryRequest,
    FilterRule,
    MatchedBangumi,
    SubtitleGroupSelection,
)
from tracking_engine.controllers.submit import classify_existing_resource_result
from tracking_engine.models.tracking import (
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_ADDED_TO_DOWNLOAD,
    TRACKING_STATUS_RECOVERY_REQUIRED,
    TRACKING_STATUS_SUBMIT_FAILED,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
)

#: The verified 3.1.18 paths; the inventory documents collect as an *external*
#: AB endpoint that never enters this repository's Flask url_map or OpenAPI.
_COLLECT_PATH = "/api/v1/rss/collect"
_STATUS_PATH = "/api/v1/status"
_LOGIN_PATH = "/api/v1/auth/login"

#: Provenance of every fixture below.  Each entry names the artifact it came
#: from so a reviewer can re-derive the bytes instead of trusting this file.
_SOURCE_EVIDENCE = (
    "real 3.1.18 instance: GET /api/v1/status -> {\"version\": \"3.1.18\"}",
    "real 3.1.18 instance openapi.json: POST /api/v1/rss/collect requestBody $ref #/components/schemas/Bangumi",
    "upstream tag 3.1.18: backend/src/module/api/rss.py:185-191 (route takes a bare Bangumi)",
    "upstream tag 3.1.18: backend/src/module/manager/collector.py:11-46 (write, comma replace, 406)",
    "upstream tag 3.1.18: backend/src/module/api/response.py:7-14 (u_response drops status)",
)

#: A successful collection: HTTP 200 and a top-level object with only the two
#: message fields.  ``status`` is deliberately absent (issue #216).
_SUCCESS_ENVELOPE: dict[str, Any] = {
    "msg_en": "Collections of 番剧 Season 1 completed.",
    "msg_zh": "收集 番剧 第 1 季完成。",
}

#: The upstream 406 copy is *one* message for both semantics ("filtered to
#: nothing" and "downloader rejected/already added"); the two cases below differ
#: only in the title they were produced for, because upstream cannot tell them
#: apart (``collector.py:37-46``).  Issue #217 therefore classifies every 406 as
#: a definite failure and never guesses success.
_NOT_FOUND_ENVELOPE: dict[str, Any] = {
    "msg_en": "Collection of 番剧 Season 1 failed.",
    "msg_zh": "收集 番剧 第 1 季失败, 种子已经添加。",
}
_ALREADY_ADDED_ENVELOPE: dict[str, Any] = {
    "msg_en": "Collection of 番剧 第二季 Season 2 failed.",
    "msg_zh": "收集 番剧 第二季 第 2 季失败, 种子已经添加。",
}


def _raw(status: str, body: bytes, *, declared_length: int | None = None) -> bytes:
    """One raw HTTP/1.1 response with an explicit Content-Length."""

    length = len(body) if declared_length is None else declared_length
    return (
        f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\n"
        f"Content-Length: {length}\r\n\r\n"
    ).encode("iso-8859-1") + body


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


#: The verified login/status surface, answered exactly like the real instance.
_LOGIN_RESPONSE = _raw("200 OK", _json_bytes({"access_token": "ab-session"}))


def _status_response(version: str) -> bytes:
    return _raw("200 OK", _json_bytes({"version": version}))


@dataclass(frozen=True)
class _CollectCase:
    """One source-derived collect exchange and its required judgement."""

    name: str
    expected_error_type: str | None
    expected_http_status: int | None
    #: The raw response of the collection POST (``None`` with ``stall`` for a
    #: peer that accepts and never answers).
    collect: bytes | None = None
    #: The exact version ``GET /api/v1/status`` reports.
    version: str = "3.1.18"
    #: Overrides the production-built collection body (validation fixtures).
    payload: dict[str, Any] | None = None
    stall: bool = False
    #: No listener at all, so the very first connect is refused.
    refused: bool = False
    timeout: float = 2.0
    #: False when the adapter must refuse *before* the collection request.
    expect_collect_attempt: bool = True
    #: Bounded upstream text that may appear in the sanitized diagnostics.
    expected_message: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


_SUCCESS_CASE = _CollectCase(
    "collect_200_success_envelope",
    None,
    None,
    collect=_raw("200 OK", _json_bytes(_SUCCESS_ENVELOPE)),
)
_FILTER_EMPTY_CASE = _CollectCase(
    "collect_406_filtered_to_nothing",
    "ab_submit_failed",
    406,
    collect=_raw("406 Not Acceptable", _json_bytes(_NOT_FOUND_ENVELOPE)),
    expected_message=_NOT_FOUND_ENVELOPE["msg_zh"],
)
_DOWNLOADER_REJECTED_CASE = _CollectCase(
    "collect_406_downloader_already_added",
    "ab_submit_failed",
    406,
    collect=_raw("406 Not Acceptable", _json_bytes(_ALREADY_ADDED_ENVELOPE)),
    expected_message=_ALREADY_ADDED_ENVELOPE["msg_zh"],
)
_UNAUTHORIZED_CASE = _CollectCase(
    "collect_401_unauthorized",
    "ab_auth_failed",
    401,
    collect=_raw("401 Unauthorized", _json_bytes({"detail": "Unauthorized"})),
)
_FORBIDDEN_CASE = _CollectCase(
    "collect_403_forbidden",
    "ab_auth_failed",
    403,
    collect=_raw("403 Forbidden", _json_bytes({"detail": "Forbidden"})),
)
_INVALID_BODY_CASE = _CollectCase(
    "collect_422_body_validation",
    "ab_submit_failed",
    422,
    collect=_raw(
        "422 Unprocessable Entity",
        _json_bytes(
            {
                "detail": [
                    {
                        "loc": ["body", "season"],
                        "msg": "Input should be a valid integer",
                        "type": "int_parsing",
                    }
                ]
            }
        ),
    ),
)
_SERVER_ERROR_CASE = _CollectCase(
    "collect_500_empty_body",
    "ab_submit_failed",
    500,
    collect=_raw("500 Internal Server Error", b""),
)
_INVALID_JSON_CASE = _CollectCase(
    "collect_200_invalid_json",
    "invalid_ab_response",
    None,
    collect=_raw("200 OK", b"{not json"),
)
_NON_OBJECT_CASE = _CollectCase(
    "collect_200_non_object_body",
    "invalid_ab_response",
    None,
    collect=_raw("200 OK", _json_bytes([])),
)
_MISSING_FIELD_CASE = _CollectCase(
    "collect_200_missing_message_field",
    "invalid_ab_response",
    None,
    collect=_raw("200 OK", _json_bytes({"msg_en": "Collections completed."})),
)
_TRUNCATED_BODY_CASE = _CollectCase(
    "collect_200_truncated_body",
    "invalid_ab_response",
    None,
    collect=_raw("200 OK", b'{"msg_en": "cut', declared_length=512),
)
_CREATED_CASE = _CollectCase(
    "collect_201_created",
    "ab_submit_failed",
    201,
    collect=_raw("201 Created", _json_bytes(_SUCCESS_ENVELOPE)),
)
_NO_CONTENT_CASE = _CollectCase(
    "collect_204_no_content",
    "ab_submit_failed",
    204,
    collect=_raw("204 No Content", b""),
)
_REDIRECT_CASE = _CollectCase(
    "collect_302_redirect",
    "ab_submit_failed",
    302,
    collect=_raw("302 Found", b""),
)
_TIMEOUT_CASE = _CollectCase(
    "collect_timeout",
    "ab_timeout",
    None,
    stall=True,
    timeout=0.3,
)
_CONNECTION_REFUSED_CASE = _CollectCase(
    "collect_connection_refused",
    "ab_connection_failed_pre_write",
    None,
    refused=True,
)
_UNVERIFIED_VERSION_CASE = _CollectCase(
    "collect_unverified_version",
    "ab_unsupported_version",
    None,
    version="3.1.17",
    expect_collect_attempt=False,
)
_PAYLOAD_WITH_ID_CASE = _CollectCase(
    "collect_payload_with_id",
    "invalid_ab_payload",
    None,
    payload={
        "id": 999999,
        "official_title": "番剧 标准标题",
        "title_raw": "番剧 标准标题",
        "season": 1,
        "rss_link": "https://example.invalid/rss.xml",
        "save_path": "番剧 标准标题",
    },
    expect_collect_attempt=False,
)

#: Every case whose judgement must be a definite 提交失败 (no false success).
_FAILURE_CASES = (
    _FILTER_EMPTY_CASE,
    _DOWNLOADER_REJECTED_CASE,
    _UNAUTHORIZED_CASE,
    _FORBIDDEN_CASE,
    _INVALID_BODY_CASE,
    _SERVER_ERROR_CASE,
    _INVALID_JSON_CASE,
    _NON_OBJECT_CASE,
    _MISSING_FIELD_CASE,
    _TRUNCATED_BODY_CASE,
    _CREATED_CASE,
    _NO_CONTENT_CASE,
    _REDIRECT_CASE,
    _TIMEOUT_CASE,
    _CONNECTION_REFUSED_CASE,
    _UNVERIFIED_VERSION_CASE,
    _PAYLOAD_WITH_ID_CASE,
)
_ALL_CASES = (_SUCCESS_CASE, *_FAILURE_CASES)


class _CollectStandIn:
    """A localhost-only raw-byte Auto Bangumi stand-in (never bound publicly)."""

    def __init__(self, case: _CollectCase) -> None:
        self._case = case
        self._socket = socket.socket()
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(8)
        # A short accept timeout lets close() stop the listener deterministically.
        self._socket.settimeout(0.2)
        self.port = self._socket.getsockname()[1]
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.requests: list[tuple[str, str, str]] = []
        threading.Thread(target=self._serve, daemon=True).start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def paths(self) -> list[str]:
        with self._lock:
            return [path for _method, path, _body in self.requests]

    def collect_bodies(self) -> list[Any]:
        with self._lock:
            return [
                json.loads(body or "{}")
                for _method, path, body in self.requests
                if path == _COLLECT_PATH
            ]

    def close(self) -> None:
        self._stop.set()
        with contextlib.suppress(OSError):
            self._socket.close()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                connection, _address = self._socket.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            threading.Thread(target=self._handle, args=(connection,), daemon=True).start()

    def _handle(self, connection: socket.socket) -> None:
        try:
            method, path, body = _read_request(connection)
            with self._lock:
                self.requests.append((method, path, body))
            if path == _LOGIN_PATH:
                connection.sendall(_LOGIN_RESPONSE)
                return
            if path == _STATUS_PATH:
                connection.sendall(_status_response(self._case.version))
                return
            if path == _COLLECT_PATH:
                if self._case.stall:
                    self._stop.wait(30)
                    return
                if self._case.collect is not None:
                    connection.sendall(self._case.collect)
                return
            raise AssertionError(f"unexpected Auto Bangumi path: {path}")
        except OSError:
            pass
        finally:
            with contextlib.suppress(OSError):
                connection.close()


def _read_request(connection: socket.socket) -> tuple[str, str, str]:
    """Consume one whole request before answering it.

    Answering while the body is still unread makes the kernel reset the
    connection on close, which would corrupt the response the client reads.
    """
    buffer = b""
    while b"\r\n\r\n" not in buffer:
        chunk = connection.recv(65536)
        if not chunk:
            return "", "/", ""
        buffer += chunk
    head, rest = buffer.split(b"\r\n\r\n", 1)
    lines = head.decode("iso-8859-1", "replace").split("\r\n")
    parts = lines[0].split(" ")
    method = parts[0] if parts and parts[0] else "POST"
    path = parts[1].split("?", 1)[0] if len(parts) > 1 else "/"
    length = 0
    for line in lines[1:]:
        name, _, value = line.partition(":")
        if name.strip().lower() == "content-length":
            with contextlib.suppress(ValueError):
                length = int(value.strip() or 0)
    while len(rest) < length:
        chunk = connection.recv(65536)
        if not chunk:
            break
        rest += chunk
    return method, path, rest[:length].decode("utf-8", "replace")


@contextlib.contextmanager
def _stand_in(case: _CollectCase):
    """Yield ``(base_url, server_or_None)`` for one case's exchange."""

    if case.refused:
        # Take a free loopback port and release it, so the following connect is
        # refused.  Assumption: nothing else binds that port in between (a
        # standard, tiny-probability local-test race, never a real service).
        holder = socket.socket()
        holder.bind(("127.0.0.1", 0))
        port = holder.getsockname()[1]
        holder.close()
        yield f"http://127.0.0.1:{port}", None
        return
    server = _CollectStandIn(case)
    try:
        yield server.base_url, server
    finally:
        server.close()


def _accepted_request() -> dict[str, Any]:
    """One accepted Request snapshot, built locally (no shared test import)."""

    pending = build_pending_request(
        EntryRequest("番剧"),
        MatchedBangumi("番剧 标准标题", [], "https://example.invalid/bangumi", 1.0),
        [],
        SubtitleGroupSelection("Loli", "https://example.invalid/rss.xml", []),
        FilterRule(must_contain="1080p", must_not_contain="SP"),
        "番剧 标准标题",
    )
    return accept_request(pending)


def _collect_body() -> dict[str, Any]:
    return build_legacy_31_collection_payload(_accepted_request())


def _run_case(case: _CollectCase) -> tuple[dict[str, Any], _CollectStandIn | None]:
    """Drive one case through the real 3.1.18 adapter and normalizer."""

    payload = _collect_body() if case.payload is None else case.payload
    with _stand_in(case) as (base_url, server):
        # The real 3.1.18 password adapter over the real transport; only the
        # bounded deadline is shortened so a stalled peer cannot hold the test
        # for the production 30s budget.
        client = LegacyAutoBangumi31Client(
            AutoBangumiConfig(base_url, "password", False, username="u", password="p"),
            transport=UrlopenAutoBangumiHttpTransport(),
            timeout=case.timeout,
        )
        result = collect_ab_resources(client, payload)
    return result, server


def test_corpus_is_source_derived_and_keeps_its_provenance() -> None:
    """The fixture corpus and its evidence list are the reviewable artifact."""

    assert {case.name for case in _ALL_CASES} == {
        "collect_200_success_envelope",
        "collect_406_filtered_to_nothing",
        "collect_406_downloader_already_added",
        "collect_401_unauthorized",
        "collect_403_forbidden",
        "collect_422_body_validation",
        "collect_500_empty_body",
        "collect_200_invalid_json",
        "collect_200_non_object_body",
        "collect_200_missing_message_field",
        "collect_200_truncated_body",
        "collect_201_created",
        "collect_204_no_content",
        "collect_302_redirect",
        "collect_timeout",
        "collect_connection_refused",
        "collect_unverified_version",
        "collect_payload_with_id",
    }
    assert len(_SOURCE_EVIDENCE) == 5
    assert all("3.1.18" in entry for entry in _SOURCE_EVIDENCE)
    for case in _ALL_CASES:
        if case.collect is not None:
            assert case.collect.startswith(b"HTTP/1.1 "), case.name


def test_success_envelope_has_no_status_field() -> None:
    """Issue #216's core correction, pinned on the collect envelope itself."""

    assert "status" not in _SUCCESS_ENVELOPE
    assert set(_SUCCESS_ENVELOPE) == {"msg_en", "msg_zh"}
    assert all(
        isinstance(value, str) and value.strip() for value in _SUCCESS_ENVELOPE.values()
    )
    decoded = json.loads(
        _raw("200 OK", _json_bytes(_SUCCESS_ENVELOPE)).split(b"\r\n\r\n", 1)[1]
    )
    assert decoded == _SUCCESS_ENVELOPE


def test_collect_success_posts_the_bare_body_and_is_added_to_download() -> None:
    result, server = _run_case(_SUCCESS_CASE)

    assert server is not None
    assert result["success"] is True
    # Exactly one collection POST, on the verified external path only: collect
    # never creates an RSS subscription.
    assert server.paths().count(_COLLECT_PATH) == 1
    assert "/api/v1/rss/subscribe" not in server.paths()
    sent = server.collect_bodies()[0]
    assert sent == _collect_body()
    assert set(sent).isdisjoint({"id", "data", "rss"})
    assert sent["rss_link"] == "https://example.invalid/rss.xml"
    # A one-time collection establishes no controlled subscription, and the real
    # #98 classifier turns the normalized success into 已加入下载.
    assert result["ab_subscription_id"] is None
    assert result["fallback_config"] is None
    assert classify_existing_resource_result(result) == TRACKING_STATUS_ADDED_TO_DOWNLOAD


def test_collect_never_attempts_a_write_for_an_unverified_version_or_payload() -> None:
    """Zero external writes before the boundary: version gate and payload shape."""

    for case in (_UNVERIFIED_VERSION_CASE, _PAYLOAD_WITH_ID_CASE):
        result, server = _run_case(case)
        assert result["success"] is False, case.name
        assert result["error"]["error_type"] == case.expected_error_type, case.name
        if server is not None:
            assert _COLLECT_PATH not in server.paths(), case.name


@pytest.mark.parametrize(
    "case", [_FILTER_EMPTY_CASE, _DOWNLOADER_REJECTED_CASE], ids=lambda case: case.name
)
def test_collect_406_dual_semantics_collapse_to_one_definite_failure(
    case: _CollectCase,
) -> None:
    """Upstream cannot distinguish "filtered to nothing" from "already added".

    Both answer 406 with the same copy, so claiming either one succeeded would
    invent evidence Auto Bangumi does not provide.
    """

    result, server = _run_case(case)

    assert server is not None
    assert result["success"] is False
    assert result["error"]["error_type"] == "ab_submit_failed"
    assert result["error"]["details"]["status_code"] == 406
    assert result["error"]["details"]["http_status"] == 406
    assert server.paths().count(_COLLECT_PATH) == 1
    assert classify_existing_resource_result(result) == TRACKING_STATUS_SUBMIT_FAILED


@pytest.mark.parametrize("case", _FAILURE_CASES, ids=lambda case: case.name)
def test_source_derived_failures_are_definite_collect_failures(
    case: _CollectCase,
) -> None:
    result, server = _run_case(case)

    assert result["success"] is False, case.name
    error = result["error"]
    assert error["error_type"] == case.expected_error_type, case.name
    details = error["details"]
    if case.expected_http_status is None:
        assert "status_code" not in details, case.name
    else:
        assert details.get("status_code") == case.expected_http_status, case.name

    if server is not None and case.expect_collect_attempt:
        # One attempt, one external call: a collection never auto-retries.
        assert server.paths().count(_COLLECT_PATH) == 1, case.name
    if case.expected_message is not None:
        # Issue #101/#216: the bounded, sanitized reason may travel in the
        # diagnostics, and only there.
        assert details.get("message_zh") == case.expected_message, case.name
        assert len(details["message_zh"]) <= 200, case.name

    # The raw upstream framing and the session cookie never leave the adapter.
    serialized = json.dumps(error, ensure_ascii=False)
    for leaked in ("ab-session", "Content-Length", "HTTP/1.1", "Unauthorized", "Forbidden"):
        assert leaked not in serialized, case.name

    outcome = classify_existing_resource_result(result)
    assert outcome == TRACKING_STATUS_SUBMIT_FAILED, case.name
    # Collect is a one-time request: a fault stays a retryable 提交失败 and must
    # never be promoted into a controlled-subscription state.
    assert outcome not in (
        TRACKING_STATUS_ACTIVE,
        TRACKING_STATUS_VERIFYING_EXTERNAL,
        TRACKING_STATUS_RECOVERY_REQUIRED,
    ), case.name
