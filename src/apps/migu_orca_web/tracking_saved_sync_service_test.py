from pathlib import Path

import pytest
from pydantic import ValidationError

from ab_engine.models.management import AutoBangumiCapabilities, ExternalSubscription
from apps.migu_orca_web.schemas import SavedTrackingSyncInput
from apps.migu_orca_web.tracking_saved_sync_service import run_saved_tracking_sync
from storage_engine.controllers.autobangumi_config_repository import (
    AutoBangumiConfigRepository,
    build_stored_autobangumi_config,
)


class _Client:
    def read_snapshot(self):
        return (
            AutoBangumiCapabilities(
                probe_status="VERIFIED", version="3.1.18", adapter="legacy_3_1",
                subscription_list="SUPPORTED", subscription_detail="SUPPORTED",
                rss_list="SUPPORTED", external_verify="SUPPORTED",
            ),
            [ExternalSubscription("sub-1", "Show", 1, "Group")],
            [],
        )


def test_saved_sync_binds_mapping_to_requested_connection(monkeypatch, tmp_path: Path) -> None:
    config_root = tmp_path / "private"
    repo = AutoBangumiConfigRepository(config_root)
    record = repo.save(
        build_stored_autobangumi_config({
            "auth_mode": "password", "base_url": "http://ab.test",
            "username": "u", "password": "p",
        }), expected_configuration_revision=0,
    )
    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_saved_sync_service.create_legacy_31_management_client",
        lambda *_args, **_kwargs: _Client(),
    )
    monkeypatch.setattr("apps.migu_orca_web.services._WEB_STORAGE_ROOT", tmp_path / "business")
    result = run_saved_tracking_sync(
        SavedTrackingSyncInput(
            connection_ref=str(record.connection_ref),
            configuration_revision=record.configuration_revision,
            confirm=True,
            storage_dir=None,
        ),
        config_root=config_root,
    )
    assert result.summary.created == 1
    from storage_engine.controllers.storage_config import load_storage_config
    from storage_engine.controllers.tracking_repository import list_tracking_records
    mapping = list_tracking_records(load_storage_config(tmp_path / "business")).records[0].external_mapping
    assert mapping["connection_ref"] == str(record.connection_ref)
    assert mapping["schema_version"] == 2


def test_saved_sync_rejects_stale_generation() -> None:
    with pytest.raises(ValidationError):
        SavedTrackingSyncInput(
            connection_ref="11111111-1111-4111-8111-111111111111",
            configuration_revision=True,
            confirm=True,
        )
