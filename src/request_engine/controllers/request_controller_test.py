from __future__ import annotations

from request_engine.controllers.request_controller import build_pending_request
from shared.models import (
    EntryRequest,
    FilterRule,
    MatchedBangumi,
    SubtitleGroupSelection,
)


def test_request_is_pending_snapshot_not_state_machine() -> None:
    request = build_pending_request(
        EntryRequest("番剧"),
        MatchedBangumi("番剧", [], "https://example.invalid", 1.0),
        [],
        SubtitleGroupSelection(None, None, ["没有有效种子"]),
        FilterRule(),
        "番剧",
    )

    assert request["status"] == "PENDING_CONFIRM"
    assert request["confirmable_config"]["selected_subtitle_group"] is None
    assert request["confirmable_config"]["warnings"] == ["没有有效种子"]
