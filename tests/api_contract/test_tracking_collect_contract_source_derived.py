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
those exact bytes, so the assertions measure the real transport and the real
"download existing resources" classifier instead of a fake response object.
Nothing here talks to a real Auto Bangumi, and no credential is used besides the
obviously fake ``ab-session`` cookie the stand-in never validates.

Scope note: the exact-200 tightening (201/204/3xx must fail) and the
``msg_en``/``msg_zh`` field validation are issue #216 AC1, so they are not
asserted here yet.  The file's only seam stub is ``_TransportCollectClient``,
which performs exactly the one POST the production collect client will perform;
every judgement asserted below — HTTP status mapping, ``ab_submit_result``
normalization and the "download existing resources" classification — is
production code, and the transport call the stub makes is the seam #216 AC2
refines.
"""

import contextlib
import json
import socket
import threading
from dataclasses import dataclass
from typing import Any

import pytest

from ab_engine.controllers.ab_client import FakeAutoBangumiClient, submit_ab_subscription
from ab_engine.controllers.ab_http_client import UrlopenAutoBangumiHttpTransport
from ab_engine.controllers.submit_result import ab_submit_success
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

#: The verified 3.1.18 path; the inventory documents it as an *external* AB
#: endpoint that never enters this repository's Flask url_map or OpenAPI.
_COLLECT_PATH = "/api/v1/rss/collect"

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


@dataclass(frozen=True)
class _CollectCase:
    """One source-derived collect exchange and its required judgement."""

    name: str
    expected_error_type: str | None
    expected_http_status: int | None
    raw: bytes | None = None
    #: Accept the connection and never answer: the transport must hit its own
    #: deadline instead of inventing a result.
    stall: bool = False
    #: No listener at all, so the connect itself is refused.
    refused: bool = False
    timeout: float = 2.0


_SUCCESS_CASE = _CollectCase(
    "collect_200_success_envelope",
    None,
    None,
    raw=_raw("200 OK", _json_bytes(_SUCCESS_ENVELOPE)),
)
_FILTER_EMPTY_CASE = _CollectCase(
    "collect_406_filtered_to_nothing",
    "ab_submit_failed",
    406,
    raw=_raw("406 Not Acceptable", _json_bytes(_NOT_FOUND_ENVELOPE)),
)
_DOWNLOADER_REJECTED_CASE = _CollectCase(
    "collect_406_downloader_already_added",
    "ab_submit_failed",
    406,
    raw=_raw("406 Not Acceptable", _json_bytes(_ALREADY_ADDED_ENVELOPE)),
)
_UNAUTHORIZED_CASE = _CollectCase(
    "collect_401_unauthorized",
    "ab_auth_failed",
    401,
    raw=_raw("401 Unauthorized", _json_bytes({"detail": "Unauthorized"})),
)
_FORBIDDEN_CASE = _CollectCase(
    "collect_403_forbidden",
    "ab_auth_failed",
    403,
    raw=_raw("403 Forbidden", _json_bytes({"detail": "Forbidden"})),
)
_INVALID_BODY_CASE = _CollectCase(
    "collect_422_body_validation",
    "ab_submit_failed",
    422,
    raw=_raw(
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
_INVALID_JSON_CASE = _CollectCase(
    "collect_200_invalid_json",
    "invalid_ab_response",
    None,
    raw=_raw("200 OK", b"{not json"),
)
_NON_OBJECT_CASE = _CollectCase(
    "collect_200_non_object_body",
    "invalid_ab_response",
    None,
    raw=_raw("200 OK", _json_bytes([])),
)
_TRUNCATED_BODY_CASE = _CollectCase(
    "collect_200_truncated_body",
    "invalid_ab_response",
    None,
    raw=_raw("200 OK", b'{"msg_en": "cut', declared_length=512),
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
    "ab_connection_failed",
    None,
    refused=True,
)

#: Every case whose judgement must be a definite 提交失败.
_FAILURE_CASES = (
    _FILTER_EMPTY_CASE,
    _DOWNLOADER_REJECTED_CASE,
    _UNAUTHORIZED_CASE,
    _FORBIDDEN_CASE,
    _INVALID_BODY_CASE,
    _INVALID_JSON_CASE,
    _NON_OBJECT_CASE,
    _TRUNCATED_BODY_CASE,
    _TIMEOUT_CASE,
    _CONNECTION_REFUSED_CASE,
)
_ALL_CASES = (_SUCCESS_CASE, *_FAILURE_CASES)


class _CollectStandIn:
    """A localhost-only raw-byte Auto Bangumi stand-in (never bound publicly)."""

    def __init__(self, response: bytes | None, *, stall: bool = False) -> None:
        self._response = response
        self._stall = stall
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
            if self._stall:
                self._stop.wait(30)
                return
            if self._response:
                connection.sendall(self._response)
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
    server = _CollectStandIn(case.raw, stall=case.stall)
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


def _post_collect(
    base_url: str, *, timeout: float, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    """One real transport POST to the collect path with the built body.

    This is the single point coupling this file to the transport seam that
    issue #216 AC2 refines (exact status plus a contract-validated object).
    """

    transport = UrlopenAutoBangumiHttpTransport()
    return transport.post_json_same_origin(
        f"{base_url}{_COLLECT_PATH}",
        {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Cookie": "token=ab-session",
        },
        _collect_body() if payload is None else payload,
        timeout=timeout,
    )


class _TransportCollectClient:
    """The minimal Auto Bangumi client over the verified external collect path.

    The file's only seam stub: it performs exactly the one POST the production
    collect client will perform, so the *response* fed into the production
    ``submit_ab_subscription``/``classify_existing_resource_result`` chain is the
    real wire result instead of a test-constructed result object.
    """

    def __init__(self, base_url: str, *, timeout: float) -> None:
        self._base_url = base_url
        self._timeout = timeout

    def create_subscription(self, payload: dict[str, Any]) -> dict[str, Any]:
        return _post_collect(self._base_url, timeout=self._timeout, payload=payload)


def _collect_exchange(base_url: str, *, timeout: float) -> dict[str, Any]:
    """One collect attempt normalized by the production submit chain."""

    return submit_ab_subscription(
        _TransportCollectClient(base_url, timeout=timeout), _collect_body()
    )


def test_corpus_is_source_derived_and_keeps_its_provenance() -> None:
    """The fixture corpus and its evidence list are the reviewable artifact."""

    assert {case.name for case in _ALL_CASES} == {
        "collect_200_success_envelope",
        "collect_406_filtered_to_nothing",
        "collect_406_downloader_already_added",
        "collect_401_unauthorized",
        "collect_403_forbidden",
        "collect_422_body_validation",
        "collect_200_invalid_json",
        "collect_200_non_object_body",
        "collect_200_truncated_body",
        "collect_timeout",
        "collect_connection_refused",
    }
    assert len(_SOURCE_EVIDENCE) == 5
    assert all("3.1.18" in entry for entry in _SOURCE_EVIDENCE)
    for case in _ALL_CASES:
        if case.raw is not None:
            assert case.raw.startswith(b"HTTP/1.1 "), case.name


def test_success_envelope_has_no_status_field() -> None:
    """Issue #216's core correction, pinned on the collect envelope itself."""

    assert "status" not in _SUCCESS_ENVELOPE
    assert set(_SUCCESS_ENVELOPE) == {"msg_en", "msg_zh"}
    assert all(
        isinstance(value, str) and value.strip() for value in _SUCCESS_ENVELOPE.values()
    )
    decoded = json.loads(_raw("200 OK", _json_bytes(_SUCCESS_ENVELOPE)).split(b"\r\n\r\n", 1)[1])
    assert decoded == _SUCCESS_ENVELOPE


