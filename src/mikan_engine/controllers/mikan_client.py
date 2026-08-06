from __future__ import annotations

from typing import Protocol

from mikan_engine.controllers.mikan_config import MikanConfig
from shared.errors import Stage1Error
from shared.models import BangumiCandidate, MatchedBangumi, RssSource


class MikanTransport(Protocol):
    """Transport boundary for real MiKanProject reads."""


class MikanClient:
    """Real MiKanProject adapter boundary.

    The client only accepts explicit MiKan config plus domain inputs. Concrete
    HTTP search and page parsing are implemented behind this seam in later
    Stage 5 stories.
    """

    def __init__(
        self,
        config: MikanConfig,
        *,
        transport: MikanTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport

    @property
    def config(self) -> MikanConfig:
        return self._config

    @property
    def transport(self) -> MikanTransport | None:
        return self._transport

    def list_bangumi_candidates(self, raw_title: str) -> list[BangumiCandidate]:
        if not raw_title.strip():
            raise Stage1Error("invalid_input", "番剧名称不能为空", "mikan_search")
        raise Stage1Error(
            "mikan_not_implemented",
            "真实 MiKan 搜索尚未实现",
            "mikan_search",
        )

    def list_rss_sources(self, matched_bangumi: MatchedBangumi) -> list[RssSource]:
        if not matched_bangumi.mikan_url.strip():
            raise Stage1Error(
                "invalid_input",
                "MiKan 番剧页 URL 不能为空",
                "mikan_list_rss_sources",
            )
        raise Stage1Error(
            "mikan_not_implemented",
            "真实 MiKan RSS 源发现尚未实现",
            "mikan_list_rss_sources",
        )


def create_mikan_client(
    config: MikanConfig,
    *,
    transport: MikanTransport | None = None,
) -> MikanClient:
    """Build the real MiKan client from explicit MiKan config."""

    return MikanClient(config, transport=transport)
