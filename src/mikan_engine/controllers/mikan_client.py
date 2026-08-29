from __future__ import annotations

import re
from codecs import getincrementaldecoder
from dataclasses import dataclass, field
from html.parser import HTMLParser
from time import monotonic
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

from mikan_engine.controllers.mikan_config import MikanConfig
from shared.errors import Stage1Error
from shared.models import BangumiCandidate, MatchedBangumi, RssSource

# MiKan search pages can include large episode result tables in addition to
# bangumi candidates. Keep a bounded read, but allow broad queries to finish.
MAX_MIKAN_RESPONSE_BYTES = 8_000_000
MIKAN_READ_CHUNK_BYTES = 64 * 1024
MAX_MIKAN_STREAM_SECONDS = 60.0


class MikanResponseTooLargeError(Exception):
    """Raised when a MiKan response exceeds the bounded read limit."""


class MikanPartialResponseError(Exception):
    """Raised when a MiKan read times out after receiving partial content."""

    def __init__(self, body: bytes) -> None:
        self.body = body


@dataclass(frozen=True)
class MikanEpisodeSummary:
    title: str
    episode_url: str


@dataclass(frozen=True)
class MikanSubgroupDetail:
    name: str
    rss_url: str | None
    episodes: list[MikanEpisodeSummary]


@dataclass(frozen=True)
class MikanBangumiDetail:
    bangumi_id: str
    title: str
    mikan_url: str
    broadcast_start: str | None
    poster_url: str | None
    bangumi_rss_url: str | None
    subgroups: list[MikanSubgroupDetail]
    total_episodes: int | None = None


@dataclass(frozen=True)
class MikanCandidate:
    """A visible MiKan search candidate collection card.

    Only public candidate metadata is stored: the bangumi id, display title,
    normalized absolute bangumi URL, optional public poster URL, the query that
    produced the search, and optional aliases. Raw HTML, raw RSS XML, cookies,
    tokens, and full failed URLs never appear on this model.
    """

    bangumi_id: str
    title: str
    mikan_url: str
    source_query: str
    poster_url: str | None = None
    total_episodes: int | None = None
    aliases: list[str] = field(default_factory=list)


class MikanTransport(Protocol):
    """Transport boundary for real MiKanProject reads."""

    def get_text(self, url: str, *, timeout: float) -> str:
        """Read text from a MiKanProject URL."""


class UrlopenMikanTransport:
    """urllib-backed transport for real MiKanProject page reads."""

    def get_text(self, url: str, *, timeout: float) -> str:
        return self._get_text(url, timeout=timeout)

    def get_search_text(self, url: str, *, timeout: float) -> str:
        """Read a search page until its complete candidate region when possible.

        MiKan search pages append potentially large episode tables after the
        related-candidate section.  The detector is deliberately conservative:
        it only stops after seeing a candidate link and the matching section
        close tag.  Missing or malformed markers therefore retain the normal
        bounded full-read behavior.
        """

        detector = _MikanCandidateSectionDetector()
        return self._get_text(url, timeout=timeout, stop_detector=detector)

    def _get_text(
        self,
        url: str,
        *,
        timeout: float,
        stop_detector: _MikanCandidateSectionDetector | None = None,
    ) -> str:
        started_at = monotonic()
        max_deadline = started_at + MAX_MIKAN_STREAM_SECONDS
        deadline = min(started_at + timeout, max_deadline)
        request = Request(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": "migu-orca/0.1",
            },
            method="GET",
        )
        with urlopen(request, timeout=timeout) as response:
            chunks: list[bytes] = []
            total = 0
            while True:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    if chunks:
                        raise MikanPartialResponseError(b"".join(chunks))
                    raise TimeoutError
                _set_response_timeout(response, remaining)
                try:
                    chunk = _read_response_chunk(
                        response,
                        min(
                            MIKAN_READ_CHUNK_BYTES,
                            MAX_MIKAN_RESPONSE_BYTES + 1 - total,
                        ),
                    )
                except TimeoutError:
                    if chunks:
                        raise MikanPartialResponseError(b"".join(chunks)) from None
                    raise
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > MAX_MIKAN_RESPONSE_BYTES:
                    raise MikanResponseTooLargeError
                if stop_detector is not None and stop_detector.feed(chunk):
                    break
                deadline = min(monotonic() + timeout, max_deadline)
            body = b"".join(chunks)
        if len(body) > MAX_MIKAN_RESPONSE_BYTES:
            raise MikanResponseTooLargeError
        return body.decode("utf-8")


