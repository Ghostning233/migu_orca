from __future__ import annotations

import pytest

from shared.title_season import parse_title_season


@pytest.mark.parametrize(
    ("title", "base", "season", "normalized"),
    [
        ("无职转生s4", "无职转生", 4, "无职转生 第四季"),
        ("作品 S ４", "作品", 4, "作品 第四季"),
        ("作品 Season 12", "作品", 12, "作品 第十二季"),
        ("作品 第四季", "作品", 4, "作品 第四季"),
        ("作品 第１２期", "作品", 12, "作品 第十二季"),
        ("作品 第九十九季", "作品", 99, "作品 第九十九季"),
        ("作品 S4 / Season 4 / 第四季", "作品 / /", 4, "作品 / / 第四季"),
    ],
)
def test_parse_title_season_recognizes_explicit_supported_forms(
    title: str, base: str, season: int, normalized: str
) -> None:
    result = parse_title_season(title)

    assert result.base_title == base
    assert result.season == season
    assert result.season_hint == f"S{season}"
    assert result.normalized_title == normalized


@pytest.mark.parametrize("title", ["作品", "作品 S0", "作品 S100", "作品 Season", "作品 第百季", "作品 Part 2", "作品 分割放送"])
def test_parse_title_season_never_guesses_or_accepts_unprovable_markers(title: str) -> None:
    result = parse_title_season(title)

    assert result.season is None
    assert result.season_hint is None
    if title != "作品":
        assert result.review_hints == ("季数标记无法确认，请人工核对",)


def test_parse_title_season_requires_review_for_conflicting_markers() -> None:
    result = parse_title_season("作品 S2 第三季")

    assert result.season is None
    assert result.review_hints == ("识别到冲突季数，请人工核对",)
