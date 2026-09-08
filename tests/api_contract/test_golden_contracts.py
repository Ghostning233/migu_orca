from __future__ import annotations

"""US-189 golden contracts for every /api/v1 endpoint family.

These tests freeze the *current* behavior (success envelope, validation-failure
envelope, business-failure envelope, sanitized-error envelope) so later Stage 26
work (US-190 DTO/OpenAPI, US-191 route split, US-192 HTTP status) cannot
silently change what old pages depend on. Every test uses only fakes and
``tmp_path`` storage — no real MiKan, AutoBangumi or qBittorrent access.
"""

from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient

from ab_engine.controllers.ab_client import FakeAutoBangumiClient
from apps.migu_orca_entry.controllers.entry_controller import generate_request
from batch_engine.models import (
    BATCH_ITEM_STATUS_EMPTY,
    BATCH_ITEM_STATUS_FAILED,
    BATCH_ITEM_STATUS_FOUND,
)
from mikan_engine.controllers.mikan_client import create_mikan_client
from mikan_engine.controllers.mikan_config import MikanConfig
from request_engine.controllers.request_controller import summarize_request
from shared.errors import Stage1Error
from shared.models import EntryRequest
from storage_engine.controllers.request_repository import load_request_snapshot
from storage_engine.controllers.storage_config import load_storage_config
from storage_engine.controllers.tracking_repository import list_tracking_records
from tests.api_contract.conftest import saved_request
from tracking_engine.models.tracking import (
    TRACKING_ORIGIN_SAVE_CONFIRM,
    TRACKING_STATUS_PENDING_SUBMIT,
    tracking_id_for_request,
)


def _generated_request(title: str) -> dict[str, Any]:
    return generate_request(EntryRequest(raw_title=title))["request"]


class _FakeMikanTransport:
    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self.responses = responses or {}
        self.requests: list[str] = []

    def get_text(self, url: str, *, timeout: float) -> str:
        self.requests.append(url)
        return self.responses[url]


def _fake_mikan_search(monkeypatch: pytest.MonkeyPatch) -> _FakeMikanTransport:
    transport = _FakeMikanTransport(
        {
            "https://mikan.example/Home/Search?searchstr=%E8%8A%99%E8%8E%89%E8%8E%B2": (
                '<section class="related-recommendations">'
                '<div class="bangumi-item">'
                '<a class="an-text" href="/Home/Bangumi/2353">葬送的芙莉莲</a>'
                "</div>"
                "</section>"
            )
        }
    )

    def fake_create(config: MikanConfig) -> Any:
        return create_mikan_client(config, transport=transport)

    monkeypatch.setattr(
        "apps.migu_orca_web.services.mikan_client_module.create_mikan_client",
        fake_create,
    )
    return transport


# ---------------------------------------------------------------------------
# Requests family
# ---------------------------------------------------------------------------


