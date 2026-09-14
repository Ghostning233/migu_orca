from __future__ import annotations

"""Batches-family API routes (US-191 split).

Migrated from ``views.py`` without behavior change. The parse view orchestrates
the shared title-parsing / candidate-search / preference-application pipeline;
accept/submit/retry/recover reuse the batch engine services with the storage
seams built in ``services.py``. US-216 adds the batch save-confirm partial-
success endpoint on top of the single save-confirm service.
"""

from dataclasses import replace

from apps.migu_orca_web.blueprints import api_blueprint
from apps.migu_orca_web.routes_requests import _run_draft_save_confirm
from apps.migu_orca_web.save_confirm_service import (
    BATCH_OUTCOME_CONFIRMED,
    BATCH_OUTCOME_FAILED,
    ERROR_TYPE_SAVE_CONFIRM_FAILED,
    BatchSaveConfirmItemResult,
    BatchSaveConfirmResult,
    SaveConfirmOutcome,
    build_batch_process_one,
    run_batch_save_confirm,
    serialize_batch_save_confirm_result,
)
from apps.migu_orca_web.schemas import (
    BatchParsePayload,
    BatchSaveConfirmPayload,
)
from apps.migu_orca_web.serializers import (
    _serialize_attempted_queries,
    _serialize_batch_parse_result,
    _serialize_failed_batch_item,
    _serialize_preference_application,
    _with_candidate_season_evidence,
)
from apps.migu_orca_web.services import (
    _batch_title_parsing_provider,
    _enhanced_entries_for_item,
    _load_corrections_for_batch,
    _load_preferences_for_batch,
    _preference_application_for_item,
    _resolve_mikan_config,
    _search_batch_item_candidates,
    _search_candidates_from_parse_result,
    _storage_dir,
)
from apps.migu_orca_web.tracking_handoff import (
    TrackingHandoff,
    ensure_confirmed_request_tracking,
    unavailable_tracking_handoff,
)
from batch_engine.controllers.anime_title_parser import (
    RuleAnimeTitleParsingProvider,
    parse_anime_title,
)
from batch_engine.controllers.batch_draft_controller import (
    create_batch_draft,
    split_batch_raw_input,
    update_batch_item_status,
)
from batch_engine.controllers.preference_applicator import build_review_metadata
from batch_engine.models import (
    BATCH_ITEM_STATUS_EMPTY,
    BATCH_ITEM_STATUS_FAILED,
    BATCH_ITEM_STATUS_FOUND,
    MAX_BATCH_ITEMS,
)
from extensions.flask_api import class_route
from extensions.flask_api.views import PostView
from shared.errors import Stage1Error
from storage_engine.controllers.request_repository import load_request_snapshot
from storage_engine.controllers.storage_config import StorageConfig, load_storage_config
from tracking_engine.models.tracking import TRACKING_ORIGIN_SAVE_CONFIRM


