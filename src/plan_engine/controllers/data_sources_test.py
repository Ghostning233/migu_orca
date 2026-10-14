from __future__ import annotations

import json
from pathlib import Path

import pytest

from mikan_engine.controllers.mikan_client import (
    MikanBangumiDetail,
    MikanSubgroupDetail,
)
from mikan_engine.controllers.mikan_config import MikanConfig
from plan_engine.controllers.data_sources import (
    DirectEntryResolution,
    MikanDataSource,
    StaticFixtureDataSource,
)
from shared.errors import Stage1Error
from shared.models import BangumiCandidate, MatchedBangumi, RssSource, UserPreference

_FIXTURE_RSS_XML = (
    "<rss><channel><item><title>芙莉莲 - 01</title>"
    "<link>https://example.invalid/1</link></item></channel></rss>"
)
_SEARCH_PAGE = '<a href="/Home/Bangumi/123" title="芙莉莲">芙莉莲</a>'
_DETAIL_PAGE = (
    '<h1 class="bangumi-title">芙莉莲</h1>'
    '<section class="subgroup-section">'
    '<h2 class="subgroup-name">Loli</h2>'
    '<a href="/RSS/Bangumi?bangumiId=123&subgroupid=10">RSS</a>'
    "</section>"
)
_RSS_PAGE = _FIXTURE_RSS_XML


class _FakeTransport:
    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, float]] = []

    def get_text(self, url: str, *, timeout: float) -> str:
        self.requests.append((url, timeout))
        return self.responses[url]


class _FakeClient:
    """Duck-typed MiKan client; records the calls the adapter makes."""

    def __init__(self, *, detail: MikanBangumiDetail | None = None) -> None:
        self.transport = _FakeTransport({})
        self.config = MikanConfig(
            search_endpoint="https://mikan.example/Home/Search",
            timeout_seconds=7.5,
        )
        self.detail = detail
        self.rss_source_calls = 0

    def list_bangumi_candidates(self, raw_title: str) -> list[BangumiCandidate]:
        return []

    def list_rss_sources(self, matched_bangumi: MatchedBangumi) -> list[RssSource]:
        self.rss_source_calls += 1
        return []

    def get_direct_bangumi_detail(self, direct_entry: str) -> MikanBangumiDetail:
        assert self.detail is not None
        return self.detail

    def list_rss_sources_from_detail(
        self, detail: MikanBangumiDetail
    ) -> list[RssSource]:
        return []


