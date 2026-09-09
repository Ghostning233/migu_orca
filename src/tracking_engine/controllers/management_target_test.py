from __future__ import annotations

import pytest

from ab_engine.models.management import ExternalRss, ExternalSubscription
from shared.errors import Stage1Error
from tracking_engine.controllers.management_target import (
    build_complete_rss_update,
    build_complete_subscription_update,
    build_management_binding,
    build_management_patch,
    resolve_management_target,
)
from tracking_engine.models.tracking import TrackingRecord


def _record() -> TrackingRecord:
    return TrackingRecord(
        tracking_id="trk_test",
        external_mapping={"subscription_id": "sub-1", "rss_ids": ["12", "2"]},
    )


def test_resolves_mapping_and_orders_associated_rss_without_public_ids() -> None:
    target = resolve_management_target(
        _record(),
        "ASSOCIATED_RSS",
        [ExternalSubscription("sub-1", "番剧", 1, "组")],
        [
            ExternalRss("12", "晚", "https://example.invalid/12"),
            ExternalRss("2", "早", "https://example.invalid/2"),
        ],
    )
    assert [item.name for item in target.rss] == ["早", "晚"]
    assert "12" not in repr(target)


def test_mapping_drift_is_rejected_before_a_write() -> None:
    with pytest.raises(Stage1Error) as exc:
        resolve_management_target(_record(), "SUBSCRIPTION", [], [])
    assert exc.value.error_type == "tracking_target_drift"


@pytest.mark.parametrize(
    "patch",
    [
        {},
        {"name": "x", "title": "cross-scope"},
        {"url": "https://example.invalid"},
        {"name": "/tmp/unsafe"},
        {"name": "../unsafe"},
        {"filter_rule": "raw expression"},
        {"filter_rule": {"raw": "x"}},
    ],
)
def test_patch_boundary_rejects_empty_mixed_sensitive_and_raw_values(patch: dict) -> None:
    with pytest.raises(Stage1Error):
        build_management_patch("ASSOCIATED_RSS" if "name" in patch or "url" in patch else "SUBSCRIPTION", patch)


def test_complete_bodies_preserve_snapshot_fields_and_never_accept_url() -> None:
    sub_target = resolve_management_target(
        _record(), "SUBSCRIPTION", [ExternalSubscription("sub-1", "旧标题", 2, "旧组")], []
    )
    assert build_complete_subscription_update(sub_target, {"title": "新标题"}) == {
        "title": "新标题", "season": 2, "subtitle_group": "旧组"
    }

    rss_target = resolve_management_target(
        _record(), "ASSOCIATED_RSS", [], [
            ExternalRss("2", "早", "https://example.invalid/2"),
            ExternalRss("12", "晚", "https://example.invalid/12"),
        ]
    )
    bodies = build_complete_rss_update(rss_target, {"name": "新名称"})
    assert [body["name"] for body in bodies] == ["新名称", "新名称"]
    assert all("url" not in body for body in bodies)


def test_complete_bodies_use_31_18_field_names_and_retain_snapshot_fields() -> None:
    sub = ExternalSubscription(
        "sub-1", "旧标题", 2, "旧组", upstream_fields={
            "official_title": "旧标题", "year": "2024", "title_raw": "raw",
            "season": 2, "season_raw": "S2", "group_name": "旧组", "dpi": "1080p",
            "source": "WEB", "subtitle": "简", "eps_collect": False, "offset": 0,
            "filter": "720,\\d+-\\d+", "rss_link": "https://rss.invalid",
            "poster_link": None, "added": True, "rule_name": "rule", "save_path": "/downloads",
            "deleted": False,
        }
    )
    target = resolve_management_target(_record(), "SUBSCRIPTION", [sub], [])
    body = build_complete_subscription_update(target, {"title": "新标题", "subtitle_group": "新组", "expected_folder_name": "new"})
    assert body["official_title"] == "新标题"
    assert body["group_name"] == "新组"
    assert body["save_path"] == "new"
    assert body["title_raw"] == "raw" and body["filter"] == "720,\\d+-\\d+"

    rss = ExternalRss("2", "早", "https://example.invalid/2", True, "mikan", True,
                      {"name": "早", "url": "https://example.invalid/2", "aggregate": True,
                       "parser": "mikan", "enabled": True})
    rss_target = resolve_management_target(_record(), "ASSOCIATED_RSS", [], [rss, ExternalRss("12", "晚", "https://example.invalid/12")])
    assert build_complete_rss_update(rss_target, {"name": "新名称"})[0] == {
        "name": "新名称", "url": "https://example.invalid/2", "aggregate": True,
        "parser": "mikan", "enabled": True,
    }


def test_binding_is_digest_only_and_deterministic() -> None:
    first = build_management_binding(action="MODIFY", scope="SUBSCRIPTION", patch={"title": "番剧"})
    second = build_management_binding(action="MODIFY", scope="SUBSCRIPTION", patch={"title": "番剧"})
    assert first == second
    assert first.action_fingerprint.startswith("sha256:")
    assert "番剧" not in repr(first)
