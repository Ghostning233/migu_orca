from __future__ import annotations

"""Issue #204: the test-time response DTO audit and its coverage gaps.

``tests/api_contract/conftest.py`` validates every real ``/api/v1`` JSON
success envelope produced by this package against the DTO declared in
``openapi_gen._ENDPOINTS`` (ADR-0004). This module

1. adds the success paths the rest of the package does not exercise
   (``cancel`` / ``tracking/sync`` / the four management writes / the
   ``batches/parse`` preference-fallback branch, which is the drift the #172
   audit found), and
2. ends with the fail-closed assertion that every declared endpoint was
   observed and valid. ``pytest_collection_modifyitems`` in the package
   conftest moves this file to the end of the session so the assertion always
   sees the whole package's responses — running this file alone is expected to
   fail closed, never to pass with a partial observation.
"""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient

from mikan_engine.controllers.mikan_config import MikanConfig
from tests.api_contract.conftest import saved_request
from tests.api_contract.response_dto_audit import (
    RESPONSE_DTO_AUDIT,
    ResponseDtoAudit,
    declared_success_dtos,
    unregistered_success_declarations,
)
from tests.api_contract.test_golden_contracts import _fake_mikan_search
from tests.api_contract.test_tracking_confirmation_local_ab import (
    LocalAb318,
)
from tests.api_contract.test_tracking_confirmation_local_ab import (
    _seed as _local_ab_seed,
)
from tests.api_contract.test_tracking_modify_local_plan_api import (
    FakeAbClient,
)
from tests.api_contract.test_tracking_modify_local_plan_api import (
    _seed as _management_seed,
)

# ---------------------------------------------------------------------------
# Coverage gaps: success paths no other test in this package produces
# ---------------------------------------------------------------------------


