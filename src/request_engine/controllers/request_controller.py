from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
import re
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
from subscription_engine.controllers.subscription_controller import generate_folder_name

PENDING_CONFIRM = "PENDING_CONFIRM"
ACCEPTED = "ACCEPTED"
CANCELLED = "CANCELLED"
MODIFY_PATCH_FIELDS = {
    "selected_subtitle_group",
    "filter_rule",
    "expected_folder_name",
}
FILTER_RULE_PATCH_FIELDS = {"must_contain", "must_not_contain"}


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


def validate_modify_patch(patch: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(patch, dict):
        raise Stage1Error(
            "invalid_modify_patch",
            "修改补丁必须是对象",
            "validate_modify_patch",
        )

    illegal_fields = sorted(set(patch) - MODIFY_PATCH_FIELDS)
    if illegal_fields:
        raise Stage1Error(
            "invalid_modify_patch_field",
            "修改补丁包含不可修改字段",
            "validate_modify_patch",
            {
                "illegal_fields": illegal_fields,
                "allowed_fields": sorted(MODIFY_PATCH_FIELDS),
            },
        )

    validated = deepcopy(patch)
    if "selected_subtitle_group" in validated:
        group = validated["selected_subtitle_group"]
        if group is not None and not isinstance(group, str):
            raise Stage1Error(
                "invalid_modify_patch",
                "selected_subtitle_group 必须是字符串或 null",
                "validate_modify_patch",
                {"field": "selected_subtitle_group"},
            )

    if "expected_folder_name" in validated:
        folder_name = validated["expected_folder_name"]
        if not isinstance(folder_name, str):
            raise Stage1Error(
                "invalid_modify_patch",
                "expected_folder_name 必须是字符串",
                "validate_modify_patch",
                {"field": "expected_folder_name"},
            )
        validated["expected_folder_name"] = folder_name.strip()

    if "filter_rule" in validated:
        validated["filter_rule"] = _validate_filter_rule_patch(validated["filter_rule"])

    return validated


def modify_request(request: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    validated = validate_modify_patch(patch)
    updated = _copy_pending_request(request, "modify_request")
    confirmable = updated["confirmable_config"]
    source_info = updated["source_info"]
    rss_sources = source_info.get("rss_sources", [])

    if "filter_rule" in validated:
        next_filter_rule = {
            **confirmable.get("filter_rule", {}),
            **validated["filter_rule"],
        }
        confirmable["filter_rule"] = next_filter_rule
        for source in rss_sources:
            _recompute_source_seed_filter(source, next_filter_rule)

    if "selected_subtitle_group" in validated:
        selected_group = validated["selected_subtitle_group"]
        selected_source = _find_rss_source_by_group(rss_sources, selected_group)
        confirmable["selected_subtitle_group"] = selected_group
        confirmable["selected_rss_url"] = (
            selected_source.get("rss_url") if selected_source else None
        )

    if "expected_folder_name" in validated:
        expected_folder_name = validated["expected_folder_name"]
        confirmable["expected_folder_name"] = (
            generate_folder_name(expected_folder_name) if expected_folder_name else ""
        )

    selected_source = _find_rss_source_by_group(
        rss_sources,
        confirmable.get("selected_subtitle_group"),
    )
    confirmable["effective_seed_names"] = (
        list(selected_source.get("valid_seed_names", [])) if selected_source else []
    )
    updated["status"] = PENDING_CONFIRM
    updated["updated_at"] = datetime.now(UTC).isoformat()
    return updated


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


def _validate_filter_rule_patch(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise Stage1Error(
            "invalid_modify_patch",
            "filter_rule 必须是对象",
            "validate_modify_patch",
            {"field": "filter_rule"},
        )

    illegal_fields = sorted(set(value) - FILTER_RULE_PATCH_FIELDS)
    if illegal_fields:
        raise Stage1Error(
            "invalid_modify_patch_field",
            "filter_rule 包含不可修改字段",
            "validate_modify_patch",
            {
                "illegal_fields": [f"filter_rule.{field}" for field in illegal_fields],
                "allowed_fields": sorted(FILTER_RULE_PATCH_FIELDS),
            },
        )

    validated = deepcopy(value)
    for field, rule in validated.items():
        if not isinstance(rule, str):
            raise Stage1Error(
                "invalid_modify_patch",
                "filter_rule 字段必须是字符串",
                "validate_modify_patch",
                {"field": f"filter_rule.{field}"},
            )
        _compile_patch_regex(rule, field)
    return validated


def _compile_patch_regex(value: str, field: str) -> None:
    if not value:
        return
    try:
        re.compile(value)
    except re.error as exc:
        raise Stage1Error(
            "invalid_modify_patch",
            f"filter_rule.{field} 不是合法正则",
            "validate_modify_patch",
            {"field": f"filter_rule.{field}", "rule": value, "reason": str(exc)},
        ) from exc


def _find_rss_source_by_group(
    rss_sources: list[dict[str, Any]],
    subtitle_group: str | None,
) -> dict[str, Any] | None:
    if subtitle_group is None:
        return None
    for source in rss_sources:
        if source.get("subtitle_group") == subtitle_group:
            return source
    raise Stage1Error(
        "invalid_modify_patch",
        "selected_subtitle_group 不在候选 RSS 中",
        "modify_request",
        {"field": "selected_subtitle_group", "value": subtitle_group},
    )


def _recompute_source_seed_filter(
    source: dict[str, Any],
    filter_rule: dict[str, str],
) -> None:
    must_contain = _compile_request_filter_rule(
        filter_rule.get("must_contain", ""),
        "must_contain",
    )
    must_not_contain = _compile_request_filter_rule(
        filter_rule.get("must_not_contain", ""),
        "must_not_contain",
    )
    seed_names = _source_seed_names(source)
    valid: list[str] = []
    excluded: list[dict[str, str]] = []
    for seed_name in seed_names:
        if must_not_contain and must_not_contain.search(seed_name):
            excluded.append(
                {
                    "name": seed_name,
                    "reason": f"命中必须不含规则：{filter_rule['must_not_contain']}",
                    "rule": "must_not_contain",
                }
            )
        elif must_contain and not must_contain.search(seed_name):
            excluded.append(
                {
                    "name": seed_name,
                    "reason": f"未命中必须包含规则：{filter_rule['must_contain']}",
                    "rule": "must_contain",
                }
            )
        else:
            valid.append(seed_name)

    source["total_seed_count"] = len(seed_names)
    source["valid_seed_count"] = len(valid)
    source["invalid_seed_count"] = len(excluded)
    source["valid_seed_names"] = valid
    source["excluded_seed_names"] = excluded


def _source_seed_names(source: dict[str, Any]) -> list[str]:
    seed_names: list[str] = []
    for seed_name in source.get("valid_seed_names", []):
        if seed_name not in seed_names:
            seed_names.append(seed_name)
    for seed in source.get("excluded_seed_names", []):
        seed_name = seed.get("name")
        if seed_name and seed_name not in seed_names:
            seed_names.append(seed_name)
    return seed_names


def _compile_request_filter_rule(value: str, field: str) -> re.Pattern[str] | None:
    if not value:
        return None
    try:
        return re.compile(value)
    except re.error as exc:  # pragma: no cover - validate_modify_patch guards this
        raise Stage1Error(
            "invalid_modify_patch",
            f"filter_rule.{field} 不是合法正则",
            "modify_request",
            {"field": f"filter_rule.{field}", "rule": value, "reason": str(exc)},
        ) from exc


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
