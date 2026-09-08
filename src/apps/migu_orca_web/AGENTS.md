# AGENTS.md — apps/migu_orca_web

Stage 26 US-191 将原先 2,000+ 行的 `views.py` 按职责拆分。新增/修改 Web API 代码时遵循以下约定。

## 模块职责（拆分后的布局）

- `blueprints.py`：定义 `api_blueprint` / `web_blueprint`（唯一 Blueprint 归属地，避免循环导入）。
- `schemas.py`：请求/查询 Pydantic 模型（`RequestCreatePayload` 等）。响应 DTO 在 `api_contract.py`。
- `serializers.py`：响应序列化与脱敏白名单（`_serialize_*`、`_sanitize_*`、`_strip_sensitive_result_fields`）。
- `services.py`：用例编排与存储 seam（`_storage_dir`、`_resolve_mikan_config`、`_search_*`、`_build_batch_*`），复用 engine/repository，不复制业务规则。
- `contexts.py`：短期候选选择上下文（`candidate_selection_contexts` / `CandidateSelectionContextStore`）。
- `drafts.py`（US-194）：服务端权威未保存草案存储（`draft_store` / `DraftStore`，TTL 30 分钟、
  容量 128、一次性保存与重放保护）；`preview-modify`/`preview-save` 只接受 opaque `draft_id`。
- `routes_requests.py` / `routes_mikan.py` / `routes_batches.py` / `routes_settings.py` / `routes_connections.py`：按端点族注册 `/api/v1` 路由。
- `routes_app.py`（US-197）：`app_blueprint` 托管 Vue SPA——`/app/` 外壳、`/app/<path:subpath>`
  fallback（真实构建文件直接服务，其余 `/app/*` 返回 SPA 外壳）、`_dist_dir()` 指向
  `frontend/dist/`（无构建时返回依赖无关的占位模板，测试 monkeypatch `_dist_dir`）。
- `views.py`：仅保留 Web 入口重定向路由（`/`、`/index`、`/Settings`、`/settings` → SPA，
  US-209 起旧 Jinja 页面已删除）+ 导入 route 模块（导入副作用即注册端点）+ 再导出
  blueprints；同时为测试兼容再导出 `CandidateSelectionContextStore` /
  `candidate_selection_contexts`。
- `__init__.py` 的 `blueprints = [web_blueprint, api_blueprint, app_blueprint]` 由 `apps/registry.py` 消费。

## SPA 托管与 fallback 边界（US-197）

- Vite `base` 固定为 `/app/`，`frontend/dist/` 的 `index.html` 引用 `/app/assets/*`；
  Flask 的 `app_blueprint` 在 `/app/` 同源托管，生产不依赖 Node 运行时。
- **fallback 只接管 `/app/*`**：`/api/v1/*`、海报、`/healthz`、`/readiness`、入口路由
  （`/`、`/index`、`/Settings`、`/settings`）都由各自的 Flask 路由处理，绝不能被
  `/app/<path:subpath>` 截获（`tests/api_contract/test_inventory_consistency.py` 只核对
  `/api/v1`，但 `src/apps/migu_orca_web/app_routes_test.py` 断言非 `/app` 路由端点
  不属于 `migu_orca_app.*`）。
- `frontend/dist` 不入库；CI 的 frontend/browser job 在跑套件前执行 `npm ci && npm run build`。
  浏览器测试 `tests/browser/test_app_shell.py` 在 `MIGU_ORCA_CI=1` 下缺构建直接失败（不 skip）。
- US-199 起 SPA 客户端路由为 4 条：`/app/workbench`、`/app/requests`、`/app/queue`、
  `/app/settings`（history base `/app/`，见 `frontend/src/app/router/index.ts`）。这些是
  客户端路由，Flask 侧除 `/app/` 与 `/app/<path:subpath>` fallback 外**不需要**新增任何
  服务端路由；浏览器测试在 `test_app_shell.py` 断言 4 项导航与各 route 挂载。

## 默认入口（US-209）

