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

import pytest
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
    tracking_batch_scope,
)
from tracking_engine.models.operation import transition_tracking_operation
from tracking_engine.models.tracking import (
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_NEEDS_RECONFIRM,
    TrackingRecord,
    create_external_tracking_record,
)

REF = "11111111-1111-4111-8111-111111111111"


def _config(tmp_path: Path) -> StorageConfig:
    return load_storage_config(tmp_path / "storage")


def _profile(tmp_path: Path) -> str:
    return str((tmp_path / "storage").resolve())


def _seed(
    tmp_path: Path,
    index: int,
    *,
    status: str = TRACKING_STATUS_ACTIVE,
) -> TrackingRecord:
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
    seeded, _created = ensure_tracking_record(config, replace(record, status=status))
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
    # Refused before any persistence: no intent and the record is untouched.
    store = _config(tmp_path)
    assert list(store.tracking_operations_dir.glob("*.json")) == []
    assert load_tracking_record(store, owned.tracking_id).revision == owned.revision


def test_pure_local_write_on_an_owned_record_is_not_refused(
    tmp_path: Path, client: FlaskClient
) -> None:
    owned = _seed(tmp_path, 1, status=TRACKING_STATUS_NEEDS_RECONFIRM)
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
    assert revalidate.status_code == 200, revalidate.get_json()
    assert check.status_code in {200, 409}, check.get_json()
    for response in (revalidate, check):
        assert response.status_code != 500
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

    # The record does not exist in the other profile: the view answers 404, not
    # a batch refusal.
    assert response.status_code == 404, response.get_json()
    assert response.get_json()["error_type"] == "tracking_not_found"


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
    """A caller that does not publish resources keeps #223's blanket refusal.

    All three real batch routes publish their scope (see the route-level tests
    above); this is the defensive fallback for any other caller.
    """
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


def test_the_body_profile_wins_over_the_query(tmp_path: Path, client: FlaskClient) -> None:
    """I3 (#248): the guard must resolve the profile exactly like the view."""
    owned = _seed(tmp_path, 1)
    with _HeldBatch(tracking_ids={owned.tracking_id}, storage_dir=_profile(tmp_path)):
        # The body points at another (empty) profile, so the record there is not
        # the one the batch owns; a query string must not change that.
        response = client.post(
            f"/api/v1/tracking/items/{owned.tracking_id}/delete-plan?storage_dir=storage",
            json={
                "confirm": True,
                "idempotency_key": "body-profile-wins",
                "storage_dir": "other",
            },
        )

    assert response.status_code == 404, response.get_json()
    assert response.get_json()["error_type"] == "tracking_not_found"


def test_a_connection_level_change_is_refused_while_a_batch_pins_it(
    tmp_path: Path, client: FlaskClient
) -> None:
    """I1 (#248): replacing the saved connection changes the batch generation."""
    with _HeldBatch(tracking_ids={_seed(tmp_path, 1).tracking_id}, storage_dir=_profile(tmp_path)):
        response = client.put("/api/v1/settings/autobangumi", json={})

    assert response.status_code == 409, response.get_json()
    assert response.get_json()["error_type"] == "connection_in_use"


def test_a_local_only_batch_does_not_block_a_connection_change(
    tmp_path: Path, client: FlaskClient
) -> None:
    record = _seed(tmp_path, 1)
    with tracking_batch_lease(
        batch_key="local-only-batch",
        tracking_ids={record.tracking_id},
        storage_dir=_profile(tmp_path),
    ):
        response = client.put("/api/v1/settings/autobangumi", json={})

    assert response.status_code != 409, response.get_json()


