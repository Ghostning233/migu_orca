# MiGuOrca Web API 端点清单（US-189 冻结基线）

> 本文档是 Stage 26 US-189 的产物：在改动 HTTP 状态语义**之前**（US-192 待办），
> 先把现有 `/api/v1` 行为、敏感值边界和旧前端依赖冻结成可审查、可自动核对的事实基线。
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
- 当前所有 `/api/v1` JSON 端点失败时 HTTP 状态仍为 **200**（envelope 表达失败），
  HTTP 状态语义修正属于 US-192。唯一例外：`/api/v1/mikan/posters/<key>` 是非 envelope
  二进制端点，失败时直接抛 `Stage1Error`（详见 §4.3 记录的问题）。
- 未注册路由返回 Flask 默认 404 HTML，不属于 API envelope。
- 所有响应在 `failed_response` / `sanitize_error_data` / 各 serializer 白名单中脱敏：
  endpoint、token、cookie、Authorization、SID、password、raw HTML、raw RSS XML、
  原始响应体、完整失败 URL、magnet 与本地绝对路径不得进入 API 展示。

## 2. 端点总表（与 url_map 自动核对）

| 方法 | 路径 | endpoint 名称 | 视图 |
| --- | --- | --- | --- |
| GET | `/api/v1/requests` | `migu_orca_web_api.RequestListView` | RequestListView |
| GET | `/api/v1/requests/<path:request_id>` | `migu_orca_web_api.RequestDetailView` | RequestDetailView |
| POST | `/api/v1/requests` | `migu_orca_web_api.RequestCreateView` | RequestCreateView |
| POST | `/api/v1/requests/preview-modify` | `migu_orca_web_api.RequestPreviewModifyView` | RequestPreviewModifyView |
| POST | `/api/v1/requests/preview-save` | `migu_orca_web_api.RequestPreviewSaveView` | RequestPreviewSaveView |
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
| POST | `/api/v1/batches/<batch_id>/accept` | `migu_orca_web_api.BatchAcceptView` | BatchAcceptView |
| GET | `/api/v1/batches/<batch_id>/queue` | `migu_orca_web_api.BatchQueueView` | BatchQueueView |
| POST | `/api/v1/batches/<batch_id>/submit` | `migu_orca_web_api.BatchSubmitView` | BatchSubmitView |
| POST | `/api/v1/batches/<batch_id>/retry` | `migu_orca_web_api.BatchRetryView` | BatchRetryView |
| POST | `/api/v1/batches/<batch_id>/recover` | `migu_orca_web_api.BatchRecoverView` | BatchRecoverView |
| POST | `/api/v1/qbittorrent/test-connection` | `migu_orca_web_api.QbittorrentTestConnectionView` | QbittorrentTestConnectionView |
| POST | `/api/v1/autobangumi/test-connection` | `migu_orca_web_api.AutoBangumiTestConnectionView` | AutoBangumiTestConnectionView |

页面路由（非 JSON API，供对照）：`GET /` → 302 `/index`；`GET /index`；
`GET /Settings` → 302 `/settings`；`GET /settings`；`GET /migu-orca-static/<path:filename>`；
`GET /healthz`；`GET /readiness`。

## 3. 端点族明细

### 3.1 Requests（`/api/v1/requests`）

公共查询参数（所有 Requests 端点）：`storage_dir`（可选字符串，当前可指向任意本地路径，
US-193 将收紧为服务端允许根目录；CLI 显式 `--storage-dir` 行为不受影响）。

