from __future__ import annotations

from shared.models import TitleCorrection
from shared.title_season import parse_title_season, season_variants


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
    season_number = parse_title_season(season_hint or "").season
    if season_number is not None:
        for alt in season_variants(season_number):
            variant = _replace_or_append_season(title, alt)
            if variant and variant != title:
                forms.append(variant)
    return _non_empty_unique(forms)


def _replace_or_append_season(title: str, alt: str) -> str:
    """Replace an existing season marker in ``title`` with ``alt`` or append it."""
    parsed = parse_title_season(title)
    if parsed.season is not None:
        return f"{parsed.base_title} {alt}".strip()
    return f"{title} {alt}".strip()


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