def test_collect_success_is_a_bare_bangumi_body_and_added_to_download() -> None:
    with _stand_in(_SUCCESS_CASE) as (base_url, server):
        assert server is not None
        body = _post_collect(base_url, timeout=_SUCCESS_CASE.timeout)

    assert body == _SUCCESS_ENVELOPE
    # Exactly one request, on the verified external path only: collect never
    # creates an RSS subscription.
    assert [path for _method, path, _body in server.requests] == [_COLLECT_PATH]
    method, _path, sent = server.requests[0]
    assert method == "POST"
    parsed = json.loads(sent)
    assert parsed == _collect_body()
    assert "data" not in parsed and "rss" not in parsed and "id" not in parsed
    # A one-time collection establishes no controlled subscription and its
    # success envelope carries no subscription id, so the shared subscribe
    # normalization provably cannot carry it: the collect seam must normalize
    # this one case itself (production work for #217 after #216).
    refused = submit_ab_subscription(
        FakeAutoBangumiClient(response=dict(body)), _collect_body()
    )
    assert refused["success"] is False
    assert refused["error"]["error_type"] == "invalid_ab_submit_result"
    # The collect-mode outcome is then 已加入下载, never a subscription state.
    assert classify_existing_resource_result(ab_submit_success(None, body)) == (
        TRACKING_STATUS_ADDED_TO_DOWNLOAD
    )


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

    with _stand_in(case) as (base_url, server):
        assert server is not None
        result = _collect_exchange(base_url, timeout=case.timeout)

    assert len(server.requests) == 1, case.name
    assert result["success"] is False, case.name
    assert result["error"]["error_type"] == "ab_submit_failed", case.name
    assert result["error"]["details"].get("status_code") == 406, case.name
    assert classify_existing_resource_result(result) == TRACKING_STATUS_SUBMIT_FAILED


@pytest.mark.parametrize("case", _FAILURE_CASES, ids=lambda case: case.name)
def test_source_derived_failures_are_definite_collect_failures(
    case: _CollectCase,
) -> None:
    with _stand_in(case) as (base_url, server):
        result = _collect_exchange(base_url, timeout=case.timeout)

    if server is not None:
        # One attempt, one external call: collect never auto-retries a fault.
        assert len(server.requests) == 1, case.name
    assert result["success"] is False, case.name
    error = result["error"]
    assert error["error_type"] == case.expected_error_type, case.name
    if case.expected_http_status is None:
        assert "status_code" not in error["details"], case.name
    else:
        assert error["details"].get("status_code") == case.expected_http_status, case.name

    # The raw upstream envelope and the session cookie never leave the adapter.
    serialized = json.dumps(error, ensure_ascii=False)
    for leaked in (
        "种子已经添加",
        "Unauthorized",
        "Forbidden",
        "Input should be a valid integer",
        "ab-session",
    ):
        assert leaked not in serialized, case.name

    outcome = classify_existing_resource_result(result)
    assert outcome == TRACKING_STATUS_SUBMIT_FAILED, case.name
    # Collect is a one-time request: a fault stays a retryable 提交失败 and must
    # never be promoted into a controlled-subscription confirmation state.
    assert outcome not in (
        TRACKING_STATUS_ACTIVE,
        TRACKING_STATUS_VERIFYING_EXTERNAL,
        TRACKING_STATUS_RECOVERY_REQUIRED,
    ), case.name
