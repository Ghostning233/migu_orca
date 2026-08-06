from __future__ import annotations

import pytest
from flask import Blueprint, Flask
from pydantic import BaseModel

from extensions.flask_api.api import (
    class_route,
    failed_response,
    handle_exception,
    ok_response,
    route,
)
from extensions.flask_api.exceptions import APIException
from extensions.flask_api.views import GetView, PostView
from shared.errors import Stage1Error


@pytest.fixture
def app() -> Flask:
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    return flask_app


def test_ok_response_uses_shared_envelope(app: Flask) -> None:
    with app.app_context():
        response = ok_response({"value": 1})

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "result": {"value": 1}}


def test_failed_response_omits_missing_error_data(app: Flask) -> None:
    with app.app_context():
        response = failed_response("bad_input", "Bad input")

    assert response.get_json() == {
        "ok": False,
        "error_type": "bad_input",
        "error_message": "Bad input",
    }


def test_failed_response_sanitizes_error_data(app: Flask) -> None:
    with app.app_context():
        response = failed_response(
            "bad_source",
            "failed at https://example.invalid/rss?token=secret",
            {
                "path": "/home/user/private/file.xml",
                "token": "secret-token",
                "payload": "<rss>secret</rss>",
            },
        )

    payload = response.get_json()
    assert payload["error_message"] == "failed at [redacted-url]"
    assert payload["error_data"] == {
        "path": "[redacted-path]",
        "token": "[redacted]",
        "payload": "[redacted-content]",
    }


def test_route_wraps_success_response() -> None:
    app = Flask(__name__)
    blueprint = Blueprint("api_test", __name__)

    @route(blueprint, "/ping")
    def ping() -> dict[str, str]:
        return {"pong": "ok"}

    app.register_blueprint(blueprint)

    response = app.test_client().get("/ping")

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "result": {"pong": "ok"}}


def test_route_converts_stage1_error_to_sanitized_api_error() -> None:
    app = Flask(__name__)
    blueprint = Blueprint("stage_error_test", __name__)

    @route(blueprint, "/boom")
    def boom() -> dict[str, str]:
        raise Stage1Error(
            "mikan_failed",
            "RSS failed from https://example.invalid/feed",
            "fetch_rss",
            {
                "local_path": "/tmp/private/rss.xml",
                "raw_xml": "<rss>secret</rss>",
            },
        )

    app.register_blueprint(blueprint)

    response = app.test_client().get("/boom")

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": False,
        "error_type": "mikan_failed",
        "error_message": "RSS failed from [redacted-url]",
        "error_data": {
            "failed_step": "fetch_rss",
            "details": {
                "local_path": "[redacted-path]",
                "raw_xml": "[redacted-content]",
            },
        },
    }


def test_class_route_validates_post_json() -> None:
    app = Flask(__name__)
    blueprint = Blueprint("class_test", __name__)

    class CreatePayload(BaseModel):
        title: str

    @class_route(blueprint, "/requests", methods=["POST"])
    class CreateRequestView(PostView):
        request_validator_model = CreatePayload

        def save(self) -> dict[str, str]:
            assert isinstance(self.request_validator_model, CreatePayload)
            return {"title": self.request_validator_model.title}

    app.register_blueprint(blueprint)

    response = app.test_client().post("/requests", json={"title": "Bangumi"})

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "result": {"title": "Bangumi"}}


def test_class_route_returns_validation_errors() -> None:
    app = Flask(__name__)
    blueprint = Blueprint("validation_test", __name__)

    class QueryPayload(BaseModel):
        limit: int

    @class_route(blueprint, "/requests")
    class RequestListView(GetView):
        request_validator_model = QueryPayload

        def get_object(self) -> dict[str, int]:
            assert isinstance(self.request_validator_model, QueryPayload)
            return {"limit": self.request_validator_model.limit}

    app.register_blueprint(blueprint)

    response = app.test_client().get("/requests?limit=bad")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert payload["error_data"]["errors"][0]["field"] == "limit"


def test_api_exception_returns_failed_response(app: Flask) -> None:
    with app.app_context():
        response = handle_exception(
            "test_view",
            APIException("not_found", "Request not found", {"request_id": "r1"}),
        )

    assert response.get_json() == {
        "ok": False,
        "error_type": "not_found",
        "error_message": "Request not found",
        "error_data": {"request_id": "r1"},
    }


def test_unhandled_exception_reraises_in_testing(app: Flask) -> None:
    with app.app_context(), pytest.raises(RuntimeError, match="unexpected"):
        handle_exception("test_view", RuntimeError("unexpected"))


def test_unhandled_exception_is_generic_outside_debug() -> None:
    app = Flask(__name__)
    app.config["TESTING"] = False
    app.config["DEBUG"] = False

    with app.app_context():
        response = handle_exception(
            "test_view",
            RuntimeError("secret-token at /home/user/private"),
        )

    assert response.get_json() == {
        "ok": False,
        "error_type": "internal_server_error",
        "error_message": "A server error occurred.",
    }
