from __future__ import annotations

"""US-219: TrackingRecord model, deterministic ID and schema tests.

These cover the deterministic opaque ``tracking_id``, the strict fail-closed
schema whitelist, status/status-group/audit model, revision-atomic helpers and
the guarantee that serialized records never carry sensitive nested content.
"""

from dataclasses import replace

import pytest

from shared.errors import Stage1Error
from tracking_engine.models.tracking import (
    TRACKING_AUDIT_ACTIONS,
    TRACKING_AUDIT_ACTOR_SYSTEM,
    TRACKING_AUDIT_ACTOR_USER,
    TRACKING_AUDIT_REVALIDATION_PASSED,
    TRACKING_AUDIT_SUBMIT_FAILED,
    TRACKING_AUDIT_TRACKING_CREATED,
    TRACKING_ORIGIN_EXTERNAL_SYNC,
    TRACKING_ORIGIN_SAVE_CONFIRM,
    TRACKING_OVERVIEW_CARD_GROUPS,
    TRACKING_SCHEMA_VERSION,
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_EXTERNAL_DELETED,
    TRACKING_STATUS_EXTERNAL_ONLY,
    TRACKING_STATUS_GROUP_ACTIVE,
    TRACKING_STATUS_GROUP_ATTENTION,
    TRACKING_STATUS_GROUP_INACTIVE,
    TRACKING_STATUS_GROUP_LABELS,
    TRACKING_STATUS_GROUP_ORDER,
    TRACKING_STATUS_GROUP_PENDING,
    TRACKING_STATUS_GROUP_PROCESSING,
    TRACKING_STATUS_GROUPS,
    TRACKING_STATUS_LABELS,
    TRACKING_STATUS_PENDING_SUBMIT,
    TRACKING_STATUS_REVALIDATING,
    TRACKING_STATUSES,
    TrackingRecord,
    append_audit_event,
    build_audit_event,
    create_external_tracking_record,
    create_tracking_record,
    tracking_from_storage_dict,
    tracking_id_for_external,
    tracking_id_for_request,
    tracking_status_group,
    tracking_to_storage_dict,
    transition_record,
)

REQUEST_ID = "0f8fad5b-d9cb-469f-a165-70867728950e"
#: Frozen expected value — changing the namespace/digest must not silently
#: change existing tracking ids (Stage 29 PRD §7.4).
EXPECTED_TRACKING_ID = "trk_ba8abbe28fb5345ceccabd82850ee091"

PLAN_SUMMARY = {
    "title": "葬送的芙莉莲",
    "season": 2,
    "subtitle_group": "喵萌奶茶屋",
    "poster_path": "/api/v1/mikan/posters/opaque-key",
}


def _record() -> TrackingRecord:
    return create_tracking_record(
        request_id=REQUEST_ID,
        status=TRACKING_STATUS_PENDING_SUBMIT,
        plan_summary=PLAN_SUMMARY,
        now="2026-09-08T00:00:00+00:00",
    )


def test_tracking_id_is_deterministic_and_frozen() -> None:
    first = tracking_id_for_request(REQUEST_ID)
    second = tracking_id_for_request(f" {REQUEST_ID} ")

    assert first == EXPECTED_TRACKING_ID
    assert second == first
    assert tracking_id_for_request("different-request") != first


def test_tracking_id_is_opaque_and_prefix_namespaced() -> None:
    tracking_id = tracking_id_for_request(REQUEST_ID)

    assert tracking_id.startswith("trk_")
    assert REQUEST_ID not in tracking_id
    # Opaque id must be a single safe path/URL segment.
    assert "/" not in tracking_id
    assert "\\" not in tracking_id


def test_external_tracking_id_uses_frozen_versioned_namespace() -> None:
    first = tracking_id_for_external("legacy_3_1", "subscription", "sub-123")
    second = tracking_id_for_external("legacy_3_1", "subscription", "sub-123")

    assert first == second
    assert first == "trk_" + __import__("hashlib").sha256(
        b"migu-orca/tracking/external/v1\x00legacy_3_1\x00subscription\x00sub-123"
    ).hexdigest()[:32]


