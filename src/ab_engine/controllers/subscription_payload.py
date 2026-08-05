from __future__ import annotations

from copy import deepcopy
from typing import Any

from request_engine.controllers.request_controller import ACCEPTED
from shared.errors import Stage1Error


def build_ab_subscription_payload(request: dict[str, Any]) -> dict[str, Any]:
    """Map an accepted Request snapshot to an Auto Bangumi subscription payload."""

    status = request.get("status")
    if status != ACCEPTED:
        raise Stage1Error(
            "invalid_request_status",
            "只有 ACCEPTED Request 可以提交到 Auto Bangumi",
            "build_ab_subscription_payload",
            {"status": status},
        )

    confirmable = request.get("confirmable_config", {})
    rss_url = _required_string(
        confirmable.get("selected_rss_url"),
        "selected_rss_url",
    )
    folder_name = _required_string(
        confirmable.get("expected_folder_name"),
        "expected_folder_name",
    )

    return {
        "title": _request_title(request),
        "rss_url": rss_url,
        "save_path": folder_name,
        "filter_rule": deepcopy(confirmable.get("filter_rule", {})),
    }


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Stage1Error(
            "missing_ab_payload_field",
            "Auto Bangumi payload 缺少必填字段",
            "build_ab_subscription_payload",
            {"field": f"confirmable_config.{field}"},
        )
    return value.strip()


def _request_title(request: dict[str, Any]) -> str | None:
    source_info = request.get("source_info", {})
    matched = source_info.get("matched_bangumi", {})
    title = matched.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    raw_title = request.get("input", {}).get("raw_title")
    if isinstance(raw_title, str) and raw_title.strip():
        return raw_title.strip()
    return None
