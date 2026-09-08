from __future__ import annotations

"""US-224: pure pre-submit revalidation classifier tests (PRD §11.5)."""

from request_engine.controllers.request_controller import ACCEPTED, CANCELLED
from tracking_engine.controllers.revalidate import (
    REVALIDATE_ISSUE_EXTERNAL_ALREADY_LINKED,
    REVALIDATE_ISSUE_MIKAN_SELECTION_MISSING,
    REVALIDATE_ISSUE_NO_VALID_RESOURCES,
    REVALIDATE_ISSUE_OPERATION_IN_PROGRESS,
    REVALIDATE_ISSUE_REQUEST_CHANGED,
    REVALIDATE_ISSUE_REQUEST_MISSING,
    REVALIDATE_ISSUE_REQUEST_NOT_ACCEPTED,
    REVALIDATE_ISSUE_SEASON_REVIEW_REQUIRED,
    REVALIDATE_ISSUE_SUBTITLE_GROUP_MISSING,
    REVALIDATE_ISSUE_TITLE_MISSING,
    REVALIDATE_ISSUE_TRACKING_STATE_INVALID,
    RevalidationEvidence,
    classify_revalidation,
)
from tracking_engine.models.tracking import (
    TRACKING_ORIGIN_SAVE_CONFIRM,
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_PENDING_SUBMIT,
    TrackingRecord,
    create_tracking_record,
)

FINGERPRINT_CONFIRMED = "a" * 64
FINGERPRINT_CURRENT = "b" * 64


def _record(
    *,
    status: str = TRACKING_STATUS_PENDING_SUBMIT,
    fingerprint: str | None = FINGERPRINT_CONFIRMED,
    external_mapping: dict[str, object] | None = None,
) -> TrackingRecord:
    return create_tracking_record(
        request_id="request-1",
        status=status,
        plan_summary={
            "title": "葬送的芙莉莲",
            "season": 1,
            "subtitle_group": "喵萌",
        },
        origin=TRACKING_ORIGIN_SAVE_CONFIRM,
        request_fingerprint=fingerprint,
    )


def _request(
    *,
    status: str = ACCEPTED,
    title: str = "葬送的芙莉莲",
    season: int | None = None,
    season_raw: str | None = None,
    season_evidence: str | None = None,
    mikan_url: str = "https://example.invalid/Home/Bangumi/12345",
    subtitle_group: str = "喵萌",
    valid_seed_names: list[str] | None = None,
    effective_seed_names: list[str] | None = None,
    request_id: str = "request-1",
) -> dict[str, object]:
    if valid_seed_names is None:
        valid_seed_names = ["seed-1"]
    if effective_seed_names is None:
        effective_seed_names = ["seed-1"]
    matched: dict[str, object] = {
        "title": title,
        "mikan_url": mikan_url,
        "aliases": [],
    }
    if season is not None:
        matched["season"] = season
    if season_raw is not None:
        matched["season_raw"] = season_raw
    if season_evidence is not None:
        matched["season_evidence"] = season_evidence
    source = {
        "subtitle_group": subtitle_group,
        "rss_url": "https://example.invalid/rss",
        "total_seed_count": len(valid_seed_names or []),
        "valid_seed_count": len(valid_seed_names or []),
        "invalid_seed_count": 0,
        "valid_seed_names": valid_seed_names or [],
        "excluded_seed_names": [],
    }
    return {
        "request_id": request_id,
        "status": status,
        "input": {"raw_title": title},
        "source_info": {
            "matched_bangumi": matched,
            "rss_sources": [source],
        },
        "confirmable_config": {
            "selected_subtitle_group": subtitle_group,
            "filter_rule": {
                "must_contain": "",
                "must_not_contain": "",
                "use_regex": False,
                "case_sensitive": False,
            },
            "expected_folder_name": "芙莉莲",
            "effective_seed_names": effective_seed_names if effective_seed_names is not None else [],
        },
    }


def _codes(issues: object) -> list[str]:
    return [issue.code for issue in issues]  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Ready path
# ---------------------------------------------------------------------------


def test_healthy_accepted_request_is_ready() -> None:
    record = _record(fingerprint=FINGERPRINT_CONFIRMED)
    request = _request()
    evidence = RevalidationEvidence(
        request=request,
        request_fingerprint=FINGERPRINT_CONFIRMED,
    )
    assert classify_revalidation(record, evidence) == ()


def test_legacy_request_without_season_or_bangumi_id_is_ready() -> None:
    # A legacy plan with no season marker and an arbitrary collection URL is
    # still a valid confirmed plan (mirrors the static-fixture accepted
    # Request used across Stage 29).
    record = _record(fingerprint="fp")
    request = _request(season=None, season_raw=None, mikan_url="https://example.invalid/bangumi/frieren")
    evidence = RevalidationEvidence(request=request, request_fingerprint="fp")
    assert classify_revalidation(record, evidence) == ()


# ---------------------------------------------------------------------------
# Hard short-circuit checks
# ---------------------------------------------------------------------------


def test_missing_request_reports_request_missing() -> None:
    record = _record()
    evidence = RevalidationEvidence(request=None, request_fingerprint=None)
    assert _codes(classify_revalidation(record, evidence)) == [
        REVALIDATE_ISSUE_REQUEST_MISSING
    ]


