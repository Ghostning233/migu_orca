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

Lock order (issue #247, refined by issue #248)
---------------------------------------------
An **external write intent** (``lock_tracking_record``) takes the store lock
first, then the per-record lock, then (inside ``operation_repository``) the
per-operation lock:

1. the batch store lock (``_serialized_tracking_write`` / ``tracking_batch_lease``);
2. the per-record lock (``lock_tracking_record``, keyed by ``tracking_id``);
3. the per-idempotency-key / per-operation lock taken inside
   ``operation_repository`` (keyed by the derived ``operation_id``).

The direction is mandatory: never take the store lock while holding a record or
operation lock, never take a record lock while holding an operation lock, take
several record locks in a stable id order if a caller ever needs two, and never
call an external service (Auto Bangumi, MiKan, qBittorrent) while any of these
locks is held.

Since #248 the store lock protects the batch's **occupied resources** (storage
profile + tracking id, plus the connection generation for connection-level
writes) instead of the whole store: a pure-local record write (CAS/ensure/delete
from revalidate, check, sync, handoff) takes only the per-record lock, so it
never queues behind a batch and never takes the store lock.  An external write
intent that targets a record the running batch owns waits for that batch
(bounded, ``connection_in_use``) *before* its bind, so it is never refused after
persisting its intent; an intent on another record or profile passes without the
store lock.  When no batch runs, the intent still holds the store lock across
``bind + record-pointer write + the operation execution gate`` so a batch cannot
start inside that critical section (ADR-0008 decision 2).  That critical section
is what keeps a concurrent same-key request from observing a half-written
binding and two retriers from both taking execution.  A process crash can still
interrupt the two file writes; that residue is claimed by the verified rule in
``operation_repository.claimable_prepared_operation``.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Iterable, Iterator
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


#: Issue #223/#248 (ADR-0007): a batch occupies a **resource scope**, not the
#: whole store.  The scope names the tracking records it will write ([profile,
#: tracking_id] pairs) and the connection generation it uses.  Single external
#: writes on an occupied record queue behind the batch (bounded, then
#: ``connection_in_use``); unrelated records, other storage profiles and
#: pure-local writes are not blocked at all.
_BATCH_LOCK = threading.Lock()
_BATCH_STATE = threading.local()
#: Set while a **batch** lease is held.
_ACTIVE_BATCH = threading.Event()
_SCOPE_GUARD = threading.Lock()
_ACTIVE_SCOPE: TrackingBatchScope | None = None
#: External write intents currently inside their bind/pointer critical section.
#: A batch waits for this to drain before publishing its scope, so a new batch
#: can never start between an intent's decision and its binder (issue #248 R1/R2).
_INTENT_COND = threading.Condition(_SCOPE_GUARD)
_ACTIVE_INTENTS = 0

#: How long a batch waits for another batch/single write before failing closed.
#: The request itself keeps its own budget; this only bounds the queueing window.
_BATCH_WAIT_SECONDS = 10.0


@dataclass(frozen=True)
class TrackingBatchScope:
    """The resources one running batch occupies (issue #248).

    ``tracking_ids`` empty means the batch published no scope (a caller that did
    not use the scoped lease); such a batch keeps #223's fail-safe: every single
    external write conflicts.
    """

    batch_key: str
    tracking_ids: frozenset[str]
    connection_ref: str | None
    storage_dir: str | None


def _batch_depth() -> int:
    return getattr(_BATCH_STATE, "depth", 0)


@contextmanager
def _external_write_intent() -> Iterator[None]:
    """Mark one external write as inside its critical section (issue #248)."""
    global _ACTIVE_INTENTS
    with _INTENT_COND:
        _ACTIVE_INTENTS += 1
    try:
        yield
    finally:
        with _INTENT_COND:
            _ACTIVE_INTENTS -= 1
            if _ACTIVE_INTENTS == 0:
                _INTENT_COND.notify_all()


def _await_no_active_intents(step: str) -> None:
    """Wait (bounded) until no external write is mid critical section."""
    deadline = time.monotonic() + _BATCH_WAIT_SECONDS
    with _INTENT_COND:
        while _ACTIVE_INTENTS > 0:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Stage1Error(
                    "connection_in_use",
                    "另一个外部写正在执行，请稍后再试",
                    step,
                )
            _INTENT_COND.wait(timeout=remaining)


def _active_scope() -> TrackingBatchScope | None:
    with _SCOPE_GUARD:
        return _ACTIVE_SCOPE


def tracking_batch_scope() -> TrackingBatchScope | None:
    """The occupied resource scope of the running batch, or ``None``."""
    return _active_scope()


