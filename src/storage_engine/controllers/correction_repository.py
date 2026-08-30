from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import Any

from shared.errors import Stage1Error
from shared.models import BangumiCorrectionMetadata, TitleCorrection
from storage_engine.controllers.preference_repository import contains_sensitive_value
from storage_engine.controllers.storage_config import (
    StorageConfig,
    ensure_storage_layout,
)

#: Single-user correction file inside ``<storage>/corrections``.
CORRECTIONS_FILENAME = "corrections.json"
CORRECTIONS_VERSION = 1

#: Maximum lengths for user-supplied correction strings. These keep the saved
#: JSON bounded and are enforced by ``validate_correction`` on both save and
#: load, so an oversized value can never round-trip through the Web API.
MAX_CORRECTION_TITLE_LENGTH = 200
MAX_CORRECTION_QUERY_LENGTH = 200
MAX_SEASON_HINT_LENGTH = 20

#: Allowed keys in a Web API correction payload. Unknown fields are rejected so
#: the API only ever accepts the defined non-sensitive correction contract.
_CORRECTION_FIELDS = frozenset(
    {"raw_title", "canonical_title", "season_hint", "bangumi_metadata", "query_correction"}
)
_BANGUMI_METADATA_FIELDS = frozenset({"bangumi_id", "title"})


def default_corrections() -> list[TitleCorrection]:
    """Return the safe empty correction list for a fresh storage."""
    return []


