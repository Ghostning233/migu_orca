from __future__ import annotations

"""Issue #87 contract tests for the explicit batch submit endpoint.

The batch is N *independent* reliable submissions: every entry keeps its own
revision and idempotency key, one failure never rolls back a success, and a
repeated request reuses the same operations.  These tests run against the real
Flask app with an isolated temporary storage root and a programmable Auto
Bangumi seam, so no external system is ever touched.
"""

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from flask.testing import FlaskClient

from ab_engine.models.management import ExternalRss, ExternalSubscription
from apps.migu_orca_entry.controllers.entry_controller import generate_request
from apps.migu_orca_web.api_contract import TrackingBatchSubmitResultDTO
from apps.migu_orca_web.tracking_handoff import ensure_confirmed_request_tracking
from request_engine.controllers.request_controller import accept_request
from shared.models import EntryRequest
from storage_engine.controllers.autobangumi_config_repository import (
    AutoBangumiConfigRepository,
    build_stored_autobangumi_config,
)
from storage_engine.controllers.operation_repository import load_tracking_operation
from storage_engine.controllers.request_repository import save_request_snapshot
from storage_engine.controllers.storage_config import (
    StorageConfig,
    load_storage_config,
)
from storage_engine.controllers.tracking_repository import load_tracking_record
from tracking_engine.controllers.submit import classify_external_submit_result
from tracking_engine.models.operation import (
    TRACKING_OPERATION_STATE_FAILED,
    TRACKING_OPERATION_STATE_SUCCEEDED,
)
from tracking_engine.models.tracking import (
    TRACKING_ORIGIN_SAVE_CONFIRM,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
    TrackingRecord,
)

BATCH_ENDPOINT = "/api/v1/tracking/batch-submit"
SUCCESS_RESULT = {"success": True, "ab_subscription_id": "ab-created", "error": None}
AUTH_FAILURE = {"success": False, "ab_subscription_id": None, "error": {"error_type": "ab_auth_failed"}}
UNKNOWN_RESULT = {"success": False, "ab_subscription_id": None, "error": {"error_type": "ab_timeout"}}


def _config(tmp_path: Path) -> StorageConfig:
    return load_storage_config(tmp_path / "storage")


def _seed_records(tmp_path: Path, count: int) -> tuple[dict[str, Any], list[TrackingRecord]]:
    """Seed one saved connection generation and ``count`` pending records."""
    saved = AutoBangumiConfigRepository(tmp_path / "config").save(
        build_stored_autobangumi_config(
            {
                "auth_mode": "password",
                "base_url": "http://ab.invalid",
                "username": "operator",
                "password": "secret-password",
            }
        ),
        expected_configuration_revision=0,
    )
    config = _config(tmp_path)
    records: list[TrackingRecord] = []
    for index in range(count):
        request = accept_request(
            {
                **generate_request(EntryRequest(raw_title="芙莉莲"))["request"],
                "request_id": f"request-{index}",
            }
        )
        save_request_snapshot(config, request)
        handoff = ensure_confirmed_request_tracking(
            config=config,
            request=request,
            origin=TRACKING_ORIGIN_SAVE_CONFIRM,
            now=f"2026-09-08T00:00:{index:02d}+00:00",
        )
        records.append(load_tracking_record(config, handoff.tracking_id))
    connection = {
        "connection_ref": str(saved.connection_ref),
        "configuration_revision": saved.configuration_revision,
    }
    return connection, records


def _batch_body(
    connection: dict[str, Any],
    records: list[TrackingRecord],
    **overrides: Any,
) -> dict[str, Any]:
    return {
        "items": [
            {
                "tracking_id": record.tracking_id,
                "expected_revision": record.revision,
                "idempotency_key": f"batch-key-{record.tracking_id}",
            }
            for record in records
        ],
        "confirm": True,
        "storage_dir": "storage",
        **connection,
        **overrides,
    }


