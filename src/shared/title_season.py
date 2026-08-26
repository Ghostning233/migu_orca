"""Conservative, shared season-marker parsing for public anime titles.

This module deliberately recognizes only explicit one-to-ninety-nine season
markers.  A parsed season is a search/display hint, never confirmation that a
selected MiKan candidate has that season.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

_SEASON_MARKER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<s>[Ss]\s*(?P<s_number>\d{1,3}))(?!\d)"
    r"|\b(?P<english>Season\s*(?P<english_number>\d{1,3}))\b"
    r"|(?P<chinese>第\s*(?P<chinese_number>[零一二三四五六七八九十两\d]+)\s*(?P<suffix>季|期))"
)
_UNSUPPORTED_MARKER_RE = re.compile(r"\b[Ss](?:\s*\d*)\b|\bSeason\b|第\s*[^\s季期]*\s*[季期]")
_PART_MARKER_RE = re.compile(r"\bPart\s*\d+\b|分割放送|分割", re.IGNORECASE)
_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


@dataclass(frozen=True)
class TitleSeasonParse:
    """The normalized title and only a provable explicit season, if any."""

    normalized_title: str
    base_title: str
    season: int | None
    season_hint: str | None
    season_marker: str | None = None
    review_hints: tuple[str, ...] = ()


def parse_title_season(title: str) -> TitleSeasonParse:
    """Parse explicit season markers without guessing a default first season."""

    normalized = _normalize(title)
    matches = list(_SEASON_MARKER_RE.finditer(normalized))
    numbers = {_marker_number(match) for match in matches}
    valid_numbers = {number for number in numbers if number is not None and 1 <= number <= 99}
    has_invalid = any(number is None or not 1 <= number <= 99 for number in numbers)
    unsupported = bool(_UNSUPPORTED_MARKER_RE.search(normalized)) and not matches
    part_only = bool(_PART_MARKER_RE.search(normalized)) and not matches

    hints: list[str] = []
    season: int | None = None
    marker: re.Match[str] | None = None
    if len(valid_numbers) == 1 and not has_invalid:
        season = valid_numbers.pop()
        marker = matches[0]
    elif len(valid_numbers) > 1:
        hints.append("识别到冲突季数，请人工核对")
    elif has_invalid or unsupported or part_only:
        hints.append("季数标记无法确认，请人工核对")

    if season is not None and marker is not None:
        base = _normalize(_SEASON_MARKER_RE.sub(" ", normalized))
        return TitleSeasonParse(
            normalized_title=_normalize(f"{base} 第{_to_chinese_numeral(season)}季"),
            base_title=base or normalized,
            season=season,
            season_hint=f"S{season}",
            season_marker=marker.group(0),
            review_hints=tuple(hints),
        )
    return TitleSeasonParse(normalized, normalized, None, None, None, tuple(hints))


def season_variants(number: int) -> tuple[str, ...]:
    """Return stable public spellings for a known one-to-ninety-nine season."""

    if not 1 <= number <= 99:
        return ()
    return (f"第{number}季", f"S{number}", f"Season {number}", f"第{_to_chinese_numeral(number)}季")


def _marker_number(match: re.Match[str]) -> int | None:
    number = match.group("s_number") or match.group("english_number")
    if number is not None:
        return int(number)
    return _chinese_to_int(match.group("chinese_number") or "")


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _chinese_to_int(value: str) -> int | None:
    if value.isdecimal():
        return int(value)
    if value in _CN_DIGITS:
        return _CN_DIGITS[value]
    if value == "十":
        return 10
    if "十" not in value or value.count("十") != 1:
        return None
    tens, ones = value.split("十")
    if tens and tens not in _CN_DIGITS:
        return None
    if ones and ones not in _CN_DIGITS:
        return None
    return (1 if not tens else _CN_DIGITS[tens]) * 10 + (0 if not ones else _CN_DIGITS[ones])


def _to_chinese_numeral(number: int) -> str:
    if number < 10:
        return "零一二三四五六七八九"[number]
    tens, ones = divmod(number, 10)
    prefix = "十" if tens == 1 else "零一二三四五六七八九"[tens] + "十"
    return prefix if not ones else prefix + "零一二三四五六七八九"[ones]


__all__ = ["TitleSeasonParse", "parse_title_season", "season_variants"]
