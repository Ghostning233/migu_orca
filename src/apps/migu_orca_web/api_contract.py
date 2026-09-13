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

from typing import Any, Literal

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


class RequestSubtitleGroupSummaryDTO(_StrictBase):
    """Strict public summary for one candidate subtitle group.

    Request list consumers only need the group label and resource counts.  In
    particular, RSS URLs and any other source metadata are deliberately not
    part of this DTO.
    """

    subtitle_group: str | None
    total_resource_count: int
    valid_resource_count: int
    invalid_resource_count: int


class RequestSummaryDTO(_StrictBase):
    """Public ``summary`` shape produced by ``summarize_request``."""

    request_id: str | None
    status: str | None
    bangumi_title: str | None
    season: int | None
    updated_at: str | None
    candidate_subtitle_groups: list[RequestSubtitleGroupSummaryDTO]
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


class _SnapshotBase(BaseModel):
    """Base for opaque engine snapshot shapes (detail/action responses).

    Unlike the whitelisted envelope DTOs (``extra="forbid"``), engine
    snapshot dicts may legitimately gain fields over time. ``extra="allow"``
    lets them pass through the boundary while the typed fields give the
    generated TypeScript client stable display types for the fields the UI
    renders. The response half is not re-serialized through these models at
    runtime (the views return the engine dicts as-is), so the emitted field
    set is never altered.
    """

    model_config = ConfigDict(extra="allow")


class RequestInputDTO(_SnapshotBase):
    raw_title: str | None = None


class MatchedBangumiDTO(_SnapshotBase):
    title: str | None = None
    aliases: list[str] = []
    mikan_url: str | None = None
    match_score: float | None = None
    poster_url: str | None = None


class RssSourceDTO(_SnapshotBase):
    subtitle_group: str | None = None
    rss_url: str | None = None
    source_type: str | None = None
    total_seed_count: int | None = None
    seed_names: list[str] = []
    valid_seed_count: int | None = None
    invalid_seed_count: int | None = None
    valid_seed_names: list[str] = []
    excluded_seed_names: list[dict[str, Any]] = []
    warnings: list[str] = []


class SourceInfoDTO(_SnapshotBase):
    matched_bangumi: MatchedBangumiDTO | None = None
    rss_sources: list[RssSourceDTO] = []


class FilterRuleDTO(_SnapshotBase):
    must_contain: str | None = None
    must_not_contain: str | None = None
    use_regex: bool | None = None
    case_sensitive: bool | None = None


class ConfirmableConfigDTO(_SnapshotBase):
    selected_subtitle_group: str | None = None
    selected_rss_url: str | None = None
    filter_rule: FilterRuleDTO | None = None
    effective_seed_names: list[str] = []
    expected_folder_name: str | None = None
    warnings: list[str] = []


class UserActionDTO(_SnapshotBase):
    action: str | None = None
    reason: str | None = None
    decided_at: str | None = None


class RequestSnapshotDTO(_SnapshotBase):
    """Typed view of the saved Request snapshot the detail panel renders.

    Only the display fields are typed; the engine may add fields without
    breaking the boundary (``extra="allow"``). ``mikan_url``/``rss_url``/
    ``poster_url`` are declared for schema accuracy but the frontend must
    never render them (URLs are redacted at display time).
    """

    request_id: str | None = None
    status: str | None = None
    input: RequestInputDTO | None = None
    source_info: SourceInfoDTO | None = None
    confirmable_config: ConfirmableConfigDTO | None = None
    ab_submit_result: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None
    user_action: UserActionDTO | None = None


class HistoryEventDTO(_SnapshotBase):
    request_id: str | None = None
    previous_status: str | None = None
    next_status: str | None = None
    action: str | None = None
    timestamp: str | None = None
    details: dict[str, Any] | None = None


class HistorySectionDTO(_SnapshotBase):
    available: bool = True
    events: list[HistoryEventDTO] = []
    error: dict[str, Any] | None = None


class AbSubmitResultRecordDTO(_SnapshotBase):
    """Lenient copy of the sanitized AB submit result for the Audit section.

    The strict ``AbSubmitResultDTO`` (extra="forbid") whitelists the
    submit-ab *response*; records read back from storage may carry extra
    fields, so the detail panel uses this lenient variant.
    """

    success: bool | None = None
    ab_subscription_id: str | None = None
    ab_response: dict[str, Any] | None = None
    fallback_config: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class AbResultRecordDTO(_SnapshotBase):
    request_id: str | None = None
    recorded_at: str | None = None
    ab_submit_result: AbSubmitResultRecordDTO | None = None


class AbResultSectionDTO(_SnapshotBase):
    available: bool = True
    record: AbResultRecordDTO | None = None
    error: dict[str, Any] | None = None


class _RequestDetailInputDTO(_StrictBase):
    raw_title: str | None = None