def _patch_submit_one(monkeypatch: pytest.MonkeyPatch, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Serve one queued Auto Bangumi result per external call, in order."""
    queue = list(results)
    calls: list[dict[str, Any]] = []
    state: dict[str, Any] = {"result": None}

    def submit_one(request: dict[str, Any], _config: Any) -> dict[str, Any]:
        calls.append(request)
        assert queue, "the batch issued more external calls than the test queued"
        state["result"] = queue[0]
        return queue.pop(0)

    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_submission_service.compose_tracking_submit_one",
        lambda: submit_one,
    )
    _patch_readback(monkeypatch, state)
    return calls


def _post(client: FlaskClient, body: dict[str, Any]) -> Any:
    return client.post(BATCH_ENDPOINT, json=body)


# ---------------------------------------------------------------------------
# Batch sizes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("count", [1, 12, 36])
def test_batch_submit_runs_every_selected_entry(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch, count: int
) -> None:
    connection, records = _seed_records(tmp_path, count)
    calls = _patch_submit_one(monkeypatch, [SUCCESS_RESULT] * count)

    response = _post(client, _batch_body(connection, records))

    payload = response.get_json()
    assert response.status_code == 200
    result = payload["result"]
    TrackingBatchSubmitResultDTO.model_validate(result)
    assert result["summary"] == {
        "total": count, "succeeded": count, "failed": 0, "unknown": 0, "blocked": 0,
    }
    assert [item["tracking_id"] for item in result["items"]] == [
        record.tracking_id for record in records
    ]
    assert all(item["ok"] is True for item in result["items"])
    assert all(item["result"]["outcome"] == "ACTIVE" for item in result["items"])
    assert len(calls) == count


# ---------------------------------------------------------------------------
# Per-entry independence
# ---------------------------------------------------------------------------


def test_batch_submit_partial_success_never_rolls_back_a_success(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection, records = _seed_records(tmp_path, 3)
    _patch_submit_one(monkeypatch, [SUCCESS_RESULT, AUTH_FAILURE, UNKNOWN_RESULT])

    payload = _post(client, _batch_body(connection, records)).get_json()

    result = payload["result"]
    assert result["summary"] == {
        "total": 3, "succeeded": 1, "failed": 1, "unknown": 1, "blocked": 0,
    }
    by_id = {item["tracking_id"]: item for item in result["items"]}
    succeeded = by_id[records[0].tracking_id]
    assert succeeded["ok"] is True
    assert succeeded["result"]["failure_category"] is None
    failed = by_id[records[1].tracking_id]
    assert failed["ok"] is False
    assert failed["result"]["outcome"] == "SUBMIT_FAILED"
    assert failed["result"]["failure_category"] == "AUTHENTICATION"
    unknown = by_id[records[2].tracking_id]
    assert unknown["ok"] is False
    assert unknown["result"]["outcome"] == "VERIFYING_EXTERNAL"
    assert unknown["result"]["failure_category"] == "OUTCOME_UNKNOWN"

    # The success stayed persisted even though a later entry failed.
    config = _config(tmp_path)
    assert load_tracking_record(config, records[0].tracking_id).status == "ACTIVE"
    assert load_tracking_record(config, records[1].tracking_id).status == "SUBMIT_FAILED"
    assert load_tracking_record(config, records[2].tracking_id).status == "VERIFYING_EXTERNAL"


def test_batch_submit_reports_every_entry_when_all_fail(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection, records = _seed_records(tmp_path, 2)
    _patch_submit_one(monkeypatch, [AUTH_FAILURE, AUTH_FAILURE])

    result = _post(client, _batch_body(connection, records)).get_json()["result"]

    assert result["summary"] == {
        "total": 2, "succeeded": 0, "failed": 2, "unknown": 0, "blocked": 0,
    }
    assert all(item["ok"] is False for item in result["items"])
    assert all(item["result"]["failure_category"] == "AUTHENTICATION" for item in result["items"])


def test_batch_submit_precondition_conflict_blocks_only_that_entry(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection, records = _seed_records(tmp_path, 2)
    calls = _patch_submit_one(monkeypatch, [SUCCESS_RESULT])
    body = _batch_body(connection, records)
    body["items"][1]["expected_revision"] = records[1].revision + 5

    result = _post(client, body).get_json()["result"]

    assert result["summary"] == {
        "total": 2, "succeeded": 1, "failed": 0, "unknown": 0, "blocked": 1,
    }
    by_id = {item["tracking_id"]: item for item in result["items"]}
    assert by_id[records[0].tracking_id]["ok"] is True
    blocked = by_id[records[1].tracking_id]
    assert blocked["ok"] is False
    assert blocked["error_type"] == "tracking_revision_conflict"
    assert blocked["result"] is None
    # The refused entry never reached Auto Bangumi.
    assert len(calls) == 1


def test_batch_submit_replays_one_key_without_a_second_external_call(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection, records = _seed_records(tmp_path, 1)
    calls = _patch_submit_one(monkeypatch, [SUCCESS_RESULT])
    body = _batch_body(connection, records)

    first = _post(client, body).get_json()["result"]
    second = _post(client, body).get_json()["result"]

    assert first["summary"]["succeeded"] == 1
    assert second["summary"]["succeeded"] == 1
    assert len(calls) == 1
    assert second["items"][0]["result"]["outcome"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Strict payload
# ---------------------------------------------------------------------------


def test_batch_submit_rejects_an_empty_oversized_or_duplicated_batch(
    tmp_path: Path, client: FlaskClient
) -> None:
    connection, records = _seed_records(tmp_path, 1)
    body = _batch_body(connection, records)

    for invalid in (
        {**body, "items": []},
        {**body, "items": body["items"] * 37},
        {**body, "items": [body["items"][0], body["items"][0]]},
        {**body, "confirm": False},
        {**body, "unexpected": True},
    ):
        response = _post(client, invalid)
        assert response.status_code == 400, invalid
        assert response.get_json()["error_type"] == "data_validation_errors"


def test_batch_submit_never_leaks_credentials_or_paths(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection, records = _seed_records(tmp_path, 2)
    _patch_submit_one(monkeypatch, [AUTH_FAILURE, UNKNOWN_RESULT])

    response = _post(client, _batch_body(connection, records))

    body_text = response.get_data(as_text=True)
    for forbidden in ("secret-password", "operator", "ab.invalid", str(tmp_path)):
        assert forbidden not in body_text

#: The plan fixture's exact RSS identity; a read-back that matched nothing is
#: what a definite external failure looks like (issue #97 AC 5).
FIXTURE_RSS_URL = "https://example.invalid/rss/frieren-moe.xml"


def _patch_readback(
    monkeypatch: pytest.MonkeyPatch,
    state: dict[str, Any],
    *,
    rss_url: str = FIXTURE_RSS_URL,
    external_id: str = "fake-ab-subscription",
) -> None:
    """Inject an exact read-back that follows the write result (issue #97).

    A successful write reads back the exact RSS + owning subscription; a failed
    write reads back nothing, which the server must treat as a definite failure.
    """

    def read_snapshot() -> Any:
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

# -- issue #100: exactly one submission mode for the whole batch ---------------


def _patch_collect(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def collect_one(request: dict[str, Any], _config: Any) -> dict[str, Any]:
        calls.append(request)
        return {"success": True, "ab_response": {"status": "ok"}}

    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_submission_service.compose_tracking_collect_one",
        lambda: collect_one,
    )
    return calls


@pytest.mark.parametrize(
    ("mode", "expected_status"),
    [("DOWNLOAD_EXISTING", "ADDED_TO_DOWNLOAD"), ("CONTINUE_TRACKING", "ACTIVE")],
)
def test_batch_applies_one_mode_to_every_entry(
    tmp_path: Path,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected_status: str,
) -> None:
    """AC 2: one mode for the batch; AC 6: never creates an RSS for a one-time run."""
    connection, records = _seed_records(tmp_path, 2)
    if mode == "DOWNLOAD_EXISTING":
        calls = _patch_collect(monkeypatch)
    else:
        calls = _patch_submit_one(monkeypatch, [{"success": True, "ab_subscription_id": "sub-1"}] * 2)

    response = _post(client, _batch_body(connection, records, submission_mode=mode))

    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["summary"]["succeeded"] == 2 and result["summary"]["blocked"] == 0
    assert all(item["ok"] is True for item in result["items"])
    config = _config(tmp_path)
    for record in records:
        stored = load_tracking_record(config, record.tracking_id)
        assert stored.status == expected_status
        operation = load_tracking_operation(config, stored.current_operation_id)
        assert operation.submission_mode == mode
        # A one-time batch never claims a controlled external subscription.
        assert (stored.external_mapping is None) == (mode == "DOWNLOAD_EXISTING")
    assert len(calls) == 2


def test_batch_rejects_a_per_entry_submission_mode(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC 2: per-entry overrides are refused outright — never partially applied."""
    connection, records = _seed_records(tmp_path, 2)
    calls = _patch_submit_one(monkeypatch, [{"success": True, "ab_subscription_id": "sub-1"}] * 2)
    body = _batch_body(connection, records)
    body["items"][0]["submission_mode"] = "DOWNLOAD_EXISTING"

    response = _post(client, body)

    assert response.status_code == 400
    assert response.get_json()["error_type"] == "data_validation_errors"
    assert calls == []
    for record in records:
        assert load_tracking_record(_config(tmp_path), record.tracking_id).status == "PENDING_SUBMIT"


def test_batch_defaults_to_continue_tracking(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection, records = _seed_records(tmp_path, 1)
    _patch_submit_one(monkeypatch, [{"success": True, "ab_subscription_id": "sub-1"}])

    response = _post(client, _batch_body(connection, records))

    assert response.status_code == 200
    config = _config(tmp_path)
    stored = load_tracking_record(config, records[0].tracking_id)
    assert load_tracking_operation(config, stored.current_operation_id).submission_mode == (
        "CONTINUE_TRACKING"
    )

class _EmptyListAbResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _EmptyListAbResponse:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None


class _EmptyListAbOpener:
    """A verified 3.1.18 session whose list endpoints answer ``[]`` in bytes."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def open(self, request: Any, timeout: float) -> _EmptyListAbResponse:
        path = urlsplit(request.full_url).path
        self.calls.append(f"{request.get_method()} {path}")
        if path == "/api/v1/auth/login":
            return _EmptyListAbResponse(b'{"access_token": "ab-session"}')
        if path == "/api/v1/status":
            return _EmptyListAbResponse(b'{"version": "3.1.18"}')
        if path == "/api/v1/rss/subscribe":
            return _EmptyListAbResponse(b'{"status": true}')
        if path in ("/api/v1/bangumi/get/all", "/api/v1/rss"):
            return _EmptyListAbResponse(b"[]")
        raise AssertionError(f"unexpected Auto Bangumi path: {path}")  # pragma: no cover


def test_batch_single_miss_on_a_real_bare_list_keeps_every_item_pending(
    tmp_path: Path,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #182: batch shares the single-item rule through the real decoder.

    Two independent writes succeed, the real list endpoints answer a legal bare
    empty array, and one miss per item stays 结果待确认 instead of turning into a
    safely retryable failure.
    """
    connection, records = _seed_records(tmp_path, 2)
    opener = _EmptyListAbOpener()
    monkeypatch.setattr(
        "ab_engine.controllers.ab_http_client.build_opener", lambda *handlers: opener
    )

    response = _post(client, _batch_body(connection, records))

    assert response.status_code == 200
    items = response.get_json()["result"]["items"]
    assert len(items) == 2
    assert all(item["ok"] is False for item in items)
    for entry in items:
        assert entry["result"]["outcome"] == TRACKING_STATUS_VERIFYING_EXTERNAL
        assert entry["result"]["failure_category"] == "OUTCOME_UNKNOWN"
        assert entry["result"]["tracking"]["status"] == TRACKING_STATUS_VERIFYING_EXTERNAL
    for record in records:
        stored = load_tracking_record(_config(tmp_path), record.tracking_id)
        assert stored.external_mapping is None
        assert stored.last_error is not None
        assert stored.last_error.get("reason_code") == "NOT_FOUND"
    assert opener.calls.count("POST /api/v1/rss/subscribe") == 2
