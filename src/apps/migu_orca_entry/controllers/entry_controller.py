from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Sequence

from catalog_engine.controllers.catalog_controller import load_catalog, match_bangumi
from request_engine.controllers.request_controller import build_pending_request
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="离线生成 MiGuOrca Request")
    parser.add_argument("title", help="番剧名称")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--user-config", type=Path, default=DEFAULT_USER_CONFIG_PATH)
    parser.add_argument("--log-file", type=Path)
    args = parser.parse_args(argv)

    configure_logging(args.log_file)
    result = generate_request(
        EntryRequest(raw_title=args.title),
        catalog_path=args.catalog,
        user_config_path=args.user_config,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["success"] else 1
