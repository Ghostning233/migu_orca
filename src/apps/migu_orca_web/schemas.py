from __future__ import annotations

"""Request/query/payload Pydantic schemas for the Web API (US-191 split).

These were previously defined in ``views.py``. Keeping them in their own module
gives the route modules a single place for request validation while the public
response DTOs stay in ``api_contract.py`` (which is the Stage 27 contract).
"""

import re
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from tracking_engine.models.tracking import (
    TRACKING_STATUS_GROUP_ACTIVE,
    TRACKING_STATUS_GROUP_ATTENTION,
    TRACKING_STATUS_GROUP_INACTIVE,
    TRACKING_STATUS_GROUP_PENDING,
    TRACKING_STATUS_GROUP_PROCESSING,
)


class RequestListQuery(BaseModel):
    storage_dir: str | None = None


class RequestDetailQuery(BaseModel):
    request_id: str
    storage_dir: str | None = None


class MikanCandidateSearchPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        query = value.strip()
        if not query:
            raise ValueError("query cannot be empty")
        return query


class BatchParsePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    raw_input: str
    storage_dir: str | None = None


class BatchItemDescriptorPayload(BaseModel):
    """One batch card descriptor for the accept endpoint.

    ``request_id`` is present only when the card already has a saved Request
    (legacy descriptor retained only for local parsing compatibility).
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
    model_config = ConfigDict(extra="forbid")
    title: str
    mikan_bangumi: str | None = None
    storage_dir: str | None = None
    season_confirmation: int | None = None
    candidate_context: str | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("title cannot be empty")
        return title

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
    US-211: ``base_revision`` is the revision the client last observed; the
    server replaces the draft only when it still matches (compare-and-swap), so
    a stale out-of-order modify cannot overwrite a newer result.
    """

    draft_id: str
    base_revision: int = Field(ge=1)
    patch: dict[str, Any]
    storage_dir: str | None = None


class _SaveConfirmStrictBase(BaseModel):
    """Strict base for the Stage 28 save-confirm request models (US-213 fix).

    ``extra="forbid"`` makes an unknown field (a leaked ``request``/``draft``/
    ``token`` key, or any future accidental addition) fail validation with the
    existing 400 ``data_validation_errors`` envelope instead of being silently
    ignored. Only the save-confirm family is tightened here — historical
    request models keep their existing lenient behavior.
    """

    model_config = ConfigDict(extra="forbid")


class RequestSaveConfirmPayload(_SaveConfirmStrictBase):
    """Save + confirm one preview draft in a single durable operation.

    US-213/US-214: the request only carries the server-issued ``draft_id``,
    the ``base_revision`` the client last observed, and an opaque
    ``idempotency_key`` that makes retries converge to one public outcome —
    the full Request never crosses the boundary. ``idempotency_key`` is a
    request-scoped opaque value validated as a safe filename token (never a
    path segment), mirroring the ``candidate_context`` capability contract.
    ``extra="forbid"`` rejects unknown/sensitive keys instead of ignoring them.
    """

    draft_id: str
    base_revision: int = Field(ge=1)
    idempotency_key: str
    storage_dir: str | None = None

    @field_validator("idempotency_key")
    @classmethod
    def validate_idempotency_key(cls, value: str) -> str:
        token = value.strip()
        if (
            not token
            or len(token) > 128
            or not token.replace("-", "").replace("_", "").isalnum()
        ):
            raise ValueError("idempotency_key 必须是不含路径的安全 opaque 值")
        return token


