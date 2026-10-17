from __future__ import annotations

"""Issue #183 review: the real HTTP transport honours one absolute deadline.

Every case runs against a **localhost-only** Auto Bangumi stand-in that speaks
raw bytes, so the assertions measure real socket behaviour instead of a fake
response object.  The previous implementation bounded a single socket operation:
a peer that kept trickling headers or a body held the read open far past the
endpoint budget, and closing the response from another thread did not interrupt
the blocked read.
"""

import contextlib
import json
import os
import socket
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient

from ab_engine.controllers.ab_config import AutoBangumiConfig
from ab_engine.controllers.ab_http_client import UrlopenAutoBangumiHttpTransport
from ab_engine.controllers.ab_management_client import create_legacy_31_management_client
from apps.migu_orca_web.tracking_external_check import single_flight_check
from apps.migu_orca_web.tracking_handoff import ensure_confirmed_request_tracking
from shared.errors import Stage1Error
from storage_engine.controllers.autobangumi_config_repository import (
    AutoBangumiConfigRepository,
    build_stored_autobangumi_config,
)
from storage_engine.controllers.storage_config import load_storage_config
from storage_engine.controllers.tracking_repository import load_tracking_record
from tests.api_contract.ab_write_envelopes import SOURCE_DERIVED_SUBSCRIBE_ENVELOPE
from tests.api_contract.test_tracking_submit_api import (
    _accepted_request,
)
from tracking_engine.controllers.submit import (
    classify_external_submit_result,
    confirm_subscription_outcome,
)
from tracking_engine.models.operation import TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN
from tracking_engine.models.tracking import (
    TRACKING_ORIGIN_SAVE_CONFIRM,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
)

#: Scheduling tolerance for a real loopback measurement. It must stay far below
#: the violations this module catches (10s body / 1s headers on the old code).
_TOLERANCE_SECONDS = 0.4

_Handler = Callable[[socket.socket, threading.Event, str], None]


class _LocalAbServer:
    """A localhost-only raw-byte HTTP stand-in; never bound to a public host."""

    def __init__(self, handler: _Handler) -> None:
        self._handler = handler
        self._socket = socket.socket()
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(8)
        # A short accept timeout lets close() stop the listener even while the
        # accept loop is blocked (a plain close does not interrupt accept()).
        self._socket.settimeout(0.2)
        self.port = self._socket.getsockname()[1]
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.requests: list[str] = []
        self.disconnects = 0
        threading.Thread(target=self._serve, daemon=True).start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                connection, _ = self._socket.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            threading.Thread(target=self._handle, args=(connection,), daemon=True).start()

    def _handle(self, connection: socket.socket) -> None:
        try:
            entry, path = _read_request(connection)
            with self._lock:
                self.requests.append(entry)
            self._handler(connection, self._stop, path)
        except OSError:
            pass
        finally:
            with self._lock:
                self.disconnects += 1
            with contextlib.suppress(OSError):
                connection.close()

    def close(self) -> None:
        self._stop.set()
        with contextlib.suppress(OSError):
            self._socket.close()

    def count(self, entry: str) -> int:
        with self._lock:
            return self.requests.count(entry)


def _read_request(connection: socket.socket) -> tuple[str, str]:
    """Consume one complete request (headers and body) before answering it.

    Answering while the request body is still unread makes the kernel reset the
    connection on close, which would corrupt the response the client reads.
    """
    buffer = b""
    while b"\r\n\r\n" not in buffer:
        chunk = connection.recv(65536)
        if not chunk:
            return "", "/"
        buffer += chunk
    head, rest = buffer.split(b"\r\n\r\n", 1)
    lines = head.decode("iso-8859-1", "replace").split("\r\n")
    parts = lines[0].split(" ")
    method = parts[0] if parts and parts[0] else "GET"
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
    return f"{method} {path}", path


def _send(connection: socket.socket, data: bytes) -> bool:
    """Send one chunk; False means the peer is gone (the read must stop)."""
    try:
        connection.sendall(data)
    except OSError:
        return False
    return True


def _respond_json(body: bytes, *, delay: float = 0.0) -> _Handler:
    def handler(connection: socket.socket, stop: threading.Event, path: str) -> None:
        del stop, path
        if delay:
            time.sleep(delay)
        _send(
            connection,
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n"
            % len(body)
            + body,
        )

    return handler


