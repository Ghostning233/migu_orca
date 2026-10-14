from __future__ import annotations

from pathlib import Path

import pytest

from apps.migu_orca_web.tracking_handoff import (
    TRACKING_HANDOFF_RETRY_MESSAGE,
    TrackingHandoff,
    ensure_confirmed_request_tracking,
    unavailable_tracking_handoff,
)
from plan_engine.controllers.data_sources import StaticFixtureDataSource
from plan_engine.controllers.plan_generation import build_plan
from request_engine.controllers.request_controller import accept_request
from shared.errors import Stage1Error
from shared.models import EntryRequest
from storage_engine.controllers.storage_config import (
    StorageConfig,
    load_storage_config,
)
from storage_engine.controllers.tracking_repository import (
    list_tracking_records,
    load_tracking_record,
)
from tracking_engine.models.tracking import (
    TRACKING_ORIGIN_LEGACY_ACCEPT,
    TRACKING_ORIGIN_SAVE_CONFIRM,
    TRACKING_STATUS_PENDING_SUBMIT,
    tracking_id_for_request,
)

TITLE = "芙莉莲"


def _config(tmp_path: Path) -> StorageConfig:
    return load_storage_config(tmp_path / "storage")


def _accepted_request(request_id: str = "request-1") -> dict[str, object]:
    request = build_plan(EntryRequest(raw_title=TITLE), data_source=StaticFixtureDataSource())["request"]
    return accept_request({**request, "request_id": request_id})


def _storage_config_tracking_dir(config: StorageConfig) -> Path:
    return config.tracking_dir


def test_ensure_creates_fresh_record_with_origin_and_pending_submit(
    tmp_path: Path,
) -> None:
    """US-222: a fresh ACCEPTED Request converges to one SAVE_CONFIRM record."""
    config = _config(tmp_path)
    request = _accepted_request("request-1")

    handoff = ensure_confirmed_request_tracking(
        config=config,
        request=request,
        origin=TRACKING_ORIGIN_SAVE_CONFIRM,
    )

    assert handoff == TrackingHandoff(
        tracking_id=tracking_id_for_request("request-1"),
        tracking_status=TRACKING_STATUS_PENDING_SUBMIT,
        tracking_ready=True,
        safe_message=None,
    )
    records = list_tracking_records(config).records
    assert len(records) == 1
    record = records[0]
    assert record.tracking_id == tracking_id_for_request("request-1")
    assert record.request_id == "request-1"
    assert record.status == TRACKING_STATUS_PENDING_SUBMIT
    assert record.origin == TRACKING_ORIGIN_SAVE_CONFIRM
    assert record.revision == 1
    assert len(record.audit_events) == 1
    assert record.audit_events[0]["action"] == "TRACKING_CREATED"


def test_ensure_legacy_accept_origin_is_preserved(tmp_path: Path) -> None:
    """US-222: the single-plan accept entry uses the LEGACY_ACCEPT origin."""
    config = _config(tmp_path)
    request = _accepted_request("request-2")

    handoff = ensure_confirmed_request_tracking(
        config=config,
        request=request,
        origin=TRACKING_ORIGIN_LEGACY_ACCEPT,
    )

    assert handoff.tracking_ready is True
    record = load_tracking_record(config, handoff.tracking_id)
    assert record.origin == TRACKING_ORIGIN_LEGACY_ACCEPT


def test_ensure_existing_record_returns_unchanged(tmp_path: Path) -> None:
    """US-222: re-running ensure never adds records/audits or bumps revision."""
    config = _config(tmp_path)
    request = _accepted_request("request-3")

    first = ensure_confirmed_request_tracking(
        config=config,
        request=request,
        origin=TRACKING_ORIGIN_SAVE_CONFIRM,
    )
    second = ensure_confirmed_request_tracking(
        config=config,
        request=request,
        origin=TRACKING_ORIGIN_SAVE_CONFIRM,
    )

    assert first == second
    records = list_tracking_records(config).records
    assert len(records) == 1
    assert records[0].revision == 1
    assert len(records[0].audit_events) == 1


def test_ensure_write_failure_returns_not_ready_handoff(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """US-222: a tracking write failure never fakes a state nor raises."""
    import apps.migu_orca_web.tracking_handoff as tracking_handoff

    config = _config(tmp_path)
    request = _accepted_request("request-4")

    def failing_ensure(_config: StorageConfig, _record: object) -> tuple[object, bool]:
        raise Stage1Error(
            "storage_error", "模拟追番记录写入失败", "ensure_tracking_record", {}
        )

    monkeypatch.setattr(tracking_handoff, "ensure_tracking_record", failing_ensure)

    handoff = ensure_confirmed_request_tracking(
        config=config,
        request=request,
        origin=TRACKING_ORIGIN_SAVE_CONFIRM,
    )

    assert handoff.tracking_ready is False
    assert handoff.tracking_status is None
    assert handoff.safe_message == TRACKING_HANDOFF_RETRY_MESSAGE
    assert handoff.tracking_id == tracking_id_for_request("request-4")
    assert list_tracking_records(config).records == []


def test_unavailable_handoff_is_always_deterministic(tmp_path: Path) -> None:
    """US-222: the not-ready handoff still hands a stable deterministic id."""
    handoff = unavailable_tracking_handoff("request-5")

    assert handoff.tracking_id == tracking_id_for_request("request-5")
    assert handoff.tracking_status is None
    assert handoff.tracking_ready is False
    assert handoff.safe_message == TRACKING_HANDOFF_RETRY_MESSAGE


def test_ensure_rejects_non_accepted_request(tmp_path: Path) -> None:
    """US-222: only an ACCEPTED Request may enter the tracking handoff."""
    config = _config(tmp_path)
    pending = build_plan(EntryRequest(raw_title=TITLE), data_source=StaticFixtureDataSource())["request"]
    pending["request_id"] = "request-pending"

    with pytest.raises(ValueError):
        ensure_confirmed_request_tracking(
            config=config,
            request=pending,
            origin=TRACKING_ORIGIN_SAVE_CONFIRM,
        )


def test_ensure_rejects_missing_request_id(tmp_path: Path) -> None:
    """US-222: a Request without a public id cannot be tracked."""
    config = _config(tmp_path)
    request = _accepted_request("request-6")
    request.pop("request_id", None)

    with pytest.raises(ValueError):
        ensure_confirmed_request_tracking(
            config=config,
            request=request,
            origin=TRACKING_ORIGIN_SAVE_CONFIRM,
        )
