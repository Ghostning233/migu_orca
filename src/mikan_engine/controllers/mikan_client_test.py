from __future__ import annotations

from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from mikan_engine.controllers.mikan_client import (
    _MikanBangumiPageParser,
    create_mikan_client,
)
from mikan_engine.controllers.mikan_config import MikanConfig
from shared.errors import Stage1Error
from shared.models import MatchedBangumi

FIXTURE_DIR = Path(__file__).with_name("fixtures")


class FakeTransport:
    def __init__(self, response: str = "") -> None:
        self.response = response
        self.requests: list[tuple[str, float]] = []

    def get_text(self, url: str, *, timeout: float) -> str:
        self.requests.append((url, timeout))
        return self.response


class ErrorTransport:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def get_text(self, url: str, *, timeout: float) -> str:
        raise self.error


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


def test_mikan_search_http_failure_is_stable_and_url_free() -> None:
    http_error = HTTPError(
        "https://mikan.example/Home/Search?searchstr=secret-token",
        503,
        "backend leaked secret-token",
        {},
        None,
    )
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/Home/Search?cookie=secret-token",
            timeout_seconds=5,
        ),
        transport=ErrorTransport(http_error),
    )

    with pytest.raises(Stage1Error) as error:
        client.list_bangumi_candidates("芙莉莲")

    assert error.value.as_dict() == {
        "error_type": "mikan_http_failed",
        "error_message": "MiKan HTTP 请求失败",
        "failed_step": "mikan_search",
        "details": {"status_code": 503},
    }
    assert "secret-token" not in str(error.value.as_dict())


def test_mikan_search_connection_failure_is_stable_and_reason_free() -> None:
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/Home/Search",
            timeout_seconds=5,
        ),
        transport=ErrorTransport(URLError("connection failed with cookie=secret-token")),
    )

    with pytest.raises(Stage1Error) as error:
        client.list_bangumi_candidates("芙莉莲")

    assert error.value.as_dict() == {
        "error_type": "mikan_connection_failed",
        "error_message": "MiKan HTTP 连接失败",
        "failed_step": "mikan_search",
        "details": {"category": "connection"},
    }
    assert "secret-token" not in str(error.value.as_dict())


def test_mikan_search_timeout_is_stable_and_reason_free() -> None:
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/Home/Search",
            timeout_seconds=5,
        ),
        transport=ErrorTransport(URLError(TimeoutError("timed out secret-token"))),
    )

    with pytest.raises(Stage1Error) as error:
        client.list_bangumi_candidates("芙莉莲")

    assert error.value.as_dict() == {
        "error_type": "mikan_timeout",
        "error_message": "MiKan HTTP 请求超时",
        "failed_step": "mikan_search",
        "details": {"category": "timeout"},
    }
    assert "secret-token" not in str(error.value.as_dict())


def test_mikan_injected_stage_error_is_sanitized() -> None:
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/Home/Search",
            timeout_seconds=5,
        ),
        transport=ErrorTransport(
            Stage1Error(
                "mikan_parse_failed",
                "raw <html>secret-token</html>",
                "fake_step",
                {"html": "<html>secret-token</html>"},
            )
        ),
    )

    with pytest.raises(Stage1Error) as error:
        client.list_bangumi_candidates("芙莉莲")

    assert error.value.as_dict() == {
        "error_type": "mikan_parse_failed",
        "error_message": "MiKan 页面解析失败",
        "failed_step": "mikan_search",
        "details": {},
    }
    assert "secret-token" not in str(error.value.as_dict())


def test_mikan_client_exposes_rss_source_listing_boundary() -> None:
    transport = FakeTransport(
        """
        <html>
          <body>
            <table>
              <tr>
                <td>喵萌奶茶屋</td>
                <td>
                  <a href="/RSS/Bangumi?bangumiId=1&subtitleGroupId=10">
                    RSS
                  </a>
                </td>
              </tr>
              <tr>
                <td>桜都字幕组</td>
                <td>
                  <a href="https://mikan.example/RSS/Bangumi?bangumiId=1&subtitleGroupId=11">
                    订阅
                  </a>
                  <a href="https://mikan.example/RSS/Bangumi?bangumiId=1&subtitleGroupId=11">
                    RSS
                  </a>
                </td>
              </tr>
              <tr>
                <td>无效链接</td>
                <td><a href="ftp://mikan.example/RSS/Bangumi?bad=1">RSS</a></td>
              </tr>
            </table>
          </body>
        </html>
        """
    )
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/search",
            timeout_seconds=5,
        ),
        transport=transport,
    )
    matched = MatchedBangumi(
        title="芙莉莲",
        aliases=[],
        mikan_url="https://mikan.example/Home/Bangumi/1",
        match_score=1,
    )

    sources = client.list_rss_sources(matched)

    assert transport.requests == [("https://mikan.example/Home/Bangumi/1", 5)]
    assert sources[0].subtitle_group == "喵萌奶茶屋"
    assert (
        sources[0].rss_url
        == "https://mikan.example/RSS/Bangumi?bangumiId=1&subtitleGroupId=10"
    )
    assert sources[0].source_type == "mikan_http"
    assert sources[0].fixture_path == ""
    assert sources[1].subtitle_group == "桜都字幕组"
    assert (
        sources[1].rss_url
        == "https://mikan.example/RSS/Bangumi?bangumiId=1&subtitleGroupId=11"
    )
    assert len(sources) == 2


