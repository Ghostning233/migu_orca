from __future__ import annotations

"""Requests-family API routes (US-191 split).

Migrated from ``views.py`` without behavior change. URL, methods and endpoint
names are identical; the golden contract tests protect this compatibility.
"""

from extensions.flask_api import class_route
from extensions.flask_api.views import GetView, PostView
from apps.migu_orca_entry.controllers.entry_controller import (
    apply_ab_submit_action,
    apply_confirmation_action,
    apply_modify_action,
    apply_request_save_action,
    generate_request,
    _build_history_event,
    _confirmation_history_details,
)
from request_engine.controllers.request_controller import (
    PENDING_CONFIRM,
    summarize_request,
)
from shared.errors import Stage1Error
from shared.models import EntryRequest
from shared.season_evidence import attach_selected_candidate_season

from apps.migu_orca_web.blueprints import api_blueprint
from apps.migu_orca_web.contexts import candidate_selection_contexts
from apps.migu_orca_web.schemas import (
    RequestListQuery,
    RequestDetailQuery,
    RequestCreatePayload,
    RequestActionPayload,
    RequestCancelPayload,
    RequestModifyPayload,
    RequestPreviewModifyPayload,
    RequestPreviewSavePayload,
    RequestAbSubmitPayload,
)
from apps.migu_orca_web.serializers import (
    _raise_result_error,
    _sanitize_ab_submit_result,
)
from apps.migu_orca_web.services import (
    _storage_dir,
    _resolve_mikan_config,
    _load_history_section,
    _load_ab_result_section,
)
from storage_engine.controllers.request_repository import (
    delete_request_snapshot,
    list_request_snapshots,
    load_request_snapshot,
)
from storage_engine.controllers.storage_config import load_storage_config
from ab_engine.controllers.ab_config import build_ab_config


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

    def get_object(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, RequestDetailQuery)
        config = load_storage_config(_storage_dir(self.request_validator_model.storage_dir))
        request_id = self.request_validator_model.request_id
        request = load_request_snapshot(config, request_id)
        return {
            "request": request,
            "history": _load_history_section(config, request_id),
            "ab_result": _load_ab_result_section(config, request_id),
        }


@class_route(api_blueprint, "/api/v1/requests", methods=["POST"])
class RequestCreateView(PostView):
    request_validator_model = RequestCreatePayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, RequestCreatePayload)
        payload = self.request_validator_model
        mikan_config = None
        if payload.source == "mikan":
            mikan_config = _resolve_mikan_config(payload.mikan_config)
        result = generate_request(
            EntryRequest(raw_title=payload.title),
            source_mode="mikan_http" if payload.source == "mikan" else "static_fixture",
            mikan_config=mikan_config,
            mikan_bangumi=payload.mikan_bangumi,
        )
        if not result["success"]:
            _raise_result_error(result)
        matched = result["request"].get("source_info", {}).get("matched_bangumi")
        trusted_hint = None
        if isinstance(matched, dict):
            mikan_url = matched.get("mikan_url")
            if isinstance(mikan_url, str):
                context_found, trusted_hint = candidate_selection_contexts.consume(
                    payload.candidate_context, mikan_url
                )
                if payload.candidate_context is not None and not context_found:
                    raise Stage1Error(
                        "candidate_context_invalid",
                        "候选上下文已失效，请重新搜索并选择合集",
                        "selected_candidate_context",
                        {"field": "candidate_context"},
                    )
        result["request"] = attach_selected_candidate_season(
            result["request"], trusted_hint, payload.season_confirmation
        )

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


@class_route(api_blueprint, "/api/v1/requests/preview-modify", methods=["POST"])
class RequestPreviewModifyView(PostView):
    request_validator_model = RequestPreviewModifyPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, RequestPreviewModifyPayload)
        payload = self.request_validator_model
        # The preview request is an in-memory generated draft (status
        # PENDING_CONFIRM but never written to storage). modify_request
        # recomputes per-source seed filters and the selected group's effective
        # seeds without saving, so the UI can show live seed updates before the
        # user decides to persist the draft.
        result = apply_modify_action(
            {"success": True, "request": payload.request, "error": None},
            payload.patch,
        )
        if not result["success"]:
            _raise_result_error(result)
        req = result["request"]
        return {"request": req, "summary": summarize_request(req)}


@class_route(api_blueprint, "/api/v1/requests/preview-save", methods=["POST"])
class RequestPreviewSaveView(PostView):
    request_validator_model = RequestPreviewSavePayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, RequestPreviewSavePayload)
        payload = self.request_validator_model
        request = payload.request
        # Only a PENDING_CONFIRM draft may be saved; this keeps the saved object
        # entering the existing confirmation flow (accept/cancel/modify/delete).
        if request.get("status") != PENDING_CONFIRM:
            raise Stage1Error(
                "invalid_request_status",
                "只有待确认的订阅草案可以保存",
                "save_preview_request",
                {"status": request.get("status")},
            )
        result = apply_request_save_action(
            {"success": True, "request": request, "error": None},
            True,
            storage_dir=_storage_dir(payload.storage_dir),
        )
        if not result["success"]:
            _raise_result_error(result)
        req = result["request"]
        response: dict[str, object] = {
            "request": req,
            "summary": summarize_request(req),
        }
        if "saved_request" in result:
            response["saved_request"] = result["saved_request"]
        return response