| 端点 | 请求字段 | 成功 `result` | 业务失败示例 |
| --- | --- | --- | --- |
| GET `/api/v1/requests` | `storage_dir?` | `{"requests": [summary...]}` | 损坏 snapshot → `storage_json_error` |
| GET `/api/v1/requests/<request_id>` | `request_id`（路径）、`storage_dir?` | `{"request": <snapshot>, "history": {available, events, error}, "ab_result": {available, record, error}}` | 缺失 → `request_not_found`；路径片段 → `invalid_request_id` |
| POST `/api/v1/requests` | `title`、`source`（`static-fixture`/`mikan`）、`mikan_config?`、`mikan_bangumi?`、`storage_dir?`、`save_request`（默认 false）、`season_confirmation?`、`candidate_context?` | `{"request", "summary", "saved_request"?}` | `data_validation_errors`（title 缺失）；`candidate_context_invalid`；保存失败 → `storage_error` |
| POST `/api/v1/requests/preview-modify` | `request`（完整预览草案）、`patch`、`storage_dir?` | `{"request", "summary"}` | `invalid_modify_patch_field` |
| POST `/api/v1/requests/preview-save` | `request`（完整预览草案）、`storage_dir?` | `{"request", "summary", "saved_request"?}` | 非 PENDING_CONFIRM → `invalid_request_status` |
| POST `/api/v1/requests/<request_id>/accept` | `request_id`（路径）、`storage_dir?` | `{"request", "summary", "saved_request"?}` | 缺失 → `request_not_found`；状态冲突 → `invalid_request_status` |
| POST `/api/v1/requests/<request_id>/cancel` | `request_id`（路径）、`cancel_reason?`、`storage_dir?` | `{"request", "summary", "saved_request"?}` | 同上 |
| POST `/api/v1/requests/<request_id>/modify` | `request_id`（路径）、`patch`、`storage_dir?` | `{"request", "summary", "saved_request"?}` | `invalid_modify_patch_field` |
| POST `/api/v1/requests/<request_id>/delete` | `request_id`（路径）、`storage_dir?` | `{"request_id", "storage", "directory", "filename", "deleted": true}` | 缺失 → `request_not_found` |
| POST `/api/v1/requests/<request_id>/submit-ab` | `request_id`（路径）、`ab_config`（`auth_mode`/`base_url`/`username`/`password`/`token`/`fallback_enabled`）、`storage_dir?` | `{"request", "summary", "ab_submit_result", "saved_request"?, "saved_ab_result"?}` | 非 ACCEPTED → `invalid_request_status` |

`summary` 形状（`request_engine.controllers.request_controller.summarize_request`）：
`request_id`、`status`、`bangumi_title`、`candidate_subtitle_groups[]`
（`subtitle_group`/`rss_url`/`total_seed_count`/`valid_seed_count`/`invalid_seed_count`）、
`selected_subtitle_group`、`effective_seed_count`、`expected_folder_name`、`warnings[]`。

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
| POST `/api/v1/batches/parse` | `raw_input`、`mikan_config?`、`storage_dir?` | `{"batch_id", "raw_input", "items": [item...]}` | 空输入 → `validation_error`「请至少输入一个番剧名称」 |
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

## 4. 敏感值边界（已冻结）

### 4.1 永不进入 API 展示/响应

- `endpoint`、`base_url`、`search_endpoint` 完整值、`token`、`cookie`、`Authorization`、
  `SID`、`username`、`password`、`magnet`、raw HTML、raw RSS XML、原始响应体、
  完整失败 URL、本地绝对路径。
- 连接测试成功响应只回白名单字段；`_sanitize_ab_connection_summary` /
  `_sanitize_qbittorrent_connection_summary` 主动丢弃其他字段。
- 失败 details 经 `sanitize_error_data` 与 `_strip_sensitive_result_fields` 双重脱敏。

### 4.2 request-scoped 配置（不进入 storage JSON / 浏览器 storage / URL / 日志 / trace）

- `mikan_config`、`mikan_bangumi`、`ab_config`、`qbittorrent_config`、`candidate_context`。

### 4.3 已记录的问题（供 US-190/US-192 治理）

- `GET /api/v1/mikan/posters/<key>` 是**函数视图**（非 class-based view），不经过
  `APIBaseView.dispatch_request` 的 envelope 包装。`poster_service.get` 抛出的
  `Stage1Error`（如 `invalid_poster_key`、`poster_not_found`、`poster_unavailable`）在
  TESTING 模式直接上抛，非 TESTING 模式变成 Flask 500 HTML 响应，没有 JSON envelope。
  US-192 修正 HTTP 状态时应把该端点纳入统一错误处理。

## 5. 旧前端依赖（已冻结）

前端：`src/apps/migu_orca_web/static/app.js`（单文件，`/index` 与 `/settings` 共用）。

### 5.1 使用的 API URL（`fetchJson` 调用点）

