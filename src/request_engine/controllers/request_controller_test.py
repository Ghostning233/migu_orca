from __future__ import annotations

import pytest

from request_engine.controllers.request_controller import (
    accept_request,
    build_pending_request,
    cancel_request,
    summarize_request,
    validate_modify_patch,
)
from shared.errors import Stage1Error
from shared.models import (
    EntryRequest,
    ExcludedSeed,
    FilteredRss,
    FilterRule,
    MatchedBangumi,
    RssSeed,
    RssSource,
    SubtitleGroupSelection,
)


def _pending_request() -> dict:
    return build_pending_request(
        EntryRequest("番剧"),
        MatchedBangumi("番剧", [], "https://example.invalid", 1.0),
        [],
        SubtitleGroupSelection(None, None, ["没有有效种子"]),
        FilterRule(),
        "番剧",
    )


def _pending_request_with_sources() -> dict:
    rss_results = [
        FilteredRss(
            RssSource("Loli", "https://example.invalid/loli.xml", "mikan", "loli.xml"),
            3,
            [
                RssSeed("[Loli] 番剧 - 01", "https://example.invalid/1"),
                RssSeed("[Loli] 番剧 - 02", "https://example.invalid/2"),
            ],
            [
                ExcludedSeed(
                    "[Loli] 番剧 - SP",
                    "命中排除关键词",
                    "must_not_contain=SP",
                ),
            ],
            ["Loli RSS 缺少发布日期"],
        ),
        FilteredRss(
            RssSource("NC", "https://example.invalid/nc.xml", "mikan", "nc.xml"),
            1,
            [RssSeed("[NC] 番剧 - 01", "https://example.invalid/nc-1")],
            [],
        ),
    ]
    return build_pending_request(
        EntryRequest("番剧"),
        MatchedBangumi("番剧", ["Bangumi"], "https://mikan.example/bangumi", 0.95),
        rss_results,
        SubtitleGroupSelection("Loli", "https://example.invalid/loli.xml", []),
        FilterRule(must_not_contain="SP"),
        "番剧",
        ["候选标题由别名匹配"],
    )


def test_request_is_pending_snapshot_not_state_machine() -> None:
    request = _pending_request()

    assert request["status"] == "PENDING_CONFIRM"
    assert request["confirmable_config"]["selected_subtitle_group"] is None
    assert request["confirmable_config"]["warnings"] == ["没有有效种子"]


def test_accept_request_marks_pending_request_accepted_without_mutating_original() -> None:
    request = _pending_request()

    accepted = accept_request(request)

    assert request["status"] == "PENDING_CONFIRM"
    assert "user_action" not in request
    assert accepted["status"] == "ACCEPTED"
    assert accepted["updated_at"] >= request["updated_at"]
    assert accepted["ab_submit_result"] is None
    assert accepted["user_action"] == {
        "action": "ACCEPT",
        "reason": None,
        "decided_at": accepted["updated_at"],
    }


def test_cancel_request_marks_pending_request_cancelled_with_reason() -> None:
    request = _pending_request()

    cancelled = cancel_request(request, "匹配结果不符合预期")

    assert request["status"] == "PENDING_CONFIRM"
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["user_action"] == {
        "action": "CANCEL",
        "reason": "匹配结果不符合预期",
        "decided_at": cancelled["updated_at"],
    }


def test_accept_and_cancel_reject_non_pending_request() -> None:
    accepted = accept_request(_pending_request())

    with pytest.raises(Stage1Error) as accept_error:
        accept_request(accepted)
    with pytest.raises(Stage1Error) as cancel_error:
        cancel_request(accepted, "不需要")

    assert accept_error.value.error_type == "invalid_request_status"
    assert cancel_error.value.details == {"status": "ACCEPTED"}


def test_cancel_request_rejects_empty_reason() -> None:
    with pytest.raises(Stage1Error) as error:
        cancel_request(_pending_request(), "  ")

    assert error.value.error_type == "invalid_cancel_reason"