def _trickle_headers(connection: socket.socket, stop: threading.Event, path: str) -> None:
    """Status line at once, then one header every 50ms for a long time."""
    del path
    _send(connection, b"HTTP/1.1 200 OK\r\n")
    for index in range(400):
        if stop.is_set():
            return
        time.sleep(0.05)
        if not _send(connection, b"X-Pad-%d: %d\r\n" % (index, index)):
            return


def _trickle_body(connection: socket.socket, stop: threading.Event, path: str) -> None:
    """A declared 4000-byte body that arrives one byte every 50ms."""
    del path
    _send(
        connection,
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 4000\r\n\r\n",
    )
    for _ in range(4000):
        if stop.is_set():
            return
        time.sleep(0.05)
        if not _send(connection, b"x"):
            return


def _created_then_stall(connection: socket.socket, stop: threading.Event, path: str) -> None:
    """A 201 whose declared body never arrives: the status is already decided."""
    del path
    _send(
        connection,
        b"HTTP/1.1 201 Created\r\nContent-Length: 4000\r\n\r\n",
    )
    for _ in range(4000):
        if stop.is_set():
            return
        time.sleep(0.05)
        if not _send(connection, b"x"):
            return


def _stalled_handshake(connection: socket.socket, stop: threading.Event, path: str) -> None:
    """Accept TCP and then say nothing, so the TLS handshake cannot finish."""
    del path
    stop.wait(30)
    del connection


def _unauthorized_then_stall(connection: socket.socket, stop: threading.Event, path: str) -> None:
    """A 401 whose body never arrives: the status is already proven."""
    del path
    _send(
        connection,
        b"HTTP/1.1 401 Unauthorized\r\nContent-Length: 4000\r\n\r\n",
    )
    for _ in range(4000):
        if stop.is_set():
            return
        time.sleep(0.05)
        if not _send(connection, b"x"):
            return


def _stall(connection: socket.socket, stop: threading.Event, path: str) -> None:
    del path
    stop.wait(30)


def _ab_submit_session() -> _Handler:
    """One 3.1.18 session: a successful write, then a stalled read-back list."""

    def handler(connection: socket.socket, stop: threading.Event, path: str) -> None:
        if path == "/api/v1/auth/login":
            _respond_json(b'{"access_token": "ab-session"}')(connection, stop, path)
        elif path == "/api/v1/status":
            _respond_json(b'{"version": "3.1.18"}')(connection, stop, path)
        elif path == "/api/v1/rss/subscribe":
            _respond_json(json.dumps(SOURCE_DERIVED_SUBSCRIBE_ENVELOPE).encode("utf-8"))(connection, stop, path)
        elif path == "/api/v1/bangumi/get/all":
            # The read-back never finishes: it must time out, not be invented.
            _trickle_body(connection, stop, path)
        else:
            _respond_json(b"[]")(connection, stop, path)

    return handler


def _ab_healthy_session() -> _Handler:
    """A complete, fast 3.1.18 session: login, status and empty lists."""

    def handler(connection: socket.socket, stop: threading.Event, path: str) -> None:
        if path == "/api/v1/auth/login":
            _respond_json(b'{"access_token": "ab-session"}')(connection, stop, path)
        elif path == "/api/v1/status":
            _respond_json(b'{"version": "3.1.18"}')(connection, stop, path)
        else:
            _respond_json(b"[]")(connection, stop, path)

    return handler


def _write_elapsed(url: str, timeout: float) -> tuple[int, float]:
    """One write through the real transport: its exact status and elapsed time."""
    transport = UrlopenAutoBangumiHttpTransport()
    started = time.monotonic()
    response = transport.write_json(
        "POST", f"{url}/api/v1/rss/subscribe", {"Content-Type": "application/json"}, {}, timeout=timeout
    )
    return response.status_code, time.monotonic() - started


def _exchange_elapsed(url: str, timeout: float) -> tuple[str, float]:
    transport = UrlopenAutoBangumiHttpTransport()
    started = time.monotonic()
    try:
        transport.request_json(
            "GET", f"{url}/api/v1/rss", {"Accept": "application/json"}, timeout=timeout
        )
        outcome = "ok"
    except Stage1Error as exc:
        outcome = exc.error_type
    return outcome, time.monotonic() - started


