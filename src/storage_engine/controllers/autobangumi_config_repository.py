from __future__ import annotations

"""Private deployment-level Auto Bangumi configuration repository.

This repository is intentionally separate from :mod:`storage_config`: the
business storage root can be selected as a relative profile by the Web API,
while this root is selected only by the server process.  The only persistent
record that may contain an AB address or credential is ``autobangumi.json`` in
this directory.
"""

import contextlib
import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Literal
from uuid import UUID, uuid4

from ab_engine.controllers.ab_config import AutoBangumiConfig, normalize_service_root
from shared.config import PROJECT_ROOT
from shared.errors import Stage1Error

WEB_CONFIG_ROOT_ENV = "MIGU_ORCA_WEB_CONFIG_ROOT"
DEFAULT_WEB_CONFIG_ROOT = PROJECT_ROOT / ".migu_orca" / "config"
AUTOBANGUMI_CONFIG_FILENAME = "autobangumi.json"
_AUTOBANGUMI_TEMP_FILENAME = f".{AUTOBANGUMI_CONFIG_FILENAME}.tmp"
_CONFIG_VERSION = 1
_MAX_CONFIG_BYTES = 64 * 1024
_MAX_SERVICE_ROOT_LENGTH = 2048
_MAX_USERNAME_LENGTH = 1024
_CONFIG_FIELDS = frozenset(
    {"version", "configuration_revision", "configured", "connection_ref", "config"}
)
_CONFIG_DATA_FIELDS = frozenset({"base_url", "auth_mode", "username", "password", "token"})
_AUTH_MODES = ("password", "api_token")
_repository_lock = RLock()
_active_leases: dict[Path, int] = {}


@dataclass(frozen=True, repr=False)
class StoredAutoBangumiConfig:
    """A validated, server-only AB credential snapshot.

    ``repr`` is custom even though the individual secret fields also have
    ``repr=False``.  This protects callers that print the enclosing object and
    makes it impossible to accidentally add a new displayed field later.
    """

    base_url: str = field(repr=False)
    auth_mode: Literal["password", "api_token"] = field(repr=False)
    username: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)
    token: str | None = field(default=None, repr=False)

    def __repr__(self) -> str:
        return (
            "StoredAutoBangumiConfig("
            f"auth_mode={self.auth_mode!r}, credential_present={self.credential_present}"
            ")"
        )

    @property
    def credential_present(self) -> bool:
        return self.username is not None or self.token is not None

    def to_runtime_config(self) -> AutoBangumiConfig:
        """Create a request-scoped adapter config without persisting it."""

        return AutoBangumiConfig(
            base_url=self.base_url,
            auth_mode=self.auth_mode,
            fallback_enabled=False,
            username=self.username,
            password=self.password,
            token=self.token,
        )


# Descriptive aliases keep the repository seam easy to discover for later
# service stories without creating a second model or storage format.
AutoBangumiStoredConfig = StoredAutoBangumiConfig


@dataclass(frozen=True, repr=False)
class AutoBangumiConfigRecord:
    """The durable configuration version, including a possible tombstone."""

    configuration_revision: int
    connection_ref: UUID | None
    config: StoredAutoBangumiConfig | None = field(repr=False, default=None)

    def __repr__(self) -> str:
        return (
            "AutoBangumiConfigRecord("
            f"configuration_revision={self.configuration_revision}, "
            f"configured={self.config is not None}, connection_ref={self.connection_ref!s})"
        )

    @property
    def configured(self) -> bool:
        return self.config is not None


class AutoBangumiConfigLease:
    """Process-local lease over one immutable saved configuration snapshot."""

    def __init__(self, root: Path, record: AutoBangumiConfigRecord) -> None:
        self.record = record
        self._root = root
        self._released = False

    def __enter__(self) -> AutoBangumiConfigLease:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()

    def release(self) -> None:
        if self._released:
            return
        with _repository_lock:
            count = _active_leases.get(self._root, 0)
            if count <= 1:
                _active_leases.pop(self._root, None)
            else:
                _active_leases[self._root] = count - 1
            self._released = True


def resolve_web_config_root(root: Path | str | None = None) -> Path:
    """Resolve the server-owned configuration root without following links.

    A relative environment value is anchored to the project root so a changed
    working directory cannot silently select a different credentials store.
    The returned path is lexical; symlink checks happen before every IO.
    """

    if root is None:
        configured_root = os.environ.get(WEB_CONFIG_ROOT_ENV, "").strip()
        root = configured_root or DEFAULT_WEB_CONFIG_ROOT
    path = Path(root).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return Path(os.path.abspath(path))


# Short names are useful at the app seam and remain server-side functions; no
# request payload is ever passed here.
get_web_config_root = resolve_web_config_root