@class_route(api_blueprint, "/api/v1/batches/parse", methods=["POST"])
class BatchParseView(PostView):
    request_validator_model = BatchParsePayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, BatchParsePayload)
        raw_input = self.request_validator_model.raw_input
        # US-215: count normalized non-empty lines via the same splitter the
        # engine uses. A 37+ line batch is rejected here — before the title
        # parser, MiKan search or any persistence seam — with only the
        # field/limit/actual summary (never echoing the raw batch input).
        non_empty_lines = split_batch_raw_input(raw_input)
        if not non_empty_lines:
            raise Stage1Error(
                "validation_error",
                "请至少输入一个番剧名称",
                "batch_parse",
                {"field": "raw_input"},
            )
        if len(non_empty_lines) > MAX_BATCH_ITEMS:
            raise Stage1Error(
                "batch_limit_exceeded",
                f"单批最多支持 {MAX_BATCH_ITEMS} 部，当前输入 {len(non_empty_lines)} 部",
                "batch_parse",
                {
                    "field": "raw_input",
                    "limit": MAX_BATCH_ITEMS,
                    "actual": len(non_empty_lines),
                },
            )
        batch = create_batch_draft(raw_input)

        mikan_config = _resolve_mikan_config(self.request_validator_model.mikan_config)
        config = load_storage_config(
            _storage_dir(self.request_validator_model.storage_dir)
        )
        preferences = _load_preferences_for_batch(config)
        corrections = _load_corrections_for_batch(config)
        # Keep the explicit provider seam used by batch tests. Saved corrections
        # are part of the same rule-provider query plan rather than a second
        # search fallback implementation.
        provider = (
            RuleAnimeTitleParsingProvider(corrections=corrections)
            if corrections
            else _batch_title_parsing_provider()
        )
        serialized_items: list[dict[str, object]] = []
        for item in batch.items:
            try:
                parse_result = parse_anime_title(item.raw_title, provider)
            except Stage1Error as exc:
                failed_batch = update_batch_item_status(
                    batch,
                    item.item_id,
                    BATCH_ITEM_STATUS_FAILED,
                )
                failed_item = next(
                    updated
                    for updated in failed_batch.items
                    if updated.item_id == item.item_id
                )
                applied_obj, warnings = _preference_application_for_item(
                    item.raw_title, None, preferences
                )
                applied, hits, warnings = _serialize_preference_application(
                    applied_obj, warnings
                )
                review = build_review_metadata(
                    raw_title=item.raw_title,
                    parse_result=None,
                    candidates=[],
                    preference_warnings=warnings,
                    status=BATCH_ITEM_STATUS_FAILED,
                )
                serialized_items.append(
                    _serialize_failed_batch_item(
                        failed_item,
                        exc,
                        applied_preferences=applied,
                        preference_hits=hits,
                        preference_warnings=warnings,
                        review_hints=review.review_hints,
                        enhanced_search_queries=_enhanced_entries_for_item(
                            item.raw_title, None, corrections
                        ),
                    )
                )
                continue

            enhanced_queries = _enhanced_entries_for_item(
                item.raw_title, parse_result, corrections
            )
            searched = _search_candidates_from_parse_result(
                parse_result,
                mikan_config,
                search_one=lambda query: _search_batch_item_candidates([query], mikan_config),
            )
            if searched.status == BATCH_ITEM_STATUS_FAILED:
                exc = searched.error or Stage1Error(
                    "mikan_search_failed", "MiKan 候选搜索失败", "mikan_search"
                )
                failed_batch = update_batch_item_status(
                    batch,
                    item.item_id,
                    BATCH_ITEM_STATUS_FAILED,
                )
                failed_item = next(
                    updated
                    for updated in failed_batch.items
                    if updated.item_id == item.item_id
                )
                applied_obj, warnings = _preference_application_for_item(
                    item.raw_title, parse_result, preferences
                )
                applied, hits, warnings = _serialize_preference_application(
                    applied_obj, warnings
                )
                review = build_review_metadata(
                    raw_title=item.raw_title,
                    parse_result=parse_result,
                    candidates=[],
                    preference_warnings=warnings,
                    search_failed=True,
                    status=BATCH_ITEM_STATUS_FAILED,
                )
                serialized_items.append(
                    _serialize_batch_parse_result(
                        failed_item,
                        parse_result,
                        candidates=[],
                        error=exc,
                        applied_preferences=applied,
                        preference_hits=hits,
                        preference_warnings=warnings,
                        needs_user_review=review.needs_user_review,
                        review_hints=review.review_hints,
                        enhanced_search_queries=enhanced_queries,
                        attempted_queries=_serialize_attempted_queries(parse_result, searched),
                    )
                )
                continue

            candidates = [
                _with_candidate_season_evidence(candidate, parse_result)
                for candidate in searched.candidates
            ]

            candidate_status = (
                BATCH_ITEM_STATUS_FOUND
                if candidates
                else BATCH_ITEM_STATUS_EMPTY
            )
            searched_batch = update_batch_item_status(
                batch,
                item.item_id,
                candidate_status,
            )
            searched_item = next(
                updated
                for updated in searched_batch.items
                if updated.item_id == item.item_id
            )
            applied_obj, warnings = _preference_application_for_item(
                item.raw_title, parse_result, preferences
            )
            applied, hits, warnings = _serialize_preference_application(
                applied_obj, warnings
            )
            review = build_review_metadata(
                raw_title=item.raw_title,
                parse_result=parse_result,
                candidates=candidates,
                preference_warnings=warnings,
                status=candidate_status,
            )
            serialized_items.append(
                _serialize_batch_parse_result(
                    searched_item,
                    parse_result,
                    candidates=candidates,
                    applied_preferences=applied,
                    preference_hits=hits,
                    preference_warnings=warnings,
                    needs_user_review=review.needs_user_review,
                    review_hints=review.review_hints,
                    enhanced_search_queries=enhanced_queries,
                    attempted_queries=_serialize_attempted_queries(parse_result, searched),
                )
            )

        return {
            "batch_id": batch.batch_id,
            "raw_input": batch.raw_input,
            "items": serialized_items,
        }


