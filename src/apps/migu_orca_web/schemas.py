from __future__ import annotations

"""Request/query/payload Pydantic schemas for the Web API (US-191 split).

These were previously defined in ``views.py``. Keeping them in their own module
gives the route modules a single place for request validation while the public
response DTOs stay in ``api_contract.py`` (which is the Stage 27 contract).
"""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class RequestListQuery(BaseModel):
    storage_dir: str | None = None


class RequestDetailQuery(BaseModel):
    request_id: str
    storage_dir: str | None = None


class RequestMikanConfigPayload(BaseModel):
    search_endpoint: str
    timeout_seconds: float = Field(gt=0)

    @field_validator("search_endpoint")
    @classmethod
    def validate_search_endpoint(cls, value: str) -> str:
        endpoint = value.strip()
        if not endpoint:
            raise ValueError("search_endpoint cannot be empty")
        return endpoint


class MikanCandidateSearchPayload(BaseModel):
    query: str
    mikan_config: RequestMikanConfigPayload | None = Field(
        default=None,
        validate_default=True,
    )

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        query = value.strip()
        if not query:
            raise ValueError("query cannot be empty")
        return query


class BatchParsePayload(BaseModel):
    raw_input: str
    mikan_config: RequestMikanConfigPayload | None = Field(
        default=None,
        validate_default=True,
    )
    storage_dir: str | None = None


class BatchItemDescriptorPayload(BaseModel):
    """One batch card descriptor for the accept endpoint.

    ``request_id`` is present only when the card already has a saved Request
    (unsaved preview drafts are persisted through preview-save before accept).
    """

    item_id: str
    request_id: str | None = None
    title: str | None = None

    @field_validator("item_id")
    @classmethod
    def validate_item_id(cls, value: str) -> str:
        item_id = value.strip()
        if not item_id:
            raise ValueError("item_id cannot be empty")
        return item_id

    @field_validator("request_id")
    @classmethod
    def validate_request_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        request_id = value.strip()
        if not request_id:
            raise ValueError("request_id cannot be empty")
        return request_id


class BatchAcceptPayload(BaseModel):
    """Accept selected or all batch cards into the pre-submission queue.

    ``batch_id`` comes from the URL path; ``items`` describes the batch cards
    (the server never persists the parsed batch, so the client sends the cards
    it currently holds). ``item_ids`` optionally filters which cards are
    accepted (omit for accept-all, preserving batch order).
    """

    batch_id: str
    items: list[BatchItemDescriptorPayload]
    item_ids: list[str] | None = None
    storage_dir: str | None = None


class BatchQueueQuery(BaseModel):
    """Read a batch pre-submission queue (URL path + query args only)."""

    batch_id: str
    storage_dir: str | None = None


class BatchSubmitPayload(BaseModel):
    """Submit a batch queue to Auto Bangumi with explicit request-scoped config.

    ``ab_config`` is optional in the payload so the view can raise a Chinese
    ``validation_error`` envelope when it is missing (instead of the default
    English pydantic envelope); ``confirm`` is the explicit user confirmation
    field. Neither value is ever persisted into the queue storage.
    """

    batch_id: str
    ab_config: RequestAbConfigPayload | None = Field(default=None)
    confirm: bool = False
    storage_dir: str | None = None


class BatchRetryPayload(BatchSubmitPayload):
    """Retry a single FAILED/RETRYABLE queue item with explicit AB config.

    ``request_id`` selects the queue item to retry; only FAILED/RETRYABLE items
    are retried (already-SUCCEEDED items are skipped server-side). The request-
    scoped ``ab_config``/``confirm`` contract matches ``BatchSubmitPayload`` and
    is never persisted into the queue storage.
    """

    request_id: str


class BatchRecoverPayload(BaseModel):
    """Recover a stuck queue item (SUBMITTING / RESULT_PERSIST_FAILED).

    ``action`` selects the recovery mode: ``auto`` (only for SUBMITTING, uses a
    previously persisted AB result to finalize SUCCEEDED), ``succeeded``
    (manual confirmation that Auto Bangumi created the subscription), or
    ``failed`` (manual confirmation that it did not, turning the item into a
    normal retryable FAILED). Manual actions require ``confirm=True`` so a
    wrong click cannot silently mark a subscription as created.
    """

    batch_id: str
    request_id: str
    action: str
    confirm: bool = False
    storage_dir: str | None = None


class PreferenceQuery(BaseModel):
    """Read the saved non-sensitive user preferences (query args only)."""

    storage_dir: str | None = None


