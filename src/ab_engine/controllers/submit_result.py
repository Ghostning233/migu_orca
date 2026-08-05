from __future__ import annotations

from copy import deepcopy
from typing import Any

from shared.errors import Stage1Error


def ab_submit_success(
    ab_subscription_id: str,
    ab_response: dict[str, Any],
) -> dict[str, Any]:
    """Build the stable Auto Bangumi submit success result."""

    clean_subscription_id = ab_subscription_id.strip()
    if not clean_subscription_id:
        raise Stage1Error(
            "invalid_ab_submit_result",
            "Auto Bangumi subscription id 不能为空",
            "build_ab_submit_success",
        )

    return {
        "success": True,
        "ab_subscription_id": clean_subscription_id,
        "ab_response": deepcopy(ab_response),
        "fallback_config": None,
        "error": None,
    }


def ab_submit_failure(
    error: Stage1Error | dict[str, Any],
    *,
    fallback_config: dict[str, Any] | None = None,
    ab_response: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the stable Auto Bangumi submit failure result."""

    return {
        "success": False,
        "ab_subscription_id": None,
        "ab_response": deepcopy(ab_response),
        "fallback_config": deepcopy(fallback_config),
        "error": _error_to_dict(error),
    }


def _error_to_dict(error: Stage1Error | dict[str, Any]) -> dict[str, Any]:
    if isinstance(error, Stage1Error):
        return error.as_dict()
    return deepcopy(error)
