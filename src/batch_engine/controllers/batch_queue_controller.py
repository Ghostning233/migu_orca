"""Stage 20 batch pre-submission queue controller.

Pure functions over ``BatchSubmissionQueue`` / ``BatchQueueItem``. The
controller owns queue identity, idempotent enqueue (by ``request_id``), status
transitions, sanitized summary creation, and safe serialization so later
API/UI stories can reuse one queue contract. Auto Bangumi secrets (endpoint,
token, cookie, Authorization header), raw response bodies, full RSS URLs,
magnets, and local absolute paths must never reach a queue item: summaries are
sanitized on write and re-sanitized on serialization.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import re
from typing import Any, Callable
from uuid import uuid4

from batch_engine.models.queue import (
    BATCH_QUEUE_STATUS_FAILED,
    BATCH_QUEUE_STATUS_LABELS,
    BATCH_QUEUE_STATUS_READY_TO_SUBMIT,
    BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED,
    BATCH_QUEUE_STATUS_RETRYABLE,
    BATCH_QUEUE_STATUS_SUBMITTING,
    BATCH_QUEUE_STATUS_SUCCEEDED,
    BATCH_QUEUE_TRANSITIONS,
    BatchQueueItem,
    BatchSubmissionQueue,
)

IdFactory = Callable[[], str]
NowFactory = Callable[[], str]

#: Keys dropped from a summary before it becomes a queue item field.
SENSITIVE_SUMMARY_KEYS = (
    "token",
    "secret",
    "cookie",
    "authorization",
    "password",
    "passwd",
    "bearer",
    "endpoint",
    "rss_url",
    "raw_html",
    "raw_rss",
    "response_body",
    "request_body",
    "magnet",
)

_URL_RE = re.compile(r"https?://[^\s<>'\"]+")
_ABSOLUTE_PATH_RE = re.compile(r"(?<!\w)(?:/[^\s<>'\"]+)+")
_MAGNET_RE = re.compile(r"magnet:\?[^\s<>'\"]*", re.IGNORECASE)
_TOKEN_WORD_RE = re.compile(
    r"(?i)(token|secret|cookie|authorization|password|passwd|bearer|username|sid|session)"
)
# Redacts "key=value" / "key: value" pairs where the key names a sensitive
# value, so the secret value itself cannot survive inside a plain string.
_SENSITIVE_KEY_VALUE_RE = re.compile(
    r"(?i)\b(?:token|secret|cookie|authorization|password|passwd|bearer|"
    r"username|sid|session|endpoint|rss_url)\s*[=:]\s*[^\s,;]+"
)
# Redacts a sensitive keyword followed by a space-separated value (e.g.
# "Bearer abc123", "Authorization: Bearer xyz") — replacing only the keyword
# would leave the raw token value behind.
_SENSITIVE_WORD_VALUE_RE = re.compile(
    r"(?i)\b(?:token|secret|cookie|authorization|password|passwd|bearer|"
    r"username|sid|session)\s+[^\s,;'\"<>]+"
)


def create_submission_queue(
    batch_id: str,
    *,
    queue_id_factory: IdFactory | None = None,
    now_factory: NowFactory | None = None,
) -> BatchSubmissionQueue:
    """Create an empty pre-submission queue for an accepted batch."""
    clean_batch_id = _non_empty("batch_id", batch_id)
    now = _now(now_factory)
    return BatchSubmissionQueue(
        queue_id=_next_id("queue", queue_id_factory),
        batch_id=clean_batch_id,
        items=[],
        created_at=now,
        updated_at=now,
    )


def enqueue_item(
    queue: BatchSubmissionQueue,
    *,
    item_id: str,
    request_id: str,
    title: str,
    now_factory: NowFactory | None = None,
) -> BatchSubmissionQueue:
    """Add an accepted item to the queue.

    Idempotent by ``request_id``: if the queue already holds an item for the
    same ``request_id``, the queue is returned unchanged, so repeated batch
    accepts never create duplicate queue items.
    """
    clean_item_id = _non_empty("item_id", item_id)
    clean_request_id = _non_empty("request_id", request_id)
    clean_title = _non_empty("title", title)
    if _find_item(queue, clean_request_id) is not None:
        return queue

    now = _now(now_factory)
    item = BatchQueueItem(
        queue_id=queue.queue_id,
        batch_id=queue.batch_id,
        item_id=clean_item_id,
        request_id=clean_request_id,
        title=clean_title,
        created_at=now,
        updated_at=now,
    )
    return replace(queue, items=[*queue.items, item], updated_at=now)


def start_queue_item_submit(
    queue: BatchSubmissionQueue,
    request_id: str,
    *,
    now_factory: NowFactory | None = None,
) -> BatchSubmissionQueue:
    """Begin a submit attempt: move an item to SUBMITTING and increment attempts.

    Allowed from READY_TO_SUBMIT (first attempt) or FAILED/RETRYABLE (retry).
    """
    item = _required_item(queue, request_id)
    next_status = BATCH_QUEUE_STATUS_SUBMITTING
    _assert_transition(item.status, next_status)
    now = _now(now_factory)
    updated_item = replace(
        item,
        status=next_status,
        attempts=item.attempts + 1,
        updated_at=now,
    )
    return _replace_item(queue, updated_item, now=now)


def complete_queue_item_submit(
    queue: BatchSubmissionQueue,
    request_id: str,
    status: str,
    *,
    ab_result_summary: Any = None,
    last_error: Any = None,
    now_factory: NowFactory | None = None,
) -> BatchSubmissionQueue:
    """Finish a submit attempt with a terminal-or-retryable result.

    ``status`` must be SUCCEEDED, FAILED, RETRYABLE, or
    RESULT_PERSIST_FAILED and the item must be SUBMITTING. On SUCCEEDED the
    sanitized ``ab_result_summary`` is stored and ``last_error`` is cleared; on
    FAILED/RETRYABLE/RESULT_PERSIST_FAILED the sanitized ``last_error`` is
    stored and ``ab_result_summary`` is cleared.
    """
    if status not in {
        BATCH_QUEUE_STATUS_SUCCEEDED,
        BATCH_QUEUE_STATUS_FAILED,
        BATCH_QUEUE_STATUS_RETRYABLE,
        BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED,
    }:
        raise ValueError(f"invalid queue result status: {status}")
    item = _required_item(queue, request_id)
    _assert_transition(item.status, status)

    now = _now(now_factory)
    if status == BATCH_QUEUE_STATUS_SUCCEEDED:
        updated_item = replace(
            item,
            status=status,
            ab_result_summary=sanitize_queue_summary(ab_result_summary),
            last_error=None,
            updated_at=now,
        )
    else:
        updated_item = replace(
            item,
            status=status,
            last_error=sanitize_queue_summary(last_error),
            ab_result_summary=None,
            updated_at=now,
        )
    return _replace_item(queue, updated_item, now=now)


def mark_queue_item_failed(
    queue: BatchSubmissionQueue,
    request_id: str,
    *,
    status: str = BATCH_QUEUE_STATUS_FAILED,
    last_error: Any = None,
    now_factory: NowFactory | None = None,
) -> BatchSubmissionQueue:
    """Mark a READY item FAILED or RETRYABLE without a submit attempt.

    Used when pre-submit validation rejects an item (e.g. its Request is no
    longer ACCEPTED) so the rest of the batch can keep processing.
    """
    item = _required_item(queue, request_id)
    if status not in {
        BATCH_QUEUE_STATUS_FAILED,
        BATCH_QUEUE_STATUS_RETRYABLE,
    }:
        raise ValueError(f"invalid pre-submit failure status: {status}")
    if item.status != BATCH_QUEUE_STATUS_READY_TO_SUBMIT:
        raise ValueError(
            f"cannot mark a {item.status} item as pre-submit failed; "
            "only READY_TO_SUBMIT items can be rejected before submit"
        )

    now = _now(now_factory)
    updated_item = replace(
        item,
        status=status,
        last_error=sanitize_queue_summary(last_error),
        ab_result_summary=None,
        updated_at=now,
    )
    return _replace_item(queue, updated_item, now=now)


def mark_queue_item_retry_failed(
    queue: BatchSubmissionQueue,
    request_id: str,
    *,
    status: str = BATCH_QUEUE_STATUS_FAILED,
    last_error: Any = None,
    now_factory: NowFactory | None = None,
) -> BatchSubmissionQueue:
    """Record a failed retry pre-submit check without a submit attempt.

    Only a FAILED or RETRYABLE item may be updated here: when a single-item
    retry finds its Request no longer ACCEPTED (missing/deleted/cancelled), the
    item stays FAILED/RETRYABLE with a fresh sanitized ``last_error`` and its
    ``attempts`` is NOT incremented (no Auto Bangumi submit was attempted).
    """
    item = _required_item(queue, request_id)
    if status not in {
        BATCH_QUEUE_STATUS_FAILED,
        BATCH_QUEUE_STATUS_RETRYABLE,
    }:
        raise ValueError(f"invalid retry failure status: {status}")
    if item.status not in {
        BATCH_QUEUE_STATUS_FAILED,
        BATCH_QUEUE_STATUS_RETRYABLE,
    }:
        raise ValueError(
            f"cannot update a {item.status} item after a failed retry; "
            "only FAILED/RETRYABLE items can be retried"
        )

    now = _now(now_factory)
    updated_item = replace(
        item,
        status=status,
        last_error=sanitize_queue_summary(last_error),
        ab_result_summary=None,
        updated_at=now,
    )
    return _replace_item(queue, updated_item, now=now)


def serialize_queue(queue: BatchSubmissionQueue) -> dict[str, Any]:
    """Serialize a queue with only non-sensitive, public fields.

    Every item is re-sanitized defensively on the way out, so even a directly
    constructed item with raw values can never leak secrets through the queue
    serialization boundary.
    """
    return {
        "queue_id": queue.queue_id,
        "batch_id": queue.batch_id,
        "created_at": queue.created_at,
        "updated_at": queue.updated_at,
        "items": [serialize_queue_item(item) for item in queue.items],
    }


def serialize_queue_item(item: BatchQueueItem) -> dict[str, Any]:
    return {
        "queue_id": item.queue_id,
        "batch_id": item.batch_id,
        "item_id": item.item_id,
        "request_id": item.request_id,
        "title": sanitize_queue_summary(item.title) or item.title,
        "status": item.status,
        "status_label": BATCH_QUEUE_STATUS_LABELS.get(item.status, item.status),
        "attempts": item.attempts,
        "last_error": sanitize_queue_summary(item.last_error),
        "ab_result_summary": sanitize_queue_summary(item.ab_result_summary),
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def queue_to_storage_dict(queue: BatchSubmissionQueue) -> dict[str, Any]:
    """Lossless round-trip serialization used for queue persistence.

    Unlike ``serialize_queue`` (the public API boundary), this keeps the raw
    queue fields so a persisted queue can be reconstructed exactly. The queue
    dataclass only holds non-sensitive public fields, and ``last_error`` /
    ``ab_result_summary`` are already sanitized one-line summaries, so writing
    the full queue never persists Auto Bangumi secrets.
    """
    return {
        "queue_id": queue.queue_id,
        "batch_id": queue.batch_id,
        "created_at": queue.created_at,
        "updated_at": queue.updated_at,
        "items": [queue_item_to_storage_dict(item) for item in queue.items],
    }


def queue_item_to_storage_dict(item: BatchQueueItem) -> dict[str, Any]:
    return {
        "queue_id": item.queue_id,
        "batch_id": item.batch_id,
        "item_id": item.item_id,
        "request_id": item.request_id,
        "title": item.title,
        "status": item.status,
        "attempts": item.attempts,
        "last_error": item.last_error,
        "ab_result_summary": item.ab_result_summary,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def queue_from_storage_dict(data: Any) -> BatchSubmissionQueue:
    """Reconstruct a queue from a storage dict written by ``queue_to_storage_dict``.

    Invalid shapes raise ``ValueError`` so callers can map them to a stable
    storage error (the queue repository does this on load).
    """
    if not isinstance(data, dict):
        raise ValueError("queue storage JSON must be an object")
    items_data = data.get("items")
    if not isinstance(items_data, list):
        raise ValueError("queue storage items must be a list")
    return BatchSubmissionQueue(
        queue_id=str(data.get("queue_id") or ""),
        batch_id=str(data.get("batch_id") or ""),
        items=[queue_item_from_storage_dict(item) for item in items_data],
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
    )


def queue_item_from_storage_dict(data: Any) -> BatchQueueItem:
    if not isinstance(data, dict):
        raise ValueError("queue item storage JSON must be an object")
    status = str(data.get("status") or BATCH_QUEUE_STATUS_READY_TO_SUBMIT)
    if status not in _KNOWN_QUEUE_STATUSES:
        # A corrupted/poisoned queue file with an unknown status would silently
        # become a "ghost item" that every submit/retry/recover skips; reject it
        # as invalid storage so the caller maps it to storage_json_error.
        raise ValueError(f"invalid queue item status: {status}")
    return BatchQueueItem(
        queue_id=str(data.get("queue_id") or ""),
        batch_id=str(data.get("batch_id") or ""),
        item_id=str(data.get("item_id") or ""),
        request_id=str(data.get("request_id") or ""),
        title=str(data.get("title") or ""),
        status=status,
        attempts=int(data.get("attempts") or 0),
        last_error=_optional_str(data.get("last_error")),
        ab_result_summary=_optional_str(data.get("ab_result_summary")),
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
    )


_KNOWN_QUEUE_STATUSES = frozenset(
    {
        BATCH_QUEUE_STATUS_READY_TO_SUBMIT,
        BATCH_QUEUE_STATUS_SUBMITTING,
        BATCH_QUEUE_STATUS_SUCCEEDED,
        BATCH_QUEUE_STATUS_FAILED,
        BATCH_QUEUE_STATUS_RETRYABLE,
        BATCH_QUEUE_STATUS_RESULT_PERSIST_FAILED,
    }
)


def sanitize_queue_summary(value: Any, *, fallback: str | None = None) -> str | None:
    """Convert a raw result/error value into a sanitized one-line summary.

    The summary drops sensitive keys and redacts URLs, magnets, local absolute
    paths, raw HTML/RSS content, and token-like words so Auto Bangumi secrets,
    raw response bodies, full RSS URLs, and other sensitive values never become
    queue item fields.
    """
    sanitized = _strip_sensitive(value)
    if sanitized is None:
        return fallback
    text = _flatten_summary(sanitized)
    if not text:
        return fallback
    return text


def _strip_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if any(term in key_text.lower() for term in SENSITIVE_SUMMARY_KEYS):
                continue
            stripped = _strip_sensitive(item)
            if stripped is not None:
                sanitized[key_text] = stripped
        return sanitized or None
    if isinstance(value, list):
        items = [_strip_sensitive(item) for item in value]
        items = [item for item in items if item is not None]
        return items or None
    if isinstance(value, tuple):
        items = [_strip_sensitive(item) for item in value]
        items = [item for item in items if item is not None]
        return items or None
    if isinstance(value, str):
        return _sanitize_string_value(value) or None
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    return value


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _sanitize_string_value(value: str) -> str:
    text = _MAGNET_RE.sub("[redacted]", value)
    text = _URL_RE.sub("[redacted-url]", text)
    # Keyword + space-separated value FIRST (so "Bearer abc123" is swallowed as
    # one unit), then "key=value"/"key: value" pairs — the reverse order would
    # let the pair regex consume the keyword and leave the raw value behind.
    text = _SENSITIVE_WORD_VALUE_RE.sub("[redacted]", text)
    text = _SENSITIVE_KEY_VALUE_RE.sub("[redacted]", text)
    text = _ABSOLUTE_PATH_RE.sub("[redacted-path]", text)
    if "<rss" in text.lower() or "<html" in text.lower():
        return "[redacted-content]"
    if _TOKEN_WORD_RE.search(text):
        return _TOKEN_WORD_RE.sub("[redacted]", text)
    return text


def _flatten_summary(value: Any) -> str:
    if isinstance(value, dict):
        parts: list[str] = []
        for key, item in sorted(value.items()):
            rendered = _flatten_summary(item)
            if rendered:
                parts.append(f"{key}={rendered}")
        return "; ".join(parts)
    if isinstance(value, list):
        rendered_items = [_flatten_summary(item) for item in value]
        return ", ".join(part for part in rendered_items if part)
    if isinstance(value, str):
        return value.strip()
    return str(value)


def _required_item(
    queue: BatchSubmissionQueue,
    request_id: str,
) -> BatchQueueItem:
    item = _find_item(queue, request_id)
    if item is None:
        raise ValueError("unknown request_id")
    return item


def _find_item(
    queue: BatchSubmissionQueue,
    request_id: str,
) -> BatchQueueItem | None:
    for item in queue.items:
        if item.request_id == request_id:
            return item
    return None


def _replace_item(
    queue: BatchSubmissionQueue,
    item: BatchQueueItem,
    *,
    now: str | None,
) -> BatchSubmissionQueue:
    replaced: list[BatchQueueItem] = []
    for existing in queue.items:
        if existing.request_id == item.request_id:
            replaced.append(item)
        else:
            replaced.append(existing)
    return replace(queue, items=replaced, updated_at=now)


def _assert_transition(current: str, next_status: str) -> None:
    allowed = BATCH_QUEUE_TRANSITIONS.get(current, frozenset())
    if next_status not in allowed:
        raise ValueError(f"invalid queue transition: {current} -> {next_status}")


def _non_empty(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _now(now_factory: NowFactory | None) -> str:
    if now_factory is None:
        return datetime.now(UTC).isoformat()
    value = now_factory()
    if not isinstance(value, str) or not value.strip():
        raise ValueError("now_factory must return a non-empty string")
    return value.strip()


def _next_id(prefix: str, factory: IdFactory | None) -> str:
    if factory is None:
        return f"{prefix}-{uuid4()}"
    value = factory()
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{prefix}_id must be a non-empty string")
    return value.strip()


__all__ = [
    "complete_queue_item_submit",
    "create_submission_queue",
    "enqueue_item",
    "mark_queue_item_failed",
    "mark_queue_item_retry_failed",
    "queue_from_storage_dict",
    "queue_item_from_storage_dict",
    "queue_item_to_storage_dict",
    "queue_to_storage_dict",
    "sanitize_queue_summary",
    "serialize_queue",
    "serialize_queue_item",
    "start_queue_item_submit",
]
