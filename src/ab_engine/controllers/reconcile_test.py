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

