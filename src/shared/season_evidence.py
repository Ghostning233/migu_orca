"""Conservative season evidence rules for selected public MiKan candidates."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from shared.errors import Stage1Error
from shared.title_season import parse_title_season


def candidate_season_evidence(
    title: str, aliases: Iterable[str], parser_season: int | None
) -> dict[str, object]:
    """Describe whether a candidate proves a parser season without guessing.

    The result is intentionally public and JSON-safe.  A parser season remains
    a search hint: it is only stored after matching candidate evidence or an
    explicit confirmation for a candidate with no season marker.
    """
    markers = [parse_title_season(value) for value in (title, *aliases)]
    proven = {item.season for item in markers if item.season is not None}
    if len(proven) > 1:
        return {"status": "CONFLICT", "season": None, "requires_review": True}
    candidate_season = next(iter(proven), None)
    if parser_season is None:
        return {
            "status": "PROVEN" if candidate_season is not None else "NONE",
            "season": candidate_season,
            "requires_review": False,
        }
    if candidate_season is None:
        return {
            "status": "NEEDS_CONFIRMATION",
            "season": parser_season,
            "requires_review": True,
        }
    if candidate_season != parser_season:
        return {"status": "CONFLICT", "season": None, "requires_review": True}
    return {"status": "PROVEN", "season": candidate_season, "requires_review": False}


def attach_selected_candidate_season(
    request: dict[str, Any], confirmed_season: int | None
) -> dict[str, Any]:
    """Attach only candidate-proven or explicitly-confirmed season metadata.

    ``request`` has already been built from a real MiKan detail page, so its
    title is the selected candidate's public title.  This helper never sees or
    copies parser canonical titles into the Request.
    """
    source_info = request.get("source_info")
    matched = source_info.get("matched_bangumi") if isinstance(source_info, dict) else None
    if not isinstance(matched, dict):
        return request
    title = matched.get("title")
    aliases = matched.get("aliases")
    evidence = candidate_season_evidence(
        title if isinstance(title, str) else "",
        aliases if isinstance(aliases, list) else (),
        confirmed_season,
    )
    status = evidence["status"]
    if status == "CONFLICT":
        raise Stage1Error(
            "season_evidence_conflict",
            "候选合集的季数与待确认季数冲突，请先人工核对",
            "selected_candidate_season",
            {"field": "season_confirmation"},
        )
    if status == "PROVEN" and evidence["season"] is not None:
        season = int(evidence["season"])
        marker = parse_title_season(str(title)).season_marker
        matched.update(
            {
                "season": season,
                "season_raw": marker or f"第{season}季",
                "season_evidence": "candidate_public_title",
            }
        )
    elif status == "NEEDS_CONFIRMATION" and confirmed_season is not None:
        matched.update(
            {
                "season": confirmed_season,
                "season_raw": f"第{confirmed_season}季",
                "season_evidence": "user_confirmed",
            }
        )
    return request


__all__ = ["attach_selected_candidate_season", "candidate_season_evidence"]