class TestStrictReadDeadline:
    def test_normal_response_succeeds(self) -> None:
        server = _LocalAbServer(_respond_json(b'[{"id": 7, "url": "https://rss.invalid/feed"}]'))
        try:
            outcome, elapsed = _exchange_elapsed(server.base_url, 2.0)
        finally:
            server.close()
        assert outcome == "ok"
        assert elapsed < 1.0

    def test_trickling_response_headers_stop_at_the_deadline(self) -> None:
        server = _LocalAbServer(_trickle_headers)
        try:
            outcome, elapsed = _exchange_elapsed(server.base_url, 0.2)
        finally:
            server.close()
        assert outcome == "ab_timeout"
        assert elapsed < 0.2 + _TOLERANCE_SECONDS, elapsed

    def test_trickling_response_body_stops_at_the_deadline(self) -> None:
        server = _LocalAbServer(_trickle_body)
        try:
            outcome, elapsed = _exchange_elapsed(server.base_url, 0.2)
        finally:
            server.close()
        assert outcome == "ab_timeout"
        assert elapsed < 0.2 + _TOLERANCE_SECONDS, elapsed

    def test_a_fully_stalled_response_stops_at_the_deadline(self) -> None:
        server = _LocalAbServer(_stall)
        try:
            outcome, elapsed = _exchange_elapsed(server.base_url, 0.2)
        finally:
            server.close()
        assert outcome == "ab_timeout"
        assert elapsed < 0.2 + _TOLERANCE_SECONDS, elapsed

    def test_a_snapshot_shares_one_deadline_across_its_requests(self) -> None:
        """The sub-requests of one read never restart the budget."""
        server = _LocalAbServer(_trickle_headers)
        config = AutoBangumiConfig(server.base_url, "password", False, username="u", password="p")
        client = create_legacy_31_management_client(
            config, transport=UrlopenAutoBangumiHttpTransport()
        )
        started = time.monotonic()
        try:
            with pytest.raises(Stage1Error) as error:
                client.read_snapshot(deadline=time.monotonic() + 0.3)
        finally:
            server.close()
        elapsed = time.monotonic() - started
        assert error.value.error_type == "ab_timeout"
        assert elapsed < 0.3 + _TOLERANCE_SECONDS, elapsed
        assert server.count("POST /api/v1/auth/login") == 1, server.requests

    def test_the_connection_and_reading_resources_are_reclaimed(self) -> None:
        """The timed-out socket is closed, nothing keeps reading in the background."""
        baseline_threads = threading.active_count()
        assert baseline_threads >= 1
        server = _LocalAbServer(_trickle_body)
        try:
            outcome, _elapsed = _exchange_elapsed(server.base_url, 0.2)
            assert outcome == "ab_timeout"
            deadline = time.monotonic() + 2.0
            while server.disconnects == 0 and time.monotonic() < deadline:
                time.sleep(0.02)
            disconnects = server.disconnects
        finally:
            server.close()
        assert disconnects >= 1, "the client must close the timed-out connection"
        healthy = _LocalAbServer(_respond_json(b'{"version": "3.1.18"}'))
        try:
            assert _exchange_elapsed(healthy.base_url, 2.0)[0] == "ok"
        finally:
            healthy.close()
        # The implementation reads on the calling thread: the removed watchdog
        # was a non-daemon Timer, so no non-daemon worker may survive a timeout.
        assert baseline_threads >= 1
        assert [
            thread.name for thread in threading.enumerate()
            if thread is not threading.main_thread() and not thread.daemon
        ] == []

    def test_timeout_releases_the_dedupe_lock_and_the_config_lease(self, tmp_path: Path) -> None:
        """Issue #183: after a timeout a later check can run again."""
        server = _LocalAbServer(_trickle_body)
        repository = AutoBangumiConfigRepository(tmp_path / "private")
        saved = repository.save(
            build_stored_autobangumi_config(
                {
                    "auth_mode": "password", "base_url": server.base_url,
                    "username": "u", "password": "p",
                }
            ),
            expected_configuration_revision=0,
        )
        transport = UrlopenAutoBangumiHttpTransport()
        try:
            with (
                single_flight_check("tracking-a"),
                repository.acquire_lease(connection_ref=saved.connection_ref) as lease,
            ):
                assert lease.record.config is not None
                client = create_legacy_31_management_client(
                    lease.record.config.to_runtime_config(), transport=transport
                )
                with pytest.raises(Stage1Error) as error:
                    client.read_snapshot(deadline=time.monotonic() + 0.2)
                assert error.value.error_type == "ab_timeout"
        finally:
            server.close()

        healthy = _LocalAbServer(_ab_healthy_session())
        try:
            rebound = repository.save(
                build_stored_autobangumi_config(
                    {
                        "auth_mode": "password", "base_url": healthy.base_url,
                        "username": "u", "password": "p",
                    }
                ),
                expected_configuration_revision=saved.configuration_revision,
            )
            with (
                single_flight_check("tracking-a"),
                repository.acquire_lease(connection_ref=rebound.connection_ref) as lease,
            ):
                assert lease.record.config is not None
                client = create_legacy_31_management_client(
                    lease.record.config.to_runtime_config(), transport=transport
                )
                _capabilities, subscriptions, rss = client.read_snapshot()
                assert subscriptions == [] and rss == []
        finally:
            healthy.close()


