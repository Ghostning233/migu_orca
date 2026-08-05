from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
from typing import Any, Sequence

from ab_engine.controllers.ab_client import (
    AutoBangumiClient,
    FakeAutoBangumiClient,
    submit_ab_subscription,
)
from ab_engine.controllers.ab_config import load_ab_config
from ab_engine.controllers.subscription_payload import build_ab_subscription_payload
from catalog_engine.controllers.catalog_controller import load_catalog, match_bangumi
from request_engine.controllers.request_controller import (
    accept_request,
    build_pending_request,
    cancel_request,
)
from rss_engine.controllers.rss_controller import filter_seeds, parse_rss
from shared.config import (
    DEFAULT_CATALOG_PATH,
    DEFAULT_USER_CONFIG_PATH,
    PROJECT_ROOT,
    load_user_preference,
)
from shared.errors import Stage1Error
from shared.logging import configure_logging
from shared.models import EntryRequest, FilteredRss
from subscription_engine.controllers.subscription_controller import (
    generate_folder_name,
    select_subtitle_group,
)


LOGGER = logging.getLogger(__name__)


def generate_request(
    entry: EntryRequest,
    *,
    catalog_path: Path = DEFAULT_CATALOG_PATH,
    user_config_path: Path = DEFAULT_USER_CONFIG_PATH,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    try:
        if not entry.raw_title.strip():
            raise Stage1Error("invalid_input", "番剧名称不能为空", "validate_input")

        preference = load_user_preference(user_config_path)
        candidates = load_catalog(catalog_path)
        matched, candidate = match_bangumi(entry.raw_title, candidates)
        rss_results: list[FilteredRss] = []
        flow_warnings: list[str] = []
        for source in candidate.rss_sources:
            try:
                parsed = parse_rss(source, project_root)
            except Stage1Error as exc:
                flow_warnings.append(
                    f"字幕组 {source.subtitle_group} 的 RSS 解析失败：{exc.message}"
                )
                continue
            rss_results.append(filter_seeds(parsed, preference.filter_rule))

        if not rss_results:
            raise Stage1Error(
                "rss_parse_failed",
                "所有候选 RSS 均解析失败",
                "parse_rss",
            )

        selection = select_subtitle_group(
            rss_results,
            preference.subtitle_group_priority,
        )
        folder_name = generate_folder_name(matched.title)
        request = build_pending_request(
            entry,
            matched,
            rss_results,
            selection,
            preference.filter_rule,
            folder_name,
            flow_warnings,
        )
        LOGGER.info("Request 生成完成：%s", request["request_id"])
        return {"success": True, "request": request, "error": None}
    except Stage1Error as exc:
        LOGGER.warning("Request 生成失败：%s", exc.message)
        return {"success": False, "request": None, "error": exc.as_dict()}
    except Exception as exc:  # pragma: no cover - safety boundary
        LOGGER.exception("Request 生成发生未预期错误")
        error = Stage1Error(
            "unexpected_error",
            "Request 生成发生未预期错误",
            "generate_request",
            {"reason": str(exc)},
        )
        return {"success": False, "request": None, "error": error.as_dict()}


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
        LOGGER.exception("Request 确认发生未预期错误")
        error = Stage1Error(
            "unexpected_error",
            "Request 确认发生未预期错误",
            "confirm_request",
            {"reason": str(exc)},
        )
        return {"success": False, "request": None, "error": error.as_dict()}


def apply_ab_submit_action(
    result: dict[str, Any],
    submit_ab: bool,
    *,
    ab_config_path: Path | None = None,
    client: AutoBangumiClient | None = None,
) -> dict[str, Any]:
    if not submit_ab or not result["success"]:
        return result

    try:
        if ab_config_path is None:
            raise Stage1Error(
                "config_error",
                "提交 Auto Bangumi 必须显式提供配置文件路径",
                "load_ab_config",
                {"field": "ab_config"},
            )

        ab_config = load_ab_config(ab_config_path)
        request = result["request"]
        payload = build_ab_subscription_payload(request)
        ab_submit_result = submit_ab_subscription(
            client or FakeAutoBangumiClient(),
            payload,
            fallback_enabled=ab_config.fallback_enabled,
        )
        updated_request = deepcopy(request)
        updated_request["ab_submit_result"] = ab_submit_result
        updated_request["updated_at"] = datetime.now(UTC).isoformat()
        return {
            "success": True,
            "request": updated_request,
            "ab_submit_result": ab_submit_result,
            "error": None,
        }
    except Stage1Error as exc:
        LOGGER.warning("Auto Bangumi 提交准备失败：%s", exc.message)
        return {
            "success": False,
            "request": None,
            "ab_submit_result": None,
            "error": exc.as_dict(),
        }
    except Exception as exc:  # pragma: no cover - safety boundary
        LOGGER.exception("Auto Bangumi 提交发生未预期错误")
        error = Stage1Error(
            "unexpected_error",
            "Auto Bangumi 提交发生未预期错误",
            "submit_ab_subscription",
            {"reason": str(exc)},
        )
        return {
            "success": False,
            "request": None,
            "ab_submit_result": None,
            "error": error.as_dict(),
        }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="离线生成 MiGuOrca Request")
    parser.add_argument("title", help="番剧名称")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--user-config", type=Path, default=DEFAULT_USER_CONFIG_PATH)
    parser.add_argument("--log-file", type=Path)
    parser.add_argument("--action", choices=["accept", "cancel"])
    parser.add_argument("--cancel-reason")
    parser.add_argument(
        "--submit-ab",
        action="store_true",
        help="显式提交已接受 Request 到 Auto Bangumi",
    )
    parser.add_argument("--ab-config", type=Path)
    args = parser.parse_args(argv)

    configure_logging(args.log_file)
    result = generate_request(
        EntryRequest(raw_title=args.title),
        catalog_path=args.catalog,
        user_config_path=args.user_config,
    )
    result = apply_confirmation_action(
        result,
        args.action,
        cancel_reason=args.cancel_reason,
    )
    result = apply_ab_submit_action(
        result,
        args.submit_ab,
        ab_config_path=args.ab_config,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["success"] else 1
