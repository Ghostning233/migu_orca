"""Unified "delete the tracking plan" use case (issue #92).

One business action removes the local tracking plan **and** its tracking record
together, and optionally the controlled external subscription as well:

* without the external checkbox the external object keeps running and MiGuOrca
  simply stops managing it (the mapping disappears with the record, so later
  syncs can never re-import or adopt it);
* with the checkbox the exact mapped external object is removed first through
  the reliable management sequence (confirm, expected revision, idempotency,
  read-back, unknown-outcome recovery, adapter-fixed ``file=false``), and only a
  confirmed success is followed by the local delete.

An external failure or an unknown outcome removes nothing: the plan, the record,
the mapping and the recovery evidence all stay, so the user never loses control
of the external object. No path here deletes downloaded media.

Issue #230 (T5b, ADR-0006) narrows the delete lock from the *record status* to
"**may the external write still be running**", judged on the current operation:

* ``IN_PROGRESS`` / ``PREPARED`` → refused (running, or may be turned into a
  running write by another executor);
* ``OUTCOME_UNKNOWN`` / ``RECOVERY_REQUIRED`` → allowed only as a **risk-confirmed
  abandon** that binds the record revision and the operation id and is re-checked
  right before the local delete (so a ``PREPARED → IN_PROGRESS`` race loses);
* missing / damaged / unreadable / unknown operation state → refused;
* no current operation → the historical status guard.

The abandon path deletes local data only and refuses ``delete_external``: an
abandon must never become a new external write.
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any

from apps.migu_orca_web.schemas import (
    SavedTrackingManagementInput,
    SavedTrackingPlanDeleteInput,
)
from apps.migu_orca_web.tracking_saved_management_service import run_saved_tracking_management
from shared.errors import Stage1Error
from storage_engine.controllers.operation_repository import load_tracking_operation
from storage_engine.controllers.request_repository import delete_request_snapshot
from storage_engine.controllers.storage_config import StorageConfig
from storage_engine.controllers.tracking_repository import (
    delete_tracking_record,
    load_tracking_record,
)
from tracking_engine.models.operation import (
    TRACKING_OPERATION_STATE_FAILED,
    TRACKING_OPERATION_STATE_IN_PROGRESS,
    TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
    TRACKING_OPERATION_STATE_PREPARED,
    TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
    TRACKING_OPERATION_STATE_SUCCEEDED,
)
from tracking_engine.models.tracking import (
    TRACKING_STATUS_RECOVERY_REQUIRED,
    TRACKING_STATUS_REVALIDATING,
    TRACKING_STATUS_SUBMITTING,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
    TrackingRecord,
)

#: Operation states where the external write may still run: deleting then would
#: race it and discard the only recovery evidence.  ``PREPARED`` is included on
#: purpose — another executor may turn it into ``IN_PROGRESS`` (ADR-0006).
_IN_FLIGHT_OPERATION_STATES = frozenset(
    {TRACKING_OPERATION_STATE_PREPARED, TRACKING_OPERATION_STATE_IN_PROGRESS}
)

#: Operation states that already exited but left the result undecidable: the only
#: states that unlock the risk-confirmed abandon (ADR-0006).
_ABANDONABLE_OPERATION_STATES = frozenset(
    {TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN, TRACKING_OPERATION_STATE_RECOVERY_REQUIRED}
)

#: Operation states that are finished history: they are shown as 操作记录 but
#: never lock an allowed local action (issue #96).
_SETTLED_OPERATION_STATES = frozenset(
    {TRACKING_OPERATION_STATE_SUCCEEDED, TRACKING_OPERATION_STATE_FAILED}
)

#: Every state the storage layer can hand back.  Anything else fails closed.
_KNOWN_OPERATION_STATES = (
    _IN_FLIGHT_OPERATION_STATES | _ABANDONABLE_OPERATION_STATES | _SETTLED_OPERATION_STATES
)

#: Statuses used only when the record has **no** current operation pointer: keep
#: the historical guard, because the status is then the only evidence available.
_UNDELETABLE_STATUSES = frozenset(
    {
        TRACKING_STATUS_SUBMITTING,
        TRACKING_STATUS_REVALIDATING,
        TRACKING_STATUS_VERIFYING_EXTERNAL,
        TRACKING_STATUS_RECOVERY_REQUIRED,
    }
)

_STEP = "run_saved_tracking_plan_delete"


@dataclass(frozen=True)
class _DeleteVerdict:
    """What one delete is allowed to do, decided from the current operation.

    ``abandon`` marks the risk-confirmed local-only path; the operation identity
    is kept so the re-read before the delete can prove nothing moved.
    """

    abandon: bool
    operation_id: str | None = None
    operation_state: str | None = None

_MANAGEMENT_SUCCEEDED = "SUCCEEDED"
_MANAGEMENT_FAILED = "FAILED"


def run_saved_tracking_plan_delete(
    config: StorageConfig,
    *,
    payload: SavedTrackingPlanDeleteInput,
    repository: Any = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Delete one tracking plan, optionally removing its external subscription.

    An unresolved operation can only be removed as a risk-confirmed **abandon**:
    local-only, bound to the record revision and the operation the user saw
    (ADR-0006).  Everything else keeps the plain-delete semantics.
    """
    record = load_tracking_record(config, payload.tracking_id)
    verdict = _delete_verdict(config, record)
    _verify_confirmation(payload, record, verdict)

    mapping = record.external_mapping if isinstance(record.external_mapping, dict) else {}
    has_controlled_external = isinstance(mapping.get("subscription_id"), str) and bool(
        mapping.get("subscription_id")
    )

    external_deleted = False
    if payload.delete_external and has_controlled_external:
        outcome = _delete_external(payload=payload, record=record)
        if outcome != _MANAGEMENT_SUCCEEDED:
            # Nothing local is removed: the plan, record, mapping and recovery
            # evidence stay so the user can retry or recover deliberately.
            return {
                "tracking_id": record.tracking_id,
                "outcome": "EXTERNAL_FAILED" if outcome == _MANAGEMENT_FAILED else "EXTERNAL_UNKNOWN",
                "external_deleted": False,
            }
        external_deleted = True

    # Atomic re-verify (ADR-0006 decision 2): re-read the record and its current
    # operation right before the delete.  A ``PREPARED → IN_PROGRESS`` race, a
    # new unresolved write or a changed operation identity refuses the stale
    # confirmation, and nothing local is removed.
    fresh = load_tracking_record(config, record.tracking_id)
    fresh_verdict = _delete_verdict(config, fresh)
    _require_unchanged(verdict, fresh_verdict)
    if verdict.abandon and payload.expected_revision != fresh.revision:
        raise Stage1Error(
            "tracking_revision_conflict",
            "追番记录版本已变化，请刷新后重试",
            _STEP,
            {"expected_revision": payload.expected_revision, "current_revision": fresh.revision},
        )

    _delete_local(config, fresh)
    return {
        "tracking_id": fresh.tracking_id,
        "outcome": "DELETED",
        "external_deleted": external_deleted,
    }