def _empty_batch_search(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep batch parsing offline (mirrors test_batch_parse_progress_api)."""
    monkeypatch.setattr(
        "apps.migu_orca_web.services._search_batch_item_candidates",
        lambda search_queries, mikan_config: [],
    )


def test_batches_parse_preference_fallback_publishes_null_preference_hits(
    tmp_path: Path, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#204 drift A: the documented fallback really emits ``preference_hits: null``.

    ``serializers._serialize_preference_application`` returns ``None`` for the
    applied preferences/hits when the saved preferences are unreadable, and the
    batch falls back to the default flow with a warning. A damaged
    ``user_preferences.json`` triggers that real branch without any monkeypatch
    on the serializer.
    """
    _empty_batch_search(monkeypatch)
    damaged = tmp_path / "storage" / "preferences" / "user_preferences.json"
    damaged.parent.mkdir(parents=True, exist_ok=True)
    damaged.write_text("{ this is not valid json", encoding="utf-8")

    response = client.post(
        "/api/v1/batches/parse",
        json={"raw_input": "芙莉莲", "storage_dir": "storage"},
    )

    payload = response.get_json()
    assert response.status_code == 200, payload
    item = payload["result"]["items"][0]
    assert item["applied_preferences"] is None
    assert item["preference_hits"] is None
    assert any("偏好读取失败" in warning for warning in item["preference_warnings"])


def test_post_preferences_success(client: FlaskClient) -> None:
    response = client.post(
        "/api/v1/preferences",
        json={
            "storage_dir": "storage",
            "preferences": {
                "version": 1,
                "subtitle_groups": {
                    "preferred": ["喵萌"],
                    "excluded": [],
                    "fallback": "next_preferred",
                },
                "filter_defaults": {
                    "must_contain": "1080p",
                    "must_not_contain": "",
                    "use_regex": False,
                    "case_sensitive": False,
                },
                "naming": {"strategy": "official_title_season", "template": "{title}"},
                "search": {"reuse_explicit_corrections": True},
            },
        },
    )

    assert response.status_code == 200, response.get_json()


def test_post_corrections_success(client: FlaskClient) -> None:
    response = client.post(
        "/api/v1/corrections",
        json={
            "storage_dir": "storage",
            "correction": {
                "raw_title": "路哥S4",
                "canonical_title": "欢迎来到实力至上主义的教室",
                "season_hint": "S4",
                "bangumi_metadata": {
                    "bangumi_id": "4001",
                    "title": "欢迎来到实力至上主义的教室",
                },
                "query_correction": "欢迎来到实力至上主义的教室 第四季",
            },
        },
    )

    assert response.status_code == 200, response.get_json()


def test_post_mikan_candidates_success(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real candidate search through the default MiKan config and a fake transport."""
    _fake_mikan_search(monkeypatch)
    monkeypatch.setattr(
        "apps.migu_orca_web.routes_mikan.default_mikan_config",
        lambda: MikanConfig(
            search_endpoint="https://mikan.example/Home/Search", timeout_seconds=5
        ),
    )

    response = client.post("/api/v1/mikan/candidates", json={"query": "芙莉莲"})

    payload = response.get_json()
    assert response.status_code == 200, payload
    assert payload["result"]["status"] == "FOUND"


def test_post_request_cancel_success(tmp_path: Path, client: FlaskClient) -> None:
    request = saved_request(tmp_path, request_id="audit-cancel")

    response = client.post(
        f"/api/v1/requests/{request['request_id']}/cancel",
        json={"storage_dir": "storage", "cancel_reason": "审计取消"},
    )

    assert response.status_code == 200, response.get_json()


def test_post_request_accept_success(tmp_path: Path, client: FlaskClient) -> None:
    request = saved_request(tmp_path, request_id="audit-accept")

    response = client.post(
        f"/api/v1/requests/{request['request_id']}/accept",
        json={"storage_dir": "storage"},
    )

    assert response.status_code == 200, response.get_json()


def test_post_request_modify_success(tmp_path: Path, client: FlaskClient) -> None:
    request = saved_request(tmp_path, request_id="audit-modify")

    response = client.post(
        f"/api/v1/requests/{request['request_id']}/modify",
        json={"storage_dir": "storage", "patch": {"expected_folder_name": "审计修改"}},
    )

    assert response.status_code == 200, response.get_json()


def test_post_tracking_sync_success(tmp_path: Path, client: FlaskClient) -> None:
    """Real sync orchestration against the localhost AB 3.1.18 stand-in."""
    ab = LocalAb318()
    try:
        body, _record = _local_ab_seed(tmp_path, ab)
        response = client.post(
            "/api/v1/tracking/sync",
            json={
                "confirm": True,
                "storage_dir": body["storage_dir"],
                "connection_ref": body["connection_ref"],
                "configuration_revision": body["configuration_revision"],
            },
        )
    finally:
        ab.close()

    assert response.status_code == 200, response.get_json()


class _ManagementFakeAbClient(FakeAbClient):
    """The fixed 3.1.18 management surface with an in-memory read-back.

    Extends the existing modify fake (issue #202) with the three remaining
    management actions so the real route + coordinator + serializer run; only
    the outermost Auto Bangumi client is a fake.
    """

    def read_snapshot(self, *, deadline: float | None = None) -> Any:
        subscriptions = [] if self.sub is None else [self.sub]
        return self.capabilities, subscriptions, [self.rss]

    def set_subscription_enabled(self, ident: str, enabled: bool) -> dict[str, int]:
        self.calls.append(("set_subscription_enabled", ident, enabled))
        if self.fail_write:
            raise TimeoutError("offline")
        assert self.sub is not None
        # 3.1.18 keeps a disabled subscription in the list with deleted=true.
        self.sub = replace(self.sub, deleted=not enabled)
        return {"status_code": 200}

    def delete_subscription(self, ident: str) -> dict[str, int]:
        self.calls.append(("delete_subscription", ident, None))
        if self.fail_write:
            raise TimeoutError("offline")
        self.sub = None
        return {"status_code": 200}

    def refresh_rss(self, ident: str) -> dict[str, int]:
        self.calls.append(("refresh_rss", ident, None))
        if self.fail_write:
            raise TimeoutError("offline")
        return {"status_code": 200}


def _patch_management_client(
    monkeypatch: pytest.MonkeyPatch, client: _ManagementFakeAbClient
) -> None:
    monkeypatch.setattr(
        "apps.migu_orca_web.tracking_saved_management_service.create_management_client",
        lambda *_args, **_kwargs: client,
    )


def _management_body(saved: Any, record: Any, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "target_scope": "SUBSCRIPTION",
        "expected_revision": record.revision,
        "idempotency_key": "audit-management-key",
        "confirm": True,
        "connection_ref": str(saved.connection_ref),
        "configuration_revision": saved.configuration_revision,
        "storage_dir": "storage",
    }
    body.update(overrides)
    return body


@pytest.mark.parametrize(
    ("path", "scope", "extra"),
    [
        ("modify", "SUBSCRIPTION", {"patch": {"title": "审计标题"}}),
        ("set-enabled", "SUBSCRIPTION", {"enabled": False}),
        ("refresh", "ASSOCIATED_RSS", {}),
    ],
)
def test_management_write_real_success_path(
    tmp_path: Path,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    scope: str,
    extra: dict[str, Any],
) -> None:
    """#204 drift B: every management write serializes through the real route."""
    saved, _config, record, _snapshot = _management_seed(tmp_path)
    _patch_management_client(monkeypatch, _ManagementFakeAbClient())

    body = _management_body(
        saved, record, target_scope=scope, idempotency_key=f"audit-{path}-1", **extra
    )
    response = client.post(
        f"/api/v1/tracking/items/{record.tracking_id}/{path}", json=body
    )

    payload = response.get_json()
    assert response.status_code == 200, payload
    result = payload["result"]
    assert result["management_status"] == "SUCCEEDED", result
    # #204 drift B: the internal ``outcome`` is not part of the public result.
    assert "outcome" not in result


# ---------------------------------------------------------------------------
# Fail-closed coverage assertion (must run last — enforced by the conftest hook)
# ---------------------------------------------------------------------------


def test_success_registry_rejects_unnamed_success_declarations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every ``_ENDPOINTS`` entry must declare its success shape structurally.

    A typed ``success`` model *or* an explicit ``responses`` mapping is a
    declaration; anything else (a bare ``success=None``, or a non-model class
    such as ``dict``) is an unregistered endpoint and must fail closed even
    though the DTO count alone could still look right.
    """
    typed = declared_success_dtos()["POST /api/v1/batches/parse"]
    synthetic = {
        "GET /api/v1/binary": {
            "success": None,
            "responses": {"200": {"description": "bytes"}},
        },
        "POST /api/v1/typed": {"success": typed},
        "GET /api/v1/unregistered": {"success": None},
        "GET /api/v1/not-a-model": {"success": dict},
    }

    assert unregistered_success_declarations(synthetic) == [
        "GET /api/v1/not-a-model",
        "GET /api/v1/unregistered",
    ]

    # The recorder the coverage assertion reads must flag the same hole, and the
    # failure must be locatable in the message it prints.
    from tests.api_contract import response_dto_audit as audit_module

    grown_registry = dict(audit_module._ENDPOINTS)
    grown_registry["GET /api/v1/new-binary"] = {"success": None}
    monkeypatch.setattr(audit_module, "_ENDPOINTS", grown_registry)
    audit = ResponseDtoAudit()

    assert audit.unregistered == ["GET /api/v1/new-binary"]
    assert "declared nowhere" in audit.report()
    assert "GET /api/v1/new-binary" in audit.report()


def test_audit_recorder_fails_closed_on_every_drift_shape() -> None:
    """The recorder's observation channels must never let a drift pass silently.

    A fresh recorder (independent of the session singleton) is used so three
    fail-closed shapes are proven without perturbing the real run: an
    unobserved declared endpoint, a JSON success envelope with no declared
    success DTO, and a declared result that violates its DTO. The fourth
    channel — the hook's own errors — is pinned by
    ``test_audit_hook_records_its_own_failure``.
    """
    audit = ResponseDtoAudit()
    assert "GET /api/v1/preferences" in audit.missing

    audit.observe("GET /api/v1/not-declared", {}, method="GET", path="/x")
    assert "GET /api/v1/not-declared" in audit.undeclared

    audit.observe(
        "POST /api/v1/batches/parse",
        {"batch_id": "b", "raw_input": "x", "items": "not-a-list"},
        method="POST",
        path="/api/v1/batches/parse",
    )
    assert "items" in audit.failures["POST /api/v1/batches/parse"][0]


def test_audit_hook_records_its_own_failure(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hook error is recorded and located; it never breaks the response.

    The real hook path is exercised (a live ``/api/v1`` request) while the
    recorder raises, so both halves of the contract are pinned: the failure
    lands in ``hook_errors`` with the request path — the exact condition the
    coverage assertion checks — and the response still reaches the client
    untouched. ``monkeypatch`` restores the singleton's recorder/list, so the
    session-wide audit is not perturbed.
    """
    audit = RESPONSE_DTO_AUDIT
    monkeypatch.setattr(audit, "hook_errors", [])

    def exploding_observe(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("audit recorder exploded")

    monkeypatch.setattr(audit, "observe", exploding_observe)

    response = client.get(
        "/api/v1/preferences", query_string={"storage_dir": "storage"}
    )

    assert response.status_code == 200, response.get_json()
    assert len(audit.hook_errors) == 1, audit.report()
    assert "/api/v1/preferences" in audit.hook_errors[0]
    assert "RuntimeError" in audit.hook_errors[0]
    # This is the coverage assertion's fail-closed condition for the channel,
    # and the failure is locatable in the assertion message it would print.
    assert audit.hook_errors != []
    assert "audit hook errors:" in audit.report()
    assert "RuntimeError" in audit.report()


def test_every_declared_success_endpoint_was_observed_and_valid() -> None:
    """All declared success DTOs were produced by a real response and passed."""
    audit = RESPONSE_DTO_AUDIT
    # Issue #228 retired the standalone /delete-external success endpoint.
    assert len(declared_success_dtos()) == 36, (
        "the endpoint registry changed; review the audit coverage:\n" + audit.report()
    )
    assert audit.unregistered == [], audit.report()
    assert audit.hook_errors == [], audit.report()
    assert audit.undeclared == {}, audit.report()
    assert audit.missing == [], audit.report()
    assert audit.failures == {}, audit.report()
