"""Process-wide MiKan poster cache service (issue #84).

Candidate search and saved tracking covers must resolve through the *same*
service instance: candidate serialization registers the server-parsed upstream
URL here, the poster route downloads and caches the bytes under an opaque key,
and a saved plan pins that key so the cover keeps being served after a restart.
Upstream image addresses never leave this registry and are never persisted.
"""
from __future__ import annotations

from mikan_engine.controllers.mikan_poster_service import MikanPosterService

poster_service = MikanPosterService()

__all__ = ["poster_service"]