def test_summarize_request_returns_compact_confirmation_view() -> None:
    request = _pending_request_with_sources()

    summary = summarize_request(request)

    assert summary == {
        "request_id": request["request_id"],
        "status": "PENDING_CONFIRM",
        "bangumi_title": "番剧",
        "candidate_subtitle_groups": [
            {
                "subtitle_group": "Loli",
                "rss_url": "https://example.invalid/loli.xml",
                "total_seed_count": 3,
                "valid_seed_count": 2,
                "invalid_seed_count": 1,
            },
            {
                "subtitle_group": "NC",
                "rss_url": "https://example.invalid/nc.xml",
                "total_seed_count": 1,
                "valid_seed_count": 1,
                "invalid_seed_count": 0,
            },
        ],
        "selected_subtitle_group": "Loli",
        "effective_seed_count": 2,
        "expected_folder_name": "番剧",
        "warnings": ["候选标题由别名匹配", "Loli RSS 缺少发布日期"],
    }


def test_summarize_request_does_not_mutate_or_replace_original_json_contract() -> None:
    request = _pending_request_with_sources()
    original = dict(request)

    summary = summarize_request(request)

    assert request == original
    assert request["confirmable_config"]["effective_seed_names"] == [
        "[Loli] 番剧 - 01",
        "[Loli] 番剧 - 02",
    ]
    assert "source_info" in request
    assert "source_info" not in summary


def test_validate_modify_patch_allows_only_confirmable_fields() -> None:
    patch = {
        "selected_subtitle_group": "NC",
        "filter_rule": {"must_contain": "1080p", "must_not_contain": "SP"},
        "expected_folder_name": "  番剧 NC  ",
    }

    validated = validate_modify_patch(patch)

    assert validated == {
        "selected_subtitle_group": "NC",
        "filter_rule": {"must_contain": "1080p", "must_not_contain": "SP"},
        "expected_folder_name": "番剧 NC",
    }
    assert patch["expected_folder_name"] == "  番剧 NC  "


@pytest.mark.parametrize(
    "field",
    ["effective_seed_names", "source_info", "matched_bangumi", "status"],
)
def test_validate_modify_patch_rejects_unconfirmable_fields(field: str) -> None:
    with pytest.raises(Stage1Error) as error:
        validate_modify_patch({field: "value"})

    assert error.value.error_type == "invalid_modify_patch_field"
    assert error.value.details["illegal_fields"] == [field]
    assert error.value.details["allowed_fields"] == [
        "expected_folder_name",
        "filter_rule",
        "selected_subtitle_group",
    ]


def test_validate_modify_patch_rejects_illegal_filter_rule_fields() -> None:
    with pytest.raises(Stage1Error) as error:
        validate_modify_patch({"filter_rule": {"effective_seed_names": []}})

    assert error.value.error_type == "invalid_modify_patch_field"
    assert error.value.details["illegal_fields"] == [
        "filter_rule.effective_seed_names"
    ]


@pytest.mark.parametrize(
    ("patch", "field"),
    [
        ([], None),
        ({"selected_subtitle_group": 1}, "selected_subtitle_group"),
        ({"expected_folder_name": "  "}, "expected_folder_name"),
        ({"filter_rule": []}, "filter_rule"),
        ({"filter_rule": {"must_contain": 1080}}, "filter_rule.must_contain"),
        ({"filter_rule": {"must_not_contain": "["}}, "filter_rule.must_not_contain"),
    ],
)
def test_validate_modify_patch_rejects_invalid_patch_values(
    patch: object,
    field: str | None,
) -> None:
    with pytest.raises(Stage1Error) as error:
        validate_modify_patch(patch)  # type: ignore[arg-type]

    assert error.value.error_type == "invalid_modify_patch"
    if field is not None:
        assert error.value.details["field"] == field
