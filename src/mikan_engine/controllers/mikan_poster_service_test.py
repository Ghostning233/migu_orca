from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from mikan_engine.controllers.mikan_poster_cache import MikanPosterCacheConfig
from mikan_engine.controllers.mikan_poster_service import MikanPosterService
from shared.errors import Stage1Error


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


def _service(tmp_path: Path, payload: bytes = b"GIF89a\x01\x00") -> MikanPosterService:
    return MikanPosterService(
        MikanPosterCacheConfig(cache_dir=tmp_path / "posters"),
        resolve=lambda _host, _port: [(None, None, None, None, ("8.8.8.8", 0))],
        open_request=lambda _request, _timeout: _Response(payload),
    )


def test_registered_source_is_fetched_once_and_then_served_from_cache(tmp_path: Path) -> None:
    service = _service(tmp_path)
    key = service.register("https://mikan.example/poster.gif")
    assert key is not None
    path, content_type = service.get(key)
    assert path.read_bytes().startswith(b"GIF89a")
    assert content_type == "image/gif"
    service._sources.clear()
    cached, cached_type = service.get(key)
    assert cached == path
    assert cached_type == "image/gif"


@pytest.mark.parametrize("source", ["http://127.0.0.1/p.jpg", "file:///tmp/p.jpg"])
def test_poster_service_rejects_untrusted_or_private_sources(tmp_path: Path, source: str) -> None:
    service = _service(tmp_path)
    key = service.register(source)
    if key is None:
        return
    service._resolve = lambda _host, _port: [(None, None, None, None, ("127.0.0.1", 0))]
    with pytest.raises(Stage1Error, match="地址无效"):
        service.get(key)


def test_unregistered_key_never_becomes_an_open_proxy(tmp_path: Path) -> None:
    with pytest.raises(Stage1Error, match="暂不可用"):
        _service(tmp_path).get("a" * 64)


def test_non_image_response_leaves_no_cached_file(tmp_path: Path) -> None:
    service = _service(tmp_path)
    key = service.register("https://mikan.example/poster.jpg")
    assert key is not None
    service._open_request = lambda _request, _timeout: type("Response", (), {
        "headers": type("Headers", (), {"get_content_type": staticmethod(lambda: "text/html")})(),
        "__enter__": lambda self: self,
        "__exit__": lambda self, *_args: None,
    })()
    with pytest.raises(Stage1Error, match="不是支持的图片"):
        service.get(key)
    assert not list((tmp_path / "posters").glob("*.img"))
