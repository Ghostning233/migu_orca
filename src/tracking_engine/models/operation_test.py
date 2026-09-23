from __future__ import annotations

"""US-220: TrackingOperation model, deterministic ID and state machine tests.

These cover the deterministic opaque ``operation_id`` derived from an
idempotency key, the strict fail-closed schema whitelist, the fixed
PREPARED/IN_PROGRESS/terminal state machine, and the guarantee that
serialized operations never carry sensitive content fields.
"""

from dataclasses import replace
from uuid import UUID

import pytest

from tracking_engine.models.operation import (
    TRACKING_OPERATION_CONNECTION_SCHEMA_VERSION,
    TRACKING_OPERATION_KIND_DELETE_EXTERNAL,
    TRACKING_OPERATION_KIND_MODIFY,
    TRACKING_OPERATION_KIND_REFRESH_RSS,
    TRACKING_OPERATION_KIND_SET_ENABLED,
    TRACKING_OPERATION_KIND_SUBMIT,
    TRACKING_OPERATION_KINDS,
    TRACKING_OPERATION_SCHEMA_VERSION,
    TRACKING_OPERATION_STATE_FAILED,
    TRACKING_OPERATION_STATE_IN_PROGRESS,
    TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
    TRACKING_OPERATION_STATE_PREPARED,
    TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
    TRACKING_OPERATION_STATE_SUCCEEDED,
    TRACKING_OPERATION_STATES,
    TRACKING_OPERATION_TERMINAL_STATES,
    TRACKING_SUBMISSION_MODE_CONTINUE,
    TRACKING_SUBMISSION_MODE_DOWNLOAD_EXISTING,
    TrackingOperation,
    create_tracking_operation,
    operation_from_storage_dict,
    operation_to_storage_dict,
    tracking_operation_id_for_idempotency_key,
    tracking_operation_transition_allowed,
    transition_tracking_operation,
)

IDEMPOTENCY_KEY = "client-op-key-20260908-a1"
SECOND_KEY = "client-op-key-20260908-b2"
#: Frozen expected value — changing the namespace/digest must not silently
#: change existing operation ids (Stage 29 PRD §7.3/§7.4 pattern).
EXPECTED_OPERATION_ID = "op_dac47e39f1ae9190486f7bf0379811c5"
SECOND_OPERATION_ID = "op_24dd3793561ee14678cbfcc4a361637e"

TRACKING_ID = "trk_ba8abbe28fb5345ceccabd82850ee091"
FINGERPRINT = "sha256:abc123"
NOW = "2026-09-08T00:00:00+00:00"


def _operation() -> TrackingOperation:
    return create_tracking_operation(
        tracking_id=TRACKING_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        expected_revision=5,
        request_fingerprint=FINGERPRINT,
        now=NOW,
    )


def test_operation_id_is_deterministic_and_frozen() -> None:
    first = tracking_operation_id_for_idempotency_key(IDEMPOTENCY_KEY)
    second = tracking_operation_id_for_idempotency_key(f" {IDEMPOTENCY_KEY} ")

    assert first == EXPECTED_OPERATION_ID
    assert second == first
    assert tracking_operation_id_for_idempotency_key(SECOND_KEY) == SECOND_OPERATION_ID
    assert tracking_operation_id_for_idempotency_key(SECOND_KEY) != first


def test_operation_id_is_opaque_and_prefix_namespaced() -> None:
    operation_id = tracking_operation_id_for_idempotency_key(IDEMPOTENCY_KEY)

    assert operation_id.startswith("op_")
    assert IDEMPOTENCY_KEY not in operation_id
    # Opaque id must be a single safe path/URL segment.
    assert "/" not in operation_id
    assert "\\" not in operation_id


def test_operation_id_rejects_empty_key() -> None:
    with pytest.raises(ValueError):
        tracking_operation_id_for_idempotency_key("")
    with pytest.raises(ValueError):
        tracking_operation_id_for_idempotency_key("   ")


def test_create_operation_builds_prepared_record() -> None:
    operation = _operation()

    assert operation.schema_version == TRACKING_OPERATION_SCHEMA_VERSION
    assert operation.operation_id == EXPECTED_OPERATION_ID
    assert operation.tracking_id == TRACKING_ID
    assert operation.operation == TRACKING_OPERATION_KIND_SUBMIT
    assert operation.idempotency_key == IDEMPOTENCY_KEY
    assert operation.expected_revision == 5
    assert operation.request_fingerprint == FINGERPRINT
    assert operation.state == TRACKING_OPERATION_STATE_PREPARED
    assert operation.attempt == 1
    assert operation.external_result_id is None
    assert operation.error_type is None
    assert operation.created_at == NOW
    assert operation.updated_at == NOW
    assert operation.completed_at is None
    assert operation.state in TRACKING_OPERATION_STATES


