from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Literal

from request_engine.controllers.request_controller import ACCEPTED
from shared.errors import Stage1Error


def build_ab_subscription_payload(request: dict[str, Any]) -> dict[str, Any]:
    """Map an accepted Request snapshot to an Auto Bangumi subscription payload."""

    status = request.get("status")
    if status != ACCEPTED:
        raise Stage1Error(
            "invalid_request_status",
            "只有已确认订阅方案可以提交到 Auto Bangumi",
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


def build_legacy_31_subscription_payload(request: dict[str, Any]) -> dict[str, Any]:
    """Map an accepted Request to AutoBangumi 3.1's subscribe body.

    AutoBangumi 3.1 expects two named JSON arguments, ``data: Bangumi`` and
    ``rss: RSSItem``.  Keep this conversion pure so every submit entry point
    can prepare exactly the same body without retaining request credentials.
    """

    payload = build_ab_subscription_payload(request)
    title = _required_string(payload["title"], "title")
    rss_url = _required_string(payload["rss_url"], "rss_url")
    save_path = _required_string(payload["save_path"], "save_path")
    return {
        "data": {
            "official_title": title,
            "title_raw": title,
            "filter": _legacy_31_filter(payload["filter_rule"]),
            "rss_link": rss_url,
            "save_path": save_path,
        },
        "rss": {
            "name": title,
            "url": rss_url,
            "aggregate": False,
            "parser": "mikan",
        },
    }


def build_ab_submit_payload(
    request: dict[str, Any], auth_mode: Literal["password", "api_token"]
) -> dict[str, Any]:
    """Build the verified subscription body for one authentication adapter."""

    if auth_mode == "password":
        return build_legacy_31_subscription_payload(request)
    return build_ab_subscription_payload(request)


def _legacy_31_filter(value: Any) -> str:
    """Encode the request filter only when 3.1's regex string preserves it."""

    if not isinstance(value, dict):
        raise Stage1Error(
            "ab_filter_unsupported",
            "当前筛选规则无法兼容 Auto Bangumi 3.1",
            "build_legacy_31_subscription_payload",
        )
    must_contain = _filter_string(value, "must_contain")
    must_not_contain = _filter_string(value, "must_not_contain")
    use_regex = value.get("use_regex", False)
    case_sensitive = value.get("case_sensitive", False)
    if not isinstance(use_regex, bool) or not isinstance(case_sensitive, bool):
        raise Stage1Error(
            "ab_filter_unsupported",
            "当前筛选规则无法兼容 Auto Bangumi 3.1",
            "build_legacy_31_subscription_payload",
        )
    if not use_regex:
        must_contain = re.escape(must_contain)
        must_not_contain = re.escape(must_not_contain)

    expression = "^"
    if not case_sensitive:
        expression = "(?i)^"
    if must_contain:
        expression += f"(?=.*(?:{must_contain}))"
    if must_not_contain:
        expression += f"(?!.*(?:{must_not_contain}))"
    expression += ".*$"
    try:
        re.compile(expression)
    except re.error as exc:
        raise Stage1Error(
            "ab_filter_unsupported",
            "当前筛选规则无法兼容 Auto Bangumi 3.1",
            "build_legacy_31_subscription_payload",
        ) from exc
    return expression


def _filter_string(value: dict[str, Any], field: str) -> str:
    candidate = value.get(field, "")
    if not isinstance(candidate, str):
        raise Stage1Error(
            "ab_filter_unsupported",
            "当前筛选规则无法兼容 Auto Bangumi 3.1",
            "build_legacy_31_subscription_payload",
        )
    return candidate.strip()


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
