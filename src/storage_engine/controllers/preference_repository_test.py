from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from shared.errors import Stage1Error
from shared.models import (
    FilterDefaults,
    NamingPreference,
    SearchPreference,
    SubtitleGroupPreference,
    VersionedUserPreference,
)
from shared.sensitive_values import contains_sensitive_value
from storage_engine.controllers.preference_repository import (
    MAX_FILTER_RULE_LENGTH,
    MAX_NAMING_TEMPLATE_LENGTH,
    MAX_SUBTITLE_GROUP_NAME_LENGTH,
    PREFERENCES_FILENAME,
    build_preferences_from_api,
    default_user_preferences,
    load_user_preferences,
    save_user_preferences,
    serialize_preferences,
    validate_preferences,
)
from storage_engine.controllers.storage_config import load_storage_config


def _config(tmp_path: Path):
    return load_storage_config(tmp_path / "migu-state")


def _full_preferences() -> VersionedUserPreference:
    return VersionedUserPreference(
        version=1,
        subtitle_groups=SubtitleGroupPreference(
            preferred=["Loli", "喵萌"],
            excluded=["示例组"],
            fallback="next_preferred",
        ),
        filter_defaults=FilterDefaults(
            must_contain="1080p",
            must_not_contain="合集版",
            use_regex=False,
            case_sensitive=False,
        ),
        naming=NamingPreference(strategy="official_title_season", template="{title}"),
        search=SearchPreference(reuse_explicit_corrections=True),
    )


def _written_body(config) -> dict:
    return json.loads(
        (config.preferences_dir / PREFERENCES_FILENAME).read_text(encoding="utf-8")
    )


class TestDefaultPreferences:
    def test_default_preferences_are_safe_and_empty(self) -> None:
        prefs = default_user_preferences()

        assert prefs.version == 1
        assert prefs.subtitle_groups.preferred == []
        assert prefs.subtitle_groups.excluded == []
        assert prefs.subtitle_groups.fallback == "next_preferred"
        assert prefs.filter_defaults.must_contain == ""
        assert prefs.filter_defaults.must_not_contain == ""
        assert prefs.filter_defaults.use_regex is False
        assert prefs.filter_defaults.case_sensitive is False
        assert prefs.naming.strategy == "official_title_season"
        assert prefs.naming.template == "{title}"
        assert prefs.search.reuse_explicit_corrections is True

    def test_default_preferences_are_fresh_instances(self) -> None:
        first = default_user_preferences()
        second = default_user_preferences()

        assert first is not second
        first.subtitle_groups.preferred.append("突变")
        assert second.subtitle_groups.preferred == []


