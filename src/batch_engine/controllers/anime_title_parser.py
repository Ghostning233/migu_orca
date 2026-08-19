from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from batch_engine.models import ANIME_TITLE_PARSE_SOURCE_FAKE, AnimeTitleParseResult
from shared.errors import Stage1Error


LOW_CONFIDENCE_THRESHOLD = 0.7


class AnimeTitleParsingProvider(Protocol):
    def parse(self, raw_title: str) -> AnimeTitleParseResult:
        """Parse a shorthand anime title into reviewable search metadata."""


class FakeAnimeTitleParsingProvider:
    """Deterministic offline parser for tests and local batch-workbench flows."""

    _MAPPINGS = {
        "萌王S4": AnimeTitleParseResult(
            raw_title="萌王S4",
            canonical_title_candidates=[
                "关于我转生变成史莱姆这档事 第四季",
                "关于我转生变成史莱姆这档事 第4季",
            ],
            season_hint="S4",
            search_queries=[
                "关于我转生变成史莱姆这档事 第四季",
                "转生史莱姆 第四季",
                "萌王 S4",
            ],
            confidence=0.86,
            needs_user_review=True,
            source=ANIME_TITLE_PARSE_SOURCE_FAKE,
        ),
        "路哥S4": AnimeTitleParseResult(
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
        ),
        "杖剑谭S2": AnimeTitleParseResult(
            raw_title="杖剑谭S2",
            canonical_title_candidates=["杖与剑的魔剑谭 第二季"],
            season_hint="S2",
            search_queries=[
                "杖与剑的魔剑谭 第二季",
                "杖剑谭 S2",
            ],
            confidence=0.62,
            needs_user_review=True,
            source=ANIME_TITLE_PARSE_SOURCE_FAKE,
        ),
        "邻家天使S2": AnimeTitleParseResult(
            raw_title="邻家天使S2",
            canonical_title_candidates=[
                "关于邻家的天使大人不知不觉把我惯成了废人这档子事 第二季"
            ],
            season_hint="S2",
            search_queries=[
                "关于邻家的天使大人不知不觉把我惯成了废人这档子事 第二季",
                "邻家的天使大人 第二季",
                "邻家天使 S2",
            ],
            confidence=0.88,
            needs_user_review=False,
            source=ANIME_TITLE_PARSE_SOURCE_FAKE,
        ),
    }

    def __init__(self, *, fail_titles: set[str] | None = None) -> None:
        self._fail_titles = fail_titles or set()

    def parse(self, raw_title: str) -> AnimeTitleParseResult:
        normalized = raw_title.strip()
        if not normalized:
            raise Stage1Error(
                "invalid_input",
                "番剧名称不能为空",
                "ai_title_parse",
                {"field": "raw_title"},
            )
        if normalized in self._fail_titles:
            raise _safe_provider_error(normalized)

        mapped = self._MAPPINGS.get(normalized)
        if mapped is None:
            return _result(
                raw_title=raw_title,
                canonical_title_candidates=[normalized],
                season_hint=None,
                search_queries=[normalized],
                confidence=0.4,
                source=ANIME_TITLE_PARSE_SOURCE_FAKE,
            )
        return replace(mapped, raw_title=raw_title)


def parse_anime_title(
    raw_title: str,
    provider: AnimeTitleParsingProvider | None = None,
) -> AnimeTitleParseResult:
    parser = provider or FakeAnimeTitleParsingProvider()
    try:
        result = parser.parse(raw_title)
    except Stage1Error as exc:
        raise _sanitize_provider_exception(exc) from exc
    except Exception as exc:
        raise _safe_provider_error(raw_title) from exc
    return _normalize_result(raw_title, result)


def _result(
    *,
    raw_title: str,
    canonical_title_candidates: list[str],
    season_hint: str | None,
    search_queries: list[str],
    confidence: float,
    source: str,
) -> AnimeTitleParseResult:
    return AnimeTitleParseResult(
        raw_title=raw_title,
        canonical_title_candidates=canonical_title_candidates,
        season_hint=season_hint,
        search_queries=search_queries,
        confidence=confidence,
        needs_user_review=_needs_user_review(canonical_title_candidates, confidence),
        source=source,
    )


def _normalize_result(raw_title: str, result: AnimeTitleParseResult) -> AnimeTitleParseResult:
    candidates = _non_empty_unique(result.canonical_title_candidates)
    queries = _non_empty_unique(result.search_queries)
    if not candidates or not queries:
        raise Stage1Error(
            "ai_title_parse_failed",
            "AI 名称解析未返回可用搜索词",
            "ai_title_parse",
            {"provider_source": result.source or "unknown"},
        )
    confidence = max(0.0, min(1.0, float(result.confidence)))
    return AnimeTitleParseResult(
        raw_title=raw_title,
        canonical_title_candidates=candidates,
        season_hint=result.season_hint,
        search_queries=queries,
        confidence=confidence,
        needs_user_review=result.needs_user_review
        or _needs_user_review(candidates, confidence),
        source=result.source,
    )


def _needs_user_review(candidates: list[str], confidence: float) -> bool:
    return confidence < LOW_CONFIDENCE_THRESHOLD or len(candidates) != 1


def _non_empty_unique(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = value.strip()
        if text and text not in seen:
            deduped.append(text)
            seen.add(text)
    return deduped


def _safe_provider_error(raw_title: str) -> Stage1Error:
    return Stage1Error(
        "ai_title_parse_failed",
        "AI 名称解析失败，请检查该条目后重试",
        "ai_title_parse",
        {
            "raw_title_length": len(raw_title),
            "provider_source": ANIME_TITLE_PARSE_SOURCE_FAKE,
            "recoverable": True,
        },
    )


def _sanitize_provider_exception(error: Stage1Error) -> Stage1Error:
    return Stage1Error(
        error.error_type or "ai_title_parse_failed",
        error.message or "AI 名称解析失败，请检查该条目后重试",
        "ai_title_parse",
        {
            "provider_source": "unknown",
            "recoverable": True,
        },
    )


__all__ = [
    "AnimeTitleParsingProvider",
    "FakeAnimeTitleParsingProvider",
    "LOW_CONFIDENCE_THRESHOLD",
    "parse_anime_title",
]
