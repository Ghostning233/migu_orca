from __future__ import annotations

from plan_engine.controllers.data_sources import (
    DirectEntryResolution,
    StaticFixtureDataSource,
)
from plan_engine.controllers.plan_generation import build_plan
from shared.config import load_user_preference
from shared.errors import Stage1Error
from shared.models import (
    BangumiCandidate,
    EntryRequest,
    MatchedBangumi,
    ParsedRss,
    RssSeed,
    RssSource,
)

_LOLI_SOURCE = RssSource(
    subtitle_group="Loli",
    rss_url="https://example.invalid/rss/loli.xml",
    source_type="static_fixture",
    fixture_path="loli.xml",
)
_MOE_SOURCE = RssSource(
    subtitle_group="喵萌",
    rss_url="https://example.invalid/rss/moe.xml",
    source_type="static_fixture",
    fixture_path="moe.xml",
)


class RecordingDataSource:
    """Fixture data source that records the calls `build_plan` makes.

    Uses the real user preference file so filtering/subtitle selection behaviour
    matches the production path without touching MiKan.
    """

    def __init__(
        self,
        *,
        title: str = "芙莉莲",
        mikan_url: str = "https://example.invalid/bangumi/1",
        rss_sources: list[RssSource] | None = None,
        seed_titles: tuple[str, ...] = ("芙莉莲 - 01",),
        parse_error_groups: tuple[str, ...] = (),
        direct: DirectEntryResolution | None = None,
    ) -> None:
        self.calls: list[str] = []
        self._candidate = BangumiCandidate(
            bangumi_id="1",
            title=title,
            aliases=[],
            mikan_url=mikan_url,
            rss_sources=list(rss_sources if rss_sources is not None else [_LOLI_SOURCE]),
        )
        self._seed_titles = seed_titles
        self._parse_error_groups = set(parse_error_groups)
        self._direct = direct

    def load_preference(self):
        self.calls.append("load_preference")
        return load_user_preference()

    def list_candidates(self, raw_title: str) -> list[BangumiCandidate]:
        self.calls.append("list_candidates")
        return [self._candidate]

    def resolve_direct_entry(self, direct_entry: str) -> DirectEntryResolution:
        self.calls.append("resolve_direct_entry")
        if self._direct is None:
            raise Stage1Error(
                "invalid_input",
                "fixture 不支持直连入口",
                "mikan_direct_entry",
                {"field": "mikan_bangumi"},
            )
        return self._direct

    def list_rss_sources(
        self,
        matched: MatchedBangumi,
        candidate: BangumiCandidate,
    ) -> list[RssSource]:
        self.calls.append("list_rss_sources")
        return list(candidate.rss_sources)

    def parse_rss(self, source: RssSource) -> ParsedRss:
        self.calls.append(f"parse_rss:{source.subtitle_group}")
        if source.subtitle_group in self._parse_error_groups:
            raise Stage1Error(
                "rss_parse_failed",
                "fixture RSS 无法解析",
                "parse_rss",
                {"reason": "broken fixture"},
            )
        return ParsedRss(
            source=source,
            seeds=[
                RssSeed(title=title, link=f"https://example.invalid/{index}")
                for index, title in enumerate(self._seed_titles)
            ],
        )


def test_build_plan_uses_only_the_injected_data_source() -> None:
    source = RecordingDataSource()

    result = build_plan(EntryRequest(raw_title="芙莉莲"), data_source=source)

    assert result["success"] is True
    assert result["error"] is None
    assert source.calls == [
        "load_preference",
        "list_candidates",
        "list_rss_sources",
        "parse_rss:Loli",
    ]
    request = result["request"]
    assert request["status"] == "PENDING_CONFIRM"
    assert request["input"] == {"raw_title": "芙莉莲"}
    assert request["source_info"]["matched_bangumi"]["title"] == "芙莉莲"
    assert request["confirmable_config"]["selected_subtitle_group"] == "Loli"
    assert request["confirmable_config"]["expected_folder_name"] == "芙莉莲"
    assert request["ab_submit_result"] is None


