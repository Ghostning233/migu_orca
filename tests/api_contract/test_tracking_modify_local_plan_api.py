from __future__ import annotations

"""Issue #202: the modify route accepts and passes through ``local_plan`` again.

``local_plan`` (issue #91) is the local plan the server raises **after** a
SUBSCRIPTION modify was confirmed by an external read-back.  The field survived
in the frontend and in the coordinator but was dropped from the HTTP validator
(``TrackingModifyPayload`` is ``extra="forbid"``), so every real browser modify
answered 400 while the mocked browser test kept passing.

These tests run the real Flask route, the real saved-connection lease, the real
coordinator and the real persistence; only the outermost Auto Bangumi client is
a fake (no HTTP, no real instance).  Assertions are about the persisted local
truth, the exact upstream write body, and the stable rejection of an invalid
scope/plan combination.
"""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient

from ab_engine.models.management import (
    AutoBangumiCapabilities,
    ExternalRss,
    ExternalSubscription,
)
from apps.migu_orca_web.save_confirm_service import compute_request_fingerprint
from storage_engine.controllers.autobangumi_config_repository import (
    AutoBangumiConfigRepository,
    build_stored_autobangumi_config,
)
from storage_engine.controllers.operation_repository import load_tracking_operation
from storage_engine.controllers.request_repository import (
    load_request_snapshot,
    save_request_snapshot,
)
from storage_engine.controllers.storage_config import load_storage_config
from storage_engine.controllers.tracking_repository import (
    ensure_tracking_record,
    load_tracking_record,
)
from tracking_engine.models.tracking import (
    create_external_tracking_record,
    tracking_id_for_request,
)

MODIFY = "/api/v1/tracking/items/{tracking_id}/modify"


