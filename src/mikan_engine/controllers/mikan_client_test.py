from __future__ import annotations

import pytest

from mikan_engine.controllers.mikan_client import create_mikan_client
from mikan_engine.controllers.mikan_config import MikanConfig
from shared.errors import Stage1Error
from shared.models import MatchedBangumi


class FakeTransport:
    pass


def test_create_mikan_client_keeps_explicit_config_and_transport() -> None:
    config = MikanConfig(
        search_endpoint="https://mikan.example/search",
        timeout_seconds=5,
    )
    transport = FakeTransport()

    client = create_mikan_client(config, transport=transport)

    assert client.config is config
    assert client.transport is transport


def test_mikan_client_exposes_candidate_listing_boundary() -> None:
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/search",
            timeout_seconds=5,
        )
    )

    with pytest.raises(Stage1Error) as error:
        client.list_bangumi_candidates("芙莉莲")

    assert error.value.error_type == "mikan_not_implemented"
    assert error.value.failed_step == "mikan_search"


def test_mikan_client_exposes_rss_source_listing_boundary() -> None:
    client = create_mikan_client(
        MikanConfig(
            search_endpoint="https://mikan.example/search",
            timeout_seconds=5,
        )
    )
    matched = MatchedBangumi(
        title="芙莉莲",
        aliases=[],
        mikan_url="https://mikan.example/Home/Bangumi/1",
        match_score=1,
    )

    with pytest.raises(Stage1Error) as error:
        client.list_rss_sources(matched)

    assert error.value.error_type == "mikan_not_implemented"
    assert error.value.failed_step == "mikan_list_rss_sources"
