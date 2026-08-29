from __future__ import annotations

"""MiKan-family API routes (US-191 split).

Migrated from ``views.py`` without behavior change. ``/api/v1/mikan/posters/<key>``
is the one binary function view that bypasses the ``APIBaseView`` envelope
(US-192): failures are folded into the unified error handling through
``failed_response`` + ``_error_http_status``, so clients always get a JSON
envelope with a classified status (see ``docs/api/endpoint_inventory.md`` §4.3).
"""

from flask import Response

from apps.migu_orca_web.blueprints import api_blueprint
from apps.migu_orca_web.schemas import MikanCandidateSearchPayload
from apps.migu_orca_web.serializers import (
    _serialize_attempted_queries,
    _serialize_parse_summary,
    _serialize_title_search_error,
    _with_candidate_season_evidence,
    poster_service,
)
from apps.migu_orca_web.services import (
    _resolve_mikan_config,
    _search_candidates_from_parse_result,
)
from batch_engine.controllers.anime_title_parser import parse_anime_title
from batch_engine.models import BATCH_ITEM_STATUS_FAILED
from extensions.flask_api import class_route
from extensions.flask_api.api import _error_http_status, failed_response
from extensions.flask_api.views import PostView
from shared.errors import Stage1Error


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
    """Serve only a prior parser-registered poster under an opaque key.

    This is the one binary function view that bypasses the JSON envelope
    (US-192). Failures are folded into the unified error handling: a JSON
    envelope with the mapped HTTP status (404 for unknown/unregistered keys,
    502 when the upstream poster fetch fails, 400 for malformed keys), so
    clients can always read ``error_type`` from the body. Successful responses
    stay raw image bytes with the documented content types.
    """
    try:
        path, content_type = poster_service.get(key)
    except Stage1Error as exc:
        # Keep the envelope shape identical to every other /api/v1 failure;
        # poster keys are opaque so the error details never echo the key.
        return failed_response(
            exc.error_type,
            exc.message,
            {"failed_step": exc.failed_step},
            status=_error_http_status(exc.error_type),
        )
    return Response(
        path.read_bytes(),
        content_type=content_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )
