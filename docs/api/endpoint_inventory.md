# MiGuOrca Web API 端点清单（US-189 冻结基线）

> 本文档是 Stage 26 US-189 的产物：先把现有 `/api/v1` 行为、敏感值边界和前端依赖
> 冻结成可审查、可自动核对的事实基线（US-209 已随旧前端删除更新前端依赖章节）。US-192 已在此基础上修正 HTTP 状态语义
> （envelope 保持不变，状态码表达失败分类），因此 §1 总览描述的是**当前生效**
> 的状态语义。Stage 28（US-211～US-217）已把 draft revision、save-confirm、批量 36 部边界
> 与 safe-info 端点/错误并入同一基线并保持无漂移。Stage 29（US-222～US-226）把
> `/api/v1/tracking/items` 六条端点与 tracking handoff 扩展并入同一基线（§3.6 与 §4
> US 里程碑），全部为严格 DTO + 可读 operationId，保持无漂移。
> 它不是 OpenAPI 契约（US-190 已基于 Pydantic DTO 生成 `docs/api/openapi.json`，
> 见 `docs/api/README.md`），也不替代 README 的示例用法。
>
> 自动核对：`tests/api_contract/test_inventory_consistency.py` 会把本清单与 Flask
> 实际 `url_map` 逐一比对，任何新端点漏记都会导致测试失败。
>
> 实现位置（US-191 拆分后）：请求模型在 `src/apps/migu_orca_web/schemas.py`，
> 响应 DTO 在 `api_contract.py`，序列化在 `serializers.py`，用例编排在 `services.py`，
> 路由按端点族在 `routes_requests.py` / `routes_mikan.py` / `routes_batches.py` /
> `routes_settings.py` / `routes_connections.py`，页面路由与 Blueprint 组装在 `views.py`。

## 1. 总览

- 统一成功 envelope：`{"ok": true, "result": {...}}`（`extensions/flask_api/api.py:ok_response`）。
- 统一失败 envelope：`{"ok": false, "error_type", "error_message", "error_data"}`（`failed_response`）。
  - `error_data` 恒包含 `failed_step`，Pydantic 校验失败时包含 `errors: [{error_type, field, message}]`。
- **HTTP 状态语义（US-192 修正）**：envelope 形状不变，状态码按 `error_type` 分类
  （`extensions/flask_api/api.py:_error_http_status`，与 OpenAPI 注册表一致）：
  - `400`：客户端输入/状态不可用（`data_validation_errors`、`validation_error`、
    `invalid_*`、`config_error`、`queue_not_found`、`invalid_storage_dir`；
    US-215 的 `batch_limit_exceeded`（批量超过 36 部）也归此类）。
  - `404`：资源不存在（`request_not_found`、`queue_item_not_found`、`poster_not_found`）。
  - `409`：状态冲突/一次性上下文失效/重放（`invalid_request_status`、`request_cancelled`、
    `season_evidence_conflict`、`season_confirmation_required`、`candidate_context_invalid`；
    US-194 的 `draft_expired`/`draft_evicted`/`draft_replayed`/`draft_mismatch` 与
    US-211 的 `draft_revision_conflict`、US-212 的 `draft_reserved`、US-213 的
    `idempotency_conflict`、US-214 的 `save_confirm_failed` 也归此类）。
  - `401`：外部服务认证失败（`ab_auth_failed`、`qbittorrent_auth_failed`）。
  - `502`：上游不可达/不健康（`mikan_connection_failed`、`mikan_http_failed`、
    `mikan_parse_failed`、`poster_unavailable`、`ab_connection_failed`、`ab_submit_failed`、
    `qbittorrent_connection_failed` 等）。
  - `503`：上游不可用/版本不受支持（`ab_unsupported_version`、`ab_submit_unsupported`、
    `ab_probe_unsupported`）。
  - `504`：上游超时（`mikan_timeout`、`ab_timeout`、`qbittorrent_timeout`）。
  - `500`：服务端内部错误（`storage_error`、`storage_json_error`、未知异常）。
- 唯一二进制端点 `/api/v1/mikan/posters/<key>` 不经 JSON envelope，成功返回图片字节；
  失败返回 JSON envelope + 分类状态码（US-198 校准后与 OpenAPI 声明一致）：
  `invalid_poster_key`/`invalid_poster` → 400，`poster_not_found` → 404，
  `poster_unavailable` → 502，`storage_error` → 500。
- 未注册路由返回 Flask 默认 404 HTML，不属于 API envelope。
- 所有响应在 `failed_response` / `sanitize_error_data` / 各 serializer 白名单中脱敏：
  endpoint、token、cookie、Authorization、SID、password、raw HTML、raw RSS XML、
  原始响应体、完整失败 URL、magnet 与本地绝对路径不得进入 API 展示。

## 2. 端点总表（与 url_map 自动核对）

