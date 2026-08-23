from __future__ import annotations

from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

import mikan_engine.controllers.mikan_client as mikan_client_module
from mikan_engine.controllers.mikan_client import (
    MIKAN_READ_CHUNK_BYTES,
    MAX_MIKAN_STREAM_SECONDS,
    MAX_MIKAN_RESPONSE_BYTES,
    MikanPartialResponseError,
    _MikanBangumiPageParser,
    _MikanCandidatePageParser,
    _parse_candidate_cards,
    UrlopenMikanTransport,
    create_mikan_client,
)
from mikan_engine.models import MikanCandidate
from mikan_engine.controllers.mikan_config import (
    DEFAULT_MIKAN_TIMEOUT_SECONDS,
    MikanConfig,
    default_mikan_config,
)
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


class _FakeUrlopenResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.offset = 0
        self.read_sizes: list[int] = []

    def __enter__(self) -> "_FakeUrlopenResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if size < 0:
            chunk = self.body[self.offset :]
            self.offset = len(self.body)
            return chunk
        chunk = self.body[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


class _ChunkedFakeUrlopenResponse:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.read_sizes: list[int] = []

    def __enter__(self) -> "_ChunkedFakeUrlopenResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if not self.chunks:
            return b""
        return self.chunks.pop(0)


class _Read1FakeUrlopenResponse(_ChunkedFakeUrlopenResponse):
    def __init__(self, chunks: list[bytes]) -> None:
        super().__init__(chunks)
        self.read_calls = 0
        self.read1_calls = 0

    def read(self, size: int = -1) -> bytes:
        self.read_calls += 1
        return super().read(size)

    def read1(self, size: int = -1) -> bytes:
        self.read1_calls += 1
        return super().read(size)


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


def test_mikan_client_direct_id_derives_detail_url_from_config() -> None:
    transport = FakeTransport(
        """
        <h1 class="bangumi-title">芙莉莲</h1>
        <a class="mikan-rss" href="/RSS/Bangumi?bangumiId=3072">RSS</a>
        """
    )
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/Home/Search?classic=true",
            timeout_seconds=7,
        ),
        transport=transport,
    )

    detail = client.get_direct_bangumi_detail("3072")

    assert transport.requests == [("https://mikan.example/Home/Bangumi/3072", 7)]
    assert detail.bangumi_id == "3072"
    assert detail.mikan_url == "https://mikan.example/Home/Bangumi/3072"


def test_mikan_client_direct_id_derives_detail_url_from_default_host() -> None:
    transport = FakeTransport(
        """
        <h1 class="bangumi-title">芙莉莲</h1>
        <a class="mikan-rss" href="/RSS/Bangumi?bangumiId=3072">RSS</a>
        """
    )
    client = create_mikan_client(default_mikan_config(), transport=transport)

    detail = client.get_direct_bangumi_detail("3072")

    assert transport.requests == [
        ("https://mikanani.me/Home/Bangumi/3072", DEFAULT_MIKAN_TIMEOUT_SECONDS)
    ]
    assert detail.bangumi_id == "3072"
    assert detail.mikan_url == "https://mikanani.me/Home/Bangumi/3072"


def test_mikan_client_direct_url_normalizes_and_rejects_unsafe_values() -> None:
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/Home/Search",
            timeout_seconds=5,
        ),
        transport=FakeTransport(
            """
            <h1 class="bangumi-title">芙莉莲</h1>
            <a class="mikan-rss" href="/RSS/Bangumi?bangumiId=3072">RSS</a>
            """
        ),
    )

    detail = client.get_direct_bangumi_detail(
        "https://mikan.example/Home/Bangumi/3072?token=secret#frag"
    )

    assert detail.mikan_url == "https://mikan.example/Home/Bangumi/3072"
    for value in [
        "",
        "not-a-url",
        "ftp://mikan.example/Home/Bangumi/3072",
        "https://mikan.example/Home/Search?searchstr=secret-token",
        "https://evil.example/Home/Bangumi/3072?token=secret-token",
        "https://mikan.example/Home/Bangumi/../3072",
        "https://mikan.example/Home/Bangumi/abc",
    ]:
        with pytest.raises(Stage1Error) as error:
            client.get_direct_bangumi_detail(value)

        assert error.value.as_dict() == {
            "error_type": "invalid_input",
            "error_message": "MiKan bangumi 直连入口必须是数字 ID 或 Home/Bangumi URL",
            "failed_step": "mikan_direct_entry",
            "details": {"field": "mikan_bangumi"},
        }
        assert "secret-token" not in str(error.value.as_dict())


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


