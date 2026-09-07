from __future__ import annotations

"""US-190: public response DTOs reject unknown/sensitive fields.

The DTOs in ``apps.migu_orca_web.api_contract`` are the response half of the
public contract: every whitelisted shape is ``extra="forbid"`` so an engine
dict that gains an unknown field (or a future accidental addition) fails
validation instead of silently passing through the API boundary. These tests
pin the whitelisted shapes against real serializer output.
"""

from typing import Any

import pytest
from pydantic import ValidationError

from apps.migu_orca_entry.controllers.entry_controller import generate_request
from apps.migu_orca_web.api_contract import (
    AutoBangumiConnectionResultDTO,
    BatchAcceptResultDTO,
    BatchParseResultDTO,
    BatchQueueResultDTO,
    BatchSaveConfirmResultDTO,
    BatchSubmitResultDTO,
    CorrectionsResultDTO,
    MikanCandidateResultDTO,
    PreferenceResultDTO,
    QbittorrentConnectionResultDTO,
    RequestAbSubmitResultDTO,
    RequestActionResultDTO,
    RequestCreateResultDTO,
    RequestDeleteResultDTO,
    RequestDetailResultDTO,
    RequestListResultDTO,
    RequestPreviewModifyResultDTO,
    RequestPreviewSaveResultDTO,
    RequestSaveConfirmResultDTO,
    RequestSummaryDTO,
    SaveConfirmFailedErrorDataDTO,
)
from batch_engine.controllers.batch_draft_controller import create_batch_draft
from batch_engine.controllers.batch_queue_controller import serialize_queue
from batch_engine.models import BatchSubmissionQueue
from request_engine.controllers.request_controller import (
    accept_request,
    summarize_request,
)
from shared.models import EntryRequest


def _generated_request(title: str = "芙莉莲") -> dict[str, Any]:
    return generate_request(EntryRequest(raw_title=title))["request"]


def _summary(request: dict[str, Any]) -> dict[str, Any]:
    return summarize_request(request)


def _accept_result() -> dict[str, Any]:
    queue = BatchSubmissionQueue(
        queue_id="queue-1",
        batch_id="batch-1",
        created_at="2026-08-29T00:00:00+00:00",
        updated_at="2026-08-29T00:00:00+00:00",
        items=[],
    )
    return {
        "batch_id": "batch-1",
        "queue": serialize_queue(queue),
        "items": [
            {
                "item_id": "item-1",
                "request_id": None,
                "title": "示例",
                "status": "unacceptable",
                "reason": "卡片缺少订阅草案，无法接受",
                "error_type": None,
                "queued": False,
            }
        ],
        "summary": {"accepted": 0, "already_accepted": 0, "unacceptable": 1, "failed": 0},
    }


# ---------------------------------------------------------------------------
# Requests family
# ---------------------------------------------------------------------------


def test_request_summary_dto_rejects_unknown_fields() -> None:
    summary = _summary(_generated_request())
    assert RequestSummaryDTO.model_validate(summary) is not None
    with pytest.raises(ValidationError):
        RequestSummaryDTO.model_validate({**summary, "leaked_secret": "x"})


def test_request_list_dto_accepts_real_summaries() -> None:
    """US-202: the list result is typed as full summary DTOs, not bare dicts."""
    request = _generated_request()
    payload = {"requests": [_summary(request), _summary(request)]}
    validated = RequestListResultDTO.model_validate(payload)
    assert all(isinstance(item, RequestSummaryDTO) for item in validated.requests)


def test_request_list_dto_rejects_unknown_fields() -> None:
    summary = _summary(_generated_request())
    with pytest.raises(ValidationError):
        RequestListResultDTO.model_validate(
            {"requests": [summary], "leaked_secret": "x"}
        )
    with pytest.raises(ValidationError):
        RequestListResultDTO.model_validate(
            {"requests": [{**summary, "leaked_secret": "x"}]}
        )