| 方法 | 路径 | endpoint 名称 | 视图 |
| --- | --- | --- | --- |
| GET | `/api/v1/requests` | `migu_orca_web_api.RequestListView` | RequestListView |
| GET | `/api/v1/requests/<path:request_id>` | `migu_orca_web_api.RequestDetailView` | RequestDetailView |
| GET | `/api/v1/requests/<path:request_id>/safe-info` | `migu_orca_web_api.RequestSafeInfoView` | RequestSafeInfoView |
| POST | `/api/v1/requests` | `migu_orca_web_api.RequestCreateView` | RequestCreateView |
| POST | `/api/v1/requests/preview-modify` | `migu_orca_web_api.RequestPreviewModifyView` | RequestPreviewModifyView |
| POST | `/api/v1/requests/preview-save` | `migu_orca_web_api.RequestPreviewSaveView` | RequestPreviewSaveView |
| POST | `/api/v1/requests/save-confirm` | `migu_orca_web_api.RequestSaveConfirmView` | RequestSaveConfirmView |
| POST | `/api/v1/requests/<path:request_id>/accept` | `migu_orca_web_api.RequestAcceptView` | RequestAcceptView |
| POST | `/api/v1/requests/<path:request_id>/cancel` | `migu_orca_web_api.RequestCancelView` | RequestCancelView |
| POST | `/api/v1/requests/<path:request_id>/modify` | `migu_orca_web_api.RequestModifyView` | RequestModifyView |
| POST | `/api/v1/requests/<path:request_id>/delete` | `migu_orca_web_api.RequestDeleteView` | RequestDeleteView |
| POST | `/api/v1/requests/<path:request_id>/submit-ab` | `migu_orca_web_api.RequestAbSubmitView` | RequestAbSubmitView |
| POST | `/api/v1/mikan/candidates` | `migu_orca_web_api.MikanCandidateSearchView` | MikanCandidateSearchView |
| GET | `/api/v1/mikan/posters/<key>` | `migu_orca_web_api.mikan_poster` | mikan_poster（函数视图） |
| GET | `/api/v1/preferences` | `migu_orca_web_api.PreferenceView` | PreferenceView |
| POST | `/api/v1/preferences` | `migu_orca_web_api.PreferenceSaveView` | PreferenceSaveView |
| GET | `/api/v1/corrections` | `migu_orca_web_api.CorrectionView` | CorrectionView |
| POST | `/api/v1/corrections` | `migu_orca_web_api.CorrectionSaveView` | CorrectionSaveView |
| POST | `/api/v1/batches/parse` | `migu_orca_web_api.BatchParseView` | BatchParseView |
| POST | `/api/v1/batches/<batch_id>/save-confirm` | `migu_orca_web_api.BatchSaveConfirmView` | BatchSaveConfirmView |
| POST | `/api/v1/batches/<batch_id>/accept` | `migu_orca_web_api.BatchAcceptView` | BatchAcceptView |
| GET | `/api/v1/batches/<batch_id>/queue` | `migu_orca_web_api.BatchQueueView` | BatchQueueView |
| POST | `/api/v1/batches/<batch_id>/submit` | `migu_orca_web_api.BatchSubmitView` | BatchSubmitView |
| POST | `/api/v1/batches/<batch_id>/retry` | `migu_orca_web_api.BatchRetryView` | BatchRetryView |
| POST | `/api/v1/batches/<batch_id>/recover` | `migu_orca_web_api.BatchRecoverView` | BatchRecoverView |
| POST | `/api/v1/qbittorrent/test-connection` | `migu_orca_web_api.QbittorrentTestConnectionView` | QbittorrentTestConnectionView |
| POST | `/api/v1/autobangumi/test-connection` | `migu_orca_web_api.AutoBangumiTestConnectionView` | AutoBangumiTestConnectionView |
| POST | `/api/v1/autobangumi/capabilities` | `migu_orca_web_api.AutoBangumiCapabilitiesView` | AutoBangumiCapabilitiesView |
| GET | `/api/v1/tracking/items` | `migu_orca_web_api.TrackingItemListView` | TrackingItemListView |
| GET | `/api/v1/tracking/items/<path:tracking_id>` | `migu_orca_web_api.TrackingItemDetailView` | TrackingItemDetailView |
| POST | `/api/v1/tracking/items/<path:tracking_id>/revalidate` | `migu_orca_web_api.TrackingItemRevalidateView` | TrackingItemRevalidateView |
| POST | `/api/v1/tracking/items/<path:tracking_id>/submit` | `migu_orca_web_api.TrackingItemSubmitView` | TrackingItemSubmitView |
| POST | `/api/v1/tracking/items/<path:tracking_id>/retry` | `migu_orca_web_api.TrackingItemRetryView` | TrackingItemRetryView |
| POST | `/api/v1/tracking/items/<path:tracking_id>/recover` | `migu_orca_web_api.TrackingItemRecoverView` | TrackingItemRecoverView |

页面路由（非 JSON API，供对照）：`GET /` → 302 `/app/workbench`；`GET /index` →
302 `/app/workbench`（保留 `request_id`/`batch_id` query）；`GET /Settings` →
302 `/app/settings`；`GET /settings` → 302 `/app/settings`（保留 `request_id` query）；
`GET /app/*`（SPA 外壳与静态资产，US-197）；`GET /healthz`（存活探针）；
`GET /readiness`（就绪探针，US-195：服务端 Web storage 根目录可创建/可写才 200，
否则 503 `{"ok": false, "result": "storage_unavailable"}`；两者都不访问真实外部系统）。

## 3. 端点族明细

### 3.1 Requests（`/api/v1/requests`）

公共查询参数（所有 Requests 端点）：`storage_dir`（可选字符串；US-193 起为服务端允许
根目录下的相对目录 profile，拒绝绝对路径/穿越/符号链接逃逸并返回 400 `invalid_storage_dir`；
**未传时回落服务端根本身**（US-196 回归：绝不回退 CLI 默认 `DEFAULT_STORAGE_DIR`）；
CLI 显式 `--storage-dir` 行为不受影响）。

