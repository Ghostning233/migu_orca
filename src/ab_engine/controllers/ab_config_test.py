from __future__ import annotations

import json
from pathlib import Path

import pytest

from ab_engine.controllers.ab_config import AutoBangumiConfig, load_ab_config
from shared.errors import Stage1Error


def test_load_ab_config_from_explicit_json_path(tmp_path: Path) -> None:
    path = tmp_path / "ab.json"
    path.write_text(
        """{
          "endpoint": " https://ab.example.invalid ",
          "token": " token-value ",
          "fallback_enabled": true
        }""",
        encoding="utf-8",
    )

    config = load_ab_config(path)

    assert config == AutoBangumiConfig(
        endpoint="https://ab.example.invalid",
        token="token-value",
        fallback_enabled=True,
    )


def test_load_ab_config_fails_for_missing_file(tmp_path: Path) -> None:
    with pytest.raises(Stage1Error) as error:
        load_ab_config(tmp_path / "missing.json")

    assert error.value.as_dict() == {
        "error_type": "config_error",
        "error_message": f"Auto Bangumi 配置文件不存在：{tmp_path / 'missing.json'}",
        "failed_step": "load_ab_config",
        "details": {},
    }


def test_load_ab_config_fails_for_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "ab.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(Stage1Error) as error:
        load_ab_config(path)

    assert error.value.error_type == "config_error"
    assert error.value.failed_step == "load_ab_config"
    assert "合法 JSON" in error.value.message
    assert "reason" in error.value.details


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"token": "token-value", "fallback_enabled": True}, "endpoint"),
        (
            {
                "endpoint": "https://ab.example.invalid",
                "fallback_enabled": True,
            },
            "token",
        ),
        (
            {
                "endpoint": "https://ab.example.invalid",
                "token": "token-value",
                "fallback_enabled": "yes",
            },
            "fallback_enabled",
        ),
    ],
)
def test_load_ab_config_fails_for_field_type_errors(
    tmp_path: Path,
    payload: dict[str, object],
    field: str,
) -> None:
    path = tmp_path / "ab.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(Stage1Error) as error:
        load_ab_config(path)

    assert error.value.as_dict()["error_type"] == "config_error"
    assert error.value.as_dict()["failed_step"] == "load_ab_config"
    assert error.value.as_dict()["details"] == {"field": field}


def test_load_ab_config_fails_for_non_object_json(tmp_path: Path) -> None:
    path = tmp_path / "ab.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(Stage1Error) as error:
        load_ab_config(path)

    assert error.value.as_dict() == {
        "error_type": "config_error",
        "error_message": "Auto Bangumi 配置必须是 JSON 对象",
        "failed_step": "load_ab_config",
        "details": {},
    }
