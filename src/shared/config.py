from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shared.errors import Stage1Error
from shared.models import FilterRule, UserPreference

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG_PATH = PROJECT_ROOT / "config/system/static_mikan_sources.json"
DEFAULT_USER_CONFIG_PATH = PROJECT_ROOT / "config/user/default_rules.json"


def _read_json(path: Path, failed_step: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage1Error(
            "config_error",
            f"无法读取 JSON 配置：{path}",
            failed_step,
            {"reason": str(exc)},
        ) from exc


def load_user_preference(path: Path = DEFAULT_USER_CONFIG_PATH) -> UserPreference:
    data = _read_json(path, "load_user_config")
    try:
        filter_data = data["filter_rule"]
        must_contain = filter_data["must_contain"]
        must_not_contain = filter_data["must_not_contain"]
        priority = data["subtitle_group_priority"]
    except (KeyError, TypeError) as exc:
        raise Stage1Error(
            "config_error",
            "用户配置缺少必要字段",
            "load_user_config",
        ) from exc

    if not isinstance(must_contain, str) or not isinstance(must_not_contain, str):
        raise Stage1Error(
            "config_error",
            "筛选规则必须是字符串",
            "load_user_config",
        )
    # 旧配置可能缺少 use_regex / case_sensitive，按默认 False 兼容加载。
    use_regex = filter_data.get("use_regex", False)
    case_sensitive = filter_data.get("case_sensitive", False)
    if not isinstance(use_regex, bool) or not isinstance(case_sensitive, bool):
        raise Stage1Error(
            "config_error",
            "筛选规则选项必须是布尔值",
            "load_user_config",
        )
    if not isinstance(priority, list) or not all(
        isinstance(item, str) for item in priority
    ):
        raise Stage1Error(
            "config_error",
            "subtitle_group_priority 必须是字符串数组",
            "load_user_config",
        )

    return UserPreference(
        filter_rule=FilterRule(
            must_contain=must_contain,
            must_not_contain=must_not_contain,
            use_regex=use_regex,
            case_sensitive=case_sensitive,
        ),
        subtitle_group_priority=priority,
    )