| 端点 | 请求字段 | 成功 `result` | 业务失败示例 |
| --- | --- | --- | --- |
| GET `/api/v1/requests` | `storage_dir?` | `{"requests": [summary...]}` | 损坏 snapshot → `storage_json_error` |
| GET `/api/v1/requests/<request_id>` | `request_id`（路径）、`storage_dir?` | `{"request": <snapshot>, "history": {available, events, error}, "ab_result": {available, record, error}}` | 缺失 → `request_not_found`；路径片段 → `invalid_request_id` |
| GET `/api/v1/requests/<request_id>/safe-info` | `request_id`（路径）、`storage_dir?` | `{"safe_info": <RequestSafeInfoDTO>}`（US-217 严格白名单，`extra="forbid"`） | 缺失 → `request_not_found`；路径片段 → `invalid_request_id`；损坏 → `storage_json_error` |
| POST `/api/v1/requests` | `title`、`source`（`static-fixture`/`mikan`）、`mikan_config?`、`mikan_bangumi?`、`storage_dir?`、`save_request`（默认 false）、`season_confirmation?`、`candidate_context?` | `{"request", "summary", "saved_request"?}`；`save_request=false` 时另含 `draft_id` + `draft_revision`（US-194/211：服务端权威草案 opaque id 与单调 revision） | `data_validation_errors`（title 缺失）；`candidate_context_invalid`；保存失败 → `storage_error` |
| POST `/api/v1/requests/preview-modify` | `draft_id`（US-194，不再收完整 `request`）、`base_revision`（US-211 必填，compare-and-swap）、`patch`、`storage_dir?` | `{"request", "summary", "draft_id", "draft_revision"}` | `invalid_modify_patch_field`；draft 失效 → `draft_expired`/`draft_evicted`/`draft_replayed`（409）；`base_revision` 过期 → `draft_revision_conflict`（409，error_data 只含 `field`/`current_revision`） |
| POST `/api/v1/requests/preview-save` | `draft_id`（US-194，一次性预留）、`base_revision`（US-212 必填，预留校验）、`storage_dir?` | `{"request", "summary", "saved_request"?}` | draft 失效/重放 → `draft_expired`/`draft_evicted`/`draft_replayed`（409）；`base_revision` 过期 → `draft_revision_conflict`；正在保存 → `draft_reserved`（409） |
| POST `/api/v1/requests/save-confirm` | `draft_id`、`base_revision`、`idempotency_key`、`storage_dir?`（US-214；不接受完整 Request） | `{"outcome": "CONFIRMED", "request", "summary", "handoff": {request_id, status: "ACCEPTED", next_action: "OPEN_TRACKING", tracking_id, tracking_status?, tracking_ready, safe_message?}}`（US-222 起 handoff 携带 unified tracking 身份；tracking 写失败时 `tracking_ready=false` + 固定 `safe_message`，不回滚已确认 Request） | 同 preview-save 的 draft 409；同键不同 payload/操作 → `idempotency_conflict`（409）；确认失败 → `save_confirm_failed`（409，details 只含 `outcome=SAVED_CONFIRM_FAILED`/`request_id`/`retry_action=ACCEPT_SAVED_REQUEST`） |
| POST `/api/v1/requests/<request_id>/accept` | `request_id`（路径）、`storage_dir?` | `{"request", "summary", "saved_request"?}` | 缺失 → `request_not_found`；状态冲突 → `invalid_request_status` |
| POST `/api/v1/requests/<request_id>/cancel` | `request_id`（路径）、`cancel_reason?`、`storage_dir?` | `{"request", "summary", "saved_request"?}` | 同上 |
| POST `/api/v1/requests/<request_id>/modify` | `request_id`（路径）、`patch`、`storage_dir?` | `{"request", "summary", "saved_request"?}` | `invalid_modify_patch_field` |
| POST `/api/v1/requests/<request_id>/delete` | `request_id`（路径）、`storage_dir?` | `{"request_id", "storage", "directory", "filename", "deleted": true}` | 缺失 → `request_not_found` |
| POST `/api/v1/requests/<request_id>/submit-ab` | `request_id`（路径）、`ab_config`（`auth_mode`/`base_url`/`username`/`password`/`token`/`fallback_enabled`）、`storage_dir?` | `{"request", "summary", "ab_submit_result", "saved_request"?, "saved_ab_result"?}` | 非 ACCEPTED → `invalid_request_status` |

`summary` 形状（`request_engine.controllers.request_controller.summarize_request`）：
`request_id`、`status`、`bangumi_title`、`candidate_subtitle_groups[]`
（`subtitle_group`/`rss_url`/`total_seed_count`/`valid_seed_count`/`invalid_seed_count`）、
`selected_subtitle_group`、`effective_seed_count`、`expected_folder_name`、`warnings[]`。

`safe-info` 形状（`RequestSafeInfoDTO`，US-217 严格白名单，`extra="forbid"`）：
`request_id`、`status`、`raw_title`/`title`/`aliases[]`、`season`/`season_raw`/
`season_evidence`、`mikan_collection{title, bangumi_id}`（只含公开合集标题与编号，
**不含完整合集/RSS URL**）、`subtitle_groups[]`
（`subtitle_group`/`total_resource_count`/`valid_resource_count`/
`invalid_resource_count`/`warnings[]`，无 RSS URL/种子原文）、
`selected_subtitle_group`、`filter_rule`（用户可读摘要）、`resources`
（`selected_subtitle_group`/`valid_resource_count`/`invalid_resource_count`/
`complete_resource_count`/`valid_file_names[]`/`excluded_file_names[]`，只含脱敏
torrent 文件名，不含 magnet/下载 URL/原始 RSS）、`folder_name`（安全文件夹名）、
`storage_profile`（相对 profile 或 `null`）、`total_episodes`（默认 `null`，无公开数据）、
`updated_episode: null`、`updated_episode_status: "NOT_IMPLEMENTED"`（BL-020 不实现，
绝不从种子/RSS/下载状态猜测）、`history_summary[]`
（`action`/`previous_status`/`next_status`/`timestamp`，丢弃 details/诊断）、
`ab_status{submitted, success?, ab_subscription_id?, error_type?}`（不含 endpoint/凭据/
原始响应）。

### 3.2 MiKan 候选（`/api/v1/mikan/...`）

| 端点 | 请求字段 | 成功 `result` | 业务失败示例 |
| --- | --- | --- | --- |
| POST `/api/v1/mikan/candidates` | `query`、`mikan_config?`（`search_endpoint`/`timeout_seconds`） | `{"query", "status", "parse_result", "attempted_queries", "candidates": [candidate...], "error"?}` | 空 query → `data_validation_errors`；搜索失败 → 结果内 `error` + `status=FAILED` |
| GET `/api/v1/mikan/posters/<key>` | `key`（路径，opaque） | 图片字节（`image/jpeg`/`image/png`/`image/gif`/`image/webp`），`Cache-Control: private, max-age=86400` | 见 §4.3 |

`candidate` 形状：`bangumi_id`、`title`、`mikan_url`、`poster_url`（同源 opaque 代理 URL 或 null）、
`source_query`、`aliases[]`、`recommendation?`（display-only）、`total_episodes?`、
`season_evidence?`、`candidate_context?`（仅当季数需确认时签发的一次性 opaque token）。

### 3.3 Preferences / Corrections（`/api/v1/preferences`、`/api/v1/corrections`）

| 端点 | 请求字段 | 成功 `result` | 业务失败示例 |
| --- | --- | --- | --- |
| GET `/api/v1/preferences` | `storage_dir?` | 非敏感偏好对象（`version`/`subtitle_groups`/`filter_defaults`/`naming`/`search`） | 损坏文件 → `storage_json_error` |
| POST `/api/v1/preferences` | `storage_dir?`、`preferences`（宽松对象） | 规范化偏好对象 | 缺失 → `validation_error`「请提供偏好配置」；类型/枚举/敏感值 → `validation_error` |
| GET `/api/v1/corrections` | `storage_dir?` | `{"corrections": [...]}` | — |
| POST `/api/v1/corrections` | `storage_dir?`、`correction`（宽松对象） | `{"corrections": [...]}` | 缺失 → `validation_error`「请提供修正内容」 |

### 3.4 Batches（`/api/v1/batches/...`）