def _delete_verdict(config: StorageConfig, record: TrackingRecord) -> _DeleteVerdict:
    """Decide what this delete may do, from the **current operation's** state.

    The record status is only consulted when the record has no operation pointer
    at all: then it is the only evidence available, so the historical guard is
    kept.  Every unreadable or unrecognized operation state fails closed.
    """
    if not record.current_operation_id:
        if record.status in _UNDELETABLE_STATUSES:
            raise Stage1Error(
                "tracking_state_conflict",
                "当前追番正在进行外部操作或存在未决结果，请先恢复后再删除",
                _STEP,
            )
        return _DeleteVerdict(abandon=False)

    try:
        operation = load_tracking_operation(config, record.current_operation_id)
    except Stage1Error as exc:
        raise Stage1Error(
            "tracking_state_conflict",
            "当前外部操作状态无法读取，请先恢复后再删除",
            _STEP,
        ) from exc
    if getattr(operation, "tracking_id", None) != record.tracking_id:
        # A pointer that names another record's operation proves nothing about
        # this one, so it fails closed instead of unlocking a delete.
        raise Stage1Error(
            "tracking_state_conflict",
            "当前外部操作不属于该追番记录，不能删除",
            _STEP,
        )

    state = operation.state
    if state not in _KNOWN_OPERATION_STATES:
        raise Stage1Error(
            "tracking_state_conflict",
            "当前外部操作状态无法识别，不能删除",
            _STEP,
        )
    if state in _IN_FLIGHT_OPERATION_STATES:
        raise Stage1Error(
            "tracking_state_conflict",
            "外部操作仍在执行或随时可能开始，请先恢复后再删除",
            _STEP,
        )
    if state in _ABANDONABLE_OPERATION_STATES:
        return _DeleteVerdict(
            abandon=True,
            operation_id=operation.operation_id,
            operation_state=state,
        )
    # A settled operation is history, not a delete lock (issue #96).
    assert state in _SETTLED_OPERATION_STATES
    return _DeleteVerdict(
        abandon=False,
        operation_id=operation.operation_id,
        operation_state=state,
    )


