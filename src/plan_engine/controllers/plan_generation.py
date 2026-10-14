from __future__ import annotations

"""CLI-free subscription-plan generation entry (issue #174).

`build_plan` is the single orchestration entry for turning a raw title (or a
direct MiKan entry) into a PENDING_CONFIRM plan snapshot. It knows nothing about
``source_mode``/``catalog_path``/``user_config_path``/``project_root``: all of
that is resolved by the injected `PlanDataSource`.
"""

import logging
from typing import Any

from catalog_engine.controllers.catalog_controller import match_bangumi
from plan_engine.controllers.data_sources import PlanDataSource
from request_engine.controllers.request_controller import build_pending_request
from rss_engine.controllers.rss_controller import filter_seeds
from shared.errors import Stage1Error
from shared.models import EntryRequest, FilteredRss
from subscription_engine.controllers.subscription_controller import (
    generate_folder_name,
    select_subtitle_group,
)

LOGGER = logging.getLogger(__name__)


def build_plan(
    entry: EntryRequest,
    *,
    data_source: PlanDataSource,
    mikan_bangumi: str | None = None,
) -> dict[str, Any]:
    """Build a subscription plan snapshot for ``entry``.

    ``mikan_bangumi`` is the optional user-supplied direct MiKan entry (a numeric
    ID or Home/Bangumi URL); whether it is supported is decided by the data
    source. Returns the stable action envelope
    ``{"success", "request", "error"}`` used across the plan seam.
    """

    try:
        direct_entry_provided = mikan_bangumi is not None
        direct_entry = (mikan_bangumi or "").strip()
        if direct_entry_provided and not direct_entry:
            raise Stage1Error(
                "invalid_input",
                "MiKan bangumi 直连入口必须是数字 ID 或 Home/Bangumi URL",
                "mikan_direct_entry",
                {"field": "mikan_bangumi"},
            )
        if not entry.raw_title.strip() and not direct_entry:
            raise Stage1Error("invalid_input", "番剧名称不能为空", "validate_input")

        preference = data_source.load_preference()
        if direct_entry:
            resolution = data_source.resolve_direct_entry(direct_entry)
            matched = resolution.matched
            rss_sources = resolution.rss_sources
        else:
            matched, candidate = match_bangumi(
                entry.raw_title,
                data_source.list_candidates(entry.raw_title),
            )
            rss_sources = data_source.list_rss_sources(matched, candidate)

        rss_results: list[FilteredRss] = []
        flow_warnings: list[str] = []
        for source in rss_sources:
            try:
                parsed = data_source.parse_rss(source)
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
        LOGGER.error("订阅方案生成发生未预期错误")
        error = Stage1Error(
            "unexpected_error",
            "订阅方案生成发生未预期错误",
            "generate_request",
            {"reason": str(exc)},
        )
        return {"success": False, "request": None, "error": error.as_dict()}
