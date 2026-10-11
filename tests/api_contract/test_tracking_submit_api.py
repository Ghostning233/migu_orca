from __future__ import annotations

"""US-225 route/contract tests for the unified reliable submit endpoint.

These run against the real Flask app through the ``client`` fixture and never
touch an external system.  Accepted Requests come from the static fixture and
tracking records are seeded through the handoff; Auto Bangumi is faked by
monkeypatching the AB HTTP client factory that the compose seam resolves at
call time.  The autouse ``_web_storage_root`` fixture maps the relative
``storage`` profile onto ``tmp_path`` so absolute tmp paths never leak into
payloads or URLs.
"""

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from flask.testing import FlaskClient

from ab_engine.controllers.ab_client import FakeAutoBangumiClient
from ab_engine.models.management import ExternalRss, ExternalSubscription
from apps.migu_orca_entry.controllers.entry_controller import generate_request
from apps.migu_orca_web.api_contract import TrackingSubmitResultDTO
from apps.migu_orca_web.tracking_handoff import ensure_confirmed_request_tracking
from request_engine.controllers.request_controller import accept_request
from shared.errors import Stage1Error
from shared.models import EntryRequest
from storage_engine.controllers.autobangumi_config_repository import (
    AutoBangumiConfigRepository,
    build_stored_autobangumi_config,
)
from storage_engine.controllers.operation_repository import load_tracking_operation
from storage_engine.controllers.request_repository import (
    load_request_snapshot,
    save_request_snapshot,
)
from storage_engine.controllers.storage_config import (
    StorageConfig,
    load_storage_config,
)
from storage_engine.controllers.tracking_repository import (
    compare_and_swap_tracking_record,
    load_tracking_record,
)
from tracking_engine.controllers.submit import classify_external_submit_result
from tracking_engine.models.operation import (
    TRACKING_OPERATION_STATE_FAILED,
    TRACKING_OPERATION_STATE_SUCCEEDED,
)
from tracking_engine.models.tracking import (
    TRACKING_AUDIT_SUBMIT_STARTED,
    TRACKING_AUDIT_SUBMIT_SUCCEEDED,
    TRACKING_AUDIT_TRACKING_CREATED,
    TRACKING_ORIGIN_SAVE_CONFIRM,
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_NEEDS_RECONFIRM,
    TRACKING_STATUS_SUBMIT_FAILED,
    TRACKING_STATUS_SUBMITTING,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
    TrackingRecord,
    transition_record,
)

AB_CONFIG = {
    "auth_mode": "api_token",
    "base_url": "http://auto-bangumi.local",
    "token": "secret-token",
    "fallback_enabled": False,
}

SAVED_GENERATION: tuple[str, int] = ("", 0)


def _config(tmp_path: Path) -> StorageConfig:
    return load_storage_config(tmp_path / "storage")


def _accepted_request(
    tmp_path: Path,
    request_id: str = "request-1",
) -> dict[str, Any]:
    config = _config(tmp_path)
    request = accept_request(
        {
            **generate_request(EntryRequest(raw_title="芙莉莲"))["request"],
            "request_id": request_id,
        }
    )
    save_request_snapshot(config, request)
    return request


def _seed_tracking(tmp_path: Path, request: dict[str, Any]) -> TrackingRecord:
    global SAVED_GENERATION
    saved = AutoBangumiConfigRepository(tmp_path / "config").save(
        build_stored_autobangumi_config({"auth_mode": "password", "base_url": "http://ab.invalid", "username": "u", "password": "p"}),
        expected_configuration_revision=0,
    )
    SAVED_GENERATION = (str(saved.connection_ref), saved.configuration_revision)
    config = _config(tmp_path)
    handoff = ensure_confirmed_request_tracking(
        config=config,
        request=request,
        origin=TRACKING_ORIGIN_SAVE_CONFIRM,
        now="2026-09-08T00:00:00+00:00",
    )
    assert handoff.tracking_id is not None
    return load_tracking_record(config, handoff.tracking_id)


def _save_modified_request(tmp_path: Path, request_id: str, **changes: Any) -> None:
    config = _config(tmp_path)
    request = load_request_snapshot(config, request_id)
    confirmable = request.get("confirmable_config")
    assert isinstance(confirmable, dict)
    for key, value in changes.items():
        confirmable[key] = value
    save_request_snapshot(config, request)