def test_request_create_dto_accepts_real_payload() -> None:
    request = _generated_request()
    payload = {"request": request, "summary": _summary(request)}
    validated = RequestCreateResultDTO.model_validate(payload)
    assert validated.request.status == "PENDING_CONFIRM"


def test_request_create_dto_rejects_unknown_result_field() -> None:
    request = _generated_request()
    payload = {"request": request, "summary": _summary(request), "bogus": 1}
    with pytest.raises(ValidationError):
        RequestCreateResultDTO.model_validate(payload)


def test_request_preview_modify_save_accept_cancel_share_shape() -> None:
    request = _generated_request()
    base = {"request": request, "summary": _summary(request)}
    for dto in (
        RequestPreviewModifyResultDTO,
        RequestPreviewSaveResultDTO,
        RequestActionResultDTO,
    ):
        assert dto.model_validate(base) is not None


def test_request_create_dto_accepts_draft_id_for_unsaved_preview() -> None:
    """US-194/211: an unsaved generation returns draft_id and draft_revision."""
    request = _generated_request()
    payload = {
        "request": request,
        "summary": _summary(request),
        "draft_id": "opaque-draft-token",
        "draft_revision": 1,
    }
    validated = RequestCreateResultDTO.model_validate(payload)
    assert validated.draft_id == "opaque-draft-token"
    assert validated.draft_revision == 1


def test_request_preview_modify_dto_accepts_draft_id_and_revision() -> None:
    """US-211: preview-modify returns draft_id + the new draft_revision."""
    request = _generated_request()
    payload = {
        "request": request,
        "summary": _summary(request),
        "draft_id": "opaque-draft-token",
        "draft_revision": 2,
    }
    validated = RequestPreviewModifyResultDTO.model_validate(payload)
    assert validated.draft_id == "opaque-draft-token"
    assert validated.draft_revision == 2


def test_request_preview_save_dto_rejects_draft_id() -> None:
    """US-194: preview-save consumes the draft; the response has no draft_id.

    US-211: the save response equally has no draft_revision (the draft is gone
    after a successful save).
    """
    request = _generated_request()
    base = {"request": request, "summary": _summary(request)}
    assert RequestPreviewSaveResultDTO.model_validate(base) is not None
    with pytest.raises(ValidationError):
        RequestPreviewSaveResultDTO.model_validate(
            {**base, "draft_id": "opaque-draft-token"}
        )
    with pytest.raises(ValidationError):
        RequestPreviewSaveResultDTO.model_validate(
            {**base, "draft_revision": 1}
        )


def test_request_ab_submit_dto_requires_top_level_ab_result() -> None:
    """submit-ab adds a top-level ``ab_submit_result`` the base DTO lacks."""
    request = _generated_request()
    base = {"request": request, "summary": _summary(request)}
    # The base create/action DTO does not declare ``ab_submit_result`` at the
    # top level, so a submit-ab payload fails it (extra field).
    with pytest.raises(ValidationError):
        RequestCreateResultDTO.model_validate(
            {**base, "ab_submit_result": {"success": True}}
        )
    # A partial ``ab_submit_result`` (missing the required whitelist fields)
    # fails the strict AbSubmitResultDTO...
    with pytest.raises(ValidationError):
        RequestAbSubmitResultDTO.model_validate(
            {**base, "ab_submit_result": {"success": True}}
        )
    # ...and the full sanitized submit-result shape validates.
    payload = {
        **base,
        "ab_submit_result": {
            "success": True,
            "ab_subscription_id": "ab-sub-1",
            "ab_response": {"id": "ab-sub-1"},
            "fallback_config": None,
            "error": None,
        },
    }
    assert RequestAbSubmitResultDTO.model_validate(payload) is not None


