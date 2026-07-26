from __future__ import annotations

import pytest

from catalog_engine.controllers.catalog_controller import match_bangumi
from shared.errors import Stage1Error
from shared.models import BangumiCandidate


def _candidate(title: str, aliases: list[str] | None = None) -> BangumiCandidate:
    return BangumiCandidate(
        bangumi_id=title,
        title=title,
        aliases=aliases or [],
        mikan_url=f"https://example.invalid/{title}",
        rss_sources=[],
    )


def test_exact_alias_wins() -> None:
    matched, selected = match_bangumi(
        "  FRIEREN ",
        [_candidate("葬送的芙莉莲", ["Frieren"]), _candidate("其他番剧")],
    )

    assert selected.title == "葬送的芙莉莲"
    assert matched.match_score == 1.0


def test_low_score_fails() -> None:
    with pytest.raises(Stage1Error) as error:
        match_bangumi("完全不同", [_candidate("葬送的芙莉莲")])

    assert error.value.error_type == "bangumi_match_failed"


def test_tied_highest_score_is_ambiguous() -> None:
    with pytest.raises(Stage1Error) as error:
        match_bangumi("测试", [_candidate("测试甲"), _candidate("测试乙")])

    assert error.value.error_type == "ambiguous_bangumi_match"
