from __future__ import annotations

from typing import Protocol, Sequence
import unicodedata

from batch_engine.models import (
    ANIME_TITLE_PARSE_SOURCE_FAKE,
    AnimeTitleParseResult,
    AnimeTitleParseSource,
    AnimeTitleQuery,
    MAX_ANIME_TITLE_QUERY_COUNT,
)
from shared.errors import Stage1Error
from shared.models import TitleCorrection
from shared.title_season import parse_title_season, season_variants


LOW_CONFIDENCE_THRESHOLD = 0.7


class AnimeTitleParsingProvider(Protocol):
    def parse(self, raw_title: str) -> AnimeTitleParseResult:
        """Parse a shorthand anime title into reviewable search metadata."""


class RuleAnimeTitleParsingProvider:
    """Offline deterministic parser used by normal application flows.

    The alias table is intentionally small and conservative: it only plans
    searches and never asserts that a MiKan collection has been selected.
    """

    _ALIASES: dict[str, tuple[str, tuple[str, ...]]] = {
        "萌王": ("关于我转生变成史莱姆这档事", ("转生史莱姆",)),
        "路哥": ("欢迎来到实力至上主义的教室", ("实力至上主义教室",)),
        "杖剑谭": ("杖与剑的魔剑谭", ()),
        "邻家天使": ("关于邻家的天使大人不知不觉把我惯成了废人这档子事", ("邻家的天使大人",)),
    }

    def __init__(self, *, corrections: Sequence[TitleCorrection] = ()) -> None:
        self._corrections = tuple(corrections)

    def parse(self, raw_title: str) -> AnimeTitleParseResult:
        if not raw_title.strip():
            raise Stage1Error("invalid_input", "番剧名称不能为空", "ai_title_parse", {"field": "raw_title"})
        parsed = parse_title_season(raw_title)
        correction = _find_correction(raw_title, self._corrections)
        known = self._ALIASES.get(_key(parsed.base_title))
        canonical, aliases = known or (parsed.base_title, ())
        plan: list[tuple[str, AnimeTitleParseSource]] = []
        if correction is not None:
            plan.append((correction.query_correction or correction.canonical_title, AnimeTitleParseSource.CORRECTION))
            canonical = correction.canonical_title
        for alias in aliases:
            plan.append((_with_season(alias, parsed.season), AnimeTitleParseSource.ALIAS))
        plan.extend((query, AnimeTitleParseSource.RULE) for query in _canonical_queries(canonical, parsed.season))
        plan.append((_normalized(raw_title), AnimeTitleParseSource.FALLBACK))
        deduped = _dedupe_plan(plan)
        query_plan = _bounded_query_plan(deduped)
        hints = list(parsed.review_hints)
        if correction is None and known is None:
            hints.append("未识别正式别名，请人工核对")
        if len(deduped) > len(query_plan):
            hints.append("搜索词已截断，请人工核对")
        confidence = 0.92 if correction else (0.82 if known else 0.45)
        return AnimeTitleParseResult(
            raw_title=raw_title,
            canonical_title_candidates=[canonical],
            season_hint=parsed.season_hint,
            search_queries=[entry.query for entry in query_plan],
            query_plan=tuple(query_plan),
            confidence=confidence,
            needs_user_review=bool(hints) or confidence < LOW_CONFIDENCE_THRESHOLD,
            source=query_plan[0].source,
            normalized_title=parsed.normalized_title,
            base_title=parsed.base_title,
            season=parsed.season,
            review_hints=tuple(dict.fromkeys(hints)),
        )


class FakeAnimeTitleParsingProvider:
    """Deterministic fixture provider; use only through explicit injection."""

    _MAPPINGS = {
        "萌王S4": ("关于我转生变成史莱姆这档事 第四季", 0.86),
        "路哥S4": ("欢迎来到实力至上主义的教室 第四季", 0.9),
        "杖剑谭S2": ("杖与剑的魔剑谭 第二季", 0.62),
        "邻家天使S2": ("关于邻家的天使大人不知不觉把我惯成了废人这档子事 第二季", 0.88),
    }

    def __init__(self, *, fail_titles: set[str] | None = None) -> None:
        self._fail_titles = fail_titles or set()

    def parse(self, raw_title: str) -> AnimeTitleParseResult:
        normalized = raw_title.strip()
        if not normalized:
            raise Stage1Error("invalid_input", "番剧名称不能为空", "ai_title_parse", {"field": "raw_title"})
        if normalized in self._fail_titles:
            raise _safe_provider_error(raw_title)
        parsed = parse_title_season(raw_title)
        canonical, confidence = self._MAPPINGS.get(normalized, (parsed.base_title, 0.4))
        return AnimeTitleParseResult(
            raw_title=raw_title, canonical_title_candidates=[canonical], season_hint=parsed.season_hint,
            search_queries=[canonical, _normalized(raw_title)], confidence=confidence,
            needs_user_review=confidence < LOW_CONFIDENCE_THRESHOLD, source=ANIME_TITLE_PARSE_SOURCE_FAKE,
            normalized_title=parsed.normalized_title, base_title=parsed.base_title, season=parsed.season,
            review_hints=parsed.review_hints,
        )