class TestLoadMissingFile:
    def test_load_missing_preferences_returns_defaults(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        prefs = load_user_preferences(config)

        assert prefs == default_user_preferences()
        assert not config.preferences_dir.exists()


class TestSaveAndLoad:
    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        prefs = _full_preferences()

        saved = save_user_preferences(config, prefs)
        loaded = load_user_preferences(config)

        assert saved == {
            "storage": "local_json",
            "directory": "preferences",
            "filename": PREFERENCES_FILENAME,
            "version": 1,
        }
        assert loaded == prefs
        assert loaded is not prefs

    def test_save_writes_only_non_sensitive_fields(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        save_user_preferences(config, _full_preferences())

        body = _written_body(config)
        assert body["version"] == 1
        assert body["subtitle_groups"] == {
            "preferred": ["Loli", "喵萌"],
            "excluded": ["示例组"],
            "fallback": "next_preferred",
        }
        assert body["filter_defaults"] == {
            "must_contain": "1080p",
            "must_not_contain": "合集版",
            "use_regex": False,
            "case_sensitive": False,
        }
        assert body["naming"] == {"strategy": "official_title_season", "template": "{title}"}
        assert body["search"] == {"reuse_explicit_corrections": True}
        assert not body.get("endpoint")
        assert not body.get("token")

    def test_save_uses_temp_file_and_leaves_no_tmp(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        save_user_preferences(config, _full_preferences())

        assert not list(config.preferences_dir.glob("*.tmp"))
        final = config.preferences_dir / PREFERENCES_FILENAME
        assert final.exists()
        assert _written_body(config)["version"] == 1

    def test_save_overwrites_existing_preferences(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        save_user_preferences(config, _full_preferences())
        updated = VersionedUserPreference(
            subtitle_groups=SubtitleGroupPreference(preferred=["喵萌"])
        )
        save_user_preferences(config, updated)

        loaded = load_user_preferences(config)
        assert loaded.subtitle_groups.preferred == ["喵萌"]
        assert loaded.filter_defaults.must_contain == ""

    def test_save_and_load_preserves_empty_lists(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        save_user_preferences(config, default_user_preferences())

        loaded = load_user_preferences(config)
        assert loaded.subtitle_groups.preferred == []
        assert loaded.subtitle_groups.excluded == []


class TestOldVersionCompatibility:
    def test_load_missing_version_treats_as_v1(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        (config.preferences_dir).mkdir(parents=True, exist_ok=True)
        (config.preferences_dir / PREFERENCES_FILENAME).write_text(
            json.dumps(
                {
                    "subtitle_groups": {"preferred": ["Loli"]},
                    "filter_defaults": {"must_contain": "1080p"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        loaded = load_user_preferences(config)
        assert loaded.version == 1
        assert loaded.subtitle_groups.preferred == ["Loli"]
        assert loaded.filter_defaults.must_contain == "1080p"

    def test_load_legacy_m08_shape_with_filter_rule_and_priority(
        self, tmp_path: Path
    ) -> None:
        config = _config(tmp_path)
        (config.preferences_dir).mkdir(parents=True, exist_ok=True)
        (config.preferences_dir / PREFERENCES_FILENAME).write_text(
            json.dumps(
                {
                    "filter_rule": {
                        "must_contain": "V2",
                        "must_not_contain": "合集",
                        "use_regex": True,
                        "case_sensitive": True,
                    },
                    "subtitle_group_priority": ["喵萌", "Loli"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        loaded = load_user_preferences(config)
        assert loaded.subtitle_groups.preferred == ["喵萌", "Loli"]
        assert loaded.subtitle_groups.excluded == []
        assert loaded.filter_defaults.must_contain == "V2"
        assert loaded.filter_defaults.must_not_contain == "合集"
        assert loaded.filter_defaults.use_regex is True
        assert loaded.filter_defaults.case_sensitive is True

    def test_load_missing_sections_fills_defaults(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        (config.preferences_dir).mkdir(parents=True, exist_ok=True)
        (config.preferences_dir / PREFERENCES_FILENAME).write_text(
            '{"version": 1, "subtitle_groups": {"preferred": ["Loli"]}}',
            encoding="utf-8",
        )

        loaded = load_user_preferences(config)
        assert loaded.subtitle_groups.preferred == ["Loli"]
        assert loaded.subtitle_groups.excluded == []
        assert loaded.subtitle_groups.fallback == "next_preferred"
        assert loaded.filter_defaults.must_contain == ""
        assert loaded.naming.strategy == "official_title_season"
        assert loaded.search.reuse_explicit_corrections is True


class TestInvalidStoredFile:
    def test_load_damaged_json_returns_stable_error(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        (config.preferences_dir).mkdir(parents=True, exist_ok=True)
        (config.preferences_dir / PREFERENCES_FILENAME).write_text(
            "not json", encoding="utf-8"
        )

        with pytest.raises(Stage1Error) as error:
            load_user_preferences(config)

        assert error.value.error_type == "storage_json_error"
        assert error.value.failed_step == "load_user_preferences"
        assert "读取用户偏好 JSON 失败" in error.value.message

    def test_load_non_object_json_returns_stable_error(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        (config.preferences_dir).mkdir(parents=True, exist_ok=True)
        (config.preferences_dir / PREFERENCES_FILENAME).write_text(
            '["not", "an", "object"]', encoding="utf-8"
        )

        with pytest.raises(Stage1Error) as error:
            load_user_preferences(config)

        assert error.value.error_type == "storage_json_error"
        assert "必须是对象" in error.value.message

    def test_load_bad_priority_type_returns_stable_error(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        (config.preferences_dir).mkdir(parents=True, exist_ok=True)
        (config.preferences_dir / PREFERENCES_FILENAME).write_text(
            '{"subtitle_groups": {"preferred": "Loli"}}', encoding="utf-8"
        )

        with pytest.raises(Stage1Error) as error:
            load_user_preferences(config)

        assert error.value.error_type == "storage_json_error"
        assert "字符串数组" in error.value.message

    def test_load_sensitive_stored_value_rejected(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        (config.preferences_dir).mkdir(parents=True, exist_ok=True)
        (config.preferences_dir / PREFERENCES_FILENAME).write_text(
            json.dumps(
                {"subtitle_groups": {"preferred": ["https://mikan.example/api"]}}
            ),
            encoding="utf-8",
        )

        with pytest.raises(Stage1Error) as error:
            load_user_preferences(config)

        assert error.value.error_type == "validation_error"
        assert "敏感内容" in error.value.message
        assert error.value.failed_step == "load_user_preferences"


class TestValidation:
    def test_validate_accepts_full_legal_preferences(self) -> None:
        validate_preferences(_full_preferences())

    def test_validate_accepts_naming_template_with_relative_paths(self) -> None:
        """Regression: naming templates legitimately contain relative path
        separators (subdirectory layout) and must not be rejected as sensitive."""
        for template in (
            "TV/{title}/Season {season}",
            "{title}/{season}",
            "动画/{title}",
        ):
            prefs = _full_preferences()
            prefs = replace(
                prefs,
                naming=NamingPreference(
                    strategy=prefs.naming.strategy,
                    template=template,
                ),
            )
            validate_preferences(prefs)

    def test_validate_rejects_absolute_path_in_naming_template(self) -> None:
        """Even with relative paths allowed, a true absolute path in the naming
        template is still rejected."""
        for template in (
            "/home/ghostning/动画/{title}",
            "C:\\Users\\admin\\{title}",
            "file:///tmp/{title}",
        ):
            prefs = _full_preferences()
            prefs = replace(
                prefs,
                naming=NamingPreference(
                    strategy=prefs.naming.strategy,
                    template=template,
                ),
            )
            with pytest.raises(Stage1Error) as error:
                validate_preferences(prefs)
            assert error.value.error_type == "validation_error"
            assert error.value.details == {"field": "naming.template"}

    def test_validate_rejects_invalid_fallback_enum(self) -> None:
        prefs = VersionedUserPreference(
            subtitle_groups=SubtitleGroupPreference(fallback="auto")
        )

        with pytest.raises(Stage1Error) as error:
            validate_preferences(prefs)

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "subtitle_groups.fallback"}
        assert "枚举" in error.value.message

    def test_validate_rejects_invalid_naming_strategy(self) -> None:
        prefs = VersionedUserPreference(
            naming=NamingPreference(strategy="random_strategy")
        )

        with pytest.raises(Stage1Error) as error:
            validate_preferences(prefs)

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "naming.strategy"}

    def test_validate_rejects_non_string_in_filter_defaults(self) -> None:
        prefs = VersionedUserPreference(
            filter_defaults=FilterDefaults(must_contain=123)
        )

        with pytest.raises(Stage1Error) as error:
            validate_preferences(prefs)

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "filter_defaults.must_contain"}

    def test_validate_rejects_non_bool_use_regex(self) -> None:
        prefs = VersionedUserPreference(
            filter_defaults=FilterDefaults(use_regex="yes")
        )

        with pytest.raises(Stage1Error) as error:
            validate_preferences(prefs)

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "filter_defaults.use_regex"}

    def test_validate_rejects_non_string_list_preferred(self) -> None:
        prefs = VersionedUserPreference(
            subtitle_groups=SubtitleGroupPreference(preferred=[123])
        )

        with pytest.raises(Stage1Error) as error:
            validate_preferences(prefs)

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "subtitle_groups.preferred"}

    def test_validate_rejects_bad_version(self) -> None:
        prefs = VersionedUserPreference(version=0)

        with pytest.raises(Stage1Error) as error:
            validate_preferences(prefs)

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "version"}


class TestSaveRejectsSensitiveValues:
    @pytest.mark.parametrize(
        "field,value",
        [
            ("preferred", "https://mikanani.me/Home/Search"),
            ("excluded", "token=abc123"),
            ("must_contain", "magnet:?xt=urn:btih:deadbeef"),
            ("must_not_contain", "Cookie: session=xyz"),
            ("template", "/home/ghostning/secret"),
            ("preferred", "<html><body>raw</body></html>"),
            ("must_contain", "<rss><channel>raw</channel></rss>"),
            ("preferred", "Bearer abcdef12345"),
            ("must_not_contain", "Authorization: Bearer xyz"),
            ("template", "file:///etc/passwd"),
            ("preferred", "C:\\Windows\\system32"),
            ("must_contain", '{"response_body": "raw"}'),
        ],
    )
    def test_save_rejects_sensitive_value(
        self, tmp_path: Path, field: str, value: str
    ) -> None:
        config = _config(tmp_path)
        base = _full_preferences()
        prefs = _with_field(base, field, value)

        with pytest.raises(Stage1Error) as error:
            save_user_preferences(config, prefs)

        assert error.value.error_type == "validation_error"
        assert "敏感内容" in error.value.message
        assert not (config.preferences_dir / PREFERENCES_FILENAME).exists()

    def test_save_rejects_invalid_enum(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        prefs = VersionedUserPreference(
            subtitle_groups=SubtitleGroupPreference(fallback="always")
        )

        with pytest.raises(Stage1Error) as error:
            save_user_preferences(config, prefs)

        assert error.value.error_type == "validation_error"
        assert error.value.failed_step == "save_user_preferences"
        assert not (config.preferences_dir / PREFERENCES_FILENAME).exists()


class TestContainsSensitiveValue:
    def test_legitimate_preference_text_is_allowed(self) -> None:
        for value in (
            "Loli",
            "喵萌",
            "1080p",
            "合集版",
            "[v2]",
            "葬送的芙莉莲 第三季",
            "HEVC/10bit",
            "{title}",
            "next_preferred",
            "official_title_season",
        ):
            assert not contains_sensitive_value(value), value

    def test_sensitive_text_is_detected(self) -> None:
        for value in (
            "https://ab.example.com/api/subscribe",
            "token=abc123",
            "Bearer secret-token",
            "cookie: sid=abc",
            "magnet:?xt=urn:btih:abcd",
            "/home/ghostning/prefs.json",
            "file:///etc/shadow",
            "<html>raw</html>",
            "<rss version='2.0'>",
            "Authorization: Bearer x",
            "C:\\Users\\admin\\prefs",
        ):
            assert contains_sensitive_value(value), value

    def test_authorization_keyword_alone_is_detected(self) -> None:
        assert contains_sensitive_value("authorization: Bearer xyz")

    def test_sid_word_is_detected_but_side_is_not(self) -> None:
        assert contains_sensitive_value("sid=abc")
        assert not contains_sensitive_value("side")


class TestBuildPreferencesFromApi:
    def test_build_full_payload_round_trips(self) -> None:
        prefs = build_preferences_from_api(
            {
                "version": 1,
                "subtitle_groups": {
                    "preferred": ["Loli", "喵萌"],
                    "excluded": ["示例组"],
                    "fallback": "next_preferred",
                },
                "filter_defaults": {
                    "must_contain": "1080p",
                    "must_not_contain": "合集版",
                    "use_regex": False,
                    "case_sensitive": False,
                },
                "naming": {"strategy": "official_title_season", "template": "{title}"},
                "search": {"reuse_explicit_corrections": True},
            }
        )

        assert prefs == _full_preferences()
        assert serialize_preferences(prefs)["subtitle_groups"]["preferred"] == [
            "Loli",
            "喵萌",
        ]

    def test_build_empty_payload_returns_safe_defaults(self) -> None:
        prefs = build_preferences_from_api({})

        assert prefs == default_user_preferences()

    def test_build_partial_payload_fills_default_sections(self) -> None:
        prefs = build_preferences_from_api(
            {"subtitle_groups": {"preferred": ["喵萌"]}}
        )

        assert prefs.subtitle_groups.preferred == ["喵萌"]
        assert prefs.filter_defaults.must_contain == ""
        assert prefs.naming.strategy == "official_title_season"

    def test_build_rejects_non_object_payload(self) -> None:
        with pytest.raises(Stage1Error) as error:
            build_preferences_from_api(["Loli"])

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "preferences"}
        assert "对象" in error.value.message

    def test_build_rejects_unknown_top_level_field(self) -> None:
        with pytest.raises(Stage1Error) as error:
            build_preferences_from_api({"endpoint": "https://example.test/api"})

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "preferences"}
        assert "未定义字段" in error.value.message

    def test_build_rejects_unknown_section_field(self) -> None:
        with pytest.raises(Stage1Error) as error:
            build_preferences_from_api(
                {"subtitle_groups": {"preferred": [], "token": "secret"}}
            )

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "subtitle_groups"}

    def test_build_rejects_non_object_section(self) -> None:
        with pytest.raises(Stage1Error) as error:
            build_preferences_from_api({"naming": "official_title"})

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "naming"}

    def test_build_rejects_invalid_enum_through_validate(self) -> None:
        with pytest.raises(Stage1Error) as error:
            build_preferences_from_api(
                {"subtitle_groups": {"fallback": "auto"}}
            )

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "subtitle_groups.fallback"}

    def test_build_rejects_non_boolean_filter_flag(self) -> None:
        with pytest.raises(Stage1Error) as error:
            build_preferences_from_api(
                {"filter_defaults": {"use_regex": "yes"}}
            )

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "filter_defaults.use_regex"}


class TestStricterSaveValidation:
    def test_validate_rejects_empty_string_list_item(self) -> None:
        prefs = VersionedUserPreference(
            subtitle_groups=SubtitleGroupPreference(preferred=[""])
        )

        with pytest.raises(Stage1Error) as error:
            validate_preferences(prefs)

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "subtitle_groups.preferred"}
        assert "空字符串" in error.value.message

    def test_validate_rejects_duplicate_preferred_group(self) -> None:
        prefs = VersionedUserPreference(
            subtitle_groups=SubtitleGroupPreference(preferred=["Loli", "Loli"])
        )

        with pytest.raises(Stage1Error) as error:
            validate_preferences(prefs)

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "subtitle_groups.preferred"}
        assert "重复" in error.value.message

    def test_validate_rejects_duplicate_excluded_group(self) -> None:
        prefs = VersionedUserPreference(
            subtitle_groups=SubtitleGroupPreference(excluded=["喵萌", "喵萌"])
        )

        with pytest.raises(Stage1Error) as error:
            validate_preferences(prefs)

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "subtitle_groups.excluded"}

    def test_validate_rejects_group_in_both_lists(self) -> None:
        prefs = VersionedUserPreference(
            subtitle_groups=SubtitleGroupPreference(
                preferred=["Loli"], excluded=["Loli"]
            )
        )

        with pytest.raises(Stage1Error) as error:
            validate_preferences(prefs)

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "subtitle_groups"}
        assert "不能同时出现" in error.value.message

    def test_validate_accepts_empty_lists(self) -> None:
        validate_preferences(default_user_preferences())

    def test_validate_rejects_overlong_group_name(self) -> None:
        prefs = VersionedUserPreference(
            subtitle_groups=SubtitleGroupPreference(
                preferred=["长" * (MAX_SUBTITLE_GROUP_NAME_LENGTH + 1)]
            )
        )

        with pytest.raises(Stage1Error) as error:
            validate_preferences(prefs)

        assert error.value.error_type == "validation_error"
        assert "长度不能超过" in error.value.message

    def test_validate_rejects_overlong_filter_rule(self) -> None:
        prefs = VersionedUserPreference(
            filter_defaults=FilterDefaults(
                must_contain="a" * (MAX_FILTER_RULE_LENGTH + 1)
            )
        )

        with pytest.raises(Stage1Error) as error:
            validate_preferences(prefs)

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "filter_defaults.must_contain"}

    def test_validate_rejects_overlong_naming_template(self) -> None:
        prefs = VersionedUserPreference(
            naming=NamingPreference(template="x" * (MAX_NAMING_TEMPLATE_LENGTH + 1))
        )

        with pytest.raises(Stage1Error) as error:
            validate_preferences(prefs)

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "naming.template"}

    def test_save_rejects_duplicate_groups_without_writing(
        self, tmp_path: Path
    ) -> None:
        config = _config(tmp_path)
        prefs = VersionedUserPreference(
            subtitle_groups=SubtitleGroupPreference(preferred=["Loli", "Loli"])
        )

        with pytest.raises(Stage1Error) as error:
            save_user_preferences(config, prefs)

        assert error.value.error_type == "validation_error"
        assert not (config.preferences_dir / PREFERENCES_FILENAME).exists()


def _with_field(
    base: VersionedUserPreference, field: str, value: str
) -> VersionedUserPreference:
    from dataclasses import replace

    if field in ("preferred", "excluded"):
        group = replace(base.subtitle_groups)
        if field == "preferred":
            group = SubtitleGroupPreference(
                preferred=[value], excluded=group.excluded, fallback=group.fallback
            )
        else:
            group = SubtitleGroupPreference(
                preferred=group.preferred, excluded=[value], fallback=group.fallback
            )
        return replace(base, subtitle_groups=group)
    if field in ("must_contain", "must_not_contain"):
        fd = base.filter_defaults
        fd = (
            replace(fd, must_contain=value)
            if field == "must_contain"
            else replace(fd, must_not_contain=value)
        )
        return replace(base, filter_defaults=fd)
    if field == "template":
        return replace(base, naming=replace(base.naming, template=value))
    raise AssertionError(f"unknown field {field}")
