"""Trusted, same-origin retrieval for MiKan poster cache entries."""
from __future__ import annotations

import socket
from collections.abc import Callable
from ipaddress import ip_address
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from mikan_engine.controllers.mikan_poster_cache import (
    MikanPosterCacheConfig,
    MikanPosterCacheRepository,
    poster_cache_key,
)
from shared.errors import Stage1Error

_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


class MikanPosterService:
    """Register parser-produced sources and retrieve them under opaque keys.

    Source URLs deliberately live only in this process-local registry.  They are
    never persisted alongside cached bytes and cannot be supplied by a route
    caller.
    """

    def __init__(
        self,
        config: MikanPosterCacheConfig | None = None,
        *,
        resolve: Callable[[str, int], object] = socket.getaddrinfo,
        open_request: Callable[[Request, float], object] | None = None,
    ) -> None:
        cache_config = config or MikanPosterCacheConfig()
        self._cache = MikanPosterCacheRepository(cache_config)
        self._download_timeout_seconds = cache_config.download_timeout_seconds
        self._sources: dict[str, str] = {}
        self._resolve = resolve
        self._open_request = open_request or _open_without_redirects

    def register(self, poster_url: str | None) -> str | None:
        if poster_url is None:
            return None
        if not _is_http_url(poster_url):
            return None
        key = poster_cache_key(poster_url)
        self._sources[key] = poster_url
        return key

    def get(self, key: str) -> tuple[Path, str]:
        cached = self._cache.get(key)
        if cached is not None:
            return cached, _content_type_for_bytes(cached.read_bytes())
        source = self._sources.get(key)
        if source is None:
            raise Stage1Error("poster_not_found", "封面暂不可用", "get_mikan_poster")
        self._validate_public_source(source)
        request = Request(source, headers={"Accept": "image/jpeg,image/png,image/gif,image/webp"})
        try:
            response = self._open_request(request, self._download_timeout_seconds)
            with response:
                content_type = str(response.headers.get_content_type()).lower()
                if content_type not in _IMAGE_TYPES:
                    raise Stage1Error("invalid_poster", "封面响应不是支持的图片", "get_mikan_poster")
                path = self._cache.put(key, content_type, _iter_chunks(response))
        except Stage1Error:
            raise
        except (HTTPError, URLError, OSError, TimeoutError, ValueError) as exc:
            raise Stage1Error("poster_unavailable", "封面暂不可用", "get_mikan_poster", {"reason": exc.__class__.__name__}) from exc
        return path, content_type

    def _validate_public_source(self, source: str) -> None:
        parsed = urlparse(source)
        host = parsed.hostname
        if not host or parsed.username or parsed.password or parsed.port not in {80, 443, None}:
            raise Stage1Error("invalid_poster", "封面地址无效", "get_mikan_poster")
        try:
            addresses = self._resolve(host, parsed.port or (443 if parsed.scheme == "https" else 80))
        except OSError as exc:
            raise Stage1Error("poster_unavailable", "封面暂不可用", "get_mikan_poster", {"reason": exc.__class__.__name__}) from exc
        if not addresses or any(not ip_address(entry[4][0]).is_global for entry in addresses):
            raise Stage1Error("invalid_poster", "封面地址无效", "get_mikan_poster")


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and not parsed.username and not parsed.password


def _open_without_redirects(request: Request, timeout: float) -> object:
    class _RejectRedirects(HTTPRedirectHandler):
        def redirect_request(self, *args: object, **kwargs: object) -> Request | None:
            return None

    return build_opener(_RejectRedirects).open(request, timeout=timeout)


def _iter_chunks(response: object) -> object:
    while chunk := response.read(64 * 1024):
        yield chunk


def _content_type_for_bytes(payload: bytes) -> str:
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if payload.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if payload.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return "image/webp"
    raise Stage1Error("invalid_poster", "封面缓存无效", "get_mikan_poster")
