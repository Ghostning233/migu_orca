"""Resource-level batch exclusion at the HTTP boundary (issue #248).

#223 refused every single tracking write while a batch ran.  #248 narrows the
early (``before_request``) refusal to the resources the batch occupies:

* an external write on a record the batch owns -> 409 ``connection_in_use``;
* a pure-local write (``revalidate``/``check``) -> never refused;
* an unrelated record or another storage profile -> not refused;
* a request that cannot be parsed/invalid profile -> answered by the view (400),
  never turned into a 409;
* a batch that publishes no scope keeps #223's fail-safe blanket refusal.

The repository half (queueing, connection-level wait budget) is covered by
``src/storage_engine/controllers/tracking_batch_scope_test.py``.
"""
from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

from flask.testing import FlaskClient

from storage_engine.controllers.operation_repository import (
    bind_tracking_operation,
    compare_and_swap_tracking_operation,
)
from storage_engine.controllers.storage_config import StorageConfig, load_storage_config
from storage_engine.controllers.tracking_repository import (
    compare_and_swap_tracking_record,
    ensure_tracking_record,
    load_tracking_record,
    tracking_batch_lease,
)
from tracking_engine.models.operation import transition_tracking_operation
from tracking_engine.models.tracking import (
    TRACKING_STATUS_ACTIVE,
    TrackingRecord,
    create_external_tracking_record,
)

REF = "11111111-1111-4111-8111-111111111111"


def _config(tmp_path: Path) -> StorageConfig:
    return load_storage_config(tmp_path / "storage")


def _profile(tmp_path: Path) -> str:
    return str((tmp_path / "storage").resolve())


def _seed(tmp_path: Path, index: int) -> TrackingRecord:
    config = _config(tmp_path)
    record = create_external_tracking_record(
        adapter="legacy_3_1",
        object_kind="subscription",
        external_id=f"sub-{index}",
        subscription_id=f"sub-{index}",
        title=f"Show {index}",
        season=1,
        connection_ref=REF,
    )
    seeded, _created = ensure_tracking_record(
        config, replace(record, status=TRACKING_STATUS_ACTIVE)
    )
    return seeded


class _HeldBatch:
    """Hold a batch lease with an explicit resource scope for one test."""

    def __init__(self, *, tracking_ids: set[str], storage_dir: str | None) -> None:
        self._tracking_ids = tracking_ids
        self._storage_dir = storage_dir
        self.entered = threading.Event()
        self.release = threading.Event()
        self.thread = threading.Thread(target=self._run)

    def _run(self) -> None:
        with tracking_batch_lease(
            batch_key="contract-batch",
            tracking_ids=self._tracking_ids,
            connection_ref=REF,
            storage_dir=self._storage_dir,
        ):
            self.entered.set()
            assert self.release.wait(timeout=10)

    def __enter__(self) -> _HeldBatch:
        self.thread.start()
        assert self.entered.wait(timeout=10)
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.release.set()
        self.thread.join(timeout=10)


def _delete_plan(client: FlaskClient, record: TrackingRecord, **overrides: Any) -> Any:
    body = {
        "confirm": True,
        "idempotency_key": f"single-delete-{record.tracking_id}",
        "storage_dir": "storage",
        **overrides,
    }
    return client.post(f"/api/v1/tracking/items/{record.tracking_id}/delete-plan", json=body)


def test_external_write_on_an_owned_record_is_refused(
    tmp_path: Path, client: FlaskClient
) -> None:
    owned = _seed(tmp_path, 1)
    with _HeldBatch(tracking_ids={owned.tracking_id}, storage_dir=_profile(tmp_path)):
        response = _delete_plan(client, owned)

    assert response.status_code == 409, response.get_json()
    assert response.get_json()["error_type"] == "connection_in_use"
    # Refused before any persistence: the record is untouched.
    load_tracking_record(_config(tmp_path), owned.tracking_id)


