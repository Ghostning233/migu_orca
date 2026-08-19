from __future__ import annotations

from shared.models import FilteredRss, RssSeed, RssSource
from subscription_engine.controllers.subscription_controller import (
    generate_folder_name,
    select_subtitle_group,
)


def _result(group: str, valid_count: int) -> FilteredRss:
    source = RssSource(group, f"https://example.invalid/{group}", "static_fixture", "x")
    return FilteredRss(
        source=source,
        total_seed_count=valid_count,
        valid_seeds=[RssSeed(f"{group}-{index}", str(index)) for index in range(valid_count)],
        excluded_seeds=[],
    )


def test_selection_uses_user_priority_and_ignores_empty_group() -> None:
    selection = select_subtitle_group(
        [_result("Loli", 0), _result("喵萌", 1), _result("其他", 1)],
        ["Loli", "喵萌"],
    )

    assert selection.subtitle_group == "喵萌"


def test_all_empty_returns_no_selection_with_warning() -> None:
    selection = select_subtitle_group([_result("Loli", 0)], ["Loli"])

    assert selection.subtitle_group is None
    assert selection.rss_url is None
    assert selection.warnings


def test_excluded_group_is_never_selected_even_when_preferred() -> None:
    selection = select_subtitle_group(
        [_result("Loli", 1), _result("喵萌", 1)],
        ["Loli", "喵萌"],
        excluded=["Loli"],
    )

    assert selection.subtitle_group == "喵萌"
    assert selection.warnings == []


def test_all_excluded_groups_return_no_selection_with_warning() -> None:
    selection = select_subtitle_group(
        [_result("Loli", 1), _result("喵萌", 1)],
        ["Loli", "喵萌"],
        excluded=["Loli", "喵萌"],
    )

    assert selection.subtitle_group is None
    assert selection.rss_url is None
    assert "被排除" in selection.warnings[0]


def test_excluded_group_with_no_valid_seed_is_not_counted_as_usable() -> None:
    selection = select_subtitle_group(
        [_result("Loli", 0), _result("喵萌", 1)],
        ["Loli"],
        excluded=["喵萌"],
    )

    assert selection.subtitle_group is None
    assert selection.warnings


def test_priority_miss_falls_back_to_first_valid_non_excluded_group() -> None:
    selection = select_subtitle_group(
        [_result("Loli", 1), _result("喵萌", 1), _result("示例组", 1)],
        ["不存在组"],
        excluded=["示例组"],
    )

    assert selection.subtitle_group == "Loli"
    assert selection.warnings


def test_folder_name_replaces_dangerous_characters() -> None:
    assert generate_folder_name("  A/B\\C\x00  ") == "A_B_C_"
