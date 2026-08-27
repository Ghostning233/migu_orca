from __future__ import annotations

import pytest

from shared.errors import Stage1Error
from shared.season_evidence import attach_selected_candidate_season, candidate_season_evidence


def _request(title: str) -> dict[str, object]:
    return {"source_info": {"matched_bangumi": {"title": title, "aliases": []}}}


def test_candidate_evidence_requires_explicit_confirmation_without_public_marker() -> None:
    assert candidate_season_evidence("无职转生", [], 4) == {
        "status": "NEEDS_CONFIRMATION", "season": 4, "requires_review": True,
    }
    with pytest.raises(Stage1Error, match="明确确认"):
        attach_selected_candidate_season(_request("无职转生"), 4, None)
    request = attach_selected_candidate_season(_request("无职转生"), 4, 4)
    assert request["source_info"]["matched_bangumi"]["season"] == 4  # type: ignore[index]
    assert request["source_info"]["matched_bangumi"]["season_evidence"] == "user_confirmed"  # type: ignore[index]


def test_candidate_public_title_proves_matching_season_without_parser_override() -> None:
    request = attach_selected_candidate_season(_request("无职转生 第四季"), 4, None)
    matched = request["source_info"]["matched_bangumi"]  # type: ignore[index]
    assert matched["title"] == "无职转生 第四季"
    assert matched["season_evidence"] == "candidate_public_title"


def test_server_trusted_candidate_alias_can_prove_season() -> None:
    request = _request("无职转生")
    request["source_info"]["matched_bangumi"]["aliases"] = ["无职转生 S4"]  # type: ignore[index]
    matched = attach_selected_candidate_season(request, None, None)["source_info"]["matched_bangumi"]  # type: ignore[index]
    assert matched["season"] == 4
    assert matched["season_evidence"] == "candidate_public_title"


def test_conflicting_candidate_season_fails_closed() -> None:
    with pytest.raises(Stage1Error, match="冲突"):
        attach_selected_candidate_season(_request("无职转生 第三季"), 4, None)
