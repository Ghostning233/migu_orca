from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from ab_engine.controllers.ab_config import AutoBangumiConfig
from apps.migu_orca_web.save_confirm_service import compute_request_fingerprint
from apps.migu_orca_web.schemas import SavedTrackingSubmitInput
from apps.migu_orca_web.tracking_handoff import ensure_confirmed_request_tracking
from apps.migu_orca_web.tracking_submission_service import (
    run_saved_tracking_retry,
    run_saved_tracking_submit,
)
from plan_engine.controllers.data_sources import StaticFixtureDataSource
from plan_engine.controllers.plan_generation import build_plan
from request_engine.controllers.request_controller import accept_request
from shared.errors import Stage1Error
from shared.models import EntryRequest
from storage_engine.controllers.autobangumi_config_repository import (
    AutoBangumiConfigRepository,
    build_stored_autobangumi_config,
)
from storage_engine.controllers.operation_repository import (
    bind_tracking_operation,
    load_tracking_operation,
)
from storage_engine.controllers.request_repository import (
    load_request_snapshot,
    save_request_snapshot,
)
from storage_engine.controllers.storage_config import load_storage_config
from storage_engine.controllers.tracking_repository import load_tracking_record
from tracking_engine.models.operation import (
    TRACKING_OPERATION_KIND_SUBMIT,
    TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN,
    TRACKING_OPERATION_STATE_RECOVERY_REQUIRED,
    TRACKING_OPERATION_STATE_SUCCEEDED,
)
from tracking_engine.models.tracking import (
    TRACKING_STATUS_SUBMIT_FAILED,
    TRACKING_STATUS_VERIFYING_EXTERNAL,
)

NOW = "2026-09-13T00:00:00+00:00"


FIXTURE_RSS_URL = "https://example.invalid/rss/frieren-moe.xml"


def _empty_readback():
    """Issue #97 AC 5: a readable read-back that confirms no external object."""

    def read_snapshot(deadline=None):
        return (None, [], [])

    return read_snapshot


def _unreadable_readback():
    """Issue #97 AC 6: a read-back that cannot prove anything."""

    def read_snapshot(deadline=None):
        return None

    return read_snapshot


def _matching_readback(external_id: str = "saved-subscription-1"):
    """Issue #97: an exact read-back proving the controlled subscription."""

    def read_snapshot(deadline=None):
        from ab_engine.models.management import ExternalRss, ExternalSubscription

        return (
            None,
            [
                ExternalSubscription(
                    external_id, "葬送的芙莉莲", 1, "喵萌", rss_urls=(FIXTURE_RSS_URL,)
                )
            ],
            [ExternalRss("rss-1", "芙莉莲", FIXTURE_RSS_URL)],
        )

    return read_snapshot


def test_saved_submit_input_rejects_legacy_secret_and_noncanonical_values() -> None:
    with pytest.raises(ValidationError):
        SavedTrackingSubmitInput(
            tracking_id="trk-x", expected_revision=1, idempotency_key="key-x",
            confirm=True, connection_ref="11111111-1111-4111-8111-111111111111",
            configuration_revision=1, ab_config={"password": "must-not-be-here"},
        )


def _storage(tmp_path: Path):
    return load_storage_config(tmp_path / "storage")


def _saved_repository(tmp_path: Path) -> AutoBangumiConfigRepository:
    repository = AutoBangumiConfigRepository(tmp_path / "ab-config")
    repository.save(
        build_stored_autobangumi_config(
            {
                "auth_mode": "password",
                "base_url": "https://ab.example.invalid",
                "username": "alice",
                "password": "secret-password",
            }
        ),
        expected_configuration_revision=0,
    )
    return repository


def _tracking(tmp_path: Path):
    config = _storage(tmp_path)
    request = accept_request(
        {
            **build_plan(EntryRequest(raw_title="芙莉莲"), data_source=StaticFixtureDataSource())["request"],
            "request_id": "saved-submit-request",
        }
    )
    save_request_snapshot(config, request)
    handoff = ensure_confirmed_request_tracking(
        config=config, request=request, origin="SAVE_CONFIRM", now=NOW
    )
    assert handoff.tracking_id is not None
    return config, load_tracking_record(config, handoff.tracking_id)


