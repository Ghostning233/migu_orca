from __future__ import annotations

"""Unit tests for the tracking read service and serializers (US-223)."""

from dataclasses import replace
from pathlib import Path
from typing import Any, get_args

from apps.migu_orca_web.api_contract import TrackingAvailableActionDTO
from apps.migu_orca_web.tracking_read_service import (
    list_tracking_items,
    project_tracking_last_failure,
)
from apps.migu_orca_web.tracking_serializers import (
    serialize_tracking_audit_events,
    serialize_tracking_operation_summary,
    tracking_available_actions,
    tracking_summary_fields,
)
from storage_engine.controllers.storage_config import load_storage_config
from storage_engine.controllers.tracking_repository import ensure_tracking_record
from tracking_engine.controllers.submit import SUBMIT_FAILED_MESSAGE
from tracking_engine.models.operation import (
    TRACKING_OPERATION_KIND_SUBMIT,
    TRACKING_OPERATION_STATE_FAILED,
    TRACKING_OPERATION_STATE_IN_PROGRESS,
    TRACKING_OPERATION_STATE_SUCCEEDED,
    create_tracking_operation,
    transition_tracking_operation,
)
from tracking_engine.models.tracking import (
    TRACKING_AUDIT_ACTOR_SYSTEM,
    TRACKING_AUDIT_ACTOR_USER,
    TRACKING_AUDIT_REVALIDATION_FAILED,
    TRACKING_AUDIT_SUBMIT_FAILED,
    TRACKING_AUDIT_TRACKING_CREATED,
    TRACKING_ORIGIN_SAVE_CONFIRM,
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_ADDED_TO_DOWNLOAD,
    TRACKING_STATUS_DISABLED,
    TRACKING_STATUS_EXTERNAL_DELETED,
    TRACKING_STATUS_EXTERNAL_ONLY,
    TRACKING_STATUS_NEEDS_RECONFIRM,
    TRACKING_STATUS_PENDING_SUBMIT,
    TRACKING_STATUS_RECOVERY_REQUIRED,
    TRACKING_STATUS_REVALIDATING,
    TRACKING_STATUS_SUBMIT_FAILED,
    TRACKING_STATUS_SUBMITTING,
    TRACKING_STATUS_UNKNOWN,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
    TRACKING_STATUSES,
    TrackingRecord,
    build_audit_event,
    create_external_tracking_record,
    create_tracking_record,
    transition_record,
)


def _record(
    *,
    status: str = TRACKING_STATUS_PENDING_SUBMIT,
    title: str = "葬送的芙莉莲",
    request_id: str = "request-1",
) -> TrackingRecord:
    return create_tracking_record(
        request_id=request_id,
        status=status,
        plan_summary={"title": title, "season": 1, "subtitle_group": "喵萌"},
        origin=TRACKING_ORIGIN_SAVE_CONFIRM,
        audit_action=TRACKING_AUDIT_TRACKING_CREATED,
        audit_actor=TRACKING_AUDIT_ACTOR_USER,
    )


#: The action codes issue #228 (T5a) retires from the public contract.  The
#: revalidate endpoint and the internal ``DELETE_EXTERNAL`` execution chain stay
#: (E1/E4); they are simply no longer offered as user-facing entries.
RETIRED_PUBLIC_ACTIONS = frozenset(
    {"REVALIDATE", "RECOVER_AUTO", "MARK_SUCCEEDED", "MARK_FAILED", "DELETE_EXTERNAL"}
)


def test_available_actions_for_pending_and_reconfirm() -> None:
    # #228 E1: the submit path revalidates internally, so 重新复核 is not a
    # separate user decision; only the submit decision itself is offered.
    assert [a["code"] for a in tracking_available_actions(TRACKING_STATUS_PENDING_SUBMIT)] == [
        "SUBMIT",
    ]
    assert [
        a["code"] for a in tracking_available_actions(TRACKING_STATUS_NEEDS_RECONFIRM)
    ] == ["SUBMIT"]


def test_available_actions_for_submit_failed_is_retry_not_submit() -> None:
    codes = [a["code"] for a in tracking_available_actions(TRACKING_STATUS_SUBMIT_FAILED)]
    assert codes == ["RETRY"]