class BatchItemSaveConfirmPayload(_SaveConfirmStrictBase):
    """One batch card save-confirm descriptor (US-216).

    Each item only carries the public ``item_id`` plus the server-issued
    ``draft_id``, the ``base_revision`` the client last observed, and an opaque
    ``idempotency_key``. The full Request never crosses the boundary; the
    per-item key follows the single save-confirm capability contract (a safe
    opaque value, never a path segment). ``extra="forbid"`` rejects a leaked
    full Request or unknown field inside an item.
    """

    item_id: str
    draft_id: str
    base_revision: int = Field(ge=1)
    idempotency_key: str

    @field_validator("item_id")
    @classmethod
    def validate_item_id(cls, value: str) -> str:
        item_id = value.strip()
        if not item_id:
            raise ValueError("item_id cannot be empty")
        return item_id

    @field_validator("idempotency_key")
    @classmethod
    def validate_idempotency_key(cls, value: str) -> str:
        token = value.strip()
        if (
            not token
            or len(token) > 128
            or not token.replace("-", "").replace("_", "").isalnum()
        ):
            raise ValueError("idempotency_key 必须是不含路径的安全 opaque 值")
        return token


class BatchSaveConfirmPayload(_SaveConfirmStrictBase):
    """Save + confirm selected batch draft cards in one partial-success call.

    US-216: every selected item runs the same single save-confirm use case
    (revision check, reservation, persistence, confirmation and idempotent
    outcome). ``item_ids`` optionally filters which ``items`` are processed;
    when omitted every item is processed in input order. A per-item expected
    failure never rolls back successful siblings — it is reported as a
    sanitized per-item result. ``batch_id`` comes from the URL path.
    ``extra="forbid"`` rejects unknown top-level keys.
    """

    batch_id: str
    items: list[BatchItemSaveConfirmPayload]
    item_ids: list[str] | None = None
    storage_dir: str | None = None


class RequestAbConfigPayload(BaseModel):
    auth_mode: Literal["password", "api_token"] = "password"
    base_url: str | None = None
    username: str | None = None
    password: str | None = None
    token: str | None = None
    fallback_enabled: bool


class AutoBangumiConfigPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    auth_mode: Literal["password", "api_token"] = Field(repr=False)
    base_url: str = Field(repr=False)
    username: str | None = Field(default=None, repr=False)
    password: str | None = Field(default=None, repr=False)
    token: str | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def validate_auth_union(self) -> AutoBangumiConfigPayload:
        if self.base_url is None:
            raise ValueError("base_url is required")
        if self.auth_mode == "password":
            if self.username is None or self.password is None or self.token is not None:
                raise ValueError("password credentials required")
        elif self.token is None or self.username is not None or self.password is not None:
            raise ValueError("token credential required")
        return self


class AutoBangumiConnectionTestPayload(BaseModel):
    """One-shot connection test; never persisted."""

    model_config = ConfigDict(extra="forbid")
    config: AutoBangumiConfigPayload


class AutoBangumiConfigSavePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: StrictBool
    expected_configuration_revision: StrictInt = Field(ge=0)
    config: AutoBangumiConfigPayload

    @model_validator(mode="after")
    def require_literal_true(self) -> AutoBangumiConfigSavePayload:
        if self.confirm is not True:
            raise ValueError("confirm must be true")
        return self


class AutoBangumiConfigDeletePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: StrictBool
    expected_configuration_revision: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def require_literal_true(self) -> AutoBangumiConfigDeletePayload:
        if self.confirm is not True:
            raise ValueError("confirm must be true")
        return self


class SavedAutoBangumiProbePayload(BaseModel):
    """Reference one immutable, server-owned saved configuration generation."""

    model_config = ConfigDict(extra="forbid")
    connection_ref: UUID
    configuration_revision: StrictInt = Field(ge=0)

    @field_validator("connection_ref", mode="before")
    @classmethod
    def require_canonical_connection_ref(cls, value: Any) -> Any:
        if not isinstance(value, str):
            raise ValueError("connection_ref 必须是规范 UUID")
        try:
            parsed = UUID(value)
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError("connection_ref 必须是规范 UUID") from exc
        if str(parsed) != value:
            raise ValueError("connection_ref 必须是规范 UUID")
        return value


