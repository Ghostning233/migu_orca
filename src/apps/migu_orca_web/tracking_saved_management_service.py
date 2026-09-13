"""Management orchestration bound to a server-owned AB configuration."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from ab_engine.controllers.ab_http_client import UrlopenAutoBangumiHttpTransport
from ab_engine.controllers.ab_management_client import create_legacy_31_management_client
from apps.migu_orca_web.schemas import SavedTrackingManagementInput
from apps.migu_orca_web.services import _storage_dir
from apps.migu_orca_web.tracking_management_service import ManagementWriter, run_tracking_management
from storage_engine.controllers.autobangumi_config_repository import AutoBangumiConfigRepository
from storage_engine.controllers.storage_config import load_storage_config


def run_saved_tracking_management(
    payload: SavedTrackingManagementInput,
    *,
    config_root: Path | str | None = None,
    write: ManagementWriter | None = None,
    readback: Callable | None = None,
) -> dict[str, object]:
    """Hold the immutable config lease across read, write, and readback."""
    ref = UUID(payload.connection_ref)
    repository = AutoBangumiConfigRepository(config_root)
    with repository.acquire_lease(connection_ref=ref, configuration_revision=payload.configuration_revision) as lease:
        assert lease.record.config is not None
        client = create_legacy_31_management_client(
            lease.record.config.to_runtime_config(), transport=UrlopenAutoBangumiHttpTransport()
        )
        if write is None:
            # Imported lazily: routes_tracking already depends on the core
            # coordinator, while the adapter closure is pure request wiring.
            from apps.migu_orca_web.routes_tracking import _management_writer
            write = _management_writer(client, payload.operation)
        config = load_storage_config(_storage_dir(payload.storage_dir))
        return run_tracking_management(
            config,
            tracking_id=payload.tracking_id.strip(), expected_revision=payload.expected_revision,
            idempotency_key=payload.idempotency_key.strip(), confirm=payload.confirm,
            operation=payload.operation, target_scope=payload.target_scope,
            management_client=client, patch=payload.patch, enabled=payload.enabled,
            write=write, readback=readback,
        )


__all__ = ["run_saved_tracking_management"]
