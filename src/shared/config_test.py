from __future__ import annotations

from pathlib import Path

import pytest

from shared.config import load_user_preference
from shared.errors import Stage1Error


def test_load_user_preference(tmp_path: Path) -> None:
    path = tmp_path / "rules.json"
    path.write_text(
        """{
          "filter_rule": {"must_contain": "1080p", "must_not_contain": "V2"},
          "subtitle_group_priority": ["喵萌"]
        }""",
        encoding="utf-8",
    )

    preference = load_user_preference(path)

    assert preference.filter_rule.must_contain == "1080p"
    assert preference.filter_rule.use_regex is False
    assert preference.filter_rule.case_sensitive is False
    assert preference.subtitle_group_priority == ["喵萌"]


def test_load_user_preference_old_config_defaults_regex_and_case_flags(tmp_path: Path) -> None:
    # 旧配置没有 use_regex / case_sensitive，必须按默认 False 兼容加载。
    path = tmp_path / "rules.json"
    path.write_text(
        """{
          "filter_rule": {"must_contain": "1080p", "must_not_contain": "V2"},
          "subtitle_group_priority": ["喵萌"]
        }""",
        encoding="utf-8",
    )

    preference = load_user_preference(path)

    assert preference.filter_rule.use_regex is False
    assert preference.filter_rule.case_sensitive is False


def test_load_user_preference_new_config_reads_regex_and_case_flags(tmp_path: Path) -> None:
    path = tmp_path / "rules.json"
    path.write_text(
        """{
          "filter_rule": {
            "must_contain": "1080p",
            "must_not_contain": "V2",
            "use_regex": true,
            "case_sensitive": true
          },
          "subtitle_group_priority": ["喵萌"]
        }""",
        encoding="utf-8",
    )

    preference = load_user_preference(path)

    assert preference.filter_rule.use_regex is True
    assert preference.filter_rule.case_sensitive is True


def test_invalid_regex_or_case_flag_is_config_error(tmp_path: Path) -> None:
    path = tmp_path / "rules.json"
    path.write_text(
        """{
          "filter_rule": {
            "must_contain": "1080p",
            "must_not_contain": "V2",
            "use_regex": "yes"
          },
          "subtitle_group_priority": ["喵萌"]
        }""",
        encoding="utf-8",
    )

    with pytest.raises(Stage1Error) as error:
        load_user_preference(path)

    assert error.value.error_type == "config_error"


def test_invalid_config_fails(tmp_path: Path) -> None:
    path = tmp_path / "rules.json"
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(Stage1Error) as error:
        load_user_preference(path)

    assert error.value.error_type == "config_error"