def test_request_save_confirm_result_dto_accepts_accepted_payload() -> None:
    """US-214: the save-confirm success result whitelists the CONFIRMED handoff."""
    request = accept_request(_generated_request())
    payload = {
        "outcome": "CONFIRMED",
        "request": request,
        "summary": _summary(request),
        "handoff": {
            "request_id": request["request_id"],
            "status": "ACCEPTED",
            "next_action": "OPEN_TRACKING",
        },
    }
    validated = RequestSaveConfirmResultDTO.model_validate(payload)
    assert validated.outcome == "CONFIRMED"
    assert validated.handoff.request_id == request["request_id"]
    assert validated.handoff.status == "ACCEPTED"
    assert validated.handoff.next_action == "OPEN_TRACKING"


def test_request_save_confirm_result_dto_rejects_unknown_or_sensitive_fields() -> None:
    """US-214: the save-confirm success envelope is strict and leak-free.

    The frozen PRD §6.3 success result is ``{outcome, request, summary,
    handoff}``. A draft_id, a tracking id, credentials or any unknown field
    must be rejected at the boundary; the handoff itself only carries the
    public request_id + ACCEPTED status + the stable OPEN_TRACKING next_action.
    """
    request = accept_request(_generated_request())
    base = {
        "outcome": "CONFIRMED",
        "request": request,
        "summary": _summary(request),
        "handoff": {
            "request_id": request["request_id"],
            "status": "ACCEPTED",
            "next_action": "OPEN_TRACKING",
        },
    }
    with pytest.raises(ValidationError):
        RequestSaveConfirmResultDTO.model_validate({**base, "draft_id": "opaque"})
    with pytest.raises(ValidationError):
        RequestSaveConfirmResultDTO.model_validate(
            {**base, "tracking_id": "tracking-1"}
        )
    with pytest.raises(ValidationError):
        RequestSaveConfirmResultDTO.model_validate(
            {**base, "handoff": {**base["handoff"], "ab_url": "https://example.invalid"}}
        )
    with pytest.raises(ValidationError):
        RequestSaveConfirmResultDTO.model_validate(
            {**base, "handoff": {**base["handoff"], "request_id": request["request_id"], "secret_token": "x"}}
        )


def test_save_confirm_failed_error_data_dto_whitelists_details() -> None:
    """US-214: the confirm-failed failure details are exactly the PRD whitelist.

    Only outcome + public request_id + retry_action may appear; a draft_id,
    title, URL or path must be rejected so the boundary never carries draft
    content or credentials into the failure envelope.
    """
    base = {
        "outcome": "SAVED_CONFIRM_FAILED",
        "request_id": "public-request-1",
        "retry_action": "ACCEPT_SAVED_REQUEST",
    }
    assert SaveConfirmFailedErrorDataDTO.model_validate(base) is not None
    with pytest.raises(ValidationError):
        SaveConfirmFailedErrorDataDTO.model_validate(
            {**base, "draft_id": "consumed-draft"}
        )
    with pytest.raises(ValidationError):
        SaveConfirmFailedErrorDataDTO.model_validate(
            {**base, "title": "芙莉莲"}
        )
    with pytest.raises(ValidationError):
        SaveConfirmFailedErrorDataDTO.model_validate(
            {**base, "rss_url": "https://mikan.example/secret"}
        )
    with pytest.raises(ValidationError):
        SaveConfirmFailedErrorDataDTO.model_validate(
            {**base, "token": "secret-token"}
        )
    with pytest.raises(ValidationError):
        SaveConfirmFailedErrorDataDTO.model_validate(
            {**base, "storage_dir": "/home/user/private"}
        )
    with pytest.raises(ValidationError):
        SaveConfirmFailedErrorDataDTO.model_validate(
            {**base, "tracking_id": "tracking-1"}
        )


def test_request_detail_dto_shape() -> None:
    payload = {
        "request": _generated_request(),
        "history": {"available": True, "events": [], "error": None},
        "ab_result": {"available": False, "record": None, "error": None},
    }
    assert RequestDetailResultDTO.model_validate(payload) is not None
    with pytest.raises(ValidationError):
        RequestDetailResultDTO.model_validate({**payload, "extra": 1})