def test_build_plan_accepts_the_static_fixture_adapter() -> None:
    result = build_plan(
        EntryRequest(raw_title="咒术回战第三季"),
        data_source=StaticFixtureDataSource(),
    )

    assert result["success"] is True
    request = result["request"]
    assert request["source_info"]["matched_bangumi"]["title"] == "咒术回战 第三季"
    assert request["confirmable_config"]["selected_subtitle_group"] == "Loli"


def test_build_plan_direct_entry_comes_from_the_data_source() -> None:
    direct = DirectEntryResolution(
        matched=MatchedBangumi(
            title="直连番剧",
            aliases=[],
            mikan_url="https://example.invalid/bangumi/9",
            match_score=1.0,
            poster_url="https://example.invalid/poster.jpg",
        ),
        rss_sources=[_LOLI_SOURCE],
    )
    source = RecordingDataSource(direct=direct)

    result = build_plan(
        EntryRequest(raw_title=""),
        data_source=source,
        mikan_bangumi="https://example.invalid/Home/Bangumi/9",
    )

    assert result["success"] is True
    assert source.calls == ["load_preference", "resolve_direct_entry", "parse_rss:Loli"]
    matched = result["request"]["source_info"]["matched_bangumi"]
    assert matched["title"] == "直连番剧"
    assert matched["poster_url"] == "https://example.invalid/poster.jpg"
    assert matched["match_score"] == 1.0


def test_build_plan_rejects_blank_direct_entry_before_using_the_source() -> None:
    source = RecordingDataSource()

    result = build_plan(
        EntryRequest(raw_title="芙莉莲"),
        data_source=source,
        mikan_bangumi="   ",
    )

    assert result["success"] is False
    assert result["error"] == {
        "error_type": "invalid_input",
        "error_message": "MiKan bangumi 直连入口必须是数字 ID 或 Home/Bangumi URL",
        "failed_step": "mikan_direct_entry",
        "details": {"field": "mikan_bangumi"},
    }
    assert source.calls == []


def test_build_plan_rejects_blank_title_before_using_the_source() -> None:
    source = RecordingDataSource()

    result = build_plan(EntryRequest(raw_title="   "), data_source=source)

    assert result["success"] is False
    assert result["error"]["failed_step"] == "validate_input"
    assert source.calls == []


def test_build_plan_fails_when_every_rss_source_fails() -> None:
    source = RecordingDataSource(parse_error_groups=("Loli",))

    result = build_plan(EntryRequest(raw_title="芙莉莲"), data_source=source)

    assert result["success"] is False
    assert result["request"] is None
    assert result["error"]["error_type"] == "rss_parse_failed"
    assert result["error"]["error_message"] == "所有候选 RSS 均解析失败"
    assert result["error"]["failed_step"] == "parse_rss"


def test_build_plan_keeps_going_when_one_rss_source_fails() -> None:
    source = RecordingDataSource(
        rss_sources=[_MOE_SOURCE, _LOLI_SOURCE],
        parse_error_groups=("喵萌",),
    )

    result = build_plan(EntryRequest(raw_title="芙莉莲"), data_source=source)

    assert result["success"] is True
    assert source.calls == [
        "load_preference",
        "list_candidates",
        "list_rss_sources",
        "parse_rss:喵萌",
        "parse_rss:Loli",
    ]
    request = result["request"]
    assert request["confirmable_config"]["selected_subtitle_group"] == "Loli"
    assert any(
        "字幕组 喵萌 的 RSS 解析失败" in warning
        for warning in request["confirmable_config"]["warnings"]
    )


def test_build_plan_wraps_unexpected_data_source_failures() -> None:
    class _BoomSource(RecordingDataSource):
        def list_candidates(self, raw_title: str) -> list[BangumiCandidate]:
            raise RuntimeError("unexpected boom")

    result = build_plan(EntryRequest(raw_title="芙莉莲"), data_source=_BoomSource())

    assert result["success"] is False
    assert result["request"] is None
    assert result["error"]["error_type"] == "unexpected_error"
    assert result["error"]["error_message"] == "订阅方案生成发生未预期错误"
    assert result["error"]["failed_step"] == "generate_request"
    assert result["error"]["details"] == {"reason": "unexpected boom"}