def _input(repository: AutoBangumiConfigRepository, record, **overrides: Any) -> dict[str, Any]:
    saved = repository.load()
    assert saved.connection_ref is not None
    return {
        "tracking_id": record.tracking_id,
        "expected_revision": record.revision,
        "idempotency_key": "saved-submit-key",
        "confirm": True,
        "connection_ref": str(saved.connection_ref),
        "configuration_revision": saved.configuration_revision,
        **overrides,
    }


def _success() -> dict[str, Any]:
    return {
        "success": True,
        "ab_subscription_id": "saved-subscription-1",
        "ab_response": {"id": "saved-subscription-1", "status": "created"},
        "fallback_config": None,
        "error": None,
    }


def _failure() -> dict[str, Any]:
    return {
        "success": False,
        "ab_subscription_id": None,
        "ab_response": None,
        "fallback_config": None,
        "error": {
            "error_type": "ab_auth_failed",
            "error_message": "认证失败",
            "failed_step": "create_ab_subscription",
            "details": {},
        },
    }


def _unknown() -> dict[str, Any]:
    result = _failure()
    result["error"] = {
        "error_type": "ab_timeout",
        "error_message": "请求超时",
        "failed_step": "create_ab_subscription",
        "details": {},
    }
    return result


def test_saved_submit_holds_snapshot_and_binds_operation_and_mapping(tmp_path: Path) -> None:
    config, record = _tracking(tmp_path)
    repository = _saved_repository(tmp_path)
    saved = repository.load()
    calls: list[AutoBangumiConfig] = []
    lease_conflicts: list[str] = []

    def submit_one(_request: dict[str, Any], runtime: AutoBangumiConfig) -> dict[str, Any]:
        calls.append(runtime)
        try:
            repository.save(
                build_stored_autobangumi_config(
                    {
                        "auth_mode": "password",
                        "base_url": "https://replacement.example.invalid",
                        "username": "alice",
                        "password": "replacement-password",
                    }
                ),
                expected_configuration_revision=1,
            )
        except Stage1Error as error:
            lease_conflicts.append(error.error_type)
        return _success()

    result = run_saved_tracking_submit(
        config,
        repository=repository,
        payload=SavedTrackingSubmitInput.model_validate(_input(repository, record)),
        submit_one=submit_one,
        readback_external=_matching_readback(),
        now=NOW,
    )

    assert result["outcome"] == "ACTIVE"
    assert len(calls) == 1
    assert calls[0].base_url == "https://ab.example.invalid"
    assert lease_conflicts == ["connection_in_use"]
    operation = load_tracking_operation(config, result["operation_id"])
    assert operation.state == TRACKING_OPERATION_STATE_SUCCEEDED
    assert operation.connection_ref == str(saved.connection_ref)
    stored = load_tracking_record(config, record.tracking_id)
    assert stored.external_mapping == {
        "schema_version": 2,
        "adapter": "legacy_3_1",
        "subscription_id": "saved-subscription-1",
        "rss_ids": [],
        "match_reason": "EXTERNAL_ID",
        "external_deleted": False,
        "enabled": True,
        "missing_sync_count": 0,
        "last_verified_at": NOW,
        "connection_ref": str(saved.connection_ref),
    }


def test_saved_terminal_replay_after_config_delete_does_not_call_again(tmp_path: Path) -> None:
    config, record = _tracking(tmp_path)
    repository = _saved_repository(tmp_path)
    payload = _input(repository, record)
    calls: list[int] = []

    first = run_saved_tracking_submit(
        config,
        repository=repository,
        **payload,
        submit_one=lambda *_args: calls.append(1) or _success(),
        readback_external=_matching_readback(),
        now=NOW,
    )
    repository.delete(expected_configuration_revision=1)

    replay = run_saved_tracking_submit(
        config,
        repository=repository,
        **payload,
        submit_one=lambda *_args: calls.append(1) or _success(),
        readback_external=_matching_readback(),
        now=NOW,
    )
    assert first["outcome"] == replay["outcome"] == "ACTIVE"
    assert len(calls) == 1


