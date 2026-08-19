from __future__ import annotations

import re

from shared.errors import Stage1Error
from shared.models import FilteredRss, SubtitleGroupSelection


def select_subtitle_group(
    rss_results: list[FilteredRss],
    priority: list[str],
    excluded: list[str] | None = None,
) -> SubtitleGroupSelection:
    """Pick the default subtitle group from filtered RSS results.

    M05 recommendation order (Stage 21): excluded groups are filtered out
    first, then the user's preferred groups are tried in priority order, then
    the first remaining usable group is the fallback. A group is usable only
    when it has at least one valid seed; a group with no valid seeds can never
    be selected.
    """
    excluded_set = set(excluded or [])
    usable = [result for result in rss_results if result.valid_seeds]
    available = [
        result for result in usable if result.source.subtitle_group not in excluded_set
    ]
    if not available:
        if usable:
            return SubtitleGroupSelection(
                subtitle_group=None,
                rss_url=None,
                warnings=["所有有效字幕组均被排除，未设置默认字幕组"],
            )
        return SubtitleGroupSelection(
            subtitle_group=None,
            rss_url=None,
            warnings=["所有字幕组均没有有效种子，未设置默认字幕组"],
        )

    for preferred_group in priority:
        if preferred_group in excluded_set:
            continue
        for result in available:
            if result.source.subtitle_group == preferred_group:
                return SubtitleGroupSelection(
                    subtitle_group=result.source.subtitle_group,
                    rss_url=result.source.rss_url,
                )

    selected = available[0]
    return SubtitleGroupSelection(
        subtitle_group=selected.source.subtitle_group,
        rss_url=selected.source.rss_url,
        warnings=["用户字幕组优先级未命中，已选择第一个有效候选"],
    )


def generate_folder_name(title: str) -> str:
    cleaned = re.sub(r"[/\\\x00]", "_", title.strip())
    if not cleaned:
        raise Stage1Error(
            "folder_name_failed",
            "匹配番剧标题无法生成文件夹名",
            "generate_folder_name",
        )
    return cleaned
