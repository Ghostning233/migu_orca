from __future__ import annotations

import re

import pytest

from ab_engine.controllers import subscription_payload as subscription_payload_module
from ab_engine.controllers.subscription_payload import (
    build_ab_submit_payload,
    build_ab_subscription_payload,
    build_legacy_31_collection_payload,
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


def test_build_ab_subscription_payload_rejects_missing_confirmed_title() -> None:
    request = _accepted_request()
    request["source_info"]["matched_bangumi"]["title"] = ""

    with pytest.raises(Stage1Error) as error:
        build_ab_subscription_payload(request)

    assert error.value.error_type == "missing_ab_payload_field"


def test_build_legacy_31_subscription_payload_maps_confirmed_request_to_real_contract() -> None:
    payload = build_legacy_31_subscription_payload(_accepted_request())

    assert payload == {
        "data": {
            "official_title": "番剧 标准标题",
            "title_raw": "番剧 标准标题",
            "season": 1,
            "group_name": "Loli",
            "filter": "(?is)(?:^(?!.*(?:1080p)).*$|.*(?:SP).*)",
            "rss_link": "https://example.invalid/rss.xml",
            "save_path": "番剧 标准标题",
            "poster_link": None,
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


def test_build_legacy_31_subscription_payload_propagates_only_trusted_public_poster() -> None:
    request = _accepted_request()
    request["source_info"]["matched_bangumi"]["poster_url"] = "https://mikan.example/images/public-cover.jpg"

    assert build_legacy_31_subscription_payload(request)["data"]["poster_link"] == "https://mikan.example/images/public-cover.jpg"


@pytest.mark.parametrize(
    "poster_url",
    [
        "/api/v1/mikan/posters/opaque-key",
        "javascript:alert(1)",
        "https://user:password@mikan.example/cover.jpg",
        "https://mikan.example/cover.jpg\nsecret",
    ],
)
def test_build_legacy_31_subscription_payload_omits_invalid_or_opaque_poster(
    poster_url: str,
) -> None:
    request = _accepted_request()
    request["source_info"]["matched_bangumi"]["poster_url"] = poster_url

    payload = build_legacy_31_subscription_payload(request)

    assert payload["data"]["poster_link"] is None
    assert "password" not in str(payload)


def test_build_legacy_31_subscription_payload_detects_a_nonfirst_season_from_title() -> None:
    request = _accepted_request()
    request["source_info"]["matched_bangumi"]["title"] = "番剧 第2季"

    data = build_legacy_31_subscription_payload(request)["data"]

    assert data["season"] == 2
    assert data["season_raw"] == "第2季"


@pytest.mark.parametrize(
    ("marker", "season"),
    [("第二季", 2), ("第四季", 4), ("第十季", 10), ("第十二季", 12), ("第九十九季", 99)],
)
def test_build_legacy_31_subscription_payload_parses_chinese_season_markers(
    marker: str, season: int
) -> None:
    request = _accepted_request()
    request["source_info"]["matched_bangumi"]["title"] = f"番剧 {marker}"

    data = build_legacy_31_subscription_payload(request)["data"]

    assert data["season"] == season
    assert data["season_raw"] == marker


@pytest.mark.parametrize("marker", ["第零季", "第一百季", "第百二季"])
def test_build_legacy_31_subscription_payload_refuses_unprovable_explicit_season(
    marker: str,
) -> None:
    request = _accepted_request()
    request["source_info"]["matched_bangumi"]["title"] = f"番剧 {marker}"

    with pytest.raises(Stage1Error) as error:
        build_legacy_31_subscription_payload(request)

    assert error.value.error_type == "ab_season_unsupported"


def test_build_legacy_31_subscription_payload_uses_only_confirmed_title_for_season() -> None:
    request = _accepted_request()
    request["input"]["raw_title"] = "番剧 第十二季"

    data = build_legacy_31_subscription_payload(request)["data"]

    assert data["season"] == 1
    assert "season_raw" not in data


def test_build_legacy_31_subscription_payload_refuses_regex_invalid_after_embedding() -> None:
    request = _accepted_request()
    request["confirmable_config"]["filter_rule"] = {
        "must_contain": "(?i)1080p",
        "must_not_contain": "",
        "use_regex": True,
        "case_sensitive": True,
    }

    with pytest.raises(Stage1Error) as error:
        build_legacy_31_subscription_payload(request)

    assert error.value.error_type == "ab_filter_unsupported"


def test_build_legacy_31_collection_payload_is_the_bare_bangumi_model() -> None:
    """Issue #217: ``POST /api/v1/rss/collect`` takes a bare ``Bangumi`` body.

    The real 3.1.18 instance declares the requestBody as ``$ref Bangumi`` (not
    the ``Body_subscribe_...`` wrapper ``/rss/subscribe`` uses), and the endpoint
    never creates an RSS subscription, so neither ``data``/``rss`` nor ``id``
    may appear in the collection body.
    """

    payload = build_legacy_31_collection_payload(_accepted_request())

    assert payload == build_legacy_31_subscription_payload(_accepted_request())["data"]
    assert "data" not in payload
    assert "rss" not in payload
    assert "id" not in payload


def test_build_legacy_31_collection_payload_preserves_save_path_and_exact_rss_link() -> None:
    request = _accepted_request()
    request["confirmable_config"]["expected_folder_name"] = "番剧/第一季"
    request["confirmable_config"]["selected_rss_url"] = "https://example.invalid/rss.xml?tid=7&f=1"

    payload = build_legacy_31_collection_payload(request)

    assert payload["save_path"] == "番剧/第一季"
    assert payload["rss_link"] == "https://example.invalid/rss.xml?tid=7&f=1"


def test_build_legacy_31_collection_payload_never_carries_an_id() -> None:
    """An ``id`` would silently target an existing rule's update path upstream."""

    request = _accepted_request()
    request["source_info"]["matched_bangumi"]["id"] = 999999

    payload = build_legacy_31_collection_payload(request)

    assert "id" not in payload
    assert "999999" not in str(payload)


def test_build_legacy_31_collection_payload_never_shares_the_subscribe_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reused subscribe ``data`` object must be deep-copied, never aliased.

    Patching the builder is the only way to observe the copy: the real ``data``
    is rebuilt from strings on every call, so an aliasing regression there would
    be invisible to an end-to-end assertion.
    """

    shared = {
        "official_title": "番剧 标准标题",
        "filter": "(?!)",
        "save_path": "番剧 标准标题",
        "rss_link": "https://example.invalid/rss.xml",
        "nested": {"must_contain": "1080p"},
    }
    monkeypatch.setattr(
        subscription_payload_module,
        "build_legacy_31_subscription_payload",
        lambda request: {"data": shared, "rss": {"url": shared["rss_link"]}},
    )

    payload = build_legacy_31_collection_payload(_accepted_request())

    assert payload == shared
    assert payload is not shared
    shared["nested"]["must_contain"] = "changed"
    shared["save_path"] = "changed"
    assert payload["nested"]["must_contain"] == "1080p"
    assert payload["save_path"] == "番剧 标准标题"


def test_build_legacy_31_collection_payload_requires_an_accepted_request() -> None:
    request = _accepted_request()
    request["status"] = "PENDING_CONFIRM"

    with pytest.raises(Stage1Error) as error:
        build_legacy_31_collection_payload(request)

    assert error.value.error_type == "invalid_request_status"


@pytest.mark.parametrize(
    ("filter_rule", "expected_filter"),
    [
        (
            {"must_contain": "a{1,3}", "must_not_contain": "", "use_regex": True, "case_sensitive": False},
            "(?is)(?:^(?!.*(?:a{1,3})).*$)",
        ),
        (
            {"must_contain": "1080p, 简体", "must_not_contain": "", "use_regex": False, "case_sensitive": False},
            "(?is)(?:^(?!.*(?:1080p,\\ 简体)).*$)",
        ),
        (
            {"must_contain": "1080p", "must_not_contain": "SP, OVA", "use_regex": False, "case_sensitive": False},
            "(?is)(?:^(?!.*(?:1080p)).*$|.*(?:SP,\\ OVA).*)",
        ),
    ],
)
def test_build_legacy_31_collection_payload_refuses_ascii_comma_zero_write(
    filter_rule: dict,
    expected_filter: str,
) -> None:
    """Auto Bangumi 3.1.18 runs ``bangumi.filter.replace(",", "|")`` for collect.

    A comma silently changes the filter semantics (``a{1,3}`` becomes
    ``a{1|3}``), so the collection body must be refused instead of rewritten.
    The existing subscribe body keeps the expression, proving the guard is a
    collect-only refusal and not a silent rewrite.
    """

    request = _accepted_request()
    request["confirmable_config"]["filter_rule"] = filter_rule

    assert build_legacy_31_subscription_payload(request)["data"]["filter"] == expected_filter

    with pytest.raises(Stage1Error) as error:
        build_legacy_31_collection_payload(request)

    assert error.value.as_dict() == {
        "error_type": "ab_filter_unsupported",
        "error_message": "当前筛选规则无法兼容 Auto Bangumi 3.1",
        "failed_step": "build_legacy_31_collection_payload",
        "details": {},
    }


def test_build_legacy_31_collection_payload_allows_a_comma_free_filter() -> None:
    payload = build_legacy_31_collection_payload(_accepted_request())

    assert payload["filter"] == "(?is)(?:^(?!.*(?:1080p)).*$|.*(?:SP).*)"
