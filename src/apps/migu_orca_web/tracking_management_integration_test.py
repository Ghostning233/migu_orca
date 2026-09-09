from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ab_engine.controllers.ab_config import AutoBangumiConfig
from ab_engine.controllers.ab_management_client import create_legacy_31_management_client
from apps.migu_orca_web.routes_tracking import _management_writer
from apps.migu_orca_web.tracking_management_service import run_tracking_management
from storage_engine.controllers.storage_config import load_storage_config
from storage_engine.controllers.tracking_repository import ensure_tracking_record, load_tracking_record
from tracking_engine.models.tracking import create_external_tracking_record


class _OfflineTransport:
    """Exact adapter transport script; it never opens a socket."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, Mapping[str, Any] | None]] = []

    def request_json(
        self, method: str, endpoint: str, headers: Mapping[str, str],
        payload: Mapping[str, Any] | None = None, *, timeout: float,
    ) -> dict[str, Any]:
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
        {"access_token": "write"}, {"version": "3.1.18"}, {"status": True},
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
        {"access_token": "write"}, {"version": "3.1.18"}, {"status": True},
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
        {"access_token": "write"}, {"version": "3.1.18"}, {"status": True},
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