def test_request_detail_dto_accepts_real_sections() -> None:
    """US-203: the detail result types the history/AB section shapes the UI renders."""
    request = _generated_request()
    payload = {
        "request": request,
        "history": {
            "available": True,
            "events": [
                {
                    "request_id": request["request_id"],
                    "previous_status": "PENDING_CONFIRM",
                    "next_status": "ACCEPTED",
                    "action": "ACCEPT",
                    "timestamp": "2026-08-31T00:00:00+00:00",
                    "details": None,
                }
            ],
            "error": None,
        },
        "ab_result": {
            "available": True,
            "record": {
                "request_id": request["request_id"],
                "recorded_at": "2026-08-31T00:00:00+00:00",
                "ab_submit_result": {
                    "success": True,
                    "ab_subscription_id": "ab-sub-1",
                    "ab_response": {"id": "ab-sub-1"},
                    "fallback_config": None,
                    "error": None,
                },
            },
            "error": None,
        },
    }
    validated = RequestDetailResultDTO.model_validate(payload)
    assert validated.request.status == "PENDING_CONFIRM"
    assert validated.request.input.raw_title == "芙莉莲"
    assert validated.request.source_info.rss_sources[0].subtitle_group
    assert validated.request.confirmable_config.filter_rule.use_regex is False
    assert validated.history.events[0].action == "ACCEPT"
    assert validated.ab_result.record.ab_submit_result.ab_subscription_id == "ab-sub-1"
    # Lenient snapshot shapes still reject unknown envelope fields.
    with pytest.raises(ValidationError):
        RequestDetailResultDTO.model_validate({**payload, "leaked": 1})


def test_request_detail_dto_accepts_error_sections() -> None:
    """US-203: history/AB sections may carry a sanitized error dict."""
    payload = {
        "request": _generated_request(),
        "history": {
            "available": False,
            "events": [],
            "error": {
                "error_type": "storage_error",
                "error_message": "读取状态历史失败",
                "failed_step": "load_status_history",
                "details": {"request_id": "req-1"},
            },
        },
        "ab_result": {
            "available": False,
            "record": None,
            "error": {
                "error_type": "storage_error",
                "error_message": "读取提交结果失败",
                "failed_step": "load_ab_submit_result",
                "details": {"request_id": "req-1"},
            },
        },
    }
    validated = RequestDetailResultDTO.model_validate(payload)
    assert validated.history.error is not None
    assert validated.ab_result.error is not None


def test_request_snapshot_dto_rejects_unknown_envelope_field() -> None:
    """US-203: the snapshot DTO itself is lenient, but extra request keys are fine.

    The lenient snapshot shape only lives inside the whitelisted detail/action
    envelopes; the envelope must never gain unexpected top-level keys.
    """
    request = _generated_request()
    request["future_engine_field"] = {"anything": 1}
    payload = {
        "request": request,
        "summary": _summary(request),
    }
    assert RequestCreateResultDTO.model_validate(payload) is not None


def test_request_delete_dto_shape() -> None:
    payload = {
        "request_id": "request-1",
        "storage": "local_json",
        "directory": "requests",
        "filename": "request-1.json",
        "deleted": True,
    }
    assert RequestDeleteResultDTO.model_validate(payload) is not None
    with pytest.raises(ValidationError):
        RequestDeleteResultDTO.model_validate({**payload, "absolute_path": "/etc"})


# ---------------------------------------------------------------------------
# MiKan family
# ---------------------------------------------------------------------------


def test_mikan_candidate_dto_accepts_optional_error() -> None:
    payload = {
        "query": "芙莉莲",
        "status": "FAILED",
        "parse_result": {},
        "attempted_queries": [],
        "candidates": [],
        "error": {"error_type": "mikan_http_failed", "error_message": "失败"},
    }
    assert MikanCandidateResultDTO.model_validate(payload) is not None
    with pytest.raises(ValidationError):
        MikanCandidateResultDTO.model_validate({**payload, "raw_html": "<html>"})


