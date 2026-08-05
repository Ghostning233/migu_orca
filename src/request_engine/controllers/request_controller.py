from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from shared.errors import Stage1Error
from shared.models import (
    EntryRequest,
    FilteredRss,
    FilterRule,
    MatchedBangumi,
    SubtitleGroupSelection,
)

PENDING_CONFIRM = "PENDING_CONFIRM"
ACCEPTED = "ACCEPTED"
CANCELLED = "CANCELLED"


def build_pending_request(
    entry: EntryRequest,
    matched: MatchedBangumi,
    rss_results: list[FilteredRss],
    selection: SubtitleGroupSelection,
    filter_rule: FilterRule,
    folder_name: str,
    flow_warnings: list[str] | None = None,
) -> dict[str, Any]:
    created_at = datetime.now(UTC).isoformat()
    selected_result = next(
        (
            result
            for result in rss_results
            if result.source.rss_url == selection.rss_url
        ),
        None,
    )
    warnings = [*(flow_warnings or []), *selection.warnings]
    for result in rss_results:
        warnings.extend(result.warnings)

    return {
        "request_id": str(uuid4()),
        "status": PENDING_CONFIRM,
        "input": asdict(entry),
        "source_info": {
            "matched_bangumi": asdict(matched),
            "rss_sources": [_rss_result_to_dict(result) for result in rss_results],
        },
        "confirmable_config": {
            "selected_subtitle_group": selection.subtitle_group,
            "selected_rss_url": selection.rss_url,
            "filter_rule": asdict(filter_rule),
            "effective_seed_names": (
                [seed.title for seed in selected_result.valid_seeds]
                if selected_result
                else []
            ),
            "expected_folder_name": folder_name,
            "warnings": warnings,
        },
        "ab_submit_result": None,
        "created_at": created_at,
        "updated_at": created_at,
    }


def accept_request(request: dict[str, Any]) -> dict[str, Any]:
    updated = _copy_pending_request(request, "accept_request")
    decided_at = datetime.now(UTC).isoformat()
    updated["status"] = ACCEPTED
    updated["updated_at"] = decided_at
    updated["user_action"] = {
        "action": "ACCEPT",
        "reason": None,
        "decided_at": decided_at,
    }
    return updated


def cancel_request(request: dict[str, Any], reason: str) -> dict[str, Any]:
    clean_reason = reason.strip()
    if not clean_reason:
        raise Stage1Error(
            "invalid_cancel_reason",
            "取消原因不能为空",
            "cancel_request",
        )

    updated = _copy_pending_request(request, "cancel_request")
    decided_at = datetime.now(UTC).isoformat()
    updated["status"] = CANCELLED
    updated["updated_at"] = decided_at
    updated["user_action"] = {
        "action": "CANCEL",
        "reason": clean_reason,
        "decided_at": decided_at,
    }
    return updated


def summarize_request(request: dict[str, Any]) -> dict[str, Any]:
    confirmable = request.get("confirmable_config", {})
    source_info = request.get("source_info", {})
    matched = source_info.get("matched_bangumi", {})
    rss_sources = source_info.get("rss_sources", [])

    return {
        "request_id": request.get("request_id"),
        "status": request.get("status"),
        "bangumi_title": matched.get("title"),
        "candidate_subtitle_groups": [
            {
                "subtitle_group": source.get("subtitle_group"),
                "rss_url": source.get("rss_url"),
                "total_seed_count": source.get("total_seed_count", 0),
                "valid_seed_count": source.get("valid_seed_count", 0),
                "invalid_seed_count": source.get("invalid_seed_count", 0),
            }
            for source in rss_sources
        ],
        "selected_subtitle_group": confirmable.get("selected_subtitle_group"),
        "effective_seed_count": len(confirmable.get("effective_seed_names", [])),
        "expected_folder_name": confirmable.get("expected_folder_name"),
        "warnings": list(confirmable.get("warnings", [])),
    }


def _copy_pending_request(
    request: dict[str, Any],
    failed_step: str,
) -> dict[str, Any]:
    status = request.get("status")
    if status != PENDING_CONFIRM:
        raise Stage1Error(
            "invalid_request_status",
            "只有 PENDING_CONFIRM Request 可以执行确认操作",
            failed_step,
            {"status": status},
        )
    return deepcopy(request)


def _rss_result_to_dict(result: FilteredRss) -> dict[str, Any]:
    return {
        "subtitle_group": result.source.subtitle_group,
        "rss_url": result.source.rss_url,
        "source_type": result.source.source_type,
        "total_seed_count": result.total_seed_count,
        "valid_seed_count": len(result.valid_seeds),
        "invalid_seed_count": len(result.excluded_seeds),
        "valid_seed_names": [seed.title for seed in result.valid_seeds],
        "excluded_seed_names": [asdict(seed) for seed in result.excluded_seeds],
        "warnings": result.warnings,
    }
