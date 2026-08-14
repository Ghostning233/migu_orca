# MiGuOrca Stage 14 Web UI Request Operability PRD

## Status

- Stage: 14
- Scope: Web UI request operability, seed filtering visibility, and Settings qBittorrent layout cleanup
- Architecture: Flask server-side rendering with existing static CSS and vanilla JavaScript
- Owner: Ralph autonomous development agent
- Date: 2026-08-14

## Background

Stage 13 split the Web UI into `/index` as the Request workbench and `/settings` as the configuration page. Manual inspection after Stage 13 found that the page structure is cleaner, but several user-visible workflow bugs still block request generation and validation.

Current observed issues:

- In `/index`, entering `咒术回战` and clicking generate can render Request details, but clicking confirm, cancel, or modify shows `操作失败 未找到已保存的 Request`.
- The generated Request detail is actionable even when the request was created as an unsaved preview.
- Because the generated Request is not saved by default, the Request list cannot be meaningfully tested from the normal UI flow.
- In the modify form, entering `[v2]` in the exclude filter does not give visible feedback that seeds containing `v2` were removed.
- The Seeds area only exposes the effective seed list, making it hard to compare all source seeds against valid and excluded seeds.
- In `/settings`, the qBittorrent connection test section is still wrapped in a disclosure/dropdown whose label is itself the action name. This interaction is confusing and should be removed.

## Goals

1. Make generated Requests operable from the default workbench flow.
2. Prevent unsaved preview Requests from exposing actions that require persisted storage.
3. Make modify filter results observable in the Request detail immediately after a successful modification.
4. Split Seeds visibility into complete source seeds, effective/valid seeds, and excluded seeds.
5. Simplify the Settings qBittorrent section by showing the configuration/test form directly.
6. Preserve the Stage 13 safety boundary and avoid leaking external service secrets or raw responses.

## Non-Goals

- Do not introduce React, Vite, a front-end build chain, or complex animation.
- Do not add new MiKan, qBittorrent download, or Auto Bangumi subscription capabilities.
- Do not persist real external endpoint, token, username, password, cookie, SID, raw HTML, raw RSS XML, or raw response body to storage JSON, browser storage, URL, logs, screenshots, or traces.
- Do not loosen existing backend validation for request modification.

## Safety Requirements

- Browser-visible state may include non-sensitive `request_id`, title, status, sanitized seed titles from fixtures, counts, and high-level warnings.
- Browser-visible state must not include real MiKan, Auto Bangumi, or qBittorrent endpoint, token, username, password, cookie, SID, raw HTML, raw RSS XML, or raw response body.
- Logs, screenshots, and browser traces must use fixtures or sanitized values only.
- Error messages must remain actionable and sanitized.

## User Stories

The authoritative Ralph task definition is stored in `scripts/ralph/prd.json`.

### US-097: Fix generated Request persistence and action contract

Default generation from `/index` must create a saved, operable Request or clearly mark the result as a read-only preview. The normal workbench path should allow the user to generate, see the Request in the list, and use confirm, cancel, and modify without receiving `未找到已保存的 Request`.

### US-098: Guard unsaved preview Request actions

If a preview mode remains available, preview details must not expose persisted-only actions. The UI should show a clear preview badge and a save action instead of confirm, cancel, modify, or Auto Bangumi submission.

### US-099: Make modify filter results visible and correct

The modify form must give observable results when exclusion filters are changed. The user-entered `[v2]` case must be covered by browser regression, either by treating the UI input as a literal helper or by making the regex semantics explicit and showing the resulting excluded seeds.

### US-100: Split Seeds into complete, effective, and excluded lists

Request details must show enough seed information to verify filtering. The Seeds area should include complete source seeds, effective/valid seeds, excluded seeds, and counts.

### US-101: Remove qBittorrent Settings disclosure

The qBittorrent Settings section must show its configuration/test form directly. The current dropdown/disclosure around `测试 qBittorrent 连接` should be removed.

### US-102: Complete Stage 14 docs and regression coverage

Update docs and tests affected by the Stage 14 UI contract changes. Browser tests must cover the reported `咒术回战` generation flow, action behavior, filter visibility, Seeds grouping, qBittorrent Settings layout, responsive layout, and secret-safety checks.

## Acceptance Summary

- `uv run pytest -q` passes.
- `uv run pytest tests/browser/ -v` passes.
- `uv run python -m compileall -q src` passes.
- Stage 14 browser regression verifies the normal `/index` request generation flow end-to-end.
- Stage 14 does not introduce any new sensitive-data persistence or display path.