- `views.py` 的入口路由**始终重定向到 SPA**（旧 Jinja 页面与 `web_entry_mode()`
  已在 US-209 删除）：`GET /`、`GET /index` → `/app/workbench`，`GET /Settings`、
  `GET /settings` → `/app/settings`，保留 `request_id`/`batch_id` query。
- 重定向只转发公开已保存标识符（`request_id`/`batch_id`），endpoint/token/storage
  路径等敏感值绝不进入重定向 URL（
  `app_routes_test.py::test_spa_entry_never_forwards_sensitive_query_values` 守护）。
- `web_blueprint` 不再挂 `static_folder`/`template_folder`（旧 `app.js`/`style.css`/
  Jinja 模板已删）；`blueprints.py` 只定义 Blueprint 对象，SPA 由 `app_blueprint` 托管。

## 路由注册与测试 seam 的坑

- route 模块**导入即注册**：`views.py` 必须 import 所有 `routes_*` 模块，否则端点不注册（`tests/api_contract/test_inventory_consistency.py` 会失败）。
- monkeypatch 目标必须指向**符号实际被调用处的模块命名空间**，不是定义处：
  - 路由类里调用的 `generate_request`/`apply_request_save_action`/`delete_request_snapshot` → patch `apps.migu_orca_web.routes_requests.<sym>`。
  - `_search_batch_item_candidates`/`_batch_title_parsing_provider` 在 `routes_batches` 命名空间调用 → patch `apps.migu_orca_web.routes_batches.<sym>`；`_search_candidates_from_parse_result` 在 `routes_mikan` 调用。
  - `test_ab_connection`/`test_qbittorrent_connection` → patch `routes_connections.<sym>`；`save_user_preferences` → patch `routes_settings.<sym>`。
  - `mikan_client_module.create_mikan_client`/`candidate_search_cache` 在 `services` 命名空间使用 → patch `apps.migu_orca_web.services.<sym>`。
  - 上下文单例从 `apps.migu_orca_web.contexts` 导入（`views` 也再导出，两者指向同一对象）。
- 新增/删除 `/api/v1` 端点必须同步 4 处，否则 CI 失败：
  1. `docs/api/endpoint_inventory.md` §2 总表 + §5.1 前端依赖（若 app.js 使用）；
  2. `src/apps/migu_orca_web/openapi_gen.py` 的 `_ENDPOINTS` 注册表；
  3. 重新生成 `docs/api/openapi.json`（`uv run python -m apps.migu_orca_web.openapi_gen`）；
  4. `tests/api_contract/` 相关 golden/DTO 测试。
- 响应 DTO 全部 `extra="forbid"`；深层的 engine dict（request 快照、parse_result、queue item 等）在 DTO 内仍为 `dict[str, Any]`，脱敏由 serializer 白名单负责。

## HTTP 状态语义（US-192）

- **envelope 形状不变，状态码表达失败分类**：`extensions/flask_api/api.py:_error_http_status`
  是唯一分类来源（400/404/409/401/502/503/504/500），路由**不得**硬编码状态码。
- `openapi_gen.py` 的 `_ENDPOINTS` 注册表 `errors` 声明必须与 `_error_http_status` 分类一致；
  改分类或改注册表都要跑 `uv run python -m apps.migu_orca_web.openapi_gen` 重生成
  `docs/api/openapi.json`。`tests/api_contract/test_openapi_runtime_consistency.py`（US-198）
  自动核对：每个声明 status/error_type 与运行时分类一致、每个被分类的 error_type 都有声明
  （或列入该文件的显式豁免集）、operationId 唯一/可读/稳定、前端生成客户端不漂移。
- 新增 `Stage1Error` error_type 时：若它属于已分类语义（not_found/conflict/timeout/
  auth/upstream），直接加入 `_error_http_status` 对应集合；未知 error_type 默认 400。
  若该 error_type 会作为 API envelope 失败返回，必须在对应 `_ENDPOINTS` 条目声明；
  若只在 CLI/批内 item 结果等非 envelope 路径出现，加入
  `test_openapi_runtime_consistency.py` 的 `_UNDOCUMENTED_ERROR_TYPES` 豁免集。