def test_mikan_urlopen_transport_uses_bounded_read_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _FakeUrlopenResponse(b"ok")
    timeouts: list[float] = []

    def fake_urlopen(request: object, *, timeout: float) -> _FakeUrlopenResponse:
        timeouts.append(timeout)
        return response

    monkeypatch.setattr(mikan_client_module, "urlopen", fake_urlopen)

    text = UrlopenMikanTransport().get_text("https://mikan.example/Home/Search", timeout=3)

    assert text == "ok"
    assert response.read_sizes == [MIKAN_READ_CHUNK_BYTES, MIKAN_READ_CHUNK_BYTES]
    assert timeouts == [3]


def test_mikan_urlopen_transport_extends_deadline_when_chunks_arrive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _ChunkedFakeUrlopenResponse([b"he", b"ll", b"o", b""])
    clock_values = iter([0.0, 0.0, 14.0, 16.0, 28.0, 30.0, 44.0, 45.0])

    def fake_urlopen(request: object, *, timeout: float) -> _ChunkedFakeUrlopenResponse:
        return response

    monkeypatch.setattr(mikan_client_module, "urlopen", fake_urlopen)
    monkeypatch.setattr(mikan_client_module, "monotonic", lambda: next(clock_values))

    text = UrlopenMikanTransport().get_text("https://mikan.example/Home/Search", timeout=15)

    assert text == "hello"
    assert response.read_sizes == [
        MIKAN_READ_CHUNK_BYTES,
        MIKAN_READ_CHUNK_BYTES,
        MIKAN_READ_CHUNK_BYTES,
        MIKAN_READ_CHUNK_BYTES,
    ]


def test_mikan_urlopen_transport_prefers_read1_for_streaming_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _Read1FakeUrlopenResponse([b"partial", b""])

    def fake_urlopen(request: object, *, timeout: float) -> _Read1FakeUrlopenResponse:
        return response

    monkeypatch.setattr(mikan_client_module, "urlopen", fake_urlopen)

    text = UrlopenMikanTransport().get_text("https://mikan.example/Home/Search", timeout=15)

    assert text == "partial"
    assert response.read1_calls == 2
    assert response.read_calls == 0


