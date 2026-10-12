from __future__ import annotations

"""Issue #183: server-resolved bounded read-only check of a pending submit."""

from dataclasses import replace
from pathlib import Path

import pytest

from ab_engine.models.management import ExternalRss, ExternalSubscription
from apps.migu_orca_web.schemas import TrackingCheckPayload
from apps.migu_orca_web.tracking_check_service import run_saved_tracking_check
from apps.migu_orca_web.tracking_external_check import CheckPolicy, single_flight_check
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
    load_tracking_operation,
)
from storage_engine.controllers.tracking_repository import (
    compare_and_swap_tracking_record,
    load_tracking_record,
)
from tracking_engine.controllers.submit import (
    CONFIRM_REASON_AMBIGUOUS,
    CONFIRM_REASON_CONNECTION_CHANGED,
    CONFIRM_REASON_NOT_FOUND,
)
from tracking_engine.models.operation import (
    TRACKING_OPERATION_STATE_IN_PROGRESS,
    TRACKING_OPERATION_STATE_PREPARED,
    TRACKING_OPERATION_STATE_SUCCEEDED,
)
from tracking_engine.models.tracking import (
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_RECOVERY_REQUIRED,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
)

RSS_URL = "https://rss.invalid/feed"


def _payload(record, **overrides) -> TrackingCheckPayload:
    values = {
        "tracking_id": record.tracking_id,
        "expected_revision": record.revision,
        "storage_dir": "storage",
    }
    values.update(overrides)
    return TrackingCheckPayload(**values)


def _matching_snapshot(external_id: str = "external-1"):
    return (
        ExternalSubscription(external_id, "芙莉莲", 1, "Group", rss_urls=(RSS_URL,), rss_ids=("rss-1",)),
        ExternalRss("rss-1", "芙莉莲", RSS_URL),
    )


def test_check_confirms_the_exact_subscription_and_persists_active(monkeypatch, tmp_path: Path) -> None:
    config_root = tmp_path / "private"
    config, record, saved, op, verifying = _bound_submit_scenario(
        monkeypatch, tmp_path, TRACKING_OPERATION_STATE_IN_PROGRESS
    )
    external, rss = _matching_snapshot()

    result = run_saved_tracking_check(
        _payload(verifying),
        config_root=config_root,
        management_client=ReadOnlyClient([external], rss_items=[rss]),
    )

    assert result["action"] == "VERIFY_EXTERNAL"
    assert result["outcome"] == TRACKING_STATUS_ACTIVE
    assert result["needs_manual"] is False
    assert result["verification_reason"] is None
    after = load_tracking_record(config, record.tracking_id)
    assert after.status == TRACKING_STATUS_ACTIVE
    assert after.external_mapping is not None
    assert after.external_mapping["subscription_id"] == "external-1"
    assert load_tracking_operation(config, op.operation_id).state == TRACKING_OPERATION_STATE_SUCCEEDED


def test_check_reports_a_legal_miss_as_pending_with_a_proven_reason(monkeypatch, tmp_path: Path) -> None:
    config, record, saved, op, verifying = _bound_submit_scenario(
        monkeypatch, tmp_path, TRACKING_OPERATION_STATE_IN_PROGRESS
    )

    result = run_saved_tracking_check(
        _payload(verifying), config_root=tmp_path / "private", management_client=ReadOnlyClient()
    )

    assert result["outcome"] == TRACKING_STATUS_RECOVERY_REQUIRED
    assert result["needs_manual"] is True
    assert result["verification_reason"] == CONFIRM_REASON_NOT_FOUND
    assert load_tracking_record(config, record.tracking_id).external_mapping is None