def test_available_actions_for_recovery_statuses() -> None:
    # #228 E2/E3/E5: 自动恢复/标记为成功/标记为失败 are retired.  The remaining
    # recovery family member is the read-only external verification: a page flow
    # (state + proven capability) that never writes, so an unresolved record
    # projects no state-changing action at all.
    for status in (
        TRACKING_STATUS_VERIFYING_EXTERNAL,
        TRACKING_STATUS_RECOVERY_REQUIRED,
        TRACKING_STATUS_UNKNOWN,
    ):
        assert tracking_available_actions(status) == []


def test_retired_action_codes_never_appear_in_any_public_projection() -> None:
    """#228: no status/mapping may announce a retired action code again."""
    mappings = (
        None,
        {"subscription_id": "opaque-sub", "rss_ids": ["opaque-rss"]},
        {"subscription_id": "opaque-sub", "rss_ids": []},
        {"subscription_id": "", "rss_ids": ["opaque-rss"]},
    )
    projected = {
        action["code"]
        for status in TRACKING_STATUSES
        for mapping in mappings
        for action in tracking_available_actions(status, mapping)
    }
    assert projected & RETIRED_PUBLIC_ACTIONS == set()


def test_announced_actions_stay_inside_the_published_action_enum() -> None:
    """The projection never emits a code the public action DTO cannot express."""
    published = frozenset(
        get_args(TrackingAvailableActionDTO.model_fields["code"].annotation)
    )
    mappings = (
        None,
        {"subscription_id": "opaque-sub", "rss_ids": ["opaque-rss"]},
    )
    for status in TRACKING_STATUSES:
        for mapping in mappings:
            for action in tracking_available_actions(status, mapping):
                assert action["code"] in published


def test_available_actions_empty_when_no_state_change_possible() -> None:
    for status in (
        TRACKING_STATUS_REVALIDATING,
        TRACKING_STATUS_SUBMITTING,
    ):
        assert tracking_available_actions(status) == []


def test_available_actions_expose_stage31_management_actions() -> None:
    mapping = {"subscription_id": "opaque-sub", "rss_ids": ["opaque-rss"]}
    assert [item["code"] for item in tracking_available_actions(TRACKING_STATUS_ACTIVE, mapping)] == [
        "MODIFY", "SET_ENABLED", "REFRESH_RSS",
    ]
    # #228 E4: 独立「删除 Auto Bangumi 外部对象」不再公告；内部复合删除链仍执行它
    # （见 tests/api_contract/test_tracking_plan_delete_api.py）。
    assert [item["code"] for item in tracking_available_actions(TRACKING_STATUS_DISABLED, mapping)] == [
        "SET_ENABLED",
    ]
    # Issue #224 A4: the retired read-only archive offers no management action in
    # the projection either — the write policy and the read model agree.
    assert tracking_available_actions(TRACKING_STATUS_EXTERNAL_ONLY, mapping) == []


def test_available_action_objects_are_strict_shape() -> None:
    for action in tracking_available_actions(TRACKING_STATUS_SUBMIT_FAILED):
        assert set(action) == {"code", "label", "style", "requires_confirmation", "target_scopes"}
        assert action["target_scopes"] == []
        assert action["style"] in {"PRIMARY", "SECONDARY", "DANGER"}
        assert isinstance(action["requires_confirmation"], bool)


def test_summary_fields_redact_poisoned_title_and_reject_foreign_poster() -> None:
    record = create_tracking_record(
        request_id="request-2",
        status=TRACKING_STATUS_PENDING_SUBMIT,
        plan_summary={
            "title": "https://private.example/leak",
            "subtitle_group": "喵萌",
            "poster_path": "https://cdn.example/poster.jpg",
        },
        origin=TRACKING_ORIGIN_SAVE_CONFIRM,
        audit_action=TRACKING_AUDIT_TRACKING_CREATED,
        audit_actor=TRACKING_AUDIT_ACTOR_USER,
    )
    summary = tracking_summary_fields(record)
    assert summary["title"] == "[redacted]"
    assert summary["poster_path"] is None


