"""Pure contracts for tracking-management actions.

This module intentionally has no web, storage, or transport dependency.  It is
safe to use from adapters and services alike; only the returned digest and
classification are intended to cross a durable boundary.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

ManagementAction = Literal["MODIFY", "SET_ENABLED", "DELETE_EXTERNAL", "REFRESH_RSS"]
ManagementOutcome = Literal[
    "SUCCESS", "DEFINITE_FAILURE", "OUTCOME_UNKNOWN", "RECOVERY_REQUIRED"
]

MANAGEMENT_OUTCOME_SUCCESS = "SUCCESS"
MANAGEMENT_OUTCOME_DEFINITE_FAILURE = "DEFINITE_FAILURE"
MANAGEMENT_OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
MANAGEMENT_OUTCOME_RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


def canonical_management_fingerprint(
    *, action: str, target_scope: str, expected_projection: Any,
    connection_ref: str | None = None,
) -> str:
    """Return a deterministic SHA-256 digest without retaining the projection."""
    if action not in {"MODIFY", "SET_ENABLED", "DELETE_EXTERNAL", "REFRESH_RSS"}:
        raise ValueError("unsupported management action")
    if target_scope not in {"SUBSCRIPTION", "ASSOCIATED_RSS"}:
        raise ValueError("unsupported management target scope")
    try:
        binding = {"action": action, "scope": target_scope, "projection": expected_projection}
        # Preserve the historical digest for legacy/unbound operations.  A
        # saved connection is isolated only when an actual canonical ref is
        # present.
        if connection_ref is not None:
            binding["connection_ref"] = connection_ref
        encoded = json.dumps(
            binding,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("expected_projection must be JSON-compatible") from exc
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def classify_management_action(
    *,
    status_code: int | None = None,
    transport_error: str | None = None,
    response_valid: bool = True,
    persisted: bool = True,
) -> ManagementOutcome:
    """Classify an action result using only transport facts.

    Authentication/configuration/validation failures are definite.  A lost
    response, server error, or malformed response is unknown.  A known external
    result followed by a local persistence failure requires recovery.
    """
    if not persisted:
        return MANAGEMENT_OUTCOME_RECOVERY_REQUIRED
    if transport_error in {"timeout", "connection", "5xx", "unknown"}:
        return MANAGEMENT_OUTCOME_UNKNOWN
    if status_code is not None and 200 <= status_code < 300 and response_valid:
        return MANAGEMENT_OUTCOME_SUCCESS
    if status_code is not None and (400 <= status_code < 500 or status_code == 406):
        return MANAGEMENT_OUTCOME_DEFINITE_FAILURE
    if status_code is not None and status_code >= 500:
        return MANAGEMENT_OUTCOME_UNKNOWN
    if not response_valid:
        return MANAGEMENT_OUTCOME_UNKNOWN
    return MANAGEMENT_OUTCOME_DEFINITE_FAILURE


def classify_management_readback(
    *, expected_fingerprint: str, actual_fingerprint: str | None, read_succeeded: bool
) -> ManagementOutcome:
    """Classify a write's complete readback without making a new write."""
    if not read_succeeded or actual_fingerprint is None:
        return MANAGEMENT_OUTCOME_UNKNOWN
    if actual_fingerprint == expected_fingerprint:
        return MANAGEMENT_OUTCOME_SUCCESS
    return MANAGEMENT_OUTCOME_DEFINITE_FAILURE


def safe_action_summary(action: str, target_scope: str) -> dict[str, str]:
    """Return the only public action identity (no input or external values)."""
    if action not in {"MODIFY", "SET_ENABLED", "DELETE_EXTERNAL", "REFRESH_RSS"}:
        raise ValueError("unsupported management action")
    if target_scope not in {"SUBSCRIPTION", "ASSOCIATED_RSS"}:
        raise ValueError("unsupported management target scope")
    return {"action": action, "target_scope": target_scope}


__all__ = [
    "ManagementAction",
    "ManagementOutcome",
    "MANAGEMENT_OUTCOME_SUCCESS",
    "MANAGEMENT_OUTCOME_DEFINITE_FAILURE",
    "MANAGEMENT_OUTCOME_UNKNOWN",
    "MANAGEMENT_OUTCOME_RECOVERY_REQUIRED",
    "canonical_management_fingerprint",
    "classify_management_action",
    "classify_management_readback",
    "safe_action_summary",
]
