from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID

import pytest

from shared.errors import Stage1Error
from storage_engine.controllers.autobangumi_config_repository import (
    AUTOBANGUMI_CONFIG_FILENAME,
    DEFAULT_WEB_CONFIG_ROOT,
    AutoBangumiConfigRecord,
    AutoBangumiConfigRepository,
    StoredAutoBangumiConfig,
    build_stored_autobangumi_config,
    normalize_service_root,
    resolve_web_config_root,
)


def _config() -> StoredAutoBangumiConfig:
    return build_stored_autobangumi_config(
        {
            "auth_mode": "password",
            "base_url": "192.168.1.20:8080",
            "username": "admin",
            "password": "password-value",
        }
    )


def test_web_config_root_is_server_owned_and_has_a_separate_default() -> None:
    assert resolve_web_config_root() == DEFAULT_WEB_CONFIG_ROOT
    assert resolve_web_config_root("profiles/one") == DEFAULT_WEB_CONFIG_ROOT.parents[1] / "profiles/one"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("192.168.1.20:8080", "http://192.168.1.20:8080"),
        (" https://ab.example.invalid/ ", "https://ab.example.invalid"),
        ("[::1]:8080", "http://[::1]:8080"),
    ],
)
def test_stored_config_normalizes_http_root_and_bare_host_port(value: str, expected: str) -> None:
    assert normalize_service_root(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "ab.example.invalid",
        "https://user:password@ab.example.invalid",
        "https://ab.example.invalid/api/v1/status",
        "https://ab.example.invalid/?query=value",
        "https://ab.example.invalid/#fragment",
        "ftp://ab.example.invalid",
    ],
)
def test_stored_config_rejects_ambiguous_or_unsafe_roots(value: str) -> None:
    with pytest.raises(Stage1Error) as error:
        build_stored_autobangumi_config(
            {
                "auth_mode": "password",
                "base_url": value,
                "username": "admin",
                "password": "secret",
            }
        )
    assert error.value.error_type == "config_error"
    assert error.value.details == {"field": "base_url"}


@pytest.mark.parametrize("value", ["mailto:80", "ftp:80", "http://", "http://bad host:80"])
def test_service_root_rejects_pseudo_schemes_and_malformed_hosts(value: str) -> None:
    with pytest.raises(Stage1Error):
        normalize_service_root(value)


def test_save_revalidates_directly_constructed_mixed_credentials(tmp_path: Path) -> None:
    repository = AutoBangumiConfigRepository(tmp_path / "private-config")
    malformed = StoredAutoBangumiConfig(
        base_url="http://ab.example.invalid",
        auth_mode="password",
        username="u",
        password="p",
        token="unexpected",
    )
    with pytest.raises(Stage1Error):
        repository.save(malformed, expected_configuration_revision=0)


def test_tombstone_and_uuid_must_have_complete_canonical_shape(tmp_path: Path) -> None:
    repository = AutoBangumiConfigRepository(tmp_path / "private-config")
    repository.save(_config(), expected_configuration_revision=0)
    payload = json.loads(repository.path.read_text(encoding="utf-8"))
    payload["connection_ref"] = payload["connection_ref"].upper()
    repository.path.write_text(json.dumps(payload), encoding="utf-8")
    repository.path.chmod(0o600)
    with pytest.raises(Stage1Error):
        repository.load()
    repository.path.write_text(json.dumps({"version": 1, "configuration_revision": 2, "configured": False}), encoding="utf-8")
    repository.path.chmod(0o600)
    with pytest.raises(Stage1Error):
        repository.load()


@pytest.mark.parametrize(
    "payload",
    [
        {"auth_mode": "password", "base_url": "http://ab.invalid", "username": "u"},
        {"auth_mode": "api_token", "base_url": "http://ab.invalid", "password": "p"},
        {"auth_mode": "password", "base_url": "http://ab.invalid", "username": "u", "password": "p", "token": "t"},
    ],
)
def test_stored_config_is_a_strict_disjoint_auth_union(payload: dict[str, str]) -> None:
    with pytest.raises(Stage1Error) as error:
        build_stored_autobangumi_config(payload)
    assert error.value.error_type == "config_error"


def test_secret_models_do_not_leak_repr() -> None:
    config = _config()
    runtime = config.to_runtime_config()
    assert "password-value" not in repr(config)
    assert "192.168.1.20" not in repr(config)
    assert "password-value" not in repr(runtime)


def test_save_rebuild_delete_and_cas_are_revision_bound(tmp_path: Path) -> None:
    repository = AutoBangumiConfigRepository(tmp_path / "private-config")

    initial = repository.load()
    assert initial == AutoBangumiConfigRecord(0, None)

    saved = repository.save(_config(), expected_configuration_revision=0)
    assert saved.configuration_revision == 1
    assert isinstance(saved.connection_ref, UUID)
    assert repository.path == repository.root / AUTOBANGUMI_CONFIG_FILENAME
    assert os.stat(repository.root).st_mode & 0o777 == 0o700
    assert os.stat(repository.path).st_mode & 0o777 == 0o600
    assert repository.load() == saved

    with pytest.raises(Stage1Error) as error:
        repository.save(_config(), expected_configuration_revision=0)
    assert error.value.error_type == "configuration_revision_conflict"
    assert repository.load() == saved

    deleted = repository.delete(expected_configuration_revision=1)
    assert deleted.configuration_revision == 2
    assert deleted.connection_ref is None
    assert deleted.config is None
    stored = json.loads(repository.path.read_text(encoding="utf-8"))
    assert stored == {
        "version": 1,
        "configuration_revision": 2,
        "configured": False,
        "connection_ref": None,
    }

    rebuilt = AutoBangumiConfigRepository(repository.root).save(
        _config(), expected_configuration_revision=2
    )
    assert rebuilt.configuration_revision == 3
    assert rebuilt.connection_ref != saved.connection_ref