def test_saved_external_tracking_ids_are_connection_isolated() -> None:
    first = tracking_id_for_external(
        "legacy_3_1", "subscription", "sub-123",
        "11111111-1111-4111-8111-111111111111",
    )
    second = tracking_id_for_external(
        "legacy_3_1", "subscription", "sub-123",
        "22222222-2222-4222-8222-222222222222",
    )
    legacy = tracking_id_for_external("legacy_3_1", "subscription", "sub-123")
    assert len({first, second, legacy}) == 3
    assert "sub-123" not in first
    with pytest.raises(ValueError):
        tracking_id_for_external("legacy_3_1", "subscription", "https://bad")


def test_external_record_has_no_request_and_round_trips_strict_mapping() -> None:
    record = create_external_tracking_record(
        adapter="legacy_3_1",
        object_kind="subscription",
        external_id="sub-123",
        title="葬送的芙莉莲",
        season=2,
        subtitle_group="字幕组",
        subscription_id="sub-123",
        rss_ids=["rss-a", "rss-a", "rss-b"],
        now="2026-09-09T00:00:00+00:00",
    )
    restored = tracking_from_storage_dict(tracking_to_storage_dict(record))

    assert record.origin == TRACKING_ORIGIN_EXTERNAL_SYNC
    assert record.request_id is None
    assert record.external_mapping["rss_ids"] == ["rss-a", "rss-b"]
    assert restored == record


def test_external_mapping_v2_round_trip_binds_connection_ref() -> None:
    connection_ref = "11111111-1111-4111-8111-111111111111"
    record = create_external_tracking_record(
        adapter="legacy_3_1",
        object_kind="subscription",
        external_id="sub-123",
        subscription_id="sub-123",
        connection_ref=connection_ref,
        now="2026-09-09T00:00:00+00:00",
    )

    assert record.external_mapping["schema_version"] == 2
    assert record.external_mapping["connection_ref"] == connection_ref
    assert tracking_from_storage_dict(tracking_to_storage_dict(record)) == record


@pytest.mark.parametrize(
    "mapping_update",
    [
        {"connection_ref": None},
        {"connection_ref": "11111111-1111-4111-8111-11111111111"},
        {"connection_ref": "abcdefab-cdef-4abc-8def-abcdefabcdef".upper()},
        {"connection_ref": "https://secret.invalid"},
        {"unexpected": "value"},
    ],
)
def test_external_mapping_v2_rejects_missing_invalid_or_unknown_binding(
    mapping_update: dict[str, object],
) -> None:
    storage = tracking_to_storage_dict(_record())
    storage["external_mapping"] = {
        "schema_version": 2,
        "adapter": "legacy_3_1",
        "subscription_id": "sub-123",
        "rss_ids": [],
        "match_reason": "EXTERNAL_ID",
        "external_deleted": False,
        "enabled": True,
        "missing_sync_count": 0,
        "last_verified_at": None,
        "connection_ref": "11111111-1111-4111-8111-111111111111",
        **mapping_update,
    }
    with pytest.raises(ValueError):
        tracking_from_storage_dict(storage)


def test_external_mapping_rejects_boolean_schema_version() -> None:
    storage = tracking_to_storage_dict(_record())
    storage["external_mapping"] = {"schema_version": True}
    with pytest.raises(ValueError, match="schema_version must be an integer"):
        tracking_from_storage_dict(storage)


def test_external_mapping_v1_rejects_unknown_fields_but_legacy_is_preserved() -> None:
    storage = tracking_to_storage_dict(_record())
    storage["external_mapping"] = {
        "schema_version": 1,
        "adapter": "legacy_3_1",
        "subscription_id": None,
        "rss_ids": [],
        "match_reason": "EXTERNAL_ONLY",
        "external_deleted": False,
        "enabled": True,
        "missing_sync_count": 0,
        "last_verified_at": None,
        "unexpected": "reject",
    }
    with pytest.raises(ValueError, match="unknown external_mapping fields"):
        tracking_from_storage_dict(storage)

    storage["external_mapping"] = {"legacy_key": "legacy-value"}
    assert tracking_from_storage_dict(storage).external_mapping == storage["external_mapping"]


def test_tracking_id_rejects_empty_request_id() -> None:
    with pytest.raises(ValueError):
        tracking_id_for_request("")
    with pytest.raises(ValueError):
        tracking_id_for_request("   ")


