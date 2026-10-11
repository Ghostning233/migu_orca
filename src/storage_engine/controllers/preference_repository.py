from __future__ import annotations

import json
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
from shared.sensitive_values import contains_sensitive_value
from storage_engine.controllers.storage_config import (
    StorageConfig,
    ensure_storage_layout,
)
from storage_engine.controllers.storage_primitives import (
    is_relative_to,
    write_text_atomic,
)

#: Single-user default preference file inside ``<storage>/preferences``.
PREFERENCES_FILENAME = "user_preferences.json"
PREFERENCES_VERSION = 1

#: Maximum lengths for user-supplied preference strings. These keep the saved
#: JSON bounded and are enforced by ``validate_preferences`` on both save and
#: load, so an oversized value can never round-trip through the Web API.
MAX_SUBTITLE_GROUP_NAME_LENGTH = 100
MAX_FILTER_RULE_LENGTH = 500
MAX_NAMING_TEMPLATE_LENGTH = 200

#: Allowed keys in a Web API save payload. Unknown fields are rejected so the
#: API only ever accepts the defined non-sensitive preference contract.
_PREFERENCE_TOP_LEVEL_FIELDS = frozenset(
    {"version", "subtitle_groups", "filter_defaults", "naming", "search"}
)
_SUBTITLE_GROUP_FIELDS = frozenset({"preferred", "excluded", "fallback"})
_FILTER_DEFAULT_FIELDS = frozenset(
    {"must_contain", "must_not_contain", "use_regex", "case_sensitive"}
)
_NAMING_FIELDS = frozenset({"strategy", "template"})
_SEARCH_FIELDS = frozenset({"reuse_explicit_corrections"})

# Sensitive-content markers. A preference field may never hold an endpoint,
# token, cookie, Authorization header, magnet, raw HTML/RSS, raw response
# body, or local absolute path. Word-boundary keywords follow the queue
# sanitizer's token-word list so legitimate values like "1080p" or "喵萌"
# are never rejected.
def default_user_preferences() -> VersionedUserPreference:
    """Return the safe non-sensitive default preferences.

    Used when the local preference file is missing, so callers always get a
    usable (empty) preference set instead of an error.
    """
    return VersionedUserPreference()


