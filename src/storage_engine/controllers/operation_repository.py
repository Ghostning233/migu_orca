"""Durable submit-operation repository (US-220).

The operation repository persists exactly one JSON file per deterministic
``operation_id`` under ``<storage>/tracking_operations``.  It is the durable
idempotency + recovery-evidence boundary for external submits and is **independent**
from the Stage 28 save-confirm idempotency repository (D29-04).

Keyed replay / binding rules
---------------------------
- ``bind_tracking_operation`` creates a ``PREPARED`` operation the first time an
  ``idempotency_key`` is seen, deriving the ``operation_id`` deterministically
  from the key.  A same-key request whose binding
  (``tracking_id``/``operation``/``expected_revision``/``request_fingerprint``)
  matches the stored operation returns the stored operation unchanged
  (``created=False``) so the caller replays the same public outcome.  A same-key
  request with any differing binding raises ``tracking_idempotency_conflict``.
- A user-initiated retry uses a fresh key, which derives a fresh operation.
- ``compare_and_swap_tracking_operation`` replaces an operation atomically only
  when the on-disk state equals ``expected_state`` and the record is a legal
  state transition; a concurrent/stale transition raises
  ``tracking_operation_state_conflict``.

Storage rules
-------------
- Writes use a temp file + ``os.replace`` (same pattern as the tracking and
  idempotency repositories) so a crash can never leave a half-written file.
- A per-``operation_id`` process lock serializes concurrent bind/CAS writers;
  readers rely on atomic replace.  Multiple OS processes sharing one storage
  directory remain out of scope for Stage 29.
- Operations are validated/normalized through
  ``operation_to/from_storage_dict`` before write, so persisted bytes always
  match the strict whitelist and never carry request bodies, AB config,
  upstream responses, titles, URLs, magnets or paths.
- After a restart the last atomically-written state (including ``IN_PROGRESS``
  and terminal results) is readable, which is what makes the record usable as
  cross-restart recovery evidence.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
from pathlib import Path
from threading import RLock
from typing import Any

from shared.errors import Stage1Error
from storage_engine.controllers.storage_config import (
    StorageConfig,
    ensure_storage_layout,
)
from tracking_engine.models.operation import (
    TrackingOperation,
    create_tracking_operation,
    operation_from_storage_dict,
    operation_to_storage_dict,
    tracking_operation_id_for_idempotency_key,
    tracking_operation_transition_allowed,
)

#: Opaque operation-id shape (``op_<32 hex>``).  The character whitelist keeps
#: the id usable as a single safe path/URL segment.
_OPERATION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

#: Safe opaque idempotency-key shape — mirrors the model so a bad key fails at
#: the repository boundary with a stable error before it ever reaches disk.
_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-:=]{0,199}$")

#: Fields that are immutable for the lifetime of an operation.  CAS writers may
#: only change state/result/error/timestamps, never the binding itself.
_IMMUTABLE_FIELDS = (
    "operation_id",
    "tracking_id",
    "operation",
    "idempotency_key",
    "expected_revision",
    "request_fingerprint",
    "attempt",
    "created_at",
)


def bind_tracking_operation(
    config: StorageConfig,
    *,
    tracking_id: str,
    operation: str,
    idempotency_key: str,
    expected_revision: int,
    request_fingerprint: str,
    attempt: int = 1,
    now: str | None = None,
) -> tuple[TrackingOperation, bool]:
    """Create a ``PREPARED`` operation for a key, or replay the bound one.

    The target ``operation_id`` is derived from ``idempotency_key`` (never
    trusted from the caller), so concurrent binds/restarts/network replays for
    the same key converge to the same file.  When an operation already exists
    for the key:

    - identical binding -> the stored operation is returned unchanged
      (``created=False``) so the caller replays the same public result without
      a second external call;
    - any differing binding -> ``tracking_idempotency_conflict`` is raised and
      the stored operation is left untouched.

    Returns ``(operation, created)``.
    """
    clean_key = _validated_idempotency_key(idempotency_key, "bind_tracking_operation")
    operation_id = tracking_operation_id_for_idempotency_key(clean_key)
    ensure_storage_layout(config)

    with _key_lock(operation_id):
        if _operation_path(config, operation_id, "bind_tracking_operation").exists():
            existing = _load_tracking_operation(
                config, operation_id, "bind_tracking_operation"
            )
            _check_binding(
                existing,
                tracking_id=tracking_id,
                operation=operation,
                expected_revision=expected_revision,
                request_fingerprint=request_fingerprint,
            )
            return existing, False
        try:
            record = create_tracking_operation(
                tracking_id=tracking_id,
                idempotency_key=clean_key,
                expected_revision=expected_revision,
                request_fingerprint=request_fingerprint,
                operation=operation,
                attempt=attempt,
                now=now,
            )
        except ValueError as exc:
            raise Stage1Error(
                "invalid_tracking_operation",
                "提交操作参数无效",
                "bind_tracking_operation",
                {"reason": str(exc)},
            ) from exc
        normalized = _normalize(record, "bind_tracking_operation")
        _atomic_write(config, operation_id, normalized, "bind_tracking_operation")
        return normalized, True


def load_tracking_operation(
    config: StorageConfig,
    operation_id: str,
) -> TrackingOperation:
    """Load one operation, raising ``tracking_operation_not_found`` when absent.

    A damaged/non-object/invalid file raises a stable ``storage_json_error`` /
    ``invalid_tracking_operation`` (never raw bytes or absolute paths).
    """
    clean_id = _validated_operation_id(operation_id, "load_tracking_operation")
    return _load_tracking_operation(config, clean_id, "load_tracking_operation")


def compare_and_swap_tracking_operation(
    config: StorageConfig,
    operation_id: str,
    expected_state: str,
    record: TrackingOperation,
) -> TrackingOperation:
    """Atomically replace an operation iff its on-disk state is current.

    On success the returned record is the normalized written form.  A missing
    operation raises ``tracking_operation_not_found``; a stale
    ``expected_state`` raises ``tracking_operation_state_conflict``; a record
    whose state is not a legal transition from the on-disk state (or whose
    immutable binding fields changed) raises ``invalid_tracking_operation``.
    """
    clean_id = _validated_operation_id(
        operation_id, "compare_and_swap_tracking_operation"
    )
    ensure_storage_layout(config)

    with _key_lock(clean_id):
        current = _load_tracking_operation(
            config, clean_id, "compare_and_swap_tracking_operation"
        )
        if current.state != expected_state:
            raise Stage1Error(
                "tracking_operation_state_conflict",
                "提交操作状态已变化，请重新读取后重试",
                "compare_and_swap_tracking_operation",
                {
                    "expected_state": expected_state,
                    "current_state": current.state,
                },
            )
        if record.operation_id != clean_id:
            raise Stage1Error(
                "invalid_tracking_operation",
                "compare-and-swap 操作记录 operation_id 不一致",
                "compare_and_swap_tracking_operation",
                {"field": "operation_id"},
            )
        if not tracking_operation_transition_allowed(current.state, record.state):
            raise Stage1Error(
                "invalid_tracking_operation",
                "提交操作状态迁移无效",
                "compare_and_swap_tracking_operation",
                {
                    "from_state": current.state,
                    "to_state": record.state,
                },
            )
        _check_immutable_binding(current, record)
        normalized = _normalize(record, "compare_and_swap_tracking_operation")
        _atomic_write(
            config, clean_id, normalized, "compare_and_swap_tracking_operation"
        )
        return normalized


def _check_binding(
    existing: TrackingOperation,
    *,
    tracking_id: str,
    operation: str,
    expected_revision: int,
    request_fingerprint: str,
) -> None:
    """Raise ``tracking_idempotency_conflict`` when the binding differs."""
    binding = (
        existing.tracking_id,
        existing.operation,
        existing.expected_revision,
        existing.request_fingerprint,
    )
    incoming = (
        tracking_id,
        operation,
        expected_revision,
        request_fingerprint,
    )
    if binding != incoming:
        raise Stage1Error(
            "tracking_idempotency_conflict",
            "同一幂等键已绑定不同的提交内容，不能复用",
            "bind_tracking_operation",
            {"field": "idempotency_key"},
        )


def _check_immutable_binding(
    current: TrackingOperation, record: TrackingOperation
) -> None:
    """Raise when a CAS tries to mutate an operation's immutable binding."""
    for field in _IMMUTABLE_FIELDS:
        if getattr(record, field) != getattr(current, field):
            raise Stage1Error(
                "invalid_tracking_operation",
                "compare-and-swap 不能修改提交操作的绑定字段",
                "compare_and_swap_tracking_operation",
                {"field": field},
            )


