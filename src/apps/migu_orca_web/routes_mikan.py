from __future__ import annotations

"""MiKan-family API routes (US-191 split).

Migrated from ``views.py`` without behavior change. ``/api/v1/mikan/posters/<key>``
is the one function view that bypasses the ``APIBaseView`` envelope (see
``docs/api/endpoint_inventory.md`` §4.3 — US-192 will fold it into the unified
error handling).
"""

from flask import Response

from extensions.flask_api import class_route
from extensions.flask_api.views import PostView
from batch_engine.controllers.anime_title_parser import parse_anime_title
from batch_engine.models import BATCH_ITEM_STATUS_FAILED
from shared.errors import Stage1Error

from apps.migu_orca_web.blueprints import api_blueprint
from apps.migu_orca_web.schemas import MikanCandidateSearchPayload
from apps.migu_orca_web.serializers import (
    _serialize_parse_summary,
    _serialize_attempted_queries,
    _serialize_title_search_error,
    _with_candidate_season_evidence,
    poster_service,
)
from apps.migu_orca_web.services import (
    _resolve_mikan_config,
    _search_candidates_from_parse_result,
)


@class_route(api_blueprint, "/api/v1/mikan/candidates", methods=["POST"])
class MikanCandidateSearchView(PostView):
    request_validator_model = MikanCandidateSearchPayload

    def save(self) -> dict[str, object]:
        assert isinstance(self.request_validator_model, MikanCandidateSearchPayload)
        payload = self.request_validator_model
        mikan_config = _resolve_mikan_config(payload.mikan_config)
        parse_result = parse_anime_title(payload.query)
        searched = _search_candidates_from_parse_result(parse_result, mikan_config)
        result: dict[str, object] = {
            "query": payload.query,
            "status": searched.status,
            "parse_result": _serialize_parse_summary(parse_result),
            "attempted_queries": _serialize_attempted_queries(parse_result, searched),
            "candidates": [
                _with_candidate_season_evidence(candidate, parse_result)
                for candidate in searched.candidates
            ],
        }
        if searched.status == BATCH_ITEM_STATUS_FAILED:
            result["error"] = _serialize_title_search_error(
                searched.error
                or Stage1Error("mikan_search_failed", "MiKan 候选搜索失败", "mikan_search")
            )
        return result


@api_blueprint.get("/api/v1/mikan/posters/<key>")
def mikan_poster(key: str) -> Response:
    """Serve only a prior parser-registered poster under an opaque key."""
    path, content_type = poster_service.get(key)
    return Response(path.read_bytes(), content_type=content_type, headers={"Cache-Control": "private, max-age=86400"})