def test_mikan_client_parses_sanitized_bangumi_detail_fixture() -> None:
    html = _read_fixture("mikan_bangumi_2353_detail.html")
    transport = FakeTransport(html)
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikanani.me/Home/Search",
            timeout_seconds=5,
        ),
        transport=transport,
    )
    matched = MatchedBangumi(
        title="无职转生～到了异世界就拿出真本事～",
        aliases=[],
        mikan_url="https://mikanani.me/Home/Bangumi/2353",
        match_score=1,
    )

    sources = client.list_rss_sources(matched)

    assert transport.requests == [("https://mikanani.me/Home/Bangumi/2353", 5)]
    assert [source.subtitle_group for source in sources] == [
        "桜都字幕组",
        "喵萌奶茶屋",
    ]
    assert [source.rss_url for source in sources] == [
        "https://mikanani.me/RSS/Bangumi?bangumiId=2353&subgroupid=203",
        "https://mikanani.me/RSS/Bangumi?bangumiId=2353&subgroupid=1231",
    ]
    assert all(source.source_type == "mikan_http" for source in sources)
    assert all(source.fixture_path == "" for source in sources)


def test_mikan_bangumi_detail_fixture_exposes_title_subgroups_and_episode_links() -> None:
    html = _read_fixture("mikan_bangumi_2353_detail.html")
    parser = _MikanBangumiPageParser("https://mikanani.me/Home/Bangumi/2353")

    parser.feed(html)

    assert parser.title() == "无职转生～到了异世界就拿出真本事～"
    assert parser.subgroup_names() == ["桜都字幕组", "喵萌奶茶屋"]
    assert 'class="bangumi-title"' in html
    assert 'class="mikan-rss"' in html
    assert 'class="subgroup-name"' in html
    assert "/Home/Episode/fixture-2353-01" in html
    assert "magnet:?xt=urn:btih:SANITIZED235301" in html
    assert "[桜都字幕组] 无职转生～到了异世界就拿出真本事～ - 01" in html


def test_mikan_bangumi_detail_fixture_is_sanitized() -> None:
    html = _read_fixture("mikan_bangumi_2353_detail.html")
    forbidden_tokens = [
        "cookie",
        "token",
        "authorization",
        "session",
        "sid=",
        "/home/ghostning/",
        "file://",
        "/users/",
        "c:\\",
    ]

    normalized_html = html.casefold()

    assert "SANITIZED" in html
    assert all(token not in normalized_html for token in forbidden_tokens)


def test_mikan_client_uses_anchor_metadata_for_rss_source_group() -> None:
    transport = FakeTransport(
        """
        <a
          data-subtitle-group="Lilith-Raws"
          href="https://mikan.example/feed/frieren.xml"
        >
          RSS
        </a>
        """
    )
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/search",
            timeout_seconds=5,
        ),
        transport=transport,
    )
    matched = MatchedBangumi(
        title="芙莉莲",
        aliases=[],
        mikan_url="https://mikan.example/Home/Bangumi/1",
        match_score=1,
    )

    sources = client.list_rss_sources(matched)

    assert len(sources) == 1
    assert sources[0].subtitle_group == "Lilith-Raws"
    assert sources[0].rss_url == "https://mikan.example/feed/frieren.xml"


def test_mikan_client_rejects_empty_bangumi_url_before_transport() -> None:
    transport = FakeTransport()
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/search",
            timeout_seconds=5,
        ),
        transport=transport,
    )
    matched = MatchedBangumi(
        title="芙莉莲",
        aliases=[],
        mikan_url="  ",
        match_score=1,
    )

    with pytest.raises(Stage1Error) as error:
        client.list_rss_sources(matched)

    assert error.value.error_type == "invalid_input"
    assert error.value.failed_step == "mikan_list_rss_sources"
    assert transport.requests == []


def test_mikan_client_raises_parse_error_when_bangumi_page_has_no_rss_sources() -> None:
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/search",
            timeout_seconds=5,
        ),
        transport=FakeTransport("<a href='/Home/Bangumi/2'>not rss</a>"),
    )
    matched = MatchedBangumi(
        title="芙莉莲",
        aliases=[],
        mikan_url="https://mikan.example/Home/Bangumi/1",
        match_score=1,
    )

    with pytest.raises(Stage1Error) as error:
        client.list_rss_sources(matched)

    assert error.value.error_type == "mikan_parse_failed"
    assert error.value.failed_step == "mikan_list_rss_sources"
    assert "<html" not in str(error.value.as_dict())


def test_mikan_bangumi_page_http_failure_uses_rss_listing_step() -> None:
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/search",
            timeout_seconds=5,
        ),
        transport=ErrorTransport(TimeoutError("timeout with secret-token")),
    )
    matched = MatchedBangumi(
        title="芙莉莲",
        aliases=[],
        mikan_url="https://mikan.example/Home/Bangumi/1?cookie=secret-token",
        match_score=1,
    )

    with pytest.raises(Stage1Error) as error:
        client.list_rss_sources(matched)

    assert error.value.as_dict() == {
        "error_type": "mikan_timeout",
        "error_message": "MiKan HTTP 请求超时",
        "failed_step": "mikan_list_rss_sources",
        "details": {"category": "timeout"},
    }
    assert "secret-token" not in str(error.value.as_dict())


def _read_fixture(filename: str) -> str:
    return (FIXTURE_DIR / filename).read_text(encoding="utf-8")