- `_ENDPOINTS` 每个条目**必须显式声明可读 `operationId`**（如 `listRequests`、
  `submitBatchQueue`）；不要把新端点交给自动推导，否则可读性测试失败。
- 海报二进制端点 `GET /api/v1/mikan/posters/<key>`（函数视图）在 `routes_mikan.py` 里
  用 `try/except Stage1Error` + `failed_response(..., status=_error_http_status(...))`
  统一错误处理，成功仍返回图片字节。

## 安全边界

- 外部 endpoint、token、cookie、password、raw HTML/RSS、完整失败 URL、magnet、本地绝对路径不得进入 API 展示、storage、URL、browser storage、日志或 trace。
- 新增响应字段时走 `serializers.py` 的白名单/脱敏路径，不要直接回传 engine dict。

## Web storage 根目录（US-193）

- Web API 的 `storage_dir` 只能选择服务端根目录下的**相对 profile**；解析统一在
  `services._storage_dir`（`_WEB_STORAGE_ROOT` 为服务端根，默认 `.migu_orca/storage`，
  可用 `MIGU_ORCA_WEB_STORAGE_ROOT` 环境变量覆盖，测试用 `services.set_web_storage_root`）。
- 绝对路径（Unix `/...`、Windows `C:\...`）、`..` 穿越、符号链接逃逸 → 400
  `invalid_storage_dir`，details 只含 `field`/`reason`，绝不回显原始路径。
- **空值必须解析为服务端根**：`_storage_dir(None|""|"  ")` 返回 `_WEB_STORAGE_ROOT`
  （US-196 回归修复），**绝不**返回 `None`——`load_storage_config(None)` 会回退到 CLI
  默认 `DEFAULT_STORAGE_DIR`（仓库根 `.migu_orca/storage`），绕过服务端 root 覆盖
  （含生产 `MIGU_ORCA_WEB_STORAGE_ROOT`）。新增/修改任何取 `_storage_dir(...)` 的端点后，
  检查该端点在不传 `storage_dir` 时仍写入服务端根而非仓库根。
- CLI `--storage-dir` 是不同信任边界（显式本地路径），不要用 Web 解析器约束它。
- 浏览器测试：`set_storage_preferences` 存 profile 名（`storage_dir.name`），server 端
  `_web_storage_root` fixture 指向 tmp 父目录；不要往 localStorage/URL/payload 里放绝对路径。
- 修改 `_error_http_status` 或 `_ENDPOINTS` 的 errors 后必须重生成 `docs/api/openapi.json`。

## 服务端权威草案（US-194 / US-210 / US-211 / US-212）

- 未保存预览草案由服务端 `drafts.py:DraftStore` 持有（进程内单例 `draft_store`，TTL 30 分钟、
  容量 128、自动清理、一次性保存 + 重放保护）。`POST /api/v1/requests`（`save_request=false`）
  在响应里签发 opaque `draft_id` **和单调 `draft_revision`（=1）**；`preview-modify` 只收
  `draft_id` + `base_revision` + 允许 patch，做 compare-and-swap（成功 revision+1，返回新
  `draft_revision`）；`preview-save` 只收 `draft_id` + `base_revision`。
- **保存生命周期（US-212）**：`preview-save` 用 `draft_store.reserve_for_save(draft_id,
  base_revision)` 预留草案并取回权威 Request → `apply_request_save_action` 持久化 → 成功才
  `draft_store.commit_save(draft_id)`（写重放 tombstone）；持久化/校验抛异常必须在 except 里
  `draft_store.release_save(draft_id)` 释放，草案保留原 revision 可重试。**不要**再在持久化前
  `consume_for_save`（旧语义会让写盘失败丢草案）。预留期间并发 get/CAS/consume/update/逐出/
  过期都返回 `REASON_RESERVED`（路由映射 409 `draft_reserved`）。