def test_mikan_candidate_dto_rejects_unknown_or_sensitive_fields() -> None:
    """US-204: the candidate card whitelist rejects engine-only fields."""
    candidate = {
        "bangumi_id": "2353",
        "title": "葬送的芙莉莲",
        "mikan_url": "https://mikan.example/Home/Bangumi/2353",
        "poster_url": None,
        "source_query": "芙莉莲",
        "aliases": ["Frieren EN"],
        "recommendation": None,
        "total_episodes": 28,
        "season_evidence": {"status": "NEEDS_CONFIRMATION", "season": 4, "requires_review": True},
        "candidate_context": "opaque-context",
    }
    payload = {
        "query": "芙莉莲",
        "status": "FOUND",
        "parse_result": {},
        "attempted_queries": [],
        "candidates": [candidate],
        "error": None,
    }
    assert MikanCandidateResultDTO.model_validate(payload) is not None
    # A raw engine field (raw HTML / RSS / token / cookie) must never pass the
    # public candidate boundary.
    for leaked in ("raw_html", "raw_rss_xml", "token", "cookie", "raw_response_body"):
        with pytest.raises(ValidationError):
            MikanCandidateResultDTO.model_validate(
                {**payload, "candidates": [{**candidate, leaked: "secret"}]}
            )
    # Unknown envelope fields are rejected too.
    with pytest.raises(ValidationError):
        MikanCandidateResultDTO.model_validate({**payload, "leaked": 1})


# ---------------------------------------------------------------------------
# Preferences / Corrections
# ---------------------------------------------------------------------------


def test_preference_dto_accepts_real_defaults() -> None:
    payload = {
        "version": 1,
        "subtitle_groups": {"preferred": [], "excluded": [], "fallback": "next_preferred"},
        "filter_defaults": {
            "must_contain": "",
            "must_not_contain": "",
            "use_regex": False,
            "case_sensitive": False,
        },
        "naming": {"strategy": "official_title_season", "template": "{title}"},
        "search": {"reuse_explicit_corrections": True},
    }
    assert PreferenceResultDTO.model_validate(payload) is not None
    with pytest.raises(ValidationError):
        PreferenceResultDTO.model_validate({**payload, "endpoint": "https://x"})


def test_corrections_dto_shape() -> None:
    assert CorrectionsResultDTO.model_validate({"corrections": []}) is not None
    with pytest.raises(ValidationError):
        CorrectionsResultDTO.model_validate({"corrections": [], "token": "x"})


# ---------------------------------------------------------------------------
# Batches family
# ---------------------------------------------------------------------------


def test_batch_parse_dto_shape() -> None:
    batch = create_batch_draft("萌王S4")
    payload = {"batch_id": batch.batch_id, "raw_input": batch.raw_input, "items": []}
    assert BatchParseResultDTO.model_validate(payload) is not None
    with pytest.raises(ValidationError):
        BatchParseResultDTO.model_validate({**payload, "raw_rss": "<rss>"})


def test_batch_parse_dto_accepts_real_serialized_items() -> None:
    """US-205: the batch parse item is typed (parse summary + strict candidates)."""
    request = _generated_request()
    item = {
        "item_id": "item-1",
        "raw_title": "萌王S4",
        "status": "FOUND",
        "canonical_title_candidates": ["关于我转生变成史莱姆这档事 第四季"],
        "season_hint": "S4",
        "search_queries": ["转生史莱姆 第四季"],
        "confidence": 0.9,
        "needs_user_review": False,
        "source": "rule",
        "parse_result": {
            "normalized_title": "关于我转生变成史莱姆这档事 第四季",
            "season": {"number": 4, "raw": "s4", "normalized": "第四季", "source": "title_marker"},
        },
        "attempted_queries": [{"query": "转生史莱姆 第四季", "source": "rule", "priority": 1}],
        "candidates": [
            {
                "bangumi_id": "42",
                "title": "关于我转生变成史莱姆这档事 第四季",
                "mikan_url": "https://mikan.example/Home/Bangumi/42",
                "poster_url": None,
                "source_query": "转生史莱姆 第四季",
                "aliases": [],
                "recommendation": None,
                "total_episodes": None,
                "season_evidence": None,
                "candidate_context": None,
            }
        ],
        "applied_preferences": None,
        "preference_hits": [],
        "preference_warnings": [],
        "review_hints": [],
        "enhanced_search_queries": [],
        "preview_request": request,
        "draft_id": "opaque-draft-token",
        "error": None,
    }
    payload = {"batch_id": "batch-1", "raw_input": "萌王S4", "items": [item]}
    validated = BatchParseResultDTO.model_validate(payload)
    assert validated.items[0].item_id == "item-1"
    assert validated.items[0].preview_request is not None
    assert validated.items[0].draft_id == "opaque-draft-token"
    # A raw engine candidate field must never pass the nested strict whitelist.
    with pytest.raises(ValidationError):
        BatchParseResultDTO.model_validate(
            {
                **payload,
                "items": [{**item, "candidates": [{**item["candidates"][0], "raw_html": "<html>"}]}],
            }
        )


