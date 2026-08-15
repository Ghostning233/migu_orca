# MiGuOrca Stage 17 PRD: Real MiKan Candidate Search and Selection

## 1. Status

- Stage: 17
- Scope: MiKan search candidates, manual collection selection, and search cache
- Date: 2026-08-15
- Status: Planned
- Dependency: Stage 16 completed and merged in PR #28

## 2. Purpose

Stage 17 makes real MiKan search usable without pretending fuzzy title search is reliable.

The core interaction is:

```text
User enters a title or search phrase
  -> MiGuOrca searches MiKan
  -> MiGuOrca displays parseable bangumi collection candidates
  -> user selects one collection
  -> Stage 16 detail parser generates sources through mikan_bangumi
  -> MiGuOrca generates a Request
```

Stage 17 must reuse Stage 16 detail parsing. It must not introduce a second bangumi detail parser.

## 3. Background

Manual MiKan validation showed that `GET /Home/Search?searchstr=<query>` exposes visible collection candidates, especially in the `相关推荐` section. However, MiKan does not guarantee all relevant collections are visible for a fuzzy title. For example, searching `无职转生` can surface later seasons while the first-season collection requires a fuller title such as `无职转生～到了异世界就拿出真本事～`.

Therefore Stage 17 should treat search results as candidate discovery only. The user must explicitly select the final MiKan collection, even when only one candidate is returned.

## 4. Goals

1. Parse MiKan search result pages for visible bangumi collection candidates.
2. Expose a sanitized candidate-search API.
3. Display candidate collections as Web UI cards with title, poster when available, MiKan ID, and source query.
4. Require explicit user selection before real MiKan Request generation.
5. Provide direct MiKan URL/ID fallback in the same Web UI flow using Stage 16 `mikan_bangumi`.
6. Add a small non-sensitive search cache to avoid repeated requests for the same query.
7. Add optional recommendation labels without automatic selection.

## 5. Non-Goals

1. Do not implement AI title normalization in Stage 17.
2. Do not guarantee that MiKan returns all possible collections for a title.
3. Do not auto-select a collection.
4. Do not use hidden browser automation for MiKan pages.
5. Do not add qBittorrent download or Auto Bangumi auto-submit behavior.
6. Do not persist real MiKan endpoints, raw HTML, raw RSS XML, cookies, tokens, or raw response bodies.

## 6. Architecture Rules

1. Stage 17 candidate selection passes selected candidates through the existing Stage 16 `mikan_bangumi` API/entry field.
2. Candidate selection must not create another detail parser.
3. Candidate search must remain request-scoped and explicit; default `/index` generation still uses static fixture mode.
4. The candidate cache may store only public, non-sensitive metadata: query, candidate title, candidate ID, normalized MiKan URL, poster URL if public, and timestamp.
5. URL query and browser storage must not store MiKan endpoint, raw candidate HTML, cookies, tokens, or credentials.

## 7. User Stories

The authoritative Ralph task definition is stored in `scripts/ralph/prd.json`.

### US-116: Parse MiKan search candidate collections

Add a parser/model for MiKan search result pages that extracts visible collection candidates from `相关推荐` and equivalent candidate card structures.

### US-117: Add request-scoped candidate search API

Add a Web API endpoint that accepts a query plus explicit MiKan config and returns sanitized candidate metadata.

### US-118: Add Web UI candidate search controls

Add real MiKan candidate search controls to the Web UI without changing the default fixture generation path.

### US-119: Add manual candidate selection Request generation

Allow users to select one candidate card and generate a Request through existing Stage 16 `mikan_bangumi`.

### US-120: Add direct URL/ID fallback in Web UI

Expose Stage 16 direct MiKan URL/ID entry in the same UI flow for cases where search does not surface the correct collection.

### US-121: Add safe candidate search cache

Cache sanitized candidate metadata for repeated searches and provide safe invalidation.

### US-122: Add recommendation labels without auto-select

Add optional display-only recommendation labels based on simple title similarity and query signals. These labels must not choose the final collection.

### US-123: Stage 17 documentation and regression closeout

Update docs, backlog, Ralph progress, browser tests, and security checks for Stage 17.

## 8. Safety Requirements

1. Candidate API responses must not include raw HTML, raw RSS XML, full failed URLs, cookies, tokens, credentials, original response bodies, or local absolute paths.
2. Web UI must not write MiKan endpoint, raw candidate HTML, cookies, tokens, or credentials to localStorage, sessionStorage, URL query, Request snapshots, history, logs, screenshots, or traces.
3. Public candidate URLs and poster URLs may be displayed if they are part of visible MiKan public metadata and are not error details.
4. Errors must use sanitized `Stage1Error` shapes and safe details such as `category`, `field`, or `status_code`.
5. Default fixture mode must not call candidate search or real MiKan APIs.

## 9. Acceptance Summary

1. `uv run pytest -q` passes.
2. `uv run python -m compileall -q src` passes.
3. `uv run pytest tests/browser/ -v` passes when browser binaries are available; otherwise skip reason must be recorded.
4. Web UI candidate search and manual selection are covered by browser regression.
5. Stage 17 does not leak sensitive external config or raw MiKan responses.

