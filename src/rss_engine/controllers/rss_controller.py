from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from mikan_engine.controllers.mikan_client import (
    MikanTransport,
    UrlopenMikanTransport,
    _read_mikan_text,
)
from shared.errors import Stage1Error
from shared.models import (
    ExcludedSeed,
    FilteredRss,
    FilterRule,
    ParsedRss,
    RssSeed,
    RssSource,
)


DEFAULT_RSS_TIMEOUT_SECONDS = 10.0


def parse_rss(
    source: RssSource,
    project_root: Path,
    *,
    transport: MikanTransport | None = None,
    timeout: float = DEFAULT_RSS_TIMEOUT_SECONDS,
) -> ParsedRss:
    if source.source_type == "static_fixture":
        root = _load_static_fixture(source, project_root)
    elif source.source_type == "mikan_http":
        root = _load_mikan_http(source, transport=transport, timeout=timeout)
    else:
        raise Stage1Error(
            "rss_parse_failed",
            f"Stage 1 不支持 RSS 类型：{source.source_type}",
            "parse_rss",
        )

    return _parse_rss_root(source, root)


def _load_static_fixture(source: RssSource, project_root: Path) -> ElementTree.Element:
    fixture_path = Path(source.fixture_path)
    if not fixture_path.is_absolute():
        fixture_path = project_root / fixture_path
    try:
        return ElementTree.parse(fixture_path).getroot()
    except (OSError, ElementTree.ParseError) as exc:
        raise Stage1Error(
            "rss_parse_failed",
            f"RSS fixture 无法解析：{fixture_path}",
            "parse_rss",
            {"reason": str(exc)},
        ) from exc


def _load_mikan_http(
    source: RssSource,
    *,
    transport: MikanTransport | None,
    timeout: float,
) -> ElementTree.Element:
    rss_url = source.rss_url.strip()
    if not rss_url:
        raise Stage1Error(
            "rss_parse_failed",
            "MiKan RSS URL 不能为空",
            "parse_rss",
            {"source_type": source.source_type},
        )

    rss_transport = transport or UrlopenMikanTransport()
    try:
        xml_text = _read_mikan_text(
            rss_transport,
            rss_url,
            timeout=timeout,
            failed_step="parse_rss",
        )
    except Stage1Error:
        raise
    except Exception as exc:
        raise Stage1Error(
            "rss_parse_failed",
            "MiKan RSS 读取失败",
            "parse_rss",
            {"reason": exc.__class__.__name__},
        ) from exc

    try:
        return ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise Stage1Error(
            "rss_parse_failed",
            f"MiKan RSS XML 无法解析：{source.subtitle_group}",
            "parse_rss",
            {"reason": str(exc)},
        ) from exc


def _parse_rss_root(source: RssSource, root: ElementTree.Element) -> ParsedRss:
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
    must_contain = rule.must_contain
    must_not_contain = rule.must_not_contain
    valid: list[RssSeed] = []
    excluded: list[ExcludedSeed] = []
    for seed in parsed.seeds:
        if must_not_contain and _rule_matches(
            must_not_contain,
            seed.title,
            rule=rule,
            name="must_not_contain",
        ):
            excluded.append(
                ExcludedSeed(
                    name=seed.title,
                    reason=f"命中排除规则：{must_not_contain}",
                    rule="must_not_contain",
                )
            )
        elif must_contain and not _rule_matches(
            must_contain,
            seed.title,
            rule=rule,
            name="must_contain",
        ):
            excluded.append(
                ExcludedSeed(
                    name=seed.title,
                    reason=f"未命中包含规则：{must_contain}",
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


def _rule_matches(
    value: str,
    seed_name: str,
    *,
    rule: FilterRule,
    name: str,
) -> bool:
    """Match a single non-empty rule value against a seed name.

    use_regex=False performs a literal substring match; case_sensitive=False
    ignores case for both literal and regex matching. Regex compilation only
    happens when use_regex=True, so literal inputs such as ``[`` or ``[v2]``
    never raise a regex validation error.
    """
    if rule.use_regex:
        flags = 0 if rule.case_sensitive else re.IGNORECASE
        try:
            pattern = re.compile(value, flags)
        except re.error as exc:
            raise Stage1Error(
                "config_error",
                f"{name} 不是合法正则",
                "filter_seeds",
                {"rule": value, "reason": str(exc)},
            ) from exc
        return pattern.search(seed_name) is not None
    if rule.case_sensitive:
        return value in seed_name
    return value.lower() in seed_name.lower()