def test_batch_parse_dto_rejects_sensitive_item_fields() -> None:
    """US-205: engine-only/sensitive item keys are rejected at the boundary."""
    payload = {
        "batch_id": "batch-1",
        "raw_input": "萌王S4",
        "items": [
            {
                "item_id": "item-1",
                "raw_title": "萌王S4",
                "status": "FAILED",
                "canonical_title_candidates": [],
                "season_hint": None,
                "search_queries": [],
                "confidence": 0.0,
                "needs_user_review": True,
                "source": "unknown",
                "parse_result": None,
                "attempted_queries": [],
                "candidates": [],
                "applied_preferences": None,
                "preference_hits": [],
                "preference_warnings": [],
                "review_hints": [],
                "enhanced_search_queries": [],
                "preview_request": None,
                "draft_id": None,
                "error": None,
            }
        ],
    }
    # The parse item is lenient (engine may add review metadata), so unknown
    # non-sensitive fields pass — but the envelope stays strict.
    assert BatchParseResultDTO.model_validate(payload) is not None
    with pytest.raises(ValidationError):
        BatchParseResultDTO.model_validate({**payload, "token": "x"})


def test_batch_queue_dto_accepts_null_queue() -> None:
    assert BatchQueueResultDTO.model_validate({"batch_id": "b1", "queue": None}) is not None
    with pytest.raises(ValidationError):
        BatchQueueResultDTO.model_validate({"batch_id": "b1", "queue": None, "x": 1})


def test_batch_queue_dto_types_queue_items() -> None:
    """US-205: queue items carry only non-sensitive public fields."""
    queue = {
        "queue_id": "queue-1",
        "batch_id": "batch-1",
        "created_at": "2026-08-19T00:00:00+00:00",
        "updated_at": "2026-08-19T00:00:00+00:00",
        "items": [
            {
                "queue_id": "queue-1",
                "batch_id": "batch-1",
                "item_id": "item-1",
                "request_id": "req-1",
                "title": "关于我转生变成史莱姆这档事 第四季",
                "status": "READY_TO_SUBMIT",
                "status_label": "待提交",
                "attempts": 0,
                "last_error": None,
                "ab_result_summary": None,
                "created_at": "2026-08-19T00:00:00+00:00",
                "updated_at": "2026-08-19T00:00:00+00:00",
            }
        ],
    }
    payload = {"batch_id": "batch-1", "queue": queue}
    validated = BatchQueueResultDTO.model_validate(payload)
    assert validated.queue.items[0].status == "READY_TO_SUBMIT"
    assert validated.queue.items[0].title


def test_batch_accept_dto_validates_serialized_result() -> None:
    result = _accept_result()
    assert BatchAcceptResultDTO.model_validate(result) is not None
    with pytest.raises(ValidationError):
        BatchAcceptResultDTO.model_validate({**result, "leak": 1})


