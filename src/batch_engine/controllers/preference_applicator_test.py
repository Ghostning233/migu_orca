from __future__ import annotations

from batch_engine.controllers.preference_applicator import (
    apply_preferences_to_item,
    build_preference_config,
    build_preference_hits,
    build_review_metadata,
)
from batch_engine.models import (
    BATCH_ITEM_STATUS_FAILED,
    BATCH_ITEM_STATUS_PARSED,
    AnimeTitleParseResult,
)
from shared.models import (
    FilterDefaults,
    NamingPreference,
    SearchPreference,
    SubtitleGroupPreference,
    VersionedUserPreference,
)


def _parse_result(
    *,
    raw_title: str = "萌王S4",
    canonical: list[str] | None = None,
    season_hint: str | None = "S4",
) -> AnimeTitleParseResult:
    return AnimeTitleParseResult(
        raw_title=raw_title,
        canonical_title_candidates=canonical or ["关于我转生变成史莱姆这档事 第四季"],
        season_hint=season_hint,
        search_queries=["关于我转生变成史莱姆这档事 第四季"],
        confidence=0.9,
        needs_user_review=False,
        source="fake",
    )


def _preferences(
    *,
    preferred: list[str] | None = None,
    excluded: list[str] | None = None,
    fallback: str = "next_preferred",
    must_contain: str = "",
    must_not_contain: str = "",
    use_regex: bool = False,
    case_sensitive: bool = False,
    strategy: str = "official_title_season",
    template: str = "{title}",
) -> VersionedUserPreference:
    return VersionedUserPreference(
        version=1,
        subtitle_groups=SubtitleGroupPreference(
            preferred=preferred or [],
            excluded=excluded or [],
            fallback=fallback,
        ),
        filter_defaults=FilterDefaults(
            must_contain=must_contain,
            must_not_contain=must_not_contain,
            use_regex=use_regex,
            case_sensitive=case_sensitive,
        ),
        naming=NamingPreference(strategy=strategy, template=template),
        search=SearchPreference(reuse_explicit_corrections=True),
    )


class TestBuildPreferenceConfig:
    def test_build_preference_config_mirrors_saved_preference_contract(self) -> None:
        config = build_preference_config(
            _preferences(
                preferred=["Loli", "喵萌"],
                excluded=["示例组"],
                must_contain="1080p",
                use_regex=False,
                case_sensitive=True,
                strategy="official_title",
                template="[{title}]",
            )
        )

        assert config == {
            "subtitle_groups": {
                "preferred": ["Loli", "喵萌"],
                "excluded": ["示例组"],
                "fallback": "next_preferred",
            },
            "filter_rule": {
                "must_contain": "1080p",
                "must_not_contain": "",
                "use_regex": False,
                "case_sensitive": True,
            },
            "naming": {"strategy": "official_title", "template": "[{title}]"},
        }


