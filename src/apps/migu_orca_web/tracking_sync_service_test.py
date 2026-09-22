from dataclasses import asdict, replace
from pathlib import Path

from ab_engine.models.management import AutoBangumiCapabilities, ExternalSubscription
from apps.migu_orca_web.tracking_sync_service import run_tracking_sync
from shared.errors import Stage1Error
from storage_engine.controllers.operation_repository import bind_tracking_operation
from storage_engine.controllers.storage_config import load_storage_config
from storage_engine.controllers.tracking_repository import (
    ensure_tracking_record,
    list_tracking_records,
)
from tracking_engine.models.tracking import (
    TRACKING_STATUS_ACTIVE,
    create_tracking_record,
)

CAPABILITIES = AutoBangumiCapabilities(
    probe_status="VERIFIED", version="3.1.18", adapter="legacy_3_1",
    subscription_list="SUPPORTED", subscription_detail="SUPPORTED",
    rss_list="SUPPORTED", external_verify="SUPPORTED",
)


class FakeManagementClient:
    def __init__(self, subscriptions=(), *, fail=False):
        self.subscriptions = list(subscriptions)
        self.fail = fail

    def read_snapshot(self):
        if self.fail:
            raise Stage1Error("ab_timeout", "外部读取失败", "test")
        return CAPABILITIES, self.subscriptions, []


def test_unmapped_external_subscription_is_counted_but_never_persisted(tmp_path: Path) -> None:
    """Issue #88: a stranger in Auto Bangumi never enters 我的追番."""
    config = load_storage_config(tmp_path)
    client = FakeManagementClient([ExternalSubscription("sub-1", "Show", 1, "Group")])

    first = run_tracking_sync(config=config, management_client=client, now="2026-01-01T00:00:00+00:00")
    second = run_tracking_sync(config=config, management_client=client, now="2026-01-02T00:00:00+00:00")

    assert first.sync_status == "COMPLETE"
    assert first.summary.created == 0
    assert first.summary.ignored == 1
    assert second.summary.ignored == 1
    assert second.summary.created == 0
    assert list_tracking_records(config).records == []


def test_a_released_subscription_is_never_reimported(tmp_path: Path) -> None:
    """Issue #88: after local deletion the external object stays unmanaged."""
    config = load_storage_config(tmp_path)

    result = run_tracking_sync(
        config=config,
        management_client=FakeManagementClient([ExternalSubscription("sub-1", "Show", 1, "Group")]),
    )

    assert result.summary.ignored == 1
    assert list_tracking_records(config).records == []


def test_a_similar_local_plan_never_adopts_an_external_subscription(tmp_path: Path) -> None:
    """Issue #88: identical title/season/group/RSS is not ownership evidence."""
    config = load_storage_config(tmp_path)
    from storage_engine.controllers.request_repository import save_request_snapshot
    save_request_snapshot(config, {
        "request_id": "legacy-rss", "confirmable_config": {"selected_rss_url": "expected-rss"},
    })
    local_record = create_tracking_record(
        request_id="legacy-rss", status=TRACKING_STATUS_ACTIVE,
        plan_summary={"title": "Show", "season": 1, "subtitle_group": "Group"},
    )
    ensure_tracking_record(config, local_record)

    result = run_tracking_sync(
        config=config,
        management_client=FakeManagementClient([ExternalSubscription(
            "sub-1", "Show", 1, "Group", rss_urls=("expected-rss",),
        )]),
    )

    records = {record.tracking_id: record for record in list_tracking_records(config).records}
    assert result.summary.ignored == 1
    assert result.summary.updated == 0
    assert records[local_record.tracking_id].external_mapping is None
    assert records[local_record.tracking_id].status == TRACKING_STATUS_ACTIVE


def test_a_mapped_record_is_updated_once_from_its_exact_mapping(tmp_path: Path) -> None:
    """Issue #88: only an exact mapping refreshes a local record, idempotently."""
    config = load_storage_config(tmp_path)
    local = replace(
        create_tracking_record(
            request_id="req-1", status=TRACKING_STATUS_ACTIVE,
            plan_summary={"title": "Show", "season": 1, "subtitle_group": "Group"},
            now="2026-01-01T00:00:00+00:00",
        ),
        external_mapping={"subscription_id": "sub-1"},
    )
    ensure_tracking_record(config, local)

    result = run_tracking_sync(
        config=config,
        management_client=FakeManagementClient([ExternalSubscription("sub-1", "Show", 1, "Group")]),
        now="2026-01-02T00:00:00+00:00",
    )
    records = {record.tracking_id: record for record in list_tracking_records(config).records}
    assert result.summary.updated == 1
    assert records[local.tracking_id].external_mapping["match_reason"] == "EXTERNAL_ID"

    again = run_tracking_sync(
        config=config,
        management_client=FakeManagementClient([ExternalSubscription("sub-1", "Show", 1, "Group")]),
        now="2026-01-03T00:00:00+00:00",
    )
    assert again.summary.unchanged == 1
    assert again.summary.updated == 0


def test_external_read_failure_does_not_mark_locals_deleted(tmp_path: Path) -> None:
    config = load_storage_config(tmp_path)
    result = run_tracking_sync(config=config, management_client=FakeManagementClient(fail=True))
    assert result.sync_status == "FAILED"
    assert result.summary.checked == 0
    assert "EXTERNAL_CAPABILITY_FAILED" in result.warnings