def note_request_storage_dirs(storage_dirs: Iterable[str] | None) -> None:
    """Publish the storage profiles this request may resolve to.

    Views disagree about where ``storage_dir`` comes from (the manual views read
    the body, the validator views let a query override it — see
    ``extensions.flask_api.views``), so the route guard records **every**
    candidate profile here and the final write gate treats any match as a
    conflict (fail closed, issue #248 B3).  Background threads leave it empty and
    fall back to the record-id comparison.
    """
    _BATCH_STATE.request_storage_dirs = frozenset(storage_dirs or ())


def _request_storage_dirs() -> frozenset[str]:
    return getattr(_BATCH_STATE, "request_storage_dirs", frozenset())


def _scope_conflicts(
    scope: TrackingBatchScope, tracking_id: str, storage_dirs: Iterable[str]
) -> bool:
    """The single conflict predicate shared by the guard and the write gate."""
    if not scope.tracking_ids:
        # Unknown scope: fail safe (the #223 blanket exclusion).
        return True
    if tracking_id.strip() not in scope.tracking_ids:
        return False
    candidates = frozenset(storage_dirs)
    if not candidates or scope.storage_dir is None:
        # Unknown profile on either side: compare by record id only.
        return True
    # A different profile is a different resource; a candidate that *is* the
    # batch's profile conflicts (fail closed when the request could mean either).
    return scope.storage_dir in candidates


def batch_conflicts_with(
    tracking_id: str, *, storage_dirs: Iterable[str] = ()
) -> bool:
    """Whether one external write on ``tracking_id`` conflicts with the batch."""
    scope = _active_scope()
    return scope is not None and _scope_conflicts(scope, tracking_id, storage_dirs)


@contextmanager
def tracking_batch_lease(
    *,
    batch_key: str,
    tracking_ids: Iterable[str] = (),
    connection_ref: str | None = None,
    storage_dir: str | None = None,
    step: str = "tracking_batch_lease",
) -> Iterator[str]:
    """Hold one batch and publish the resources it occupies (issue #248).

    A non-zero depth means the current thread already owns the lease, so the
    batch route, the batch service and the single-item services it reuses can
    nest without re-acquiring or overwriting the outer scope.  Another thread's
    batch either finishes first or, after the bounded wait, fails closed with
    ``connection_in_use`` (409).
    """
    global _ACTIVE_SCOPE
    depth = _batch_depth()
    if depth == 0 and not _BATCH_LOCK.acquire(timeout=_BATCH_WAIT_SECONDS):
        raise Stage1Error(
            "connection_in_use",
            "另一个批量操作正在执行，请稍后再试",
            step,
            {"batch_key": batch_key},
        )
    _BATCH_STATE.depth = depth + 1
    owns_batch = getattr(_BATCH_STATE, "batch", 0) == 0
    if owns_batch:
        try:
            # No external write may be inside its binder when this batch starts,
            # even if it began while another (non-conflicting) batch was running.
            _await_no_active_intents(step)
        except Stage1Error:
            _BATCH_STATE.depth = depth
            _BATCH_LOCK.release()
            raise
        _BATCH_STATE.batch = 1
        scope = TrackingBatchScope(
            batch_key=batch_key,
            tracking_ids=frozenset(str(item) for item in tracking_ids),
            connection_ref=connection_ref,
            storage_dir=storage_dir,
        )
        with _SCOPE_GUARD:
            _ACTIVE_SCOPE = scope
        _ACTIVE_BATCH.set()
    try:
        yield batch_key
    finally:
        if owns_batch:
            with _SCOPE_GUARD:
                _ACTIVE_SCOPE = None
            _BATCH_STATE.batch = 0
            _ACTIVE_BATCH.clear()
        _BATCH_STATE.depth = depth
        if depth == 0:
            _BATCH_LOCK.release()


