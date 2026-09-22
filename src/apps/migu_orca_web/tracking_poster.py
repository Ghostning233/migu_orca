"""Durable cover references for saved tracking plans (issue #84).

A tracking summary may only ever reference a same-origin opaque poster route.
This module turns the server-parsed MiKan cover URL carried by a Request
snapshot into that reference and keeps the cached bytes alive, so "我的追番" can
show the same cover after a restart without exposing the upstream address.

Every failure degrades to "no cover" (``None``): losing a cover must never fail
or delay saving a confirmed plan, and the client renders its stable placeholder.
"""
from __future__ import annotations

from typing import Any

from apps.migu_orca_web.poster_runtime import poster_service
from mikan_engine.controllers.mikan_poster_service import MikanPosterService
from shared.errors import Stage1Error

#: Same-origin opaque route served by the mikan blueprint.
POSTER_PATH_PREFIX = "/api/v1/mikan/posters/"


def poster_path_for_key(key: str) -> str:
    """Return the same-origin opaque poster route for a cache key."""
    return f"{POSTER_PATH_PREFIX}{key}"


def poster_path_for_url(
    poster_url: str | None,
    *,
    service: MikanPosterService | None = None,
) -> str | None:
    """Return the durable same-origin cover reference for an upstream URL.

    The URL is registered with the shared poster service so the route can still
    fetch it on first view, and its already-cached bytes are pinned so the cover
    outlives the candidate-cache TTL.  An unusable URL yields ``None``.
    """
    if not isinstance(poster_url, str) or not poster_url.strip():
        return None
    try:
        key = (service or poster_service).persist(poster_url)
    except Stage1Error:
        return None
    if key is None:
        return None
    return poster_path_for_key(key)


def request_poster_path(
    request: dict[str, Any] | None,
    *,
    service: MikanPosterService | None = None,
) -> str | None:
    """Return the durable cover reference for one Request snapshot."""
    if not isinstance(request, dict):
        return None
    source_info = request.get("source_info")
    matched = source_info.get("matched_bangumi") if isinstance(source_info, dict) else None
    if not isinstance(matched, dict):
        return None
    return poster_path_for_url(matched.get("poster_url"), service=service)


__all__ = [
    "POSTER_PATH_PREFIX",
    "poster_path_for_key",
    "poster_path_for_url",
    "request_poster_path",
]
