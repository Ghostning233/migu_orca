from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from shared.errors import Stage1Error
from shared.models import (
    NAMING_STRATEGIES,
    SUBTITLE_GROUP_FALLBACKS,
    FilterDefaults,
    NamingPreference,
    SearchPreference,
    SubtitleGroupPreference,
    VersionedUserPreference,
)
from storage_engine.controllers.storage_config import (
    StorageConfig,
    ensure_storage_layout,
)

#: Single-user default preference file inside ``<storage>/preferences``.
PREFERENCES_FILENAME = "user_preferences.json"
PREFERENCES_VERSION = 1

# Sensitive-content markers. A preference field may never hold an endpoint,
# token, cookie, Authorization header, magnet, raw HTML/RSS, raw response
# body, or local absolute path. Word-boundary keywords follow the queue
# sanitizer's token-word list so legitimate values like "1080p" or "喵萌"
# are never rejected.
_SENSITIVE_KEYWORDS = re.compile(
    r"(?i)\b(?:token|secret|cookie|authorization|password|passwd|bearer|"
    r"username|sid|session|endpoint|api_key|apikey|rss_url|raw_html|raw_rss|"
    r"response_body|request_body|magnet)\b"
)
_URL_RE = re.compile(r"https?://[^\s<>'\"]+")
_MAGNET_RE = re.compile(r"magnet:\?[^\s<>'\"]*", re.IGNORECASE)
_ABSOLUTE_PATH_RE = re.compile(r"(?<!\w)(?:/[^\s<>'\"]+)+")
_FILE_SCHEME_RE = re.compile(r"file://", re.IGNORECASE)
_WINDOWS_DRIVE_RE = re.compile(r"(?i)\b[a-z]:[\\/]")
_MARKUP_RE = re.compile(
    r"<\s*(?:html|rss|xml|svg|script|body|!doctype)\b", re.IGNORECASE
)
_SENSITIVE_KEY_VALUE_RE = re.compile(
    r"(?i)\b(?:token|secret|cookie|authorization|password|passwd|bearer|"
    r"username|sid|session|endpoint|rss_url)\s*[=:]\s*[^\s,;]+"
)


def default_user_preferences() -> VersionedUserPreference:
    """Return the safe non-sensitive default preferences.

    Used when the local preference file is missing, so callers always get a
    usable (empty) preference set instead of an error.
    """
    return VersionedUserPreference()


def contains_sensitive_value(text: str) -> bool:
    """Return True when ``text`` looks like a sensitive external value."""
    if _URL_RE.search(text):
        return True
    if _MAGNET_RE.search(text):
        return True
    if _ABSOLUTE_PATH_RE.search(text):
        return True
    if _FILE_SCHEME_RE.search(text):
        return True
    if _WINDOWS_DRIVE_RE.search(text):
        return True
    if _MARKUP_RE.search(text):
        return True
    if _SENSITIVE_KEY_VALUE_RE.search(text):
        return True
    if _SENSITIVE_KEYWORDS.search(text):
        return True
    return False


def validate_preferences(
    preferences: VersionedUserPreference,
    *,
    failed_step: str = "save_user_preferences",
) -> None:
    """Validate that a preference set is legal and non-sensitive.

    Raises a Chinese ``validation_error`` when a field has the wrong type,
    uses an unsupported enum value, or contains a sensitive external value.
    """
    if not isinstance(preferences.version, int) or preferences.version < 1:
        _raise_validation(
            failed_step, "version", "preferences.version 必须是正整数"
        )

    subtitle_groups = preferences.subtitle_groups
    if not isinstance(subtitle_groups, SubtitleGroupPreference):
        _raise_validation(failed_step, "subtitle_groups", "subtitle_groups 结构无效")
    _validate_string_list(
        subtitle_groups.preferred,
        "subtitle_groups.preferred",
        failed_step,
    )
    _validate_string_list(
        subtitle_groups.excluded,
        "subtitle_groups.excluded",
        failed_step,
    )
    _validate_enum(
        subtitle_groups.fallback,
        SUBTITLE_GROUP_FALLBACKS,
        "subtitle_groups.fallback",
        failed_step,
    )

    filter_defaults = preferences.filter_defaults
    if not isinstance(filter_defaults, FilterDefaults):
        _raise_validation(failed_step, "filter_defaults", "filter_defaults 结构无效")
    _validate_string(filter_defaults.must_contain, "filter_defaults.must_contain", failed_step)
    _validate_string(
        filter_defaults.must_not_contain,
        "filter_defaults.must_not_contain",
        failed_step,
    )
    _validate_bool(filter_defaults.use_regex, "filter_defaults.use_regex", failed_step)
    _validate_bool(
        filter_defaults.case_sensitive,
        "filter_defaults.case_sensitive",
        failed_step,
    )

    naming = preferences.naming
    if not isinstance(naming, NamingPreference):
        _raise_validation(failed_step, "naming", "naming 结构无效")
    _validate_enum(naming.strategy, NAMING_STRATEGIES, "naming.strategy", failed_step)
    _validate_string(naming.template, "naming.template", failed_step)

    search = preferences.search
    if not isinstance(search, SearchPreference):
        _raise_validation(failed_step, "search", "search 结构无效")
    _validate_bool(
        search.reuse_explicit_corrections,
        "search.reuse_explicit_corrections",
        failed_step,
    )


