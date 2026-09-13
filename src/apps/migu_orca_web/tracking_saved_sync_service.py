"""Tracking synchronisation through a server-owned AB configuration."""
from __future__ import annotations

from pathlib import Path
from uuid import UUID

from ab_engine.controllers.ab_http_client import UrlopenAutoBangumiHttpTransport
from ab_engine.controllers.ab_management_client import create_legacy_31_management_client
from apps.migu_orca_web.schemas import SavedTrackingSyncInput
from apps.migu_orca_web.services import _storage_dir
from apps.migu_orca_web.tracking_sync_service import TrackingSyncResult, run_tracking_sync
from storage_engine.controllers.autobangumi_config_repository import AutoBangumiConfigRepository
from storage_engine.controllers.storage_config import load_storage_config


def run_saved_tracking_sync(
    payload: SavedTrackingSyncInput,
    *,
    config_root: Path | str | None = None,
) -> TrackingSyncResult:
    """Resolve one immutable saved snapshot and keep its lease for the sync."""
    ref = UUID(payload.connection_ref)
    repository = AutoBangumiConfigRepository(config_root)
    with repository.acquire_lease(
        connection_ref=ref,
        configuration_revision=payload.configuration_revision,
    ) as lease:
        assert lease.record.config is not None
        client = create_legacy_31_management_client(
            lease.record.config.to_runtime_config(),
            transport=UrlopenAutoBangumiHttpTransport(),
        )
        config = load_storage_config(_storage_dir(payload.storage_dir))
        return run_tracking_sync(
            config=config,
            management_client=client,
            connection_ref=ref,
        )


__all__ = ["run_saved_tracking_sync"]