def validate_preferences(
    preferences: VersionedUserPreference,
    *,
    failed_step: str = "save_user_preferences",
) -> None:
    """Validate that a preference set is legal and non-sensitive.

    Raises a Chinese ``validation_error`` when a field has the wrong type,
    uses an unsupported enum value, contains a sensitive external value, holds
    an empty subtitle-group entry, repeats a subtitle group, or exceeds the
    bounded string length.
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
        max_length=MAX_SUBTITLE_GROUP_NAME_LENGTH,
    )
    _validate_string_list(
        subtitle_groups.excluded,
        "subtitle_groups.excluded",
        failed_step,
        max_length=MAX_SUBTITLE_GROUP_NAME_LENGTH,
    )
    _validate_enum(
        subtitle_groups.fallback,
        SUBTITLE_GROUP_FALLBACKS,
        "subtitle_groups.fallback",
        failed_step,
    )
    _validate_no_duplicates(
        subtitle_groups.preferred, "subtitle_groups.preferred", failed_step
    )
    _validate_no_duplicates(
        subtitle_groups.excluded, "subtitle_groups.excluded", failed_step
    )
    _validate_no_overlap(
        subtitle_groups.preferred,
        subtitle_groups.excluded,
        failed_step,
    )

    filter_defaults = preferences.filter_defaults
    if not isinstance(filter_defaults, FilterDefaults):
        _raise_validation(failed_step, "filter_defaults", "filter_defaults 结构无效")
    _validate_string(
        filter_defaults.must_contain,
        "filter_defaults.must_contain",
        failed_step,
        max_length=MAX_FILTER_RULE_LENGTH,
    )
    _validate_string(
        filter_defaults.must_not_contain,
        "filter_defaults.must_not_contain",
        failed_step,
        max_length=MAX_FILTER_RULE_LENGTH,
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
    _validate_string(
        naming.template,
        "naming.template",
        failed_step,
        max_length=MAX_NAMING_TEMPLATE_LENGTH,
        # Naming templates legitimately contain relative path separators
        # (e.g. "TV/{title}/Season {season}"); only absolute paths / drives /
        # URLs / keywords are rejected.
        allow_relative_paths=True,
    )

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
    try:
        write_text_atomic(preferences_path, payload)
    except OSError as exc:
        raise Stage1Error(
            "storage_error",
            "保存用户偏好 JSON 失败",
            "save_user_preferences",
            {"directory": config.preferences_dir.name},
        ) from exc

    return {
        "storage": "local_json",
        "directory": config.preferences_dir.name,
        "filename": preferences_path.name,
        "version": preferences.version,
    }


def serialize_preferences(preferences: VersionedUserPreference) -> dict[str, Any]:
    """Return the public API-safe preference dict.

    Mirrors the persisted JSON shape exactly and only ever carries the defined
    non-sensitive preference fields; endpoint/token/cookie/Authorization/raw
    HTML-RSS/magnet values are rejected before save and re-validated on load.
    """
    return _preferences_to_dict(preferences)


def build_preferences_from_api(
    data: Any,
    *,
    failed_step: str = "save_user_preferences",
) -> VersionedUserPreference:
    """Build a preference model from a Web API save payload.

    Only the defined non-sensitive fields are accepted: unknown top-level or
    section keys raise a Chinese ``validation_error``. Missing sections default
    (so a partial save or an explicit ``{}`` reset-to-defaults is legal), and
    the built model is passed through ``validate_preferences`` so wrong types,
    illegal enums, empty/duplicate subtitle groups, sensitive values, and
    oversized strings are all rejected with the same Chinese envelope.
    """
    if not isinstance(data, dict):
        _raise_validation(failed_step, "preferences", "偏好配置必须是对象")
    _reject_unknown_fields(
        data, _PREFERENCE_TOP_LEVEL_FIELDS, "preferences", failed_step
    )

    version = data.get("version", PREFERENCES_VERSION)

    subtitle_groups_data = data.get("subtitle_groups")
    if subtitle_groups_data is None:
        subtitle_groups = SubtitleGroupPreference()
    else:
        if not isinstance(subtitle_groups_data, dict):
            _raise_validation(
                failed_step, "subtitle_groups", "subtitle_groups 必须是对象"
            )
        _reject_unknown_fields(
            subtitle_groups_data,
            _SUBTITLE_GROUP_FIELDS,
            "subtitle_groups",
            failed_step,
        )
        subtitle_groups = SubtitleGroupPreference(
            preferred=subtitle_groups_data.get("preferred", []),
            excluded=subtitle_groups_data.get("excluded", []),
            fallback=subtitle_groups_data.get("fallback", "next_preferred"),
        )

    filter_data = data.get("filter_defaults")
    if filter_data is None:
        filter_defaults = FilterDefaults()
    else:
        if not isinstance(filter_data, dict):
            _raise_validation(
                failed_step, "filter_defaults", "filter_defaults 必须是对象"
            )
        _reject_unknown_fields(
            filter_data, _FILTER_DEFAULT_FIELDS, "filter_defaults", failed_step
        )
        filter_defaults = FilterDefaults(
            must_contain=filter_data.get("must_contain", ""),
            must_not_contain=filter_data.get("must_not_contain", ""),
            use_regex=filter_data.get("use_regex", False),
            case_sensitive=filter_data.get("case_sensitive", False),
        )

    naming_data = data.get("naming")
    if naming_data is None:
        naming = NamingPreference()
    else:
        if not isinstance(naming_data, dict):
            _raise_validation(failed_step, "naming", "naming 必须是对象")
        _reject_unknown_fields(naming_data, _NAMING_FIELDS, "naming", failed_step)
        naming = NamingPreference(
            strategy=naming_data.get("strategy", "official_title_season"),
            template=naming_data.get("template", "{title}"),
        )

    search_data = data.get("search")
    if search_data is None:
        search = SearchPreference()
    else:
        if not isinstance(search_data, dict):
            _raise_validation(failed_step, "search", "search 必须是对象")
        _reject_unknown_fields(
            search_data, _SEARCH_FIELDS, "search", failed_step
        )
        search = SearchPreference(
            reuse_explicit_corrections=search_data.get(
                "reuse_explicit_corrections", True
            )
        )

    preferences = VersionedUserPreference(
        version=version,
        subtitle_groups=subtitle_groups,
        filter_defaults=filter_defaults,
        naming=naming,
        search=search,
    )
    validate_preferences(preferences, failed_step=failed_step)
    return preferences


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
    if not is_relative_to(candidate, preferences_root):
        raise Stage1Error(
            "storage_error",
            "偏好存储路径无效",
            "preference_repository",
            {"directory": config.preferences_dir.name},
        )
    return candidate


def _validate_string(
    value: Any,
    field: str,
    failed_step: str,
    *,
    max_length: int | None = None,
    allow_relative_paths: bool = False,
) -> None:
    if not isinstance(value, str):
        _raise_validation(failed_step, field, f"{field} 必须是字符串")
    if contains_sensitive_value(value, allow_relative_paths=allow_relative_paths):
        _raise_validation(failed_step, field, f"{field} 包含不允许的敏感内容")
    if max_length is not None and len(value) > max_length:
        _raise_validation(
            failed_step, field, f"{field} 长度不能超过 {max_length} 个字符"
        )


def _validate_string_list(
    value: Any,
    field: str,
    failed_step: str,
    *,
    max_length: int | None = None,
) -> None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        _raise_validation(failed_step, field, f"{field} 必须是字符串数组")
    for item in value:
        if not item.strip():
            _raise_validation(failed_step, field, f"{field} 不能包含空字符串")
        if contains_sensitive_value(item):
            _raise_validation(failed_step, field, f"{field} 包含不允许的敏感内容")
        if max_length is not None and len(item) > max_length:
            _raise_validation(
                failed_step, field, f"{field} 长度不能超过 {max_length} 个字符"
            )


def _validate_bool(value: Any, field: str, failed_step: str) -> None:
    if not isinstance(value, bool):
        _raise_validation(failed_step, field, f"{field} 必须是布尔值")


def _validate_enum(value: Any, allowed: tuple[str, ...], field: str, failed_step: str) -> None:
    if not isinstance(value, str) or value not in allowed:
        _raise_validation(failed_step, field, f"{field} 不是合法枚举值")


def _validate_no_duplicates(items: list[str], field: str, failed_step: str) -> None:
    seen: set[str] = set()
    for item in items:
        if item in seen:
            _raise_validation(failed_step, field, f"{field} 不能包含重复字幕组")
        seen.add(item)


def _validate_no_overlap(
    preferred: list[str],
    excluded: list[str],
    failed_step: str,
) -> None:
    overlap = set(preferred) & set(excluded)
    if overlap:
        _raise_validation(
            failed_step,
            "subtitle_groups",
            "字幕组不能同时出现在偏好与排除列表",
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


__all__ = [
    "PREFERENCES_FILENAME",
    "PREFERENCES_VERSION",
    "MAX_SUBTITLE_GROUP_NAME_LENGTH",
    "MAX_FILTER_RULE_LENGTH",
    "MAX_NAMING_TEMPLATE_LENGTH",
    "build_preferences_from_api",
    "default_user_preferences",
    "load_user_preferences",
    "save_user_preferences",
    "serialize_preferences",
    "validate_preferences",
]
