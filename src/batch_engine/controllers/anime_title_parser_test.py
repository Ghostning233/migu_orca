from __future__ import annotations

import pytest

from batch_engine.controllers.anime_title_parser import (
    FakeAnimeTitleParsingProvider,
    parse_anime_title,
)
from batch_engine.models import ANIME_TITLE_PARSE_SOURCE_FAKE, AnimeTitleParseResult
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


def test_parse_anime_title_returns_searchable_metadata() -> None:
    result = parse_anime_title("路哥S4")

    assert result == AnimeTitleParseResult(
        raw_title="路哥S4",
        canonical_title_candidates=["欢迎来到实力至上主义的教室 第四季"],
        season_hint="S4",
        search_queries=[
            "欢迎来到实力至上主义的教室 第四季",
            "实力至上主义教室 S4",
            "路哥 S4",
        ],
        confidence=0.9,
        needs_user_review=False,
        source=ANIME_TITLE_PARSE_SOURCE_FAKE,
    )


def test_low_confidence_result_needs_user_review() -> None:
    result = parse_anime_title("杖剑谭S2")

    assert result.confidence < 0.7
    assert result.needs_user_review is True


def test_multiple_candidates_need_user_review() -> None:
    result = parse_anime_title("萌王S4")

    assert len(result.canonical_title_candidates) == 2
    assert result.needs_user_review is True


def test_unknown_title_falls_back_to_reviewable_safe_query() -> None:
    result = parse_anime_title("  未知简称S9  ")

    assert result.raw_title == "  未知简称S9  "
    assert result.canonical_title_candidates == ["未知简称S9"]
    assert result.search_queries == ["未知简称S9"]
    assert result.confidence == 0.4
    assert result.needs_user_review is True


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
                canonical_title_candidates=[" 候选A ", "候选A", "候选B"],
                season_hint="S2",
                search_queries=[" 候选A ", "", "候选A", "候选B"],
                confidence=1.4,
                needs_user_review=False,
                source="custom",
            )

    result = parse_anime_title("原始输入", DuplicateProvider())

    assert result.raw_title == "原始输入"
    assert result.canonical_title_candidates == ["候选A", "候选B"]
    assert result.search_queries == ["候选A", "候选B"]
    assert result.confidence == 1.0
    assert result.needs_user_review is True