class TestSubmitReadbackDeadline:
    def test_a_timed_out_readback_never_resubmits_and_stays_unknown(
        self, tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The write went out once; an unreadable read-back stays 结果待确认."""
        server = _LocalAbServer(_ab_submit_session())
        try:
            repository = AutoBangumiConfigRepository(tmp_path / "config")
            saved = repository.save(
                build_stored_autobangumi_config(
                    {
                        "auth_mode": "password", "base_url": server.base_url,
                        "username": "u", "password": "p",
                    }
                ),
                expected_configuration_revision=0,
            )
            request = _accepted_request(tmp_path)
            record = load_tracking_record(
                load_storage_config(tmp_path / "storage"),
                ensure_confirmed_request_tracking(
                    config=load_storage_config(tmp_path / "storage"),
                    request=request,
                    origin=TRACKING_ORIGIN_SAVE_CONFIRM,
                    now="2026-09-08T00:00:00+00:00",
                ).tracking_id,
            )
            body = {
                "expected_revision": record.revision,
                "storage_dir": "storage",
                "confirm": True,
                "idempotency_key": "key-deadline",
                "connection_ref": str(saved.connection_ref),
                "configuration_revision": saved.configuration_revision,
            }
            # Only the per-attempt read timeout is shortened; the real transport,
            # decoder, adapters and persistence all still run.
            import apps.migu_orca_web.tracking_submission_service as submission

            real_factory = submission.create_management_client
            monkeypatch.setattr(
                submission,
                "create_management_client",
                lambda config, **kwargs: real_factory(
                    config, **{**kwargs, "timeout": 0.2}
                ),
            )

            response = client.post(
                f"/api/v1/tracking/items/{record.tracking_id}/submit", json=body
            )

            assert response.status_code == 200
            result = response.get_json()["result"]
            assert result["tracking"]["status"] == TRACKING_STATUS_VERIFYING_EXTERNAL
            assert result["failure_category"] == "OUTCOME_UNKNOWN"
            stored = load_tracking_record(
                load_storage_config(tmp_path / "storage"), record.tracking_id
            )
            assert stored.external_mapping is None
            # Issue #169: the unreadable read-back is 结果待确认, verbatim.
            assert stored.audit_events[-1]["safe_message"] == "Auto Bangumi 结果待确认，请先恢复核验"
            # Exactly one external write, never a resubmit after the timeout.
            assert server.count("POST /api/v1/rss/subscribe") == 1, server.requests
        finally:
            server.close()

    def test_an_unreadable_readback_is_unknown_and_never_a_failure(self) -> None:
        """The classification of a sent write + unreadable read-back, directly."""
        write_result: dict[str, Any] = {"success": True, "ab_subscription_id": "sub-1"}
        assert classify_external_submit_result(write_result) != TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN
        confirmed = confirm_subscription_outcome(
            ab_result=write_result,
            expected_rss_url="https://rss.invalid/feed",
            snapshot=None,
        )
        assert confirmed.classification == TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN
        assert confirmed.external_id is None
        assert confirmed.reason == "UNREADABLE"


class TestConnectionPhaseDeadline:
    def test_a_stalled_tls_handshake_uses_only_the_remaining_budget(self) -> None:
        """TCP is established, but TLS must not get a fresh full timeout."""
        server = _LocalAbServer(_stalled_handshake)
        try:
            outcome, elapsed = _exchange_elapsed(f"https://{server.base_url.split('//')[1]}", 0.2)
        finally:
            server.close()
        assert outcome == "ab_timeout"
        assert elapsed < 0.2 + _TOLERANCE_SECONDS, elapsed

    def test_a_rejected_write_keeps_its_status_when_the_error_body_never_arrives(self) -> None:
        """Issue #216: only a bounded slice of the budget may chase the error body.

        The 3.1.18 write body is read for one documented business rejection, but
        the header block already decided the exchange: a stalled rejection body
        costs the bounded slice at most and can never hide the status, turn it
        into a timeout or consume the whole attempt budget.
        """
        server = _LocalAbServer(_unauthorized_then_stall)
        try:
            status, elapsed = _write_elapsed(server.base_url, 10.0)
        finally:
            server.close()
        assert status == 401, status
        assert elapsed < 2.0 + _TOLERANCE_SECONDS, elapsed

    def test_a_non_200_2xx_write_keeps_its_status_when_the_body_never_arrives(self) -> None:
        """Issue #216: only an exact 200 may be a write success.

        A 201/202/206 body is therefore diagnostic, not the decision: it gets the
        same short sub-budget as any other rejection, so a stalled body can never
        replace the proven status with an unproven timeout.
        """
        server = _LocalAbServer(_created_then_stall)
        try:
            status, elapsed = _write_elapsed(server.base_url, 10.0)
        finally:
            server.close()
        assert status == 201, status
        assert elapsed < 2.0 + _TOLERANCE_SECONDS, elapsed

    def test_a_proven_unauthorized_status_is_never_reported_as_a_timeout(self) -> None:
        """A 401 is decided by the header block, before its stalled body."""
        server = _LocalAbServer(_unauthorized_then_stall)
        try:
            outcome, elapsed = _exchange_elapsed(server.base_url, 2.0)
        finally:
            server.close()
        assert outcome == "ab_auth_failed", outcome
        assert elapsed < 0.5, elapsed

    def test_a_failed_connect_is_reclaimed_and_classified(self) -> None:
        """Nothing is left half-open when the connection never establishes."""
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        dead_port = probe.getsockname()[1]
        probe.close()
        dead_url = f"http://127.0.0.1:{dead_port}"
        before = _open_file_descriptors()
        for _ in range(5):
            outcome, _elapsed = _exchange_elapsed(dead_url, 0.5)
            assert outcome in {"ab_connection_failed", "ab_timeout"}, outcome
        assert _open_file_descriptors() <= before + 1
        assert [
            thread.name for thread in threading.enumerate()
            if thread is not main_thread() and not thread.daemon
        ] == []

    def test_a_literal_or_localhost_host_never_uses_the_resolver(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DNS has no stdlib timeout, so the common hosts must not need it."""
        import ab_engine.controllers.ab_http_client as module

        def _forbidden(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("getaddrinfo must not be called for a literal host")

        server = _LocalAbServer(_respond_json(b"[]"))
        try:
            monkeypatch.setattr(module.socket, "getaddrinfo", _forbidden)
            assert _exchange_elapsed(server.base_url, 2.0)[0] == "ok"
            assert _exchange_elapsed(f"http://localhost:{server.port}", 2.0)[0] == "ok"
            assert module._resolved_addresses("127.0.0.1", 80)[0][4] == ("127.0.0.1", 80)
            assert module._resolved_addresses("localhost", 80)[0][4] == ("127.0.0.1", 80)
        finally:
            server.close()


def main_thread() -> threading.Thread:
    return threading.main_thread()


def _open_file_descriptors() -> int:
    try:
        return len(os.listdir("/proc/self/fd"))
    except OSError:  # pragma: no cover - non-Linux hosts
        return 0