- `GET /api/v1/requests`（`apiPath` 追加 `?storage_dir=`）
- `GET /api/v1/requests/<request_id>`（`apiPath`）
- `POST /api/v1/requests`（生成；`buildCreateRequestPayload`）
- `POST /api/v1/requests/preview-modify`
- `POST /api/v1/requests/preview-save`
- `POST /api/v1/requests/<request_id>/accept|cancel|modify|delete`
- `POST /api/v1/requests/<request_id>/submit-ab`（Settings，按 `request_id` 上下文）
- `POST /api/v1/mikan/candidates`
- `GET /api/v1/preferences`、`POST /api/v1/preferences`
- `GET /api/v1/corrections`、`POST /api/v1/corrections`
- `POST /api/v1/batches/parse`
- `POST /api/v1/batches/<batch_id>/accept`
- `GET /api/v1/batches/<batch_id>/queue`
- `POST /api/v1/batches/<batch_id>/submit|retry|recover`
- `POST /api/v1/qbittorrent/test-connection`
- `POST /api/v1/autobangumi/test-connection`

### 5.2 localStorage key（仅这两个，均为非敏感浏览器偏好）

- `miguOrca.web.storageDir`（自定义 storage_dir 字符串；US-193 迁移为服务端允许 profile）
- `miguOrca.web.saveRequest`（`"true"`/`"false"`）

其它敏感值（endpoint/token/cookie/密码/qBittorrent 凭据）**绝不**写入 localStorage/sessionStorage。

### 5.3 URL 参数（history 状态）

- `?request_id=<id>`：详情选择状态（`syncRequestIdToUrl`，pushState/replaceState）。
- `?batch_id=<id>`：批量队列恢复状态（`syncBatchIdToUrl`，pushState）。
- `?storage_dir=<path>`：通过 `apiPath()` 追加到 GET 请求（当前语义，US-193 治理）。

### 5.4 生命周期（US-190 在 OpenAPI 中记录）

- **request_id**：`POST /api/v1/requests` 生成 → 保存后进入待确认流程（PENDING_CONFIRM）→
  accept/cancel/modify/delete/submit-ab；删除后 `request_not_found`。
  预览草案（`save_request: false`）只有内存 `request`，`preview-save` 后才获得持久 request_id。
- **batch_id**：`POST /api/v1/batches/parse` 返回 → accept 建立队列 → queue/submit/retry/recover
  通过 URL `batch_id` 恢复；服务端不持久化解析后的批量（客户端回传卡片）。
- **candidate_context**：`POST /api/v1/mikan/candidates` 在季数需确认时签发（`CandidateSelectionContextStore`，
  TTL 300s、容量 128、单次消费、绑定 mikan_url）；`POST /api/v1/requests` 用
  `candidate_context` + `season_confirmation` 消费，失效 → `candidate_context_invalid`。
- **draft_id**（US-194 引入，当前 preview 流程尚无服务端 draft）：候选与直连生成将签发
  opaque `draft_id`，服务端保存权威 PENDING_CONFIRM 草案；preview-modify 只收
  `draft_id` + 允许 patch，preview-save 只消费有效 `draft_id`；draft store 有
  TTL、容量上限、一次性保存与重放保护。当前 `preview-modify`/`preview-save` 仍接收
  客户端完整 Request（旧前端兼容），完整 Request、draft 内容与外部敏感配置绝不进入
  URL 或 browser storage。
- **poster key**：`_serialize_candidate` 通过 `poster_service.register` 签发，同源代理读取，进程内注册表。

## 6. 测试证明

- `tests/api_contract/test_inventory_consistency.py`：清单 ↔ 实际 `url_map` 自动核对，
  漏记端点即失败；不访问真实 MiKan/AutoBangumi/qBittorrent。
- `tests/api_contract/test_golden_contracts.py`：每类端点族的成功、输入失败、
  业务失败与脱敏错误 golden contract（全部基于 fake/隔离，无真实外部写操作）。
- `tests/api_contract/test_frontend_dependencies.py`：冻结 localStorage key、URL 参数与
  前端 fetch 依赖；改动这些契约会立即失败。
- `tests/api_contract/test_dto_contracts.py`（US-190）：公开响应 DTO 拒绝未知/敏感字段。
- `tests/api_contract/test_openapi_generation.py`（US-190）：OpenAPI 覆盖全部端点、
  确定性生成、脱敏示例、海报二进制 content type 与漂移检查。
