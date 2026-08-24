from __future__ import annotations

from copy import deepcopy
from typing import Any

from shared.errors import Stage1Error


def build_ab_fallback_config(
    payload: dict[str, Any],
    error: Stage1Error | dict[str, Any],
) -> dict[str, Any]:
    """Build a manual Auto Bangumi subscription fallback from a prepared payload."""

    fields = _fallback_fields(payload)
    return {
        **fields,
        "failure_reason": _error_to_dict(error),
    }


def _fallback_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep password-mode 3.1 fallback summaries useful after its body migration."""

    data = payload.get("data")
    rss = payload.get("rss")
    if isinstance(data, dict) and isinstance(rss, dict):
        return {
            "title": deepcopy(data.get("official_title")),
            "rss_url": deepcopy(rss.get("url", data.get("rss_link"))),
            "save_path": deepcopy(data.get("save_path")),
            "filter_rule": {"legacy_31_filter": deepcopy(data.get("filter", ""))},
        }
    return {
        "title": deepcopy(payload.get("title")),
        "rss_url": deepcopy(payload.get("rss_url")),
        "save_path": deepcopy(payload.get("save_path")),
        "filter_rule": deepcopy(payload.get("filter_rule", {})),
    }


def _error_to_dict(error: Stage1Error | dict[str, Any]) -> dict[str, Any]:
    if isinstance(error, Stage1Error):
        return deepcopy(error.as_dict())
    return deepcopy(error)
