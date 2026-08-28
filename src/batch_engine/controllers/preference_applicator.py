from __future__ import annotations

from dataclasses import dataclass, field

from batch_engine.controllers.anime_title_parser import LOW_CONFIDENCE_THRESHOLD
from batch_engine.models import (
    BATCH_ITEM_STATUS_FAILED,
    BATCH_ITEM_STATUS_PARSED,
    AnimeTitleParseResult,
)
from shared.errors import Stage1Error
from shared.models import NamingPreference, VersionedUserPreference
from shared.title_season import parse_title_season
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


#: Warning text that marks a preference configuration conflict requiring user
#: review: no preferred subtitle group is configured and the fallback is
#: disabled, so the preference cannot drive subtitle-group selection.
PREFERENCE_CONFLICT_WARNING = "fallback 为 none 且未配置偏好字幕组，不会自动选择字幕组"


def _is_preference_conflict_warning(warning: str) -> bool:
    return PREFERENCE_CONFLICT_WARNING in warning


@dataclass(frozen=True)
class BatchReviewMetadata:
    """Per-item review metadata for a batch draft.

    ``needs_user_review`` is True whenever the item should be checked by the
    user before acceptance (low confidence, multiple candidates, no candidates,
    search fallback/failure, or a preference conflict). ``review_hints`` are the
    Chinese review prompts shown to explain why. This metadata only annotates
    the item — it never changes the candidate list, never auto-selects a
    collection, and never auto-accepts a card.
    """

    needs_user_review: bool
    review_hints: list[str]


def build_preference_hits(
    applied: AppliedBatchPreferences,
) -> list[dict[str, object]]:
    """Return per-field public preference-hit summaries for one batch item.

    Each entry carries ``field``, ``applied``, and a Chinese rule summary so the
    Web UI can show which preference defaults were hit (applied as editable
    defaults), missed (not configured), or conflicted (could not be applied).
    Only public rule summaries are returned; endpoint/token/cookie/magnet/raw
    HTML-RSS/response bodies and local absolute paths never appear.
    """
    hits: list[dict[str, object]] = []

    preferred = applied.subtitle_groups.get("preferred") or []
    excluded = applied.subtitle_groups.get("excluded") or []
    if preferred or excluded:
        hits.append(
            {
                "field": "subtitle_groups",
                "applied": True,
                "summary": "字幕组偏好已作为可编辑默认值",
            }
        )
    else:
        hits.append(
            {
                "field": "subtitle_groups",
                "applied": False,
                "summary": "未配置字幕组偏好，使用默认选择流程",
            }
        )

    must_contain = (applied.filter_rule.get("must_contain") or "").strip()
    must_not_contain = (applied.filter_rule.get("must_not_contain") or "").strip()
    if must_contain or must_not_contain:
        hits.append(
            {
                "field": "filter_rule",
                "applied": True,
                "summary": "筛选默认值已作为可编辑默认规则",
            }
        )
    else:
        hits.append(
            {
                "field": "filter_rule",
                "applied": False,
                "summary": "未配置筛选默认值",
            }
        )

    if applied.expected_folder_name:
        hits.append(
            {
                "field": "naming",
                "applied": True,
                "summary": "命名策略已生成默认目录名：" + applied.expected_folder_name,
            }
        )
    else:
        hits.append(
            {
                "field": "naming",
                "applied": False,
                "summary": "未应用命名默认值",
            }
        )

    return hits


def build_review_metadata(
    *,
    raw_title: str,
    parse_result: AnimeTitleParseResult | None,
    candidates: list[dict[str, object]] | None,
    preference_warnings: list[str] | None,
    search_failed: bool = False,
    status: str = BATCH_ITEM_STATUS_PARSED,
) -> BatchReviewMetadata:
    """Compute the review-needed flag and Chinese review hints for one item.

    ``needs_user_review`` is True when the parse is low-confidence or
    multi-candidate, the item has no candidates, the candidate search fell back
    or failed, or the saved preferences conflict for this item. ``candidates``
    are the serialized public candidate dicts (empty list when a search produced
    no results). The result is item-local: one item's review state never affects
    its siblings.
    """
    hints: list[str] = []
    needs_review = status == BATCH_ITEM_STATUS_FAILED

    if parse_result is not None:
        raw = (raw_title or "").strip()
        if any((query or "").strip() == raw for query in parse_result.search_queries):
            needs_review = True
            hints.append("搜索词已回退为原始输入，建议核对搜索结果。")
        if parse_result.confidence < LOW_CONFIDENCE_THRESHOLD:
            needs_review = True
            hints.append(
                f"名称解析置信度较低（{parse_result.confidence:.2f}），建议核对候选合集。"
            )
        candidate_count = len(parse_result.canonical_title_candidates)
        if candidate_count > 1:
            needs_review = True
            hints.append(
                f"存在多个候选名称（{candidate_count} 个），建议确认正确的合集。"
            )
        elif parse_result.needs_user_review and not hints:
            needs_review = True
            hints.append("名称解析结果建议人工核对。")

        if not candidates and not search_failed:
            needs_review = True
            hints.append("未找到候选合集，建议手动选择或使用直连合集。")
    else:
        needs_review = True
        hints.append("该条目解析失败，请检查后重试。")

    if search_failed:
        needs_review = True
        hints.append("候选搜索失败，已回退默认流程，建议核对搜索结果。")

    for warning in preference_warnings or []:
        if _is_preference_conflict_warning(warning):
            needs_review = True
            hints.append("偏好字幕组存在冲突，请确认字幕组选择。")

    if needs_review and not hints:
        hints.append("该条目需要人工核对后再接受。")

    return BatchReviewMetadata(
        needs_user_review=needs_review,
        review_hints=list(dict.fromkeys(hints)),
    )


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
    parsed = parse_title_season(season_hint or "")
    if parsed.season is None or parse_title_season(base).season is not None:
        return base
    return f"{base} 第{parsed.season}季".strip()


__all__ = [
    "AppliedBatchPreferences",
    "BatchReviewMetadata",
    "PREFERENCE_CONFLICT_WARNING",
    "apply_preferences_to_item",
    "build_preference_config",
    "build_preference_hits",
    "build_review_metadata",
]
