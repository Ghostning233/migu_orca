"""Management orchestration bound to a server-owned AB configuration."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ab_engine.controllers.ab_management_factory import create_management_client
from apps.migu_orca_web.schemas import SavedTrackingManagementInput
from apps.migu_orca_web.services import _storage_dir
from apps.migu_orca_web.tracking_management_service import (
    ManagementWriter,
    _load_operation_if_present,
    management_writer,
    run_tracking_management,
)
from storage_engine.controllers.autobangumi_config_repository import AutoBangumiConfigRepository
from storage_engine.controllers.storage_config import load_storage_config
from tracking_engine.models.operation import TRACKING_OPERATION_TERMINAL_STATES


def run_saved_tracking_management(
    payload: SavedTrackingManagementInput,
    *,
    config_root: Path | str | None = None,
    write: ManagementWriter | None = None,
    readback: Callable | None = None,
) -> dict[str, object]:
    """Hold the immutable config lease across read, write, and readback."""
    # Pydantic has already validated and canonicalized this UUID.  Do not
    # construct UUID(UUID), which raises AttributeError on valid payloads.
    ref = payload.connection_ref
    config = load_storage_config(_storage_dir(payload.storage_dir))
    existing = _load_operation_if_present(config, payload.idempotency_key.strip())
    if existing is not None and existing.state in TRACKING_OPERATION_TERMINAL_STATES:
        # The coordinator owns all binding checks and paired-result recovery.
        # A terminal replay needs no current secret and cannot reach its IO gate.
        return run_tracking_management(
            config, tracking_id=payload.tracking_id.strip(),
            expected_revision=payload.expected_revision,
            idempotency_key=payload.idempotency_key.strip(), confirm=payload.confirm,
            operation=payload.operation, target_scope=payload.target_scope,
            patch=payload.patch, enabled=payload.enabled, connection_ref=str(ref),
            local_plan=_local_plan(payload),
        )
    repository = AutoBangumiConfigRepository(config_root)
    with repository.acquire_lease(connection_ref=ref, configuration_revision=payload.configuration_revision) as lease:
        assert lease.record.config is not None
        client = create_management_client(lease.record.config.to_runtime_config())
        if write is None:
            write = management_writer(client, payload.operation)
        return run_tracking_management(
            config,
            tracking_id=payload.tracking_id.strip(), expected_revision=payload.expected_revision,
            idempotency_key=payload.idempotency_key.strip(), confirm=payload.confirm,
            operation=payload.operation, target_scope=payload.target_scope,
            management_client=client, patch=payload.patch, enabled=payload.enabled,
            write=write, readback=readback, connection_ref=str(ref),
            local_plan=_local_plan(payload),
        )


def _local_plan(payload: SavedTrackingManagementInput) -> dict[str, object] | None:
    """Validated local plan values, or ``None`` when this request raises none."""
    plan = payload.local_plan
    if plan is None:
        return None
    return plan.model_dump(exclude_none=True)


__all__ = ["run_saved_tracking_management"]