def test_pure_local_write_on_an_owned_record_is_not_refused(
    tmp_path: Path, client: FlaskClient
) -> None:
    owned = _seed(tmp_path, 1)
    with _HeldBatch(tracking_ids={owned.tracking_id}, storage_dir=_profile(tmp_path)):
        revalidate = client.post(
            f"/api/v1/tracking/items/{owned.tracking_id}/revalidate",
            json={"expected_revision": owned.revision, "storage_dir": "storage"},
        )
        check = client.post(
            f"/api/v1/tracking/items/{owned.tracking_id}/check",
            json={"expected_revision": owned.revision, "storage_dir": "storage"},
        )

    # Neither request may be refused by the batch guard; any remaining 409 is a
    # business state conflict (e.g. the record is not revalidatable while ACTIVE).
    for response in (revalidate, check):
        assert response.get_json().get("error_type") != "connection_in_use", response.get_json()


def test_external_write_on_an_unowned_record_proceeds(
    tmp_path: Path, client: FlaskClient
) -> None:
    owned = _seed(tmp_path, 1)
    other = _seed(tmp_path, 2)
    with _HeldBatch(tracking_ids={owned.tracking_id}, storage_dir=_profile(tmp_path)):
        response = _delete_plan(client, other)

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["result"]["outcome"] == "DELETED"


def test_another_profile_is_not_refused(tmp_path: Path, client: FlaskClient) -> None:
    owned = _seed(tmp_path, 1)
    with _HeldBatch(tracking_ids={owned.tracking_id}, storage_dir=_profile(tmp_path)):
        response = _delete_plan(client, owned, storage_dir="other")

    assert response.status_code != 409, response.get_json()


def test_malformed_body_is_a_400_not_a_409(tmp_path: Path, client: FlaskClient) -> None:
    owned = _seed(tmp_path, 1)
    with _HeldBatch(tracking_ids={owned.tracking_id}, storage_dir=_profile(tmp_path)):
        response = client.post(
            f"/api/v1/tracking/items/{owned.tracking_id}/submit",
            data="{not json",
            content_type="application/json",
        )

    assert response.status_code == 400, response.get_json()
    assert response.get_json()["error_type"] == "data_validation_errors"


def test_invalid_profile_is_a_400_not_a_409(tmp_path: Path, client: FlaskClient) -> None:
    owned = _seed(tmp_path, 1)
    with _HeldBatch(tracking_ids={owned.tracking_id}, storage_dir=_profile(tmp_path)):
        response = _delete_plan(client, owned, storage_dir="/absolute/path")

    assert response.status_code == 400, response.get_json()
    assert response.get_json()["error_type"] == "invalid_storage_dir"


def test_unscoped_batch_keeps_the_fail_safe_exclusion(
    tmp_path: Path, client: FlaskClient
) -> None:
    record = _seed(tmp_path, 1)
    with _HeldBatch(tracking_ids=set(), storage_dir=None):
        response = _delete_plan(client, record)

    assert response.status_code == 409, response.get_json()
    assert response.get_json()["error_type"] == "connection_in_use"


def test_an_unresolved_single_operation_keeps_its_protection_after_the_batch(
    tmp_path: Path, client: FlaskClient
) -> None:
    """#248: releasing the batch lease does not unlock an unresolved operation."""
    record = _seed(tmp_path, 1)
    config = _config(tmp_path)
    operation, _created = bind_tracking_operation(
        config,
        tracking_id=record.tracking_id,
        operation="SUBMIT",
        idempotency_key="unresolved-before-batch",
        expected_revision=record.revision,
        request_fingerprint="fingerprint",
    )
    operation = compare_and_swap_tracking_operation(
        config,
        operation.operation_id,
        operation.state,
        transition_tracking_operation(operation, state="IN_PROGRESS"),
    )
    compare_and_swap_tracking_record(
        config,
        record.tracking_id,
        record.revision,
        replace(record, revision=record.revision + 1, current_operation_id=operation.operation_id),
    )

    # A batch that owns another record runs and releases; the unresolved record
    # must still refuse an external single write.
    other = _seed(tmp_path, 2)
    with _HeldBatch(tracking_ids={other.tracking_id}, storage_dir=_profile(tmp_path)):
        pass

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/delete-plan",
        json={
            "confirm": True,
            "delete_external": True,
            "idempotency_key": "delete-after-batch",
            "connection_ref": REF,
            "configuration_revision": 1,
            "storage_dir": "storage",
        },
    )

    assert response.status_code == 409, response.get_json()
    assert response.get_json()["error_type"] in {
        "tracking_management_state_conflict",
        "tracking_state_conflict",
    }
