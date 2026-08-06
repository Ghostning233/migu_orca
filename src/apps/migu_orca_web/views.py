from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Blueprint, redirect, render_template, url_for
from pydantic import BaseModel, field_validator

from extensions.flask_api import class_route
from extensions.flask_api.views import GetView, PostView
from apps.migu_orca_entry.controllers.entry_controller import (
    apply_request_save_action,
    generate_request,
)
from request_engine.controllers.request_controller import summarize_request
from shared.errors import Stage1Error
from shared.models import EntryRequest
from storage_engine.controllers.request_repository import (
    list_request_snapshots,
    load_request_snapshot,
)
from storage_engine.controllers.storage_config import load_storage_config

api_blueprint = Blueprint("migu_orca_web_api", __name__)
web_blueprint = Blueprint(
    "migu_orca_web",
    __name__,
    static_folder="static",
    template_folder="templates",
)


class RequestListQuery(BaseModel):
    storage_dir: str | None = None


class RequestDetailQuery(BaseModel):
    request_id: str
    storage_dir: str | None = None


class RequestCreatePayload(BaseModel):
    title: str
    storage_dir: str | None = None
    save_request: bool = False

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("title cannot be empty")
        return title


def _storage_dir(value: str | None) -> Path | None:
    if value is None or not value.strip():
        return None
    return Path(value.strip())


def _raise_result_error(result: dict[str, Any]) -> None:
    error = result.get("error")
    if not isinstance(error, dict):
        raise Stage1Error(
            "unexpected_error",
            "Request API 操作失败",
            "migu_orca_web_api",
        )
    details = error.get("details")
    raise Stage1Error(
        str(error.get("error_type") or "unexpected_error"),
        str(error.get("error_message") or "Request API 操作失败"),
        str(error.get("failed_step") or "migu_orca_web_api"),
        details if isinstance(details, dict) else None,
    )


@web_blueprint.get("/")
def index_redirect() -> object:
    return redirect(url_for("migu_orca_web.index"))


@web_blueprint.get("/index")
def index() -> str:
    return render_template("migu_orca_web/index.html")


@class_route(api_blueprint, "/api/v1/requests", methods=["GET"])
class RequestListView(GetView):
    request_validator_model = RequestListQuery

    def get_object(self) -> dict[str, list[dict[str, object]]]:
        assert isinstance(self.request_validator_model, RequestListQuery)
        config = load_storage_config(_storage_dir(self.request_validator_model.storage_dir))
        requests = [
            summarize_request(snapshot) for snapshot in list_request_snapshots(config)
        ]
        return {"requests": requests}


@class_route(api_blueprint, "/api/v1/requests/<path:request_id>", methods=["GET"])
class RequestDetailView(GetView):
    request_validator_model = RequestDetailQuery

    def get_object(self) -> dict[str, dict[str, object]]:
        assert isinstance(self.request_validator_model, RequestDetailQuery)
        config = load_storage_config(_storage_dir(self.request_validator_model.storage_dir))
        request = load_request_snapshot(config, self.request_validator_model.request_id)
        return {"request": request}


@class_route(api_blueprint, "/api/v1/requests", methods=["POST"])
class RequestCreateView(PostView):
    request_validator_model = RequestCreatePayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, RequestCreatePayload)
        payload = self.request_validator_model
        result = generate_request(EntryRequest(raw_title=payload.title))
        if not result["success"]:
            _raise_result_error(result)

        result = apply_request_save_action(
            result,
            payload.save_request,
            storage_dir=_storage_dir(payload.storage_dir),
        )
        if not result["success"]:
            _raise_result_error(result)

        request = result["request"]
        response: dict[str, object] = {
            "request": request,
            "summary": summarize_request(request),
        }
        if "saved_request" in result:
            response["saved_request"] = result["saved_request"]
        return response