def _batch_item_save_confirm_error(
    item_id: str, exc: Stage1Error
) -> BatchSaveConfirmItemResult:
    """Map a single save-confirm Stage1Error to a sanitized per-item result.

    Expected per-item failures (stale/expired/reserved/replayed draft,
    idempotency conflict, unexpected error) become a stable ``failed`` result
    whose ``error_type`` is the public draft/idempotency reason. The failed
    branch never echoes the draft_id, the idempotency key, the original title,
    a URL or an absolute path — the client retries a failed item with the same
    draft_id/base_revision (the draft is released and kept on an expected
    failure) or re-generates when the draft is gone.
    """
    # A saved-but-unconfirmed request is a terminal, durable per-item outcome:
    # the Request exists (PENDING_CONFIRM) and the client accepts it through
    # the existing Request accept contract (ACCEPT_SAVED_REQUEST). The per-item
    # failure carries only the public request_id.
    if exc.error_type == ERROR_TYPE_SAVE_CONFIRM_FAILED:
        details = exc.details or {}
        return BatchSaveConfirmItemResult(
            item_id=item_id,
            outcome=BATCH_OUTCOME_FAILED,
            request_id=str(details.get("request_id") or ""),
            error_type=ERROR_TYPE_SAVE_CONFIRM_FAILED,
            error_message="订阅方案已保存但确认失败，请对已保存的方案重试确认",
        )
    return BatchSaveConfirmItemResult(
        item_id=item_id,
        outcome=BATCH_OUTCOME_FAILED,
        error_type=exc.error_type,
        error_message=_sanitize_save_confirm_error_message(exc),
    )


def _sanitize_save_confirm_error_message(exc: Stage1Error) -> str:
    """Return a fixed Chinese message for a per-item save-confirm error.

    Draft-state/idempotency errors map to the same stable copy the single
    endpoint uses, so the frontend can branch without echoing draft content.
    Unexpected/storage errors never surface the raw message (which could hold
    a path or upstream detail).
    """
    return {
        "draft_expired": "订阅草案已过期或不存在，请重新生成",
        "draft_evicted": "订阅草案已失效（服务器容量已满），请重新生成",
        "draft_replayed": "订阅草案已被保存，请勿重复保存",
        "draft_revision_conflict": "草案已被更新，请基于最新版本重试",
        "draft_reserved": "订阅草案正在保存中，请稍后重试",
        "idempotency_conflict": "相同的幂等键不能用于不同的保存确认操作",
        "invalid_request_status": "只有待确认的订阅方案可以保存",
    }.get(exc.error_type, "保存确认失败，请稍后重试")


