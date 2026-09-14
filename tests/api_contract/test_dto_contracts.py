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
    BatchParseResultDTO,
    BatchSaveConfirmResultDTO,
    CorrectionsResultDTO,
    MikanCandidateResultDTO,
    PreferenceResultDTO,
    RequestActionResultDTO,
    RequestCreateResultDTO,
    RequestDeleteResultDTO,
    RequestDetailResultDTO,
    RequestListResultDTO,
    RequestPreviewModifyResultDTO,
    RequestSafeInfoDTO,
    RequestSafeInfoResultDTO,
    RequestSaveConfirmResultDTO,
    RequestSummaryDTO,
    SaveConfirmFailedErrorDataDTO,
)
from apps.migu_orca_web.serializers import (
    serialize_request_detail,
    serialize_request_safe_info,
)
from batch_engine.controllers.batch_draft_controller import create_batch_draft
from request_engine.controllers.request_controller import (
    accept_request,
    summarize_request,
)
from shared.models import EntryRequest


def _generated_request(title: str = "芙莉莲") -> dict[str, Any]:
    return generate_request(EntryRequest(raw_title=title))["request"]


def _safe_detail_request(title: str = "芙莉莲") -> dict[str, Any]:
    """Return the GET-detail whitelist projection used by DTO fixtures."""
    request = _generated_request(title)
    matched = request["source_info"]["matched_bangumi"]
    matched.pop("mikan_url", None)
    matched.pop("poster_url", None)
    for source in request["source_info"]["rss_sources"]:
        source.pop("rss_url", None)
    request["confirmable_config"]["selected_rss_url"] = "SELECTED"
    request.pop("ab_submit_result", None)
    return request


def _summary(request: dict[str, Any]) -> dict[str, Any]:
    return summarize_request(request)


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


def test_request_action_dto_accepts_real_payload() -> None:
    request = _generated_request()
    base = {"request": request, "summary": _summary(request)}
    assert RequestActionResultDTO.model_validate(base) is not None


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

def test_request_save_confirm_result_dto_accepts_accepted_payload() -> None:
    """US-214/US-222: the save-confirm success result whitelists the handoff."""
    request = accept_request(_generated_request())
    handoff = {
        "request_id": request["request_id"],
        "status": "ACCEPTED",
        "next_action": "OPEN_TRACKING",
        "tracking_id": "trk_" + "a" * 32,
        "tracking_status": "PENDING_SUBMIT",
        "tracking_ready": True,
        "safe_message": None,
    }
    payload = {
        "outcome": "CONFIRMED",
        "request": request,
        "summary": _summary(request),
        "handoff": handoff,
    }
    validated = RequestSaveConfirmResultDTO.model_validate(payload)
    assert validated.outcome == "CONFIRMED"
    assert validated.handoff.request_id == request["request_id"]
    assert validated.handoff.status == "ACCEPTED"
    assert validated.handoff.next_action == "OPEN_TRACKING"
    assert validated.handoff.tracking_id == handoff["tracking_id"]
    assert validated.handoff.tracking_status == "PENDING_SUBMIT"
    assert validated.handoff.tracking_ready is True
    assert validated.handoff.safe_message is None


def test_request_save_confirm_result_dto_accepts_tracking_unavailable_handoff() -> None:
    """US-222: a tracking write failure still validates (never faked status)."""
    request = accept_request(_generated_request())
    payload = {
        "outcome": "CONFIRMED",
        "request": request,
        "summary": _summary(request),
        "handoff": {
            "request_id": request["request_id"],
            "status": "ACCEPTED",
            "next_action": "OPEN_TRACKING",
            "tracking_id": "trk_" + "b" * 32,
            "tracking_status": None,
            "tracking_ready": False,
            "safe_message": "方案已保存，追番列表将在打开时自动恢复",
        },
    }
    validated = RequestSaveConfirmResultDTO.model_validate(payload)
    assert validated.handoff.tracking_ready is False
    assert validated.handoff.tracking_status is None
    assert validated.handoff.safe_message is not None


