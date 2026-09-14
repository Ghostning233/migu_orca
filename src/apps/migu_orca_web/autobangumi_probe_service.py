"""Probe a server-owned Auto Bangumi configuration snapshot.

Only this Web service seam turns a persisted configuration record into a
request-scoped adapter configuration. Capability results are deliberately
process-local: they are safe summaries keyed by the opaque connection
generation and never contain the saved address or credentials.
"""
from __future__ import annotations

from threading import RLock
from uuid import UUID

from ab_engine.controllers.ab_capability_service import (
    probe_capabilities,
    safe_failed_capabilities,
)
from ab_engine.models.management import AutoBangumiCapabilities
from shared.errors import Stage1Error
from storage_engine.controllers.autobangumi_config_repository import (
    AutoBangumiConfigRecord,
    AutoBangumiConfigRepository,
)

_cache_lock = RLock()
_capability_cache: dict[tuple[UUID, int], AutoBangumiCapabilities] = {}


def probe_saved_capabilities(
    repository: AutoBangumiConfigRepository,
    *,
    connection_ref: UUID,
    configuration_revision: int,
) -> AutoBangumiCapabilities:
    """Probe exactly the requested saved configuration generation."""

    with repository.acquire_lease(
        connection_ref=connection_ref,
        configuration_revision=configuration_revision,
    ) as lease:
        record = lease.record
        config = record.config
        if config is None or record.connection_ref is None:
            raise Stage1Error(
                "config_error",
                "Auto Bangumi 配置未配置",
                "probe_saved_autobangumi_capabilities",
            )
        runtime_config = config.to_runtime_config()
        try:
            capabilities = probe_capabilities(runtime_config)
        except Stage1Error as exc:
            if exc.error_type == "config_error":
                raise
            capabilities = safe_failed_capabilities(runtime_config, exc)
        except Exception as exc:
            capabilities = safe_failed_capabilities(
                runtime_config,
                Stage1Error(
                    "ab_management_failed",
                    "Auto Bangumi 能力探测失败",
                    "probe_saved_autobangumi_capabilities",
                    {"reason": exc.__class__.__name__},
                ),
            )
        _store_cached_capabilities(record, capabilities)
        return capabilities


def cached_capabilities(record: AutoBangumiConfigRecord) -> AutoBangumiCapabilities | None:
    """Return a result only for the current configured ref/revision."""

    if record.connection_ref is None or not record.configured:
        return None
    with _cache_lock:
        return _capability_cache.get((record.connection_ref, record.configuration_revision))


def invalidate_saved_capabilities() -> None:
    """Discard all process-local probe results after a config mutation."""

    with _cache_lock:
        _capability_cache.clear()


def _store_cached_capabilities(
    record: AutoBangumiConfigRecord,
    capabilities: AutoBangumiCapabilities,
) -> None:
    if record.connection_ref is None:
        return
    with _cache_lock:
        _capability_cache.clear()
        _capability_cache[(record.connection_ref, record.configuration_revision)] = capabilities


__all__ = [
    "cached_capabilities",
    "invalidate_saved_capabilities",
    "probe_saved_capabilities",
]