def _ensure_batch_tracking(
    result: BatchSaveConfirmResult,
    config: StorageConfig,
) -> BatchSaveConfirmResult:
    """Enrich every CONFIRMED batch item with a unified tracking handoff (US-222).

    Each confirmed item enters the tracking list through the same
    create-if-absent ensure the single save-confirm endpoint uses, so retries
    and terminal replays converge on the deterministic tracking_id.  Tracking
    is best-effort per item: a failure never rolls back the confirmed item or a
    sibling, and only sets ``tracking_ready=False`` (recovered on a later
    tracking access).
    """
    updated_items: list[BatchSaveConfirmItemResult] = []
    for item in result.results:
        if item.outcome != BATCH_OUTCOME_CONFIRMED or not item.request_id:
            updated_items.append(item)
            continue
        handoff = _tracking_handoff_for_confirmed_item(config, item.request_id)
        updated_items.append(
            replace(
                item,
                tracking_id=handoff.tracking_id,
                tracking_ready=handoff.tracking_ready,
            )
        )
    return replace(result, results=updated_items)


def _tracking_handoff_for_confirmed_item(
    config: StorageConfig,
    request_id: str,
) -> TrackingHandoff:
    """Return the tracking handoff for one confirmed item, never raising.

    The item is already durably confirmed; the tracking ensure is a best-effort
    side effect that must not turn the batch partial-success result into an
    HTTP failure, so any tracking/load failure maps to a not-ready handoff.
    """
    try:
        request = load_request_snapshot(config, request_id)
    except Exception:  # pragma: no cover - safety boundary
        return unavailable_tracking_handoff(request_id)
    try:
        return ensure_confirmed_request_tracking(
            config=config,
            request=request,
            origin=TRACKING_ORIGIN_SAVE_CONFIRM,
        )
    except Exception:  # pragma: no cover - safety boundary
        return unavailable_tracking_handoff(request_id)


@class_route(api_blueprint, "/api/v1/batches/<batch_id>/save-confirm", methods=["POST"])
class BatchSaveConfirmView(PostView):
    """Save + confirm selected batch draft cards in one partial-success call.

    US-216: every selected card runs the exact single save-confirm use case
    (revision check, reservation, persistence, confirmation, idempotent
    outcome) through ``_run_draft_save_confirm``. Successful items stay
    confirmed and never roll back because a sibling failed; expected per-item
    failures return a stable sanitized per-item ``failed`` result (HTTP 200
    partial success), while request-level shape/storage errors still surface
    through the normal failure envelope. A same-key idempotent retry replays
    the same CONFIRMED outcome and never creates a second Request.
    """

    request_validator_model = BatchSaveConfirmPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, BatchSaveConfirmPayload)
        payload = self.request_validator_model
        storage_dir = _storage_dir(payload.storage_dir)
        config = load_storage_config(storage_dir)

        def process_one_item(
            item_id: str,
            draft_id: str,
            base_revision: int,
            idempotency_key: str,
        ) -> SaveConfirmOutcome:
            return _run_draft_save_confirm(
                draft_id=draft_id,
                base_revision=base_revision,
                idempotency_key=idempotency_key,
                storage_dir=storage_dir,
            )

        process_one = build_batch_process_one(
            process_one_item,
            map_error=_batch_item_save_confirm_error,
        )
        descriptors = [
            (item.item_id, item.draft_id, item.base_revision, item.idempotency_key)
            for item in payload.items
        ]
        result = run_batch_save_confirm(
            batch_id=payload.batch_id,
            items=descriptors,
            item_ids=payload.item_ids,
            process_one=process_one,
        )
        # US-222: every confirmed item also enters the unified tracking list
        # (create-if-absent, so idempotent retries and terminal replays converge
        # on the same deterministic tracking_id).  One item's tracking failure
        # never rolls back its own confirmation or any sibling's.
        result = _ensure_batch_tracking(result, config)
        return serialize_batch_save_confirm_result(result)
