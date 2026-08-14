from __future__ import annotations

import pytest

from ab_engine.controllers.subscription_payload import build_ab_subscription_payload
from request_engine.controllers.request_controller import (
    accept_request,
    build_pending_request,
)
from shared.errors import Stage1Error
from shared.models import (
    EntryRequest,
    FilterRule,
    MatchedBangumi,
    SubtitleGroupSelection,
)


def _accepted_request() -> dict:
    pending = build_pending_request(
        EntryRequest("番剧"),
        MatchedBangumi("番剧 标准标题", [], "https://example.invalid/bangumi", 1.0),
        [],
        SubtitleGroupSelection("Loli", "https://example.invalid/rss.xml", []),
        FilterRule(must_contain="1080p", must_not_contain="SP"),
        "番剧 标准标题",
    )
    return accept_request(pending)


def test_build_ab_subscription_payload_maps_accepted_request_fields() -> None:
    request = _accepted_request()

    payload = build_ab_subscription_payload(request)

    assert payload == {
        "title": "番剧 标准标题",
        "rss_url": "https://example.invalid/rss.xml",
        "save_path": "番剧 标准标题",
        "filter_rule": {
            "must_contain": "1080p",
            "must_not_contain": "SP",
            "use_regex": False,
            "case_sensitive": False,
        },
    }


def test_build_ab_subscription_payload_rejects_non_accepted_request() -> None:
    request = _accepted_request()
    request["status"] = "PENDING_CONFIRM"

    with pytest.raises(Stage1Error) as error:
        build_ab_subscription_payload(request)

    assert error.value.as_dict() == {
        "error_type": "invalid_request_status",
        "error_message": "只有 ACCEPTED Request 可以提交到 Auto Bangumi",
        "failed_step": "build_ab_subscription_payload",
        "details": {"status": "PENDING_CONFIRM"},
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("selected_rss_url", None),
        ("selected_rss_url", "  "),
        ("expected_folder_name", None),
        ("expected_folder_name", "  "),
    ],
)
def test_build_ab_subscription_payload_requires_core_confirmable_fields(
    field: str,
    value: object,
) -> None:
    request = _accepted_request()
    request["confirmable_config"][field] = value

    with pytest.raises(Stage1Error) as error:
        build_ab_subscription_payload(request)

    assert error.value.error_type == "missing_ab_payload_field"
    assert error.value.details == {"field": f"confirmable_config.{field}"}


def test_build_ab_subscription_payload_does_not_mutate_or_retain_request_objects() -> None:
    request = _accepted_request()

    payload = build_ab_subscription_payload(request)
    request["confirmable_config"]["filter_rule"]["must_contain"] = "changed"

    assert request["status"] == "ACCEPTED"
    assert payload["filter_rule"] == {
        "must_contain": "1080p",
        "must_not_contain": "SP",
        "use_regex": False,
        "case_sensitive": False,
    }


def test_build_ab_subscription_payload_falls_back_to_input_title() -> None:
    request = _accepted_request()
    request["source_info"]["matched_bangumi"]["title"] = ""

    payload = build_ab_subscription_payload(request)

    assert payload["title"] == "番剧"