class TestApplyPreferencesToItem:
    def test_default_preferences_generate_folder_name_from_canonical_title(self) -> None:
        applied = apply_preferences_to_item(
            "萌王S4",
            _parse_result(),
            _preferences(),
        )

        assert applied.expected_folder_name == "关于我转生变成史莱姆这档事 第四季"
        assert applied.warnings == []
        assert applied.subtitle_groups == {
            "preferred": [],
            "excluded": [],
            "fallback": "next_preferred",
        }
        assert applied.filter_rule == {
            "must_contain": "",
            "must_not_contain": "",
            "use_regex": False,
            "case_sensitive": False,
        }
        assert applied.naming == {
            "strategy": "official_title_season",
            "template": "{title}",
        }

    def test_subtitle_group_preferences_are_preserved_in_applied_config(self) -> None:
        applied = apply_preferences_to_item(
            "萌王S4",
            _parse_result(),
            _preferences(preferred=["Loli"], excluded=["示例组"]),
        )

        assert applied.subtitle_groups == {
            "preferred": ["Loli"],
            "excluded": ["示例组"],
            "fallback": "next_preferred",
        }

    def test_filter_defaults_preserve_regex_and_case_sensitive_semantics(self) -> None:
        applied = apply_preferences_to_item(
            "萌王S4",
            _parse_result(),
            _preferences(
                must_contain="1080p",
                must_not_contain="合集版",
                use_regex=True,
                case_sensitive=True,
            ),
        )

        assert applied.filter_rule == {
            "must_contain": "1080p",
            "must_not_contain": "合集版",
            "use_regex": True,
            "case_sensitive": True,
        }

    def test_official_title_season_appends_season_hint_when_title_lacks_season(self) -> None:
        parse = _parse_result(
            canonical=["转生史莱姆"],
            season_hint="S2",
        )
        applied = apply_preferences_to_item("萌王S2", parse, _preferences())

        assert applied.expected_folder_name == "转生史莱姆 第2季"

    def test_official_title_season_does_not_append_duplicate_season(self) -> None:
        applied = apply_preferences_to_item(
            "萌王S4",
            _parse_result(canonical=["关于我转生变成史莱姆这档事 第四季"]),
            _preferences(),
        )

        assert applied.expected_folder_name == "关于我转生变成史莱姆这档事 第四季"

    def test_official_title_strategy_ignores_season_hint(self) -> None:
        parse = _parse_result(
            canonical=["转生史莱姆"],
            season_hint="S2",
        )
        applied = apply_preferences_to_item(
            "萌王S2", parse, _preferences(strategy="official_title")
        )

        assert applied.expected_folder_name == "转生史莱姆"

    def test_raw_title_strategy_uses_raw_title(self) -> None:
        applied = apply_preferences_to_item(
            "萌王S4",
            _parse_result(),
            _preferences(strategy="raw_title"),
        )

        assert applied.expected_folder_name == "萌王S4"

    def test_template_substitution_applies_after_strategy_title(self) -> None:
        applied = apply_preferences_to_item(
            "萌王S4",
            _parse_result(canonical=["转生史莱姆"]),
            _preferences(strategy="official_title", template="[新番] {title}"),
        )

        assert applied.expected_folder_name == "[新番] 转生史莱姆"

    def test_folder_name_sanitizes_path_dangerous_characters(self) -> None:
        applied = apply_preferences_to_item(
            "萌王S4",
            _parse_result(canonical=["转生/史莱姆\\S4"]),
            _preferences(),
        )

        assert applied.expected_folder_name == "转生_史莱姆_S4"

    def test_failed_item_has_no_naming_default_and_keeps_config(self) -> None:
        applied = apply_preferences_to_item(
            "未知条目",
            None,
            _preferences(),
        )

        assert applied.expected_folder_name is None
        assert "该条目解析失败，命名默认值不可用" in applied.warnings
        assert applied.filter_rule["use_regex"] is False

    def test_fallback_none_without_preferred_warns_no_auto_subtitle_group(self) -> None:
        applied = apply_preferences_to_item(
            "萌王S4",
            _parse_result(),
            _preferences(fallback="none"),
        )

        assert "fallback 为 none 且未配置偏好字幕组，不会自动选择字幕组" in applied.warnings
        assert applied.expected_folder_name == "关于我转生变成史莱姆这档事 第四季"

    def test_to_dict_serializes_public_fields_without_warnings(self) -> None:
        applied = apply_preferences_to_item(
            "萌王S4",
            _parse_result(),
            _preferences(),
        )

        as_dict = applied.to_dict()
        assert as_dict == {
            "subtitle_groups": {
                "preferred": [],
                "excluded": [],
                "fallback": "next_preferred",
            },
            "filter_rule": {
                "must_contain": "",
                "must_not_contain": "",
                "use_regex": False,
                "case_sensitive": False,
            },
            "naming": {"strategy": "official_title_season", "template": "{title}"},
            "expected_folder_name": "关于我转生变成史莱姆这档事 第四季",
        }
        assert "warnings" not in as_dict


def _review_parse_result(
    *,
    raw_title: str = "某番S1",
    canonical: list[str] | None = None,
    search_queries: list[str] | None = None,
    confidence: float = 0.9,
    needs_user_review: bool = False,
) -> AnimeTitleParseResult:
    return AnimeTitleParseResult(
        raw_title=raw_title,
        canonical_title_candidates=canonical or ["某番 第一季"],
        season_hint="S1",
        search_queries=search_queries or ["某番 第一季"],
        confidence=confidence,
        needs_user_review=needs_user_review,
        source="fake",
    )


class TestBuildPreferenceHits:
    def test_hits_mark_all_fields_when_configured(self) -> None:
        applied = apply_preferences_to_item(
            "萌王S4",
            _parse_result(),
            _preferences(
                preferred=["Loli"],
                excluded=["示例组"],
                must_contain="1080p",
                strategy="official_title",
            ),
        )

        by_field = {hit["field"]: hit for hit in build_preference_hits(applied)}
        assert by_field["subtitle_groups"]["applied"] is True
        assert by_field["filter_rule"]["applied"] is True
        assert by_field["naming"]["applied"] is True
        assert "字幕组偏好已作为可编辑默认值" in by_field["subtitle_groups"]["summary"]
        assert "筛选默认值已作为可编辑默认规则" in by_field["filter_rule"]["summary"]

    def test_hits_mark_miss_when_unconfigured(self) -> None:
        applied = apply_preferences_to_item(
            "萌王S4",
            _parse_result(),
            _preferences(),
        )

        by_field = {hit["field"]: hit for hit in build_preference_hits(applied)}
        assert by_field["subtitle_groups"]["applied"] is False
        assert by_field["filter_rule"]["applied"] is False
        # The naming default is still applied from the canonical title.
        assert by_field["naming"]["applied"] is True

    def test_hits_mark_naming_miss_on_failed_item(self) -> None:
        applied = apply_preferences_to_item(
            "未知条目",
            None,
            _preferences(),
        )

        by_field = {hit["field"]: hit for hit in build_preference_hits(applied)}
        assert by_field["naming"]["applied"] is False
        assert "未应用命名默认值" in by_field["naming"]["summary"]

    def test_hits_are_public_rule_summaries_only(self) -> None:
        applied = apply_preferences_to_item(
            "萌王S4",
            _parse_result(),
            _preferences(preferred=["Loli"], must_contain="1080p"),
        )

        for hit in build_preference_hits(applied):
            assert set(hit) == {"field", "applied", "summary"}
            assert isinstance(hit["summary"], str)


