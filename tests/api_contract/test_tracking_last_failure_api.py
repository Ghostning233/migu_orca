from __future__ import annotations

"""Issue #241: the detail publishes the persisted reason of the current failure.

A refreshed ``SUBMIT_FAILED`` / ``NEEDS_RECONFIRM`` record must still explain
*why* it failed.  The read projection publishes one nullable ``last_failure``
object from the stored evidence only:

- ``NEEDS_RECONFIRM`` keeps its reason in the revalidation audit transition
  (``REVALIDATION_FAILED``/``PLAN_CHANGE_DETECTED`` + the §11.5 issue code);
- ``SUBMIT_FAILED`` keeps ``last_error`` and must prove it belongs to the
  current terminal operation before it is published;
- ``OUTCOME_UNKNOWN`` and every other status publish nothing, and a stale error
  from a previous failure is never replayed.

These tests go through the real Flask detail route so the contract, the read
projection and the response body are checked together.
"""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient
from pydantic import ValidationError

from apps.migu_orca_web.api_contract import (
    TrackingDetailResultDTO,
    TrackingLastFailureDTO,
)
from apps.migu_orca_web.openapi_gen import generate_openapi
from storage_engine.controllers.operation_repository import (
    bind_tracking_operation,
    compare_and_swap_tracking_operation,
)
from storage_engine.controllers.tracking_repository import compare_and_swap_tracking_record
from tests.api_contract.test_tracking_items_api import _config, _seed_record
from tracking_engine.controllers.submit import SUBMIT_FAILED_MESSAGE
from tracking_engine.models.operation import (
    TRACKING_OPERATION_STATE_FAILED,
    TRACKING_OPERATION_STATE_IN_PROGRESS,
    TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
    transition_tracking_operation,
)
from tracking_engine.models.tracking import (
    TRACKING_AUDIT_REVALIDATION_FAILED,
    TRACKING_AUDIT_SUBMIT_FAILED,
    TRACKING_AUDIT_TRACKING_CREATED,
    TRACKING_STATUS_NEEDS_RECONFIRM,
    TRACKING_STATUS_PENDING_SUBMIT,
    TRACKING_STATUS_SUBMIT_FAILED,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
    transition_record,
)

FAILED_AT = "2026-10-20T10:00:00+00:00"
OPERATION_FAILED_AT = "2026-10-20T10:05:00+00:00"
RECONFIRM_MESSAGE = "当前方案需要重新核对资源筛选。"


