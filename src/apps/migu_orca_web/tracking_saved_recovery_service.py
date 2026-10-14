"""Recovery through a server-owned Auto Bangumi connection."""
from __future__ import annotations

from pathlib import Path

# The module-level seam name stays historical: existing tests inject a fake
# factory under ``create_legacy_31_management_client`` while transport selection
# and the default timeout now live in the AB factory (issue #175).
from ab_engine.controllers.ab_management_factory import (
    create_management_client as create_legacy_31_management_client,
)
from apps.migu_orca_web.schemas import SavedTrackingRecoveryInput
from apps.migu_orca_web.services import _storage_dir
from apps.migu_orca_web.tracking_recovery_service import run_tracking_recover
from shared.errors import Stage1Error
from storage_engine.controllers.autobangumi_config_repository import AutoBangumiConfigRepository
from storage_engine.controllers.operation_repository import load_tracking_operation
from storage_engine.controllers.storage_config import load_storage_config
from storage_engine.controllers.tracking_repository import load_tracking_record
from tracking_engine.controllers.management_target import validate_management_mapping
from tracking_engine.controllers.recover import RECOVERABLE_STATUSES
from tracking_engine.models.operation import (
    TRACKING_OPERATION_KIND_DELETE_EXTERNAL,
    TRACKING_OPERATION_KIND_MODIFY,
    TRACKING_OPERATION_KIND_REFRESH_RSS,
    TRACKING_OPERATION_KIND_SET_ENABLED,
    TRACKING_OPERATION_KIND_SUBMIT,
    TRACKING_OPERATION_STATE_IN_PROGRESS,
)


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
    operation = load_tracking_operation(config, record.current_operation_id) if record.current_operation_id else None
    allowed_kinds = {TRACKING_OPERATION_KIND_SUBMIT, TRACKING_OPERATION_KIND_MODIFY,
                     TRACKING_OPERATION_KIND_SET_ENABLED, TRACKING_OPERATION_KIND_DELETE_EXTERNAL,
                     TRACKING_OPERATION_KIND_REFRESH_RSS}
    allowed_states = {TRACKING_OPERATION_STATE_IN_PROGRESS, "OUTCOME_UNKNOWN", "RECOVERY_REQUIRED"}
    mapping = record.external_mapping if isinstance(record.external_mapping, dict) else {}
    if (operation is None or record.revision != payload.expected_revision
            or record.status not in RECOVERABLE_STATUSES
            or operation.tracking_id != record.tracking_id
            or operation.operation not in allowed_kinds
            or operation.state not in allowed_states
            or operation.connection_ref != str(payload.connection_ref)
            or (operation.operation != TRACKING_OPERATION_KIND_SUBMIT
                and (mapping.get("schema_version") != 2
                     or mapping.get("connection_ref") != str(payload.connection_ref)))):
        raise Stage1Error(
            "tracking_connection_mismatch", "历史操作未绑定当前连接，不能进行外部核验",
            "tracking_recover",
        )
    if operation.operation != TRACKING_OPERATION_KIND_SUBMIT:
        try:
            validate_management_mapping(record, str(payload.connection_ref))
        except Exception as exc:
            raise Stage1Error(
                "tracking_connection_mismatch", "历史操作未绑定当前连接，不能进行外部核验",
                "tracking_recover",
            ) from exc
    repository = AutoBangumiConfigRepository(config_root)
    with repository.acquire_lease(
        connection_ref=payload.connection_ref,
        configuration_revision=payload.configuration_revision,
    ) as lease:
        assert lease.record.config is not None
        client = management_client or create_legacy_31_management_client(
            lease.record.config.to_runtime_config()
        )
        return run_tracking_recover(
            config, tracking_id=payload.tracking_id, expected_revision=payload.expected_revision,
            action=payload.action, confirm=payload.confirm, management_client=client,
            connection_ref=str(payload.connection_ref),
            expected_operation_id=operation.operation_id,
            expected_operation_kind=operation.operation,
            ab_config=lease.record.config.to_runtime_config(),
        )


__all__ = ["run_saved_tracking_recovery"]
