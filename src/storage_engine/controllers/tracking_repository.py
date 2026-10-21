"""Durable unified tracking-record repository (US-219).

The tracking repository persists exactly one JSON file per deterministic
``tracking_id`` under ``<storage>/tracking``.  It is the persistence boundary
for the Stage 29 B-B tracking flow and provides:

- ``ensure_tracking_record`` — create-if-absent keyed by the deterministic id
  derived from ``request_id``; concurrent callers converge to the same record
  (D29-02/D29-03);
- ``load_tracking_record`` — read one record (``tracking_not_found`` when the
  file is absent, a stable ``storage_json_error`` when damaged);
- ``compare_and_swap_tracking_record`` — replace a record atomically only when
  the on-disk ``revision`` equals ``base_revision``, bumping ``revision`` by
  exactly one (revision compare-and-swap, D29-05);
- ``list_tracking_records`` — healthy records plus the opaque ids of damaged
  files so callers can report safe counts without leaking file paths.

Storage rules
-------------
- Writes go through ``storage_primitives.write_text_atomic`` (temp file +
  ``os.replace``) so a crash can never leave a
  half-written record (the same pattern as ``idempotency_repository``).
- A per-``tracking_id`` process lock serializes ensure/CAS writers; readers rely
  on atomic replace.  Multiple OS processes sharing one storage directory are
  still out of scope for Stage 29.
- Records are validated/normalized through ``tracking_to/from_storage_dict``
  before write, so the persisted bytes always match the strict schema whitelist
  and never carry sensitive content.
- Damaged records are never deleted or auto-overwritten; a single damaged file
  does not block the healthy list.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shared.errors import Stage1Error
from storage_engine.controllers.storage_config import (
    StorageConfig,
    ensure_storage_layout,
)
from storage_engine.controllers.storage_primitives import (
    KeyedLocks,
    is_relative_to,
    write_text_atomic,
)
from tracking_engine.models.tracking import (
    TRACKING_ORIGIN_EXTERNAL_SYNC,
    TrackingRecord,
    tracking_from_storage_dict,
    tracking_id_for_request,
    tracking_to_storage_dict,
)

#: Opaque tracking-id shape.  Request-backed ids are ``trk_<32 hex>``; the
#: character whitelist keeps the id usable as a single safe path/URL segment.
_TRACKING_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class TrackingListResult:
    """Healthy records plus the opaque ids of damaged files.

    ``damaged_tracking_ids`` is intended for internal bookkeeping (e.g. the
    migration manifest's unreadable count); API layers must only expose the
    safe ``unreadable_count`` and a fixed warning, never the ids themselves.
    """

    records: list[TrackingRecord]
    damaged_tracking_ids: tuple[str, ...]

    @property
    def unreadable_count(self) -> int:
        return len(self.damaged_tracking_ids)


#: Issue #223 (ADR-0007): one batch owns every tracking write for its whole
#: duration.  The lock is process-wide and non-blocking: a second batch — or a
#: single external write that would persist an intent — is refused instead of
#: racing the batch.  The batch's own nested writes pass through because the
#: owning thread carries a non-zero depth.
_BATCH_LOCK = threading.Lock()
_BATCH_STATE = threading.local()


def _batch_depth() -> int:
    return getattr(_BATCH_STATE, "depth", 0)


@contextmanager
def tracking_batch_lease(
    *, batch_key: str, step: str = "tracking_batch_lease"
) -> Iterator[str]:
    """Hold the batch write lease (non-blocking, re-entrant per thread).

    A non-zero depth means the current thread already owns the lease, so the
    batch service and the single-item services it reuses can nest.  Any other
    thread's batch or single tracking write fails closed with
    ``connection_in_use``, which the API maps to 409.
    """
    depth = _batch_depth()
    if depth == 0 and not _BATCH_LOCK.acquire(blocking=False):
        raise Stage1Error(
            "connection_in_use",
            "另一个批量操作正在执行，请稍后再试",
            step,
            {"batch_key": batch_key},
        )
    _BATCH_STATE.depth = depth + 1
    try:
        yield batch_key
    finally:
        _BATCH_STATE.depth = depth
        if depth == 0:
            _BATCH_LOCK.release()


def tracking_batch_active() -> bool:
    """True while any batch holds the write lease (safe to call anywhere)."""
    return _BATCH_LOCK.locked()


def _require_foreign_batch_allows_write(step: str) -> None:
    """Refuse a tracking write while another thread's batch owns the store."""
    if _BATCH_LOCK.locked() and _batch_depth() == 0:
        raise Stage1Error(
            "connection_in_use",
            "批量操作正在执行，请稍后再试",
            step,
        )


def ensure_tracking_record(
    config: StorageConfig,
    record: TrackingRecord,
) -> tuple[TrackingRecord, bool]:
    """Atomically create ``record`` if no record exists for its request.

    The target id is derived from ``record.request_id`` (never trusted from
    the caller), so concurrent ``ensure``/restart/terminal replay/migration for
    the same Request always converge to the same file.  When a record already
    exists the on-disk record is returned unchanged (``created=False``); an
    existing record is never overwritten by a later ensure.

    Returns ``(record, created)``.
    """
    _require_foreign_batch_allows_write("ensure_tracking_record")
    request_id = record.request_id
    if record.origin == TRACKING_ORIGIN_EXTERNAL_SYNC:
        if request_id is not None:
            raise Stage1Error(
                "invalid_tracking_record",
                "外部同步记录不得包含 request_id",
                "ensure_tracking_record",
                {"field": "request_id"},
            )
        clean_id = _validated_tracking_id(record.tracking_id, "ensure_tracking_record")
        if record.revision != 1:
            raise Stage1Error(
                "invalid_tracking_record",
                "新建追番记录 revision 必须为 1",
                "ensure_tracking_record",
                {"field": "revision", "revision": record.revision},
            )
        ensure_storage_layout(config)
        with _LOCKS.for_key(clean_id):
            if _tracking_path(config, clean_id, "ensure_tracking_record").exists():
                return _load_tracking_record(config, clean_id, "ensure_tracking_record"), False
            normalized = _normalize(record, "ensure_tracking_record")
            _atomic_write(config, clean_id, normalized, "ensure_tracking_record")
            return normalized, True
    if not isinstance(request_id, str) or not request_id.strip():
        raise Stage1Error(
            "invalid_tracking_record",
            "ensure 需要非空 request_id",
            "ensure_tracking_record",
            {"field": "request_id"},
        )
    if record.revision != 1:
        raise Stage1Error(
            "invalid_tracking_record",
            "新建追番记录 revision 必须为 1",
            "ensure_tracking_record",
            {"field": "revision", "revision": record.revision},
        )
    expected_id = tracking_id_for_request(request_id)
    if record.tracking_id != expected_id:
        raise Stage1Error(
            "invalid_tracking_record",
            "tracking_id 与 request_id 派生的确定性 ID 不一致",
            "ensure_tracking_record",
            {"field": "tracking_id"},
        )
    ensure_storage_layout(config)

    with _LOCKS.for_key(expected_id):
        if _tracking_path(config, expected_id, "ensure_tracking_record").exists():
            existing = _load_tracking_record(
                config, expected_id, "ensure_tracking_record"
            )
            return existing, False
        normalized = _normalize(record, "ensure_tracking_record")
        _atomic_write(config, expected_id, normalized, "ensure_tracking_record")
        return normalized, True


def load_tracking_record(
    config: StorageConfig,
    tracking_id: str,
) -> TrackingRecord:
    """Load one tracking record, raising ``tracking_not_found`` when absent."""
    clean_id = _validated_tracking_id(tracking_id, "load_tracking_record")
    return _load_tracking_record(config, clean_id, "load_tracking_record")


def delete_tracking_record(
    config: StorageConfig,
    tracking_id: str,
    *,
    expected_revision: int | None = None,
    step: str = "delete_tracking_record",
) -> dict[str, Any]:
    """Delete one tracking record file (issue #92).

    A missing record is an explicit ``tracking_not_found`` instead of a silent
    success, so a plan delete can never half-apply and report success. Only the
    record file is removed: no media, cache or external object is touched.

    Issue #230 (ADR-0006): ``expected_revision`` turns the delete into a
    compare-and-swap.  The revision is checked against the bytes on disk
    immediately before the unlink, so a delete that was confirmed against an
    older record removes nothing.  The project keeps its JSON store in one
    process without a background worker, so this read-then-unlink inside the
    repository is the strongest guarantee the storage layer offers.
    """
    _require_foreign_batch_allows_write(step)
    clean_id = _validated_tracking_id(tracking_id, step)
    path = _tracking_path(config, clean_id, step)
    # The read → compare → unlink runs under the same per-key lock as every other
    # tracking write, so a concurrent CAS cannot slip a new revision between the
    # check and the unlink (issue #230, ADR-0006).
    with _LOCKS.for_key(clean_id):
        if not path.exists():
            raise Stage1Error(
                "tracking_not_found",
                "未找到该追番记录",
                step,
                {"tracking_id": clean_id},
            )
        if expected_revision is not None:
            current = _load_tracking_record(config, clean_id, step)
            if current.revision != expected_revision:
                raise Stage1Error(
                    "tracking_revision_conflict",
                    "追番记录版本已变化，请刷新后重试",
                    step,
                    {
                        "tracking_id": clean_id,
                        "expected_revision": expected_revision,
                        "current_revision": current.revision,
                    },
                )
        try:
            path.unlink()
        except OSError as exc:
            raise Stage1Error(
                "storage_error",
                "删除追番记录失败",
                step,
                {"tracking_id": clean_id, "directory": config.tracking_dir.name},
            ) from exc
    return {"tracking_id": clean_id, "deleted": True}


def compare_and_swap_tracking_record(
    config: StorageConfig,
    tracking_id: str,
    base_revision: int,
    record: TrackingRecord,
) -> TrackingRecord:
    """Atomically replace a record iff its on-disk ``revision`` is current.

    On success the returned record has ``revision = base_revision + 1`` and the
    write is atomic.  A missing record raises ``tracking_not_found``; a stale
    ``base_revision`` raises ``tracking_revision_conflict``.  The caller is
    responsible for embedding the matching audit event in ``record``; the
    repository persists status + audit + revision as one atomic replace
    (D29-05).
    """
    _require_foreign_batch_allows_write("compare_and_swap_tracking_record")
    clean_id = _validated_tracking_id(tracking_id, "compare_and_swap_tracking_record")
    ensure_storage_layout(config)

    with _LOCKS.for_key(clean_id):
        current = _load_tracking_record(
            config, clean_id, "compare_and_swap_tracking_record"
        )
        if current.revision != base_revision:
            raise Stage1Error(
                "tracking_revision_conflict",
                "追番记录版本已变化，请刷新最新记录后重试",
                "compare_and_swap_tracking_record",
                {
                    "expected_revision": base_revision,
                    "current_revision": current.revision,
                },
            )
        if record.tracking_id != clean_id:
            raise Stage1Error(
                "invalid_tracking_record",
                "compare-and-swap 记录 tracking_id 不一致",
                "compare_and_swap_tracking_record",
                {"field": "tracking_id"},
            )
        if record.revision != base_revision + 1:
            raise Stage1Error(
                "invalid_tracking_record",
                "compare-and-swap 记录 revision 必须是当前 revision + 1",
                "compare_and_swap_tracking_record",
                {
                    "field": "revision",
                    "base_revision": base_revision,
                    "revision": record.revision,
                },
            )
        normalized = _normalize(record, "compare_and_swap_tracking_record")
        _atomic_write(
            config, clean_id, normalized, "compare_and_swap_tracking_record"
        )
        return normalized


def list_tracking_records(config: StorageConfig) -> TrackingListResult:
    """Return all healthy records plus ids of damaged/poisoned files.

    A damaged single file never blocks the healthy list and is never deleted;
    the damaged ids are reported so callers can expose only a safe count and a
    fixed warning.
    """
    if not config.tracking_dir.exists():
        return TrackingListResult(records=[], damaged_tracking_ids=())
    if not config.tracking_dir.is_dir():
        raise Stage1Error(
            "storage_error",
            "本地追番记录路径不是目录",
            "list_tracking_records",
            {"directory": config.tracking_dir.name},
        )

    try:
        tracking_files = sorted(config.tracking_dir.glob("*.json"))
    except OSError as exc:
        raise Stage1Error(
            "storage_error",
            "列出追番记录失败",
            "list_tracking_records",
            {"directory": config.tracking_dir.name},
        ) from exc

    records: list[TrackingRecord] = []
    damaged: list[str] = []
    for tracking_file in tracking_files:
        candidate_id = tracking_file.stem
        if not _TRACKING_ID_RE.fullmatch(candidate_id):
            # A stray JSON file that is not shaped like a tracking record.
            damaged.append(candidate_id)
            continue
        try:
            records.append(
                _load_tracking_record(config, candidate_id, "list_tracking_records")
            )
        except Stage1Error:
            damaged.append(candidate_id)
    return TrackingListResult(records=records, damaged_tracking_ids=tuple(damaged))


def _load_tracking_record(
    config: StorageConfig,
    tracking_id: str,
    failed_step: str,
) -> TrackingRecord:
    record_path = _tracking_path(config, tracking_id, failed_step)
    if not record_path.exists():
        raise Stage1Error(
            "tracking_not_found",
            "未找到该追番记录",
            failed_step,
            {"tracking_id": tracking_id},
        )

    try:
        loaded = json.loads(record_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise Stage1Error(
            "storage_json_error",
            "读取追番记录 JSON 失败",
            failed_step,
            {"tracking_id": tracking_id, "reason": exc.msg},
        ) from exc
    except OSError as exc:
        raise Stage1Error(
            "storage_error",
            "读取追番记录失败",
            failed_step,
            {"tracking_id": tracking_id, "directory": config.tracking_dir.name},
        ) from exc

    try:
        return tracking_from_storage_dict(loaded)
    except ValueError as exc:
        raise Stage1Error(
            "storage_json_error",
            "追番记录 JSON 格式无效",
            failed_step,
            {"tracking_id": tracking_id, "reason": str(exc)},
        ) from exc


def _atomic_write(
    config: StorageConfig,
    tracking_id: str,
    record: TrackingRecord,
    failed_step: str,
) -> None:
    record_path = _tracking_path(config, tracking_id, failed_step)
    payload = (
        json.dumps(
            tracking_to_storage_dict(record),
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
            "写入追番记录失败",
            failed_step,
            {"tracking_id": tracking_id, "directory": config.tracking_dir.name},
        ) from exc


def _normalize(record: TrackingRecord, failed_step: str) -> TrackingRecord:
    """Validate/normalize a record through the strict storage schema.

    This guarantees the exact bytes written always match the whitelist and that
    accidental sensitive nested content is stripped before it reaches disk.
    """
    try:
        return tracking_from_storage_dict(tracking_to_storage_dict(record))
    except ValueError as exc:
        raise Stage1Error(
            "invalid_tracking_record",
            "追番记录结构无效",
            failed_step,
            {"reason": str(exc)},
        ) from exc


def _validated_tracking_id(tracking_id: str, failed_step: str) -> str:
    if not isinstance(tracking_id, str) or not tracking_id.strip():
        raise Stage1Error(
            "invalid_tracking_id",
            "tracking_id 不能为空",
            failed_step,
            {"field": "tracking_id"},
        )
    clean_id = tracking_id.strip()
    if Path(clean_id).name != clean_id or "\\" in clean_id:
        raise Stage1Error(
            "invalid_tracking_id",
            "tracking_id 不能包含路径片段",
            failed_step,
            {"field": "tracking_id"},
        )
    if not _TRACKING_ID_RE.fullmatch(clean_id):
        raise Stage1Error(
            "invalid_tracking_id",
            "tracking_id 包含不合法字符",
            failed_step,
            {"field": "tracking_id"},
        )
    return clean_id


#: 进程内 per-key 锁池：同一条目的 ensure/CAS 写串行，不同条目互不阻塞。
_LOCKS = KeyedLocks()


def _tracking_path(
    config: StorageConfig,
    tracking_id: str,
    failed_step: str,
) -> Path:
    clean_id = _validated_tracking_id(tracking_id, failed_step)
    tracking_root = config.tracking_dir.resolve(strict=False)
    candidate = (config.tracking_dir / f"{clean_id}.json").resolve(strict=False)
    if not is_relative_to(candidate, tracking_root):
        raise Stage1Error(
            "invalid_tracking_id",
            "tracking_id 不能包含路径片段",
            failed_step,
            {"field": "tracking_id"},
        )
    return candidate


__all__ = [
    "tracking_batch_active",
    "tracking_batch_lease",
    "TrackingListResult",
    "compare_and_swap_tracking_record",
    "delete_tracking_record",
    "ensure_tracking_record",
    "list_tracking_records",
    "load_tracking_record",
]