| 端点 | 请求字段 | 成功 `result` | 业务失败示例 |
| --- | --- | --- | --- |
| POST `/api/v1/batches/parse` | `raw_input`、`mikan_config?`、`storage_dir?` | `{"batch_id", "raw_input", "items": [item...]}` | 空输入 → `validation_error`「请至少输入一个番剧名称」；超过 36 个非空行 → `batch_limit_exceeded`（400，details 只含 `field=raw_input`/`limit=36`/`actual`，任何标题解析/MiKan/持久化 seam 前拒绝） |
| POST `/api/v1/batches/<batch_id>/save-confirm` | `batch_id`（路径）、`items[]`（`item_id`/`draft_id`/`base_revision`/`idempotency_key`）、`item_ids?`、`storage_dir?` | `{"batch_id", "results": [{item_id, outcome, request_id?, status?, error_type?, error_message?, tracking_id?, tracking_ready?}], "summary": {requested, confirmed, failed}}`（HTTP 200 逐条部分成功；US-222 起 CONFIRMED 项携带 `tracking_id`/`tracking_ready`，单条 tracking 写失败不回滚该已确认项或其他条目） | 每条复用单番 save-confirm 用例；可预期单条失败（`draft_expired`/`draft_revision_conflict`/`draft_reserved`/`idempotency_conflict`/`save_confirm_failed` 等）→ 逐条 `failed` 脱敏结果，不回滚成功项；重复 `item_id` → `skipped`；请求级错误仍走普通失败 envelope（缺 item 字段/idempotency_key → `data_validation_errors`；非法 storage_dir → `invalid_storage_dir`） |
| POST `/api/v1/batches/<batch_id>/accept` | `batch_id`（路径）、`items[]`（`item_id`/`request_id?`/`title?`）、`item_ids?`、`storage_dir?` | `serialize_batch_accept_result`：`{batch_id, queue, items[], summary}` | 单卡不可接受 → 项内中文 reason |
| GET `/api/v1/batches/<batch_id>/queue` | `batch_id`（路径）、`storage_dir?` | `{"batch_id", "queue": {...} | null}` | — |
| POST `/api/v1/batches/<batch_id>/submit` | `batch_id`（路径）、`ab_config?`、`confirm`、`storage_dir?` | `serialize_batch_submit_result` | 缺 `ab_config` → `validation_error`「请提供 Auto Bangumi 配置」；缺 `confirm` → `validation_error`；queue 缺失 → `queue_not_found` |
| POST `/api/v1/batches/<batch_id>/retry` | 同上 + `request_id` | 同上 | 未知 request_id → `queue_item_not_found` |
| POST `/api/v1/batches/<batch_id>/recover` | `batch_id`、`request_id`、`action`（`auto`/`succeeded`/`failed`）、`confirm`、`storage_dir?` | 同上 | 非法 action → `validation_error`；未知 request_id → `queue_item_not_found` |

`parse` 的 `item` 形状：`item_id`、`raw_title`、`status`（`RAW`/`PARSED`/`FOUND`/`EMPTY`/`FAILED`）、
`canonical_title_candidates[]`、`season_hint`、`search_queries[]`、`confidence`、
`needs_user_review`、`source`、`parse_result`（嵌套 `AnimeTitleParseResult.to_dict()`）、
`attempted_queries[]`、`candidates[]`、`applied_preferences?`、`preference_hits?`、
`preference_warnings[]`、`review_hints[]`、`enhanced_search_queries[]`、`preview_request?`、`error?`。

### 3.5 连接测试（`/api/v1/.../test-connection`）

| 端点 | 请求字段 | 成功 `result`（白名单） | 业务失败示例 |
| --- | --- | --- | --- |
| POST `/api/v1/qbittorrent/test-connection` | `qbittorrent_config`（`endpoint`/`username`/`password`/`timeout_seconds`/`verify_tls`） | `{"status", "reachable", "version"}` | `qbittorrent_auth_failed` / `qbittorrent_timeout` / `qbittorrent_connection_failed` |
| POST `/api/v1/autobangumi/test-connection` | `ab_config`（`auth_mode`/`base_url`/`username`/`password`/`token`/`fallback_enabled`） | `{"reachable", "authenticated", "version", "auth_mode", "adapter", "submit_supported"}` | `ab_auth_failed` / `ab_connection_failed` / `ab_timeout` / `ab_unsupported_version` |

两类连接测试的请求凭据都保持 request-scoped：不写入 storage、URL、浏览器 storage、日志或测试 trace。

### 3.6 Tracking（`/api/v1/tracking/items`，US-223 + US-224 + US-225 + US-226）

Tracking 读端点全部是纯本地操作：执行前先运行历史回填协调器（manifest `COMPLETE` 后不再全量扫描），
绝不访问外部系统。列表/详情/复核只返回 TrackingRecord 与 Request 的安全白名单投影；单条 tracking
JSON 损坏不阻塞健康列表，只增加 `unreadable` 计数与固定 warning，绝不暴露文件信息。revalidate
不接收 `ab_config`/连接/capability 配置，只接受 `expected_revision`（revision-aware）。submit
（US-225）与 retry（US-226）是唯一会访问 Auto Bangumi 的端点族：`confirm` 必须严格为 true，
`ab_config` 只在单次请求内存中存在，外部调用前先持久化 `SUBMITTING` + operation `IN_PROGRESS`
作为持久化边界。retry 只允许 `SUBMIT_FAILED`；recover（US-226）的 `AUTO` 只读本地证据、绝不访问
外部，人工动作必须 `confirm=true` 并写 USER 审计。