class FakeAbClient:
    """The fixed 3.1.18 management surface with an in-memory read-back."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.fail_write = False
        self.sub = ExternalSubscription("sub-1", "Old", 1, "Group")
        self.rss = ExternalRss("rss-1", "Feed", "https://rss.invalid", enabled=True)
        self.capabilities = AutoBangumiCapabilities(
            probe_status="VERIFIED", version="3.1.18", adapter="legacy_3_1",
            subscription_list="SUPPORTED", subscription_detail="SUPPORTED",
            subscription_modify="SUPPORTED", subscription_enable="SUPPORTED",
            subscription_disable="SUPPORTED", subscription_delete="SUPPORTED",
            rss_list="SUPPORTED", rss_modify="SUPPORTED", rss_enable="SUPPORTED",
            rss_disable="SUPPORTED", rss_delete="SUPPORTED", rss_refresh="SUPPORTED",
        )

    def read_snapshot(self, *, deadline: float | None = None):
        return self.capabilities, [self.sub], [self.rss]

    def update_subscription(self, ident: str, payload: Any):
        self.calls.append(("update_subscription", ident, dict(payload)))
        if self.fail_write:
            raise TimeoutError("offline")
        # The read-back reflects exactly what the write applied.
        self.sub = ExternalSubscription(
            ident, payload["official_title"], payload["season"], payload["group_name"]
        )
        return {"status_code": 200}


def _seed(tmp_path: Path):
    """One saved connection generation + a mapped record owning a local plan."""
    saved = AutoBangumiConfigRepository(tmp_path / "config").save(
        build_stored_autobangumi_config({
            "auth_mode": "password", "base_url": "http://ab.invalid",
            "username": "operator", "password": "secret-password",
        }),
        expected_configuration_revision=0,
    )
    config = load_storage_config(tmp_path / "storage")
    ref = str(saved.connection_ref)
    snapshot = {
        "request_id": "req-local",
        "status": "ACCEPTED",
        "input": {"raw_title": "芙莉莲"},
        "source_info": {"matched_bangumi": {"title": "Old", "season": 1, "aliases": []},
                        "rss_sources": []},
        "confirmable_config": {
            "selected_subtitle_group": "Group",
            "filter_rule": {"must_contain": "", "must_not_contain": "",
                            "use_regex": False, "case_sensitive": False},
            "expected_folder_name": "Old",
            "warnings": [],
        },
        "ab_submit_result": None,
        "created_at": "2026-09-01T00:00:00+00:00",
        "updated_at": "2026-09-01T00:00:00+00:00",
    }
    save_request_snapshot(config, snapshot)
    record = replace(
        create_external_tracking_record(
            adapter="legacy_3_1", object_kind="subscription", external_id="sub-1",
            subscription_id="sub-1", rss_ids=("rss-1",), title="Old", season=1,
            subtitle_group="Group", connection_ref=ref,
        ),
        request_id="req-local",
        origin="SAVE_CONFIRM",
        tracking_id=tracking_id_for_request("req-local"),
    )
    stored, _created = ensure_tracking_record(config, record)
    assert stored.external_mapping is not None
    assert stored.external_mapping["schema_version"] == 2
    return saved, config, stored, snapshot


def _fake_client(monkeypatch: pytest.MonkeyPatch) -> FakeAbClient:
    client = FakeAbClient()
    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_saved_management_service.create_management_client",
        lambda *_args, **_kwargs: client,
    )
    return client


def _body(saved: Any, record: Any, **overrides: Any) -> dict[str, Any]:
    return {
        "target_scope": "SUBSCRIPTION",
        "expected_revision": record.revision,
        "idempotency_key": "modify-key-1",
        "confirm": True,
        "connection_ref": str(saved.connection_ref),
        "configuration_revision": saved.configuration_revision,
        "storage_dir": "storage",
        "patch": {"title": "Changed"},
        **overrides,
    }


def _post(client: FlaskClient, record: Any, body: dict[str, Any]):
    return client.post(MODIFY.format(tracking_id=record.tracking_id), json=body)


def test_confirmed_modify_raises_the_local_plan_over_http(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC 1: the real route accepts ``local_plan`` and persists the raise."""
    saved, config, record, _snapshot = _seed(tmp_path)
    ab = _fake_client(monkeypatch)

    response = _post(client, record, _body(saved, record, local_plan={
        "filter_rule": {"must_contain": "1080p"}, "expected_folder_name": "New",
    }))

    payload = response.get_json()
    assert response.status_code == 200, payload
    assert payload["result"]["management_status"] == "SUCCEEDED", payload

    # The local plan was actually persisted, not merely acknowledged.
    stored_plan = load_request_snapshot(config, "req-local")["confirmable_config"]
    assert stored_plan["filter_rule"]["must_contain"] == "1080p"
    # Merge, not replace: the untouched rule fields stay as they were.
    assert stored_plan["filter_rule"]["must_not_contain"] == ""
    assert stored_plan["filter_rule"]["use_regex"] is False
    assert stored_plan["expected_folder_name"] == "New"
    # The fingerprint follows the raised plan so the next review does not
    # misread the confirmation as a plan change.
    stored_record = load_tracking_record(config, record.tracking_id)
    assert stored_record.request_fingerprint == compute_request_fingerprint(
        load_request_snapshot(config, "req-local")
    )
    # The local plan never leaks into the external write body: only ``patch``
    # describes the external object.
    (call,) = ab.calls
    assert call[0] == "update_subscription"
    assert call[2]["official_title"] == "Changed"
    assert "save_path" not in call[2]
    assert "filter" not in call[2]


