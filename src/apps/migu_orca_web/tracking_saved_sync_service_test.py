import json
from dataclasses import asdict, replace
from pathlib import Path
from threading import Event, Thread

import pytest
from pydantic import ValidationError

from ab_engine.models.management import AutoBangumiCapabilities, ExternalSubscription
from apps.migu_orca_web.schemas import SavedTrackingSyncInput
from apps.migu_orca_web.tracking_saved_sync_service import run_saved_tracking_sync
from shared.errors import Stage1Error
from storage_engine.controllers.autobangumi_config_repository import (
    AutoBangumiConfigRepository,
    build_stored_autobangumi_config,
)
from storage_engine.controllers.operation_repository import (
    bind_tracking_operation,
    compare_and_swap_tracking_operation,
)
from storage_engine.controllers.request_repository import save_request_snapshot
from storage_engine.controllers.storage_config import load_storage_config
from storage_engine.controllers.tracking_repository import ensure_tracking_record, list_tracking_records
from tracking_engine.models.operation import (
    TRACKING_OPERATION_STATE_IN_PROGRESS,
    TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
    TRACKING_OPERATION_STATE_PREPARED,
    TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
    transition_tracking_operation,
)
from tracking_engine.models.tracking import (
    TRACKING_STATUS_ACTIVE,
    create_tracking_record,
)


class _Client:
    def __init__(self):
        self.subscriptions = [ExternalSubscription("sub-1", "Show", 1, "Group")]

    def read_snapshot(self, *, deadline=None):
        return (
            AutoBangumiCapabilities(
                probe_status="VERIFIED", version="3.1.18", adapter="legacy_3_1",
                subscription_list="SUPPORTED", subscription_detail="SUPPORTED",
                rss_list="SUPPORTED", external_verify="SUPPORTED",
            ),
            self.subscriptions,
            [],
        )


def _save_config(root: Path, *, password: str = "p", username: str = "u"):
    return AutoBangumiConfigRepository(root).save(
        build_stored_autobangumi_config({
            "auth_mode": "password", "base_url": "http://ab.test",
            "username": username, "password": password,
        }), expected_configuration_revision=AutoBangumiConfigRepository(root).load().configuration_revision,
    )


def _payload(record) -> SavedTrackingSyncInput:
    return SavedTrackingSyncInput(
        connection_ref=str(record.connection_ref),
        configuration_revision=record.configuration_revision,
        confirm=True,
        storage_dir=None,
    )


def test_saved_sync_binds_mapping_to_requested_connection(monkeypatch, tmp_path: Path) -> None:
    config_root = tmp_path / "private"
    repo = AutoBangumiConfigRepository(config_root)
    record = repo.save(
        build_stored_autobangumi_config({
            "auth_mode": "password", "base_url": "http://ab.test",
            "username": "u", "password": "p",
        }), expected_configuration_revision=0,
    )
    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_saved_sync_service.create_management_client",
        lambda *_args, **_kwargs: _Client(),
    )
    monkeypatch.setattr("apps.migu_orca_web.services._WEB_STORAGE_ROOT", tmp_path / "business")
    business_config = load_storage_config(tmp_path / "business")
    # Issue #88: only a record this product already controls is synced; the
    # mapping stays bound to the connection that owns it.
    local = replace(
        create_tracking_record(
            request_id="req-sync", status=TRACKING_STATUS_ACTIVE,
            plan_summary={"title": "Show", "season": 1, "subtitle_group": "Group"},
        ),
        external_mapping={"subscription_id": "sub-1", "connection_ref": str(record.connection_ref)},
    )
    ensure_tracking_record(business_config, local)
    result = run_saved_tracking_sync(
        SavedTrackingSyncInput(
            connection_ref=str(record.connection_ref),
            configuration_revision=record.configuration_revision,
            confirm=True,
            storage_dir=None,
        ),
        config_root=config_root,
    )
    assert result.summary.updated == 1
    mapping = list_tracking_records(business_config).records[0].external_mapping
    assert mapping["connection_ref"] == str(record.connection_ref)
    assert mapping["schema_version"] == 2


def test_saved_sync_rejects_stale_generation() -> None:
    with pytest.raises(ValidationError):
        SavedTrackingSyncInput(
            connection_ref="11111111-1111-4111-8111-111111111111",
            configuration_revision=True,
            confirm=True,
        )


