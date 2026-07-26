from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from shared.models import (
    EntryRequest,
    FilteredRss,
    FilterRule,
    MatchedBangumi,
    SubtitleGroupSelection,
)


def build_pending_request(
    entry: EntryRequest,
    matched: MatchedBangumi,
    rss_results: list[FilteredRss],
    selection: SubtitleGroupSelection,
    filter_rule: FilterRule,
    folder_name: str,
    flow_warnings: list[str] | None = None,
) -> dict[str, Any]:
    created_at = datetime.now(UTC).isoformat()
    selected_result = next(
        (
            result
            for result in rss_results
            if result.source.rss_url == selection.rss_url
        ),
        None,
    )
    warnings = [*(flow_warnings or []), *selection.warnings]
    for result in rss_results:
        warnings.extend(result.warnings)

    return {
        "request_id": str(uuid4()),
        "status": "PENDING_CONFIRM",
        "input": asdict(entry),
        "source_info": {
            "matched_bangumi": asdict(matched),
            "rss_sources": [_rss_result_to_dict(result) for result in rss_results],
        },
        "confirmable_config": {
            "selected_subtitle_group": selection.subtitle_group,
            "selected_rss_url": selection.rss_url,
            "filter_rule": asdict(filter_rule),
            "effective_seed_names": (
                [seed.title for seed in selected_result.valid_seeds]
                if selected_result
                else []
            ),
            "expected_folder_name": folder_name,
            "warnings": warnings,
        },
        "ab_submit_result": None,
        "created_at": created_at,
        "updated_at": created_at,
    }


def _rss_result_to_dict(result: FilteredRss) -> dict[str, Any]:
    return {
        "subtitle_group": result.source.subtitle_group,
        "rss_url": result.source.rss_url,
        "source_type": result.source.source_type,
        "total_seed_count": result.total_seed_count,
        "valid_seed_count": len(result.valid_seeds),
        "invalid_seed_count": len(result.excluded_seeds),
        "valid_seed_names": [seed.title for seed in result.valid_seeds],
        "excluded_seed_names": [asdict(seed) for seed in result.excluded_seeds],
        "warnings": result.warnings,
    }
