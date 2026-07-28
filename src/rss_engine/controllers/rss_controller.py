from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from shared.errors import Stage1Error
from shared.models import (
    ExcludedSeed,
    FilteredRss,
    FilterRule,
    ParsedRss,
    RssSeed,
    RssSource,
)


def parse_rss(source: RssSource, project_root: Path) -> ParsedRss:
    if source.source_type != "static_fixture":
        raise Stage1Error(
            "rss_parse_failed",
            f"Stage 1 不支持 RSS 类型：{source.source_type}",
            "parse_rss",
        )
    fixture_path = Path(source.fixture_path)
    if not fixture_path.is_absolute():
        fixture_path = project_root / fixture_path
    try:
        root = ElementTree.parse(fixture_path).getroot()
    except (OSError, ElementTree.ParseError) as exc:
        raise Stage1Error(
            "rss_parse_failed",
            f"RSS fixture 无法解析：{fixture_path}",
            "parse_rss",
            {"reason": str(exc)},
        ) from exc

    seeds: list[RssSeed] = []
    warnings: list[str] = []
    for index, item in enumerate(root.findall(".//item"), start=1):
        title = _text(item.find("title"))
        link = _text(item.find("link"))
        if not title or not link:
            warnings.append(f"跳过第 {index} 个 item：缺少 title 或 link")
            continue
        seeds.append(
            RssSeed(
                title=title,
                link=link,
                published_at=_text(item.find("pubDate")),
                guid=_text(item.find("guid")),
            )
        )
    if not seeds:
        raise Stage1Error(
            "rss_parse_failed",
            f"RSS 中没有有效条目：{source.subtitle_group}",
            "parse_rss",
        )
    return ParsedRss(source=source, seeds=seeds, warnings=warnings)


def _text(element: ElementTree.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def filter_seeds(parsed: ParsedRss, rule: FilterRule) -> FilteredRss:
    must_contain = _compile_rule(rule.must_contain, "must_contain")
    must_not_contain = _compile_rule(rule.must_not_contain, "must_not_contain")
    valid: list[RssSeed] = []
    excluded: list[ExcludedSeed] = []
    for seed in parsed.seeds:
        if must_not_contain and must_not_contain.search(seed.title):
            excluded.append(
                ExcludedSeed(
                    name=seed.title,
                    reason=f"命中必须不含规则：{rule.must_not_contain}",
                    rule="must_not_contain",
                )
            )
        elif must_contain and not must_contain.search(seed.title):
            excluded.append(
                ExcludedSeed(
                    name=seed.title,
                    reason=f"未命中必须包含规则：{rule.must_contain}",
                    rule="must_contain",
                )
            )
        else:
            valid.append(seed)
    return FilteredRss(
        source=parsed.source,
        total_seed_count=len(parsed.seeds),
        valid_seeds=valid,
        excluded_seeds=excluded,
        warnings=parsed.warnings,
    )


def _compile_rule(value: str, name: str) -> re.Pattern[str] | None:
    if not value:
        return None
    try:
        return re.compile(value)
    except re.error as exc:
        raise Stage1Error(
            "config_error",
            f"{name} 不是合法正则",
            "filter_seeds",
            {"rule": value, "reason": str(exc)},
        ) from exc