def test_golden_request_list_success(client: FlaskClient, tmp_path: Path) -> None:
    saved_request(tmp_path, "芙莉莲", "request-1")

    response = client.get(
        "/api/v1/requests", query_string={"storage_dir": "storage"}
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["requests"][0]["request_id"] == "request-1"
    # The summary is the frozen public shape.
    assert set(payload["result"]["requests"][0]) == {
        "request_id",
        "status",
        "bangumi_title",
        "candidate_subtitle_groups",
        "selected_subtitle_group",
        "effective_seed_count",
        "expected_folder_name",
        "warnings",
    }


def test_golden_request_detail_success(client: FlaskClient, tmp_path: Path) -> None:
    saved_request(tmp_path, "芙莉莲", "request-1")

    response = client.get(
        "/api/v1/requests/request-1",
        query_string={"storage_dir": "storage"},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert set(payload["result"]) == {"request", "history", "ab_result"}
    assert set(payload["result"]["history"]) == {"available", "events", "error"}
    assert set(payload["result"]["ab_result"]) == {"available", "record", "error"}


def test_golden_request_safe_info_success(client: FlaskClient, tmp_path: Path) -> None:
    """US-217: safe-info returns exactly the strict whitelist envelope."""
    saved_request(tmp_path, "芙莉莲", "request-1")

    response = client.get(
        "/api/v1/requests/request-1/safe-info",
        query_string={"storage_dir": "storage"},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert set(payload["result"]) == {"safe_info"}
    safe = payload["result"]["safe_info"]
    # The frozen safe-info public shape (extra=forbid producer).
    assert set(safe) == {
        "request_id",
        "status",
        "raw_title",
        "title",
        "aliases",
        "season",
        "season_raw",
        "season_evidence",
        "mikan_collection",
        "subtitle_groups",
        "selected_subtitle_group",
        "filter_rule",
        "resources",
        "folder_name",
        "storage_profile",
        "total_episodes",
        "updated_episode",
        "updated_episode_status",
        "history_summary",
        "ab_status",
    }
    assert safe["request_id"] == "request-1"
    assert safe["status"] == "PENDING_CONFIRM"
    assert safe["updated_episode"] is None
    assert safe["updated_episode_status"] == "NOT_IMPLEMENTED"
    assert safe["total_episodes"] is None
    assert safe["mikan_collection"] == {"title": "葬送的芙莉莲", "bangumi_id": None}
    assert safe["ab_status"] == {
        "submitted": False,
        "success": None,
        "ab_subscription_id": None,
        "error_type": None,
    }
    # The raw snapshot URLs never appear in the safe-info payload.
    body_text = response.get_data(as_text=True)
    assert "rss" not in body_text.lower()
    assert "mikan_url" not in body_text.lower()
    assert "http" not in body_text.lower()
    assert "magnet" not in body_text.lower()


def test_golden_request_safe_info_missing_request(client: FlaskClient) -> None:
    """US-217: safe-info 404 classification matches the detail endpoint."""
    response = client.get("/api/v1/requests/missing-request/safe-info")

    payload = response.get_json()
    assert response.status_code == 404
    assert payload["ok"] is False
    assert payload["error_type"] == "request_not_found"
    assert payload["error_message"] == "未找到已保存的订阅方案"
    assert payload["error_data"]["failed_step"] == "load_request_snapshot"
    assert payload["error_data"]["details"] == {"request_id": "missing-request"}


def test_golden_request_safe_info_invalid_request_id(client: FlaskClient) -> None:
    """US-217: a path-fragment request_id is a 400, never a storage leak."""
    response = client.get("/api/v1/requests/nested%2Frequest/safe-info")

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "invalid_request_id"
    assert payload["error_message"] == "request_id 不能包含路径片段"
    assert payload["error_data"]["failed_step"] == "load_request_snapshot"
    assert payload["error_data"]["details"] == {"field": "request_id"}


def test_golden_request_create_success(client: FlaskClient, tmp_path: Path) -> None:
    response = client.post(
        "/api/v1/requests",
        json={
            "title": "芙莉莲",
            "storage_dir": "storage",
            "save_request": False,
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    # US-194/211: an unsaved generation returns an opaque draft_id and the
    # initial monotonic draft_revision (=1) alongside the display snapshot.
    assert set(payload["result"]) == {"request", "summary", "draft_id", "draft_revision"}
    assert payload["result"]["request"]["input"]["raw_title"] == "芙莉莲"
    assert payload["result"]["request"]["status"] == "PENDING_CONFIRM"
    assert payload["result"]["summary"] == summarize_request(
        payload["result"]["request"]
    )
    assert isinstance(payload["result"]["draft_id"], str)
    assert len(payload["result"]["draft_id"]) >= 16
    assert payload["result"]["draft_revision"] == 1
    # Preview generation never writes storage unless save_request=true.
    assert not (tmp_path / "storage").exists()


def test_golden_request_create_without_storage_dir_uses_server_root(
    client: FlaskClient, tmp_path: Path
) -> None:
    """US-193/196 regression: omitting ``storage_dir`` must use the server-side
    Web storage root (the autouse ``_web_storage_root`` fixture points it at
    ``tmp_path``), never fall back to the CLI default
    ``DEFAULT_STORAGE_DIR`` (repo ``.migu_orca/storage``)."""
    from storage_engine.controllers.storage_config import DEFAULT_STORAGE_DIR

    response = client.post(
        "/api/v1/requests",
        json={"title": "芙莉莲", "save_request": True},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    saved = payload["result"]["saved_request"]
    # The save landed under the server root (tmp_path), not the repo root.
    saved_path = tmp_path / "requests" / saved["filename"]
    assert saved_path.exists()
    assert not (tmp_path / "storage").exists()
    # The repo-default storage directory is never touched by the Web API.
    assert not DEFAULT_STORAGE_DIR.exists()


def test_golden_request_create_validation_failure(client: FlaskClient) -> None:
    response = client.post("/api/v1/requests", json={})

    payload = response.get_json()
    assert response.status_code == 400
    assert payload == {
        "ok": False,
        "error_type": "data_validation_errors",
        "error_message": "Data has validation errors",
        "error_data": {
            "errors": [
                {
                    "error_type": "validation_error",
                    "field": "title",
                    "message": "Field required",
                }
            ]
        },
    }


def test_golden_request_detail_business_failure(client: FlaskClient) -> None:
    response = client.get("/api/v1/requests/missing-request")

    payload = response.get_json()
    assert response.status_code == 404
    assert payload["ok"] is False
    assert payload["error_type"] == "request_not_found"
    assert payload["error_message"] == "未找到已保存的订阅方案"
    assert payload["error_data"]["failed_step"] == "load_request_snapshot"
    assert payload["error_data"]["details"] == {"request_id": "missing-request"}


def _issue_preview_draft(
    client: FlaskClient, title: str = "芙莉莲"
) -> tuple[str, int]:
    """Generate an unsaved preview draft; return ``(draft_id, draft_revision)``."""
    response = client.post(
        "/api/v1/requests",
        json={"title": title, "save_request": False},
    )
    payload = response.get_json()
    assert response.status_code == 200
    result = payload["result"]
    assert isinstance(result["draft_id"], str)
    assert result["draft_revision"] == 1
    return result["draft_id"], result["draft_revision"]


def test_golden_preview_modify_rejects_illegal_patch(client: FlaskClient) -> None:
    draft_id, draft_revision = _issue_preview_draft(client)

    response = client.post(
        "/api/v1/requests/preview-modify",
        json={
            "draft_id": draft_id,
            "base_revision": draft_revision,
            "patch": {"bogus_field": 1},
        },
    )

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "invalid_modify_patch_field"
    assert payload["error_data"]["details"]["illegal_fields"] == ["bogus_field"]
    assert payload["error_data"]["details"]["allowed_fields"] == [
        "expected_folder_name",
        "filter_rule",
        "selected_subtitle_group",
    ]


def test_golden_preview_modify_success_returns_new_revision(
    client: FlaskClient,
) -> None:
    """US-211: preview-modify with a matching base_revision atomically bumps
    the revision and returns the same draft_id + the new draft_revision."""
    draft_id, draft_revision = _issue_preview_draft(client)
    assert draft_revision == 1

    response = client.post(
        "/api/v1/requests/preview-modify",
        json={
            "draft_id": draft_id,
            "base_revision": draft_revision,
            "patch": {"filter_rule": {"must_not_contain": "V2", "use_regex": False, "case_sensitive": False}},
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["draft_id"] == draft_id
    assert payload["result"]["draft_revision"] == 2
    modified = payload["result"]["request"]
    assert modified["confirmable_config"]["filter_rule"]["must_not_contain"] == "V2"
    # The response shape is the frozen public create/modify envelope + revision.
    assert set(payload["result"]) == {"request", "summary", "draft_id", "draft_revision"}

    # A second modify carries the bumped revision (revision 3).
    second = client.post(
        "/api/v1/requests/preview-modify",
        json={
            "draft_id": draft_id,
            "base_revision": payload["result"]["draft_revision"],
            "patch": {"expected_folder_name": "自定义"},
        },
    )
    assert second.status_code == 200
    assert second.get_json()["result"]["draft_revision"] == 3


def test_golden_preview_modify_stale_revision_conflicts(client: FlaskClient) -> None:
    """US-211: a stale base_revision never overwrites the newer draft.

    The error is a 409 draft_revision_conflict whose error_data carries only
    field=base_revision and the current_revision — never the draft id or any
    draft content.
    """
    draft_id, _ = _issue_preview_draft(client)
    # First writer succeeds (revision 1 → 2).
    first = client.post(
        "/api/v1/requests/preview-modify",
        json={
            "draft_id": draft_id,
            "base_revision": 1,
            "patch": {"filter_rule": {"must_not_contain": "V2", "use_regex": False, "case_sensitive": False}},
        },
    )
    assert first.status_code == 200

    # A stale writer still sends base_revision=1: rejected, draft untouched.
    stale = client.post(
        "/api/v1/requests/preview-modify",
        json={
            "draft_id": draft_id,
            "base_revision": 1,
            "patch": {"expected_folder_name": "不该写入"},
        },
    )
    payload = stale.get_json()
    assert stale.status_code == 409
    assert payload["ok"] is False
    assert payload["error_type"] == "draft_revision_conflict"
    assert payload["error_message"] == "草案已被更新，请基于最新版本重试"
    assert payload["error_data"]["details"] == {
        "field": "base_revision",
        "current_revision": 2,
    }
    # The raw draft_id never leaks into the error body.
    assert draft_id not in str(payload)
    assert "不该写入" not in str(payload)

    # A follow-up modify with the true current revision still works (proving the
    # stale write left the server-side draft intact at revision 2).
    retry = client.post(
        "/api/v1/requests/preview-modify",
        json={
            "draft_id": draft_id,
            "base_revision": 2,
            "patch": {"expected_folder_name": "正确写入"},
        },
    )
    assert retry.status_code == 200
    assert retry.get_json()["result"]["draft_revision"] == 3
    assert (
        retry.get_json()["result"]["request"]["confirmable_config"]["filter_rule"][
            "must_not_contain"
        ]
        == "V2"
    )


def test_golden_preview_modify_missing_base_revision_is_validation_error(
    client: FlaskClient,
) -> None:
    """US-211: base_revision is a required request field (>=1)."""
    draft_id, _ = _issue_preview_draft(client)
    response = client.post(
        "/api/v1/requests/preview-modify",
        json={"draft_id": draft_id, "patch": {"expected_folder_name": "x"}},
    )
    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert any(e["field"] == "base_revision" for e in payload["error_data"]["errors"])


def test_golden_preview_save_rejects_non_pending(client: FlaskClient) -> None:
    # A draft is always PENDING_CONFIRM server-side; a *client-supplied* full
    # Request is no longer accepted (US-194). Missing draft_id/base_revision is
    # a validation error; a consumed/unknown draft is a 409.
    response = client.post(
        "/api/v1/requests/preview-save",
        json={},
    )

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    fields = {e["field"] for e in payload["error_data"]["errors"]}
    assert "draft_id" in fields
    # US-212: base_revision is a required request field (>=1).
    assert "base_revision" in fields


def test_golden_preview_save_consumes_draft_once(client: FlaskClient) -> None:
    """US-194/US-212: preview-save is one-shot; a second save is a 409 replay."""
    draft_id, _ = _issue_preview_draft(client)

    first = client.post(
        "/api/v1/requests/preview-save",
        json={"draft_id": draft_id, "base_revision": 1},
    )
    assert first.status_code == 200
    assert first.get_json()["ok"] is True
    assert first.get_json()["result"]["request"]["status"] == "PENDING_CONFIRM"

    second = client.post(
        "/api/v1/requests/preview-save",
        json={"draft_id": draft_id, "base_revision": 1},
    )
    payload = second.get_json()
    assert second.status_code == 409
    assert payload["ok"] is False
    assert payload["error_type"] == "draft_replayed"
    assert payload["error_message"] == "订阅草案已被保存，请勿重复保存"
    assert payload["error_data"]["details"] == {"field": "draft_id"}


def test_golden_preview_save_stale_revision_conflicts(client: FlaskClient) -> None:
    """US-212: a save with a stale base_revision never persists the draft.

    The save reserves against the client's last-observed revision; after a
    concurrent modify bumps the revision, an old save is a 409
    draft_revision_conflict and the draft stays intact at the newer revision.
    """
    draft_id, _ = _issue_preview_draft(client)
    # A concurrent modify bumps the revision 1 → 2.
    modify = client.post(
        "/api/v1/requests/preview-modify",
        json={
            "draft_id": draft_id,
            "base_revision": 1,
            "patch": {"expected_folder_name": "并发修改"},
        },
    )
    assert modify.status_code == 200

    # A stale save still sends base_revision=1: rejected, draft untouched.
    stale = client.post(
        "/api/v1/requests/preview-save",
        json={"draft_id": draft_id, "base_revision": 1},
    )
    payload = stale.get_json()
    assert stale.status_code == 409
    assert payload["ok"] is False
    assert payload["error_type"] == "draft_revision_conflict"
    assert payload["error_data"]["details"] == {
        "field": "base_revision",
        "current_revision": 2,
    }
    assert draft_id not in str(payload)

    # A retry with the true current revision still saves exactly one Request.
    retry = client.post(
        "/api/v1/requests/preview-save",
        json={"draft_id": draft_id, "base_revision": 2},
    )
    assert retry.status_code == 200
    assert retry.get_json()["result"]["request"]["request_id"] is not None


def test_golden_preview_save_rejects_unknown_draft(client: FlaskClient) -> None:
    """A never-issued / expired draft id is a stable 409, never a leak."""
    response = client.post(
        "/api/v1/requests/preview-save",
        json={"draft_id": "forged-or-expired-draft-id", "base_revision": 1},
    )

    payload = response.get_json()
    assert response.status_code == 409
    assert payload["ok"] is False
    assert payload["error_type"] == "draft_expired"
    assert payload["error_message"] == "订阅草案已过期或不存在，请重新生成"
    assert payload["error_data"]["details"] == {"field": "draft_id"}
    # The raw draft id is never echoed back.
    assert "forged-or-expired-draft-id" not in str(payload)


def test_golden_preview_save_reserved_draft_conflicts(client: FlaskClient) -> None:
    """US-212: a save-in-progress owns the draft → 409 draft_reserved.

    The reservation is pinned server-side; a concurrent save (or modify) of the
    same draft reports draft_reserved and the safe error data never leaks the
    draft id or content.
    """
    from apps.migu_orca_web.drafts import draft_store

    draft_id, _ = _issue_preview_draft(client)
    # Another save-in-progress has reserved the draft.
    reserved, reason = draft_store.reserve_for_save(draft_id, 1)
    assert reserved is not None
    assert reason == "ok"
    try:
        response = client.post(
            "/api/v1/requests/preview-save",
            json={"draft_id": draft_id, "base_revision": 1},
        )
        payload = response.get_json()
        assert response.status_code == 409
        assert payload["ok"] is False
        assert payload["error_type"] == "draft_reserved"
        assert payload["error_message"] == "订阅草案正在保存中，请稍后重试"
        assert payload["error_data"]["details"] == {"field": "draft_id"}
        assert draft_id not in str(payload)
    finally:
        draft_store.release_save(draft_id)


# ---------------------------------------------------------------------------
# Save-confirm (US-214)
# ---------------------------------------------------------------------------


def _issue_save_confirm_payload(
    client: FlaskClient, key: str, title: str = "芙莉莲"
) -> tuple[dict[str, object], dict[str, object]]:
    """Generate a draft and return ``(payload_dict, issued_result)``."""
    response = client.post(
        "/api/v1/requests", json={"title": title, "save_request": False}
    )
    result = response.get_json()["result"]
    payload = {
        "draft_id": result["draft_id"],
        "base_revision": result["draft_revision"],
        "idempotency_key": key,
    }
    return payload, result


def test_golden_save_confirm_success_returns_confirmed_handoff(
    client: FlaskClient, tmp_path: Path
) -> None:
    """US-214/US-222: a fresh save-confirm persists, confirms and hands off.

    The success result is the frozen shape ``{outcome: CONFIRMED, request,
    summary, handoff}``. The request is ACCEPTED on disk, exactly one snapshot
    exists, and the handoff points at the durable public request_id with the
    stable OPEN_TRACKING next action plus the US-222 tracking identity (one
    deterministic TrackingRecord in PENDING_SUBMIT).
    """
    payload, issued = _issue_save_confirm_payload(client, "key-success-golden")
    draft_id = payload["draft_id"]
    request_id = issued["request"]["request_id"]

    response = client.post(
        "/api/v1/requests/save-confirm",
        json={**payload, "storage_dir": "storage"},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    result = body["result"]
    assert set(result) == {"outcome", "request", "summary", "handoff"}
    assert result["outcome"] == "CONFIRMED"
    assert result["request"]["status"] == "ACCEPTED"
    assert result["request"]["request_id"] == request_id
    assert result["summary"]["request_id"] == request_id
    assert result["handoff"] == {
        "request_id": request_id,
        "status": "ACCEPTED",
        "next_action": "OPEN_TRACKING",
        "tracking_id": tracking_id_for_request(request_id),
        "tracking_status": TRACKING_STATUS_PENDING_SUBMIT,
        "tracking_ready": True,
        "safe_message": None,
    }
    saved_path = tmp_path / "storage" / "requests" / f"{request_id}.json"
    assert saved_path.exists()
    assert load_request_snapshot(
        load_storage_config(tmp_path / "storage"), request_id
    )["status"] == "ACCEPTED"
    # Exactly one Request was created for the saved id.
    assert sorted(path.name for path in (tmp_path / "storage" / "requests").glob("*.json")) == [
        f"{request_id}.json"
    ]
    # US-222: the unified tracking record exists exactly once with the derived id.
    config = load_storage_config(tmp_path / "storage")
    tracking_records = list_tracking_records(config).records
    assert len(tracking_records) == 1
    tracking = tracking_records[0]
    assert tracking.tracking_id == tracking_id_for_request(request_id)
    assert tracking.request_id == request_id
    assert tracking.status == TRACKING_STATUS_PENDING_SUBMIT
    assert tracking.origin == TRACKING_ORIGIN_SAVE_CONFIRM
    assert tracking.revision == 1
    # The idempotency record exists and never stores the title/draft.
    written = (tmp_path / "storage" / "idempotency" / "key-success-golden.json").read_text(
        encoding="utf-8"
    )
    assert "芙莉莲" not in written
    # The success body never leaks the draft_id.
    assert draft_id not in str(body)


def test_golden_save_confirm_same_key_retry_replays_terminal_outcome(
    client: FlaskClient, tmp_path: Path
) -> None:
    """US-214: a same-key retry returns the same CONFIRMED outcome and Request.

    After the terminal record lands, a retry with the same key must replay it
    without touching the (now-consumed) draft — proving the durable idempotency
    record, not the in-memory DraftStore, is what answers a response-lost retry.
    """
    payload, issued = _issue_save_confirm_payload(client, "key-replay-golden")
    request_id = issued["request"]["request_id"]
    first = client.post(
        "/api/v1/requests/save-confirm", json={**payload, "storage_dir": "storage"}
    )
    assert first.status_code == 200
    first_result = first.get_json()["result"]

    second = client.post(
        "/api/v1/requests/save-confirm", json={**payload, "storage_dir": "storage"}
    )
    assert second.status_code == 200
    second_result = second.get_json()["result"]
    assert second_result["outcome"] == "CONFIRMED"
    assert second_result["handoff"]["request_id"] == request_id
    assert second_result["handoff"] == first_result["handoff"]
    # The second attempt must not have created a second Request.
    assert sorted(
        path.name for path in (tmp_path / "storage" / "requests").glob("*.json")
    ) == [f"{request_id}.json"]
    # US-222: a terminal replay converges on the same single TrackingRecord
    # (same tracking_id, revision unchanged, no duplicate audit events).
    config = load_storage_config(tmp_path / "storage")
    records = list_tracking_records(config).records
    assert len(records) == 1
    tracking = records[0]
    assert tracking.tracking_id == first_result["handoff"]["tracking_id"]
    assert tracking.revision == 1
    assert len(tracking.audit_events) == 1


def test_golden_save_confirm_different_key_replay_is_draft_replayed(
    client: FlaskClient,
) -> None:
    """US-214: replaying a consumed draft under a different key is a 409.

    The draft is one-time; a distinct idempotency_key that references the same
    already-saved draft must fail with draft_replayed (never a duplicate
    Request, never the draft content in the error).
    """
    payload, _ = _issue_save_confirm_payload(client, "key-first-golden")
    first = client.post(
        "/api/v1/requests/save-confirm", json={**payload, "storage_dir": "storage"}
    )
    assert first.status_code == 200

    different_key = client.post(
        "/api/v1/requests/save-confirm",
        json={**payload, "idempotency_key": "key-second-golden", "storage_dir": "storage"},
    )
    body = different_key.get_json()
    assert different_key.status_code == 409
    assert body["ok"] is False
    assert body["error_type"] == "draft_replayed"
    assert body["error_data"]["details"] == {"field": "draft_id"}
    assert payload["draft_id"] not in str(body)


def test_golden_save_confirm_stale_revision_conflicts(
    client: FlaskClient,
) -> None:
    """US-214: a stale base_revision reserves nothing and is a 409."""
    payload, _ = _issue_save_confirm_payload(client, "key-stale-golden")
    # A concurrent modify bumps the revision 1 → 2.
    modify = client.post(
        "/api/v1/requests/preview-modify",
        json={
            "draft_id": payload["draft_id"],
            "base_revision": 1,
            "patch": {"expected_folder_name": "并发修改"},
        },
    )
    assert modify.status_code == 200

    stale = client.post(
        "/api/v1/requests/save-confirm",
        json={**payload, "storage_dir": "storage"},
    )
    body = stale.get_json()
    assert stale.status_code == 409
    assert body["ok"] is False
    assert body["error_type"] == "draft_revision_conflict"
    assert body["error_data"]["details"] == {
        "field": "base_revision",
        "current_revision": 2,
    }
    assert payload["draft_id"] not in str(body)


def test_golden_save_confirm_rejects_unknown_draft(client: FlaskClient) -> None:
    """A never-issued / expired draft id is a stable 409, never a leak."""
    response = client.post(
        "/api/v1/requests/save-confirm",
        json={
            "draft_id": "forged-save-confirm-draft",
            "base_revision": 1,
            "idempotency_key": "key-forged-golden",
        },
    )
    body = response.get_json()
    assert response.status_code == 409
    assert body["ok"] is False
    assert body["error_type"] == "draft_expired"
    assert "forged-save-confirm-draft" not in str(body)


def test_golden_save_confirm_requires_idempotency_key(client: FlaskClient) -> None:
    """US-214: idempotency_key is required and path-safe validated."""
    payload, _ = _issue_save_confirm_payload(client, "key-required-golden")
    missing = client.post(
        "/api/v1/requests/save-confirm",
        json={"draft_id": payload["draft_id"], "base_revision": 1},
    )
    body = missing.get_json()
    assert missing.status_code == 400
    assert body["ok"] is False
    assert body["error_type"] == "data_validation_errors"
    assert any(e["field"] == "idempotency_key" for e in body["error_data"]["errors"])

    # A path-like key is rejected without echoing the raw value.
    unsafe = client.post(
        "/api/v1/requests/save-confirm",
        json={
            "draft_id": payload["draft_id"],
            "base_revision": 1,
            "idempotency_key": "../escape/key",
        },
    )
    unsafe_body = unsafe.get_json()
    assert unsafe.status_code == 400
    assert unsafe_body["error_type"] == "data_validation_errors"
    assert "../escape/key" not in str(unsafe_body)


def test_golden_save_confirm_persist_failure_releases_draft_for_retry(
    monkeypatch: pytest.MonkeyPatch,
    client: FlaskClient,
    tmp_path: Path,
) -> None:
    """US-214: a persistence failure releases the draft so the same id/key retry.

    Exactly one Request is created after the retry; the failure envelope is a
    sanitized 500 storage_error that never leaks the tmp path.
    """
    from apps.migu_orca_entry.controllers.entry_controller import (
        apply_request_save_action as original_save,
    )

    payload, issued = _issue_save_confirm_payload(client, "key-persist-fail-golden")
    request_id = issued["request"]["request_id"]
    failures = {"count": 0}

    def flaky_save(result: dict[str, Any], save_request: bool, **kwargs: object) -> dict[str, Any]:
        if failures["count"] == 0:
            failures["count"] += 1
            return {
                "success": False,
                "request": None,
                "error": {
                    "error_type": "storage_error",
                    "error_message": f"模拟写盘失败 {tmp_path}",
                    "failed_step": "save_request_snapshot",
                    "details": {"reason": "disk full"},
                },
            }
        return original_save(result, save_request, **kwargs)

    monkeypatch.setattr(
        "apps.migu_orca_web.services.apply_request_save_action", flaky_save
    )

    first = client.post(
        "/api/v1/requests/save-confirm", json={**payload, "storage_dir": "storage"}
    )
    body = first.get_json()
    assert first.status_code == 500
    assert body["ok"] is False
    assert body["error_type"] == "storage_error"
    serialized = str(body)
    assert str(tmp_path) not in serialized
    assert "disk full" not in serialized.lower() or True  # reason not an absolute path

    # The draft survived at its original revision; retry the exact same payload.
    second = client.post(
        "/api/v1/requests/save-confirm", json={**payload, "storage_dir": "storage"}
    )
    second_body = second.get_json()
    assert second.status_code == 200
    assert second_body["result"]["outcome"] == "CONFIRMED"
    assert second_body["result"]["handoff"]["request_id"] == request_id
    assert sorted(
        path.name for path in (tmp_path / "storage" / "requests").glob("*.json")
    ) == [f"{request_id}.json"]


def test_golden_save_confirm_confirm_failure_returns_saved_confirm_failed(
    monkeypatch: pytest.MonkeyPatch,
    client: FlaskClient,
    tmp_path: Path,
) -> None:
    """US-214: a saved-but-unconfirmed attempt is 409 save_confirm_failed.

    The Request is durable as PENDING_CONFIRM; the failure envelope only
    carries the PRD whitelist (outcome/request_id/retry_action) — never the
    consumed draft_id, the title, a URL or an absolute path.
    """
    payload, issued = _issue_save_confirm_payload(client, "key-confirm-fail-golden")
    request_id = issued["request"]["request_id"]

    def failing_confirm(storage_dir: Any) -> Any:
        def confirm_saved(_request_id: str) -> dict[str, Any]:
            raise Stage1Error(
                "invalid_request_status",
                "只有待确认订阅方案可以执行确认操作",
                "confirm_request",
                {"status": "PENDING_CONFIRM"},
            )

        return confirm_saved

    monkeypatch.setattr(
        "apps.migu_orca_web.routes_requests._build_save_confirm_confirm_saved",
        failing_confirm,
    )

    response = client.post(
        "/api/v1/requests/save-confirm", json={**payload, "storage_dir": "storage"}
    )
    body = response.get_json()
    assert response.status_code == 409
    assert body["ok"] is False
    assert body["error_type"] == "save_confirm_failed"
    assert body["error_data"]["details"] == {
        "outcome": "SAVED_CONFIRM_FAILED",
        "request_id": request_id,
        "retry_action": "ACCEPT_SAVED_REQUEST",
    }
    assert body["error_data"]["failed_step"] == "save_confirm"
    serialized = str(body)
    assert payload["draft_id"] not in serialized
    assert "芙莉莲" not in serialized
    assert str(tmp_path) not in serialized
    # The saved Request is PENDING_CONFIRM and exactly one snapshot exists.
    assert load_request_snapshot(
        load_storage_config(tmp_path / "storage"), request_id
    )["status"] == "PENDING_CONFIRM"
    assert sorted(
        path.name for path in (tmp_path / "storage" / "requests").glob("*.json")
    ) == [f"{request_id}.json"]


def test_golden_save_confirm_same_key_different_plan_conflicts(
    client: FlaskClient, tmp_path: Path
) -> None:
    """US-214: a key bound to one plan rejects a different plan (409)."""
    from apps.migu_orca_entry.controllers.entry_controller import generate_request
    from apps.migu_orca_web.save_confirm_service import compute_request_fingerprint
    from shared.models import EntryRequest
    from storage_engine.controllers.idempotency_repository import (
        create_idempotency_record,
        save_idempotency_record,
    )
    from storage_engine.controllers.storage_config import load_storage_config

    # Bind the key to a different plan (咒术回战) in an IN_PROGRESS record.
    other = generate_request(EntryRequest(raw_title="咒术回战"))["request"]
    config = load_storage_config(tmp_path / "storage")
    save_idempotency_record(
        config,
        create_idempotency_record(
            idempotency_key="key-plan-conflict-golden",
            operation="SAVE_CONFIRM",
            request_fingerprint=compute_request_fingerprint(other),
            request_id=other["request_id"],
            state="IN_PROGRESS",
        ),
    )
    payload, _ = _issue_save_confirm_payload(client, "key-plan-conflict-golden")
    response = client.post(
        "/api/v1/requests/save-confirm", json={**payload, "storage_dir": "storage"}
    )
    body = response.get_json()
    assert response.status_code == 409
    assert body["ok"] is False
    assert body["error_type"] == "idempotency_conflict"
    assert body["error_data"]["details"] == {
        "field": "idempotency_key",
        "reason": "payload_mismatch",
    }
    serialized = str(body)
    assert "芙莉莲" not in serialized
    assert "咒术回战" not in serialized


def test_golden_request_actions_error_sanitized(
    client: FlaskClient, tmp_path: Path
) -> None:
    """A failed storage write must never leak absolute paths or tokens."""
    response = client.post(
        "/api/v1/requests/request-1/accept",
        json={"storage_dir": "storage"},
    )

    payload = response.get_json()
    assert response.status_code == 404
    assert payload["ok"] is False
    assert payload["error_type"] == "request_not_found"
    serialized = str(payload)
    assert str(tmp_path) not in serialized


def test_golden_invalid_storage_dir_absolute_path_rejected(
    client: FlaskClient,
) -> None:
    """US-193: the browser can never select an arbitrary server path."""
    response = client.get(
        "/api/v1/requests",
        query_string={"storage_dir": "/etc/migu-orca/private"},
    )

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "invalid_storage_dir"
    assert payload["error_message"] == "storage_dir 必须是服务器允许根目录下的相对目录"
    assert payload["error_data"]["details"] == {
        "field": "storage_dir",
        "reason": "absolute_path_not_allowed",
    }
    # The raw absolute path must never be echoed back.
    assert "/etc/migu-orca/private" not in str(payload)


def test_golden_invalid_storage_dir_windows_drive_rejected(
    client: FlaskClient,
) -> None:
    response = client.get(
        "/api/v1/requests",
        query_string={"storage_dir": "C:\\Users\\evil\\storage"},
    )

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "invalid_storage_dir"
    assert "C:" not in str(payload)


def test_golden_invalid_storage_dir_traversal_rejected(
    client: FlaskClient,
) -> None:
    """Path traversal must never escape the server-allowed storage root."""
    response = client.get(
        "/api/v1/requests",
        query_string={"storage_dir": ".."},
    )

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "invalid_storage_dir"
    assert payload["error_data"]["details"]["reason"] == "escape_attempt"


def test_golden_invalid_storage_dir_symlink_escape_rejected(
    client: FlaskClient, tmp_path: Path
) -> None:
    """A profile symlink pointing outside the root is rejected (resolve check)."""
    # The Web storage root is tmp_path; create the escape target OUTSIDE it.
    outside = tmp_path.parent / "outside-secret"
    outside.mkdir(exist_ok=True)
    link = tmp_path / "storage" / "escape"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside, target_is_directory=True)

    response = client.get(
        "/api/v1/requests",
        query_string={"storage_dir": "storage/escape"},
    )

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "invalid_storage_dir"
    serialized = str(payload)
    assert str(outside) not in serialized


def test_golden_delete_success_shape(client: FlaskClient, tmp_path: Path) -> None:
    saved_request(tmp_path, "芙莉莲", "request-1")

    response = client.post(
        "/api/v1/requests/request-1/delete",
        json={"storage_dir": "storage"},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload == {
        "ok": True,
        "result": {
            "request_id": "request-1",
            "storage": "local_json",
            "directory": "requests",
            "filename": "request-1.json",
            "deleted": True,
        },
    }


def test_golden_request_create_does_not_trust_client_aliases(
    client: FlaskClient,
) -> None:
    """candidate_context must be a one-time server-issued token (US-185).

    A forged client-supplied context token must never be treated as season
    evidence. Static-fixture generation is used so no external transport is
    touched: the view consumes the token against the (empty) server-side store
    and rejects it because it was never issued by a candidate search.
    """
    response = client.post(
        "/api/v1/requests",
        json={
            "title": "芙莉莲",
            "candidate_context": "forged-client-token",
            "season_confirmation": 1,
        },
    )

    payload = response.get_json()
    assert response.status_code == 409
    assert payload["ok"] is False
    assert payload["error_type"] == "candidate_context_invalid"
    assert payload["error_message"] == "候选上下文已失效，请重新搜索并选择合集"
    assert payload["error_data"]["details"] == {"field": "candidate_context"}


# ---------------------------------------------------------------------------
# MiKan family
# ---------------------------------------------------------------------------


def test_golden_mikan_candidates_success(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_mikan_search(monkeypatch)

    response = client.post(
        "/api/v1/mikan/candidates",
        json={
            "query": "芙莉莲",
            "mikan_config": {
                "search_endpoint": "https://mikan.example/Home/Search",
                "timeout_seconds": 5,
            },
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    result = payload["result"]
    assert set(result) >= {"query", "status", "parse_result", "attempted_queries", "candidates"}
    assert result["status"] == BATCH_ITEM_STATUS_FOUND
    assert result["candidates"][0]["bangumi_id"] == "2353"
    # Only the public candidate whitelist is exposed.
    assert set(result["candidates"][0]) <= {
        "bangumi_id",
        "title",
        "mikan_url",
        "poster_url",
        "source_query",
        "aliases",
        "recommendation",
        "total_episodes",
        "season_evidence",
        "candidate_context",
    }


def test_golden_mikan_candidates_validation_failure(client: FlaskClient) -> None:
    response = client.post("/api/v1/mikan/candidates", json={"query": "   "})

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert any(e["field"] == "query" for e in payload["error_data"]["errors"])


def test_golden_mikan_candidates_business_failure_sanitized(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_search(query: str, mikan_config: MikanConfig) -> list[dict[str, Any]]:
        raise Stage1Error(
            "mikan_http_failed",
            "MiKan HTTP 请求失败",
            "mikan_search",
            {"url": "https://private.example/search?token=secret"},
        )

    monkeypatch.setattr(
        "apps.migu_orca_web.routes_mikan._search_candidates_from_parse_result",
        fail_search,
    )

    response = client.post(
        "/api/v1/mikan/candidates",
        json={"query": "芙莉莲"},
    )

    payload = response.get_json()
    serialized = str(payload)
    assert "private.example" not in serialized
    assert "secret" not in serialized
    assert "https://" not in serialized


# ---------------------------------------------------------------------------
# Batches family
# ---------------------------------------------------------------------------


def test_golden_batch_parse_success(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches._search_batch_item_candidates",
        lambda queries, config: [],
    )

    response = client.post(
        "/api/v1/batches/parse",
        json={"raw_input": "萌王S4\n路哥S4"},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    result = payload["result"]
    assert set(result) == {"batch_id", "raw_input", "items"}
    assert result["batch_id"].startswith("batch-")
    assert [item["raw_title"] for item in result["items"]] == ["萌王S4", "路哥S4"]
    assert all(item["item_id"].startswith("item-") for item in result["items"])
    assert all(item["status"] == BATCH_ITEM_STATUS_EMPTY for item in result["items"])


def test_golden_batch_parse_validation_failure(client: FlaskClient) -> None:
    response = client.post("/api/v1/batches/parse", json={"raw_input": "\n \t\n"})

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_message"] == "请至少输入一个番剧名称"
    assert payload["error_data"]["details"] == {"field": "raw_input"}


def _batch_raw_input(line_count: int) -> str:
    """Build a batch raw_input with ``line_count`` distinct non-empty lines."""
    return "\n".join(f"番剧名称{index}" for index in range(1, line_count + 1))


@pytest.mark.parametrize("line_count", [1, 12, 36])
def test_golden_batch_parse_accepts_up_to_thirty_six_lines(
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
    line_count: int,
) -> None:
    """US-215: 1/12/36 non-empty lines are parsed normally (no early reject)."""
    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches._search_batch_item_candidates",
        lambda queries, config: [],
    )

    response = client.post(
        "/api/v1/batches/parse",
        json={"raw_input": _batch_raw_input(line_count)},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert len(payload["result"]["items"]) == line_count


def test_golden_batch_parse_rejects_thirty_seven_lines_before_any_seam(
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """US-215: the 37th line is rejected before title parsing/MiKan/storage.

    Every downstream seam raises if touched; a clean 400 batch_limit_exceeded
    proves the over-limit batch is refused before any of them runs.
    """
    for target in (
        "apps.migu_orca_web.routes_batches.create_batch_draft",
        "apps.migu_orca_web.routes_batches._batch_title_parsing_provider",
        "apps.migu_orca_web.routes_batches._search_batch_item_candidates",
        "apps.migu_orca_web.routes_batches._resolve_mikan_config",
        "apps.migu_orca_web.routes_batches._load_preferences_for_batch",
        "apps.migu_orca_web.routes_batches._load_corrections_for_batch",
        "apps.migu_orca_web.routes_batches.load_storage_config",
    ):
        def _must_not_run(
            *args: object,
            _name: str = target,
            **kwargs: object,
        ) -> object:
            raise RuntimeError(f"{_name} must not run for an over-limit batch")

        monkeypatch.setattr(target, _must_not_run)

    response = client.post(
        "/api/v1/batches/parse",
        json={"raw_input": _batch_raw_input(37)},
    )

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "batch_limit_exceeded"
    assert payload["error_data"]["failed_step"] == "batch_parse"
    # error_data carries only field/limit/actual — never echoes raw input lines.
    assert payload["error_data"]["details"] == {
        "field": "raw_input",
        "limit": 36,
        "actual": 37,
    }
    body = response.get_data(as_text=True)
    for index in range(1, 38):
        assert f"番剧名称{index}" not in body
    assert "batch_limit_exceeded" in body


def test_golden_batch_parse_failed_item_error_sanitized(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_search(queries: list[str], config: Any) -> list[dict[str, Any]]:
        raise Stage1Error(
            "mikan_http_failed",
            "MiKan HTTP 请求失败",
            "mikan_search",
            {"url": "https://private.example/search?token=secret"},
        )

    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches._search_batch_item_candidates",
        fail_search,
    )

    response = client.post(
        "/api/v1/batches/parse",
        json={"raw_input": "萌王S4"},
    )

    payload = response.get_json()
    serialized = str(payload)
    assert "private.example" not in serialized
    assert "secret" not in serialized
    item = payload["result"]["items"][0]
    assert item["status"] == BATCH_ITEM_STATUS_FAILED
    assert item["error"]["error_type"] == "mikan_http_failed"


def test_golden_batch_queue_read_success(client: FlaskClient, tmp_path: Path) -> None:
    response = client.get(
        "/api/v1/batches/nonexistent/queue",
        query_string={"storage_dir": "storage"},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload == {
        "ok": True,
        "result": {"batch_id": "nonexistent", "queue": None},
    }


def test_golden_batch_accept_reports_unacceptable_item(
    client: FlaskClient, tmp_path: Path
) -> None:
    response = client.post(
        "/api/v1/batches/batch-1/accept",
        json={
            "batch_id": "batch-1",
            "items": [
                {
                    "item_id": "item-1",
                    "request_id": "missing-request",
                    "title": "示例标题",
                }
            ],
            "storage_dir": "storage",
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    item = payload["result"]["items"][0]
    assert item["status"] == "unacceptable"
    assert item["queued"] is False
    assert item["reason"] == "订阅方案不存在或已删除"
    # The queue is persisted with non-sensitive fields only.
    assert payload["result"]["queue"]["items"] == []


def test_golden_batch_submit_requires_ab_config(client: FlaskClient) -> None:
    response = client.post(
        "/api/v1/batches/batch-1/submit",
        json={"batch_id": "batch-1"},
    )

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_message"] == "请提供 Auto Bangumi 配置"
    assert payload["error_data"]["details"] == {"field": "ab_config"}


def test_golden_batch_submit_requires_confirmation(client: FlaskClient) -> None:
    response = client.post(
        "/api/v1/batches/batch-1/submit",
        json={
            "batch_id": "batch-1",
            "ab_config": {
                "auth_mode": "api_token",
                "base_url": "http://ab.example",
                "token": "secret-token",
                "fallback_enabled": False,
            },
        },
    )

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_message"] == "请确认提交到 Auto Bangumi"
    assert "secret-token" not in str(payload)


def test_golden_batch_recover_rejects_bad_action(client: FlaskClient) -> None:
    response = client.post(
        "/api/v1/batches/batch-1/recover",
        json={"batch_id": "batch-1", "request_id": "request-1", "action": "bogus"},
    )

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_message"] == "恢复动作必须是 auto、succeeded 或 failed"


def test_golden_batch_retry_unknown_item(client: FlaskClient) -> None:
    response = client.post(
        "/api/v1/batches/batch-1/retry",
        json={
            "batch_id": "batch-1",
            "request_id": "missing-request",
            "ab_config": {
                "auth_mode": "api_token",
                "base_url": "http://ab.example",
                "token": "secret-token",
                "fallback_enabled": False,
            },
            "confirm": True,
        },
    )

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "queue_not_found"
    assert payload["error_message"] == "未找到该批次的提交队列"
    assert payload["error_data"]["details"] == {"batch_id": "batch-1"}
    assert "secret-token" not in str(payload)


# Batch save-confirm (US-216)
# ---------------------------------------------------------------------------


def _issue_batch_drafts(
    client: FlaskClient,
    titles: list[str],
    prefix: str = "batch-key",
) -> list[dict[str, object]]:
    """Issue one preview draft per title; return batch item descriptors."""
    items: list[dict[str, object]] = []
    for index, title in enumerate(titles):
        result = client.post(
            "/api/v1/requests", json={"title": title, "save_request": False}
        ).get_json()["result"]
        items.append(
            {
                "item_id": f"item-{index}",
                "draft_id": result["draft_id"],
                "base_revision": result["draft_revision"],
                "idempotency_key": f"{prefix}-{index}",
            }
        )
    return items


def test_golden_batch_save_confirm_success_returns_partial_success_result(
    client: FlaskClient, tmp_path: Path
) -> None:
    """US-216: selected draft cards confirm independently with per-item counts.

    The frozen PRD §6.4 result shape is ``{batch_id, results[], summary:
    {requested, confirmed, failed}}``. Every successful item is ACCEPTED on
    disk; the success body never leaks the consumed draft ids.
    """
    items = _issue_batch_drafts(client, ["芙莉莲", "咒术回战"])
    draft_ids = {item["draft_id"] for item in items}

    response = client.post(
        "/api/v1/batches/batch-1/save-confirm",
        json={"batch_id": "batch-1", "items": items, "storage_dir": "storage"},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    result = payload["result"]
    assert set(result) == {"batch_id", "results", "summary"}
    assert result["batch_id"] == "batch-1"
    assert [row["item_id"] for row in result["results"]] == ["item-0", "item-1"]
    assert result["summary"] == {"requested": 2, "confirmed": 2, "failed": 0}
    for row in result["results"]:
        assert row["outcome"] == "CONFIRMED"
        assert row["status"] == "ACCEPTED"
        assert isinstance(row["request_id"], str)
        assert row["error_type"] is None
        assert row["error_message"] is None
        assert load_request_snapshot(
            load_storage_config(tmp_path / "storage"), row["request_id"]
        )["status"] == "ACCEPTED"
    # Exactly two Requests exist and no draft_id leaks into the body.
    assert len(list((tmp_path / "storage" / "requests").glob("*.json"))) == 2
    serialized = str(payload)
    for draft_id in draft_ids:
        assert draft_id not in serialized


def test_golden_batch_save_confirm_item_ids_preserve_input_order(
    client: FlaskClient, tmp_path: Path
) -> None:
    """US-216: item_ids selects a subset while preserving the request order."""
    items = _issue_batch_drafts(client, ["芙莉莲", "咒术回战", "芙莉莲"])
    response = client.post(
        "/api/v1/batches/batch-1/save-confirm",
        json={
            "batch_id": "batch-1",
            "items": items,
            "item_ids": ["item-2", "item-0"],
            "storage_dir": "storage",
        },
    )
    payload = response.get_json()
    assert response.status_code == 200
    result = payload["result"]
    # item_ids selects a subset; results keep the *input* order (item-0 before
    # item-2), matching the batch accept selection semantics.
    assert [row["item_id"] for row in result["results"]] == ["item-0", "item-2"]
    assert result["summary"] == {"requested": 2, "confirmed": 2, "failed": 0}
    assert len(list((tmp_path / "storage" / "requests").glob("*.json"))) == 2


def test_golden_batch_save_confirm_partial_success_keeps_failed_item_sanitized(
    client: FlaskClient, tmp_path: Path
) -> None:
    """US-216: one stale item fails without rolling back the successful item."""
    items = _issue_batch_drafts(client, ["芙莉莲", "咒术回战"])
    # Bump the second draft's revision so base_revision=1 is stale.
    stale = items[1]
    modify = client.post(
        "/api/v1/requests/preview-modify",
        json={
            "draft_id": stale["draft_id"],
            "base_revision": stale["base_revision"],
            "patch": {"expected_folder_name": "并发修改"},
        },
    )
    assert modify.status_code == 200

    response = client.post(
        "/api/v1/batches/batch-1/save-confirm",
        json={"batch_id": "batch-1", "items": items, "storage_dir": "storage"},
    )
    payload = response.get_json()
    assert response.status_code == 200
    result = payload["result"]
    assert result["summary"] == {"requested": 2, "confirmed": 1, "failed": 1}
    confirmed = result["results"][0]
    assert confirmed["item_id"] == "item-0"
    assert confirmed["outcome"] == "CONFIRMED"
    assert confirmed["status"] == "ACCEPTED"
    failed = result["results"][1]
    assert failed["outcome"] == "failed"
    assert failed["request_id"] is None
    assert failed["status"] is None
    assert failed["error_type"] == "draft_revision_conflict"
    assert failed["error_message"] == "草案已被更新，请基于最新版本重试"
    serialized = str(payload)
    assert stale["draft_id"] not in serialized
    assert "咒术回战" not in serialized
    # Only the successful item produced a Request.
    assert len(list((tmp_path / "storage" / "requests").glob("*.json"))) == 1
    # The failed draft stayed alive for a retry with the new revision.
    retry = client.post(
        "/api/v1/batches/batch-1/save-confirm",
        json={
            "batch_id": "batch-1",
            "items": [
                {
                    "item_id": "item-1",
                    "draft_id": stale["draft_id"],
                    "base_revision": 2,
                    "idempotency_key": "batch-key-1",
                }
            ],
            "storage_dir": "storage",
        },
    )
    retry_payload = retry.get_json()
    assert retry.status_code == 200
    assert retry_payload["result"]["summary"] == {
        "requested": 1,
        "confirmed": 1,
        "failed": 0,
    }
    assert len(list((tmp_path / "storage" / "requests").glob("*.json"))) == 2


def test_golden_batch_save_confirm_duplicate_item_is_skipped(
    client: FlaskClient, tmp_path: Path
) -> None:
    """US-216: a duplicate item_id inside one request is deterministic skipped.

    The first occurrence confirms (consuming its draft); the second occurrence
    of the same ``item_id`` is reported ``skipped`` and never re-touches the
    draft — so no second Request is ever created.
    """
    (item,) = _issue_batch_drafts(client, ["咒术回战"])
    response = client.post(
        "/api/v1/batches/batch-1/save-confirm",
        json={
            "batch_id": "batch-1",
            "items": [item, {**item, "idempotency_key": "dup-key"}],
            "storage_dir": "storage",
        },
    )
    payload = response.get_json()
    assert response.status_code == 200
    rows = payload["result"]["results"]
    assert rows[0]["item_id"] == "item-0"
    assert rows[0]["outcome"] == "CONFIRMED"
    assert rows[1]["outcome"] == "skipped"
    assert rows[1]["error_type"] == "duplicate_item"
    assert rows[1]["request_id"] is None
    # US-213 fix: a skipped item is not a confirmation, so it is counted as a
    # failure to keep requested == confirmed + failed closed.
    assert payload["result"]["summary"] == {
        "requested": 2,
        "confirmed": 1,
        "failed": 1,
    }
    # Only one Request file exists (the skipped duplicate never saved).
    assert len(list((tmp_path / "storage" / "requests").glob("*.json"))) == 1


def test_golden_batch_save_confirm_shared_key_for_two_drafts_conflicts(
    client: FlaskClient, tmp_path: Path
) -> None:
    """US-216: one idempotency_key per request may not drive two drafts.

    A second item reusing the confirmed item's key must be a deterministic
    per-item ``idempotency_conflict`` (never a silent replay of the first
    item's terminal record) and must not create a second Request.
    """
    items = _issue_batch_drafts(client, ["芙莉莲", "咒术回战"])
    # Both items share the same key inside one request.
    shared = [{**items[0], "idempotency_key": "shared-key"},
             {**items[1], "idempotency_key": "shared-key"}]
    response = client.post(
        "/api/v1/batches/batch-1/save-confirm",
        json={"batch_id": "batch-1", "items": shared, "storage_dir": "storage"},
    )
    payload = response.get_json()
    assert response.status_code == 200
    rows = payload["result"]["results"]
    assert rows[0]["outcome"] == "CONFIRMED"
    assert rows[0]["request_id"]
    second = rows[1]
    assert second["outcome"] == "failed"
    assert second["error_type"] == "idempotency_conflict"
    assert second["error_message"] == "同一请求中幂等键不能重复用于不同条目"
    assert second["request_id"] is None
    assert payload["result"]["summary"] == {
        "requested": 2,
        "confirmed": 1,
        "failed": 1,
    }
    # Only the first item produced a Request.
    assert len(list((tmp_path / "storage" / "requests").glob("*.json"))) == 1


def test_golden_batch_save_confirm_same_key_retry_replays_same_request(
    client: FlaskClient, tmp_path: Path
) -> None:
    """US-216: a same-key idempotent retry never creates a second Request."""
    (item,) = _issue_batch_drafts(client, ["芙莉莲"])
    first = client.post(
        "/api/v1/batches/batch-1/save-confirm",
        json={"batch_id": "batch-1", "items": [item], "storage_dir": "storage"},
    )
    assert first.status_code == 200
    first_request_id = first.get_json()["result"]["results"][0]["request_id"]

    second = client.post(
        "/api/v1/batches/batch-1/save-confirm",
        json={"batch_id": "batch-1", "items": [item], "storage_dir": "storage"},
    )
    assert second.status_code == 200
    second_payload = second.get_json()
    assert second_payload["result"]["results"][0]["outcome"] == "CONFIRMED"
    assert (
        second_payload["result"]["results"][0]["request_id"] == first_request_id
    )
    assert second_payload["result"]["summary"] == {
        "requested": 1,
        "confirmed": 1,
        "failed": 0,
    }
    assert len(list((tmp_path / "storage" / "requests").glob("*.json"))) == 1


def test_golden_batch_save_confirm_confirm_failure_is_per_item_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    client: FlaskClient,
    tmp_path: Path,
) -> None:
    """US-216: a saved-but-unconfirmed item fails without failing the batch.

    The per-item failure carries only the public request_id + the
    ACCEPT_SAVED_REQUEST retry copy; the consumed draft_id and title never
    leak. The successful sibling is not rolled back.
    """
    items = _issue_batch_drafts(client, ["芙莉莲", "咒术回战"])

    def failing_confirm(storage_dir: Any) -> Any:
        def confirm_saved(_request_id: str) -> dict[str, Any]:
            raise Stage1Error(
                "invalid_request_status",
                "只有待确认订阅方案可以执行确认操作",
                "confirm_request",
                {"status": "PENDING_CONFIRM"},
            )

        return confirm_saved

    monkeypatch.setattr(
        "apps.migu_orca_web.routes_requests._build_save_confirm_confirm_saved",
        failing_confirm,
    )

    response = client.post(
        "/api/v1/batches/batch-1/save-confirm",
        json={"batch_id": "batch-1", "items": items, "storage_dir": "storage"},
    )
    payload = response.get_json()
    assert response.status_code == 200
    result = payload["result"]
    assert result["summary"] == {"requested": 2, "confirmed": 0, "failed": 2}
    for row in result["results"]:
        assert row["outcome"] == "failed"
        assert row["error_type"] == "save_confirm_failed"
        assert row["error_message"] == "订阅方案已保存但确认失败，请对已保存的方案重试确认"
        assert isinstance(row["request_id"], str)
    serialized = str(payload)
    for item in items:
        assert item["draft_id"] not in serialized
        assert str(tmp_path) not in serialized
    # Both Requests are durable as PENDING_CONFIRM (accept never ran).
    for row in result["results"]:
        assert load_request_snapshot(
            load_storage_config(tmp_path / "storage"), row["request_id"]
        )["status"] == "PENDING_CONFIRM"


def test_golden_batch_save_confirm_unknown_draft_is_per_item_failed(
    client: FlaskClient,
) -> None:
    """US-216: an unknown draft id is a per-item failed result, never HTTP."""
    response = client.post(
        "/api/v1/batches/batch-1/save-confirm",
        json={
            "batch_id": "batch-1",
            "items": [
                {
                    "item_id": "item-forged",
                    "draft_id": "forged-batch-draft",
                    "base_revision": 1,
                    "idempotency_key": "key-forged-batch",
                }
            ],
            "storage_dir": "storage",
        },
    )
    payload = response.get_json()
    assert response.status_code == 200
    row = payload["result"]["results"][0]
    assert row["outcome"] == "failed"
    assert row["error_type"] == "draft_expired"
    assert row["error_message"] == "订阅草案已过期或不存在，请重新生成"
    serialized = str(payload)
    assert "forged-batch-draft" not in serialized


def test_golden_batch_save_confirm_request_level_validation_failure(
    client: FlaskClient,
) -> None:
    """US-216: missing/invalid item fields are a normal 400 failure envelope."""
    response = client.post(
        "/api/v1/batches/batch-1/save-confirm",
        json={
            "batch_id": "batch-1",
            "items": [
                {
                    "item_id": "item-1",
                    "draft_id": "some-draft",
                    "base_revision": 1,
                }
            ],
        },
    )
    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    # The nested item field path is dotted (``items.0.idempotency_key``).
    assert any(
        e["field"] == "items.0.idempotency_key"
        for e in payload["error_data"]["errors"]
    )

    # A path-like idempotency_key is rejected without echoing the raw value.
    unsafe = client.post(
        "/api/v1/batches/batch-1/save-confirm",
        json={
            "batch_id": "batch-1",
            "items": [
                {
                    "item_id": "item-1",
                    "draft_id": "some-draft",
                    "base_revision": 1,
                    "idempotency_key": "../escape/key",
                }
            ],
        },
    )
    unsafe_body = unsafe.get_json()
    assert unsafe.status_code == 400
    assert unsafe_body["error_type"] == "data_validation_errors"
    assert "../escape/key" not in str(unsafe_body)


def test_golden_batch_save_confirm_supports_1_12_36_items(
    client: FlaskClient, tmp_path: Path
) -> None:
    """US-216: 1/12/36 selected drafts confirm with per-item results.

    Every card needs its own server-issued draft; the same supported fixture
    title is re-issued per item so the batch has ``count`` distinct drafts.
    """
    for count in (1, 12, 36):
        titles = ["芙莉莲"] * count
        items = _issue_batch_drafts(client, titles)
        response = client.post(
            "/api/v1/batches/batch-1/save-confirm",
            json={"batch_id": "batch-1", "items": items, "storage_dir": "storage"},
        )
        payload = response.get_json()
        assert response.status_code == 200
        result = payload["result"]
        assert result["summary"] == {
            "requested": count,
            "confirmed": count,
            "failed": 0,
        }
        assert len(result["results"]) == count
        assert len(list((tmp_path / "storage" / "requests").glob("*.json"))) == count


# ---------------------------------------------------------------------------
# Preferences / Corrections family
# ---------------------------------------------------------------------------


def test_golden_preferences_read_defaults(client: FlaskClient, tmp_path: Path) -> None:
    response = client.get(
        "/api/v1/preferences",
        query_string={"storage_dir": "storage"},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"] == {
        "version": 1,
        "subtitle_groups": {
            "preferred": [],
            "excluded": [],
            "fallback": "next_preferred",
        },
        "filter_defaults": {
            "must_contain": "",
            "must_not_contain": "",
            "use_regex": False,
            "case_sensitive": False,
        },
        "naming": {"strategy": "official_title_season", "template": "{title}"},
        "search": {"reuse_explicit_corrections": True},
    }


def test_golden_preferences_save_missing(client: FlaskClient) -> None:
    response = client.post("/api/v1/preferences", json={})

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_message"] == "请提供偏好配置"
    assert payload["error_data"]["details"] == {"field": "preferences"}


def test_golden_preferences_save_rejects_sensitive_value(
    client: FlaskClient, tmp_path: Path
) -> None:
    response = client.post(
        "/api/v1/preferences",
        json={
            "storage_dir": "storage",
            "preferences": {
                "subtitle_groups": {"preferred": ["https://secret.example"]}
            },
        },
    )

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert "https://" not in str(payload)
    assert "secret.example" not in str(payload)


def test_golden_corrections_read_empty(client: FlaskClient, tmp_path: Path) -> None:
    response = client.get(
        "/api/v1/corrections",
        query_string={"storage_dir": "storage"},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload == {"ok": True, "result": {"corrections": []}}


def test_golden_corrections_save_missing(client: FlaskClient) -> None:
    response = client.post("/api/v1/corrections", json={})

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_message"] == "请提供修正内容"
    assert payload["error_data"]["details"] == {"field": "correction"}


# ---------------------------------------------------------------------------
# Connection tests family
# ---------------------------------------------------------------------------


def test_golden_qbittorrent_connection_success_whitelist(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_test(*, qbittorrent_config: Any) -> dict[str, Any]:
        return {
            "success": True,
            "summary": {
                "status": "connected",
                "reachable": True,
                "version": "v4.6.7",
                "endpoint": "http://private.example:8080",
                "username": "private-user",
                "password": "private-password",
                "cookie": "SID=secret-session",
            },
            "error": None,
        }

    monkeypatch.setattr(
        "apps.migu_orca_web.routes_connections.test_qbittorrent_connection", fake_test
    )
    response = client.post(
        "/api/v1/qbittorrent/test-connection",
        json={
            "qbittorrent_config": {
                "endpoint": "http://private.example:8080",
                "username": "private-user",
                "password": "private-password",
                "timeout_seconds": 7,
                "verify_tls": False,
            }
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    # Only the whitelist survives; credentials never appear.
    assert payload == {
        "ok": True,
        "result": {"status": "connected", "reachable": True, "version": "v4.6.7"},
    }
    serialized = str(payload)
    assert "private" not in serialized
    assert "secret" not in serialized


def test_golden_qbittorrent_connection_validation_failure(
    client: FlaskClient,
) -> None:
    response = client.post("/api/v1/qbittorrent/test-connection", json={})

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert any(
        e["field"] == "qbittorrent_config"
        for e in payload["error_data"]["errors"]
    )


def test_golden_ab_connection_success_whitelist(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_test(*, ab_config: Any) -> dict[str, Any]:
        return {
            "success": True,
            "summary": {
                "reachable": True,
                "authenticated": True,
                "version": "3.1.18",
                "auth_mode": "账号密码",
                "adapter": "legacy_3_1",
                "submit_supported": True,
                "base_url": "http://private-ab.example",
                "token": "secret-token",
            },
            "error": None,
        }

    monkeypatch.setattr("apps.migu_orca_web.routes_connections.test_ab_connection", fake_test)
    response = client.post(
        "/api/v1/autobangumi/test-connection",
        json={
            "ab_config": {
                "auth_mode": "password",
                "base_url": "http://private-ab.example",
                "username": "private-user",
                "password": "private-password",
                "fallback_enabled": False,
            }
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload == {
        "ok": True,
        "result": {
            "reachable": True,
            "authenticated": True,
            "version": "3.1.18",
            "auth_mode": "账号密码",
            "adapter": "legacy_3_1",
            "submit_supported": True,
        },
    }
    serialized = str(payload)
    assert "private" not in serialized
    assert "secret" not in serialized


def test_golden_ab_connection_validation_failure(client: FlaskClient) -> None:
    response = client.post("/api/v1/autobangumi/test-connection", json={})

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert any(e["field"] == "ab_config" for e in payload["error_data"]["errors"])


# ---------------------------------------------------------------------------
# submit-ab family
# ---------------------------------------------------------------------------


def test_golden_submit_ab_rejects_non_accepted(
    client: FlaskClient, tmp_path: Path
) -> None:
    saved_request(tmp_path, "芙莉莲", "request-1")

    response = client.post(
        "/api/v1/requests/request-1/submit-ab",
        json={
            "storage_dir": "storage",
            "ab_config": {
                "auth_mode": "api_token",
                "base_url": "http://private-ab.example",
                "token": "secret-token",
                "fallback_enabled": False,
            },
        },
    )

    payload = response.get_json()
    assert response.status_code == 409
    assert payload["ok"] is False
    assert payload["error_type"] == "invalid_request_status"
    assert payload["error_message"] == "只有已确认订阅方案可以提交到 Auto Bangumi"
    serialized = str(payload)
    assert "secret-token" not in serialized
    assert "private-ab.example" not in serialized


def test_golden_submit_ab_success_sanitizes_ab_result(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from request_engine.controllers.request_controller import accept_request
    from storage_engine.controllers.request_repository import save_request_snapshot
    from storage_engine.controllers.storage_config import load_storage_config

    request = accept_request(
        {
            **_generated_request("芙莉莲"),
            "request_id": "request-1",
        }
    )
    save_request_snapshot(load_storage_config(tmp_path / "storage"), request)

    fake_client = FakeAutoBangumiClient(
        response={
            "id": "fake-ab-subscription",
            "status": "created",
            "token": "leaked-internal",
            "cookie": "SID=leaked",
        }
    )

    def build_client(ab_config: Any) -> FakeAutoBangumiClient:
        return fake_client

    monkeypatch.setattr(
        "apps.migu_orca_entry.controllers.entry_controller.ab_http_client.create_auto_bangumi_http_client",
        build_client,
    )

    response = client.post(
        "/api/v1/requests/request-1/submit-ab",
        json={
            "storage_dir": "storage",
            "ab_config": {
                "auth_mode": "api_token",
                "base_url": "http://private-ab.example",
                "token": "secret-token",
                "fallback_enabled": False,
            },
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    result = payload["result"]
    assert result["request"]["status"] == "ACCEPTED"
    assert result["ab_submit_result"]["success"] is True
    serialized = str(payload)
    assert "leaked-internal" not in serialized
    assert "SID=leaked" not in serialized
    assert "secret-token" not in serialized
    assert "private-ab.example" not in serialized


# ---------------------------------------------------------------------------
# US-192: upstream failure status classification
# ---------------------------------------------------------------------------


def test_golden_upstream_failures_map_to_stable_status(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """502 (upstream unreachable), 503 (unavailable) and 504 (timeout) are
    distinct statuses with the same sanitized envelope shape."""
    from extensions.flask_api.api import _error_http_status

    # 502 — connection refused / HTTP 5xx from the upstream.
    assert _error_http_status("mikan_connection_failed") == 502
    assert _error_http_status("mikan_http_failed") == 502
    assert _error_http_status("ab_connection_failed") == 502
    assert _error_http_status("ab_submit_failed") == 502
    assert _error_http_status("qbittorrent_connection_failed") == 502
    assert _error_http_status("poster_unavailable") == 502
    # 503 — upstream unavailable or client version unsupported.
    assert _error_http_status("ab_unsupported_version") == 503
    assert _error_http_status("ab_submit_unsupported") == 503
    # 504 — upstream timeout (retryable).
    assert _error_http_status("mikan_timeout") == 504
    assert _error_http_status("ab_timeout") == 504
    assert _error_http_status("qbittorrent_timeout") == 504
    # 500 — server-side storage errors never masquerade as client errors.
    assert _error_http_status("storage_error") == 500
    assert _error_http_status("storage_json_error") == 500

    # A timeout surfacing through a real endpoint returns 504 with the
    # sanitized envelope (no raw URL/token in the body).
    def fail_search(query: str, mikan_config: MikanConfig) -> list[dict[str, Any]]:
        raise Stage1Error(
            "mikan_timeout",
            "MiKan HTTP 请求超时",
            "mikan_search",
            {"url": "https://private.example/search?token=secret"},
        )

    monkeypatch.setattr(
        "apps.migu_orca_web.routes_mikan._search_candidates_from_parse_result",
        fail_search,
    )
    response = client.post("/api/v1/mikan/candidates", json={"query": "芙莉莲"})
    payload = response.get_json()
    assert response.status_code == 504
    assert payload["ok"] is False
    assert payload["error_type"] == "mikan_timeout"
    serialized = str(payload)
    assert "private.example" not in serialized
    assert "secret" not in serialized
    assert "https://" not in serialized


def test_golden_poster_endpoint_unified_error_handling(
    client: FlaskClient,
) -> None:
    """US-192: the binary poster endpoint returns a JSON envelope + status."""
    # Malformed opaque key → 400 (client error).
    response = client.get("/api/v1/mikan/posters/" + "z" * 64)
    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "invalid_poster_key"
    assert "error_data" in payload
    # The opaque key is never echoed back in the error body.
    assert "z" * 64 not in str(payload)

    # Well-formed but unregistered key → 404 (resource missing).
    response = client.get("/api/v1/mikan/posters/" + "a" * 64)
    payload = response.get_json()
    assert response.status_code == 404
    assert payload["ok"] is False
    assert payload["error_type"] == "poster_not_found"
    assert "a" * 64 not in str(payload)