- 客户端**绝不**把完整 Request 作为权威快照提交；前端只在内存持有 `draft_id`/`draft_revision`
  （新前端 DraftPreviewPanel 的局部 ref / 批量卡片的字段），不写 URL/browser storage。
- 失败语义统一 409：`draft_expired`（过期/未知）、`draft_evicted`（容量满）、
  `draft_replayed`（重复保存）、`draft_revision_conflict`（base_revision 过期，US-211）、
  `draft_reserved`（保存中，US-212）；错误 details 不回显 draft_id、revision 以外的值或草案
  内容（conflict 只含 `field=base_revision` + `current_revision`）。新 error_type 必须加入
  `extensions/flask_api/api.py` 的 409 集合并声明到 `openapi_gen._ENDPOINTS`。
- `preview-modify` 的 `base_revision` 校验走 `draft_store.compare_and_swap`，不要用旧的
  `draft_store.update`（无 CAS，属 US-210 前语义）。
- 测试：`DraftStore` 是进程级单例，必须在 `views_test`/`api_contract`/`browser` 的
  autouse fixture 里 `draft_store.clear()`；浏览器 mock 用 conftest 的
  `preview_result_json(request)`（签发真实 draft 并返回 draft_id + draft_revision）与
  `save_preview_handler(calls?)`（消费 draft 并返回保存结果），批量卡片 mock 用
  `issue_draft_id(preview_request)` 给每个 `preview_request` 补 draft_id。
- 新增/修改 preview 端点后同步 `docs/api/endpoint_inventory.md` §3.1/§4.2/§5.3 与 OpenAPI 注册表。

## 保存确认幂等协议（US-213，US-214 将接线）

- 持久化幂等记录在 storage profile 的 `<storage>/idempotency/<opaque-key>.json`（
  `storage_engine.controllers.idempotency_repository`）。记录字段白名单：
  `idempotency_key/operation/request_fingerprint/request_id/state/created_at/updated_at`；
  原子写 = temp 文件 + `os.replace`，绝不保存 draft/标题/URL/凭据/绝对路径。
- 指纹：`apps/migu_orca_web/save_confirm_service.compute_request_fingerprint(request)`
  只对允许业务字段（status/raw_title/bangumi_title/selected_subtitle_group/filter_rule/
  expected_folder_name）做规范化 sha256；排除 `request_id`（重新生成的草案是同一用户操作）与
  一切敏感字段。
- `run_save_confirm(...)` 是可复用组合协调器，US-214 用注入 seam（reserve_draft /
  persist_pending / confirm_saved / commit_draft / release_draft）接真实
  DraftStore/entry-controller 流。状态机要点：
  - 终态（`CONFIRMED`/`SAVED_CONFIRM_FAILED`）同键重放前经无副作用 `peek_draft`
    （`DraftStore.peek`）核对仍存在草案的 fingerprint：指纹不一致 → 409
    `idempotency_conflict`（草案保持可用，不被预留/消费）；草案缺失/预留/无 seam → 安全重放；
  - `IN_PROGRESS` 重试先用 `resolve_in_progress_retry` 核对已落盘 Request（在 → 继续确认；
    不在 → 只在仍持有效 reservation 时重试保存），不无条件新建 Request；
  - 首次写盘成功后记录保持 `IN_PROGRESS` 并绑定 `request_id`，崩溃后重试靠 rule 3 收敛；
    确认失败才转 `SAVED_CONFIRM_FAILED`（消费 draft 防重复）并让客户端用
    `ACCEPT_SAVED_REQUEST` 动作重试。
  - 同键不同 operation/payload → Stage1Error `idempotency_conflict`（409，details 只含
    `field`/`reason`），错误经 `_error_http_status`/`sanitize_error_data` 不回显 payload。
