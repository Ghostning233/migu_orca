# MiGuOrca Stage 15 Web UI Accepted Management and Filter Semantics PRD

## Status

- Stage: 15
- Scope: Web UI accepted Request management and filter-rule usability
- Architecture: Flask server-side rendering with existing static CSS and vanilla JavaScript
- Owner: Ralph autonomous development agent
- Date: 2026-08-14

## Current State

Stage 14 has been completed and merged into `main`. The current `main` branch is aligned with `origin/main` and includes PR #26:

- `/index` defaults to generating and saving operable Requests.
- Unsaved preview Requests are read-only until saved.
- Request details show complete, valid, and excluded seed lists.
- Settings qBittorrent connection testing is shown directly.

Remaining issues reported after Stage 14:

- After a Request is confirmed and reaches `ACCEPTED`, the Web UI no longer allows deleting or modifying it.
- Filter rules are still too close to raw regex semantics.
- Case sensitivity needs to be user-controllable, with the default being case-insensitive.
- Regex should be an opt-in checkbox capability near the filter inputs, not the default input mode.
- Default filter behavior should be literal substring matching:
  - Include rule: if the entered characters appear in the seed name, the seed remains valid; otherwise it is excluded.
  - Exclude rule: if the entered characters appear in the seed name, the seed is excluded.

## Goals

1. Add explicit saved Request deletion from Web UI and API, including for `ACCEPTED` Requests.
2. Allow safe modification of `ACCEPTED` Requests without regressing their status to `PENDING_CONFIRM`.
3. Change default filter behavior from regex-first to literal substring matching.
4. Add a case-sensitive option near filter controls, default unchecked.
5. Add a regex option near filter controls, default unchecked.
6. Preserve old saved Request compatibility and existing security boundaries.

## Non-Goals

- Do not add qBittorrent download, subscription, or batch automation actions.
- Do not implicitly submit modified `ACCEPTED` Requests to Auto Bangumi.
- Do not add React, Vite, a front-end build chain, or complex animation.
- Do not persist real MiKan, Auto Bangumi, or qBittorrent endpoint/token/username/password/cookie/SID/raw responses.

## Safety Requirements

- Delete and modify actions must require explicit user intent and use sanitized notifications.
- URL state may contain only non-sensitive `request_id`.
- Filter rules are user-entered non-secret strings, but error messages must not include local storage paths or raw external responses.
- Real MiKan, Auto Bangumi, and qBittorrent endpoint, token, username, password, cookie, SID, raw HTML, raw RSS XML, and raw response body must not be written to storage JSON, browser storage, URL, logs, screenshots, or traces.

## User Stories

The authoritative Ralph task definition is stored in `scripts/ralph/prd.json`.

### US-103: Add saved Request delete support

Add repository and Web API support for deleting a saved Request snapshot by `request_id`. Deletion must be explicit, path-safe, and refresh list/detail state.

### US-104: Allow safe modification of ACCEPTED Requests

Modify backend request behavior so `ACCEPTED` Requests can be updated through the same restricted patch fields as pending Requests. The Request must remain `ACCEPTED`, record modify history, and still be eligible for explicit Auto Bangumi submission.

### US-105: Add Web UI actions for ACCEPTED modify and delete

Render `修改` and `删除` actions for saved `ACCEPTED` Requests. Keep delete available for saved Requests where appropriate, but never for unsaved previews.

### US-106: Update filter model to literal-by-default semantics

Extend filter rules with `case_sensitive` and `use_regex` options. Default matching must be case-insensitive literal substring matching.

### US-107: Improve filter edit controls

Replace regex-first wording and literal helper with clearer controls: include input, exclude input, `使用正则` checkbox, and `大小写敏感` checkbox.

### US-108: Refresh filter details and seed explanations

Show filter mode, case sensitivity, and readable exclusion reasons in Request detail so users can verify the exact effect of rules.

### US-109: Stage 15 documentation and regression closeout

Update README, backlog, module docs, browser tests, and safety regressions for the Stage 15 contracts.

## Acceptance Summary

- `uv run pytest -q` passes.
- `uv run pytest tests/browser/ -v` passes.
- `uv run python -m compileall -q src` passes.
- Browser regression verifies ACCEPTED modify/delete.
- Browser regression verifies default literal, case-insensitive filtering.
- Browser regression verifies opt-in regex and case-sensitive filtering.
