"""Safe on-disk cache primitives for server-fetched MiKan poster images.

This module deliberately does not fetch images or expose a Flask route.  It
only owns the bounded filesystem contract that a later, trusted transport can
use after it has validated a MiKan poster URL.
"""
from __future__ import annotations

import contextlib
import os
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from shared.config import PROJECT_ROOT
from shared.errors import Stage1Error

POSTER_CACHE_VERSION = "v1"
#: Sidecar marker for a poster the product must keep serving long-term (a saved
#: plan's cover).  A pinned entry is never expired or cleaned; the marker holds
#: no bytes and no source URL.
POSTER_PIN_SUFFIX = ".pin"
DEFAULT_POSTER_CACHE_DIR = PROJECT_ROOT / ".migu_orca" / "mikan_posters_v1"
DEFAULT_POSTER_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
DEFAULT_POSTER_DOWNLOAD_TIMEOUT_SECONDS = 10.0
DEFAULT_POSTER_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_CLEANUP_INTERVAL_SECONDS = 60 * 60


@dataclass(frozen=True)
class MikanPosterCacheConfig:
    """Versioned limits and trusted application-selected poster cache path."""

    cache_dir: Path = DEFAULT_POSTER_CACHE_DIR
    ttl_seconds: int = DEFAULT_POSTER_CACHE_TTL_SECONDS
    download_timeout_seconds: float = DEFAULT_POSTER_DOWNLOAD_TIMEOUT_SECONDS
    max_bytes: int = DEFAULT_POSTER_MAX_BYTES
    cleanup_interval_seconds: int = DEFAULT_CLEANUP_INTERVAL_SECONDS


def poster_cache_key(poster_url: str) -> str:
    """Return a non-reversible, path-safe opaque identifier for a poster URL."""
    if not isinstance(poster_url, str) or not poster_url.strip():
        raise Stage1Error("invalid_poster", "封面地址无效", "poster_cache_key")
    material = f"mikan-poster-cache:{POSTER_CACHE_VERSION}\0{poster_url.strip()}"
    return sha256(material.encode("utf-8")).hexdigest()