def test_saved_sync_stale_ref_rejects_without_constructing_client(monkeypatch, tmp_path: Path) -> None:
    first = _save_config(tmp_path / "private")
    second = _save_config(tmp_path / "private", password="new")
    calls = 0

    def factory(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return _Client()

    monkeypatch.setattr("apps.migu_orca_web.tracking_saved_sync_service.create_management_client", factory)
    with pytest.raises(Stage1Error, match="已变化"):
        run_saved_tracking_sync(
            SavedTrackingSyncInput(connection_ref=str(first.connection_ref), configuration_revision=second.configuration_revision, confirm=True),
            config_root=tmp_path / "private",
        )
    assert calls == 0
    with pytest.raises(Stage1Error, match="已变化"):
        run_saved_tracking_sync(
            SavedTrackingSyncInput(connection_ref=str(second.connection_ref), configuration_revision=first.configuration_revision, confirm=True),
            config_root=tmp_path / "private",
        )
    assert calls == 0
    assert second.configuration_revision == 2


def test_saved_sync_ambiguous_rss_match_preserves_old_record_bytes(monkeypatch, tmp_path: Path) -> None:
    private = tmp_path / "private"
    record = _save_config(private)
    business = tmp_path / "business"
    monkeypatch.setattr("apps.migu_orca_web.services._WEB_STORAGE_ROOT", business)
    config = load_storage_config(business)
    request = {
        "request_id": "req-rss-ambiguous",
        "confirmable_config": {"selected_rss_url": "http://mikan.test/rss/group"},
    }
    save_request_snapshot(config, request)
    local = replace(
        create_tracking_record(
            request_id=request["request_id"], status=TRACKING_STATUS_ACTIVE,
            plan_summary={"title": "Show", "season": 1, "subtitle_group": "Group"},
        ),
            external_mapping={
                "schema_version": 2, "adapter": "legacy_3_1", "subscription_id": "new-1",
                "rss_ids": [], "match_reason": "EXTERNAL_ID", "external_deleted": False,
                "enabled": True, "missing_sync_count": 0, "last_verified_at": None,
                "connection_ref": str(record.connection_ref),
            },
    )
    ensure_tracking_record(config, local)
    other_request = {"request_id": "req-rss-ambiguous-2", "confirmable_config": request["confirmable_config"]}
    save_request_snapshot(config, other_request)
    other = replace(
        create_tracking_record(
            request_id=other_request["request_id"], status=TRACKING_STATUS_ACTIVE,
            plan_summary={"title": "Show", "season": 1, "subtitle_group": "Group"},
        ),
        external_mapping={
            "subscription_id": "new-1", "connection_ref": str(record.connection_ref),
        },
    )
    ensure_tracking_record(config, other)
    before = (business / "tracking" / f"{local.tracking_id}.json").read_bytes()

    class AmbiguousClient:
        def read_snapshot(self, *, deadline=None):
            caps = AutoBangumiCapabilities(
                probe_status="VERIFIED", version="3.1.18", adapter="legacy_3_1",
                subscription_list="SUPPORTED", subscription_detail="SUPPORTED",
                rss_list="SUPPORTED", external_verify="SUPPORTED",
            )
            return caps, [
                ExternalSubscription("new-1", "Show", 1, "Group", rss_urls=("http://mikan.test/rss/group",), rss_ids=("rss-1",)),
                ExternalSubscription("new-2", "Show", 1, "Group", rss_urls=("http://mikan.test/rss/group",), rss_ids=("rss-2",)),
            ], []

    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_saved_sync_service.create_management_client",
        lambda *_args, **_kwargs: AmbiguousClient(),
    )
    result = run_saved_tracking_sync(_payload(record), config_root=private)
    after = (business / "tracking" / f"{local.tracking_id}.json").read_bytes()
    assert "AMBIGUOUS_EXTERNAL_MATCH" in result.warnings
    assert after == before


def test_saved_sync_dual_instances_same_external_id_are_isolated(monkeypatch, tmp_path: Path) -> None:
    private = tmp_path / "private"
    first = _save_config(private, password="one")
    business = tmp_path / "business"
    monkeypatch.setattr("apps.migu_orca_web.services._WEB_STORAGE_ROOT", business)
    config = load_storage_config(business)
    clients = []

    class Client(_Client):
        pass

    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_saved_sync_service.create_management_client",
        lambda *_args, **_kwargs: clients.append(Client()) or clients[-1],
    )
    first_local = replace(
        create_tracking_record(
            request_id="req-first", status=TRACKING_STATUS_ACTIVE,
            plan_summary={"title": "Show", "season": 1, "subtitle_group": "Group"},
        ),
        external_mapping={"subscription_id": "sub-1", "connection_ref": str(first.connection_ref)},
    )
    ensure_tracking_record(config, first_local)
    run_saved_tracking_sync(_payload(first), config_root=private)
    first_path = business / "tracking" / f"{first_local.tracking_id}.json"
    first_bytes = first_path.read_bytes()

    second = _save_config(private, password="two")
    second_local = replace(
        create_tracking_record(
            request_id="req-second", status=TRACKING_STATUS_ACTIVE,
            plan_summary={"title": "Show", "season": 1, "subtitle_group": "Group"},
        ),
        external_mapping={"subscription_id": "sub-1", "connection_ref": str(second.connection_ref)},
    )
    ensure_tracking_record(config, second_local)
    run_saved_tracking_sync(_payload(second), config_root=private)

    records = list_tracking_records(config).records
    refs = {record.external_mapping.get("connection_ref") for record in records}
    assert str(first.connection_ref) in refs
    assert str(second.connection_ref) in refs
    # The first connection's own record bytes never change because of the second.
    assert first_path.read_bytes() == first_bytes