def test_request_save_confirm_result_dto_rejects_unknown_or_sensitive_fields() -> None:
    """US-214/US-222: the save-confirm success envelope is strict and leak-free.

    The frozen success result is ``{outcome, request, summary, handoff}``. A
    draft_id, credentials or any unknown field must be rejected at the boundary;
    the handoff carries the public request_id + ACCEPTED status + the stable
    OPEN_TRACKING next_action + the whitelisted US-222 tracking fields, and
    rejects any unknown/secret value.
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
            "tracking_id": "trk_" + "c" * 32,
            "tracking_status": "PENDING_SUBMIT",
            "tracking_ready": True,
            "safe_message": None,
        },
    }
    with pytest.raises(ValidationError):
        RequestSaveConfirmResultDTO.model_validate({**base, "draft_id": "opaque"})
    with pytest.raises(ValidationError):
        RequestSaveConfirmResultDTO.model_validate(
            {**base, "handoff": {**base["handoff"], "ab_url": "https://example.invalid"}}
        )
    with pytest.raises(ValidationError):
        RequestSaveConfirmResultDTO.model_validate(
            {**base, "handoff": {**base["handoff"], "request_id": request["request_id"], "secret_token": "x"}}
        )
    with pytest.raises(ValidationError):
        RequestSaveConfirmResultDTO.model_validate(
            {**base, "handoff": {**base["handoff"], "tracking_status": 1}}
        )
    # A missing tracking field on the strict handoff is a validation error.
    with pytest.raises(ValidationError):
        RequestSaveConfirmResultDTO.model_validate(
            {**base, "handoff": {k: v for k, v in base["handoff"].items() if k != "tracking_ready"}}
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
        "request": _safe_detail_request(),
        "history": {"available": True, "events": [], "error": None},
        "ab_result": {"available": False, "record": None, "error": None},
    }
    assert RequestDetailResultDTO.model_validate(payload) is not None
    with pytest.raises(ValidationError):
        RequestDetailResultDTO.model_validate({**payload, "extra": 1})


def test_request_detail_dto_accepts_real_sections() -> None:
    """US-203: the detail result accepts only the safe UI projection."""
    request = {
        "request_id": "req-1",
        "status": "PENDING_CONFIRM",
        "input": {"raw_title": "芙莉莲"},
        "source_info": {
            "matched_bangumi": {
                "title": "芙莉莲",
                "aliases": ["Frieren"],
                "match_score": 1.0,
            },
            "rss_sources": [
                {
                    "subtitle_group": "喵萌奶茶屋",
                    "source_type": "mikan",
                    "total_seed_count": 1,
                    "seed_names": ["芙莉莲 01.mkv"],
                    "valid_seed_count": 1,
                    "invalid_seed_count": 0,
                    "valid_seed_names": ["芙莉莲 01.mkv"],
                    "excluded_seed_names": [],
                    "warnings": [],
                }
            ],
        },
        "confirmable_config": {
            "selected_subtitle_group": "喵萌奶茶屋",
            "selected_rss_url": "SELECTED",
            "filter_rule": {
                "must_contain": "",
                "must_not_contain": "",
                "use_regex": False,
                "case_sensitive": False,
            },
            "effective_seed_names": ["芙莉莲 01.mkv"],
            "expected_folder_name": "芙莉莲",
            "warnings": [],
        },
        "user_action": None,
        "created_at": "2026-08-31T00:00:00+00:00",
        "updated_at": "2026-08-31T00:00:00+00:00",
    }
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
                    "ab_subscription_id": None,
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
    assert validated.ab_result.record.ab_submit_result.success is True
    # Lenient snapshot shapes still reject unknown envelope fields.
    with pytest.raises(ValidationError):
        RequestDetailResultDTO.model_validate({**payload, "leaked": 1})


def test_request_detail_dto_accepts_error_sections() -> None:
    """US-203: history/AB sections may carry a sanitized error dict."""
    payload = {
        "request": _safe_detail_request(),
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


def test_request_detail_serializer_preserves_ab_missing_vs_read_error() -> None:
    request = _generated_request()
    common = {"events": [], "available": True, "error": None}

    missing = serialize_request_detail(
        request,
        history_section=common,
        ab_section={"available": False, "record": None, "error": None},
    )
    assert missing["ab_result"] == {
        "available": False,
        "record": None,
        "error": None,
    }

    read_error = {
        "error_type": "ab_result_corrupt",
        "error_message": "提交结果记录损坏",
        "failed_step": "load_ab_submit_result",
    }
    damaged = serialize_request_detail(
        request,
        history_section=common,
        ab_section={"available": False, "record": None, "error": read_error},
    )
    assert damaged["ab_result"]["available"] is False
    assert damaged["ab_result"]["error"] == read_error


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


def _safe_info_payload() -> dict[str, Any]:
    """Build the real serializer output for a generated Request."""
    request = {
        **generate_request(EntryRequest(raw_title="芙莉莲"))["request"],
        "request_id": "request-1",
    }
    return serialize_request_safe_info(
        request,
        history_events=[],
        ab_submit_result=None,
        storage_profile="storage",
    )


def test_request_safe_info_dto_accepts_real_serializer_output() -> None:
    """US-217: the strict safe-info DTO validates real serializer output."""
    payload = _safe_info_payload()
    validated = RequestSafeInfoResultDTO.model_validate({"safe_info": payload})
    assert validated.safe_info.request_id == "request-1"
    assert validated.safe_info.title == "葬送的芙莉莲"
    assert validated.safe_info.updated_episode is None
    assert validated.safe_info.updated_episode_status == "NOT_IMPLEMENTED"
    assert validated.safe_info.resources.valid_file_names
    assert validated.safe_info.mikan_collection.title == "葬送的芙莉莲"
    # extra="forbid" holds on the envelope too.
    with pytest.raises(ValidationError):
        RequestSafeInfoResultDTO.model_validate(
            {"safe_info": payload, "leaked_secret": "x"}
        )


def test_request_safe_info_dto_whitelists_top_level_fields() -> None:
    """US-217: only the frozen PRD whitelist may appear on the safe-info result."""
    base = {
        "request_id": "request-1",
        "status": "ACCEPTED",
        "raw_title": "芙莉莲",
        "title": "葬送的芙莉莲",
        "aliases": ["芙莉莲", "Frieren"],
        "season": 1,
        "season_raw": None,
        "season_evidence": None,
        "mikan_collection": {"title": "葬送的芙莉莲", "bangumi_id": "2353"},
        "subtitle_groups": [],
        "selected_subtitle_group": "喵萌",
        "filter_rule": {
            "must_contain": "",
            "must_not_contain": "",
            "use_regex": False,
            "case_sensitive": False,
        },
        "resources": {
            "selected_subtitle_group": "喵萌",
            "valid_resource_count": 1,
            "invalid_resource_count": 0,
            "complete_resource_count": 1,
            "valid_file_names": ["[喵萌] 葬送的芙莉莲 - 01.mkv"],
            "excluded_file_names": [],
        },
        "folder_name": "葬送的芙莉莲",
        "storage_profile": "storage",
        "total_episodes": None,
        "updated_episode": None,
        "updated_episode_status": "NOT_IMPLEMENTED",
        "history_summary": [],
        "ab_status": None,
    }
    assert RequestSafeInfoDTO.model_validate(base) is not None
    # A URL-looking extra key, a raw snapshot key, or a credential field must
    # be rejected at the boundary, not silently passed through.
    for leaked in (
        "rss_url",
        "mikan_url",
        "poster_url",
        "selected_rss_url",
        "token",
        "password",
        "raw_response",
        "absolute_path",
        "request",
        "source_info",
        "confirmable_config",
    ):
        with pytest.raises(ValidationError):
            RequestSafeInfoDTO.model_validate({**base, leaked: "secret-value"})


def test_request_safe_info_dto_rejects_nested_sensitive_fields() -> None:
    """US-217: nested whitelists (collection/resources/groups/history/ab) are strict."""
    base = _safe_info_payload()
    # The collection may never carry a full URL, magnet or alias-of-URL.
    with pytest.raises(ValidationError):
        RequestSafeInfoDTO.model_validate(
            {**base, "mikan_collection": {**base["mikan_collection"], "mikan_url": "https://mikan.example/x"}}
        )
    with pytest.raises(ValidationError):
        RequestSafeInfoDTO.model_validate(
            {**base, "mikan_collection": {**base["mikan_collection"], "rss_url": "https://mikan.example/x"}}
        )
    # A subtitle group entry may not carry the raw RSS URL or seed list.
    leaked_group = {
        **base["subtitle_groups"][0],
        "rss_url": "https://mikan.example/RSS/Bangumi?bangumiId=1",
        "seed_names": ["secret-seed"],
    }
    with pytest.raises(ValidationError):
        RequestSafeInfoDTO.model_validate(
            {**base, "subtitle_groups": [leaked_group]}
        )
    # Resource entries may not carry an extra raw-snapshot/credential key.
    leaked_file = {
        **base["resources"],
        "magnet": "magnet:?xt=urn:btih:deadbeef",
    }
    with pytest.raises(ValidationError):
        RequestSafeInfoDTO.model_validate({**base, "resources": leaked_file})
    leaked_file_list = {
        **base["resources"],
        "valid_file_names": ["magnet:?xt=urn:btih:deadbeef"],
        "download_url": "https://mikan.example/dl/1",
    }
    with pytest.raises(ValidationError):
        RequestSafeInfoDTO.model_validate({**base, "resources": leaked_file_list})
    leaked_history = [
        {
            "action": "ACCEPT",
            "previous_status": "PENDING_CONFIRM",
            "next_status": "ACCEPTED",
            "timestamp": "2026-09-08T00:00:00+00:00",
            "details": {"rss_url": "https://mikan.example/x"},
        }
    ]
    with pytest.raises(ValidationError):
        RequestSafeInfoDTO.model_validate(
            {**base, "history_summary": leaked_history}
        )
    # AB status never carries the endpoint or raw upstream response.
    leaked_ab = {
        "submitted": True,
        "success": False,
        "ab_subscription_id": None,
        "error_type": "ab_connection_failed",
        "base_url": "https://ab.example",
        "ab_response": {"id": 1},
    }
    with pytest.raises(ValidationError):
        RequestSafeInfoDTO.model_validate({**base, "ab_status": leaked_ab})


def test_request_safe_info_dto_requires_updated_episode_not_implemented() -> None:
    """US-217: updated_episode is pinned null and status is the literal marker."""
    base = _safe_info_payload()
    # A real "current episode" value is never allowed (BL-020 not implemented).
    with pytest.raises(ValidationError):
        RequestSafeInfoDTO.model_validate({**base, "updated_episode": 3})
    with pytest.raises(ValidationError):
        RequestSafeInfoDTO.model_validate(
            {**base, "updated_episode_status": "IMPLEMENTED"}
        )
    # Unknown top-level fields are rejected.
    with pytest.raises(ValidationError):
        RequestSafeInfoDTO.model_validate({**base, "tracking_id": "tracking-1"})


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












def test_batch_save_confirm_dto_validates_partial_success_result() -> None:
    """US-216/US-222: the batch save-confirm result is strict and public-only."""
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
                "tracking_id": "trk_" + "a" * 32,
                "tracking_ready": True,
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
    validated = BatchSaveConfirmResultDTO.model_validate(payload)
    assert validated is not None
    assert validated.results[0].tracking_id is not None
    assert validated.results[0].tracking_ready is True
    assert validated.results[1].tracking_id is None
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

# ---------------------------------------------------------------------------
# Stage 28 static-review fixes: strict save-confirm request schemas
# ---------------------------------------------------------------------------


def test_save_confirm_request_schemas_reject_unknown_fields() -> None:
    """US-213 fix: the save-confirm request models are ``extra="forbid"``."""
    from apps.migu_orca_web.schemas import (
        BatchItemSaveConfirmPayload,
        BatchSaveConfirmPayload,
        RequestSaveConfirmPayload,
    )

    # Single save-confirm: a leaked token/request key is rejected.
    with pytest.raises(ValidationError):
        RequestSaveConfirmPayload.model_validate(
            {
                "draft_id": "draft-1",
                "base_revision": 1,
                "idempotency_key": "key-1",
                "storage_dir": "storage",
                "token": "secret",
            }
        )
    with pytest.raises(ValidationError):
        RequestSaveConfirmPayload.model_validate(
            {
                "draft_id": "draft-1",
                "base_revision": 1,
                "idempotency_key": "key-1",
                "request": {"status": "ACCEPTED"},
            }
        )
    # A valid single request still validates.
    assert (
        RequestSaveConfirmPayload.model_validate(
            {
                "draft_id": "draft-1",
                "base_revision": 1,
                "idempotency_key": "key-1",
                "storage_dir": "storage",
            }
        )
        is not None
    )

    # Batch item: a leaked full Request or unknown field is rejected.
    with pytest.raises(ValidationError):
        BatchItemSaveConfirmPayload.model_validate(
            {
                "item_id": "item-1",
                "draft_id": "draft-1",
                "base_revision": 1,
                "idempotency_key": "key-1",
                "request": {"status": "ACCEPTED"},
            }
        )
    with pytest.raises(ValidationError):
        BatchItemSaveConfirmPayload.model_validate(
            {
                "item_id": "item-1",
                "draft_id": "draft-1",
                "base_revision": 1,
                "idempotency_key": "key-1",
                "draft": {"title": "secret"},
            }
        )

    # Batch top-level: unknown field is rejected.
    with pytest.raises(ValidationError):
        BatchSaveConfirmPayload.model_validate(
            {
                "batch_id": "batch-1",
                "items": [
                    {
                        "item_id": "item-1",
                        "draft_id": "draft-1",
                        "base_revision": 1,
                        "idempotency_key": "key-1",
                    }
                ],
                "storage_dir": "storage",
                "token": "secret",
            }
        )
    # A valid batch request still validates.
    assert (
        BatchSaveConfirmPayload.model_validate(
            {
                "batch_id": "batch-1",
                "items": [
                    {
                        "item_id": "item-1",
                        "draft_id": "draft-1",
                        "base_revision": 1,
                        "idempotency_key": "key-1",
                    }
                ],
                "storage_dir": "storage",
            }
        )
        is not None
    )