def test_summary_fields_allow_same_origin_poster_route() -> None:
    record = _record()
    record = TrackingRecord(
        **{
            **record.__dict__,
            "plan_summary": {
                "title": "葬送的芙莉莲",
                "poster_path": "/api/v1/mikan/posters/opaque-key",
            },
        }
    )
    summary = tracking_summary_fields(record)
    assert summary["poster_path"] == "/api/v1/mikan/posters/opaque-key"
    assert summary["updated_episode"] is None
    assert summary["updated_episode_status"] == "NOT_IMPLEMENTED"
    assert summary["total_episodes"] is None


def test_operation_summary_never_exposes_binding() -> None:
    operation = create_tracking_operation(
        tracking_id="trk_x",
        idempotency_key="opaque-client-key",
        expected_revision=3,
        request_fingerprint="fp",
    )
    summary = serialize_tracking_operation_summary(operation)
    body = str(summary)
    assert "opaque-client-key" not in body
    assert "expected_revision" not in summary
    assert "request_fingerprint" not in summary
    assert summary["operation_id"] == operation.operation_id
    assert summary["state"] == "PREPARED"


def test_audit_events_returns_only_recent_window() -> None:
    events: list[dict[str, Any]] = []
    for index in range(25):
        events.append(
            build_audit_event(
                action=TRACKING_AUDIT_TRACKING_CREATED,
                actor=TRACKING_AUDIT_ACTOR_USER,
                from_status=None,
                to_status=TRACKING_STATUS_PENDING_SUBMIT,
                tracking_revision=1,
                safe_message=f"event-{index}",
                created_at=f"2026-01-01T00:{index:02d}:00+00:00",
            )
        )
    recent = serialize_tracking_audit_events(events)
    assert len(recent) == 20
    assert recent[0]["safe_message"] == "event-5"
    assert recent[-1]["safe_message"] == "event-24"


def test_list_tracking_items_defaults_and_summary(tmp_path: Path) -> None:
    config = load_storage_config(tmp_path / "storage")
    ensure_tracking_record(config, _record(status=TRACKING_STATUS_PENDING_SUBMIT))
    ensure_tracking_record(config, _record(status=TRACKING_STATUS_ACTIVE, title="咒术回战", request_id="request-2"))

    payload = list_tracking_items(config)
    assert payload["summary"]["total"] == 2
    assert payload["summary"]["pending"] == 1
    assert payload["summary"]["active"] == 1
    assert payload["summary"]["unreadable"] == 0
    # Issue #224 A7: the service publishes the whole group vocabulary, including
    # the transient 处理中 group that has no overview card.
    assert payload["status_groups"] == [
        {"group": "PENDING", "label": "待处理", "count": 1, "has_overview_card": True},
        {"group": "PROCESSING", "label": "处理中", "count": 0, "has_overview_card": False},
        {"group": "ACTIVE", "label": "追番中", "count": 1, "has_overview_card": True},
        {"group": "ATTENTION", "label": "需处理", "count": 0, "has_overview_card": True},
        {"group": "INACTIVE", "label": "已停用", "count": 0, "has_overview_card": True},
    ]
    # Default updated_at sort is newest first, but both timestamps are identical
    # here so the tie-break is the deterministic tracking_id.
    assert len(payload["items"]) == 2


def test_list_tracking_items_keeps_external_only_history_read_only(tmp_path: Path) -> None:
    """Issue #224 A4: real label, no card count, no filter hit, no action."""
    config = load_storage_config(tmp_path / "storage")
    record = create_external_tracking_record(
        adapter="legacy_3_1",
        object_kind="subscription",
        external_id="sub-history-1",
        subscription_id="sub-history-1",
        title="历史外部订阅",
        season=1,
    )
    ensure_tracking_record(config, record)

    payload = list_tracking_items(config)
    assert payload["summary"]["total"] == 1
    assert payload["summary"]["inactive"] == 0
    groups = {entry["group"]: entry for entry in payload["status_groups"]}
    assert groups["INACTIVE"]["count"] == 0
    item = payload["items"][0]
    assert item["tracking_id"] == record.tracking_id
    assert item["status_label"] == "仅外部"
    assert item["status_group"] == "INACTIVE"
    assert item["available_actions"] == []
    assert list_tracking_items(config, status_group="INACTIVE")["items"] == []


RECONFIRM_MESSAGE = "当前方案需要重新核对资源筛选。"
FAILED_AT = "2026-10-20T10:00:00+00:00"
OPERATION_FAILED_AT = "2026-10-20T10:05:00+00:00"