def load_user_preferences(config: StorageConfig) -> VersionedUserPreference:
    """Load the saved user preferences, returning safe defaults when absent.

    Missing files return ``default_user_preferences()``; damaged JSON raises a
    stable ``storage_json_error``; old-version files (missing ``version``,
    legacy ``filter_rule``/``subtitle_group_priority`` shapes) are read into
    the current model with defaults for missing sections.
    """
    preferences_path = _preferences_path(config)
    if not preferences_path.exists():
        return default_user_preferences()

    try:
        loaded = json.loads(preferences_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise Stage1Error(
            "storage_json_error",
            "读取用户偏好 JSON 失败",
            "load_user_preferences",
            {"reason": exc.msg, "filename": preferences_path.name},
        ) from exc
    except OSError as exc:
        raise Stage1Error(
            "storage_error",
            "读取用户偏好 JSON 失败",
            "load_user_preferences",
            {"directory": config.preferences_dir.name},
        ) from exc

    preferences = _preferences_from_dict(loaded)
    validate_preferences(preferences, failed_step="load_user_preferences")
    return preferences


def save_user_preferences(
    config: StorageConfig,
    preferences: VersionedUserPreference,
) -> dict[str, Any]:
    """Persist user preferences with an atomic temp-file write.

    The preference file name is fixed (never derived from user input), so an
    illegal batch/request value can never traverse out of the preferences
    directory. Sensitive or illegal fields are rejected before writing.
    """
    validate_preferences(preferences, failed_step="save_user_preferences")
    preferences_path = _preferences_path(config)
    ensure_storage_layout(config)

    payload = (
        json.dumps(
            _preferences_to_dict(preferences), ensure_ascii=False, indent=2
        )
        + "\n"
    )
    temp_path = preferences_path.with_name(PREFERENCES_FILENAME + ".tmp")
    try:
        temp_path.write_text(payload, encoding="utf-8")
        os.replace(temp_path, preferences_path)
    except OSError as exc:
        raise Stage1Error(
            "storage_error",
            "保存用户偏好 JSON 失败",
            "save_user_preferences",
            {"directory": config.preferences_dir.name},
        ) from exc
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

    return {
        "storage": "local_json",
        "directory": config.preferences_dir.name,
        "filename": preferences_path.name,
        "version": preferences.version,
    }


def _preferences_to_dict(preferences: VersionedUserPreference) -> dict[str, Any]:
    return {
        "version": preferences.version,
        "subtitle_groups": {
            "preferred": list(preferences.subtitle_groups.preferred),
            "excluded": list(preferences.subtitle_groups.excluded),
            "fallback": preferences.subtitle_groups.fallback,
        },
        "filter_defaults": {
            "must_contain": preferences.filter_defaults.must_contain,
            "must_not_contain": preferences.filter_defaults.must_not_contain,
            "use_regex": preferences.filter_defaults.use_regex,
            "case_sensitive": preferences.filter_defaults.case_sensitive,
        },
        "naming": {
            "strategy": preferences.naming.strategy,
            "template": preferences.naming.template,
        },
        "search": {
            "reuse_explicit_corrections": preferences.search.reuse_explicit_corrections,
        },
    }


def _preferences_from_dict(data: Any) -> VersionedUserPreference:
    if not isinstance(data, dict):
        raise Stage1Error(
            "storage_json_error",
            "用户偏好 JSON 必须是对象",
            "load_user_preferences",
        )

    version = data.get("version", PREFERENCES_VERSION)
    if not isinstance(version, int) or version < 1:
        version = PREFERENCES_VERSION

    subtitle_groups_data = data.get("subtitle_groups")
    if isinstance(subtitle_groups_data, dict):
        preferred = _list_from_dict(
            subtitle_groups_data.get("preferred", []), "subtitle_groups.preferred"
        )
        excluded = _list_from_dict(
            subtitle_groups_data.get("excluded", []), "subtitle_groups.excluded"
        )
        fallback = subtitle_groups_data.get("fallback", "next_preferred")
    else:
        # Legacy M08 shape: a flat subtitle_group_priority list.
        legacy_priority = data.get("subtitle_group_priority", [])
        preferred = _list_from_dict(legacy_priority, "subtitle_group_priority")
        excluded: list[str] = []
        fallback = "next_preferred"
    if not isinstance(fallback, str):
        fallback = "next_preferred"
    subtitle_groups = SubtitleGroupPreference(
        preferred=preferred,
        excluded=excluded,
        fallback=fallback,
    )

    filter_data = data.get("filter_defaults")
    if not isinstance(filter_data, dict):
        # Legacy M08 shape: a flat filter_rule object.
        filter_data = data.get("filter_rule")
    if isinstance(filter_data, dict):
        must_contain = _str_from_dict(filter_data.get("must_contain", ""), "must_contain")
        must_not_contain = _str_from_dict(
            filter_data.get("must_not_contain", ""), "must_not_contain"
        )
        use_regex = _bool_from_dict(filter_data.get("use_regex", False), "use_regex")
        case_sensitive = _bool_from_dict(
            filter_data.get("case_sensitive", False), "case_sensitive"
        )
    else:
        must_contain = ""
        must_not_contain = ""
        use_regex = False
        case_sensitive = False
    filter_defaults = FilterDefaults(
        must_contain=must_contain,
        must_not_contain=must_not_contain,
        use_regex=use_regex,
        case_sensitive=case_sensitive,
    )

    naming_data = data.get("naming")
    if isinstance(naming_data, dict):
        strategy = _str_from_dict(
            naming_data.get("strategy", "official_title_season"), "naming.strategy"
        )
        template = _str_from_dict(naming_data.get("template", "{title}"), "naming.template")
    else:
        strategy = "official_title_season"
        template = "{title}"
    naming = NamingPreference(strategy=strategy, template=template)

    search_data = data.get("search")
    if isinstance(search_data, dict):
        reuse = _bool_from_dict(
            search_data.get("reuse_explicit_corrections", True),
            "search.reuse_explicit_corrections",
        )
    else:
        reuse = True
    search = SearchPreference(reuse_explicit_corrections=reuse)

    return VersionedUserPreference(
        version=version,
        subtitle_groups=subtitle_groups,
        filter_defaults=filter_defaults,
        naming=naming,
        search=search,
    )


def _list_from_dict(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise Stage1Error(
            "storage_json_error",
            f"{field} 必须是字符串数组",
            "load_user_preferences",
            {"field": field},
        )
    if not all(isinstance(item, str) for item in value):
        raise Stage1Error(
            "storage_json_error",
            f"{field} 必须是字符串数组",
            "load_user_preferences",
            {"field": field},
        )
    return list(value)


def _str_from_dict(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise Stage1Error(
            "storage_json_error",
            f"{field} 必须是字符串",
            "load_user_preferences",
            {"field": field},
        )
    return value


def _bool_from_dict(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise Stage1Error(
            "storage_json_error",
            f"{field} 必须是布尔值",
            "load_user_preferences",
            {"field": field},
        )
    return value


def _preferences_path(config: StorageConfig) -> Path:
    preferences_root = config.preferences_dir.resolve(strict=False)
    candidate = (config.preferences_dir / PREFERENCES_FILENAME).resolve(strict=False)
    if not _is_relative_to(candidate, preferences_root):
        raise Stage1Error(
            "storage_error",
            "偏好存储路径无效",
            "preference_repository",
            {"directory": config.preferences_dir.name},
        )
    return candidate


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _validate_string(value: Any, field: str, failed_step: str) -> None:
    if not isinstance(value, str):
        _raise_validation(failed_step, field, f"{field} 必须是字符串")
    if contains_sensitive_value(value):
        _raise_validation(failed_step, field, f"{field} 包含不允许的敏感内容")


def _validate_string_list(value: Any, field: str, failed_step: str) -> None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        _raise_validation(failed_step, field, f"{field} 必须是字符串数组")
    for item in value:
        if contains_sensitive_value(item):
            _raise_validation(failed_step, field, f"{field} 包含不允许的敏感内容")


def _validate_bool(value: Any, field: str, failed_step: str) -> None:
    if not isinstance(value, bool):
        _raise_validation(failed_step, field, f"{field} 必须是布尔值")


def _validate_enum(value: Any, allowed: tuple[str, ...], field: str, failed_step: str) -> None:
    if not isinstance(value, str) or value not in allowed:
        _raise_validation(failed_step, field, f"{field} 不是合法枚举值")


def _raise_validation(failed_step: str, field: str, message: str) -> None:
    raise Stage1Error(
        "validation_error",
        message,
        failed_step,
        {"field": field},
    )


__all__ = [
    "PREFERENCES_FILENAME",
    "PREFERENCES_VERSION",
    "contains_sensitive_value",
    "default_user_preferences",
    "load_user_preferences",
    "save_user_preferences",
    "validate_preferences",
]
