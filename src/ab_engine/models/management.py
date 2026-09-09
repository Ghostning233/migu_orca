"""Request-scoped Auto Bangumi management models.

The objects in this module are deliberately separate from API/storage DTOs.
Only the projection helpers may cross the management adapter boundary.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

CapabilityState = Literal["SUPPORTED", "UNSUPPORTED", "UNKNOWN"]
ProbeStatus = Literal["VERIFIED", "PARTIAL", "FAILED"]


@dataclass(frozen=True)
class AutoBangumiCapabilities:
    probe_status: ProbeStatus
    version: str | None
    adapter: Literal["legacy_3_1", "api_token"] | None
    subscription_list: CapabilityState
    subscription_detail: CapabilityState
    subscription_modify: CapabilityState = "UNKNOWN"
    subscription_enable: CapabilityState = "UNKNOWN"
    subscription_disable: CapabilityState = "UNKNOWN"
    subscription_delete: CapabilityState = "UNKNOWN"
    rss_list: CapabilityState = "UNKNOWN"
    rss_modify: CapabilityState = "UNKNOWN"
    rss_enable: CapabilityState = "UNKNOWN"
    rss_disable: CapabilityState = "UNKNOWN"
    rss_delete: CapabilityState = "UNKNOWN"
    rss_refresh: CapabilityState = "UNKNOWN"
    external_verify: CapabilityState = "UNKNOWN"
    checked_at: str | None = None
    safe_message: str | None = None

    def to_public_dict(self) -> dict[str, object]:
        """Return the stable capability contract; never expose adapter internals."""
        return {
            "probe_status": self.probe_status,
            "version": self.version,
            "adapter": self.adapter,
            "subscription_list": self.subscription_list,
            "subscription_detail": self.subscription_detail,
            "subscription_modify": self.subscription_modify,
            "subscription_enable": self.subscription_enable,
            "subscription_disable": self.subscription_disable,
            "subscription_delete": self.subscription_delete,
            "rss_list": self.rss_list,
            "rss_modify": self.rss_modify,
            "rss_enable": self.rss_enable,
            "rss_disable": self.rss_disable,
            "rss_delete": self.rss_delete,
            "rss_refresh": self.rss_refresh,
            "external_verify": self.external_verify,
            "checked_at": self.checked_at,
            "safe_message": self.safe_message,
        }


@dataclass(frozen=True, repr=False)
class ExternalSubscription:
    """Raw-ish, bounded data usable only during one adapter request."""

    external_id: str
    title: str
    season: int | None
    subtitle_group: str | None
    rss_urls: tuple[str, ...] = ()
    rss_ids: tuple[str, ...] = ()
    deleted: bool = False
    enabled: bool = True
    # Request-scoped complete Auto Bangumi BangumiUpdate projection.  This is
    # never persisted; it lets the writer retain fields not exposed by our
    # public patch DTO.
    upstream_fields: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def __repr__(self) -> str:
        return (
            f"ExternalSubscription(external_id={self.external_id!r}, title={self.title!r}, season={self.season!r}, "
            f"subtitle_group={self.subtitle_group!r}, rss_count={len(self.rss_ids)!r}, deleted={self.deleted!r})"
        )

    def safe_projection(self) -> ExternalSubscriptionProjection:
        return ExternalSubscriptionProjection(
            external_id=self.external_id,
            title=self.title,
            season=self.season,
            subtitle_group=self.subtitle_group,
            deleted=self.deleted,
            rss_count=len(self.rss_ids) or len(self.rss_urls),
        )


@dataclass(frozen=True)
class ExternalSubscriptionProjection:
    external_id: str
    title: str
    season: int | None
    subtitle_group: str | None
    deleted: bool
    rss_count: int


@dataclass(frozen=True, repr=False)
class ExternalRss:
    external_id: str
    name: str | None
    url: str = ""
    aggregate: bool = False
    parser: str | None = None
    enabled: bool = True
    upstream_fields: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def __repr__(self) -> str:
        return f"ExternalRss(external_id={self.external_id!r}, name={self.name!r}, aggregate={self.aggregate!r}, parser={self.parser!r}, enabled={self.enabled!r})"

    def safe_projection(self) -> ExternalRssProjection:
        return ExternalRssProjection(self.external_id, self.name, self.aggregate, self.parser, self.enabled)


@dataclass(frozen=True)
class ExternalRssProjection:
    external_id: str
    name: str | None
    aggregate: bool
    parser: str | None
    enabled: bool
