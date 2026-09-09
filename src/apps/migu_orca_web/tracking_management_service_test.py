from __future__ import annotations

from pathlib import Path

import pytest

from ab_engine.models.management import AutoBangumiCapabilities, ExternalRss, ExternalSubscription
from apps.migu_orca_web.tracking_management_service import run_tracking_management
from shared.errors import Stage1Error
from storage_engine.controllers.operation_repository import load_tracking_operation
from storage_engine.controllers.storage_config import load_storage_config
from storage_engine.controllers.tracking_repository import ensure_tracking_record, load_tracking_record
from tracking_engine.models.operation import TRACKING_OPERATION_STATE_IN_PROGRESS, TRACKING_OPERATION_STATE_SUCCEEDED
from tracking_engine.models.tracking import TRACKING_STATUS_ACTIVE, create_external_tracking_record


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
    with pytest.raises(Stage1Error, match="已有管理操作"):
        _run(config, load_tracking_record(config, record.tracking_id), client, calls)
    # The operation is intentionally still in progress until US-242/244 recovery.
    assert client.reads == 0
    assert len(calls) == 1


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
