from __future__ import annotations

import json
from pathlib import Path

import pytest

from ab_engine.controllers.ab_config import AutoBangumiConfig, build_ab_config, load_ab_config
from shared.errors import Stage1Error


def test_load_ab_config_from_explicit_json_path(tmp_path: Path) -> None:
    path = tmp_path / "ab.json"
    path.write_text(
        """{
          "base_url": " https://ab.example.invalid/ ",
          "username": " user-name ",
          "password": " password-value ",
          "fallback_enabled": true
        }""",
        encoding="utf-8",
    )

    config = load_ab_config(path)

    assert config == AutoBangumiConfig(
        base_url="https://ab.example.invalid",
        auth_mode="password",
        username="user-name",
        password="password-value",
        fallback_enabled=True,
    )


def test_load_ab_config_fails_for_missing_file(tmp_path: Path) -> None:
    with pytest.raises(Stage1Error) as error:
        load_ab_config(tmp_path / "missing.json")

    assert error.value.as_dict() == {
        "error_type": "config_error",
        "error_message": "Auto Bangumi 配置文件不存在",
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
    assert error.value.details == {}


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"username": "user", "password": "password", "fallback_enabled": True}, "base_url"),
        (
            {
                "base_url": "https://ab.example.invalid",
                "username": "user",
                "fallback_enabled": True,
            },
            "password",
        ),
        (
            {
                "base_url": "https://ab.example.invalid",
                "username": "user",
                "password": "password",
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


@pytest.mark.parametrize(
    "service_url",
    [
        "ftp://ab.example.invalid",
        "https://user:password@ab.example.invalid",
        "https://ab.example.invalid/api/v1/status",
        "https://ab.example.invalid/?query=value",
        "https://ab.example.invalid/#fragment",
    ],
)
def test_build_ab_config_rejects_non_root_or_unsafe_service_urls(service_url: str) -> None:
    with pytest.raises(Stage1Error) as error:
        build_ab_config({"base_url": service_url, "username": "user", "password": "secret", "fallback_enabled": False})

    assert error.value.as_dict() == {
        "error_type": "config_error",
        "error_message": "Auto Bangumi 配置无效",
        "failed_step": "load_ab_config",
        "details": {"field": "base_url"},
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"auth_mode": "unknown", "base_url": "https://ab.example.invalid", "fallback_enabled": False},
        {"base_url": "https://ab.example.invalid", "username": "user", "password": "secret", "token": "token-value", "fallback_enabled": False},
        {"auth_mode": "api_token", "base_url": "https://ab.example.invalid", "token": "token-value", "username": "user", "fallback_enabled": False},
    ],
)
def test_build_ab_config_rejects_unknown_or_mixed_auth_fields(payload: dict[str, object]) -> None:
    with pytest.raises(Stage1Error) as error:
        build_ab_config(payload)

    assert error.value.as_dict() == {
        "error_type": "config_error",
        "error_message": "Auto Bangumi 配置无效",
        "failed_step": "load_ab_config",
        "details": {"field": "auth_mode"},
    }
