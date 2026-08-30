from __future__ import annotations

"""Public /api/v1 response DTOs (US-190).

Every public success/failure envelope and its ``result`` payload is modelled
here with ``extra="forbid"`` so an unknown field (a typo, a leaked engine
dict, a future accidental addition) fails validation instead of silently
passing through the API boundary.

Scope notes
-----------
- The *request* schemas live in ``schemas.py`` (``RequestCreatePayload``
  etc.) and are wired to the view validation; this module is the response
  half of the contract.
- Deep engine dicts that are intentionally opaque to the frontend
  (``request`` snapshots, preference/correction objects, batch items,
  ``parse_result``, queue items, AB/qBittorrent results) are typed as
  ``dict[str, Any]``/``list[dict[str, Any]]`` *inside* a whitelisted
  envelope.  The DTOs therefore guarantee the envelope shape and the
  **top-level** result keys, while per-field secret sanitization stays in the
  existing serializers/sanitizers that own those dicts.  This mirrors the
  current API contract (golden tests freeze the envelope and top-level
  result keys) without pretending the opaque dicts are fully typed today.
- ``strict_success_result`` exists for tests that must prove a *specific*
  DTO rejects unknown fields in its whitelisted ``result`` sub-shape
  (e.g. the connection-test whitelist and the request ``summary``).
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from extensions.flask_api.api import ok_response

# ---------------------------------------------------------------------------
# Shared envelopes
# ---------------------------------------------------------------------------


class _StrictBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApiOkEnvelope(_StrictBase):
    """Successful envelope: ``{"ok": true, "result": {...}}``."""

    ok: bool = Field(description="Always true for success.")
    result: Any = Field(description="Endpoint-specific success payload.")


class ApiErrorEnvelope(_StrictBase):
    """Failed envelope: ``{"ok": false, "error_type", "error_message", ...}``.

    ``error_data`` is optional and, when present, always carries at least a
    ``failed_step`` plus endpoint-specific safe details.
    """

    ok: bool = Field(description="Always false for failures.")
    error_type: str
    error_message: str
    error_data: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Requests family
# ---------------------------------------------------------------------------


class RequestSummaryDTO(_StrictBase):
    """Public ``summary`` shape produced by ``summarize_request``."""

    request_id: str | None
    status: str | None
    bangumi_title: str | None
    candidate_subtitle_groups: list[dict[str, Any]]
    selected_subtitle_group: str | None
    effective_seed_count: int
    expected_folder_name: str | None
    warnings: list[str]


class RequestListResultDTO(_StrictBase):
    """Public list-result whitelist: every entry is a full summary DTO.

    US-202: the new frontend consumes ``GET /api/v1/requests`` exclusively
    through the generated TypeScript client, so the result shape is typed at
    the boundary instead of a bare ``list[dict[str, Any]]``.
    """

    requests: list[RequestSummaryDTO]


class RequestDetailResultDTO(_StrictBase):
    request: dict[str, Any]
    history: dict[str, Any]
    ab_result: dict[str, Any]


class RequestCreateResultDTO(_StrictBase):
    request: dict[str, Any]
    summary: RequestSummaryDTO
    saved_request: dict[str, Any] | None = None
    draft_id: str | None = None


class RequestPreviewModifyResultDTO(_StrictBase):
    request: dict[str, Any]
    summary: RequestSummaryDTO
    draft_id: str | None = None


class RequestPreviewSaveResultDTO(_StrictBase):
    """preview-save result equals the create result shape (draft consumed)."""

    request: dict[str, Any]
    summary: RequestSummaryDTO
    saved_request: dict[str, Any] | None = None


class RequestActionResultDTO(RequestCreateResultDTO):
    """accept/cancel/modify results equal the create result shape."""


class RequestDeleteResultDTO(_StrictBase):
    request_id: str
    storage: str
    directory: str
    filename: str
    deleted: bool


class AbSubmitResultDTO(_StrictBase):
    """Public Auto Bangumi submit-result whitelist.

    ``ab_response`` is sanitized by ``_sanitize_ab_submit_result`` (never
    carries tokens/cookies/URLs); ``fallback_config`` is an opaque
    non-sensitive fallback payload when enabled.
    """

    success: bool
    ab_subscription_id: str | None
    ab_response: dict[str, Any]
    fallback_config: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class RequestAbSubmitResultDTO(RequestCreateResultDTO):
    ab_submit_result: AbSubmitResultDTO
    saved_ab_result: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# MiKan family
# ---------------------------------------------------------------------------


class MikanCandidateResultDTO(_StrictBase):
    query: str
    status: str
    parse_result: dict[str, Any]
    attempted_queries: list[dict[str, Any]]
    candidates: list[dict[str, Any]]
    error: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Preferences / Corrections family
# ---------------------------------------------------------------------------


class SubtitleGroupPreferenceDTO(_StrictBase):
    """Non-sensitive subtitle-group preference section.

    ``preferred``/``excluded`` are display lists (Chinese business names);
    ``fallback`` is the stable internal code (``next_preferred``/``none``)
    rendered via the shared select primitive — never shown as raw text.
    """

    preferred: list[str]
    excluded: list[str]
    fallback: str


class FilterDefaultsDTO(_StrictBase):
    """Non-sensitive default filter rule section."""

    must_contain: str
    must_not_contain: str
    use_regex: bool
    case_sensitive: bool


class NamingPreferenceDTO(_StrictBase):
    """Non-sensitive default naming section (folder-name defaults only)."""

    strategy: str
    template: str


class SearchPreferenceDTO(_StrictBase):
    """Non-sensitive default search section."""

    reuse_explicit_corrections: bool


class PreferenceResultDTO(_StrictBase):
    version: int
    subtitle_groups: SubtitleGroupPreferenceDTO
    filter_defaults: FilterDefaultsDTO
    naming: NamingPreferenceDTO
    search: SearchPreferenceDTO


class CorrectionsResultDTO(_StrictBase):
    corrections: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Batches family
# ---------------------------------------------------------------------------


class BatchParseResultDTO(_StrictBase):
    batch_id: str
    raw_input: str
    items: list[dict[str, Any]]


class BatchQueueResultDTO(_StrictBase):
    batch_id: str
    queue: dict[str, Any] | None = None


class BatchAcceptResultDTO(_StrictBase):
    batch_id: str
    queue: dict[str, Any]
    items: list[dict[str, Any]]
    summary: dict[str, int]


class BatchSubmitResultDTO(BatchAcceptResultDTO):
    """submit/retry/recover results equal the accept result shape."""


# ---------------------------------------------------------------------------
# Connection tests family
# ---------------------------------------------------------------------------


class QbittorrentConnectionResultDTO(_StrictBase):
    """Public whitelist; endpoint/username/password/cookie never appear."""

    status: str
    reachable: bool
    version: str


class AutoBangumiConnectionResultDTO(_StrictBase):
    """Public whitelist; base_url/token/credentials never appear."""

    reachable: bool
    authenticated: bool
    version: str
    auth_mode: str
    adapter: str
    submit_supported: bool


# ---------------------------------------------------------------------------
# Serialization entry points (envelope-level validation)
# ---------------------------------------------------------------------------


def ok_result(result: Any, dto: type[BaseModel] | None = None) -> Any:
    """Return a validated ``{ok: true, result}`` envelope.

    When ``dto`` is given the result is validated against it first, so a
    whitelisted result shape that gains an unexpected field fails loudly.
    The validated model is dumped to JSON-safe dicts before the shared
    ``ok_response`` envelope is built (Flask's jsonify cannot serialize
    pydantic models directly).
    """
    if dto is not None:
        result = dto.model_validate(result).model_dump(mode="json")
    return ok_response(result)