def test_mikan_search_transport_stops_after_complete_candidate_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The de-identified large fixture models episode data after candidates."""
    fixture = _read_fixture("mikan_search_large_response.html").encode("utf-8")
    full_response = _FakeUrlopenResponse(fixture)
    early_response = _ChunkedFakeUrlopenResponse(
        [fixture[index : index + 37] for index in range(0, len(fixture), 37)]
    )

    def fake_urlopen_full(request: object, *, timeout: float) -> _FakeUrlopenResponse:
        return full_response

    monkeypatch.setattr(mikan_client_module, "urlopen", fake_urlopen_full)
    full_html = UrlopenMikanTransport().get_text(
        "https://mikan.example/Home/Search", timeout=15
    )

    def fake_urlopen_early(
        request: object, *, timeout: float
    ) -> _ChunkedFakeUrlopenResponse:
        return early_response

    monkeypatch.setattr(mikan_client_module, "urlopen", fake_urlopen_early)
    early_html = UrlopenMikanTransport().get_search_text(
        "https://mikan.example/Home/Search", timeout=15
    )

    assert len(early_html.encode("utf-8")) < len(full_html.encode("utf-8")) // 4
    assert _parse_candidate_cards(
        early_html, "https://mikan.example/Home/Search", "fixture"
    ) == _parse_candidate_cards(
        full_html, "https://mikan.example/Home/Search", "fixture"
    )


def test_mikan_search_transport_handles_utf8_and_marker_across_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = (
        '<section class="related-recommendations"><a href="/Home/Bangumi/7">'
        "芙莉莲</a></section><div>ignored</div>"
    ).encode("utf-8")
    response = _ChunkedFakeUrlopenResponse(
        [body[index : index + 2] for index in range(0, len(body), 2)]
    )
    monkeypatch.setattr(mikan_client_module, "urlopen", lambda request, timeout: response)

    html = UrlopenMikanTransport().get_search_text(
        "https://mikan.example/Home/Search", timeout=15
    )

    assert "ignored" not in html
    assert _parse_candidate_cards(html, "https://mikan.example/Home/Search", "fixture")[0].title == "芙莉莲"


@pytest.mark.parametrize(
    "body",
    [
        b'<section class="not-candidates"><a href="/Home/Bangumi/7">x</a></section>tail',
        b'<section class="related-recommendations"><a href="/Home/Bangumi/7">x</a>tail',
    ],
)
def test_mikan_search_transport_falls_back_to_full_bounded_read(
    monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    response = _ChunkedFakeUrlopenResponse([body[:12], body[12:], b""])
    monkeypatch.setattr(mikan_client_module, "urlopen", lambda request, timeout: response)

    assert UrlopenMikanTransport().get_search_text(
        "https://mikan.example/Home/Search", timeout=15
    ) == body.decode("utf-8")


def test_mikan_urlopen_transport_stops_at_stream_hard_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _ChunkedFakeUrlopenResponse([b"a", b"b", b""])
    clock_values = iter(
        [
            0.0,
            0.0,
            50.0,
            59.0,
            MAX_MIKAN_STREAM_SECONDS - 0.1,
            MAX_MIKAN_STREAM_SECONDS + 0.1,
        ]
    )

    def fake_urlopen(request: object, *, timeout: float) -> _ChunkedFakeUrlopenResponse:
        return response

    monkeypatch.setattr(mikan_client_module, "urlopen", fake_urlopen)
    monkeypatch.setattr(mikan_client_module, "monotonic", lambda: next(clock_values))

    with pytest.raises(MikanPartialResponseError) as error:
        UrlopenMikanTransport().get_text("https://mikan.example/Home/Search", timeout=15)

    assert error.value.body == b"ab"


def test_mikan_urlopen_oversized_response_is_sanitized_by_call_site(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: object, *, timeout: float) -> _FakeUrlopenResponse:
        return _FakeUrlopenResponse(b"x" * (MAX_MIKAN_RESPONSE_BYTES + 1))

    monkeypatch.setattr(mikan_client_module, "urlopen", fake_urlopen)
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/Home/Search?token=secret-token",
            timeout_seconds=5,
        )
    )

    with pytest.raises(Stage1Error) as error:
        client.list_bangumi_candidates("芙莉莲")

    assert error.value.as_dict() == {
        "error_type": "mikan_parse_failed",
        "error_message": "MiKan 页面解析失败",
        "failed_step": "mikan_search",
        "details": {"category": "response_too_large"},
    }
    assert "secret-token" not in str(error.value.as_dict())


def test_mikan_urlopen_encoding_failure_is_sanitized_by_detail_call_site(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: object, *, timeout: float) -> _FakeUrlopenResponse:
        return _FakeUrlopenResponse(b"\xff\xfe")

    monkeypatch.setattr(mikan_client_module, "urlopen", fake_urlopen)
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/Home/Search",
            timeout_seconds=5,
        )
    )
    matched = MatchedBangumi(
        title="芙莉莲",
        aliases=[],
        mikan_url="https://mikan.example/Home/Bangumi/1?cookie=secret-token",
        match_score=1,
    )

    with pytest.raises(Stage1Error) as error:
        client.get_bangumi_detail(matched)

    assert error.value.as_dict() == {
        "error_type": "mikan_parse_failed",
        "error_message": "MiKan 页面解析失败",
        "failed_step": "mikan_bangumi_detail",
        "details": {"category": "encoding"},
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
            <h1 class="bangumi-title">芙莉莲</h1>
            <a class="mikan-rss" href="/RSS/Bangumi?bangumiId=1">RSS</a>
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
    assert all(
        source.rss_url != "https://mikan.example/RSS/Bangumi?bangumiId=1"
        for source in sources
    )


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


def test_mikan_client_list_rss_sources_prefers_subgroups_over_bangumi_rss() -> None:
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/Home/Search",
            timeout_seconds=5,
        ),
        transport=FakeTransport(
            """
            <h1 class="bangumi-title">芙莉莲</h1>
            <a class="mikan-rss" href="/RSS/Bangumi?bangumiId=1">RSS</a>
            <section class="subgroup-section">
              <h2 class="subgroup-name">喵萌奶茶屋</h2>
              <a href="/RSS/Bangumi?bangumiId=1&subgroupid=10">RSS</a>
            </section>
            <section class="subgroup-section">
              <h2 class="subgroup-name">桜都字幕组</h2>
              <a href="/RSS/Bangumi?bangumiId=1&subgroupid=11">RSS</a>
            </section>
            """
        ),
    )
    matched = MatchedBangumi(
        title="芙莉莲",
        aliases=[],
        mikan_url="https://mikan.example/Home/Bangumi/1",
        match_score=1,
    )

    sources = client.list_rss_sources(matched)

    assert [source.subtitle_group for source in sources] == ["喵萌奶茶屋", "桜都字幕组"]
    assert [source.rss_url for source in sources] == [
        "https://mikan.example/RSS/Bangumi?bangumiId=1&subgroupid=10",
        "https://mikan.example/RSS/Bangumi?bangumiId=1&subgroupid=11",
    ]
    assert all(source.source_type == "mikan_http" for source in sources)
    assert all(source.fixture_path == "" for source in sources)


def test_mikan_client_list_rss_sources_parses_current_subgroup_text_sections() -> None:
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikanani.me/Home/Search",
            timeout_seconds=5,
        ),
        transport=FakeTransport(
            """
            <p class="bangumi-title">
              咒术回战
              <a href="/RSS/Bangumi?bangumiId=2283" class="mikan-rss">RSS</a>
            </p>
            <a class="subgroup-name subgroup-552" data-anchor="#552">Lilith-Raws</a>
            <a class="subgroup-name subgroup-562" data-anchor="#562">NC-Raws</a>
            <div class="subgroup-text" id="552">
              <a href="/RSS/Bangumi?bangumiId=2283&subgroupid=552" class="mikan-rss">RSS</a>
              <div class="episode-table">
                <a class="magnet-link-wrap" href="/Home/Episode/SANITIZED1">
                  [Lilith-Raws] 咒术回战 - 24 [1080p]
                </a>
              </div>
            </div>
            <div class="subgroup-text" id="562">
              <a href="/RSS/Bangumi?bangumiId=2283&subgroupid=562" class="mikan-rss">RSS</a>
            </div>
            """
        ),
    )
    matched = MatchedBangumi(
        title="咒术回战",
        aliases=[],
        mikan_url="https://mikanani.me/Home/Bangumi/2283",
        match_score=1,
    )

    sources = client.list_rss_sources(matched)

    assert [source.subtitle_group for source in sources] == ["Lilith-Raws", "NC-Raws"]
    assert [source.rss_url for source in sources] == [
        "https://mikanani.me/RSS/Bangumi?bangumiId=2283&subgroupid=552",
        "https://mikanani.me/RSS/Bangumi?bangumiId=2283&subgroupid=562",
    ]


def test_mikan_client_list_rss_sources_deduplicates_subgroup_rss_urls() -> None:
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/Home/Search",
            timeout_seconds=5,
        ),
        transport=FakeTransport(
            """
            <h1 class="bangumi-title">芙莉莲</h1>
            <section class="subgroup-section">
              <h2 class="subgroup-name">喵萌奶茶屋</h2>
              <a href="/RSS/Bangumi?bangumiId=1&subgroupid=10">RSS</a>
              <a href="/RSS/Bangumi?bangumiId=1&subgroupid=10">订阅</a>
            </section>
            """
        ),
    )
    matched = MatchedBangumi(
        title="芙莉莲",
        aliases=[],
        mikan_url="https://mikan.example/Home/Bangumi/1",
        match_score=1,
    )

    sources = client.list_rss_sources(matched)

    assert len(sources) == 1
    assert sources[0].subtitle_group == "喵萌奶茶屋"
    assert (
        sources[0].rss_url
        == "https://mikan.example/RSS/Bangumi?bangumiId=1&subgroupid=10"
    )


def test_mikan_client_list_rss_sources_falls_back_to_bangumi_rss() -> None:
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/Home/Search",
            timeout_seconds=5,
        ),
        transport=FakeTransport(
            """
            <h1 class="bangumi-title">芙莉莲</h1>
            <a class="mikan-rss" href="/RSS/Bangumi?bangumiId=1">RSS</a>
            <section class="subgroup-section">
              <h2 class="subgroup-name">喵萌奶茶屋</h2>
              <a href="/Home/Episode/1">[喵萌奶茶屋] 芙莉莲 - 01</a>
            </section>
            """
        ),
    )
    matched = MatchedBangumi(
        title="芙莉莲",
        aliases=[],
        mikan_url="https://mikan.example/Home/Bangumi/1",
        match_score=1,
    )

    sources = client.list_rss_sources(matched)

    assert len(sources) == 1
    assert sources[0].subtitle_group == "全部字幕组"
    assert sources[0].rss_url == "https://mikan.example/RSS/Bangumi?bangumiId=1"
    assert sources[0].source_type == "mikan_http"
    assert sources[0].fixture_path == ""


def test_mikan_client_parses_structured_bangumi_detail_fixture() -> None:
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

    detail = client.get_bangumi_detail(matched)

    assert transport.requests == [("https://mikanani.me/Home/Bangumi/2353", 5)]
    assert detail.bangumi_id == "2353"
    assert detail.title == "无职转生～到了异世界就拿出真本事～"
    assert detail.mikan_url == "https://mikanani.me/Home/Bangumi/2353"
    assert detail.broadcast_start is None
    assert detail.poster_url is None
    assert (
        detail.bangumi_rss_url
        == "https://mikanani.me/RSS/Bangumi?bangumiId=2353"
    )
    assert [subgroup.name for subgroup in detail.subgroups] == [
        "桜都字幕组",
        "喵萌奶茶屋",
    ]
    assert [subgroup.rss_url for subgroup in detail.subgroups] == [
        "https://mikanani.me/RSS/Bangumi?bangumiId=2353&subgroupid=203",
        "https://mikanani.me/RSS/Bangumi?bangumiId=2353&subgroupid=1231",
    ]
    assert detail.subgroups[0].episodes[0].title == (
        "[桜都字幕组] 无职转生～到了异世界就拿出真本事～ - 01 "
        "[1080p][简繁内封]"
    )
    assert (
        detail.subgroups[0].episodes[0].episode_url
        == "https://mikanani.me/Home/Episode/fixture-2353-01"
    )
    assert "magnet:" not in repr(detail)
    assert "SANITIZED235301" not in repr(detail)


def test_mikan_bangumi_detail_deduplicates_rss_urls_and_episode_summaries() -> None:
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/Home/Search",
            timeout_seconds=5,
        ),
        transport=FakeTransport(
            """
            <h1 class="bangumi-title">芙莉莲</h1>
            <a class="mikan-rss" href="/RSS/Bangumi?bangumiId=1">RSS</a>
            <section class="subgroup-section">
              <h2 class="subgroup-name">喵萌奶茶屋</h2>
              <table>
                <tr>
                  <td class="subgroup-name">喵萌奶茶屋</td>
                  <td>
                    <a href="/RSS/Bangumi?bangumiId=1&subgroupid=10">RSS</a>
                    <a href="/RSS/Bangumi?bangumiId=1&subgroupid=10">订阅</a>
                  </td>
                </tr>
                <tr>
                  <td>
                    <a href="/Home/Episode/1">[喵萌奶茶屋] 芙莉莲 - 01</a>
                    <a href="/Home/Episode/1">[喵萌奶茶屋] 芙莉莲 - 01</a>
                  </td>
                </tr>
              </table>
            </section>
            """
        ),
    )
    matched = MatchedBangumi(
        title="芙莉莲",
        aliases=[],
        mikan_url="https://mikan.example/Home/Bangumi/1",
        match_score=1,
    )

    detail = client.get_bangumi_detail(matched)

    assert len(detail.subgroups) == 1
    assert detail.subgroups[0].rss_url == (
        "https://mikan.example/RSS/Bangumi?bangumiId=1&subgroupid=10"
    )
    assert len(detail.subgroups[0].episodes) == 1
    assert detail.subgroups[0].episodes[0].title == "[喵萌奶茶屋] 芙莉莲 - 01"


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
        <h1 class="bangumi-title">芙莉莲</h1>
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


def test_mikan_client_rejects_empty_detail_url_before_transport() -> None:
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
        client.get_bangumi_detail(matched)

    assert error.value.error_type == "invalid_input"
    assert error.value.failed_step == "mikan_bangumi_detail"
    assert transport.requests == []


def test_mikan_client_raises_parse_error_when_bangumi_page_has_no_rss_sources() -> None:
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/search",
            timeout_seconds=5,
        ),
        transport=FakeTransport(
            "<h1 class='bangumi-title'>secret-token 番剧</h1><div>raw html</div>"
        ),
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
        "error_type": "mikan_parse_failed",
        "error_message": "MiKan 番剧页未找到 RSS 源",
        "failed_step": "mikan_list_rss_sources",
        "details": {},
    }
    assert "secret-token" not in str(error.value.as_dict())
    assert "raw html" not in str(error.value.as_dict())


def test_mikan_client_raises_safe_detail_parse_error_when_page_has_no_rss() -> None:
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/search",
            timeout_seconds=5,
        ),
        transport=FakeTransport(
            "<h1 class='bangumi-title'>secret-token 番剧</h1><div>raw html</div>"
        ),
    )
    matched = MatchedBangumi(
        title="芙莉莲",
        aliases=[],
        mikan_url="https://mikan.example/Home/Bangumi/1?cookie=secret-token",
        match_score=1,
    )

    with pytest.raises(Stage1Error) as error:
        client.get_bangumi_detail(matched)

    assert error.value.as_dict() == {
        "error_type": "mikan_parse_failed",
        "error_message": "MiKan 番剧页未找到可用 RSS",
        "failed_step": "mikan_bangumi_detail",
        "details": {},
    }
    assert "secret-token" not in str(error.value.as_dict())
    assert "raw html" not in str(error.value.as_dict())


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


def test_mikan_search_candidates_can_use_partial_html_after_stream_timeout() -> None:
    partial_html = b"""
    <ul class="list-inline an-ul">
      <li>
        <a href="/Home/Bangumi/3074" target="_blank">
          <div class="an-info">
            <div class="an-info-group">
              <div class="an-text" title="\xe5\x92\x92\xe6\x9c\xaf\xe5\x9b\x9e\xe6\x88\x98 \xe7\xac\xac\xe4\xba\x8c\xe5\xad\xa3">\xe5\x92\x92\xe6\x9c\xaf\xe5\x9b\x9e\xe6\x88\x98 \xe7\xac\xac\xe4\xba\x8c\xe5\xad\xa3</div>
            </div>
          </div>
        </a>
      </li>
    </ul>
    """
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikanani.me/Home/Search",
            timeout_seconds=15,
        ),
        transport=ErrorTransport(MikanPartialResponseError(partial_html)),
    )

    candidates = client.search_candidates("咒术回战")

    assert [(candidate.bangumi_id, candidate.title) for candidate in candidates] == [
        ("3074", "咒术回战 第二季")
    ]


def test_mikan_detail_rejects_partial_html_after_stream_timeout() -> None:
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikanani.me/Home/Search",
            timeout_seconds=15,
        ),
        transport=ErrorTransport(MikanPartialResponseError(b"<p class='bangumi-title'>x")),
    )
    matched = MatchedBangumi(
        title="咒术回战",
        aliases=[],
        mikan_url="https://mikanani.me/Home/Bangumi/2283",
        match_score=1,
    )

    with pytest.raises(Stage1Error) as error:
        client.get_bangumi_detail(matched)

    assert error.value.as_dict() == {
        "error_type": "mikan_timeout",
        "error_message": "MiKan HTTP 请求超时",
        "failed_step": "mikan_bangumi_detail",
        "details": {"category": "timeout"},
    }


def test_mikan_bangumi_detail_http_failure_uses_detail_step() -> None:
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/search",
            timeout_seconds=5,
        ),
        transport=ErrorTransport(
            HTTPError("https://mikan.example/secret", 500, "", {}, None)
        ),
    )
    matched = MatchedBangumi(
        title="芙莉莲",
        aliases=[],
        mikan_url="https://mikan.example/Home/Bangumi/1?cookie=secret-token",
        match_score=1,
    )

    with pytest.raises(Stage1Error) as error:
        client.get_bangumi_detail(matched)

    assert error.value.as_dict() == {
        "error_type": "mikan_http_failed",
        "error_message": "MiKan HTTP 请求失败",
        "failed_step": "mikan_bangumi_detail",
        "details": {"status_code": 500},
    }
    assert "secret-token" not in str(error.value.as_dict())


def test_mikan_client_parses_candidate_fixture_with_posters_and_order() -> None:
    html = _read_fixture("mikan_search_candidates.html")
    transport = FakeTransport(html)
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikanani.me/Home/Search",
            timeout_seconds=5,
        ),
        transport=transport,
    )

    candidates = client.search_candidates("无职转生")

    assert transport.requests == [
        ("https://mikanani.me/Home/Search?searchstr=%E6%97%A0%E8%81%8C%E8%BD%AC%E7%94%9F", 5)
    ]
    assert [candidate.bangumi_id for candidate in candidates] == ["2353", "3072", "9999"]
    assert [candidate.title for candidate in candidates] == [
        "无职转生～到了异世界就拿出真本事～",
        "葬送的芙莉莲",
        "咒术回战 第三季",
    ]
    assert [candidate.mikan_url for candidate in candidates] == [
        "https://mikanani.me/Home/Bangumi/2353",
        "https://mikanani.me/Home/Bangumi/3072",
        "https://mikanani.me/Home/Bangumi/9999",
    ]
    assert [candidate.poster_url for candidate in candidates] == [
        "https://mikanani.me/assets/cover/SANITIZED-2353.jpg",
        "https://mikanani.me/assets/cover/SANITIZED-3072.jpg",
        None,
    ]
    assert all(candidate.source_query == "无职转生" for candidate in candidates)
    assert candidates[0].aliases == ["Mushoku Tensei: Jobless Reincarnation"]
    assert candidates[1].aliases == []
    assert candidates[2].aliases == []


def test_mikan_candidate_search_parses_current_mikan_recommendation_links() -> None:
    transport = FakeTransport(
        """
        <ul class="list-inline an-ul">
          <li>
            <a href="/Home/Bangumi/3074" target="_blank">
              <span data-src="/images/Bangumi/202307/SANITIZED.jpg?width=400" class="b-lazy"></span>
              <div class="an-info">
                <div class="an-info-group">
                  <div class="an-text" title="咒术回战 第二季">咒术回战 第二季</div>
                </div>
              </div>
            </a>
          </li>
          <li>
            <a href="/Home/Bangumi/2283" target="_blank">
              <div class="an-info">
                <div class="an-info-group">
                  <div class="an-text" title="咒术回战">咒术回战</div>
                </div>
              </div>
            </a>
          </li>
        </ul>
        """
    )
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikanani.me/Home/Search",
            timeout_seconds=5,
        ),
        transport=transport,
    )

    candidates = client.search_candidates("咒术回战")

    assert [candidate.bangumi_id for candidate in candidates] == ["3074", "2283"]
    assert [candidate.title for candidate in candidates] == ["咒术回战 第二季", "咒术回战"]
    assert candidates[0].poster_url == (
        "https://mikanani.me/images/Bangumi/202307/SANITIZED.jpg?width=400"
    )


def test_mikan_candidate_search_rejects_unsafe_hrefs() -> None:
    transport = FakeTransport(
        """
        <section class="related-recommendations">
          <h2>相关推荐</h2>
          <div class="bangumi-item">
            <a class="an-text" href="/Home/Bangumi/100">迷宫饭</a>
          </div>
          <div class="bangumi-item">
            <a class="an-text" href="/Home/News/1">不是番剧</a>
          </div>
          <div class="bangumi-item">
            <a class="an-text" href="ftp://mikan.example/Home/Bangumi/200">非 HTTP</a>
          </div>
          <div class="bangumi-item">
            <a class="an-text" href="/Home/Bangumi/../300">路径穿越</a>
          </div>
          <div class="bangumi-item">
            <a class="an-text" href="/Home/Bangumi/abc">非数字 ID</a>
          </div>
          <div class="bangumi-item">
            <a class="an-text" href="/Home/Bangumi/">空 ID</a>
          </div>
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

    candidates = client.search_candidates("迷宫饭")

    assert len(candidates) == 1
    assert candidates[0].bangumi_id == "100"
    assert candidates[0].title == "迷宫饭"
    assert candidates[0].mikan_url == "https://mikan.example/Home/Bangumi/100"