def build_stored_autobangumi_config(
    data: dict[str, Any], *, failed_step: str = "save_autobangumi_config"
) -> StoredAutoBangumiConfig:
    """Build the strict password/token union used by the private repository."""

    if not isinstance(data, dict) or set(data) - _CONFIG_DATA_FIELDS:
        _raise_config(failed_step, "config")
    auth_mode = data.get("auth_mode")
    if auth_mode not in _AUTH_MODES:
        _raise_config(failed_step, "auth_mode")
    base_url = normalize_service_root(data.get("base_url"), failed_step=failed_step)

    if auth_mode == "password":
        if set(data) != {"auth_mode", "base_url", "username", "password"}:
            _raise_config(failed_step, "auth_mode")
        username = _required_secret(
            data.get("username"), "username", failed_step, max_length=_MAX_USERNAME_LENGTH
        )
        password = _required_secret(data.get("password"), "password", failed_step)
        return StoredAutoBangumiConfig(
            base_url=base_url,
            auth_mode="password",
            username=username,
            password=password,
        )

    if set(data) != {"auth_mode", "base_url", "token"}:
        _raise_config(failed_step, "auth_mode")
    return StoredAutoBangumiConfig(
        base_url=base_url,
        auth_mode="api_token",
        token=_required_secret(data.get("token"), "token", failed_step),
    )