- `POST /api/v1/requests/save-confirm`（US-214）接线：route 用 `services._build_save_confirm_persist_pending`
  /`_build_save_confirm_confirm_saved` + DraftStore `reserve_for_save`/`commit_save`/`release_save`
  闭包注入 `run_save_confirm`。成功 = `{outcome: CONFIRMED, request, summary, handoff:{request_id,
  status: ACCEPTED, next_action: OPEN_TRACKING}}`（DTO `RequestSaveConfirmResultDTO` strict）；
  确认失败（Request 已落盘）→ Stage1Error `save_confirm_failed`（409，details 白名单只含
  `outcome=SAVED_CONFIRM_FAILED`/`request_id`/`retry_action=ACCEPT_SAVED_REQUEST`，
  `build_saved_confirm_failed_error` 构造）。monkeypatch 持久化失败要 patch
  `apps.migu_orca_web.services.apply_request_save_action`（seam 在 services 命名空间调用），
  确认失败 patch `apps.migu_orca_web.routes_requests._build_save_confirm_confirm_saved`。
- 新增会触发该错误的端点时，把 `idempotency_conflict` 从
  `tests/api_contract/test_openapi_runtime_consistency.py::_UNDOCUMENTED_ERROR_TYPES`
  移到对应 `_ENDPOINTS` 声明。

## 批量 36 部服务端边界（US-215）

- `POST /api/v1/batches/parse` 在 route 里先按规范化非空行计数（
  `batch_draft_controller.split_batch_raw_input`——`create_batch_draft` 也用同一 splitter，
  计数与 engine 拆分的 item 数永远一致），**早于** 标题解析 / MiKan / 持久化 seam。
  0 行 → `validation_error`「请至少输入一个番剧名称」；超过 `MAX_BATCH_ITEMS = 36`（
  `batch_engine/models` 导出）→ Stage1Error `batch_limit_exceeded`（HTTP 400，属
  `_error_http_status` 的 `_HTTP_BAD_REQUEST_ERROR_TYPES`），`error_data.details` 只含
  `field=raw_input`/`limit=36`/`actual`，绝不回显原始批量输入行。
- 新增/修改会返回该错误的端点时，把 `batch_limit_exceeded` 声明到对应 `_ENDPOINTS` 的 400
  errors（runtime-consistency 测试要求每个被分类 error_type 都有文档声明）。

## 批量 save-confirm 逐条部分成功（US-216）

- `POST /api/v1/batches/{batch_id}/save-confirm`（`routes_batches.BatchSaveConfirmView`，
  operationId `saveConfirmBatchItems`）每条复用单番 save-confirm 用例：route 用
  `_run_draft_save_confirm`（`routes_requests.py`，DraftStore reserve/commit/release +
  `services._build_save_confirm_*` seam 注入 US-213 `run_save_confirm`）处理一条
  `(item_id, draft_id, base_revision, idempotency_key)`，再经
  `save_confirm_service.build_batch_process_one` / `run_batch_save_confirm` /
  `serialize_batch_save_confirm_result` 返回 HTTP 200 逐条部分成功
  `{batch_id, results[], summary:{requested, confirmed, failed}}`。
- 请求 schema `BatchSaveConfirmPayload`（schemas.py）每条 `item_id/draft_id/base_revision/
  idempotency_key` + 可选 `item_ids`（保持输入顺序）；响应 DTO
  `BatchSaveConfirmResultDTO` + `BatchSaveConfirmItemResultDTO`（strict `extra="forbid"`）。
- 可预期单条失败（`draft_*`/`idempotency_conflict`/`save_confirm_failed`/`storage_*`）映射为
  逐条脱敏 `failed` 结果（HTTP 仍 200），成功项不因失败项回滚；同一请求内重复 `item_id`
  → `skipped`（不二次触碰 draft）。请求级 shape/batch_id/storage profile 错误仍走普通失败
  envelope。同一 item + 同 `idempotency_key` 重试重放同一 CONFIRMED；不同键重放已保存草案
  → 逐条 `draft_replayed` failed。
