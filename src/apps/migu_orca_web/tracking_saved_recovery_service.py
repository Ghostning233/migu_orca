"""Recovery through a server-owned Auto Bangumi connection."""
from __future__ import annotations

from pathlib import Path

from ab_engine.controllers.ab_http_client import UrlopenAutoBangumiHttpTransport
from ab_engine.controllers.ab_management_client import create_legacy_31_management_client
from apps.migu_orca_web.schemas import SavedTrackingRecoveryInput
from apps.migu_orca_web.services import _storage_dir
from apps.migu_orca_web.tracking_recovery_service import run_tracking_recover
from shared.errors import Stage1Error
from storage_engine.controllers.autobangumi_config_repository import AutoBangumiConfigRepository
from storage_engine.controllers.operation_repository import load_tracking_operation
from storage_engine.controllers.storage_config import load_storage_config
from storage_engine.controllers.tracking_repository import load_tracking_record


def run_saved_tracking_recovery(
    payload: SavedTrackingRecoveryInput,
    *,
    config_root: Path | str | None = None,
    management_client: object | None = None,
) -> dict[str, object]:
    """Keep VERIFY_EXTERNAL bound to the original operation and saved generation."""
    config = load_storage_config(_storage_dir(payload.storage_dir))
    if payload.action != "VERIFY_EXTERNAL":
        return run_tracking_recover(
            config, tracking_id=payload.tracking_id, expected_revision=payload.expected_revision,
            action=payload.action, confirm=payload.confirm,
        )

    record = load_tracking_record(config, payload.tracking_id)
    operation = (
        load_tracking_operation(config, record.current_operation_id)
        if record.current_operation_id else None
    )
    if operation is None or operation.connection_ref != str(payload.connection_ref):
        raise Stage1Error(
            "tracking_connection_mismatch", "历史操作未绑定当前连接，不能进行外部核验",
            "tracking_recover",
        )
    repository = AutoBangumiConfigRepository(config_root)
    with repository.acquire_lease(
        connection_ref=payload.connection_ref,
        configuration_revision=payload.configuration_revision,
    ) as lease:
        assert lease.record.config is not None
        client = management_client or create_legacy_31_management_client(
            lease.record.config.to_runtime_config(), transport=UrlopenAutoBangumiHttpTransport()
        )
        return run_tracking_recover(
            config, tracking_id=payload.tracking_id, expected_revision=payload.expected_revision,
            action=payload.action, confirm=payload.confirm, management_client=client,
        )


__all__ = ["run_saved_tracking_recovery"]
