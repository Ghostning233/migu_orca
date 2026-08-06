from __future__ import annotations

from html.parser import HTMLParser
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

from mikan_engine.controllers.mikan_config import MikanConfig
from shared.errors import Stage1Error
from shared.models import BangumiCandidate, MatchedBangumi, RssSource


class MikanTransport(Protocol):
    """Transport boundary for real MiKanProject reads."""

    def get_text(self, url: str, *, timeout: float) -> str:
        """Read text from a MiKanProject URL."""


class UrlopenMikanTransport:
    """urllib-backed transport for real MiKanProject page reads."""

    def get_text(self, url: str, *, timeout: float) -> str:
        request = Request(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": "migu-orca/0.1",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read()
        except HTTPError as exc:
            raise Stage1Error(
                "mikan_http_failed",
                "MiKan HTTP 请求失败",
                "mikan_search",
                {"status_code": exc.code},
            ) from exc
        except URLError as exc:
            reason = getattr(exc, "reason", None)
            if isinstance(reason, TimeoutError):
                raise Stage1Error(
                    "mikan_timeout",
                    "MiKan HTTP 请求超时",
                    "mikan_search",
                    {"category": "timeout"},
                ) from exc
            raise Stage1Error(
                "mikan_connection_failed",
                "MiKan HTTP 连接失败",
                "mikan_search",
                {"category": "connection"},
            ) from exc
        except TimeoutError as exc:
            raise Stage1Error(
                "mikan_timeout",
                "MiKan HTTP 请求超时",
                "mikan_search",
                {"category": "timeout"},
            ) from exc

        try:
            return body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise Stage1Error(
                "mikan_parse_failed",
                "MiKan 搜索页编码无法解析",
                "mikan_search",
            ) from exc


class MikanClient:
    """Real MiKanProject adapter boundary.

    The client only accepts explicit MiKan config plus domain inputs. Concrete
    HTTP search and page parsing are implemented behind this seam in later
    Stage 5 stories.
    """

    def __init__(
        self,
        config: MikanConfig,
        *,
        transport: MikanTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport or UrlopenMikanTransport()

    @property
    def config(self) -> MikanConfig:
        return self._config

    @property
    def transport(self) -> MikanTransport:
        return self._transport

    def list_bangumi_candidates(self, raw_title: str) -> list[BangumiCandidate]:
        normalized_title = raw_title.strip()
        if not normalized_title:
            raise Stage1Error("invalid_input", "番剧名称不能为空", "mikan_search")
        search_url = _build_search_url(
            self._config.search_endpoint,
            normalized_title,
        )
        html = self._transport.get_text(
            search_url,
            timeout=self._config.timeout_seconds,
        )
        return _parse_search_candidates(html, self._config.search_endpoint)

    def list_rss_sources(self, matched_bangumi: MatchedBangumi) -> list[RssSource]:
        if not matched_bangumi.mikan_url.strip():
            raise Stage1Error(
                "invalid_input",
                "MiKan 番剧页 URL 不能为空",
                "mikan_list_rss_sources",
            )
        raise Stage1Error(
            "mikan_not_implemented",
            "真实 MiKan RSS 源发现尚未实现",
            "mikan_list_rss_sources",
        )


def create_mikan_client(
    config: MikanConfig,
    *,
    transport: MikanTransport | None = None,
) -> MikanClient:
    """Build the real MiKan client from explicit MiKan config."""

    return MikanClient(config, transport=transport)


def _build_search_url(search_endpoint: str, raw_title: str) -> str:
    parsed = urlparse(search_endpoint)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("searchstr", raw_title))
    return urlunparse(parsed._replace(query=urlencode(query)))


def _parse_search_candidates(html: str, search_endpoint: str) -> list[BangumiCandidate]:
    parser = _MikanSearchParser(search_endpoint)
    try:
        parser.feed(html)
    except Exception as exc:
        raise Stage1Error(
            "mikan_parse_failed",
            "MiKan 搜索页解析失败",
            "mikan_search",
        ) from exc

    candidates = parser.candidates()
    if not candidates:
        raise Stage1Error(
            "mikan_parse_failed",
            "MiKan 搜索页未找到番剧候选",
            "mikan_search",
        )
    return candidates


class _MikanSearchParser(HTMLParser):
    def __init__(self, search_endpoint: str) -> None:
        super().__init__(convert_charrefs=True)
        self._base_url = search_endpoint
        self._active_href: str | None = None
        self._active_title: str | None = None
        self._active_text: list[str] = []
        self._raw_candidates: list[tuple[str, str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attr_map = {name.lower(): value for name, value in attrs if value is not None}
        href = attr_map.get("href", "")
        if "/Home/Bangumi/" not in href:
            return
        self._active_href = href
        self._active_title = attr_map.get("title")
        self._active_text = []

    def handle_data(self, data: str) -> None:
        if self._active_href is not None:
            self._active_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._active_href is None:
            return
        title = " ".join("".join(self._active_text).split())
        self._raw_candidates.append((self._active_href, title, self._active_title))
        self._active_href = None
        self._active_title = None
        self._active_text = []

    def candidates(self) -> list[BangumiCandidate]:
        candidates: list[BangumiCandidate] = []
        seen_ids: set[str] = set()
        for href, title, title_attr in self._raw_candidates:
            bangumi_id = _extract_bangumi_id(href)
            if bangumi_id is None or bangumi_id in seen_ids:
                continue

            names = [_clean_title(title), _clean_title(title_attr or "")]
            names = [name for name in names if name]
            if not names:
                continue

            canonical_title = names[0]
            aliases = _unique([name for name in names[1:] if name != canonical_title])
            candidates.append(
                BangumiCandidate(
                    bangumi_id=bangumi_id,
                    title=canonical_title,
                    aliases=aliases,
                    mikan_url=urljoin(self._base_url, href),
                    rss_sources=[],
                )
            )
            seen_ids.add(bangumi_id)
        return candidates


def _extract_bangumi_id(href: str) -> str | None:
    marker = "/Home/Bangumi/"
    if marker not in href:
        return None
    remainder = href.split(marker, 1)[1]
    bangumi_id = remainder.split("?", 1)[0].split("#", 1)[0].strip("/")
    if not bangumi_id:
        return None
    return bangumi_id


def _clean_title(value: str) -> str:
    return " ".join(value.split()).strip()


def _unique(values: list[str]) -> list[str]:
    unique_values: list[str] = []
    for value in values:
        if value not in unique_values:
            unique_values.append(value)
    return unique_values
