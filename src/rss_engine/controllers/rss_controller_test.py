from __future__ import annotations

from pathlib import Path
from urllib.error import HTTPError

import pytest

from rss_engine.controllers.rss_controller import filter_seeds, parse_rss
from shared.errors import Stage1Error
from shared.models import FilterRule, ParsedRss, RssSeed, RssSource


class FakeTransport:
    def __init__(self, response: str = "") -> None:
        self.response = response
        self.requests: list[tuple[str, float]] = []

    def get_text(self, url: str, *, timeout: float) -> str:
        self.requests.append((url, timeout))
        return self.response


class FailingTransport:
    def get_text(self, url: str, *, timeout: float) -> str:
        raise OSError("network failed with hidden xml <rss>secret</rss>")


class HttpErrorTransport:
    def get_text(self, url: str, *, timeout: float) -> str:
        raise HTTPError(
            "https://mikan.example/RSS/Bangumi?token=secret-token",
            502,
            "bad gateway secret-token",
            {},
            None,
        )


def test_parse_rss_skips_item_missing_link(tmp_path: Path) -> None:
    fixture = tmp_path / "feed.xml"
    fixture.write_text(
        """<rss><channel>
        <item><title>有效条目</title><link>https://example.invalid/1</link></item>
        <item><title>缺少链接</title></item>
        </channel></rss>""",
        encoding="utf-8",
    )
    source = RssSource("组", "https://example.invalid/rss", "static_fixture", str(fixture))

    parsed = parse_rss(source, tmp_path)

    assert [seed.title for seed in parsed.seeds] == ["有效条目"]
    assert parsed.warnings


def test_parse_static_fixture_does_not_call_transport(tmp_path: Path) -> None:
    fixture = tmp_path / "feed.xml"
    fixture.write_text(
        """<rss><channel>
        <item><title>离线条目</title><link>https://example.invalid/1</link></item>
        </channel></rss>""",
        encoding="utf-8",
    )
    transport = FailingTransport()
    source = RssSource("组", "https://example.invalid/rss", "static_fixture", str(fixture))

    parsed = parse_rss(source, tmp_path, transport=transport)

    assert [seed.title for seed in parsed.seeds] == ["离线条目"]


def test_parse_mikan_http_rss_uses_injected_transport_and_existing_contract() -> None:
    transport = FakeTransport(
        """<rss><channel>
        <item>
          <title>[喵萌] 番剧 - 01 [1080p]</title>
          <link>https://example.invalid/torrent/1</link>
          <pubDate>Thu, 06 Aug 2026 10:00:00 GMT</pubDate>
          <guid>torrent-1</guid>
        </item>
        <item>
          <title>[喵萌] 番剧 - SP [720p]</title>
          <link>https://example.invalid/torrent/sp</link>
        </item>
        </channel></rss>"""
    )
    source = RssSource(
        "喵萌",
        "https://mikan.example/RSS/Bangumi?bangumiId=100&subgroupid=10",
        "mikan_http",
        "",
    )

    parsed = parse_rss(source, Path.cwd(), transport=transport, timeout=3)
    filtered = filter_seeds(
        parsed,
        FilterRule(must_contain="1080p", must_not_contain="SP"),
    )

    assert transport.requests == [(source.rss_url, 3)]
    assert parsed.source is source
    assert parsed.seeds[0].published_at == "Thu, 06 Aug 2026 10:00:00 GMT"
    assert parsed.seeds[0].guid == "torrent-1"
    assert [seed.title for seed in filtered.valid_seeds] == [
        "[喵萌] 番剧 - 01 [1080p]"
    ]
    assert filtered.total_seed_count == 2


def test_parse_mikan_http_read_failure_is_content_free_stage1_error() -> None:
    source = RssSource(
        "喵萌",
        "https://mikan.example/RSS/Bangumi?bangumiId=100",
        "mikan_http",
        "",
    )

    with pytest.raises(Stage1Error) as error:
        parse_rss(source, Path.cwd(), transport=FailingTransport())

    assert error.value.error_type == "rss_parse_failed"
    assert error.value.failed_step == "parse_rss"
    assert "hidden xml" not in error.value.message
    assert "hidden xml" not in str(error.value.details)


def test_parse_mikan_http_error_uses_parse_rss_step_and_safe_details() -> None:
    source = RssSource(
        "喵萌",
        "https://mikan.example/RSS/Bangumi?bangumiId=100&token=secret-token",
        "mikan_http",
        "",
    )

    with pytest.raises(Stage1Error) as error:
        parse_rss(source, Path.cwd(), transport=HttpErrorTransport())

    assert error.value.as_dict() == {
        "error_type": "mikan_http_failed",
        "error_message": "MiKan HTTP 请求失败",
        "failed_step": "parse_rss",
        "details": {"status_code": 502},
    }
    assert "secret-token" not in str(error.value.as_dict())


def test_parse_mikan_http_invalid_xml_does_not_include_raw_xml() -> None:
    source = RssSource(
        "喵萌",
        "https://mikan.example/RSS/Bangumi?bangumiId=100",
        "mikan_http",
        "",
    )

    with pytest.raises(Stage1Error) as error:
        parse_rss(source, Path.cwd(), transport=FakeTransport("<rss>secret"))

    assert error.value.error_type == "rss_parse_failed"
    assert "secret" not in error.value.message
    assert "secret" not in str(error.value.details)