@contextmanager
def _serialized_tracking_write(step: str) -> Iterator[None]:
    """Serialize one repository step against the resources a batch occupies.

    Only an **external write intent** (``lock_tracking_record``, taken around the
    bind + record pointer before any Auto Bangumi call) competes with a batch: it
    queues behind a batch that owns the same record and, after the bounded wait,
    fails closed with ``connection_in_use``.  Because #247 put the bind inside
    that critical section, the refusal happens before any intent is persisted, so
    no orphan operation can be left behind.

    Pure-local record writes (CAS/ensure/delete from revalidate, check, sync,
    handoff) and external writes on unrelated records or profiles do not touch a
    batch-occupied resource and proceed under their own per-record lock only
    (issue #248).
    """
    depth = _batch_depth()
    if depth > 0:
        # The owning batch (or an enclosing write in this thread) already holds
        # the store; count the nesting so a nested call cannot deadlock.
        _BATCH_STATE.depth = depth + 1
        try:
            yield
        finally:
            _BATCH_STATE.depth = depth
        return
    # ``lock_tracking_record`` publishes the record it is about to bind for; the
    # pure-local writers (CAS/ensure/delete from revalidate, check, sync, handoff)
    # publish nothing and therefore never wait for a batch (issue #248).
    tracking_id = getattr(_BATCH_STATE, "external_write_id", None)
    if tracking_id is None:
        yield
        return
    profiles = _request_storage_dirs()
    scope = _active_scope()
    if scope is not None and not _scope_conflicts(scope, tracking_id, profiles):
        # The batch owns other resources; the per-record lock is enough.  Mark
        # the nesting so a *nested* write can never fall back into the store-lock
        # path while this record lock is held (issue #248 R1).
        _BATCH_STATE.depth = 1
        try:
            yield
        finally:
            _BATCH_STATE.depth = 0
        return
    # No batch: hold the store lock so a batch cannot start *inside* this
    # external-write critical section (ADR-0008 decision 2 / #247).  Conflicting
    # batch: queue behind it — the bind happens after this gate, so the refusal
    # is always pre-intent.
    if not _BATCH_LOCK.acquire(timeout=_BATCH_WAIT_SECONDS):
        raise Stage1Error(
            "connection_in_use",
            "批量操作进行中：请等待批次结束后再操作该记录",
            step,
        )
    # Re-check under the lock: a batch that started in the race window and owns
    # other resources must not make an unrelated write fail.
    scope = _active_scope()
    if scope is not None and not _scope_conflicts(scope, tracking_id, profiles):
        _BATCH_LOCK.release()
        _BATCH_STATE.depth = 1
        try:
            yield
        finally:
            _BATCH_STATE.depth = 0
        return
    _BATCH_STATE.depth = 1
    try:
        yield
    finally:
        _BATCH_STATE.depth = 0
        _BATCH_LOCK.release()


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
        with _serialized_tracking_write("ensure_tracking_record"), _LOCKS.for_key(clean_id):
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

    with _serialized_tracking_write("ensure_tracking_record"), _LOCKS.for_key(expected_id):
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
    clean_id = _validated_tracking_id(tracking_id, step)
    path = _tracking_path(config, clean_id, step)
    # The read → compare → unlink runs under the same per-key lock as every other
    # tracking write, so a concurrent CAS cannot slip a new revision between the
    # check and the unlink (issue #230, ADR-0006); the batch serializer keeps a
    # running batch from interleaving with this delete (issue #223, ADR-0007).
    with _serialized_tracking_write(step), _LOCKS.for_key(clean_id):
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
    clean_id = _validated_tracking_id(tracking_id, "compare_and_swap_tracking_record")
    ensure_storage_layout(config)

    with _serialized_tracking_write("compare_and_swap_tracking_record"), _LOCKS.for_key(clean_id):
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


@contextmanager
def lock_tracking_record(tracking_id: str) -> Iterator[None]:
    """Hold the store + per-record critical section for one write (issue #247).

    The store lock is taken first (the order every other tracking writer uses),
    then the per-record ``RLock``; ``operation_repository`` takes its
    per-operation lock inside.  Nested record writes re-enter both, so the whole
    bind + pointer write + execution gate is one critical section in this
    process, and it is released before any external call.  A crash still leaves
    either both writes or the recoverable operation-without-pointer residue.
    """
    clean_id = _validated_tracking_id(tracking_id, "lock_tracking_record")
    _BATCH_STATE.external_write_id = clean_id
    try:
        # The store lock (batch exclusion) is taken before the per-record lock;
        # #247's order is unchanged.  ``_serialized_tracking_write`` reads the
        # record published above to decide whether this write conflicts.  The
        # intent is published only after that gate, so a write queued behind a
        # batch never blocks the batch that is already holding the lock.
        with (
            _serialized_tracking_write("lock_tracking_record"),
            _external_write_intent(),
            _LOCKS.for_key(clean_id),
        ):
            yield
    finally:
        _BATCH_STATE.external_write_id = None


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
    "batch_conflicts_with",
    "note_request_storage_dirs",
    "tracking_batch_lease",
    "tracking_batch_scope",
    "TrackingListResult",
    "compare_and_swap_tracking_record",
    "delete_tracking_record",
    "ensure_tracking_record",
    "list_tracking_records",
    "load_tracking_record",
    "lock_tracking_record",
]
