from __future__ import annotations

from copy import deepcopy
import re
from urllib.parse import urlparse
from typing import Any, Literal

from request_engine.controllers.request_controller import ACCEPTED
from shared.errors import Stage1Error
from shared.title_season import parse_title_season


def build_ab_subscription_payload(request: dict[str, Any]) -> dict[str, Any]:
    """Map an accepted Request snapshot to an Auto Bangumi subscription payload."""

    status = request.get("status")
    if status != ACCEPTED:
        raise Stage1Error(
            "invalid_request_status",
            "只有已确认订阅方案可以提交到 Auto Bangumi",
            "build_ab_subscription_payload",
            {"status": status},
        )

    confirmable = request.get("confirmable_config", {})
    rss_url = _required_string(
        confirmable.get("selected_rss_url"),
        "selected_rss_url",
    )
    folder_name = _required_string(
        confirmable.get("expected_folder_name"),
        "expected_folder_name",
    )

    return {
        "title": _required_string(_request_title(request), "title"),
        "rss_url": rss_url,
        "save_path": folder_name,
        "filter_rule": deepcopy(confirmable.get("filter_rule", {})),
    }


def build_legacy_31_subscription_payload(request: dict[str, Any]) -> dict[str, Any]:
    """Map an accepted Request to AutoBangumi 3.1's subscribe body.

    AutoBangumi 3.1 expects two named JSON arguments, ``data: Bangumi`` and
    ``rss: RSSItem``.  Keep this conversion pure so every submit entry point
    can prepare exactly the same body without retaining request credentials.
    """

    payload = build_ab_subscription_payload(request)
    official_title = _required_string(payload["title"], "title")
    title_raw = official_title
    rss_url = _required_string(payload["rss_url"], "rss_url")
    save_path = _required_string(payload["save_path"], "save_path")
    subtitle_group = _required_string(
        request.get("confirmable_config", {}).get("selected_subtitle_group"),
        "selected_subtitle_group",
    )
    bangumi = request.get("source_info", {}).get("matched_bangumi", {})
    season, season_raw = _legacy_31_season(bangumi, official_title, title_raw)
    optional_metadata = _legacy_31_optional_metadata(bangumi)
    poster_link = _legacy_31_poster_link(bangumi)
    return {
        "data": {
            # These are the public fields AutoBangumi 3.1 uses to identify a
            # Bangumi.  Keep the raw user input distinct from the confirmed
            # canonical title instead of silently replacing one with the other.
            "official_title": official_title,
            "title_raw": title_raw,
            "season": season,
            "group_name": subtitle_group,
            "filter": _legacy_31_filter(payload["filter_rule"]),
            "rss_link": rss_url,
            "save_path": save_path,
            "poster_link": poster_link,
            **({"season_raw": season_raw} if season_raw else {}),
            **optional_metadata,
        },
        "rss": {
            "name": official_title,
            "url": rss_url,
            "aggregate": False,
            "parser": "mikan",
        },
    }


def build_ab_submit_payload(
    request: dict[str, Any], auth_mode: Literal["password", "api_token"]
) -> dict[str, Any]:
    """Build the verified subscription body for one authentication adapter."""

    if auth_mode == "password":
        return build_legacy_31_subscription_payload(request)
    return build_ab_subscription_payload(request)


def _legacy_31_filter(value: Any) -> str:
    """Encode only rules with the same exclusion semantics as AutoBangumi 3.1.

    AutoBangumi 3.1 treats ``Bangumi.filter`` as an exclusion expression: a
    matching torrent is skipped.  The output therefore matches either a title
    that fails MiGuOrca's all-terms ``must_contain`` rule or one that matches
    its any-term ``must_not_contain`` rule.
    """

    if not isinstance(value, dict):
        raise Stage1Error(
            "ab_filter_unsupported",
            "当前筛选规则无法兼容 Auto Bangumi 3.1",
            "build_legacy_31_subscription_payload",
        )
    must_contain = _filter_string(value, "must_contain")
    must_not_contain = _filter_string(value, "must_not_contain")
    use_regex = value.get("use_regex", False)
    case_sensitive = value.get("case_sensitive", False)
    if not isinstance(use_regex, bool) or not isinstance(case_sensitive, bool):
        raise Stage1Error(
            "ab_filter_unsupported",
            "当前筛选规则无法兼容 Auto Bangumi 3.1",
            "build_legacy_31_subscription_payload",
        )
    contains_terms = _filter_terms(must_contain)
    excluded_terms = _filter_terms(must_not_contain)
    terms = [*contains_terms, *excluded_terms]
    prepared = [term if use_regex else re.escape(term) for term in terms]
    try:
        for term in prepared:
            re.compile(term, 0 if case_sensitive else re.IGNORECASE)
    except re.error as exc:
        raise Stage1Error(
            "ab_filter_unsupported",
            "当前筛选规则无法兼容 Auto Bangumi 3.1",
            "build_legacy_31_subscription_payload",
        ) from exc
    if not prepared:
        # AutoBangumi calls re.search(); this is an explicitly never-matching
        # regex, so an empty MiGuOrca rule excludes nothing.
        return "(?!)"

    flags = "(?s)" if case_sensitive else "(?is)"
    contains_exclusion = [
        f"^(?!.*(?:{term})).*$" for term in prepared[: len(contains_terms)]
    ]
    excluded_exclusion = [
        f".*(?:{term}).*" for term in prepared[len(contains_terms) :]
    ]
    expression = f"{flags}(?:{'|'.join([*contains_exclusion, *excluded_exclusion])})"
    try:
        # A regex may compile in isolation but be invalid once placed in the
        # exclusion expression (for example a global inline flag such as
        # ``(?i)``).  AutoBangumi receives the complete expression, so prove
        # that exact expression is valid before allowing a write attempt.
        re.compile(expression)
    except re.error as exc:
        raise Stage1Error(
            "ab_filter_unsupported",
            "当前筛选规则无法兼容 Auto Bangumi 3.1",
            "build_legacy_31_subscription_payload",
        ) from exc
    return expression