| 端点 | 请求字段 | 成功 `result`（白名单） | 业务失败示例 |
| --- | --- | --- | --- |
| GET `/api/v1/tracking/items` | `storage_dir?`、`q?`、`status_group?`（`PENDING`/`PROCESSING`/`ACTIVE`/`ATTENTION`/`INACTIVE`）、`sort?`（`updated_at`/`title`/`status`） | `{"items": [<TrackingItemDTO>], "summary": {total, pending, processing, active, needs_attention, unreadable}, "warnings": []}` | 非法枚举 → `data_validation_errors`；`invalid_storage_dir` |
| GET `/api/v1/tracking/items/<tracking_id>` | `tracking_id`（路径）、`storage_dir?` | `{...summary 字段, origin, batch_id?, created_at, updated_at?, last_synced_at?, safe_info?, current_operation?, revalidation_issues: [], external_mapping?, audit_events[]（最近 20 条）, warnings}` | 缺失 → `tracking_not_found`（404）；路径片段 → `invalid_tracking_id`；损坏 → `storage_json_error` |
| POST `/api/v1/tracking/items/<tracking_id>/revalidate`（US-224） | `tracking_id`（路径）、`expected_revision`（必填）、`storage_dir?` | `{tracking_id, ready, checked_revision, next_revision, checked_at, next_status, issues[], tracking}`（业务复核失败仍 HTTP 200：`ready=false`、`next_status=NEEDS_RECONFIRM` + 固定 §11.5 issue code） | 缺 `expected_revision`/多余字段（如 `ab_config`）→ `data_validation_errors`；`expected_revision` 过期 → `tracking_revision_conflict`（409）；非可复核状态 → `tracking_state_conflict`（409）；缺失 → `tracking_not_found`（404）；路径片段 → `invalid_tracking_id` |
| POST `/api/v1/tracking/items/<tracking_id>/submit`（US-225） | `tracking_id`（路径）、`expected_revision`（必填）、`idempotency_key`（必填）、`confirm`（必须严格 `true`）、`ab_config`（request-scoped，必填）、`storage_dir?` | `{tracking_id, outcome, checked_revision, next_revision, checked_at, operation_id?, issues[], tracking}`（已落盘业务结果 HTTP 200，`outcome` ∈ `ACTIVE`/`SUBMIT_FAILED`/`VERIFYING_EXTERNAL`/`RECOVERY_REQUIRED`/`NEEDS_RECONFIRM`） | `confirm=false` → `tracking_confirmation_required`（400）；`expected_revision` 过期 → `tracking_revision_conflict`（409）；非可提交状态 → `tracking_state_conflict`（409）；同键不同绑定 → `tracking_idempotency_conflict`（409）；进行中提交 → `tracking_operation_in_progress`（409）；缺失 → `tracking_not_found`（404）；路径片段 → `invalid_tracking_id`；非法 `idempotency_key` → `data_validation_errors` |
| POST `/api/v1/tracking/items/<tracking_id>/retry`（US-226） | `tracking_id`（路径）、`expected_revision`（必填）、`idempotency_key`（必填）、`confirm`（必须严格 `true`）、`ab_config`（request-scoped，必填）、`storage_dir?` | `{tracking_id, outcome, checked_revision, next_revision, checked_at, operation_id?, issues[], tracking}`（复用统一提交服务，`outcome` ∈ `ACTIVE`/`SUBMIT_FAILED`/`VERIFYING_EXTERNAL`/`RECOVERY_REQUIRED`/`NEEDS_RECONFIRM`） | 非 `SUBMIT_FAILED` → `tracking_state_conflict`（409，`VERIFYING_EXTERNAL`/`RECOVERY_REQUIRED` 必须先 recover）；`confirm=false` → `tracking_confirmation_required`（400）；其余与 submit 相同（`tracking_revision_conflict`/`tracking_idempotency_conflict`/`tracking_operation_in_progress`） |
| POST `/api/v1/tracking/items/<tracking_id>/recover`（US-226） | `tracking_id`（路径）、`expected_revision`（必填）、`action`（`AUTO`/`MARK_SUCCEEDED`/`MARK_FAILED`）、`confirm`（人工动作必须严格 `true`）、`storage_dir?` | `{tracking_id, action, outcome, checked_revision, next_revision, checked_at, operation_id?, needs_manual, tracking}`（已落盘恢复结果 HTTP 200，`outcome` ∈ `ACTIVE`/`SUBMIT_FAILED`/`RECOVERY_REQUIRED`；`needs_manual=true` 表示 AUTO 无明确本地证据，只能人工核验） | `action` 非法 → `data_validation_errors`；人工动作未确认 → `tracking_confirmation_required`（400）；非可恢复状态 → `tracking_state_conflict`（409）；`expected_revision` 过期 → `tracking_revision_conflict`（409）；缺失 → `tracking_not_found`（404） |

`revalidate` 的 `issues[]`（`TrackingRevalidationIssueDTO`，固定 §11.5 枚举）字段：
`code`、`field?`、`message`、`recovery_action`。code 只允许
`REQUEST_MISSING`/`REQUEST_NOT_ACCEPTED`/`REQUEST_CHANGED`/`TITLE_MISSING`/
`SEASON_REVIEW_REQUIRED`/`MIKAN_SELECTION_MISSING`/`SUBTITLE_GROUP_MISSING`/
`NO_VALID_RESOURCES`/`EXTERNAL_ALREADY_LINKED`/`OPERATION_IN_PROGRESS`/
`TRACKING_STATE_INVALID`，文案为脱敏中文，绝不包含上游响应/路径/原始 JSON。

`TrackingItemDTO`（US-223 strict `extra="forbid"`）字段：`tracking_id`、`request_id?`、`title?`、
`season?`、`subtitle_group?`、`poster_path?`（只允许同源 `/api/v1/mikan/posters/<opaque-key>`）、
`status`、`status_label`（中文）、`status_group`、`available_actions[]`（服务端计算，只含当前可执行
动作，`code`/`label`/`style`/`requires_confirmation`）、`valid_resource_count`、
`updated_episode: null`、`updated_episode_status: "NOT_IMPLEMENTED"`、`total_episodes: null`、
`revision`、`updated_at`。

详情在 summary 之外只复用 Request `safe-info` 白名单与当前 operation 安全摘要、revalidation
issues、外部安全映射摘要和最近 20 条审计事件；绝不回显完整 Request、外部原始 JSON、完整 URL、
凭据、magnet 或绝对路径。

## 4. 敏感值边界（已冻结）

### 4.1 永不进入 API 展示/响应

- `endpoint`、`base_url`、`search_endpoint` 完整值、`token`、`cookie`、`Authorization`、
  `SID`、`username`、`password`、`magnet`、raw HTML、raw RSS XML、原始响应体、
  完整失败 URL、本地绝对路径。
- 连接测试成功响应只回白名单字段；`_sanitize_ab_connection_summary` /
  `_sanitize_qbittorrent_connection_summary` 主动丢弃其他字段。
- 失败 details 经 `sanitize_error_data` 与 `_strip_sensitive_result_fields` 双重脱敏。

### 4.2 request-scoped 配置（不进入 storage JSON / 浏览器 storage / URL / 日志 / trace）

- `mikan_config`、`mikan_bangumi`、`ab_config`、`qbittorrent_config`、`candidate_context`、
  `draft_id`（US-194：draft 内容由服务端持有，客户端只持有 opaque id，绝不进入 URL /
  browser storage / 日志 / trace）。