class PreferenceSavePayload(BaseModel):
    """Save the non-sensitive user preferences.

    ``preferences`` is typed loosely (``Any``) so the view can convert the raw
    payload through ``build_preferences_from_api`` and raise a Chinese
    ``validation_error`` envelope for every shape/type/enum/sensitive-value
    problem — pydantic's default English ``data_validation_errors`` envelope
    cannot express the business messages, mirroring the batch submit/retry
    validation pattern.
    """

    storage_dir: str | None = None
    preferences: Any = None


class CorrectionQuery(BaseModel):
    """Read the saved non-sensitive title corrections (query args only)."""

    storage_dir: str | None = None


class CorrectionSavePayload(BaseModel):
    """Save one explicit title correction.

    ``correction`` is typed loosely (``Any``) so the view can convert the raw
    payload through ``build_correction_from_api`` and raise a Chinese
    ``validation_error`` envelope for every shape/type/sensitive-value problem —
    the same loose-typing convention as ``PreferenceSavePayload``.
    """

    storage_dir: str | None = None
    correction: Any = None


class RequestCreatePayload(BaseModel):
    title: str
    source: str = "static-fixture"
    mikan_config: RequestMikanConfigPayload | None = Field(
        default=None,
        validate_default=True,
    )
    mikan_bangumi: str | None = None
    storage_dir: str | None = None
    save_request: bool = False
    season_confirmation: int | None = None
    candidate_context: str | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("title cannot be empty")
        return title

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        source = value.strip()
        if source not in {"static-fixture", "mikan"}:
            raise ValueError("source must be static-fixture or mikan")
        return source

    @field_validator("mikan_bangumi")
    @classmethod
    def validate_mikan_bangumi(cls, value: str | None) -> str | None:
        if value is None:
            return None
        bangumi = value.strip()
        if not bangumi:
            raise ValueError("mikan_bangumi cannot be empty")
        return bangumi

    @field_validator("season_confirmation")
    @classmethod
    def validate_season_confirmation(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not 1 <= value <= 99:
            raise ValueError("season_confirmation must be between 1 and 99")
        return value

    @field_validator("candidate_context")
    @classmethod
    def validate_candidate_context(cls, value: str | None) -> str | None:
        if value is None:
            return None
        token = value.strip()
        if not token or len(token) > 128 or not token.replace("-", "").replace("_", "").isalnum():
            raise ValueError("candidate_context is invalid")
        return token


class RequestActionPayload(BaseModel):
    """Base payload for confirm/cancel/modify operations. `request_id` comes from URL path."""

    request_id: str
    storage_dir: str | None = None


class RequestCancelPayload(RequestActionPayload):
    cancel_reason: str | None = None


class RequestModifyPayload(RequestActionPayload):
    patch: dict[str, Any]


class RequestPreviewModifyPayload(BaseModel):
    """Recompute an unsaved preview request in memory (no persistence).

    US-194: the server is authoritative for unsaved drafts. The client sends
    only the opaque ``draft_id`` it received from generation (or a previous
    modify) plus an allowed patch; it never sends the full Request snapshot.
    """

    draft_id: str
    patch: dict[str, Any]
    storage_dir: str | None = None


class RequestPreviewSavePayload(BaseModel):
    """Persist an unsaved, already-modified preview draft.

    US-194: ``draft_id`` is a one-time capability. The server consumes it
    atomically, so saving the same draft twice is a replay (409).
    """

    draft_id: str
    storage_dir: str | None = None


class RequestAbConfigPayload(BaseModel):
    auth_mode: Literal["password", "api_token"] = "password"
    base_url: str | None = None
    username: str | None = None
    password: str | None = None
    token: str | None = None
    fallback_enabled: bool


class RequestAbSubmitPayload(RequestActionPayload):
    ab_config: RequestAbConfigPayload


class AutoBangumiTestConnectionPayload(BaseModel):
    """Explicit request-scoped credentials for a read-only AB probe."""

    ab_config: RequestAbConfigPayload


class QbittorrentConfigPayload(BaseModel):
    endpoint: str
    username: str
    password: str
    timeout_seconds: float = Field(gt=0)
    verify_tls: bool = True

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        endpoint = value.strip()
        if not endpoint:
            raise ValueError("endpoint cannot be empty")
        return endpoint

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        username = value.strip()
        if not username:
            raise ValueError("username cannot be empty")
        return username

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        password = value.strip()
        if not password:
            raise ValueError("password cannot be empty")
        return password


class QbittorrentTestConnectionPayload(BaseModel):
    qbittorrent_config: QbittorrentConfigPayload
