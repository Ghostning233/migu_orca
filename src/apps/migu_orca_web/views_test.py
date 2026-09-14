from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient

from apps.base import create_app
from apps.migu_orca_entry.controllers.entry_controller import generate_request
from batch_engine.controllers.anime_title_parser import FakeAnimeTitleParsingProvider
from batch_engine.models import (
    BATCH_ITEM_STATUS_EMPTY,
    BATCH_ITEM_STATUS_FAILED,
    BATCH_ITEM_STATUS_FOUND,
)
from mikan_engine.controllers.mikan_client import MikanCandidate, create_mikan_client
from mikan_engine.controllers.mikan_config import (
    DEFAULT_MIKAN_SEARCH_ENDPOINT,
    DEFAULT_MIKAN_TIMEOUT_SECONDS,
    MikanConfig,
    default_mikan_config,
)
from mikan_engine.controllers.mikan_poster_cache import poster_cache_key
from request_engine.controllers.request_controller import (
    accept_request,
    cancel_request,
    summarize_request,
)
from shared.errors import Stage1Error
from shared.models import (
    BangumiCandidate,
    EntryRequest,
    FilterDefaults,
    MatchedBangumi,
    NamingPreference,
    RssSource,
    SearchPreference,
    SubtitleGroupPreference,
    VersionedUserPreference,
)
from storage_engine.controllers.ab_result_repository import (
    save_ab_submit_result,
)
from storage_engine.controllers.history_repository import (
    append_status_history,
)
from storage_engine.controllers.idempotency_repository import (
    load_idempotency_record,
)
from storage_engine.controllers.preference_repository import save_user_preferences
from storage_engine.controllers.request_repository import (
    load_request_snapshot,
    save_request_snapshot,
)
from storage_engine.controllers.storage_config import load_storage_config
from storage_engine.controllers.tracking_repository import (
    list_tracking_records,
    load_tracking_record,
)
from tracking_engine.models.tracking import (
    TRACKING_ORIGIN_LEGACY_ACCEPT,
    TRACKING_STATUS_PENDING_SUBMIT,
    tracking_id_for_request,
)


def _client() -> FlaskClient:
    return create_app("testing").test_client()


def _saved_request(tmp_path: Path, title: str, request_id: str) -> dict[str, Any]:
    request = {
        **generate_request(EntryRequest(raw_title=title))["request"],
        "request_id": request_id,
    }
    save_request_snapshot(load_storage_config(tmp_path / "storage"), request)
    return request


def _saved_accepted_request(
    tmp_path: Path,
    title: str = "芙莉莲",
    request_id: str = "request-1",
) -> dict[str, Any]:
    request = accept_request(
        {
            **generate_request(EntryRequest(raw_title=title))["request"],
            "request_id": request_id,
        }
    )
    save_request_snapshot(load_storage_config(tmp_path / "storage"), request)
    return request


def _saved_cancelled_request(
    tmp_path: Path,
    title: str = "芙莉莲",
    request_id: str = "request-cancelled",
) -> dict[str, Any]:
    request = cancel_request(
        {
            **generate_request(EntryRequest(raw_title=title))["request"],
            "request_id": request_id,
        },
        "不需要",
    )
    save_request_snapshot(load_storage_config(tmp_path / "storage"), request)
    return request


@pytest.fixture(autouse=True)
def _clear_candidate_cache() -> None:
    """Reset the shared in-process candidate cache before every view test.

    The candidate search cache is a process-level singleton, so tests that do not
    opt into cache behavior must never observe entries written by earlier tests.
    """
    from mikan_engine.controllers.mikan_candidate_cache import candidate_search_cache

    candidate_search_cache.clear()
    from apps.migu_orca_web.contexts import candidate_selection_contexts

    candidate_selection_contexts.clear()
    from apps.migu_orca_web.drafts import draft_store

    draft_store.clear()


@pytest.fixture(autouse=True)
def _web_storage_root(tmp_path: Path) -> None:
    """US-193: point the Web storage root at the test tmp dir.

    Web API tests pass *relative profile* names (e.g. ``storage``) as
    ``storage_dir``; the server resolves them under this root so absolute
    tmp paths never appear in API payloads/URLs.
    """
    from apps.migu_orca_web.services import set_web_storage_root

    set_web_storage_root(tmp_path)
    yield
    set_web_storage_root(None)


def _profile(tmp_path: Path, name: str = "storage") -> str:
    """Return the relative Web storage profile for a tmp-based storage dir."""
    return name


class _FakeMikanTransport:
    def __init__(self, responses: dict[str, str] | None = None, error: Stage1Error | None = None) -> None:
        self.responses = responses or {}
        self.error = error
        self.requests: list[tuple[str, float]] = []

    def get_text(self, url: str, *, timeout: float) -> str:
        self.requests.append((url, timeout))
        if self.error is not None:
            raise self.error
        if url in self.responses:
            return self.responses[url]
        # Legacy fixtures may key the same public fake page under example hosts;
        # Web always uses the server-owned default mikanani.me host.
        legacy_url = url.replace("https://mikanani.me/", "https://mikan.example/")
        return self.responses[legacy_url]


class _FakeMikanClient:
    def __init__(self, config: MikanConfig, transport: _FakeMikanTransport) -> None:
        self.config = config
        self.transport = transport

    def list_bangumi_candidates(self, raw_title: str) -> list[BangumiCandidate]:
        assert raw_title == "芙莉莲"
        return [
            BangumiCandidate(
                bangumi_id="123",
                title="芙莉莲",
                aliases=["葬送的芙莉莲"],
                mikan_url="https://mikan.example/Home/Bangumi/123",
                rss_sources=[],
            )
        ]

    def list_rss_sources(self, matched_bangumi: MatchedBangumi) -> list[RssSource]:
        assert matched_bangumi.title == "芙莉莲"
        return [
            RssSource(
                subtitle_group="Loli",
                rss_url="https://mikan.example/RSS/Bangumi?bangumiId=123",
                source_type="mikan_http",
                fixture_path="",
            )
        ]


class _FakeCandidateSearchClient:
    def __init__(
        self,
        candidates: list[Any] | None = None,
        error: Stage1Error | None = None,
    ) -> None:
        self.candidates = candidates or []
        self.error = error
        self.searches: list[str] = []

    def search_candidates(self, raw_title: str) -> list[Any]:
        self.searches.append(raw_title)
        if self.error is not None:
            raise self.error
        return self.candidates


class _MappedCandidateSearchClient:
    def __init__(
        self,
        responses: dict[str, list[MikanCandidate]] | None = None,
        errors: dict[str, Stage1Error] | None = None,
    ) -> None:
        self.responses = responses or {}
        self.errors = errors or {}
        self.searches: list[str] = []

    def search_candidates(self, raw_title: str) -> list[MikanCandidate]:
        self.searches.append(raw_title)
        if raw_title in self.errors:
            raise self.errors[raw_title]
        return self.responses.get(raw_title, [])


def test_root_redirects_to_add() -> None:
    """US-259: the default entry redirects / to the public add route."""
    response = _client().get("/")

    assert response.status_code == 302
    assert response.headers["Location"] == "/app/add"


def test_index_redirects_to_spa_add_by_default() -> None:
    """US-259: /index now redirects to the public add route."""
    response = _client().get("/index")

    assert response.status_code == 302
    assert response.headers["Location"] == "/app/add"


def test_index_redirect_preserves_public_query_params() -> None:
    """US-259: only the add route's public batch_id survives the redirect."""
    response = _client().get("/index?request_id=req-1&batch_id=batch-2")

    assert response.status_code == 302
    assert response.headers["Location"] == "/app/add?batch_id=batch-2"


def test_settings_case_redirects_to_settings() -> None:
    """US-208: the default entry redirects /Settings to the SPA Settings page."""
    response = _client().get("/Settings")

    assert response.status_code == 302
    assert response.headers["Location"] == "/app/settings"


def test_settings_redirects_to_spa_settings_by_default() -> None:
    """US-208: /settings now redirects to the SPA Settings page."""
    response = _client().get("/settings")

    assert response.status_code == 302
    assert response.headers["Location"] == "/app/settings"


def test_settings_redirect_preserves_public_request_id() -> None:
    """US-208: the legacy /settings?request_id=<id>#auto-bangumi entry keeps working."""
    response = _client().get("/settings?request_id=req-ab-3")

    assert response.status_code == 302
    assert response.headers["Location"] == "/app/settings?request_id=req-ab-3"


def test_list_requests_returns_empty_list_for_missing_storage_dir(
    tmp_path: Path,
) -> None:
    response = _client().get(
        "/api/v1/requests",
        query_string={"storage_dir": "missing-storage"},
    )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "result": {"requests": []}}


# --- US-193: Web storage root / profile resolution ---


def test_storage_dir_resolver_maps_relative_profile_under_root(
    tmp_path: Path,
) -> None:
    """A relative profile resolves under the server storage root."""
    from apps.migu_orca_web.services import _storage_dir

    resolved = _storage_dir("storage")
    assert resolved == (tmp_path / "storage").resolve()
    # US-193/196: an empty storage_dir means the *server* storage root itself,
    # never ``None`` (which would fall back to the CLI default and bypass the
    # server-controlled Web root).
    assert _storage_dir("") == (tmp_path).resolve()
    assert _storage_dir(None) == (tmp_path).resolve()
    assert _storage_dir("  ") == (tmp_path).resolve()


def test_storage_dir_resolver_rejects_absolute_path(
    tmp_path: Path,
) -> None:
    from apps.migu_orca_web.services import _storage_dir

    for bad in ("/etc/migu-orca", "/tmp/x", "C:\\Users\\evil"):
        with pytest.raises(Stage1Error) as exc_info:
            _storage_dir(bad)
        assert exc_info.value.error_type == "invalid_storage_dir"
        assert exc_info.value.details["reason"] == "absolute_path_not_allowed"
        # The raw value must never leak into the error.
        assert bad not in str(exc_info.value.details)


def test_storage_dir_resolver_rejects_traversal_escape(tmp_path: Path) -> None:
    from apps.migu_orca_web.services import _storage_dir

    for bad in ("..", "../..", "a/../../b", "storage/../../../x"):
        with pytest.raises(Stage1Error) as exc_info:
            _storage_dir(bad)
        assert exc_info.value.error_type == "invalid_storage_dir"
        assert exc_info.value.details["reason"] == "escape_attempt"


def test_storage_dir_resolver_rejects_symlink_escape(tmp_path: Path) -> None:
    from apps.migu_orca_web.services import _storage_dir

    outside = tmp_path.parent / "web-storage-outside"
    outside.mkdir(exist_ok=True)
    link = tmp_path / "storage" / "escape"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(Stage1Error) as exc_info:
        _storage_dir("storage/escape")
    assert exc_info.value.error_type == "invalid_storage_dir"
    assert exc_info.value.details["reason"] == "escape_attempt"


def test_storage_dir_resolver_allows_nested_relative_profile(tmp_path: Path) -> None:
    from apps.migu_orca_web.services import _storage_dir

    resolved = _storage_dir("user-one/deep")
    assert resolved == (tmp_path / "user-one" / "deep").resolve()


def test_web_storage_root_can_be_overridden_server_side(
    tmp_path: Path,
) -> None:
    """Server-side override must not be client-controllable; it is a test seam."""
    from apps.migu_orca_web.services import _storage_dir, set_web_storage_root

    override = tmp_path / "custom-root"
    set_web_storage_root(override)
    try:
        assert _storage_dir("profile") == (override / "profile").resolve()
        with pytest.raises(Stage1Error):
            _storage_dir(str(tmp_path / "other"))
    finally:
        set_web_storage_root(None)


def test_list_requests_returns_saved_request_summaries(tmp_path: Path) -> None:
    request_b = _saved_request(tmp_path, "芙莉莲", "request-b")
    request_a = _saved_request(tmp_path, "咒术回战第三季", "request-a")

    response = _client().get(
        "/api/v1/requests",
        query_string={"storage_dir": "storage"},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "result": {
            "requests": [
                summarize_request(request_a),
                summarize_request(request_b),
            ]
        },
    }


