from __future__ import annotations

import json

import pytest

from batch_engine.controllers.anime_title_parser import (
    FakeAnimeTitleParsingProvider,
    RuleAnimeTitleParsingProvider,
    parse_anime_title,
)
from batch_engine.models import (
    ANIME_TITLE_PARSE_SOURCE_FAKE,
    AnimeTitleParseResult,
    AnimeTitleParseSource,
    AnimeTitleQuery,
)
from shared.errors import Stage1Error


def test_fake_provider_parses_supported_shorthand_titles() -> None:
    provider = FakeAnimeTitleParsingProvider()

    results = [provider.parse(title) for title in ["萌王S4", "路哥S4", "杖剑谭S2", "邻家天使S2"]]

    assert [result.raw_title for result in results] == [
        "萌王S4",
        "路哥S4",
        "杖剑谭S2",
        "邻家天使S2",
    ]
    assert results[0].canonical_title_candidates[0] == "关于我转生变成史莱姆这档事 第四季"
    assert results[1].season_hint == "S4"
    assert results[2].season_hint == "S2"
    assert results[3].search_queries[0].startswith("关于邻家的天使大人")
    assert {result.source for result in results} == {ANIME_TITLE_PARSE_SOURCE_FAKE}


def test_default_parser_uses_deterministic_rules_not_the_fake_provider() -> None:
    result = parse_anime_title("路哥S4")

    assert result.canonical_title_candidates == ("欢迎来到实力至上主义的教室",)
    assert result.season_hint == "S4"
    assert result.source is AnimeTitleParseSource.ALIAS
    assert result.search_queries[:2] == ("实力至上主义教室 第四季", "欢迎来到实力至上主义的教室 第4季")
    assert {entry.source for entry in result.query_plan} >= {AnimeTitleParseSource.ALIAS, AnimeTitleParseSource.RULE, AnimeTitleParseSource.FALLBACK}
    assert result.normalized_title == "路哥 第四季"
    assert result.base_title == "路哥"
    assert result.season == 4


def test_known_rule_alias_is_high_confidence() -> None:
    result = parse_anime_title("杖剑谭S2")

    assert result.confidence >= 0.7
    assert result.needs_user_review is False


def test_known_alias_has_one_conservative_canonical_candidate() -> None:
    result = parse_anime_title("萌王S4")

    assert result.canonical_title_candidates == ("关于我转生变成史莱姆这档事",)
    assert result.needs_user_review is False


def test_unknown_title_falls_back_to_reviewable_safe_query() -> None:
    result = parse_anime_title("  未知简称S9  ")

    assert result.raw_title == "  未知简称S9  "
    assert result.canonical_title_candidates == ("未知简称",)
    assert result.search_queries[-1] == "未知简称S9"
    assert result.confidence == 0.45
    assert result.needs_user_review is True


def test_unknown_explicit_season_is_only_a_reviewable_search_hint() -> None:
    result = parse_anime_title("无职转生s4")

    assert result.base_title == "无职转生"
    assert result.normalized_title == "无职转生 第四季"
    assert result.season == 4
    assert result.season_hint == "S4"


def test_unknown_title_never_defaults_to_first_season() -> None:
    result = parse_anime_title("无职转生")

    assert result.season is None
    assert result.season_hint is None


def test_rule_provider_orders_correction_alias_rule_and_fallback_queries() -> None:
    from shared.models import TitleCorrection

    result = parse_anime_title(
        " 萌王Ｓ4 ",
        RuleAnimeTitleParsingProvider(
            corrections=[TitleCorrection(raw_title="萌王S4", canonical_title="转生史莱姆", query_correction="Tensei Slime")]
        ),
    )

    assert result.search_queries == (
        "Tensei Slime",
        "转生史莱姆 第四季",
        "转生史莱姆 第4季",
        "转生史莱姆 S4",
        "转生史莱姆 Season 4",
        "萌王S4",
    )
    assert [entry.source for entry in result.query_plan] == [
        AnimeTitleParseSource.CORRECTION,
        AnimeTitleParseSource.ALIAS,
        AnimeTitleParseSource.RULE,
        AnimeTitleParseSource.RULE,
        AnimeTitleParseSource.RULE,
        AnimeTitleParseSource.FALLBACK,
    ]
    assert result.needs_user_review is False


def test_rule_provider_keeps_unknown_and_overlong_query_plans_reviewable_and_bounded() -> None:
    result = parse_anime_title("未知标题" * 40)

    assert len(result.query_plan) <= 8
    assert result.source is AnimeTitleParseSource.RULE
    assert result.needs_user_review is True
    assert "未识别正式别名，请人工核对" in result.review_hints


