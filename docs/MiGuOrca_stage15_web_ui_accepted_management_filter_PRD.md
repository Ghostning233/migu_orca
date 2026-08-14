# MiGuOrca Stage 15 Web UI Accepted Management and Filter Semantics PRD

## Status

- Stage: 15
- Scope: Web UI accepted Request management and filter-rule usability
- Architecture: Flask server-side rendering with existing static CSS and vanilla JavaScript
- Owner: Ralph autonomous development agent
- Date: 2026-08-14
- Completion: Completed on 2026-08-14

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

## Implementation Decisions

- Deletion is a path-safe repository operation: `delete_request_snapshot` in `src/storage_engine/controllers/request_repository.py` validates `request_id` through the shared `_request_path` guard (rejects empty, path fragments, and traversal), returns a stable `request_not_found` error for missing Requests without leaking absolute paths, maps unlink errors to a sanitized `storage_error`, and returns only a safe summary `{request_id, storage, directory, filename, deleted}`.
- The Web delete API is `POST /api/v1/requests/<path:request_id>/delete` reusing the existing `RequestActionPayload` (request_id comes from the URL path; payload only carries `storage_dir`). The response never contains the deleted snapshot body; the delete flow also removes the request from the Web list and drops `request_id` from the URL.
- `modify_request` accepts both `PENDING_CONFIRM` and `ACCEPTED` Requests via `_copy_modifiable_request` and preserves the original status — an ACCEPTED Request stays ACCEPTED after modification and records a `MODIFY` history event. `CANCELLED` and unknown statuses are still rejected with the stable `invalid_request_status` error, and the restricted patch fields remain `selected_subtitle_group`, `filter_rule`, and `expected_folder_name`. Auto Bangumi submission still requires explicit `POST /submit-ab` and remains ACCEPTED-only.
- `FilterRule` carries `use_regex` and `case_sensitive` (default `false`). Old configs and old saved Requests missing the fields load with defaults via `.get("use_regex", False)` / `.get("case_sensitive", False)`. Default matching is case-insensitive literal substring matching; regex compilation only happens when `use_regex=true`, so literal inputs like `[` or `[v2]` no longer raise regex validation errors. Exclusion reasons are `命中排除规则：<rule>` / `未命中包含规则：<rule>`.
- The modify form uses 包含规则/排除规则 labels plus 使用正则/大小写敏感 checkboxes; a `filter_rule` patch always carries explicit `use_regex`/`case_sensitive` booleans reflecting checkbox state, so default submits send `false` and clearing fields keeps the regex/case option state. The Stage 14 literal helper and literal checkbox were removed.
- The detail Filter section renders 包含规则/排除规则 labels, 匹配模式 (正则 vs 普通字符), and 大小写 (区分大小写 vs 不区分大小写) from the saved `filter_rule`, always showing the raw rule text the user typed — never an auto-generated regex.
- Security boundary preserved: real MiKan, Auto Bangumi, and qBittorrent endpoint/token/username/password/cookie/SID/raw HTML/raw RSS XML/raw response body must not be written to storage JSON, browser storage, URL, logs, screenshots, or traces. Browser regression checks these surfaces after ACCEPTED modify/delete and filter flows.
