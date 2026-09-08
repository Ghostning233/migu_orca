"""Pure pre-submit revalidation classification (US-224).

This module turns one TrackingRecord plus its current local Request into the
fixed ``issues`` verdict the ``POST .../revalidate`` endpoint returns.  It
implements the pure-local checklist of Stage 29 PRD §11.5:

    Request exists and ACCEPTED, fingerprint, title/season confirmation, MiKan
    collection, subtitle group, valid resources, external mapping, unfinished
    operation, current tracking state

The module is deliberately **pure** — it performs no I/O and imports no storage
repository.  The web revalidate service loads the record/Request/operation,
computes the current Request fingerprint through the save-confirm producer and
hands them to :func:`classify_revalidation`; the service persists the resulting
state transition (``PENDING_SUBMIT``/``SUBMIT_FAILED`` → ``NEEDS_RECONFIRM`` on
failure, ``NEEDS_RECONFIRM`` → ``PENDING_SUBMIT`` on success) and never lets the
route duplicate the checklist.

Issue codes are a fixed enum (Stage 29 PRD §11.5).  Messages are fixed safe
Chinese strings; ``recovery_action`` is either a safe action code (``SUBMIT``
for a changed plan the user may confirm-and-submit) or the empty string.  No
file name, path, raw JSON, credential, URL, magnet or absolute path is accepted
or returned here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from request_engine.controllers.request_controller import ACCEPTED
from tracking_engine.models.tracking import (
    TRACKING_STATUS_NEEDS_RECONFIRM,
    TRACKING_STATUS_PENDING_SUBMIT,
    TRACKING_STATUS_SUBMIT_FAILED,
    TrackingRecord,
)

# -- fixed issue codes (Stage 29 PRD §11.5) -----------------------------------
REVALIDATE_ISSUE_REQUEST_MISSING = "REQUEST_MISSING"
REVALIDATE_ISSUE_REQUEST_NOT_ACCEPTED = "REQUEST_NOT_ACCEPTED"
REVALIDATE_ISSUE_REQUEST_CHANGED = "REQUEST_CHANGED"
REVALIDATE_ISSUE_TITLE_MISSING = "TITLE_MISSING"
REVALIDATE_ISSUE_SEASON_REVIEW_REQUIRED = "SEASON_REVIEW_REQUIRED"
REVALIDATE_ISSUE_MIKAN_SELECTION_MISSING = "MIKAN_SELECTION_MISSING"
REVALIDATE_ISSUE_SUBTITLE_GROUP_MISSING = "SUBTITLE_GROUP_MISSING"
REVALIDATE_ISSUE_NO_VALID_RESOURCES = "NO_VALID_RESOURCES"
REVALIDATE_ISSUE_EXTERNAL_ALREADY_LINKED = "EXTERNAL_ALREADY_LINKED"
REVALIDATE_ISSUE_OPERATION_IN_PROGRESS = "OPERATION_IN_PROGRESS"
REVALIDATE_ISSUE_TRACKING_STATE_INVALID = "TRACKING_STATE_INVALID"

#: The fixed, documented issue-code enum in canonical order (§11.5).
REVALIDATE_ISSUE_CODES = (
    REVALIDATE_ISSUE_REQUEST_MISSING,
    REVALIDATE_ISSUE_REQUEST_NOT_ACCEPTED,
    REVALIDATE_ISSUE_REQUEST_CHANGED,
    REVALIDATE_ISSUE_TITLE_MISSING,
    REVALIDATE_ISSUE_SEASON_REVIEW_REQUIRED,
    REVALIDATE_ISSUE_MIKAN_SELECTION_MISSING,
    REVALIDATE_ISSUE_SUBTITLE_GROUP_MISSING,
    REVALIDATE_ISSUE_NO_VALID_RESOURCES,
    REVALIDATE_ISSUE_EXTERNAL_ALREADY_LINKED,
    REVALIDATE_ISSUE_OPERATION_IN_PROGRESS,
    REVALIDATE_ISSUE_TRACKING_STATE_INVALID,
)
REVALIDATE_ISSUE_CODES_SET = frozenset(REVALIDATE_ISSUE_CODES)

#: The tracking statuses a user may revalidate from.  ``REVALIDATING`` /
#: ``SUBMITTING`` / ``VERIFYING_EXTERNAL`` and the B-C reserved states are not
#: user-revalidatable; they are resolved through submit/retry/recover instead.
REVALIDATABLE_STATUSES = frozenset(
    {
        TRACKING_STATUS_PENDING_SUBMIT,
        TRACKING_STATUS_NEEDS_RECONFIRM,
        TRACKING_STATUS_SUBMIT_FAILED,
    }
)


@dataclass(frozen=True)
class RevalidationIssue:
    """One fixed, non-sensitive revalidation issue (§11.5)."""

    code: str
    message: str
    field: str | None = None
    #: Safe recovery-action code the UI may offer, or "" when no single
    #: action applies (a changed plan offers ``SUBMIT`` so the user can
    #: confirm-and-submit the latest Request).
    recovery_action: str = ""


@dataclass(frozen=True)
class RevalidationEvidence:
    """Everything the pure classifier needs about the current local Request."""

    #: The fresh Request snapshot, or None when it is missing/unreadable.
    request: dict[str, Any] | None
    #: Fingerprint of ``request`` (computed by the web save-confirm producer),
    #: or None when no Request could be read.
    request_fingerprint: str | None = None
    #: True when the record's current operation is not terminal (a submit may
    #: still be in flight, so the plan must not be re-confirmed yet).
    operation_in_progress: bool = False


def classify_revalidation(
    record: TrackingRecord,
    evidence: RevalidationEvidence,
) -> tuple[RevalidationIssue, ...]:
    """Return the fixed-ordered revalidation issues for one record + Request.

    An empty tuple means the plan is ready to submit.  The web service decides
    the resulting state transition from ``ready = not issues``; this function
    never writes anything and never leaks file/path/raw content.
    """
    issues: list[RevalidationIssue] = []

    if record.status not in REVALIDATABLE_STATUSES:
        issues.append(_issue(REVALIDATE_ISSUE_TRACKING_STATE_INVALID))
        # A non-revalidatable state short-circuits the plan checks below.
        return _ordered(issues)

    if evidence.operation_in_progress:
        issues.append(_issue(REVALIDATE_ISSUE_OPERATION_IN_PROGRESS))

    request = evidence.request
    if request is None:
        issues.append(_issue(REVALIDATE_ISSUE_REQUEST_MISSING))
        return _ordered(issues)
    if request.get("status") != ACCEPTED:
        issues.append(_issue(REVALIDATE_ISSUE_REQUEST_NOT_ACCEPTED))
        # The remaining checks read confirmed-plan content; a non-ACCEPTED
        # Request is not a confirmed plan, so do not keep checking it.
        return _ordered(issues)

    if _request_changed(record, evidence.request_fingerprint):
        issues.append(_issue(REVALIDATE_ISSUE_REQUEST_CHANGED))

    matched = _matched_bangumi(request)
    if _blank(matched.get("title")):
        issues.append(_issue(REVALIDATE_ISSUE_TITLE_MISSING))
    if _season_review_required(matched):
        issues.append(_issue(REVALIDATE_ISSUE_SEASON_REVIEW_REQUIRED))
    if not isinstance(matched.get("mikan_url"), str) or not matched.get("mikan_url").strip():
        issues.append(_issue(REVALIDATE_ISSUE_MIKAN_SELECTION_MISSING))

    confirmable = _confirmable_config(request)
    if _blank(confirmable.get("selected_subtitle_group")):
        issues.append(_issue(REVALIDATE_ISSUE_SUBTITLE_GROUP_MISSING))
    if _no_valid_resources(request, confirmable):
        issues.append(_issue(REVALIDATE_ISSUE_NO_VALID_RESOURCES))

    if _already_externally_linked(record):
        issues.append(_issue(REVALIDATE_ISSUE_EXTERNAL_ALREADY_LINKED))

    return _ordered(issues)


# ---------------------------------------------------------------------------
# Internal check helpers
# ---------------------------------------------------------------------------


def _request_changed(record: TrackingRecord, current_fingerprint: str | None) -> bool:
    """A stored confirmed fingerprint exists and no longer matches the Request."""
    stored = record.request_fingerprint
    if stored is None or current_fingerprint is None:
        return False
    return stored != current_fingerprint


def _season_review_required(matched: dict[str, Any]) -> bool:
    """A season marker exists on the plan but the season is not usable.

    Legacy plans that never carried a season marker are not flagged; once a
    plan carries ``season_raw``/``season_evidence`` a concrete positive-integer
    ``season`` must be present, otherwise the stored evidence is inconsistent
    and the season must be re-confirmed before submission.
    """
    has_marker = not _blank(matched.get("season_raw")) or not _blank(
        matched.get("season_evidence")
    )
    if not has_marker:
        return False
    season = matched.get("season")
    return not (isinstance(season, int) and not isinstance(season, bool) and season >= 1)


def _no_valid_resources(
    request: dict[str, Any],
    confirmable: dict[str, Any],
) -> bool:
    """The selected subtitle group has zero effective valid torrent seeds."""
    selected_group = confirmable.get("selected_subtitle_group")
    names: list[Any] = []
    if isinstance(selected_group, str) and selected_group.strip():
        source_info = request.get("source_info")
        sources = source_info.get("rss_sources") if isinstance(source_info, dict) else None
        if isinstance(sources, list):
            for source in sources:
                if not isinstance(source, dict):
                    continue
                if source.get("subtitle_group") == selected_group:
                    valid_names = source.get("valid_seed_names")
                    if isinstance(valid_names, list):
                        names = [name for name in valid_names if isinstance(name, str)]
                    break
    if not names:
        effective = confirmable.get("effective_seed_names")
        if isinstance(effective, list):
            names = [name for name in effective if isinstance(name, str)]
    return not names


def _already_externally_linked(record: TrackingRecord) -> bool:
    mapping = record.external_mapping
    return isinstance(mapping, dict) and bool(mapping)


def _matched_bangumi(request: dict[str, Any]) -> dict[str, Any]:
    source_info = request.get("source_info")
    matched = source_info.get("matched_bangumi") if isinstance(source_info, dict) else None
    return matched if isinstance(matched, dict) else {}


def _confirmable_config(request: dict[str, Any]) -> dict[str, Any]:
    confirmable = request.get("confirmable_config")
    return confirmable if isinstance(confirmable, dict) else {}


def _blank(value: Any) -> bool:
    return not (isinstance(value, str) and value.strip())


def _issue(code: str) -> RevalidationIssue:
    message, field, recovery = _ISSUE_META[code]
    return RevalidationIssue(
        code=code,
        message=message,
        field=field,
        recovery_action=recovery,
    )


def _ordered(issues: list[RevalidationIssue]) -> tuple[RevalidationIssue, ...]:
    """Return issues in the fixed §11.5 code order (deduplicated)."""
    by_code = {issue.code: issue for issue in issues}
    return tuple(by_code[code] for code in REVALIDATE_ISSUE_CODES if code in by_code)


#: Fixed safe Chinese copy + optional field/action per issue code (§11.5).
_ISSUE_META: dict[str, tuple[str, str | None, str]] = {
    REVALIDATE_ISSUE_REQUEST_MISSING: (
        "本地方案不存在或暂时不可读，无法提交追番",
        None,
        "",
    ),
    REVALIDATE_ISSUE_REQUEST_NOT_ACCEPTED: (
        "订阅方案未处于已确认状态，无法提交追番",
        "status",
        "",
    ),
    REVALIDATE_ISSUE_REQUEST_CHANGED: (
        "订阅方案已发生修改，请确认最新方案后再提交",
        None,
        "SUBMIT",
    ),
    REVALIDATE_ISSUE_TITLE_MISSING: (
        "订阅方案缺少作品标题，无法提交追番",
        "title",
        "",
    ),
    REVALIDATE_ISSUE_SEASON_REVIEW_REQUIRED: (
        "订阅方案的季度信息需要重新确认",
        "season",
        "",
    ),
    REVALIDATE_ISSUE_MIKAN_SELECTION_MISSING: (
        "订阅方案缺少真实的 MiKan 合集选择",
        "mikan_collection",
        "",
    ),
    REVALIDATE_ISSUE_SUBTITLE_GROUP_MISSING: (
        "订阅方案缺少选定的字幕组",
        "subtitle_group",
        "",
    ),
    REVALIDATE_ISSUE_NO_VALID_RESOURCES: (
        "订阅方案没有可用的有效资源，无法提交追番",
        "resources",
        "",
    ),
    REVALIDATE_ISSUE_EXTERNAL_ALREADY_LINKED: (
        "该方案已关联外部追番，不能重复提交",
        "external_mapping",
        "",
    ),
    REVALIDATE_ISSUE_OPERATION_IN_PROGRESS: (
        "存在尚未完成的提交操作，请先完成或恢复后再复核",
        "operation",
        "",
    ),
    REVALIDATE_ISSUE_TRACKING_STATE_INVALID: (
        "当前追番记录状态不允许复核",
        "tracking_status",
        "",
    ),
}


__all__ = [
    "REVALIDATE_ISSUE_CODES",
    "REVALIDATE_ISSUE_CODES_SET",
    "REVALIDATE_ISSUE_EXTERNAL_ALREADY_LINKED",
    "REVALIDATE_ISSUE_MIKAN_SELECTION_MISSING",
    "REVALIDATE_ISSUE_NO_VALID_RESOURCES",
    "REVALIDATE_ISSUE_OPERATION_IN_PROGRESS",
    "REVALIDATE_ISSUE_REQUEST_CHANGED",
    "REVALIDATE_ISSUE_REQUEST_MISSING",
    "REVALIDATE_ISSUE_REQUEST_NOT_ACCEPTED",
    "REVALIDATE_ISSUE_SEASON_REVIEW_REQUIRED",
    "REVALIDATE_ISSUE_SUBTITLE_GROUP_MISSING",
    "REVALIDATE_ISSUE_TITLE_MISSING",
    "REVALIDATE_ISSUE_TRACKING_STATE_INVALID",
    "REVALIDATABLE_STATUSES",
    "RevalidationEvidence",
    "RevalidationIssue",
    "classify_revalidation",
]