def test_saved_sync_partial_or_failed_snapshot_preserves_existing_record(monkeypatch, tmp_path: Path) -> None:
    private = tmp_path / "private"
    saved = _save_config(private)
    business = tmp_path / "business"
    monkeypatch.setattr("apps.migu_orca_web.services._WEB_STORAGE_ROOT", business)
    config = load_storage_config(business)
    local = replace(
        create_tracking_record(
            request_id="sync-preserved", status=TRACKING_STATUS_ACTIVE,
            plan_summary={"title": "Show", "season": 1, "subtitle_group": "Group"},
        ),
        external_mapping={"subscription_id": "sub-1", "connection_ref": str(saved.connection_ref)},
    )
    ensure_tracking_record(config, local)
    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_saved_sync_service.create_management_client",
        lambda *_args, **_kwargs: _Client(),
    )
    run_saved_tracking_sync(_payload(saved), config_root=private)
    path = business / "tracking" / f"{local.tracking_id}.json"
    before = path.read_bytes()

    class Broken(_Client):
        def read_snapshot(self, *, deadline=None):
            raise RuntimeError("secret-password must not escape")

    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_saved_sync_service.create_management_client",
        lambda *_args, **_kwargs: Broken(),
    )
    result = run_saved_tracking_sync(_payload(saved), config_root=private)
    assert result.sync_status == "FAILED"
    assert path.read_bytes() == before
    assert "secret-password" not in repr(result)


@pytest.mark.parametrize(
    ("probe_status", "subscription_list"),
    [("PARTIAL", "SUPPORTED"), ("FAILED", "SUPPORTED"), ("VERIFIED", "UNKNOWN")],
)
def test_saved_sync_degraded_capability_preserves_existing_record(
    monkeypatch, tmp_path: Path, probe_status: str, subscription_list: str,
) -> None:
    private = tmp_path / "private"
    saved = _save_config(private)
    business = tmp_path / "business"
    monkeypatch.setattr("apps.migu_orca_web.services._WEB_STORAGE_ROOT", business)
    config = load_storage_config(business)
    from storage_engine.controllers.tracking_repository import ensure_tracking_record
    ensure_tracking_record(config, create_tracking_record(
        request_id="partial-local", status=TRACKING_STATUS_ACTIVE,
        plan_summary={"title": "Show", "season": 1, "subtitle_group": "Group"},
    ))
    path = next((business / "tracking").glob("*.json"))
    before = path.read_bytes()
    partial = AutoBangumiCapabilities(
        probe_status=probe_status, version="3.1.18", adapter="legacy_3_1",
        subscription_list=subscription_list, subscription_detail="UNKNOWN",
        rss_list="UNKNOWN", external_verify="UNKNOWN",
    )
    client = _Client()
    reads = 0
    def read_once():
        nonlocal reads
        reads += 1
        return partial, partial_subscriptions, []
    partial_subscriptions = [ExternalSubscription("partial-sub", "Show", 1, "Group")]
    client.read_snapshot = read_once
    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_saved_sync_service.create_management_client",
        lambda *_args, **_kwargs: client,
    )
    result = run_saved_tracking_sync(_payload(saved), config_root=private)
    assert result.sync_status == "FAILED"
    assert result.summary.checked == 0
    assert result.capabilities.probe_status == probe_status
    assert reads == 1
    assert path.read_bytes() == before
    replacement = AutoBangumiConfigRepository(private).save(
        build_stored_autobangumi_config({"auth_mode": "password", "base_url": "http://ab.test", "username": "u", "password": "x"}),
        expected_configuration_revision=saved.configuration_revision,
    )
    assert replacement.configuration_revision == saved.configuration_revision + 1


