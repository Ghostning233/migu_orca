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
    sanitize_error_data,
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


def test_stage32_security_matrix_redacts_nested_upstream_evidence() -> None:
    """US-253: error details never carry upstream or local evidence."""
    canaries = (
        "stage32-password",
        "stage32-token",
        "stage32-cookie",
        "stage32-external-id",
        "stage32-response-body",
        "stage32-magnet",
        "stage32-stack",
        "stage32-file",
    )
    sanitized = sanitize_error_data(
        {
            "password": canaries[0],
            "nested": [
                {"authorization": canaries[1]},
                {"cookie": canaries[2]},
                {"external_id": canaries[3]},
                {"raw_response_body": canaries[4]},
                {"magnet": canaries[5]},
                {"traceback": canaries[6]},
                {"local_path": f"/private/{canaries[7]}"},
                {"safe": "public-summary"},
            ],
            "endpoint": "https://private.stage32.invalid/api?token=stage32-token",
            "windows_path": r"C:\private\stage32-secret.json",
            "raw_text": "<rss>stage32-response-body</rss>",
        }
    )
    rendered = repr(sanitized)
    assert all(canary not in rendered for canary in canaries)
    assert sanitized["nested"][-1] == {"safe": "public-summary"}
    assert sanitized["endpoint"] == "[redacted-url]"
    assert sanitized["windows_path"] == "[redacted-path]"


def test_error_http_status_maps_semantic_categories() -> None:
    """US-192: error types map to stable HTTP statuses."""
    from extensions.flask_api.api import _error_http_status

    # Client/input errors → 400
    assert _error_http_status("validation_error") == 400
    assert _error_http_status("data_validation_errors") == 400
    assert _error_http_status("invalid_modify_patch_field") == 400
    assert _error_http_status("invalid_input") == 400
    assert _error_http_status("config_error") == 400
    assert _error_http_status("invalid_storage_dir") == 400
    # US-215 batch input over the 36-work limit → 400.
    assert _error_http_status("batch_limit_exceeded") == 400
    # Missing resources → 404
    assert _error_http_status("request_not_found") == 404
    assert _error_http_status("poster_not_found") == 404
    # State conflicts / replay → 409
    assert _error_http_status("invalid_request_status") == 409
    assert _error_http_status("request_cancelled") == 409
    assert _error_http_status("season_evidence_conflict") == 409
    assert _error_http_status("candidate_context_invalid") == 409
    # US-194 draft store failures → 409 (expired/evicted/replayed/mismatch).
    assert _error_http_status("draft_expired") == 409
    assert _error_http_status("draft_evicted") == 409
    assert _error_http_status("draft_replayed") == 409
    assert _error_http_status("draft_mismatch") == 409
    # US-213 save-confirm idempotency conflicts → 409.
    assert _error_http_status("idempotency_conflict") == 409
    # US-214 save-confirm acceptance-failure (Request saved, not confirmed) → 409.
    assert _error_http_status("save_confirm_failed") == 409
    # External auth → 401
    assert _error_http_status("ab_auth_failed") == 401
    # Upstream bad gateway → 502
    assert _error_http_status("mikan_connection_failed") == 502
    assert _error_http_status("ab_submit_failed") == 502
    # Upstream unavailable/unsupported → 503
    assert _error_http_status("ab_unsupported_version") == 503
    # Upstream timeout → 504
    assert _error_http_status("mikan_timeout") == 504
    assert _error_http_status("ab_timeout") == 504
    # Unknown error types default to 400 (client-visible, never 500).
    assert _error_http_status("some_future_error") == 400
    assert _error_http_status("") == 400


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

    # mikan_failed is not in a known category; the envelope defaults to 400
    # (client-visible) rather than 500.
    assert response.status_code == 400
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

    assert response.status_code == 400
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

    assert response.status_code == 500
    assert response.get_json() == {
        "ok": False,
        "error_type": "internal_server_error",
        "error_message": "A server error occurred.",
    }


def test_stage1_error_maps_to_semantic_http_status(app: Flask) -> None:
    """US-192: a Stage1Error's HTTP status follows its error_type category."""
    with app.app_context():
        not_found = handle_exception(
            "test_view",
            Stage1Error(
                "request_not_found", "未找到订阅方案", "load", {"request_id": "r1"}
            ),
        )
        conflict = handle_exception(
            "test_view",
            Stage1Error(
                "invalid_request_status", "状态冲突", "confirm", {"status": "x"}
            ),
        )
        idempotency_conflict = handle_exception(
            "test_view",
            Stage1Error(
                "idempotency_conflict",
                "相同的幂等键不能用于不同的保存确认操作",
                "save_confirm_idempotency",
                {"field": "idempotency_key", "reason": "payload_mismatch"},
            ),
        )
        timeout = handle_exception(
            "test_view",
            Stage1Error("mikan_timeout", "MiKan 请求超时", "search"),
        )
        gateway = handle_exception(
            "test_view",
            Stage1Error("ab_submit_failed", "AB 提交失败", "submit"),
        )
        capability_unknown = handle_exception(
            "test_view",
            Stage1Error(
                "tracking_management_capability_unknown",
                "当前 Auto Bangumi 管理能力未验证",
                "tracking_management",
            ),
        )

    assert not_found.status_code == 404
    assert not_found.get_json()["error_type"] == "request_not_found"
    assert conflict.status_code == 409
    assert conflict.get_json()["error_type"] == "invalid_request_status"
    assert idempotency_conflict.status_code == 409
    assert idempotency_conflict.get_json()["error_data"]["details"] == {
        "field": "idempotency_key",
        "reason": "payload_mismatch",
    }
    assert timeout.status_code == 504
    assert timeout.get_json()["error_type"] == "mikan_timeout"
    assert gateway.status_code == 502
    assert capability_unknown.status_code == 409
    assert capability_unknown.get_json()["error_type"] == "tracking_management_capability_unknown"
    assert gateway.get_json()["error_type"] == "ab_submit_failed"