def _reconfirm_record(
    *,
    reason_code: str = "NO_VALID_RESOURCES",
    safe_message: str = RECONFIRM_MESSAGE,
    now: str = FAILED_AT,
) -> TrackingRecord:
    return transition_record(
        _record(),
        status=TRACKING_STATUS_NEEDS_RECONFIRM,
        audit_action=TRACKING_AUDIT_REVALIDATION_FAILED,
        reason_code=reason_code,
        safe_message=safe_message,
        now=now,
    )


def _failed_operation(
    *,
    tracking_id: str,
    error_type: str = "ab_auth_failed",
    state: str = TRACKING_OPERATION_STATE_FAILED,
    key: str = "op-key-1",
):
    operation = create_tracking_operation(
        tracking_id=tracking_id,
        idempotency_key=key,
        expected_revision=1,
        request_fingerprint="fingerprint-1",
        operation=TRACKING_OPERATION_KIND_SUBMIT,
    )
    operation = transition_tracking_operation(
        operation, state=TRACKING_OPERATION_STATE_IN_PROGRESS, now=FAILED_AT
    )
    if state == TRACKING_OPERATION_STATE_IN_PROGRESS:
        return operation
    return transition_tracking_operation(
        operation, state=state, error_type=error_type, now=OPERATION_FAILED_AT
    )


def _failed_submit_record_and_operation(
    *,
    error_type: str = "ab_auth_failed",
):
    """A SUBMIT_FAILED record whose stored error is bound to its operation."""
    record = _record()
    operation = _failed_operation(tracking_id=record.tracking_id, error_type=error_type)
    record = transition_record(
        record,
        status=TRACKING_STATUS_SUBMIT_FAILED,
        audit_action=TRACKING_AUDIT_SUBMIT_FAILED,
        operation_id=operation.operation_id,
        reason_code=error_type,
        safe_message=SUBMIT_FAILED_MESSAGE,
        now=FAILED_AT,
    )
    record = replace(
        record,
        current_operation_id=operation.operation_id,
        last_error={
            "error_type": error_type,
            "reason_code": error_type,
            "safe_message": SUBMIT_FAILED_MESSAGE,
        },
    )
    return record, operation


def test_last_failure_projects_the_revalidation_transition() -> None:
    failure = project_tracking_last_failure(_reconfirm_record(), None)

    assert failure == {
        "error_type": None,
        "category": None,
        "reason_code": "NO_VALID_RESOURCES",
        "safe_message": RECONFIRM_MESSAGE,
        # The audit event that moved the record into NEEDS_RECONFIRM carries the
        # only reliable failure time; updated_at is never used.
        "occurred_at": FAILED_AT,
    }


def test_last_failure_ignores_a_stale_error_after_a_revalidation_failure() -> None:
    # A NEEDS_RECONFIRM record that came from a failed submit keeps the old
    # adapter error; it must not be re-used as this failure's reason.
    record = replace(
        _reconfirm_record(),
        last_error={
            "error_type": "ab_auth_failed",
            "reason_code": "ab_auth_failed",
            "safe_message": "提交失败，可重新提交",
        },
    )

    failure = project_tracking_last_failure(
        record,
        _failed_operation(tracking_id=record.tracking_id),
    )

    assert failure is not None
    assert failure["error_type"] is None
    assert failure["reason_code"] == "NO_VALID_RESOURCES"
    assert failure["safe_message"] == RECONFIRM_MESSAGE


def test_last_failure_is_absent_without_a_bound_revalidation_event() -> None:
    # create_tracking_record only writes TRACKING_CREATED: no failure evidence.
    record = create_tracking_record(
        request_id="request-1",
        status=TRACKING_STATUS_NEEDS_RECONFIRM,
        plan_summary={"title": "葬送的芙莉莲"},
        audit_action=TRACKING_AUDIT_TRACKING_CREATED,
        audit_actor=TRACKING_AUDIT_ACTOR_USER,
    )

    assert project_tracking_last_failure(record, None) is None