def test_provider_failure_returns_recoverable_safe_error() -> None:
    sensitive_title = "token=secret https://private.example/Home/Search cookie SID /home/user/raw.html"
    provider = FakeAnimeTitleParsingProvider(fail_titles={sensitive_title.strip()})

    with pytest.raises(Stage1Error) as error:
        parse_anime_title(sensitive_title, provider)

    payload = error.value.as_dict()
    assert payload == {
        "error_type": "ai_title_parse_failed",
        "error_message": "AI 名称解析失败，请检查该条目后重试",
        "failed_step": "ai_title_parse",
        "details": {
            "provider_source": "unknown",
            "recoverable": True,
        },
    }
    assert "secret" not in str(payload)
    assert "private.example" not in str(payload)
    assert "cookie" not in str(payload)
    assert "/home/user" not in str(payload)


def test_unexpected_provider_exception_is_sanitized() -> None:
    class BrokenProvider:
        def parse(self, raw_title: str) -> AnimeTitleParseResult:
            raise RuntimeError(
                "token=secret http://private.example/raw <html>raw</html> /home/user/file"
            )

    with pytest.raises(Stage1Error) as error:
        parse_anime_title("萌王S4", BrokenProvider())

    payload = error.value.as_dict()
    assert payload["error_type"] == "ai_title_parse_failed"
    assert payload["error_message"] == "AI 名称解析失败，请检查该条目后重试"
    assert payload["failed_step"] == "ai_title_parse"
    assert payload["details"] == {
        "raw_title_length": 4,
        "provider_source": ANIME_TITLE_PARSE_SOURCE_FAKE,
        "recoverable": True,
    }
    assert "secret" not in str(payload)
    assert "private.example" not in str(payload)
    assert "<html>" not in str(payload)
    assert "/home/user" not in str(payload)


def test_provider_result_is_normalized_and_marks_ambiguous_output_for_review() -> None:
    class DuplicateProvider:
        def parse(self, raw_title: str) -> AnimeTitleParseResult:
            return AnimeTitleParseResult(
                raw_title="provider raw",
                canonical_title_candidates=["候选A", "候选B"],
                season_hint="S2",
                search_queries=["候选A", "候选B"],
                confidence=1.0,
                needs_user_review=False,
                source="custom",
            )

    result = parse_anime_title("原始输入", DuplicateProvider())

    assert result.raw_title == "原始输入"
    assert result.canonical_title_candidates == ("候选A", "候选B")
    assert result.search_queries == ("候选A", "候选B")
    assert result.confidence == 1.0
    assert result.needs_user_review is True
    assert result.source is AnimeTitleParseSource.FALLBACK


def test_parse_result_is_immutable_json_safe_and_derives_legacy_queries() -> None:
    result = AnimeTitleParseResult(
        raw_title="  无职转生s4  ",
        canonical_title_candidates=["无职转生 第四季"],
        season_hint="S4",
        search_queries=["无职转生 第四季", "无职转生 S4"],
        confidence=0.8,
        needs_user_review=False,
        source="untrusted-provider-detail",
        normalized_title="无职转生s4",
        base_title="无职转生",
        season=4,
        review_hints=["请核对"],
    )

    assert result.source is AnimeTitleParseSource.FALLBACK
    assert result.query_plan == (
        AnimeTitleQuery("无职转生 第四季", AnimeTitleParseSource.FALLBACK, 1),
        AnimeTitleQuery("无职转生 S4", AnimeTitleParseSource.FALLBACK, 2),
    )
    with pytest.raises(AttributeError):
        result.search_queries.append("不允许")  # type: ignore[attr-defined]
    payload = result.to_dict()
    assert json.loads(json.dumps(payload)) == payload
    assert payload["search_queries"] == [entry["query"] for entry in payload["query_plan"]]


@pytest.mark.parametrize(
    ("season", "query_count"),
    [(0, 1), (100, 1), (1, 9)],
)
def test_parse_result_rejects_out_of_bounds_season_and_query_plan(
    season: int, query_count: int
) -> None:
    queries = [f"查询 {index}" for index in range(query_count)]
    with pytest.raises(ValueError):
        AnimeTitleParseResult(
            raw_title="测试标题",
            canonical_title_candidates=["测试标题"],
            season_hint=None,
            search_queries=queries,
            confidence=0.5,
            needs_user_review=True,
            source=AnimeTitleParseSource.RULE,
            season=season,
        )
