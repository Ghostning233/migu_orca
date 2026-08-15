# MiGuOrca Stage 17 PRD Draft: Real MiKan Candidate Search and Selection

## 1. Status

- Stage: 17
- Scope: MiKan search candidates, manual collection selection, and search cache
- Date: 2026-08-15
- Status: Draft, depends on Stage 16

## 2. Purpose

Stage 17 should make real MiKan search usable without pretending fuzzy title search is reliable. The core interaction is:

```text
User enters a title or search phrase
  -> MiGuOrca searches MiKan
  -> MiGuOrca displays parseable bangumi collection candidates
  -> user selects one collection
  -> Stage 16 detail parser generates sources
  -> MiGuOrca generates a Request
```

## 3. Goals

1. Parse MiKan search result pages for visible bangumi collection candidates, especially the `相关推荐` section.
2. Display candidate collections as Web UI cards with title, poster when available, MiKan ID, and source query.
3. Require explicit user selection even when only one candidate is found.
4. Allow users to retry with another query or paste a direct MiKan bangumi URL/ID.
5. Add a small non-sensitive search cache to avoid repeated requests for the same query.
6. Add optional recommendation labels without automatic selection.

## 4. Non-Goals

1. Do not implement AI title normalization in Stage 17 unless backlog priority changes.
2. Do not guarantee that MiKan returns all possible collections for a title.
3. Do not use hidden browser automation for MiKan pages.
4. Do not add qBittorrent download or Auto Bangumi auto-submit behavior.

## 5. Dependency

Stage 17 depends on Stage 16. Candidate selection should pass the selected detail URL or ID into the Stage 16 parser. If Stage 16 direct-entry parsing is not stable, Stage 17 should not proceed.

## 6. Draft User Stories

1. Search MiKan and parse candidate collection cards.
2. Add candidate-card API endpoint returning sanitized public metadata.
3. Add Web UI candidate selection before Request generation in real MiKan mode.
4. Add direct URL/ID fallback to the same candidate-selection UI.
5. Add query cache for candidate metadata with safe invalidation.
6. Add docs, browser regression, and security checks.

## 7. AI Title Normalization Handoff

AI title normalization remains a later backlog item. It should be implemented as an optional query enhancer that produces candidate search phrases, never as a required dependency and never as an automatic final selector.

