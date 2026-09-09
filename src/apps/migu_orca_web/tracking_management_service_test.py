from __future__ import annotations

from pathlib import Path

import pytest

import apps.migu_orca_web.tracking_management_service as management_service
from ab_engine.models.management import AutoBangumiCapabilities, ExternalRss, ExternalSubscription
from apps.migu_orca_web.tracking_management_service import recover_tracking_management, run_tracking_management
from shared.errors import Stage1Error
from storage_engine.controllers.operation_repository import load_tracking_operation
from storage_engine.controllers.storage_config import load_storage_config
from storage_engine.controllers.tracking_repository import ensure_tracking_record, load_tracking_record
from tracking_engine.controllers.management_target import ResolvedManagementTarget
from tracking_engine.models.operation import (
    TRACKING_OPERATION_STATE_FAILED,
    TRACKING_OPERATION_STATE_IN_PROGRESS,
    TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
    TRACKING_OPERATION_STATE_SUCCEEDED,
)
from tracking_engine.models.tracking import (
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_EXTERNAL_DELETED,
    create_external_tracking_record,
)


class _FakeClient:
    def __init__(self) -> None:
        self.reads = 0
        self.capabilities = AutoBangumiCapabilities(
            probe_status="VERIFIED", version="3.1.18", adapter="legacy_3_1",
            subscription_list="SUPPORTED", subscription_detail="SUPPORTED",
            subscription_modify="SUPPORTED", subscription_enable="SUPPORTED",
            subscription_disable="SUPPORTED", subscription_delete="SUPPORTED",
            rss_list="SUPPORTED", rss_modify="SUPPORTED", rss_enable="SUPPORTED",
            rss_disable="SUPPORTED", rss_delete="SUPPORTED", rss_refresh="SUPPORTED",
        )

    def read_snapshot(self):
        self.reads += 1
        return self.capabilities, [ExternalSubscription("sub-1", "Test", 1, "Group")], [ExternalRss("7", "Feed", "https://rss.invalid")]


def _seed(tmp_path: Path):
    config = load_storage_config(tmp_path / "storage")
    record = create_external_tracking_record(
        adapter="legacy_3_1", object_kind="subscription", external_id="sub-1",
        subscription_id="sub-1", rss_ids=("7",), title="Test", season=1,
    )
    stored, _ = ensure_tracking_record(config, record)
    return config, stored


def _run(config, record, client, calls, **kwargs):
    writer = kwargs.pop("write", lambda target, payload: calls.append((target, payload)))
    return run_tracking_management(
        config, tracking_id=record.tracking_id, expected_revision=record.revision,
        idempotency_key=kwargs.pop("idempotency_key", "key-1"), confirm=True,
        operation="MODIFY", target_scope="SUBSCRIPTION", management_client=client,
        patch={"title": "Changed"}, write=writer,
        **kwargs,
    )


def test_management_durably_gates_external_call_and_preserves_safe_storage(tmp_path: Path) -> None:
    config, record = _seed(tmp_path)
    client, calls = _FakeClient(), []
    result = _run(config, record, client, calls)
    assert result["management_status"] == "IN_PROGRESS"
    assert len(calls) == 1
    assert load_tracking_operation(config, result["operation_id"]).state == TRACKING_OPERATION_STATE_IN_PROGRESS
    stored = load_tracking_record(config, record.tracking_id)
    assert stored.current_operation_id == result["operation_id"]
    operation = load_tracking_operation(config, result["operation_id"])
    assert all(secret not in str(operation) for secret in ("https://", "sub-1", "Changed"))


def test_same_key_replays_without_read_or_write(tmp_path: Path) -> None:
    config, record = _seed(tmp_path)
    client, calls = _FakeClient(), []
    _run(config, record, client, calls)
    client.reads = 0
    with pytest.raises(Stage1Error):
        _run(config, load_tracking_record(config, record.tracking_id), client, calls)
    # The operation is intentionally still in progress until US-242/244 recovery.
    assert client.reads == 0
    assert len(calls) == 1


