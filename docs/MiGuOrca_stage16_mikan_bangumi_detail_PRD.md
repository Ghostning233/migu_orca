# MiGuOrca Stage 16 PRD: Real MiKan Bangumi Detail Parsing

## 1. Status

- Stage: 16
- Scope: Real MiKan bangumi detail-page parsing and direct bangumi entry
- Architecture: Existing Python engines, Flask server-rendered Web UI, no new frontend build chain
- Owner: Ralph autonomous development agent
- Date: 2026-08-15
- Status: Planned

## 2. Background

Stage 15 completed Web UI accepted Request management and filter semantics. The next real MiKan blocker is not Auto Bangumi or qBittorrent integration, but reliable MiKan source discovery.

Manual validation on 2026-08-15 found:

1. Searching MiKan with `GET https://mikanani.me/Home/Search?searchstr=无职转生` returns a search page whose `相关推荐` section usually contains only a small number of bangumi collections.
2. The limited recommendation slots can be occupied by newer seasons. For example, searching `无职转生` can show later seasons while the first season collection is not visible.
3. Searching `无职转生 第一季` may return no useful collection, while searching the full first-season title `无职转生～到了异世界就拿出真本事～` can surface `https://mikanani.me/Home/Bangumi/2353`.
4. The selected bangumi detail page is structurally useful: `https://mikanani.me/Home/Bangumi/2353` exposes the bangumi title, a bangumi-level RSS link such as `/RSS/Bangumi?bangumiId=2353`, subgroup-level RSS links such as `/RSS/Bangumi?bangumiId=2353&subgroupid=1231`, subgroup names, episode rows, episode detail links, and magnet attributes.

This means the immediate reliable path is:

```text
User chooses or provides a MiKan bangumi collection
  -> MiGuOrca parses that detail page
  -> MiGuOrca generates structured RSS/source metadata
  -> existing Request generation continues
```

Search and candidate choice should be handled in Stage 17. AI-based title normalization is explicitly deferred to backlog.

## 3. Goals

1. Add a reliable MiKan bangumi detail-page parser for selected `Home/Bangumi/<id>` pages.
2. Support direct real MiKan entry by bangumi URL or bangumi ID so users can bypass unreliable search.
3. Parse subgroup-level RSS sources as the primary source list for MiGuOrca Request generation.
4. Parse safe detail metadata that can later support candidate cards and diagnostics.
5. Preserve existing security boundaries: do not persist raw HTML, raw RSS XML, full external URLs in errors, cookies, tokens, credentials, or magnet values unless a later Stage explicitly consumes them.

## 4. Non-Goals

1. Do not implement the Web UI candidate search/selection flow in Stage 16.
2. Do not implement AI title normalization in Stage 16.
3. Do not add qBittorrent download, task creation, or direct subscription actions.
4. Do not implicitly submit anything to Auto Bangumi.
5. Do not introduce React, Vite, a frontend build chain, browser extension automation, or a database.
6. Do not promise to discover all MiKan collections from a fuzzy title.

## 5. Architecture Decision

Stage 16 and Stage 17 are intentionally split.

Stage 16 handles selected-detail parsing and direct entry because this is the deterministic foundation. It can be tested with offline HTML fixtures and reused by CLI, Web API, and future Web UI candidate selection.

Stage 17 will handle search result parsing, candidate cards, caching, and manual selection. It depends on Stage 16 because each search candidate should be verifiable by fetching/parsing its detail page before Request generation.

AI title normalization remains a later optional enhancer. It must never become a required dependency for the main flow.

## 6. User Stories

The authoritative Ralph task definition is stored in `scripts/ralph/prd.json`.

### US-110: Add MiKan bangumi detail parser fixtures

Capture sanitized offline HTML fixtures that represent the current MiKan `Home/Bangumi/<id>` detail-page structure, including bangumi title, bangumi-level RSS, subgroup names, subgroup-level RSS links, episode titles, episode detail links, and magnet attributes. Tests must avoid raw external secrets and must not require live MiKan access.

### US-111: Parse selected MiKan bangumi detail metadata

Implement parser support for selected bangumi detail pages. The parser should return structured metadata including `bangumi_id`, `title`, optional `broadcast_start`, optional `poster_url`, bangumi-level RSS, subgroup entries, subgroup RSS URLs, and safe episode title/detail summaries.

### US-112: Prefer subgroup-level RSS sources for Request generation

Update the real MiKan source adapter so `list_rss_sources(matched_bangumi)` returns subgroup-level `RssSource` entries when present. Use bangumi-level RSS only as an explicit fallback when no subgroup RSS can be parsed. RSS source output must remain compatible with existing RSS parsing and Request generation.

### US-113: Add direct MiKan bangumi URL or ID entry