def _load_tracking_operation(
    config: StorageConfig,
    operation_id: str,
    failed_step: str,
) -> TrackingOperation:
    record_path = _operation_path(config, operation_id, failed_step)
    if not record_path.exists():
        raise Stage1Error(
            "tracking_operation_not_found",
            "未找到该提交操作",
            failed_step,
            {"operation_id": operation_id},
        )

    try:
        loaded = json.loads(record_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise Stage1Error(
            "storage_json_error",
            "读取提交操作 JSON 失败",
            failed_step,
            {"operation_id": operation_id, "reason": exc.msg},
        ) from exc
    except OSError as exc:
        raise Stage1Error(
            "storage_error",
            "读取提交操作失败",
            failed_step,
            {
                "operation_id": operation_id,
                "directory": config.tracking_operations_dir.name,
            },
        ) from exc

    try:
        return operation_from_storage_dict(loaded)
    except ValueError as exc:
        raise Stage1Error(
            "storage_json_error",
            "提交操作 JSON 格式无效",
            failed_step,
            {"operation_id": operation_id, "reason": str(exc)},
        ) from exc


def _atomic_write(
    config: StorageConfig,
    operation_id: str,
    operation: TrackingOperation,
    failed_step: str,
) -> None:
    record_path = _operation_path(config, operation_id, failed_step)
    payload = (
        json.dumps(
            operation_to_storage_dict(operation),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    temp_path = record_path.with_name(record_path.name + ".tmp")
    try:
        temp_path.write_text(payload, encoding="utf-8")
        os.replace(temp_path, record_path)
    except OSError as exc:
        raise Stage1Error(
            "storage_error",
            "写入提交操作失败",
            failed_step,
            {
                "operation_id": operation_id,
                "directory": config.tracking_operations_dir.name,
            },
        ) from exc
    finally:
        if temp_path.exists():
            with contextlib.suppress(OSError):
                temp_path.unlink()


def _normalize(operation: TrackingOperation, failed_step: str) -> TrackingOperation:
    """Validate/normalize an operation through the strict storage schema."""
    try:
        return operation_from_storage_dict(operation_to_storage_dict(operation))
    except ValueError as exc:
        raise Stage1Error(
            "invalid_tracking_operation",
            "提交操作结构无效",
            failed_step,
            {"reason": str(exc)},
        ) from exc


def _validated_idempotency_key(idempotency_key: Any, failed_step: str) -> str:
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise Stage1Error(
            "invalid_idempotency_key",
            "idempotency_key 不能为空",
            failed_step,
            {"field": "idempotency_key"},
        )
    clean_key = idempotency_key.strip()
    if not _IDEMPOTENCY_KEY_RE.fullmatch(clean_key):
        raise Stage1Error(
            "invalid_idempotency_key",
            "idempotency_key 包含不合法字符",
            failed_step,
            {"field": "idempotency_key"},
        )
    return clean_key


def _validated_operation_id(operation_id: Any, failed_step: str) -> str:
    if not isinstance(operation_id, str) or not operation_id.strip():
        raise Stage1Error(
            "invalid_operation_id",
            "operation_id 不能为空",
            failed_step,
            {"field": "operation_id"},
        )
    clean_id = operation_id.strip()
    if Path(clean_id).name != clean_id or "\\" in clean_id:
        raise Stage1Error(
            "invalid_operation_id",
            "operation_id 不能包含路径片段",
            failed_step,
            {"field": "operation_id"},
        )
    if not _OPERATION_ID_RE.fullmatch(clean_id):
        raise Stage1Error(
            "invalid_operation_id",
            "operation_id 包含不合法字符",
            failed_step,
            {"field": "operation_id"},
        )
    return clean_id


#: Process-level per-key locks so concurrent bind/CAS writers on the same
#: operation_id are serialized.  Locks live for the process lifetime; the id
#: space is small (one lock per operation).
_LOCK_GUARD: RLock = RLock()
_KEY_LOCKS: dict[str, RLock] = {}


def _key_lock(operation_id: str) -> RLock:
    with _LOCK_GUARD:
        lock = _KEY_LOCKS.get(operation_id)
        if lock is None:
            lock = RLock()
            _KEY_LOCKS[operation_id] = lock
        return lock


def _operation_path(
    config: StorageConfig,
    operation_id: str,
    failed_step: str,
) -> Path:
    clean_id = _validated_operation_id(operation_id, failed_step)
    operations_root = config.tracking_operations_dir.resolve(strict=False)
    candidate = (config.tracking_operations_dir / f"{clean_id}.json").resolve(
        strict=False
    )
    if not _is_relative_to(candidate, operations_root):
        raise Stage1Error(
            "invalid_operation_id",
            "operation_id 不能包含路径片段",
            failed_step,
            {"field": "operation_id"},
        )
    return candidate


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


__all__ = [
    "bind_tracking_operation",
    "compare_and_swap_tracking_operation",
    "load_tracking_operation",
]