def test_create_operation_trims_safe_strings_and_derives_id() -> None:
    operation = create_tracking_operation(
        tracking_id=f" {TRACKING_ID} ",
        idempotency_key=f" {IDEMPOTENCY_KEY} ",
        expected_revision=1,
        request_fingerprint=f" {FINGERPRINT} ",
        now=NOW,
    )

    assert operation.tracking_id == TRACKING_ID
    assert operation.idempotency_key == IDEMPOTENCY_KEY
    assert operation.request_fingerprint == FINGERPRINT
    assert operation.operation_id == EXPECTED_OPERATION_ID


@pytest.mark.parametrize(
    "mutator",
    [
        lambda: dict(tracking_id=""),
        lambda: dict(tracking_id="   "),
        lambda: dict(idempotency_key=""),
        lambda: dict(idempotency_key="has/slash"),
        lambda: dict(idempotency_key="magnet:?xt=urn:btih:abc"),
        lambda: dict(request_fingerprint=""),
        lambda: dict(expected_revision=0),
        lambda: dict(expected_revision=-3),
        lambda: dict(expected_revision=True),
        lambda: dict(attempt=0),
        lambda: dict(attempt=True),
    ],
)
def test_create_operation_rejects_invalid_bindings(mutator: object) -> None:
    kwargs: dict = {
        "tracking_id": TRACKING_ID,
        "idempotency_key": IDEMPOTENCY_KEY,
        "expected_revision": 5,
        "request_fingerprint": FINGERPRINT,
    }
    kwargs.update(mutator())  # type: ignore[operator]
    with pytest.raises(ValueError):
        create_tracking_operation(now=NOW, **kwargs)


def test_operation_kind_set_accepts_submit_and_all_management_actions() -> None:
    assert frozenset(
        {
            TRACKING_OPERATION_KIND_SUBMIT,
            TRACKING_OPERATION_KIND_MODIFY,
            TRACKING_OPERATION_KIND_SET_ENABLED,
            TRACKING_OPERATION_KIND_DELETE_EXTERNAL,
            TRACKING_OPERATION_KIND_REFRESH_RSS,
        }
    ) == TRACKING_OPERATION_KINDS


def test_transition_to_in_progress_is_allowed_from_prepared() -> None:
    operation = transition_tracking_operation(
        _operation(),
        state=TRACKING_OPERATION_STATE_IN_PROGRESS,
        now="2026-09-08T00:01:00+00:00",
    )

    assert operation.state == TRACKING_OPERATION_STATE_IN_PROGRESS
    assert operation.updated_at == "2026-09-08T00:01:00+00:00"
    assert operation.completed_at is None


def test_transition_to_terminal_states_stamps_completed_at() -> None:
    prepared = _operation()
    in_progress = transition_tracking_operation(
        prepared,
        state=TRACKING_OPERATION_STATE_IN_PROGRESS,
        now="2026-09-08T00:01:00+00:00",
    )

    succeeded = transition_tracking_operation(
        in_progress,
        state=TRACKING_OPERATION_STATE_SUCCEEDED,
        external_result_id="ab-123",
        now="2026-09-08T00:02:00+00:00",
    )
    assert succeeded.completed_at == "2026-09-08T00:02:00+00:00"
    assert succeeded.external_result_id == "ab-123"

    failed = transition_tracking_operation(
        in_progress,
        state=TRACKING_OPERATION_STATE_FAILED,
        error_type="AB_REQUEST_FAILED",
        now="2026-09-08T00:03:00+00:00",
    )
    assert failed.completed_at == "2026-09-08T00:03:00+00:00"
    assert failed.error_type == "AB_REQUEST_FAILED"
    assert failed.external_result_id is None


@pytest.mark.parametrize(
    ("to_state",),
    [
        (TRACKING_OPERATION_STATE_FAILED,),
        (TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,),
        (TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,),
    ],
)
def test_terminal_outcomes_are_reachable_from_in_progress(to_state: str) -> None:
    in_progress = transition_tracking_operation(
        _operation(),
        state=TRACKING_OPERATION_STATE_IN_PROGRESS,
        now="2026-09-08T00:01:00+00:00",
    )
    outcome = transition_tracking_operation(
        in_progress, state=to_state, now="2026-09-08T00:02:00+00:00"
    )
    assert outcome.state == to_state
    assert outcome.completed_at == "2026-09-08T00:02:00+00:00"


@pytest.mark.parametrize(
    "from_state",
    [
        TRACKING_OPERATION_STATE_PREPARED,
        TRACKING_OPERATION_STATE_IN_PROGRESS,
    ],
)
def test_valid_transitions_are_reported(from_state: str) -> None:
    assert tracking_operation_transition_allowed(
        from_state, TRACKING_OPERATION_STATE_FAILED
    )