def test_saved_terminal_replay_after_repository_rebuild_does_not_call_again(
    tmp_path: Path,
) -> None:
    config, record = _tracking(tmp_path)
    repository = _saved_repository(tmp_path)
    payload = _input(repository, record)
    calls: list[int] = []

    first = run_saved_tracking_submit(
        config,
        repository=repository,
        **payload,
        submit_one=lambda *_args: calls.append(1) or _success(),
        readback_external=_matching_readback(),
        now=NOW,
    )
    rebuilt_repository = AutoBangumiConfigRepository(tmp_path / "ab-config")
    replay = run_saved_tracking_submit(
        config,
        repository=rebuilt_repository,
        **payload,
        submit_one=lambda *_args: calls.append(1) or _success(),
        readback_external=_matching_readback(),
        now=NOW,
    )

    assert first["outcome"] == replay["outcome"] == "ACTIVE"
    assert len(calls) == 1


def test_saved_persist_failure_after_external_call_releases_lease_for_save(
    tmp_path: Path,
) -> None:
    config, record = _tracking(tmp_path)
    repository = _saved_repository(tmp_path)
    calls: list[int] = []

    def persist_failure(_request: dict[str, Any] | None, _result: dict[str, Any]) -> dict[str, Any]:
        raise Stage1Error("storage_error", "测试持久化失败", "test_persist")

    result = run_saved_tracking_submit(
        config,
        repository=repository,
        **_input(repository, record),
        submit_one=lambda *_args: calls.append(1) or _success(),
        readback_external=_matching_readback(),
        persist_ab_result=persist_failure,
        now=NOW,
    )

    assert result["outcome"] == "RECOVERY_REQUIRED"
    assert calls == [1]
    assert load_tracking_operation(config, result["operation_id"]).state == TRACKING_OPERATION_STATE_RECOVERY_REQUIRED
    replacement = repository.save(
        build_stored_autobangumi_config(
            {
                "auth_mode": "password",
                "base_url": "https://replacement.example.invalid",
                "username": "alice",
                "password": "replacement-password",
            }
        ),
        expected_configuration_revision=1,
    )
    assert replacement.configuration_revision == 2


def test_saved_needs_reconfirm_does_not_call_external(tmp_path: Path) -> None:
    config, record = _tracking(tmp_path)
    repository = _saved_repository(tmp_path)
    request = load_request_snapshot(config, record.request_id)
    invalid_request = deepcopy(request)
    invalid_request["status"] = "DRAFT"
    save_request_snapshot(config, invalid_request)
    calls: list[int] = []

    result = run_saved_tracking_submit(
        config,
        repository=repository,
        **_input(repository, record),
        submit_one=lambda *_args: calls.append(1) or _success(),
        readback_external=_matching_readback(),
        now=NOW,
    )

    assert result["outcome"] == "NEEDS_RECONFIRM"
    assert calls == []


def test_saved_unknown_result_rejects_fresh_key_without_external_call(
    tmp_path: Path,
) -> None:
    config, record = _tracking(tmp_path)
    repository = _saved_repository(tmp_path)
    calls: list[int] = []
    first = run_saved_tracking_submit(
        config,
        repository=repository,
        **_input(repository, record),
        submit_one=lambda *_args: calls.append(1) or _unknown(),
        now=NOW,
    )
    current = load_tracking_record(config, record.tracking_id)
    with pytest.raises(Stage1Error) as error:
        run_saved_tracking_submit(
            config,
            repository=repository,
            **_input(repository, current, idempotency_key="fresh-after-unknown"),
            submit_one=lambda *_args: calls.append(1) or _success(),
        readback_external=_matching_readback(),
            now=NOW,
        )

    assert first["outcome"] == "VERIFYING_EXTERNAL"
    assert error.value.error_type == "tracking_state_conflict"
    assert calls == [1]