def test_not_accepted_request_reports_request_not_accepted() -> None:
    record = _record()
    request = _request(status=CANCELLED)
    evidence = RevalidationEvidence(
        request=request, request_fingerprint=FINGERPRINT_CURRENT
    )
    assert _codes(classify_revalidation(record, evidence)) == [
        REVALIDATE_ISSUE_REQUEST_NOT_ACCEPTED
    ]


def test_non_revalidatable_tracking_state_reports_state_invalid() -> None:
    record = _record(status=TRACKING_STATUS_ACTIVE)
    request = _request()
    evidence = RevalidationEvidence(
        request=request, request_fingerprint=FINGERPRINT_CURRENT
    )
    assert _codes(classify_revalidation(record, evidence)) == [
        REVALIDATE_ISSUE_TRACKING_STATE_INVALID
    ]


def test_operation_in_progress_reports_operation_issue() -> None:
    record = _record()
    request = _request()
    evidence = RevalidationEvidence(
        request=request,
        request_fingerprint=FINGERPRINT_CONFIRMED,
        operation_in_progress=True,
    )
    assert _codes(classify_revalidation(record, evidence)) == [
        REVALIDATE_ISSUE_OPERATION_IN_PROGRESS
    ]


# ---------------------------------------------------------------------------
# Plan-content checks
# ---------------------------------------------------------------------------


def test_changed_fingerprint_reports_request_changed() -> None:
    record = _record(fingerprint=FINGERPRINT_CONFIRMED)
    request = _request()
    evidence = RevalidationEvidence(
        request=request, request_fingerprint=FINGERPRINT_CURRENT
    )
    assert _codes(classify_revalidation(record, evidence)) == [
        REVALIDATE_ISSUE_REQUEST_CHANGED
    ]
    issue = classify_revalidation(record, evidence)[0]
    assert issue.recovery_action == "SUBMIT"
    assert issue.message == "订阅方案已发生修改，请确认最新方案后再提交"


def test_blank_title_reports_title_missing() -> None:
    record = _record()
    request = _request(title="  ")
    evidence = RevalidationEvidence(
        request=request, request_fingerprint=FINGERPRINT_CONFIRMED
    )
    assert REVALIDATE_ISSUE_TITLE_MISSING in _codes(
        classify_revalidation(record, evidence)
    )


def test_season_marker_without_season_reports_review_required() -> None:
    record = _record()
    request = _request(season=None, season_raw="第2季", season_evidence="candidate_public_title")
    evidence = RevalidationEvidence(
        request=request, request_fingerprint=FINGERPRINT_CONFIRMED
    )
    assert REVALIDATE_ISSUE_SEASON_REVIEW_REQUIRED in _codes(
        classify_revalidation(record, evidence)
    )


def test_season_positive_int_with_marker_is_ready() -> None:
    record = _record()
    request = _request(season=2, season_raw="第2季", season_evidence="candidate_public_title")
    evidence = RevalidationEvidence(
        request=request, request_fingerprint=FINGERPRINT_CONFIRMED
    )
    assert classify_revalidation(record, evidence) == ()


def test_missing_mikan_url_reports_selection_missing() -> None:
    record = _record()
    request = _request(mikan_url="")
    evidence = RevalidationEvidence(
        request=request, request_fingerprint=FINGERPRINT_CONFIRMED
    )
    assert REVALIDATE_ISSUE_MIKAN_SELECTION_MISSING in _codes(
        classify_revalidation(record, evidence)
    )


def test_missing_subtitle_group_reports_group_missing() -> None:
    record = _record()
    request = _request(subtitle_group="")
    evidence = RevalidationEvidence(
        request=request, request_fingerprint=FINGERPRINT_CONFIRMED
    )
    assert REVALIDATE_ISSUE_SUBTITLE_GROUP_MISSING in _codes(
        classify_revalidation(record, evidence)
    )


def test_no_valid_resources_reports_no_valid_resources() -> None:
    record = _record()
    request = _request(valid_seed_names=[], effective_seed_names=[])
    evidence = RevalidationEvidence(
        request=request, request_fingerprint=FINGERPRINT_CONFIRMED
    )
    assert REVALIDATE_ISSUE_NO_VALID_RESOURCES in _codes(
        classify_revalidation(record, evidence)
    )


def test_external_mapping_reports_already_linked() -> None:
    from dataclasses import replace

    record = replace(
        _record(),
        external_mapping={"external_subscription_id": "ext-1"},
    )
    request = _request()
    evidence = RevalidationEvidence(
        request=request, request_fingerprint=FINGERPRINT_CONFIRMED
    )
    assert REVALIDATE_ISSUE_EXTERNAL_ALREADY_LINKED in _codes(
        classify_revalidation(record, evidence)
    )


def test_multiple_issues_return_in_fixed_enum_order() -> None:
    record = _record()
    request = _request(
        title="",
        season_raw="第2季",
        season=None,
        subtitle_group="",
        valid_seed_names=[],
        effective_seed_names=[],
    )
    evidence = RevalidationEvidence(
        request=request, request_fingerprint=FINGERPRINT_CURRENT
    )
    codes = _codes(classify_revalidation(record, evidence))
    assert codes == [
        REVALIDATE_ISSUE_REQUEST_CHANGED,
        REVALIDATE_ISSUE_TITLE_MISSING,
        REVALIDATE_ISSUE_SEASON_REVIEW_REQUIRED,
        REVALIDATE_ISSUE_SUBTITLE_GROUP_MISSING,
        REVALIDATE_ISSUE_NO_VALID_RESOURCES,
    ]
