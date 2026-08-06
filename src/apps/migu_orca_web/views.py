from __future__ import annotations

from pathlib import Path

from flask import Blueprint
from pydantic import BaseModel

from extensions.flask_api import class_route
from extensions.flask_api.views import GetView
from request_engine.controllers.request_controller import summarize_request
from storage_engine.controllers.request_repository import (
    list_request_snapshots,
    load_request_snapshot,
)
from storage_engine.controllers.storage_config import load_storage_config

api_blueprint = Blueprint("migu_orca_web_api", __name__)


class RequestListQuery(BaseModel):
    storage_dir: str | None = None


class RequestDetailQuery(BaseModel):
    request_id: str
    storage_dir: str | None = None


def _storage_dir(value: str | None) -> Path | None:
    if value is None or not value.strip():
        return None
    return Path(value.strip())


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
