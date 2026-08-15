from __future__ import annotations

from pathlib import Path

import pytest

from mikan_engine.controllers.mikan_config import (
    DEFAULT_MIKAN_SEARCH_ENDPOINT,
    DEFAULT_MIKAN_TIMEOUT_SECONDS,
    MikanConfig,
    default_mikan_config,
    load_mikan_config,
)
from shared.errors import Stage1Error


def test_load_mikan_config_from_explicit_json_path(tmp_path: Path) -> None:
    config_path = tmp_path / "mikan.json"
    config_path.write_text(
        '{"search_endpoint": " https://mikan.example/search ", "timeout_seconds": 8}',
        encoding="utf-8",
    )

    config = load_mikan_config(config_path)

    assert config == MikanConfig(
        search_endpoint="https://mikan.example/search",
        timeout_seconds=8.0,
    )


def test_load_mikan_config_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(Stage1Error) as error:
        load_mikan_config(tmp_path / "missing.json")

    assert error.value.error_type == "config_error"
    assert error.value.failed_step == "load_mikan_config"


def test_load_mikan_config_requires_endpoint_and_timeout(tmp_path: Path) -> None:
    config_path = tmp_path / "mikan.json"
    config_path.write_text('{"search_endpoint": "", "timeout_seconds": 0}', encoding="utf-8")

    with pytest.raises(Stage1Error) as error:
        load_mikan_config(config_path)

    assert error.value.error_type == "config_error"
    assert error.value.details == {"field": "search_endpoint"}


def test_default_mikan_config_uses_public_search_endpoint() -> None:
    config = default_mikan_config()

    assert config == MikanConfig(
        search_endpoint=DEFAULT_MIKAN_SEARCH_ENDPOINT,
        timeout_seconds=DEFAULT_MIKAN_TIMEOUT_SECONDS,
    )
    assert config.search_endpoint == "https://mikanani.me/Home/Search"
    assert config.timeout_seconds == 15.0


def test_default_mikan_config_contains_no_secrets() -> None:
    config = default_mikan_config()

    serialized = {
        "search_endpoint": config.search_endpoint,
        "timeout_seconds": config.timeout_seconds,
    }
    text = str(serialized).lower()
    assert "secret" not in text
    assert "token" not in text
    assert "cookie" not in text
    assert "password" not in text
