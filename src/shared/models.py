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
    # Server-parsed public MiKan source URL only. Browser-facing opaque poster
    # routes and client supplied values never enter this field.
    poster_url: str | None = None


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
    use_regex: bool = False
    case_sensitive: bool = False


@dataclass(frozen=True)
class UserPreference:
    filter_rule: FilterRule
    subtitle_group_priority: list[str]


# Stage 21 non-sensitive user preference contract. Only subtitle-group choices,
# filter defaults, naming defaults, and a search-enhancement toggle are stored;
# endpoint/token/cookie/Authorization/magnet/raw HTML-RSS/response bodies and
# local absolute paths are rejected by the preference repository validation.

#: Allowed subtitle-group fallback strategies.
SUBTITLE_GROUP_FALLBACKS = ("next_preferred", "none")

#: Allowed folder-naming strategies for the ``expected_folder_name`` default.
NAMING_STRATEGIES = ("official_title_season", "official_title", "raw_title")


@dataclass(frozen=True)
class SubtitleGroupPreference:
    preferred: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    fallback: str = "next_preferred"


@dataclass(frozen=True)
class FilterDefaults:
    must_contain: str = ""
    must_not_contain: str = ""
    use_regex: bool = False
    case_sensitive: bool = False


@dataclass(frozen=True)
class NamingPreference:
    strategy: str = "official_title_season"
    template: str = "{title}"


@dataclass(frozen=True)
class SearchPreference:
    reuse_explicit_corrections: bool = True


@dataclass(frozen=True)
class VersionedUserPreference:
    """Non-sensitive user defaults used to prefill batch drafts.

    Versioned so old-format preference files (missing ``version``, legacy
    ``filter_rule``/``subtitle_group_priority`` keys) can still be read.
    """

    version: int = 1
    subtitle_groups: SubtitleGroupPreference = field(
        default_factory=SubtitleGroupPreference
    )
    filter_defaults: FilterDefaults = field(default_factory=FilterDefaults)
    naming: NamingPreference = field(default_factory=NamingPreference)
    search: SearchPreference = field(default_factory=SearchPreference)


# Stage 21 explicit title-correction contract. A correction links a shorthand
# ``raw_title`` (what the user typed) to the public canonical title the user
# confirmed, plus a season hint, optional public bangumi metadata, and an
# explicit search-query correction. Only non-sensitive public fields are stored;
# endpoint/token/cookie/Authorization/magnet/raw HTML-RSS/response bodies and
# local absolute paths are rejected by the correction repository validation.

#: Maximum number of corrections kept per storage (global cap; same-raw_title
#: duplicates use a latest-version strategy that never grows this bound).
MAX_STORED_CORRECTIONS = 500


@dataclass(frozen=True)
class BangumiCorrectionMetadata:
    """Public, non-sensitive bangumi metadata captured with a title correction.

    Only the public bangumi id and canonical title are stored — never raw HTML,
    raw RSS XML, magnets, cookies, tokens, endpoints, full failed URLs, response
    bodies, or local absolute paths.
    """

    bangumi_id: str | None = None
    title: str | None = None


@dataclass(frozen=True)
class TitleCorrection:
    """An explicitly-saved user correction reused by later batch searches.

    ``raw_title`` is the shorthand the user typed; ``canonical_title`` is the
    public canonical title the user confirmed; ``season_hint`` is an optional
    season marker (``S4``/``第四季``/``Season 4``); ``bangumi_metadata`` holds
    optional public bangumi identity; ``query_correction`` is an explicit
    search query the user found reliable (may be a Chinese, Japanese, numeric,
    or romanized variant). Only non-sensitive public fields are stored.
    """

    raw_title: str
    canonical_title: str
    season_hint: str | None = None
    bangumi_metadata: BangumiCorrectionMetadata | None = None
    query_correction: str | None = None


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
