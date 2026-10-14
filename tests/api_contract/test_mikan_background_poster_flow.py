"""Issue #179: selected MiKan CSS cover survives both consumer boundaries."""
from __future__ import annotations

from pathlib import Path

import pytest

from ab_engine.controllers.subscription_payload import build_legacy_31_subscription_payload
from apps.migu_orca_web import tracking_poster
from apps.migu_orca_web.tracking_handoff import ensure_confirmed_request_tracking
from apps.migu_orca_web.tracking_serializers import tracking_summary_fields
from mikan_engine.controllers.mikan_client import create_mikan_client
from mikan_engine.controllers.mikan_config import MikanConfig
from mikan_engine.controllers.mikan_poster_cache import MikanPosterCacheConfig, poster_cache_key
from mikan_engine.controllers.mikan_poster_service import MikanPosterService
from plan_engine.controllers.data_sources import MikanDataSource
from plan_engine.controllers.plan_generation import build_plan
from request_engine.controllers.request_controller import accept_request
from shared.models import EntryRequest
from storage_engine.controllers.request_repository import load_request_snapshot, save_request_snapshot
from storage_engine.controllers.storage_config import load_storage_config
from storage_engine.controllers.tracking_repository import load_tracking_record
from tracking_engine.models.tracking import TRACKING_ORIGIN_SAVE_CONFIRM


class _Transport:
    def __init__(self, with_cover: bool) -> None:
        self.with_cover = with_cover

    def get_text(self, url: str, *, timeout: float) -> str:
        if "/Home/Bangumi/" in url:
            cover = (
                '<div class="bangumi-poster" style="background-image: '
                "url('/images/Bangumi/cover.jpg?width=400&amp;format=webp');\"></div>"
                if self.with_cover else ""
            )
            return (
                '<h1 class="bangumi-title">BanG Dream! YUME∞MITA</h1>' + cover
                + '<section class="subgroup-section"><h2 class="subgroup-name">Loli</h2>'
                '<a href="/RSS/Bangumi?bangumiId=1&amp;subgroupid=10">RSS</a></section>'
            )
        assert "/RSS/Bangumi?" in url
        return (
            '<rss><channel><item><title>BanG Dream! YUME∞MITA - 01 [1080p]</title>'
            '<link>https://mikan.example/Home/Episode/fixture-01</link></item></channel></rss>'
        )


@pytest.mark.parametrize("with_cover", [True, False])
def test_selected_collection_cover_reaches_saved_tracking_and_ab(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, with_cover: bool,
) -> None:
    config = MikanConfig(search_endpoint="https://mikan.example/Home/Search", timeout_seconds=5)
    transport = _Transport(with_cover)
    client = create_mikan_client(config, transport=transport)
    result = build_plan(
        EntryRequest(raw_title="BanG Dream! YUME∞MITA"),
        data_source=MikanDataSource(config=config, client=client),
        mikan_bangumi="https://mikan.example/Home/Bangumi/1",
    )
    assert result["success"] is True
    source = "https://mikan.example/images/Bangumi/cover.jpg?width=400&format=webp"
    expected = source if with_cover else None
    assert result["request"]["source_info"]["matched_bangumi"]["poster_url"] == expected
    request = accept_request(result["request"])
    storage = load_storage_config(tmp_path / "storage")
    save_request_snapshot(storage, request)
    saved = load_request_snapshot(storage, request["request_id"])
    assert build_legacy_31_subscription_payload(saved)["data"]["poster_link"] == expected

    service = MikanPosterService(MikanPosterCacheConfig(cache_dir=tmp_path / "posters"))
    monkeypatch.setattr(tracking_poster, "poster_service", service)
    handoff = ensure_confirmed_request_tracking(
        config=storage, request=saved, origin=TRACKING_ORIGIN_SAVE_CONFIRM,
    )
    assert handoff.tracking_ready
    record = load_tracking_record(storage, handoff.tracking_id)
    summary = tracking_summary_fields(record)
    assert summary["poster_path"] == (
        f"/api/v1/mikan/posters/{poster_cache_key(source)}" if with_cover else None
    )
    assert source not in str(summary)