def test_prepared_to_in_progress_cas_failure_is_compensated_before_any_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    config, record = _seed(tmp_path)
    original = management_service.compare_and_swap_tracking_operation
    attempts = 0

    def fail_start(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1 and args[2] == "PREPARED":
            raise OSError("injected prepared CAS failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(management_service, "compare_and_swap_tracking_operation", fail_start)
    calls: list[object] = []
    with pytest.raises(OSError):
        _run(config, record, _FakeClient(), calls)
    operation = load_tracking_operation(config, management_service.tracking_operation_id_for_idempotency_key("key-1"))
    assert operation.state == TRACKING_OPERATION_STATE_FAILED
    stored = load_tracking_record(config, record.tracking_id)
    assert stored.current_operation_id is None
    assert stored.status == record.status
    assert calls == []


def test_capability_failure_happens_before_operation_binding(tmp_path: Path) -> None:
    config, record = _seed(tmp_path)
    client, calls = _FakeClient(), []
    client.capabilities = AutoBangumiCapabilities(
        probe_status="VERIFIED", version="3.1.17", adapter="legacy_3_1",
        subscription_list="SUPPORTED", subscription_detail="SUPPORTED",
    )
    with pytest.raises(Stage1Error) as error:
        _run(config, record, client, calls)
    assert error.value.error_type == "tracking_management_capability_unknown"
    assert calls == []


def test_disable_requires_the_disable_capability_before_external_write(tmp_path: Path) -> None:
    config, record = _seed(tmp_path)
    client = _FakeClient()
    client.capabilities = AutoBangumiCapabilities(
        probe_status="VERIFIED", version="3.1.18", adapter="legacy_3_1",
        subscription_list="SUPPORTED", subscription_detail="SUPPORTED",
        subscription_enable="SUPPORTED", subscription_disable="UNKNOWN",
    )
    calls = []
    with pytest.raises(Stage1Error) as error:
        run_tracking_management(
            config, tracking_id=record.tracking_id, expected_revision=record.revision,
            idempotency_key="disable-without-capability", confirm=True,
            operation="SET_ENABLED", target_scope="SUBSCRIPTION", enabled=False,
            management_client=client, write=lambda *_args: calls.append(True),
        )
    assert error.value.error_type == "tracking_management_capability_unknown"
    assert calls == []


def test_subscription_disable_readback_derives_enabled_from_deleted(tmp_path: Path) -> None:
    config, record = _seed(tmp_path)
    client = _FakeClient()
    result = run_tracking_management(
        config, tracking_id=record.tracking_id, expected_revision=record.revision,
        idempotency_key="disable-derived-from-deleted", confirm=True,
        operation="SET_ENABLED", target_scope="SUBSCRIPTION", enabled=False,
        management_client=client, write=lambda _target, _payload: {"status_code": 200},
        readback=lambda _operation, _scope, _target: ResolvedManagementTarget(
            scope="SUBSCRIPTION", subscription=ExternalSubscription("sub-1", "Test", 1, "Group", deleted=True),
        ),
    )
    assert result["management_status"] == TRACKING_OPERATION_STATE_SUCCEEDED
    assert load_tracking_record(config, record.tracking_id).status == "DISABLED"


def test_modify_requires_matching_readback_and_persists_projection(tmp_path: Path) -> None:
    config, record = _seed(tmp_path)
    client, calls = _FakeClient(), []

    def write(_target, _payload):
        return {"status_code": 200}

    def readback(_operation, _scope, _target):
        return _target.__class__(
            scope="SUBSCRIPTION",
            subscription=ExternalSubscription("sub-1", "Changed", 1, "Group"),
        )

    result = _run(config, record, client, calls, write=write, readback=readback)
    assert result["outcome"] == "SUCCESS"
    assert result["management_status"] == TRACKING_OPERATION_STATE_SUCCEEDED
    assert load_tracking_operation(config, result["operation_id"]).state == TRACKING_OPERATION_STATE_SUCCEEDED
    stored = load_tracking_record(config, record.tracking_id)
    assert stored.status == TRACKING_STATUS_ACTIVE
    assert stored.plan_summary["title"] == "Changed"


def test_readback_mismatch_is_a_definite_failure_without_state_mutation(tmp_path: Path) -> None:
    config, record = _seed(tmp_path)
    client, calls = _FakeClient(), []

    result = _run(
        config, record, client, calls, write=lambda _target, _payload: {"status_code": 200},
        readback=lambda _operation, _scope, _target: _target,
    )
    assert result["outcome"] == "DEFINITE_FAILURE"
    assert load_tracking_operation(config, result["operation_id"]).state == "FAILED"
    assert load_tracking_record(config, record.tracking_id).status == record.status


@pytest.mark.parametrize("response", [
    {"status_code": 503},
    {"transport_error": "timeout"},
    {"transport_error": "connection"},
    {"unexpected": "body"},
])
def test_write_timeout_connection_5xx_and_unknown_response_are_outcome_unknown(tmp_path: Path, response: dict) -> None:
    config, record = _seed(tmp_path)
    result = _run(config, record, _FakeClient(), [], write=lambda _target, _payload: response)
    assert result["outcome"] == "OUTCOME_UNKNOWN"
    assert load_tracking_operation(config, result["operation_id"]).state == "OUTCOME_UNKNOWN"


@pytest.mark.parametrize("error", [TimeoutError(), ConnectionError()])
def test_write_transport_exceptions_are_outcome_unknown(tmp_path: Path, error: Exception) -> None:
    config, record = _seed(tmp_path)
    result = _run(config, record, _FakeClient(), [], write=lambda _target, _payload: (_ for _ in ()).throw(error))
    assert result["outcome"] == "OUTCOME_UNKNOWN"


@pytest.mark.parametrize("error", [
    Stage1Error("ab_timeout", "timeout", "ab_management"),
    Stage1Error("ab_connection_failed", "connection", "ab_management"),
    Stage1Error("ab_management_failed", "server", "ab_management", {"status_code": 503}),
])
def test_real_adapter_stage1_transport_errors_are_outcome_unknown(tmp_path: Path, error: Stage1Error) -> None:
    config, record = _seed(tmp_path)
    result = _run(config, record, _FakeClient(), [], write=lambda _target, _payload: (_ for _ in ()).throw(error))
    assert result["outcome"] == "OUTCOME_UNKNOWN"


def test_subscription_delete_verifies_absence_without_touching_local_record(tmp_path: Path) -> None:
    config, record = _seed(tmp_path)
    client, calls = _FakeClient(), []
    result = run_tracking_management(
        config, tracking_id=record.tracking_id, expected_revision=record.revision,
        idempotency_key="delete-subscription", confirm=True,
        operation="DELETE_EXTERNAL", target_scope="SUBSCRIPTION",
        management_client=client,
        write=lambda target, payload: calls.append((target, payload)) or {"status_code": 200},
        readback=lambda _operation, _scope, _target: None,
    )
    assert result["outcome"] == "SUCCESS"
    stored = load_tracking_record(config, record.tracking_id)
    assert stored.status == TRACKING_STATUS_EXTERNAL_DELETED
    assert stored.external_mapping["subscription_id"] == "sub-1"
    assert stored.external_mapping["rss_ids"] == ["7"]
    assert calls[0][1] is None


def test_disabled_subscription_can_still_use_the_file_safe_delete_path(tmp_path: Path) -> None:
    config, record = _seed(tmp_path)
    client = _FakeClient()
    client.read_snapshot = lambda: (
        client.capabilities,
        [ExternalSubscription("sub-1", "Test", 1, "Group", deleted=True)],
        [ExternalRss("7", "Feed", "https://rss.invalid")],
    )
    calls: list[object] = []
    result = run_tracking_management(
        config, tracking_id=record.tracking_id, expected_revision=record.revision,
        idempotency_key="delete-disabled-subscription", confirm=True,
        operation="DELETE_EXTERNAL", target_scope="SUBSCRIPTION", management_client=client,
        write=lambda target, payload: calls.append((target, payload)) or {"status_code": 200},
        readback=lambda _operation, _scope, _target: None,
    )
    assert result["management_status"] == TRACKING_OPERATION_STATE_SUCCEEDED
    assert len(calls) == 1


def test_rss_delete_calls_each_bound_id_and_removes_only_mapping(tmp_path: Path) -> None:
    config, record = _seed(tmp_path)
    client = _FakeClient()
    client.read_snapshot = lambda: (
        client.capabilities,
        [ExternalSubscription("sub-1", "Test", 1, "Group")],
        [ExternalRss("7", "Feed", "https://rss.invalid"), ExternalRss("8", "Feed 2", "https://rss2.invalid")],
    )
    calls = []
    result = run_tracking_management(
        config, tracking_id=record.tracking_id, expected_revision=record.revision,
        idempotency_key="delete-rss", confirm=True,
        operation="DELETE_EXTERNAL", target_scope="ASSOCIATED_RSS",
        management_client=client,
        write=lambda target, payload: calls.append(target) or {"status_code": 204},
        readback=lambda _operation, _scope, _target: ResolvedManagementTarget(scope="ASSOCIATED_RSS"),
    )
    assert result["outcome"] == "SUCCESS"
    assert [item.external_id for target in calls for item in target.rss] == ["7"]
    assert load_tracking_record(config, record.tracking_id).external_mapping["rss_ids"] == []


def test_refresh_success_terminalizes_from_bounded_transport_evidence(tmp_path: Path) -> None:
    config, record = _seed(tmp_path)
    result = run_tracking_management(
        config, tracking_id=record.tracking_id, expected_revision=record.revision,
        idempotency_key="refresh-rss", confirm=True,
        operation="REFRESH_RSS", target_scope="ASSOCIATED_RSS",
        management_client=_FakeClient(),
        write=lambda _target, _payload: {"status_code": 200},
    )
    assert result["management_status"] == "SUCCEEDED"
    assert result["needs_manual"] is False


def test_management_verify_resolves_unknown_without_a_second_write(tmp_path: Path) -> None:
    config, record = _seed(tmp_path)
    client = _FakeClient()
    first = _run(
        config, record, client, [],
        write=lambda _target, _payload: {"transport_error": "timeout"},
    )
    uncertain_record = load_tracking_record(config, record.tracking_id)
    uncertain_operation = load_tracking_operation(config, first["operation_id"])
    assert uncertain_operation.state == "OUTCOME_UNKNOWN"

    # The original title is still present, so the bound title change is
    # definitively known not to have been applied.
    result = recover_tracking_management(
        config, record=uncertain_record, operation=uncertain_operation,
        management_client=client, now="2026-09-09T01:00:00+00:00",
    )
    assert result["outcome"] == "DEFINITE_FAILURE"
    assert result["needs_manual"] is False
    assert load_tracking_operation(config, first["operation_id"]).state == TRACKING_OPERATION_STATE_FAILED


def test_recovered_modify_and_rss_delete_restore_the_operation_previous_status(tmp_path: Path) -> None:
    config, record = _seed(tmp_path)
    modify_client = _FakeClient()
    first = _run(config, record, modify_client, [], write=lambda _target, _payload: {"transport_error": "timeout"})
    modify_client.read_snapshot = lambda: (
        modify_client.capabilities,
        [ExternalSubscription("sub-1", "Changed", 1, "Group")],
        [ExternalRss("7", "Feed", "https://rss.invalid")],
    )
    recovered = recover_tracking_management(
        config, record=load_tracking_record(config, record.tracking_id),
        operation=load_tracking_operation(config, first["operation_id"]), management_client=modify_client,
    )
    assert recovered["outcome"] == "SUCCESS"
    assert load_tracking_record(config, record.tracking_id).status == record.status

    config, record = _seed(tmp_path / "rss")
    delete_client = _FakeClient()
    first = run_tracking_management(
        config, tracking_id=record.tracking_id, expected_revision=record.revision,
        idempotency_key="recover-rss-delete", confirm=True, operation="DELETE_EXTERNAL",
        target_scope="ASSOCIATED_RSS", management_client=delete_client,
        write=lambda _target, _payload: {"transport_error": "timeout"},
    )
    delete_client.read_snapshot = lambda: (delete_client.capabilities, [ExternalSubscription("sub-1", "Test", 1, "Group")], [])
    recovered = recover_tracking_management(
        config, record=load_tracking_record(config, record.tracking_id),
        operation=load_tracking_operation(config, first["operation_id"]), management_client=delete_client,
    )
    assert recovered["outcome"] == "SUCCESS"
    assert load_tracking_record(config, record.tracking_id).status == record.status


def test_management_refresh_recovery_never_infers_success(tmp_path: Path) -> None:
    config, record = _seed(tmp_path)
    first = run_tracking_management(
        config, tracking_id=record.tracking_id, expected_revision=record.revision,
        idempotency_key="refresh-unknown", confirm=True,
        operation="REFRESH_RSS", target_scope="ASSOCIATED_RSS",
        management_client=_FakeClient(),
        write=lambda _target, _payload: {"transport_error": "timeout"},
    )
    result = recover_tracking_management(
        config, record=load_tracking_record(config, record.tracking_id),
        operation=load_tracking_operation(config, first["operation_id"]),
        management_client=_FakeClient(),
    )
    assert result["outcome"] == "OUTCOME_UNKNOWN"
    assert result["needs_manual"] is True
    assert load_tracking_operation(config, first["operation_id"]).state == TRACKING_OPERATION_STATE_RECOVERY_REQUIRED


def test_terminal_same_key_replay_returns_persisted_outcome_without_external_io(tmp_path: Path) -> None:
    config, record = _seed(tmp_path)
    client, calls = _FakeClient(), []
    first = _run(
        config, record, client, calls,
        write=lambda _target, _payload: {"status_code": 200},
        readback=lambda _operation, _scope, _target: ResolvedManagementTarget(
            scope="SUBSCRIPTION", subscription=ExternalSubscription("sub-1", "Changed", 1, "Group")
        ),
    )
    current = load_tracking_record(config, record.tracking_id)
    reads = client.reads
    replay = _run(
        config, record, client, calls,
        write=lambda *_args: (_ for _ in ()).throw(AssertionError("replay must not write")),
        idempotency_key="key-1",
    )
    assert replay == {
        "operation_id": first["operation_id"], "management_status": "SUCCEEDED",
        "outcome": "SUCCESS", "needs_manual": False, "created": False,
    }
    assert client.reads == reads and len(calls) == 0

    with pytest.raises(Stage1Error) as conflict:
        _run(config, current, client, calls, idempotency_key="key-1")
    assert conflict.value.error_type == "tracking_idempotency_conflict"


@pytest.mark.parametrize("operation,scope,extra", [
    ("MODIFY", "SUBSCRIPTION", {"patch": {"title": "Again"}}),
    ("REFRESH_RSS", "ASSOCIATED_RSS", {}),
])
def test_unknown_or_recovery_state_rejects_a_fresh_idempotency_key(tmp_path: Path, operation: str, scope: str, extra: dict) -> None:
    config, record = _seed(tmp_path)
    first = run_tracking_management(
        config, tracking_id=record.tracking_id, expected_revision=record.revision,
        idempotency_key=f"uncertain-{operation}", confirm=True, operation=operation,
        target_scope=scope, management_client=_FakeClient(),
        write=lambda _target, _payload: {"transport_error": "timeout"}, **extra,
    )
    current = load_tracking_record(config, record.tracking_id)
    with pytest.raises(Stage1Error) as error:
        run_tracking_management(
            config, tracking_id=current.tracking_id, expected_revision=current.revision,
            idempotency_key=f"fresh-{operation}", confirm=True, operation=operation,
            target_scope=scope, management_client=_FakeClient(),
            write=lambda *_args: pytest.fail("fresh key must not write"), **extra,
        )
    assert error.value.error_type == "tracking_management_state_conflict"
    assert load_tracking_operation(config, first["operation_id"]).state in {"OUTCOME_UNKNOWN", "RECOVERY_REQUIRED"}


def test_second_repository_write_failure_never_returns_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config, record = _seed(tmp_path)
    original = management_service.compare_and_swap_tracking_operation
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected operation repository failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(management_service, "compare_and_swap_tracking_operation", fail_second)
    result = _run(config, record, _FakeClient(), [], write=lambda _target, _payload: {"status_code": 200},
                  readback=lambda _operation, _scope, _target: ResolvedManagementTarget(
                      scope="SUBSCRIPTION", subscription=ExternalSubscription("sub-1", "Changed", 1, "Group")
                  ))
    assert result["management_status"] == TRACKING_OPERATION_STATE_RECOVERY_REQUIRED
    assert result["needs_manual"] is True
    assert load_tracking_operation(config, result["operation_id"]).state == TRACKING_OPERATION_STATE_RECOVERY_REQUIRED
    assert load_tracking_record(config, record.tracking_id).status == "RECOVERY_REQUIRED"


def test_result_operation_is_persisted_before_record_and_record_fault_compensates_both(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    config, record = _seed(tmp_path)
    events: list[str] = []
    original_operation = management_service.compare_and_swap_tracking_operation
    original_record = management_service.compare_and_swap_tracking_record
    record_calls = 0

    def observe_operation(*args, **kwargs):
        events.append("operation")
        return original_operation(*args, **kwargs)

    def fail_result_record(*args, **kwargs):
        nonlocal record_calls
        record_calls += 1
        events.append("record")
        if record_calls == 2:
            raise OSError("injected result record persistence failure")
        return original_record(*args, **kwargs)

    monkeypatch.setattr(management_service, "compare_and_swap_tracking_operation", observe_operation)
    monkeypatch.setattr(management_service, "compare_and_swap_tracking_record", fail_result_record)
    result = _run(config, record, _FakeClient(), [], write=lambda _target, _payload: {"status_code": 200},
                  readback=lambda _operation, _scope, _target: ResolvedManagementTarget(
                      scope="SUBSCRIPTION", subscription=ExternalSubscription("sub-1", "Changed", 1, "Group"),
                  ))
    assert events[2:4] == ["operation", "record"]
    assert result["management_status"] == "RECOVERY_REQUIRED"
    assert load_tracking_operation(config, result["operation_id"]).state == "RECOVERY_REQUIRED"
    assert load_tracking_record(config, record.tracking_id).status == "RECOVERY_REQUIRED"


def test_recovery_operation_first_record_fault_compensates_both(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config, record = _seed(tmp_path)
    client = _FakeClient()
    first = _run(config, record, client, [], write=lambda _target, _payload: {"transport_error": "timeout"})
    client.read_snapshot = lambda: (
        client.capabilities, [ExternalSubscription("sub-1", "Changed", 1, "Group")],
        [ExternalRss("7", "Feed", "https://rss.invalid")],
    )
    original_record = management_service.compare_and_swap_tracking_record

    def fail_once(*args, **kwargs):
        raise OSError("injected recovery record persistence failure")

    monkeypatch.setattr(management_service, "compare_and_swap_tracking_record", fail_once)
    result = recover_tracking_management(
        config, record=load_tracking_record(config, record.tracking_id),
        operation=load_tracking_operation(config, first["operation_id"]), management_client=client,
    )
    assert result["management_status"] == "RECOVERY_REQUIRED"
    assert load_tracking_operation(config, first["operation_id"]).state == "RECOVERY_REQUIRED"
    # The injected repository remains unwritable, so no stale snapshot may be
    # written over the current verifying record.
    monkeypatch.setattr(management_service, "compare_and_swap_tracking_record", original_record)
    assert load_tracking_record(config, record.tracking_id).status == "VERIFYING_EXTERNAL"
