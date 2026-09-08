from pathlib import Path

from ab_engine.models.management import AutoBangumiCapabilities, ExternalSubscription
from apps.migu_orca_web.tracking_sync_service import run_tracking_sync
from shared.errors import Stage1Error
from storage_engine.controllers.storage_config import load_storage_config
from storage_engine.controllers.tracking_repository import (
    ensure_tracking_record,
    list_tracking_records,
)
from tracking_engine.models.tracking import (
    TRACKING_STATUS_ACTIVE,
    create_tracking_record,
    tracking_id_for_external,
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


def test_external_sync_is_idempotent(tmp_path: Path) -> None:
    config = load_storage_config(tmp_path)
    client = FakeManagementClient([ExternalSubscription("sub-1", "Show", 1, "Group")])

    first = run_tracking_sync(config=config, management_client=client, now="2026-01-01T00:00:00+00:00")
    second = run_tracking_sync(config=config, management_client=client, now="2026-01-02T00:00:00+00:00")

    assert first.sync_status == "COMPLETE"
    assert first.summary.created == 1
    assert second.summary.unchanged == 1
    assert second.summary.updated == 0
    record = list_tracking_records(config).records[0]
    assert record.revision == 1
    assert len(record.audit_events) == 1


def test_unique_local_match_updates_once_and_merges_old_orphan(tmp_path: Path) -> None:
    config = load_storage_config(tmp_path)
    orphan = run_tracking_sync(
        config=config,
        management_client=FakeManagementClient([ExternalSubscription("sub-1", "Show", 1, "Group")]),
        now="2026-01-01T00:00:00+00:00",
    )
    assert orphan.summary.created == 1
    local = create_tracking_record(
        request_id="req-1", status=TRACKING_STATUS_ACTIVE,
        plan_summary={"title": "Show", "season": 1, "subtitle_group": "Group"},
        now="2026-01-01T00:00:00+00:00",
    )
    ensure_tracking_record(config, local)

    result = run_tracking_sync(
        config=config,
        management_client=FakeManagementClient([ExternalSubscription("sub-1", "Show", 1, "Group")]),
        now="2026-01-02T00:00:00+00:00",
    )
    records = {record.tracking_id: record for record in list_tracking_records(config).records}
    assert result.summary.updated == 2
    assert records[local.tracking_id].external_mapping["match_reason"] == "EXACT_FIELDS"
    orphan_id = tracking_id_for_external("legacy_3_1", "subscription", "sub-1")
    assert records[orphan_id].recovery == {"merged_into_tracking_id": local.tracking_id}


def test_external_read_failure_does_not_mark_locals_deleted(tmp_path: Path) -> None:
    config = load_storage_config(tmp_path)
    result = run_tracking_sync(config=config, management_client=FakeManagementClient(fail=True))
    assert result.sync_status == "FAILED"
    assert result.summary.checked == 0
    assert "EXTERNAL_CAPABILITY_FAILED" in result.warnings
