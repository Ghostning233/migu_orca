from __future__ import annotations

"""Shared fixtures for the US-189 API contract freeze tests.

Everything in this package runs against the real Flask app but never touches
real MiKan, AutoBangumi or qBittorrent: candidate search, AB submission and
connection tests all go through fakes/monkeypatched seams. All storage writes
use ``tmp_path`` so the workspace ``.migu_orca/storage`` is never touched.
"""

from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient

from apps.base import create_app
from apps.migu_orca_entry.controllers.entry_controller import generate_request
from shared.models import EntryRequest
from storage_engine.controllers.request_repository import (
    save_request_snapshot,
)
from storage_engine.controllers.storage_config import load_storage_config


@pytest.fixture()
def client() -> FlaskClient:
    return create_app("testing").test_client()


@pytest.fixture(autouse=True)
def _web_config_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep deployment credentials isolated from the developer workspace."""
    monkeypatch.setenv("MIGU_ORCA_WEB_CONFIG_ROOT", str(tmp_path / "config"))


@pytest.fixture(autouse=True)
def _web_storage_root(tmp_path: Path) -> None:
    """US-193: point the Web storage root at the test tmp dir.

    Contract tests pass *relative profile* names (e.g. ``storage``) as
    ``storage_dir``; the server resolves them under this root so absolute
    tmp paths never appear in API payloads/URLs.
    """
    from apps.migu_orca_web.services import set_web_storage_root

    set_web_storage_root(tmp_path)
    yield
    set_web_storage_root(None)


@pytest.fixture(autouse=True)
def _reset_shared_state() -> None:
    """Reset the process-level candidate cache and selection contexts.

    These singletons are shared across tests, so contract tests must never
    observe entries written by earlier tests.
    """
    from apps.migu_orca_web.contexts import candidate_selection_contexts
    from apps.migu_orca_web.drafts import draft_store
    from mikan_engine.controllers.mikan_candidate_cache import candidate_search_cache

    candidate_search_cache.clear()
    candidate_selection_contexts.clear()
    draft_store.clear()
    yield


def saved_request(tmp_path: Path, title: str = "芙莉莲", request_id: str = "request-1") -> dict[str, Any]:
    """Generate and persist a static-fixture Request snapshot into tmp storage."""
    request = {
        **generate_request(EntryRequest(raw_title=title))["request"],
        "request_id": request_id,
    }
    save_request_snapshot(load_storage_config(tmp_path / "storage"), request)
    return request
