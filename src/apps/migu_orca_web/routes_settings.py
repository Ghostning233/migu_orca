from __future__ import annotations

"""Preferences / corrections (settings-family) API routes (US-191 split).

Migrated from ``views.py`` without behavior change. These endpoints read/write
only non-sensitive user preferences and title corrections through the shared
storage repositories.
"""

from flask import request

from apps.migu_orca_web.autobangumi_probe_service import (
    invalidate_saved_capabilities,
    probe_saved_capabilities,
)
from apps.migu_orca_web.blueprints import api_blueprint
from apps.migu_orca_web.schemas import (
    AutoBangumiConfigDeletePayload,
    AutoBangumiConfigSavePayload,
    CorrectionQuery,
    CorrectionSavePayload,
    PreferenceQuery,
    PreferenceSavePayload,
    SavedAutoBangumiProbePayload,
)
from apps.migu_orca_web.serializers import serialize_autobangumi_connection_summary
from apps.migu_orca_web.services import _storage_dir
from extensions.flask_api import class_route
from extensions.flask_api.views import GetView, PostView
from shared.errors import Stage1Error
from storage_engine.controllers.autobangumi_config_repository import (
    AutoBangumiConfigRepository,
    build_stored_autobangumi_config,
)
from storage_engine.controllers.correction_repository import (
    build_correction_from_api,
    load_corrections,
    save_correction,
    serialize_corrections,
)
from storage_engine.controllers.preference_repository import (
    build_preferences_from_api,
    load_user_preferences,
    save_user_preferences,
    serialize_preferences,
)
from storage_engine.controllers.storage_config import load_storage_config


def _require_json() -> None:
    if request.mimetype != "application/json":
        raise Stage1Error("validation_error", "请求必须使用 application/json", "parse_json")


@class_route(api_blueprint, "/api/v1/settings/autobangumi", methods=["GET"])
class AutoBangumiConfigView(GetView):
    def get_object(self) -> dict[str, object]:
        return serialize_autobangumi_connection_summary(AutoBangumiConfigRepository().load())


@class_route(api_blueprint, "/api/v1/settings/autobangumi", methods=["PUT"])
class AutoBangumiConfigSaveView(PostView):
    request_validator_model = AutoBangumiConfigSavePayload

    def save(self) -> dict[str, object]:
        _require_json()
        assert isinstance(self.request_validator_model, AutoBangumiConfigSavePayload)
        payload = self.request_validator_model
        config = build_stored_autobangumi_config(payload.config.model_dump(exclude_none=True))
        record = AutoBangumiConfigRepository().save(
            config, expected_configuration_revision=payload.expected_configuration_revision
        )
        invalidate_saved_capabilities()
        return serialize_autobangumi_connection_summary(record)

    def put(self) -> object:
        return self.post()


@class_route(api_blueprint, "/api/v1/settings/autobangumi", methods=["DELETE"])
class AutoBangumiConfigDeleteView(PostView):
    request_validator_model = AutoBangumiConfigDeletePayload

    def save(self) -> dict[str, object]:
        _require_json()
        assert isinstance(self.request_validator_model, AutoBangumiConfigDeletePayload)
        payload = self.request_validator_model
        record = AutoBangumiConfigRepository().delete(
            expected_configuration_revision=payload.expected_configuration_revision
        )
        invalidate_saved_capabilities()
        return serialize_autobangumi_connection_summary(record)

    def delete(self) -> object:
        return self.post()


@class_route(api_blueprint, "/api/v1/settings/autobangumi/probe", methods=["POST"])
class SavedAutoBangumiCapabilitiesView(PostView):
    request_validator_model = SavedAutoBangumiProbePayload

    def save(self) -> dict[str, object]:
        _require_json()
        assert isinstance(self.request_validator_model, SavedAutoBangumiProbePayload)
        payload = self.request_validator_model
        capabilities = probe_saved_capabilities(
            AutoBangumiConfigRepository(),
            connection_ref=payload.connection_ref,
            configuration_revision=payload.configuration_revision,
        )
        return capabilities.to_public_dict()


@class_route(api_blueprint, "/api/v1/preferences", methods=["GET"])
class PreferenceView(GetView):
    """Read the saved non-sensitive user preferences (defaults when absent)."""

    request_validator_model = PreferenceQuery

    def get_object(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, PreferenceQuery)
        payload = self.request_validator_model
        config = load_storage_config(_storage_dir(payload.storage_dir))
        preferences = load_user_preferences(config)
        return serialize_preferences(preferences)


@class_route(api_blueprint, "/api/v1/preferences", methods=["POST"])
class PreferenceSaveView(PostView):
    """Save non-sensitive user preferences and return the normalized result."""

    request_validator_model = PreferenceSavePayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, PreferenceSavePayload)
        payload = self.request_validator_model
        if payload.preferences is None:
            raise Stage1Error(
                "validation_error",
                "请提供偏好配置",
                "save_user_preferences",
                {"field": "preferences"},
            )
        preferences = build_preferences_from_api(payload.preferences)
        save_user_preferences(
            load_storage_config(_storage_dir(payload.storage_dir)),
            preferences,
        )
        return serialize_preferences(preferences)


@class_route(api_blueprint, "/api/v1/corrections", methods=["GET"])
class CorrectionView(GetView):
    """Read the saved non-sensitive title corrections (empty when absent)."""

    request_validator_model = CorrectionQuery

    def get_object(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, CorrectionQuery)
        payload = self.request_validator_model
        config = load_storage_config(_storage_dir(payload.storage_dir))
        corrections = load_corrections(config)
        return {"corrections": serialize_corrections(corrections)}


@class_route(api_blueprint, "/api/v1/corrections", methods=["POST"])
class CorrectionSaveView(PostView):
    """Save one non-sensitive title correction and return the normalized list."""

    request_validator_model = CorrectionSavePayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, CorrectionSavePayload)
        payload = self.request_validator_model
        if payload.correction is None:
            raise Stage1Error(
                "validation_error",
                "请提供修正内容",
                "save_correction",
                {"field": "correction"},
            )
        correction = build_correction_from_api(payload.correction)
        config = load_storage_config(_storage_dir(payload.storage_dir))
        save_correction(config, correction)
        return {"corrections": serialize_corrections(load_corrections(config))}
