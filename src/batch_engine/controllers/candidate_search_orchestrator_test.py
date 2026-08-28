from __future__ import annotations

from batch_engine.controllers.anime_title_parser import RuleAnimeTitleParsingProvider, parse_anime_title
from batch_engine.controllers.candidate_search_orchestrator import search_parsed_candidates
from shared.errors import Stage1Error
from shared.models import TitleCorrection


def test_stops_after_first_priority_with_candidates_and_stably_deduplicates() -> None:
    parsed = parse_anime_title("萌王S4")
    calls: list[str] = []

    def search(query: str) -> list[dict[str, str]]:
        calls.append(query)
        return [{"id": "one"}, {"id": "one"}, {"id": "two"}]

    result = search_parsed_candidates(parsed, search, lambda candidate: candidate["id"])

    assert result.status == "FOUND"
    assert calls == [parsed.query_plan[0].query]
    assert [candidate["id"] for candidate in result.candidates] == ["one", "two"]
    assert result.attempted_queries == tuple(calls)


def test_search_error_does_not_block_later_fallback() -> None:
    parsed = parse_anime_title("萌王S4")
    calls: list[str] = []

    def search(query: str) -> list[str]:
        calls.append(query)
        if len(calls) == 1:
            raise Stage1Error("mikan_timeout", "超时", "mikan_search")
        return ["candidate"]

    result = search_parsed_candidates(parsed, search, lambda candidate: candidate)

    assert result.status == "FOUND"
    assert calls == list(parsed.search_queries[:2])
    assert result.candidates == ("candidate",)


def test_all_failed_and_all_empty_are_distinct() -> None:
    parsed = parse_anime_title("未知标题")

    failed = search_parsed_candidates(
        parsed,
        lambda query: (_ for _ in ()).throw(Stage1Error("mikan_timeout", "超时", "mikan_search")),
        lambda candidate: candidate,
    )
    empty = search_parsed_candidates(parsed, lambda query: [], lambda candidate: candidate)

    assert failed.status == "FAILED"
    assert failed.error is not None
    assert empty.status == "EMPTY"
    assert empty.error is None


def test_correction_season_hint_display_plan_equals_actual_transport_order() -> None:
    parsed = parse_anime_title(
        "frieren",
        RuleAnimeTitleParsingProvider(
            corrections=[
                TitleCorrection(
                    raw_title="frieren",
                    canonical_title="Frieren: Beyond Journey's End",
                    query_correction="Sousou no Frieren",
                    season_hint="S2",
                )
            ]
        ),
    )
    calls: list[str] = []

    result = search_parsed_candidates(
        parsed,
        lambda query: calls.append(query) or [],
        lambda candidate: candidate,
    )

    assert result.status == "EMPTY"
    assert calls == list(parsed.search_queries)
    assert result.attempted_queries == tuple(calls)
    assert "Sousou no Frieren 第二季" in calls
