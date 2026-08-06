from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
from typing import Any, Literal, Sequence

from ab_engine.controllers import ab_http_client
from ab_engine.controllers.ab_client import AutoBangumiClient, submit_ab_subscription
from ab_engine.controllers.ab_config import load_ab_config
from ab_engine.controllers.subscription_payload import build_ab_subscription_payload
from catalog_engine.controllers.catalog_controller import load_catalog, match_bangumi
from mikan_engine.controllers import mikan_client as mikan_client_module
from mikan_engine.controllers.mikan_client import MikanClient, MikanTransport
from mikan_engine.controllers.mikan_config import load_mikan_config
from request_engine.controllers.request_controller import (
    accept_request,
    build_pending_request,
    cancel_request,
    modify_request,
    summarize_request,
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
from storage_engine.controllers.history_repository import append_status_history
from storage_engine.controllers.request_repository import (
    list_request_snapshots,
    load_request_snapshot,
    save_request_snapshot,
)
from storage_engine.controllers.storage_config import load_storage_config
from subscription_engine.controllers.subscription_controller import (
    generate_folder_name,
    select_subtitle_group,
)


LOGGER = logging.getLogger(__name__)
SourceMode = Literal["static_fixture", "mikan_http"]


def generate_request(
    entry: EntryRequest,
    *,
    catalog_path: Path = DEFAULT_CATALOG_PATH,
    user_config_path: Path = DEFAULT_USER_CONFIG_PATH,
    project_root: Path = PROJECT_ROOT,
    source_mode: SourceMode = "static_fixture",
    mikan_config_path: Path | None = None,
    mikan_client: MikanClient | None = None,
    mikan_rss_transport: MikanTransport | None = None,
) -> dict[str, Any]:
    try:
        if not entry.raw_title.strip():
            raise Stage1Error("invalid_input", "番剧名称不能为空", "validate_input")

        preference = load_user_preference(user_config_path)
        real_mikan_client: MikanClient | None = None
        rss_transport = mikan_rss_transport
        rss_timeout = 10.0
        if source_mode == "static_fixture":
            candidates = load_catalog(catalog_path)
        elif source_mode == "mikan_http":
            real_mikan_client = _resolve_mikan_client(
                mikan_config_path=mikan_config_path,
                mikan_client=mikan_client,
            )
            candidates = real_mikan_client.list_bangumi_candidates(entry.raw_title)
            rss_transport = rss_transport or real_mikan_client.transport
            rss_timeout = real_mikan_client.config.timeout_seconds
        else:
            raise Stage1Error(
                "invalid_input",
                "不支持的数据源模式",
                "generate_request",
                {"source_mode": source_mode},
            )
        matched, candidate = match_bangumi(entry.raw_title, candidates)
        rss_sources = (
            real_mikan_client.list_rss_sources(matched)
            if real_mikan_client is not None
            else candidate.rss_sources
        )
        rss_results: list[FilteredRss] = []
        flow_warnings: list[str] = []
        for source in rss_sources:
            try:
                parsed = parse_rss(
                    source,
                    project_root,
                    transport=rss_transport,
                    timeout=rss_timeout,
                )
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


def _resolve_mikan_client(
    *,
    mikan_config_path: Path | None,
    mikan_client: MikanClient | None,
) -> MikanClient:
    if mikan_client is not None:
        return mikan_client
    if mikan_config_path is None:
        raise Stage1Error(
            "config_error",
            "真实 MiKan 数据源必须显式提供配置文件路径",
            "load_mikan_config",
            {"field": "mikan_config"},
        )
    config = load_mikan_config(mikan_config_path)
    return mikan_client_module.create_mikan_client(config)


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
        LOGGER.exception("Request 修改发生未预期错误")
        error = Stage1Error(
            "unexpected_error",
            "Request 修改发生未预期错误",
            "modify_request",
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
        ab_client = client or ab_http_client.create_auto_bangumi_http_client(ab_config)
        ab_submit_result = submit_ab_subscription(
            ab_client,
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
        return saved
    except Stage1Error as exc:
        LOGGER.warning("Request 保存失败：%s", exc.message)
        return {"success": False, "request": None, "error": exc.as_dict()}
    except Exception as exc:  # pragma: no cover - safety boundary
        LOGGER.exception("Request 保存发生未预期错误")
        error = Stage1Error(
            "unexpected_error",
            "Request 保存发生未预期错误",
            "save_request_snapshot",
            {"reason": str(exc)},
        )
        return {"success": False, "request": None, "error": error.as_dict()}


def list_saved_requests(
    *,
    storage_dir: Path | None = None,
) -> dict[str, Any]:
    try:
        config = load_storage_config(storage_dir)
        requests = [
            summarize_request(request) for request in list_request_snapshots(config)
        ]
        return {"success": True, "requests": requests, "error": None}
    except Stage1Error as exc:
        LOGGER.warning("Request 查询失败：%s", exc.message)
        return {"success": False, "requests": None, "error": exc.as_dict()}
    except Exception as exc:  # pragma: no cover - safety boundary
        LOGGER.exception("Request 查询发生未预期错误")
        error = Stage1Error(
            "unexpected_error",
            "Request 查询发生未预期错误",
            "list_request_snapshots",
            {"reason": str(exc)},
        )
        return {"success": False, "requests": None, "error": error.as_dict()}


def load_saved_request(
    request_id: str,
    *,
    storage_dir: Path | None = None,
) -> dict[str, Any]:
    try:
        config = load_storage_config(storage_dir)
        request = load_request_snapshot(config, request_id)
        return {"success": True, "request": request, "error": None}
    except Stage1Error as exc:
        LOGGER.warning("Request 读取失败：%s", exc.message)
        return {"success": False, "request": None, "error": exc.as_dict()}
    except Exception as exc:  # pragma: no cover - safety boundary
        LOGGER.exception("Request 读取发生未预期错误")
        error = Stage1Error(
            "unexpected_error",
            "Request 读取发生未预期错误",
            "load_request_snapshot",
            {"reason": str(exc)},
        )
        return {"success": False, "request": None, "error": error.as_dict()}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="离线生成 MiGuOrca Request")
    parser.add_argument("title", nargs="?", help="番剧名称")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--user-config", type=Path, default=DEFAULT_USER_CONFIG_PATH)
    parser.add_argument(
        "--source",
        choices=["static-fixture", "mikan"],
        default="static-fixture",
        help="显式选择数据源；默认使用离线静态 fixture",
    )
    parser.add_argument("--mikan-config", type=Path)
    parser.add_argument("--log-file", type=Path)
    parser.add_argument(
        "--modify-patch",
        help="确认前应用的 Request 修改补丁 JSON 对象",
    )
    parser.add_argument("--action", choices=["accept", "cancel"])
    parser.add_argument("--cancel-reason")
    parser.add_argument(
        "--submit-ab",
        action="store_true",
        help="显式提交已接受 Request 到 Auto Bangumi",
    )
    parser.add_argument("--ab-config", type=Path)
    parser.add_argument(
        "--save-request",
        action="store_true",
        help="显式保存生成的 Request 到本地 JSON 存储",
    )
    parser.add_argument(
        "--storage-dir",
        type=Path,
        help="本地 JSON 存储根目录；默认使用项目下 .migu_orca/storage",
    )
    parser.add_argument(
        "--list-requests",
        action="store_true",
        help="列出本地 JSON 存储中已保存的 Request 摘要",
    )
    parser.add_argument(
        "--load-request",
        help="按 request_id 读取本地 JSON 存储中的完整 Request",
    )
    args = parser.parse_args(argv)

    configure_logging(args.log_file)
    storage_query_result = _run_storage_query_action(args)
    if storage_query_result is not None:
        print(json.dumps(storage_query_result, ensure_ascii=False, indent=2))
        return 0 if storage_query_result["success"] else 1
    if args.title is None:
        result = {
            "success": False,
            "request": None,
            "error": Stage1Error(
                "invalid_input",
                "番剧名称不能为空",
                "parse_args",
                {"field": "title"},
            ).as_dict(),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    modify_patch_result = _parse_modify_patch_arg(args.modify_patch)
    if not modify_patch_result["success"]:
        print(json.dumps(modify_patch_result, ensure_ascii=False, indent=2))
        return 1
    modify_patch = modify_patch_result["patch"]
    history_events: list[dict[str, Any]] = []
    result = generate_request(
        EntryRequest(raw_title=args.title),
        catalog_path=args.catalog,
        user_config_path=args.user_config,
        source_mode="mikan_http" if args.source == "mikan" else "static_fixture",
        mikan_config_path=args.mikan_config,
    )
    if modify_patch is not None:
        previous_request = result["request"] if result["success"] else None
        result = apply_modify_action(result, modify_patch)
        if result["success"] and previous_request is not None:
            history_events.append(
                _build_history_event(
                    previous_request,
                    result["request"],
                    action="MODIFY",
                    details={"patch": modify_patch},
                )
            )
    previous_request = result["request"] if result["success"] else None
    result = apply_confirmation_action(
        result,
        args.action,
        cancel_reason=args.cancel_reason,
    )
    if result["success"] and previous_request is not None and args.action is not None:
        history_events.append(
            _build_history_event(
                previous_request,
                result["request"],
                action=args.action.upper(),
                details=_confirmation_history_details(args.action, args.cancel_reason),
            )
        )
    result = apply_ab_submit_action(
        result,
        args.submit_ab,
        ab_config_path=args.ab_config,
    )
    result = apply_request_save_action(
        result,
        args.save_request,
        storage_dir=args.storage_dir,
        history_events=history_events,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["success"] else 1


def _run_storage_query_action(args: argparse.Namespace) -> dict[str, Any] | None:
    if args.list_requests and args.load_request:
        error = Stage1Error(
            "invalid_input",
            "Request 查询参数不能同时使用",
            "parse_args",
            {"fields": ["list_requests", "load_request"]},
        )
        return {"success": False, "request": None, "error": error.as_dict()}
    if args.list_requests:
        return list_saved_requests(storage_dir=args.storage_dir)
    if args.load_request is not None:
        return load_saved_request(args.load_request, storage_dir=args.storage_dir)
    return None


def _parse_modify_patch_arg(value: str | None) -> dict[str, Any]:
    if value is None:
        return {"success": True, "patch": None, "error": None}

    try:
        patch = json.loads(value)
    except json.JSONDecodeError as exc:
        error = Stage1Error(
            "invalid_modify_patch",
            "修改补丁必须是 JSON 对象",
            "parse_modify_patch",
            {"reason": exc.msg},
        )
        return {"success": False, "request": None, "error": error.as_dict()}
    if not isinstance(patch, dict):
        error = Stage1Error(
            "invalid_modify_patch",
            "修改补丁必须是 JSON 对象",
            "parse_modify_patch",
        )
        return {"success": False, "request": None, "error": error.as_dict()}
    return {"success": True, "patch": patch, "error": None}


def _build_history_event(
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


def _confirmation_history_details(
    action: str,
    cancel_reason: str | None,
) -> dict[str, Any] | None:
    if action == "cancel":
        return {"reason": cancel_reason or ""}
    return None