def test_last_failure_projects_a_bound_submit_failure_with_its_category() -> None:
    record, operation = _failed_submit_record_and_operation()

    failure = project_tracking_last_failure(record, operation)

    assert failure == {
        "error_type": "ab_auth_failed",
        # The public category comes from the same engine mapper the live submit
        # response uses, so the browser keeps one label table (#241).
        "category": "AUTHENTICATION",
        "reason_code": "ab_auth_failed",
        "safe_message": SUBMIT_FAILED_MESSAGE,
        "occurred_at": FAILED_AT,
    }


def test_last_failure_requires_the_failure_operation_to_match() -> None:
    record, operation = _failed_submit_record_and_operation()

    # A different terminal operation cannot prove this error belongs to it.
    assert project_tracking_last_failure(
        record,
        _failed_operation(
            tracking_id=record.tracking_id, error_type="ab_timeout_pre_write", key="op-key-2"
        ),
    ) is None
    # A non-failed operation means the record's error is stale.
    assert project_tracking_last_failure(
        record,
        _failed_operation(
            tracking_id=record.tracking_id,
            state=TRACKING_OPERATION_STATE_SUCCEEDED,
        ),
    ) is None
    # No operation pointer at all (legacy archive): no binding, no reason.
    assert project_tracking_last_failure(record, None) is None
    assert project_tracking_last_failure(record, operation) is not None


def test_last_failure_falls_back_to_the_operation_completion_time() -> None:
    record, operation = _failed_submit_record_and_operation()
    record = replace(record, audit_events=[])  # no bound SUBMIT_FAILED event

    failure = project_tracking_last_failure(record, operation)

    assert failure is not None
    assert failure["occurred_at"] == OPERATION_FAILED_AT


def test_last_failure_never_guesses_a_time_from_updated_at() -> None:
    record, operation = _failed_submit_record_and_operation()
    record = replace(
        record,
        updated_at="2026-10-19T00:00:00+00:00",
        audit_events=[],
    )
    operation = replace(operation, completed_at=None)

    failure = project_tracking_last_failure(record, operation)

    assert failure is not None
    assert failure["occurred_at"] is None
    assert failure["occurred_at"] != record.updated_at


def test_last_failure_is_absent_for_every_non_failure_state() -> None:
    for status in (
        TRACKING_STATUS_ACTIVE,
        TRACKING_STATUS_PENDING_SUBMIT,
        TRACKING_STATUS_REVALIDATING,
        TRACKING_STATUS_SUBMITTING,
        TRACKING_STATUS_VERIFYING_EXTERNAL,
        TRACKING_STATUS_RECOVERY_REQUIRED,
        TRACKING_STATUS_UNKNOWN,
        TRACKING_STATUS_ADDED_TO_DOWNLOAD,
        TRACKING_STATUS_EXTERNAL_DELETED,
        TRACKING_STATUS_EXTERNAL_ONLY,
    ):
        record = replace(
            _record(),
            status=status,
            current_operation_id="op-1",
            last_error={
                "error_type": "ab_auth_failed",
                "reason_code": "ab_auth_failed",
                "safe_message": SUBMIT_FAILED_MESSAGE,
            },
        )
        assert project_tracking_last_failure(
            record,
            _failed_operation(tracking_id=record.tracking_id),
        ) is None


def test_a_same_status_bookkeeping_event_is_not_the_failure_reason() -> None:
    record = _reconfirm_record()
    # Defensive: if a same-status bookkeeping event ever carries the failure
    # action, it is not the transition into this failure.  (Today sync only
    # writes PLAN_CHANGE_DETECTED for statuses outside NEEDS_RECONFIRM.)
    bookkeeping = build_audit_event(
        action="PLAN_CHANGE_DETECTED",
        actor=TRACKING_AUDIT_ACTOR_SYSTEM,
        from_status=TRACKING_STATUS_NEEDS_RECONFIRM,
        to_status=TRACKING_STATUS_NEEDS_RECONFIRM,
        tracking_revision=record.revision,
        safe_message="外部同步已更新追番映射",
        created_at="2026-10-20T12:00:00+00:00",
    )
    record = replace(record, audit_events=[*record.audit_events, bookkeeping])

    failure = project_tracking_last_failure(record, None)

    assert failure is not None
    assert failure["safe_message"] == RECONFIRM_MESSAGE
    assert failure["occurred_at"] == FAILED_AT


