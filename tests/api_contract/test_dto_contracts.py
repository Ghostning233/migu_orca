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
    RequestPreviewModifyResultDTO,
    RequestPreviewSaveResultDTO,
    RequestSummaryDTO,
)
from batch_engine.controllers.batch_accept_controller import (
    serialize_batch_accept_result,
)
from batch_engine.controllers.batch_draft_controller import create_batch_draft
from batch_engine.controllers.batch_queue_controller import serialize_queue
from batch_engine.models import BatchSubmissionQueue
from request_engine.controllers.request_controller import summarize_request
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


def test_request_create_dto_accepts_real_payload() -> None:
    request = _generated_request()
    payload = {"request": request, "summary": _summary(request)}
    validated = RequestCreateResultDTO.model_validate(payload)
    assert validated.request["status"] == "PENDING_CONFIRM"


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
    payload = {**base, "ab_submit_result": {"success": True}}
    assert RequestAbSubmitResultDTO.model_validate(payload) is not None


def test_request_detail_dto_shape() -> None:
    payload = {
        "request": _generated_request(),
        "history": {"available": True, "events": [], "error": None},
        "ab_result": {"available": False, "record": None, "error": None},
    }
    assert RequestDetailResultDTO.model_validate(payload) is not None
    with pytest.raises(ValidationError):
        RequestDetailResultDTO.model_validate({**payload, "extra": 1})


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


def test_batch_queue_dto_accepts_null_queue() -> None:
    assert BatchQueueResultDTO.model_validate({"batch_id": "b1", "queue": None}) is not None
    with pytest.raises(ValidationError):
        BatchQueueResultDTO.model_validate({"batch_id": "b1", "queue": None, "x": 1})


def test_batch_accept_dto_validates_serialized_result() -> None:
    result = _accept_result()
    assert BatchAcceptResultDTO.model_validate(result) is not None
    with pytest.raises(ValidationError):
        BatchAcceptResultDTO.model_validate({**result, "leak": 1})


def test_batch_submit_dto_shares_accept_shape() -> None:
    result = _accept_result()
    assert BatchSubmitResultDTO.model_validate(result) is not None


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