- monkeypatch 确认失败要 patch `apps.migu_orca_web.routes_requests._build_save_confirm_confirm_saved`
  （`_run_draft_save_confirm` 在 routes_requests 命名空间调用该工厂）；持久化失败 patch
  `apps.migu_orca_web.services.apply_request_save_action`。
- 改批量 save-confirm 后必须重生成 `docs/api/openapi.json` 与 `frontend/src/api/generated/api.ts`，
  并同步 endpoint inventory §2/§3.4/§4 与 `api.test.ts` 期望集。

## Request safe-info 严格白名单（US-217）

- `GET /api/v1/requests/{request_id}/safe-info`（`routes_requests.RequestSafeInfoView`，
  operationId `getRequestSafeInfo`）返回 `{safe_info: <RequestSafeInfoDTO>}`。route 只读
  `RequestDetailQuery`（request_id 路径 + 可选 storage_dir），失败（404/非法 request_id/
  storage profile 错误）沿用详情端点同一 envelope 分类。
- DTO（`api_contract.py`）全 strict `extra="forbid"`：`RequestSafeInfoDTO` +
  `RequestSafeInfoCollectionDTO`/`RequestSafeInfoSubtitleGroupDTO`/
  `RequestSafeInfoFilterRuleDTO`/`RequestSafeInfoExcludedFileDTO`/
  `RequestSafeInfoResourcesDTO`/`RequestSafeInfoHistoryEventDTO`/
  `RequestSafeInfoAbStatusDTO` + 外层 `RequestSafeInfoResultDTO`。未知嵌套字段、
  endpoint、URL、token/cookie/password/Authorization、magnet、原始响应与绝对路径在边界
  被拒绝或完全省略。
- **默认拒绝**：`serializers.serialize_request_safe_info` 逐字段显式构造白名单，绝不返回
  完整 snapshot 再让前端隐藏。`updated_episode` 恒为 `null`、
  `updated_episode_status` 恒为 `NOT_IMPLEMENTED`（BL-020 不实现，绝不从种子/RSS/下载
  数量猜测当前集数）。
- 免费文本 label 经 `_safe_label` 二次脱敏（Stage 28 静态审查修复后收紧）：非字符串值
  一律返回 `None`（绝不 `str(dict/list)`）；字符串中**任意位置**出现的 `http(s)/ftp/file/ws`
  等 scheme、`magnet:?`、Unix 绝对路径、Windows 盘符、UNC 路径与
  `token/password/cookie/authorization/endpoint/rss_url` 等 `key=value`/`key:value` 敏感文本
  都稳定替换为 `[redacted]`；普通中文标题/字幕组/文件名/过滤规则不被误删。`total_episodes`
  目前无数据源，serializer 恒置 `null`（不要从 `MikanCandidate.total_episodes` 推断）。
- `storage_profile` 用 `services._storage_profile(storage_dir)`（解析后相对服务端
  Web storage root 的首段 profile 名，根目录/越界 → `None`）。不要回传原始 snapshot。
- 改 safe-info DTO/serializer 后必须重生成 `docs/api/openapi.json` 与
  `frontend/src/api/generated/api.ts`，并同步 endpoint inventory §2/§3.1/§4 与
  `api.test.ts` 期望集（operationId 数 26 → 27）。

## MiKan 候选公开 DTO（US-204）

- `POST /api/v1/mikan/candidates` 的 `result.candidates` 在
  `api_contract.py` 里是 `list[MikanCandidateDTO]`（strict `extra="forbid"`），每个候选只
  暴露公开白名单：`bangumi_id/title/mikan_url/poster_url/source_query/aliases/
  recommendation/total_episodes/season_evidence/candidate_context`。engine 字段
  （raw_html/raw_rss_xml/token/cookie/raw_response_body）在边界被拒绝，测试见
  `test_dto_contracts.py::test_mikan_candidate_dto_rejects_unknown_or_sensitive_fields`。