def test_check_retries_transient_reads_inside_the_injected_budget(monkeypatch, tmp_path: Path) -> None:
    class _FlakyClient(ReadOnlyClient):
        def read_snapshot(self, *, deadline=None):
            self.reads += 1
            if self.reads == 1:
                raise Stage1Error("ab_connection_failed", "连接失败", "check", {"category": "connection"})
            return self.capabilities, self.subscriptions, self.rss_items

    config, record, saved, op, verifying = _bound_submit_scenario(
        monkeypatch, tmp_path, TRACKING_OPERATION_STATE_IN_PROGRESS
    )
    external, rss = _matching_snapshot()
    client = _FlakyClient([external], rss_items=[rss])
    slept: list[float] = []

    result = run_saved_tracking_check(
        _payload(verifying),
        config_root=tmp_path / "private",
        management_client=client,
        read_policy=CheckPolicy(sleep=slept.append, monotonic=lambda: 0.0),
    )

    assert result["outcome"] == TRACKING_STATUS_ACTIVE
    assert client.reads == 2
    assert slept == [CheckPolicy().backoff_seconds]


def test_check_never_rebinds_a_replaced_saved_connection(monkeypatch, tmp_path: Path) -> None:
    """Issue #183: a different saved instance is reported, never used."""
    config, record, saved, op, verifying = _bound_submit_scenario(
        monkeypatch, tmp_path, TRACKING_OPERATION_STATE_IN_PROGRESS
    )
    # Replace the saved connection: new ref, so the old operation binding is gone.
    replaced = AutoBangumiConfigRepository(tmp_path / "private")
    replaced.save(
        build_stored_autobangumi_config(
            {"auth_mode": "password", "base_url": "http://other.invalid", "username": "u", "password": "p"}
        ),
        expected_configuration_revision=saved.configuration_revision,
    )
    external, rss = _matching_snapshot()
    client = ReadOnlyClient([external], rss_items=[rss])

    result = run_saved_tracking_check(
        _payload(verifying), config_root=tmp_path / "private", management_client=client
    )

    assert result["outcome"] == TRACKING_STATUS_VERIFYING_EXTERNAL
    assert result["needs_manual"] is True
    assert result["verification_reason"] == CONFIRM_REASON_CONNECTION_CHANGED
    assert client.reads == 0, "a replaced connection must not be read at all"
    assert load_tracking_record(config, record.tracking_id).status == TRACKING_STATUS_VERIFYING_EXTERNAL


def test_check_rejects_a_stale_revision(monkeypatch, tmp_path: Path) -> None:
    config, record, saved, op, verifying = _bound_submit_scenario(
        monkeypatch, tmp_path, TRACKING_OPERATION_STATE_IN_PROGRESS
    )

    with pytest.raises(Stage1Error) as error:
        run_saved_tracking_check(
            _payload(verifying, expected_revision=verifying.revision + 1),
            config_root=tmp_path / "private",
            management_client=ReadOnlyClient(),
        )

    assert error.value.error_type == "tracking_revision_conflict"


def test_check_rejects_a_record_without_a_pending_submit(monkeypatch, tmp_path: Path) -> None:
    config, record, saved, op, verifying = _bound_submit_scenario(
        monkeypatch, tmp_path, TRACKING_OPERATION_STATE_IN_PROGRESS
    )
    # A management operation is not a pending submission: its recovery entry stays
    # the existing one and the check must refuse instead of guessing.
    management, created = bind_tracking_operation(
        config,
        tracking_id=record.tracking_id,
        operation="MODIFY",
        idempotency_key="modify-1",
        expected_revision=record.revision,
        request_fingerprint=record.request_fingerprint or "fingerprint",
        now="2026-09-14T00:00:00+00:00",
        connection_ref=op.connection_ref,
        target_scope="SUBSCRIPTION",
        previous_tracking_status=TRACKING_STATUS_ACTIVE,
        expected_external_fingerprint="sha256:" + "a" * 64,
    )
    assert created
    assert management.state == TRACKING_OPERATION_STATE_PREPARED
    rebound = compare_and_swap_tracking_record(
        config,
        record.tracking_id,
        base_revision=verifying.revision,
        record=replace(verifying, current_operation_id=management.operation_id, revision=verifying.revision + 1),
    )

    with pytest.raises(Stage1Error) as error:
        run_saved_tracking_check(
            _payload(rebound), config_root=tmp_path / "private", management_client=ReadOnlyClient()
        )

    assert error.value.error_type == "tracking_state_conflict"


