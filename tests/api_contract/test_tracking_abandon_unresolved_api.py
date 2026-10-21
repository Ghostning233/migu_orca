from __future__ import annotations

"""Issue #230 (T5b): risk-confirmed abandon and the fail-closed delete guard.

ADR-0006 narrows the delete lock from the record status to "**may the external
write still be running**", judged on the operation state:

* ``IN_PROGRESS`` / ``PREPARED`` → refused (the write may still run, or may be
  turned into a running one by another executor);
* ``OUTCOME_UNKNOWN`` / ``RECOVERY_REQUIRED`` → allowed only through the explicit
  risk confirmation that binds the record revision and the current operation;
* missing / damaged / unreadable / unknown operation state → refused.

The abandon path deletes **local data only**.  It must never accept the external
delete scope: turning an abandon into a new external write is exactly the loop
ADR-0006 closes.  These tests run against the real Flask app with an isolated
temporary storage root and a stubbed management sequence.
"""

import types
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient

from apps.migu_orca_web.schemas import SavedTrackingPlanDeleteInput
from apps.migu_orca_web.tracking_plan_delete_service import run_saved_tracking_plan_delete
from shared.errors import Stage1Error
from storage_engine.controllers.operation_repository import bind_tracking_operation
from storage_engine.controllers.request_repository import load_request_snapshot
from storage_engine.controllers.tracking_repository import (
    compare_and_swap_tracking_record,
    list_tracking_records,
    load_tracking_record,
)
from tests.api_contract.test_tracking_plan_delete_api import (
    _body,
    _config,
    _post,
    _seed,
    _stub_management,
    _with_operation,
)
from tracking_engine.models.operation import (
    TRACKING_OPERATION_STATE_IN_PROGRESS,
    TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
    TRACKING_OPERATION_STATE_PREPARED,
    TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
    TRACKING_OPERATION_STATE_SUCCEEDED,
)
from tracking_engine.models.tracking import TRACKING_STATUS_SUBMITTING

_STEP = "run_saved_tracking_plan_delete"


def _abandon_body(record, **overrides: Any) -> dict[str, Any]:
    """The risk confirmation: local-only delete + record/operation binding."""
    body = _body(
        record,
        delete_external=False,
        expected_revision=record.revision,
        expected_operation_id=record.current_operation_id,
    )
    body.update(overrides)
    return body


def _post_abandon(client: FlaskClient, record, **overrides: Any):
    return client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/delete-plan",
        json=_abandon_body(record, **overrides),
    )


def _still_there(tmp_path: Path, record) -> bool:
    return [item.tracking_id for item in list_tracking_records(_config(tmp_path)).records] == [
        record.tracking_id
    ]


# ---------------------------------------------------------------------------
# The confirmation contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "missing",
    [("expected_revision", "expected_operation_id"), ("expected_operation_id",), ("expected_revision",)],
)
def test_abandon_requires_the_full_bound_confirmation(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch, missing
) -> None:
    """ADR-0006: the confirmation binds record revision **and** operation."""
    record, _request = _seed(tmp_path, mapped=False)
    record = _with_operation(tmp_path, record, state=TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN)
    calls = _stub_management(monkeypatch, "SUCCEEDED")
    body = _abandon_body(record)
    for field in missing:
        body.pop(field)

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/delete-plan", json=body
    )

    assert response.status_code == 400
    assert response.get_json()["error_type"] in {"data_validation_errors", "validation_error"}
    assert calls == []
    assert _still_there(tmp_path, record)