class _MikanCandidateSectionDetector(HTMLParser):
    """Incrementally recognize a complete ``related-recommendations`` section.

    HTMLParser retains incomplete tags across ``feed`` calls, while the
    incremental decoder retains partial UTF-8 code points.  This makes the
    early-stop boundary safe when either HTML markers or Chinese text cross a
    network chunk boundary.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._decoder = getincrementaldecoder("utf-8")("strict")
        self._section_depth = 0
        self._saw_candidate = False
        self.complete = False

    def feed(self, chunk: bytes) -> bool:  # type: ignore[override]
        if self.complete:
            return True
        super().feed(self._decoder.decode(chunk))
        return self.complete

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.lower()
        attr_map = {name.lower(): value for name, value in attrs if value is not None}
        if self._section_depth == 0:
            classes = set(attr_map.get("class", "").split())
            if tag_name == "section" and "related-recommendations" in classes:
                self._section_depth = 1
            return
        if tag_name == "section":
            self._section_depth += 1
        elif tag_name == "a" and _extract_bangumi_id(attr_map.get("href", "")) is not None:
            self._saw_candidate = True

    def handle_endtag(self, tag: str) -> None:
        if self._section_depth == 0 or tag.lower() != "section":
            return
        self._section_depth -= 1
        if self._section_depth == 0 and self._saw_candidate:
            self.complete = True


def _set_response_timeout(response: object, timeout: float) -> None:
    fp = getattr(response, "fp", None)
    raw = getattr(fp, "raw", None)
    sock = getattr(raw, "_sock", None)
    if sock is not None:
        sock.settimeout(timeout)


def _read_response_chunk(response: object, size: int) -> bytes:
    read1 = getattr(response, "read1", None)
    if callable(read1):
        return read1(size)
    read = getattr(response, "read")
    return read(size)


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
        html = _read_mikan_search_text(
            self._transport, search_url, timeout=self._config.timeout_seconds
        )
        return _parse_search_candidates(html, self._config.search_endpoint)

    def search_candidates(self, raw_title: str) -> list[MikanCandidate]:
        """Search MiKan and return sanitized visible candidate cards.

        The search is request-scoped and explicit: it requires a non-empty title
        and reads the configured MiKan search page through the transport seam.
        The page is treated as candidate discovery only; the returned candidates
        are never auto-selected.
        """
        normalized_title = raw_title.strip()
        if not normalized_title:
            raise Stage1Error("invalid_input", "番剧名称不能为空", "mikan_search")
        search_url = _build_search_url(
            self._config.search_endpoint,
            normalized_title,
        )
        html = _read_mikan_search_text(
            self._transport, search_url, timeout=self._config.timeout_seconds
        )
        return _parse_candidate_cards(
            html,
            self._config.search_endpoint,
            normalized_title,
        )

    def list_rss_sources(self, matched_bangumi: MatchedBangumi) -> list[RssSource]:
        mikan_url = matched_bangumi.mikan_url.strip()
        if not mikan_url:
            raise Stage1Error(
                "invalid_input",
                "MiKan 番剧页 URL 不能为空",
                "mikan_list_rss_sources",
            )
        html = _read_mikan_text(
            self._transport,
            mikan_url,
            timeout=self._config.timeout_seconds,
            failed_step="mikan_list_rss_sources",
        )
        return _parse_bangumi_rss_sources(html, mikan_url)

    def get_direct_bangumi_detail(self, direct_entry: str) -> MikanBangumiDetail:
        mikan_url = _direct_bangumi_url(direct_entry, self._config)
        html = _read_mikan_text(
            self._transport,
            mikan_url,
            timeout=self._config.timeout_seconds,
            failed_step="mikan_bangumi_detail",
        )
        return _parse_bangumi_detail(html, mikan_url)

    def get_bangumi_detail(self, matched_bangumi: MatchedBangumi) -> MikanBangumiDetail:
        mikan_url = matched_bangumi.mikan_url.strip()
        if not mikan_url:
            raise Stage1Error(
                "invalid_input",
                "MiKan 番剧页 URL 不能为空",
                "mikan_bangumi_detail",
            )
        html = _read_mikan_text(
            self._transport,
            mikan_url,
            timeout=self._config.timeout_seconds,
            failed_step="mikan_bangumi_detail",
        )
        return _parse_bangumi_detail(html, mikan_url)

    def list_rss_sources_from_detail(
        self,
        detail: MikanBangumiDetail,
    ) -> list[RssSource]:
        sources = _rss_sources_from_bangumi_detail(detail)
        if not sources:
            raise Stage1Error(
                "mikan_parse_failed",
                "MiKan 番剧页未找到 RSS 源",
                "mikan_list_rss_sources",
            )
        return sources


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


def _direct_bangumi_url(direct_entry: str, config: MikanConfig) -> str:
    value = direct_entry.strip()
    if not value:
        raise _invalid_direct_entry("mikan_bangumi")
    if _is_bangumi_id(value):
        return _direct_bangumi_url_from_id(value, config)
    return _validated_direct_bangumi_url(value, config)


def _direct_bangumi_url_from_id(bangumi_id: str, config: MikanConfig) -> str:
    base = urlparse(config.search_endpoint)
    if base.scheme not in {"http", "https"} or not base.netloc:
        raise Stage1Error(
            "config_error",
            "MiKan search_endpoint 无法派生番剧页 URL",
            "mikan_direct_entry",
            {"field": "search_endpoint"},
        )
    return urlunparse(
        (
            base.scheme,
            base.netloc,
            f"/Home/Bangumi/{bangumi_id}",
            "",
            "",
            "",
        )
    )


def _validated_direct_bangumi_url(value: str, config: MikanConfig) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise _invalid_direct_entry("mikan_bangumi")

    config_origin = urlparse(config.search_endpoint)
    if (
        config_origin.scheme not in {"http", "https"}
        or not config_origin.netloc
        or parsed.netloc.casefold() != config_origin.netloc.casefold()
    ):
        raise _invalid_direct_entry("mikan_bangumi")

    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) != 3:
        raise _invalid_direct_entry("mikan_bangumi")
    if [part.casefold() for part in path_parts[:2]] != ["home", "bangumi"]:
        raise _invalid_direct_entry("mikan_bangumi")
    bangumi_id = path_parts[2]
    if not _is_bangumi_id(bangumi_id):
        raise _invalid_direct_entry("mikan_bangumi")

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            f"/Home/Bangumi/{bangumi_id}",
            "",
            "",
            "",
        )
    )


def _invalid_direct_entry(field: str) -> Stage1Error:
    return Stage1Error(
        "invalid_input",
        "MiKan bangumi 直连入口必须是数字 ID 或 Home/Bangumi URL",
        "mikan_direct_entry",
        {"field": field},
    )


def _is_bangumi_id(value: str) -> bool:
    return value.isascii() and value.isdecimal()


def _read_mikan_text(
    transport: MikanTransport,
    url: str,
    *,
    timeout: float,
    failed_step: str,
) -> str:
    try:
        return transport.get_text(url, timeout=timeout)
    except HTTPError as exc:
        raise _mikan_http_failed(failed_step, exc.code) from exc
    except URLError as exc:
        raise _mikan_network_error(failed_step, exc) from exc
    except TimeoutError as exc:
        raise _mikan_timeout(failed_step) from exc
    except ConnectionError as exc:
        raise _mikan_connection_failed(failed_step) from exc
    except UnicodeDecodeError as exc:
        raise _mikan_parse_failed(failed_step, "encoding") from exc
    except MikanResponseTooLargeError as exc:
        raise _mikan_parse_failed(failed_step, "response_too_large") from exc
    except MikanPartialResponseError as exc:
        if failed_step == "mikan_search":
            try:
                return exc.body.decode("utf-8")
            except UnicodeDecodeError as decode_error:
                raise _mikan_parse_failed(failed_step, "encoding") from decode_error
        raise _mikan_timeout(failed_step) from exc
    except Stage1Error as exc:
        raise _sanitize_mikan_stage_error(exc, failed_step) from exc


def _read_mikan_search_text(
    transport: MikanTransport,
    url: str,
    *,
    timeout: float,
) -> str:
    """Use candidate-aware streaming when the transport provides it.

    Test and integration transports only promise ``get_text``; retaining that
    fallback keeps the transport seam backwards-compatible and bounded.
    """

    get_search_text = getattr(transport, "get_search_text", None)
    if callable(get_search_text):
        class _SearchTransport:
            def get_text(self, request_url: str, *, timeout: float) -> str:
                return get_search_text(request_url, timeout=timeout)

        return _read_mikan_text(
            _SearchTransport(), url, timeout=timeout, failed_step="mikan_search"
        )
    return _read_mikan_text(transport, url, timeout=timeout, failed_step="mikan_search")


def _sanitize_mikan_stage_error(error: Stage1Error, failed_step: str) -> Stage1Error:
    if error.error_type == "mikan_http_failed":
        status_code = error.details.get("status_code")
        return _mikan_http_failed(
            failed_step,
            status_code if isinstance(status_code, int) else None,
        )
    if error.error_type == "mikan_timeout":
        return _mikan_timeout(failed_step)
    if error.error_type == "mikan_connection_failed":
        return _mikan_connection_failed(failed_step)
    if error.error_type == "mikan_parse_failed":
        category = error.details.get("category")
        return _mikan_parse_failed(
            failed_step,
            category if isinstance(category, str) else None,
        )
    return error


def _mikan_network_error(failed_step: str, error: URLError) -> Stage1Error:
    reason = getattr(error, "reason", None)
    if isinstance(reason, TimeoutError):
        return _mikan_timeout(failed_step)
    return _mikan_connection_failed(failed_step)


def _mikan_http_failed(failed_step: str, status_code: int | None) -> Stage1Error:
    details = {"status_code": status_code} if status_code is not None else {}
    return Stage1Error(
        "mikan_http_failed",
        "MiKan HTTP 请求失败",
        failed_step,
        details,
    )


def _mikan_connection_failed(failed_step: str) -> Stage1Error:
    return Stage1Error(
        "mikan_connection_failed",
        "MiKan HTTP 连接失败",
        failed_step,
        {"category": "connection"},
    )


def _mikan_timeout(failed_step: str) -> Stage1Error:
    return Stage1Error(
        "mikan_timeout",
        "MiKan HTTP 请求超时",
        failed_step,
        {"category": "timeout"},
    )


def _mikan_parse_failed(failed_step: str, category: str | None = None) -> Stage1Error:
    details = {"category": category} if category is not None else {}
    return Stage1Error(
        "mikan_parse_failed",
        "MiKan 页面解析失败",
        failed_step,
        details,
    )


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


def _parse_candidate_cards(
    html: str,
    search_endpoint: str,
    source_query: str,
) -> list[MikanCandidate]:
    parser = _MikanCandidatePageParser(search_endpoint, source_query)
    try:
        parser.feed(html)
    except Exception as exc:
        raise Stage1Error(
            "mikan_parse_failed",
            "MiKan 搜索页解析失败",
            "mikan_search",
        ) from exc
    return parser.candidates()


def _parse_bangumi_rss_sources(html: str, bangumi_url: str) -> list[RssSource]:
    parser = _MikanBangumiPageParser(bangumi_url)
    try:
        parser.feed(html)
    except Exception as exc:
        raise Stage1Error(
            "mikan_parse_failed",
            "MiKan 番剧页解析失败",
            "mikan_list_rss_sources",
        ) from exc

    detail = parser.bangumi_detail()
    sources = _rss_sources_from_bangumi_detail(detail) if detail is not None else []
    if not sources:
        raise Stage1Error(
            "mikan_parse_failed",
            "MiKan 番剧页未找到 RSS 源",
            "mikan_list_rss_sources",
    )
    return sources


def _rss_sources_from_bangumi_detail(
    detail: MikanBangumiDetail | None,
) -> list[RssSource]:
    if detail is None:
        return []

    sources: list[RssSource] = []
    seen_urls: set[str] = set()
    for subgroup in detail.subgroups:
        rss_url = subgroup.rss_url
        if rss_url is None or rss_url in seen_urls:
            continue
        sources.append(
            RssSource(
                subtitle_group=subgroup.name,
                rss_url=rss_url,
                source_type="mikan_http",
                fixture_path="",
            )
        )
        seen_urls.add(rss_url)

    if sources:
        return sources

    if detail.bangumi_rss_url is None:
        return []
    return [
        RssSource(
            subtitle_group="全部字幕组",
            rss_url=detail.bangumi_rss_url,
            source_type="mikan_http",
            fixture_path="",
        )
    ]


def _parse_bangumi_detail(html: str, bangumi_url: str) -> MikanBangumiDetail:
    parser = _MikanBangumiPageParser(bangumi_url)
    try:
        parser.feed(html)
    except Exception as exc:
        raise Stage1Error(
            "mikan_parse_failed",
            "MiKan 番剧页解析失败",
            "mikan_bangumi_detail",
        ) from exc

    detail = parser.bangumi_detail()
    if detail is None:
        raise Stage1Error(
            "mikan_parse_failed",
            "MiKan 番剧页未找到可用 RSS",
            "mikan_bangumi_detail",
        )
    return detail


_TOTAL_EPISODE_ATTRS = frozenset(
    {"data-total-episodes", "data-total-episode", "data-episodes-total"}
)
_TOTAL_EPISODE_TEXT = re.compile(
    r"(?:总集数|共|全)\s*[：:]?\s*([1-9]\d{0,3})\s*集"
)


def _validated_total_episodes(value: str | None) -> int | None:
    """Return an explicitly supplied public total, never an inferred count."""
    if value is None or not re.fullmatch(r"[1-9]\d{0,3}", value.strip()):
        return None
    return int(value)


def _total_episodes_from_attrs(attrs: dict[str, str]) -> int | None:
    for name in _TOTAL_EPISODE_ATTRS:
        total = _validated_total_episodes(attrs.get(name))
        if total is not None:
            return total
    return None


def _total_episodes_from_public_text(text: str) -> int | None:
    """Read only an explicit labelled total from visible candidate metadata."""
    match = _TOTAL_EPISODE_TEXT.search(" ".join(text.split()))
    return _validated_total_episodes(match.group(1)) if match is not None else None


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


class _MikanCandidatePageParser(HTMLParser):
    """Parse visible MiKan search candidate cards into sanitized models.

    Candidate cards are scoped to their container elements (``.bangumi-item``,
    ``.search-result``, ``.sk-bangumi``, ``.an-card``, ``.related-item``, etc.)
    so the ``相关推荐`` and equivalent search sections are covered without
    depending on a single page layout. Every candidate URL is normalized to an
    absolute HTTP(S) bangumi URL; traversal, empty or non-numeric ids, wrong
    paths, and non-HTTP(S) schemes are silently rejected. Cards are returned in
    page order and deduplicated by ``bangumi_id``.
    """

    def __init__(self, base_url: str, source_query: str) -> None:
        super().__init__(convert_charrefs=True)
        self._base_url = base_url
        self._source_query = source_query
        self._tag_stack: list[tuple[str, bool]] = []
        self._card_depth = 0
        self._current_card: _MikanCandidateCard | None = None
        self._cards: list[_MikanCandidateCard] = []
        self._active_href: str | None = None
        self._active_title_attr: str | None = None
        self._active_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.lower()
        attr_map = {name.lower(): value for name, value in attrs if value is not None}
        classes = set(attr_map.get("class", "").split())

        if tag_name == "a":
            normalized = _candidate_bangumi_url(attr_map.get("href", ""), self._base_url)
            if normalized is not None:
                if self._card_depth == 0:
                    self._current_card = _MikanCandidateCard()
                    self._current_card.href = normalized
                if self._current_card is not None and self._current_card.href is None:
                    self._current_card.href = normalized
                self._active_href = normalized
                self._active_title_attr = attr_map.get("title")
                self._active_text = []
        elif self._current_card is not None and tag_name in {"img", "span"}:
            if self._current_card is not None and self._current_card.poster_url is None:
                poster_url = _poster_url_from_attrs(attr_map, self._base_url)
                if poster_url is not None:
                    self._current_card.poster_url = poster_url

        is_container = _is_candidate_card_container(tag_name, classes)
        if is_container:
            if self._card_depth == 0:
                self._current_card = _MikanCandidateCard()
            self._card_depth += 1
        if self._current_card is not None and self._current_card.total_episodes is None:
            self._current_card.total_episodes = _total_episodes_from_attrs(attr_map)
        if tag_name not in _HTML_VOID_ELEMENTS:
            self._tag_stack.append((tag_name, is_container))

    def handle_data(self, data: str) -> None:
        if self._active_href is not None:
            self._active_text.append(data)
        if self._current_card is not None and self._card_depth > 0:
            self._current_card.metadata_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name == "a" and self._active_href is not None:
            if self._current_card is not None and self._current_card.title is None:
                title = _clean_title(" ".join(self._active_text))
                if title:
                    self._current_card.title = title
                    self._current_card.title_attr = _clean_title(
                        self._active_title_attr or ""
                    )
            self._active_href = None
            self._active_title_attr = None
            self._active_text = []
            if self._card_depth == 0 and self._current_card is not None:
                card = self._current_card
                self._current_card = None
                if card.href is not None:
                    self._cards.append(card)

        if self._tag_stack and self._tag_stack[-1][0] == tag_name:
            _, is_container = self._tag_stack.pop()
            if is_container:
                if self._card_depth > 0:
                    self._card_depth -= 1
                if self._card_depth == 0:
                    card = self._current_card
                    self._current_card = None
                    if card is not None and card.href is not None:
                        self._cards.append(card)

    def candidates(self) -> list[MikanCandidate]:
        candidates: list[MikanCandidate] = []
        seen_ids: set[str] = set()
        for card in self._cards:
            if card.href is None:
                continue
            bangumi_id = _extract_bangumi_id(card.href)
            if bangumi_id is None or bangumi_id in seen_ids:
                continue

            names = [
                _clean_title(card.title or ""),
                _clean_title(card.title_attr or ""),
            ]
            names = [name for name in names if name]
            if not names:
                continue

            canonical_title = names[0]
            aliases = _unique([name for name in names[1:] if name != canonical_title])
            candidates.append(
                MikanCandidate(
                    bangumi_id=bangumi_id,
                    title=canonical_title,
                    mikan_url=card.href,
                    poster_url=card.poster_url,
                    total_episodes=(
                        card.total_episodes
                        if card.total_episodes is not None
                        else _total_episodes_from_public_text(" ".join(card.metadata_text))
                    ),
                    source_query=self._source_query,
                    aliases=aliases,
                )
            )
            seen_ids.add(bangumi_id)
        return candidates


class _MikanCandidateCard:
    def __init__(self) -> None:
        self.href: str | None = None
        self.title: str | None = None
        self.title_attr: str | None = None
        self.poster_url: str | None = None
        self.total_episodes: int | None = None
        self.metadata_text: list[str] = []


class _MikanBangumiPageParser(HTMLParser):
    def __init__(self, bangumi_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self._base_url = bangumi_url
        self._row_depth = 0
        self._current_row: _MikanPageRow | None = None
        self._completed_rows: list[_MikanPageRow] = []
        self._active_anchor: _MikanPageAnchor | None = None
        self._standalone_anchors: list[_MikanPageAnchor] = []
        self._title_depth = 0
        self._title_parts: list[str] = []
        self._subgroup_depth = 0
        self._subgroup_parts: list[str] = []
        self._subgroup_section_parts: list[str] = []
        self._active_subgroup_anchor_id: str | None = None
        self._subgroup_names_by_id: dict[str, str] = {}
        self._subgroup_names: list[str] = []
        self._subgroup_section_depth = 0
        self._current_subgroup_section_id: str | None = None
        self._current_subgroup_name: str | None = None
        self._anchors: list[_MikanPageAnchor] = []
        self._broadcast_depth = 0
        self._broadcast_parts: list[str] = []
        self._poster_url: str | None = None
        self._total_episodes: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.lower()
        if self._title_depth:
            self._title_depth += 1
        if self._subgroup_depth:
            self._subgroup_depth += 1
        if self._broadcast_depth:
            self._broadcast_depth += 1
        if self._subgroup_section_depth:
            self._subgroup_section_depth += 1

        if tag_name == "tr":
            self._row_depth += 1
            if self._current_row is None:
                self._current_row = _MikanPageRow()

        attr_map = {name.lower(): value for name, value in attrs if value is not None}
        if self._total_episodes is None:
            self._total_episodes = _total_episodes_from_attrs(attr_map)
        classes = set(attr_map.get("class", "").split())
        if "bangumi-title" in classes:
            self._title_depth = 1
            self._title_parts = []
        if classes.intersection({"subgroup-section", "subgroup-text"}):
            self._subgroup_section_depth = 1
            self._current_subgroup_section_id = attr_map.get("id")
            self._current_subgroup_name = self._subgroup_names_by_id.get(
                self._current_subgroup_section_id or ""
            )
            self._subgroup_section_parts = []
        if "subgroup-name" in classes:
            self._subgroup_depth = 1
            self._subgroup_parts = []
            data_anchor = attr_map.get("data-anchor", "").strip()
            self._active_subgroup_anchor_id = (
                data_anchor.lstrip("#") if data_anchor.startswith("#") else None
            )
        if classes.intersection({"broadcast-start", "broadcast-date", "air-date"}):
            self._broadcast_depth = 1
            self._broadcast_parts = []
        if tag_name == "img" and self._poster_url is None:
            image_url = _poster_url_from_attrs(attr_map, self._base_url)
            if image_url is not None:
                self._poster_url = image_url
        if tag_name == "a":
            self._active_anchor = _MikanPageAnchor(
                attr_map,
                [],
                self._current_subgroup_name,
            )

    def handle_data(self, data: str) -> None:
        if self._title_depth:
            self._title_parts.append(data)
        if self._subgroup_depth:
            self._subgroup_parts.append(data)
        if (
            self._subgroup_section_depth
            and self._current_subgroup_name is None
            and self._active_anchor is None
        ):
            self._subgroup_section_parts.append(data)
        if self._broadcast_depth:
            self._broadcast_parts.append(data)
        if self._active_anchor is not None:
            self._active_anchor.text_parts.append(data)
        if self._current_row is not None:
            self._current_row.text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name == "a" and self._active_anchor is not None:
            if (
                self._active_anchor.subgroup_name is None
                and self._subgroup_section_depth
            ):
                section_name = _clean_title(" ".join(self._subgroup_section_parts))
                if section_name:
                    self._current_subgroup_name = section_name
                    self._active_anchor.subgroup_name = section_name
                    if section_name not in self._subgroup_names:
                        self._subgroup_names.append(section_name)
            if self._current_row is not None:
                self._current_row.anchors.append(self._active_anchor)
            else:
                self._standalone_anchors.append(self._active_anchor)
            self._anchors.append(self._active_anchor)
            self._active_anchor = None

        if self._title_depth:
            self._title_depth -= 1
        if self._subgroup_depth:
            self._subgroup_depth -= 1
            if self._subgroup_depth == 0:
                subgroup_name = _clean_title(" ".join(self._subgroup_parts))
                if subgroup_name:
                    self._subgroup_names.append(subgroup_name)
                    if self._active_subgroup_anchor_id:
                        self._subgroup_names_by_id[
                            self._active_subgroup_anchor_id
                        ] = subgroup_name
                    if self._subgroup_section_depth:
                        self._current_subgroup_name = subgroup_name
                self._active_subgroup_anchor_id = None
                self._subgroup_parts = []
        if self._broadcast_depth:
            self._broadcast_depth -= 1
        if self._subgroup_section_depth:
            self._subgroup_section_depth -= 1
            if self._subgroup_section_depth == 0:
                self._current_subgroup_name = None
                self._current_subgroup_section_id = None
                self._subgroup_section_parts = []

        if tag_name == "tr" and self._row_depth:
            self._row_depth -= 1
            if self._row_depth == 0 and self._current_row is not None:
                self._completed_rows.append(self._current_row)
                self._current_row = None

    def title(self) -> str | None:
        title = _clean_title(" ".join(self._title_parts))
        return title or None

    def subgroup_names(self) -> list[str]:
        return _unique(self._subgroup_names)

    def rss_sources(self) -> list[RssSource]:
        rows = self._rows_with_sources()
        sources: list[RssSource] = []
        seen_urls: set[str] = set()
        for row in rows:
            row_text = _clean_title(" ".join(row.text_parts))
            for anchor in row.anchors:
                rss_url = _rss_url_from_href(anchor.attrs.get("href", ""), self._base_url)
                if rss_url is None or rss_url in seen_urls:
                    continue
                subtitle_group = _subtitle_group_from_anchor(anchor, row_text)
                if subtitle_group is None:
                    continue
                sources.append(
                    RssSource(
                        subtitle_group=subtitle_group,
                        rss_url=rss_url,
                        source_type="mikan_http",
                        fixture_path="",
                    )
                )
                seen_urls.add(rss_url)
        return sources

    def bangumi_detail(self) -> MikanBangumiDetail | None:
        bangumi_id = _extract_bangumi_id(self._base_url)
        title = self.title()
        if bangumi_id is None or title is None:
            return None

        bangumi_rss_url = self._bangumi_rss_url()
        subgroups = self._subgroup_details()
        if bangumi_rss_url is None and not any(group.rss_url for group in subgroups):
            return None

        return MikanBangumiDetail(
            bangumi_id=bangumi_id,
            title=title,
            mikan_url=urlunparse(urlparse(self._base_url)),
            broadcast_start=_clean_title(" ".join(self._broadcast_parts)) or None,
            poster_url=self._poster_url,
            bangumi_rss_url=bangumi_rss_url,
            subgroups=subgroups,
            total_episodes=self._total_episodes,
        )

    def _bangumi_rss_url(self) -> str | None:
        for anchor in self._anchors:
            rss_url = _rss_url_from_href(anchor.attrs.get("href", ""), self._base_url)
            if rss_url is None:
                continue
            if _rss_query_subgroup_id(rss_url) is None:
                return rss_url
        return None

    def _subgroup_details(self) -> list[MikanSubgroupDetail]:
        sources_by_group = {source.subtitle_group: source.rss_url for source in self.rss_sources()}
        episodes_by_group: dict[str, list[MikanEpisodeSummary]] = {
            group_name: [] for group_name in self.subgroup_names()
        }

        for anchor in self._anchors:
            episode_url = _episode_url_from_href(anchor.attrs.get("href", ""), self._base_url)
            if episode_url is None:
                continue
            title = _clean_title(" ".join(anchor.text_parts))
            if not title:
                continue
            group_name = anchor.subgroup_name or _subgroup_name_from_episode_title(title)
            if group_name is None:
                continue
            episodes_by_group.setdefault(group_name, []).append(
                MikanEpisodeSummary(title=title, episode_url=episode_url)
            )

        group_names = _unique(
            self.subgroup_names()
            + list(sources_by_group.keys())
            + list(episodes_by_group.keys())
        )
        return [
            MikanSubgroupDetail(
                name=group_name,
                rss_url=sources_by_group.get(group_name),
                episodes=_unique_episodes(episodes_by_group.get(group_name, [])),
            )
            for group_name in group_names
        ]

    def _rows_with_sources(self) -> list[_MikanPageRow]:
        rows = list(self._completed_rows)
        if self._current_row is not None:
            rows.append(self._current_row)
        for anchor in self._standalone_anchors:
            rows.append(_MikanPageRow(text_parts=anchor.text_parts, anchors=[anchor]))
        return rows


class _MikanPageAnchor:
    def __init__(
        self,
        attrs: dict[str, str],
        text_parts: list[str],
        subgroup_name: str | None = None,
    ) -> None:
        self.attrs = attrs
        self.text_parts = text_parts
        self.subgroup_name = subgroup_name


class _MikanPageRow:
    def __init__(
        self,
        text_parts: list[str] | None = None,
        anchors: list[_MikanPageAnchor] | None = None,
    ) -> None:
        self.text_parts = text_parts or []
        self.anchors = anchors or []


def _extract_bangumi_id(href: str) -> str | None:
    marker = "/Home/Bangumi/"
    if marker not in href:
        return None
    remainder = href.split(marker, 1)[1]
    bangumi_id = remainder.split("?", 1)[0].split("#", 1)[0].strip("/")
    if not bangumi_id:
        return None
    return bangumi_id


CANDIDATE_CARD_CONTAINER_CLASSES = {
    "bangumi-item",
    "search-result",
    "an-card",
    "result-item",
    "related-item",
    "recommend-item",
    "sk-bangumi",
}

CANDIDATE_CARD_CONTAINER_TAGS = {"div", "li", "article", "section"}

_HTML_VOID_ELEMENTS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


def _is_candidate_card_container(tag_name: str, classes: set[str]) -> bool:
    return tag_name in CANDIDATE_CARD_CONTAINER_TAGS and bool(
        classes.intersection(CANDIDATE_CARD_CONTAINER_CLASSES)
    )


def _candidate_bangumi_url(href: str, base_url: str) -> str | None:
    """Normalize a candidate href to an absolute bangumi URL or reject it.

    The returned URL always has an HTTP(S) scheme, a netloc, and the normalized
    path ``/Home/Bangumi/<numeric-id>`` without query or fragment. Traversal,
    empty or non-numeric ids, non-bangumi paths, and non-HTTP(S) schemes return
    ``None`` so the caller can skip the candidate safely.
    """
    if not href.strip():
        return None
    absolute_url = urljoin(base_url, href.strip())
    parsed = urlparse(absolute_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) != 3:
        return None
    if [part.casefold() for part in path_parts[:2]] != ["home", "bangumi"]:
        return None
    bangumi_id = path_parts[2]
    if not _is_bangumi_id(bangumi_id):
        return None

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            f"/Home/Bangumi/{bangumi_id}",
            "",
            "",
            "",
        )
    )


def _rss_url_from_href(href: str, base_url: str) -> str | None:
    if not href.strip():
        return None
    absolute_url = urljoin(base_url, href.strip())
    parsed = urlparse(absolute_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    path = parsed.path.casefold()
    if "/rss/" not in path and not path.endswith((".rss", ".xml")):
        return None
    return urlunparse(parsed)


def _episode_url_from_href(href: str, base_url: str) -> str | None:
    if not href.strip():
        return None
    absolute_url = urljoin(base_url, href.strip())
    parsed = urlparse(absolute_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if "/home/episode/" not in parsed.path.casefold():
        return None
    return urlunparse(parsed)


def _poster_url_from_attrs(attrs: dict[str, str], base_url: str) -> str | None:
    classes = set(attrs.get("class", "").split())
    if not classes.intersection({"bangumi-poster", "poster", "cover", "b-lazy"}):
        return None
    src = attrs.get("src", "").strip() or attrs.get("data-src", "").strip()
    if not src:
        return None
    absolute_url = urljoin(base_url, src)
    parsed = urlparse(absolute_url)
    if not _is_safe_public_poster_url(parsed):
        return None
    return urlunparse(parsed)


def _is_safe_public_poster_url(parsed: object) -> bool:
    """Accept only normal public HTTP(S) cover URLs from server-read MiKan HTML."""
    scheme = getattr(parsed, "scheme", "")
    netloc = getattr(parsed, "netloc", "")
    username = getattr(parsed, "username", None)
    password = getattr(parsed, "password", None)
    values = (getattr(parsed, field, "") for field in ("path", "params", "query", "fragment"))
    return (
        scheme in {"http", "https"}
        and bool(netloc)
        and username is None
        and password is None
        and all(not any(ord(char) < 32 or ord(char) == 127 for char in value) for value in values)
    )


def _rss_query_subgroup_id(rss_url: str) -> str | None:
    parsed = urlparse(rss_url)
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.casefold() in {"subgroupid", "subtitlegroupid"} and value.strip():
            return value.strip()
    return None


def _subgroup_name_from_episode_title(title: str) -> str | None:
    stripped = title.strip()
    if not stripped.startswith("[") or "]" not in stripped:
        return None
    subgroup_name = stripped.split("]", 1)[0].strip("[] ")
    return subgroup_name or None


def _subtitle_group_from_anchor(
    anchor: _MikanPageAnchor,
    row_text: str,
) -> str | None:
    if anchor.subgroup_name:
        return anchor.subgroup_name

    for key in (
        "data-subtitle-group",
        "data-subtitle-group-name",
        "data-group",
        "data-group-name",
        "title",
    ):
        value = _clean_title(anchor.attrs.get(key, ""))
        if value and not _is_rss_label(value):
            return value

    anchor_text = _clean_title(" ".join(anchor.text_parts))
    if anchor_text and not _is_rss_label(anchor_text):
        return anchor_text

    cleaned_row = row_text
    for noise in ("RSS", "rss", "订阅", "复制", "复制链接"):
        cleaned_row = cleaned_row.replace(noise, " ")
    cleaned_row = _clean_title(cleaned_row)
    return cleaned_row or None


def _is_rss_label(value: str) -> bool:
    normalized = value.strip().casefold()
    return normalized in {"rss", "rss订阅", "订阅", "订阅rss", "复制", "复制链接"}


def _clean_title(value: str) -> str:
    return " ".join(value.split()).strip()


def _unique(values: list[str]) -> list[str]:
    unique_values: list[str] = []
    for value in values:
        if value not in unique_values:
            unique_values.append(value)
    return unique_values


def _unique_episodes(episodes: list[MikanEpisodeSummary]) -> list[MikanEpisodeSummary]:
    unique_episodes: list[MikanEpisodeSummary] = []
    seen: set[tuple[str, str]] = set()
    for episode in episodes:
        key = (episode.title, episode.episode_url)
        if key in seen:
            continue
        seen.add(key)
        unique_episodes.append(episode)
    return unique_episodes
