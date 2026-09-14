from ab_engine.controllers.reconcile import (
    LocalTrackingEvidence,
    classify_missing_mapping,
    reconcile_subscription,
)
from ab_engine.models.management import ExternalSubscription


def external(**overrides: object) -> ExternalSubscription:
    values: dict[str, object] = {
        "external_id": "sub-1",
        "title": "葬送的芙莉莲",
        "season": 2,
        "subtitle_group": "喵萌",
        "rss_urls": ("https://ab.invalid/a",),
        "rss_ids": ("rss-1", "rss-1"),
    }
    values.update(overrides)
    return ExternalSubscription(**values)  # type: ignore[arg-type]


def local(**overrides: object) -> LocalTrackingEvidence:
    values: dict[str, object] = {
        "tracking_id": "trk-local",
        "status": "UNKNOWN",
        "plan_summary": {"title": "葬送的芙莉莲", "season": 2, "subtitle_group": "喵萌"},
        "rss_urls": ("https://ab.invalid/a",),
    }
    values.update(overrides)
    return LocalTrackingEvidence(**values)  # type: ignore[arg-type]


def test_external_id_has_priority_and_produces_safe_mapping() -> None:
    result = reconcile_subscription(
        external(),
        [local(external_mapping={"subscription_id": "sub-1"})],
    )
    assert result.tracking_id == "trk-local"
    assert result.match_reason == "EXTERNAL_ID"
    assert result.status == "ACTIVE"
    assert result.safe_mapping() == {
        "schema_version": 1,
        "adapter": "legacy_3_1",
        "subscription_id": "sub-1",
        "rss_ids": ["rss-1"],
        "match_reason": "EXTERNAL_ID",
        "external_deleted": False,
        "enabled": True,
        "missing_sync_count": 0,
        "last_verified_at": None,
    }
    assert "https://ab.invalid" not in repr(result)


def test_reconcile_can_emit_a_connection_bound_mapping_without_external_details() -> None:
    connection_ref = "11111111-1111-4111-8111-111111111111"
    mapping = reconcile_subscription(external(), [local()]).safe_mapping(
        connection_ref=connection_ref
    )
    assert mapping["schema_version"] == 2
    assert mapping["connection_ref"] == connection_ref
    assert "https://ab.invalid" not in str(mapping)


def test_unique_exact_fields_match_and_conflicting_rss_does_not_match() -> None:
    result = reconcile_subscription(external(), [local()])
    assert result.match_reason == "EXACT_FIELDS"
    assert result.tracking_id == "trk-local"

    conflict = reconcile_subscription(external(), [local(rss_urls=("https://ab.invalid/other",))])
    assert conflict.tracking_id is None
    assert conflict.match_reason == "EXTERNAL_ONLY"


def test_zero_and_multiple_candidates_are_safe_external_only() -> None:
    zero = reconcile_subscription(external(), [local(plan_summary={"title": "different"})])
    assert zero.tracking_id is None
    assert zero.status == "EXTERNAL_ONLY"

    ambiguous = reconcile_subscription(external(), [local(tracking_id="a"), local(tracking_id="b")])
    assert ambiguous.tracking_id is None
    assert ambiguous.warning == "AMBIGUOUS_EXTERNAL_MATCH"


def test_deleted_and_in_progress_status_mapping() -> None:
    deleted = reconcile_subscription(external(deleted=True), [local()])
    assert deleted.status == "DISABLED"

    pending = reconcile_subscription(external(), [local(status="SUBMITTING")])
    assert pending.status == "SUBMITTING"

    missing = classify_missing_mapping(
        local(status="ACTIVE", external_mapping={"subscription_id": "sub-1"}),
        complete_subscription_list=True,
    )
    assert missing is not None
    assert missing.status == "EXTERNAL_DELETED"

    protected = classify_missing_mapping(
        local(status="REVALIDATING", external_mapping={"subscription_id": "sub-1"}),
        complete_subscription_list=True,
    )
    assert protected is not None
    assert protected.status == "REVALIDATING"


def test_saved_sync_excludes_other_connection_id_and_requires_rss_proof() -> None:
    ref = "11111111-1111-4111-8111-111111111111"
    other = local(rss_urls=("https://ab.invalid/other",), external_mapping={"subscription_id": "sub-1", "connection_ref": "22222222-2222-4222-8222-222222222222"})
    assert reconcile_subscription(external(), [other], connection_ref=ref).tracking_id is None
    no_rss = local(rss_urls=(), external_mapping={"subscription_id": "sub-1"})
    assert reconcile_subscription(external(), [no_rss], connection_ref=ref).tracking_id is None


def test_saved_sync_cross_connection_requires_unique_rss_evidence() -> None:
    ref = "11111111-1111-4111-8111-111111111111"
    candidate = local(external_mapping={"subscription_id": "sub-old", "connection_ref": "22222222-2222-4222-8222-222222222222"})
    result = reconcile_subscription(external(), [candidate], connection_ref=ref)
    assert result.tracking_id == "trk-local"
    ambiguous = reconcile_subscription(external(), [candidate, local(tracking_id="other", external_mapping={"connection_ref": "33333333-3333-4333-8333-333333333333"})], connection_ref=ref)
    assert ambiguous.tracking_id is None


def test_saved_sync_same_connection_changed_mapping_requires_selected_rss() -> None:
    ref = "11111111-1111-4111-8111-111111111111"
    candidate = local(external_mapping={"subscription_id": "sub-old", "connection_ref": ref}, rss_urls=())
    result = reconcile_subscription(external(), [candidate], connection_ref=ref)
    assert result.tracking_id is None
    candidate_with_rss = local(
        external_mapping={"subscription_id": "sub-old", "connection_ref": ref},
    )
    proven = reconcile_subscription(external(), [candidate_with_rss], connection_ref=ref)
    assert proven.tracking_id == "trk-local"


def test_saved_sync_same_connection_unbound_mapping_requires_selected_rss() -> None:
    ref = "11111111-1111-4111-8111-111111111111"
    candidate = local(external_mapping={"connection_ref": ref}, rss_urls=())
    result = reconcile_subscription(external(), [candidate], connection_ref=ref)
    assert result.tracking_id is None


def test_saved_sync_does_not_match_legacy_mapping_without_request_rss() -> None:
    ref = "11111111-1111-4111-8111-111111111111"
    legacy = local(external_mapping={"subscription_id": "sub-1"}, rss_urls=())
    result = reconcile_subscription(external(), [legacy], connection_ref=ref)
    assert result.tracking_id is None
