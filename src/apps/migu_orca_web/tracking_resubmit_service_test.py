from __future__ import annotations

"""Issue #184: risk-confirmed single manual resubmission of a pending submit.

These exercise the orchestration seam directly (no HTTP): the two-phase
read-only/confirmed interaction, the binding guards, the one-new-operation
idempotency, the preserved pending operation/audit and the fail-closed refusals.
The real Flask + localhost Auto Bangumi main chain lives in
``tests/api_contract/test_tracking_resubmit_local_ab.py``.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from ab_engine.models.management import ExternalRss, ExternalSubscription
from apps.migu_orca_web.schemas import TrackingResubmitPayload
from apps.migu_orca_web.tracking_external_check import CheckPolicy
from apps.migu_orca_web.tracking_resubmit_service import (
    RESUBMIT_BLOCKED_EXTERNAL_WRITE_IN_PROGRESS,
    RESUBMIT_BLOCKED_PLAN_NOT_SUBMITTABLE,
    RESUBMIT_BLOCKED_RESULT_UNPROVEN,
    RESUBMIT_STATUS_BLOCKED,
    RESUBMIT_STATUS_CONFIRMED,
    RESUBMIT_STATUS_UNRESOLVED,
    _blocked_reason_for_unresolved,
    _record_risk_confirmation,
    resubmit_idempotency_key,
    run_saved_tracking_resubmit,
)
from apps.migu_orca_web.tracking_saved_recovery_service_test import (
    ReadOnlyClient,
    _bound_submit_scenario,
)
from shared.errors import Stage1Error
from storage_engine.controllers.autobangumi_config_repository import (
    AutoBangumiConfigRepository,
    build_stored_autobangumi_config,
)
from storage_engine.controllers.operation_repository import (
    bind_tracking_operation,
    compare_and_swap_tracking_operation,
    load_tracking_operation,
)
from storage_engine.controllers.request_repository import (
    load_request_snapshot,
    save_request_snapshot,
)
from storage_engine.controllers.tracking_repository import (
    compare_and_swap_tracking_record,
    load_tracking_record,
)
from tracking_engine.controllers.submit import CONFIRM_REASON_CONNECTION
from tracking_engine.models.operation import (
    TRACKING_OPERATION_STATE_IN_PROGRESS,
    TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
    TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
    TRACKING_OPERATION_STATE_SUCCEEDED,
    create_tracking_operation,
    transition_tracking_operation,
)
from tracking_engine.models.tracking import (
    TRACKING_AUDIT_ACTOR_USER,
    TRACKING_AUDIT_RESUBMIT_CONFIRMED,
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_RECOVERY_REQUIRED,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
)

RSS_URL = "https://rss.invalid/feed"
REF = "abcdefab-cdef-4abc-8def-abcdefabcdef"
SECOND_REF = "22222222-2222-4222-8222-222222222222"

_FAST_POLICY = CheckPolicy(max_attempts=1, budget_seconds=1.0, backoff_seconds=0.0, sleep=lambda _s: None)


class _SubmitSpy:
    """The external create seam: records calls, never touches a real system."""

    def __init__(self, result: dict | None = None) -> None:
        self.calls: list[tuple[dict, object]] = []
        self.result = result or {"success": True, "ab_subscription_id": "external-1"}

    def __call__(self, request, ab_config):
        self.calls.append((request, ab_config))
        return dict(self.result)


def _matching_snapshot():
    return (
        ExternalSubscription("external-1", "芙莉莲", 1, "Group", rss_urls=(RSS_URL,), rss_ids=("rss-1",)),
        ExternalRss("rss-1", "芙莉莲", RSS_URL),
    )


def _reading_client() -> ReadOnlyClient:
    external, rss = _matching_snapshot()
    return ReadOnlyClient([external], rss_items=[rss])


def _empty_client() -> ReadOnlyClient:
    return ReadOnlyClient()


def _check_payload(record, **overrides) -> TrackingResubmitPayload:
    values: dict = {
        "tracking_id": record.tracking_id,
        "expected_revision": record.revision,
        "storage_dir": "storage",
        "confirm": False,
    }
    values.update(overrides)
    return TrackingResubmitPayload(**values)


def _confirm_payload(record, binding: dict, **overrides) -> TrackingResubmitPayload:
    values: dict = {
        "tracking_id": record.tracking_id,
        "expected_revision": binding["expected_revision"],
        "storage_dir": "storage",
        "confirm": True,
        "previous_operation_id": binding["previous_operation_id"],
        "connection_ref": binding["connection_ref"],
    }
    values.update(overrides)
    return TrackingResubmitPayload(**values)


def _phase_one_check(monkeypatch, tmp_path, state, client):
    """Return (config, scenario record, phase-1 result) for one bound scenario."""
    config, _record, saved, op, verifying = _bound_submit_scenario(
        monkeypatch, tmp_path, state, plan_ready=True
    )
    result = run_saved_tracking_resubmit(
        _check_payload(verifying),
        config_root=tmp_path / "private",
        management_client=client,
        read_policy=_FAST_POLICY,
        now="2026-09-14T00:00:00+00:00",
    )
    return config, verifying, saved, op, result


# ---------------------------------------------------------------------------
# Phase 1 — read-only, offered risk, never an automatic resubmit
# ---------------------------------------------------------------------------


def test_check_only_offers_the_risk_confirmation_without_any_external_write(monkeypatch, tmp_path: Path) -> None:
    config, verifying, saved, op, result = _phase_one_check(
        monkeypatch, tmp_path, TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN, _empty_client()
    )

    assert result["check_status"] == RESUBMIT_STATUS_UNRESOLVED
    assert result["requires_risk_confirmation"] is True
    assert result["verification_reason"] == "NOT_FOUND"
    assert result["binding"] == {
        "expected_revision": result["next_revision"],
        "previous_operation_id": op.operation_id,
        "connection_ref": str(saved.connection_ref),
    }
    assert result["operation_id"] == op.operation_id
    assert result["previous_operation_id"] is None
    # The check converged the record locally; the pending operation is untouched.
    after = load_tracking_record(config, verifying.tracking_id)
    assert after.status == TRACKING_STATUS_RECOVERY_REQUIRED
    assert after.current_operation_id == op.operation_id
    assert load_tracking_operation(config, op.operation_id).state == TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN
    assert after.external_mapping is None


def test_check_only_confirms_an_existing_subscription_with_zero_writes(monkeypatch, tmp_path: Path) -> None:
    submit_one = _SubmitSpy()
    config, _record, _saved, op, verifying = _bound_submit_scenario(
        monkeypatch, tmp_path, TRACKING_OPERATION_STATE_IN_PROGRESS, plan_ready=True
    )

    result = run_saved_tracking_resubmit(
        _check_payload(verifying),
        config_root=tmp_path / "private",
        management_client=_reading_client(),
        submit_one=submit_one,
        read_policy=_FAST_POLICY,
    )

    assert result["check_status"] == RESUBMIT_STATUS_CONFIRMED
    assert result["outcome"] == TRACKING_STATUS_ACTIVE
    assert result["requires_risk_confirmation"] is False
    assert result["binding"] is None
    assert result["verification_reason"] is None
    assert submit_one.calls == []
    after = load_tracking_record(config, verifying.tracking_id)
    assert after.status == TRACKING_STATUS_ACTIVE
    assert after.external_mapping is not None
    assert load_tracking_operation(config, op.operation_id).state == TRACKING_OPERATION_STATE_SUCCEEDED


@pytest.mark.parametrize(
    ("state", "expected_reason"),
    [
        (TRACKING_OPERATION_STATE_IN_PROGRESS, RESUBMIT_BLOCKED_EXTERNAL_WRITE_IN_PROGRESS),
        (TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN, None),
        (TRACKING_OPERATION_STATE_RECOVERY_REQUIRED, None),
    ],
)
def test_check_only_blocks_only_while_a_write_may_still_be_running(
    monkeypatch, tmp_path: Path, state: str, expected_reason: str | None
) -> None:
    _config, _verifying, _saved, _op, result = _phase_one_check(
        monkeypatch, tmp_path, state, _empty_client()
    )

    if expected_reason is None:
        assert result["check_status"] == RESUBMIT_STATUS_UNRESOLVED
        assert result["requires_risk_confirmation"] is True
    else:
        assert result["check_status"] == RESUBMIT_STATUS_BLOCKED
        assert result["blocked_reason"] == expected_reason
        assert result["requires_risk_confirmation"] is False


def test_a_proven_connection_failure_blocks_the_offer_instead_of_authorizing_it(
    monkeypatch, tmp_path: Path
) -> None:
    class _FailingClient:
        reads = 0

        def read_snapshot(self, *, deadline=None):
            self.reads += 1
            raise Stage1Error("ab_connection_failed", "无法连接", "read_snapshot")

    client = _FailingClient()
    _config, _verifying, _saved, _op, result = _phase_one_check(
        monkeypatch, tmp_path, TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN, client
    )

    assert result["check_status"] == RESUBMIT_STATUS_BLOCKED
    assert result["blocked_reason"] == CONFIRM_REASON_CONNECTION
    assert result["requires_risk_confirmation"] is False


def test_a_replaced_saved_connection_is_reported_not_rebound(monkeypatch, tmp_path: Path) -> None:
    submit_one = _SubmitSpy()
    config, _record, saved, op, verifying = _bound_submit_scenario(
        monkeypatch, tmp_path, TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN, plan_ready=True
    )
    # A new saved generation replaces the one the pending operation is bound to.
    AutoBangumiConfigRepository(tmp_path / "private").save(
        build_stored_autobangumi_config(
            {"auth_mode": "password", "base_url": "http://ab.invalid", "username": "u", "password": "p"}
        ),
        expected_configuration_revision=saved.configuration_revision,
    )

    result = run_saved_tracking_resubmit(
        _check_payload(verifying),
        config_root=tmp_path / "private",
        management_client=_reading_client(),
        submit_one=submit_one,
        read_policy=_FAST_POLICY,
    )

    assert result["check_status"] == RESUBMIT_STATUS_BLOCKED
    assert result["blocked_reason"] == "CONNECTION_CHANGED"
    assert submit_one.calls == []
    after = load_tracking_record(config, verifying.tracking_id)
    assert after.external_mapping is None
    assert after.current_operation_id == op.operation_id


# ---------------------------------------------------------------------------
# Phase 2 — the confirmed resubmit
# ---------------------------------------------------------------------------


def test_confirmed_resubmit_creates_one_traceable_operation_and_one_write(
    monkeypatch, tmp_path: Path
) -> None:
    submit_one = _SubmitSpy()
    config, verifying, _saved, op, offer = _phase_one_check(
        monkeypatch, tmp_path, TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN, _empty_client()
    )
    external, rss = _matching_snapshot()
    readback = lambda: (None, [external], [rss])  # noqa: E731

    result = run_saved_tracking_resubmit(
        _confirm_payload(verifying, offer["binding"]),
        config_root=tmp_path / "private",
        management_client=_empty_client(),
        submit_one=submit_one,
        readback_external=readback,
        read_policy=_FAST_POLICY,
        now="2026-09-14T00:05:00+00:00",
    )

    assert result["confirm"] is True
    assert result["check_status"] == RESUBMIT_STATUS_UNRESOLVED
    assert result["outcome"] == TRACKING_STATUS_ACTIVE
    assert result["previous_operation_id"] == op.operation_id
    assert result["operation_id"] != op.operation_id
    assert len(submit_one.calls) == 1

    new_operation = load_tracking_operation(config, result["operation_id"])
    assert new_operation.previous_operation_id == op.operation_id
    assert new_operation.state == TRACKING_OPERATION_STATE_SUCCEEDED
    assert new_operation.connection_ref == str(offer["binding"]["connection_ref"])
    # The pending original operation and its own evidence are preserved verbatim.
    original = load_tracking_operation(config, op.operation_id)
    assert original.state == TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN
    assert original.previous_operation_id is None

    after = load_tracking_record(config, verifying.tracking_id)
    assert after.status == TRACKING_STATUS_ACTIVE
    assert after.current_operation_id == result["operation_id"]
    assert any(
        event["action"] == TRACKING_AUDIT_RESUBMIT_CONFIRMED and event["actor"] == TRACKING_AUDIT_ACTOR_USER
        for event in after.audit_events
    )
    # The original unresolved audit trail survives the resubmit.
    assert any(event["action"] == "SUBMIT_OUTCOME_UNKNOWN" for event in after.audit_events)


def test_replaying_the_same_confirmation_reuses_the_one_new_operation(
    monkeypatch, tmp_path: Path
) -> None:
    submit_one = _SubmitSpy()
    config, verifying, _saved, op, offer = _phase_one_check(
        monkeypatch, tmp_path, TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN, _empty_client()
    )
    external, rss = _matching_snapshot()
    readback = lambda: (None, [external], [rss])  # noqa: E731
    payload = _confirm_payload(verifying, offer["binding"])

    first = run_saved_tracking_resubmit(
        payload,
        config_root=tmp_path / "private",
        management_client=_empty_client(),
        submit_one=submit_one,
        readback_external=readback,
        read_policy=_FAST_POLICY,
    )
    second = run_saved_tracking_resubmit(
        payload,
        config_root=tmp_path / "private",
        management_client=_empty_client(),
        submit_one=submit_one,
        readback_external=readback,
        read_policy=_FAST_POLICY,
    )

    assert second["operation_id"] == first["operation_id"]
    assert second["outcome"] == first["outcome"]
    assert len(submit_one.calls) == 1, "one confirmation must perform at most one submit"
    assert load_tracking_record(config, verifying.tracking_id).current_operation_id == first["operation_id"]


def test_an_unproven_check_cause_refuses_with_its_own_code() -> None:
    """AC 3/6: an unresolved result without a proven cause is never an offer."""
    operation = create_tracking_operation(
        tracking_id="trk_" + "a" * 32,
        idempotency_key="resubmit-unproven-1",
        expected_revision=1,
        request_fingerprint="sha256:x",
        connection_ref=REF,
        now="2026-09-14T00:00:00+00:00",
    )
    in_progress = transition_tracking_operation(
        operation, state=TRACKING_OPERATION_STATE_IN_PROGRESS, now="2026-09-14T00:00:00+00:00"
    )
    unknown = transition_tracking_operation(
        in_progress,
        state=TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
        now="2026-09-14T00:00:00+00:00",
    )

    assert _blocked_reason_for_unresolved({}, unknown) == RESUBMIT_BLOCKED_RESULT_UNPROVEN
    assert (
        _blocked_reason_for_unresolved({"verification_reason": "SOMETHING_NEW"}, unknown)
        == RESUBMIT_BLOCKED_RESULT_UNPROVEN
    )
    # A proven cause is either offerable or a specific refusal.
    assert _blocked_reason_for_unresolved({"verification_reason": "NOT_FOUND"}, unknown) is None
    assert (
        _blocked_reason_for_unresolved({"verification_reason": "AUTHENTICATION"}, unknown)
        == "AUTHENTICATION"
    )


def test_a_connection_replaced_after_the_offer_leaves_no_confirmation_behind(
    monkeypatch, tmp_path: Path
) -> None:
    """AC 4/6: an unusable bound generation refuses before the audit or any write."""
    config, verifying, saved, op, offer = _phase_one_check(
        monkeypatch, tmp_path, TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN, _empty_client()
    )
    before = load_tracking_record(config, verifying.tracking_id)
    AutoBangumiConfigRepository(tmp_path / "private").save(
        build_stored_autobangumi_config(
            {"auth_mode": "password", "base_url": "http://ab.invalid", "username": "u", "password": "p"}
        ),
        expected_configuration_revision=saved.configuration_revision,
    )
    submit_one = _SubmitSpy()

    result = run_saved_tracking_resubmit(
        _confirm_payload(verifying, offer["binding"]),
        config_root=tmp_path / "private",
        management_client=_reading_client(),
        submit_one=submit_one,
        read_policy=_FAST_POLICY,
    )

    assert result["check_status"] == RESUBMIT_STATUS_BLOCKED
    assert result["blocked_reason"] == "CONNECTION_CHANGED"
    assert submit_one.calls == []
    after = load_tracking_record(config, verifying.tracking_id)
    assert after.current_operation_id == op.operation_id
    assert not any(
        event["action"] == TRACKING_AUDIT_RESUBMIT_CONFIRMED for event in after.audit_events
    )
    # A refused resubmit never manufactures a revision the client did not confirm.
    assert after.revision == before.revision


def _point_record_at(config, record, operation_id: str):
    """Rebind one record to an operation the scenario did not create."""
    return compare_and_swap_tracking_record(
        config,
        record.tracking_id,
        base_revision=record.revision,
        record=replace(record, current_operation_id=operation_id, revision=record.revision + 1),
    )


def _one_time_operation(config, record, connection_ref: str):
    operation, created = bind_tracking_operation(
        config,
        tracking_id=record.tracking_id,
        operation="SUBMIT",
        idempotency_key="resubmit-one-time-key-1",
        expected_revision=record.revision,
        request_fingerprint=record.request_fingerprint or "sha256:x",
        connection_ref=connection_ref,
        submission_mode="DOWNLOAD_EXISTING",
        now="2026-09-14T00:00:00+00:00",
    )
    assert created
    in_progress = compare_and_swap_tracking_operation(
        config, operation.operation_id, expected_state="PREPARED",
        record=transition_tracking_operation(
            operation, state=TRACKING_OPERATION_STATE_IN_PROGRESS, now="2026-09-14T00:00:00+00:00"
        ),
    )
    return compare_and_swap_tracking_operation(
        config, in_progress.operation_id, expected_state=TRACKING_OPERATION_STATE_IN_PROGRESS,
        record=transition_tracking_operation(
            in_progress, state=TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
            now="2026-09-14T00:00:00+00:00",
        ),
    )


def test_a_one_time_submission_is_refused_by_the_server_without_any_read(
    monkeypatch, tmp_path: Path
) -> None:
    """AC 1/#184 scope: only persistent submissions may be resubmitted.

    A 「下载现有资源」operation whose result was never persisted reaches the same
    pending statuses as a persistent one, so the page alone cannot scope the
    feature; the server must refuse it before it reads or collects anything.
    """
    class _ExplodingClient:
        reads = 0

        def read_snapshot(self, *, deadline=None):
            self.reads += 1
            raise AssertionError("a one-time submission must be refused before any read")

    submit_one = _SubmitSpy()
    config, _record, saved, op, verifying = _bound_submit_scenario(
        monkeypatch, tmp_path, TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN, plan_ready=True
    )
    one_time = _one_time_operation(config, verifying, str(saved.connection_ref))
    verifying = _point_record_at(config, verifying, one_time.operation_id)
    client = _ExplodingClient()

    offer = run_saved_tracking_resubmit(
        _check_payload(verifying),
        config_root=tmp_path / "private",
        management_client=client,
        submit_one=submit_one,
        read_policy=_FAST_POLICY,
    )

    assert offer["check_status"] == RESUBMIT_STATUS_BLOCKED
    assert offer["blocked_reason"] == "ONE_TIME_SUBMISSION"
    assert offer["requires_risk_confirmation"] is False
    assert offer["binding"] is None
    assert client.reads == 0
    assert submit_one.calls == []
    after = load_tracking_record(config, verifying.tracking_id)
    assert after.current_operation_id == one_time.operation_id
    assert load_tracking_operation(config, op.operation_id).state == TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN
    assert not any(
        event["action"] == TRACKING_AUDIT_RESUBMIT_CONFIRMED for event in after.audit_events
    )


def test_a_one_time_submission_confirmation_is_refused_before_any_collect(
    monkeypatch, tmp_path: Path
) -> None:
    """AC 1: an already-issued confirmation can never re-run a one-time collect."""
    config, _record, saved, _op, verifying = _bound_submit_scenario(
        monkeypatch, tmp_path, TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN, plan_ready=True
    )
    one_time = _one_time_operation(config, verifying, str(saved.connection_ref))
    verifying = _point_record_at(config, verifying, one_time.operation_id)
    # Wire the one-time collection seam itself: if the gate were ever removed, the
    # refused confirmation would run this seam and the count below would move.
    collect_calls: list[dict] = []
    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_submission_service.compose_tracking_collect_one",
        lambda: (lambda request, _config: (collect_calls.append(request), {"success": True})[1]),
    )

    result = run_saved_tracking_resubmit(
        _check_payload(
            verifying,
            confirm=True,
            previous_operation_id=one_time.operation_id,
            connection_ref=str(saved.connection_ref),
        ),
        config_root=tmp_path / "private",
        management_client=_reading_client(),
        submit_one=None,
        read_policy=_FAST_POLICY,
    )

    assert result["check_status"] == RESUBMIT_STATUS_BLOCKED
    assert result["blocked_reason"] == "ONE_TIME_SUBMISSION"
    assert collect_calls == []
    assert load_tracking_record(config, verifying.tracking_id).current_operation_id == (
        one_time.operation_id
    )


def test_a_crash_between_the_bind_and_submitting_resumes_that_operation(
    monkeypatch, tmp_path: Path
) -> None:
    """AC 5: the confirmation's own operation is resumed, never a misleading 409.

    The durable binder is on disk but the record has not reached SUBMITTING yet:
    PREPARED proves the external was never called, so the replayed confirmation
    resumes it exactly like a same-key submit resume.
    """
    config, _record, saved, op, verifying = _bound_submit_scenario(
        monkeypatch, tmp_path, TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN, plan_ready=True
    )
    offer = run_saved_tracking_resubmit(
        _check_payload(verifying),
        config_root=tmp_path / "private",
        management_client=_empty_client(),
        read_policy=_FAST_POLICY,
        now="2026-09-14T00:00:00+00:00",
    )
    binding = offer["binding"]
    key = resubmit_idempotency_key(
        tracking_id=verifying.tracking_id,
        previous_operation_id=binding["previous_operation_id"],
        expected_revision=binding["expected_revision"],
        connection_ref=str(binding["connection_ref"]),
    )
    # The real flow writes the USER verdict and binds the operation, then crashes
    # before the record reaches SUBMITTING.
    record = load_tracking_record(config, verifying.tracking_id)
    record = _record_risk_confirmation(
        config, record=record, operation=op, timestamp="2026-09-14T00:00:01+00:00"
    )
    bound, created = bind_tracking_operation(
        config,
        tracking_id=verifying.tracking_id,
        operation="SUBMIT",
        idempotency_key=key,
        expected_revision=record.revision,
        request_fingerprint=record.request_fingerprint or "sha256:x",
        connection_ref=str(binding["connection_ref"]),
        previous_operation_id=op.operation_id,
        now="2026-09-14T00:00:01+00:00",
    )
    assert created
    assert load_tracking_operation(config, bound.operation_id).state == "PREPARED"

    submit_one = _SubmitSpy()
    external, rss = _matching_snapshot()
    result = run_saved_tracking_resubmit(
        _check_payload(
            verifying,
            expected_revision=binding["expected_revision"],
            confirm=True,
            previous_operation_id=binding["previous_operation_id"],
            connection_ref=str(binding["connection_ref"]),
        ),
        config_root=tmp_path / "private",
        management_client=_empty_client(),
        submit_one=submit_one,
        readback_external=lambda: (None, [external], [rss]),
        read_policy=_FAST_POLICY,
        now="2026-09-14T00:00:02+00:00",
    )

    assert result["operation_id"] == bound.operation_id
    assert result["outcome"] == TRACKING_STATUS_ACTIVE
    assert len(submit_one.calls) == 1
    assert load_tracking_operation(config, bound.operation_id).state == TRACKING_OPERATION_STATE_SUCCEEDED


def test_a_binding_change_that_is_not_a_plan_change_is_refused_as_a_stale_confirmation(
    monkeypatch, tmp_path: Path
) -> None:
    """AC 4: an operation/mapping binding change is a 409, not a plan verdict."""
    config, _record, saved, op, verifying = _bound_submit_scenario(
        monkeypatch, tmp_path, TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN, plan_ready=True
    )
    # A legacy mapping the bound generation does not own: the read-only
    # verification refuses the identity while the plan itself is unchanged.
    verifying = compare_and_swap_tracking_record(
        config,
        verifying.tracking_id,
        base_revision=verifying.revision,
        record=replace(
            verifying,
            external_mapping={
                "schema_version": 1,
                "adapter": "legacy_3_1",
                "subscription_id": "external-legacy",
                "rss_ids": [],
                "match_reason": "EXTERNAL_ID",
                "external_deleted": False,
                "enabled": True,
                "missing_sync_count": 0,
                "last_verified_at": None,
            },
            revision=verifying.revision + 1,
        ),
    )

    with pytest.raises(Stage1Error) as error:
        run_saved_tracking_resubmit(
            _check_payload(verifying),
            config_root=tmp_path / "private",
            management_client=_reading_client(),
            read_policy=_FAST_POLICY,
        )

    assert error.value.error_type == "tracking_resubmit_binding_conflict"
    assert load_tracking_record(config, verifying.tracking_id).current_operation_id == op.operation_id


def test_confirmed_resubmit_refuses_a_stale_revision_before_any_read(monkeypatch, tmp_path: Path) -> None:
    config, verifying, _saved, _op, offer = _phase_one_check(
        monkeypatch, tmp_path, TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN, _empty_client()
    )
    client = _reading_client()
    submit_one = _SubmitSpy()

    with pytest.raises(Stage1Error) as error:
        run_saved_tracking_resubmit(
            _confirm_payload(verifying, offer["binding"], expected_revision=offer["binding"]["expected_revision"] + 5),
            config_root=tmp_path / "private",
            management_client=client,
            submit_one=submit_one,
            read_policy=_FAST_POLICY,
        )

    assert error.value.error_type == "tracking_revision_conflict"
    assert client.reads == 0
    assert submit_one.calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    [("previous_operation_id", "op_" + "0" * 32), ("connection_ref", SECOND_REF)],
)
def test_confirmed_resubmit_refuses_a_rebound_confirmation(
    monkeypatch, tmp_path: Path, field: str, value: str
) -> None:
    _config, verifying, _saved, _op, offer = _phase_one_check(
        monkeypatch, tmp_path, TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN, _empty_client()
    )
    client = _reading_client()
    submit_one = _SubmitSpy()

    with pytest.raises(Stage1Error) as error:
        run_saved_tracking_resubmit(
            _confirm_payload(verifying, offer["binding"], **{field: value}),
            config_root=tmp_path / "private",
            management_client=client,
            submit_one=submit_one,
            read_policy=_FAST_POLICY,
        )

    assert error.value.error_type == "tracking_resubmit_binding_conflict"
    assert client.reads == 0
    assert submit_one.calls == []


def test_an_in_flight_original_operation_blocks_the_confirmed_resubmit(
    monkeypatch, tmp_path: Path
) -> None:
    config, verifying, saved, op, offer = _phase_one_check(
        monkeypatch, tmp_path, TRACKING_OPERATION_STATE_IN_PROGRESS, _empty_client()
    )
    assert offer["requires_risk_confirmation"] is False
    client = _empty_client()
    submit_one = _SubmitSpy()

    result = run_saved_tracking_resubmit(
        _check_payload(
            verifying,
            expected_revision=offer["next_revision"],
            confirm=True,
            previous_operation_id=op.operation_id,
            connection_ref=str(saved.connection_ref),
        ),
        config_root=tmp_path / "private",
        management_client=client,
        submit_one=submit_one,
        read_policy=_FAST_POLICY,
    )

    assert result["check_status"] == RESUBMIT_STATUS_BLOCKED
    assert result["blocked_reason"] == RESUBMIT_BLOCKED_EXTERNAL_WRITE_IN_PROGRESS
    assert submit_one.calls == []
    after = load_tracking_record(config, verifying.tracking_id)
    assert after.current_operation_id == op.operation_id
    assert load_tracking_operation(config, op.operation_id).state == TRACKING_OPERATION_STATE_IN_PROGRESS


def test_a_changed_plan_is_never_adopted_under_a_risk_confirmation(
    monkeypatch, tmp_path: Path
) -> None:
    config, verifying, _saved, _op, offer = _phase_one_check(
        monkeypatch, tmp_path, TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN, _empty_client()
    )
    # The local plan changes after the confirmation was published: the chosen
    # collection identity is part of the business fingerprint, so the pending
    # confirmation no longer describes the plan it was given for.
    snapshot = load_request_snapshot(config, verifying.request_id)
    snapshot["source_info"]["matched_bangumi"]["title"] = "改过的标题"
    save_request_snapshot(config, snapshot)
    client = _empty_client()
    submit_one = _SubmitSpy()

    result = run_saved_tracking_resubmit(
        _confirm_payload(verifying, offer["binding"]),
        config_root=tmp_path / "private",
        management_client=client,
        submit_one=submit_one,
        read_policy=_FAST_POLICY,
    )

    assert result["check_status"] == RESUBMIT_STATUS_BLOCKED
    assert result["blocked_reason"] == RESUBMIT_BLOCKED_PLAN_NOT_SUBMITTABLE
    assert any(issue["code"] == "REQUEST_CHANGED" for issue in result["issues"])
    assert submit_one.calls == []


def test_the_confirmed_recheck_converges_without_a_new_operation(
    monkeypatch, tmp_path: Path
) -> None:
    config, verifying, _saved, op, offer = _phase_one_check(
        monkeypatch, tmp_path, TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN, _empty_client()
    )
    submit_one = _SubmitSpy()

    result = run_saved_tracking_resubmit(
        _confirm_payload(verifying, offer["binding"]),
        config_root=tmp_path / "private",
        management_client=_reading_client(),
        submit_one=submit_one,
        read_policy=_FAST_POLICY,
    )

    assert result["check_status"] == RESUBMIT_STATUS_CONFIRMED
    assert result["outcome"] == TRACKING_STATUS_ACTIVE
    assert submit_one.calls == []
    after = load_tracking_record(config, verifying.tracking_id)
    assert after.status == TRACKING_STATUS_ACTIVE
    assert after.current_operation_id == op.operation_id
    assert load_tracking_operation(config, op.operation_id).state == TRACKING_OPERATION_STATE_SUCCEEDED


def test_the_result_never_leaks_the_saved_credential_or_binding_secrets(
    monkeypatch, tmp_path: Path
) -> None:
    _config, verifying, _saved, _op, offer = _phase_one_check(
        monkeypatch, tmp_path, TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN, _empty_client()
    )
    serialized = repr(offer) + repr(
        run_saved_tracking_resubmit(
            _confirm_payload(verifying, offer["binding"]),
            config_root=tmp_path / "private",
            management_client=_reading_client(),
            submit_one=_SubmitSpy(),
            read_policy=_FAST_POLICY,
        )
    )

    for forbidden in ("secret", "password", "ab.invalid", "token", "rss.invalid", "http://"):
        assert forbidden not in serialized
    assert TRACKING_STATUS_VERIFYING_EXTERNAL  # the pending status itself is not a secret