- `base_revision`/`draft_revision`（US-211：单调草案 revision 只在请求体与组件内存，
  绝不进入 URL / browser storage / 日志 / trace）。

### 4.3 已治理的问题（US-192 统一错误处理 / US-193 Web storage 根目录）

- `GET /api/v1/mikan/posters/<key>` 是**函数视图**（非 class-based view），US-192 已把
  它纳入统一错误处理：`poster_service.get` 抛出的 `Stage1Error`（`invalid_poster_key`、
  `poster_not_found`、`poster_unavailable`、`invalid_poster`）现在转换为 JSON envelope +
  分类状态码（`_error_http_status`），不再在 TESTING 上抛或变成 500 HTML。
- US-193：Web API 的 `storage_dir` 从任意本地路径收紧为服务端根目录下的相对 profile。
  默认根为仓库 `.migu_orca/storage`，部署可用 `MIGU_ORCA_WEB_STORAGE_ROOT` 覆盖（仅服务端）。
  绝对路径（Unix/Windows 盘符）、`..` 穿越与符号链接逃逸统一返回 400 `invalid_storage_dir`，
  details 只含 `field`/`reason`，绝不回显原始路径。旧前端在 localStorage 中的绝对路径旧值
  会被自动忽略并回退默认根目录。
- US-196 回归修复：`storage_dir` 未传/空值时回落**服务端 Web storage 根**（
  `services._storage_dir` 返回 `_WEB_STORAGE_ROOT`），绝不返回 `None`——返回 `None` 会让
  `load_storage_config(None)` 回退 CLI 默认 `DEFAULT_STORAGE_DIR`（仓库根），绕过服务端
  root 覆盖；golden contract 已覆盖「不传 `storage_dir` 的保存写入服务端根而非仓库根」。
- US-194：`preview-modify`/`preview-save` 不再接收客户端完整 Request，只接受服务端签发的
  `draft_id`；未保存草案由 `DraftStore`（`apps/migu_orca_web/drafts.py`）持有，TTL 30 分钟、
  容量 128、一次性保存与重放保护，失效/重放统一 409 `draft_expired`/`draft_evicted`/
  `draft_replayed`，错误 details 不回显 draft_id 或草案内容。
- US-210/211：每个草案带单调 revision（签发为 1，成功 CAS 修改 +1）。`preview-modify`
  必填 `base_revision` 做 compare-and-swap，过期 base → 409 `draft_revision_conflict`，
  error_data 只含 `field=base_revision` 与 `current_revision`，绝不回显 draft_id 或草案内容。
- US-212：`preview-save` 改为「预留 → 持久化 → 提交/释放」。`draft_id` + `base_revision`
  通过 `reserve_for_save` 校验并预留草案；Request 成功落盘后才 `commit_save`（写入重放
  tombstone），持久化异常用 `release_save` 释放并保留原 revision——同一草案写盘失败后可重试，
  不再先 pop 后持久化导致用户重新搜索。预留期间的并发修改/保存返回 409 `draft_reserved`。
- US-213：storage engine 新增持久化 save-confirm 幂等记录（`<storage>/idempotency/` 下
  `<opaque-key>.json`，见 `storage_engine/controllers/idempotency_repository.py`）。记录只含
  `idempotency_key`、`operation=SAVE_CONFIRM`、不可逆 `request_fingerprint`（sha256 over
  allowed business fields）、`request_id?`、`state`
  （`IN_PROGRESS`/`SAVED_CONFIRM_FAILED`/`CONFIRMED`）与时间戳；绝不保存 draft、标题、URL、
  凭据或绝对路径。应用层协议见 `apps/migu_orca_web/save_confirm_service.py`：
  终态同键重放同一公开结果；`IN_PROGRESS` 重试先核对已落盘 Request（§7 rule 3）再决定继续
  确认或安全重试保存；同键绑定不同 operation/payload → 409 `idempotency_conflict`，错误不回显
  原始 payload。`idempotency_key` 是 request-scoped opaque 值，只进请求体与页面内存。
- US-214：新增 `POST /api/v1/requests/save-confirm`，把 US-213 协调器接真实
  DraftStore/entry-controller 流（`services._build_save_confirm_persist_pending` /
  `_build_save_confirm_confirm_saved`）。成功返回 `CONFIRMED` + 已保存 ACCEPTED Request +
  `handoff`（`request_id`/`status=ACCEPTED`/`next_action=OPEN_TRACKING`）。持久化成功但确认失败返回 HTTP 409 `save_confirm_failed`，
  `error_data.details` 只含 `outcome=SAVED_CONFIRM_FAILED`、`request_id`、
  `retry_action=ACCEPT_SAVED_REQUEST`——已消费 draft_id 与草案内容绝不回显；客户端用既有
  Request accept 契约重试确认。
- US-215：`POST /api/v1/batches/parse` 按规范化非空行计数，单批接受 1～36 部（
  `MAX_BATCH_ITEMS = 36`，`batch_engine/models`）。0 部沿用 `validation_error`；37 部及以上
  在任何标题解析、MiKan 搜索或持久化 seam 前返回 HTTP 400 `batch_limit_exceeded`，
  `error_data.details` 只含 `field=raw_input`、`limit=36`、`actual`——绝不回显原始批量输入。
- US-216：新增 `POST /api/v1/batches/{batch_id}/save-confirm`（`BatchSaveConfirmView`，
  operationId `saveConfirmBatchItems`），每条复用单番 save-confirm 用例
  （`routes_requests._run_draft_save_confirm` → US-213 `run_save_confirm`）。请求每条只收
  `item_id`/`draft_id`/`base_revision`/`idempotency_key`，支持 `item_ids` 选择并保持输入
  顺序。成功 = HTTP 200 `{batch_id, results[], summary:{requested, confirmed, failed}}`
  （逐条部分成功）；可预期单条失败返回逐条脱敏 `failed` 结果（`error_type` 为
  `draft_expired`/`draft_revision_conflict`/`draft_reserved`/`idempotency_conflict`/
  `save_confirm_failed` 等，`error_message` 固定中文，绝不回显 draft_id/标题/URL/路径），
  成功项不因失败项回滚；同一 `item_id` 重复 → `skipped`。同一 item + `idempotency_key`
  幂等重试重放同一 CONFIRMED 结果，不创建第二个 Request。请求级 shape/batch_id/storage
  profile 错误仍走普通失败 envelope。