def parse_anime_title(raw_title: str, provider: AnimeTitleParsingProvider | None = None) -> AnimeTitleParseResult:
    parser = provider or RuleAnimeTitleParsingProvider()
    try:
        result = parser.parse(raw_title)
    except Stage1Error as exc:
        raise _sanitize_provider_exception(exc) from exc
    except Exception as exc:
        raise _safe_provider_error(raw_title) from exc
    return _normalize_result(raw_title, result)


def _normalize_result(raw_title: str, result: AnimeTitleParseResult) -> AnimeTitleParseResult:
    candidates = _non_empty_unique(result.canonical_title_candidates)
    plan = _bounded_query_plan([(entry.query, entry.source) for entry in result.query_plan])
    if not candidates or not plan:
        raise Stage1Error("ai_title_parse_failed", "名称解析未返回可用搜索词", "ai_title_parse", {"provider_source": result.source.value})
    confidence = max(0.0, min(1.0, float(result.confidence)))
    season_parse = parse_title_season(raw_title)
    hints = tuple(dict.fromkeys((*result.review_hints, *season_parse.review_hints)))
    return AnimeTitleParseResult(
        raw_title=raw_title, canonical_title_candidates=candidates, season_hint=season_parse.season_hint,
        search_queries=[entry.query for entry in plan], query_plan=tuple(plan), confidence=confidence,
        needs_user_review=result.needs_user_review or _needs_user_review(candidates, confidence) or bool(hints),
        source=plan[0].source, normalized_title=season_parse.normalized_title,
        base_title=season_parse.base_title, season=season_parse.season, review_hints=hints,
    )


def _canonical_queries(title: str, season: int | None) -> list[str]:
    return [_with_season(title, form) for form in season_variants(season)] if season else [title]


def _with_season(title: str, form: str | int | None) -> str:
    if isinstance(form, int):
        variants = season_variants(form)
        form = variants[-1] if variants else ""
    parsed = parse_title_season(title)
    base = parsed.base_title if parsed.season is not None else _normalized(title)
    return f"{base} {form}".strip() if form else base


def _bounded_query_plan(entries: Sequence[tuple[str, AnimeTitleParseSource]]) -> list[AnimeTitleQuery]:
    return [AnimeTitleQuery(query, source, index) for index, (query, source) in enumerate(_dedupe_plan(entries)[:MAX_ANIME_TITLE_QUERY_COUNT], 1)]


def _dedupe_plan(entries: Sequence[tuple[str, AnimeTitleParseSource]]) -> list[tuple[str, AnimeTitleParseSource]]:
    result: list[tuple[str, AnimeTitleParseSource]] = []
    seen: set[str] = set()
    for query, source in entries:
        normalized = _normalized(query)
        if normalized and normalized.casefold() not in seen:
            seen.add(normalized.casefold())
            result.append((normalized, source))
    return result


def _find_correction(raw_title: str, corrections: Sequence[TitleCorrection]) -> TitleCorrection | None:
    return next((item for item in corrections if _key(item.raw_title) == _key(raw_title)), None)


def _key(value: str) -> str:
    return _normalized(value).casefold()


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _needs_user_review(candidates: list[str], confidence: float) -> bool:
    return confidence < LOW_CONFIDENCE_THRESHOLD or len(candidates) != 1


def _non_empty_unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def _safe_provider_error(raw_title: str) -> Stage1Error:
    return Stage1Error("ai_title_parse_failed", "AI 名称解析失败，请检查该条目后重试", "ai_title_parse", {"raw_title_length": len(raw_title), "provider_source": ANIME_TITLE_PARSE_SOURCE_FAKE, "recoverable": True})


def _sanitize_provider_exception(error: Stage1Error) -> Stage1Error:
    return Stage1Error(error.error_type or "ai_title_parse_failed", error.message or "AI 名称解析失败，请检查该条目后重试", "ai_title_parse", {"provider_source": "unknown", "recoverable": True})


__all__ = ["AnimeTitleParsingProvider", "FakeAnimeTitleParsingProvider", "LOW_CONFIDENCE_THRESHOLD", "RuleAnimeTitleParsingProvider", "parse_anime_title"]
