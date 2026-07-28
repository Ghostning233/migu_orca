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
    assert preference.subtitle_group_priority == ["喵萌"]


def test_invalid_config_fails(tmp_path: Path) -> None:
    path = tmp_path / "rules.json"
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(Stage1Error) as error:
        load_user_preference(path)

    assert error.value.error_type == "config_error"
