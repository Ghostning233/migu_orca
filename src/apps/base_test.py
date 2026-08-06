from __future__ import annotations

from flask import Flask

from apps.base import create_app
from apps.registry import ALL_BLUEPRINTS


def test_create_app_returns_flask_app() -> None:
    app = create_app()

    assert isinstance(app, Flask)
    assert app.name == "migu_orca"
    assert app.config["CONFIG_NAME"] is None


def test_create_app_applies_test_config_name() -> None:
    app = create_app("testing")

    assert app.config["CONFIG_NAME"] == "testing"
    assert app.config["TESTING"] is True


def test_create_app_registers_all_blueprints() -> None:
    app = create_app()

    for blueprint in ALL_BLUEPRINTS:
        assert blueprint.name in app.blueprints