def _clean_tracking_id_value(value: str) -> str:
    tracking_id = value.strip()
    if not tracking_id:
        raise ValueError("tracking_id cannot be empty")
    return tracking_id


def _clean_idempotency_key_value(value: str) -> str:
    key = value.strip()
    if not _IDEMPOTENCY_KEY_RE.fullmatch(key):
        raise ValueError("idempotency_key 包含不合法字符")
    return key


class SavedTrackingSubmitInput(BaseModel):
    """Strict server-side handoff for submit/retry using saved AB config.

    This model is intentionally not an HTTP replacement for
    :class:`TrackingSubmitPayload` yet.  US-328 switches the public request
    shape; until then the new service seam consumes only the opaque saved
    connection generation and the existing tracking submit fields.
    """

    model_config = ConfigDict(extra="forbid")

    tracking_id: StrictStr
    expected_revision: StrictInt = Field(ge=1)
    idempotency_key: StrictStr
    confirm: StrictBool
    connection_ref: UUID
    configuration_revision: StrictInt = Field(ge=0)
    #: Issue #98: one operation-level submission mode; never a plan field.
    submission_mode: Literal["CONTINUE_TRACKING", "DOWNLOAD_EXISTING"] = "CONTINUE_TRACKING"
    storage_dir: str | None = None

    @field_validator("tracking_id")
    @classmethod
    def _clean_tracking_id(cls, value: str) -> str:
        return _clean_tracking_id_value(value)

    @field_validator("idempotency_key")
    @classmethod
    def _clean_saved_submit_key(cls, value: str) -> str:
        return _clean_idempotency_key_value(value)

    @field_validator("connection_ref", mode="before")
    @classmethod
    def _require_canonical_saved_submit_ref(cls, value: Any) -> Any:
        if not isinstance(value, str):
            raise ValueError("connection_ref 必须是规范 UUID")
        try:
            parsed = UUID(value)
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError("connection_ref 必须是规范 UUID") from exc
        if str(parsed) != value:
            raise ValueError("connection_ref 必须是规范 UUID")
        return value

    @model_validator(mode="after")
    def _require_confirmation(self) -> SavedTrackingSubmitInput:
        if self.confirm is not True:
            raise ValueError("confirm must be true")
        return self


# Retry deliberately has the same strict handoff shape.  Separate aliases keep
# the two service entry points discoverable without introducing a second input
# contract that could drift from submit.
SavedTrackingRetryInput = SavedTrackingSubmitInput
SavedTrackingSubmitPayload = SavedTrackingSubmitInput
SavedTrackingRetryPayload = SavedTrackingRetryInput

#: Upper bound of one explicit batch (issue #87). A batch is a user selection of
#: independent submissions, never a single transactional external call.
MAX_TRACKING_BATCH_SUBMIT_ITEMS = 36


class SavedTrackingBatchSubmitItem(BaseModel):
    """One independent submission inside an explicit batch (issue #87)."""

    model_config = ConfigDict(extra="forbid")

    tracking_id: StrictStr
    expected_revision: StrictInt = Field(ge=1)
    idempotency_key: StrictStr

    @field_validator("tracking_id")
    @classmethod
    def _clean_batch_tracking_id(cls, value: str) -> str:
        return _clean_tracking_id_value(value)

    @field_validator("idempotency_key")
    @classmethod
    def _clean_batch_submit_key(cls, value: str) -> str:
        return _clean_idempotency_key_value(value)