- `season_evidence` 用 lenient `SeasonEvidenceDTO`（`_SnapshotBase`，`extra="allow"`）：
  `status`（PROVEN/NEEDS_CONFIRMATION/CONFLICT/NONE）+ `season` + `requires_review`，
  只作公开审核摘要；前端绝不把 parser 提示当作真实季数证据（只有显式确认 checkbox 或
  服务端一次性 `candidate_context` 能成为证据）。
- 改 `MikanCandidateResultDTO`/候选白名单后必须重生成 `docs/api/openapi.json` 与
  `frontend/src/api/generated/api.ts`（drift check 双守护），并同步
  `test_golden_contracts.py::test_golden_mikan_candidates_success` 的白名单集合断言。

## 批量公开 DTO（US-205）

- `BatchParseResultDTO.items` 是 `list[BatchParseItemDTO]`（lenient `_SnapshotBase`，
  `extra="allow"`）：类型化 parse 摘要/candidates/preview_request/draft_id/error 等公开
  字段，同时允许引擎继续追加 review 元数据。**内嵌 `candidates` 仍是 strict
  `MikanCandidateDTO`**——原始 engine 字段在嵌套层被拒绝（测试见
  `test_dto_contracts.py::test_batch_parse_dto_accepts_real_serialized_items`）。
- `BatchQueueResultDTO.queue` / `BatchAcceptResultDTO.queue` 用 lenient
  `BatchQueueDTO` + `BatchQueueItemDTO`（只含公开非敏感字段：item_id/request_id/title/
  status/status_label/attempts/last_error/ab_result_summary）；accept/submit 结果项用
  lenient `BatchResultItemDTO`（accept 带 `queued`、submit/retry/recover 带 `attempts`，
  一个 lenient shape 覆盖两个 family 的共享字段）。envelope 仍 strict
  `extra="forbid"`。
- 改批量 DTO 后必须重生成 `docs/api/openapi.json` 与 `frontend/src/api/generated/api.ts`
  （drift check 双守护）；`test_dto_contracts.py` 用真实 serializer 输出断言嵌套白名单。

## 静态检查与就绪探针（US-195）

- 静态检查是 `uv run ruff check src tests`（`pyproject.toml` `[tool.ruff.lint]`：
  F/E4/E7/E9/W/I/UP/B/SIM，排除 E402/E501/B009/UP046/UP047/UP031）。新增代码必须通过
  ruff；`compileall` 只是语法检查，不替代静态检查。
- 就绪探针 `src/apps/healthz/views.py:readiness` 通过 `services._web_storage_root()` +
  `ensure_storage_layout(load_storage_config(...))` 检查服务端 storage 根目录；`healthz`
  是纯存活探针。两者都不访问真实外部系统；测试用 `set_web_storage_root(tmp_path)` 隔离，
  避免创建仓库根 `.migu_orca/storage`。
- CI（`.github/workflows/ci.yml`）在 `MIGU_ORCA_CI=1` 下浏览器不可用会失败而不是静默
  skip；浏览器测试 conftest 的 `pytest_collection_modifyitems` 处理该逻辑。

## SPA 静态缓存与构建产物（US-207）

- `routes_app.py` 的缓存策略：`/app/assets/*`（Vite 内容哈希文件名）返回
  `public, max-age=31536000, immutable`；SPA shell（`/app/` 与 `/app/<path:subpath>`
  的 fallback）返回 `no-cache`——部署换哈希后不会 pin 旧资源。改缓存策略必须同步
  `app_routes_test.py` 的 `test_app_assets_served_with_immutable_cache` /
  `test_app_shell_never_cached`。
- `frontend/dist` 永不提交 `.map` 文件（`sourcemap: false` + gitignore）：
  `app_routes_test.py::test_build_has_no_sourcemaps` 断言 build 无 `.map` 且 asset
  无 `sourceMappingURL`，避免公开 sourcemap 泄漏源码与可能的敏感字面量。
- 路由返回类型：`app_shell`/`app_fallback` 现在返回 `Response`（带 Cache-Control
  头），不再是裸 `str`；新增 `/app/*` 处理函数时保持 `Response` 返回并显式设置
  缓存头，不要依赖默认缓存。
