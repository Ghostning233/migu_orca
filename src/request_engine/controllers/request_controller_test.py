from __future__ import annotations

import pytest

from request_engine.controllers.request_controller import (
    accept_request,
    build_pending_request,
    cancel_request,
)
from shared.errors import Stage1Error
from shared.models import (
    EntryRequest,
    FilterRule,
    MatchedBangumi,
    SubtitleGroupSelection,
)


def _pending_request() -> dict:
    return build_pending_request(
        EntryRequest("番剧"),
        MatchedBangumi("番剧", [], "https://example.invalid", 1.0),
        [],
        SubtitleGroupSelection(None, None, ["没有有效种子"]),
        FilterRule(),
        "番剧",
    )


def test_request_is_pending_snapshot_not_state_machine() -> None:
    request = _pending_request()

    assert request["status"] == "PENDING_CONFIRM"
    assert request["confirmable_config"]["selected_subtitle_group"] is None
    assert request["confirmable_config"]["warnings"] == ["没有有效种子"]


def test_accept_request_marks_pending_request_accepted_without_mutating_original() -> None:
    request = _pending_request()

    accepted = accept_request(request)

    assert request["status"] == "PENDING_CONFIRM"
    assert "user_action" not in request
    assert accepted["status"] == "ACCEPTED"
    assert accepted["updated_at"] >= request["updated_at"]
    assert accepted["ab_submit_result"] is None
    assert accepted["user_action"] == {
        "action": "ACCEPT",
        "reason": None,
        "decided_at": accepted["updated_at"],
    }


def test_cancel_request_marks_pending_request_cancelled_with_reason() -> None:
    request = _pending_request()

    cancelled = cancel_request(request, "匹配结果不符合预期")

    assert request["status"] == "PENDING_CONFIRM"
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["user_action"] == {
        "action": "CANCEL",
        "reason": "匹配结果不符合预期",
        "decided_at": cancelled["updated_at"],
    }


def test_accept_and_cancel_reject_non_pending_request() -> None:
    accepted = accept_request(_pending_request())

    with pytest.raises(Stage1Error) as accept_error:
        accept_request(accepted)
    with pytest.raises(Stage1Error) as cancel_error:
        cancel_request(accepted, "不需要")

    assert accept_error.value.error_type == "invalid_request_status"
    assert cancel_error.value.details == {"status": "ACCEPTED"}


def test_cancel_request_rejects_empty_reason() -> None:
    with pytest.raises(Stage1Error) as error:
        cancel_request(_pending_request(), "  ")

    assert error.value.error_type == "invalid_cancel_reason"