class SavedTrackingBatchSubmitInput(BaseModel):
    """Strict server-side handoff for one explicit batch submit (issue #87).

    Every entry keeps its own revision and opaque idempotency key, so a batch is
    exactly N independent reliable submissions: one failure never rolls back the
    entries that already succeeded.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[SavedTrackingBatchSubmitItem] = Field(
        min_length=1, max_length=MAX_TRACKING_BATCH_SUBMIT_ITEMS
    )
    confirm: StrictBool
    connection_ref: UUID
    configuration_revision: StrictInt = Field(ge=0)
    storage_dir: str | None = None

    @field_validator("connection_ref", mode="before")
    @classmethod
    def _require_canonical_batch_ref(cls, value: Any) -> Any:
        if not isinstance(value, str):
            raise ValueError("connection_ref 必须是规范 UUID")
        try:
            parsed = UUID(value)
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError("connection_ref 必须是规范 UUID") from exc
        if str(parsed) != value:
            raise ValueError("connection_ref 必须是规范 UUID")
        return value

    @model_validator(mode="after")
    def _require_batch_confirmation(self) -> SavedTrackingBatchSubmitInput:
        if self.confirm is not True:
            raise ValueError("confirm must be true")
        return self

    @model_validator(mode="after")
    def _require_unique_entries(self) -> SavedTrackingBatchSubmitInput:
        seen = [item.tracking_id for item in self.items]
        if len(set(seen)) != len(seen):
            raise ValueError("batch items must address distinct tracking records")
        return self


class AutoBangumiCapabilitiesConfigPayload(BaseModel):
    """Strict nested config for the capability endpoint only."""

    model_config = ConfigDict(extra="forbid")
    auth_mode: Literal["password", "api_token"] = "password"
    base_url: str | None = None
    username: str | None = None
    password: str | None = None
    token: str | None = None
    fallback_enabled: bool


class TrackingSyncPayload(BaseModel):
    """Read-only synchronization request resolved through a saved generation."""

    model_config = ConfigDict(extra="forbid")
    connection_ref: UUID
    configuration_revision: StrictInt = Field(ge=0)
    storage_dir: str | None = None
    confirm: Literal[True]


class SavedTrackingSyncInput(BaseModel):
    """Strict handoff for syncing through a server-owned AB connection."""
    model_config = ConfigDict(extra="forbid")
    connection_ref: str
    configuration_revision: StrictInt = Field(ge=0)
    confirm: StrictBool
    storage_dir: str | None = None

    @field_validator("connection_ref")
    @classmethod
    def _canonical_ref(cls, value: str) -> str:
        try:
            parsed = UUID(value)
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError("connection_ref 必须是规范 UUID") from exc
        if str(parsed) != value:
            raise ValueError("connection_ref 必须是规范 UUID")
        return value

    @model_validator(mode="after")
    def _confirmed(self) -> SavedTrackingSyncInput:
        if self.confirm is not True:
            raise ValueError("confirm must be true")
        return self


class SavedTrackingRecoveryInput(BaseModel):
    """Strict recovery handoff for a server-owned AB connection."""

    model_config = ConfigDict(extra="forbid")
    tracking_id: StrictStr
    expected_revision: StrictInt = Field(ge=1)
    action: Literal["AUTO", "MARK_SUCCEEDED", "MARK_FAILED", "VERIFY_EXTERNAL"]
    confirm: StrictBool = False
    connection_ref: UUID | None = None
    configuration_revision: StrictInt | None = Field(default=None, ge=0)
    storage_dir: str | None = None

    @field_validator("tracking_id")
    @classmethod
    def _clean_recovery_tracking_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("tracking_id cannot be empty")
        return value

    @field_validator("connection_ref", mode="before")
    @classmethod
    def _require_canonical_recovery_ref(cls, value: Any) -> Any:
        if not isinstance(value, str):
            raise ValueError("connection_ref 必须是规范 UUID")
        try:
            parsed = UUID(value)
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError("connection_ref 必须是规范 UUID") from exc
        if str(parsed) != value:
            raise ValueError("connection_ref 必须是规范 UUID")
        return value

    @model_validator(mode="after")
    def _manual_confirmation(self) -> SavedTrackingRecoveryInput:
        if self.action in {"MARK_SUCCEEDED", "MARK_FAILED"} and self.confirm is not True:
            raise ValueError("confirm must be true")
        supplied = self.model_fields_set
        if self.action == "VERIFY_EXTERNAL":
            if self.connection_ref is None or self.configuration_revision is None:
                raise ValueError("VERIFY_EXTERNAL requires saved connection generation")
        elif supplied & {"connection_ref", "configuration_revision"}:
            raise ValueError("local recovery cannot include saved connection generation")
        return self


# ---------------------------------------------------------------------------
# Tracking list/detail queries (US-223)
# ---------------------------------------------------------------------------

#: Fixed user status-group enum accepted by ``GET /api/v1/tracking/items``
#: (Stage 29 PRD §11.2).  ``INACTIVE`` groups B-C reserved statuses.
_TRACKING_LIST_STATUS_GROUPS = frozenset(
    {
        TRACKING_STATUS_GROUP_PENDING,
        TRACKING_STATUS_GROUP_PROCESSING,
        TRACKING_STATUS_GROUP_ACTIVE,
        TRACKING_STATUS_GROUP_ATTENTION,
        TRACKING_STATUS_GROUP_INACTIVE,
    }
)

#: Fixed sort enum for the tracking list (§11.2): updated time / title / status.
_TRACKING_LIST_SORTS = frozenset({"updated_at", "title", "status"})

#: Bound on the free-text ``q`` filter (the list is local and small; the bound
#: only stops an absurd query string, never truncates a real title match).
_TRACKING_Q_MAX_LENGTH = 200


class TrackingListQuery(BaseModel):
    """Query args for ``GET /api/v1/tracking/items`` (URL query only)."""

    storage_dir: str | None = None
    q: str | None = None
    status_group: str | None = None
    sort: str | None = None

    @field_validator("q")
    @classmethod
    def _clean_q(cls, value: str | None) -> str | None:
        if value is None:
            return None
        query = value.strip()
        return query[:_TRACKING_Q_MAX_LENGTH] or None

    @field_validator("status_group")
    @classmethod
    def _validate_status_group(cls, value: str | None) -> str | None:
        if value is None:
            return None
        token = value.strip().upper()
        if token not in _TRACKING_LIST_STATUS_GROUPS:
            raise ValueError("status_group 必须为 PENDING/PROCESSING/ACTIVE/ATTENTION/INACTIVE")
        return token

    @field_validator("sort")
    @classmethod
    def _validate_sort(cls, value: str | None) -> str | None:
        if value is None:
            return None
        token = value.strip().lower()
        if token not in _TRACKING_LIST_SORTS:
            raise ValueError("sort 必须为 updated_at/title/status")
        return token


class TrackingDetailQuery(BaseModel):
    """Query args for ``GET /api/v1/tracking/items/{tracking_id}``.

    ``tracking_id`` comes from the URL path; ``storage_dir`` from the query.
    """

    tracking_id: str = ""
    storage_dir: str | None = None


class TrackingRevalidatePayload(BaseModel):
    """Body for ``POST /api/v1/tracking/items/{tracking_id}/revalidate`` (US-224).

    The request carries only the server-observed ``expected_revision`` (a
    revision-aware compare, so a stale client never silently re-checks an
    outdated record) and an optional storage profile.  ``extra="forbid"``
    rejects credentials/other leaked fields: revalidation is a
    pure-local check that never accepts connection or capability config.
    ``tracking_id`` comes from the URL path.
    """

    model_config = ConfigDict(extra="forbid")

    tracking_id: str
    expected_revision: StrictInt = Field(ge=1)
    storage_dir: str | None = None

    @field_validator("tracking_id")
    @classmethod
    def _clean_tracking_id(cls, value: str) -> str:
        tracking_id = value.strip()
        return tracking_id


#: Opaque idempotency-key shape for the unified submit (mirrors the operation
#: model's printable-token contract so a bad key fails at the boundary).
_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-:=]{0,199}$")


#: Fixed recovery-action enum accepted by
#: ``POST /api/v1/tracking/items/{tracking_id}/recover`` (Stage 29 PRD §11.8).
_RECOVERY_ACTIONS = frozenset({"AUTO", "MARK_SUCCEEDED", "MARK_FAILED", "VERIFY_EXTERNAL"})


class TrackingRecoverPayload(BaseModel):
    """Body for ``POST /api/v1/tracking/items/{tracking_id}/recover`` (US-226).

    ``action`` is one of ``AUTO``/``MARK_SUCCEEDED``/``MARK_FAILED``; the two
    manual actions require ``confirm=true`` (written as a USER audit).  ``AUTO``
    only reads local operation/Request/AB-result evidence and never contacts an
    external system, and it never accepts an external id/URL/raw result.
    ``expected_revision`` is the server-observed revision the user is acting
    on.  ``extra="forbid"`` rejects leaked fields.  ``tracking_id`` comes from
    the URL path.
    """

    model_config = ConfigDict(extra="forbid")

    tracking_id: str
    expected_revision: StrictInt = Field(ge=1)
    action: str
    confirm: bool = False
    storage_dir: str | None = None
    connection_ref: UUID | None = None
    configuration_revision: StrictInt | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _verify_external_requires_config(self) -> TrackingRecoverPayload:
        if self.action == "VERIFY_EXTERNAL" and (self.connection_ref is None or self.configuration_revision is None):
            raise ValueError("VERIFY_EXTERNAL requires saved connection generation")
        if self.action != "VERIFY_EXTERNAL" and (self.connection_ref is not None or self.configuration_revision is not None):
            raise ValueError("local recovery cannot include saved connection generation")
        return self

    @field_validator("tracking_id")
    @classmethod
    def _clean_tracking_id(cls, value: str) -> str:
        tracking_id = value.strip()
        if not tracking_id:
            raise ValueError("tracking_id cannot be empty")
        return tracking_id

    @field_validator("action")
    @classmethod
    def _clean_action(cls, value: str) -> str:
        action = value.strip().upper()
        if action not in _RECOVERY_ACTIONS:
            raise ValueError("action 必须为 AUTO、MARK_SUCCEEDED 或 MARK_FAILED")
        return action


# ---------------------------------------------------------------------------
# Tracking management writes (US-245)
# ---------------------------------------------------------------------------

_MANAGEMENT_SCOPES = frozenset({"SUBSCRIPTION", "ASSOCIATED_RSS"})
_SUBSCRIPTION_MANAGEMENT_FIELDS = frozenset(
    {"title", "season", "subtitle_group", "filter_rule", "offset", "expected_folder_name"}
)
_RSS_MANAGEMENT_FIELDS = frozenset({"name", "aggregate", "parser"})


class TrackingFilterRulePatch(BaseModel):
    """Strict public subset of the subscription filter rule patch."""

    model_config = ConfigDict(extra="forbid")

    must_contain: str | None = None
    must_not_contain: str | None = None
    use_regex: bool | None = None
    case_sensitive: bool | None = None

    @model_validator(mode="after")
    def _require_field(self) -> TrackingFilterRulePatch:
        if not self.model_fields_set:
            raise ValueError("filter_rule 不能为空")
        return self


class TrackingSubscriptionPatch(BaseModel):
    """Fields that may be changed on the mapped external subscription."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    season: StrictInt | None = Field(default=None, ge=0, le=100)
    subtitle_group: str | None = None
    filter_rule: TrackingFilterRulePatch | None = None
    offset: StrictInt | None = Field(default=None, ge=0)
    expected_folder_name: str | None = None

    @model_validator(mode="after")
    def _require_field(self) -> TrackingSubscriptionPatch:
        if not self.model_fields_set:
            raise ValueError("patch 不能为空")
        return self


