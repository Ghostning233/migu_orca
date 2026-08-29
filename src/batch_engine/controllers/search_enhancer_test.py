from __future__ import annotations

from batch_engine.controllers.search_enhancer import enhance_search_queries
from shared.models import BangumiCorrectionMetadata, TitleCorrection


def _correction() -> TitleCorrection:
    return TitleCorrection(
        raw_title="芙莉莲",
        canonical_title="葬送的芙莉莲",
        season_hint="S2",
        bangumi_metadata=BangumiCorrectionMetadata(
            bangumi_id="12345",
            title="葬送的芙莉莲",
        ),
        query_correction="葬送的芙莉莲 第二季",
    )


def _queries(entries: list[dict[str, str]]) -> list[str]:
    return [entry["query"] for entry in entries]


class TestNoCorrection:
    def test_empty_corrections_returns_empty(self) -> None:
        assert enhance_search_queries("芙莉莲", ["芙莉莲"], []) == []

    def test_no_matching_raw_title_returns_empty(self) -> None:
        assert (
            enhance_search_queries(
                "推子", ["推子"], [_correction()]
            )
            == []
        )

    def test_empty_raw_title_returns_empty(self) -> None:
        assert enhance_search_queries("", ["芙莉莲"], [_correction()]) == []


class TestCorrectionMatch:
    def test_exact_raw_title_reuses_saved_correction(self) -> None:
        entries = enhance_search_queries("芙莉莲", ["芙莉莲"], [_correction()])

        assert entries
        for entry in entries:
            assert entry["original_query"] == "芙莉莲"
            assert entry["source"] in ("correction:query", "correction:canonical")

    def test_case_insensitive_raw_title_matches(self) -> None:
        correction = TitleCorrection(
            raw_title="Frieren",
            canonical_title="Frieren: Beyond Journey's End",
            query_correction="Frieren",
        )
        entries = enhance_search_queries("frieren", ["frieren"], [correction])

        assert entries
        assert entries[0]["query"] == "Frieren"
        assert entries[0]["source"] == "correction:query"

    def test_raw_title_matches_after_strip(self) -> None:
        correction = _correction()
        entries = enhance_search_queries("  芙莉莲  ", ["芙莉莲"], [correction])

        assert entries
        assert entries[0]["original_query"] == "芙莉莲"


class TestQueryCorrection:
    def test_query_correction_is_expanded_with_season_variants(self) -> None:
        entries = enhance_search_queries("芙莉莲", ["芙莉莲"], [_correction()])
        query_source = [
            entry for entry in entries if entry["source"] == "correction:query"
        ]

        assert _queries(query_source) == [
            "葬送的芙莉莲 第二季",
            "葬送的芙莉莲 第2季",
            "葬送的芙莉莲 S2",
            "葬送的芙莉莲 Season 2",
        ]

    def test_chinese_numeral_season_hint_expands_forms(self) -> None:
        correction = TitleCorrection(
            raw_title="芙莉莲",
            canonical_title="葬送的芙莉莲",
            season_hint="第四季",
            query_correction="葬送的芙莉莲 第四季",
        )
        entries = enhance_search_queries("芙莉莲", ["芙莉莲"], [correction])
        query_source = [
            entry for entry in entries if entry["source"] == "correction:query"
        ]

        assert _queries(query_source) == [
            "葬送的芙莉莲 第四季",
            "葬送的芙莉莲 第4季",
            "葬送的芙莉莲 S4",
            "葬送的芙莉莲 Season 4",
        ]

    def test_numeric_season_hint_expands_forms(self) -> None:
        correction = TitleCorrection(
            raw_title="芙莉莲",
            canonical_title="葬送的芙莉莲",
            season_hint="第2季",
            query_correction="葬送的芙莉莲 第二季",
        )
        entries = enhance_search_queries("芙莉莲", ["芙莉莲"], [correction])

        assert any(entry["query"] == "葬送的芙莉莲 第二季" for entry in entries)
        assert any(entry["query"] == "葬送的芙莉莲 第2季" for entry in entries)
        assert any(entry["query"] == "葬送的芙莉莲 S2" for entry in entries)

    def test_season_marker_in_query_is_replaced_not_duplicated(self) -> None:
        correction = TitleCorrection(
            raw_title="芙莉莲",
            canonical_title="葬送的芙莉莲",
            season_hint="S3",
            query_correction="葬送的芙莉莲 第二季",
        )
        entries = enhance_search_queries("芙莉莲", ["芙莉莲"], [correction])

        # The existing 第二季 marker is replaced by 第3季, never duplicated.
        assert any(entry["query"] == "葬送的芙莉莲 第3季" for entry in entries)
        assert not any("第二季 第3季" in entry["query"] for entry in entries)

    def test_query_correction_without_season_hint_stays_unchanged(self) -> None:
        correction = TitleCorrection(
            raw_title="推子",
            canonical_title="我推的孩子",
            query_correction="【我推的孩子】",
        )
        entries = enhance_search_queries("推子", ["推子"], [correction])

        assert entries[0] == {
            "query": "【我推的孩子】",
            "original_query": "推子",
            "source": "correction:query",
        }
        assert "我推的孩子" in _queries(entries)