def load_corrections(config: StorageConfig) -> list[TitleCorrection]:
    """Load the saved user title corrections, returning ``[]`` when absent.

    Missing files return an empty list; damaged JSON raises a stable
    ``storage_json_error``. Only non-sensitive public correction fields are
    loaded (validated on load, so a poisoned on-disk file is rejected).
    """
    corrections_path = _corrections_path(config)
    if not corrections_path.exists():
        return default_corrections()

    try:
        loaded = json.loads(corrections_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise Stage1Error(
            "storage_json_error",
            "读取搜索修正 JSON 失败",
            "load_corrections",
            {"reason": exc.msg, "filename": corrections_path.name},
        ) from exc
    except OSError as exc:
        raise Stage1Error(
            "storage_error",
            "读取搜索修正 JSON 失败",
            "load_corrections",
            {"directory": config.corrections_dir.name},
        ) from exc

    entries = _corrections_list_from_dict(loaded)
    validate_corrections(entries, failed_step="load_corrections")
    return entries


def save_correction(
    config: StorageConfig,
    correction: TitleCorrection,
) -> dict[str, Any]:
    """Persist one title correction with an atomic temp-file write.

    Same-``raw_title`` duplicates use a latest-version strategy: the existing
    entry is replaced and moved to the end, so repeated corrections never grow
    the file. The total list is capped at ``MAX_STORED_CORRECTIONS`` (oldest
    entries are evicted first), so the correction store cannot grow unbounded.
    The correction file name is fixed (never derived from user input), so an
    illegal batch/request value can never traverse out of the corrections
    directory.
    """
    validate_correction(correction, failed_step="save_correction")
    corrections_path = _corrections_path(config)
    ensure_storage_layout(config)

    try:
        existing = load_corrections(config)
    except Stage1Error:
        # A damaged existing file must not silently lose data: fail the save
        # with the same stable Chinese envelope instead of overwriting it.
        raise
    merged = _merge_latest_by_raw_title(existing, correction)

    payload = (
        json.dumps(
            _corrections_to_dict(merged), ensure_ascii=False, indent=2
        )
        + "\n"
    )
    temp_path = corrections_path.with_name(CORRECTIONS_FILENAME + ".tmp")
    try:
        temp_path.write_text(payload, encoding="utf-8")
        os.replace(temp_path, corrections_path)
    except OSError as exc:
        raise Stage1Error(
            "storage_error",
            "保存搜索修正 JSON 失败",
            "save_correction",
            {"directory": config.corrections_dir.name},
        ) from exc
    finally:
        if temp_path.exists():
            with contextlib.suppress(OSError):
                temp_path.unlink()

    return {
        "storage": "local_json",
        "directory": config.corrections_dir.name,
        "filename": corrections_path.name,
        "count": len(merged),
    }


def validate_correction(
    correction: TitleCorrection,
    *,
    failed_step: str = "save_correction",
) -> None:
    """Validate that a single title correction is legal and non-sensitive.

    Raises a Chinese ``validation_error`` when a required field is missing,
    a field has the wrong type, an optional string is empty, a value contains
    a sensitive external marker, or a value exceeds the bounded length.
    """
    _validate_string(
        correction.raw_title,
        "raw_title",
        failed_step,
        max_length=MAX_CORRECTION_TITLE_LENGTH,
    )
    _validate_string(
        correction.canonical_title,
        "canonical_title",
        failed_step,
        max_length=MAX_CORRECTION_TITLE_LENGTH,
    )
    if correction.season_hint is not None:
        _validate_string(
            correction.season_hint,
            "season_hint",
            failed_step,
            max_length=MAX_SEASON_HINT_LENGTH,
        )
    if correction.query_correction is not None:
        _validate_string(
            correction.query_correction,
            "query_correction",
            failed_step,
            max_length=MAX_CORRECTION_QUERY_LENGTH,
        )
    bangumi = correction.bangumi_metadata
    if bangumi is not None:
        if not isinstance(bangumi, BangumiCorrectionMetadata):
            _raise_validation(failed_step, "bangumi_metadata", "bangumi_metadata 结构无效")
        if bangumi.bangumi_id is not None:
            _validate_string(
                bangumi.bangumi_id,
                "bangumi_metadata.bangumi_id",
                failed_step,
                max_length=MAX_CORRECTION_TITLE_LENGTH,
            )
        if bangumi.title is not None:
            _validate_string(
                bangumi.title,
                "bangumi_metadata.title",
                failed_step,
                max_length=MAX_CORRECTION_TITLE_LENGTH,
            )


def validate_corrections(
    corrections: list[TitleCorrection],
    *,
    failed_step: str = "load_corrections",
) -> None:
    """Validate a whole correction list on load."""
    if not isinstance(corrections, list) or not all(
        isinstance(item, TitleCorrection) for item in corrections
    ):
        raise Stage1Error(
            "storage_json_error",
            "搜索修正 JSON 必须是修正对象数组",
            failed_step,
        )
    for correction in corrections:
        validate_correction(correction, failed_step=failed_step)


def build_correction_from_api(
    data: Any,
    *,
    failed_step: str = "save_correction",
) -> TitleCorrection:
    """Build a title correction from a Web API save payload.

    Only the defined non-sensitive fields are accepted: unknown keys raise a
    Chinese ``validation_error``. The built model is passed through
    ``validate_correction`` so wrong types, missing required fields, sensitive
    values, and oversized strings are all rejected with the same envelope.
    """
    if not isinstance(data, dict):
        _raise_validation(failed_step, "correction", "修正内容必须是对象")
    _reject_unknown_fields(data, _CORRECTION_FIELDS, "correction", failed_step)

    raw_title = data.get("raw_title")
    canonical_title = data.get("canonical_title")
    season_hint = data.get("season_hint")
    bangumi_data = data.get("bangumi_metadata")
    query_correction = data.get("query_correction")

    bangumi_metadata: BangumiCorrectionMetadata | None = None
    if bangumi_data is not None:
        if not isinstance(bangumi_data, dict):
            _raise_validation(
                failed_step, "bangumi_metadata", "bangumi_metadata 必须是对象"
            )
        _reject_unknown_fields(
            bangumi_data, _BANGUMI_METADATA_FIELDS, "bangumi_metadata", failed_step
        )
        bangumi_metadata = BangumiCorrectionMetadata(
            bangumi_id=bangumi_data.get("bangumi_id"),
            title=bangumi_data.get("title"),
        )

    correction = TitleCorrection(
        raw_title=raw_title,
        canonical_title=canonical_title,
        season_hint=season_hint,
        bangumi_metadata=bangumi_metadata,
        query_correction=query_correction,
    )
    validate_correction(correction, failed_step=failed_step)
    return correction


def serialize_correction(correction: TitleCorrection) -> dict[str, Any]:
    """Return the public API-safe dict for one title correction."""
    return _correction_to_dict(correction)


def serialize_corrections(corrections: list[TitleCorrection]) -> list[dict[str, Any]]:
    """Return the public API-safe dict list for saved corrections."""
    return [serialize_correction(correction) for correction in corrections]


def _correction_to_dict(correction: TitleCorrection) -> dict[str, Any]:
    bangumi = correction.bangumi_metadata
    return {
        "raw_title": correction.raw_title,
        "canonical_title": correction.canonical_title,
        "season_hint": correction.season_hint,
        "bangumi_metadata": (
            {
                "bangumi_id": bangumi.bangumi_id,
                "title": bangumi.title,
            }
            if bangumi is not None
            else None
        ),
        "query_correction": correction.query_correction,
    }


def _corrections_to_dict(corrections: list[TitleCorrection]) -> dict[str, Any]:
    return {
        "version": CORRECTIONS_VERSION,
        "corrections": [_correction_to_dict(correction) for correction in corrections],
    }


def _corrections_list_from_dict(data: Any) -> list[TitleCorrection]:
    if not isinstance(data, dict):
        raise Stage1Error(
            "storage_json_error",
            "搜索修正 JSON 必须是对象",
            "load_corrections",
        )
    entries = data.get("corrections")
    if not isinstance(entries, list):
        raise Stage1Error(
            "storage_json_error",
            "搜索修正 JSON 必须是对象",
            "load_corrections",
        )
    corrections: list[TitleCorrection] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise Stage1Error(
                "storage_json_error",
                "搜索修正条目必须是对象",
                "load_corrections",
            )
        bangumi_data = entry.get("bangumi_metadata")
        bangumi_metadata: BangumiCorrectionMetadata | None = None
        if isinstance(bangumi_data, dict):
            bangumi_metadata = BangumiCorrectionMetadata(
                bangumi_id=_optional_str(bangumi_data.get("bangumi_id")),
                title=_optional_str(bangumi_data.get("title")),
            )
        corrections.append(
            TitleCorrection(
                raw_title=_str(entry.get("raw_title"), "raw_title"),
                canonical_title=_str(entry.get("canonical_title"), "canonical_title"),
                season_hint=_optional_str(entry.get("season_hint")),
                bangumi_metadata=bangumi_metadata,
                query_correction=_optional_str(entry.get("query_correction")),
            )
        )
    return corrections


def _merge_latest_by_raw_title(
    existing: list[TitleCorrection],
    correction: TitleCorrection,
) -> list[TitleCorrection]:
    from shared.models import MAX_STORED_CORRECTIONS

    merged = [item for item in existing if item.raw_title != correction.raw_title]
    merged.append(correction)
    if len(merged) > MAX_STORED_CORRECTIONS:
        merged = merged[-MAX_STORED_CORRECTIONS:]
    return merged


def _corrections_path(config: StorageConfig) -> Path:
    corrections_root = config.corrections_dir.resolve(strict=False)
    candidate = (config.corrections_dir / CORRECTIONS_FILENAME).resolve(strict=False)
    if not _is_relative_to(candidate, corrections_root):
        raise Stage1Error(
            "storage_error",
            "搜索修正存储路径无效",
            "correction_repository",
            {"directory": config.corrections_dir.name},
        )
    return candidate


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _validate_string(
    value: Any,
    field: str,
    failed_step: str,
    *,
    max_length: int | None = None,
) -> None:
    if not isinstance(value, str):
        _raise_validation(failed_step, field, f"{field} 必须是字符串")
    if not value.strip():
        _raise_validation(failed_step, field, f"{field} 不能为空")
    if contains_sensitive_value(value):
        _raise_validation(failed_step, field, f"{field} 包含不允许的敏感内容")
    if max_length is not None and len(value) > max_length:
        _raise_validation(
            failed_step, field, f"{field} 长度不能超过 {max_length} 个字符"
        )


def _reject_unknown_fields(
    data: dict[str, Any],
    allowed: frozenset[str],
    field: str,
    failed_step: str,
) -> None:
    unknown = sorted(set(data.keys()) - allowed)
    if unknown:
        _raise_validation(failed_step, field, f"{field} 包含未定义字段")


def _raise_validation(failed_step: str, field: str, message: str) -> None:
    raise Stage1Error(
        "validation_error",
        message,
        failed_step,
        {"field": field},
    )


def _str(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise Stage1Error(
            "storage_json_error",
            f"{field} 必须是字符串",
            "load_corrections",
            {"field": field},
        )
    return value


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise Stage1Error(
            "storage_json_error",
            "修正字段必须是字符串或 null",
            "load_corrections",
        )
    return value


__all__ = [
    "CORRECTIONS_FILENAME",
    "CORRECTIONS_VERSION",
    "MAX_CORRECTION_QUERY_LENGTH",
    "MAX_CORRECTION_TITLE_LENGTH",
    "MAX_SEASON_HINT_LENGTH",
    "build_correction_from_api",
    "default_corrections",
    "load_corrections",
    "save_correction",
    "serialize_correction",
    "serialize_corrections",
    "validate_correction",
    "validate_corrections",
]
