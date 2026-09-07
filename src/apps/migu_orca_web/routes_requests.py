from __future__ import annotations

"""Requests-family API routes (US-191 split).

Migrated from ``views.py`` without behavior change. URL, methods and endpoint
names are identical; the golden contract tests protect this compatibility.
"""

from ab_engine.controllers.ab_config import build_ab_config
from apps.migu_orca_entry.controllers.entry_controller import (
    _build_history_event,
    _confirmation_history_details,
    apply_ab_submit_action,
    apply_confirmation_action,
    apply_modify_action,
    apply_request_save_action,
    generate_request,
)
from apps.migu_orca_web.blueprints import api_blueprint
from apps.migu_orca_web.contexts import candidate_selection_contexts
from apps.migu_orca_web.drafts import (
    REASON_EVICTED,
    REASON_OK,
    REASON_REPLAYED,
    REASON_REVISION_CONFLICT,
    DraftRead,
    draft_store,
)
from apps.migu_orca_web.schemas import (
    RequestAbSubmitPayload,
    RequestActionPayload,
    RequestCancelPayload,
    RequestCreatePayload,
    RequestDetailQuery,
    RequestListQuery,
    RequestModifyPayload,
    RequestPreviewModifyPayload,
    RequestPreviewSavePayload,
)
from apps.migu_orca_web.serializers import (
    _raise_result_error,
    _sanitize_ab_submit_result,
)
from apps.migu_orca_web.services import (
    _load_ab_result_section,
    _load_history_section,
    _resolve_mikan_config,
    _storage_dir,
)
from extensions.flask_api import class_route
from extensions.flask_api.views import GetView, PostView
from request_engine.controllers.request_controller import (
    PENDING_CONFIRM,
    summarize_request,
)
from shared.errors import Stage1Error
from shared.models import EntryRequest
from shared.season_evidence import attach_selected_candidate_season
from storage_engine.controllers.request_repository import (
    delete_request_snapshot,
    list_request_snapshots,
    load_request_snapshot,
)
from storage_engine.controllers.storage_config import load_storage_config


def _draft_store_error(reason: str, current_revision: int | None = None) -> Stage1Error:
    """Map a DraftStore lookup reason to a stable 409 draft_* error.

    US-194: expired/evicted/replayed/mismatched drafts are state conflicts
    (409) with a Chinese message telling the user to regenerate, never a leak
    of draft content or an absolute path. US-210: a stale ``base_revision`` is
    its own ``draft_revision_conflict`` (the payload/revision are untouched),
    still 409 but with only the current revision in the safe error data
    (US-211: never the draft id or any draft content).
    """
    if reason == REASON_REVISION_CONFLICT:
        details: dict[str, object] = {"field": "base_revision"}
        if current_revision is not None:
            details["current_revision"] = current_revision
        return Stage1Error(
            "draft_revision_conflict",
            "草案已被更新，请基于最新版本重试",
            "compare_and_swap_draft",
            details,
        )
    if reason == REASON_REPLAYED:
        return Stage1Error(
            "draft_replayed",
            "订阅草案已被保存，请勿重复保存",
            "consume_preview_draft",
            {"field": "draft_id"},
        )
    if reason == REASON_EVICTED:
        return Stage1Error(
            "draft_evicted",
            "订阅草案已失效（服务器容量已满），请重新生成",
            "load_preview_draft",
            {"field": "draft_id"},
        )
    # expired / unknown both mean "not usable anymore, regenerate".
    return Stage1Error(
        "draft_expired",
        "订阅草案已过期或不存在，请重新生成",
        "load_preview_draft",
        {"field": "draft_id"},
    )


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
        elif not payload.save_request:
            # US-194: an unsaved draft is server-authoritative. Store it in the
            # bounded draft store and hand the client only an opaque draft_id;
            # preview-modify/preview-save reference this id instead of a
            # client-supplied full Request. The draft itself never enters URL,
            # browser storage, history, logs or screenshots. US-211: the
            # monotonic draft_revision is returned alongside the id so the
            # next modify/save can send it back as base_revision.
            handle = draft_store.issue(request)
            response["draft_id"] = handle.draft_id
            response["draft_revision"] = handle.revision
        return response


@class_route(api_blueprint, "/api/v1/requests/preview-modify", methods=["POST"])
class RequestPreviewModifyView(PostView):
    request_validator_model = RequestPreviewModifyPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, RequestPreviewModifyPayload)
        payload = self.request_validator_model
        # US-194: the server is the authority for unsaved drafts. The client
        # only holds an opaque draft_id and an allowed patch; the authoritative
        # PENDING_CONFIRM draft lives in the bounded draft store and is never
        # trusted from the client. modify_request recomputes per-source seed
        # filters and the selected group's effective seeds without saving, so
        # the UI can show live seed updates before the user saves the draft.
        # US-210/US-211: ``get`` returns the current revision alongside the
        # payload so the modify is a compare-and-swap against the client's
        # ``base_revision``; a stale base is a 409 draft_revision_conflict and
        # never overwrites the newer draft.
        draft_read: DraftRead | None
        draft_read, draft_reason = draft_store.get(payload.draft_id)
        if draft_read is None or draft_reason != REASON_OK:
            raise _draft_store_error(draft_reason)
        result = apply_modify_action(
            {"success": True, "request": draft_read.request, "error": None},
            payload.patch,
        )
        if not result["success"]:
            _raise_result_error(result)
        req = result["request"]
        # CAS against the revision the client observed. On success the
        # server-side draft is replaced atomically and the revision bumps by 1
        # so preview-save persists the exact state the user just reviewed.
        new_revision, swap_reason = draft_store.compare_and_swap(
            payload.draft_id,
            payload.base_revision,
            req,
        )
        if new_revision is None or swap_reason != REASON_OK:
            # Re-read so the safe error data carries the true current revision
            # (a concurrent modify may have bumped it after the first read).
            current_revision = None
            if swap_reason == REASON_REVISION_CONFLICT:
                latest_read, latest_reason = draft_store.get(payload.draft_id)
                if latest_read is not None and latest_reason == REASON_OK:
                    current_revision = latest_read.revision
            raise _draft_store_error(swap_reason, current_revision=current_revision)
        return {
            "request": req,
            "summary": summarize_request(req),
            "draft_id": payload.draft_id,
            "draft_revision": new_revision,
        }


@class_route(api_blueprint, "/api/v1/requests/preview-save", methods=["POST"])
class RequestPreviewSaveView(PostView):
    request_validator_model = RequestPreviewSavePayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, RequestPreviewSavePayload)
        payload = self.request_validator_model
        # US-194: preview-save consumes a valid draft_id once (replay
        # protection). The authoritative draft content never comes from the
        # client; a stale/expired/already-saved id returns a stable 409.
        request, save_reason = draft_store.consume_for_save(payload.draft_id)
        if request is None or save_reason != REASON_OK:
            raise _draft_store_error(save_reason)
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
