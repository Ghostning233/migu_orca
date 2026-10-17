from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from ab_engine.controllers.ab_config import AutoBangumiConfig
from ab_engine.controllers.ab_http_client import AutoBangumiWriteResponse
from ab_engine.controllers.ab_management_client import create_legacy_31_management_client
from apps.migu_orca_web.routes_tracking import _management_writer
from apps.migu_orca_web.tracking_management_service import run_tracking_management
from shared.errors import Stage1Error
from storage_engine.controllers.storage_config import load_storage_config
from storage_engine.controllers.tracking_repository import ensure_tracking_record, load_tracking_record
from tracking_engine.models.tracking import create_external_tracking_record

#: The verified 3.1.18 write envelope (issue #216): two message strings, no
#: ``status`` field, and the exact 200 carries the accepted-action result.  The
#: wording is the real recording documented in
#: ``tests/api_contract/ab_write_envelopes.py``.
WRITE_ACCEPTED = AutoBangumiWriteResponse(
    200, {"msg_en": "Delete RSS successfully.", "msg_zh": "删除 RSS 成功。"}
)


class _OfflineTransport:
    """Exact adapter transport script; it never opens a socket."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, Mapping[str, Any] | None]] = []

    def request_json(
        self, method: str, endpoint: str, headers: Mapping[str, str],
        payload: Mapping[str, Any] | None = None, *, timeout: float,
    ) -> dict[str, Any]:
        self.calls.append((method, endpoint, payload))
        return self.responses.pop(0)

    def write_json(
        self, method: str, endpoint: str, headers: Mapping[str, str],
        payload: Mapping[str, Any] | None = None, *, timeout: float,
        step: str = "create_ab_subscription",
    ) -> AutoBangumiWriteResponse:
        self.calls.append((method, endpoint, payload))
        return self.responses.pop(0)


def _subscription(title: str) -> dict[str, Any]:
    return {
        "id": "sub-1", "official_title": title, "year": "2026", "title_raw": "raw",
        "season": 1, "season_raw": "S1", "group_name": "Group", "dpi": "1080p",
        "source": "WEB", "subtitle": "简", "eps_collect": False, "offset": 0,
        "filter": "(?!)", "rss_link": "https://rss.invalid/feed", "poster_link": None,
        "added": True, "rule_name": "rule", "save_path": "downloads", "deleted": False,
        "rss_ids": [7],
    }


def _rss() -> dict[str, Any]:
    return {"id": 7, "name": "Feed", "url": "https://rss.invalid/feed", "aggregate": False, "enabled": True}


def test_real_adapter_writer_and_coordinator_complete_modify_readback(tmp_path: Path) -> None:
    """Exercise adapter -> route writer -> coordinator without mocking it."""
    config = load_storage_config(tmp_path / "storage")
    record, _ = ensure_tracking_record(config, create_external_tracking_record(
        adapter="legacy_3_1", object_kind="subscription", external_id="sub-1",
        subscription_id="sub-1", rss_ids=("7",), title="Test", season=1,
    ))
    transport = _OfflineTransport([
        # Initial authoritative snapshot.
        {"access_token": "first"}, {"version": "3.1.18"}, {"data": [_subscription("Test")]},
        {"data": [{"id": 7, "name": "Feed", "url": "https://rss.invalid/feed", "aggregate": False, "enabled": True}]},
        # The write action.
        {"access_token": "write"}, {"version": "3.1.18"}, WRITE_ACCEPTED,
        # Mandatory post-write snapshot.
        {"access_token": "readback"}, {"version": "3.1.18"}, {"data": [_subscription("Changed")]},
        {"data": [{"id": 7, "name": "Feed", "url": "https://rss.invalid/feed", "aggregate": False, "enabled": True}]},
    ])
    client = create_legacy_31_management_client(AutoBangumiConfig(
        base_url="https://ab.invalid", auth_mode="password", username="user", password="secret", fallback_enabled=False,
    ), transport=transport)

    result = run_tracking_management(
        config, tracking_id=record.tracking_id, expected_revision=record.revision,
        idempotency_key="adapter-writer-service", confirm=True, operation="MODIFY",
        target_scope="SUBSCRIPTION", management_client=client,
        patch={"title": "Changed"}, write=_management_writer(client, "MODIFY"),
    )

    assert result["management_status"] == "SUCCEEDED"
    assert load_tracking_record(config, record.tracking_id).plan_summary["title"] == "Changed"
    patch_calls = [call for call in transport.calls if call[0] == "PATCH"]
    assert patch_calls[0][2]["official_title"] == "Changed"
    assert patch_calls[0][2]["filter"] == "(?!)"
    assert transport.responses == []


def test_real_adapter_writer_and_coordinator_complete_rss_modify_readback(tmp_path: Path) -> None:
    config = load_storage_config(tmp_path / "storage")
    record, _ = ensure_tracking_record(config, create_external_tracking_record(
        adapter="legacy_3_1", object_kind="subscription", external_id="sub-1",
        subscription_id="sub-1", rss_ids=("7",), title="Test", season=1,
    ))
    transport = _OfflineTransport([
        {"access_token": "first"}, {"version": "3.1.18"}, {"data": [_subscription("Test")]},
        {"data": [{"id": 7, "name": "Feed", "url": "https://rss.invalid/feed", "aggregate": False, "parser": "rss", "enabled": True}]},
        {"access_token": "write"}, {"version": "3.1.18"}, WRITE_ACCEPTED,
        {"access_token": "readback"}, {"version": "3.1.18"}, {"data": [_subscription("Test")]},
        {"data": [{"id": 7, "name": "Changed feed", "url": "https://rss.invalid/feed", "aggregate": False, "parser": "rss", "enabled": True}]},
    ])
    client = create_legacy_31_management_client(AutoBangumiConfig(
        base_url="https://ab.invalid", auth_mode="password", username="user", password="secret", fallback_enabled=False,
    ), transport=transport)

    result = run_tracking_management(
        config, tracking_id=record.tracking_id, expected_revision=record.revision,
        idempotency_key="adapter-writer-rss", confirm=True, operation="MODIFY",
        target_scope="ASSOCIATED_RSS", management_client=client,
        patch={"name": "Changed feed"}, write=_management_writer(client, "MODIFY"),
    )

    assert result["management_status"] == "SUCCEEDED"
    patch_calls = [call for call in transport.calls if call[0] == "PATCH"]
    assert patch_calls[0][1].endswith("/api/v1/rss/update/7")
    assert patch_calls[0][2] == {
        "name": "Changed feed", "url": "https://rss.invalid/feed", "aggregate": False,
        "parser": "rss", "enabled": True,
    }
    assert transport.responses == []


def test_real_delete_readback_requires_list_absence_not_deleted_flag(tmp_path: Path) -> None:
    config = load_storage_config(tmp_path / "storage")
    record, _ = ensure_tracking_record(config, create_external_tracking_record(
        adapter="legacy_3_1", object_kind="subscription", external_id="sub-1",
        subscription_id="sub-1", rss_ids=("7",), title="Test", season=1,
    ))
    disabled = {**_subscription("Test"), "deleted": True}
    transport = _OfflineTransport([
        {"access_token": "first"}, {"version": "3.1.18"}, {"data": [disabled]}, {"data": [_rss()]},
        {"access_token": "write"}, {"version": "3.1.18"}, WRITE_ACCEPTED,
        # The disabled item remains in the actual upstream list.
        {"access_token": "readback"}, {"version": "3.1.18"}, {"data": [disabled]}, {"data": [_rss()]},
    ])
    client = create_legacy_31_management_client(AutoBangumiConfig(
        base_url="https://ab.invalid", auth_mode="password", username="user", password="secret", fallback_enabled=False,
    ), transport=transport)
    result = run_tracking_management(
        config, tracking_id=record.tracking_id, expected_revision=record.revision,
        idempotency_key="delete-presence-readback", confirm=True, operation="DELETE_EXTERNAL",
        target_scope="SUBSCRIPTION", management_client=client, write=_management_writer(client, "DELETE_EXTERNAL"),
    )
    assert result["outcome"] == "DEFINITE_FAILURE"
    assert load_tracking_record(config, record.tracking_id).status != "EXTERNAL_DELETED"
    assert transport.responses == []


@pytest.mark.parametrize(
    ("write_status", "expected_error", "expected_details"),
    [
        (200, None, {"status_code": 200}),
        (
            406, "ab_submit_failed",
            {
                "status_code": 406, "http_status": 406,
                "message_zh": "无法找到 id 999999", "message_en": "Can't find id 999999",
            },
        ),
        (401, "ab_auth_failed", {"status_code": 401}),
    ],
)
def test_real_transport_accepts_a_management_write_only_on_the_exact_status(
    monkeypatch: pytest.MonkeyPatch,
    write_status: int,
    expected_error: str | None,
    expected_details: dict[str, Any],
) -> None:
    """Issue #216 AC2/AC4 through the real transport and JSON decoder.

    The real transport, the real management adapter and the real classification
    run; only the HTTP exchange is replaced, so a body-only judgement (the
    deleted ``else -> 502`` branch) can no longer turn a real 200 envelope into a
    failed management write, nor a 406/401 into anything but its proven class.
    """
    import json

    envelope = {"msg_en": "Delete RSS successfully.", "msg_zh": "删除 RSS 成功。"}

    def exchange(method, endpoint, headers, body, *, timeout, step, inspect_error_body=False, monotonic=None):
        path = urlsplit(endpoint).path
        if path == "/api/v1/auth/login":
            return 200, {}, b'{"access_token": "session-secret"}'
        if path == "/api/v1/status":
            return 200, {}, b'{"version": "3.1.18"}'
        if path == "/api/v1/bangumi/delete/42":
            payload = envelope if write_status == 200 else {
                "msg_en": "Can't find id 999999", "msg_zh": "无法找到 id 999999",
            }
            return write_status, {}, json.dumps(payload).encode("utf-8")
        raise AssertionError(f"unexpected Auto Bangumi path: {path}")

    monkeypatch.setattr("ab_engine.controllers.ab_http_client._exchange", exchange)
    from ab_engine.controllers.ab_http_client import UrlopenAutoBangumiHttpTransport

    client = create_legacy_31_management_client(
        AutoBangumiConfig(
            base_url="https://ab.invalid", auth_mode="password", username="user",
            password="secret", fallback_enabled=False,
        ),
        transport=UrlopenAutoBangumiHttpTransport(),
    )

    if expected_error is None:
        assert client.delete_subscription("42") == expected_details
    else:
        with pytest.raises(Stage1Error) as error:
            client.delete_subscription("42")
        assert error.value.error_type == expected_error
        assert error.value.details == expected_details
        assert "session-secret" not in repr(error.value.as_dict())