def test_parse_rss_fails_when_no_item_is_valid(tmp_path: Path) -> None:
    fixture = tmp_path / "empty.xml"
    fixture.write_text(
        "<rss><channel><item><title>缺少链接</title></item></channel></rss>",
        encoding="utf-8",
    )
    source = RssSource("组", "url", "static_fixture", str(fixture))

    with pytest.raises(Stage1Error) as error:
        parse_rss(source, tmp_path)

    assert error.value.error_type == "rss_parse_failed"


def test_parse_rss_fails_for_invalid_xml(tmp_path: Path) -> None:
    fixture = tmp_path / "invalid.xml"
    fixture.write_text("<rss>", encoding="utf-8")
    source = RssSource("组", "url", "static_fixture", str(fixture))

    with pytest.raises(Stage1Error) as error:
        parse_rss(source, tmp_path)

    assert error.value.error_type == "rss_parse_failed"


def test_filter_uses_must_not_contain_before_must_contain() -> None:
    source = RssSource("组", "url", "static_fixture", "feed.xml")
    parsed = ParsedRss(
        source=source,
        seeds=[
            RssSeed("番剧 01 1080p", "1"),
            RssSeed("番剧 01 V2 1080p", "2"),
            RssSeed("番剧 01 720p", "3"),
        ],
    )

    result = filter_seeds(
        parsed,
        FilterRule(must_contain="1080p", must_not_contain="V2"),
    )

    assert [seed.title for seed in result.valid_seeds] == ["番剧 01 1080p"]
    assert [item.rule for item in result.excluded_seeds] == [
        "must_not_contain",
        "must_contain",
    ]


def test_invalid_regex_is_config_error_when_use_regex_enabled() -> None:
    source = RssSource("组", "url", "static_fixture", "feed.xml")
    parsed = ParsedRss(source=source, seeds=[RssSeed("条目", "1")])

    with pytest.raises(Stage1Error) as error:
        filter_seeds(parsed, FilterRule(must_contain="[", use_regex=True))

    assert error.value.error_type == "config_error"


def test_literal_default_does_not_compile_brackets_as_regex() -> None:
    source = RssSource("组", "url", "static_fixture", "feed.xml")
    parsed = ParsedRss(
        source=source,
        seeds=[
            RssSeed("[Loli] 番剧 - 01 [v2]", "1"),
            RssSeed("[Loli] 番剧 - 02", "2"),
        ],
    )

    result = filter_seeds(parsed, FilterRule(must_contain="[v2]"))

    assert [seed.title for seed in result.valid_seeds] == ["[Loli] 番剧 - 01 [v2]"]
    assert [item.rule for item in result.excluded_seeds] == ["must_contain"]
    assert result.excluded_seeds[0].reason == "未命中包含规则：[v2]"


def test_literal_match_is_case_insensitive_by_default() -> None:
    source = RssSource("组", "url", "static_fixture", "feed.xml")
    parsed = ParsedRss(
        source=source,
        seeds=[RssSeed("番剧 01 V2 1080p", "1")],
    )

    result = filter_seeds(parsed, FilterRule(must_contain="v2"))

    assert [seed.title for seed in result.valid_seeds] == ["番剧 01 V2 1080p"]
    assert result.excluded_seeds == []


def test_literal_case_sensitive_does_not_match_different_case() -> None:
    source = RssSource("组", "url", "static_fixture", "feed.xml")
    parsed = ParsedRss(
        source=source,
        seeds=[RssSeed("番剧 01 V2 1080p", "1")],
    )

    result = filter_seeds(
        parsed,
        FilterRule(must_contain="v2", case_sensitive=True),
    )

    assert result.valid_seeds == []
    assert result.excluded_seeds[0].rule == "must_contain"
    assert result.excluded_seeds[0].reason == "未命中包含规则：v2"


def test_regex_match_is_case_insensitive_by_default() -> None:
    source = RssSource("组", "url", "static_fixture", "feed.xml")
    parsed = ParsedRss(
        source=source,
        seeds=[RssSeed("番剧 01 V2 1080p", "1")],
    )

    result = filter_seeds(
        parsed,
        FilterRule(must_contain="^番剧.*v2", use_regex=True),
    )

    assert [seed.title for seed in result.valid_seeds] == ["番剧 01 V2 1080p"]


def test_regex_case_sensitive_does_not_match_different_case() -> None:
    source = RssSource("组", "url", "static_fixture", "feed.xml")
    parsed = ParsedRss(
        source=source,
        seeds=[RssSeed("番剧 01 V2 1080p", "1")],
    )

    result = filter_seeds(
        parsed,
        FilterRule(must_contain="^番剧.*v2", use_regex=True, case_sensitive=True),
    )

    assert result.valid_seeds == []
    assert result.excluded_seeds[0].reason == "未命中包含规则：^番剧.*v2"


def test_must_not_contain_literal_excludes_with_reason() -> None:
    source = RssSource("组", "url", "static_fixture", "feed.xml")
    parsed = ParsedRss(
        source=source,
        seeds=[RssSeed("[Loli] 番剧 - 01 [v2]", "1")],
    )

    result = filter_seeds(parsed, FilterRule(must_not_contain="[v2]"))

    assert result.valid_seeds == []
    assert result.excluded_seeds[0].rule == "must_not_contain"
    assert result.excluded_seeds[0].reason == "命中排除规则：[v2]"
