from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from ab_engine.models.management import AutoBangumiCapabilities, ExternalRss, ExternalSubscription
from apps.migu_orca_web.schemas import SavedTrackingRecoveryInput
from apps.migu_orca_web.tracking_recovery_service_test import (
    _accepted_request,
    _config,
    _move_record,
    _seeded_tracking,
)
from apps.migu_orca_web.tracking_saved_management_service import run_saved_tracking_management
from apps.migu_orca_web.tracking_saved_management_service_test import _payload as _management_payload
from apps.migu_orca_web.tracking_saved_management_service_test import _record as _management_record
from apps.migu_orca_web.tracking_saved_management_service_test import _saved
from apps.migu_orca_web.tracking_saved_recovery_service import run_saved_tracking_recovery
from shared.errors import Stage1Error
from storage_engine.controllers.operation_repository import (
    bind_tracking_operation,
    compare_and_swap_tracking_operation,
    load_tracking_operation,
)
from storage_engine.controllers.tracking_repository import compare_and_swap_tracking_record, load_tracking_record
from tracking_engine.models.operation import (
    TRACKING_OPERATION_STATE_IN_PROGRESS,
    TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
    TRACKING_OPERATION_STATE_PREPARED,
    TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
    transition_tracking_operation,
)
from tracking_engine.models.tracking import (
    TRACKING_AUDIT_RECOVERY_MANUAL_SUCCEEDED,
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_RECOVERY_REQUIRED,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
)

REF = "abcdefab-cdef-4abc-8def-abcdefabcdef"


class ReadOnlyClient:
    def __init__(self, subscriptions: list[ExternalSubscription] | None = None, *, caps=None, rss_items=None):
        self.reads = 0
        self.subscriptions = subscriptions or []
        # Issue #182: the verified 3.1.18 snapshot always carries its RSS list,
        # and the shared confirmation rule needs it to prove the exact identity.
        self.rss_items = rss_items or []
        self.capabilities = caps or AutoBangumiCapabilities(
            probe_status="VERIFIED", version="3.1.18", adapter="legacy_3_1",
            subscription_list="SUPPORTED", subscription_detail="SUPPORTED",
            external_verify="SUPPORTED",
        )

    def read_snapshot(self, *, deadline=None):
        self.reads += 1
        return self.capabilities, self.subscriptions, self.rss_items

    def __repr__(self):
        return "ReadOnlyClient(reads=%d)" % self.reads


def _payload(record, action="AUTO", **kwargs):
    storage_dir = kwargs.pop("storage_dir", "storage")
    return SavedTrackingRecoveryInput(
        tracking_id=record.tracking_id, expected_revision=record.revision,
        action=action, storage_dir=storage_dir, **kwargs,
    )


def _saved_submit_operation(config, record, ref: str, key: str):
    operation, created = bind_tracking_operation(
        config, tracking_id=record.tracking_id, operation="SUBMIT", idempotency_key=key,
        expected_revision=record.revision, request_fingerprint=record.request_fingerprint or "fingerprint",
        now="2026-09-14T00:00:00+00:00", connection_ref=ref,
    )
    assert created
    return compare_and_swap_tracking_operation(
        config, operation.operation_id, expected_state=TRACKING_OPERATION_STATE_PREPARED,
        record=transition_tracking_operation(operation, state=TRACKING_OPERATION_STATE_IN_PROGRESS, now="2026-09-14T00:00:00+00:00"),
    )


def test_saved_recovery_schema_is_strict_and_local_actions_are_connection_free():
    base = {"tracking_id": "trk", "expected_revision": 1, "action": "AUTO"}
    SavedTrackingRecoveryInput(**base)
    SavedTrackingRecoveryInput(**{**base, "action": "MARK_SUCCEEDED", "confirm": True})
    for action in ("MARK_SUCCEEDED", "MARK_FAILED"):
        with pytest.raises(ValidationError):
            SavedTrackingRecoveryInput(**{**base, "action": action})
    for extra in ("connection_ref", "configuration_revision", "secret", "id", "url", "note", "extra"):
        with pytest.raises(ValidationError):
            SavedTrackingRecoveryInput(**{**base, extra: REF if extra == "connection_ref" else 1})
    with pytest.raises(ValidationError):
        SavedTrackingRecoveryInput(**{**base, "action": "VERIFY_EXTERNAL", "connection_ref": REF})
    with pytest.raises(ValidationError):
        SavedTrackingRecoveryInput(**{**base, "action": "VERIFY_EXTERNAL", "configuration_revision": 1})
    with pytest.raises(ValidationError):
        SavedTrackingRecoveryInput(**{**base, "action": "VERIFY_EXTERNAL", "connection_ref": REF.upper(), "configuration_revision": 1})
    with pytest.raises(ValidationError):
        SavedTrackingRecoveryInput(**{**base, "action": "VERIFY_EXTERNAL", "connection_ref": REF, "configuration_revision": True})


