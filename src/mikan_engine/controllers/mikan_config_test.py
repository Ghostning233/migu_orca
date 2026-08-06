from __future__ import annotations

from pathlib import Path

import pytest

from mikan_engine.controllers.mikan_config import MikanConfig, load_mikan_config
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
