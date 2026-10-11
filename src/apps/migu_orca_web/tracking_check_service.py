"""Server-resolved read-only confirmation of a pending submission (issue #183).

``POST /api/v1/tracking/items/{tracking_id}/check`` answers the only question a
user has about a 结果待确认 persistent submission: *did Auto Bangumi actually
create this subscription?* The check is **read-only** — it never creates,
modifies, deletes or resubmits anything — and it never asks the browser for a
connection: the Auto Bangumi instance is the one the original submit operation
was bound to, resolved from that operation alone.

The actual read is the same bounded, unified confirmation the post-submit
read-back uses (:mod:`apps.migu_orca_web.tracking_external_check` +
``match_subscription_by_exact_rss``), so the two can never disagree. A replaced
saved connection is reported as ``CONNECTION_CHANGED`` instead of rebinding the
old operation to a new instance, and a check that cannot prove the object stays
结果待确认 with the proven reason class.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.migu_orca_web.schemas import TrackingCheckPayload
from apps.migu_orca_web.services import _storage_dir
from apps.migu_orca_web.tracking_external_check import CheckPolicy
from apps.migu_orca_web.tracking_recovery_service import run_tracking_recover
from apps.migu_orca_web.tracking_serializers import tracking_summary_fields
from shared.errors import Stage1Error
from storage_engine.controllers.autobangumi_config_repository import (
    AutoBangumiConfigRepository,
)
from storage_engine.controllers.operation_repository import load_tracking_operation
from storage_engine.controllers.storage_config import load_storage_config
from storage_engine.controllers.tracking_repository import load_tracking_record
from tracking_engine.controllers.recover import (
    RECOVERABLE_STATUSES,
    RECOVERY_ACTION_VERIFY_EXTERNAL,
)
from tracking_engine.controllers.submit import CONFIRM_REASON_CONNECTION_CHANGED
from tracking_engine.models.operation import (
    TRACKING_OPERATION_KIND_SUBMIT,
    TRACKING_OPERATION_STATE_IN_PROGRESS,
    TRACKING_OPERATION_STATE_PREPARED,
)
from tracking_engine.models.tracking import utc_now

_CHECK_FAILED_STEP = "tracking_check"

#: Operation states a pending submission may still be checked from. A PREPARED
#: operation proves the external call never happened, so there is nothing to
#: verify; a terminal operation has already been resolved.
_CHECKABLE_OPERATION_STATES = frozenset(
    {
        TRACKING_OPERATION_STATE_IN_PROGRESS,
        "OUTCOME_UNKNOWN",
        "RECOVERY_REQUIRED",
    }
)


def run_saved_tracking_check(
    payload: TrackingCheckPayload,
    *,
    config_root: Path | str | None = None,
    management_client: object | None = None,
    now: str | None = None,
    read_policy: CheckPolicy | None = None,
) -> dict[str, Any]:
    """Run one bounded read-only check bound to the original submit operation."""
    config = load_storage_config(_storage_dir(payload.storage_dir))
    timestamp = now or utc_now()
    record = load_tracking_record(config, payload.tracking_id)
    operation = (
        load_tracking_operation(config, record.current_operation_id)
        if record.current_operation_id
        else None
    )
    if (
        operation is None
        or operation.tracking_id != record.tracking_id
        or operation.operation != TRACKING_OPERATION_KIND_SUBMIT
        or operation.state not in _CHECKABLE_OPERATION_STATES
        or record.status not in RECOVERABLE_STATUSES
        or operation.state == TRACKING_OPERATION_STATE_PREPARED
    ):
        raise Stage1Error(
            "tracking_state_conflict",
            "当前追番记录没有可核验的待确认提交",
            _CHECK_FAILED_STEP,
            {"field": "status", "current_status": record.status},
        )
    connection_ref = operation.connection_ref
    if not isinstance(connection_ref, str) or not connection_ref:
        return _unresolved_check(
            config,
            record=record,
            expected_revision=payload.expected_revision,
            timestamp=timestamp,
            reason=CONFIRM_REASON_CONNECTION_CHANGED,
        )
    repository = AutoBangumiConfigRepository(config_root)
    try:
        current = repository.load()
    except Stage1Error:
        current = None
    if (
        current is None
        or current.connection_ref is None
        or str(current.connection_ref) != connection_ref
        or current.config is None
    ):
        # Issue #183: a replaced saved connection never rebinds the old
        # operation; the check reports the proven binding change and reads nothing.
        return _unresolved_check(
            config,
            record=record,
            expected_revision=payload.expected_revision,
            timestamp=timestamp,
            reason=CONFIRM_REASON_CONNECTION_CHANGED,
        )
    return run_tracking_recover(
        config,
        tracking_id=payload.tracking_id,
        expected_revision=payload.expected_revision,
        action=RECOVERY_ACTION_VERIFY_EXTERNAL,
        confirm=False,
        now=timestamp,
        ab_config=current.config.to_runtime_config(),
        management_client=management_client,
        connection_ref=connection_ref,
        expected_operation_id=operation.operation_id,
        expected_operation_kind=operation.operation,
        read_policy=read_policy,
    )


def _unresolved_check(
    config: Any,
    *,
    record: Any,
    expected_revision: int,
    timestamp: str,
    reason: str,
) -> dict[str, Any]:
    """Report a check that could not even be attempted, without any write.

    The record keeps its 待确认 status and revision: a binding that changed is
    not new evidence about the external object, so nothing is persisted and no
    external read is performed.
    """
    return {
        "tracking_id": record.tracking_id,
        "action": RECOVERY_ACTION_VERIFY_EXTERNAL,
        "outcome": record.status,
        "checked_revision": expected_revision,
        "next_revision": record.revision,
        "checked_at": timestamp,
        "operation_id": record.current_operation_id,
        "needs_manual": True,
        "verification_reason": reason,
        "tracking": tracking_summary_fields(record),
    }


__all__ = ["run_saved_tracking_check"]