def test_the_delete_route_publishes_its_occupied_scope(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B2 (#248): the batch service must run under the route's scoped lease."""
    import apps.migu_orca_web.routes_tracking as routes

    record = _seed(tmp_path, 1)
    captured: dict[str, Any] = {}

    def spy(config: Any, *, payload: Any, delete_external: bool) -> dict[str, Any]:
        captured["scope"] = tracking_batch_scope()
        captured["delete_external"] = delete_external
        return {
            "batch_key": payload.idempotency_key,
            "kind": "LOCAL_ONLY",
            "state": "COMPLETED",
            "items": [],
            "summary": {
                "total": 0, "deleted": 0, "external_deleted": 0,
                "skipped": 0, "failed": 0, "unknown": 0,
            },
        }

    monkeypatch.setattr(routes, "run_saved_tracking_batch_delete", spy)
    response = client.post(
        "/api/v1/tracking/batch-delete-plan",
        json={
            "confirm": True,
            "idempotency_key": "scoped-route-batch",
            "items": [{"tracking_id": record.tracking_id, "expected_revision": record.revision}],
            "storage_dir": "storage",
        },
    )

    assert response.status_code == 200, response.get_json()
    scope = captured["scope"]
    assert scope is not None
    assert scope.tracking_ids == frozenset({record.tracking_id})
    assert scope.storage_dir == _profile(tmp_path)
    assert scope.connection_ref is None


def test_read_only_verifications_do_not_declare_the_batch_exclusion() -> None:
    """I5 (#248): the published 409 must be reachable after the narrowing."""
    import json
    from pathlib import Path as _Path

    doc = json.loads(
        (_Path(__file__).resolve().parents[2] / "docs/api/openapi.json").read_text(encoding="utf-8")
    )
    read_only = (
        "/api/v1/tracking/items/{tracking_id}/check",
        "/api/v1/tracking/items/{tracking_id}/revalidate",
        "/api/v1/tracking/items/{tracking_id}/recover",
    )
    external = (
        "/api/v1/tracking/items/{tracking_id}/submit",
        "/api/v1/tracking/items/{tracking_id}/retry",
        "/api/v1/tracking/items/{tracking_id}/delete-plan",
        "/api/v1/tracking/items/{tracking_id}/resubmit",
        "/api/v1/tracking/items/{tracking_id}/modify",
        "/api/v1/tracking/items/{tracking_id}/set-enabled",
        "/api/v1/tracking/items/{tracking_id}/refresh",
    )
    for path in read_only:
        description = doc["paths"][path]["post"]["responses"]["409"]["description"]
        assert "connection_in_use" not in description, path
    for path in external:
        description = doc["paths"][path]["post"]["responses"]["409"]["description"]
        assert "connection_in_use" in description, path


def test_the_submit_route_publishes_its_occupied_scope(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B2 (#248): batch-submit must run under the route's scoped lease too."""
    import apps.migu_orca_web.routes_tracking as routes

    record = _seed(tmp_path, 1, status=TRACKING_STATUS_NEEDS_RECONFIRM)
    captured: dict[str, Any] = {}

    def spy(config: Any, *, payload: Any) -> dict[str, Any]:
        captured["scope"] = tracking_batch_scope()
        return {
            "items": [],
            "summary": {
                "total": 0, "succeeded": 0, "failed": 0, "unknown": 0, "blocked": 0,
            },
        }

    monkeypatch.setattr(routes, "run_saved_tracking_batch_submit", spy)
    response = client.post(
        "/api/v1/tracking/batch-submit",
        json={
            "confirm": True,
            "connection_ref": REF,
            "configuration_revision": 1,
            "storage_dir": "storage",
            "items": [{
                "tracking_id": record.tracking_id,
                "expected_revision": record.revision,
                "idempotency_key": "route-scoped-submit",
            }],
        },
    )

    assert response.status_code == 200, response.get_json()
    scope = captured["scope"]
    assert scope is not None
    assert scope.tracking_ids == frozenset({record.tracking_id})
    assert scope.storage_dir == _profile(tmp_path)
    assert scope.connection_ref == REF


@pytest.mark.parametrize(
    "suffix",
    ["submit", "retry", "delete-plan", "resubmit", "modify", "set-enabled", "refresh"],
)
def test_every_external_write_route_is_refused_on_an_owned_record(
    tmp_path: Path, client: FlaskClient, suffix: str
) -> None:
    owned = _seed(tmp_path, 1)
    with _HeldBatch(tracking_ids={owned.tracking_id}, storage_dir=_profile(tmp_path)):
        response = client.post(
            f"/api/v1/tracking/items/{owned.tracking_id}/{suffix}",
            json={"confirm": True, "storage_dir": "storage"},
        )

    assert response.status_code == 409, (suffix, response.get_json())
    assert response.get_json()["error_type"] == "connection_in_use"
    assert response.get_json()["error_data"]["failed_step"] == "tracking_batch_exclusion"


@pytest.mark.parametrize("suffix", ["check", "revalidate", "recover"])
def test_read_only_routes_are_never_refused_by_the_batch(
    tmp_path: Path, client: FlaskClient, suffix: str
) -> None:
    owned = _seed(tmp_path, 1)
    with _HeldBatch(tracking_ids={owned.tracking_id}, storage_dir=_profile(tmp_path)):
        response = client.post(
            f"/api/v1/tracking/items/{owned.tracking_id}/{suffix}",
            json={"expected_revision": owned.revision, "action": "VERIFY_EXTERNAL", "storage_dir": "storage"},
        )

    assert response.status_code != 500, (suffix, response.get_json())
    assert response.get_json().get("error_type") != "connection_in_use", (suffix, response.get_json())
