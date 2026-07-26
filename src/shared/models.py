from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EntryRequest:
    raw_title: str


@dataclass(frozen=True)
class RssSource:
    subtitle_group: str
    rss_url: str
    source_type: str
    fixture_path: str


@dataclass(frozen=True)
class BangumiCandidate:
    bangumi_id: str
    title: str
    aliases: list[str]
    mikan_url: str
    rss_sources: list[RssSource]


@dataclass(frozen=True)
class MatchedBangumi:
    title: str
    aliases: list[str]
    mikan_url: str
    match_score: float


@dataclass(frozen=True)
class RssSeed:
    title: str
    link: str
    published_at: str | None = None
    guid: str | None = None


@dataclass(frozen=True)
class ParsedRss:
    source: RssSource
    seeds: list[RssSeed]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FilterRule:
    must_contain: str = ""
    must_not_contain: str = ""


@dataclass(frozen=True)
class UserPreference:
    filter_rule: FilterRule
    subtitle_group_priority: list[str]


@dataclass(frozen=True)
class ExcludedSeed:
    name: str
    reason: str
    rule: str


@dataclass(frozen=True)
class FilteredRss:
    source: RssSource
    total_seed_count: int
    valid_seeds: list[RssSeed]
    excluded_seeds: list[ExcludedSeed]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SubtitleGroupSelection:
    subtitle_group: str | None
    rss_url: str | None
    warnings: list[str] = field(default_factory=list)
