from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mikan_engine.controllers.mikan_poster_cache import (
    POSTER_CACHE_VERSION,
    MikanPosterCacheConfig,
    MikanPosterCacheRepository,
    poster_cache_key,
)
from shared.errors import Stage1Error


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 23, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


def _repository(tmp_path: Path, clock: Clock, **kwargs: object) -> MikanPosterCacheRepository:
    return MikanPosterCacheRepository(
        MikanPosterCacheConfig(cache_dir=tmp_path / "posters", **kwargs), now=clock.now
    )


def test_poster_cache_key_is_opaque_path_safe_and_versioned() -> None:
    key = poster_cache_key("https://mikan.example/assets/cover.jpg?secret=nope")
    assert len(key) == 64
    assert "/" not in key and "secret" not in key
    assert POSTER_CACHE_VERSION == "v1"


def test_cache_miss_put_hit_and_sliding_ttl(tmp_path: Path) -> None:
    clock = Clock()
    cache = _repository(tmp_path, clock, ttl_seconds=10)
    key = poster_cache_key("https://mikan.example/cover.jpg")
    assert cache.get(key) is None
    stored = cache.put(key, "image/jpeg", [b"image"])
    assert stored.read_bytes() == b"image"
    clock.value += timedelta(seconds=9)
    assert cache.get(key) == stored
    clock.value += timedelta(seconds=9)
    assert cache.get(key) == stored


def test_expired_cleanup_deletes_only_regular_cache_files(tmp_path: Path) -> None:
    clock = Clock()
    cache = _repository(tmp_path, clock, ttl_seconds=10, cleanup_interval_seconds=0)
    key = poster_cache_key("https://mikan.example/old.jpg")
    path = cache.put(key, "image/jpeg", [b"old"])
    outside = tmp_path / "outside"
    outside.write_bytes(b"keep")
    symlink = path.parent / f"{poster_cache_key('https://mikan.example/link.jpg')}.img"
    symlink.symlink_to(outside)
    clock.value += timedelta(seconds=11)
    cache.cleanup_expired()
    assert not path.exists()
    assert outside.read_bytes() == b"keep"
    assert symlink.is_symlink()


@pytest.mark.parametrize("key", ["../escape", "a" * 63, "A" * 64])
def test_cache_rejects_path_traversal_and_invalid_keys(tmp_path: Path, key: str) -> None:
    with pytest.raises(Stage1Error, match="标识"):
        _repository(tmp_path, Clock()).get(key)


def test_cache_rejects_non_images_and_oversized_content_without_files(tmp_path: Path) -> None:
    cache = _repository(tmp_path, Clock(), max_bytes=3)
    key = poster_cache_key("https://mikan.example/cover.jpg")
    with pytest.raises(Stage1Error, match="不是图片"):
        cache.put(key, "text/html", [b"no"])
    with pytest.raises(Stage1Error, match="超过大小"):
        cache.put(key, "image/png", [b"toolong"])
    assert not (tmp_path / "posters" / f"{key}.img").exists()
    assert not list((tmp_path / "posters").glob(".poster-*.tmp"))


def test_atomic_write_failure_leaves_previous_file_and_no_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = _repository(tmp_path, Clock())
    key = poster_cache_key("https://mikan.example/cover.jpg")
    original = cache.put(key, "image/jpeg", [b"old"])

    def fail_replace(_source: object, _target: object) -> None:
        raise OSError("disk trouble")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(Stage1Error, match="保存"):
        cache.put(key, "image/jpeg", [b"new"])
    assert original.read_bytes() == b"old"
    assert not list(original.parent.glob(".poster-*.tmp"))
