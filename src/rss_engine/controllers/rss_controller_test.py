from __future__ import annotations

from pathlib import Path

import pytest

from rss_engine.controllers.rss_controller import filter_seeds, parse_rss
from shared.errors import Stage1Error
from shared.models import FilterRule, ParsedRss, RssSeed, RssSource


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


def test_invalid_regex_is_config_error() -> None:
    source = RssSource("组", "url", "static_fixture", "feed.xml")
    parsed = ParsedRss(source=source, seeds=[RssSeed("条目", "1")])

    with pytest.raises(Stage1Error) as error:
        filter_seeds(parsed, FilterRule(must_contain="["))

    assert error.value.error_type == "config_error"