class TestBuildReviewMetadata:
    def test_high_confidence_single_candidate_with_candidate_no_review(self) -> None:
        review = build_review_metadata(
            raw_title="某番S1",
            parse_result=_review_parse_result(),
            candidates=[{"bangumi_id": "1", "title": "某番 第一季"}],
            preference_warnings=[],
            status=BATCH_ITEM_STATUS_PARSED,
        )

        assert review.needs_user_review is False
        assert review.review_hints == []

    def test_low_confidence_requires_review(self) -> None:
        review = build_review_metadata(
            raw_title="杖剑谭S2",
            parse_result=_review_parse_result(confidence=0.62),
            candidates=[{"bangumi_id": "2", "title": "杖与剑的魔剑谭 第二季"}],
            preference_warnings=[],
            status=BATCH_ITEM_STATUS_PARSED,
        )

        assert review.needs_user_review is True
        assert any("置信度较低" in hint for hint in review.review_hints)

    def test_multi_candidate_requires_review(self) -> None:
        review = build_review_metadata(
            raw_title="萌王S4",
            parse_result=_review_parse_result(
                canonical=["A 第四季", "B 第四季"],
                confidence=0.9,
            ),
            candidates=[{"bangumi_id": "1", "title": "A 第四季"}],
            preference_warnings=[],
            status=BATCH_ITEM_STATUS_PARSED,
        )

        assert review.needs_user_review is True
        assert any("存在多个候选名称" in hint for hint in review.review_hints)

    def test_no_candidate_requires_review(self) -> None:
        review = build_review_metadata(
            raw_title="某番S1",
            parse_result=_review_parse_result(),
            candidates=[],
            preference_warnings=[],
            status=BATCH_ITEM_STATUS_PARSED,
        )

        assert review.needs_user_review is True
        assert any("未找到候选合集" in hint for hint in review.review_hints)

    def test_preference_conflict_requires_review(self) -> None:
        applied = apply_preferences_to_item(
            "萌王S4",
            _parse_result(),
            _preferences(fallback="none"),
        )

        review = build_review_metadata(
            raw_title="萌王S4",
            parse_result=_review_parse_result(),
            candidates=[{"bangumi_id": "1", "title": "A 第四季"}],
            preference_warnings=list(applied.warnings),
            status=BATCH_ITEM_STATUS_PARSED,
        )

        assert review.needs_user_review is True
        assert any("偏好字幕组存在冲突" in hint for hint in review.review_hints)

    def test_search_fallback_requires_review(self) -> None:
        review = build_review_metadata(
            raw_title="神秘作品",
            parse_result=_review_parse_result(
                raw_title="神秘作品",
                search_queries=["神秘作品"],  # fell back to the raw title
            ),
            candidates=[{"bangumi_id": "3", "title": "神秘作品"}],
            preference_warnings=[],
            status=BATCH_ITEM_STATUS_PARSED,
        )

        assert review.needs_user_review is True
        assert any("搜索词已回退为原始输入" in hint for hint in review.review_hints)

    def test_search_failed_requires_review(self) -> None:
        review = build_review_metadata(
            raw_title="某番S1",
            parse_result=_review_parse_result(),
            candidates=[],
            preference_warnings=[],
            search_failed=True,
            status=BATCH_ITEM_STATUS_FAILED,
        )

        assert review.needs_user_review is True
        assert any("候选搜索失败" in hint for hint in review.review_hints)

    def test_parse_failed_requires_review(self) -> None:
        review = build_review_metadata(
            raw_title="坏条目",
            parse_result=None,
            candidates=[],
            preference_warnings=[],
            status=BATCH_ITEM_STATUS_FAILED,
        )

        assert review.needs_user_review is True
        assert any("解析失败" in hint for hint in review.review_hints)

    def test_provider_marked_review_adds_hint(self) -> None:
        review = build_review_metadata(
            raw_title="萌王S4",
            parse_result=_review_parse_result(needs_user_review=True),
            candidates=[{"bangumi_id": "1", "title": "A 第四季"}],
            preference_warnings=[],
            status=BATCH_ITEM_STATUS_PARSED,
        )

        assert review.needs_user_review is True
        assert any("人工核对" in hint for hint in review.review_hints)

    def test_review_hints_are_deduplicated(self) -> None:
        review = build_review_metadata(
            raw_title="神秘作品",
            parse_result=_review_parse_result(
                raw_title="神秘作品",
                search_queries=["神秘作品"],
                confidence=0.4,
            ),
            candidates=[{"bangumi_id": "3", "title": "神秘作品"}],
            preference_warnings=[],
            status=BATCH_ITEM_STATUS_PARSED,
        )

        assert len(review.review_hints) == len(set(review.review_hints))
        # search fallback + low confidence, each exactly once
        assert len(review.review_hints) == 2