@class_route(api_blueprint, "/api/v1/requests/<path:request_id>/accept", methods=["POST"])
class RequestAcceptView(PostView):
    request_validator_model = RequestActionPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, RequestActionPayload)
        payload = self.request_validator_model
        config = load_storage_config(_storage_dir(payload.storage_dir))
        request = load_request_snapshot(config, payload.request_id)

        result = apply_confirmation_action(
            {"success": True, "request": request, "error": None},
            "accept",
        )
        if not result["success"]:
            _raise_result_error(result)

        history_event = _build_history_event(
            request, result["request"], action="ACCEPT",
        )
        result = apply_request_save_action(
            result,
            True,
            storage_dir=_storage_dir(payload.storage_dir),
            history_events=[history_event],
        )
        if not result["success"]:
            _raise_result_error(result)

        req = result["request"]
        response: dict[str, object] = {
            "request": req,
            "summary": summarize_request(req),
        }
        if "saved_request" in result:
            response["saved_request"] = result["saved_request"]
        return response


@class_route(api_blueprint, "/api/v1/requests/<path:request_id>/cancel", methods=["POST"])
class RequestCancelView(PostView):
    request_validator_model = RequestCancelPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, RequestCancelPayload)
        payload = self.request_validator_model
        config = load_storage_config(_storage_dir(payload.storage_dir))
        request = load_request_snapshot(config, payload.request_id)

        cancel_reason = payload.cancel_reason or "用户取消"
        result = apply_confirmation_action(
            {"success": True, "request": request, "error": None},
            "cancel",
            cancel_reason=cancel_reason,
        )
        if not result["success"]:
            _raise_result_error(result)

        history_event = _build_history_event(
            request, result["request"],
            action="CANCEL",
            details=_confirmation_history_details("cancel", cancel_reason),
        )
        result = apply_request_save_action(
            result,
            True,
            storage_dir=_storage_dir(payload.storage_dir),
            history_events=[history_event],
        )
        if not result["success"]:
            _raise_result_error(result)

        req = result["request"]
        response: dict[str, object] = {
            "request": req,
            "summary": summarize_request(req),
        }
        if "saved_request" in result:
            response["saved_request"] = result["saved_request"]
        return response


@class_route(api_blueprint, "/api/v1/requests/<path:request_id>/modify", methods=["POST"])
class RequestModifyView(PostView):
    request_validator_model = RequestModifyPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, RequestModifyPayload)
        payload = self.request_validator_model
        config = load_storage_config(_storage_dir(payload.storage_dir))
        request = load_request_snapshot(config, payload.request_id)

        result = apply_modify_action(
            {"success": True, "request": request, "error": None},
            payload.patch,
        )
        if not result["success"]:
            _raise_result_error(result)

        history_event = _build_history_event(
            request, result["request"],
            action="MODIFY",
            details={"patch": payload.patch},
        )
        result = apply_request_save_action(
            result,
            True,
            storage_dir=_storage_dir(payload.storage_dir),
            history_events=[history_event],
        )
        if not result["success"]:
            _raise_result_error(result)

        req = result["request"]
        response: dict[str, object] = {
            "request": req,
            "summary": summarize_request(req),
        }
        if "saved_request" in result:
            response["saved_request"] = result["saved_request"]
        return response


@class_route(api_blueprint, "/api/v1/requests/<path:request_id>/delete", methods=["POST"])
class RequestDeleteView(PostView):
    request_validator_model = RequestActionPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, RequestActionPayload)
        payload = self.request_validator_model
        config = load_storage_config(_storage_dir(payload.storage_dir))
        return delete_request_snapshot(config, payload.request_id)


@class_route(api_blueprint, "/api/v1/requests/<path:request_id>/submit-ab", methods=["POST"])
class RequestAbSubmitView(PostView):
    request_validator_model = RequestAbSubmitPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, RequestAbSubmitPayload)
        payload = self.request_validator_model
        storage_dir = _storage_dir(payload.storage_dir)
        config = load_storage_config(storage_dir)
        request = load_request_snapshot(config, payload.request_id)
        ab_config = build_ab_config(payload.ab_config.model_dump(exclude_none=True))

        result = apply_ab_submit_action(
            {"success": True, "request": request, "error": None},
            True,
            ab_config=ab_config,
        )
        if not result["success"]:
            _raise_result_error(result)

        result["ab_submit_result"] = _sanitize_ab_submit_result(
            result["ab_submit_result"]
        )
        result["request"]["ab_submit_result"] = result["ab_submit_result"]
        result = apply_request_save_action(
            result,
            True,
            storage_dir=storage_dir,
        )
        if not result["success"]:
            _raise_result_error(result)

        req = result["request"]
        response: dict[str, object] = {
            "request": req,
            "summary": summarize_request(req),
            "ab_submit_result": result["ab_submit_result"],
        }
        if "saved_request" in result:
            response["saved_request"] = result["saved_request"]
        if "saved_ab_result" in result:
            response["saved_ab_result"] = result["saved_ab_result"]
        return response
