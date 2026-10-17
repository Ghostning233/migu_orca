from __future__ import annotations

"""Main chain: confirm whether Auto Bangumi created the subscription.

Real Flask, the real Auto Bangumi 3.1.18 password adapters, the real URL
decoder, the real bounded read and the real persistence all run; only the
outermost HTTP hop is a **localhost** Auto Bangumi stand-in (issue #182/#183,
scoped to HTTP + literal IPv4).  Nothing here touches a real Auto Bangumi, and
every assertion is about the persisted local truth plus the exact external
requests that were made.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient

from apps.migu_orca_web.tracking_handoff import ensure_confirmed_request_tracking
from storage_engine.controllers.autobangumi_config_repository import (
    AutoBangumiConfigRepository,
    build_stored_autobangumi_config,
)
from storage_engine.controllers.operation_repository import load_tracking_operation
from storage_engine.controllers.storage_config import load_storage_config
from storage_engine.controllers.tracking_repository import load_tracking_record
from tests.api_contract.ab_write_envelopes import SOURCE_DERIVED_SUBSCRIBE_ENVELOPE
from tests.api_contract.test_tracking_submit_api import _accepted_request
from tracking_engine.controllers.submit import SUBMIT_SUCCEEDED_MESSAGE
from tracking_engine.models.tracking import (
    TRACKING_ORIGIN_SAVE_CONFIRM,
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
)

SUBMIT = "/api/v1/tracking/items/{tracking_id}/submit"
CHECK = "/api/v1/tracking/items/{tracking_id}/check"


class _AbState:
    """Everything the stand-in Auto Bangumi needs, mutated by each test."""

    def __init__(self) -> None:
        self.mode = "match"          # match | empty | drop_list | auth_fail_list
        self.version = "3.1.18"      # issue #184: a test may pin another version
        #: Issue #184: when set, the subscription only becomes visible once this
        #: many subscribe writes happened ("eventually visible"), so one test can
        #: hold a pending submit, refuse the resubmit offer, and still let the
        #: second write be confirmed. ``None`` keeps the #183 behavior.
        self.visible_after_writes: int | None = None
        self.drop_write = False      # accept the write, then answer nothing
        self.rss_url: str | None = None
        self.subscribe_bodies: list[dict[str, Any]] = []
        self.list_requests = 0
        self.requests: list[str] = []
        self._lock = threading.Lock()

    def record(self, entry: str) -> None:
        with self._lock:
            self.requests.append(entry)

    def snapshot(self) -> tuple[int, int]:
        with self._lock:
            return len(self.subscribe_bodies), self.list_requests


def _visible(state: _AbState) -> bool:
    if not state.rss_url:
        return False
    if state.visible_after_writes is not None:
        return len(state.subscribe_bodies) >= state.visible_after_writes
    return state.mode == "match"


def _subscriptions(state: _AbState) -> list[dict[str, Any]]:
    if not _visible(state):
        return []
    return [{
        "id": 42, "official_title": "葬送的芙莉莲", "title_raw": "Frieren",
        "season": 1, "group_name": "喵萌", "rss_link": state.rss_url,
        "rss_ids": [7], "deleted": False,
    }]


def _rss_items(state: _AbState) -> list[dict[str, Any]]:
    if not _visible(state):
        return []
    return [{
        "id": 7, "name": "RSS", "url": state.rss_url,
        "aggregate": False, "parser": "rss", "enabled": True,
    }]


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    state: _AbState

    def log_message(self, *args: Any) -> None:  # keep pytest output clean
        return

    def _reply(self, status: int, payload: Any) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _drop(self) -> None:
        """Answer nothing and close: an unreadable upstream, not a verdict."""
        self.close_connection = True
        self.connection.close()

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        self.state.record(f"POST {path}")
        if path == "/api/v1/auth/login":
            return self._reply(200, {"access_token": "ab-session"})
        if path == "/api/v1/rss/subscribe":
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                payload = {}
            url = (payload.get("rss") or {}).get("url")
            with self.state._lock:
                self.state.subscribe_bodies.append(payload)
                if isinstance(url, str):
                    self.state.rss_url = url
            if self.state.drop_write:
                return self._drop()
            return self._reply(200, SOURCE_DERIVED_SUBSCRIBE_ENVELOPE)
        return self._reply(404, {"detail": "not found"})

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        self.state.record(f"GET {path}")
        if path == "/api/v1/status":
            return self._reply(200, {"version": self.state.version})
        if path in ("/api/v1/bangumi/get/all", "/api/v1/rss"):
            with self.state._lock:
                self.state.list_requests += 1
            if self.state.mode == "drop_list":
                return self._drop()
            if self.state.mode == "auth_fail_list":
                return self._reply(401, {"detail": "unauthorized"})
            rows = _subscriptions(self.state) if path.endswith("get/all") else _rss_items(self.state)
            return self._reply(200, rows)
        return self._reply(404, {"detail": "not found"})


class LocalAb318:
    """A localhost-only Auto Bangumi 3.1.18 stand-in (password + bare arrays)."""

    def __init__(self) -> None:
        self.state = _AbState()
        handler = type("_BoundHandler", (_Handler,), {"state": self.state})
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture()
def ab() -> Any:
    server = LocalAb318()
    try:
        yield server
    finally:
        server.close()


def _seed(tmp_path: Path, ab: LocalAb318) -> tuple[dict[str, Any], Any]:
    """One saved connection generation pointing at the localhost stand-in."""
    saved = AutoBangumiConfigRepository(tmp_path / "config").save(
        build_stored_autobangumi_config({
            "auth_mode": "password", "base_url": ab.base_url,
            "username": "operator", "password": "secret-password",
        }),
        expected_configuration_revision=0,
    )
    request = _accepted_request(tmp_path)
    config = load_storage_config(tmp_path / "storage")
    handoff = ensure_confirmed_request_tracking(
        config=config, request=request, origin=TRACKING_ORIGIN_SAVE_CONFIRM,
        now="2026-10-11T00:00:00+00:00",
    )
    assert handoff.tracking_id is not None
    record = load_tracking_record(config, handoff.tracking_id)
    body = {
        "expected_revision": record.revision,
        "storage_dir": "storage",
        "confirm": True,
        "idempotency_key": "local-ab-key-1",
        "connection_ref": str(saved.connection_ref),
        "configuration_revision": saved.configuration_revision,
    }
    return body, record


def _cfg(tmp_path: Path) -> Any:
    return load_storage_config(tmp_path / "storage")


def test_bare_array_readback_confirms_and_persists_success(
    tmp_path: Path, client: FlaskClient, ab: LocalAb318
) -> None:
    """Requirement 1/2/3: real list response, exact RSS, persisted success."""
    body, record = _seed(tmp_path, ab)

    response = client.post(SUBMIT.format(tracking_id=record.tracking_id), json=body)

    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["outcome"] == TRACKING_STATUS_ACTIVE
    stored = load_tracking_record(_cfg(tmp_path), record.tracking_id)
    assert stored.status == TRACKING_STATUS_ACTIVE
    assert stored.external_mapping is not None
    assert stored.external_mapping["subscription_id"] == "42"
    assert stored.external_mapping["connection_ref"] == body["connection_ref"]
    assert load_tracking_operation(_cfg(tmp_path), stored.current_operation_id).state == "SUCCEEDED"
    # Issue #216: the real 3.1.18 write envelope is a clean success, not a
    # write whose body had to be downgraded to the read-back warning.
    assert any(
        str(event.get("safe_message") or "") == SUBMIT_SUCCEEDED_MESSAGE
        for event in stored.audit_events
    ), stored.audit_events
    # One write, and the exact RSS identity was the only evidence used.
    subscribe_calls, list_requests = ab.state.snapshot()
    assert subscribe_calls == 1
    assert list_requests >= 2, ab.state.requests
    assert "secret-password" not in response.get_data(as_text=True)


def test_unknown_write_outcome_but_exact_readback_confirms_once(
    tmp_path: Path, client: FlaskClient, ab: LocalAb318
) -> None:
    """Requirement 4: an unreadable write response still confirms without resubmitting."""
    ab.state.drop_write = True
    body, record = _seed(tmp_path, ab)

    response = client.post(SUBMIT.format(tracking_id=record.tracking_id), json=body)

    result = response.get_json()["result"]
    assert result["outcome"] == TRACKING_STATUS_ACTIVE
    stored = load_tracking_record(_cfg(tmp_path), record.tracking_id)
    assert stored.status == TRACKING_STATUS_ACTIVE
    assert stored.external_mapping["subscription_id"] == "42"
    subscribe_calls, _ = ab.state.snapshot()
    assert subscribe_calls == 1, "the unknown write must never be repeated"
    # The unconfirmed body is recorded as a resource-handling warning, not hidden.
    assert any("写响应未确认" in str(e.get("safe_message", "")) for e in stored.audit_events)


def test_first_miss_stays_pending_then_recheck_confirms_without_new_write(
    tmp_path: Path, client: FlaskClient, ab: LocalAb318
) -> None:
    """Requirement 5/6: one miss is not proof; a read-only recheck converges."""
    ab.state.mode = "empty"
    body, record = _seed(tmp_path, ab)

    first = client.post(SUBMIT.format(tracking_id=record.tracking_id), json=body).get_json()["result"]
    assert first["outcome"] == TRACKING_STATUS_VERIFYING_EXTERNAL
    assert first["verification_reason"] == "NOT_FOUND"
    assert first["failure_category"] == "OUTCOME_UNKNOWN"
    pending = load_tracking_record(_cfg(tmp_path), record.tracking_id)
    assert pending.status == TRACKING_STATUS_VERIFYING_EXTERNAL
    assert pending.external_mapping is None
    writes_after_submit, _ = ab.state.snapshot()
    assert writes_after_submit == 1

    # The subscription becomes visible; only a read-only check may converge it.
    ab.state.mode = "match"
    check = client.post(CHECK.format(tracking_id=record.tracking_id), json={
        "expected_revision": pending.revision, "storage_dir": "storage",
    })
    assert check.status_code == 200
    checked = check.get_json()["result"]
    assert checked["outcome"] == TRACKING_STATUS_ACTIVE
    assert checked["verification_reason"] is None
    confirmed = load_tracking_record(_cfg(tmp_path), record.tracking_id)
    assert confirmed.status == TRACKING_STATUS_ACTIVE
    assert confirmed.external_mapping["subscription_id"] == "42"
    writes_after_check, _ = ab.state.snapshot()
    assert writes_after_check == 1, "the check must never create a subscription"


@pytest.mark.parametrize(
    ("mode", "reason"),
    [("auth_fail_list", "AUTHENTICATION"), ("drop_list", "UNREADABLE")],
)
def test_query_failure_keeps_pending_with_a_proven_reason_then_recovers(
    tmp_path: Path, client: FlaskClient, ab: LocalAb318, mode: str, reason: str
) -> None:
    """Requirement 5/6: a failed read is not a verdict, and it is explained."""
    ab.state.mode = mode
    body, record = _seed(tmp_path, ab)

    first = client.post(SUBMIT.format(tracking_id=record.tracking_id), json=body).get_json()["result"]
    assert first["outcome"] == TRACKING_STATUS_VERIFYING_EXTERNAL
    assert first["verification_reason"] == reason
    pending = load_tracking_record(_cfg(tmp_path), record.tracking_id)
    assert pending.status == TRACKING_STATUS_VERIFYING_EXTERNAL
    assert pending.external_mapping is None

    ab.state.mode = "match"
    checked = client.post(CHECK.format(tracking_id=record.tracking_id), json={
        "expected_revision": pending.revision, "storage_dir": "storage",
    }).get_json()["result"]
    assert checked["outcome"] == TRACKING_STATUS_ACTIVE
    assert load_tracking_record(_cfg(tmp_path), record.tracking_id).status == TRACKING_STATUS_ACTIVE
    subscribe_calls, _ = ab.state.snapshot()
    assert subscribe_calls == 1


def test_replay_and_stale_revision_never_create_a_second_subscription(
    tmp_path: Path, client: FlaskClient, ab: LocalAb318
) -> None:
    """Requirement 8: idempotency, state and revision protections stay intact."""
    body, record = _seed(tmp_path, ab)

    first = client.post(SUBMIT.format(tracking_id=record.tracking_id), json=body).get_json()["result"]
    assert first["outcome"] == TRACKING_STATUS_ACTIVE
    subscribe_calls, _ = ab.state.snapshot()
    assert subscribe_calls == 1

    # Same key, same binding: the terminal outcome is replayed, never re-written.
    replay = client.post(SUBMIT.format(tracking_id=record.tracking_id), json=body)
    assert replay.status_code == 200
    assert replay.get_json()["result"]["outcome"] == TRACKING_STATUS_ACTIVE
    assert ab.state.snapshot()[0] == 1

    # A new key against an already-active record is a state conflict (no write).
    fresh = {**body, "idempotency_key": "local-ab-key-2"}
    conflict = client.post(SUBMIT.format(tracking_id=record.tracking_id), json=fresh)
    assert conflict.status_code == 409
    assert conflict.get_json()["error_type"] == "tracking_state_conflict"
    assert ab.state.snapshot()[0] == 1

    # A check on a settled record is refused before it can read anything new.
    settled = load_tracking_record(_cfg(tmp_path), record.tracking_id)
    stale = client.post(CHECK.format(tracking_id=record.tracking_id), json={
        "expected_revision": settled.revision + 5, "storage_dir": "storage",
    })
    assert stale.status_code == 409
    assert stale.get_json()["error_type"] == "tracking_revision_conflict"
