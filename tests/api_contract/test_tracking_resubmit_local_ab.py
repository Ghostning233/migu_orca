from __future__ import annotations

"""Issue #184 main chain: risk-confirmed single manual resubmission.

Real Flask, the real Auto Bangumi 3.1.18 password adapters, the real URL
decoder, the real bounded read and the real persistence all run; only the
outermost HTTP hop is a **localhost** Auto Bangumi stand-in (reused from the
#182/#183 confirmation chain).  Nothing here touches a real Auto Bangumi, and
every assertion is about the persisted local truth plus the exact external
requests that were made.
"""

from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient

from apps.base import create_app
from apps.migu_orca_web.schemas import TrackingResubmitPayload
from storage_engine.controllers.autobangumi_config_repository import (
    AutoBangumiConfigRepository,
    build_stored_autobangumi_config,
)
from storage_engine.controllers.operation_repository import (
    load_tracking_operation,
)
from storage_engine.controllers.tracking_repository import load_tracking_record
from tests.api_contract.test_tracking_confirmation_local_ab import (
    SUBMIT,
    LocalAb318,
    _cfg,
    _seed,
)
from tracking_engine.models.operation import (
    TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
    TRACKING_OPERATION_STATE_SUCCEEDED,
)
from tracking_engine.models.tracking import (
    TRACKING_AUDIT_ACTOR_USER,
    TRACKING_AUDIT_RESUBMIT_CONFIRMED,
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_RECOVERY_REQUIRED,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
)

RESUBMIT = "/api/v1/tracking/items/{tracking_id}/resubmit"

@pytest.fixture()
def ab() -> Any:
    server = LocalAb318()
    try:
        yield server
    finally:
        server.close()


def _pending_submission(
    client: FlaskClient,
    tmp_path: Path,
    ab: LocalAb318,
    *,
    visible_after_writes: int | None = None,
) -> dict[str, Any]:
    """Submit once against a readable instance that does not show the object yet.

    ``visible_after_writes`` models an eventually-visible Auto Bangumi: the write
    is accepted but the subscription only appears in a later list response, which
    is exactly the 结果待确认 situation the resubmit feature exists for.
    """
    ab.state.mode = "match"
    ab.state.visible_after_writes = visible_after_writes
    body, record = _seed(tmp_path, ab)
    response = client.post(SUBMIT.format(tracking_id=record.tracking_id), json=body)
    assert response.status_code == 200, response.get_json()
    result = response.get_json()["result"]
    assert result["outcome"] == TRACKING_STATUS_VERIFYING_EXTERNAL, result
    stored = load_tracking_record(_cfg(tmp_path), result["tracking_id"])
    assert stored.status == TRACKING_STATUS_VERIFYING_EXTERNAL
    writes, _reads = ab.state.snapshot()
    assert writes == 1
    return {
        "tracking_id": result["tracking_id"],
        "revision": stored.revision,
        "submit_body": body,
    }


