from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.errors import Stage1Error
from shared.models import (
    MAX_STORED_CORRECTIONS,
    BangumiCorrectionMetadata,
    TitleCorrection,
)
from storage_engine.controllers.correction_repository import (
    CORRECTIONS_FILENAME,
    MAX_CORRECTION_QUERY_LENGTH,
    MAX_CORRECTION_TITLE_LENGTH,
    MAX_SEASON_HINT_LENGTH,
    build_correction_from_api,
    default_corrections,
    load_corrections,
    save_correction,
    serialize_correction,
    serialize_corrections,
    validate_correction,
)
from storage_engine.controllers.preference_repository import contains_sensitive_value
from storage_engine.controllers.storage_config import load_storage_config


def _config(tmp_path: Path):
    return load_storage_config(tmp_path / "migu-state")


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


def _written_body(config) -> dict:
    return json.loads(
        (config.corrections_dir / CORRECTIONS_FILENAME).read_text(encoding="utf-8")
    )


class TestDefaultCorrections:
    def test_default_corrections_are_safe_and_empty(self) -> None:
        assert default_corrections() == []

    def test_default_corrections_are_fresh_instances(self) -> None:
        assert default_corrections() is not default_corrections()


class TestLoadMissingFile:
    def test_load_missing_corrections_returns_empty(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        corrections = load_corrections(config)

        assert corrections == []
        assert not config.corrections_dir.exists()


class TestSaveAndLoad:
    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        correction = _correction()

        saved = save_correction(config, correction)
        loaded = load_corrections(config)

        assert saved == {
            "storage": "local_json",
            "directory": "corrections",
            "filename": CORRECTIONS_FILENAME,
            "count": 1,
        }
        assert loaded == [correction]
        assert loaded[0] is not correction

    def test_save_writes_only_non_sensitive_fields(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        save_correction(config, _correction())

        body = _written_body(config)
        assert body["version"] == 1
        assert body["corrections"] == [
            {
                "raw_title": "芙莉莲",
                "canonical_title": "葬送的芙莉莲",
                "season_hint": "S2",
                "bangumi_metadata": {
                    "bangumi_id": "12345",
                    "title": "葬送的芙莉莲",
                },
                "query_correction": "葬送的芙莉莲 第二季",
            }
        ]
        assert not body.get("endpoint")
        assert not body.get("token")

    def test_save_uses_temp_file_and_leaves_no_tmp(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        save_correction(config, _correction())

        assert not list(config.corrections_dir.glob("*.tmp"))
        assert (config.corrections_dir / CORRECTIONS_FILENAME).exists()
        assert _written_body(config)["version"] == 1

    def test_save_appends_distinct_raw_titles(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        save_correction(config, _correction())
        save_correction(
            config,
            TitleCorrection(
                raw_title="推子",
                canonical_title="我推的孩子",
                query_correction="我推的孩子",
            ),
        )

        loaded = load_corrections(config)
        assert [c.raw_title for c in loaded] == ["芙莉莲", "推子"]

    def test_save_replaces_same_raw_title_with_latest_version(
        self, tmp_path: Path
    ) -> None:
        config = _config(tmp_path)
        save_correction(config, _correction())
        save_correction(
            config,
            TitleCorrection(
                raw_title="芙莉莲",
                canonical_title="葬送的芙莉莲 第二季 修正",
                season_hint="S3",
                query_correction="葬送的芙莉莲 第二季 S3",
            ),
        )

        loaded = load_corrections(config)
        assert len(loaded) == 1
        assert loaded[0].raw_title == "芙莉莲"
        assert loaded[0].canonical_title == "葬送的芙莉莲 第二季 修正"
        assert loaded[0].season_hint == "S3"
        assert loaded[0].query_correction == "葬送的芙莉莲 第二季 S3"

    def test_save_evicts_oldest_past_global_cap(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        for index in range(MAX_STORED_CORRECTIONS + 3):
            save_correction(
                config,
                TitleCorrection(
                    raw_title=f"标题{index}",
                    canonical_title=f"正名{index}",
                    query_correction=f"查询{index}",
                ),
            )

        loaded = load_corrections(config)
        assert len(loaded) == MAX_STORED_CORRECTIONS
        # The three oldest raw titles are evicted; the newest stay.
        assert loaded[0].raw_title == "标题3"
        assert loaded[-1].raw_title == f"标题{MAX_STORED_CORRECTIONS + 2}"


class TestInvalidStoredFile:
    def test_load_damaged_json_returns_stable_error(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        (config.corrections_dir).mkdir(parents=True, exist_ok=True)
        (config.corrections_dir / CORRECTIONS_FILENAME).write_text(
            "not json", encoding="utf-8"
        )

        with pytest.raises(Stage1Error) as error:
            load_corrections(config)

        assert error.value.error_type == "storage_json_error"
        assert error.value.failed_step == "load_corrections"
        assert "读取搜索修正 JSON 失败" in error.value.message

    def test_load_non_object_json_returns_stable_error(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        (config.corrections_dir).mkdir(parents=True, exist_ok=True)
        (config.corrections_dir / CORRECTIONS_FILENAME).write_text(
            '["not", "an", "object"]', encoding="utf-8"
        )

        with pytest.raises(Stage1Error) as error:
            load_corrections(config)

        assert error.value.error_type == "storage_json_error"
        assert "必须是对象" in error.value.message

    def test_load_sensitive_stored_value_rejected(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        (config.corrections_dir).mkdir(parents=True, exist_ok=True)
        (config.corrections_dir / CORRECTIONS_FILENAME).write_text(
            json.dumps(
                {
                    "version": 1,
                    "corrections": [
                        {
                            "raw_title": "芙莉莲",
                            "canonical_title": "https://mikan.example/api",
                            "query_correction": "芙莉莲",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        with pytest.raises(Stage1Error) as error:
            load_corrections(config)

        assert error.value.error_type == "validation_error"
        assert "敏感内容" in error.value.message
        assert error.value.failed_step == "load_corrections"

    def test_save_does_not_overwrite_damaged_existing_file(
        self, tmp_path: Path
    ) -> None:
        config = _config(tmp_path)
        (config.corrections_dir).mkdir(parents=True, exist_ok=True)
        corrections_path = config.corrections_dir / CORRECTIONS_FILENAME
        corrections_path.write_text("not json", encoding="utf-8")

        with pytest.raises(Stage1Error) as error:
            save_correction(config, _correction())

        assert error.value.error_type == "storage_json_error"
        # The damaged original is preserved, not silently overwritten.
        assert corrections_path.read_text(encoding="utf-8") == "not json"


class TestValidation:
    def test_validate_accepts_full_legal_correction(self) -> None:
        validate_correction(_correction())

    def test_validate_accepts_minimal_correction(self) -> None:
        validate_correction(
            TitleCorrection(raw_title="芙莉莲", canonical_title="葬送的芙莉莲")
        )

    def test_validate_rejects_missing_raw_title(self) -> None:
        with pytest.raises(Stage1Error) as error:
            validate_correction(
                TitleCorrection(raw_title="", canonical_title="葬送的芙莉莲")
            )

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "raw_title"}
        assert "不能为空" in error.value.message

    def test_validate_rejects_missing_canonical_title(self) -> None:
        with pytest.raises(Stage1Error) as error:
            validate_correction(TitleCorrection(raw_title="芙莉莲", canonical_title=""))

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "canonical_title"}

    def test_validate_rejects_non_string_raw_title(self) -> None:
        with pytest.raises(Stage1Error) as error:
            validate_correction(
                TitleCorrection(raw_title=123, canonical_title="葬送的芙莉莲")
            )

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "raw_title"}
        assert "必须是字符串" in error.value.message

    def test_validate_rejects_overlong_standard_title(self) -> None:
        with pytest.raises(Stage1Error) as error:
            validate_correction(
                TitleCorrection(
                    raw_title="x" * (MAX_CORRECTION_TITLE_LENGTH + 1),
                    canonical_title="葬送的芙莉莲",
                )
            )

        assert error.value.error_type == "validation_error"
        assert "长度不能超过" in error.value.message

    def test_validate_rejects_overlong_query_correction(self) -> None:
        with pytest.raises(Stage1Error) as error:
            validate_correction(
                TitleCorrection(
                    raw_title="芙莉莲",
                    canonical_title="葬送的芙莉莲",
                    query_correction="q" * (MAX_CORRECTION_QUERY_LENGTH + 1),
                )
            )

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "query_correction"}
        assert "长度不能超过" in error.value.message

    def test_validate_rejects_overlong_season_hint(self) -> None:
        with pytest.raises(Stage1Error) as error:
            validate_correction(
                TitleCorrection(
                    raw_title="芙莉莲",
                    canonical_title="葬送的芙莉莲",
                    season_hint="S" * (MAX_SEASON_HINT_LENGTH + 1),
                )
            )

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "season_hint"}


class TestSaveRejectsSensitiveValues:
    @pytest.mark.parametrize(
        "field,value",
        [
            ("raw_title", "https://mikanani.me/Home/Search"),
            ("canonical_title", "token=abc123"),
            ("query_correction", "magnet:?xt=urn:btih:deadbeef"),
            ("canonical_title", "Cookie: session=xyz"),
            ("raw_title", "/home/ghostning/secret"),
            ("query_correction", "<html><body>raw</body></html>"),
            ("canonical_title", "<rss><channel>raw</channel></rss>"),
            ("raw_title", "Bearer abcdef12345"),
            ("season_hint", "Authorization: Bearer xyz"),
            ("canonical_title", "file:///etc/passwd"),
            ("raw_title", "C:\\Windows\\system32"),
            ("query_correction", '{"response_body": "raw"}'),
        ],
    )
    def test_save_rejects_sensitive_value(
        self, tmp_path: Path, field: str, value: str
    ) -> None:
        config = _config(tmp_path)
        base = _correction()
        correction = _with_field(base, field, value)

        with pytest.raises(Stage1Error) as error:
            save_correction(config, correction)

        assert error.value.error_type == "validation_error"
        assert "敏感内容" in error.value.message
        assert not (config.corrections_dir / CORRECTIONS_FILENAME).exists()

    def test_save_rejects_missing_field_without_writing(
        self, tmp_path: Path
    ) -> None:
        config = _config(tmp_path)
        correction = TitleCorrection(raw_title="", canonical_title="葬送的芙莉莲")

        with pytest.raises(Stage1Error) as error:
            save_correction(config, correction)

        assert error.value.error_type == "validation_error"
        assert not (config.corrections_dir / CORRECTIONS_FILENAME).exists()


class TestContainsSensitiveValue:
    def test_legitimate_correction_text_is_allowed(self) -> None:
        for value in (
            "芙莉莲",
            "葬送的芙莉莲",
            "葬送のフリーレン",
            "Frieren: Beyond Journey's End",
            "第二季",
            "第4季",
            "S2",
            "Season 2",
            "我推的孩子",
        ):
            assert not contains_sensitive_value(value), value

    def test_sensitive_text_is_detected(self) -> None:
        for value in (
            "https://ab.example.com/api/subscribe",
            "token=abc123",
            "Bearer secret-token",
            "cookie: sid=abc",
            "magnet:?xt=urn:btih:abcd",
            "/home/ghostning/corrections.json",
            "file:///etc/shadow",
            "<html>raw</html>",
            "<rss version='2.0'>",
            "Authorization: Bearer x",
            "C:\\Users\\admin\\corrections",
        ):
            assert contains_sensitive_value(value), value


class TestBuildCorrectionFromApi:
    def test_build_full_payload_round_trips(self) -> None:
        correction = build_correction_from_api(
            {
                "raw_title": "芙莉莲",
                "canonical_title": "葬送的芙莉莲",
                "season_hint": "S2",
                "bangumi_metadata": {
                    "bangumi_id": "12345",
                    "title": "葬送的芙莉莲",
                },
                "query_correction": "葬送的芙莉莲 第二季",
            }
        )

        assert correction == _correction()
        assert serialize_correction(correction) == {
            "raw_title": "芙莉莲",
            "canonical_title": "葬送的芙莉莲",
            "season_hint": "S2",
            "bangumi_metadata": {
                "bangumi_id": "12345",
                "title": "葬送的芙莉莲",
            },
            "query_correction": "葬送的芙莉莲 第二季",
        }

    def test_build_partial_payload_defaults_optionals(self) -> None:
        correction = build_correction_from_api(
            {"raw_title": "芙莉莲", "canonical_title": "葬送的芙莉莲"}
        )

        assert correction.season_hint is None
        assert correction.bangumi_metadata is None
        assert correction.query_correction is None
        assert serialize_correction(correction)["bangumi_metadata"] is None

    def test_serialize_corrections_round_trips(self) -> None:
        corrections = [
            _correction(),
            TitleCorrection(raw_title="推子", canonical_title="我推的孩子"),
        ]

        assert serialize_corrections(corrections) == [
            {
                "raw_title": "芙莉莲",
                "canonical_title": "葬送的芙莉莲",
                "season_hint": "S2",
                "bangumi_metadata": {
                    "bangumi_id": "12345",
                    "title": "葬送的芙莉莲",
                },
                "query_correction": "葬送的芙莉莲 第二季",
            },
            {
                "raw_title": "推子",
                "canonical_title": "我推的孩子",
                "season_hint": None,
                "bangumi_metadata": None,
                "query_correction": None,
            },
        ]

    def test_build_rejects_non_object_payload(self) -> None:
        with pytest.raises(Stage1Error) as error:
            build_correction_from_api(["芙莉莲"])

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "correction"}
        assert "必须是对象" in error.value.message

    def test_build_rejects_unknown_top_level_field(self) -> None:
        with pytest.raises(Stage1Error) as error:
            build_correction_from_api(
                {"raw_title": "芙莉莲", "canonical_title": "葬送的芙莉莲", "token": "secret"}
            )

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "correction"}
        assert "未定义字段" in error.value.message

    def test_build_rejects_unknown_bangumi_metadata_field(self) -> None:
        with pytest.raises(Stage1Error) as error:
            build_correction_from_api(
                {
                    "raw_title": "芙莉莲",
                    "canonical_title": "葬送的芙莉莲",
                    "bangumi_metadata": {"bangumi_id": "123", "endpoint": "https://x"},
                }
            )

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "bangumi_metadata"}
        assert "未定义字段" in error.value.message

    def test_build_rejects_non_object_bangumi_metadata(self) -> None:
        with pytest.raises(Stage1Error) as error:
            build_correction_from_api(
                {
                    "raw_title": "芙莉莲",
                    "canonical_title": "葬送的芙莉莲",
                    "bangumi_metadata": "12345",
                }
            )

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "bangumi_metadata"}
        assert "必须是对象" in error.value.message

    def test_build_rejects_sensitive_through_validate(self) -> None:
        with pytest.raises(Stage1Error) as error:
            build_correction_from_api(
                {
                    "raw_title": "芙莉莲",
                    "canonical_title": "葬送的芙莉莲",
                    "query_correction": "https://mikan.example/api",
                }
            )

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "query_correction"}

    def test_build_rejects_overlong_through_validate(self) -> None:
        with pytest.raises(Stage1Error) as error:
            build_correction_from_api(
                {
                    "raw_title": "芙莉莲",
                    "canonical_title": "x" * (MAX_CORRECTION_TITLE_LENGTH + 1),
                }
            )

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "canonical_title"}

    def test_build_rejects_missing_required_through_validate(self) -> None:
        with pytest.raises(Stage1Error) as error:
            build_correction_from_api({"canonical_title": "葬送的芙莉莲"})

        assert error.value.error_type == "validation_error"
        assert error.value.details == {"field": "raw_title"}


def _with_field(base: TitleCorrection, field: str, value: str) -> TitleCorrection:
    from dataclasses import replace

    if field == "raw_title":
        return replace(base, raw_title=value)
    if field == "canonical_title":
        return replace(base, canonical_title=value)
    if field == "season_hint":
        return replace(base, season_hint=value)
    if field == "query_correction":
        return replace(base, query_correction=value)
    raise AssertionError(f"unknown field {field}")