def test_auto_and_manual_do_not_load_saved_config_or_construct_client(monkeypatch, tmp_path: Path):
    request = _accepted_request(tmp_path)
    record = _move_record(tmp_path, _seeded_tracking(tmp_path, request), TRACKING_STATUS_RECOVERY_REQUIRED)
    monkeypatch.setattr("apps.migu_orca_web.services._WEB_STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_saved_recovery_service.create_legacy_31_management_client",
        lambda *_a, **_k: pytest.fail("local recovery must not construct client"),
    )
    auto = run_saved_tracking_recovery(_payload(record), config_root=tmp_path / "missing")
    assert auto["outcome"] == TRACKING_STATUS_RECOVERY_REQUIRED
    manual_record = load_tracking_record(_config(tmp_path), record.tracking_id)
    manual = run_saved_tracking_recovery(
        _payload(manual_record, "MARK_SUCCEEDED", confirm=True), config_root=tmp_path / "missing"
    )
    assert manual["outcome"] == TRACKING_STATUS_ACTIVE
    assert load_tracking_record(_config(tmp_path), record.tracking_id).audit_events[-1]["action"] == TRACKING_AUDIT_RECOVERY_MANUAL_SUCCEEDED


def _bound_submit_scenario(monkeypatch, tmp_path: Path, state: str, *, plan_ready: bool = False):
    """One SUBMIT operation bound to the saved generation, ready to verify.

    ``plan_ready=True`` additionally makes the saved plan pass every pure-local
    submit precondition (selected subtitle group + one valid seed); issue #184's
    resubmit re-runs those checks, so its tests need a submittable plan.  The
    operation and record fingerprints are computed from that exact content.
    """
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    config = _config(tmp_path)
    # Persist the finalized request before binding the operation so the
    # durable fingerprint is the exact handoff being recovered.
    req = __import__("storage_engine.controllers.request_repository", fromlist=["load_request_snapshot"]).load_request_snapshot(config, request["request_id"])
    req["confirmable_config"] = {"selected_rss_url": "https://rss.invalid/feed"}
    if plan_ready:
        req["confirmable_config"].update(
            {"selected_subtitle_group": "Group", "effective_seed_names": ["ep-1"]}
        )
    req["plan"] = {"title": "芙莉莲", "season": 1, "subtitle_group": "Group"}
    from storage_engine.controllers.request_repository import save_request_snapshot
    save_request_snapshot(config, req)
    from apps.migu_orca_web.save_confirm_service import compute_request_fingerprint
    record = compare_and_swap_tracking_record(
        config, record.tracking_id, record.revision,
        __import__("dataclasses").replace(record, request_fingerprint=compute_request_fingerprint(req),
                                           plan_summary={"title": "芙莉莲", "season": 1, "subtitle_group": "Group"},
                                           revision=record.revision + 1),
    )
    saved = _saved(tmp_path / "private")
    op = _saved_submit_operation(config, record, str(saved.connection_ref), "verify-" + state.lower())
    if state != TRACKING_OPERATION_STATE_IN_PROGRESS:
        from storage_engine.controllers.operation_repository import compare_and_swap_tracking_operation
        from tracking_engine.models.operation import transition_tracking_operation
        compare_and_swap_tracking_operation(config, op.operation_id, TRACKING_OPERATION_STATE_IN_PROGRESS,
            transition_tracking_operation(op, state=state, now="2026-09-14T00:00:00+00:00"))
    verifying = _move_record(tmp_path, record, TRACKING_STATUS_VERIFYING_EXTERNAL, current_operation_id=op.operation_id)
    monkeypatch.setattr("apps.migu_orca_web.services._WEB_STORAGE_ROOT", tmp_path)
    return config, record, saved, op, verifying