def _offer(client: FlaskClient, pending: dict[str, Any]) -> dict[str, Any]:
    response = client.post(
        RESUBMIT.format(tracking_id=pending["tracking_id"]),
        json={
            "expected_revision": pending["revision"],
            "confirm": False,
            "storage_dir": "storage",
        },
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()["result"]


def _confirm(client: FlaskClient, pending: dict[str, Any], offer: dict[str, Any], **overrides: Any) -> Any:
    body = {
        "expected_revision": offer["binding"]["expected_revision"],
        "confirm": True,
        "previous_operation_id": offer["binding"]["previous_operation_id"],
        "connection_ref": offer["binding"]["connection_ref"],
        "storage_dir": "storage",
    }
    body.update(overrides)
    return client.post(RESUBMIT.format(tracking_id=pending["tracking_id"]), json=body)


def test_offer_is_read_only_and_the_confirmed_resubmit_writes_exactly_once(
    tmp_path: Path, client: FlaskClient, ab: LocalAb318
) -> None:
    """AC 1/2/3/5: check → risk offer → one confirmed new operation + one write."""
    pending = _pending_submission(client, tmp_path, ab, visible_after_writes=2)
    reads_before = ab.state.snapshot()[1]

    offer = _offer(client, pending)

    assert offer["check_status"] == "UNRESOLVED"
    assert offer["requires_risk_confirmation"] is True
    assert offer["verification_reason"] == "NOT_FOUND"
    assert offer["binding"]["previous_operation_id"] == pending_operation_id(tmp_path, pending)
    assert offer["binding"]["connection_ref"] == pending["submit_body"]["connection_ref"]
    # The read-only phase performed a read and zero writes.
    writes, reads = ab.state.snapshot()
    assert writes == 1
    assert reads > reads_before
    offered_record = load_tracking_record(_cfg(tmp_path), pending["tracking_id"])
    assert offered_record.status == TRACKING_STATUS_RECOVERY_REQUIRED
    assert offered_record.current_operation_id == offer["binding"]["previous_operation_id"]

    confirmed = _confirm(client, pending, offer)

    assert confirmed.status_code == 200, confirmed.get_json()
    result = confirmed.get_json()["result"]
    assert result["confirm"] is True
    assert result["outcome"] == TRACKING_STATUS_ACTIVE
    assert result["previous_operation_id"] == offer["binding"]["previous_operation_id"]
    assert result["operation_id"] != offer["binding"]["previous_operation_id"]

    # Exactly one new external write for the whole confirmation.
    assert ab.state.snapshot()[0] == 2

    new_operation = load_tracking_operation(_cfg(tmp_path), result["operation_id"])
    assert new_operation.previous_operation_id == offer["binding"]["previous_operation_id"]
    assert new_operation.state == TRACKING_OPERATION_STATE_SUCCEEDED
    # The pending operation and its own evidence survive untouched.
    original = load_tracking_operation(_cfg(tmp_path), offer["binding"]["previous_operation_id"])
    assert original.state == TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN
    assert original.previous_operation_id is None

    final = load_tracking_record(_cfg(tmp_path), pending["tracking_id"])
    assert final.status == TRACKING_STATUS_ACTIVE
    assert final.external_mapping["subscription_id"] == "42"
    assert any(
        event["action"] == TRACKING_AUDIT_RESUBMIT_CONFIRMED
        and event["actor"] == TRACKING_AUDIT_ACTOR_USER
        for event in final.audit_events
    )


def _operation_file(tmp_path: Path, operation_id: str) -> Path:
    return _cfg(tmp_path).tracking_operations_dir / f"{operation_id}.json"


def pending_operation_id(tmp_path: Path, pending: dict[str, Any]) -> str:
    record = load_tracking_record(_cfg(tmp_path), pending["tracking_id"])
    assert record.current_operation_id is not None
    return record.current_operation_id


def test_the_offer_converges_with_zero_new_writes_once_the_object_appears(
    tmp_path: Path, client: FlaskClient, ab: LocalAb318
) -> None:
    """AC 2: a proven subscription converges the record without any external write."""
    pending = _pending_submission(client, tmp_path, ab, visible_after_writes=2)
    # The subscription becomes visible; the read-only phase must prove it.
    ab.state.visible_after_writes = 1

    offer = _offer(client, pending)

    assert offer["check_status"] == "CONFIRMED"
    assert offer["outcome"] == TRACKING_STATUS_ACTIVE
    assert offer["requires_risk_confirmation"] is False
    assert offer["binding"] is None
    assert ab.state.snapshot()[0] == 1, "confirming an existing object must not write"
    final = load_tracking_record(_cfg(tmp_path), pending["tracking_id"])
    assert final.status == TRACKING_STATUS_ACTIVE


def test_cancelling_after_the_offer_creates_no_operation_and_no_write(
    tmp_path: Path, client: FlaskClient, ab: LocalAb318
) -> None:
    """AC 3: the offer alone never resubmits; only a further confirmation does."""
    pending = _pending_submission(client, tmp_path, ab, visible_after_writes=2)
    offer = _offer(client, pending)
    assert offer["requires_risk_confirmation"] is True

    # The user cancels: no second request is sent, so nothing new is created.
    record = load_tracking_record(_cfg(tmp_path), pending["tracking_id"])
    assert record.current_operation_id == offer["binding"]["previous_operation_id"]
    assert record.external_mapping is None
    assert ab.state.snapshot()[0] == 1
    assert not any(
        event["action"] == TRACKING_AUDIT_RESUBMIT_CONFIRMED for event in record.audit_events
    )


def test_a_replayed_confirmation_and_a_stale_offer_never_write_twice(
    tmp_path: Path, client: FlaskClient, ab: LocalAb318
) -> None:
    """AC 4/5: same confirmation replays one operation; stale input is refused."""
    pending = _pending_submission(client, tmp_path, ab, visible_after_writes=2)
    offer = _offer(client, pending)

    first = _confirm(client, pending, offer).get_json()["result"]
    assert ab.state.snapshot()[0] == 2
    confirmed_path = _operation_file(tmp_path, first["operation_id"])
    confirmed_bytes = confirmed_path.read_bytes()
    original_bytes = _operation_file(tmp_path, offer["binding"]["previous_operation_id"]).read_bytes()

    # A restarted process (a fresh app + client reading the same storage) replays
    # the identical confirmation onto the very same operation: no third write and
    # neither operation file is rewritten.
    restarted = create_app("testing").test_client()
    replay = _confirm(restarted, pending, offer)
    assert replay.status_code == 200
    replayed = replay.get_json()["result"]
    assert replayed["operation_id"] == first["operation_id"]
    assert replayed["outcome"] == TRACKING_STATUS_ACTIVE
    assert ab.state.snapshot()[0] == 2
    assert confirmed_path.read_bytes() == confirmed_bytes
    assert _operation_file(tmp_path, offer["binding"]["previous_operation_id"]).read_bytes() == original_bytes

    # A stale revision is refused before anything is read or written.
    stale = client.post(
        RESUBMIT.format(tracking_id=pending["tracking_id"]),
        json={
            "expected_revision": offer["binding"]["expected_revision"] + 5,
            "confirm": True,
            "previous_operation_id": offer["binding"]["previous_operation_id"],
            "connection_ref": offer["binding"]["connection_ref"],
            "storage_dir": "storage",
        },
    )
    assert stale.status_code == 409
    assert stale.get_json()["error_type"] == "tracking_revision_conflict"
    assert ab.state.snapshot()[0] == 2


def test_a_replaced_connection_is_never_rebound_or_written_through(
    tmp_path: Path, client: FlaskClient, ab: LocalAb318
) -> None:
    """AC 4/6: a replaced saved generation refuses the confirmation and writes nothing."""
    pending = _pending_submission(client, tmp_path, ab, visible_after_writes=2)
    offer = _offer(client, pending)

    # Replace the saved connection generation the pending operation is bound to.
    repository = AutoBangumiConfigRepository(tmp_path / "config")
    current = repository.load()
    repository.save(
        build_stored_autobangumi_config(
            {
                "auth_mode": "password",
                "base_url": ab.base_url,
                "username": "operator",
                "password": "another-password",
            }
        ),
        expected_configuration_revision=current.configuration_revision,
    )

    response = _confirm(client, pending, offer)

    assert response.status_code == 200, response.get_json()
    result = response.get_json()["result"]
    assert result["check_status"] == "BLOCKED"
    assert result["blocked_reason"] == "CONNECTION_CHANGED"
    assert ab.state.snapshot()[0] == 1, "no write may reach any instance"
    record = load_tracking_record(_cfg(tmp_path), pending["tracking_id"])
    assert record.current_operation_id == offer["binding"]["previous_operation_id"]
    assert record.external_mapping is None


def test_an_unsupported_version_blocks_the_resubmit_before_any_write(
    tmp_path: Path, client: FlaskClient, ab: LocalAb318
) -> None:
    """AC 6: a proven version mismatch gives a reason instead of a blind write."""
    pending = _pending_submission(client, tmp_path, ab, visible_after_writes=2)
    # The instance stops reporting the verified version after the pending submit.
    ab.state.version = "3.0.0"

    offer = _offer(client, pending)

    assert offer["check_status"] == "BLOCKED"
    assert offer["blocked_reason"] == "VERSION"
    assert offer["requires_risk_confirmation"] is False
    assert ab.state.snapshot()[0] == 1


def test_the_resubmit_payload_is_strict_and_binding_free_while_checking() -> None:
    """AC 3/4: the read-only phase cannot carry a binding; the write needs one."""
    TrackingResubmitPayload(
        tracking_id="trk_x", expected_revision=1, confirm=False, storage_dir="storage"
    )
    with pytest.raises(ValueError):
        TrackingResubmitPayload(
            tracking_id="trk_x",
            expected_revision=1,
            confirm=False,
            previous_operation_id="op_" + "0" * 32,
        )
    with pytest.raises(ValueError):
        TrackingResubmitPayload(tracking_id="trk_x", expected_revision=1, confirm=True)
    with pytest.raises(ValueError):
        TrackingResubmitPayload(
            tracking_id="trk_x", expected_revision=1, confirm=True,
            previous_operation_id="https://secret.invalid",
            connection_ref="11111111-1111-4111-8111-111111111111",
        )
    with pytest.raises(ValueError):
        TrackingResubmitPayload(
            tracking_id="trk_x", expected_revision=1, confirm=True,
            previous_operation_id="op_" + "0" * 32, connection_ref="not-a-uuid",
        )


def test_no_batch_force_resubmit_path_is_added_for_pending_records(
    tmp_path: Path, client: FlaskClient, ab: LocalAb318
) -> None:
    """AC 7: pending records are resubmitted one by one, never through a batch.

    The explicit batch keeps its own single-item revalidation, so it refuses a
    结果待确认 record with a stable pre-boundary code and writes nothing.
    """
    pending = _pending_submission(client, tmp_path, ab, visible_after_writes=2)
    body = pending["submit_body"]

    response = client.post(
        "/api/v1/tracking/batch-submit",
        json={
            "items": [{
                "tracking_id": pending["tracking_id"],
                "expected_revision": pending["revision"],
                "idempotency_key": "batch-resubmit-attempt-1",
            }],
            "confirm": True,
            "connection_ref": body["connection_ref"],
            "configuration_revision": body["configuration_revision"],
            "storage_dir": "storage",
        },
    )

    assert response.status_code == 200, response.get_json()
    entry = response.get_json()["result"]["items"][0]
    assert entry["ok"] is False
    assert entry["error_type"] == "tracking_state_conflict"
    assert entry["result"] is None
    assert ab.state.snapshot()[0] == 1, "a batch must not force a pending resubmit"