def _write_catalog(tmp_path: Path, candidate: BangumiCandidate) -> Path:
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            [
                {
                    "bangumi_id": candidate.bangumi_id,
                    "title": candidate.title,
                    "aliases": candidate.aliases,
                    "mikan_url": candidate.mikan_url,
                    "rss_sources": [
                        {
                            "subtitle_group": source.subtitle_group,
                            "rss_url": source.rss_url,
                            "source_type": source.source_type,
                            "fixture_path": source.fixture_path,
                        }
                        for source in candidate.rss_sources
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    return catalog


def test_static_fixture_source_serves_catalog_rss_and_preference(tmp_path: Path) -> None:
    (tmp_path / "rss.xml").write_text(_FIXTURE_RSS_XML, encoding="utf-8")
    rss_source = RssSource(
        subtitle_group="Loli",
        rss_url="https://example.invalid/rss.xml",
        source_type="static_fixture",
        fixture_path="rss.xml",
    )
    candidate = BangumiCandidate(
        bangumi_id="fixture-1",
        title="芙莉莲",
        aliases=["Frieren"],
        mikan_url="https://example.invalid/bangumi/1",
        rss_sources=[rss_source],
    )
    source = StaticFixtureDataSource(
        catalog_path=_write_catalog(tmp_path, candidate),
        project_root=tmp_path,
    )

    assert source.list_candidates("芙莉莲") == [candidate]
    matched = MatchedBangumi(
        title="芙莉莲",
        aliases=["Frieren"],
        mikan_url=candidate.mikan_url,
        match_score=1.0,
    )
    assert source.list_rss_sources(matched, candidate) == [rss_source]

    parsed = source.parse_rss(rss_source)
    assert parsed.source == rss_source
    assert [seed.title for seed in parsed.seeds] == ["芙莉莲 - 01"]

    preference = source.load_preference()
    assert isinstance(preference, UserPreference)
    assert preference.subtitle_group_priority


def test_static_fixture_source_rejects_direct_entries() -> None:
    source = StaticFixtureDataSource()

    with pytest.raises(Stage1Error) as error:
        source.resolve_direct_entry("123")

    assert error.value.as_dict() == {
        "error_type": "invalid_input",
        "error_message": "MiKan 直连入口仅支持真实 MiKan 数据源",
        "failed_step": "mikan_direct_entry",
        "details": {"field": "mikan_bangumi"},
    }


def test_mikan_source_requires_explicit_configuration() -> None:
    source = MikanDataSource()

    with pytest.raises(Stage1Error) as error:
        source.list_candidates("芙莉莲")

    assert error.value.as_dict() == {
        "error_type": "config_error",
        "error_message": "真实 MiKan 数据源必须显式提供配置文件路径",
        "failed_step": "load_mikan_config",
        "details": {"field": "mikan_config"},
    }


def test_mikan_source_loads_config_from_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "mikan.json"
    config_path.write_text(
        json.dumps(
            {
                "search_endpoint": "https://mikan.example/Home/Search",
                "timeout_seconds": 3,
            }
        ),
        encoding="utf-8",
    )
    created: list[MikanConfig] = []

    def fake_create_mikan_client(config: MikanConfig) -> _FakeClient:
        created.append(config)
        return _FakeClient()

    monkeypatch.setattr(
        "plan_engine.controllers.data_sources.mikan_client_module.create_mikan_client",
        fake_create_mikan_client,
    )
    source = MikanDataSource(config_path=config_path)

    assert source.list_candidates("芙莉莲") == []
    assert created == [
        MikanConfig(
            search_endpoint="https://mikan.example/Home/Search",
            timeout_seconds=3.0,
        )
    ]


def test_mikan_source_parse_rss_prefers_the_injected_transport() -> None:
    http_source = RssSource(
        subtitle_group="Loli",
        rss_url="https://example.invalid/rss.xml",
        source_type="mikan_http",
        fixture_path="",
    )
    transport = _FakeTransport(
        {"https://example.invalid/rss.xml": _FIXTURE_RSS_XML}
    )
    client = _FakeClient()
    source = MikanDataSource(client=client, transport=transport)

    parsed = source.parse_rss(http_source)

    assert [seed.title for seed in parsed.seeds] == ["芙莉莲 - 01"]
    # The RSS override transport served the read with the client's timeout; the
    # client's own transport (an empty fake) was never used.
    assert transport.requests == [("https://example.invalid/rss.xml", 7.5)]
    assert client.transport.requests == []


def test_mikan_source_parse_rss_resolves_fixtures_under_its_root(tmp_path: Path) -> None:
    (tmp_path / "rss.xml").write_text(_FIXTURE_RSS_XML, encoding="utf-8")
    fixture_source = RssSource(
        subtitle_group="Loli",
        rss_url="https://example.invalid/rss.xml",
        source_type="static_fixture",
        fixture_path="rss.xml",
    )
    source = MikanDataSource(client=_FakeClient(), rss_fixture_root=tmp_path)

    parsed = source.parse_rss(fixture_source)

    assert [seed.title for seed in parsed.seeds] == ["芙莉莲 - 01"]


def test_mikan_source_direct_entry_maps_detail_to_matched_bangumi() -> None:
    detail = MikanBangumiDetail(
        bangumi_id="123",
        title="芙莉莲",
        mikan_url="https://mikan.example/Home/Bangumi/123",
        broadcast_start=None,
        poster_url="https://mikan.example/poster.jpg",
        bangumi_rss_url=None,
        subgroups=[
            MikanSubgroupDetail(
                name="Loli",
                rss_url="https://mikan.example/rss",
                episodes=[],
            )
        ],
    )
    client = _FakeClient(detail=detail)
    source = MikanDataSource(client=client)

    resolution = source.resolve_direct_entry("123")

    assert isinstance(resolution, DirectEntryResolution)
    assert resolution.matched == MatchedBangumi(
        title="芙莉莲",
        aliases=[],
        mikan_url="https://mikan.example/Home/Bangumi/123",
        match_score=1.0,
        poster_url="https://mikan.example/poster.jpg",
    )
    assert resolution.rss_sources == []


def test_mikan_source_reuses_one_client_per_instance() -> None:
    client = _FakeClient()
    source = MikanDataSource(client=client)

    source.list_rss_sources(
        MatchedBangumi(
            title="芙莉莲",
            aliases=[],
            mikan_url="https://mikan.example/Home/Bangumi/123",
            match_score=1.0,
        ),
        BangumiCandidate(
            bangumi_id="123",
            title="芙莉莲",
            aliases=[],
            mikan_url="https://mikan.example/Home/Bangumi/123",
            rss_sources=[],
        ),
    )
    source.list_rss_sources(
        MatchedBangumi(
            title="芙莉莲",
            aliases=[],
            mikan_url="https://mikan.example/Home/Bangumi/123",
            match_score=1.0,
        ),
        BangumiCandidate(
            bangumi_id="123",
            title="芙莉莲",
            aliases=[],
            mikan_url="https://mikan.example/Home/Bangumi/123",
            rss_sources=[],
        ),
    )

    assert client.rss_source_calls == 2


def test_mikan_source_accepts_an_inline_config() -> None:
    config = MikanConfig(
        search_endpoint="https://mikan.example/Home/Search",
        timeout_seconds=4,
    )
    client = _FakeClient()
    source = MikanDataSource(config=config, client=client)

    assert source.list_candidates("芙莉莲") == []