def test_create_tracking_record_builds_revision_one_record_with_created_event() -> None:
    record = _record()

    assert record.schema_version == TRACKING_SCHEMA_VERSION
    assert record.tracking_id == EXPECTED_TRACKING_ID
    assert record.request_id == REQUEST_ID
    assert record.origin == TRACKING_ORIGIN_SAVE_CONFIRM
    assert record.status == TRACKING_STATUS_PENDING_SUBMIT
    assert record.revision == 1
    assert record.created_at == "2026-09-08T00:00:00+00:00"
    assert record.updated_at == "2026-09-08T00:00:00+00:00"
    assert len(record.audit_events) == 1
    event = record.audit_events[0]
    assert event["action"] == TRACKING_AUDIT_TRACKING_CREATED
    assert event["actor"] == TRACKING_AUDIT_ACTOR_USER
    assert event["from_status"] is None
    assert event["to_status"] == TRACKING_STATUS_PENDING_SUBMIT
    assert event["tracking_revision"] == 1


def test_storage_dict_round_trip_preserves_all_public_fields() -> None:
    record = _record()
    storage = tracking_to_storage_dict(record)
    restored = tracking_from_storage_dict(storage)

    assert restored == record
    assert set(storage) == {
        "schema_version",
        "tracking_id",
        "request_id",
        "batch_id",
        "origin",
        "status",
        "revision",
        "request_fingerprint",
        "plan_summary",
        "external_mapping",
        "current_operation_id",
        "last_error",
        "recovery",
        "audit_events",
        "created_at",
        "updated_at",
        "last_synced_at",
    }


def test_storage_dict_round_trip_preserves_last_error_and_fingerprint() -> None:
    record = replace(
        _record(),
        request_fingerprint="a" * 64,
        last_error={
            "error_type": "ab_submit_failed",
            "reason_code": "EXPLICIT_FAILURE",
            "safe_message": "已明确失败，可重试",
        },
    )

    restored = tracking_from_storage_dict(tracking_to_storage_dict(record))

    assert restored.request_fingerprint == "a" * 64
    assert restored.last_error == record.last_error


def test_from_storage_dict_rejects_unknown_last_error_field() -> None:
    storage = tracking_to_storage_dict(_record())
    storage["last_error"] = {"error_type": "x", "traceback": "secret-stack"}

    with pytest.raises(ValueError, match="unknown last_error fields"):
        tracking_from_storage_dict(storage)


def test_transition_record_increments_revision_and_embeds_audit() -> None:
    record = _record()
    moved = transition_record(
        record,
        status=TRACKING_STATUS_REVALIDATING,
        audit_action=TRACKING_AUDIT_REVALIDATION_PASSED,
        audit_actor=TRACKING_AUDIT_ACTOR_SYSTEM,
        now="2026-09-08T00:01:00+00:00",
    )

    assert moved.revision == 2
    assert moved.status == TRACKING_STATUS_REVALIDATING
    assert moved.updated_at == "2026-09-08T00:01:00+00:00"
    assert moved.created_at == record.created_at
    assert len(moved.audit_events) == 2
    event = moved.audit_events[-1]
    assert event["action"] == TRACKING_AUDIT_REVALIDATION_PASSED
    assert event["from_status"] == TRACKING_STATUS_PENDING_SUBMIT
    assert event["to_status"] == TRACKING_STATUS_REVALIDATING
    assert event["tracking_revision"] == 2
    assert record.revision == 1  # original record is immutable


def test_append_audit_event_keeps_record_immutable() -> None:
    record = _record()
    event = build_audit_event(
        action=TRACKING_AUDIT_SUBMIT_FAILED,
        actor=TRACKING_AUDIT_ACTOR_SYSTEM,
        from_status=TRACKING_STATUS_PENDING_SUBMIT,
        to_status=TRACKING_STATUS_PENDING_SUBMIT,
        tracking_revision=1,
    )
    appended = append_audit_event(record, event)

    assert len(appended.audit_events) == 2
    assert len(record.audit_events) == 1
    assert appended.tracking_id == record.tracking_id
    assert appended.revision == record.revision


def test_audit_event_rejects_unknown_action_and_actor() -> None:
    with pytest.raises(ValueError):
        build_audit_event(
            action="NOT_AN_ACTION",
            actor=TRACKING_AUDIT_ACTOR_SYSTEM,
            from_status=None,
            to_status=TRACKING_STATUS_PENDING_SUBMIT,
            tracking_revision=1,
        )
    with pytest.raises(ValueError):
        build_audit_event(
            action=TRACKING_AUDIT_TRACKING_CREATED,
            actor="GUEST",
            from_status=None,
            to_status=TRACKING_STATUS_PENDING_SUBMIT,
            tracking_revision=1,
        )


