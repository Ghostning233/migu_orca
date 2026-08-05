from __future__ import annotations

from copy import deepcopy
from typing import Any

from shared.errors import Stage1Error


def build_ab_fallback_config(
    payload: dict[str, Any],
    error: Stage1Error | dict[str, Any],
) -> dict[str, Any]:
    """Build a manual Auto Bangumi subscription fallback from a prepared payload."""

    return {
        "title": deepcopy(payload.get("title")),
        "rss_url": deepcopy(payload.get("rss_url")),
        "save_path": deepcopy(payload.get("save_path")),
        "filter_rule": deepcopy(payload.get("filter_rule", {})),
        "failure_reason": _error_to_dict(error),
    }


def _error_to_dict(error: Stage1Error | dict[str, Any]) -> dict[str, Any]:
    if isinstance(error, Stage1Error):
        return deepcopy(error.as_dict())
    return deepcopy(error)