def test_mikan_candidate_search_returns_empty_when_none_found() -> None:
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/Home/Search",
            timeout_seconds=5,
        ),
        transport=FakeTransport(
            """
            <section class="related-recommendations">
              <h2>相关推荐</h2>
              <p>暂无相关合集</p>
              <a href="/Home/News/1">只有新闻链接</a>
            </section>
            """
        ),
    )

    candidates = client.search_candidates("不存在的番剧")

    assert candidates == []


def test_mikan_candidate_search_rejects_empty_query_before_transport() -> None:
    transport = FakeTransport()
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/Home/Search",
            timeout_seconds=5,
        ),
        transport=transport,
    )

    with pytest.raises(Stage1Error) as error:
        client.search_candidates("  ")

    assert error.value.error_type == "invalid_input"
    assert error.value.failed_step == "mikan_search"
    assert transport.requests == []


def test_mikan_candidate_search_http_failure_is_sanitized() -> None:
    http_error = HTTPError(
        "https://mikan.example/Home/Search?searchstr=secret-token",
        503,
        "backend leaked secret-token",
        {},
        None,
    )
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/Home/Search",
            timeout_seconds=5,
        ),
        transport=ErrorTransport(http_error),
    )

    with pytest.raises(Stage1Error) as error:
        client.search_candidates("芙莉莲")

    assert error.value.as_dict() == {
        "error_type": "mikan_http_failed",
        "error_message": "MiKan HTTP 请求失败",
        "failed_step": "mikan_search",
        "details": {"status_code": 503},
    }
    assert "secret-token" not in str(error.value.as_dict())


