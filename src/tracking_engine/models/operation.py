"""TrackingOperation data contract and submit idempotency state machine (US-220).

A TrackingOperation is the durable evidence of **one external submit attempt**.
It is an independent repository from the Stage 28 save-confirm idempotency
records (D29-04): the file is keyed by a deterministic ``operation_id`` derived
from the client ``idempotency_key``, so a same-key replay converges to the same
operation file across restarts and concurrent binders, while a user-initiated
retry (a fresh key) creates a fresh operation.  This module owns the **content**
contract only — durable JSON persistence lives in
``storage_engine.controllers.operation_repository``.

State machine
-------------

.. code-block:: text

    (none) -> PREPARED                    binding is durable; external not yet called
    PREPARED -> IN_PROGRESS               durable boundary before the external call
    PREPARED -> FAILED                    pre-external persist failed -> the external
                                          system was provably never called
    IN_PROGRESS -> SUCCEEDED              external result clearly succeeded
    IN_PROGRESS -> FAILED                 external result clearly failed
    IN_PROGRESS -> OUTCOME_UNKNOWN        external outcome cannot be determined
    IN_PROGRESS -> RECOVERY_REQUIRED      external succeeded/unknown but a critical
                                          local result could not be persisted

``PREPARED`` means the idempotent binding is on disk but the external system has
not been called; only after the operation switches to ``IN_PROGRESS`` is a caller
allowed to touch Auto Bangumi.  Terminal states
(``SUCCEEDED``/``FAILED``/``OUTCOME_UNKNOWN``/``RECOVERY_REQUIRED``) are
replayable outcomes: a same-key/same-binding replay returns the stored result
instead of making a second external call.  An operation that reaches a terminal
state has no outgoing transitions.

Security
--------
The operation never stores the request body, AB config, upstream responses,
titles, URLs, magnets or paths.  Its schema is a strict whitelist of typed
non-sensitive fields only; unknown top-level fields fail closed on read, never
guessed.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

TRACKING_OPERATION_SCHEMA_VERSION = 1

# -- operation kinds ----------------------------------------------------------
#: The only operation kind Stage 29 B-B produces.  Future B-C actions
#: (e.g. ``MODIFY``/``DISABLE``) extend this set in a later story.
TRACKING_OPERATION_KIND_SUBMIT = "SUBMIT"
TRACKING_OPERATION_KINDS = frozenset({TRACKING_OPERATION_KIND_SUBMIT})

# -- states -------------------------------------------------------------------
#: Binding is durable on disk but the external system has not been called.
TRACKING_OPERATION_STATE_PREPARED = "PREPARED"
#: Durable boundary already written; an external call may have happened.
TRACKING_OPERATION_STATE_IN_PROGRESS = "IN_PROGRESS"
TRACKING_OPERATION_STATE_SUCCEEDED = "SUCCEEDED"
TRACKING_OPERATION_STATE_FAILED = "FAILED"
TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
TRACKING_OPERATION_STATE_RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
TRACKING_OPERATION_STATES = frozenset(
    {
        TRACKING_OPERATION_STATE_PREPARED,
        TRACKING_OPERATION_STATE_IN_PROGRESS,
        TRACKING_OPERATION_STATE_SUCCEEDED,
        TRACKING_OPERATION_STATE_FAILED,
        TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
        TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
    }
)

#: States that finish the external attempt and are replayable outcomes.
TRACKING_OPERATION_TERMINAL_STATES = frozenset(
    {
        TRACKING_OPERATION_STATE_SUCCEEDED,
        TRACKING_OPERATION_STATE_FAILED,
        TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
        TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
    }
)

#: Allowed transitions (Stage 29 PRD §7.3).  Terminal states have no outgoing
#: transitions; a transition that is absent from this map is invalid.
_TRANSITIONS: dict[str, frozenset[str]] = {
    TRACKING_OPERATION_STATE_PREPARED: frozenset(
        {
            TRACKING_OPERATION_STATE_IN_PROGRESS,
            TRACKING_OPERATION_STATE_FAILED,
        }
    ),
    TRACKING_OPERATION_STATE_IN_PROGRESS: frozenset(
        {
            TRACKING_OPERATION_STATE_SUCCEEDED,
            TRACKING_OPERATION_STATE_FAILED,
            TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
            TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
        }
    ),
    TRACKING_OPERATION_STATE_SUCCEEDED: frozenset(),
    TRACKING_OPERATION_STATE_FAILED: frozenset(),
    TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN: frozenset(),
    TRACKING_OPERATION_STATE_RECOVERY_REQUIRED: frozenset(),
}

# -- schema whitelist ---------------------------------------------------------
_OPERATION_FIELDS = frozenset(
    {
        "schema_version",
        "operation_id",
        "tracking_id",
        "operation",
        "idempotency_key",
        "expected_revision",
        "request_fingerprint",
        "state",
        "attempt",
        "external_result_id",
        "error_type",
        "created_at",
        "updated_at",
        "completed_at",
    }
)

#: Safe opaque idempotency-key shape.  The key never becomes a file name (the
#: operation id is a hash of it) but the whitelist keeps the persisted field a
#: single printable token that cannot carry a URL/magnet/absolute path.
_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-:=]{0,199}$")


def tracking_operation_id_for_idempotency_key(idempotency_key: str) -> str:
    """Return the deterministic opaque ``operation_id`` for one idempotency key.

    The namespace + digest algorithm is part of the storage contract and is
    frozen by tests: the same key must always resolve to the same operation
    across restarts, concurrent binds and network replays, so a replayed key
    can never start a second external call (D29-03 pattern for operations).
    """
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise ValueError("idempotency_key must be a non-empty string")
    clean = idempotency_key.strip()
    digest = hashlib.sha256(
        f"migu-orca/tracking-operation/v1\x00{clean}".encode()
    ).hexdigest()
    return f"op_{digest[:32]}"


def tracking_operation_transition_allowed(from_state: str, to_state: str) -> bool:
    """Return whether ``to_state`` is a legal transition from ``from_state``."""
    return to_state in _TRANSITIONS.get(from_state, frozenset())


@dataclass(frozen=True)
class TrackingOperation:
    """One durable external-submit operation (Stage 29 PRD §7.3).

    Every value is non-sensitive and whitelisted.  ``external_result_id`` is
    only ever a safe opaque external id and ``error_type`` only a stable code —
    never raw upstream responses, URLs, magnets, paths or credentials.
    """

    schema_version: int = TRACKING_OPERATION_SCHEMA_VERSION
    operation_id: str = ""
    tracking_id: str = ""
    operation: str = TRACKING_OPERATION_KIND_SUBMIT
    idempotency_key: str = ""
    expected_revision: int = 1
    request_fingerprint: str = ""
    state: str = TRACKING_OPERATION_STATE_PREPARED
    attempt: int = 1
    external_result_id: str | None = None
    error_type: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None


def utc_now() -> str:
    """Current UTC RFC3339 timestamp used for operation timestamps."""
    return datetime.now(UTC).isoformat()


def create_tracking_operation(
    *,
    tracking_id: str,
    idempotency_key: str,
    expected_revision: int,
    request_fingerprint: str,
    operation: str = TRACKING_OPERATION_KIND_SUBMIT,
    attempt: int = 1,
    now: str | None = None,
) -> TrackingOperation:
    """Build a fresh ``PREPARED`` operation bound to ``idempotency_key``.

    ``tracking_id``/``idempotency_key``/``request_fingerprint`` must be
    non-empty safe strings and ``expected_revision`` a positive integer.  The
    ``operation_id`` is derived deterministically from the key so the same key
    always produces the same operation file.
    """
    if operation not in TRACKING_OPERATION_KINDS:
        raise ValueError(f"unknown tracking operation kind: {operation}")
    clean_tracking_id = _require_non_empty_str(tracking_id, "tracking_id")
    clean_key = _validated_idempotency_key(idempotency_key, "create_tracking_operation")
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
        raise ValueError("expected_revision must be a positive integer")
    if expected_revision < 1:
        raise ValueError("expected_revision must be a positive integer")
    clean_fingerprint = _require_non_empty_str(
        request_fingerprint, "request_fingerprint"
    )
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise ValueError("attempt must be a positive integer")
    timestamp = now or utc_now()
    return TrackingOperation(
        schema_version=TRACKING_OPERATION_SCHEMA_VERSION,
        operation_id=tracking_operation_id_for_idempotency_key(clean_key),
        tracking_id=clean_tracking_id,
        operation=operation,
        idempotency_key=clean_key,
        expected_revision=expected_revision,
        request_fingerprint=clean_fingerprint,
        state=TRACKING_OPERATION_STATE_PREPARED,
        attempt=attempt,
        created_at=timestamp,
        updated_at=timestamp,
    )


def transition_tracking_operation(
    operation: TrackingOperation,
    *,
    state: str,
    external_result_id: str | None = None,
    error_type: str | None = None,
    now: str | None = None,
) -> TrackingOperation:
    """Return a new operation for a validated state transition.

    Only the transitions in ``_TRANSITIONS`` are allowed (Stage 29 PRD §7.3);
    an unknown state or a transition out of a terminal state raises
    ``ValueError`` so the repository can map it to a stable error.  Entering a
    terminal state stamps ``completed_at``; other transitions leave it unset.
    ``external_result_id``/``error_type`` are optional non-empty safe strings.
    """
    if state not in TRACKING_OPERATION_STATES:
        raise ValueError(f"unknown tracking operation state: {state}")
    if not tracking_operation_transition_allowed(operation.state, state):
        raise ValueError(
            f"invalid tracking operation state transition: {operation.state} -> {state}"
        )
    timestamp = now or utc_now()
    return replace(
        operation,
        state=state,
        external_result_id=_optional_clean_str(
            external_result_id, "external_result_id"
        ),
        error_type=_optional_clean_str(error_type, "error_type"),
        updated_at=timestamp,
        completed_at=timestamp if state in TRACKING_OPERATION_TERMINAL_STATES else None,
    )


def operation_to_storage_dict(operation: TrackingOperation) -> dict[str, Any]:
    """Serialize an operation for persistence.

    The writer emits exactly the top-level whitelist with normalized values, so
    an accidental sensitive field can never reach disk.
    """
    return {
        "schema_version": TRACKING_OPERATION_SCHEMA_VERSION,
        "operation_id": operation.operation_id,
        "tracking_id": operation.tracking_id,
        "operation": operation.operation,
        "idempotency_key": operation.idempotency_key,
        "expected_revision": operation.expected_revision,
        "request_fingerprint": operation.request_fingerprint,
        "state": operation.state,
        "attempt": operation.attempt,
        "external_result_id": operation.external_result_id,
        "error_type": operation.error_type,
        "created_at": operation.created_at,
        "updated_at": operation.updated_at,
        "completed_at": operation.completed_at,
    }


def operation_from_storage_dict(data: Any) -> TrackingOperation:
    """Reconstruct an operation from a storage dict (fail-closed validation).

    Unknown top-level fields, an unsupported ``schema_version``, an invalid
    state/operation kind, missing required fields, type mismatches and an
    ``operation_id`` that does not match the idempotency-key-derived id all
    raise ``ValueError`` so the repository maps them to a stable storage error.
    """
    if not isinstance(data, dict):
        raise ValueError("tracking operation JSON must be an object")
    unknown = sorted(set(data) - _OPERATION_FIELDS)
    if unknown:
        raise ValueError(f"unknown tracking operation fields: {', '.join(unknown)}")

    schema_version = data.get("schema_version")
    if schema_version != TRACKING_OPERATION_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported tracking operation schema_version: {schema_version!r}"
        )

    operation_id = _require_non_empty_str(data.get("operation_id"), "operation_id")
    tracking_id = _require_non_empty_str(data.get("tracking_id"), "tracking_id")
    operation = data.get("operation")
    if operation not in TRACKING_OPERATION_KINDS:
        raise ValueError(f"invalid tracking operation kind: {operation!r}")
    idempotency_key = _validated_idempotency_key(
        data.get("idempotency_key"), "operation_from_storage_dict"
    )
    if operation_id != tracking_operation_id_for_idempotency_key(idempotency_key):
        raise ValueError(
            "operation_id does not match idempotency-key-derived id: "
            f"{operation_id}"
        )

    state = data.get("state")
    if state not in TRACKING_OPERATION_STATES:
        raise ValueError(f"invalid tracking operation state: {state!r}")
    expected_revision = data.get("expected_revision")
    if (
        not isinstance(expected_revision, int)
        or isinstance(expected_revision, bool)
        or expected_revision < 1
    ):
        raise ValueError("expected_revision must be a positive integer")
    attempt = data.get("attempt")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise ValueError("attempt must be a positive integer")

    created_at = _require_non_empty_str(data.get("created_at"), "created_at")
    updated_at = _require_non_empty_str(data.get("updated_at"), "updated_at")

    return TrackingOperation(
        schema_version=TRACKING_OPERATION_SCHEMA_VERSION,
        operation_id=operation_id,
        tracking_id=tracking_id,
        operation=operation,
        idempotency_key=idempotency_key,
        expected_revision=expected_revision,
        request_fingerprint=_require_non_empty_str(
            data.get("request_fingerprint"), "request_fingerprint"
        ),
        state=state,
        attempt=attempt,
        external_result_id=_optional_clean_str(
            data.get("external_result_id"), "external_result_id"
        ),
        error_type=_optional_clean_str(data.get("error_type"), "error_type"),
        created_at=created_at,
        updated_at=updated_at,
        completed_at=_optional_clean_str(data.get("completed_at"), "completed_at"),
    )


# -- helpers ------------------------------------------------------------------


def _validated_idempotency_key(value: Any, failed_step: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("idempotency_key must be a non-empty string")
    clean = value.strip()
    if not _IDEMPOTENCY_KEY_RE.fullmatch(clean):
        raise ValueError("idempotency_key contains unsupported characters")
    return clean


def _require_non_empty_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _optional_clean_str(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string or null")
    return value.strip()


__all__ = [
    "TRACKING_OPERATION_KINDS",
    "TRACKING_OPERATION_KIND_SUBMIT",
    "TRACKING_OPERATION_SCHEMA_VERSION",
    "TRACKING_OPERATION_STATES",
    "TRACKING_OPERATION_STATE_FAILED",
    "TRACKING_OPERATION_STATE_IN_PROGRESS",
    "TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN",
    "TRACKING_OPERATION_STATE_PREPARED",
    "TRACKING_OPERATION_STATE_RECOVERY_REQUIRED",
    "TRACKING_OPERATION_STATE_SUCCEEDED",
    "TRACKING_OPERATION_TERMINAL_STATES",
    "TrackingOperation",
    "create_tracking_operation",
    "operation_from_storage_dict",
    "operation_to_storage_dict",
    "tracking_operation_id_for_idempotency_key",
    "tracking_operation_transition_allowed",
    "transition_tracking_operation",
]