def _verify_confirmation(
    payload: SavedTrackingPlanDeleteInput,
    record: TrackingRecord,
    verdict: _DeleteVerdict,
) -> None:
    """Check the client's risk confirmation against what the server sees.

    The abandon requires the full pair (schema-enforced) and is re-checked right
    before the delete.  A plain delete may carry the pair too: it is verified
    here, before any external work, but not again afterwards — an authorized
    external delete is itself a tracking-record write, so the pair would always
    look stale at the end.  The final plain-delete CAS is bound to the freshly
    re-read revision instead.
    """
    if verdict.abandon:
        if payload.delete_external:
            raise Stage1Error(
                "validation_error",
                "放弃跟踪只能删除本地数据，不能同时删除外部订阅",
                _STEP,
                {"field": "delete_external"},
            )
        if payload.expected_revision is None or payload.expected_operation_id is None:
            raise Stage1Error(
                "validation_error",
                "放弃跟踪必须先完成风险确认（绑定条目版本与当前外部操作）",
                _STEP,
                {"field": "expected_operation_id"},
            )
    if payload.expected_revision is not None and payload.expected_revision != record.revision:
        raise Stage1Error(
            "tracking_revision_conflict",
            "追番记录版本已变化，请刷新后重试",
            _STEP,
            {"expected_revision": payload.expected_revision, "current_revision": record.revision},
        )
    if (
        payload.expected_operation_id is not None
        and payload.expected_operation_id != record.current_operation_id
    ):
        raise Stage1Error(
            "tracking_state_conflict",
            "当前外部操作已变化，请重新核验后再决定",
            _STEP,
        )


def _require_unchanged(first: _DeleteVerdict, second: _DeleteVerdict) -> None:
    """Refuse when the operation moved between the guard and the delete."""
    if first.abandon != second.abandon:
        raise Stage1Error(
            "tracking_state_conflict",
            "外部操作状态已变化，请重新核验后再决定",
            _STEP,
        )
    if first.abandon and (
        first.operation_id != second.operation_id
        or first.operation_state != second.operation_state
    ):
        raise Stage1Error(
            "tracking_state_conflict",
            "外部操作已变化，放弃确认已过期，请重新核验后再试",
            _STEP,
        )


def _delete_external(
    *,
    payload: SavedTrackingPlanDeleteInput,
    record: TrackingRecord,
) -> str:
    """Run the reliable external delete; return its management status.

    ``internal_plan_delete=True`` is the one opt-in that keeps
    ``DELETE_EXTERNAL`` executable for a retired read-only record without
    advertising any management action for it (issue #224 A4 + #218 exception
    (a)).  Without it, deleting the local plan of such a record would leave its
    Auto Bangumi object behind with no remaining path to clean it up.
    """
    management = SavedTrackingManagementInput(
        tracking_id=payload.tracking_id,
        target_scope="SUBSCRIPTION",
        operation="DELETE_EXTERNAL",
        expected_revision=record.revision,
        idempotency_key=payload.idempotency_key,
        confirm=True,
        # The management contract takes the canonical string form.
        connection_ref=str(payload.connection_ref) if payload.connection_ref else None,
        configuration_revision=payload.configuration_revision,
        storage_dir=payload.storage_dir,
    )
    result = run_saved_tracking_management(management, internal_plan_delete=True)
    status = result.get("management_status")
    return status if isinstance(status, str) else "OUTCOME_UNKNOWN"


def _delete_local(config: StorageConfig, record: TrackingRecord) -> None:
    """Remove the local tracking record (CAS) then its plan; media is untouched.

    The record is the user's authoritative pointer and is deleted through the
    compare-and-swap so a losing revision removes nothing.  The plan snapshot is
    cleaned up afterwards and never blocks the delete: an unreadable or already
    removed snapshot still leaves the record deletion as the explicit request.
    """
    delete_tracking_record(
        config, record.tracking_id, expected_revision=record.revision, step=_STEP
    )
    if record.request_id:
        # The request repository already converts I/O failures into
        # ``Stage1Error``; a plan that cannot be removed leaves an orphan
        # snapshot (nothing else points at it) rather than failing a delete whose
        # tracking record is already gone.
        with contextlib.suppress(Stage1Error):
            delete_request_snapshot(config, record.request_id)


__all__ = ["run_saved_tracking_plan_delete"]