def test_mikan_candidate_search_handles_nested_non_card_containers() -> None:
    transport = FakeTransport(
        """
        <section class="related-recommendations">
          <h2>相关推荐</h2>
          <div class="bangumi-item">
            <div class="inner-card">
              <a class="an-text" href="/Home/Bangumi/100">迷宫饭</a>
            </div>
          </div>
          <div class="bangumi-item">
            <a class="an-text" href="/Home/Bangumi/200">葬送的芙莉莲</a>
          </div>
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

    candidates = client.search_candidates("迷宫饭")

    assert [candidate.bangumi_id for candidate in candidates] == ["100", "200"]


def test_mikan_candidate_page_parser_exposes_related_recommendation_cards() -> None:
    html = _read_fixture("mikan_search_candidates.html")
    parser = _MikanCandidatePageParser(
        "https://mikanani.me/Home/Search",
        "无职转生",
    )

    parser.feed(html)

    assert "相关推荐" in html
    assert 'class="bangumi-item"' in html
    assert 'class="bangumi-poster"' in html
    assert "/Home/Bangumi/2353" in html
    assert all(isinstance(candidate, MikanCandidate) for candidate in parser.candidates())


def test_mikan_candidate_fixture_is_sanitized() -> None:
    html = _read_fixture("mikan_search_candidates.html")
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


def _read_fixture(filename: str) -> str:
    return (FIXTURE_DIR / filename).read_text(encoding="utf-8")
