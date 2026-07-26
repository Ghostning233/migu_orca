from __future__ import annotations

import json
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from shared.errors import Stage1Error
from shared.models import BangumiCandidate, MatchedBangumi, RssSource


def _require_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} 必须是非空字符串")
    return value


def load_catalog(path: Path) -> list[BangumiCandidate]:
    try:
        raw_catalog = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw_catalog, list):
            raise ValueError("根节点必须是数组")
        candidates: list[BangumiCandidate] = []
        for raw_candidate in raw_catalog:
            if not isinstance(raw_candidate, dict):
                raise ValueError("候选项必须是对象")
            raw_aliases = raw_candidate.get("aliases", [])
            raw_sources = raw_candidate.get("rss_sources", [])
            if not isinstance(raw_aliases, list) or not all(
                isinstance(alias, str) for alias in raw_aliases
            ):
                raise ValueError("aliases 必须是字符串数组")
            if not isinstance(raw_sources, list):
                raise ValueError("rss_sources 必须是数组")
            sources = [
                RssSource(
                    subtitle_group=_require_string(source, "subtitle_group"),
                    rss_url=_require_string(source, "rss_url"),
                    source_type=_require_string(source, "source_type"),
                    fixture_path=_require_string(source, "fixture_path"),
                )
                for source in raw_sources
                if isinstance(source, dict)
            ]
            candidates.append(
                BangumiCandidate(
                    bangumi_id=_require_string(raw_candidate, "bangumi_id"),
                    title=_require_string(raw_candidate, "title"),
                    aliases=raw_aliases,
                    mikan_url=_require_string(raw_candidate, "mikan_url"),
                    rss_sources=sources,
                )
            )
        return candidates
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise Stage1Error(
            "catalog_load_failed",
            f"静态候选数据无效：{path}",
            "load_catalog",
            {"reason": str(exc)},
        ) from exc


def _normalize_title(value: str) -> str:
    return "".join(value.strip().casefold().split())


def match_bangumi(
    raw_title: str,
    candidates: list[BangumiCandidate],
    threshold: float = 0.6,
) -> tuple[MatchedBangumi, BangumiCandidate]:
    normalized = _normalize_title(raw_title)
    if not normalized:
        raise Stage1Error("invalid_input", "番剧名称不能为空", "validate_input")
    if not candidates:
        raise Stage1Error(
            "bangumi_match_failed",
            "没有可用的候选番剧",
            "match_bangumi",
        )

    exact_matches = [
        candidate
        for candidate in candidates
        if normalized
        in {_normalize_title(name) for name in [candidate.title, *candidate.aliases]}
    ]
    if len(exact_matches) > 1:
        raise Stage1Error(
            "ambiguous_bangumi_match",
            "多个候选番剧精确匹配",
            "match_bangumi",
            {"candidates": [item.title for item in exact_matches]},
        )
    if exact_matches:
        selected = exact_matches[0]
        return _to_match(selected, 1.0), selected

    scores: list[tuple[float, BangumiCandidate]] = []
    for candidate in candidates:
        score = max(
            SequenceMatcher(None, normalized, _normalize_title(name)).ratio()
            for name in [candidate.title, *candidate.aliases]
        )
        scores.append((score, candidate))

    highest = max(score for score, _ in scores)
    if highest < threshold:
        raise Stage1Error(
            "bangumi_match_failed",
            "未找到可靠的番剧匹配",
            "match_bangumi",
            {"highest_score": round(highest, 4), "threshold": threshold},
        )
    winners = [candidate for score, candidate in scores if score == highest]
    if len(winners) > 1:
        raise Stage1Error(
            "ambiguous_bangumi_match",
            "多个候选番剧的最高匹配分相同",
            "match_bangumi",
            {"candidates": [item.title for item in winners]},
        )
    return _to_match(winners[0], highest), winners[0]


def _to_match(candidate: BangumiCandidate, score: float) -> MatchedBangumi:
    return MatchedBangumi(
        title=candidate.title,
        aliases=candidate.aliases,
        mikan_url=candidate.mikan_url,
        match_score=round(score, 4),
    )