class _RequestDetailMatchedBangumiDTO(_StrictBase):
    title: str | None = None
    aliases: list[str] = Field(default_factory=list)
    match_score: float | None = None


class _RequestDetailRssSourceDTO(_StrictBase):
    subtitle_group: str | None = None
    source_type: str | None = None
    total_seed_count: int | None = None
    seed_names: list[str] = Field(default_factory=list)
    valid_seed_count: int | None = None
    invalid_seed_count: int | None = None
    valid_seed_names: list[str] = Field(default_factory=list)
    excluded_seed_names: list[dict[str, str]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class _RequestDetailSourceInfoDTO(_StrictBase):
    matched_bangumi: _RequestDetailMatchedBangumiDTO | None = None
    rss_sources: list[_RequestDetailRssSourceDTO] = Field(default_factory=list)


class _RequestDetailFilterRuleDTO(_StrictBase):
    must_contain: str | None = None
    must_not_contain: str | None = None
    use_regex: bool | None = None
    case_sensitive: bool | None = None


class _RequestDetailConfirmableConfigDTO(_StrictBase):
    selected_subtitle_group: str | None = None
    # The UI only needs to know whether a source was selected; the URL itself
    # is never part of the detail response.
    selected_rss_url: Literal["SELECTED"] | None = None
    filter_rule: _RequestDetailFilterRuleDTO | None = None
    effective_seed_names: list[str] = Field(default_factory=list)
    expected_folder_name: str | None = None
    warnings: list[str] = Field(default_factory=list)


class _RequestDetailUserActionDTO(_StrictBase):
    action: str | None = None
    reason: str | None = None
    decided_at: str | None = None


class _RequestDetailSnapshotDTO(_StrictBase):
    """Strict, sanitized Request projection used only by GET detail."""

    request_id: str | None = None
    status: str | None = None
    input: _RequestDetailInputDTO | None = None
    source_info: _RequestDetailSourceInfoDTO | None = None
    confirmable_config: _RequestDetailConfirmableConfigDTO | None = None
    created_at: str | None = None
    updated_at: str | None = None
    user_action: _RequestDetailUserActionDTO | None = None


class _RequestDetailHistoryEventDTO(_StrictBase):
    request_id: str | None = None
    previous_status: str | None = None
    next_status: str | None = None
    action: str | None = None
    timestamp: str | None = None


class _RequestDetailHistorySectionDTO(_StrictBase):
    available: bool = True
    events: list[_RequestDetailHistoryEventDTO] = Field(default_factory=list)
    error: dict[str, Any] | None = None


class _RequestDetailAbSubmitResultDTO(_StrictBase):
    success: bool | None = None
    # External IDs and upstream response/config bodies are deliberately absent.
    ab_subscription_id: None = None
    fallback_config: None = None
    error: dict[str, Any] | None = None


class _RequestDetailAbRecordDTO(_StrictBase):
    request_id: str | None = None
    recorded_at: str | None = None
    ab_submit_result: _RequestDetailAbSubmitResultDTO | None = None


class _RequestDetailAbResultSectionDTO(_StrictBase):
    available: bool = True
    record: _RequestDetailAbRecordDTO | None = None
    error: dict[str, Any] | None = None


class RequestDetailResultDTO(_StrictBase):
    request: _RequestDetailSnapshotDTO
    history: _RequestDetailHistorySectionDTO
    ab_result: _RequestDetailAbResultSectionDTO


class RequestCreateResultDTO(_StrictBase):
    request: RequestSnapshotDTO
    summary: RequestSummaryDTO
    saved_request: RequestSnapshotDTO | None = None
    draft_id: str | None = None
    draft_revision: int | None = None


class RequestPreviewModifyResultDTO(_StrictBase):
    request: RequestSnapshotDTO
    summary: RequestSummaryDTO
    draft_id: str | None = None
    draft_revision: int | None = None


class RequestPreviewSaveResultDTO(_StrictBase):
    """preview-save result equals the create result shape (draft consumed)."""

    request: RequestSnapshotDTO
    summary: RequestSummaryDTO
    saved_request: RequestSnapshotDTO | None = None


class RequestSaveConfirmHandoffDTO(_StrictBase):
    """Public ``handoff`` of a confirmed save (US-214 + US-222).

    The handoff hands the frontend the durable ACCEPTED Request identity plus
    its unified tracking identity. ``tracking_id`` is always the deterministic
    id derived from the Request id; ``tracking_ready`` is True when a usable
    TrackingRecord exists, False when the tracking write failed (the confirmed
    Request is never rolled back and the record is recovered on the next
    tracking access — ``tracking_status`` stays null so a state is never
    faked). ``safe_message`` carries a fixed recovery copy only in that case.
    ``next_action`` remains the stable B-B hook.
    """

    request_id: str
    status: str
    next_action: str
    tracking_id: str
    tracking_status: str | None
    tracking_ready: bool
    safe_message: str | None


class RequestSaveConfirmResultDTO(_StrictBase):
    """Save-confirm success result (US-214).

    ``outcome`` is always ``CONFIRMED`` here (the SAVED_CONFIRM_FAILED branch
    is returned through the failure envelope's ``error_data``, whose shape is
    frozen by ``test_dto_contracts``). ``request``/``summary`` carry the saved
    ACCEPTED Request; ``handoff`` hands the durable public identity onward.
    """

    outcome: str
    request: RequestSnapshotDTO
    summary: RequestSummaryDTO
    handoff: RequestSaveConfirmHandoffDTO


class SaveConfirmFailedErrorDataDTO(_StrictBase):
    """Failure-envelope ``error_data.details`` whitelist for a saved-but-
    unconfirmed attempt (US-214).

    Mirrors the Stage 28 PRD §6.3 SAVED_CONFIRM_FAILED contract: the saved
    Request exists on disk and only the acceptance/confirmation step failed, so
    the client must retry with the existing Request accept contract. Only the
    public request_id, the outcome marker and the retry action are allowed;
    the consumed draft_id and the draft content never appear.
    """

    outcome: str
    request_id: str
    retry_action: str


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


class SeasonEvidenceDTO(_SnapshotBase):
    """Public candidate season evidence summary (never parser raw text).

    ``status`` is one of PROVEN / NEEDS_CONFIRMATION / CONFLICT / NONE and
    ``season`` the proven-or-awaiting number; the frontend only ever renders
    the confirmation checkbox for NEEDS_CONFIRMATION and blocks CONFLICT.
    """

    status: str | None = None
    season: int | None = None
    requires_review: bool | None = None


class MikanCandidateDTO(_StrictBase):
    """Public whitelist for one MiKan candidate card.

    Only non-sensitive public metadata is exposed: the opaque poster key
    (served by the poster endpoint), the public bangumi id/title, the source
    query and aliases. ``mikan_url`` is declared for contract accuracy (the
    backend uses it to fetch the detail page) but the frontend must never
    render it. ``candidate_context`` is the one-time opaque season-confirmation
    capability (request-scoped); ``season_evidence`` is the public review
    summary. Unknown engine fields (raw HTML/RSS/cookies/tokens) are rejected
    at the boundary.
    """

    bangumi_id: str
    title: str
    mikan_url: str
    poster_url: str | None = None
    source_query: str
    aliases: list[str] = []
    recommendation: str | None = None
    total_episodes: int | None = None
    season_evidence: SeasonEvidenceDTO | None = None
    candidate_context: str | None = None


class MikanCandidateResultDTO(_StrictBase):
    query: str
    status: str
    parse_result: dict[str, Any]
    attempted_queries: list[dict[str, Any]]
    candidates: list[MikanCandidateDTO]
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


class BatchParseItemDTO(_SnapshotBase):
    """One batch card's public parse/search metadata (US-205).

    The parse item carries the auditable title-parse summary, the whitelisted
    candidate list, and the client-side draft state (``preview_request`` +
    ``draft_id``) after a candidate is chosen. Lenient (``extra="allow"``) so
    the engine can keep adding review metadata without breaking the boundary;
    the nested candidates stay strict (``MikanCandidateDTO``) so raw engine
    fields never pass.
    """

    item_id: str | None = None
    raw_title: str | None = None
    status: str | None = None
    queue_status: str | None = None
    canonical_title_candidates: list[str] = []
    season_hint: str | None = None
    search_queries: list[str] = []
    confidence: float | None = None
    needs_user_review: bool | None = None
    source: str | None = None
    parse_result: dict[str, Any] | None = None
    attempted_queries: list[dict[str, Any]] = []
    candidates: list[MikanCandidateDTO] = []
    applied_preferences: dict[str, Any] | None = None
    preference_hits: list[dict[str, Any]] = []
    preference_warnings: list[str] = []
    review_hints: list[str] = []
    enhanced_search_queries: list[dict[str, Any]] = []
    preview_request: RequestSnapshotDTO | None = None
    draft_id: str | None = None
    draft_revision: int | None = None
    error: dict[str, Any] | None = None


class BatchParseResultDTO(_StrictBase):
    batch_id: str
    raw_input: str
    items: list[BatchParseItemDTO]


class BatchQueueItemDTO(_SnapshotBase):
    """One public pre-submission queue item (non-sensitive fields only)."""

    queue_id: str | None = None
    batch_id: str | None = None
    item_id: str | None = None
    request_id: str | None = None
    title: str | None = None
    status: str | None = None
    status_label: str | None = None
    attempts: int | None = None
    last_error: str | None = None
    ab_result_summary: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class BatchQueueDTO(_SnapshotBase):
    """The public pre-submission queue (idempotent, sanitized summaries)."""

    queue_id: str | None = None
    batch_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    items: list[BatchQueueItemDTO] = []


class BatchResultItemDTO(_SnapshotBase):
    """One accept/submit result item (public Chinese reason only).

    Accept items carry ``queued``; submit/retry/recover items carry
    ``attempts``. The lenient shape types the shared fields and lets each
    family's extra field pass without a second DTO.
    """

    item_id: str | None = None
    request_id: str | None = None
    title: str | None = None
    status: str | None = None
    reason: str | None = None
    error_type: str | None = None
    queued: bool | None = None
    attempts: int | None = None


class BatchQueueResultDTO(_StrictBase):
    batch_id: str
    queue: BatchQueueDTO | None = None


class BatchAcceptResultDTO(_StrictBase):
    batch_id: str
    queue: BatchQueueDTO
    items: list[BatchResultItemDTO]
    summary: dict[str, int]


class BatchSubmitResultDTO(BatchAcceptResultDTO):
    """submit/retry/recover results equal the accept result shape."""


class BatchSaveConfirmItemResultDTO(_StrictBase):
    """One batch save-confirm per-item result (US-216).

    Per-item failures are *partial-success* results (``outcome=CONFIRMED`` for
    successful items, a stable sanitized failure otherwise) and never escalate
    the whole request to an HTTP failure. ``request_id``/``status`` are only
    present on the CONFIRMED branch; failed items carry the sanitized
    ``error_type`` + a fixed Chinese ``error_message`` and stay retryable by
    the client (the draft is not consumed on an expected failure).
    ``tracking_id``/``tracking_ready`` are present on the CONFIRMED branch
    (US-222): the item also entered the unified tracking list, and a tracking
    write failure still keeps the item confirmed with ``tracking_ready=False``.
    """

    item_id: str
    outcome: str
    request_id: str | None = None
    status: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    tracking_id: str | None = None
    tracking_ready: bool | None = None


class BatchSaveConfirmResultDTO(_StrictBase):
    """Partial-success batch save-confirm result (US-216).

    ``results`` preserves the input/``item_ids`` order and only carries public
    per-item metadata; ``summary`` counts ``requested`` (processed items),
    ``confirmed`` and ``failed``. The queue is intentionally not part of this
    contract — Stage 28 hands off ACCEPTED Request identities; the tracking
    phase builds the pre-submit view from them.
    """

    batch_id: str
    results: list[BatchSaveConfirmItemResultDTO]
    summary: dict[str, int]


# ---------------------------------------------------------------------------
# Request safe-info (US-217)
# ---------------------------------------------------------------------------
# The ``GET /api/v1/requests/{request_id}/safe-info`` result is the single
# safe data source for the "全部信息" read-only dialog. It is built by an
# explicit default-deny serializer (never by copying the snapshot and hiding
# fields in the frontend), and every nested shape is ``extra="forbid"`` so an
# unknown/engine/URL/credential field is rejected at the boundary. The raw
# snapshot's ``mikan_url``/``rss_url``/``poster_url``/``selected_rss_url`` and
# any endpoint/token/cookie/response-body/absolute-path values never appear.


class RequestSafeInfoCollectionDTO(_StrictBase):
    """Selected MiKan collection public identity (never the full URL)."""

    title: str | None = None
    bangumi_id: str | None = None


class RequestSafeInfoSubtitleGroupDTO(_StrictBase):
    """One subtitle-group resource summary (no RSS URL, seeds or raw feed)."""

    subtitle_group: str | None = None
    total_resource_count: int = 0
    valid_resource_count: int = 0
    invalid_resource_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class RequestSafeInfoFilterRuleDTO(_StrictBase):
    """User-readable filter rule summary (safe, user-controlled text)."""

    must_contain: str = ""
    must_not_contain: str = ""
    use_regex: bool = False
    case_sensitive: bool = False


class RequestSafeInfoExcludedFileDTO(_StrictBase):
    """One excluded torrent-file name plus its readable filter reason."""

    name: str = ""
    reason: str = ""


class RequestSafeInfoResourcesDTO(_StrictBase):
    """Resource counts and sanitized file-name summaries.

    Only torrent *names* (file titles) are exposed — never magnet links,
    download URLs or raw RSS. ``valid`` is the currently selected subtitle
    group's effective seeds; ``excluded`` its excluded seeds; ``complete`` is
    the combined unique seeds across every candidate group.
    """

    selected_subtitle_group: str | None = None
    valid_resource_count: int = 0
    invalid_resource_count: int = 0
    complete_resource_count: int = 0
    valid_file_names: list[str] = Field(default_factory=list)
    excluded_file_names: list[RequestSafeInfoExcludedFileDTO] = Field(
        default_factory=list
    )


class RequestSafeInfoHistoryEventDTO(_StrictBase):
    """One sanitized status-history event (details/diagnostics dropped)."""

    action: str | None = None
    previous_status: str | None = None
    next_status: str | None = None
    timestamp: str | None = None


class RequestSafeInfoAbStatusDTO(_StrictBase):
    """Safe Auto Bangumi submission summary (no endpoint/raw response).

    ``submitted`` reports whether a submission result exists; ``success`` and
    ``ab_subscription_id`` are the public outcome; ``error_type`` is a stable
    classified failure marker when the submission did not succeed.
    """

    submitted: bool = False
    success: bool | None = None
    ab_subscription_id: str | None = None
    error_type: str | None = None


class RequestSafeInfoDTO(_StrictBase):
    """The strict safe-info whitelist for one saved Request (US-217).

    ``extra="forbid"``: unknown nested fields, endpoints, URLs, credentials,
    raw responses and absolute paths are rejected instead of passing through.
    ``updated_episode`` is always ``None`` and ``updated_episode_status`` is
    always ``NOT_IMPLEMENTED`` — Stage 28 never guesses current-episode
    progress from seeds/RSS/download state (BL-020 is out of scope).
    """

    request_id: str
    status: str
    raw_title: str | None = None
    title: str | None = None
    aliases: list[str] = Field(default_factory=list)
    season: int | None = None
    season_raw: str | None = None
    season_evidence: str | None = None
    mikan_collection: RequestSafeInfoCollectionDTO | None = None
    subtitle_groups: list[RequestSafeInfoSubtitleGroupDTO] = Field(
        default_factory=list
    )
    selected_subtitle_group: str | None = None
    filter_rule: RequestSafeInfoFilterRuleDTO = Field(
        default_factory=RequestSafeInfoFilterRuleDTO
    )
    resources: RequestSafeInfoResourcesDTO = Field(
        default_factory=RequestSafeInfoResourcesDTO
    )
    folder_name: str | None = None
    storage_profile: str | None = None
    total_episodes: int | None = None
    updated_episode: None = None
    updated_episode_status: Literal["NOT_IMPLEMENTED"] = "NOT_IMPLEMENTED"
    history_summary: list[RequestSafeInfoHistoryEventDTO] = Field(
        default_factory=list
    )
    ab_status: RequestSafeInfoAbStatusDTO | None = None


class RequestSafeInfoResultDTO(_StrictBase):
    """Envelope for the safe-info endpoint: only the whitelist object.

    The endpoint result is ``{"safe_info": {...}}`` — no raw request snapshot,
    history section or AB section is ever attached.
    """

    safe_info: RequestSafeInfoDTO


# ---------------------------------------------------------------------------
# Tracking items family (US-223)
# ---------------------------------------------------------------------------
# The unified tracking list/detail read contract.  Every shape is
# ``extra="forbid"`` (unknown/engine/URL/credential fields fail at the
# boundary).  The list item only exposes the non-sensitive record summary plus
# the server-computed ``available_actions``; the detail additionally reuses the
# Request safe-info whitelist and returns the current operation's safe summary,
# revalidation issues, external mapping summary and the most recent audit
# events — never the full Request, upstream raw JSON, URLs, credentials,
# magnets or absolute paths.


class TrackingAvailableActionDTO(_StrictBase):
    """One server-computed action (Stage 29 PRD §11.4).

    ``style`` is one of ``PRIMARY | SECONDARY | DANGER``; ``code`` one of the
    fixed §11.4 candidates.  Only currently-executable actions are returned —
    never a disabled fake action.
    """

    code: Literal[
        "REVALIDATE", "SUBMIT", "RETRY", "RECOVER_AUTO", "MARK_SUCCEEDED",
        "MARK_FAILED", "MODIFY", "SET_ENABLED", "REFRESH_RSS", "DELETE_EXTERNAL",
    ]
    label: str
    style: Literal["PRIMARY", "SECONDARY", "DANGER"]
    requires_confirmation: bool
    target_scopes: list[Literal["SUBSCRIPTION", "ASSOCIATED_RSS"]] = Field(default_factory=list)


class TrackingAuditEventDTO(_StrictBase):
    """One safe embedded audit event (Stage 29 PRD §9)."""

    event_id: str
    action: Literal[
        "TRACKING_CREATED", "TRACKING_BACKFILLED", "PLAN_CHANGE_DETECTED",
        "REVALIDATION_PASSED", "REVALIDATION_FAILED", "SUBMIT_STARTED",
        "SUBMIT_SUCCEEDED", "SUBMIT_FAILED", "SUBMIT_OUTCOME_UNKNOWN",
        "MANAGEMENT_STARTED", "MANAGEMENT_SUCCEEDED", "MANAGEMENT_FAILED",
        "MANAGEMENT_UNKNOWN", "RESULT_PERSIST_FAILED", "RECOVERY_AUTO_SUCCEEDED",
        "RECOVERY_AUTO_FAILED", "RECOVERY_NEEDS_MANUAL",
        "RECOVERY_MANUAL_SUCCEEDED", "RECOVERY_MANUAL_FAILED",
        "RECOVERY_EXTERNAL_VERIFIED", "COMPAT_QUEUE_UPDATED",
        "COMPAT_QUEUE_UPDATE_FAILED",
    ]
    actor: str
    from_status: Literal[
        "PENDING_SUBMIT", "REVALIDATING", "NEEDS_RECONFIRM", "SUBMITTING",
        "VERIFYING_EXTERNAL", "ACTIVE", "SUBMIT_FAILED", "RECOVERY_REQUIRED",
        "UNKNOWN", "DISABLED", "EXTERNAL_DELETED", "EXTERNAL_ONLY",
    ] | None = None
    to_status: Literal[
        "PENDING_SUBMIT", "REVALIDATING", "NEEDS_RECONFIRM", "SUBMITTING",
        "VERIFYING_EXTERNAL", "ACTIVE", "SUBMIT_FAILED", "RECOVERY_REQUIRED",
        "UNKNOWN", "DISABLED", "EXTERNAL_DELETED", "EXTERNAL_ONLY",
    ] | None = None
    tracking_revision: int
    operation_id: str | None = None
    reason_code: str | None = None
    safe_message: str | None = None
    created_at: str


class TrackingRevalidationIssueDTO(_StrictBase):
    """One structured revalidation issue (Stage 29 PRD §11.5 fixed codes).

    ``recovery_action`` is a safe code (e.g. ``SUBMIT``) the UI can offer.
    """

    code: Literal[
        "REQUEST_MISSING", "REQUEST_NOT_ACCEPTED", "REQUEST_CHANGED",
        "TITLE_MISSING", "SEASON_REVIEW_REQUIRED", "MIKAN_SELECTION_MISSING",
        "SUBTITLE_GROUP_MISSING", "NO_VALID_RESOURCES",
        "EXTERNAL_ALREADY_LINKED", "OPERATION_IN_PROGRESS",
        "TRACKING_STATE_INVALID",
    ]
    field: str | None = None
    message: str
    recovery_action: Literal["", "SUBMIT"]


class TrackingOperationSummaryDTO(_StrictBase):
    """Safe summary of the current TrackingOperation (US-223 detail).

    Only the non-sensitive operation identity/state/outcome markers are
    exposed — never the idempotency binding, fingerprint, request body, AB
    config, upstream response or credentials.
    """

    operation_id: str
    operation: Literal["SUBMIT", "MODIFY", "SET_ENABLED", "DELETE_EXTERNAL", "REFRESH_RSS"]
    state: Literal[
        "PREPARED", "IN_PROGRESS", "SUCCEEDED", "FAILED",
        "OUTCOME_UNKNOWN", "RECOVERY_REQUIRED",
    ]
    attempt: int
    external_result_id: str | None = None
    error_type: str | None = None
    created_at: str
    updated_at: str
    completed_at: str | None = None


class TrackingExternalSummaryDTO(_StrictBase):
    """Safe external state summary; opaque external identifiers stay server-side."""

    match_reason: str | None = None
    external_deleted: bool = False
    enabled: bool = False
    missing_sync_count: int = 0
    last_verified_at: str | None = None


class TrackingItemDTO(_StrictBase):
    """One unified tracking list item (Stage 29 PRD §11.2).

    ``updated_episode`` is always null and ``updated_episode_status`` is always
    NOT_IMPLEMENTED (BL-020 out of scope — never guessed from seeds/RSS).
    ``poster_path`` may only be a same-origin opaque poster proxy route.
    """

    tracking_id: str
    request_id: str | None = None
    title: str | None = None
    season: int | None = None
    subtitle_group: str | None = None
    poster_path: str | None = None
    status: Literal[
        "PENDING_SUBMIT", "REVALIDATING", "NEEDS_RECONFIRM", "SUBMITTING",
        "VERIFYING_EXTERNAL", "ACTIVE", "SUBMIT_FAILED", "RECOVERY_REQUIRED",
        "UNKNOWN", "DISABLED", "EXTERNAL_DELETED", "EXTERNAL_ONLY",
    ]
    status_label: str
    status_group: Literal["PENDING", "PROCESSING", "ACTIVE", "ATTENTION", "INACTIVE"]
    available_actions: list[TrackingAvailableActionDTO] = Field(default_factory=list)
    valid_resource_count: int = 0
    updated_episode: None = None
    updated_episode_status: Literal["NOT_IMPLEMENTED"] = "NOT_IMPLEMENTED"
    total_episodes: int | None = None
    revision: int
    updated_at: str | None = None


class TrackingItemListSummaryDTO(_StrictBase):
    """Safe summary counts for the tracking list (§11.2)."""

    total: int
    pending: int
    processing: int
    active: int
    needs_attention: int
    unreadable: int


class TrackingItemListResultDTO(_StrictBase):
    """Result of ``GET /api/v1/tracking/items``."""

    items: list[TrackingItemDTO]
    summary: TrackingItemListSummaryDTO
    warnings: list[str] = Field(default_factory=list)


class TrackingDetailResultDTO(_StrictBase):
    """Result of ``GET /api/v1/tracking/items/{tracking_id}`` (§11.3).

    Reuses the strict Request ``safe_info`` whitelist and additionally returns
    only the current operation's safe summary, revalidation issues, external
    mapping summary and the most recent 20 audit events.  ``safe_info`` is null
    only when the backing Request cannot be read (damaged/deleted); a fixed
    warning is added instead of failing the whole detail.
    """

    tracking_id: str
    request_id: str | None = None
    title: str | None = None
    season: int | None = None
    subtitle_group: str | None = None
    poster_path: str | None = None
    status: Literal[
        "PENDING_SUBMIT", "REVALIDATING", "NEEDS_RECONFIRM", "SUBMITTING",
        "VERIFYING_EXTERNAL", "ACTIVE", "SUBMIT_FAILED", "RECOVERY_REQUIRED",
        "UNKNOWN", "DISABLED", "EXTERNAL_DELETED", "EXTERNAL_ONLY",
    ]
    status_label: str
    status_group: Literal["PENDING", "PROCESSING", "ACTIVE", "ATTENTION", "INACTIVE"]
    available_actions: list[TrackingAvailableActionDTO] = Field(default_factory=list)
    valid_resource_count: int = 0
    updated_episode: None = None
    updated_episode_status: Literal["NOT_IMPLEMENTED"] = "NOT_IMPLEMENTED"
    total_episodes: int | None = None
    revision: int
    origin: str
    batch_id: str | None = None
    created_at: str
    updated_at: str | None = None
    last_synced_at: str | None = None
    safe_info: RequestSafeInfoDTO | None = None
    current_operation: TrackingOperationSummaryDTO | None = None
    revalidation_issues: list[TrackingRevalidationIssueDTO] = Field(
        default_factory=list
    )
    external_mapping: TrackingExternalSummaryDTO | None = None
    audit_events: list[TrackingAuditEventDTO] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TrackingRevalidateResultDTO(_StrictBase):
    """Result of ``POST /api/v1/tracking/items/{tracking_id}/revalidate`` (§11.5).

    A business revalidation failure is still HTTP 200: ``ready=false``,
    ``next_status=NEEDS_RECONFIRM`` and the fixed §11.5 issue codes.  A passing
    check returns ``ready=true`` with ``next_status=PENDING_SUBMIT`` (or keeps
    ``SUBMIT_FAILED`` when the record is a failed submission whose plan is still
    valid).  ``checked_revision`` is the revision the client expected;
    ``next_revision`` is the record's revision after the outcome persisted (they
    differ only when the outcome changed the record's status).  ``tracking`` is
    the safe summary of the persisted record so the client can update the list
    item without a second read; ``issues`` reuse the fixed §11.5 shape and never
    leak file names/paths/raw content.
    """

    tracking_id: str
    ready: bool
    checked_revision: int
    next_revision: int
    checked_at: str
    next_status: Literal[
        "PENDING_SUBMIT", "REVALIDATING", "NEEDS_RECONFIRM", "SUBMITTING",
        "VERIFYING_EXTERNAL", "ACTIVE", "SUBMIT_FAILED", "RECOVERY_REQUIRED",
        "UNKNOWN", "DISABLED", "EXTERNAL_DELETED", "EXTERNAL_ONLY",
    ]
    issues: list[TrackingRevalidationIssueDTO] = Field(default_factory=list)
    tracking: TrackingItemDTO


class TrackingSubmitResultDTO(_StrictBase):
    """Result of ``POST /api/v1/tracking/items/{tracking_id}/submit`` (US-225).

    A persisted business result is HTTP 200: ``outcome`` is the record's final
    status (``ACTIVE``/``SUBMIT_FAILED``/``VERIFYING_EXTERNAL``/
    ``RECOVERY_REQUIRED``/``NEEDS_RECONFIRM``).  ``checked_revision`` is the
    revision the client confirmed; ``next_revision`` is the record's revision
    after the outcome persisted.  ``operation_id`` is set when a submit
    operation was created/reused; ``issues`` carry the fixed §11.5 codes when
    the submit was blocked before any external call.  ``tracking`` is the safe
    summary of the persisted record so the client can update the list item
    without a second read.
    """

    tracking_id: str
    outcome: Literal[
        "ACTIVE", "SUBMIT_FAILED", "VERIFYING_EXTERNAL",
        "RECOVERY_REQUIRED", "NEEDS_RECONFIRM",
    ]
    checked_revision: int
    next_revision: int
    checked_at: str
    operation_id: str | None = None
    issues: list[TrackingRevalidationIssueDTO] = Field(default_factory=list)
    tracking: TrackingItemDTO


class TrackingRecoverResultDTO(_StrictBase):
    """Result of ``POST /api/v1/tracking/items/{tracking_id}/recover`` (US-226).

    A persisted recovery result is HTTP 200: ``action`` echoes the requested
    action (``AUTO``/``MARK_SUCCEEDED``/``MARK_FAILED``) and ``outcome`` is the
    record's final status (``ACTIVE``/``SUBMIT_FAILED``/``RECOVERY_REQUIRED``).
    ``checked_revision`` is the revision the client acted on; ``next_revision``
    is the record's revision after the outcome persisted (unchanged when an
    ``AUTO`` recovery finds no new evidence on an already-``RECOVERY_REQUIRED``
    record).  ``operation_id`` is set when the record references a submit
    operation.  ``needs_manual`` is True when an ``AUTO`` recovery could not
    resolve the outcome from local evidence and only a manual action can
    progress.  ``tracking`` is the safe summary of the persisted record so the
    client can update the list item without a second read.
    """

    tracking_id: str
    action: Literal["AUTO", "MARK_SUCCEEDED", "MARK_FAILED", "VERIFY_EXTERNAL"]
    outcome: Literal["ACTIVE", "SUBMIT_FAILED", "RECOVERY_REQUIRED"]
    checked_revision: int
    next_revision: int
    checked_at: str
    operation_id: str | None = None
    needs_manual: bool = False
    tracking: TrackingItemDTO


class TrackingManagementResultDTO(_StrictBase):
    """Safe result shared by the four Stage 31 management write routes."""

    action: Literal["MODIFY", "SET_ENABLED", "DELETE_EXTERNAL", "REFRESH_RSS"]
    management_status: Literal[
        "PREPARED", "IN_PROGRESS", "SUCCEEDED", "FAILED",
        "OUTCOME_UNKNOWN", "RECOVERY_REQUIRED",
    ]
    needs_manual: bool
    safe_message: str
    operation_id: str | None = None
    tracking: TrackingItemDTO
    operation: TrackingOperationSummaryDTO | None = None


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


class AutoBangumiCapabilitiesDTO(_StrictBase):
    probe_status: Literal["VERIFIED", "PARTIAL", "FAILED"]
    version: str | None
    adapter: Literal["legacy_3_1", "api_token"] | None
    subscription_list: Literal["SUPPORTED", "UNSUPPORTED", "UNKNOWN"]
    subscription_detail: Literal["SUPPORTED", "UNSUPPORTED", "UNKNOWN"]
    subscription_submit: Literal["SUPPORTED", "UNSUPPORTED", "UNKNOWN"]
    subscription_modify: Literal["SUPPORTED", "UNSUPPORTED", "UNKNOWN"]
    subscription_enable: Literal["SUPPORTED", "UNSUPPORTED", "UNKNOWN"]
    subscription_disable: Literal["SUPPORTED", "UNSUPPORTED", "UNKNOWN"]
    subscription_delete: Literal["SUPPORTED", "UNSUPPORTED", "UNKNOWN"]
    rss_list: Literal["SUPPORTED", "UNSUPPORTED", "UNKNOWN"]
    rss_modify: Literal["SUPPORTED", "UNSUPPORTED", "UNKNOWN"]
    rss_enable: Literal["SUPPORTED", "UNSUPPORTED", "UNKNOWN"]
    rss_disable: Literal["SUPPORTED", "UNSUPPORTED", "UNKNOWN"]
    rss_delete: Literal["SUPPORTED", "UNSUPPORTED", "UNKNOWN"]
    rss_refresh: Literal["SUPPORTED", "UNSUPPORTED", "UNKNOWN"]
    external_verify: Literal["SUPPORTED", "UNSUPPORTED", "UNKNOWN"]
    checked_at: str | None
    safe_message: str | None


class TrackingSyncSummaryDTO(_StrictBase):
    checked: int
    created: int
    updated: int
    unchanged: int
    external_only: int
    failed: int
    unreadable: int


class TrackingSyncResultDTO(_StrictBase):
    sync_status: Literal["COMPLETE", "PARTIAL", "FAILED"]
    checked_at: str
    capabilities: AutoBangumiCapabilitiesDTO
    summary: TrackingSyncSummaryDTO
    warnings: list[str] = Field(default_factory=list)
    items: list[TrackingItemDTO] = Field(default_factory=list)


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