def test_local_plan_is_independent_from_the_patch_binding(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC 3: ``local_plan`` does not change the external action binding."""
    saved, config, record, _snapshot = _seed(tmp_path)
    _fake_client(monkeypatch)

    with_plan = _post(
        client, record, _body(saved, record, local_plan={"expected_folder_name": "New"})
    )
    assert with_plan.status_code == 200, with_plan.get_json()
    assert with_plan.get_json()["result"]["management_status"] == "SUCCEEDED"
    first_id = load_tracking_record(config, record.tracking_id).current_operation_id
    assert first_id

    # A second modify with the same patch and no local plan binds the same
    # action fingerprint, so ``local_plan`` is not part of the external binding.
    current = load_tracking_record(config, record.tracking_id)
    promoted = current.request_fingerprint
    without_plan = _post(
        client, current,
        _body(saved, current, idempotency_key="modify-key-2", local_plan=None),
    )
    assert without_plan.status_code == 200, without_plan.get_json()
    assert without_plan.get_json()["result"]["management_status"] == "SUCCEEDED"
    after = load_tracking_record(config, record.tracking_id)
    second_id = after.current_operation_id
    assert second_id and second_id != first_id
    # A request without a local plan raises nothing locally.
    assert after.request_fingerprint == promoted

    first = load_tracking_operation(config, first_id)
    second = load_tracking_operation(config, second_id)
    assert first.request_fingerprint == second.request_fingerprint


def test_unknown_external_outcome_never_raises_the_local_plan(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC 3: 结果待确认 leaves the local plan and fingerprint untouched."""
    saved, config, record, snapshot = _seed(tmp_path)
    ab = _fake_client(monkeypatch)
    ab.fail_write = True

    response = _post(
        client, record, _body(saved, record, local_plan={"expected_folder_name": "New"})
    )

    payload = response.get_json()
    assert response.status_code == 200, payload
    assert payload["result"]["management_status"] == "OUTCOME_UNKNOWN", payload
    assert payload["result"]["needs_manual"] is True
    assert load_request_snapshot(config, "req-local") == snapshot
    assert load_tracking_record(config, record.tracking_id).request_fingerprint is None
    # The unknown outcome is a persisted operation, never a retryable failure.
    assert ab.calls and ab.calls[-1][0] == "update_subscription"


def test_rss_scope_with_a_local_plan_is_rejected_without_echoing_it(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC 2: only a subscription modify has a local plan to raise (fail closed)."""
    saved, config, record, snapshot = _seed(tmp_path)
    ab = _fake_client(monkeypatch)

    response = _post(client, record, _body(
        saved, record,
        target_scope="ASSOCIATED_RSS",
        patch={"name": "Feed"},
        local_plan={"expected_folder_name": "SecretFolder"},
    ))

    payload = response.get_json()
    assert response.status_code == 400, payload
    assert payload["error_type"] == "data_validation_errors"
    errors = payload["error_data"]["errors"]
    # A model-level scope rule has no field location; the envelope still names
    # the offending input in the fixed Chinese message.
    assert [item["field"] for item in errors] == ["_schema"]
    assert "local_plan 只适用于 SUBSCRIPTION 的修改" in errors[0]["message"]
    # The rejected plan content is never echoed back.
    assert "SecretFolder" not in response.get_data(as_text=True)
    assert ab.calls == []
    assert load_request_snapshot(config, "req-local") == snapshot
    assert load_tracking_record(config, record.tracking_id).request_fingerprint is None


@pytest.mark.parametrize(
    ("local_plan", "expected"),
    [
        ({}, "local_plan 不能为空"),
        ({"expected_folder_name": ""}, "expected_folder_name 不能为空字符串"),
        ({"expected_folder_name": "a/b"}, "expected_folder_name 含不合法字符"),
        ({"filter_rule": {}}, "filter_rule 不能为空"),
    ],
)
def test_an_empty_or_unsafe_local_plan_is_rejected(
    tmp_path: Path,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
    local_plan: dict[str, Any],
    expected: str,
) -> None:
    """The restored field keeps the #91 strictness (no empty/unsafe plans)."""
    saved, config, record, snapshot = _seed(tmp_path)
    ab = _fake_client(monkeypatch)

    response = _post(client, record, _body(saved, record, local_plan=local_plan))

    payload = response.get_json()
    assert response.status_code == 400, payload
    assert payload["error_type"] == "data_validation_errors"
    assert any(expected in item["message"] for item in payload["error_data"]["errors"])
    assert ab.calls == []
    assert load_request_snapshot(config, "req-local") == snapshot


def test_a_local_plan_alone_still_requires_the_patch(
    tmp_path: Path, client: FlaskClient
) -> None:
    """``patch`` and ``local_plan`` stay independent inputs of one request."""
    saved, config, record, _snapshot = _seed(tmp_path)
    body = _body(saved, record, local_plan={"expected_folder_name": "New"})
    body.pop("patch")

    response = _post(client, record, body)

    assert response.status_code == 400
    assert response.get_json()["error_type"] == "data_validation_errors"