@pytest.mark.parametrize("state", [TRACKING_OPERATION_STATE_IN_PROGRESS, TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN, TRACKING_OPERATION_STATE_RECOVERY_REQUIRED])
def test_saved_submit_verify_uses_one_bound_snapshot_and_persists_v2_mapping(monkeypatch, tmp_path: Path, state):
    config, record, saved, op, verifying = _bound_submit_scenario(monkeypatch, tmp_path, state)
    external = ExternalSubscription("external-1", "芙莉莲", 1, "Group", rss_urls=("https://rss.invalid/feed",), rss_ids=("rss-1",))
    rss = ExternalRss("rss-1", "芙莉莲", "https://rss.invalid/feed")
    result = run_saved_tracking_recovery(
        _payload(verifying, "VERIFY_EXTERNAL", connection_ref=str(saved.connection_ref), configuration_revision=saved.configuration_revision),
        config_root=tmp_path / "private", management_client=ReadOnlyClient([external], rss_items=[rss]),
    )
    assert result["outcome"] == TRACKING_STATUS_ACTIVE
    after = load_tracking_record(config, record.tracking_id)
    assert after.external_mapping["schema_version"] == 2
    assert after.external_mapping["connection_ref"] == str(saved.connection_ref)
    assert after.external_mapping["subscription_id"] == "external-1"
    assert load_tracking_operation(config, op.operation_id).state == "SUCCEEDED"


def test_saved_submit_verify_uses_the_same_rule_as_the_submit_readback(monkeypatch, tmp_path: Path) -> None:
    """Issue #182: the later check must not add extra season/title requirements.

    A subscription whose title, season and group match the plan but whose RSS
    list holds no exact identity is exactly what the post-submit read-back calls
    待确认; the re-check has to reach the same conclusion.
    """
    _config_, record, saved, op, verifying = _bound_submit_scenario(
        monkeypatch, tmp_path, TRACKING_OPERATION_STATE_IN_PROGRESS
    )
    # Matching plan text and season, but a different RSS URL: not the exact
    # server-private identity, so nothing may be claimed.
    other = ExternalSubscription("external-2", "芙莉莲", 1, "Group", rss_urls=("https://rss.invalid/other",), rss_ids=("rss-9",))
    other_rss = ExternalRss("rss-9", "芙莉莲", "https://rss.invalid/other")

    result = run_saved_tracking_recovery(
        _payload(verifying, "VERIFY_EXTERNAL", connection_ref=str(saved.connection_ref), configuration_revision=saved.configuration_revision),
        config_root=tmp_path / "private", management_client=ReadOnlyClient([other], rss_items=[other_rss]),
    )

    assert result["outcome"] == TRACKING_STATUS_RECOVERY_REQUIRED
    assert result["needs_manual"] is True
    assert load_tracking_record(_config(tmp_path), record.tracking_id).external_mapping is None


def test_saved_verify_rejects_wrong_ref_and_missing_config_before_read(monkeypatch, tmp_path: Path):
    request = _accepted_request(tmp_path)
    record = _seeded_tracking(tmp_path, request)
    record = _move_record(tmp_path, record, TRACKING_STATUS_VERIFYING_EXTERNAL)
    saved = _saved(tmp_path / "private")
    monkeypatch.setattr("apps.migu_orca_web.services._WEB_STORAGE_ROOT", tmp_path)
    client = ReadOnlyClient()
    for kwargs, root in (
        ({"connection_ref": "11111111-1111-4111-8111-111111111111", "configuration_revision": saved.configuration_revision}, tmp_path / "private"),
        ({"connection_ref": str(saved.connection_ref), "configuration_revision": saved.configuration_revision}, tmp_path / "deleted"),
    ):
        with pytest.raises((Stage1Error, ValidationError)):
            run_saved_tracking_recovery(_payload(record, "VERIFY_EXTERNAL", **kwargs), config_root=root, management_client=client)
        assert client.reads == 0


def test_saved_verify_result_and_repr_do_not_expose_sensitive_values(monkeypatch, tmp_path: Path):
    request = _accepted_request(tmp_path)
    record = _move_record(tmp_path, _seeded_tracking(tmp_path, request), TRACKING_STATUS_VERIFYING_EXTERNAL)
    saved = _saved(tmp_path / "private")
    monkeypatch.setattr("apps.migu_orca_web.services._WEB_STORAGE_ROOT", tmp_path)
    with pytest.raises(Stage1Error):
        run_saved_tracking_recovery(
            _payload(record, "VERIFY_EXTERNAL", storage_dir="storage", connection_ref=str(saved.connection_ref), configuration_revision=saved.configuration_revision),
            config_root=tmp_path / "private", management_client=ReadOnlyClient([]),
        )
    blob = repr(saved) + str(saved)
    for secret in ("http://ab.invalid", "username", "password", "external_id", "https://rss.invalid"):
        assert secret not in blob


