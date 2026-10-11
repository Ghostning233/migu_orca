from __future__ import annotations

"""Durable save-confirm idempotency records (US-213).

Stage 28's save-confirm composition (US-214) must be safe to retry when the
response is lost or the process restarts. The in-process ``DraftStore`` replay
tombstone only protects *one process lifetime*: after a restart the draft is
gone and a retried save would create a duplicate Request. This repository
persists the minimal non-sensitive record of every save-confirm attempt so a
retry with the same opaque ``idempotency_key`` converges to the same public
outcome instead of re-creating a Request.

Record shape (never more than this):

.. code-block:: text

    idempotency_key          opaque client key (validated, safe filename)
    operation                "SAVE_CONFIRM" (bound to the key forever)
    request_fingerprint      irreversible sha256 over an allowed-field
                             canonical form (never the raw Request)
    request_id               public saved Request id (optional until known)
    state                    IN_PROGRESS | SAVED_CONFIRM_FAILED | CONFIRMED
    created_at               ISO-8601 timestamp
    updated_at               ISO-8601 timestamp

Security rules
--------------
- A record never stores the draft, the full Request, the input title, external
  configs, URLs, magnets, credentials, error stacks, or absolute paths.
- ``request_fingerprint`` is a one-way digest: the caller passes only the
  canonicalized *allowed* fields (draft-independent identity of the Request's
  public essence), never the raw payload.
- File writes use the same atomic temp-file + ``os.replace`` pattern as
  ``save_user_preferences`` so a crash cannot leave a half-written record.
- A damaged/missing record surfaces as a stable ``storage_json_error`` /
  ``idempotency_not_found`` (never the raw bytes), and a key that was never
  bound returns ``None`` so the caller can start a fresh attempt.
"""

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shared.errors import Stage1Error
from storage_engine.controllers.storage_config import (
    StorageConfig,
    ensure_storage_layout,
)
from storage_engine.controllers.storage_primitives import (
    is_relative_to,
    write_text_atomic,
)

#: Public idempotency states (D28-06 / Stage 28 PRD §7).
IDEMPOTENCY_STATE_IN_PROGRESS = "IN_PROGRESS"
IDEMPOTENCY_STATE_SAVED_CONFIRM_FAILED = "SAVED_CONFIRM_FAILED"
IDEMPOTENCY_STATE_CONFIRMED = "CONFIRMED"

#: The single bound operation for Stage 28 save-confirm. A key can never be
#: rebound to a different operation; ``idempotency_conflict`` guards reuse.
IDEMPOTENCY_OPERATION_SAVE_CONFIRM = "SAVE_CONFIRM"


