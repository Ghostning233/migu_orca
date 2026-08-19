from __future__ import annotations

import re

from shared.models import TitleCorrection

#: Season marker that can already appear in a title (第四季 / 第4季 / S2 /
#: Season 2), so ``_replace_or_append_season`` can swap it for another form.
_SEASON_MARKER_RE = re.compile(
    r"第\s*[0-9一二三四五六七八九十百]+\s*季|\b[Ss]\d{1,2}\b|"
    r"\bSeason\s*\d{1,2}\b",
    re.IGNORECASE,
)

#: Individual season-hint shapes used to extract the season number.
_SEASON_S_RE = re.compile(r"^[Ss](\d{1,2})$")
_SEASON_SEASON_RE = re.compile(r"^Season\s*(\d{1,2})$", re.IGNORECASE)
_SEASON_CN_NUMERIC_RE = re.compile(r"^第\s*(\d{1,2})\s*季$")
_SEASON_CN_IDEOGRAPH_RE = re.compile(r"^第\s*([一二三四五六七八九十百]+)\s*季$")

_CN_DIGITS = "零一二三四五六七八九"


def enhance_search_queries(
    raw_title: str,
    search_queries: list[str],
    corrections: list[TitleCorrection],
) -> list[dict[str, str]]:
    """Return reviewable enhanced-query metadata for one batch item.

    Only explicitly-saved non-sensitive corrections are used (the correction
    repository rejects sensitive values on save and re-validates on load). A
    matching correction contributes the explicit ``query_correction`` and the
    public ``canonical_title``, each expanded into deterministic season variants
    (第N季 / 第四季 / S N / Season N), so Chinese/Japanese titles, numeric
    seasons, and romanized query corrections all become searchable variants.

    Each entry keeps ``query`` (the actual search string), ``original_query``
    (the parse result's query this derives from, for review), and ``source``
    (``correction:query`` or ``correction:canonical``). Returns ``[]`` when no
    correction matches, so the caller falls back to the original search_queries.
    """
    normalized = (raw_title or "").strip()
    correction = _find_correction(normalized, corrections)
    if correction is None:
        return []

    originals = _non_empty_unique(search_queries)
    base_original = originals[0] if originals else normalized

    enhanced: list[dict[str, str]] = []
    if correction.query_correction:
        for query in _season_variants(correction.query_correction, correction.season_hint):
            enhanced.append(
                {
                    "query": query,
                    "original_query": base_original,
                    "source": "correction:query",
                }
            )
    if correction.canonical_title:
        for query in _season_variants(correction.canonical_title, correction.season_hint):
            enhanced.append(
                {
                    "query": query,
                    "original_query": base_original,
                    "source": "correction:canonical",
                }
            )

    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in enhanced:
        query = entry["query"].strip()
        if not query or query in seen:
            continue
        seen.add(query)
        result.append(
            {
                "query": query,
                "original_query": entry["original_query"],
                "source": entry["source"],
            }
        )
    return result


def _find_correction(
    raw_title: str,
    corrections: list[TitleCorrection],
) -> TitleCorrection | None:
    if not raw_title:
        return None
    for correction in corrections:
        if correction.raw_title.strip() == raw_title:
            return correction
    lowered = raw_title.lower()
    for correction in corrections:
        if correction.raw_title.strip().lower() == lowered:
            return correction
    return None


def _season_variants(title: str, season_hint: str | None) -> list[str]:
    """Return the original title plus its alternative season forms."""
    forms = [title]
    season_number = _extract_season_number(season_hint)
    if season_number is not None:
        for alt in _season_alt_forms(season_number):
            variant = _replace_or_append_season(title, alt)
            if variant and variant != title:
                forms.append(variant)
    return _non_empty_unique(forms)


def _extract_season_number(season_hint: str | None) -> int | None:
    hint = (season_hint or "").strip()
    match = _SEASON_S_RE.match(hint)
    if match:
        return int(match.group(1))
    match = _SEASON_SEASON_RE.match(hint)
    if match:
        return int(match.group(1))
    match = _SEASON_CN_NUMERIC_RE.match(hint)
    if match:
        return int(match.group(1))
    match = _SEASON_CN_IDEOGRAPH_RE.match(hint)
    if match:
        return _chinese_to_arabic(match.group(1))
    return None


def _season_alt_forms(season_number: int) -> list[str]:
    """Return the alternative public season forms for a season number."""
    forms: list[str] = [f"第{season_number}季", f"S{season_number}", f"Season {season_number}"]
    chinese = _to_chinese_numeral(season_number)
    if chinese and f"第{chinese}季" not in forms:
        forms.append(f"第{chinese}季")
    return forms


def _replace_or_append_season(title: str, alt: str) -> str:
    """Replace an existing season marker in ``title`` with ``alt`` or append it."""
    match = _SEASON_MARKER_RE.search(title)
    if match:
        return (title[: match.start()] + alt + title[match.end() :]).strip()
    return f"{title} {alt}".strip()


def _to_chinese_numeral(number: int) -> str:
    if not 1 <= number <= 99:
        return str(number)
    if number < 10:
        return _CN_DIGITS[number]
    if number == 10:
        return "十"
    tens, ones = divmod(number, 10)
    prefix = "十" if tens == 1 else _CN_DIGITS[tens] + "十"
    if ones == 0:
        return prefix
    return prefix + _CN_DIGITS[ones]


def _chinese_to_arabic(text: str) -> int | None:
    if not text:
        return None
    if len(text) == 1:
        value = _CN_DIGITS.find(text)
        return value if value >= 0 else None
    value = 0
    if text.startswith("十"):
        value = 10
        text = text[1:]
    elif text.endswith("十"):
        tens = _CN_DIGITS.find(text[0])
        if tens <= 0:
            return None
        value = tens * 10
        text = text[:-1]
    else:
        parts = text.split("十")
        if len(parts) != 2:
            return None
        tens = _CN_DIGITS.find(parts[0])
        ones = _CN_DIGITS.find(parts[1])
        if tens <= 0 or ones < 0:
            return None
        value = tens * 10 + ones
        text = ""
    if text:
        ones = _CN_DIGITS.find(text)
        if ones < 0:
            return None
        value += ones
    return value if value > 0 else None


def _non_empty_unique(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = (value or "").strip()
        if text and text not in seen:
            deduped.append(text)
            seen.add(text)
    return deduped


__all__ = ["enhance_search_queries"]
