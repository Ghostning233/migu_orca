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
- `views.py`：仅保留 Jinja 页面路由 + 导入 route 模块（导入副作用即注册端点）+ 再导出 blueprints；同时为测试兼容再导出 `CandidateSelectionContextStore` / `candidate_selection_contexts`。
- `__init__.py` 的 `blueprints = [web_blueprint, api_blueprint, app_blueprint]` 由 `apps/registry.py` 消费。

## SPA 托管与 fallback 边界（US-197）

- Vite `base` 固定为 `/app/`，`frontend/dist/` 的 `index.html` 引用 `/app/assets/*`；
  Flask 的 `app_blueprint` 在 `/app/` 同源托管，生产不依赖 Node 运行时。
- **fallback 只接管 `/app/*`**：`/api/v1/*`、海报、`/migu-orca-static/*`、`/healthz`、
  `/readiness`、旧 `/index`、`/settings` 都由各自的 Flask 路由处理，绝不能被 `/app/<path:subpath>`
  截获（`tests/api_contract/test_inventory_consistency.py` 只核对 `/api/v1`，但
  `src/apps/migu_orca_web/app_routes_test.py` 断言非 `/app` 路由端点不属于 `migu_orca_app.*`）。
- `frontend/dist` 不入库；CI 的 frontend/browser job 在跑套件前执行 `npm ci && npm run build`。
  浏览器测试 `tests/browser/test_app_shell.py` 在 `MIGU_ORCA_CI=1` 下缺构建直接失败（不 skip）。
- US-199 起 SPA 客户端路由为 4 条：`/app/workbench`、`/app/requests`、`/app/queue`、
  `/app/settings`（history base `/app/`，见 `frontend/src/app/router/index.ts`）。这些是
  客户端路由，Flask 侧除 `/app/` 与 `/app/<path:subpath>` fallback 外**不需要**新增任何
  服务端路由；浏览器测试在 `test_app_shell.py` 断言 4 项导航与各 route 挂载。

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

## 服务端权威草案（US-194）

- 未保存预览草案由服务端 `drafts.py:DraftStore` 持有（进程内单例 `draft_store`，TTL 30 分钟、
  容量 128、自动清理、一次性保存 + 重放保护）。`POST /api/v1/requests`（`save_request=false`）
  在响应里签发 opaque `draft_id`；`preview-modify` 只收 `draft_id` + 允许 patch 并回写同一
  draft_id；`preview-save` 一次性消费 `draft_id` 后落盘。
- 客户端**绝不**把完整 Request 作为权威快照提交；前端只在内存持有 `draft_id`
  （`app.js` 的 `currentDraftId` / 批量卡片的 `row.draft_id`），不写 URL/browser storage。
- 失败语义统一 409：`draft_expired`（过期/未知）、`draft_evicted`（容量满）、
  `draft_replayed`（重复保存）；错误 details 不回显 draft_id 或草案内容。
- 测试：`DraftStore` 是进程级单例，必须在 `views_test`/`api_contract`/`browser` 的
  autouse fixture 里 `draft_store.clear()`；浏览器 mock 用 conftest 的
  `preview_result_json(request)`（签发真实 draft 并返回 draft_id）与
  `save_preview_handler(calls?)`（消费 draft 并返回保存结果），批量卡片 mock 用
  `issue_draft_id(preview_request)` 给每个 `preview_request` 补 draft_id。
- 新增/修改 preview 端点后同步 `docs/api/endpoint_inventory.md` §3.1/§5.4 与 OpenAPI 注册表。

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
