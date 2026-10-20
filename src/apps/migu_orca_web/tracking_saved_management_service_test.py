"""US-324: saved-connection management handoff (real service seam)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from ab_engine.controllers.ab_config import AutoBangumiConfig
from ab_engine.controllers.ab_http_client import AutoBangumiWriteResponse
from ab_engine.controllers.ab_management_client import create_legacy_31_management_client
from ab_engine.models.management import AutoBangumiCapabilities, ExternalRss, ExternalSubscription
from apps.migu_orca_web.schemas import SavedTrackingManagementInput
from apps.migu_orca_web.tracking_saved_management_service import run_saved_tracking_management
from shared.errors import Stage1Error
from storage_engine.controllers.autobangumi_config_repository import (
    AutoBangumiConfigRepository,
    build_stored_autobangumi_config,
)
from storage_engine.controllers.operation_repository import bind_tracking_operation, compare_and_swap_tracking_operation
from storage_engine.controllers.request_repository import save_request_snapshot
from storage_engine.controllers.storage_config import load_storage_config
from storage_engine.controllers.tracking_repository import (
    compare_and_swap_tracking_record,
    ensure_tracking_record,
    load_tracking_record,
)
from tracking_engine.controllers.management_target import ResolvedManagementTarget
from tracking_engine.models.operation import (
    TRACKING_OPERATION_STATE_PREPARED,
    TRACKING_OPERATION_STATE_SUCCEEDED,
    transition_tracking_operation,
)
from tracking_engine.models.tracking import (
    TRACKING_STATUS_ACTIVE,
    build_audit_event,
    create_external_tracking_record,
    create_tracking_record,
)

REF = "abcdefab-cdef-4abc-8def-abcdefabcdef"


def _saved(root: Path):
    return AutoBangumiConfigRepository(root).save(
        build_stored_autobangumi_config(
            {"auth_mode": "password", "base_url": "http://ab.invalid", "username": "u", "password": "p"}
        ),
        expected_configuration_revision=0,
    )


class FakeClient:
    def __init__(self, *, capabilities=None):
        self.calls: list[tuple[str, object]] = []
        self.reads = 0
        self.sub = ExternalSubscription("sub-1", "Old", 1, "Group")
        self.rss = ExternalRss("rss-1", "Feed", "https://rss.invalid", enabled=True)
        self.capabilities = capabilities or AutoBangumiCapabilities(
            probe_status="VERIFIED",
            version="3.1.18",
            adapter="legacy_3_1",
            subscription_list="SUPPORTED",
            subscription_detail="SUPPORTED",
            subscription_modify="SUPPORTED",
            subscription_enable="SUPPORTED",
            subscription_disable="SUPPORTED",
            subscription_delete="SUPPORTED",
            rss_list="SUPPORTED",
            rss_modify="SUPPORTED",
            rss_refresh="SUPPORTED",
            rss_delete="SUPPORTED",
            rss_enable="SUPPORTED",
            rss_disable="SUPPORTED",
        )

    def read_snapshot(self, *, deadline=None):
        self.reads += 1
        return self.capabilities, ([self.sub] if self.sub is not None else []), [self.rss]

    def update_subscription(self, ident, payload):
        self.calls.append(("modify", ident))
        self.sub = ExternalSubscription(ident, payload["official_title"], 1, "Group")
        return {"status_code": 200}

    def set_subscription_enabled(self, ident, enabled):
        self.calls.append(("enabled", enabled))
        self.sub = ExternalSubscription(ident, "Old", 1, "Group", deleted=not enabled)
        return {"status_code": 200}

    def delete_subscription(self, ident):
        self.calls.append(("delete", ident))
        self.sub = None
        return {"status_code": 200}

    def refresh_rss(self, ident):
        self.calls.append(("refresh", ident))
        return {"status_code": 200}


def _record(tmp_path: Path, saved, *, mapping=True):
    config = load_storage_config(tmp_path / "business")
    record = create_external_tracking_record(
        adapter="legacy_3_1",
        object_kind="subscription",
        external_id="sub-1",
        subscription_id="sub-1",
        rss_ids=("rss-1",),
        title="Old",
        season=1,
        subtitle_group="Group",
        connection_ref=(str(saved.connection_ref) if mapping is True else None),
    )
    if mapping is None:
        record = replace(record, external_mapping=None)
    elif isinstance(mapping, dict):
        complete = dict(record.external_mapping or {})
        complete.update(mapping)
        record = replace(record, external_mapping=complete)
    # Issue #224 A4: EXTERNAL_ONLY is read-only history, so the management write
    # path is exercised with a manageable ACTIVE record carrying the same mapping.
    record = replace(record, status=TRACKING_STATUS_ACTIVE)
    return config, ensure_tracking_record(config, record)[0]


def _payload(saved, record, operation, scope="SUBSCRIPTION", **extra):
    return SavedTrackingManagementInput(
        tracking_id=record.tracking_id,
        target_scope=scope,
        operation=operation,
        expected_revision=record.revision,
        idempotency_key=f"key-{operation.lower()}-{scope.lower()}",
        confirm=True,
        connection_ref=str(saved.connection_ref),
        configuration_revision=saved.configuration_revision,
        storage_dir="business",
        **extra,
    )


@pytest.mark.parametrize(
    ("operation", "scope", "extra"),
    [
        ("MODIFY", "SUBSCRIPTION", {"patch": {"title": "New"}}),
        ("SET_ENABLED", "SUBSCRIPTION", {"enabled": False}),
        ("REFRESH_RSS", "ASSOCIATED_RSS", {}),
        ("DELETE_EXTERNAL", "SUBSCRIPTION", {}),
    ],
)
def test_saved_management_real_entrypoint_four_actions_uses_ref_and_writer(
    monkeypatch, tmp_path, operation, scope, extra
):
    private = tmp_path / "private"
    saved = _saved(private)
    config, record = _record(tmp_path, saved)
    client = FakeClient()
    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_saved_management_service.create_management_client",
        lambda *_a, **_k: client,
    )
    monkeypatch.setattr("apps.migu_orca_web.services._WEB_STORAGE_ROOT", tmp_path)
    result = run_saved_tracking_management(
        _payload(saved, record, operation, scope, **extra),
        config_root=private,
        # #228 retired the standalone public entry: the delete only runs through
        # the composite plan-delete leg, which is what this case covers.
        internal_plan_delete=(operation == "DELETE_EXTERNAL"),
    )
    assert result["created"] is True
    assert result["management_status"] == "SUCCEEDED"
    assert client.reads >= (1 if operation == "REFRESH_RSS" else 2)
    from storage_engine.controllers.operation_repository import load_tracking_operation

    assert load_tracking_operation(config, result["operation_id"]).connection_ref == str(saved.connection_ref)
    assert client.calls and client.calls[0][0] in {"modify", "enabled", "refresh", "delete"}


@pytest.mark.parametrize(
    "mapping",
    [
        None,
        {"schema_version": 1, "subscription_id": "sub-1"},
        {"schema_version": 2, "subscription_id": "sub-1", "connection_ref": "22222222-2222-4222-8222-222222222222"},
    ],
)
def test_saved_management_mapping_missing_legacy_or_other_ref_has_zero_writes(monkeypatch, tmp_path, mapping):
    private = tmp_path / "private"
    saved = _saved(private)
    config, record = _record(tmp_path, saved, mapping=mapping)
    assert (
        record.external_mapping is None
        if mapping is None
        else all(record.external_mapping[key] == value for key, value in mapping.items())
    )
    client = FakeClient()
    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_saved_management_service.create_management_client",
        lambda *_a, **_k: client,
    )
    monkeypatch.setattr("apps.migu_orca_web.services._WEB_STORAGE_ROOT", tmp_path)
    with pytest.raises(Stage1Error):
        run_saved_tracking_management(_payload(saved, record, "DELETE_EXTERNAL"), config_root=private)
    assert client.calls == []
    assert client.reads == 0


@pytest.mark.parametrize("status", ["PARTIAL", "FAILED", "UNSUPPORTED"])
def test_saved_management_degraded_capability_is_fail_closed(monkeypatch, tmp_path, status):
    private = tmp_path / "private"
    saved = _saved(private)
    config, record = _record(tmp_path, saved)
    caps = AutoBangumiCapabilities(
        probe_status="VERIFIED" if status == "UNSUPPORTED" else status,
        version="3.1.18",
        adapter="legacy_3_1",
        subscription_list="SUPPORTED",
        subscription_detail="SUPPORTED",
        subscription_delete="UNSUPPORTED" if status == "UNSUPPORTED" else "SUPPORTED",
    )
    client = FakeClient(capabilities=caps)
    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_saved_management_service.create_management_client",
        lambda *_a, **_k: client,
    )
    monkeypatch.setattr("apps.migu_orca_web.services._WEB_STORAGE_ROOT", tmp_path)
    with pytest.raises(Stage1Error):
        run_saved_tracking_management(_payload(saved, record, "DELETE_EXTERNAL"), config_root=private)
    assert client.calls == []


def test_saved_management_schema_is_strict_and_canonical():
    common = dict(
        tracking_id="trk",
        target_scope="SUBSCRIPTION",
        operation="MODIFY",
        expected_revision=1,
        idempotency_key="key",
        confirm=True,
        connection_ref=REF,
        configuration_revision=1,
        patch={"title": "x"},
    )
    SavedTrackingManagementInput(**common)
    with pytest.raises(ValidationError):
        SavedTrackingManagementInput(**{**common, "connection_ref": REF.upper()})
    with pytest.raises(ValidationError):
        SavedTrackingManagementInput(**{**common, "confirm": False})
    with pytest.raises(ValidationError):
        SavedTrackingManagementInput(**{**common, "enabled": False})
    with pytest.raises(ValidationError):
        SavedTrackingManagementInput(**{**common, "extras": 1})


@pytest.mark.parametrize(
    "audit_action",
    ["SUBMIT_SUCCEEDED", "RECOVERY_AUTO_SUCCEEDED", "RECOVERY_MANUAL_SUCCEEDED", "RECOVERY_EXTERNAL_VERIFIED"],
)
def test_saved_management_allows_active_record_after_terminal_submit(monkeypatch, tmp_path, audit_action):
    """A successful SUBMIT is a terminal predecessor, not an unfinished lock."""
    private = tmp_path / "private"
    saved = _saved(private)
    config = load_storage_config(tmp_path / "business")
    mapping = create_external_tracking_record(
        adapter="legacy_3_1",
        object_kind="subscription",
        external_id="sub-1",
        subscription_id="sub-1",
        connection_ref=str(saved.connection_ref),
    ).external_mapping
    record = replace(
        create_tracking_record(
            request_id="local-success",
            status="ACTIVE",
            plan_summary={"title": "Old", "season": 1, "subtitle_group": "Group"},
        ),
        external_mapping=mapping,
    )
    ensure_tracking_record(config, record)
    submit, _ = bind_tracking_operation(
        config,
        tracking_id=record.tracking_id,
        operation="SUBMIT",
        idempotency_key="submit-done",
        expected_revision=record.revision,
        request_fingerprint="sha256:" + "a" * 64,
        previous_tracking_status=None,
        connection_ref=str(saved.connection_ref),
    )
    in_progress = transition_tracking_operation(submit, state="IN_PROGRESS")
    done = transition_tracking_operation(in_progress, state=TRACKING_OPERATION_STATE_SUCCEEDED)
    compare_and_swap_tracking_operation(config, submit.operation_id, TRACKING_OPERATION_STATE_PREPARED, in_progress)
    compare_and_swap_tracking_operation(config, submit.operation_id, "IN_PROGRESS", done)
    event = build_audit_event(
        action=audit_action,
        actor="SYSTEM",
        from_status=record.status,
        to_status=record.status,
        tracking_revision=record.revision,
        operation_id=submit.operation_id,
        reason_code="SUBMIT",
        safe_message="submitted",
    )
    record = replace(
        record,
        current_operation_id=submit.operation_id,
        revision=record.revision + 1,
        audit_events=[*record.audit_events, event],
    )
    compare_and_swap_tracking_record(config, record.tracking_id, 1, record)
    client = FakeClient()
    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_saved_management_service.create_management_client",
        lambda *_a, **_k: client,
    )
    monkeypatch.setattr("apps.migu_orca_web.services._WEB_STORAGE_ROOT", tmp_path)
    operation_path = config.tracking_operations_dir / f"{submit.operation_id}.json"
    before = operation_path.read_bytes()
    result = run_saved_tracking_management(
        _payload(saved, record, "MODIFY", patch={"title": "New"}), config_root=private
    )
    assert result["created"] is True
    assert result["management_status"] == "SUCCEEDED"
    assert operation_path.read_bytes() == before


def test_saved_management_terminal_replay_and_binding_conflicts_are_at_most_once(monkeypatch, tmp_path):
    private = tmp_path / "private"
    saved = _saved(private)
    config, record = _record(tmp_path, saved)
    client = FakeClient()
    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_saved_management_service.create_management_client",
        lambda *_a, **_k: client,
    )
    monkeypatch.setattr("apps.migu_orca_web.services._WEB_STORAGE_ROOT", tmp_path)
    original = _payload(saved, record, "MODIFY", patch={"title": "New"})
    first = run_saved_tracking_management(original, config_root=private)
    writes = len(client.calls)
    AutoBangumiConfigRepository(private).delete(expected_configuration_revision=saved.configuration_revision)
    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_saved_management_service.create_management_client",
        lambda *_args, **_kwargs: pytest.fail("terminal replay constructed client"),
    )
    replay = run_saved_tracking_management(original, config_root=private)
    assert replay["operation_id"] == first["operation_id"]
    assert len(client.calls) == writes
    for changed in (
        {"connection_ref": REF},
        {"patch": {"title": "Other"}},
        {"target_scope": "ASSOCIATED_RSS", "patch": {"name": "Other"}},
        {"expected_revision": original.expected_revision + 1},
    ):
        data = original.model_dump(mode="json")
        data.update(changed)
        with pytest.raises(Stage1Error):
            run_saved_tracking_management(SavedTrackingManagementInput(**data), config_root=private)
    assert len(client.calls) == writes


def test_saved_management_unknown_replay_and_fresh_key_never_reissue(monkeypatch, tmp_path):
    private = tmp_path / "private"
    saved = _saved(private)
    config, record = _record(tmp_path, saved)
    client = FakeClient()
    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_saved_management_service.create_management_client",
        lambda *_a, **_k: client,
    )
    monkeypatch.setattr("apps.migu_orca_web.services._WEB_STORAGE_ROOT", tmp_path)
    payload = _payload(saved, record, "MODIFY", patch={"title": "New"})
    write_calls = []
    result = run_saved_tracking_management(
        payload, config_root=private, write=lambda *_a: write_calls.append(1) or {"transport_error": "timeout"}
    )
    assert result["outcome"] == "OUTCOME_UNKNOWN"
    assert len(write_calls) == 1
    replay = run_saved_tracking_management(
        payload, config_root=private, write=lambda *_a: pytest.fail("unknown replay wrote")
    )
    assert replay["operation_id"] == result["operation_id"]
    latest = load_tracking_record(config, record.tracking_id)
    fresh = payload.model_copy(update={"idempotency_key": "fresh-key", "expected_revision": latest.revision})
    with pytest.raises(Stage1Error):
        run_saved_tracking_management(fresh, config_root=private, write=lambda *_a: pytest.fail("fresh unknown wrote"))
    assert len(write_calls) == 1


def test_old_terminal_key_preserves_later_operation_and_history(monkeypatch, tmp_path):
    private = tmp_path / "private"
    saved = _saved(private)
    config, record = _record(tmp_path, saved)
    client = FakeClient()
    monkeypatch.setattr("apps.migu_orca_web.services._WEB_STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_saved_management_service.create_management_client",
        lambda *_args, **_kwargs: client,
    )
    original = _payload(saved, record, "MODIFY", patch={"title": "New"})
    old = run_saved_tracking_management(original, config_root=private)
    current = load_tracking_record(config, record.tracking_id)
    new = run_saved_tracking_management(
        _payload(saved, current, "SET_ENABLED", enabled=False),
        config_root=private,
    )
    paths = [config.tracking_dir / f"{record.tracking_id}.json"] + [
        config.tracking_operations_dir / f"{result['operation_id']}.json" for result in (old, new)
    ]
    before = [path.read_bytes() for path in paths]
    writes = len(client.calls)
    with pytest.raises(Stage1Error) as caught:
        run_saved_tracking_management(original, config_root=private)
    assert caught.value.error_type == "tracking_management_state_conflict"
    assert [path.read_bytes() for path in paths] == before
    assert len(client.calls) == writes


def test_saved_management_lease_spans_read_write_readback_and_releases(monkeypatch, tmp_path):
    private = tmp_path / "private"
    saved = _saved(private)
    config, record = _record(tmp_path, saved)
    repository = AutoBangumiConfigRepository(private)
    client = FakeClient()
    lease_errors = []

    def touch_repository():
        for mutation in (
            lambda: repository.save(
                build_stored_autobangumi_config(
                    {"auth_mode": "password", "base_url": "http://ab.invalid", "username": "u", "password": "p2"}
                ),
                expected_configuration_revision=1,
            ),
            lambda: repository.delete(expected_configuration_revision=1),
        ):
            with pytest.raises(Stage1Error) as caught:
                mutation()
            lease_errors.append(caught.value.error_type)

    original_read = client.read_snapshot
    client.read_snapshot = lambda: touch_repository() or original_read()
    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_saved_management_service.create_management_client",
        lambda *_a, **_k: client,
    )
    monkeypatch.setattr("apps.migu_orca_web.services._WEB_STORAGE_ROOT", tmp_path)

    def writer(*_args):
        touch_repository()
        return {"status_code": 200}

    result = run_saved_tracking_management(
        _payload(saved, record, "MODIFY", patch={"title": "New"}),
        config_root=private,
        write=writer,
        readback=lambda *_args: (
            touch_repository()
            or ResolvedManagementTarget(
                scope="SUBSCRIPTION",
                subscription=ExternalSubscription("sub-1", "New", 1, "Group"),
            )
        ),
    )
    assert result["management_status"] == "SUCCEEDED"
    assert lease_errors == ["connection_in_use"] * 6
    replacement = repository.save(
        build_stored_autobangumi_config(
            {"auth_mode": "password", "base_url": "http://ab.invalid", "username": "u", "password": "p2"}
        ),
        expected_configuration_revision=1,
    )
    assert replacement.configuration_revision == 2


@pytest.mark.parametrize("outcome", ["success", "unknown", "failed", "server_error"])
def test_legacy31_delete_is_single_file_safe_and_local_bytes_survive(monkeypatch, tmp_path, outcome):
    class OfflineTransport:
        def __init__(self):
            self.calls = []

        def request_json(self, method, endpoint, headers, payload=None, *, timeout):
            self.calls.append((method, endpoint, payload))
            if method == "POST":
                return {"access_token": "offline-token"}
            if method == "GET":
                if endpoint.endswith("/status"):
                    return {"version": "3.1.18"}
                if endpoint.endswith("/bangumi/get/all"):
                    deleted = outcome == "success" and len(self.calls) > 6
                    return {
                        "data": []
                        if deleted
                        else [
                            {
                                "id": "sub-1",
                                "official_title": "Old",
                                "season": 1,
                                "group_name": "Group",
                                "deleted": False,
                            }
                        ]
                    }
                if endpoint.endswith("/rss"):
                    return {"data": []}
            raise AssertionError(f"unexpected read request: {endpoint}")

        def write_json(self, method, endpoint, headers, payload=None, *, timeout, step="create_ab_subscription"):
            """The one delete write, answered with the verified 3.1.18 envelope.

            ``unknown`` is an unreadable response (no verdict at all), ``failed``
            is a real 406 rejection envelope and ``success`` an exact 200.
            """
            self.calls.append((method, endpoint, payload))
            if outcome == "unknown":
                raise TimeoutError("offline")
            if outcome == "server_error":
                # A 5xx may have been processed upstream: the status code must
                # stay readable by the coordinator's unknown-write classifier.
                return AutoBangumiWriteResponse(500, {"msg_en": "Internal error", "msg_zh": "服务器错误"})
            if outcome == "failed":
                return AutoBangumiWriteResponse(
                    406, {"msg_en": "Can't find id 999999", "msg_zh": "无法找到 id 999999"}
                )
            return AutoBangumiWriteResponse(200, {"msg_en": "Success.", "msg_zh": "成功。"})

    transport = OfflineTransport()
    client = create_legacy_31_management_client(
        AutoBangumiConfig(
            base_url="https://ab.invalid", auth_mode="password", fallback_enabled=False, username="u", password="p"
        ),
        transport=transport,
    )
    private = tmp_path / "private"
    saved = _saved(private)
    config = load_storage_config(tmp_path / "business")
    mapping = create_external_tracking_record(
        adapter="legacy_3_1",
        object_kind="subscription",
        external_id="sub-1",
        subscription_id="sub-1",
        connection_ref=str(saved.connection_ref),
    ).external_mapping
    record = replace(
        create_tracking_record(request_id="retained-plan", status="ACTIVE", plan_summary={}), external_mapping=mapping
    )
    record = replace(
        record,
        audit_events=[
            build_audit_event(
                action="SUBMIT_SUCCEEDED",
                actor="SYSTEM",
                from_status=record.status,
                to_status=record.status,
                tracking_revision=record.revision,
                reason_code="SUBMIT",
                safe_message="既有审计",
            )
        ],
    )
    record, _ = ensure_tracking_record(config, record)
    save_request_snapshot(config, {"request_id": "retained-plan", "status": "CONFIRMED"})
    request_path = config.requests_dir / "retained-plan.json"
    request_bytes = request_path.read_bytes()
    path = config.tracking_dir / f"{record.tracking_id}.json"
    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_saved_management_service.create_management_client",
        lambda *_a, **_k: client,
    )
    monkeypatch.setattr("apps.migu_orca_web.services._WEB_STORAGE_ROOT", tmp_path)
    media = config.storage_dir / "media.bin"
    media.write_bytes(b"downloaded-media")
    payload = _payload(saved, record, "DELETE_EXTERNAL")
    if outcome in {"unknown", "server_error"}:
        # An unreadable response and a 5xx are both indeterminate: neither may be
        # reported as a definite failure (the write may have been processed).
        result = run_saved_tracking_management(payload, config_root=private, internal_plan_delete=True)
        assert result["outcome"] == "OUTCOME_UNKNOWN"
    else:
        result = run_saved_tracking_management(payload, config_root=private, internal_plan_delete=True)
        assert result["outcome"] == ("SUCCESS" if outcome == "success" else "DEFINITE_FAILURE")
    deletes = [call for call in transport.calls if call[0] == "DELETE"]
    assert len(deletes) == 1
    assert deletes[0][1].endswith("/bangumi/delete/sub-1?file=false")
    assert path.exists()
    assert load_tracking_record(config, record.tracking_id).external_mapping["subscription_id"] == "sub-1"
    assert media.read_bytes() == b"downloaded-media"
    assert request_path.read_bytes() == request_bytes
    after = load_tracking_record(config, record.tracking_id)
    assert after.request_id == "retained-plan"
    assert record.audit_events[0] in after.audit_events
    replacement = AutoBangumiConfigRepository(private).save(
        build_stored_autobangumi_config(
            {"auth_mode": "password", "base_url": "http://ab.invalid", "username": "u", "password": "new"}
        ),
        expected_configuration_revision=saved.configuration_revision,
    )
    assert replacement.configuration_revision == saved.configuration_revision + 1