def test_shared_repository_lease_blocks_mutation_and_releases(tmp_path: Path) -> None:
    first = AutoBangumiConfigRepository(tmp_path / "private-config")
    second = AutoBangumiConfigRepository(tmp_path / "private-config")
    saved = first.save(_config(), expected_configuration_revision=0)
    with first.acquire_lease(connection_ref=saved.connection_ref, configuration_revision=1) as lease:
        assert lease.record == saved
        with pytest.raises(Stage1Error) as error:
            second.delete(expected_configuration_revision=1)
        assert error.value.error_type == "connection_in_use"
    deleted = second.delete(expected_configuration_revision=1)
    assert deleted.configuration_revision == 2


def test_lease_blocks_save_and_rejects_stale_or_unconfigured_refs(tmp_path: Path) -> None:
    repository = AutoBangumiConfigRepository(tmp_path / "private-config")
    with pytest.raises(Stage1Error):
        repository.acquire_lease()
    saved = repository.save(_config(), expected_configuration_revision=0)
    with pytest.raises(Stage1Error):
        repository.acquire_lease(connection_ref=str(saved.connection_ref).upper(), configuration_revision=1)
    with pytest.raises(Stage1Error):
        repository.acquire_lease(connection_ref="00000000-0000-0000-0000-000000000000", configuration_revision=1)
    with pytest.raises(Stage1Error):
        repository.acquire_lease(connection_ref=saved.connection_ref, configuration_revision=0)
    with pytest.raises(RuntimeError), repository.acquire_lease(connection_ref=saved.connection_ref, configuration_revision=1):
        raise RuntimeError("release")
    repository.delete(expected_configuration_revision=1)


def test_atomic_write_failure_keeps_last_successful_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = AutoBangumiConfigRepository(tmp_path / "private-config")
    saved = repository.save(_config(), expected_configuration_revision=0)

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("injected")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(Stage1Error) as error:
        repository.save(
            build_stored_autobangumi_config(
                {
                    "auth_mode": "api_token",
                    "base_url": "https://other.invalid",
                    "token": "new-token",
                }
            ),
            expected_configuration_revision=1,
        )
    assert error.value.error_type == "storage_error"
    assert repository.load() == saved
    assert not (repository.root / ".autobangumi.json.tmp").exists()


def test_successful_replace_does_not_remove_recreated_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository = AutoBangumiConfigRepository(tmp_path / "private-config")
    repository.save(_config(), expected_configuration_revision=0)
    original_replace = os.replace

    def replace_and_recreate(source: Path, target: Path) -> None:
        original_replace(source, target)
        temp = target.parent / ".autobangumi.json.tmp"
        temp.write_text("attacker", encoding="utf-8")
        temp.chmod(0o600)

    monkeypatch.setattr(os, "replace", replace_and_recreate)
    repository.save(_config(), expected_configuration_revision=1)
    assert (repository.root / ".autobangumi.json.tmp").read_text(encoding="utf-8") == "attacker"


def test_root_and_file_symlinks_fail_closed(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(actual, target_is_directory=True)
    with pytest.raises(Stage1Error):
        AutoBangumiConfigRepository(link).save(_config(), expected_configuration_revision=0)

    repository = AutoBangumiConfigRepository(tmp_path / "private-config")
    repository.save(_config(), expected_configuration_revision=0)
    target = tmp_path / "outside.json"
    target.write_text("{}", encoding="utf-8")
    repository.path.unlink()
    repository.path.symlink_to(target)
    with pytest.raises(Stage1Error) as error:
        repository.load()
    assert error.value.error_type == "storage_error"


def test_insecure_permissions_and_damaged_json_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "private-config"
    root.mkdir(mode=0o700)
    root.chmod(0o755)
    with pytest.raises(Stage1Error):
        AutoBangumiConfigRepository(root).load()

    root.chmod(0o700)
    path = root / AUTOBANGUMI_CONFIG_FILENAME
    path.write_text("{", encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(Stage1Error) as error:
        AutoBangumiConfigRepository(root).load()
    assert error.value.error_type == "storage_json_error"


def test_config_canary_does_not_use_business_storage(tmp_path: Path) -> None:
    business_storage = tmp_path / "storage" / "profile-a"
    business_storage.mkdir(parents=True)
    canary = business_storage / "canary.json"
    canary.write_text('{"marker": "business"}', encoding="utf-8")

    repository = AutoBangumiConfigRepository(tmp_path / "config")
    repository.save(_config(), expected_configuration_revision=0)

    assert canary.read_text(encoding="utf-8") == '{"marker": "business"}'
    assert list(business_storage.rglob("*.json")) == [canary]
