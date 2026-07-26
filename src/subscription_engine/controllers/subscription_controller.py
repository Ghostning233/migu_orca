from __future__ import annotations

import re

from shared.errors import Stage1Error
from shared.models import FilteredRss, SubtitleGroupSelection


def select_subtitle_group(
    rss_results: list[FilteredRss],
    priority: list[str],
) -> SubtitleGroupSelection:
    usable = [result for result in rss_results if result.valid_seeds]
    if not usable:
        return SubtitleGroupSelection(
            subtitle_group=None,
            rss_url=None,
            warnings=["所有字幕组均没有有效种子，未设置默认字幕组"],
        )

    for preferred_group in priority:
        for result in usable:
            if result.source.subtitle_group == preferred_group:
                return SubtitleGroupSelection(
                    subtitle_group=result.source.subtitle_group,
                    rss_url=result.source.rss_url,
                )

    selected = usable[0]
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
