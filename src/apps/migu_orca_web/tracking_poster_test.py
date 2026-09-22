from __future__ import annotations

"""Issue #84: durable same-origin cover references for saved tracking plans."""

from io import BytesIO
from pathlib import Path

from apps.migu_orca_web.tracking_poster import (
    POSTER_PATH_PREFIX,
    poster_path_for_key,
    poster_path_for_url,
    request_poster_path,
)
from mikan_engine.controllers.mikan_poster_cache import (
    MikanPosterCacheConfig,
    poster_cache_key,
)
from mikan_engine.controllers.mikan_poster_service import MikanPosterService


class _Response(BytesIO):
    class _Headers:
        @staticmethod
        def get_content_type() -> str:
            return "image/gif"

    headers = _Headers()

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _service(tmp_path: Path) -> MikanPosterService:
    return MikanPosterService(
        MikanPosterCacheConfig(cache_dir=tmp_path / "posters"),
        resolve=lambda _host, _port: [(None, None, None, None, ("8.8.8.8", 0))],
        open_request=lambda _request, _timeout: _Response(b"GIF89a\x01\x00"),
    )


def test_request_poster_path_pins_the_rendered_cover_across_restart(tmp_path: Path) -> None:
    source = "https://mikan.example/cover.gif"
    service = _service(tmp_path)
    key = service.register(source)
    assert key is not None
    service.get(key)  # the candidate card already rendered this cover
    request = {"source_info": {"matched_bangumi": {"poster_url": source}}}

    path = request_poster_path(request, service=service)

    assert path == f"{POSTER_PATH_PREFIX}{poster_cache_key(source)}"
    restarted = _service(tmp_path)
    cached, content_type = restarted.get(key)
    assert cached.read_bytes().startswith(b"GIF89a")
    assert content_type == "image/gif"


def test_request_poster_path_never_exposes_an_uncached_upstream_url(tmp_path: Path) -> None:
    service = _service(tmp_path)
    source = "https://mikan.example/never-rendered.gif"

    path = request_poster_path(
        {"source_info": {"matched_bangumi": {"poster_url": source}}},
        service=service,
    )

    assert path == f"{POSTER_PATH_PREFIX}{poster_cache_key(source)}"
    assert source not in path


def test_request_poster_path_is_none_without_a_usable_source(tmp_path: Path) -> None:
    service = _service(tmp_path)

    assert request_poster_path(None, service=service) is None
    assert request_poster_path({}, service=service) is None
    assert request_poster_path({"source_info": {}}, service=service) is None
    assert request_poster_path({"source_info": {"matched_bangumi": {}}}, service=service) is None
    assert request_poster_path(
        {"source_info": {"matched_bangumi": {"poster_url": None}}}, service=service
    ) is None


def test_poster_path_for_url_rejects_non_http_and_empty_sources(tmp_path: Path) -> None:
    service = _service(tmp_path)

    assert poster_path_for_url(None, service=service) is None
    assert poster_path_for_url("", service=service) is None
    assert poster_path_for_url("   ", service=service) is None
    assert poster_path_for_url("file:///tmp/cover.gif", service=service) is None
    assert poster_path_for_url("javascript:alert(1)", service=service) is None
    assert poster_path_for_url("https://user:secret@mikan.example/cover.gif", service=service) is None


def test_poster_path_for_key_is_always_a_same_origin_route() -> None:
    assert poster_path_for_key("a" * 64) == f"/api/v1/mikan/posters/{'a' * 64}"