def test_saved_sync_partial_capability_does_not_write(tmp_path: Path) -> None:
    config = load_storage_config(tmp_path)
    partial = AutoBangumiCapabilities(
        probe_status="PARTIAL", version="3.1.18", adapter="legacy_3_1",
        subscription_list="SUPPORTED", subscription_detail="UNKNOWN",
        rss_list="UNKNOWN", external_verify="UNKNOWN",
    )
    client = FakeManagementClient([ExternalSubscription("sub-1", "Show", 1, "Group")])
    client.read_snapshot = lambda: (partial, client.subscriptions, [])
    result = run_tracking_sync(
        config=config, management_client=client,
        connection_ref="11111111-1111-4111-8111-111111111111",
    )
    assert result.sync_status == "FAILED"
    assert result.summary.checked == 0
    assert list_tracking_records(config).records == []


def test_saved_sync_preserves_record_with_unresolved_operation(tmp_path: Path) -> None:
    config = load_storage_config(tmp_path)
    ref = "11111111-1111-4111-8111-111111111111"
    record = replace(
        create_tracking_record(
            request_id="pending-request", status=TRACKING_STATUS_ACTIVE,
            plan_summary={"title": "Show", "season": 1, "subtitle_group": "Group"},
        ),
        external_mapping={"subscription_id": "sub-1", "connection_ref": ref},
    )
    record, _ = ensure_tracking_record(config, record)
    operation, _ = bind_tracking_operation(
        config, tracking_id=record.tracking_id, operation="SUBMIT",
        idempotency_key="pending-sync-key", expected_revision=record.revision,
        request_fingerprint="fingerprint", connection_ref=ref,
    )
    from storage_engine.controllers.tracking_repository import compare_and_swap_tracking_record
    compare_and_swap_tracking_record(
        config, record.tracking_id, record.revision,
        record.__class__(**{**record.__dict__, "revision": 2, "current_operation_id": operation.operation_id}),
    )
    before = list_tracking_records(config).records[0]
    result = run_tracking_sync(
        config=config,
        management_client=FakeManagementClient([ExternalSubscription("sub-1", "Show", 1, "Group")]),
        connection_ref=ref,
    )
    after = list_tracking_records(config).records[0]
    assert result.summary.unchanged == 1
    assert result.summary.updated == 0
    assert after.status == before.status
    assert after.external_mapping == before.external_mapping
    assert after.current_operation_id == operation.operation_id


def test_saved_sync_duplicate_external_id_never_persists_conflict_record(tmp_path: Path) -> None:
    config = load_storage_config(tmp_path)
    existing = replace(create_tracking_record(
        request_id="req-1", status=TRACKING_STATUS_ACTIVE,
        plan_summary={"title": "Show", "season": 1, "subtitle_group": "Group"},
    ), external_mapping={"subscription_id": "sub-1", "connection_ref": "11111111-1111-4111-8111-111111111111"})
    ensure_tracking_record(config, existing)
    duplicate = ExternalSubscription("sub-1", "Show", 1, "Group")
    result = run_tracking_sync(
        config=config, connection_ref="11111111-1111-4111-8111-111111111111",
        management_client=FakeManagementClient([duplicate, duplicate]),
    )
    records = list_tracking_records(config).records
    assert "EXTERNAL_MATCH_CONFLICT" in result.warnings
    assert len(records) == 1
    assert records[0].tracking_id == existing.tracking_id


def test_saved_sync_unproven_match_only_protects_affected_local(tmp_path: Path) -> None:
    config = load_storage_config(tmp_path)
    ref = "11111111-1111-4111-8111-111111111111"
    affected = replace(create_tracking_record(
        request_id="req-affected", status=TRACKING_STATUS_ACTIVE,
        plan_summary={"title": "Show", "season": 1, "subtitle_group": "Group"},
    ), external_mapping={})
    healthy = replace(create_tracking_record(
        request_id="req-healthy", status=TRACKING_STATUS_ACTIVE,
        plan_summary={"title": "Other", "season": 1, "subtitle_group": "Group"},
    ), external_mapping={"subscription_id": "sub-missing", "connection_ref": ref})
    ensure_tracking_record(config, affected)
    ensure_tracking_record(config, healthy)
    result = run_tracking_sync(
        config=config, connection_ref=ref,
        management_client=FakeManagementClient([
            ExternalSubscription("sub-a-1", "Show", 1, "Group"),
            ExternalSubscription("sub-a-2", "Show", 1, "Group"),
        ]),
    )
    records = {record.tracking_id: record for record in list_tracking_records(config).records}
    assert "EXTERNAL_MATCH_UNPROVEN" in result.warnings
    assert records[affected.tracking_id].status == TRACKING_STATUS_ACTIVE
    assert records[healthy.tracking_id].status == "EXTERNAL_DELETED"

def test_sync_summary_matches_the_published_contract(tmp_path: Path) -> None:
    """Issue #88: the safe counts (including ignored) are the strict DTO shape."""
    from apps.migu_orca_web.api_contract import TrackingSyncSummaryDTO

    config = load_storage_config(tmp_path)
    result = run_tracking_sync(
        config=config,
        management_client=FakeManagementClient(
            [ExternalSubscription("sub-1", "Show", 1, "Group")]
        ),
    )

    TrackingSyncSummaryDTO.model_validate(asdict(result.summary))
    assert result.summary.ignored == 1
    assert result.summary.created == 0