def test_saved_sync_lease_blocks_save_and_delete_then_releases(monkeypatch, tmp_path: Path) -> None:
    private = tmp_path / "private"
    saved = _save_config(private)
    started, release = Event(), Event()

    class Blocking(_Client):
        def read_snapshot(self, *, deadline=None):
            started.set()
            release.wait(timeout=5)
            return super().read_snapshot()

    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_saved_sync_service.create_management_client",
        lambda *_args, **_kwargs: Blocking(),
    )
    monkeypatch.setattr("apps.migu_orca_web.services._WEB_STORAGE_ROOT", tmp_path / "business")
    worker_result = []
    worker_errors = []

    def run_worker():
        try:
            worker_result.append(run_saved_tracking_sync(_payload(saved), config_root=private))
        except BaseException as error:  # pragma: no cover - assertion evidence
            worker_errors.append(error)

    worker = Thread(target=run_worker)
    worker.start()
    try:
        assert started.wait(timeout=2)
        repo = AutoBangumiConfigRepository(private)
        with pytest.raises(Stage1Error, match="使用中"):
            repo.save(build_stored_autobangumi_config({"auth_mode": "password", "base_url": "http://ab.test", "username": "u", "password": "x"}), expected_configuration_revision=1)
        with pytest.raises(Stage1Error, match="使用中"):
            repo.delete(expected_configuration_revision=1)
    finally:
        release.set()
        worker.join(timeout=5)
    assert not worker.is_alive()
    assert not worker_errors
    assert worker_result and worker_result[0].sync_status == "COMPLETE"
    replacement = repo.save(build_stored_autobangumi_config({"auth_mode": "password", "base_url": "http://ab.test", "username": "u", "password": "x"}), expected_configuration_revision=1)
    assert replacement.configuration_revision == 2


def test_saved_sync_exception_releases_lease(monkeypatch, tmp_path: Path) -> None:
    private = tmp_path / "private"
    saved = _save_config(private)

    class Broken(_Client):
        def read_snapshot(self, *, deadline=None):
            raise RuntimeError("upstream")

    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_saved_sync_service.create_management_client",
        lambda *_args, **_kwargs: Broken(),
    )
    monkeypatch.setattr("apps.migu_orca_web.services._WEB_STORAGE_ROOT", tmp_path / "business")
    result = run_saved_tracking_sync(_payload(saved), config_root=private)
    assert result.sync_status == "FAILED"
    repo = AutoBangumiConfigRepository(private)
    replacement = repo.save(build_stored_autobangumi_config({"auth_mode": "password", "base_url": "http://ab.test", "username": "u", "password": "x"}), expected_configuration_revision=1)
    assert replacement.configuration_revision == 2


def test_saved_sync_safe_result_contains_no_private_or_upstream_values(monkeypatch, tmp_path: Path) -> None:
    secret = "password-never-output"
    private = tmp_path / "private"
    username = "private-user-never-output"
    saved = _save_config(private, password=secret, username=username)
    monkeypatch.setattr("apps.migu_orca_web.services._WEB_STORAGE_ROOT", tmp_path / "business")
    secure_client = _Client()
    secure_client.subscriptions = [ExternalSubscription("sub-1", "Show", 1, "Group", rss_urls=("http://raw-rss.test/feed",))]
    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_saved_sync_service.create_management_client",
        lambda *_args, **_kwargs: secure_client,
    )
    result = run_saved_tracking_sync(_payload(saved), config_root=private)
    output = " ".join((repr(result), repr(asdict(result)), json.dumps(asdict(result), ensure_ascii=False)))
    for forbidden in ("http://ab.test", username, secret, "sub-1", "http://raw-rss.test/feed"):
        assert forbidden not in output