def _detail(client: FlaskClient, tracking_id: str) -> dict[str, Any]:
    response = client.get(
        f"/api/v1/tracking/items/{tracking_id}",
        query_string={"storage_dir": "storage"},
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()
    assert payload["ok"] is True
    return payload["result"]


def _seed_reconfirm_record(
    tmp_path: Path,
    *,
    reason_code: str = "NO_VALID_RESOURCES",
    stale_last_error: bool = False,
):
    """Seed a NEEDS_RECONFIRM record whose reason lives in its audit transition."""
    record = _seed_record(
        tmp_path,
        "request-1",
        status=TRACKING_STATUS_PENDING_SUBMIT,
        title="葬送的芙莉莲",
    )
    config = _config(tmp_path)
    advanced = transition_record(
        record,
        status=TRACKING_STATUS_NEEDS_RECONFIRM,
        audit_action=TRACKING_AUDIT_REVALIDATION_FAILED,
        reason_code=reason_code,
        safe_message=RECONFIRM_MESSAGE,
        now=FAILED_AT,
    )
    if stale_last_error:
        # A record that failed a submit before keeps that old adapter error.
        advanced = replace(
            advanced,
            last_error={
                "error_type": "ab_auth_failed",
                "reason_code": "ab_auth_failed",
                "safe_message": SUBMIT_FAILED_MESSAGE,
            },
        )
    compare_and_swap_tracking_record(
        config, record.tracking_id, base_revision=record.revision, record=advanced
    )
    return advanced


def _seed_failed_submit_record(
    tmp_path: Path,
    *,
    error_type: str = "ab_auth_failed",
    operation_state: str = TRACKING_OPERATION_STATE_FAILED,
):
    """Seed a SUBMIT_FAILED record bound to its terminal operation."""
    record = _seed_record(
        tmp_path,
        "request-1",
        status=TRACKING_STATUS_PENDING_SUBMIT,
        title="葬送的芙莉莲",
    )
    config = _config(tmp_path)
    operation, _created = bind_tracking_operation(
        config,
        tracking_id=record.tracking_id,
        operation="SUBMIT",
        idempotency_key="opaque-key-last-failure",
        expected_revision=record.revision,
        request_fingerprint="fp",
    )
    operation = compare_and_swap_tracking_operation(
        config,
        operation.operation_id,
        expected_state=operation.state,
        record=transition_tracking_operation(
            operation, state=TRACKING_OPERATION_STATE_IN_PROGRESS, now=FAILED_AT
        ),
    )
    operation = compare_and_swap_tracking_operation(
        config,
        operation.operation_id,
        expected_state=TRACKING_OPERATION_STATE_IN_PROGRESS,
        record=transition_tracking_operation(
            operation,
            state=operation_state,
            error_type=error_type,
            now=OPERATION_FAILED_AT,
        ),
    )
    advanced = transition_record(
        record,
        status=TRACKING_STATUS_SUBMIT_FAILED,
        audit_action=TRACKING_AUDIT_SUBMIT_FAILED,
        operation_id=operation.operation_id,
        reason_code=error_type,
        safe_message=SUBMIT_FAILED_MESSAGE,
        now=FAILED_AT,
    )
    advanced = replace(
        advanced,
        current_operation_id=operation.operation_id,
        last_error={
            "error_type": error_type,
            "reason_code": error_type,
            "safe_message": SUBMIT_FAILED_MESSAGE,
        },
    )
    compare_and_swap_tracking_record(
        config, record.tracking_id, base_revision=record.revision, record=advanced
    )
    return advanced, operation


def test_refreshed_reconfirm_record_publishes_its_issue_reason(
    tmp_path: Path, client: FlaskClient
) -> None:
    record = _seed_reconfirm_record(tmp_path)

    result = _detail(client, record.tracking_id)

    assert result["status"] == "NEEDS_RECONFIRM"
    assert result["last_failure"] == {
        "error_type": None,
        "category": None,
        "reason_code": "NO_VALID_RESOURCES",
        "safe_message": RECONFIRM_MESSAGE,
        "occurred_at": FAILED_AT,
    }
    # The persisted reason never reuses the review-issue channel (issue #241).
    assert result["revalidation_issues"] == []


def test_refreshed_submit_failure_publishes_its_category_not_invented_detail(
    tmp_path: Path, client: FlaskClient
) -> None:
    record, _operation = _seed_failed_submit_record(tmp_path)

    result = _detail(client, record.tracking_id)

    assert result["last_failure"] == {
        "error_type": "ab_auth_failed",
        "category": "AUTHENTICATION",
        "reason_code": "ab_auth_failed",
        "safe_message": SUBMIT_FAILED_MESSAGE,
        "occurred_at": FAILED_AT,
    }
    # The public object carries exactly the five safe fields; nothing stored
    # beside the error (URLs, credentials) can reach the response.
    assert set(result["last_failure"]) == {
        "error_type", "category", "reason_code", "safe_message", "occurred_at",
    }


@pytest.mark.parametrize(
    "status",
    ["VERIFYING_EXTERNAL", "RECOVERY_REQUIRED", "UNKNOWN", "ACTIVE", "DISABLED"],
)
def test_other_states_never_publish_a_failure_reason(
    tmp_path: Path, client: FlaskClient, status: str
) -> None:
    record = _seed_record(
        tmp_path, "request-1", status=TRACKING_STATUS_PENDING_SUBMIT, title="葬送的芙莉莲"
    )
    config = _config(tmp_path)
    advanced = transition_record(
        record,
        status=status,
        audit_action=TRACKING_AUDIT_TRACKING_CREATED,
        now=FAILED_AT,
    )
    advanced = replace(
        advanced,
        last_error={
            "error_type": "ab_auth_failed",
            "reason_code": "ab_auth_failed",
            "safe_message": SUBMIT_FAILED_MESSAGE,
        },
    )
    compare_and_swap_tracking_record(
        config, record.tracking_id, base_revision=record.revision, record=advanced
    )

    result = _detail(client, record.tracking_id)

    assert result["last_failure"] is None


def test_a_stale_error_does_not_become_a_new_reconfirm_reason(
    tmp_path: Path, client: FlaskClient
) -> None:
    # A record that failed a submit and then failed revalidation keeps the old
    # adapter error in last_error; the projection must use the new transition.
    record = _seed_reconfirm_record(tmp_path, stale_last_error=True)

    result = _detail(client, record.tracking_id)

    assert result["last_failure"]["error_type"] is None
    assert result["last_failure"]["reason_code"] == "NO_VALID_RESOURCES"
    assert result["last_failure"]["safe_message"] == RECONFIRM_MESSAGE


def test_a_submit_failure_without_a_bound_operation_is_not_published(
    tmp_path: Path, client: FlaskClient
) -> None:
    # Legacy archive: last_error exists but no operation can prove it is current.
    record = _seed_record(
        tmp_path, "request-1", status=TRACKING_STATUS_PENDING_SUBMIT, title="芙莉莲"
    )
    config = _config(tmp_path)
    advanced = transition_record(
        record,
        status=TRACKING_STATUS_SUBMIT_FAILED,
        audit_action=TRACKING_AUDIT_SUBMIT_FAILED,
        reason_code="ab_auth_failed",
        safe_message=SUBMIT_FAILED_MESSAGE,
        now=FAILED_AT,
    )
    advanced = replace(
        advanced,
        last_error={
            "error_type": "ab_auth_failed",
            "reason_code": "ab_auth_failed",
            "safe_message": SUBMIT_FAILED_MESSAGE,
        },
    )
    compare_and_swap_tracking_record(
        config, record.tracking_id, base_revision=record.revision, record=advanced
    )

    result = _detail(client, record.tracking_id)

    assert result["last_failure"] is None


def test_an_unbound_submit_error_is_not_published(
    tmp_path: Path, client: FlaskClient
) -> None:
    # The stored error names a different terminal state than the operation, so
    # the server cannot prove it belongs to this failure.
    record, _operation = _seed_failed_submit_record(
        tmp_path, operation_state=TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN
    )

    result = _detail(client, record.tracking_id)

    assert result["last_failure"] is None


def test_the_contract_category_matches_the_engine_policy() -> None:
    # The read projection reuses the engine's public category mapper, so the
    # contract Literal and the engine tuple must never drift apart.
    from typing import get_args

    from apps.migu_orca_web.api_contract import TrackingFailureCategory
    from tracking_engine.controllers.submit import SUBMIT_FAILURE_CATEGORIES

    assert set(get_args(TrackingFailureCategory)) == set(SUBMIT_FAILURE_CATEGORIES)


def test_contract_declares_one_nullable_last_failure_object() -> None:
    assert TrackingDetailResultDTO.model_fields["last_failure"].default is None
    fields = TrackingLastFailureDTO.model_fields
    assert set(fields) == {
        "error_type", "category", "reason_code", "safe_message", "occurred_at",
    }
    assert fields["safe_message"].is_required()
    dto = TrackingLastFailureDTO(
        reason_code="NO_VALID_RESOURCES", safe_message=RECONFIRM_MESSAGE
    )
    assert dto.model_dump() == {
        "error_type": None,
        "category": None,
        "reason_code": "NO_VALID_RESOURCES",
        "safe_message": RECONFIRM_MESSAGE,
        "occurred_at": None,
    }
    with pytest.raises(ValidationError):
        TrackingLastFailureDTO.model_validate(
            {"safe_message": "x", "request_url": "http://private.example"}
        )
    with pytest.raises(ValidationError):
        TrackingLastFailureDTO.model_validate({"reason_code": "NO_VALID_RESOURCES"})


def test_openapi_publishes_the_nullable_field() -> None:
    spec = generate_openapi()
    response = spec["paths"]["/api/v1/tracking/items/{tracking_id}"]["get"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]
    detail = response["properties"]["result"]
    # The field is optional/nullable, not required (old clients keep working).
    assert "last_failure" in detail["properties"]
    assert "last_failure" not in detail.get("required", [])
    branches = detail["properties"]["last_failure"]["anyOf"]
    last_failure = next(
        branch for branch in branches if branch.get("type") == "object"
    )
    assert set(last_failure["properties"]) == {
        "error_type", "category", "reason_code", "safe_message", "occurred_at",
    }
    assert last_failure["required"] == ["safe_message"]


def test_the_unresolved_status_keeps_its_own_meaning(
    tmp_path: Path, client: FlaskClient
) -> None:
    # OUTCOME_UNKNOWN stores a fixed "outcome unknown" note, never a reason.
    record = _seed_record(
        tmp_path, "request-1", status=TRACKING_STATUS_PENDING_SUBMIT, title="芙莉莲"
    )
    config = _config(tmp_path)
    advanced = transition_record(
        record,
        status=TRACKING_STATUS_VERIFYING_EXTERNAL,
        audit_action="SUBMIT_OUTCOME_UNKNOWN",
        safe_message="Auto Bangumi 结果待确认，请先恢复核验",
        now=FAILED_AT,
    )
    advanced = replace(advanced, last_error={
        "error_type": "outcome_unknown",
        "reason_code": "outcome_unknown",
        "safe_message": "Auto Bangumi 结果待确认，请先恢复核验",
    })
    compare_and_swap_tracking_record(
        config, record.tracking_id, base_revision=record.revision, record=advanced
    )

    result = _detail(client, record.tracking_id)

    assert result["status"] == "VERIFYING_EXTERNAL"
    assert result["last_failure"] is None