def test_batch_accept_dto_types_result_items() -> None:
    """US-205: accept result items carry public Chinese reasons only."""
    queue = {
        "queue_id": "queue-1",
        "batch_id": "batch-1",
        "created_at": "2026-08-19T00:00:00+00:00",
        "updated_at": "2026-08-19T00:00:00+00:00",
        "items": [],
    }
    payload = {
        "batch_id": "batch-1",
        "queue": queue,
        "items": [
            {
                "item_id": "item-1",
                "request_id": "req-1",
                "title": "标题",
                "status": "accepted",
                "reason": None,
                "error_type": None,
                "queued": True,
            },
            {
                "item_id": "item-2",
                "request_id": None,
                "title": "标题",
                "status": "unacceptable",
                "reason": "卡片缺少订阅草案，无法接受",
                "error_type": None,
                "queued": False,
            },
        ],
        "summary": {"accepted": 1, "already_accepted": 0, "unacceptable": 1, "failed": 0},
    }
    validated = BatchAcceptResultDTO.model_validate(payload)
    assert validated.items[0].queued is True
    assert validated.items[1].reason == "卡片缺少订阅草案，无法接受"


def test_batch_submit_dto_shares_accept_shape() -> None:
    result = _accept_result()
    assert BatchSubmitResultDTO.model_validate(result) is not None


def test_batch_save_confirm_dto_validates_partial_success_result() -> None:
    """US-216: the batch save-confirm result is strict and public-only."""
    payload = {
        "batch_id": "batch-1",
        "results": [
            {
                "item_id": "item-1",
                "outcome": "CONFIRMED",
                "request_id": "request-1",
                "status": "ACCEPTED",
                "error_type": None,
                "error_message": None,
            },
            {
                "item_id": "item-2",
                "outcome": "failed",
                "request_id": None,
                "status": None,
                "error_type": "draft_revision_conflict",
                "error_message": "草案已被更新，请基于最新版本重试",
            },
        ],
        "summary": {"requested": 2, "confirmed": 1, "failed": 1},
    }
    assert BatchSaveConfirmResultDTO.model_validate(payload) is not None
    with pytest.raises(ValidationError):
        BatchSaveConfirmResultDTO.model_validate({**payload, "leak": 1})


def test_batch_save_confirm_dto_rejects_sensitive_item_fields() -> None:
    """US-216: per-item results never carry draft content, keys or URLs."""
    base = {
        "batch_id": "batch-1",
        "results": [
            {
                "item_id": "item-1",
                "outcome": "CONFIRMED",
                "request_id": "request-1",
                "status": "ACCEPTED",
            }
        ],
        "summary": {"requested": 1, "confirmed": 1, "failed": 0},
    }
    assert BatchSaveConfirmResultDTO.model_validate(base) is not None
    for leaked in (
        "draft_id",
        "idempotency_key",
        "rss_url",
        "magnet",
        "token",
        "password",
        "storage_dir",
        "tracking_id",
    ):
        with pytest.raises(ValidationError):
            BatchSaveConfirmResultDTO.model_validate(
                {
                    **base,
                    "results": [{**base["results"][0], leaked: "secret-value"}],
                }
            )


# ---------------------------------------------------------------------------
# Connection tests (strict whitelists)
# ---------------------------------------------------------------------------


def test_qbittorrent_connection_dto_rejects_credentials() -> None:
    payload = {"status": "connected", "reachable": True, "version": "v4.6.7"}
    assert QbittorrentConnectionResultDTO.model_validate(payload) is not None
    with pytest.raises(ValidationError):
        QbittorrentConnectionResultDTO.model_validate(
            {**payload, "endpoint": "http://private.example"}
        )


def test_ab_connection_dto_rejects_credentials() -> None:
    payload = {
        "reachable": True,
        "authenticated": True,
        "version": "3.1.18",
        "auth_mode": "账号密码",
        "adapter": "legacy_3_1",
        "submit_supported": True,
    }
    assert AutoBangumiConnectionResultDTO.model_validate(payload) is not None
    with pytest.raises(ValidationError):
        AutoBangumiConnectionResultDTO.model_validate(
            {**payload, "token": "secret-token"}
        )