def test_abandon_refuses_the_external_delete_scope(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An abandon must not become a new external write (ADR-0006 decision 6)."""
    record, _request = _seed(tmp_path, mapped=True)
    record = _with_operation(tmp_path, record, state=TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN)
    calls = _stub_management(monkeypatch, "SUCCEEDED")

    response = _post_abandon(client, record, delete_external=True)

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["error_type"] == "validation_error"
    assert payload["error_data"]["details"]["field"] == "delete_external"
    assert calls == []
    assert _still_there(tmp_path, record)


@pytest.mark.parametrize(
    "state",
    [TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN, TRACKING_OPERATION_STATE_RECOVERY_REQUIRED],
)
def test_abandon_deletes_only_local_data(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    """The abandon removes the plan/record and keeps the operation as orphan evidence."""
    record, request = _seed(tmp_path, mapped=False)
    record = _with_operation(tmp_path, record, state=state)
    operation_file = next(_config(tmp_path).tracking_operations_dir.glob("*.json"))
    calls = _stub_management(monkeypatch, "SUCCEEDED")

    response = _post_abandon(client, record)

    payload = response.get_json()
    assert response.status_code == 200, payload
    assert payload["result"] == {
        "tracking_id": record.tracking_id,
        "outcome": "DELETED",
        "external_deleted": False,
    }
    # No external call was made by the abandon path.
    assert calls == []
    # Local plan and record are gone; media is never touched.
    assert list_tracking_records(_config(tmp_path)).records == []
    with pytest.raises(Stage1Error):
        load_request_snapshot(_config(tmp_path), request["request_id"])
    # ADR-0006 consequence: the operation file stays as orphan evidence.
    assert operation_file.exists()


# ---------------------------------------------------------------------------
# Fail closed on a write that may still run, or on an unreadable operation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state", [TRACKING_OPERATION_STATE_PREPARED, TRACKING_OPERATION_STATE_IN_PROGRESS]
)
def test_abandon_fails_closed_while_the_write_may_still_run(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    record, _request = _seed(tmp_path, mapped=False)
    record = _with_operation(tmp_path, record, state=state)
    calls = _stub_management(monkeypatch, "SUCCEEDED")

    response = _post_abandon(client, record)

    assert response.status_code == 409
    assert response.get_json()["error_type"] == "tracking_state_conflict"
    assert calls == []
    assert _still_there(tmp_path, record)


def test_abandon_fails_closed_when_the_operation_is_unreadable(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    record, _request = _seed(tmp_path, mapped=False)
    record = _with_operation(tmp_path, record, state=TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN)
    operation_file = next(_config(tmp_path).tracking_operations_dir.glob("*.json"))
    operation_file.write_text("{ not json", encoding="utf-8")
    calls = _stub_management(monkeypatch, "SUCCEEDED")

    response = _post_abandon(client, record)

    assert response.status_code == 409
    assert response.get_json()["error_type"] == "tracking_state_conflict"
    assert calls == []
    assert _still_there(tmp_path, record)


def test_abandon_fails_closed_when_the_current_operation_file_is_missing(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pointer whose operation file vanished proves nothing (ADR-0006)."""
    record, _request = _seed(tmp_path, mapped=False)
    record = _with_operation(tmp_path, record, state=TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN)
    config = _config(tmp_path)
    for operation_file in config.tracking_operations_dir.glob("*.json"):
        operation_file.unlink()
    calls = _stub_management(monkeypatch, "SUCCEEDED")

    response = _post_abandon(client, record)

    assert response.status_code == 409
    assert response.get_json()["error_type"] == "tracking_state_conflict"
    assert calls == []
    assert _still_there(tmp_path, record)


def test_abandon_fails_closed_on_an_unknown_operation_state(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    record, _request = _seed(tmp_path, mapped=False)
    record = _with_operation(tmp_path, record, state=TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN)
    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_plan_delete_service.load_tracking_operation",
        lambda *_a, **_k: types.SimpleNamespace(
            operation_id=record.current_operation_id,
            tracking_id=record.tracking_id,
            state="SOMETHING_NEW",
        ),
    )
    calls = _stub_management(monkeypatch, "SUCCEEDED")

    response = _post_abandon(client, record)

    assert response.status_code == 409
    assert response.get_json()["error_type"] == "tracking_state_conflict"
    assert calls == []
    assert _still_there(tmp_path, record)


# ---------------------------------------------------------------------------
# The confirmation goes stale when either binding changes
# ---------------------------------------------------------------------------


def test_abandon_rejects_a_stale_revision(tmp_path: Path, client: FlaskClient) -> None:
    record, _request = _seed(tmp_path, mapped=False)
    record = _with_operation(tmp_path, record, state=TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN)

    response = _post_abandon(client, record, expected_revision=record.revision + 1)

    assert response.status_code == 409
    assert response.get_json()["error_type"] == "tracking_revision_conflict"
    assert _still_there(tmp_path, record)


def test_abandon_rejects_a_changed_operation(tmp_path: Path, client: FlaskClient) -> None:
    record, _request = _seed(tmp_path, mapped=False)
    record = _with_operation(tmp_path, record, state=TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN)

    response = _post_abandon(client, record, expected_operation_id="op-that-is-not-current")

    assert response.status_code == 409
    assert response.get_json()["error_type"] == "tracking_state_conflict"
    assert _still_there(tmp_path, record)


def test_abandon_rechecks_the_operation_before_deleting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``PREPARED → IN_PROGRESS`` race loses: the stale confirmation is refused.

    The first read decides the abandon; the re-read right before the local delete
    sees a running write, so nothing is removed.
    """
    record, _request = _seed(tmp_path, mapped=False)
    record = _with_operation(tmp_path, record, state=TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN)
    config = _config(tmp_path)
    calls = {"count": 0}

    import apps.migu_orca_web.tracking_plan_delete_service as service

    real_loader = service.load_tracking_operation

    def racing_loader(config_arg, operation_id):
        calls["count"] += 1
        operation = real_loader(config_arg, operation_id)
        if calls["count"] >= 2:
            return replace(operation, state=TRACKING_OPERATION_STATE_IN_PROGRESS)
        return operation

    monkeypatch.setattr(service, "load_tracking_operation", racing_loader)

    with pytest.raises(Stage1Error) as excinfo:
        run_saved_tracking_plan_delete(
            config,
            payload=SavedTrackingPlanDeleteInput.model_validate(
                {
                    **_abandon_body(record),
                    "tracking_id": record.tracking_id,
                }
            ),
        )

    assert excinfo.value.error_type == "tracking_state_conflict"
    assert _still_there(tmp_path, record)


# ---------------------------------------------------------------------------
# Records without a current operation keep the historical status guard
# ---------------------------------------------------------------------------


def test_plain_delete_without_an_operation_keeps_the_status_guard(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    record, _request = _seed(tmp_path, mapped=False)
    config = _config(tmp_path)
    submitting = compare_and_swap_tracking_record(
        config,
        record.tracking_id,
        record.revision,
        replace(
            record,
            status=TRACKING_STATUS_SUBMITTING,
            current_operation_id=None,
            revision=record.revision + 1,
            updated_at="2026-09-08T00:00:00+00:00",
        ),
    )
    calls = _stub_management(monkeypatch, "SUCCEEDED")

    response = _post(client, submitting, delete_external=False)

    assert response.status_code == 409
    assert response.get_json()["error_type"] == "tracking_state_conflict"
    assert calls == []
    assert _still_there(tmp_path, record)


def test_settled_operation_still_allows_the_plain_delete(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue #96 semantics survive: a finished operation is history, not a lock."""
    record, _request = _seed(tmp_path, mapped=False)
    record = _with_operation(tmp_path, record, state=TRACKING_OPERATION_STATE_SUCCEEDED)
    calls = _stub_management(monkeypatch, "SUCCEEDED")

    response = _post(client, record, delete_external=False)

    assert response.status_code == 200
    assert response.get_json()["result"]["outcome"] == "DELETED"
    assert calls == []
    assert list_tracking_records(_config(tmp_path)).records == []


def test_abandon_never_requires_a_saved_connection(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The abandon is local-only, so it must not need any AB generation."""
    record, _request = _seed(tmp_path, mapped=False)
    record = _with_operation(tmp_path, record, state=TRACKING_OPERATION_STATE_RECOVERY_REQUIRED)
    calls = _stub_management(monkeypatch, "SUCCEEDED")
    body = _abandon_body(record)
    body.pop("connection_ref")
    body.pop("configuration_revision")

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/delete-plan", json=body
    )

    assert response.status_code == 200, response.get_json()
    assert calls == []
    assert list_tracking_records(_config(tmp_path)).records == []


def test_abandon_keeps_the_tracking_record_when_the_cas_loses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The local delete is a compare-and-swap: a losing CAS removes nothing.

    The repository raises ``tracking_revision_conflict`` when the record moved
    after the service's re-read, so the stale confirmation cannot half-apply.
    """
    record, _request = _seed(tmp_path, mapped=False)
    record = _with_operation(tmp_path, record, state=TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN)
    config = _config(tmp_path)

    def losing_cas(*_args: Any, **_kwargs: Any) -> Any:
        raise Stage1Error(
            "tracking_revision_conflict", "追番记录版本已变化，请刷新后重试", _STEP
        )

    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_plan_delete_service.delete_tracking_record", losing_cas
    )

    with pytest.raises(Stage1Error) as excinfo:
        run_saved_tracking_plan_delete(
            config,
            payload=SavedTrackingPlanDeleteInput.model_validate(
                {**_abandon_body(record), "tracking_id": record.tracking_id}
            ),
        )

    assert excinfo.value.error_type == "tracking_revision_conflict"
    assert load_tracking_record(config, record.tracking_id).revision == record.revision


def test_abandon_fails_closed_when_the_operation_belongs_to_another_record(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pointer to another record's operation proves nothing (ADR-0006).

    Cross-record pointers are not produced by the app, but a migrated or damaged
    store must not turn one into a delete decision, and the binding must never
    echo another record's operation id.
    """
    record, _request = _seed(tmp_path, mapped=False)
    config = _config(tmp_path)
    foreign_operation, _created = bind_tracking_operation(
        config,
        tracking_id="tracking-other",
        operation="SUBMIT",
        idempotency_key="foreign-operation-key",
        expected_revision=1,
        request_fingerprint="foreign-fingerprint",
    )
    pointed = compare_and_swap_tracking_record(
        config,
        record.tracking_id,
        record.revision,
        replace(
            record,
            current_operation_id=foreign_operation.operation_id,
            revision=record.revision + 1,
            updated_at="2026-09-08T00:00:00+00:00",
        ),
    )

    response = _post_abandon(client, pointed)

    assert response.status_code == 409
    assert response.get_json()["error_type"] == "tracking_state_conflict"
    assert load_tracking_record(config, record.tracking_id).revision == pointed.revision
