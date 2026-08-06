from __future__ import annotations

from flask import Flask

from apps.registry import ALL_BLUEPRINTS


def create_app(config_name: str | None = None) -> Flask:
    """Create the MiGuOrca Flask application."""

    app = Flask("migu_orca")
    app.config["CONFIG_NAME"] = config_name
    if config_name in {"test", "testing"}:
        app.config["TESTING"] = True

    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint)

    return app