def _filter_string(value: dict[str, Any], field: str) -> str:
    candidate = value.get(field, "")
    if not isinstance(candidate, str):
        raise Stage1Error(
            "ab_filter_unsupported",
            "当前筛选规则无法兼容 Auto Bangumi 3.1",
            "build_legacy_31_subscription_payload",
        )
    return candidate.strip()


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Stage1Error(
            "missing_ab_payload_field",
            "Auto Bangumi payload 缺少必填字段",
            "build_ab_subscription_payload",
            {"field": f"confirmable_config.{field}"},
        )
    return value.strip()


def _filter_terms(value: str) -> list[str]:
    """Mirror Request filtering: pipe-separated contains are all/any rules."""

    return [term.strip() for term in value.split("|") if term.strip()]


def _legacy_31_season(
    bangumi: Any, official_title: str, title_raw: str
) -> tuple[int, str | None]:
    """Resolve only an explicit non-first season; otherwise use first season.

    MiGuOrca Requests do not currently persist a dedicated season field.  A
    non-first season must consequently be visible in the accepted public title
    metadata; it is never guessed from a folder name or silently downgraded.
    """

    if isinstance(bangumi, dict):
        explicit = bangumi.get("season")
        if (
            isinstance(explicit, int)
            and not isinstance(explicit, bool)
            and explicit > 0
        ):
            raw = bangumi.get("season_raw")
            return explicit, raw.strip() if isinstance(raw, str) and raw.strip() else None
    # Only the canonical title retained in the accepted Request is public
    # confirmation data.  Never infer season from the original free-form
    # input, which may differ from the user's confirmed selection.
    del title_raw
    parsed = parse_title_season(official_title)
    if parsed.season is not None:
        return parsed.season, parsed.season_marker
    if parsed.review_hints:
        raise Stage1Error(
            "ab_season_unsupported",
            "当前番剧季数无法兼容 Auto Bangumi 3.1",
            "build_legacy_31_subscription_payload",
        )
    return 1, None


def _parse_chinese_or_arabic_season(value: str) -> int | None:
    """Parse explicit ``第…季`` markers from one through ninety-nine."""

    if value.isascii() and value.isdecimal():
        number = int(value)
        return number if 1 <= number <= 99 else None
    digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if value in digits:
        return digits[value]
    if value == "十":
        return 10
    if len(value) == 2 and value[0] == "十" and value[1] in digits:
        return 10 + digits[value[1]]
    if len(value) == 2 and value[0] in digits and value[1] == "十":
        return digits[value[0]] * 10
    if len(value) == 3 and value[0] in digits and value[1] == "十" and value[2] in digits:
        return digits[value[0]] * 10 + digits[value[2]]
    return None


def _legacy_31_optional_metadata(bangumi: Any) -> dict[str, str]:
    if not isinstance(bangumi, dict):
        return {}
    return {
        field: value.strip()
        for field in ("dpi", "source", "subtitle")
        if isinstance((value := bangumi.get(field)), str) and value.strip()
    }


def _legacy_31_poster_link(bangumi: Any) -> str | None:
    """Return only a server-trusted public source poster for AB 3.1.18."""
    if not isinstance(bangumi, dict):
        return None
    value = bangumi.get("poster_url")
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    parsed = urlparse(candidate)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or any(ord(char) < 32 or ord(char) == 127 for char in candidate)
    ):
        return None
    return candidate


def _request_title(request: dict[str, Any]) -> str | None:
    source_info = request.get("source_info", {})
    matched = source_info.get("matched_bangumi", {})
    title = matched.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return None


def _raw_title(request: dict[str, Any]) -> str | None:
    raw_title = request.get("input", {}).get("raw_title")
    if isinstance(raw_title, str) and raw_title.strip():
        return raw_title.strip()
    return None