class TestCanonicalTitle:
    def test_canonical_title_contributes_enhanced_entries(self) -> None:
        correction = TitleCorrection(
            raw_title="芙莉莲",
            canonical_title="葬送的芙莉莲",
            season_hint="S2",
        )
        entries = enhance_search_queries("芙莉莲", ["芙莉莲"], [correction])

        canonical_source = [
            entry for entry in entries if entry["source"] == "correction:canonical"
        ]
        assert _queries(canonical_source) == [
            "葬送的芙莉莲",
            "葬送的芙莉莲 第2季",
            "葬送的芙莉莲 S2",
            "葬送的芙莉莲 Season 2",
            "葬送的芙莉莲 第二季",
        ]

    def test_canonical_title_supports_romanized_variants(self) -> None:
        correction = TitleCorrection(
            raw_title="frieren",
            canonical_title="Frieren: Beyond Journey's End",
            query_correction="Sousou no Frieren",
        )
        entries = enhance_search_queries("frieren", ["frieren"], [correction])

        assert _queries(entries) == [
            "Sousou no Frieren",
            "Frieren: Beyond Journey's End",
        ]
        assert [entry["source"] for entry in entries] == [
            "correction:query",
            "correction:canonical",
        ]


class TestDeduplication:
    def test_overlapping_variants_are_deduplicated(self) -> None:
        entries = enhance_search_queries("芙莉莲", ["芙莉莲"], [_correction()])

        queries = _queries(entries)
        assert len(queries) == len(set(queries))
        assert queries == [
            "葬送的芙莉莲 第二季",
            "葬送的芙莉莲 第2季",
            "葬送的芙莉莲 S2",
            "葬送的芙莉莲 Season 2",
            "葬送的芙莉莲",
        ]

    def test_duplicate_corrections_use_first_match(self) -> None:
        first = TitleCorrection(
            raw_title="芙莉莲",
            canonical_title="葬送的芙莉莲",
            query_correction="葬送的芙莉莲 第二季",
        )
        second = TitleCorrection(
            raw_title="芙莉莲",
            canonical_title="葬送的芙莉莲 修正",
            query_correction="葬送的芙莉莲 第二季 修正",
        )
        entries = enhance_search_queries("芙莉莲", ["芙莉莲"], [first, second])

        assert entries[0]["query"] == "葬送的芙莉莲 第二季"
        assert entries[0]["source"] == "correction:query"

    def test_empty_query_strings_are_filtered(self) -> None:
        correction = TitleCorrection(
            raw_title="推子",
            canonical_title="我推的孩子",
            query_correction="",
        )
        entries = enhance_search_queries("推子", ["推子"], [correction])

        assert _queries(entries) == ["我推的孩子"]


class TestOriginalQueryFallback:
    def test_missing_search_queries_use_raw_title_as_original(self) -> None:
        entries = enhance_search_queries("芙莉莲", [], [_correction()])

        assert entries
        for entry in entries:
            assert entry["original_query"] == "芙莉莲"

    def test_blank_search_queries_use_raw_title_as_original(self) -> None:
        entries = enhance_search_queries("芙莉莲", ["  "], [_correction()])

        for entry in entries:
            assert entry["original_query"] == "芙莉莲"
