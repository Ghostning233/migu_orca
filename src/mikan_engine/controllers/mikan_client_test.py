from __future__ import annotations

import pytest

from mikan_engine.controllers.mikan_client import create_mikan_client
from mikan_engine.controllers.mikan_config import MikanConfig
from shared.errors import Stage1Error
from shared.models import MatchedBangumi


class FakeTransport:
    def __init__(self, response: str = "") -> None:
        self.response = response
        self.requests: list[tuple[str, float]] = []

    def get_text(self, url: str, *, timeout: float) -> str:
        self.requests.append((url, timeout))
        return self.response


def test_create_mikan_client_keeps_explicit_config_and_transport() -> None:
    config = MikanConfig(
        search_endpoint="https://mikan.example/search",
        timeout_seconds=5,
    )
    transport = FakeTransport()

    client = create_mikan_client(config, transport=transport)

    assert client.config is config
    assert client.transport is transport


def test_mikan_client_searches_with_injected_transport_and_encoded_query() -> None:
    transport = FakeTransport(
        """
        <html>
          <body>
            <a href="/Home/Bangumi/3072" title="Sousou no Frieren">
              葬送的芙莉莲
            </a>
          </body>
        </html>
        """
    )
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/Home/Search?classic=true",
            timeout_seconds=7,
        ),
        transport=transport,
    )

    candidates = client.list_bangumi_candidates("葬送的芙莉莲 S2")

    assert transport.requests == [
        (
            "https://mikan.example/Home/Search?classic=true&searchstr=%E8%91%AC%E9%80%81%E7%9A%84%E8%8A%99%E8%8E%89%E8%8E%B2+S2",
            7,
        )
    ]
    assert candidates[0].bangumi_id == "3072"
    assert candidates[0].title == "葬送的芙莉莲"
    assert candidates[0].aliases == ["Sousou no Frieren"]
    assert candidates[0].mikan_url == "https://mikan.example/Home/Bangumi/3072"
    assert candidates[0].rss_sources == []


def test_mikan_client_parses_search_fixture_candidates_and_deduplicates() -> None:
    transport = FakeTransport(
        """
        <section class="js-search-results">
          <a class="an-text" href="/Home/Bangumi/100">迷宫饭</a>
          <a class="duplicate-card" href="/Home/Bangumi/100">迷宫饭</a>
          <a class="an-text" href="https://mikan.example/Home/Bangumi/101?tab=info">
            葬送的芙莉莲
          </a>
          <a href="/Home/News/1">not a bangumi</a>
        </section>
        """
    )
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/Home/Search",
            timeout_seconds=5,
        ),
        transport=transport,
    )

    candidates = client.list_bangumi_candidates("frieren")

    assert [candidate.bangumi_id for candidate in candidates] == ["100", "101"]
    assert [candidate.title for candidate in candidates] == ["迷宫饭", "葬送的芙莉莲"]
    assert candidates[1].mikan_url == "https://mikan.example/Home/Bangumi/101?tab=info"


def test_mikan_client_rejects_empty_search_title_before_transport() -> None:
    transport = FakeTransport()
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/search",
            timeout_seconds=5,
        ),
        transport=transport,
    )

    with pytest.raises(Stage1Error) as error:
        client.list_bangumi_candidates("  ")

    assert error.value.error_type == "invalid_input"
    assert error.value.failed_step == "mikan_search"
    assert transport.requests == []


def test_mikan_client_exposes_rss_source_listing_boundary() -> None:
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/search",
            timeout_seconds=5,
        )
    )
    matched = MatchedBangumi(
        title="芙莉莲",
        aliases=[],
        mikan_url="https://mikan.example/Home/Bangumi/1",
        match_score=1,
    )

    with pytest.raises(Stage1Error) as error:
        client.list_rss_sources(matched)

    assert error.value.error_type == "mikan_not_implemented"
    assert error.value.failed_step == "mikan_list_rss_sources"