def test_status_groups_and_labels_cover_every_status() -> None:
    assert tracking_status_group(TRACKING_STATUS_PENDING_SUBMIT) == TRACKING_STATUS_GROUP_PENDING
    assert tracking_status_group(TRACKING_STATUS_REVALIDATING) == TRACKING_STATUS_GROUP_PROCESSING
    assert tracking_status_group(TRACKING_STATUS_ACTIVE) == TRACKING_STATUS_GROUP_ACTIVE
    # Every mapped status has a Chinese label and every schema status is mapped.
    assert set(TRACKING_STATUS_LABELS) == set(TRACKING_STATUS_GROUPS)
    assert TRACKING_STATUS_LABELS[TRACKING_STATUS_PENDING_SUBMIT] == "待提交"
    assert TRACKING_STATUS_GROUP_LABELS[TRACKING_STATUS_GROUP_PENDING] == "待处理"
    with pytest.raises(ValueError):
        tracking_status_group("NOT_A_STATUS")


def test_status_vocabulary_and_card_groups_follow_issue_224() -> None:
    """#224 A1/A3: one vocabulary, and a detected external delete needs attention."""
    assert TRACKING_STATUS_LABELS[TRACKING_STATUS_ACTIVE] == "追番中"
    assert "正在追番" not in TRACKING_STATUS_LABELS.values()
    assert "正在追番" not in TRACKING_STATUS_GROUP_LABELS.values()
    # 外部已删除 is a detected fact, not a MiGuOrca operation: it needs attention.
    assert tracking_status_group(TRACKING_STATUS_EXTERNAL_DELETED) == TRACKING_STATUS_GROUP_ATTENTION
    assert TRACKING_STATUS_GROUP_LABELS == {
        TRACKING_STATUS_GROUP_PENDING: "待处理",
        TRACKING_STATUS_GROUP_PROCESSING: "处理中",
        TRACKING_STATUS_GROUP_ACTIVE: "追番中",
        TRACKING_STATUS_GROUP_ATTENTION: "需处理",
        TRACKING_STATUS_GROUP_INACTIVE: "已停用",
    }
    assert TRACKING_STATUS_GROUP_ORDER == (
        TRACKING_STATUS_GROUP_PENDING,
        TRACKING_STATUS_GROUP_PROCESSING,
        TRACKING_STATUS_GROUP_ACTIVE,
        TRACKING_STATUS_GROUP_ATTENTION,
        TRACKING_STATUS_GROUP_INACTIVE,
    )
    assert set(TRACKING_STATUS_GROUP_ORDER) == set(TRACKING_STATUS_GROUP_LABELS)
    # Exactly four groups render as cards; 处理中 stays a transient per-row state.
    assert frozenset(
        {
            TRACKING_STATUS_GROUP_PENDING,
            TRACKING_STATUS_GROUP_ACTIVE,
            TRACKING_STATUS_GROUP_ATTENTION,
            TRACKING_STATUS_GROUP_INACTIVE,
        }
    ) == TRACKING_OVERVIEW_CARD_GROUPS
    assert TRACKING_STATUS_GROUP_PROCESSING not in TRACKING_OVERVIEW_CARD_GROUPS
    # A4: retirement is a product decision — the schema value and its real label
    # survive so a historical archive never gets renamed to 已停用.
    assert TRACKING_STATUS_EXTERNAL_ONLY in TRACKING_STATUSES
    assert TRACKING_STATUS_LABELS[TRACKING_STATUS_EXTERNAL_ONLY] == "仅外部"
    assert tracking_status_group(TRACKING_STATUS_EXTERNAL_ONLY) == TRACKING_STATUS_GROUP_INACTIVE


def test_audit_actions_are_non_empty_enum() -> None:
    assert len(TRACKING_AUDIT_ACTIONS) >= 17
    assert TRACKING_AUDIT_TRACKING_CREATED in TRACKING_AUDIT_ACTIONS
    assert TRACKING_AUDIT_SUBMIT_FAILED in TRACKING_AUDIT_ACTIONS