def _submit_body(record: TrackingRecord, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "expected_revision": record.revision,
        "storage_dir": "storage",
        "confirm": True,
        "idempotency_key": "key-1",
        "connection_ref": SAVED_GENERATION[0],
        "configuration_revision": SAVED_GENERATION[1],
    }
    body.update(overrides)
    return body


def _patch_ab_factory(monkeypatch: pytest.MonkeyPatch, client: FakeAutoBangumiClient):
    state: dict[str, Any] = {"result": None}

    def submit_one(_request: dict[str, Any], _config: Any) -> dict[str, Any]:
        try:
            client.create_subscription({"fixture": True})
        except Exception as exc:  # a pre-write/definite failure still gates read-back
            state["result"] = {
                "success": False,
                "error": {"error_type": getattr(exc, "error_type", "ab_submit_failed")},
            }
            raise
        result = {"success": True, "ab_subscription_id": "fake-ab-subscription", "error": None}
        state["result"] = result
        return result

    monkeypatch.setattr("apps.migu_orca_web.tracking_submission_service.compose_tracking_submit_one", lambda: submit_one)
    _patch_readback(monkeypatch, state)
    return client


# ---------------------------------------------------------------------------
# Success / business outcomes
# ---------------------------------------------------------------------------


def test_submit_success_persists_active_and_dto(
    tmp_path: Path,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    fake = FakeAutoBangumiClient()
    _patch_ab_factory(monkeypatch, fake)

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json=_submit_body(record),
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["outcome"] == TRACKING_STATUS_ACTIVE
    assert result["issues"] == []
    assert result["failure_category"] is None
    assert result["operation_id"] is not None
    assert result["tracking"]["status"] == TRACKING_STATUS_ACTIVE
    TrackingSubmitResultDTO.model_validate(result)

    after = load_tracking_record(_config(tmp_path), record.tracking_id)
    assert after.status == TRACKING_STATUS_ACTIVE
    assert [event["action"] for event in after.audit_events] == [
        TRACKING_AUDIT_TRACKING_CREATED,
        TRACKING_AUDIT_SUBMIT_STARTED,
        TRACKING_AUDIT_SUBMIT_SUCCEEDED,
    ]
    assert fake.calls

    body_text = response.get_data(as_text=True)
    assert "secret-token" not in body_text
    assert "auto-bangumi.local" not in body_text
    assert str(tmp_path) not in body_text


def test_submit_changed_plan_confirm_adopts_latest_and_submits(
    tmp_path: Path,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    _save_modified_request(tmp_path, "request-1", selected_subtitle_group="Loli")
    _patch_ab_factory(monkeypatch, FakeAutoBangumiClient())

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json=_submit_body(record),
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["outcome"] == TRACKING_STATUS_ACTIVE
    after = load_tracking_record(_config(tmp_path), record.tracking_id)
    assert after.status == TRACKING_STATUS_ACTIVE


def test_submit_confirm_false_returns_400_confirmation_required(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json=_submit_body(record, confirm=False),
    )
    assert response.status_code == 400
    assert response.get_json()["error_type"] == "data_validation_errors"


def test_submit_blocking_issue_returns_needs_reconfirm_without_ab_call(
    tmp_path: Path,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    _save_modified_request(tmp_path, "request-1", selected_subtitle_group="")
    fake = FakeAutoBangumiClient()
    _patch_ab_factory(monkeypatch, fake)

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json=_submit_body(record),
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["outcome"] == TRACKING_STATUS_NEEDS_RECONFIRM
    assert result["issues"]
    assert fake.calls == []
    after = load_tracking_record(_config(tmp_path), record.tracking_id)
    assert after.status == TRACKING_STATUS_NEEDS_RECONFIRM


def test_submit_definite_external_failure_returns_submit_failed(
    tmp_path: Path,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    fake = FakeAutoBangumiClient(
        error=Stage1Error(
            "ab_auth_failed",
            "Auto Bangumi 认证失败",
            "create_ab_subscription",
            {"status_code": 401},
        )
    )
    _patch_ab_factory(monkeypatch, fake)

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json=_submit_body(record),
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["outcome"] == TRACKING_STATUS_SUBMIT_FAILED
    assert result["failure_category"] == "AUTHENTICATION"
    assert fake.calls
    body_text = response.get_data(as_text=True)
    assert "secret-token" not in body_text
    assert "auto-bangumi.local" not in body_text


def test_submit_unknown_external_outcome_returns_verifying_external(
    tmp_path: Path,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    fake = FakeAutoBangumiClient(
        error=Stage1Error(
            "ab_timeout",
            "Auto Bangumi HTTP 请求超时",
            "create_ab_subscription",
            {"category": "timeout"},
        )
    )
    _patch_ab_factory(monkeypatch, fake)

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json=_submit_body(record),
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["outcome"] == TRACKING_STATUS_VERIFYING_EXTERNAL
    assert result["failure_category"] == "OUTCOME_UNKNOWN"


@pytest.mark.parametrize(
    ("error_type", "expected_category"),
    [
        ("ab_connection_failed_pre_write", "CONNECTION"),
        ("ab_timeout_pre_write", "CONNECTION"),
        ("ab_connection_failed", "OUTCOME_UNKNOWN"),
        ("ab_timeout", "OUTCOME_UNKNOWN"),
        ("ab_auth_failed", "AUTHENTICATION"),
        ("ab_unsupported_version", "VERSION"),
        ("ab_duplicate_subscription", "DUPLICATE_SUBSCRIPTION"),
        ("invalid_ab_payload", "VALIDATION"),
        ("ab_submit_failed", "REJECTED"),
    ],
)
def test_submit_publishes_a_stable_failure_category(
    tmp_path: Path,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
    error_type: str,
    expected_category: str,
) -> None:
    """Issue #86: every external failure publishes one safe, actionable class."""
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    fake = FakeAutoBangumiClient(
        error=Stage1Error(error_type, "Auto Bangumi 提交失败", "create_ab_subscription")
    )
    _patch_ab_factory(monkeypatch, fake)

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json=_submit_body(record),
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["failure_category"] == expected_category
    TrackingSubmitResultDTO.model_validate(result)
    body_text = response.get_data(as_text=True)
    for forbidden in ("secret-token", "auto-bangumi.local", str(tmp_path)):
        assert forbidden not in body_text


# ---------------------------------------------------------------------------
# Precondition guards / strict payload
# ---------------------------------------------------------------------------


def test_submit_missing_record_is_404(tmp_path: Path, client: FlaskClient) -> None:
    saved = AutoBangumiConfigRepository(tmp_path / "config").save(
        build_stored_autobangumi_config({"auth_mode": "password", "base_url": "http://ab.invalid", "username": "u", "password": "p"}),
        expected_configuration_revision=0,
    )
    response = client.post(
        "/api/v1/tracking/items/trk_nonexistent0000000000000000000000/submit",
            json=_submit_body(TrackingRecord(tracking_id="trk_nonexistent0000000000000000000000", revision=1),
                              connection_ref=str(saved.connection_ref), configuration_revision=saved.configuration_revision),
    )
    assert response.status_code == 404
    assert response.get_json()["error_type"] == "tracking_not_found"


def test_submit_revision_conflict_is_409(tmp_path: Path, client: FlaskClient) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json=_submit_body(record, expected_revision=record.revision + 99),
    )
    assert response.status_code == 409
    assert response.get_json()["error_type"] == "tracking_revision_conflict"


def test_submit_active_record_raises_state_conflict(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    active = transition_record(
        record,
        status=TRACKING_STATUS_ACTIVE,
        audit_action=TRACKING_AUDIT_SUBMIT_SUCCEEDED,
        now="2026-09-08T00:00:00+00:00",
    )
    compare_and_swap_tracking_record(
        _config(tmp_path),
        record.tracking_id,
        base_revision=record.revision,
        record=active,
    )
    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json=_submit_body(active),
    )
    assert response.status_code == 409
    assert response.get_json()["error_type"] == "tracking_state_conflict"


def test_submit_in_flight_operation_raises_operation_in_progress(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    """A new key submit against a record with an in-flight operation is 409."""
    from dataclasses import replace as _replace

    from storage_engine.controllers.operation_repository import (
        bind_tracking_operation,
        compare_and_swap_tracking_operation,
    )
    from tracking_engine.models.operation import (
        TRACKING_OPERATION_KIND_SUBMIT,
        TRACKING_OPERATION_STATE_IN_PROGRESS,
        TRACKING_OPERATION_STATE_PREPARED,
        transition_tracking_operation,
    )

    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    config = _config(tmp_path)
    bound, created = bind_tracking_operation(
        config,
        tracking_id=record.tracking_id,
        operation=TRACKING_OPERATION_KIND_SUBMIT,
        idempotency_key="old-key",
        expected_revision=record.revision,
        request_fingerprint=record.request_fingerprint or "fingerprint",
        now="2026-09-08T00:00:00+00:00",
    )
    assert created is True
    in_flight = compare_and_swap_tracking_operation(
        config,
        bound.operation_id,
        expected_state=TRACKING_OPERATION_STATE_PREPARED,
        record=transition_tracking_operation(
            bound,
            state=TRACKING_OPERATION_STATE_IN_PROGRESS,
            now="2026-09-08T00:00:00+00:00",
        ),
    )
    assert in_flight.state == TRACKING_OPERATION_STATE_IN_PROGRESS

    submitting = _replace(
        transition_record(
            record,
            status=TRACKING_STATUS_SUBMITTING,
            audit_action=TRACKING_AUDIT_SUBMIT_STARTED,
            now="2026-09-08T00:00:00+00:00",
        ),
        current_operation_id=bound.operation_id,
    )
    compare_and_swap_tracking_record(
        config,
        record.tracking_id,
        base_revision=record.revision,
        record=submitting,
    )
    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json=_submit_body(submitting, idempotency_key="new-key"),
    )
    assert response.status_code == 409
    assert response.get_json()["error_type"] == "tracking_operation_in_progress"


def test_submit_rejects_unknown_field(tmp_path: Path, client: FlaskClient) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json={**_submit_body(record), "mystery": 1},
    )
    assert response.status_code == 400
    assert response.get_json()["error_type"] == "data_validation_errors"


def test_submit_rejects_missing_idempotency_key(
    tmp_path: Path,
    client: FlaskClient,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    body = _submit_body(record)
    body.pop("idempotency_key")
    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json=body,
    )
    assert response.status_code == 400
    assert response.get_json()["error_type"] == "data_validation_errors"


def test_submit_same_key_replay_reuses_operation_without_second_external_call(
    tmp_path: Path,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    fake = FakeAutoBangumiClient()
    _patch_ab_factory(monkeypatch, fake)

    url = f"/api/v1/tracking/items/{record.tracking_id}/submit"
    first = client.post(url, json=_submit_body(record))
    assert first.status_code == 200
    assert first.get_json()["result"]["outcome"] == TRACKING_STATUS_ACTIVE
    assert len(fake.calls) == 1

    replay = client.post(url, json=_submit_body(record))
    assert replay.status_code == 200
    replay_result = replay.get_json()["result"]
    assert replay_result["outcome"] == TRACKING_STATUS_ACTIVE
    assert replay_result["operation_id"] == first.get_json()["result"]["operation_id"]
    assert len(fake.calls) == 1

#: The plan fixture's exact RSS identity; a read-back that matched nothing is
#: what a definite external failure looks like (issue #97 AC 5).
FIXTURE_RSS_URL = "https://example.invalid/rss/frieren-moe.xml"


def _patch_readback(
    monkeypatch: pytest.MonkeyPatch,
    state: dict[str, Any],
    *,
    rss_url: str = FIXTURE_RSS_URL,
    external_id: str = "fake-ab-subscription",
    mode: str = "auto",
) -> None:
    """Inject an exact read-back that follows the write result (issue #97).

    A successful write reads back the exact RSS + owning subscription; a failed
    write reads back nothing, which the server must treat as a definite failure.
    """

    def read_snapshot(deadline=None) -> Any:
        if mode == "unreadable":
            return None
        if mode == "empty":
            return (None, [], [])
        if mode == "always_match":
            return (
                None,
                [ExternalSubscription(external_id, "葬送的芙莉莲", 1, "喵萌", rss_urls=(rss_url,))],
                [ExternalRss("rss-1", "芙莉莲", rss_url)],
            )
        classification = classify_external_submit_result(state.get("result"))
        if classification != TRACKING_OPERATION_STATE_SUCCEEDED:
            # A definite failure confirms there is no object; an unresolved write
            # cannot be read at all, so it stays unresolved (issue #97 AC 5/6).
            if classification == TRACKING_OPERATION_STATE_FAILED:
                return (None, [], [])
            return None
        return (
            None,
            [ExternalSubscription(external_id, "葬送的芙莉莲", 1, "喵萌", rss_urls=(rss_url,))],
            [ExternalRss("rss-1", "芙莉莲", rss_url)],
        )

    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_submission_service.compose_tracking_readback_external",
        lambda _config: read_snapshot,
    )

# -- issue #97: the write body alone never establishes ownership ---------------


def _patch_result(monkeypatch: pytest.MonkeyPatch, result: dict[str, Any]) -> None:
    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_submission_service.compose_tracking_submit_one",
        lambda: (lambda _request, _config: result),
    )


def test_submit_non_success_write_confirmed_by_readback_is_active_with_warning(
    tmp_path: Path,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #97 AC 4: a rejected body plus an exact read-back is 追番中."""
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    _patch_result(
        monkeypatch,
        {"success": False, "error": {"error_type": "ab_submit_failed"}, "error_message": "upstream"},
    )
    _patch_readback(monkeypatch, {}, mode="always_match", external_id="sub-readback")

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit", json=_submit_body(record)
    )

    result = response.get_json()["result"]
    assert result["tracking"]["status"] == TRACKING_STATUS_ACTIVE
    stored = load_tracking_record(_config(tmp_path), record.tracking_id)
    assert stored.external_mapping is not None
    assert stored.external_mapping.get("subscription_id") == "sub-readback"
    body_text = response.get_data(as_text=True)
    for forbidden in ("upstream", "secret-token", "auto-bangumi.local", str(tmp_path)):
        assert forbidden not in body_text
    # The safe note about the unconfirmed write body is recorded.
    assert any(
        "写响应未确认" in str(event.get("safe_message", ""))
        for event in stored.audit_events
    )


def test_submit_success_body_without_a_readback_object_stays_pending(
    tmp_path: Path,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #97 AC 3/5 + #182: a 200 body alone creates no mapping, and one
    empty read-back is 结果待确认, never a safely retryable failure."""
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    _patch_result(monkeypatch, {"success": True, "ab_subscription_id": "claimed-by-body"})
    _patch_readback(monkeypatch, {}, mode="empty")

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit", json=_submit_body(record)
    )

    result = response.get_json()["result"]
    assert result["tracking"]["status"] == TRACKING_STATUS_VERIFYING_EXTERNAL
    stored = load_tracking_record(_config(tmp_path), record.tracking_id)
    assert stored.external_mapping is None
    assert stored.last_error is not None
    assert stored.last_error.get("reason_code") == "NOT_FOUND"


def test_submit_proven_write_failure_without_a_readback_object_is_submit_failed(
    tmp_path: Path,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #182: only evidence that nothing was created stays a failure."""
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    _patch_result(
        monkeypatch,
        {"success": False, "error": {"error_type": "ab_auth_failed", "details": {"status_code": 401}}},
    )
    _patch_readback(monkeypatch, {}, mode="empty")

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit", json=_submit_body(record)
    )

    result = response.get_json()["result"]
    assert result["tracking"]["status"] == TRACKING_STATUS_SUBMIT_FAILED
    stored = load_tracking_record(_config(tmp_path), record.tracking_id)
    assert stored.external_mapping is None


def test_submit_success_body_with_an_unreadable_readback_stays_unresolved(
    tmp_path: Path,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #97 AC 6: an unreadable read-back is 结果待确认, never a retry."""
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    _patch_result(monkeypatch, {"success": True, "ab_subscription_id": "claimed-by-body"})
    _patch_readback(monkeypatch, {}, mode="unreadable")

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit", json=_submit_body(record)
    )

    result = response.get_json()["result"]
    assert result["tracking"]["status"] == TRACKING_STATUS_VERIFYING_EXTERNAL
    stored = load_tracking_record(_config(tmp_path), record.tracking_id)
    assert stored.external_mapping is None


def test_submit_without_valid_resources_is_refused_before_any_external_call(
    tmp_path: Path,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #97 AC 1/2: zero resources fail before the AB write, without MiKan."""
    request = _accepted_request(tmp_path)
    config = _config(tmp_path)
    snapshot = load_request_snapshot(config, request["request_id"])
    for source in snapshot["source_info"]["rss_sources"]:
        source["valid_seed_names"] = []
    snapshot["confirmable_config"]["effective_seed_names"] = []
    save_request_snapshot(config, snapshot)
    record = _seed_tracking(tmp_path, request)
    calls: list[dict[str, Any]] = []

    def submit_one(_request: dict[str, Any], _config: Any) -> dict[str, Any]:
        calls.append(_request)
        return {"success": True, "ab_subscription_id": "never"}

    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_submission_service.compose_tracking_submit_one",
        lambda: submit_one,
    )
    _patch_readback(monkeypatch, {}, mode="always_match")

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit", json=_submit_body(record)
    )

    assert response.status_code in (200, 409)
    assert calls == []
    stored = load_tracking_record(_config(tmp_path), record.tracking_id)
    assert stored.status != TRACKING_STATUS_ACTIVE
    issues = response.get_json().get("result", {}).get("issues", [])
    if response.status_code == 200:
        assert "NO_VALID_RESOURCES" in [issue.get("code") for issue in issues]

# -- issue #98: the operation-level submission mode ---------------------------


@pytest.mark.parametrize(
    ("body_mode", "expected"),
    [(None, "CONTINUE_TRACKING"), ("DOWNLOAD_EXISTING", "DOWNLOAD_EXISTING")],
)
def test_submit_records_the_operation_level_submission_mode(
    tmp_path: Path,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
    body_mode: str | None,
    expected: str,
) -> None:
    """AC 1: the chosen mode is an operation fact, never a local plan field."""
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    _patch_ab_factory(monkeypatch, FakeAutoBangumiClient())
    overrides = {"submission_mode": body_mode} if body_mode else {}

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json=_submit_body(record, **overrides),
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    operation = load_tracking_operation(_config(tmp_path), result["operation_id"])
    assert operation.submission_mode == expected
    # The local plan snapshot never carries the submission mode.
    snapshot = load_request_snapshot(_config(tmp_path), request["request_id"])
    assert "submission_mode" not in json.dumps(snapshot, ensure_ascii=False)


def test_submit_rejects_an_unknown_submission_mode(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    _patch_ab_factory(monkeypatch, FakeAutoBangumiClient())

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json=_submit_body(record, submission_mode="SAFE_RETRY"),
    )

    assert response.status_code == 400
    assert response.get_json()["error_type"] == "data_validation_errors"

# -- issue #98: one-time "download existing resources" ------------------------


def _patch_collect(monkeypatch: pytest.MonkeyPatch, result: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def collect_one(request: dict[str, Any], _config: Any) -> dict[str, Any]:
        calls.append(request)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_submission_service.compose_tracking_collect_one",
        lambda: collect_one,
    )
    return calls


def test_download_existing_accepts_200_as_added_to_download(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC 7: 200 means 已加入下载, with no external subscription and no read-back."""
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    calls = _patch_collect(monkeypatch, {"success": True, "ab_response": {"status": "ok"}})
    readbacks: list[int] = []
    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_submission_service.compose_tracking_readback_external",
        lambda _config: (lambda: readbacks.append(1)),
    )

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json=_submit_body(record, submission_mode="DOWNLOAD_EXISTING"),
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["tracking"]["status"] == "ADDED_TO_DOWNLOAD"
    stored = load_tracking_record(_config(tmp_path), record.tracking_id)
    # A one-time request never claims a controlled external subscription.
    assert stored.external_mapping is None
    assert len(calls) == 1
    assert readbacks == [], "a one-time request must not read anything back"


@pytest.mark.parametrize(
    "result",
    [
        {"success": False, "error": {"error_type": "ab_submit_failed"}},
        Stage1Error("ab_timeout", "Auto Bangumi 提交超时", "create_ab_subscription"),
        Stage1Error("ab_connection_failed", "无法连接 Auto Bangumi", "create_ab_subscription"),
    ],
)
def test_download_existing_maps_every_other_outcome_to_submit_failed(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch, result: Any
) -> None:
    """AC 7/8: non-200, timeout and connection failure are one retryable failure."""
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    _patch_collect(monkeypatch, result)

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json=_submit_body(record, submission_mode="DOWNLOAD_EXISTING"),
    )

    assert response.status_code == 200
    payload = response.get_json()["result"]
    assert payload["tracking"]["status"] == TRACKING_STATUS_SUBMIT_FAILED
    stored = load_tracking_record(_config(tmp_path), record.tracking_id)
    assert stored.external_mapping is None
    assert stored.last_error is not None
    # The wording never promises a safe retry (ADR-0001).
    assert "可重新提交" in str(payload["tracking"].get("last_error") or stored.last_error)


def test_download_existing_fails_closed_without_a_verified_endpoint(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The unverified default seam converges on 提交失败 instead of a 400."""
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    _patch_ab_factory(monkeypatch, FakeAutoBangumiClient())

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit",
        json=_submit_body(record, submission_mode="DOWNLOAD_EXISTING"),
    )

    assert response.status_code == 200
    assert response.get_json()["result"]["tracking"]["status"] == TRACKING_STATUS_SUBMIT_FAILED

class _BareArrayAbOpener:
    """The verified 3.1.18 HTTP surface, served as raw bytes keyed by path.

    Only the outermost network exchange is replaced: the real write adapter, the
    real JSON decoder, the real management adapter and the real local
    persistence all run.  The list endpoints answer with the bare JSON arrays
    the real service returns (issue #182).
    """

    def __init__(self, rss_url: str) -> None:
        self.rss_url = rss_url
        self.calls: list[str] = []

    def exchange(
        self, method: str, endpoint: str, headers: Any, body: Any, **kwargs: Any
    ) -> tuple[int, dict[str, str], bytes]:
        path = urlsplit(endpoint).path
        self.calls.append(f"{method} {path}")
        if path == "/api/v1/auth/login":
            body = b'{"access_token": "ab-session"}'
        elif path == "/api/v1/status":
            body = b'{"version": "3.1.18"}'
        elif path == "/api/v1/bangumi/get/all":
            body = json.dumps([{
                "id": 42, "official_title": "\u846c\u9001\u7684\u8299\u8389\u83b2",
                "title_raw": "Frieren", "season": 1, "season_raw": "1",
                "group_name": "\u55b5\u840c", "rss_link": self.rss_url,
                "rss_ids": [7], "deleted": False,
            }]).encode("utf-8")
        elif path == "/api/v1/rss":
            body = json.dumps([{
                "id": 7, "name": "RSS", "url": self.rss_url,
                "aggregate": False, "parser": "rss", "enabled": True,
            }]).encode("utf-8")
        elif path == "/api/v1/rss/subscribe":
            body = b'{"status": true}'
        else:  # pragma: no cover - the fixture must stay exhaustive
            raise AssertionError(f"unexpected Auto Bangumi path: {path}")
        return 200, {}, body


def test_submit_confirms_through_the_real_http_decoder_and_persists_active(
    tmp_path: Path,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #182 AC: the Flask acceptance path really decodes and confirms.

    The write, the read-back and the persisted mapping all run through the real
    adapters; only the HTTP socket is replaced, so a wrapper-only fake can no
    longer make an unreadable list look confirmed.
    """
    request = _accepted_request(tmp_path)
    record = _seed_tracking(tmp_path, request)
    stored_request = load_request_snapshot(_config(tmp_path), request["request_id"])
    rss_url = stored_request["confirmable_config"]["selected_rss_url"]
    opener = _BareArrayAbOpener(rss_url)
    monkeypatch.setattr("ab_engine.controllers.ab_http_client._exchange", opener.exchange)

    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/submit", json=_submit_body(record)
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["tracking"]["status"] == TRACKING_STATUS_ACTIVE
    stored = load_tracking_record(_config(tmp_path), record.tracking_id)
    assert stored.external_mapping is not None
    assert stored.external_mapping["subscription_id"] == "42"
    # Exactly one write reached the (replaced) network; the read-back only read.
    assert opener.calls.count("POST /api/v1/rss/subscribe") == 1
    assert "GET /api/v1/bangumi/get/all" in opener.calls
    assert "GET /api/v1/rss" in opener.calls
    body_text = response.get_data(as_text=True)
    assert "ab-session" not in body_text
    assert "example.invalid" not in body_text