def test_a_failure_event_without_a_message_is_not_a_reason() -> None:
    record = _record()
    record = replace(
        record,
        status=TRACKING_STATUS_NEEDS_RECONFIRM,
        audit_events=[
            build_audit_event(
                action=TRACKING_AUDIT_REVALIDATION_FAILED,
                actor=TRACKING_AUDIT_ACTOR_SYSTEM,
                from_status=TRACKING_STATUS_PENDING_SUBMIT,
                to_status=TRACKING_STATUS_NEEDS_RECONFIRM,
                tracking_revision=2,
                reason_code="NO_VALID_RESOURCES",
                safe_message=None,
                created_at=FAILED_AT,
            )
        ],
    )

    # safe_message is required by the contract; a code alone is not a reason.
    assert project_tracking_last_failure(record, None) is None


def test_a_crash_reconciled_submit_failure_still_recovers_its_category() -> None:
    # ``_replay_terminal_outcome`` writes status + audit but no last_error.
    record, operation = _failed_submit_record_and_operation()
    record = replace(record, last_error=None)

    failure = project_tracking_last_failure(record, operation)

    assert failure is not None
    assert failure["error_type"] == "ab_auth_failed"
    assert failure["category"] == "AUTHENTICATION"
    assert failure["safe_message"] == SUBMIT_FAILED_MESSAGE
    assert failure["occurred_at"] == FAILED_AT


def test_a_stale_error_does_not_hide_the_bound_event_reason() -> None:
    # A new key / crash replay leaves the old last_error behind while the new
    # operation's own audit transition records the current failure.
    record, operation = _failed_submit_record_and_operation()
    replay = _failed_operation(
        tracking_id=record.tracking_id,
        error_type="ab_timeout_pre_write",
        key="op-key-2",
    )
    replay_event = build_audit_event(
        action=TRACKING_AUDIT_SUBMIT_FAILED,
        actor=TRACKING_AUDIT_ACTOR_SYSTEM,
        from_status=TRACKING_STATUS_SUBMITTING,
        to_status=TRACKING_STATUS_SUBMIT_FAILED,
        tracking_revision=record.revision + 1,
        operation_id=replay.operation_id,
        reason_code="ab_timeout_pre_write",
        safe_message=SUBMIT_FAILED_MESSAGE,
        created_at="2026-10-20T11:00:00+00:00",
    )
    record = replace(
        record,
        current_operation_id=replay.operation_id,
        audit_events=[*record.audit_events, replay_event],
    )

    failure = project_tracking_last_failure(record, replay)

    assert failure is not None
    assert failure["error_type"] == "ab_timeout_pre_write"
    assert failure["category"] == "CONNECTION"
    assert failure["occurred_at"] == "2026-10-20T11:00:00+00:00"


def test_a_crash_mid_write_still_publishes_the_event_bound_failure() -> None:
    # ``record`` is persisted before the operation's terminal state: a crash can
    # leave the operation IN_PROGRESS while the record + event + last_error are
    # complete.  The bound event proves the failure, so the reason still shows.
    record, operation = _failed_submit_record_and_operation()
    in_flight = replace(operation, state=TRACKING_OPERATION_STATE_IN_PROGRESS, completed_at=None)

    failure = project_tracking_last_failure(record, in_flight)

    assert failure is not None
    assert failure["category"] == "AUTHENTICATION"
    assert failure["occurred_at"] == FAILED_AT


def test_a_crash_reconciled_failure_without_a_bound_event_publishes_nothing() -> None:
    record, operation = _failed_submit_record_and_operation()
    record = replace(record, last_error=None, audit_events=[])

    assert project_tracking_last_failure(record, operation) is None


def test_last_failure_drops_any_field_beyond_the_safe_shape() -> None:
    record, operation = _failed_submit_record_and_operation()
    record = replace(
        record,
        last_error={
            "error_type": "ab_auth_failed",
            "reason_code": "ab_auth_failed",
            "safe_message": SUBMIT_FAILED_MESSAGE,
            "request_url": "http://secret.example/rss",
            "password": "hunter2",
        },
    )

    failure = project_tracking_last_failure(record, operation)

    assert failure is not None
    assert set(failure) == {
        "error_type", "category", "reason_code", "safe_message", "occurred_at",
    }
    assert "hunter2" not in str(failure)
    assert "secret.example" not in str(failure)
