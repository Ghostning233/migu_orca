from __future__ import annotations

import pytest

from mikan_engine.controllers.mikan_candidate_recommendation import (
    _extract_season,
    candidate_recommendation_label,
)


class TestExtractSeason:
    """AC: 推荐逻辑必须对 第一季/第二季/第三季、S1/S2/S3、I/II/III 等基础季数词有测试覆盖."""

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("葬送的芙莉莲 第一季", 1),
            ("葬送的芙莉莲 第二季", 2),
            ("葬送的芙莉莲 第三季", 3),
            ("葬送的芙莉莲 第四季", 4),
            ("葬送的芙莉莲 第十季", 10),
            ("葬送的芙莉莲 第十二季", 12),
            ("葬送的芙莉莲 第二十季", 20),
            ("葬送的芙莉莲 第 2 季", 2),
            ("葬送的芙莉莲 第 二 季", 2),
        ],
    )
    def test_chinese_season(self, text: str, expected: int) -> None:
        assert _extract_season(text) == expected

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("葬送的芙莉莲 S1", 1),
            ("葬送的芙莉莲 S2", 2),
            ("葬送的芙莉莲 S3", 3),
            ("葬送的芙莉莲 s3", 3),
            ("葬送的芙莉莲 S01", 1),
            ("葬送的芙莉莲 S12", 12),
            ("葬送的芙莉莲 Season 2", 2),
        ],
    )
    def test_ascii_season(self, text: str, expected: int) -> None:
        assert _extract_season(text) == expected

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("葬送的芙莉莲 I", 1),
            ("葬送的芙莉莲 II", 2),
            ("葬送的芙莉莲 III", 3),
            ("葬送的芙莉莲 IV", 4),
            ("葬送的芙莉莲 (II)", 2),
            ("葬送的芙莉莲（III）", 3),
        ],
    )
    def test_roman_season(self, text: str, expected: int) -> None:
        assert _extract_season(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "葬送的芙莉莲",  # no season marker
            "I Am a Hero",  # leading English word I must not read as season 1
            "FantasyS2",  # S2 glued to a word is not a season marker
            "第二季",  # season-only, no title (still extracted though)
        ],
    )
    def test_no_false_season(self, text: str) -> None:
        # The last case deliberately extracts a season; the first three must not.
        if text == "第二季":
            assert _extract_season(text) == 2
        else:
            assert _extract_season(text) is None


class TestCandidateRecommendationLabel:
    """AC: display-only labels; strong copy only on a confident season match."""

    def test_strong_match_chinese_season(self) -> None:
        assert (
            candidate_recommendation_label("芙莉莲 第二季", "葬送的芙莉莲 第二季")
            == "推荐：第 2 季"
        )

    def test_strong_match_ascii_season(self) -> None:
        assert (
            candidate_recommendation_label("芙莉莲 S2", "葬送的芙莉莲 S2")
            == "推荐：第 2 季"
        )

    def test_strong_match_roman_season(self) -> None:
        assert (
            candidate_recommendation_label("芙莉莲 II", "葬送的芙莉莲 II")
            == "推荐：第 2 季"
        )

    def test_strong_match_normalizes_chinese_season_to_arabic(self) -> None:
        assert (
            candidate_recommendation_label("芙莉莲 第一季", "葬送的芙莉莲 第一季")
            == "推荐：第 1 季"
        )

    def test_strong_match_via_alias_season(self) -> None:
        assert (
            candidate_recommendation_label(
                "芙莉莲 第二季",
                "葬送的芙莉莲",
                ["葬送的芙莉莲 第二季"],
            )
            == "推荐：第 2 季"
        )

    def test_conflicting_season_shows_no_strong_copy(self) -> None:
        label = candidate_recommendation_label("芙莉莲 第二季", "葬送的芙莉莲 第一季")
        assert label == "季数不符"
        assert "推荐：" not in label

    def test_conflicting_season_ascii(self) -> None:
        assert (
            candidate_recommendation_label("芙莉莲 S2", "葬送的芙莉莲 S1")
            == "季数不符"
        )

    def test_low_confidence_query_season_but_candidate_has_none(self) -> None:
        label = candidate_recommendation_label("芙莉莲 第二季", "葬送的芙莉莲")
        assert label == "可能匹配"
        assert "推荐：" not in label

    def test_low_confidence_no_query_season_but_candidate_has_season(self) -> None:
        label = candidate_recommendation_label("芙莉莲", "葬送的芙莉莲 第三季")
        assert label == "可能匹配"
        assert "推荐：" not in label

    def test_pure_title_similarity_label(self) -> None:
        assert candidate_recommendation_label("芙莉莲", "葬送的芙莉莲") == "可能匹配"

    def test_alias_similarity_label(self) -> None:
        assert (
            candidate_recommendation_label("Frieren", "葬送的芙莉莲", ["Frieren"])
            == "可能匹配"
        )

    def test_candidate_shorter_than_query_matches(self) -> None:
        assert candidate_recommendation_label("葬送的芙莉莲", "芙莉莲") == "可能匹配"

    def test_no_basename_match_returns_none(self) -> None:
        assert candidate_recommendation_label("芙莉莲", "咒术回战") is None

    def test_empty_query_returns_none(self) -> None:
        assert candidate_recommendation_label("   ", "葬送的芙莉莲") is None

    def test_empty_title_returns_none(self) -> None:
        assert candidate_recommendation_label("芙莉莲", "   ") is None

    def test_season_only_query_returns_none(self) -> None:
        # Stripping the season marker leaves an empty basename, so no confident
        # title signal exists to recommend against.
        assert candidate_recommendation_label("第二季", "葬送的芙莉莲 第二季") is None
