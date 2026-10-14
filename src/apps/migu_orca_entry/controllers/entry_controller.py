from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Sequence
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from ab_engine.controllers import ab_http_client
from ab_engine.controllers.ab_client import AutoBangumiClient, submit_ab_subscription
from ab_engine.controllers.ab_config import AutoBangumiConfig, load_ab_config
from ab_engine.controllers.subscription_payload import build_ab_submit_payload
from mikan_engine.controllers.mikan_client import MikanClient, MikanTransport
from mikan_engine.controllers.mikan_config import MikanConfig
from plan_engine.controllers.data_sources import (
    DirectEntryResolution,
    MikanDataSource,
    PlanDataSource,
    StaticFixtureDataSource,
)
from plan_engine.controllers.plan_actions import (
    apply_confirmation_action,
    apply_modify_action,
    apply_request_save_action,
    build_history_event,
    confirmation_history_details,
)
from plan_engine.controllers.plan_generation import build_plan
from request_engine.controllers.request_controller import summarize_request
from shared.config import (
    DEFAULT_CATALOG_PATH,
    DEFAULT_USER_CONFIG_PATH,
    PROJECT_ROOT,
    load_user_preference,
)
from shared.errors import Stage1Error
from shared.logging import configure_logging
from shared.models import (
    BangumiCandidate,
    EntryRequest,
    MatchedBangumi,
    ParsedRss,
    RssSource,
    UserPreference,
)
from storage_engine.controllers.request_repository import list_request_snapshots, load_request_snapshot
from storage_engine.controllers.storage_config import load_storage_config

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
    mikan_config: MikanConfig | None = None,
    mikan_client: MikanClient | None = None,
    mikan_rss_transport: MikanTransport | None = None,
    mikan_bangumi: str | None = None,
) -> dict[str, Any]:
    """Compatibility shell for the historical CLI-controller entry.

    Kept so existing callers/fixtures can migrate in batches; new callers use
    `plan_engine.controllers.plan_generation.build_plan` with an injected
    `PlanDataSource`. The CLI-semantics keywords are translated here, outside
    the plan seam, and behaviour is unchanged.
    """

    return build_plan(
        entry,
        data_source=_cli_data_source(
            source_mode,
            catalog_path=catalog_path,
            user_config_path=user_config_path,
            project_root=project_root,
            mikan_config_path=mikan_config_path,
            mikan_config=mikan_config,
            mikan_client=mikan_client,
            mikan_rss_transport=mikan_rss_transport,
        ),
        mikan_bangumi=mikan_bangumi,
    )


def _cli_data_source(
    source_mode: str,
    *,
    catalog_path: Path,
    user_config_path: Path,
    project_root: Path,
    mikan_config_path: Path | None,
    mikan_config: MikanConfig | None,
    mikan_client: MikanClient | None,
    mikan_rss_transport: MikanTransport | None,
) -> PlanDataSource:
    """Translate the historical CLI ``source_mode`` into a data-source adapter."""

    if source_mode == "static_fixture":
        return StaticFixtureDataSource(
            catalog_path=catalog_path,
            user_config_path=user_config_path,
            project_root=project_root,
            transport=mikan_rss_transport,
        )
    if source_mode == "mikan_http":
        return MikanDataSource(
            user_config_path=user_config_path,
            config_path=mikan_config_path,
            config=mikan_config,
            client=mikan_client,
            transport=mikan_rss_transport,
            rss_fixture_root=project_root,
        )
    return _UnsupportedDataSource(source_mode, user_config_path=user_config_path)


class _UnsupportedDataSource:
    """Fail-closed stand-in for an unknown CLI ``source_mode``.

    The historical controller loaded the user preference *before* rejecting an
    unknown mode, so this keeps that ordering (and the same stable error) intact
    for the compatibility shell.
    """

    def __init__(self, source_mode: str, *, user_config_path: Path) -> None:
        self._source_mode = source_mode
        self._user_config_path = user_config_path

    def load_preference(self) -> UserPreference:
        load_user_preference(self._user_config_path)
        raise self._error()

    def list_candidates(self, raw_title: str) -> list[BangumiCandidate]:
        raise self._error()

    def resolve_direct_entry(self, direct_entry: str) -> DirectEntryResolution:
        raise self._error()

    def list_rss_sources(
        self,
        matched: MatchedBangumi,
        candidate: BangumiCandidate,
    ) -> list[RssSource]:
        raise self._error()

    def parse_rss(self, source: RssSource) -> ParsedRss:
        raise self._error()

    def _error(self) -> Stage1Error:
        return Stage1Error(
            "invalid_input",
            "不支持的数据源模式",
            "generate_request",
            {"source_mode": self._source_mode},
        )


def apply_ab_submit_action(
    result: dict[str, Any],
    submit_ab: bool,
    *,
    ab_config_path: Path | None = None,
    ab_config: AutoBangumiConfig | None = None,
    client: AutoBangumiClient | None = None,
) -> dict[str, Any]:
    if not submit_ab or not result["success"]:
        return result

    try:
        if ab_config is None and ab_config_path is None:
            raise Stage1Error(
                "config_error",
                "提交 Auto Bangumi 必须显式提供配置文件路径",
                "load_ab_config",
                {"field": "ab_config"},
            )

        resolved_ab_config = ab_config or load_ab_config(ab_config_path)
        request = result["request"]
        payload = build_ab_submit_payload(request, resolved_ab_config.auth_mode)
        ab_client = client or ab_http_client.create_auto_bangumi_submit_client(
            resolved_ab_config
        )
        ab_submit_result = submit_ab_subscription(
            ab_client,
            payload,
            fallback_enabled=resolved_ab_config.fallback_enabled,
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
        LOGGER.error("Auto Bangumi 提交发生未预期错误")
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
        LOGGER.error("订阅方案查询发生未预期错误")
        error = Stage1Error(
            "unexpected_error",
            "订阅方案查询发生未预期错误",
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
        LOGGER.error("订阅方案读取发生未预期错误")
        error = Stage1Error(
            "unexpected_error",
            "订阅方案读取发生未预期错误",
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
    parser.add_argument(
        "--mikan-bangumi",
        help="显式 MiKan Home/Bangumi URL 或数字 ID；仅在 --source mikan 时生效",
    )
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
    if args.title is None and args.mikan_bangumi is None:
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
        EntryRequest(raw_title=args.title or args.mikan_bangumi or ""),
        catalog_path=args.catalog,
        user_config_path=args.user_config,
        source_mode="mikan_http" if args.source == "mikan" else "static_fixture",
        mikan_config_path=args.mikan_config,
        mikan_bangumi=args.mikan_bangumi,
    )
    if modify_patch is not None:
        previous_request = result["request"] if result["success"] else None
        result = apply_modify_action(result, modify_patch)
        if result["success"] and previous_request is not None:
            history_events.append(
                build_history_event(
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
            build_history_event(
                previous_request,
                result["request"],
                action=args.action.upper(),
                details=confirmation_history_details(args.action, args.cancel_reason),
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
            "订阅方案查询参数不能同时使用",
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