@pytest.mark.parametrize(
    "status", ["UNKNOWN", "VERIFYING_EXTERNAL", "RECOVERY_REQUIRED"],
)
def test_saved_sync_protects_unknown_tracking_status(monkeypatch, tmp_path: Path, status: str) -> None:
    private, business = tmp_path / "private", tmp_path / "business"
    saved = _save_config(private)
    monkeypatch.setattr("apps.migu_orca_web.services._WEB_STORAGE_ROOT", business)
    config = load_storage_config(business)
    local = replace(
        create_tracking_record(request_id=f"protected-{status}", status=status, plan_summary={"title": "Show", "season": 1, "subtitle_group": "Group"}),
        external_mapping={"schema_version": 2, "adapter": "legacy_3_1", "subscription_id": "sub-1", "rss_ids": [], "match_reason": "EXTERNAL_ID", "external_deleted": False, "enabled": True, "missing_sync_count": 0, "last_verified_at": None, "connection_ref": str(saved.connection_ref)},
    )
    ensure_tracking_record(config, local)
    path = business / "tracking" / f"{local.tracking_id}.json"
    before = path.read_bytes()
    monkeypatch.setattr("apps.migu_orca_web.tracking_saved_sync_service.create_management_client", lambda *_args, **_kwargs: _Client())
    run_saved_tracking_sync(_payload(saved), config_root=private)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "target", [TRACKING_OPERATION_STATE_PREPARED, TRACKING_OPERATION_STATE_IN_PROGRESS, TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN, TRACKING_OPERATION_STATE_RECOVERY_REQUIRED],
)
def test_saved_sync_protects_real_operation_states(monkeypatch, tmp_path: Path, target: str) -> None:
    private, business = tmp_path / "private", tmp_path / "business"
    saved = _save_config(private)
    monkeypatch.setattr("apps.migu_orca_web.services._WEB_STORAGE_ROOT", business)
    config = load_storage_config(business)
    base = create_tracking_record(request_id=f"operation-{target}", status=TRACKING_STATUS_ACTIVE, plan_summary={"title": "Show", "season": 1, "subtitle_group": "Group"})
    operation, _ = bind_tracking_operation(config, tracking_id=base.tracking_id, operation="SUBMIT", idempotency_key=f"key-{target}", expected_revision=base.revision, request_fingerprint="fingerprint", connection_ref=str(saved.connection_ref))
    if target != TRACKING_OPERATION_STATE_PREPARED:
        next_state = transition_tracking_operation(operation, state=TRACKING_OPERATION_STATE_IN_PROGRESS)
        operation = compare_and_swap_tracking_operation(config, operation.operation_id, operation.state, next_state)
        if target in (TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN, TRACKING_OPERATION_STATE_RECOVERY_REQUIRED):
            final = transition_tracking_operation(operation, state=target)
            operation = compare_and_swap_tracking_operation(config, operation.operation_id, operation.state, final)
    local = replace(base, current_operation_id=operation.operation_id, external_mapping={"schema_version": 2, "adapter": "legacy_3_1", "subscription_id": "sub-1", "rss_ids": [], "match_reason": "EXTERNAL_ID", "external_deleted": False, "enabled": True, "missing_sync_count": 0, "last_verified_at": None, "connection_ref": str(saved.connection_ref)})
    ensure_tracking_record(config, local)
    tracking_path = business / "tracking" / f"{local.tracking_id}.json"
    operation_path = business / "tracking_operations" / f"{operation.operation_id}.json"
    before_tracking, before_operation = tracking_path.read_bytes(), operation_path.read_bytes()
    monkeypatch.setattr("apps.migu_orca_web.tracking_saved_sync_service.create_management_client", lambda *_args, **_kwargs: _Client())
    run_saved_tracking_sync(_payload(saved), config_root=private)
    assert tracking_path.read_bytes() == before_tracking
    assert operation_path.read_bytes() == before_operation


@pytest.mark.parametrize("operation_id", ["op_missing", "op_corrupt"])
def test_saved_sync_protects_missing_or_corrupt_current_operation(monkeypatch, tmp_path: Path, operation_id: str) -> None:
    private, business = tmp_path / "private", tmp_path / "business"
    saved = _save_config(private)
    monkeypatch.setattr("apps.migu_orca_web.services._WEB_STORAGE_ROOT", business)
    config = load_storage_config(business)
    local = replace(
        create_tracking_record(request_id=f"broken-{operation_id}", status=TRACKING_STATUS_ACTIVE, plan_summary={"title": "Show", "season": 1, "subtitle_group": "Group"}),
        current_operation_id=operation_id,
        external_mapping={"schema_version": 2, "adapter": "legacy_3_1", "subscription_id": "sub-1", "rss_ids": [], "match_reason": "EXTERNAL_ID", "external_deleted": False, "enabled": True, "missing_sync_count": 0, "last_verified_at": None, "connection_ref": str(saved.connection_ref)},
    )
    ensure_tracking_record(config, local)
    if operation_id == "op_corrupt":
        path = business / "tracking_operations" / f"{operation_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{broken", encoding="utf-8")
    tracking_path = business / "tracking" / f"{local.tracking_id}.json"
    before = tracking_path.read_bytes()
    monkeypatch.setattr("apps.migu_orca_web.tracking_saved_sync_service.create_management_client", lambda *_args, **_kwargs: _Client())
    run_saved_tracking_sync(_payload(saved), config_root=private)
    assert tracking_path.read_bytes() == before
