from __future__ import annotations

"""Plan-generation data-source adapters (issue #174).

`build_plan` orchestrates the plan pipeline but never decides *where* candidates
and RSS bytes come from. That choice sits behind the `PlanDataSource` port, so
the same entry serves production (real MiKan) and offline tests/fixtures (static
catalog + fixture RSS files) without CLI semantics (``source_mode`` /
``catalog_path`` / ``user_config_path`` / ``project_root``) leaking into the
public entry.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from catalog_engine.controllers.catalog_controller import load_catalog
from mikan_engine.controllers import mikan_client as mikan_client_module
from mikan_engine.controllers.mikan_client import MikanClient, MikanTransport
from mikan_engine.controllers.mikan_config import MikanConfig, load_mikan_config
from rss_engine.controllers.rss_controller import parse_rss
from shared.config import (
    DEFAULT_CATALOG_PATH,
    DEFAULT_USER_CONFIG_PATH,
    PROJECT_ROOT,
    load_user_preference,
)
from shared.errors import Stage1Error
from shared.models import (
    BangumiCandidate,
    MatchedBangumi,
    ParsedRss,
    RssSource,
    UserPreference,
)

#: Offline fixture reads used a fixed 10s budget before this seam existed.
DEFAULT_RSS_FIXTURE_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class DirectEntryResolution:
    """A user-supplied direct MiKan entry resolved into plan inputs."""

    matched: MatchedBangumi
    rss_sources: list[RssSource]


class PlanDataSource(Protocol):
    """Where a subscription plan's candidates and RSS bytes come from.

    Implementations are single-use: one adapter instance serves one
    `build_plan` call, so a lazily resolved MiKan client is created at most
    once per generated plan (matching the pre-seam behaviour).
    """

    def load_preference(self) -> UserPreference:
        """Load the caller's filter/subtitle preferences."""

    def list_candidates(self, raw_title: str) -> list[BangumiCandidate]:
        """Return the candidate bangumi for a raw title."""

    def resolve_direct_entry(self, direct_entry: str) -> DirectEntryResolution:
        """Resolve a non-empty direct entry, or raise a stable Stage1Error."""

    def list_rss_sources(
        self,
        matched: MatchedBangumi,
        candidate: BangumiCandidate,
    ) -> list[RssSource]:
        """Return the RSS sources to parse for the matched bangumi.

        Both inputs are passed because the two adapters read different ones:
        the real MiKan source fetches the sources from the upstream bangumi page
        (``matched``), while the offline fixture source carries them on the
        catalog candidate card (``candidate``).
        """

    def parse_rss(self, source: RssSource) -> ParsedRss:
        """Parse one RSS source, raising Stage1Error on a stable failure."""


class StaticFixtureDataSource:
    """Offline fixture source: static catalog JSON plus fixture RSS files."""

    def __init__(
        self,
        *,
        catalog_path: Path = DEFAULT_CATALOG_PATH,
        user_config_path: Path = DEFAULT_USER_CONFIG_PATH,
        project_root: Path = PROJECT_ROOT,
        transport: MikanTransport | None = None,
        timeout: float = DEFAULT_RSS_FIXTURE_TIMEOUT_SECONDS,
    ) -> None:
        self._catalog_path = catalog_path
        self._user_config_path = user_config_path
        self._project_root = project_root
        self._transport = transport
        self._timeout = timeout

    def load_preference(self) -> UserPreference:
        return load_user_preference(self._user_config_path)

    def list_candidates(self, raw_title: str) -> list[BangumiCandidate]:
        return load_catalog(self._catalog_path)

    def resolve_direct_entry(self, direct_entry: str) -> DirectEntryResolution:
        raise Stage1Error(
            "invalid_input",
            "MiKan 直连入口仅支持真实 MiKan 数据源",
            "mikan_direct_entry",
            {"field": "mikan_bangumi"},
        )

    def list_rss_sources(
        self,
        matched: MatchedBangumi,
        candidate: BangumiCandidate,
    ) -> list[RssSource]:
        return candidate.rss_sources

    def parse_rss(self, source: RssSource) -> ParsedRss:
        return parse_rss(
            source,
            self._project_root,
            transport=self._transport,
            timeout=self._timeout,
        )


class MikanDataSource:
    """Production source: candidates and RSS come from the real MiKan site.

    The client is resolved lazily on first use so a missing/invalid MiKan
    configuration still fails inside the plan result envelope (``config_error``)
    instead of at adapter construction time. ``transport`` overrides only the RSS
    reads (mirroring the historical ``mikan_rss_transport``); the client itself
    is always built from the configured MiKan config.
    """

    def __init__(
        self,
        *,
        user_config_path: Path = DEFAULT_USER_CONFIG_PATH,
        config_path: Path | None = None,
        config: MikanConfig | None = None,
        client: MikanClient | None = None,
        transport: MikanTransport | None = None,
        rss_fixture_root: Path = PROJECT_ROOT,
    ) -> None:
        self._user_config_path = user_config_path
        self._config_path = config_path
        self._config = config
        self._transport = transport
        self._rss_fixture_root = rss_fixture_root
        self._client = client

    def load_preference(self) -> UserPreference:
        return load_user_preference(self._user_config_path)

    def list_candidates(self, raw_title: str) -> list[BangumiCandidate]:
        return self._require_client().list_bangumi_candidates(raw_title)

    def resolve_direct_entry(self, direct_entry: str) -> DirectEntryResolution:
        client = self._require_client()
        detail = client.get_direct_bangumi_detail(direct_entry)
        matched = MatchedBangumi(
            title=detail.title,
            aliases=[],
            mikan_url=detail.mikan_url,
            match_score=1.0,
            poster_url=detail.poster_url,
        )
        return DirectEntryResolution(
            matched=matched,
            rss_sources=client.list_rss_sources_from_detail(detail),
        )

    def list_rss_sources(
        self,
        matched: MatchedBangumi,
        candidate: BangumiCandidate,
    ) -> list[RssSource]:
        return self._require_client().list_rss_sources(matched)

    def parse_rss(self, source: RssSource) -> ParsedRss:
        client = self._require_client()
        return parse_rss(
            source,
            self._rss_fixture_root,
            transport=self._transport or client.transport,
            timeout=client.config.timeout_seconds,
        )

    def _require_client(self) -> MikanClient:
        if self._client is not None:
            return self._client
        if self._config is not None:
            config = self._config
        elif self._config_path is None:
            raise Stage1Error(
                "config_error",
                "真实 MiKan 数据源必须显式提供配置文件路径",
                "load_mikan_config",
                {"field": "mikan_config"},
            )
        else:
            config = load_mikan_config(self._config_path)
        self._client = mikan_client_module.create_mikan_client(config)
        return self._client