def test_get_request_detail_returns_complete_saved_snapshot(tmp_path: Path) -> None:
    request = _saved_request(tmp_path, "芙莉莲", "request-1")

    response = _client().get(
        "/api/v1/requests/request-1",
        query_string={"storage_dir": "storage"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    result = payload["result"]
    safe_request = result["request"]
    assert set(safe_request) == {
        "request_id",
        "status",
        "input",
        "source_info",
        "confirmable_config",
        "created_at",
        "updated_at",
        "user_action",
    }
    assert safe_request["request_id"] == request["request_id"]
    assert safe_request["input"] == {"raw_title": "芙莉莲"}
    assert set(safe_request["source_info"]["matched_bangumi"]) == {
        "title",
        "aliases",
        "match_score",
    }
    assert set(safe_request["source_info"]["rss_sources"][0]) == {
        "subtitle_group",
        "source_type",
        "total_seed_count",
        "seed_names",
        "valid_seed_count",
        "invalid_seed_count",
        "valid_seed_names",
        "excluded_seed_names",
        "warnings",
    }
    assert safe_request["confirmable_config"]["selected_rss_url"] == "SELECTED"
    assert result["history"] == {"available": True, "events": [], "error": None}
    assert result["ab_result"] == {"available": False, "record": None, "error": None}
    for forbidden in (
        "'mikan_url':",
        "'rss_url':",
        "'ab_response':",
        "'fallback_config':",
    ):
        assert forbidden not in str(payload)


def test_get_request_detail_returns_saved_history_and_ab_result(
    tmp_path: Path,
) -> None:
    request = _saved_request(tmp_path, "芙莉莲", "request-1")
    config = load_storage_config(tmp_path / "storage")
    event = {
        "request_id": "request-1",
        "previous_status": "PENDING_CONFIRM",
        "next_status": "ACCEPTED",
        "action": "ACCEPT",
        "timestamp": "2026-08-06T12:00:00+00:00",
    }
    append_status_history(config, event)
    request["ab_submit_result"] = {
        "success": False,
        "ab_subscription_id": None,
        "ab_response": None,
        "fallback_config": {
            "title": "芙莉莲",
            "rss_url": "https://example.invalid/rss.xml",
            "save_path": "芙莉莲",
        },
        "error": None,
    }
    save_ab_submit_result(config, request)

    response = _client().get(
        "/api/v1/requests/request-1",
        query_string={"storage_dir": "storage"},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["history"] == {
        "available": True,
        "events": [
            {
                "action": "ACCEPT",
                "previous_status": "PENDING_CONFIRM",
                "next_status": "ACCEPTED",
                "timestamp": event["timestamp"],
            }
        ],
        "error": None,
    }
    assert payload["result"]["ab_result"]["available"] is True
    assert payload["result"]["ab_result"]["record"]["request_id"] == "request-1"
    assert payload["result"]["ab_result"]["record"]["ab_submit_result"] == {
        "success": False,
        "ab_subscription_id": None,
        "fallback_config": None,
        "error": None,
    }
    assert "'rss_url':" not in str(payload)
    assert "example.invalid" not in str(payload)


def test_get_request_detail_treats_damaged_history_as_nonfatal(
    tmp_path: Path,
) -> None:
    _saved_request(tmp_path, "芙莉莲", "request-1")
    config = load_storage_config(tmp_path / "storage")
    config.history_dir.mkdir(parents=True, exist_ok=True)
    (config.history_dir / "request-1.json").write_text("{", encoding="utf-8")

    response = _client().get(
        "/api/v1/requests/request-1",
        query_string={"storage_dir": "storage"},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["request"]["request_id"] == "request-1"
    assert payload["result"]["history"]["available"] is False
    assert payload["result"]["history"]["events"] == []
    assert payload["result"]["history"]["error"]["error_type"] == "storage_json_error"
    assert payload["result"]["history"]["error"]["failed_step"] == "load_status_history"
    assert str(tmp_path) not in str(payload)


def test_get_request_detail_treats_damaged_ab_result_as_nonfatal(
    tmp_path: Path,
) -> None:
    _saved_request(tmp_path, "芙莉莲", "request-1")
    config = load_storage_config(tmp_path / "storage")
    config.ab_results_dir.mkdir(parents=True, exist_ok=True)
    (config.ab_results_dir / "request-1.json").write_text("[", encoding="utf-8")

    response = _client().get(
        "/api/v1/requests/request-1",
        query_string={"storage_dir": "storage"},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["request"]["request_id"] == "request-1"
    assert payload["result"]["ab_result"]["available"] is False
    assert payload["result"]["ab_result"]["record"] is None
    assert payload["result"]["ab_result"]["error"]["error_type"] == "storage_json_error"
    assert str(tmp_path) not in str(payload)


def test_get_request_detail_returns_unified_error_for_missing_request(
    tmp_path: Path,
) -> None:
    response = _client().get(
        "/api/v1/requests/missing-request",
        query_string={"storage_dir": "storage"},
    )

    payload = response.get_json()
    assert response.status_code == 404
    assert payload == {
        "ok": False,
        "error_type": "request_not_found",
        "error_message": "未找到已保存的订阅方案",
        "error_data": {
            "failed_step": "load_request_snapshot",
            "details": {"request_id": "missing-request"},
        },
    }
    assert str(tmp_path) not in str(payload)


def test_get_request_detail_rejects_path_fragments_without_leaking_storage_path(
    tmp_path: Path,
) -> None:
    response = _client().get(
        "/api/v1/requests/nested%2Frequest",
        query_string={"storage_dir": "storage"},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload == {
        "ok": False,
        "error_type": "invalid_request_id",
        "error_message": "request_id 不能包含路径片段",
        "error_data": {
            "failed_step": "load_request_snapshot",
            "details": {"field": "request_id"},
        },
    }
    assert str(tmp_path) not in str(payload)


def test_list_requests_returns_unified_error_for_damaged_snapshot(
    tmp_path: Path,
) -> None:
    config = load_storage_config(tmp_path / "storage")
    config.requests_dir.mkdir(parents=True)
    (config.requests_dir / "broken.json").write_text("{", encoding="utf-8")

    response = _client().get(
        "/api/v1/requests",
        query_string={"storage_dir": "storage"},
    )

    payload = response.get_json()
    assert response.status_code == 500
    assert payload["ok"] is False
    assert payload["error_type"] == "storage_json_error"
    assert payload["error_data"]["failed_step"] == "load_request_snapshot"
    assert payload["error_data"]["details"]["request_id"] == "broken"
    assert str(tmp_path) not in str(payload)


def test_delete_request_removes_saved_request_and_refreshes_list_and_detail(
    tmp_path: Path,
) -> None:
    request = _saved_request(tmp_path, "芙莉莲", "request-1")
    storage_dir = tmp_path / "storage"

    response = _client().post(
        f"/api/v1/requests/{request['request_id']}/delete",
        json={"storage_dir": _profile(tmp_path, storage_dir.name)},
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
    assert not (storage_dir / "requests" / "request-1.json").exists()

    list_response = _client().get(
        "/api/v1/requests",
        query_string={"storage_dir": _profile(tmp_path, storage_dir.name)},
    )
    assert list_response.get_json() == {"ok": True, "result": {"requests": []}}

    detail_response = _client().get(
        "/api/v1/requests/request-1",
        query_string={"storage_dir": _profile(tmp_path, storage_dir.name)},
    )
    assert detail_response.get_json() == {
        "ok": False,
        "error_type": "request_not_found",
        "error_message": "未找到已保存的订阅方案",
        "error_data": {
            "failed_step": "load_request_snapshot",
            "details": {"request_id": "request-1"},
        },
    }
    assert str(tmp_path) not in str(payload)


def test_delete_request_returns_unified_error_for_missing_request(
    tmp_path: Path,
) -> None:
    response = _client().post(
        "/api/v1/requests/missing-request/delete",
        json={"storage_dir": "storage"},
    )

    payload = response.get_json()
    assert response.status_code == 404
    assert payload == {
        "ok": False,
        "error_type": "request_not_found",
        "error_message": "未找到已保存的订阅方案",
        "error_data": {
            "failed_step": "delete_request_snapshot",
            "details": {"request_id": "missing-request"},
        },
    }
    assert str(tmp_path) not in str(payload)


# ---------------------------------------------------------------------------
# Request safe-info (US-217)
# ---------------------------------------------------------------------------


def _walk_json(value: Any) -> Any:
    """Yield every scalar leaf (and every key) recursively through JSON data."""
    if isinstance(value, dict):
        yield from value.keys()
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)
    else:
        yield value


def test_safe_info_returns_strict_whitelist_for_saved_request(
    tmp_path: Path,
) -> None:
    request = _saved_accepted_request(tmp_path, "芙莉莲", "request-1")
    config = load_storage_config(tmp_path / "storage")
    event = {
        "request_id": "request-1",
        "previous_status": "PENDING_CONFIRM",
        "next_status": "ACCEPTED",
        "action": "ACCEPT",
        "timestamp": "2026-09-08T12:00:00+00:00",
    }
    append_status_history(config, event)
    request["ab_submit_result"] = {
        "success": True,
        "ab_subscription_id": "ab-sub-1",
        "ab_response": {"id": "ab-sub-1"},
        "fallback_config": None,
        "error": None,
    }
    save_ab_submit_result(config, request)

    response = _client().get(
        "/api/v1/requests/request-1/safe-info",
        query_string={"storage_dir": "storage"},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert set(payload["result"]) == {"safe_info"}
    safe = payload["result"]["safe_info"]
    assert safe["request_id"] == "request-1"
    assert safe["status"] == "ACCEPTED"
    assert safe["title"] == "葬送的芙莉莲"
    assert safe["raw_title"] == "芙莉莲"
    assert safe["selected_subtitle_group"] == "喵萌"
    assert safe["updated_episode"] is None
    assert safe["updated_episode_status"] == "NOT_IMPLEMENTED"
    assert safe["storage_profile"] == "storage"
    assert safe["folder_name"] == "葬送的芙莉莲"
    # Resource counts and sanitized names only.
    assert safe["resources"]["valid_resource_count"] == 1
    assert safe["resources"]["valid_file_names"] == [
        "[喵萌] 葬送的芙莉莲 - 01 [1080p][CHS].mkv"
    ]
    # AB status summary only — no endpoint/raw response/fallback body.
    assert safe["ab_status"] == {
        "submitted": True,
        "success": True,
        "ab_subscription_id": "ab-sub-1",
        "error_type": None,
    }
    assert safe["history_summary"] == [
        {
            "action": "ACCEPT",
            "previous_status": "PENDING_CONFIRM",
            "next_status": "ACCEPTED",
            "timestamp": "2026-09-08T12:00:00+00:00",
        }
    ]
    # The safe-info body never carries a URL, magnet, credential, or path.
    body_text = response.get_data(as_text=True)
    assert "https://" not in body_text
    assert "http://" not in body_text
    assert "magnet:" not in body_text.lower()
    assert "rss" not in body_text.lower()
    assert str(tmp_path) not in body_text


def test_safe_info_omits_sensitive_snapshot_fields_recursively(
    tmp_path: Path,
) -> None:
    """US-217: recursive leak check over the whole safe-info JSON tree.

    Even when the stored snapshot carries raw URLs, magnets, credentials and
    absolute paths, none of them may survive into the safe-info response —
    including nested keys and scalar string values (magnet/file names).
    """
    request = {
        **generate_request(EntryRequest(raw_title="芙莉莲"))["request"],
        "request_id": "request-1",
        "source_info": {
            "matched_bangumi": {
                "title": "葬送的芙莉莲",
                "aliases": ["芙莉莲", "Frieren"],
                "mikan_url": "https://private.example/Home/Bangumi/99",
                "match_score": 1.0,
                "poster_url": "https://private.example/poster.jpg",
            },
            "rss_sources": [
                {
                    "subtitle_group": "喵萌",
                    "rss_url": "https://private.example/RSS/Bangumi?bangumiId=99",
                    "source_type": "mikan_http",
                    "total_seed_count": 2,
                    "seed_names": [
                        "[喵萌] 葬送的芙莉莲 - 01.mkv",
                        "magnet:?xt=urn:btih:deadbeef",
                    ],
                    "valid_seed_count": 2,
                    "invalid_seed_count": 1,
                    "valid_seed_names": [
                        "[喵萌] 葬送的芙莉莲 - 01.mkv",
                        "magnet:?xt=urn:btih:deadbeef",
                    ],
                    "excluded_seed_names": [
                        {
                            "name": "[喵萌] 葬送的芙莉莲 - 02.mkv",
                            "reason": "未命中包含规则：1080p",
                            "rule": "must_contain",
                        }
                    ],
                    "warnings": [],
                }
            ],
        },
        "confirmable_config": {
            "selected_subtitle_group": "喵萌",
            "selected_rss_url": "https://private.example/RSS/Bangumi?bangumiId=99",
            "filter_rule": {
                "must_contain": "1080p",
                "must_not_contain": "",
                "use_regex": False,
                "case_sensitive": False,
            },
            "effective_seed_names": [
                "[喵萌] 葬送的芙莉莲 - 01.mkv",
                "magnet:?xt=urn:btih:deadbeef",
            ],
            "expected_folder_name": "葬送的芙莉莲",
            "warnings": [],
        },
        "ab_submit_result": {
            "success": False,
            "ab_subscription_id": None,
            "ab_response": {"raw": "<html>secret</html>"},
            "fallback_config": {
                "title": "葬送的芙莉莲",
                "rss_url": "https://private.example/rss.xml",
                "save_path": "/private/absolute/path",
            },
            "error": {
                "error_type": "ab_connection_failed",
                "error_message": "连不上 https://private.example:8080",
                "failed_step": "submit_ab_subscription",
                "details": {"base_url": "https://private.example"},
            },
        },
    }
    save_request_snapshot(load_storage_config(tmp_path / "storage"), request)
    save_ab_submit_result(load_storage_config(tmp_path / "storage"), request)

    response = _client().get(
        "/api/v1/requests/request-1/safe-info",
        query_string={"storage_dir": "storage"},
    )

    payload = response.get_json()
    assert response.status_code == 200
    body_text = response.get_data(as_text=True)
    # Nothing sensitive survives in the serialized tree, including substrings.
    for marker in (
        "https://",
        "http://",
        "magnet:",
        "private.example",
        "/private/absolute",
        "token",
        "cookie",
        "password",
        "Authorization",
        "raw_response",
        "rss_url",
        "mikan_url",
        "poster_url",
        "selected_rss_url",
        "fallback_config",
        "ab_response",
        "<html",
    ):
        assert marker not in body_text.lower(), f"leaked {marker!r} in {body_text}"
    # The magnet seed name must be redacted, not surfaced as a file name.
    safe = payload["result"]["safe_info"]
    for leaf in _walk_json(safe):
        if isinstance(leaf, str):
            assert "magnet:?" not in leaf.lower()
            assert "http://" not in leaf.lower()
            assert "https://" not in leaf.lower()
            assert "/private/" not in leaf
    assert safe["title"] == "葬送的芙莉莲"
    assert safe["ab_status"]["error_type"] == "ab_connection_failed"
    # The raw_title and whitelisted filter labels stay intact.
    assert safe["raw_title"] == "芙莉莲"
    assert safe["filter_rule"]["must_contain"] == "1080p"


def test_safe_info_reuses_detail_error_classification(tmp_path: Path) -> None:
    """404/illegal request_id/storage-profile errors match the detail endpoint."""
    missing = _client().get(
        "/api/v1/requests/missing-request/safe-info",
        query_string={"storage_dir": "storage"},
    )
    missing_payload = missing.get_json()
    assert missing.status_code == 404
    assert missing_payload["error_type"] == "request_not_found"
    assert missing_payload["error_data"]["failed_step"] == "load_request_snapshot"
    assert str(tmp_path) not in str(missing_payload)

    invalid = _client().get(
        "/api/v1/requests/nested%2Frequest/safe-info",
        query_string={"storage_dir": "storage"},
    )
    invalid_payload = invalid.get_json()
    assert invalid.status_code == 400
    assert invalid_payload["error_type"] == "invalid_request_id"
    assert invalid_payload["error_data"]["details"] == {"field": "request_id"}

    bad_profile = _client().get(
        "/api/v1/requests/request-1/safe-info",
        query_string={"storage_dir": "/etc/secret"},
    )
    bad_profile_payload = bad_profile.get_json()
    assert bad_profile.status_code == 400
    assert bad_profile_payload["error_type"] == "invalid_storage_dir"
    assert "/etc/secret" not in str(bad_profile_payload)


def test_safe_info_without_storage_dir_uses_server_root_and_null_profile(
    tmp_path: Path,
) -> None:
    """US-217: omitting storage_dir resolves to the server root and reports
    storage_profile=null (the root itself), never a CLI default path."""
    request = {
        **generate_request(EntryRequest(raw_title="芙莉莲"))["request"],
        "request_id": "request-1",
    }
    save_request_snapshot(load_storage_config(tmp_path), request)

    response = _client().get("/api/v1/requests/request-1/safe-info")

    payload = response.get_json()
    assert response.status_code == 200
    safe = payload["result"]["safe_info"]
    assert safe["request_id"] == "request-1"
    assert safe["storage_profile"] is None
    assert str(tmp_path) not in str(payload)


def test_delete_request_rejects_path_fragments_without_leaking_storage_path(
    tmp_path: Path,
) -> None:
    response = _client().post(
        "/api/v1/requests/nested%2Frequest/delete",
        json={"storage_dir": "storage"},
    )

    payload = response.get_json()
    assert response.status_code == 400
    assert payload == {
        "ok": False,
        "error_type": "invalid_request_id",
        "error_message": "request_id 不能包含路径片段",
        "error_data": {
            "failed_step": "delete_request_snapshot",
            "details": {"field": "request_id"},
        },
    }
    assert str(tmp_path) not in str(payload)


def test_delete_request_returns_unified_error_for_delete_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_delete(*args: object, **kwargs: object) -> dict[str, object]:
        raise Stage1Error(
            "storage_error",
            f"删除订阅方案 JSON 失败 {tmp_path}/secret-token",
            "delete_request_snapshot",
            {
                "request_id": "request-1",
                "directory": "requests",
                "reason": f"cannot unlink {tmp_path}/requests/request-1.json",
            },
        )

    monkeypatch.setattr(
        "apps.migu_orca_web.routes_requests.delete_request_snapshot",
        fail_delete,
    )

    response = _client().post(
        "/api/v1/requests/request-1/delete",
        json={"storage_dir": "storage"},
    )

    payload = response.get_json()
    serialized = str(payload)
    assert response.status_code == 500
    assert payload["ok"] is False
    assert payload["error_type"] == "storage_error"
    assert payload["error_data"]["failed_step"] == "delete_request_snapshot"
    assert payload["error_data"]["details"]["directory"] == "requests"
    assert str(tmp_path) not in serialized
    assert "secret-token" not in serialized


def test_modify_accepted_request_preserves_status_and_records_history(
    tmp_path: Path,
) -> None:
    request = _saved_accepted_request(tmp_path, "芙莉莲", "request-1")
    storage_dir = tmp_path / "storage"
    patch = {"expected_folder_name": "芙莉莲 修改版"}

    response = _client().post(
        f"/api/v1/requests/{request['request_id']}/modify",
        json={
            "storage_dir": _profile(tmp_path, storage_dir.name),
            "patch": patch,
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["request"]["status"] == "ACCEPTED"
    assert (
        payload["result"]["request"]["confirmable_config"]["expected_folder_name"]
        == "芙莉莲 修改版"
    )
    assert payload["result"]["summary"]["status"] == "ACCEPTED"

    detail_response = _client().get(
        f"/api/v1/requests/{request['request_id']}",
        query_string={"storage_dir": _profile(tmp_path, storage_dir.name)},
    )
    detail = detail_response.get_json()
    assert detail["ok"] is True
    assert detail["result"]["history"]["available"] is True
    assert detail["result"]["history"]["events"] == [
        {
            "action": "MODIFY",
            "previous_status": "ACCEPTED",
            "next_status": "ACCEPTED",
            "timestamp": payload["result"]["request"]["updated_at"],
        }
    ]


def test_modify_accepted_request_recomputes_seeds_and_rejects_cancelled(
    tmp_path: Path,
) -> None:
    request = _saved_accepted_request(tmp_path, "芙莉莲", "request-1")
    cancelled = _saved_cancelled_request(tmp_path, "咒术回战", "request-cancelled")
    storage_dir = tmp_path / "storage"

    response = _client().post(
        f"/api/v1/requests/{request['request_id']}/modify",
        json={
            "storage_dir": _profile(tmp_path, storage_dir.name),
            "patch": {"filter_rule": {"must_contain": "01", "must_not_contain": ""}},
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["request"]["status"] == "ACCEPTED"
    assert payload["result"]["request"]["confirmable_config"]["filter_rule"] == {
        "must_contain": "01",
        "must_not_contain": "",
        "use_regex": False,
        "case_sensitive": False,
    }
    assert payload["result"]["summary"]["effective_seed_count"] == 1

    cancel_response = _client().post(
        f"/api/v1/requests/{cancelled['request_id']}/modify",
        json={
            "storage_dir": _profile(tmp_path, storage_dir.name),
            "patch": {"expected_folder_name": "不应成功"},
        },
    )
    cancel_payload = cancel_response.get_json()
    assert cancel_payload["ok"] is False
    assert cancel_payload["error_type"] == "invalid_request_status"
    assert cancel_payload["error_data"]["details"] == {"status": "CANCELLED"}
    assert str(tmp_path) not in str(cancel_payload)


def test_create_request_generates_without_writing_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage_dir = tmp_path / "storage"
    transport = _FakeMikanTransport({
        "https://mikanani.me/Home/Search?searchstr=%E8%8A%99%E8%8E%89%E8%8E%B2":
            '<a class="an-text" href="/Home/Bangumi/123">芙莉莲</a>',
        "https://mikanani.me/Home/Bangumi/123":
            '<h1 class="bangumi-title">芙莉莲</h1><a class="mikan-rss" href="/RSS/Bangumi?bangumiId=123">RSS</a>',
        "https://mikanani.me/RSS/Bangumi?bangumiId=123":
            '<rss><channel><item><title>芙莉莲 - 01</title><link>https://example.invalid/1</link></item></channel></rss>',
    })
    monkeypatch.setattr(
        "apps.migu_orca_entry.controllers.entry_controller.mikan_client_module.create_mikan_client",
        lambda config: create_mikan_client(config, transport=transport),
    )

    response = _client().post(
        "/api/v1/requests",
        json={
            "title": "芙莉莲",
            "storage_dir": _profile(tmp_path, storage_dir.name),
        },
    )

    payload = response.get_json()
    request = payload["result"]["request"]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert request["input"]["raw_title"] == "芙莉莲"
    assert payload["result"]["summary"] == summarize_request(request)
    assert "saved_request" not in payload["result"]
    assert not storage_dir.exists()


def test_create_request_defaults_to_static_fixture_without_mikan_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _FakeMikanTransport({
        "https://mikanani.me/Home/Search?searchstr=%E8%8A%99%E8%8E%89%E8%8E%B2":
            '<a class="an-text" href="/Home/Bangumi/123">芙莉莲</a>',
        "https://mikanani.me/Home/Bangumi/123":
            '<h1 class="bangumi-title">芙莉莲</h1><a class="mikan-rss" href="/RSS/Bangumi?bangumiId=123">RSS</a>',
        "https://mikanani.me/RSS/Bangumi?bangumiId=123":
            '<rss><channel><item><title>芙莉莲 - 01</title><link>https://example.invalid/1</link></item></channel></rss>',
    })
    monkeypatch.setattr(
        "apps.migu_orca_entry.controllers.entry_controller.mikan_client_module.create_mikan_client",
        lambda config: create_mikan_client(config, transport=transport),
    )

    response = _client().post(
        "/api/v1/requests",
        json={
            "title": "芙莉莲",
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert transport.requests == [
        ("https://mikanani.me/Home/Search?searchstr=%E8%8A%99%E8%8E%89%E8%8E%B2", 15.0),
        ("https://mikanani.me/Home/Bangumi/123", 15.0),
        ("https://mikanani.me/RSS/Bangumi?bangumiId=123", 15.0),
    ]
    assert payload["result"]["request"]["input"]["raw_title"] == "芙莉莲"


def test_create_request_uses_inline_mikan_config_when_explicitly_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fail_if_called(*args: Any, **kwargs: Any) -> Any:
        nonlocal called
        called = True
        raise AssertionError("inline MiKan config must be rejected before generation")
    monkeypatch.setattr("apps.migu_orca_web.routes_requests.generate_request", fail_if_called)

    response = _client().post(
        "/api/v1/requests",
        json={
            "title": "芙莉莲",
            "source": "mikan",
        },
    )

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert any(e["field"] == "source" for e in payload["error_data"]["errors"])
    assert called is False


def test_create_request_accepts_request_scoped_mikan_direct_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "storage"
    transport = _FakeMikanTransport(
        {
                "https://mikanani.me/Home/Bangumi/123": (
                '<h1 class="bangumi-title">芙莉莲</h1>'
                '<a class="mikan-rss" href="/RSS/Bangumi?bangumiId=123">RSS</a>'
                '<section class="subgroup-section">'
                '<h2 class="subgroup-name">Loli</h2>'
                '<a href="/RSS/Bangumi?bangumiId=123&subgroupid=10">RSS</a>'
                "</section>"
                ),
                "https://mikanani.me/RSS/Bangumi?bangumiId=123": (
                    "<rss><channel><item><title>芙莉莲 - 01</title>"
                    "<link>https://example.invalid/1</link></item></channel></rss>"
                ),
                "https://mikanani.me/RSS/Bangumi?bangumiId=123&subgroupid=10": (
                "<rss><channel><item><title>芙莉莲 - 01</title>"
                "<link>https://example.invalid/1</link></item></channel></rss>"
            ),
        }
    )

    def fake_create_mikan_client(config: MikanConfig):
        return create_mikan_client(config, transport=transport)

    monkeypatch.setattr(
        "apps.migu_orca_entry.controllers.entry_controller.mikan_client_module.create_mikan_client",
        fake_create_mikan_client,
    )

    response = _client().post(
        "/api/v1/requests",
        json={
            "title": "不会用于搜索",
            "mikan_bangumi": "https://mikanani.me/Home/Bangumi/123",
            "storage_dir": _profile(tmp_path, storage_dir.name),
        },
    )

    payload = response.get_json()
    request = payload["result"]["request"]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert transport.requests == [
        ("https://mikanani.me/Home/Bangumi/123", 15.0),
        ("https://mikanani.me/RSS/Bangumi?bangumiId=123&subgroupid=10", 15.0),
    ]
    assert request["source_info"]["matched_bangumi"]["title"] == "芙莉莲"
    assert (
        request["source_info"]["matched_bangumi"]["mikan_url"]
        == "https://mikanani.me/Home/Bangumi/123"
    )


def test_create_request_does_not_trust_client_candidate_aliases_for_season(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_generate_request(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "success": True,
            "request": {
                "request_id": "preview-id",
                "status": "PENDING_CONFIRM",
                "input": {"raw_title": "公开标题"},
                "source_info": {
                    "matched_bangumi": {
                        "title": "公开标题",
                        "aliases": [],
                        "mikan_url": "https://mikan.example/Home/Bangumi/44",
                        "match_score": 1.0,
                        "poster_url": None,
                    },
                    "rss_sources": [],
                },
                "confirmable_config": {},
            },
            "error": None,
        }

    monkeypatch.setattr("apps.migu_orca_web.routes_requests.generate_request", fake_generate_request)
    response = _client().post(
        "/api/v1/requests",
        json={
            "title": "公开标题",
            "mikan_bangumi": "https://mikan.example/Home/Bangumi/44",
        },
    )

    matched = response.get_json()["result"]["request"]["source_info"]["matched_bangumi"]
    assert response.status_code == 200
    assert matched["aliases"] == []
    assert matched["poster_url"] is None
    assert "season" not in matched
    assert "某番 S4" not in response.get_data(as_text=True)


def test_create_request_requires_one_time_server_candidate_context_for_nonfirst_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.migu_orca_web.contexts import candidate_selection_contexts

    mikan_url = "https://mikan.example/Home/Bangumi/45"
    rejected_context = candidate_selection_contexts.issue(mikan_url, 4)
    context = candidate_selection_contexts.issue(mikan_url, 4)

    def fake_generate_request(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "success": True,
            "request": {
                "request_id": "preview-id",
                "status": "PENDING_CONFIRM",
                "input": {"raw_title": "公开标题"},
                "source_info": {"matched_bangumi": {"title": "公开标题", "aliases": [], "mikan_url": mikan_url, "match_score": 1.0}, "rss_sources": []},
                "confirmable_config": {},
            },
            "error": None,
        }

    monkeypatch.setattr("apps.migu_orca_web.routes_requests.generate_request", fake_generate_request)
    payload = {"title": "公开标题", "mikan_bangumi": mikan_url}

    rejected = _client().post(
        "/api/v1/requests", json={**payload, "candidate_context": rejected_context}
    )
    confirmed = _client().post(
        "/api/v1/requests",
        json={**payload, "season_confirmation": 4, "candidate_context": context},
    )

    assert rejected.status_code == 409
    assert rejected.get_json()["ok"] is False
    assert "season_confirmation_required" in str(rejected.get_json())
    matched = confirmed.get_json()["result"]["request"]["source_info"]["matched_bangumi"]
    assert matched["season"] == 4
    assert matched["season_evidence"] == "user_confirmed"
    assert len(candidate_selection_contexts) == 0


def test_candidate_context_is_bound_to_url_expired_and_capacity_limited() -> None:
    from apps.migu_orca_web.contexts import CandidateSelectionContextStore

    now = [0.0]
    contexts = CandidateSelectionContextStore(ttl_seconds=10, max_entries=2, now=lambda: now[0])
    first = contexts.issue("https://mikan.example/Home/Bangumi/1", 2)
    second = contexts.issue("https://mikan.example/Home/Bangumi/2", 3)
    third = contexts.issue("https://mikan.example/Home/Bangumi/3", 4)

    assert len(contexts) == 2
    assert contexts.consume(first, "https://mikan.example/Home/Bangumi/1") == (False, None)
    assert contexts.consume(second, "https://mikan.example/Home/Bangumi/other") == (False, None)
    now[0] = 11.0
    assert contexts.consume(third, "https://mikan.example/Home/Bangumi/3") == (False, None)
    assert len(contexts) == 0


def test_create_request_rejects_invalid_mikan_direct_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fail_if_called(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        raise AssertionError("generate_request should not be called for invalid payload")

    monkeypatch.setattr("apps.migu_orca_web.routes_requests.generate_request", fail_if_called)

    response = _client().post(
        "/api/v1/requests",
        json={
            "title": "芙莉莲",
            "source": "mikan",
            "mikan_bangumi": "   ",
        },
    )

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert any(
        error["field"] == "mikan_bangumi"
        for error in payload["error_data"]["errors"]
    )
    assert called is False


def test_create_request_uses_default_mikan_config_when_source_is_mikan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    factory_configs: list[MikanConfig] = []

    def fake_create_mikan_client(config: MikanConfig) -> _FakeMikanClient:
        factory_configs.append(config)
        transport = _FakeMikanTransport(
            {
                "https://mikan.example/RSS/Bangumi?bangumiId=123": (
                    "<rss><channel><item><title>芙莉莲 - 01</title>"
                    "<link>https://example.invalid/1</link></item></channel></rss>"
                )
            }
        )
        return _FakeMikanClient(config, transport)

    def spy_generate_request(*args: Any, **kwargs: Any) -> dict[str, Any]:
        captured["source_mode"] = kwargs.get("source_mode")
        captured["mikan_config"] = kwargs.get("mikan_config")
        return generate_request(*args, **kwargs)

    monkeypatch.setattr(
        "apps.migu_orca_entry.controllers.entry_controller.mikan_client_module.create_mikan_client",
        fake_create_mikan_client,
    )
    monkeypatch.setattr("apps.migu_orca_web.routes_requests.generate_request", spy_generate_request)

    response = _client().post(
        "/api/v1/requests",
        json={
            "title": "芙莉莲",
        },
    )

    payload = response.get_json()
    request = payload["result"]["request"]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert captured["source_mode"] == "mikan_http"
    assert isinstance(captured["mikan_config"], MikanConfig)
    assert captured["mikan_config"] == default_mikan_config()
    assert captured["mikan_config"].search_endpoint == "https://mikanani.me/Home/Search"
    assert captured["mikan_config"].timeout_seconds == 15.0
    assert factory_configs == [captured["mikan_config"]]
    assert request["source_info"]["matched_bangumi"]["title"] == "芙莉莲"
    assert request["confirmable_config"]["selected_subtitle_group"] == "Loli"


def test_create_request_rejects_unsupported_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fail_if_called(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        raise AssertionError("generate_request should not be called for invalid payload")

    monkeypatch.setattr("apps.migu_orca_web.routes_requests.generate_request", fail_if_called)

    response = _client().post(
        "/api/v1/requests",
        json={
            "title": "芙莉莲",
            "source": "real-live-mikan",
        },
    )

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert payload["error_data"]["errors"][0]["field"] == "source"
    assert called is False


def test_create_request_rejects_invalid_mikan_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fail_if_called(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        raise AssertionError("generate_request should not be called for invalid payload")

    monkeypatch.setattr("apps.migu_orca_web.routes_requests.generate_request", fail_if_called)

    response = _client().post(
        "/api/v1/requests",
        json={
            "title": "芙莉莲",
            "source": "mikan",
            "mikan_config": {
                "search_endpoint": "https://mikan.example/Home/Search",
                "timeout_seconds": 0,
            },
        },
    )

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert any(
        error["field"] == "mikan_config"
        for error in payload["error_data"]["errors"]
    )
    assert called is False


def test_candidate_search_api_returns_sanitized_candidates_with_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _FakeMikanTransport(
        {
                "https://mikanani.me/Home/Search?searchstr=%E8%8A%99%E8%8E%89%E8%8E%B2": (
                '<section class="related-recommendations">'
                '<div class="bangumi-item">'
                '<a class="an-image" href="/Home/Bangumi/2353">'
                '<img class="bangumi-poster" src="/assets/cover/2353.jpg">'
                "</a>"
                '<a class="an-text" href="/Home/Bangumi/2353" title="Frieren EN">'
                "葬送的芙莉莲"
                "</a>"
                "</div>"
                '<div class="bangumi-item">'
                '<a class="an-text" href="/Home/Bangumi/3072">咒术回战 第三季</a>'
                "</div>"
                "</section>"
            )
        }
    )

    def fake_create_mikan_client(config: MikanConfig):
        return create_mikan_client(config, transport=transport)

    monkeypatch.setattr(
        "apps.migu_orca_web.services.mikan_client_module.create_mikan_client",
        fake_create_mikan_client,
    )

    response = _client().post(
        "/api/v1/mikan/candidates",
        json={
            "query": "芙莉莲",
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["query"] == "芙莉莲"
    assert payload["result"]["status"] == BATCH_ITEM_STATUS_FOUND
    assert payload["result"]["parse_result"] == {
        "raw_title": "芙莉莲",
        "normalized_title": "芙莉莲",
        "base_title": "芙莉莲",
        "canonical_title_candidates": ["芙莉莲"],
        "season": {"number": None, "raw": None, "normalized": None, "source": "none"},
        "season_number": None,
        "season_hint": None,
        "query_plan": [
            {"query": "芙莉莲", "source": "rule", "priority": 1},
        ],
        "search_queries": ["芙莉莲"],
        "source": "rule",
        "confidence": 0.45,
        "needs_user_review": True,
        "review_hints": ["未识别正式别名，请人工核对"],
    }
    assert payload["result"]["attempted_queries"] == [
        {"query": "芙莉莲", "source": "rule", "priority": 1},
    ]
    assert payload["result"]["candidates"] == [
        {
            "bangumi_id": "2353",
            "title": "葬送的芙莉莲",
                "mikan_url": "https://mikanani.me/Home/Bangumi/2353",
            "poster_url": "/api/v1/mikan/posters/"
                + poster_cache_key("https://mikanani.me/assets/cover/2353.jpg"),
            "source_query": "芙莉莲",
            "aliases": ["Frieren EN"],
            "recommendation": "可能匹配",
        },
        {
            "bangumi_id": "3072",
            "title": "咒术回战 第三季",
                "mikan_url": "https://mikanani.me/Home/Bangumi/3072",
            "poster_url": None,
            "source_query": "芙莉莲",
            "aliases": [],
            "recommendation": None,
        },
    ]
    assert transport.requests == [
        (
                "https://mikanani.me/Home/Search?searchstr=%E8%8A%99%E8%8E%89%E8%8E%B2",
                15.0,
        )
    ]


def test_candidate_search_api_returns_empty_list_when_no_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _FakeMikanTransport(
        {
            "https://mikanani.me/Home/Search?searchstr=ghost": (
                '<section class="related-recommendations"><p>暂无相关合集</p></section>'
            )
        }
    )

    def fake_create_mikan_client(config: MikanConfig):
        return create_mikan_client(config, transport=transport)

    monkeypatch.setattr(
        "apps.migu_orca_web.services.mikan_client_module.create_mikan_client",
        fake_create_mikan_client,
    )

    response = _client().post(
        "/api/v1/mikan/candidates",
        json={
            "query": "ghost",
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["candidates"] == []


def test_candidate_search_api_rejects_empty_query_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("create_mikan_client should not be called for empty query")

    monkeypatch.setattr(
        "apps.migu_orca_web.services.mikan_client_module.create_mikan_client",
        fail_if_called,
    )

    response = _client().post(
        "/api/v1/mikan/candidates",
        json={
            "query": "   ",
        },
    )

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert any(
        error["field"] == "query" for error in payload["error_data"]["errors"]
    )


def test_candidate_search_api_uses_default_mikan_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _FakeMikanTransport(
        {
            "https://mikanani.me/Home/Search?searchstr=%E8%8A%99%E8%8E%89%E8%8E%B2": (
                '<section class="related-recommendations">'
                '<div class="bangumi-item">'
                '<a class="an-text" href="/Home/Bangumi/2353">葬送的芙莉莲</a>'
                "</div>"
                "</section>"
            )
        }
    )
    received_configs: list[MikanConfig] = []

    def fake_create_mikan_client(config: MikanConfig):
        received_configs.append(config)
        return create_mikan_client(config, transport=transport)

    monkeypatch.setattr(
        "apps.migu_orca_web.services.mikan_client_module.create_mikan_client",
        fake_create_mikan_client,
    )

    response = _client().post(
        "/api/v1/mikan/candidates",
        json={"query": "芙莉莲"},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["query"] == "芙莉莲"
    assert payload["result"]["candidates"] == [
        {
            "bangumi_id": "2353",
            "title": "葬送的芙莉莲",
            "mikan_url": "https://mikanani.me/Home/Bangumi/2353",
            "poster_url": None,
            "source_query": "芙莉莲",
            "aliases": [],
            "recommendation": "可能匹配",
        }
    ]
    assert received_configs == [default_mikan_config()]
    assert received_configs[0].search_endpoint == DEFAULT_MIKAN_SEARCH_ENDPOINT
    assert received_configs[0].timeout_seconds == DEFAULT_MIKAN_TIMEOUT_SECONDS
    assert transport.requests == [
        (
            "https://mikanani.me/Home/Search?searchstr=%E8%8A%99%E8%8E%89%E8%8E%B2",
            DEFAULT_MIKAN_TIMEOUT_SECONDS,
        )
    ]


@pytest.mark.parametrize(
    "error, expected_error_type, expected_failed_step",
    [
        (
            Stage1Error(
                "mikan_http_failed",
                "MiKan HTTP 请求失败",
                "mikan_search",
                {"status_code": 503},
            ),
            "mikan_http_failed",
            "mikan_search",
        ),
        (
            Stage1Error(
                "mikan_timeout",
                "MiKan HTTP 请求超时",
                "mikan_search",
                {"category": "timeout"},
            ),
            "mikan_timeout",
            "mikan_search",
        ),
        (
            Stage1Error(
                "mikan_parse_failed",
                "MiKan 页面解析失败",
                "mikan_search",
            ),
            "mikan_parse_failed",
            "mikan_search",
        ),
    ],
)
def test_candidate_search_api_returns_sanitized_mikan_errors(
    monkeypatch: pytest.MonkeyPatch,
    error: Stage1Error,
    expected_error_type: str,
    expected_failed_step: str,
) -> None:
    client = _FakeCandidateSearchClient(error=error)

    def fake_create_mikan_client(config: MikanConfig):
        return client

    monkeypatch.setattr(
        "apps.migu_orca_web.services.mikan_client_module.create_mikan_client",
        fake_create_mikan_client,
    )

    response = _client().post(
        "/api/v1/mikan/candidates",
        json={
            "query": "芙莉莲",
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    result = payload["result"]
    assert result["status"] == BATCH_ITEM_STATUS_FAILED
    assert result["error"]["error_type"] == expected_error_type
    assert result["error"]["failed_step"] == expected_failed_step
    assert set(result["error"]["details"]) <= {"category", "field", "length", "recoverable"}
    assert client.searches == ["芙莉莲"]


def test_candidate_search_api_does_not_echo_raw_html_or_sensitive_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _FakeMikanTransport(
        {
                "https://mikanani.me/Home/Search?searchstr=%E8%8A%99%E8%8E%89%E8%8E%B2": (
                "<html><body>"
                "<script>var sessionToken = 'secret-candidate-token'</script>"
                '<div class="bangumi-item">'
                '<a class="an-text" href="/Home/Bangumi/42">芙莉莲</a>'
                "</div>"
                "</body></html>"
            )
        }
    )

    def fake_create_mikan_client(config: MikanConfig):
        return create_mikan_client(config, transport=transport)

    monkeypatch.setattr(
        "apps.migu_orca_web.services.mikan_client_module.create_mikan_client",
        fake_create_mikan_client,
    )

    response = _client().post(
        "/api/v1/mikan/candidates",
        json={
            "query": "芙莉莲",
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["candidates"] == [
        {
            "bangumi_id": "42",
            "title": "芙莉莲",
            "mikan_url": "https://mikanani.me/Home/Bangumi/42",
            "poster_url": None,
            "source_query": "芙莉莲",
            "aliases": [],
            "recommendation": "可能匹配",
        }
    ]
    body = response.get_data(as_text=True)
    assert "secret-candidate-token" not in body
    assert "<script" not in body
    assert "<html" not in body
    assert "<rss" not in body


def test_candidate_search_api_includes_display_only_recommendation_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeCandidateSearchClient(
        candidates=[
            MikanCandidate(
                bangumi_id="3072",
                title="咒术回战 第三季",
                mikan_url="https://mikanani.me/Home/Bangumi/3072",
                source_query="咒术回战 第三季",
            ),
            MikanCandidate(
                bangumi_id="3071",
                title="咒术回战 第二季",
                mikan_url="https://mikanani.me/Home/Bangumi/3071",
                source_query="咒术回战 第三季",
            ),
        ]
    )

    def fake_create_mikan_client(config: MikanConfig):
        return client

    monkeypatch.setattr(
        "apps.migu_orca_web.services.mikan_client_module.create_mikan_client",
        fake_create_mikan_client,
    )

    response = _client().post(
        "/api/v1/mikan/candidates",
        json={
            "query": "咒术回战 第三季",
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["candidates"] == [
        {
            "bangumi_id": "3072",
            "title": "咒术回战 第三季",
            "mikan_url": "https://mikanani.me/Home/Bangumi/3072",
            "poster_url": None,
            "source_query": "咒术回战 第三季",
                "aliases": [],
                "recommendation": "推荐：第 3 季",
                "season_evidence": {
                    "status": "PROVEN", "season": 3, "requires_review": False,
                },
        },
        {
            "bangumi_id": "3071",
            "title": "咒术回战 第二季",
            "mikan_url": "https://mikanani.me/Home/Bangumi/3071",
            "poster_url": None,
            "source_query": "咒术回战 第三季",
                "aliases": [],
                "recommendation": "季数不符",
                "season_evidence": {
                    "status": "CONFLICT", "season": None, "requires_review": True,
                },
        },
    ]


def test_candidate_search_api_serves_second_call_from_cache_without_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _FakeMikanTransport(
        {
            "https://mikanani.me/Home/Search?searchstr=%E8%8A%99%E8%8E%89%E8%8E%B2": (
                '<section class="related-recommendations">'
                '<div class="bangumi-item">'
                '<a class="an-text" href="/Home/Bangumi/2353">葬送的芙莉莲</a>'
                "</div>"
                "</section>"
            )
        }
    )

    def fake_create_mikan_client(config: MikanConfig):
        return create_mikan_client(config, transport=transport)

    monkeypatch.setattr(
        "apps.migu_orca_web.services.mikan_client_module.create_mikan_client",
        fake_create_mikan_client,
    )

    payload = {
        "query": "芙莉莲",
    }
    first = _client().post("/api/v1/mikan/candidates", json=payload)
    second = _client().post("/api/v1/mikan/candidates", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.get_json() == second.get_json()
    assert transport.requests == [
        ("https://mikanani.me/Home/Search?searchstr=%E8%8A%99%E8%8E%89%E8%8E%B2", 15.0)
    ]


def test_candidate_search_api_cache_isolates_different_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _FakeMikanTransport(
        {
            "https://mikanani.me/Home/Search?searchstr=%E8%8A%99%E8%8E%89%E8%8E%B2": (
                '<section class="related-recommendations">'
                '<div class="bangumi-item">'
                '<a class="an-text" href="/Home/Bangumi/2353">葬送的芙莉莲</a>'
                "</div>"
                "</section>"
            ),
            "https://mikanani.me/Home/Search?searchstr=%E5%92%92%E6%9C%AF%E5%9B%9E%E6%88%98": (
                '<section class="related-recommendations">'
                '<div class="bangumi-item">'
                '<a class="an-text" href="/Home/Bangumi/3072">咒术回战 第三季</a>'
                "</div>"
                "</section>"
            ),
        }
    )

    def fake_create_mikan_client(config: MikanConfig):
        return create_mikan_client(config, transport=transport)

    monkeypatch.setattr(
        "apps.migu_orca_web.services.mikan_client_module.create_mikan_client",
        fake_create_mikan_client,
    )

    first = _client().post(
        "/api/v1/mikan/candidates",
        json={"query": "芙莉莲"},
    )
    second = _client().post(
        "/api/v1/mikan/candidates",
        json={"query": "咒术回战"},
    )

    assert first.get_json()["result"]["candidates"][0]["bangumi_id"] == "2353"
    assert second.get_json()["result"]["candidates"][0]["bangumi_id"] == "3072"
    assert len(transport.requests) == 1


def test_candidate_search_api_cache_isolates_different_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _FakeMikanTransport(
        {
            "https://mikan.example/Home/Search?searchstr=ghost": (
                '<section class="related-recommendations">'
                '<div class="bangumi-item">'
                '<a class="an-text" href="/Home/Bangumi/100">A 番剧</a>'
                "</div>"
                "</section>"
            ),
            "https://other.example/Home/Search?searchstr=ghost": (
                '<section class="related-recommendations">'
                '<div class="bangumi-item">'
                '<a class="an-text" href="/Home/Bangumi/200">B 番剧</a>'
                "</div>"
                "</section>"
            ),
        }
    )

    def fake_create_mikan_client(config: MikanConfig):
        return create_mikan_client(config, transport=transport)

    monkeypatch.setattr(
        "apps.migu_orca_web.services.mikan_client_module.create_mikan_client",
        fake_create_mikan_client,
    )

    first = _client().post(
        "/api/v1/mikan/candidates",
        json={
            "query": "ghost",
        },
    )
    second = _client().post(
        "/api/v1/mikan/candidates",
        json={
            "query": "ghost",
        },
    )

    assert first.get_json()["result"]["candidates"][0]["bangumi_id"] == "100"
    assert second.get_json()["result"]["candidates"][0]["bangumi_id"] == "100"
    assert len(transport.requests) == 2


def test_batch_parse_api_returns_per_item_parsed_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 路哥S4 (high confidence, single candidate) gets a real candidate so it is
    # the no-review case; 萌王S4 (multi-candidate) and 邻家天使S2 (no candidate)
    # both must be flagged for review under US-154.
    def _search_candidates(search_queries: list[str], mikan_config: object) -> list[dict[str, object]]:
        if search_queries and "实力至上" in search_queries[0]:
            return [
                {
                    "bangumi_id": "4001",
                    "title": "欢迎来到实力至上主义的教室 第四季",
                    "mikan_url": "https://mikan.example/Home/Bangumi/4001",
                    "source_query": search_queries[0],
                }
            ]
        return []

    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches._search_batch_item_candidates",
        _search_candidates,
    )
    raw_input = "\n萌王S4\n  \n路哥S4\n邻家天使S2\n"

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": raw_input},
    )

    payload = response.get_json()
    result = payload["result"]
    items = result["items"]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert result["batch_id"].startswith("batch-")
    assert result["raw_input"] == raw_input
    assert [item["raw_title"] for item in items] == [
        "萌王S4",
        "路哥S4",
        "邻家天使S2",
    ]
    assert len({item["item_id"] for item in items}) == 3
    assert all(item["item_id"].startswith("item-") for item in items)
    assert [item["status"] for item in items] == [
        BATCH_ITEM_STATUS_EMPTY,
        BATCH_ITEM_STATUS_FOUND,
        BATCH_ITEM_STATUS_EMPTY,
    ]
    assert items[0]["canonical_title_candidates"] == ["关于我转生变成史莱姆这档事"]
    assert items[0]["parse_result"]["season"]["number"] == 4
    assert items[0]["parse_result"]["season_number"] == 4
    assert items[0]["parse_result"]["source"] == "alias"
    assert items[0]["attempted_queries"] == [
        {"query": entry["query"], "source": entry["source"], "priority": entry["priority"]}
        for entry in items[0]["parse_result"]["query_plan"]
    ]
    assert items[0]["season_hint"] == "S4"
    assert "转生史莱姆 第四季" in items[0]["search_queries"]
    assert items[0]["confidence"] == 0.82
    assert items[0]["needs_user_review"] is True
    assert items[0]["candidates"] == []
    assert items[1]["canonical_title_candidates"] == ["欢迎来到实力至上主义的教室"]
    assert items[1]["needs_user_review"] is True
    assert items[1]["candidates"][0]["bangumi_id"] == "4001"
    # US-154: no-candidate items (even high-confidence single-candidate ones)
    # must be flagged for review.
    assert items[2]["needs_user_review"] is True
    assert items[2]["candidates"] == []
    # Stage 21: every item carries applied_preferences + preference_warnings.
    assert items[0]["applied_preferences"] == {
        "subtitle_groups": {
            "preferred": [],
            "excluded": [],
            "fallback": "next_preferred",
        },
        "filter_rule": {
            "must_contain": "",
            "must_not_contain": "",
            "use_regex": False,
            "case_sensitive": False,
        },
        "naming": {"strategy": "official_title_season", "template": "{title}"},
        "expected_folder_name": "关于我转生变成史莱姆这档事 第4季",
    }
    assert items[0]["preference_warnings"] == []
    assert items[1]["applied_preferences"]["expected_folder_name"] == (
        "欢迎来到实力至上主义的教室 第4季"
    )
    assert items[1]["preference_warnings"] == []
    # US-154: preference_hits summarizes which preference defaults applied.
    assert items[1]["preference_hits"] == [
        {
            "field": "subtitle_groups",
            "applied": False,
            "summary": "未配置字幕组偏好，使用默认选择流程",
        },
        {
            "field": "filter_rule",
            "applied": False,
            "summary": "未配置筛选默认值",
        },
        {
            "field": "naming",
            "applied": True,
            "summary": "命名策略已生成默认目录名：欢迎来到实力至上主义的教室 第4季",
        },
    ]
    # A raw-input fallback is always reviewable, even beside a matching candidate.
    assert any("原始输入" in hint for hint in items[1]["review_hints"])
    assert any("未找到候选" in hint for hint in items[0]["review_hints"])
    assert any("未找到候选合集" in hint for hint in items[2]["review_hints"])


def test_batch_parse_api_rejects_empty_input_with_chinese_validation_error() -> None:
    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "\n \t\n"},
    )

    payload = response.get_json()
    body = response.get_data(as_text=True)
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_message"] == "请至少输入一个番剧名称"
    assert payload["error_data"]["failed_step"] == "batch_parse"
    assert payload["error_data"]["details"] == {"field": "raw_input"}
    assert "/home/" not in body


def _batch_raw_input(line_count: int) -> str:
    """Build a batch raw_input with ``line_count`` distinct non-empty lines."""
    return "\n".join(f"批量番剧{index:02d}" for index in range(1, line_count + 1))


@pytest.mark.parametrize("line_count", [1, 12, 36])
def test_batch_parse_api_accepts_boundary_batch_sizes(
    monkeypatch: pytest.MonkeyPatch,
    line_count: int,
) -> None:
    """US-215: 1/12/36 non-empty lines are all accepted and parsed."""
    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches._search_batch_item_candidates",
        lambda search_queries, mikan_config: [],
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": _batch_raw_input(line_count)},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    items = payload["result"]["items"]
    assert len(items) == line_count
    assert all(item["raw_title"].startswith("批量番剧") for item in items)
    assert len({item["item_id"] for item in items}) == line_count


def test_batch_parse_api_rejects_over_limit_before_any_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """US-215: the 37th line is rejected before title parse/MiKan/persist."""
    called: list[str] = []

    def _mark(name: str):
        def _tracked(*args: object, **kwargs: object) -> object:
            called.append(name)
            raise AssertionError(f"{name} must not run for an over-limit batch")

        return _tracked

    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches.create_batch_draft", _mark("create_batch_draft")
    )
    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches._batch_title_parsing_provider",
        _mark("_batch_title_parsing_provider"),
    )
    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches._search_batch_item_candidates",
        _mark("_search_batch_item_candidates"),
    )
    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches.load_storage_config", _mark("load_storage_config")
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": _batch_raw_input(37)},
    )

    payload = response.get_json()
    body = response.get_data(as_text=True)
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "batch_limit_exceeded"
    assert payload["error_message"] == "单批最多支持 36 部，当前输入 37 部"
    assert payload["error_data"]["failed_step"] == "batch_parse"
    assert payload["error_data"]["details"] == {
        "field": "raw_input",
        "limit": 36,
        "actual": 37,
    }
    assert called == []
    # The raw batch input is never echoed in the response.
    assert "批量番剧01" not in body
    assert "批量番剧37" not in body


def test_batch_parse_api_marks_single_provider_failure_without_blocking_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def provider() -> FakeAnimeTitleParsingProvider:
        return FakeAnimeTitleParsingProvider(fail_titles={"杖剑谭S2"})

    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches._batch_title_parsing_provider",
        provider,
    )
    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches._search_batch_item_candidates",
        lambda search_queries, mikan_config: [],
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "萌王S4\n杖剑谭S2\n路哥S4"},
    )

    payload = response.get_json()
    items = payload["result"]["items"]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert [item["status"] for item in items] == [
        BATCH_ITEM_STATUS_EMPTY,
        BATCH_ITEM_STATUS_FAILED,
        BATCH_ITEM_STATUS_EMPTY,
    ]
    assert items[1]["raw_title"] == "杖剑谭S2"
    assert items[1]["canonical_title_candidates"] == []
    assert items[1]["search_queries"] == []
    assert items[1]["candidates"] == []
    assert items[1]["needs_user_review"] is True
    assert items[1]["error"]["error_type"] == "ai_title_parse_failed"
    assert items[1]["error"]["failed_step"] == "ai_title_parse"
    assert items[0]["canonical_title_candidates"]
    assert items[2]["canonical_title_candidates"] == ["欢迎来到实力至上主义的教室 第四季"]


def test_batch_parse_api_failed_item_error_does_not_leak_sensitive_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SensitiveProvider:
        def parse(self, raw_title: str):
            raise RuntimeError(
                "token=secret-token endpoint=https://llm.example/api "
                "cookie=session-id path=/home/ghostning/raw.html <html>raw</html>"
            )

    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches._batch_title_parsing_provider",
        lambda: SensitiveProvider(),
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "敏感测试"},
    )

    payload = response.get_json()
    item = payload["result"]["items"][0]
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert payload["ok"] is True
    assert item["status"] == BATCH_ITEM_STATUS_FAILED
    assert item["error"]["error_message"] == "AI 名称解析失败，请检查该条目后重试"
    assert item["error"]["details"] == {
        "category": "title_parse",
        "length": 4,
        "recoverable": True,
    }
    assert "secret-token" not in body
    assert "llm.example" not in body
    assert "session-id" not in body
    assert "/home/ghostning" not in body


def test_batch_parse_api_applies_saved_preferences_from_storage_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches._search_batch_item_candidates",
        lambda search_queries, mikan_config: [],
    )
    storage_dir = tmp_path / "migu-state"
    save_user_preferences(
        load_storage_config(storage_dir),
        VersionedUserPreference(
            version=1,
            subtitle_groups=SubtitleGroupPreference(
                preferred=["Loli"],
                excluded=["示例组"],
                fallback="next_preferred",
            ),
            filter_defaults=FilterDefaults(
                must_contain="1080p",
                must_not_contain="合集版",
                use_regex=True,
                case_sensitive=True,
            ),
            naming=NamingPreference(strategy="raw_title", template="{title}"),
        ),
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "萌王S4", "storage_dir": _profile(tmp_path, storage_dir.name)},
    )

    item = response.get_json()["result"]["items"][0]
    assert response.status_code == 200
    assert item["applied_preferences"] == {
        "subtitle_groups": {
            "preferred": ["Loli"],
            "excluded": ["示例组"],
            "fallback": "next_preferred",
        },
        "filter_rule": {
            "must_contain": "1080p",
            "must_not_contain": "合集版",
            "use_regex": True,
            "case_sensitive": True,
        },
        "naming": {"strategy": "raw_title", "template": "{title}"},
        "expected_folder_name": "萌王S4",
    }
    assert item["preference_warnings"] == []


def test_batch_parse_api_empty_result_has_no_preview_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An empty MiKan result cannot create an editable draft skeleton."""
    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches._search_batch_item_candidates",
        lambda search_queries, mikan_config: [],
    )
    storage_dir = tmp_path / "migu-state"
    save_user_preferences(
        load_storage_config(storage_dir),
        VersionedUserPreference(
            version=1,
            subtitle_groups=SubtitleGroupPreference(
                preferred=["Loli"],
                excluded=["示例组"],
                fallback="next_preferred",
            ),
            filter_defaults=FilterDefaults(
                must_contain="1080p",
                must_not_contain="合集版",
                use_regex=True,
                case_sensitive=True,
            ),
            naming=NamingPreference(strategy="raw_title", template="{title}"),
        ),
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "萌王S4", "storage_dir": _profile(tmp_path, storage_dir.name)},
    )

    item = response.get_json()["result"]["items"][0]
    assert response.status_code == 200
    assert item["status"] == BATCH_ITEM_STATUS_EMPTY
    assert item["preview_request"] is None


def test_batch_parse_api_empty_result_has_no_preview_without_preferences(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Missing preferences do not turn an empty result into a draft."""
    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches._search_batch_item_candidates",
        lambda search_queries, mikan_config: [],
    )
    storage_dir = tmp_path / "migu-state"

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "萌王S4", "storage_dir": _profile(tmp_path, storage_dir.name)},
    )

    item = response.get_json()["result"]["items"][0]
    assert item["status"] == BATCH_ITEM_STATUS_EMPTY
    assert item["preview_request"] is None


def test_batch_parse_api_failed_item_has_no_preview_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A FAILED item (parse/search failure) has no editable preview_request."""
    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches._batch_title_parsing_provider",
        lambda: FakeAnimeTitleParsingProvider(fail_titles={"萌王S4"}),
    )
    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches._search_batch_item_candidates",
        lambda search_queries, mikan_config: [],
    )
    storage_dir = tmp_path / "migu-state"

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "萌王S4", "storage_dir": _profile(tmp_path, storage_dir.name)},
    )

    item = response.get_json()["result"]["items"][0]
    assert item["status"] == "FAILED"
    assert item.get("preview_request") is None


def test_batch_parse_api_falls_back_when_preference_file_is_damaged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches._search_batch_item_candidates",
        lambda search_queries, mikan_config: [],
    )
    storage_dir = tmp_path / "migu-state"
    config = load_storage_config(storage_dir)
    config.preferences_dir.mkdir(parents=True, exist_ok=True)
    (config.preferences_dir / "user_preferences.json").write_text(
        "{not valid json", encoding="utf-8"
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "萌王S4\n路哥S4", "storage_dir": _profile(tmp_path, storage_dir.name)},
    )

    payload = response.get_json()
    items = payload["result"]["items"]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert len(items) == 2
    assert all(item["status"] == BATCH_ITEM_STATUS_EMPTY for item in items)
    assert all(item["applied_preferences"] is None for item in items)
    assert all(item["preference_warnings"] == ["偏好读取失败，已回退默认流程"] for item in items)
    assert items[0]["canonical_title_candidates"]
    assert items[1]["canonical_title_candidates"]


def test_batch_parse_api_failed_item_keeps_applied_preferences_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def provider() -> FakeAnimeTitleParsingProvider:
        return FakeAnimeTitleParsingProvider(fail_titles={"杖剑谭S2"})

    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches._batch_title_parsing_provider",
        provider,
    )
    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches._search_batch_item_candidates",
        lambda search_queries, mikan_config: [],
    )
    storage_dir = tmp_path / "migu-state"
    save_user_preferences(
        load_storage_config(storage_dir),
        VersionedUserPreference(
            version=1,
            subtitle_groups=SubtitleGroupPreference(preferred=["Loli"]),
            naming=NamingPreference(strategy="raw_title", template="{title}"),
        ),
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "萌王S4\n杖剑谭S2", "storage_dir": _profile(tmp_path, storage_dir.name)},
    )

    items = response.get_json()["result"]["items"]
    failed = next(item for item in items if item["status"] == BATCH_ITEM_STATUS_FAILED)
    empty = next(item for item in items if item["status"] == BATCH_ITEM_STATUS_EMPTY)
    assert failed["applied_preferences"]["expected_folder_name"] is None
    assert "该条目解析失败，命名默认值不可用" in failed["preference_warnings"]
    assert failed["applied_preferences"]["subtitle_groups"] == {
        "preferred": ["Loli"],
        "excluded": [],
        "fallback": "next_preferred",
    }
    assert empty["applied_preferences"]["expected_folder_name"] == "萌王S4"
    assert empty["preference_warnings"] == []


def test_batch_parse_api_preference_response_never_leaks_sensitive_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches._search_batch_item_candidates",
        lambda search_queries, mikan_config: [],
    )
    storage_dir = tmp_path / "migu-state"
    config = load_storage_config(storage_dir)
    config.preferences_dir.mkdir(parents=True, exist_ok=True)
    # A hand-edited/legacy file carrying extra sensitive keys alongside the
    # defined contract fields: the repository strips unknown keys on load, so
    # the batch parse response must never echo them back.
    (config.preferences_dir / "user_preferences.json").write_text(
        json.dumps(
            {
                "version": 1,
                "subtitle_groups": {
                    "preferred": ["Loli"],
                    "excluded": [],
                    "fallback": "next_preferred",
                },
                "filter_defaults": {
                    "must_contain": "1080p",
                    "must_not_contain": "",
                    "use_regex": False,
                    "case_sensitive": False,
                },
                "naming": {"strategy": "raw_title", "template": "{title}"},
                "search": {"reuse_explicit_corrections": True},
                "token": "secret-token",
                "endpoint": "https://llm.example/api",
                "cookie": "session-id",
            }
        ),
        encoding="utf-8",
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "萌王S4", "storage_dir": _profile(tmp_path, storage_dir.name)},
    )

    payload = response.get_json()
    body = response.get_data(as_text=True)
    item = payload["result"]["items"][0]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert item["status"] == BATCH_ITEM_STATUS_EMPTY
    applied = item["applied_preferences"]
    assert applied is not None
    assert "token" not in applied
    assert "endpoint" not in applied
    assert "cookie" not in applied
    assert "secret-token" not in body
    assert "llm.example" not in body
    assert "session-id" not in body
    # US-154: preference_hits only carry public rule summaries, and review_hints
    # are safe Chinese prompts — no sensitive key or value can appear anywhere.
    for hit in item["preference_hits"]:
        assert set(hit) == {"field", "applied", "summary"}
        assert isinstance(hit["summary"], str)
    for hint in item["review_hints"]:
        assert isinstance(hint, str)
        assert "token" not in hint
        assert "cookie" not in hint
        assert "llm.example" not in hint


def test_batch_parse_api_searches_candidates_for_each_item_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _MappedCandidateSearchClient(
        responses={
            "欢迎来到实力至上主义的教室 第四季": [
                MikanCandidate(
                    bangumi_id="4001",
                    title="欢迎来到实力至上主义的教室 第四季",
                    mikan_url="https://mikan.example/Home/Bangumi/4001",
                    source_query="欢迎来到实力至上主义的教室 第四季",
                    aliases=["路哥 S4"],
                )
            ],
            "实力至上主义教室 S4": [
                MikanCandidate(
                    bangumi_id="4001",
                    title="欢迎来到实力至上主义的教室 第四季",
                    mikan_url="https://mikan.example/Home/Bangumi/4001",
                    source_query="实力至上主义教室 S4",
                    aliases=["路哥 S4"],
                )
            ],
            "关于邻家的天使大人不知不觉把我惯成了废人这档子事 第二季": [
                MikanCandidate(
                    bangumi_id="2002",
                    title="关于邻家的天使大人不知不觉把我惯成了废人这档子事 第二季",
                    mikan_url="https://mikan.example/Home/Bangumi/2002",
                    source_query="关于邻家的天使大人不知不觉把我惯成了废人这档子事 第二季",
                    poster_url="https://mikan.example/images/2002.jpg",
                )
            ],
        }
    )

    monkeypatch.setattr(
        "apps.migu_orca_web.services.mikan_client_module.create_mikan_client",
        lambda config: client,
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={
            "raw_input": "路哥S4\n邻家天使S2",
        },
    )

    payload = response.get_json()
    items = payload["result"]["items"]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert [item["status"] for item in items] == [
        BATCH_ITEM_STATUS_FOUND,
        BATCH_ITEM_STATUS_FOUND,
    ]
    assert "欢迎来到实力至上主义的教室 第四季" in client.searches
    assert "实力至上主义教室 第四季" in client.searches
    assert "关于邻家的天使大人不知不觉把我惯成了废人这档子事 第二季" in client.searches
    assert len(client.searches) <= 16
    assert items[0]["candidates"] == [
        {
            "bangumi_id": "4001",
            "title": "欢迎来到实力至上主义的教室 第四季",
            "mikan_url": "https://mikan.example/Home/Bangumi/4001",
            "poster_url": None,
            "source_query": "欢迎来到实力至上主义的教室 第四季",
                "aliases": ["路哥 S4"],
                "recommendation": "推荐：第 4 季",
                "season_evidence": {
                    "status": "PROVEN", "season": 4, "requires_review": False,
                },
        }
    ]
    assert items[1]["candidates"] == [
        {
            "bangumi_id": "2002",
            "title": "关于邻家的天使大人不知不觉把我惯成了废人这档子事 第二季",
            "mikan_url": "https://mikan.example/Home/Bangumi/2002",
            "poster_url": "/api/v1/mikan/posters/"
            + poster_cache_key("https://mikan.example/images/2002.jpg"),
            "source_query": "关于邻家的天使大人不知不觉把我惯成了废人这档子事 第二季",
                "aliases": [],
                "recommendation": "推荐：第 2 季",
                "season_evidence": {
                    "status": "PROVEN", "season": 2, "requires_review": False,
                },
        }
    ]


def test_batch_parse_api_tolerates_one_candidate_search_failure_without_blocking_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _MappedCandidateSearchClient(
        responses={
            "欢迎来到实力至上主义的教室 第四季": [
                MikanCandidate(
                    bangumi_id="4001",
                    title="欢迎来到实力至上主义的教室 第四季",
                    mikan_url="https://mikan.example/Home/Bangumi/4001",
                    source_query="欢迎来到实力至上主义的教室 第四季",
                )
            ]
        },
        errors={
            "杖与剑的魔剑谭 第二季": Stage1Error(
                "mikan_timeout",
                "MiKan HTTP 请求超时",
                "mikan_search",
                {
                    "url": "https://mikan.example/Home/Search?searchstr=secret-token",
                    "cookie": "session-cookie",
                },
            )
        },
    )

    monkeypatch.setattr(
        "apps.migu_orca_web.services.mikan_client_module.create_mikan_client",
        lambda config: client,
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={
            "raw_input": "路哥S4\n杖剑谭S2",
        },
    )

    payload = response.get_json()
    items = payload["result"]["items"]
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert payload["ok"] is True
    assert [item["status"] for item in items] == [
        BATCH_ITEM_STATUS_FOUND,
        BATCH_ITEM_STATUS_EMPTY,
    ]
    assert items[0]["candidates"][0]["bangumi_id"] == "4001"
    assert items[1]["raw_title"] == "杖剑谭S2"
    assert items[1]["canonical_title_candidates"] == ["杖与剑的魔剑谭"]
    assert items[1]["candidates"] == []
    assert "error" not in items[1]
    # A later successful empty fallback makes the final state EMPTY, while the
    # failed query remains non-blocking and its sensitive detail is not exposed.
    assert items[1]["needs_user_review"] is True
    assert "secret-token" not in body
    assert "session-cookie" not in body
    assert "https://mikan.example/Home/Search" not in body


def test_batch_parse_api_candidate_results_only_serialize_public_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SensitiveCandidate(MikanCandidate):
        def __init__(self) -> None:
            super().__init__(
                bangumi_id="9001",
                title="测试番剧",
                mikan_url="https://mikan.example/Home/Bangumi/9001",
                source_query="测试番剧",
                poster_url="https://mikan.example/public/poster.jpg",
                aliases=["公开别名"],
            )
            self.raw_html = "<html>secret-token</html>"
            self.raw_rss_xml = "<rss>raw</rss>"
            self.cookie = "session-cookie"
            self.token = "secret-token"
            self.magnet = "magnet:?xt=urn:btih:secret"

    client = _MappedCandidateSearchClient(
        responses={"测试番剧": [SensitiveCandidate()]}
    )

    monkeypatch.setattr(
        "apps.migu_orca_web.services.mikan_client_module.create_mikan_client",
        lambda config: client,
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={
            "raw_input": "测试番剧",
        },
    )

    payload = response.get_json()
    candidates = payload["result"]["items"][0]["candidates"]
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert payload["ok"] is True
    assert candidates == [
        {
            "bangumi_id": "9001",
            "title": "测试番剧",
            "mikan_url": "https://mikan.example/Home/Bangumi/9001",
            "poster_url": "/api/v1/mikan/posters/"
            + poster_cache_key("https://mikan.example/public/poster.jpg"),
            "source_query": "测试番剧",
            "aliases": ["公开别名"],
            "recommendation": "可能匹配",
        }
    ]
    assert "raw_html" not in body
    assert "raw_rss_xml" not in body
    assert "session-cookie" not in body
    assert "secret-token" not in body
    assert "magnet:?" not in body
    assert "<html" not in body


def test_batch_parse_api_marks_low_confidence_item_for_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 杖剑谭S2 parses at 0.62 confidence (below the 0.7 threshold) and has a
    # single canonical candidate, so it must be flagged for review even though
    # the candidate search returns a result.
    client = _MappedCandidateSearchClient(
        responses={
            "杖与剑的魔剑谭 第二季": [
                MikanCandidate(
                    bangumi_id="2001",
                    title="杖与剑的魔剑谭 第二季",
                    mikan_url="https://mikan.example/Home/Bangumi/2001",
                    source_query="杖与剑的魔剑谭 第二季",
                )
            ]
        }
    )

    monkeypatch.setattr(
        "apps.migu_orca_web.services.mikan_client_module.create_mikan_client",
        lambda config: client,
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "杖剑谭S2"},
    )

    payload = response.get_json()
    item = payload["result"]["items"][0]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert item["status"] == BATCH_ITEM_STATUS_FOUND
    assert item["confidence"] == 0.82
    assert item["candidates"][0]["bangumi_id"] == "2001"
    assert item["needs_user_review"] is True


def test_batch_parse_api_marks_preference_conflict_item_for_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # fallback=none with no preferred subtitle group conflicts with auto
    # selection, so the item is flagged for review even though the parse is
    # high-confidence and the candidate search succeeds.
    storage_dir = tmp_path / "migu-state"
    save_user_preferences(
        load_storage_config(storage_dir),
        VersionedUserPreference(
            version=1,
            subtitle_groups=SubtitleGroupPreference(
                preferred=[],
                excluded=[],
                fallback="none",
            ),
            filter_defaults=FilterDefaults(
                must_contain="",
                must_not_contain="",
                use_regex=False,
                case_sensitive=False,
            ),
            naming=NamingPreference(
                strategy="official_title_season", template="{title}"
            ),
            search=SearchPreference(reuse_explicit_corrections=True),
        ),
    )
    client = _MappedCandidateSearchClient(
        responses={
            "欢迎来到实力至上主义的教室 第四季": [
                MikanCandidate(
                    bangumi_id="4001",
                    title="欢迎来到实力至上主义的教室 第四季",
                    mikan_url="https://mikan.example/Home/Bangumi/4001",
                    source_query="欢迎来到实力至上主义的教室 第四季",
                )
            ]
        }
    )

    monkeypatch.setattr(
        "apps.migu_orca_web.services.mikan_client_module.create_mikan_client",
        lambda config: client,
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={
            "raw_input": "路哥S4",
            "storage_dir": _profile(tmp_path, storage_dir.name),
        },
    )

    payload = response.get_json()
    item = payload["result"]["items"][0]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert item["status"] == BATCH_ITEM_STATUS_FOUND
    assert item["candidates"][0]["bangumi_id"] == "4001"
    assert item["needs_user_review"] is True
    assert any(
        "偏好字幕组存在冲突" in hint for hint in item["review_hints"]
    )
    assert item["preference_warnings"] == [
        "fallback 为 none 且未配置偏好字幕组，不会自动选择字幕组"
    ]


# --- US-155: title-correction API + enhanced batch search ---


def _correction_payload() -> dict[str, Any]:
    return {
        "raw_title": "路哥S4",
        "canonical_title": "欢迎来到实力至上主义的教室",
        "season_hint": "S4",
        "bangumi_metadata": {
            "bangumi_id": "4001",
            "title": "欢迎来到实力至上主义的教室",
        },
        "query_correction": "欢迎来到实力至上主义的教室 第四季",
    }


def _correction_save_body(
    storage_profile: str,
    correction: dict[str, Any] | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"storage_dir": storage_profile}
    if correction is not None:
        body["correction"] = correction
    return body


def test_correction_api_reads_empty_list_when_missing(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().get(f"/api/v1/corrections?storage_dir={_profile(tmp_path, storage_dir.name)}")

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"] == {"corrections": []}


def test_correction_api_save_returns_normalized_list_and_persists(
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "storage"
    payload = _correction_payload()

    response = _client().post(
        "/api/v1/corrections",
        json=_correction_save_body(_profile(tmp_path, storage_dir.name), payload),
    )

    result = response.get_json()
    assert response.status_code == 200
    assert result["ok"] is True
    assert result["result"]["corrections"] == [payload]
    assert result["result"]["corrections"][0]["bangumi_metadata"] == {
        "bangumi_id": "4001",
        "title": "欢迎来到实力至上主义的教室",
    }

    # The saved JSON on disk carries only the defined non-sensitive fields.
    config = load_storage_config(storage_dir)
    written = json.loads(
        (config.corrections_dir / "corrections.json").read_text(encoding="utf-8")
    )
    assert written == {"version": 1, "corrections": [payload]}


def test_correction_api_save_uses_latest_version_for_same_raw_title(
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "storage"
    _client().post(
        "/api/v1/corrections",
        json=_correction_save_body(_profile(tmp_path, storage_dir.name), _correction_payload()),
    )
    updated = {
        **_correction_payload(),
        "canonical_title": "欢迎来到实力至上主义的教室 第四季",
        "query_correction": "欢迎来到实力至上主义的教室 第四季",
    }
    _client().post(
        "/api/v1/corrections",
        json=_correction_save_body(_profile(tmp_path, storage_dir.name), updated),
    )

    response = _client().get(f"/api/v1/corrections?storage_dir={_profile(tmp_path, storage_dir.name)}")

    corrections = response.get_json()["result"]["corrections"]
    assert len(corrections) == 1
    assert corrections[0]["canonical_title"] == "欢迎来到实力至上主义的教室 第四季"


def test_correction_api_save_rejects_missing_correction(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/corrections",
        json=_correction_save_body(_profile(tmp_path, storage_dir.name), None),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_message"] == "请提供修正内容"
    assert payload["error_data"]["details"] == {"field": "correction"}


def test_correction_api_save_rejects_invalid_correction(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/corrections",
        json=_correction_save_body(
            _profile(tmp_path, storage_dir.name), {"canonical_title": "葬送的芙莉莲"}
        ),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_data"]["details"] == {"field": "raw_title"}


def test_correction_api_save_rejects_unknown_field_without_writing(
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/corrections",
        json=_correction_save_body(
            _profile(tmp_path, storage_dir.name), {**_correction_payload(), "token": "secret"}
        ),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert "未定义字段" in payload["error_message"]
    assert not (
        load_storage_config(storage_dir).corrections_dir / "corrections.json"
    ).exists()


def test_correction_api_save_rejects_sensitive_value_without_writing(
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/corrections",
        json=_correction_save_body(
            _profile(tmp_path, storage_dir.name),
            {**_correction_payload(), "query_correction": "https://mikan.example/api"},
        ),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert "敏感内容" in payload["error_message"]
    assert not (
        load_storage_config(storage_dir).corrections_dir / "corrections.json"
    ).exists()


def test_batch_parse_api_searches_enhanced_queries_from_saved_correction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_dir = tmp_path / "storage"
    _client().post(
        "/api/v1/corrections",
        json=_correction_save_body(_profile(tmp_path, storage_dir.name), _correction_payload()),
    )
    client = _MappedCandidateSearchClient(
        responses={
            "欢迎来到实力至上主义的教室 第四季": [
                MikanCandidate(
                    bangumi_id="4001",
                    title="欢迎来到实力至上主义的教室 第四季",
                    mikan_url="https://mikan.example/Home/Bangumi/4001",
                    source_query="欢迎来到实力至上主义的教室 第四季",
                    aliases=["路哥 S4"],
                )
            ]
        }
    )
    monkeypatch.setattr(
        "apps.migu_orca_web.services.mikan_client_module.create_mikan_client",
        lambda config: client,
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "路哥S4", "storage_dir": _profile(tmp_path, storage_dir.name)},
    )

    payload = response.get_json()
    item = payload["result"]["items"][0]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert item["status"] == BATCH_ITEM_STATUS_FOUND
    # One high-priority correction query found candidates, so weaker variants
    # are not sent to MiKan.
    assert client.searches == ["欢迎来到实力至上主义的教室 第四季"]
    assert item["enhanced_search_queries"][0] == {
        "query": "欢迎来到实力至上主义的教室 第四季",
        "original_query": "欢迎来到实力至上主义的教室 第四季",
        "source": "correction:query",
    }
    assert item["candidates"][0]["bangumi_id"] == "4001"


def test_batch_parse_api_falls_back_through_the_unified_correction_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_dir = tmp_path / "storage"
    _client().post(
        "/api/v1/corrections",
        json=_correction_save_body(_profile(tmp_path, storage_dir.name), _correction_payload()),
    )
    # Only an original parse query has a candidate; the enhanced queries do not.
    client = _MappedCandidateSearchClient(
        responses={
            "路哥S4": [
                MikanCandidate(
                    bangumi_id="4001",
                    title="欢迎来到实力至上主义的教室 第四季",
                    mikan_url="https://mikan.example/Home/Bangumi/4001",
                    source_query="路哥S4",
                    aliases=["路哥S4"],
                )
            ]
        }
    )
    monkeypatch.setattr(
        "apps.migu_orca_web.services.mikan_client_module.create_mikan_client",
        lambda config: client,
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "路哥S4", "storage_dir": _profile(tmp_path, storage_dir.name)},
    )

    payload = response.get_json()
    item = payload["result"]["items"][0]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert item["status"] == BATCH_ITEM_STATUS_FOUND
    # The correction and original fallbacks share one bounded plan.
    assert client.searches[:4] == [
        "欢迎来到实力至上主义的教室 第四季",
        "实力至上主义教室 第四季",
        "欢迎来到实力至上主义的教室 第4季",
        "欢迎来到实力至上主义的教室 S4",
    ]
    assert client.searches[-1] == "路哥S4"
    assert item["candidates"][0]["bangumi_id"] == "4001"


def test_batch_parse_api_falls_back_to_original_queries_when_corrections_file_damaged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_dir = tmp_path / "storage"
    config = load_storage_config(storage_dir)
    config.corrections_dir.mkdir(parents=True, exist_ok=True)
    (config.corrections_dir / "corrections.json").write_text(
        "{not valid json", encoding="utf-8"
    )
    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches._search_batch_item_candidates",
        lambda search_queries, mikan_config: [],
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "萌王S4\n路哥S4", "storage_dir": _profile(tmp_path, storage_dir.name)},
    )

    payload = response.get_json()
    items = payload["result"]["items"]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert all(item["status"] == BATCH_ITEM_STATUS_EMPTY for item in items)
    assert all(item["enhanced_search_queries"] == [] for item in items)


def test_batch_parse_api_does_not_leak_poisoned_corrections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_dir = tmp_path / "storage"
    config = load_storage_config(storage_dir)
    config.corrections_dir.mkdir(parents=True, exist_ok=True)
    (config.corrections_dir / "corrections.json").write_text(
        json.dumps(
            {
                "version": 1,
                "corrections": [
                    {
                        "raw_title": "路哥S4",
                        "canonical_title": "https://mikan.example/api?token=secret",
                        "query_correction": "路哥",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches._search_batch_item_candidates",
        lambda search_queries, mikan_config: [],
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "路哥S4", "storage_dir": _profile(tmp_path, storage_dir.name)},
    )

    payload = response.get_json()
    item = payload["result"]["items"][0]
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert payload["ok"] is True
    assert item["status"] == BATCH_ITEM_STATUS_EMPTY
    assert item["enhanced_search_queries"] == []
    assert "mikan.example" not in body
    assert "token=secret" not in body


def test_batch_parse_api_failed_search_keeps_enhanced_queries_for_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_dir = tmp_path / "storage"
    _client().post(
        "/api/v1/corrections",
        json=_correction_save_body(_profile(tmp_path, storage_dir.name), _correction_payload()),
    )
    # Enhanced queries find nothing, and the original-query fallback raises.
    client = _MappedCandidateSearchClient()

    def _raise(*args: object, **kwargs: object) -> None:
        raise Stage1Error("mikan_timeout", "MiKan HTTP 请求超时", "mikan_search")

    monkeypatch.setattr(
        "apps.migu_orca_web.services.mikan_client_module.create_mikan_client",
        lambda config: client,
    )
    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches._search_batch_item_candidates",
        _raise,
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "路哥S4", "storage_dir": _profile(tmp_path, storage_dir.name)},
    )

    payload = response.get_json()
    item = payload["result"]["items"][0]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert item["status"] == BATCH_ITEM_STATUS_FAILED
    # The enhanced queries are still returned so the user can review what was
    # attempted even though the item failed.
    assert item["enhanced_search_queries"]
    assert all(
        entry["source"] in ("correction:query", "correction:canonical")
        for entry in item["enhanced_search_queries"]
    )


def test_candidate_search_api_cache_expires_after_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mikan_engine.controllers.mikan_candidate_cache import CandidateSearchCache

    now_holder = {"value": 1000.0}

    def _now() -> float:
        return now_holder["value"]

    cache = CandidateSearchCache(ttl_seconds=300, now=_now)
    monkeypatch.setattr("apps.migu_orca_web.services.candidate_search_cache", cache)

    transport = _FakeMikanTransport(
        {
        "https://mikanani.me/Home/Search?searchstr=%E8%8A%99%E8%8E%89%E8%8E%B2": (
                '<section class="related-recommendations">'
                '<div class="bangumi-item">'
                '<a class="an-text" href="/Home/Bangumi/2353">葬送的芙莉莲</a>'
                "</div>"
                "</section>"
            )
        }
    )

    def fake_create_mikan_client(config: MikanConfig):
        return create_mikan_client(config, transport=transport)

    monkeypatch.setattr(
        "apps.migu_orca_web.services.mikan_client_module.create_mikan_client",
        fake_create_mikan_client,
    )

    payload = {
        "query": "芙莉莲",
    }
    first = _client().post("/api/v1/mikan/candidates", json=payload)
    assert first.status_code == 200
    assert len(transport.requests) == 1

    now_holder["value"] += 301.0
    second = _client().post("/api/v1/mikan/candidates", json=payload)
    assert second.status_code == 200
    assert (
        second.get_json()["result"]["candidates"]
        == first.get_json()["result"]["candidates"]
    )
    assert len(transport.requests) == 2


def test_default_request_create_does_not_call_candidate_search_api_or_real_mikan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fail_if_called(*args: Any, **kwargs: Any) -> Any:
        nonlocal called
        called = True
        raise AssertionError(
            "default fixture generation must not create a real MiKan client"
        )

    monkeypatch.setattr(
        "apps.migu_orca_web.services.mikan_client_module.create_mikan_client",
        fail_if_called,
    )

    response = _client().post(
        "/api/v1/requests",
        json={"title": "芙莉莲"},
    )

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert called is True




def _issue_draft(
    client: FlaskClient, title: str = "咒术回战"
) -> tuple[str, int]:
    """Generate an unsaved preview draft; return (draft_id, draft_revision)."""
    response = client.post(
        "/api/v1/requests",
        json={"title": title},
    )
    payload = response.get_json()
    assert response.status_code == 200
    result = payload["result"]
    assert isinstance(result["draft_id"], str)
    assert result["draft_revision"] == 1
    return result["draft_id"], result["draft_revision"]


def test_preview_modify_recomputes_seeds_without_saving(tmp_path: Path) -> None:
    draft_id, draft_revision = _issue_draft(_client(), "咒术回战")

    response = _client().post(
        "/api/v1/requests/preview-modify",
        json={
            "draft_id": draft_id,
            "base_revision": draft_revision,
            "patch": {
                "filter_rule": {
                    "must_not_contain": "V2",
                    "use_regex": False,
                    "case_sensitive": False,
                }
            },
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    modified = payload["result"]["request"]
    assert modified["confirmable_config"]["filter_rule"]["must_not_contain"] == "V2"
    # US-194/211: the modify result keeps the same draft_id and returns the
    # bumped draft_revision so the client can save with the latest base.
    assert payload["result"]["draft_id"] == draft_id
    assert payload["result"]["draft_revision"] == 2
    # The preview is recomputed in memory and never written to storage.
    assert not (tmp_path / "storage").exists()

    # Seeds were recomputed: the Loli source now excludes the V2 seed with a
    # Chinese exclusion reason, so valid + invalid equals total.
    selected_group = modified["confirmable_config"]["selected_subtitle_group"]
    source = next(
        s for s in modified["source_info"]["rss_sources"]
        if s["subtitle_group"] == selected_group
    )
    assert source["valid_seed_count"] + source["invalid_seed_count"] == source["total_seed_count"]
    excluded = source["excluded_seed_names"]
    assert any(
        "V2" in entry["name"] and entry["reason"] == "命中排除规则：V2"
        for entry in excluded
    )


def test_preview_modify_switches_selected_subtitle_group(tmp_path: Path) -> None:
    client = _client()
    draft_id, draft_revision = _issue_draft(client, "咒术回战")
    # The stored draft's groups mirror the fixture; read them via the response.
    issued = client.post(
        "/api/v1/requests",
        json={"title": "咒术回战"},
    ).get_json()["result"]
    preview = issued["request"]
    groups = {s["subtitle_group"] for s in preview["source_info"]["rss_sources"]}
    current = preview["confirmable_config"]["selected_subtitle_group"]
    other = next(g for g in groups if g != current)

    response = client.post(
        "/api/v1/requests/preview-modify",
        json={
            "draft_id": draft_id,
            "base_revision": draft_revision,
            "patch": {"selected_subtitle_group": other},
        },
    )

    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["result"]["draft_revision"] == 2
    modified = payload["result"]["request"]
    confirmable = modified["confirmable_config"]
    assert confirmable["selected_subtitle_group"] == other
    other_source = next(
        s for s in modified["source_info"]["rss_sources"]
        if s["subtitle_group"] == other
    )
    assert confirmable["selected_rss_url"] == other_source["rss_url"]
    # effective_seed_names now reflect the newly selected group's valid seeds.
    assert confirmable["effective_seed_names"] == other_source["valid_seed_names"]


def test_preview_modify_rejects_invalid_patch_field() -> None:
    draft_id, draft_revision = _issue_draft(_client(), "芙莉莲")

    response = _client().post(
        "/api/v1/requests/preview-modify",
        json={
            "draft_id": draft_id,
            "base_revision": draft_revision,
            "patch": {"illegal_field": "x"},
        },
    )

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "invalid_modify_patch_field"


def test_preview_modify_stale_base_revision_conflicts() -> None:
    """US-211: a stale base_revision leaves the server-side draft untouched."""
    client = _client()
    draft_id, draft_revision = _issue_draft(client, "芙莉莲")
    assert draft_revision == 1

    first = client.post(
        "/api/v1/requests/preview-modify",
        json={
            "draft_id": draft_id,
            "base_revision": 1,
            "patch": {"filter_rule": {"must_not_contain": "V2", "use_regex": False, "case_sensitive": False}},
        },
    )
    assert first.status_code == 200
    assert first.get_json()["result"]["draft_revision"] == 2

    stale = client.post(
        "/api/v1/requests/preview-modify",
        json={
            "draft_id": draft_id,
            "base_revision": 1,
            "patch": {"expected_folder_name": "stale-write"},
        },
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
    assert "stale-write" not in str(payload)


def test_preview_modify_rejects_unknown_draft() -> None:
    response = _client().post(
        "/api/v1/requests/preview-modify",
        json={
            "draft_id": "not-issued",
            "base_revision": 1,
            "patch": {"expected_folder_name": "x"},
        },
    )

    payload = response.get_json()
    assert response.status_code == 409
    assert payload["ok"] is False
    assert payload["error_type"] == "draft_expired"
    assert payload["error_message"] == "订阅草案已过期或不存在，请重新生成"










def _save_confirm(
    client: FlaskClient,
    draft_id: str,
    base_revision: int,
    key: str,
    storage_dir: str | None = "storage",
):
    return client.post(
        "/api/v1/requests/save-confirm",
        json={
            "draft_id": draft_id,
            "base_revision": base_revision,
            "idempotency_key": key,
            **({"storage_dir": storage_dir} if storage_dir is not None else {}),
        },
    )


def test_save_confirm_persists_confirms_and_returns_handoff(tmp_path: Path) -> None:
    """US-214: one save-confirm call persists, accepts and hands off ACCEPTED."""
    storage_dir = tmp_path / "storage"
    client = _client()
    issued = client.post(
        "/api/v1/requests", json={"title": "芙莉莲"}
    ).get_json()["result"]
    draft_id = issued["draft_id"]
    request_id = issued["request"]["request_id"]

    response = _save_confirm(client, draft_id, 1, "view-key-1", _profile(tmp_path, storage_dir.name))
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    result = payload["result"]
    assert result["outcome"] == "CONFIRMED"
    assert result["request"]["status"] == "ACCEPTED"
    assert result["request"]["request_id"] == request_id
    assert result["handoff"]["request_id"] == request_id
    assert result["handoff"]["status"] == "ACCEPTED"
    assert result["handoff"]["next_action"] == "OPEN_TRACKING"
    # On-disk state: one ACCEPTED request + one CONFIRMED idempotency record.
    saved = load_request_snapshot(load_storage_config(storage_dir), request_id)
    assert saved["status"] == "ACCEPTED"
    assert sorted(path.name for path in (storage_dir / "requests").glob("*.json")) == [
        f"{request_id}.json"
    ]
    record = load_idempotency_record(load_storage_config(storage_dir), "view-key-1")
    assert record is not None
    assert record["state"] == "CONFIRMED"
    assert record["request_id"] == request_id


def test_save_confirm_same_key_retry_returns_same_request(tmp_path: Path) -> None:
    """US-214: a same-key retry replays the terminal CONFIRMED outcome."""
    storage_dir = tmp_path / "storage"
    client = _client()
    draft_id, _ = _issue_draft(client, "芙莉莲")
    profile = _profile(tmp_path, storage_dir.name)

    first = _save_confirm(client, draft_id, 1, "view-retry-key", profile)
    assert first.status_code == 200
    first_handoff = first.get_json()["result"]["handoff"]

    second = _save_confirm(client, draft_id, 1, "view-retry-key", profile)
    assert second.status_code == 200
    second_handoff = second.get_json()["result"]["handoff"]
    assert second_handoff == first_handoff
    assert sorted(path.name for path in (storage_dir / "requests").glob("*.json")) == [
        f"{first_handoff['request_id']}.json"
    ]


def test_save_confirm_confirm_failure_returns_saved_confirm_failed_envelope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """US-214: saved-but-unconfirmed returns the frozen SAVED_CONFIRM_FAILED details."""
    from apps.migu_orca_web import routes_requests

    storage_dir = tmp_path / "storage"
    client = _client()
    issued = client.post(
        "/api/v1/requests", json={"title": "芙莉莲"}
    ).get_json()["result"]
    draft_id = issued["draft_id"]
    request_id = issued["request"]["request_id"]

    def failing_confirm(storage_dir_arg: Any) -> Any:
        def confirm_saved(_request_id: str) -> dict[str, Any]:
            raise Stage1Error(
                "invalid_request_status",
                "只有待确认订阅方案可以执行确认操作",
                "confirm_request",
                {"status": "PENDING_CONFIRM"},
            )

        return confirm_saved

    monkeypatch.setattr(routes_requests, "_build_save_confirm_confirm_saved", failing_confirm)

    response = _save_confirm(client, draft_id, 1, "view-confirm-fail", _profile(tmp_path, storage_dir.name))
    payload = response.get_json()
    assert response.status_code == 409
    assert payload["ok"] is False
    assert payload["error_type"] == "save_confirm_failed"
    assert payload["error_data"]["details"] == {
        "outcome": "SAVED_CONFIRM_FAILED",
        "request_id": request_id,
        "retry_action": "ACCEPT_SAVED_REQUEST",
    }
    serialized = str(payload)
    assert draft_id not in serialized
    assert str(tmp_path) not in serialized
    # The saved request stays PENDING_CONFIRM (accept never ran) and is on disk.
    assert load_request_snapshot(load_storage_config(storage_dir), request_id)["status"] == "PENDING_CONFIRM"


def test_save_confirm_persist_failure_releases_draft_for_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """US-214: a persistence failure keeps the draft; a same-id/key retry succeeds."""
    from apps.migu_orca_entry.controllers.entry_controller import apply_request_save_action as original_save

    storage_dir = tmp_path / "storage"
    client = _client()
    draft_id, _ = _issue_draft(client, "芙莉莲")
    profile = _profile(tmp_path, storage_dir.name)
    failures = {"count": 0}

    def flaky_save(result: dict[str, Any], save_request: bool, **kwargs: object) -> dict[str, Any]:
        if failures["count"] == 0:
            failures["count"] += 1
            return {
                "success": False,
                "request": None,
                "error": Stage1Error(
                    "storage_error",
                    "模拟写盘失败",
                    "save_request_snapshot",
                    {"reason": "disk full"},
                ).as_dict(),
            }
        return original_save(result, save_request, **kwargs)

    monkeypatch.setattr(
        "apps.migu_orca_web.services.apply_request_save_action", flaky_save
    )

    first = _save_confirm(client, draft_id, 1, "view-persist-fail", profile)
    assert first.status_code == 500
    assert first.get_json()["error_type"] == "storage_error"

    second = _save_confirm(client, draft_id, 1, "view-persist-fail", profile)
    assert second.status_code == 200
    result = second.get_json()["result"]
    assert result["outcome"] == "CONFIRMED"
    # Exactly one Request exists.
    assert len(list((storage_dir / "requests").glob("*.json"))) == 1


def test_create_request_returns_validation_error_for_missing_title() -> None:
    response = _client().post(
        "/api/v1/requests",
        json={"save_request": False},
    )

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert payload["error_data"]["errors"][0]["field"] == "title"


def test_create_request_returns_validation_error_for_blank_title() -> None:
    response = _client().post(
        "/api/v1/requests",
        json={"title": "   "},
    )

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert payload["error_data"]["errors"][0]["field"] == "title"


def test_create_request_returns_validation_error_for_invalid_storage_dir_type() -> None:
    response = _client().post(
        "/api/v1/requests",
        json={"title": "芙莉莲", "storage_dir": 123},
    )

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert payload["error_data"]["errors"][0]["field"] == "storage_dir"






















def _batch_accept(
    client: FlaskClient,
    batch_id: str,
    storage_dir: Path,
    items: list[dict[str, Any]],
    item_ids: list[str] | None = None,
) -> Any:
    """POST the batch accept endpoint and return the raw test response."""
    payload: dict[str, Any] = {
        "items": items,
        "storage_dir": storage_dir.name,
    }
    if item_ids is not None:
        payload["item_ids"] = item_ids
    return client.post(f"/api/v1/batches/{batch_id}/accept", json=payload)


def _batch_submit_payload(storage_profile: str) -> dict[str, Any]:
    return {
        "storage_dir": storage_profile,
        "confirm": True,
        "ab_config": {
            "auth_mode": "api_token",
            "base_url": "http://auto-bangumi.local",
            "token": "secret-token",
            "fallback_enabled": False,
        },
    }




























































def _saved_request_with_ab_result(
    tmp_path: Path,
    title: str,
    request_id: str,
) -> None:
    """Save an ACCEPTED Request snapshot that already carries an AB result."""
    request = _saved_accepted_request(tmp_path, title, request_id)
    request["ab_submit_result"] = {
        "success": True,
        "ab_subscription_id": "fake-ab-subscription",
        "ab_response": {"id": "fake-ab-subscription"},
        "fallback_config": None,
        "error": None,
    }
    save_request_snapshot(load_storage_config(tmp_path / "storage"), request)












def _preferences_save_body(
    storage_profile: str,
    preferences: dict[str, Any] | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"storage_dir": storage_profile}
    if preferences is not None:
        body["preferences"] = preferences
    return body


def _full_preferences_payload() -> dict[str, Any]:
    return {
        "version": 1,
        "subtitle_groups": {
            "preferred": ["Loli", "喵萌"],
            "excluded": ["示例组"],
            "fallback": "next_preferred",
        },
        "filter_defaults": {
            "must_contain": "1080p",
            "must_not_contain": "合集版",
            "use_regex": False,
            "case_sensitive": False,
        },
        "naming": {"strategy": "official_title_season", "template": "{title}"},
        "search": {"reuse_explicit_corrections": True},
    }


def test_preference_api_reads_defaults_when_missing(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().get(
        f"/api/v1/preferences?storage_dir={_profile(tmp_path, storage_dir.name)}"
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


def test_preference_api_reads_saved_preferences(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"
    _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(_profile(tmp_path, storage_dir.name), _full_preferences_payload()),
    )

    response = _client().get(
        f"/api/v1/preferences?storage_dir={_profile(tmp_path, storage_dir.name)}"
    )

    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["result"] == _full_preferences_payload()


def test_preference_api_save_returns_normalized_preferences_and_persists(
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "storage"
    payload = _full_preferences_payload()

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(_profile(tmp_path, storage_dir.name), payload),
    )

    result = response.get_json()
    assert response.status_code == 200
    assert result["ok"] is True
    assert result["result"] == payload

    # The saved JSON on disk carries only the defined non-sensitive fields.
    config = load_storage_config(storage_dir)
    written = json.loads(
        (config.preferences_dir / "user_preferences.json").read_text(
            encoding="utf-8"
        )
    )
    assert written == payload


def test_preference_api_save_accepts_empty_payload_as_reset(
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "storage"
    _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(_profile(tmp_path, storage_dir.name), _full_preferences_payload()),
    )

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(_profile(tmp_path, storage_dir.name), {}),
    )

    result = response.get_json()
    assert result["ok"] is True
    assert result["result"]["subtitle_groups"]["preferred"] == []
    assert result["result"]["subtitle_groups"]["excluded"] == []
    assert result["result"]["filter_defaults"]["must_contain"] == ""


def test_preference_api_save_rejects_missing_preferences(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(_profile(tmp_path, storage_dir.name), None),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_message"] == "请提供偏好配置"
    assert payload["error_data"]["details"] == {"field": "preferences"}


def test_preference_api_save_rejects_non_object_payload(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(_profile(tmp_path, storage_dir.name), ["Loli"]),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_message"] == "偏好配置必须是对象"


def test_preference_api_save_rejects_unknown_field_without_leaking(
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(
            _profile(tmp_path, storage_dir.name),
            {
                "subtitle_groups": {"preferred": ["Loli"]},
                "endpoint": "https://secret-endpoint.example/api",
            },
        ),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_message"] == "preferences 包含未定义字段"
    assert "secret-endpoint" not in str(payload)


def test_preference_api_save_rejects_empty_string_list_item(
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(
            _profile(tmp_path, storage_dir.name),
            {"subtitle_groups": {"preferred": [""]}},
        ),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_data"]["details"] == {
        "field": "subtitle_groups.preferred"
    }
    assert "空字符串" in payload["error_message"]


def test_preference_api_save_rejects_duplicate_subtitle_groups(
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(
            _profile(tmp_path, storage_dir.name),
            {"subtitle_groups": {"preferred": ["Loli", "Loli"]}},
        ),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_data"]["details"] == {
        "field": "subtitle_groups.preferred"
    }
    assert "重复" in payload["error_message"]


def test_preference_api_save_rejects_group_in_both_lists(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(
            _profile(tmp_path, storage_dir.name),
            {
                "subtitle_groups": {
                    "preferred": ["Loli"],
                    "excluded": ["Loli"],
                }
            },
        ),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_data"]["details"] == {"field": "subtitle_groups"}
    assert "不能同时出现" in payload["error_message"]


def test_preference_api_save_rejects_invalid_fallback_enum(
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(
            _profile(tmp_path, storage_dir.name),
            {"subtitle_groups": {"fallback": "auto"}},
        ),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_data"]["details"] == {
        "field": "subtitle_groups.fallback"
    }


def test_preference_api_save_rejects_invalid_naming_strategy(
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(
            _profile(tmp_path, storage_dir.name),
            {"naming": {"strategy": "random"}},
        ),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_data"]["details"] == {"field": "naming.strategy"}


def test_preference_api_save_rejects_non_boolean_filter_flag(
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(
            _profile(tmp_path, storage_dir.name),
            {"filter_defaults": {"use_regex": "yes"}},
        ),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_data"]["details"] == {
        "field": "filter_defaults.use_regex"
    }


def test_preference_api_save_rejects_overlong_string(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(
            _profile(tmp_path, storage_dir.name),
            {"subtitle_groups": {"preferred": ["长" * 101]}},
        ),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert "长度不能超过" in payload["error_message"]


def test_preference_api_save_rejects_sensitive_values(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(
            _profile(tmp_path, storage_dir.name),
            {"subtitle_groups": {"preferred": ["https://mikan.example/Home/Search"]}},
        ),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert "敏感内容" in payload["error_message"]
    assert "https://mikan.example" not in str(payload)
    # No preference file is written for an illegal save.
    config = load_storage_config(storage_dir)
    assert not (config.preferences_dir / "user_preferences.json").exists()


def test_preference_api_save_does_not_leak_sensitive_values(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(_profile(tmp_path, storage_dir.name), _full_preferences_payload()),
    )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    for marker in (
        "http://",
        "https://",
        "magnet:",
        "token",
        "secret",
        "cookie",
        "Authorization",
        "raw_html",
        "raw_rss",
        "<html",
        "<rss",
    ):
        assert marker not in body.lower()


def test_preference_api_save_storage_failure_returns_chinese_envelope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "storage"

    def fail_save(*args: object, **kwargs: object) -> dict[str, Any]:
        raise Stage1Error(
            "storage_error",
            "保存用户偏好 JSON 失败",
            "save_user_preferences",
            {
                "reason": f"cannot write {tmp_path}/private-token at https://example.test/api",
                "directory": "preferences",
            },
        )

    monkeypatch.setattr(
        "apps.migu_orca_web.routes_settings.save_user_preferences",
        fail_save,
    )

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(_profile(tmp_path, storage_dir.name), _full_preferences_payload()),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "storage_error"
    assert payload["error_message"] == "保存用户偏好 JSON 失败"
    assert payload["error_data"]["failed_step"] == "save_user_preferences"
    assert str(tmp_path) not in str(payload)
    assert "https://example.test/api" not in str(payload)
    assert "token" not in str(payload).lower()


# ---------------------------------------------------------------------------
# Batch save-confirm (US-216)
# ---------------------------------------------------------------------------


def _issue_batch_draft_items(
    client: FlaskClient,
    titles: list[str],
) -> list[dict[str, object]]:
    """Issue one preview draft per title; return batch item descriptors."""
    items: list[dict[str, object]] = []
    for index, title in enumerate(titles):
        issued = client.post(
            "/api/v1/requests", json={"title": title}
        ).get_json()["result"]
        items.append(
            {
                "item_id": f"item-{index}",
                "draft_id": issued["draft_id"],
                "base_revision": issued["draft_revision"],
                "idempotency_key": f"view-batch-key-{index}",
            }
        )
    return items


def _batch_save_confirm(
    client: FlaskClient,
    items: list[dict[str, object]],
    *,
    batch_id: str = "batch-1",
    item_ids: list[str] | None = None,
    storage_dir: str = "storage",
) -> Any:
    payload: dict[str, object] = {
        "batch_id": batch_id,
        "items": items,
        "storage_dir": storage_dir,
    }
    if item_ids is not None:
        payload["item_ids"] = item_ids
    return client.post(
        f"/api/v1/batches/{batch_id}/save-confirm", json=payload
    )


def test_batch_save_confirm_api_returns_partial_success_result(
    tmp_path: Path,
) -> None:
    """US-216: a selected batch confirms per item with a sanitized result."""
    storage_dir = tmp_path / "storage"
    client = _client()
    items = _issue_batch_draft_items(client, ["芙莉莲", "咒术回战"])

    response = _batch_save_confirm(client, items)
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    result = payload["result"]
    assert set(result) == {"batch_id", "results", "summary"}
    assert result["batch_id"] == "batch-1"
    assert result["summary"] == {"requested": 2, "confirmed": 2, "failed": 0}
    assert [row["item_id"] for row in result["results"]] == ["item-0", "item-1"]
    for row in result["results"]:
        assert row["outcome"] == "CONFIRMED"
        assert row["status"] == "ACCEPTED"
        assert row["request_id"]
        assert row["error_type"] is None
        assert row["error_message"] is None
        assert load_request_snapshot(
            load_storage_config(storage_dir), row["request_id"]
        )["status"] == "ACCEPTED"
    assert len(list((storage_dir / "requests").glob("*.json"))) == 2


def test_batch_save_confirm_api_stale_item_fails_without_rolling_back_sibling(
    tmp_path: Path,
) -> None:
    """US-216: a stale revision item fails; the confirmed sibling stays."""
    storage_dir = tmp_path / "storage"
    client = _client()
    items = _issue_batch_draft_items(client, ["芙莉莲", "咒术回战"])
    stale = items[1]
    bump = client.post(
        "/api/v1/requests/preview-modify",
        json={
            "draft_id": stale["draft_id"],
            "base_revision": stale["base_revision"],
            "patch": {"expected_folder_name": "并发修改"},
        },
    )
    assert bump.status_code == 200

    response = _batch_save_confirm(client, items)
    payload = response.get_json()
    assert response.status_code == 200
    result = payload["result"]
    assert result["summary"] == {"requested": 2, "confirmed": 1, "failed": 1}
    ok_row = result["results"][0]
    assert ok_row["outcome"] == "CONFIRMED"
    assert ok_row["status"] == "ACCEPTED"
    bad_row = result["results"][1]
    assert bad_row["outcome"] == "failed"
    assert bad_row["error_type"] == "draft_revision_conflict"
    assert bad_row["error_message"] == "草案已被更新，请基于最新版本重试"
    assert bad_row["request_id"] is None
    serialized = str(payload)
    assert stale["draft_id"] not in serialized
    assert str(tmp_path) not in serialized
    # One Request file exists; the failed draft survives for a retry at r2.
    assert len(list((storage_dir / "requests").glob("*.json"))) == 1


def test_batch_save_confirm_api_same_key_retry_replays_same_request(
    tmp_path: Path,
) -> None:
    """US-216: a same-key retry of a confirmed item never duplicates it."""
    storage_dir = tmp_path / "storage"
    client = _client()
    (item,) = _issue_batch_draft_items(client, ["芙莉莲"])

    first = _batch_save_confirm(client, [item])
    assert first.status_code == 200
    request_id = first.get_json()["result"]["results"][0]["request_id"]

    second = _batch_save_confirm(client, [item])
    payload = second.get_json()
    assert second.status_code == 200
    row = payload["result"]["results"][0]
    assert row["outcome"] == "CONFIRMED"
    assert row["request_id"] == request_id
    assert len(list((storage_dir / "requests").glob("*.json"))) == 1


def test_batch_save_confirm_api_item_ids_selects_preserving_order(
    tmp_path: Path,
) -> None:
    """US-216: item_ids selects a subset while preserving the input order."""
    storage_dir = tmp_path / "storage"
    client = _client()
    items = _issue_batch_draft_items(client, ["芙莉莲", "咒术回战", "芙莉莲"])

    response = _batch_save_confirm(
        client, items, item_ids=["item-2", "item-0"]
    )
    payload = response.get_json()
    assert response.status_code == 200
    result = payload["result"]
    assert [row["item_id"] for row in result["results"]] == ["item-0", "item-2"]
    assert result["summary"] == {"requested": 2, "confirmed": 2, "failed": 0}
    assert len(list((storage_dir / "requests").glob("*.json"))) == 2


def test_batch_save_confirm_api_confirm_failure_is_per_item_failed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """US-216: a saved-but-unconfirmed item is per-item failed, not HTTP 409."""
    from apps.migu_orca_web import routes_requests

    storage_dir = tmp_path / "storage"
    client = _client()
    items = _issue_batch_draft_items(client, ["芙莉莲", "咒术回战"])

    def failing_confirm(storage_dir_arg: Any) -> Any:
        def confirm_saved(_request_id: str) -> dict[str, Any]:
            raise Stage1Error(
                "invalid_request_status",
                "只有待确认订阅方案可以执行确认操作",
                "confirm_request",
                {"status": "PENDING_CONFIRM"},
            )

        return confirm_saved

    monkeypatch.setattr(
        routes_requests, "_build_save_confirm_confirm_saved", failing_confirm
    )

    response = _batch_save_confirm(client, items)
    payload = response.get_json()
    assert response.status_code == 200
    result = payload["result"]
    assert result["summary"] == {"requested": 2, "confirmed": 0, "failed": 2}
    for row in result["results"]:
        assert row["outcome"] == "failed"
        assert row["error_type"] == "save_confirm_failed"
        assert row["error_message"] == "订阅方案已保存但确认失败，请对已保存的方案重试确认"
        assert isinstance(row["request_id"], str)
        assert load_request_snapshot(
            load_storage_config(storage_dir), row["request_id"]
        )["status"] == "PENDING_CONFIRM"
    serialized = str(payload)
    for item in items:
        assert item["draft_id"] not in serialized
    assert str(tmp_path) not in serialized


def test_batch_save_confirm_api_persist_failure_fails_item_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """US-216: a persistence failure is a per-item failure, never a 500."""
    from apps.migu_orca_entry.controllers.entry_controller import (
        apply_request_save_action as original_save,
    )

    storage_dir = tmp_path / "storage"
    client = _client()
    items = _issue_batch_draft_items(client, ["芙莉莲", "咒术回战"])
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

    response = _batch_save_confirm(client, items)
    payload = response.get_json()
    assert response.status_code == 200
    result = payload["result"]
    assert result["summary"] == {"requested": 2, "confirmed": 1, "failed": 1}
    rows = result["results"]
    failed_row = rows[0]
    assert failed_row["outcome"] == "failed"
    assert failed_row["error_type"] == "storage_error"
    assert failed_row["request_id"] is None
    serialized = str(payload)
    assert str(tmp_path) not in serialized
    # The failed item's draft was released, so the same payload can be retried.
    retry = _batch_save_confirm(
        client, [{"item_id": "item-0", **items[0]}]
    )
    retry_payload = retry.get_json()
    assert retry.status_code == 200
    assert retry_payload["result"]["summary"] == {
        "requested": 1,
        "confirmed": 1,
        "failed": 0,
    }
    assert len(list((storage_dir / "requests").glob("*.json"))) == 2


def test_batch_save_confirm_api_rejects_request_level_bad_storage(
    tmp_path: Path,
) -> None:
    """US-216: a request-level storage error stays an ordinary failure envelope."""
    client = _client()
    (item,) = _issue_batch_draft_items(client, ["芙莉莲"])
    response = _batch_save_confirm(
        client, [item], storage_dir="/etc/private"
    )
    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "invalid_storage_dir"
    serialized = str(payload)
    assert item["draft_id"] not in serialized
    assert "/etc/private" not in serialized


def test_save_confirm_terminal_replay_rejects_reserved_draft(
    tmp_path: Path,
) -> None:
    """Stage 28 boundary fix (real DraftStore wiring): a reserved draft must not
    replay an unrelated terminal record as its own success.

    - draft-A confirms under ``key-old`` (CONFIRMED terminal record).
    - draft-B (different plan) is reserved by another save-in-progress.
    - reusing ``key-old`` against draft-B must return 409 draft_reserved, never
      the old Request of draft-A.
    """
    from apps.migu_orca_web.drafts import draft_store

    storage_dir = tmp_path / "storage"
    client = _client()
    profile = _profile(tmp_path, storage_dir.name)

    # draft-A: fully confirmed under key-old.
    draft_a_id, _ = _issue_draft(client, "芙莉莲")
    first = _save_confirm(client, draft_a_id, 1, "key-old", profile)
    assert first.status_code == 200
    old_request_id = first.get_json()["result"]["handoff"]["request_id"]

    # draft-B: a different plan, reserved by a save-in-progress.
    draft_b_id, _ = _issue_draft(client, "咒术回战")
    reserved_request, reason = draft_store.reserve_for_save(draft_b_id, 1)
    assert reserved_request is not None
    assert reason == "ok"
    try:
        response = _save_confirm(client, draft_b_id, 1, "key-old", profile)
    finally:
        draft_store.release_save(draft_b_id)

    payload = response.get_json()
    assert response.status_code == 409
    assert payload["ok"] is False
    assert payload["error_type"] == "draft_reserved"
    # The old Request of draft-A is never returned.
    assert old_request_id not in str(payload)
    assert draft_b_id not in str(payload)


def test_batch_save_confirm_terminal_replay_reserved_draft_is_per_item_failed(
    tmp_path: Path,
) -> None:
    """Stage 28 boundary fix (batch): a reserved draft under a stale key is a
    sanitized per-item failure, never the old request_id as this item's success."""
    from apps.migu_orca_web.drafts import draft_store

    storage_dir = tmp_path / "storage"
    client = _client()
    profile = _profile(tmp_path, storage_dir.name)

    # Confirm one draft under key-batch-old.
    confirmed_draft_id, _ = _issue_draft(client, "芙莉莲")
    first = _save_confirm(client, confirmed_draft_id, 1, "key-batch-old", profile)
    assert first.status_code == 200
    old_request_id = first.get_json()["result"]["handoff"]["request_id"]

    # A different draft, reserved, reused with the same key-batch-old.
    reserved_draft_id, _ = _issue_draft(client, "咒术回战")
    reserved_request, reason = draft_store.reserve_for_save(reserved_draft_id, 1)
    assert reserved_request is not None
    assert reason == "ok"
    item = {
        "item_id": "item-0",
        "draft_id": reserved_draft_id,
        "base_revision": 1,
        "idempotency_key": "key-batch-old",
    }
    try:
        response = _batch_save_confirm(client, [item], batch_id="batch-reserved")
    finally:
        draft_store.release_save(reserved_draft_id)

    payload = response.get_json()
    assert response.status_code == 200  # partial-success envelope
    result = payload["result"]
    row = result["results"][0]
    assert row["outcome"] == "failed"
    assert row["error_type"] == "draft_reserved"
    assert row["request_id"] is None  # NOT the old request_id
    assert old_request_id not in str(payload)
    assert reserved_draft_id not in str(payload)


# ---------------------------------------------------------------------------
# Stage 28 static-review fixes: strict save-confirm DTOs (US-213/214/216)
# ---------------------------------------------------------------------------


def test_save_confirm_rejects_unknown_sensitive_fields(tmp_path: Path) -> None:
    """US-213 fix: single save-confirm rejects unknown fields instead of ignoring.

    A leaked ``request``/``draft``/``token`` key must fail with 400
    ``data_validation_errors`` and must never echo the sensitive value.
    """
    storage_dir = tmp_path / "storage"
    client = _client()
    draft_id, _ = _issue_draft(client, "芙莉莲")

    response = client.post(
        "/api/v1/requests/save-confirm",
        json={
            "draft_id": draft_id,
            "base_revision": 1,
            "idempotency_key": "strict-key-1",
            "storage_dir": _profile(tmp_path, storage_dir.name),
            "token": "super-secret-token",
        },
    )
    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert "super-secret-token" not in str(payload)
    # A full Request payload is rejected too.
    response2 = client.post(
        "/api/v1/requests/save-confirm",
        json={
            "draft_id": draft_id,
            "base_revision": 1,
            "idempotency_key": "strict-key-2",
            "storage_dir": _profile(tmp_path, storage_dir.name),
            "request": {"status": "ACCEPTED", "title": "芙莉莲"},
        },
    )
    assert response2.status_code == 400
    assert response2.get_json()["error_type"] == "data_validation_errors"


def test_batch_save_confirm_rejects_unknown_top_level_and_item_fields(
    tmp_path: Path,
) -> None:
    """US-213 fix: batch save-confirm rejects unknown top-level and item fields."""
    client = _client()
    (item,) = _issue_batch_draft_items(client, ["芙莉莲"])

    # Top-level unknown field.
    top = client.post(
        "/api/v1/batches/batch-1/save-confirm",
        json={
            "batch_id": "batch-1",
            "items": [item],
            "storage_dir": "storage",
            "token": "leaked-token",
        },
    )
    assert top.status_code == 400
    assert top.get_json()["error_type"] == "data_validation_errors"
    assert "leaked-token" not in str(top.get_json())

    # Item-level unknown field (a full Request leak).
    item_with_request = {**item, "request": {"status": "ACCEPTED"}}
    nested = client.post(
        "/api/v1/batches/batch-1/save-confirm",
        json={
            "batch_id": "batch-1",
            "items": [item_with_request],
            "storage_dir": "storage",
        },
    )
    assert nested.status_code == 400
    assert nested.get_json()["error_type"] == "data_validation_errors"


# ---------------------------------------------------------------------------
# Stage 28 static-review fixes: safe-info value-level redaction (US-217)
# ---------------------------------------------------------------------------


def test_safe_info_redacts_embedded_sensitive_text_and_non_string_values(
    tmp_path: Path,
) -> None:
    """US-217 fix: sensitive text embedded inside a label is redacted and a
    non-string value never surfaces via str(dict)/str(list)."""
    request = {
        **generate_request(EntryRequest(raw_title="芙莉莲"))["request"],
        "request_id": "request-redact",
        "source_info": {
            "matched_bangumi": {
                "title": "葬送的芙莉莲",
                # A URL embedded in otherwise-legal text.
                "aliases": ["芙莉莲 via https://evil.example/x", "Frieren"],
                "mikan_url": "https://private.example/Home/Bangumi/99",
            },
            "rss_sources": [
                {
                    "subtitle_group": "喵萌",
                    "rss_url": "https://private.example/rss",
                    "total_seed_count": 1,
                    "valid_seed_count": 1,
                    "invalid_seed_count": 0,
                    "valid_seed_names": ["file://etc/passwd-in-name"],
                    "excluded_seed_names": [],
                    "warnings": ["token=abc123 泄漏"],
                }
            ],
        },
        "confirmable_config": {
            "selected_subtitle_group": "喵萌",
            "filter_rule": {
                "must_contain": "1080p",
                "must_not_contain": "password=hunter2",
                "use_regex": False,
                "case_sensitive": False,
            },
            "effective_seed_names": ["file://etc/passwd-in-name"],
            "expected_folder_name": {"nested": "secret"},
            "warnings": [],
        },
    }
    save_request_snapshot(load_storage_config(tmp_path / "storage"), request)

    response = _client().get(
        "/api/v1/requests/request-redact/safe-info",
        query_string={"storage_dir": "storage"},
    )
    payload = response.get_json()
    assert response.status_code == 200
    safe = payload["result"]["safe_info"]
    body_text = response.get_data(as_text=True)

    # Embedded URL in an alias → the whole alias is redacted.
    assert safe["aliases"] == ["[redacted]", "Frieren"]
    # file:// embedded in a seed name → redacted.
    assert safe["resources"]["valid_file_names"] == ["[redacted]"]
    # key=value secret in a warning → redacted.
    assert safe["subtitle_groups"][0]["warnings"] == ["[redacted]"]
    # key=value secret in a filter rule → redacted.
    assert safe["filter_rule"]["must_not_contain"] == "[redacted]"
    # Non-string folder_name (a nested dict) → None, never str(dict).
    assert safe["folder_name"] is None
    # Nothing sensitive survives in the body.
    for marker in ("evil.example", "file://", "hunter2", "abc123", "token="):
        assert marker not in body_text
    # Legal labels are untouched.
    assert safe["title"] == "葬送的芙莉莲"
    assert safe["raw_title"] == "芙莉莲"
    assert safe["filter_rule"]["must_contain"] == "1080p"


def test_safe_label_redacts_all_sensitive_markers() -> None:
    """US-217 fix: ``_safe_label`` redacts URL/magnet/path/credential markers
    anywhere in a string, returns None for non-strings, and keeps legal text."""
    from apps.migu_orca_web.serializers import _safe_label

    redacted = "[redacted]"
    for sensitive in (
        "前 http://example.com 后",       # embedded http://
        "前 https://example.com 后",      # embedded https://
        "magnet:?xt=urn:btih:deadbeef",   # magnet
        "前 file://etc/passwd 后",        # file://
        "/usr/local/bin",                 # Unix absolute path
        "C:\\Users\\secret",              # Windows drive path
        "\\\\server\\share",              # UNC path
        "token=abc123",                   # key=value secret
        "Authorization: Bearer xyz",      # key:value secret
        "password=hunter2",               # password key=value
        "cookie=session-id",              # cookie key=value
        "rss_url=https://x/y",            # rss_url key=value
        "/tmp/abs",                       # leading slash
        # Generic POSIX absolute paths — any root, anywhere in the string.
        "/data/private/token",
        "写入失败 /data/private/token",
        "/mnt/storage/secret",
        "目录是 /mnt/storage/secret",
        "/private/config.json",
        "配置位于 /private/config.json",
        "/Users/name/secret",
        "macOS 路径 /Users/name/secret",
        "/custom-root/sub/dir",
        "任意根目录 /custom-root/sub/dir",
        # Boundaries: =, CJK text/punctuation, quotes, parentheses, colon.
        "path=/mnt/secret",
        "路径为/data/secret",
        "路径是/private/config",
        "配置（/Users/name/secret）",
        "\"/opt/config\"",
        "dest:/var/lib/data",
        "(/srv/backup)",
        "结果:/custom-root/x",
        # Chinese path-context without a separator.
        "路径/data",
        "路径：/data",
    ):
        assert _safe_label(sensitive) == redacted, f"failed to redact {sensitive!r}"

    # Non-string values never become str(dict)/str(list).
    assert _safe_label({"a": 1}) is None
    assert _safe_label([1, 2]) is None
    assert _safe_label(42) is None
    assert _safe_label(True) is None
    assert _safe_label(None) is None

    # Legal Chinese labels, slash-bearing titles and file names stay intact.
    assert _safe_label("葬送的芙莉莲") == "葬送的芙莉莲"
    assert _safe_label("[喵萌] 葬送的芙莉莲 - 01.mkv") == "[喵萌] 葬送的芙莉莲 - 01.mkv"
    assert _safe_label("1080p") == "1080p"
    assert _safe_label("喵萌") == "喵萌"
    assert _safe_label("Fate/stay night") == "Fate/stay night"
    assert _safe_label("A/B 测试") == "A/B 测试"
    assert _safe_label("[喵萌] 番剧名称 - 01.mkv") == "[喵萌] 番剧名称 - 01.mkv"
    assert _safe_label("v1/1080p 发布") == "v1/1080p 发布"
    # CJK word-internal slashes are NOT absolute paths (Unicode-aware boundary).
    assert _safe_label("简/繁字幕") == "简/繁字幕"
    assert _safe_label("中文/日文") == "中文/日文"
    assert _safe_label("命运/冠位指定") == "命运/冠位指定"
    assert _safe_label("字幕组/压制组") == "字幕组/压制组"
    assert _safe_label("新增/修改") == "新增/修改"


# ---------------------------------------------------------------------------
# US-222 accept/save-confirm -> unified tracking handoff
# ---------------------------------------------------------------------------


def test_request_accept_view_creates_tracking_record(tmp_path: Path) -> None:
    """US-222: the single-plan accept entry converges into the tracking list."""
    storage_dir = tmp_path / "storage"
    client = _client()
    request = _saved_request(tmp_path, "芙莉莲", "request-accept-tracked")
    assert request["status"] == "PENDING_CONFIRM"

    response = client.post(
        f"/api/v1/requests/{request['request_id']}/accept",
        json={"storage_dir": _profile(tmp_path, storage_dir.name)},
    )
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["request"]["status"] == "ACCEPTED"

    config = load_storage_config(storage_dir)
    tracking = load_tracking_record(
        config, tracking_id_for_request(request["request_id"])
    )
    assert tracking.origin == TRACKING_ORIGIN_LEGACY_ACCEPT
    assert tracking.status == TRACKING_STATUS_PENDING_SUBMIT
    assert tracking.revision == 1
    assert len(tracking.audit_events) == 1


def test_request_accept_view_tracking_failure_keeps_request_confirmed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """US-222: a tracking write failure never rolls a confirmed accept back."""
    import apps.migu_orca_web.tracking_handoff as tracking_handoff

    storage_dir = tmp_path / "storage"
    client = _client()
    request = _saved_request(tmp_path, "芙莉莲", "request-accept-track-fail")

    def failing_ensure(_config: Any, _record: Any) -> Any:
        raise Stage1Error(
            "storage_error", "模拟追番记录写入失败", "ensure_tracking_record", {}
        )

    monkeypatch.setattr(tracking_handoff, "ensure_tracking_record", failing_ensure)

    response = client.post(
        f"/api/v1/requests/{request['request_id']}/accept",
        json={"storage_dir": _profile(tmp_path, storage_dir.name)},
    )
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["request"]["status"] == "ACCEPTED"
    assert load_request_snapshot(
        load_storage_config(storage_dir), request["request_id"]
    )["status"] == "ACCEPTED"
    assert list_tracking_records(load_storage_config(storage_dir)).records == []


def test_save_confirm_tracking_write_failure_returns_not_ready_handoff(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """US-222: a tracking write failure keeps CONFIRMED and reports not-ready."""
    from apps.migu_orca_web import tracking_handoff
    from apps.migu_orca_web.tracking_handoff import TRACKING_HANDOFF_RETRY_MESSAGE

    storage_dir = tmp_path / "storage"
    client = _client()
    issued = client.post(
        "/api/v1/requests", json={"title": "芙莉莲"}
    ).get_json()["result"]
    draft_id = issued["draft_id"]
    request_id = issued["request"]["request_id"]

    def failing_ensure(_config: Any, _record: Any) -> Any:
        raise Stage1Error(
            "storage_error", "模拟追番记录写入失败", "ensure_tracking_record", {}
        )

    monkeypatch.setattr(tracking_handoff, "ensure_tracking_record", failing_ensure)

    response = _save_confirm(
        client, draft_id, 1, "view-tracking-fail-key",
        _profile(tmp_path, storage_dir.name),
    )
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    result = payload["result"]
    assert result["outcome"] == "CONFIRMED"
    handoff = result["handoff"]
    assert handoff["request_id"] == request_id
    assert handoff["status"] == "ACCEPTED"
    assert handoff["next_action"] == "OPEN_TRACKING"
    assert handoff["tracking_id"] == tracking_id_for_request(request_id)
    assert handoff["tracking_status"] is None
    assert handoff["tracking_ready"] is False
    assert handoff["safe_message"] == TRACKING_HANDOFF_RETRY_MESSAGE
    # The confirmed Request stays ACCEPTED and no tracking record was written.
    assert load_request_snapshot(
        load_storage_config(storage_dir), request_id
    )["status"] == "ACCEPTED"
    assert list_tracking_records(load_storage_config(storage_dir)).records == []
