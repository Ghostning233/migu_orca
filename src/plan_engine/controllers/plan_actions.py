from __future__ import annotations

"""Subscription-plan lifecycle actions shared by the Web API and the CLI.

These were previously defined in the CLI app controller; the Web API imported
them across app boundaries (including the private ``_build_history_event``).
They only depend on `request_engine` and `storage_engine`, so they belong to the
plan seam that owns plan state transitions.
"""

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from request_engine.controllers.request_controller import (
    accept_request,
    cancel_request,
    modify_request,
)
from shared.errors import Stage1Error
from storage_engine.controllers.ab_result_repository import save_ab_submit_result
from storage_engine.controllers.history_repository import append_status_history
from storage_engine.controllers.request_repository import save_request_snapshot
from storage_engine.controllers.storage_config import load_storage_config

LOGGER = logging.getLogger(__name__)


def apply_confirmation_action(
    result: dict[str, Any],
    action: str | None,
    *,
    cancel_reason: str | None = None,
) -> dict[str, Any]:
    if action is None or not result["success"]:
        return result

    try:
        request = result["request"]
        if action == "accept":
            updated_request = accept_request(request)
        elif action == "cancel":
            updated_request = cancel_request(request, cancel_reason or "")
        else:
            raise Stage1Error(
                "invalid_confirmation_action",
                "不支持的确认动作",
                "confirm_request",
                {"action": action},
            )
        return {"success": True, "request": updated_request, "error": None}
    except Stage1Error as exc:
        LOGGER.warning("Request 确认失败：%s", exc.message)
        return {"success": False, "request": None, "error": exc.as_dict()}
    except Exception as exc:  # pragma: no cover - safety boundary
        LOGGER.error("订阅方案确认发生未预期错误")
        error = Stage1Error(
            "unexpected_error",
            "订阅方案确认发生未预期错误",
            "confirm_request",
            {"reason": str(exc)},
        )
        return {"success": False, "request": None, "error": error.as_dict()}


def apply_modify_action(
    result: dict[str, Any],
    patch: dict[str, Any] | None,
) -> dict[str, Any]:
    if patch is None or not result["success"]:
        return result

    try:
        updated_request = modify_request(result["request"], patch)
        return {"success": True, "request": updated_request, "error": None}
    except Stage1Error as exc:
        LOGGER.warning("Request 修改失败：%s", exc.message)
        return {"success": False, "request": None, "error": exc.as_dict()}
    except Exception as exc:  # pragma: no cover - safety boundary
        LOGGER.error("订阅方案修改发生未预期错误")
        error = Stage1Error(
            "unexpected_error",
            "订阅方案修改发生未预期错误",
            "modify_request",
            {"reason": str(exc)},
        )
        return {"success": False, "request": None, "error": error.as_dict()}


def apply_request_save_action(
    result: dict[str, Any],
    save_request: bool,
    *,
    storage_dir: Path | None = None,
    history_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not save_request or not result["success"]:
        return result

    try:
        config = load_storage_config(storage_dir)
        saved_request = save_request_snapshot(config, result["request"])
        saved_history = [
            append_status_history(config, event) for event in history_events or []
        ]
        saved = {**result, "saved_request": saved_request}
        if saved_history:
            saved["saved_history"] = saved_history
        if isinstance(result["request"].get("ab_submit_result"), dict):
            saved["saved_ab_result"] = save_ab_submit_result(config, result["request"])
        return saved
    except Stage1Error as exc:
        LOGGER.warning("Request 保存失败：%s", exc.message)
        return {"success": False, "request": None, "error": exc.as_dict()}
    except Exception as exc:  # pragma: no cover - safety boundary
        LOGGER.error("订阅方案保存发生未预期错误")
        error = Stage1Error(
            "unexpected_error",
            "订阅方案保存发生未预期错误",
            "save_request_snapshot",
            {"reason": str(exc)},
        )
        return {"success": False, "request": None, "error": error.as_dict()}


def build_history_event(
    previous_request: dict[str, Any],
    next_request: dict[str, Any],
    *,
    action: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timestamp = next_request.get("updated_at") or datetime.now(UTC).isoformat()
    event = {
        "request_id": next_request.get("request_id"),
        "previous_status": previous_request.get("status"),
        "next_status": next_request.get("status"),
        "action": action,
        "timestamp": timestamp,
    }
    if details:
        event["details"] = details
    return event


def confirmation_history_details(
    action: str,
    cancel_reason: str | None,
) -> dict[str, Any] | None:
    if action == "cancel":
        return {"reason": cancel_reason or ""}
    return None
