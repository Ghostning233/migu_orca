from __future__ import annotations

import inspect
from typing import Any

from flask import request
from pydantic import BaseModel

from extensions.flask_api.api import APIBaseView, ok_response


class MethodApiBaseView(APIBaseView):
    """Base view with optional Pydantic request validation."""

    request_validator_model: type[BaseModel] | BaseModel | None = None

    def _validate_request_data(self, path_data: dict[str, Any]) -> None:
        validator = self.request_validator_model
        if not (inspect.isclass(validator) and issubclass(validator, BaseModel)):
            self.request_validator_model = None
            return

        request_data = self._get_request_data()
        request_data.update(path_data)
        self.request_validator_model = validator.model_validate(request_data)

    def _get_request_data(self) -> dict[str, Any]:
        data = self.parse_json()
        for key, value in request.args.items():
            data[key] = value
        return data

    @classmethod
    def parse_json(cls) -> dict[str, Any]:
        if not request.data:
            return {}
        payload = request.get_json(silent=True)
        if isinstance(payload, dict):
            return payload
        return {}


class GetView(MethodApiBaseView):
    """GET view base that returns `get_object()` in the shared envelope."""

    @classmethod
    def parse_json(cls) -> dict[str, Any]:
        return {}

    def get(self, *args: Any, **kwargs: Any) -> Any:
        self._validate_request_data(kwargs)
        return self.response(self.get_object())

    def get_object(self) -> Any:
        raise NotImplementedError

    def response(self, target_object: Any) -> Any:
        return ok_response({} if target_object is None else target_object)


class PostView(MethodApiBaseView):
    """POST view base that validates request JSON and returns `save()`."""

    def post(self, *args: Any, **kwargs: Any) -> Any:
        self._validate_request_data(kwargs)
        return self.response(self.save())

    def save(self) -> Any:
        raise NotImplementedError

    def response(self, saved_object: Any) -> Any:
        return ok_response({} if saved_object is None else saved_object)