Add explicit direct-entry support so CLI and Web API callers can pass a MiKan bangumi URL or bangumi ID. When direct entry is present, the system should bypass MiKan search and use the selected detail page as the matched bangumi source.

### US-114: Harden real MiKan read behavior and errors

Make real MiKan reads robust enough for slow or large pages: preserve explicit timeout behavior, avoid leaking full URLs or raw page content in errors, and add tests for timeout, parse failure, missing RSS, malformed URL/ID, and sanitized error details.

### US-115: Stage 16 documentation and regression closeout

Update README, main PRD, M03/M00/M13 module docs where relevant, backlog, and Ralph progress. Document the Stage 16 direct-entry contract, parser behavior, fallback rules, safety boundaries, and Stage 17 handoff.

## 7. Functional Requirements

1. Accept `https://mikanani.me/Home/Bangumi/<id>` and equivalent configured MiKan host URLs as direct bangumi inputs.
2. Accept a bare bangumi ID only when paired with an explicit configured MiKan base/search endpoint from existing real MiKan config.
3. Reject empty, malformed, non-HTTP(S), and non-`/Home/Bangumi/<id>` direct inputs with sanitized validation errors.
4. Parse bangumi title from the detail page, preferring the page's main bangumi title area.
5. Parse bangumi-level RSS links matching `/RSS/Bangumi?bangumiId=<id>`.
6. Parse subgroup-level RSS links matching `/RSS/Bangumi?bangumiId=<id>&subgroupid=<subgroup_id>`.
7. Derive subgroup names from the nearest subgroup heading/title area, not from generic `RSS` anchor text.
8. Deduplicate RSS sources by absolute RSS URL.
9. Preserve source type as `mikan_http`.
10. Return a stable parse error if the detail page contains no usable RSS sources.
11. Do not store raw MiKan HTML, raw RSS XML, raw magnet values, cookies, or full error URLs in Request snapshots, history, API responses, logs, screenshots, or browser storage.

## 8. Data Contract Notes

Existing `RssSource` remains the Request-generation contract:

```json
{
  "subtitle_group": "桜都字幕组",
  "rss_url": "https://mikanani.me/RSS/Bangumi?bangumiId=2353&subgroupid=203",
  "source_type": "mikan_http",
  "fixture_path": ""
}
```

Stage 16 may introduce an internal detail-page parse model, but it should not force a Request schema migration unless necessary:

```json
{
  "bangumi_id": "2353",
  "title": "无职转生～到了异世界就拿出真本事～",
  "mikan_url": "https://mikanani.me/Home/Bangumi/2353",
  "bangumi_rss_url": "https://mikanani.me/RSS/Bangumi?bangumiId=2353",
  "subgroups": [
    {
      "subtitle_group": "桜都字幕组",
      "subgroup_id": "203",
      "rss_url": "https://mikanani.me/RSS/Bangumi?bangumiId=2353&subgroupid=203",
      "episode_titles": ["safe title sample"]
    }
  ]
}
```

If magnet parsing is implemented in Stage 16, keep it internal or test-only unless a downstream module explicitly consumes it. Magnet links are operational download links and should not be added to Request snapshots without a separate product decision.

## 9. Safety Requirements

1. Default flows still use static fixtures unless the user explicitly selects real MiKan mode or direct MiKan input.
2. Real MiKan endpoint, full failed URL, raw HTML, raw RSS XML, cookie, token, raw response body, and local absolute paths must not appear in error messages, API responses, saved Request JSON, history, logs, browser storage, screenshots, or traces.
3. Public MiKan RSS URLs may appear in Request source metadata only when they are the selected source data required for Request generation.
4. Error details may include sanitized fields such as `category`, `field`, or `status_code`.
5. Live MiKan access must remain behind injected transport seams so unit tests are offline and deterministic.

## 10. Stage 17 Handoff

Stage 17 should build on Stage 16 by adding:

1. MiKan search-result parser focused on `相关推荐` and other safely parseable collection cards.
2. Candidate cards in Web UI with title, poster, MiKan ID, and source query.
3. Manual candidate selection before Request generation.
4. Search result caching for non-sensitive public metadata.
5. Optional recommendation scoring that never auto-selects without user confirmation.

AI title normalization is not Stage 17 unless explicitly reprioritized. It remains backlog.

## 11. Acceptance Summary

1. `uv run pytest -q` passes.
2. `uv run python -m compileall -q src` passes.
3. Browser tests pass if any Web UI surface is changed.
4. Offline fixtures cover MiKan detail-page RSS parsing.
5. Direct MiKan URL/ID entry can generate a Request using subgroup-level RSS sources.
6. Sensitive data and raw external content are not leaked.