class AutoBangumiConfigRepository:
    """CAS and atomic-file repository for one deployment-wide AB connection."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = resolve_web_config_root(root)
        self.path = self.root / AUTOBANGUMI_CONFIG_FILENAME

    def load(self) -> AutoBangumiConfigRecord:
        with _repository_lock:
            self._validate_root(create=False)
            if not _exists_without_following_links(self.path):
                return AutoBangumiConfigRecord(0, None)
            return _record_from_storage(self._read_json(), "load_autobangumi_config")

    def save(
        self,
        config: StoredAutoBangumiConfig,
        *,
        expected_configuration_revision: int,
    ) -> AutoBangumiConfigRecord:
        if not isinstance(config, StoredAutoBangumiConfig):
            _raise_config("save_autobangumi_config", "config")
        # Dataclasses can be constructed directly; revalidate the complete
        # union at the persistence boundary so malformed snapshots never land
        # on disk.
        config = build_stored_autobangumi_config(_stored_config_data(config))
        _validate_revision(expected_configuration_revision, "save_autobangumi_config")
        with _repository_lock:
            self._validate_root(create=True)
            current = self._current_locked("save_autobangumi_config")
            self._ensure_no_active_lease("save_autobangumi_config")
            _check_revision(current.configuration_revision, expected_configuration_revision, "save_autobangumi_config")
            connection_ref = uuid4()
            while connection_ref == current.connection_ref:
                connection_ref = uuid4()
            record = AutoBangumiConfigRecord(current.configuration_revision + 1, connection_ref, config)
            self._write_locked(record, "save_autobangumi_config")
            return record

    def delete(self, *, expected_configuration_revision: int) -> AutoBangumiConfigRecord:
        _validate_revision(expected_configuration_revision, "delete_autobangumi_config")
        with _repository_lock:
            self._validate_root(create=True)
            current = self._current_locked("delete_autobangumi_config")
            self._ensure_no_active_lease("delete_autobangumi_config")
            _check_revision(current.configuration_revision, expected_configuration_revision, "delete_autobangumi_config")
            record = AutoBangumiConfigRecord(current.configuration_revision + 1, None)
            self._write_locked(record, "delete_autobangumi_config")
            return record

    def acquire_lease(
        self,
        *,
        connection_ref: UUID | str | None = None,
        configuration_revision: int | None = None,
    ) -> AutoBangumiConfigLease:
        """Acquire a non-blocking lease and return the immutable snapshot."""

        with _repository_lock:
            self._validate_root(create=False)
            record = self._current_locked("acquire_autobangumi_config_lease")
            if record.config is None or record.connection_ref is None:
                raise Stage1Error("config_error", "Auto Bangumi 配置未配置", "acquire_autobangumi_config_lease")
            if configuration_revision is not None:
                _validate_revision(configuration_revision, "acquire_autobangumi_config_lease")
                if record.configuration_revision != configuration_revision:
                    _check_revision(record.configuration_revision, configuration_revision, "acquire_autobangumi_config_lease")
            if connection_ref is not None:
                try:
                    expected_ref = connection_ref if isinstance(connection_ref, UUID) else UUID(connection_ref)
                except (ValueError, AttributeError, TypeError) as exc:
                    raise Stage1Error("config_error", "Auto Bangumi 配置引用无效", "acquire_autobangumi_config_lease") from exc
                if isinstance(connection_ref, str) and str(expected_ref) != connection_ref:
                    raise Stage1Error("config_error", "Auto Bangumi 配置引用无效", "acquire_autobangumi_config_lease")
                if expected_ref != record.connection_ref:
                    raise Stage1Error("connection_ref_conflict", "Auto Bangumi 配置引用已变化", "acquire_autobangumi_config_lease")
            _active_leases[self.root] = _active_leases.get(self.root, 0) + 1
            return AutoBangumiConfigLease(self.root, record)

    def _ensure_no_active_lease(self, failed_step: str) -> None:
        if _active_leases.get(self.root, 0):
            raise Stage1Error("connection_in_use", "Auto Bangumi 连接正在使用中", failed_step)

    def _current_locked(self, failed_step: str) -> AutoBangumiConfigRecord:
        if not _exists_without_following_links(self.path):
            return AutoBangumiConfigRecord(0, None)
        return _record_from_storage(self._read_json(), failed_step)

    def _validate_root(self, *, create: bool) -> None:
        _validate_path_components(self.root, "ensure_autobangumi_config_root")
        if not _exists_without_following_links(self.root):
            if not create:
                return
            try:
                self.root.mkdir(parents=True, mode=0o700, exist_ok=False)
            except FileExistsError:
                pass
            except OSError as exc:
                raise _storage_error("ensure_autobangumi_config_root") from exc
        _require_directory_mode(self.root, "ensure_autobangumi_config_root")

    def _read_json(self) -> Any:
        _require_regular_file(self.path, "load_autobangumi_config")
        fd = -1
        try:
            nofollow = getattr(os, "O_NOFOLLOW", None)
            if nofollow is None:
                raise OSError("secure no-follow open is unavailable")
            flags = os.O_RDONLY | nofollow
            fd = os.open(self.path, flags)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > _MAX_CONFIG_BYTES:
                raise OSError("unsafe config file")
            with os.fdopen(fd, "r", encoding="utf-8") as stream:
                fd = -1
                return json.load(stream)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise Stage1Error(
                "storage_json_error",
                "读取 Auto Bangumi 配置失败",
                "load_autobangumi_config",
            ) from exc
        finally:
            if fd >= 0:
                with contextlib.suppress(OSError):
                    os.close(fd)

    def _write_locked(self, record: AutoBangumiConfigRecord, failed_step: str) -> None:
        payload = json.dumps(_record_to_storage(record), ensure_ascii=False, indent=2) + "\n"
        temp_path = self.root / _AUTOBANGUMI_TEMP_FILENAME
        if _exists_without_following_links(temp_path):
            raise _storage_error(failed_step)
        fd = -1
        created = False
        try:
            nofollow = getattr(os, "O_NOFOLLOW", None)
            if nofollow is None:
                raise OSError("secure no-follow open is unavailable")
            fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow, 0o600)
            created = True
            os.fchmod(fd, 0o600)
            if stat.S_IMODE(os.fstat(fd).st_mode) != 0o600:
                raise OSError("unsafe temporary file")
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                fd = -1
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, self.path)
            created = False
        except OSError as exc:
            raise _storage_error(failed_step) from exc
        finally:
            if fd >= 0:
                with contextlib.suppress(OSError):
                    os.close(fd)
            if created:
                with contextlib.suppress(OSError):
                    temp_path.unlink()


def load_autobangumi_config(root: Path | str | None = None) -> AutoBangumiConfigRecord:
    return AutoBangumiConfigRepository(root).load()


def save_autobangumi_config(
    config: StoredAutoBangumiConfig,
    *,
    expected_configuration_revision: int,
    root: Path | str | None = None,
) -> AutoBangumiConfigRecord:
    return AutoBangumiConfigRepository(root).save(
        config, expected_configuration_revision=expected_configuration_revision
    )


def delete_autobangumi_config(
    *, expected_configuration_revision: int, root: Path | str | None = None
) -> AutoBangumiConfigRecord:
    return AutoBangumiConfigRepository(root).delete(
        expected_configuration_revision=expected_configuration_revision
    )


def _record_to_storage(record: AutoBangumiConfigRecord) -> dict[str, Any]:
    if record.config is None:
        return {
            "version": _CONFIG_VERSION,
            "configuration_revision": record.configuration_revision,
            "configured": False,
            "connection_ref": None,
        }
    config = record.config
    data: dict[str, Any] = {
        "base_url": config.base_url,
        "auth_mode": config.auth_mode,
    }
    if config.auth_mode == "password":
        data.update({"username": config.username, "password": config.password})
    else:
        data["token"] = config.token
    return {
        "version": _CONFIG_VERSION,
        "configuration_revision": record.configuration_revision,
        "configured": True,
        "connection_ref": str(record.connection_ref),
        "config": data,
    }


def _stored_config_data(config: StoredAutoBangumiConfig) -> dict[str, Any]:
    # Preserve every field when re-validating a directly constructed
    # dataclass.  Omitting an unexpected credential here would turn a malformed
    # object into a valid one at the persistence boundary.
    data: dict[str, Any] = {
        "base_url": config.base_url,
        "auth_mode": config.auth_mode,
        "username": config.username,
        "password": config.password,
        "token": config.token,
    }
    data = {key: value for key, value in data.items() if value is not None}
    return data


def _record_from_storage(value: Any, failed_step: str) -> AutoBangumiConfigRecord:
    if not isinstance(value, dict) or set(value) - _CONFIG_FIELDS:
        raise _storage_json_error(failed_step)
    if isinstance(value.get("version"), bool) or value.get("version") != _CONFIG_VERSION:
        raise _storage_json_error(failed_step)
    revision = value.get("configuration_revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        raise _storage_json_error(failed_step)
    configured = value.get("configured")
    if not isinstance(configured, bool):
        raise _storage_json_error(failed_step)
    ref_value = value.get("connection_ref")
    if not configured:
        if set(value) != {"version", "configuration_revision", "configured", "connection_ref"} or ref_value is not None:
            raise _storage_json_error(failed_step)
        return AutoBangumiConfigRecord(revision, None)
    if not isinstance(ref_value, str):
        raise _storage_json_error(failed_step)
    try:
        connection_ref = UUID(ref_value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise _storage_json_error(failed_step) from exc
    if str(connection_ref) != ref_value:
        raise _storage_json_error(failed_step)
    if set(value) != _CONFIG_FIELDS or not isinstance(value.get("config"), dict):
        raise _storage_json_error(failed_step)
    try:
        config = build_stored_autobangumi_config(
            value["config"], failed_step=failed_step
        )
    except Stage1Error as exc:
        raise _storage_json_error(failed_step) from exc
    return AutoBangumiConfigRecord(revision, connection_ref, config)


def _required_secret(
    value: Any,
    field_name: str,
    failed_step: str,
    *,
    max_length: int = 4096,
) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        _raise_config(failed_step, field_name)
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        _raise_config(failed_step, field_name)
    return value.strip()


def _validate_revision(value: Any, failed_step: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        _raise_config(failed_step, "expected_configuration_revision")


def _check_revision(current: int, expected: int, failed_step: str) -> None:
    if current != expected:
        raise Stage1Error(
            "configuration_revision_conflict",
            "Auto Bangumi 配置已变化，请重新读取后重试",
            failed_step,
            {"expected_configuration_revision": expected, "current_configuration_revision": current},
        )


def _validate_path_components(path: Path, failed_step: str) -> None:
    current = Path(path.anchor) if path.anchor else Path()
    for part in path.parts[1:] if path.anchor else path.parts:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            break
        except OSError as exc:
            raise _storage_error(failed_step) from exc
        if stat.S_ISLNK(info.st_mode):
            raise _storage_error(failed_step)


def _exists_without_following_links(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise _storage_error("load_autobangumi_config") from exc
    return True


def _require_directory_mode(path: Path, failed_step: str) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise _storage_error(failed_step) from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
        raise _storage_error(failed_step)


def _require_regular_file(path: Path, failed_step: str) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise _storage_error(failed_step) from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
        raise _storage_error(failed_step)


def _raise_config(failed_step: str, field_name: str) -> None:
    raise Stage1Error(
        "config_error", "Auto Bangumi 配置无效", failed_step, {"field": field_name}
    )


def _storage_error(failed_step: str) -> Stage1Error:
    return Stage1Error("storage_error", "Auto Bangumi 配置存储不可用", failed_step)


def _storage_json_error(failed_step: str) -> Stage1Error:
    return Stage1Error("storage_json_error", "Auto Bangumi 配置内容无效", failed_step)


__all__ = [
    "AUTOBANGUMI_CONFIG_FILENAME",
    "AutoBangumiConfigRecord",
    "AutoBangumiConfigLease",
    "AutoBangumiConfigRepository",
    "AutoBangumiStoredConfig",
    "DEFAULT_WEB_CONFIG_ROOT",
    "StoredAutoBangumiConfig",
    "WEB_CONFIG_ROOT_ENV",
    "build_stored_autobangumi_config",
    "delete_autobangumi_config",
    "get_web_config_root",
    "load_autobangumi_config",
    "normalize_service_root",
    "resolve_web_config_root",
    "save_autobangumi_config",
]