def test_saved_old_unbound_operation_same_key_saved_ref_is_rejected(
    tmp_path: Path,
) -> None:
    config, record = _tracking(tmp_path)
    repository = _saved_repository(tmp_path)
    payload = _input(repository, record)
    bind_tracking_operation(
        config,
        tracking_id=record.tracking_id,
        operation=TRACKING_OPERATION_KIND_SUBMIT,
        idempotency_key=payload["idempotency_key"],
        expected_revision=payload["expected_revision"],
        request_fingerprint=record.request_fingerprint or compute_request_fingerprint(
            load_request_snapshot(config, record.request_id)
        ),
        connection_ref=None,
        now=NOW,
    )
    calls: list[int] = []

    with pytest.raises(Stage1Error) as error:
        run_saved_tracking_submit(
            config,
            repository=repository,
            **payload,
            submit_one=lambda *_args: calls.append(1) or _success(),
        readback_external=_matching_readback(),
            now=NOW,
        )

    assert error.value.error_type == "tracking_idempotency_conflict"
    assert calls == []


def test_saved_same_key_different_ref_is_rejected_without_external_call(tmp_path: Path) -> None:
    config, record = _tracking(tmp_path)
    repository = _saved_repository(tmp_path)
    payload = _input(repository, record)
    calls: list[int] = []
    run_saved_tracking_submit(
        config,
        repository=repository,
        **payload,
        submit_one=lambda *_args: calls.append(1) or _success(),
        readback_external=_matching_readback(),
        now=NOW,
    )
    replacement = repository.save(
        build_stored_autobangumi_config(
            {
                "auth_mode": "api_token",
                "base_url": "https://other.example.invalid",
                "token": "new-secret",
            }
        ),
        expected_configuration_revision=1,
    )
    with pytest.raises(Stage1Error) as error:
        run_saved_tracking_submit(
            config,
            repository=repository,
            **_input(
                repository,
                record,
                connection_ref=str(replacement.connection_ref),
                configuration_revision=replacement.configuration_revision,
            ),
            submit_one=lambda *_args: calls.append(1) or _success(),
        readback_external=_matching_readback(),
            now=NOW,
        )
    assert error.value.error_type == "tracking_idempotency_conflict"
    assert len(calls) == 1


def test_saved_retry_failure_and_unknown_replay_keep_at_most_once_boundary(tmp_path: Path) -> None:
    config, record = _tracking(tmp_path)
    repository = _saved_repository(tmp_path)
    failed_record = record
    calls: list[int] = []
    first = run_saved_tracking_submit(
        config,
        repository=repository,
        **_input(repository, record),
        submit_one=lambda *_args: calls.append(1) or _failure(),
        readback_external=_empty_readback(),
        now=NOW,
    )
    assert first["outcome"] == TRACKING_STATUS_SUBMIT_FAILED
    failed_record = load_tracking_record(config, record.tracking_id)
    retry_payload = _input(
        repository,
        failed_record,
        idempotency_key="saved-retry-key",
    )
    retry = run_saved_tracking_retry(
        config,
        repository=repository,
        **retry_payload,
        submit_one=lambda *_args: calls.append(1) or _unknown(),
        readback_external=_unreadable_readback(),
        now=NOW,
    )
    assert retry["outcome"] == TRACKING_STATUS_VERIFYING_EXTERNAL
    operation_id = retry["operation_id"]
    replay = run_saved_tracking_retry(
        config,
        repository=repository,
        **retry_payload,
        submit_one=lambda *_args: calls.append(1) or _success(),
        readback_external=_matching_readback(),
        now=NOW,
    )
    assert replay["outcome"] == TRACKING_STATUS_VERIFYING_EXTERNAL
    assert len(calls) == 2
    assert load_tracking_operation(config, operation_id).state == TRACKING_OPERATION_STATE_OUTCOME_UNKNOWN
