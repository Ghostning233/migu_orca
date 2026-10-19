from __future__ import annotations

"""Issue #92 + #224: the plan-delete external leg for a retired record.

Issue #218 exception (a) lets "删除追番方案" remove the controlled external
subscription when the user ticks the box.  A4 retires ``EXTERNAL_ONLY`` from the
**public** management projection, so these tests pin that the internal plan-delete
leg still executes ``DELETE_EXTERNAL`` — otherwise the record could be deleted
locally while its Auto Bangumi object becomes an orphan this product can never
clean up.
"""

from pathlib import Path
from typing import Any

import apps.migu_orca_web.services as web_services
import apps.migu_orca_web.tracking_plan_delete_service as plan_delete
import apps.migu_orca_web.tracking_saved_management_service as saved_management
from ab_engine.models.management import AutoBangumiCapabilities, ExternalSubscription
from apps.migu_orca_web.schemas import SavedTrackingPlanDeleteInput
from storage_engine.controllers.autobangumi_config_repository import (
    AutoBangumiConfigRepository,
    build_stored_autobangumi_config,
)
from storage_engine.controllers.storage_config import StorageConfig, load_storage_config
from storage_engine.controllers.tracking_repository import (
    ensure_tracking_record,
    list_tracking_records,
)
from tracking_engine.models.tracking import (
    TRACKING_STATUS_EXTERNAL_ONLY,
    TrackingRecord,
    create_external_tracking_record,
)

REF = "11111111-1111-4111-8111-111111111111"


class _FakeManagedAb:
    """Offline 3.1.18 management surface; deleting removes it from the snapshot."""

    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.subscriptions = [ExternalSubscription("sub-1", "Old", 1, "Group")]
        self.capabilities = AutoBangumiCapabilities(
            probe_status="VERIFIED", version="3.1.18", adapter="legacy_3_1",
            subscription_list="SUPPORTED", subscription_detail="SUPPORTED",
            subscription_modify="SUPPORTED", subscription_enable="SUPPORTED",
            subscription_disable="SUPPORTED", subscription_delete="SUPPORTED",
            rss_list="SUPPORTED", rss_modify="SUPPORTED", rss_enable="SUPPORTED",
            rss_disable="SUPPORTED", rss_delete="SUPPORTED", rss_refresh="SUPPORTED",
        )

    def read_snapshot(self, *, deadline: float | None = None) -> Any:
        return self.capabilities, list(self.subscriptions), []

    def delete_subscription(self, ident: str) -> dict[str, int]:
        self.deleted.append(ident)
        self.subscriptions = [item for item in self.subscriptions if item.external_id != ident]
        return {"status_code": 200}


def _seed(
    tmp_path: Path, *, with_connection_ref: bool = False
) -> tuple[StorageConfig, Any, TrackingRecord]:
    """One historical ``EXTERNAL_ONLY`` record that still owns a mapping."""
    saved = AutoBangumiConfigRepository(tmp_path / "config").save(
        build_stored_autobangumi_config({
            "auth_mode": "password", "base_url": "http://ab.invalid",
            "username": "operator", "password": "secret-password",
        }),
        expected_configuration_revision=0,
    )
    config = load_storage_config(tmp_path / "storage")
    record, _created = ensure_tracking_record(
        config,
        create_external_tracking_record(
            adapter="legacy_3_1",
            object_kind="subscription",
            external_id="sub-1",
            subscription_id="sub-1",
            title="History",
            season=1,
            connection_ref=saved.connection_ref if with_connection_ref else None,
        ),
    )
    assert record.status == TRACKING_STATUS_EXTERNAL_ONLY
    assert record.external_mapping is not None
    return config, saved, record


def _payload(saved: Any, record: TrackingRecord, key: str = "delete-retired-1") -> SavedTrackingPlanDeleteInput:
    return SavedTrackingPlanDeleteInput(
        tracking_id=record.tracking_id,
        confirm=True,
        delete_external=True,
        idempotency_key=key,
        connection_ref=str(saved.connection_ref),
        configuration_revision=saved.configuration_revision,
        # The saved-management chain resolves this profile under the Web root,
        # which the test points at tmp_path.
        storage_dir="storage",
    )


def test_retired_record_keeps_the_controlled_external_delete_leg(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """The internal leg asks the write path for DELETE_EXTERNAL explicitly."""
    config, saved, record = _seed(tmp_path)
    captured: dict[str, Any] = {}

    def fake_management(payload: Any, **kwargs: Any) -> dict[str, Any]:
        captured["payload"] = payload
        captured.update(kwargs)
        return {"management_status": "SUCCEEDED"}

    monkeypatch.setattr(plan_delete, "run_saved_tracking_management", fake_management)

    result = plan_delete.run_saved_tracking_plan_delete(
        config, payload=_payload(saved, record)
    )

    assert captured["payload"].operation == "DELETE_EXTERNAL"
    assert captured["internal_plan_delete"] is True
    assert result == {
        "tracking_id": record.tracking_id,
        "outcome": "DELETED",
        "external_deleted": True,
    }
    assert list_tracking_records(config).records == []


def test_plan_delete_end_to_end_removes_the_external_object_of_a_retired_record(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """The real saved-management chain removes the AB object, then the local plan."""
    config, saved, record = _seed(tmp_path, with_connection_ref=True)
    client = _FakeManagedAb()
    monkeypatch.setattr(web_services, "_WEB_STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(
        saved_management,
        "AutoBangumiConfigRepository",
        lambda _root: AutoBangumiConfigRepository(tmp_path / "config"),
    )
    monkeypatch.setattr(saved_management, "create_management_client", lambda _config: client)

    result = plan_delete.run_saved_tracking_plan_delete(
        config, payload=_payload(saved, record, key="delete-retired-e2e-1")
    )

    assert result == {
        "tracking_id": record.tracking_id,
        "outcome": "DELETED",
        "external_deleted": True,
    }
    # Issue #218 exception (a): the controlled external object is removed first.
    assert client.deleted == ["sub-1"]
    assert client.subscriptions == []
    assert list_tracking_records(config).records == []