# -- fail-closed schema tests -------------------------------------------------


def test_from_storage_dict_rejects_unknown_top_level_field() -> None:
    storage = tracking_to_storage_dict(_record())
    storage["ab_config"] = {"endpoint": "https://example.invalid", "token": "secret"}

    with pytest.raises(ValueError, match="unknown tracking record fields"):
        tracking_from_storage_dict(storage)


def test_from_storage_dict_rejects_unsupported_schema_version() -> None:
    storage = tracking_to_storage_dict(_record())
    storage["schema_version"] = 2

    with pytest.raises(ValueError, match="unsupported tracking schema_version"):
        tracking_from_storage_dict(storage)


def test_from_storage_dict_rejects_tracking_id_request_id_mismatch() -> None:
    storage = tracking_to_storage_dict(_record())
    storage["tracking_id"] = "trk_" + "a" * 32

    with pytest.raises(ValueError, match="does not match request_id-derived id"):
        tracking_from_storage_dict(storage)


def test_from_storage_dict_rejects_unknown_status_and_origin() -> None:
    storage = tracking_to_storage_dict(_record())
    storage["status"] = "GHOST"
    with pytest.raises(ValueError, match="invalid tracking status"):
        tracking_from_storage_dict(storage)

    storage = tracking_to_storage_dict(_record())
    storage["origin"] = "UNKNOWN_ORIGIN"
    with pytest.raises(ValueError, match="invalid tracking origin"):
        tracking_from_storage_dict(storage)


def test_from_storage_dict_rejects_bad_types_and_non_object() -> None:
    with pytest.raises(ValueError, match="must be an object"):
        tracking_from_storage_dict([])

    storage = tracking_to_storage_dict(_record())
    storage["revision"] = 0
    with pytest.raises(ValueError, match="positive integer"):
        tracking_from_storage_dict(storage)

    storage = tracking_to_storage_dict(_record())
    storage["plan_summary"] = None
    with pytest.raises(ValueError, match="plan_summary must be an object"):
        tracking_from_storage_dict(storage)


def test_from_storage_dict_rejects_unknown_plan_summary_field() -> None:
    storage = tracking_to_storage_dict(_record())
    storage["plan_summary"]["ab_config"] = {"token": "secret"}

    with pytest.raises(ValueError, match="unknown plan_summary fields"):
        tracking_from_storage_dict(storage)


def test_from_storage_dict_rejects_unknown_audit_event_field() -> None:
    storage = tracking_to_storage_dict(_record())
    storage["audit_events"][0]["request_body"] = '{"raw_title": "秘密"}'

    with pytest.raises(ValueError, match="unknown audit event fields"):
        tracking_from_storage_dict(storage)


# -- sensitive content cleaning ----------------------------------------------


def test_storage_dict_deep_cleans_future_opaque_objects() -> None:
    secret = "very-secret-token-value"
    record = replace(
        _record(),
        external_mapping={
            "external_id": "ab-123",
            "token": secret,
            "headers": {"Authorization": f"Bearer {secret}"},
            "url": "https://example.invalid/RSS?token=secret",
            "magnet": "magnet:?xt=urn:btih:abc",
            "path": "/home/ghostning/.migu_orca/storage/tracking/secret.json",
            "ok": "keep-me",
        },
        recovery={"raw": {"body": secret}, "reason": "ok"},
    )

    storage = tracking_to_storage_dict(record)

    serialized = str(storage)
    assert "external_id" in serialized
    assert "keep-me" in serialized
    assert secret not in serialized
    assert "Bearer" not in serialized
    assert "example.invalid" not in serialized
    assert "magnet:?xt" not in serialized
    assert "/home/ghostning" not in serialized
    # Sensitive keys are dropped entirely.
    assert "token" not in storage["external_mapping"]
    assert "headers" not in storage["external_mapping"]
    assert storage["recovery"] is None or "raw" not in storage["recovery"]


def test_model_is_not_a_stage1_error_surface() -> None:
    # The model raises ValueError for schema problems; repository layers map to
    # Stage1Error storage errors. Guard the boundary stays intact.
    with pytest.raises(ValueError):
        tracking_from_storage_dict({"schema_version": TRACKING_SCHEMA_VERSION})
    assert issubclass(Stage1Error, Exception)
