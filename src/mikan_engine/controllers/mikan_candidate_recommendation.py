"""Display-only recommendation labels for MiKan candidate cards.

Given a search query and a candidate's public metadata (title and optional
aliases), ``candidate_recommendation_label`` returns a short Chinese display
label that helps a user pick the intended collection: ``推荐：第 N 季`` for a
confident season match, ``季数不符`` when the query and candidate disagree on a
season, and ``可能匹配`` for a low-confidence title/alias match. The label only
annotates the card for display; it never selects the candidate or triggers
Request generation, and it never carries raw HTML, raw RSS XML, cookies,
tokens, or full failed URLs.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_CHINESE_NUMERALS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

# 第X季 where X is a Chinese numeral (possibly compound) or a bare ASCII number.
_CHINESE_SEASON_RE = re.compile(r"第\s*([一二两三四五六七八九十]{1,3}|[0-9]{1,2})\s*季")

# S1 / S2 / S01 ... S99, case-insensitive, not glued to another word.
_ASCII_SEASON_RE = re.compile(r"(?<![A-Za-z0-9])[Ss]([0-9]{1,2})(?![0-9])")

# Season 1 / Season 2 ... (English form, common on MiKan titles).
_ENGLISH_SEASON_RE = re.compile(r"\bseason\s+([0-9]{1,2})\b", re.IGNORECASE)

# Roman numerals as a trailing token (the last word) or inside parentheses.
# ``\b...\b`` would also match the English word "I", so Roman markers are only
# recognized at the end of a string or in explicit parentheses.
_ROMAN_SEASON_TRAILING_RE = re.compile(r"\b(IV|III|II|I)\b[)）]?\s*$")
_ROMAN_SEASON_PAREN_RE = re.compile(r"[(（]\s*(IV|III|II|I)\s*[)）]")

_ROMAN_VALUES = {
    "I": 1,
    "V": 5,
    "X": 10,
    "L": 50,
    "C": 100,
    "D": 500,
    "M": 1000,
}

_STRONG_SEASON_LABEL = "推荐：第 {season} 季"
_CONFLICT_SEASON_LABEL = "季数不符"
_WEAK_MATCH_LABEL = "可能匹配"


def candidate_recommendation_label(
    query: str,
    title: str,
    aliases: list[str] | None = None,
) -> str | None:
    """Return a display-only recommendation label for a candidate card.

    The label is computed from the search query and public candidate metadata
    (title and optional aliases). It never selects a candidate or triggers
    Request generation; callers must treat the result as display-only.

    Returns ``None`` when there is no confident signal (no basename/alias match,
    an empty query, or an empty candidate title).
    """
    query_text = query.strip()
    if not query_text:
        return None

    candidate_texts = [text for text in [title, *(aliases or [])] if text and text.strip()]
    if not candidate_texts:
        return None

    if not _basename_matches(query_text, candidate_texts):
        return None

    query_season = _extract_season(query_text)
    candidate_season = _first_season(candidate_texts)

    if query_season is not None:
        if candidate_season == query_season:
            return _STRONG_SEASON_LABEL.format(season=query_season)
        if candidate_season is not None:
            # The query and candidate disagree on the season; never show strong
            # recommendation copy for a conflicting season.
            return _CONFLICT_SEASON_LABEL
    return _WEAK_MATCH_LABEL


def _extract_season(text: str) -> int | None:
    """Extract a season number from a title/query string, or ``None``.

    Recognizes ``第X季`` (Chinese numeral or ASCII digit), ``S<n>``,
    ``Season <n>``, and Roman numerals (``I``/``II``/``III``/``IV``/...) that
    appear as a trailing token or inside parentheses. Returns the first match.
    """
    chinese_match = _CHINESE_SEASON_RE.search(text)
    if chinese_match is not None:
        return _chinese_numeral_to_int(chinese_match.group(1))

    ascii_match = _ASCII_SEASON_RE.search(text)
    if ascii_match is not None:
        value = int(ascii_match.group(1))
        if 1 <= value <= 99:
            return value

    english_match = _ENGLISH_SEASON_RE.search(text)
    if english_match is not None:
        value = int(english_match.group(1))
        if 1 <= value <= 99:
            return value

    paren_match = _ROMAN_SEASON_PAREN_RE.search(text)
    if paren_match is not None:
        return _roman_to_int(paren_match.group(1))

    trailing_match = _ROMAN_SEASON_TRAILING_RE.search(text)
    if trailing_match is not None:
        return _roman_to_int(trailing_match.group(1))

    return None


def _chinese_numeral_to_int(text: str) -> int | None:
    """Convert a Chinese numeral (up to 99) or ASCII digit string to an int."""
    if text.isascii() and text.isdecimal():
        value = int(text)
        return value if 1 <= value <= 99 else None

    if text == "十":
        return 10
    if len(text) == 1:
        return _CHINESE_NUMERALS.get(text)

    if "十" in text:
        parts = text.split("十")
        tens = _CHINESE_NUMERALS.get(parts[0]) if parts[0] else 1
        if tens is None:
            return None
        total = tens * 10
        if len(parts) > 1 and parts[1]:
            ones = _CHINESE_NUMERALS.get(parts[1])
            if ones is None:
                return None
            total += ones
        return total

    return None


def _roman_to_int(text: str) -> int | None:
    """Convert a Roman numeral string to an int, or ``None`` if invalid."""
    value = 0
    previous = 0
    for char in reversed(text.upper()):
        digit = _ROMAN_VALUES.get(char)
        if digit is None:
            return None
        if digit < previous:
            value -= digit
        else:
            value += digit
        previous = digit
    return value


def _first_season(texts: Iterable[str]) -> int | None:
    for text in texts:
        season = _extract_season(text)
        if season is not None:
            return season
    return None


def _basename_matches(query_text: str, candidate_texts: Iterable[str]) -> bool:
    """True when the query basename (season markers stripped) matches a candidate.

    Matching is a normalized substring comparison in either direction, so a query
    ``芙莉莲`` matches a candidate ``葬送的芙莉莲`` and vice versa.
    """
    query_core = _strip_season_markers(query_text)
    if not query_core:
        return False
    for text in candidate_texts:
        candidate_core = _strip_season_markers(text)
        if not candidate_core:
            continue
        if query_core in candidate_core or candidate_core in query_core:
            return True
    return False


def _strip_season_markers(text: str) -> str:
    """Remove season marker phrases so the basename can be compared."""
    stripped = text
    for pattern in (
        _CHINESE_SEASON_RE,
        _ASCII_SEASON_RE,
        _ENGLISH_SEASON_RE,
        _ROMAN_SEASON_PAREN_RE,
        _ROMAN_SEASON_TRAILING_RE,
    ):
        stripped = pattern.sub(" ", stripped)
    return _normalize_text(stripped)


def _normalize_text(text: str) -> str:
    return " ".join(text.casefold().split())
