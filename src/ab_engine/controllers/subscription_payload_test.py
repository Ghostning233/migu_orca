from __future__ import annotations

import re

import pytest

from ab_engine.controllers.subscription_payload import (
    build_ab_subscription_payload,
    build_ab_submit_payload,
    build_legacy_31_subscription_payload,
)
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
        "error_message": "只有已确认订阅方案可以提交到 Auto Bangumi",
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


def test_build_legacy_31_subscription_payload_maps_confirmed_request_to_real_contract() -> None:
    payload = build_legacy_31_subscription_payload(_accepted_request())

    assert payload == {
        "data": {
            "official_title": "番剧 标准标题",
            "title_raw": "番剧",
            "season": 1,
            "group_name": "Loli",
            "filter": "(?is)(?:^(?!.*(?:1080p)).*$|.*(?:SP).*)",
            "rss_link": "https://example.invalid/rss.xml",
            "save_path": "番剧 标准标题",
        },
        "rss": {
            "name": "番剧 标准标题",
            "url": "https://example.invalid/rss.xml",
            "aggregate": False,
            "parser": "mikan",
        },
    }


def test_build_ab_submit_payload_selects_the_adapter_contract() -> None:
    request = _accepted_request()

    assert build_ab_submit_payload(request, "password") == build_legacy_31_subscription_payload(request)
    assert build_ab_submit_payload(request, "api_token") == build_ab_subscription_payload(request)


def test_build_legacy_31_subscription_payload_preserves_filter_behavior() -> None:
    request = _accepted_request()
    request["confirmable_config"]["filter_rule"] = {
        "must_contain": "1080p | 简体",
        "must_not_contain": "v2?",
        "use_regex": False,
        "case_sensitive": False,
    }

    expression = build_legacy_31_subscription_payload(request)["data"]["filter"]
    assert re.search(expression, "[Loli] 番剧 1080P 简体") is None
    assert re.search(expression, "[Loli] 番剧 720p 简体") is not None
    assert re.search(expression, "[Loli] 番剧 1080p 繁体") is not None
    assert re.search(expression, "[Loli] 番剧 1080p 简体 v2?") is not None


def test_build_legacy_31_subscription_payload_preserves_regex_and_case_semantics() -> None:
    request = _accepted_request()
    request["confirmable_config"]["filter_rule"] = {
        "must_contain": "1080P",
        "must_not_contain": "V2$",
        "use_regex": True,
        "case_sensitive": True,
    }

    expression = build_legacy_31_subscription_payload(request)["data"]["filter"]
    assert re.search(expression, "1080P release") is None
    assert re.search(expression, "1080p release") is not None
    assert re.search(expression, "1080P release V2") is not None


def test_build_legacy_31_subscription_payload_refuses_invalid_regex() -> None:
    request = _accepted_request()
    request["confirmable_config"]["filter_rule"] = {
        "must_contain": "(",
        "must_not_contain": "(",
        "use_regex": True,
        "case_sensitive": False,
    }
    with pytest.raises(Stage1Error, match="当前筛选规则无法兼容"):
        build_legacy_31_subscription_payload(request)


def test_build_legacy_31_subscription_payload_uses_empty_filter_to_allow_all_releases() -> None:
    request = _accepted_request()
    request["confirmable_config"]["filter_rule"] = {
        "must_contain": "",
        "must_not_contain": "",
        "use_regex": False,
        "case_sensitive": False,
    }

    assert build_legacy_31_subscription_payload(request)["data"]["filter"] == "(?!)"


def test_build_legacy_31_subscription_payload_maps_proven_public_metadata() -> None:
    request = _accepted_request()
    request["source_info"]["matched_bangumi"].update(
        {
            "season": 4,
            "season_raw": "第四季",
            "dpi": "1080p",
            "source": "mikan",
            "subtitle": "简中",
        }
    )

    data = build_legacy_31_subscription_payload(request)["data"]

    assert data["season"] == 4
    assert data["season_raw"] == "第四季"
    assert data["dpi"] == "1080p"
    assert data["source"] == "mikan"
    assert data["subtitle"] == "简中"


def test_build_legacy_31_subscription_payload_detects_a_nonfirst_season_from_title() -> None:
    request = _accepted_request()
    request["source_info"]["matched_bangumi"]["title"] = "番剧 第2季"

    data = build_legacy_31_subscription_payload(request)["data"]

    assert data["season"] == 2
    assert data["season_raw"] == "第2季"
