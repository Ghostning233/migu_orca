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
        html = _read_mikan_text(
            self._transport,
            search_url,
            timeout=self._config.timeout_seconds,
            failed_step="mikan_search",
        )
        return _parse_search_candidates(html, self._config.search_endpoint)

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
    except Stage1Error as exc:
        raise _sanitize_mikan_stage_error(exc, failed_step) from exc


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
        return Stage1Error(
            "mikan_parse_failed",
            "MiKan 页面解析失败",
            failed_step,
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

    sources = parser.rss_sources()
    if not sources:
        raise Stage1Error(
            "mikan_parse_failed",
            "MiKan 番剧页未找到 RSS 源",
            "mikan_list_rss_sources",
        )
    return sources


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
        self._subgroup_names: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.lower()
        if self._title_depth:
            self._title_depth += 1
        if self._subgroup_depth:
            self._subgroup_depth += 1

        if tag_name == "tr":
            self._row_depth += 1
            if self._current_row is None:
                self._current_row = _MikanPageRow()

        attr_map = {name.lower(): value for name, value in attrs if value is not None}
        classes = set(attr_map.get("class", "").split())
        if "bangumi-title" in classes:
            self._title_depth = 1
            self._title_parts = []
        if "subgroup-name" in classes:
            self._subgroup_depth = 1
            self._subgroup_parts = []
        if tag_name == "a":
            self._active_anchor = _MikanPageAnchor(attr_map, [])

    def handle_data(self, data: str) -> None:
        if self._title_depth:
            self._title_parts.append(data)
        if self._subgroup_depth:
            self._subgroup_parts.append(data)
        if self._active_anchor is not None:
            self._active_anchor.text_parts.append(data)
        if self._current_row is not None:
            self._current_row.text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name == "a" and self._active_anchor is not None:
            if self._current_row is not None:
                self._current_row.anchors.append(self._active_anchor)
            else:
                self._standalone_anchors.append(self._active_anchor)
            self._active_anchor = None
            return

        if self._title_depth:
            self._title_depth -= 1
        if self._subgroup_depth:
            self._subgroup_depth -= 1
            if self._subgroup_depth == 0:
                subgroup_name = _clean_title(" ".join(self._subgroup_parts))
                if subgroup_name:
                    self._subgroup_names.append(subgroup_name)
                self._subgroup_parts = []

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

    def _rows_with_sources(self) -> list["_MikanPageRow"]:
        rows = list(self._completed_rows)
        if self._current_row is not None:
            rows.append(self._current_row)
        for anchor in self._standalone_anchors:
            rows.append(_MikanPageRow(text_parts=anchor.text_parts, anchors=[anchor]))
        return rows


class _MikanPageAnchor:
    def __init__(self, attrs: dict[str, str], text_parts: list[str]) -> None:
        self.attrs = attrs
        self.text_parts = text_parts


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


def _subtitle_group_from_anchor(
    anchor: _MikanPageAnchor,
    row_text: str,
) -> str | None:
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