def test_invalid_transition_prepared_to_succeeded_is_rejected() -> None:
    with pytest.raises(ValueError) as error:
        transition_tracking_operation(
            _operation(),
            state=TRACKING_OPERATION_STATE_SUCCEEDED,
            now="2026-09-08T00:01:00+00:00",
        )
    assert "invalid tracking operation state transition" in str(error.value)


def test_terminal_operations_have_no_outgoing_transitions() -> None:
    for terminal in TRACKING_OPERATION_TERMINAL_STATES:
        base = replace(_operation(), state=terminal)
        with pytest.raises(ValueError):
            transition_tracking_operation(
                base,
                state=TRACKING_OPERATION_STATE_FAILED,
                now="2026-09-08T00:02:00+00:00",
            )


def test_transition_rejects_unknown_state_and_empty_result_fields() -> None:
    in_progress = transition_tracking_operation(
        _operation(),
        state=TRACKING_OPERATION_STATE_IN_PROGRESS,
        now="2026-09-08T00:01:00+00:00",
    )
    with pytest.raises(ValueError):
        transition_tracking_operation(
            in_progress, state="NOPE", now="2026-09-08T00:02:00+00:00"
        )
    with pytest.raises(ValueError):
        transition_tracking_operation(
            in_progress,
            state=TRACKING_OPERATION_STATE_SUCCEEDED,
            external_result_id="",
            now="2026-09-08T00:02:00+00:00",
        )
    with pytest.raises(ValueError):
        transition_tracking_operation(
            in_progress,
            state=TRACKING_OPERATION_STATE_SUCCEEDED,
            error_type="  ",
            now="2026-09-08T00:02:00+00:00",
        )