def create_idempotency_record(
    *,
    idempotency_key: str,
    operation: str,
    request_fingerprint: str,
    request_id: str | None,
    state: str,
    now: str | None = None,
) -> dict[str, Any]:
    """Build the storage dict for one idempotency record.

    ``now`` is the current ISO-8601 timestamp (UTC); callers that must freeze
    time for deterministic tests may pass it explicitly. Only the non-sensitive
    fields above are stored — never the draft, Request, title or credentials.
    """
    timestamp = now or datetime.now(UTC).isoformat()
    return {
        "idempotency_key": idempotency_key,
        "operation": operation,
        "request_fingerprint": request_fingerprint,
        "request_id": request_id,
        "state": state,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def load_idempotency_record(
    config: StorageConfig,
    idempotency_key: str,
) -> dict[str, Any] | None:
    """Load one idempotency record, returning ``None`` when never bound.

    A missing key (no file) returns ``None`` so the caller can start a fresh
    attempt. A damaged record raises ``storage_json_error`` (never leaking raw
    bytes or absolute paths); a non-object record raises a stable
    ``storage_json_error`` as well.
    """
    record_path = _idempotency_path(config, idempotency_key, "load_idempotency_record")
    if not record_path.exists():
        return None

    try:
        loaded = json.loads(record_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise Stage1Error(
            "storage_json_error",
            "读取保存确认幂等记录 JSON 失败",
            "load_idempotency_record",
            {"idempotency_key": idempotency_key, "reason": exc.msg},
        ) from exc
    except OSError as exc:
        raise Stage1Error(
            "storage_error",
            "读取保存确认幂等记录失败",
            "load_idempotency_record",
            {
                "idempotency_key": idempotency_key,
                "directory": config.idempotency_dir.name,
            },
        ) from exc

    if not isinstance(loaded, dict):
        raise Stage1Error(
            "storage_json_error",
            "保存确认幂等记录 JSON 必须是对象",
            "load_idempotency_record",
            {"idempotency_key": idempotency_key},
        )
    return deepcopy(loaded)


def save_idempotency_record(
    config: StorageConfig,
    record: dict[str, Any],
) -> dict[str, Any]:
    """Atomically persist one idempotency record keyed by ``idempotency_key``.

    The write uses a temp file + ``os.replace`` so a reader never observes a
    partially-written record. Only validated non-sensitive records should reach
    here; the repository itself never inspects payload contents.
    """
    idempotency_key = _extract_key(record, "save_idempotency_record")
    record_path = _idempotency_path(
        config, idempotency_key, "save_idempotency_record"
    )
    ensure_storage_layout(config)

    payload = (
        json.dumps(
            {key: record[key] for key in _RECORD_FIELDS if key in record},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    try:
        write_text_atomic(record_path, payload)
    except OSError as exc:
        raise Stage1Error(
            "storage_error",
            "保存确认幂等记录写入失败",
            "save_idempotency_record",
            {
                "idempotency_key": idempotency_key,
                "directory": config.idempotency_dir.name,
            },
        ) from exc

    return {
        "idempotency_key": idempotency_key,
        "storage": "local_json",
        "directory": config.idempotency_dir.name,
        "filename": record_path.name,
    }


#: Fields persisted on write (whitelist so a future accidental sensitive field
#: can never be stored even if the caller passes a wider dict).
_RECORD_FIELDS = (
    "idempotency_key",
    "operation",
    "request_fingerprint",
    "request_id",
    "state",
    "created_at",
    "updated_at",
)


def _extract_key(record: dict[str, Any], failed_step: str) -> str:
    idempotency_key = record.get("idempotency_key")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise Stage1Error(
            "invalid_idempotency_key",
            "保存确认幂等记录缺少有效 idempotency_key",
            failed_step,
            {"field": "idempotency_key"},
        )
    return idempotency_key.strip()


def _idempotency_path(
    config: StorageConfig,
    idempotency_key: str,
    failed_step: str,
) -> Path:
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise Stage1Error(
            "invalid_idempotency_key",
            "idempotency_key 不能为空",
            failed_step,
            {"field": "idempotency_key"},
        )

    clean_key = idempotency_key.strip()
    if Path(clean_key).name != clean_key or "\\" in clean_key:
        raise Stage1Error(
            "invalid_idempotency_key",
            "idempotency_key 不能包含路径片段",
            failed_step,
            {"field": "idempotency_key"},
        )

    idempotency_root = config.idempotency_dir.resolve(strict=False)
    candidate = (config.idempotency_dir / f"{clean_key}.json").resolve(
        strict=False
    )
    if not is_relative_to(candidate, idempotency_root):
        raise Stage1Error(
            "invalid_idempotency_key",
            "idempotency_key 不能包含路径片段",
            failed_step,
            {"field": "idempotency_key"},
        )
    return candidate



__all__ = [
    "IDEMPOTENCY_OPERATION_SAVE_CONFIRM",
    "IDEMPOTENCY_STATE_CONFIRMED",
    "IDEMPOTENCY_STATE_IN_PROGRESS",
    "IDEMPOTENCY_STATE_SAVED_CONFIRM_FAILED",
    "create_idempotency_record",
    "load_idempotency_record",
    "save_idempotency_record",
]