class MikanPosterCacheRepository:
    """Store validated image bytes with atomic writes and sliding TTL renewal."""

    def __init__(
        self,
        config: MikanPosterCacheConfig,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._now = now or (lambda: datetime.now(UTC))
        self._last_cleanup_at: datetime | None = None

    def get(self, key: str) -> Path | None:
        """Return a fresh cached file and renew its TTL, otherwise return ``None``."""
        path = self._path_for_key(key)
        try:
            stat = path.lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise _storage_error("读取封面缓存失败", "get_mikan_poster", exc) from exc

        if not path.is_file() or path.is_symlink():
            return None
        if not self._is_pinned_file(path) and self._is_expired(stat.st_mtime):
            self._unlink_regular_file(path)
            return None
        try:
            now_timestamp = self._now().timestamp()
            os.utime(path, (now_timestamp, now_timestamp), follow_symlinks=False)
        except OSError as exc:
            raise _storage_error("更新封面缓存有效期失败", "get_mikan_poster", exc) from exc
        return path

    def pin_existing(self, key: str) -> bool:
        """Keep an already-cached poster forever; return ``False`` on a cache miss.

        Only a validated key with real cached bytes can be pinned: this never
        fetches a source, so a saved plan's cover stays available across restarts
        without turning the cache into an open proxy.
        """
        path = self._path_for_key(key)
        try:
            stat = path.lstat()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise _storage_error("读取封面缓存失败", "pin_mikan_poster", exc) from exc
        if not path.is_file() or path.is_symlink() or self._is_expired(stat.st_mtime):
            return False
        self._pin_marker(key).write_bytes(b"")
        return True

    def is_pinned(self, key: str) -> bool:
        """Return whether ``key`` carries a pin marker."""
        return self._pin_marker(key).is_file()

    def unpin(self, key: str) -> bool:
        """Drop a pin marker; return whether one existed (TTL cleanup then resumes)."""
        marker = self._pin_marker(key)
        self._path_for_key(key)
        try:
            marker.unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise _storage_error("更新封面缓存失败", "unpin_mikan_poster", exc) from exc

    def put(self, key: str, content_type: str, chunks: Iterable[bytes]) -> Path:
        """Atomically store image chunks; invalid or failed writes leave no partial file."""
        if not isinstance(content_type, str) or not content_type.lower().startswith("image/"):
            raise Stage1Error("invalid_poster", "封面响应不是图片", "save_mikan_poster")
        target = self._path_for_key(key)
        self._ensure_cache_dir()
        temporary: Path | None = None
        total = 0
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".poster-", suffix=".tmp", dir=self._config.cache_dir
            )
            temporary = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as handle:
                for chunk in chunks:
                    if not isinstance(chunk, bytes):
                        raise Stage1Error("invalid_poster", "封面响应无效", "save_mikan_poster")
                    total += len(chunk)
                    if total > self._config.max_bytes:
                        raise Stage1Error("poster_too_large", "封面图片超过大小限制", "save_mikan_poster")
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            temporary = None
            now_timestamp = self._now().timestamp()
            os.utime(target, (now_timestamp, now_timestamp), follow_symlinks=False)
            self.cleanup_expired()
            return target
        except Stage1Error:
            raise
        except OSError as exc:
            raise _storage_error("保存封面缓存失败", "save_mikan_poster", exc) from exc
        finally:
            if temporary is not None:
                with contextlib.suppress(OSError):
                    temporary.unlink(missing_ok=True)

    def cleanup_expired(self) -> None:
        """Occasionally delete only expired regular files inside the cache directory."""
        now = self._now()
        if (
            self._last_cleanup_at is not None
            and (now - self._last_cleanup_at).total_seconds()
            < self._config.cleanup_interval_seconds
        ):
            return
        self._last_cleanup_at = now
        self._ensure_cache_dir()
        try:
            entries = list(self._config.cache_dir.iterdir())
        except OSError as exc:
            raise _storage_error("清理封面缓存失败", "cleanup_mikan_posters", exc) from exc
        for entry in entries:
            # Cache files are exclusively generated as <opaque sha256>.img.
            if not _is_cache_filename(entry.name) or entry.is_symlink() or not entry.is_file():
                continue
            try:
                if self._is_pinned_file(entry) or not self._is_expired(entry.stat().st_mtime):
                    continue
                self._unlink_regular_file(entry)
            except OSError as exc:
                raise _storage_error("清理封面缓存失败", "cleanup_mikan_posters", exc) from exc

    def _pin_marker(self, key: str) -> Path:
        return self._path_for_key(key).with_suffix(POSTER_PIN_SUFFIX)

    def _is_pinned_file(self, path: Path) -> bool:
        return path.with_suffix(POSTER_PIN_SUFFIX).is_file()

    def _path_for_key(self, key: str) -> Path:
        if not _is_cache_key(key):
            raise Stage1Error("invalid_poster_key", "封面缓存标识无效", "mikan_poster_cache")
        root = self._config.cache_dir.resolve(strict=False)
        path = (self._config.cache_dir / f"{key}.img").resolve(strict=False)
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise Stage1Error("invalid_poster_key", "封面缓存标识无效", "mikan_poster_cache") from exc
        return path

    def _ensure_cache_dir(self) -> None:
        try:
            self._config.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise _storage_error("无法创建封面缓存目录", "mikan_poster_cache", exc) from exc
        if not self._config.cache_dir.is_dir():
            raise Stage1Error("storage_error", "封面缓存路径不是目录", "mikan_poster_cache")

    def _is_expired(self, modified_timestamp: float) -> bool:
        return self._now().timestamp() - modified_timestamp > self._config.ttl_seconds

    @staticmethod
    def _unlink_regular_file(path: Path) -> None:
        if path.is_symlink() or not path.is_file():
            return
        path.unlink()


def _is_cache_key(key: object) -> bool:
    return isinstance(key, str) and len(key) == 64 and all(char in "0123456789abcdef" for char in key)


def _is_cache_filename(name: str) -> bool:
    return name.endswith(".img") and _is_cache_key(name.removesuffix(".img"))


def _storage_error(message: str, failed_step: str, exc: OSError) -> Stage1Error:
    return Stage1Error("storage_error", message, failed_step, {"reason": exc.__class__.__name__})


__all__ = [
    "DEFAULT_CLEANUP_INTERVAL_SECONDS",
    "DEFAULT_POSTER_CACHE_DIR",
    "DEFAULT_POSTER_CACHE_TTL_SECONDS",
    "DEFAULT_POSTER_DOWNLOAD_TIMEOUT_SECONDS",
    "DEFAULT_POSTER_MAX_BYTES",
    "MikanPosterCacheConfig",
    "MikanPosterCacheRepository",
    "POSTER_CACHE_VERSION",
    "POSTER_PIN_SUFFIX",
    "poster_cache_key",
]