def test_storage_dict_round_trip_preserves_all_public_fields() -> None:
    operation = transition_tracking_operation(
        _operation(),
        state=TRACKING_OPERATION_STATE_IN_PROGRESS,
        now="2026-09-08T00:01:00+00:00",
    )

    restored = operation_from_storage_dict(operation_to_storage_dict(operation))

    assert restored == operation
    assert set(operation_to_storage_dict(operation)) == {
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


def test_current_operation_round_trip_keeps_only_opaque_connection_ref() -> None:
    connection_ref = "11111111-1111-4111-8111-111111111111"
    operation = create_tracking_operation(
        tracking_id=TRACKING_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        expected_revision=5,
        request_fingerprint=FINGERPRINT,
        connection_ref=UUID(connection_ref),
        now=NOW,
    )

    payload = operation_to_storage_dict(operation)
    # Issue #98 raised the writer version; a default mode stays off the file.
    assert payload["schema_version"] == TRACKING_OPERATION_SCHEMA_VERSION
    assert "submission_mode" not in payload
    assert payload["connection_ref"] == connection_ref
    assert operation_from_storage_dict(payload) == operation
    assert "secret" not in str(payload)


def test_old_operation_versions_remain_readable_without_connection_binding() -> None:
    old = operation_to_storage_dict(_operation())
    for version in (1, 2):
        fixture = {key: value for key, value in old.items() if key != "schema_version"}
        fixture["schema_version"] = version
        if version == 2:
            fixture["operation"] = "MODIFY"
            fixture.update({
                "target_scope": "SUBSCRIPTION",
                "previous_tracking_status": "ACTIVE",
                "expected_external_fingerprint": "sha256:" + "a" * 64,
            })
        restored = operation_from_storage_dict(fixture)
        assert restored.schema_version == version
        assert operation_to_storage_dict(restored)["schema_version"] == version
        assert restored.connection_ref is None


@pytest.mark.parametrize(
    "bad_ref", ["11111111-1111-4111-8111-11111111111", "abcdefab-cdef-4abc-8def-abcdefabcdef".upper(), "https://secret.invalid"]
)
def test_operation_rejects_noncanonical_connection_ref(bad_ref: str) -> None:
    with pytest.raises(ValueError):
        create_tracking_operation(
            tracking_id=TRACKING_ID,
            idempotency_key=IDEMPOTENCY_KEY,
            expected_revision=5,
            request_fingerprint=FINGERPRINT,
            connection_ref=bad_ref,
            now=NOW,
        )


def test_from_storage_round_trip_terminal_operation() -> None:
    terminal = transition_tracking_operation(
        transition_tracking_operation(
            _operation(),
            state=TRACKING_OPERATION_STATE_IN_PROGRESS,
            now="2026-09-08T00:01:00+00:00",
        ),
        state=TRACKING_OPERATION_STATE_SUCCEEDED,
        external_result_id="ab-42",
        now="2026-09-08T00:02:00+00:00",
    )

    restored = operation_from_storage_dict(operation_to_storage_dict(terminal))

    assert restored == terminal
    assert restored.state == TRACKING_OPERATION_STATE_SUCCEEDED
    assert restored.external_result_id == "ab-42"
    assert restored.completed_at == "2026-09-08T00:02:00+00:00"


def test_from_storage_rejects_non_object() -> None:
    with pytest.raises(ValueError):
        operation_from_storage_dict([1, 2, 3])


def test_from_storage_fails_closed_on_unknown_top_level_field() -> None:
    poisoned = operation_to_storage_dict(_operation())
    poisoned["ab_config"] = {"token": "secret"}
    with pytest.raises(ValueError) as error:
        operation_from_storage_dict(poisoned)
    assert "unknown tracking operation fields" in str(error.value)


def test_from_storage_fails_closed_on_wrong_schema_version() -> None:
    poisoned = operation_to_storage_dict(_operation())
    poisoned["schema_version"] = 99
    with pytest.raises(ValueError):
        operation_from_storage_dict(poisoned)


@pytest.mark.parametrize(
    "field,value",
    [
        ("state", "NOT_A_STATE"),
        ("operation", "MODIFY"),
        ("expected_revision", 0),
        ("attempt", 0),
        ("tracking_id", ""),
        ("request_fingerprint", ""),
        ("created_at", ""),
        ("updated_at", None),
    ],
)
def test_from_storage_fails_closed_on_invalid_value(field: str, value: object) -> None:
    poisoned = operation_to_storage_dict(_operation())
    poisoned[field] = value
    with pytest.raises(ValueError):
        operation_from_storage_dict(poisoned)


def test_from_storage_rejects_operation_id_mismatching_key() -> None:
    poisoned = operation_to_storage_dict(_operation())
    poisoned["operation_id"] = SECOND_OPERATION_ID
    with pytest.raises(ValueError) as error:
        operation_from_storage_dict(poisoned)
    assert "does not match idempotency-key-derived id" in str(error.value)


def test_from_storage_rejects_boolean_schema_version() -> None:
    payload = operation_to_storage_dict(_operation())
    payload["schema_version"] = True
    with pytest.raises(ValueError, match="schema_version must be an integer"):
        operation_from_storage_dict(payload)


def test_from_storage_rejects_sensitive_nested_field() -> None:
    poisoned = operation_to_storage_dict(_operation())
    poisoned["request_body"] = {"magnet": "magnet:?xt=urn:btih:abc"}
    with pytest.raises(ValueError):
        operation_from_storage_dict(poisoned)


def test_storage_dict_never_includes_sensitive_fields() -> None:
    in_progress = transition_tracking_operation(
        _operation(),
        state=TRACKING_OPERATION_STATE_IN_PROGRESS,
        now="2026-09-08T00:01:00+00:00",
    )
    operation = transition_tracking_operation(
        in_progress,
        state=TRACKING_OPERATION_STATE_SUCCEEDED,
        external_result_id="ab-7",
        now="2026-09-08T00:02:00+00:00",
    )
    payload = operation_to_storage_dict(operation)

    serialized = str(payload)
    for sensitive in (
        "ab_config",
        "request_body",
        "magnet",
        "http://",
        "https://",
        "/home/",
        "token",
        "password",
    ):
        assert sensitive not in serialized

def test_submission_mode_round_trips_and_defaults_for_old_versions() -> None:
    """Issue #98 AC 1: the chosen mode is an operation fact, not a plan field."""
    operation = create_tracking_operation(
        tracking_id=TRACKING_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        expected_revision=5,
        request_fingerprint=FINGERPRINT,
        submission_mode=TRACKING_SUBMISSION_MODE_DOWNLOAD_EXISTING,
        now=NOW,
    )

    payload = operation_to_storage_dict(operation)
    assert payload["submission_mode"] == TRACKING_SUBMISSION_MODE_DOWNLOAD_EXISTING
    assert operation_from_storage_dict(payload).submission_mode == (
        TRACKING_SUBMISSION_MODE_DOWNLOAD_EXISTING
    )

    # A v3 file predates the field and reads back as 持续追番.
    legacy = {key: value for key, value in payload.items() if key != "submission_mode"}
    legacy["schema_version"] = TRACKING_OPERATION_CONNECTION_SCHEMA_VERSION
    assert operation_from_storage_dict(legacy).submission_mode == (
        TRACKING_SUBMISSION_MODE_CONTINUE
    )

    with pytest.raises(ValueError):
        create_tracking_operation(
            tracking_id=TRACKING_ID,
            idempotency_key=IDEMPOTENCY_KEY,
            expected_revision=5,
            request_fingerprint=FINGERPRINT,
            submission_mode="SOMETHING_ELSE",
            now=NOW,
        )
