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


def test_similar_fields_are_never_ownership_evidence() -> None:
    """Issue #88: a matching title/season/group/RSS set does not claim an object."""
    result = reconcile_subscription(external(), [local()])

    assert result.tracking_id is None
    assert result.managed is False
    assert result.match_reason == "UNMANAGED"

    conflict = reconcile_subscription(external(), [local(rss_urls=("https://ab.invalid/other",))])
    assert conflict.tracking_id is None
    assert conflict.managed is False


def test_unmapped_objects_are_unmanaged_and_ambiguous_mappings_claim_nothing() -> None:
    zero = reconcile_subscription(external(), [local(plan_summary={"title": "different"})])
    assert zero.tracking_id is None
    assert zero.managed is False
    # Structural status stays a value the storage schema accepts; the sync use
    # case is what refuses to write it (issue #88).
    assert zero.status == "EXTERNAL_ONLY"

    ambiguous = reconcile_subscription(
        external(),
        [
            local(tracking_id="a", external_mapping={"subscription_id": "sub-1"}),
            local(tracking_id="b", external_mapping={"subscription_id": "sub-1"}),
        ],
    )
    assert ambiguous.tracking_id is None
    assert ambiguous.managed is False
    assert ambiguous.warning == "AMBIGUOUS_EXTERNAL_MATCH"


def test_deleted_and_in_progress_status_mapping() -> None:
    deleted = reconcile_subscription(
        external(deleted=True), [local(external_mapping={"subscription_id": "sub-1"})]
    )
    assert deleted.status == "DISABLED"
    assert deleted.managed is True

    pending = reconcile_subscription(
        external(), [local(status="SUBMITTING", external_mapping={"subscription_id": "sub-1"})]
    )
    assert pending.status == "SUBMITTING"
    assert pending.managed is True

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


def test_saved_sync_never_adopts_a_similar_object_from_another_connection() -> None:
    """Issue #88: even with identical fields+RSS, another connection is not ours."""
    ref = "11111111-1111-4111-8111-111111111111"
    other_connection = local(
        external_mapping={"subscription_id": "sub-1", "connection_ref": "22222222-2222-4222-8222-222222222222"}
    )
    result = reconcile_subscription(external(), [other_connection], connection_ref=ref)
    assert result.tracking_id is None
    assert result.managed is False

    ambiguous = reconcile_subscription(
        external(),
        [
            other_connection,
            local(tracking_id="other", external_mapping={"connection_ref": "33333333-3333-4333-8333-333333333333"}),
        ],
        connection_ref=ref,
    )
    assert ambiguous.tracking_id is None
    assert ambiguous.managed is False


def test_saved_sync_only_claims_an_exact_connection_bound_mapping() -> None:
    """Issue #88: only the exact external id on the same connection is ours."""
    ref = "11111111-1111-4111-8111-111111111111"
    other_id = local(external_mapping={"subscription_id": "sub-old", "connection_ref": ref})
    assert reconcile_subscription(external(), [other_id], connection_ref=ref).tracking_id is None

    exact = local(external_mapping={"subscription_id": "sub-1", "connection_ref": ref})
    claimed = reconcile_subscription(external(), [exact], connection_ref=ref)
    assert claimed.tracking_id == "trk-local"
    assert claimed.managed is True
    assert claimed.match_reason == "EXTERNAL_ID"


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
