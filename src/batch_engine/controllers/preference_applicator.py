from __future__ import annotations

import re
from dataclasses import dataclass, field

from batch_engine.models import AnimeTitleParseResult
from shared.errors import Stage1Error
from shared.models import NamingPreference, VersionedUserPreference
from subscription_engine.controllers.subscription_controller import generate_folder_name


@dataclass(frozen=True)
class AppliedBatchPreferences:
    """Per-item non-sensitive preference application result for a batch draft.

    ``subtitle_groups``/``filter_rule``/``naming`` mirror the saved preference
    contract so the Web UI can prefill the single-card editable defaults, and
    ``expected_folder_name`` is the naming-strategy default. ``warnings`` holds
    only reviewable notes (e.g. no fallback subtitle group configured), never
    external secrets or raw responses.
    """

    subtitle_groups: dict[str, object]
    filter_rule: dict[str, object]
    naming: dict[str, object]
    expected_folder_name: str | None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Serialize the public applied-preference fields.

        ``warnings`` stays on the model but is returned separately by the batch
        parse view as the item-level ``preference_warnings`` list, so the API
        exposes ``applied_preferences`` + ``preference_warnings`` as the two
        reviewable metadata fields required by US-153.
        """
        return {
            "subtitle_groups": dict(self.subtitle_groups),
            "filter_rule": dict(self.filter_rule),
            "naming": dict(self.naming),
            "expected_folder_name": self.expected_folder_name,
        }


def build_preference_config(
    preferences: VersionedUserPreference,
) -> dict[str, object]:
    """Return the item-independent preference default config as a public dict.

    The dict only carries the defined non-sensitive fields: subtitle-group
    preferred/excluded/fallback, the default filter rule (with explicit
    ``use_regex``/``case_sensitive`` booleans), and the naming strategy plus
    template. Endpoint/token/cookie/Authorization/magnet/raw HTML-RSS/response
    bodies and local absolute paths are rejected by the preference repository
    before save and re-validated on load, so this config is always safe.
    """
    subtitle_groups = preferences.subtitle_groups
    filter_defaults = preferences.filter_defaults
    naming = preferences.naming
    return {
        "subtitle_groups": {
            "preferred": list(subtitle_groups.preferred),
            "excluded": list(subtitle_groups.excluded),
            "fallback": subtitle_groups.fallback,
        },
        "filter_rule": {
            "must_contain": filter_defaults.must_contain,
            "must_not_contain": filter_defaults.must_not_contain,
            "use_regex": filter_defaults.use_regex,
            "case_sensitive": filter_defaults.case_sensitive,
        },
        "naming": {
            "strategy": naming.strategy,
            "template": naming.template,
        },
    }


def apply_preferences_to_item(
    raw_title: str,
    parse_result: AnimeTitleParseResult | None,
    preferences: VersionedUserPreference,
) -> AppliedBatchPreferences:
    """Build the reviewable preference application result for one batch item.

    ``parse_result`` may be ``None`` for a failed item: the item-independent
    default config is still returned, but the naming default is unavailable
    (with a warning). Preference conflicts are item-local: one item's warning
    never affects its siblings.
    """
    config = build_preference_config(preferences)
    warnings: list[str] = []

    subtitle_groups = preferences.subtitle_groups
    if subtitle_groups.fallback == "none" and not subtitle_groups.preferred:
        warnings.append("fallback 为 none 且未配置偏好字幕组，不会自动选择字幕组")

    expected_folder_name: str | None = None
    if parse_result is None:
        warnings.append("该条目解析失败，命名默认值不可用")
    else:
        naming_title = _naming_title(raw_title, parse_result, preferences.naming)
        if naming_title:
            try:
                expected_folder_name = generate_folder_name(naming_title)
            except Stage1Error:
                expected_folder_name = None

    return AppliedBatchPreferences(
        subtitle_groups=config["subtitle_groups"],
        filter_rule=config["filter_rule"],
        naming=config["naming"],
        expected_folder_name=expected_folder_name,
        warnings=warnings,
    )


#: A season marker already present in a title, so the season hint is not
#: appended a second time (第四季 / 第4季 / S2 / Season 2).
_SEASON_MARKER_RE = re.compile(
    r"第\s*[0-9一二三四五六七八九十百]+\s*季|[Ss]\d{1,2}|Season\s*\d+",
    re.IGNORECASE,
)


def _naming_title(
    raw_title: str,
    parse_result: AnimeTitleParseResult,
    naming: NamingPreference,
) -> str | None:
    if naming.strategy == "raw_title":
        base = raw_title.strip()
    else:
        candidates = parse_result.canonical_title_candidates
        base = (candidates[0] if candidates else raw_title).strip()
        if naming.strategy == "official_title_season":
            base = _append_season_hint(base, parse_result.season_hint)
    if not base:
        return None
    if naming.template and "{title}" in naming.template:
        base = naming.template.replace("{title}", base)
    return base.strip() or None


def _append_season_hint(base: str, season_hint: str | None) -> str:
    hint = (season_hint or "").strip()
    if not hint or _SEASON_MARKER_RE.search(base):
        return base
    suffix = hint
    season_match = re.fullmatch(r"[Ss](\d{1,2})", hint)
    if season_match:
        suffix = "第" + str(int(season_match.group(1))) + "季"
    season_match = re.fullmatch(r"Season\s*(\d+)", hint, re.IGNORECASE)
    if season_match:
        suffix = "第" + str(int(season_match.group(1))) + "季"
    return f"{base} {suffix}".strip()


__all__ = [
    "AppliedBatchPreferences",
    "apply_preferences_to_item",
    "build_preference_config",
]