- US-226：新增 `POST /api/v1/tracking/items/{tracking_id}/retry`（`TrackingItemRetryView`，
  operationId `retryTrackingItem`）与 `POST /api/v1/tracking/items/{tracking_id}/recover`
  （`TrackingItemRecoverView`，operationId `recoverTrackingItem`）。retry 请求 shape 与 submit
  相同，但只允许从 `SUBMIT_FAILED` 开始（`VERIFYING_EXTERNAL`/`RECOVERY_REQUIRED` 必须先
  recover，不能盲重试 D29-07）；复用 `run_tracking_submit` 的完整可靠序列（新键 bind 新
  operation、SUBMITTING 预写、单次外部调用、结果分类）。recover 的 `AUTO` 由
  `apps/migu_orca_web/tracking_recovery_service.run_tracking_recover` 编排：只读取本地
  operation 终态与 Request 脱敏 AB result（纯分类在
  `tracking_engine/controllers/recover.classify_auto_recovery`），无明确证据时
  `VERIFYING_EXTERNAL`/`UNKNOWN` → `RECOVERY_REQUIRED`（`needs_manual=true`）或保持
  `RECOVERY_REQUIRED`；明确成功/失败 → `ACTIVE`/`SUBMIT_FAILED`。
  `MARK_SUCCEEDED`/`MARK_FAILED` 必须 `confirm=true` 并写 USER 审计，且不接受外部
  ID/URL/原始结果。恢复会把 `IN_PROGRESS` operation 终态化到匹配状态。DTO
  `TrackingRecoverResultDTO`（`tracking_id`/`action`/`outcome`/`checked_revision`/
  `next_revision`/`checked_at`/`operation_id?`/`needs_manual`/`tracking`）。
- US-225：新增 `POST /api/v1/tracking/items/{tracking_id}/submit`
  （`TrackingItemSubmitView`，operationId `submitTrackingItem`）。统一可靠提交流程由
  `apps/migu_orca_web/tracking_submission_service.run_tracking_submit` 编排：先跑
  migration coordinator → load TrackingRecord → `confirm` 必须严格 true（否则 400
  `tracking_confirmation_required`）→ 服务端重新读取最新 Request 并跑纯本地复核
  （`classify_revalidation`，不信任浏览器 fingerprint）。仅 fingerprint 变化（其余通过）时
  `confirm=true` 采纳最新方案并在同一次 SUBMITTING 写入中更新 fingerprint/revision/审计；
  其他阻断 issue 不访问 Auto Bangumi，落盘为 HTTP 200 的 `NEEDS_RECONFIRM`。外部调用前
  先 bind operation=PREPARED → 写 TrackingRecord=SUBMITTING → operation CAS
  PREPARED→IN_PROGRESS（持久化边界，只有胜出者访问 Auto Bangumi）；结果经
  `tracking_engine/controllers/submit.classify_external_submit_result` 分类为
  `ACTIVE`/`SUBMIT_FAILED`/`VERIFYING_EXTERNAL`，先持久化 AB 安全结果再写 TrackingRecord
  终态与 operation 终态；AB 结果落盘失败 → `RECOVERY_REQUIRED`。同 `idempotency_key`
  终态重放复用原 operation 返回同一 outcome（不再外部调用），PREPARED 同键重放安全恢复，
  IN_PROGRESS 同键并发只允许一次外部调用、落败者 409 `tracking_operation_in_progress`；
  同键不同绑定 → 409 `tracking_idempotency_conflict`。ab_config 只在单次请求内存，
  绝不持久化/记录/回显。
- US-224：新增 `POST /api/v1/tracking/items/{tracking_id}/revalidate`
  （`TrackingItemRevalidateView`，operationId `revalidateTrackingItem`）。复核是
  revision-aware 纯本地操作：请求只接受 `expected_revision` 与可选 `storage_dir`
  （`extra="forbid"` 拒绝 `ab_config`/未知字段），服务端重新读取最新 Request 后跑
  `tracking_engine/controllers/revalidate.classify_revalidation`（存在且 ACCEPTED、
  fingerprint、标题/季度、MiKan 合集、字幕组、有效资源、外部映射、未完成 operation）。
  业务失败仍 HTTP 200：`ready=false`、`next_status=NEEDS_RECONFIRM`、固定 §11.5
  issue 列表；失败时 `PENDING_SUBMIT`/`SUBMIT_FAILED` → `NEEDS_RECONFIRM`（+1
  revision + 审计 `PLAN_CHANGE_DETECTED`/`REVALIDATION_FAILED`），已处于
  `NEEDS_RECONFIRM` 的重复失败是无变化复核（不 bump/不重复审计）。通过时
  `NEEDS_RECONFIRM` → `PENDING_SUBMIT`（+1 + 审计 `REVALIDATION_PASSED`），
  `PENDING_SUBMIT`/`SUBMIT_FAILED` 通过时保持原状态。`expected_revision` 过期 → 409
  `tracking_revision_conflict`；非可复核状态 → 409 `tracking_state_conflict`（两类进
  `extensions/flask_api/api.py` 的 409 分类）。存储 `request_fingerprint` 故意不在
  复核中更新——采纳新方案由 US-225 的 `confirm=true` submit 决定。
- US-223：新增 `GET /api/v1/tracking/items`（`TrackingItemListView`，operationId
  `listTrackingItems`）与 `GET /api/v1/tracking/items/{tracking_id}`
  （`TrackingItemDetailView`，operationId `getTrackingItemDetail`）。读模型
  `apps/migu_orca_web/tracking_read_service.py` 先运行历史回填协调器再读
  `list_tracking_records`/`load_tracking_record`；列表支持 `q`/`status_group`/`sort`（固定枚举）
  与 `summary` 计数（`total/pending/processing/active/needs_attention/unreadable`），单条损坏
  JSON 只增 `unreadable` 计数 + 固定 warning，不阻塞健康列表。`tracking_serializers.py` 负责
  白名单：free-text 标题/字幕组复用 `_safe_label`，`poster_path` 只允许同源 opaque 代理路径，
  `available_actions` 由服务端按 tracking status 计算（只返回当前可执行动作，无 disabled 假动作），
  operation 安全摘要不暴露幂等绑定/fingerprint，审计事件只序列化最近 20 条。详情复用 Request
  `safe-info` 白名单，Request/operation 缺失时降级返回摘要 + 固定 warning。新增
  `tracking_not_found`（404）与 `tracking_storage_error`/`tracking_migration_error`（500）
  分类。DTO/OpenAPI/inventory/TS client 同步无漂移。