class TrackingRssPatch(BaseModel):
    """Fields that may be changed on the mapped associated RSS target."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    aggregate: bool | None = None
    parser: str | None = None

    @model_validator(mode="after")
    def _require_field(self) -> TrackingRssPatch:
        if not self.model_fields_set:
            raise ValueError("patch 不能为空")
        return self


class _TrackingManagementBasePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tracking_id: str
    target_scope: str
    expected_revision: StrictInt = Field(ge=1)
    idempotency_key: StrictStr
    confirm: Literal[True]
    connection_ref: UUID
    configuration_revision: StrictInt = Field(ge=0)
    storage_dir: str | None = None

    @field_validator("tracking_id")
    @classmethod
    def _clean_management_tracking_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("tracking_id cannot be empty")
        return value

    @field_validator("target_scope")
    @classmethod
    def _validate_management_scope(cls, value: str) -> str:
        value = value.strip().upper()
        if value not in _MANAGEMENT_SCOPES:
            raise ValueError("target_scope 必须为 SUBSCRIPTION 或 ASSOCIATED_RSS")
        return value

    @field_validator("idempotency_key")
    @classmethod
    def _clean_management_idempotency_key(cls, value: str) -> str:
        value = value.strip()
        if not _IDEMPOTENCY_KEY_RE.fullmatch(value):
            raise ValueError("idempotency_key 包含不合法字符")
        return value


class TrackingModifyPayload(_TrackingManagementBasePayload):
    patch: TrackingSubscriptionPatch | TrackingRssPatch

    @model_validator(mode="after")
    def _validate_scope_fields(self) -> TrackingModifyPayload:
        if self.target_scope == "SUBSCRIPTION" and not isinstance(self.patch, TrackingSubscriptionPatch):
            raise ValueError("patch 字段与 target_scope 不匹配")
        if self.target_scope == "ASSOCIATED_RSS" and not isinstance(self.patch, TrackingRssPatch):
            raise ValueError("patch 字段与 target_scope 不匹配")
        return self


class TrackingSetEnabledPayload(_TrackingManagementBasePayload):
    enabled: bool


class TrackingDeleteExternalPayload(_TrackingManagementBasePayload):
    pass


class TrackingRefreshRssPayload(_TrackingManagementBasePayload):
    @field_validator("target_scope")
    @classmethod
    def _rss_scope_only(cls, value: str) -> str:
        if value != "ASSOCIATED_RSS":
            raise ValueError("刷新操作只能作用于 ASSOCIATED_RSS")
        return value


class SavedTrackingPlanDeleteInput(BaseModel):
    """Strict handoff for one "delete the tracking plan" request (issue #92).

    ``delete_external`` defaults to false: the external subscription keeps
    running and MiGuOrca simply stops managing it. Only the checkbox the user
    explicitly ticked can ask for the external object to be removed too.
    """

    model_config = ConfigDict(extra="forbid")

    tracking_id: StrictStr
    confirm: StrictBool
    delete_external: StrictBool = False
    idempotency_key: StrictStr
    # Only a requested external delete needs the saved connection (issue #96).
    connection_ref: UUID | None = None
    configuration_revision: StrictInt | None = Field(default=None, ge=0)
    storage_dir: str | None = None

    @field_validator("tracking_id")
    @classmethod
    def _clean_delete_tracking_id(cls, value: str) -> str:
        return _clean_tracking_id_value(value)

    @field_validator("idempotency_key")
    @classmethod
    def _clean_delete_key(cls, value: str) -> str:
        return _clean_idempotency_key_value(value)

    @field_validator("connection_ref", mode="before")
    @classmethod
    def _canonical_delete_ref(cls, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("connection_ref 必须是规范 UUID")
        try:
            parsed = UUID(value)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("connection_ref 必须是规范 UUID") from exc
        if str(parsed) != value:
            raise ValueError("connection_ref 必须是规范 UUID")
        return value

    @model_validator(mode="after")
    def _require_delete_confirmation(self) -> SavedTrackingPlanDeleteInput:
        if self.confirm is not True:
            raise ValueError("confirm must be true")
        return self

    @model_validator(mode="after")
    def _require_connection_for_external_delete(self) -> SavedTrackingPlanDeleteInput:
        if self.delete_external and (
            self.connection_ref is None or self.configuration_revision is None
        ):
            raise ValueError(
                "删除受控外部订阅需要已保存连接的 connection_ref 与 configuration_revision"
            )
        return self


class SavedTrackingLocalPlan(BaseModel):
    """Local plan values raised together with a confirmed external modify.

    Identity fields (title/season/subtitle_group) are deliberately absent: they
    come from the real MiKan collection and are never edited here. Only the
    editable plan fields travel, and the server merges them into the stored
    snapshot instead of replacing it.
    """

    model_config = ConfigDict(extra="forbid")

    filter_rule: TrackingFilterRulePatch | None = None
    expected_folder_name: str | None = None

    @model_validator(mode="after")
    def _require_local_field(self) -> SavedTrackingLocalPlan:
        if not self.model_fields_set:
            raise ValueError("local_plan 不能为空")
        return self

    @field_validator("expected_folder_name")
    @classmethod
    def _clean_local_folder(cls, value: str | None) -> str | None:
        if value is None:
            return None
        folder = value.strip()
        if not folder:
            raise ValueError("expected_folder_name 不能为空字符串")
        if len(folder) > 255 or any(char in folder for char in "/\\"):
            raise ValueError("expected_folder_name 含不合法字符")
        return folder


class SavedTrackingManagementInput(BaseModel):
    """Strict handoff for management through one saved AB generation."""
    model_config = ConfigDict(extra="forbid")
    tracking_id: StrictStr
    target_scope: StrictStr
    operation: Literal["MODIFY", "SET_ENABLED", "DELETE_EXTERNAL", "REFRESH_RSS"]
    expected_revision: StrictInt = Field(ge=1)
    idempotency_key: StrictStr
    confirm: StrictBool
    connection_ref: UUID
    configuration_revision: StrictInt = Field(ge=0)
    patch: dict[str, Any] | None = None
    enabled: StrictBool | None = None
    #: Local plan values to raise once the external modify is confirmed.
    local_plan: SavedTrackingLocalPlan | None = None
    storage_dir: str | None = None

    @field_validator("connection_ref", mode="before")
    @classmethod
    def _canonical_management_ref(cls, value: Any) -> Any:
        if not isinstance(value, str):
            raise ValueError("connection_ref 必须是规范 UUID")
        try:
            parsed = UUID(value)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("connection_ref 必须是规范 UUID") from exc
        if str(parsed) != value:
            raise ValueError("connection_ref 必须是规范 UUID")
        return value

    @model_validator(mode="after")
    def _strict_management_input(self) -> SavedTrackingManagementInput:
        if self.confirm is not True:
            raise ValueError("confirm must be true")
        if not self.tracking_id.strip() or not _IDEMPOTENCY_KEY_RE.fullmatch(self.idempotency_key.strip()):
            raise ValueError("tracking_id 或 idempotency_key 无效")
        if self.target_scope not in _MANAGEMENT_SCOPES:
            raise ValueError("target_scope 无效")
        if self.operation == "MODIFY":
            if not isinstance(self.patch, dict) or not self.patch:
                raise ValueError("MODIFY 必须提供 patch")
            patch_model = TrackingSubscriptionPatch if self.target_scope == "SUBSCRIPTION" else TrackingRssPatch
            patch_model.model_validate(self.patch)
            if self.enabled is not None:
                raise ValueError("MODIFY 不得提供 enabled")
        elif self.operation == "SET_ENABLED":
            if type(self.enabled) is not bool or self.patch is not None:
                raise ValueError("SET_ENABLED 必须仅提供 enabled")
        elif self.patch is not None or self.enabled is not None:
            raise ValueError("该管理操作不得提供 patch 或 enabled")
        if self.operation == "REFRESH_RSS" and self.target_scope != "ASSOCIATED_RSS":
            raise ValueError("刷新操作只能作用于 ASSOCIATED_RSS")
        return self