def test_check_reports_an_ambiguous_snapshot_instead_of_not_found(monkeypatch, tmp_path: Path) -> None:
    """Issue #183 review: an ambiguous snapshot has its own proven reason."""
    config, record, saved, op, verifying = _bound_submit_scenario(
        monkeypatch, tmp_path, TRACKING_OPERATION_STATE_IN_PROGRESS
    )
    external = ExternalSubscription("external-1", "芙莉莲", 1, "Group", rss_urls=(RSS_URL,), rss_ids=("rss-1",))
    duplicated = [
        ExternalRss("rss-1", "芙莉莲", RSS_URL),
        ExternalRss("rss-2", "芙莉莲副本", RSS_URL),
    ]

    result = run_saved_tracking_check(
        _payload(verifying),
        config_root=tmp_path / "private",
        management_client=ReadOnlyClient([external], rss_items=duplicated),
    )

    assert result["outcome"] == TRACKING_STATUS_RECOVERY_REQUIRED
    assert result["verification_reason"] == CONFIRM_REASON_AMBIGUOUS
    assert load_tracking_record(config, record.tracking_id).last_error["reason_code"] == CONFIRM_REASON_AMBIGUOUS


def test_check_holds_the_saved_connection_lease_while_reading(monkeypatch, tmp_path: Path) -> None:
    """Issue #183 review: the bound instance cannot be replaced mid-read."""
    config, record, saved, op, verifying = _bound_submit_scenario(
        monkeypatch, tmp_path, TRACKING_OPERATION_STATE_IN_PROGRESS
    )
    external, rss = _matching_snapshot()
    repository = AutoBangumiConfigRepository(tmp_path / "private")
    blocked: list[str] = []

    class _ReplacingClient(ReadOnlyClient):
        def read_snapshot(self, *, deadline=None):
            try:
                repository.save(
                    build_stored_autobangumi_config(
                        {"auth_mode": "password", "base_url": "http://other.invalid", "username": "u", "password": "p"}
                    ),
                    expected_configuration_revision=saved.configuration_revision,
                )
            except Stage1Error as exc:
                blocked.append(exc.error_type)
            return self.capabilities, self.subscriptions, self.rss_items

    result = run_saved_tracking_check(
        _payload(verifying),
        config_root=tmp_path / "private",
        management_client=_ReplacingClient([external], rss_items=[rss]),
    )

    assert result["outcome"] == TRACKING_STATUS_ACTIVE
    assert blocked == ["connection_in_use"], blocked


def test_check_refuses_a_stale_revision_before_the_connection_branch(monkeypatch, tmp_path: Path) -> None:
    """Issue #183 review: a stale check is a 409, never a 200 binding report."""
    config, record, saved, op, verifying = _bound_submit_scenario(
        monkeypatch, tmp_path, TRACKING_OPERATION_STATE_IN_PROGRESS
    )
    # A replaced connection AND a stale revision: the revision must win.
    AutoBangumiConfigRepository(tmp_path / "private").save(
        build_stored_autobangumi_config(
            {"auth_mode": "password", "base_url": "http://other.invalid", "username": "u", "password": "p"}
        ),
        expected_configuration_revision=saved.configuration_revision,
    )

    with pytest.raises(Stage1Error) as error:
        run_saved_tracking_check(
            _payload(verifying, expected_revision=verifying.revision + 1),
            config_root=tmp_path / "private",
            management_client=ReadOnlyClient(),
        )

    assert error.value.error_type == "tracking_revision_conflict"


def test_check_refuses_a_concurrent_check_for_the_same_record(monkeypatch, tmp_path: Path) -> None:
    """Issue #183 review: one effective check per record (server-side防重)."""
    config, record, saved, op, verifying = _bound_submit_scenario(
        monkeypatch, tmp_path, TRACKING_OPERATION_STATE_IN_PROGRESS
    )
    client = ReadOnlyClient()

    with single_flight_check(record.tracking_id), pytest.raises(Stage1Error) as error:
        run_saved_tracking_check(
            _payload(verifying), config_root=tmp_path / "private", management_client=client
        )

    assert error.value.error_type == "tracking_check_in_progress"
    assert client.reads == 0, "a refused concurrent check must not read Auto Bangumi"