- US-222：单番 accept、单番 save-confirm、批量 save-confirm 与 save-confirm 终态重放都在
  Request 进入 ACCEPTED 后调用 `ensure_confirmed_request_tracking`
  （`apps/migu_orca_web/tracking_handoff.py`），经 `ensure_tracking_record`
  （create-if-absent，按确定性 `tracking_id_for_request`）收敛到同一统一追番记录：全新记录
  origin 为 `SAVE_CONFIRM`/`LEGACY_ACCEPT`、status 为 `PENDING_SUBMIT`；已存在记录（含迁移
  记录）原样返回，重复 ensure 不新增记录/不 bump revision/不重复审计。tracking 写失败不
  回滚已确认 Request：单番 save-confirm handoff 扩展
  `tracking_id`/`tracking_status`/`tracking_ready`/`safe_message`（`tracking_ready=false` +
  固定中文 `safe_message`，status 不伪造）；批量 save-confirm 的 CONFIRMED 项返回
  `tracking_id`/`tracking_ready`，单条 tracking 写失败不回滚该条目或其他已确认条目。
- US-217：新增 `GET /api/v1/requests/{request_id}/safe-info`（`RequestSafeInfoView`，
  operationId `getRequestSafeInfo`）。`serialize_request_safe_info` 按 D28-10 默认拒绝
  显式构造白名单（绝不先返回完整 snapshot 再让前端隐藏），返回 `{safe_info: <DTO>}`。
  完整合集/RSS URL、magnet、endpoint、token/cookie/password/Authorization、原始响应与
  本地绝对路径不出现在成功/错误/OpenAPI 示例；`updated_episode=null` 且
  `updated_episode_status=NOT_IMPLEMENTED`（不猜测当前集数）。404/非法 request_id/
  storage profile 错误沿用详情端点同一 envelope 分类。

## 5. 前端依赖（Stage 27 迁移后）

旧单文件前端（`static/app.js`）已在 US-209 删除；Web UI 是 `frontend/` 的
Vue 3 + TypeScript + Vite 工程，生产构建由 Flask 在 `/app/` 同源托管。新前端
只通过 `docs/api/openapi.json` 生成 TypeScript 类型/client（US-198），不手写
第二套响应 interface。以下浏览器侧契约继续生效（与旧前端一致）：

### 5.1 localStorage key（仅这两个，均为非敏感浏览器偏好）

- `miguOrca.web.storageDir`（相对 storage profile 字符串；US-193 起只存服务端允许根目录下的
  相对目录名，绝对路径旧值在读取时被忽略并回退默认根目录）
- `miguOrca.web.saveRequest`（`"true"`/`"false"`）

其它敏感值（endpoint/token/cookie/密码/qBittorrent 凭据）**绝不**写入 localStorage/sessionStorage。

### 5.2 URL 参数（SPA history 状态）

- `?request_id=<id>`：详情选择状态（SPA RequestsView 从 URL query 读取，刷新恢复）。
- `?batch_id=<id>`：批量队列恢复状态（SPA QueueView 从 URL query 读取）。
- `?storage_dir=<profile>`：通过统一 transport 追加到 GET 请求（US-193 起为相对 profile，
  绝不携带绝对路径）。

### 5.3 生命周期（US-190 在 OpenAPI 中记录）

- **request_id**：`POST /api/v1/requests` 生成 → 保存后进入待确认流程（PENDING_CONFIRM）→
  accept/cancel/modify/delete/submit-ab；删除后 `request_not_found`。
  预览草案（`save_request: false`）由服务端权威 draft 持有（见 draft_id），
  `preview-save` 持久化成功后才消费 draft（US-212：写盘失败释放预留可重试），随后获得持久
  request_id。
- **batch_id**：`POST /api/v1/batches/parse` 返回 → accept 建立队列 → queue/submit/retry/recover
  通过 URL `batch_id` 恢复；服务端不持久化解析后的批量（客户端回传卡片）。
- **candidate_context**：`POST /api/v1/mikan/candidates` 在季数需确认时签发（`CandidateSelectionContextStore`，
  TTL 300s、容量 128、单次消费、绑定 mikan_url）；`POST /api/v1/requests` 用
  `candidate_context` + `season_confirmation` 消费，失效 → `candidate_context_invalid`。
- **draft_id**（US-194）：候选与直连生成（`save_request=false`）签发 opaque `draft_id`，
  服务端在 `DraftStore`（`apps/migu_orca_web/drafts.py`）保存权威 PENDING_CONFIRM 草案；
  `preview-modify` 只收 `draft_id` + `base_revision` + 允许 patch（返回更新草案、同一
  draft_id 与新 draft_revision，US-211），`preview-save` 预留并持久化有效 `draft_id` +
  `base_revision`（成功后才消费，重放 → 409 `draft_replayed`；US-212 起写盘失败不丢草案）。
  draft store 有 TTL（默认 30 分钟）、容量上限（128）、自动清理与一次性保存/重放保护；
  过期/逐出/未知 → 409 `draft_expired`/`draft_evicted`；`base_revision` 过期 → 409
  `draft_revision_conflict`；正在保存 → 409 `draft_reserved`。客户端**不再**提交完整
  Request；draft 内容、draft_id 与 revision 绝不进入 URL、browser storage、日志、截图或
  trace，API 只暴露 opaque id 与单调 revision。
- **poster key**：`_serialize_candidate` 通过 `poster_service.register` 签发，同源代理读取，进程内注册表。

## 6. 测试证明

- `tests/api_contract/test_inventory_consistency.py`：清单 ↔ 实际 `url_map` 自动核对，
  漏记端点即失败；不访问真实 MiKan/AutoBangumi/qBittorrent。
- `tests/api_contract/test_golden_contracts.py`：每类端点族的成功、输入失败、
  业务失败与脱敏错误 golden contract（全部基于 fake/隔离，无真实外部写操作）；
  US-192 起断言 HTTP 状态（400/404/409/401/502/503/504/500）与 envelope 双语义。
- `tests/api_contract/test_dto_contracts.py`（US-190）：公开响应 DTO 拒绝未知/敏感字段。
- `tests/api_contract/test_openapi_generation.py`（US-190）：OpenAPI 覆盖全部端点、
  确定性生成、脱敏示例、海报二进制 content type 与漂移检查；`_ENDPOINTS` 注册表的
  `errors` 声明与 `_error_http_status` 分类保持一致。