def _uncertain_management(monkeypatch, tmp_path: Path, operation: str, scope: str = "SUBSCRIPTION", **extra):
    private = tmp_path / "private"
    saved = _saved(private)
    config, record = _management_record(tmp_path, saved)
    from apps.migu_orca_web.tracking_saved_management_service_test import FakeClient
    client = FakeClient()
    monkeypatch.setattr("apps.migu_orca_web.services._WEB_STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_saved_management_service.create_legacy_31_management_client",
        lambda *_a, **_k: client,
    )
    first = run_saved_tracking_management(
        _management_payload(saved, record, operation, scope, **extra),
        config_root=private, write=lambda *_a: {"transport_error": "timeout"},
    )
    latest = load_tracking_record(config, record.tracking_id)
    return private, saved, config, latest, first["operation_id"], client


@pytest.mark.parametrize(
    ("operation", "scope", "extra", "outcome"),
    [("MODIFY", "SUBSCRIPTION", {"patch": {"title": "New"}}, "DEFINITE_FAILURE"),
     ("SET_ENABLED", "SUBSCRIPTION", {"enabled": False}, "DEFINITE_FAILURE"),
     ("DELETE_EXTERNAL", "SUBSCRIPTION", {}, "SUCCESS"),
     ("REFRESH_RSS", "ASSOCIATED_RSS", {}, "OUTCOME_UNKNOWN")],
)
def test_saved_management_recovery_is_read_only_and_preserves_operation_key(
    monkeypatch, tmp_path: Path, operation, scope, extra, outcome,
):
    private, saved, config, record, operation_id, client = _uncertain_management(
        monkeypatch, tmp_path, operation, scope, **extra
    )
    before = (operation_id, load_tracking_operation(config, operation_id).idempotency_key, len(client.calls))
    client.reads = 0
    if operation == "DELETE_EXTERNAL":
        client.sub = None
    result = run_saved_tracking_recovery(
        _payload(record, "VERIFY_EXTERNAL", storage_dir="business", connection_ref=str(saved.connection_ref), configuration_revision=saved.configuration_revision),
        config_root=private, management_client=client,
    )
    assert result["outcome"] == outcome
    assert (operation_id, load_tracking_operation(config, operation_id).idempotency_key, len(client.calls)) == before
    assert client.reads >= 2


def test_saved_management_repository_oserror_stops_before_external_read(monkeypatch, tmp_path: Path):
    private, saved, config, record, operation_id, client = _uncertain_management(
        monkeypatch, tmp_path, "MODIFY", patch={"title": "New"}
    )
    client.reads = 0
    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_saved_recovery_service.load_tracking_operation",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("operation store unavailable")),
    )
    with pytest.raises(OSError):
        run_saved_tracking_recovery(
            _payload(record, "VERIFY_EXTERNAL", storage_dir="business", connection_ref=str(saved.connection_ref), configuration_revision=saved.configuration_revision),
            config_root=private, management_client=client,
        )
    assert client.reads == 0
    assert len(client.calls) == 0


def test_saved_management_recovery_rechecks_binding_after_snapshot(monkeypatch, tmp_path: Path):
    private, saved, config, record, operation_id, client = _uncertain_management(
        monkeypatch, tmp_path, "MODIFY", patch={"title": "New"}
    )
    from storage_engine.controllers.operation_repository import compare_and_swap_tracking_operation
    from tracking_engine.models.operation import transition_tracking_operation

    original_read = client.read_snapshot
    changed = False

    def racing_read():
        nonlocal changed
        snapshot = original_read()
        if not changed:
            changed = True
            operation = load_tracking_operation(config, operation_id)
            compare_and_swap_tracking_operation(
                config, operation_id, operation.state,
                transition_tracking_operation(operation, state="SUCCEEDED", now="2026-09-14T00:00:01+00:00"),
            )
        return snapshot

    client.read_snapshot = racing_read
    result = run_saved_tracking_recovery(
        _payload(record, "VERIFY_EXTERNAL", storage_dir="business", connection_ref=str(saved.connection_ref), configuration_revision=saved.configuration_revision),
        config_root=private, management_client=client,
    )
    assert result["outcome"] != "SUCCESS"
    assert len(client.calls) == 0
