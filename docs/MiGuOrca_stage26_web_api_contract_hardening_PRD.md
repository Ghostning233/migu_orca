# MiGuOrca Stage 26 PRD：Web API 契约固化与服务端边界治理

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 项目名称 | MiGuOrca |
| 文档名称 | Stage 26 PRD：Web API 契约固化与服务端边界治理 |
| 文档类型 | Stage PRD |
| 当前状态 | 已完成 |
| 创建日期 | 2026-08-29 |
| Backlog | BL-023 |
| 优先级 | P0 |
| 依赖阶段 | Stage 25 已完成并合入 `main` |
| 规划分支 | `agent/stage26-web-api-contract-hardening` |
| Ralph stories | US-189～US-196 |

## 2. 背景与问题

Stage 25 完成后，MiGuOrca 已具备单个/批量候选搜索、草案编辑、Request 管理、提交前队列、Settings 和外部连接测试等完整用户旅程。主要业务操作已经使用 `/api/v1/*` JSON API，但 Web 工程边界仍由长期增量开发形成：

1. `apps/migu_orca_web/views.py` 曾同时包含请求模型、路由、序列化、错误转换、短期状态和业务编排，文件超过 2,000 行。Stage 26 US-191 已按职责拆分为 `schemas.py`、`serializers.py`、`services.py`、`contexts.py`、`blueprints.py` 与 `routes_*.py`（requests/mikan/batches/settings/connections），`views.py` 仅保留页面路由与 Blueprint 组装；URL、方法与 endpoint 名称保持 golden contract 兼容。
2. 成功和失败使用统一 JSON envelope；US-192 已建立稳定的 HTTP 状态语义（400/404/409/401/502/503/504/500），envelope 形状保持不变，客户端可按状态码分类处理。
3. 响应结构主要由动态 `dict` 拼装，`docs/api/` 没有可校验的 OpenAPI 文档，后续 TypeScript 前端无法安全生成类型。
4. `/requests/preview-save` 接收客户端回传的完整预览 Request；服务端只检查状态后持久化，客户端承担了过多权威状态。
5. Web API 允许浏览器提交任意 `storage_dir`。该能力符合早期本地工具习惯，但如果页面被远程暴露，会扩大服务器文件系统访问范围。
6. 候选选择 context、候选缓存等状态位于单进程内存，当前只适用于本地单进程模式，尚未形成明确部署契约。
7. 现有 Playwright 测试很好地保护了行为，却大量绑定旧 DOM；若不先固化 API，前端大改时很难区分 UI 变化和后端契约回归。

Stage 26 是前端工程化迁移前的 P0 基础阶段。它不重做产品页面，重点是让后端 API 成为稳定、可描述、可独立验证的边界。

## 3. 目标

1. 建立 `/api/v1` 端点清单、请求/响应 DTO 和兼容性基线，覆盖正常、校验失败、业务失败和脱敏错误。
2. 将 Web 请求模型、响应模型、序列化、短期 context、用例编排和路由从单一 `views.py` 中按职责拆分，保持 URL 和用户行为兼容。
3. 生成并校验 OpenAPI 文档，写入 `docs/api/`；契约可供后续 TypeScript 客户端生成使用。
4. 为 API 失败建立正确、稳定的 HTTP 状态语义，同时继续保留现有 `{ok, result}` / `{ok, error_type, error_message, error_data}` envelope。
5. 将 Web storage 限制在服务端允许的根目录内；CLI 的显式本地路径能力不受影响。
6. 用服务端权威、带 TTL 和容量上限的 draft context 代替客户端回传完整 Request 后直接保存，保证修改、保存、过期和重放行为可审核。
7. 明确默认部署为 local-only、单用户、同源；远程暴露必须显式开启并通过安全检查，不在本阶段实现完整账号体系。
8. 建立 CI 与静态质量门禁，为 Stage 27 前端工程提供稳定合并基线。

## 4. 非目标

1. 不引入 Vue、React、Vite 或新的页面组件体系。
2. 不改变 `/index`、`/settings` 的视觉设计和主要 DOM 结构。
3. 不实现多人账号、角色权限、OAuth 或互联网 SaaS 部署。
4. 不迁移本地 JSON storage 到数据库。
5. 不引入后台 worker、消息队列或并发 AutoBangumi 提交。
6. 不实施 BL-020、BL-021、BL-022 或 OF-001。
7. 不允许因拆分 Web 层复制 engine 业务规则。
8. 不向真实 MiKan、AutoBangumi 或 qBittorrent 执行自动化写操作。

## 5. 核心决策

| 编号 | 决策 | 说明 |
| --- | --- | --- |
| D26-01 | `/api/v1` URL 保持兼容 | Stage 27 直接复用现有业务入口，不通过改 URL 制造无收益迁移。 |
| D26-02 | envelope 保持兼容 | HTTP 状态码可以修正，但成功/失败 JSON 外层结构继续存在。 |
| D26-03 | DTO 是公开契约 | Pydantic 请求与响应模型成为 OpenAPI 和契约测试的唯一来源。 |
| D26-04 | OpenAPI 进入版本控制 | `docs/api/openapi.json` 由确定性脚本生成并接受差异审查。 |
| D26-05 | 路由只做适配 | 路由负责校验、调用 application service、转换响应；业务规则留在 engine。 |
| D26-06 | Web storage 由服务端约束 | 浏览器可选择逻辑 storage profile，但不能指定允许根目录之外的文件系统路径。 |
| D26-07 | 草案由服务端权威保存 | 客户端只提交 draft ID 和允许的 patch，不把任意完整 Request 当作可信持久化输入。 |
| D26-08 | local-only 是默认部署契约 | 未配置远程安全模式时，只支持同源、本机、单用户运行。 |
| D26-09 | 兼容迁移逐端点完成 | 每个端点先增加 golden contract，再迁移实现，避免一次性重写 `views.py`。 |
| D26-10 | 前端大改延后到 Stage 27 | Stage 26 只允许维持兼容所需的最小旧前端调整。 |

## 6. 目标结构

目标目录可按实际实现微调，但职责必须独立：

```text
src/apps/migu_orca_web/
  routes/
    pages.py
    requests.py
    mikan.py
    batches.py
    settings.py
    connections.py
  schemas/
    common.py
    requests.py
    mikan.py
    batches.py
    settings.py
  serializers/
  services/
  contexts/
  templates/
  static/
```

- `schemas` 不调用 engine 或访问文件系统。
- `serializers` 只从明确输入生成公开 DTO，不包含敏感字段。
- `services` 编排现有 engine/repository，不复制标题、筛选、Request 或提交状态规则。
- `contexts` 管理有界、过期、可消费的 draft/candidate 临时能力。
- `routes` 不直接拼装复杂业务结果。

## 7. API 契约要求

### 7.1 统一响应

成功继续返回：

```json
{"ok": true, "result": {}}
```

失败继续返回：

```json
{
  "ok": false,
  "error_type": "validation_error",
  "error_message": "请求参数不合法",
  "error_data": {"errors": []}
}
```

所有响应模型必须阻止未知敏感字段穿透。OpenAPI 示例只能使用虚构、脱敏值。

### 7.2 HTTP 状态

至少建立以下映射：

| 情况 | HTTP 状态 |
| --- | --- |
| 成功读取或修改 | 200 |
| 输入/Pydantic 校验失败 | 400 |
| Request、queue、draft 不存在 | 404 |
| 状态冲突、重放或 context 失效 | 409 |
| 外部依赖超时或不可达 | 502/504，按稳定分类映射 |
| 未处理服务端错误 | 500 |

旧前端 `fetchJson` 必须在兼容期同时正确处理 HTTP 非 2xx 和现有 envelope；错误页面不得回显原始响应或敏感配置。

### 7.3 OpenAPI

- 提供确定性生成命令并在 CI 校验生成结果无漂移。
- 覆盖所有 `/api/v1` JSON 端点；海报二进制端点单独声明 content type 和错误响应。
- 记录 `request_id`、`batch_id`、`draft_id`、candidate context 的生命周期。
- 明确哪些配置只能 request-scoped，哪些字段允许进入 storage 或 browser storage。

## 8. 服务端安全边界

### 8.1 Storage

1. CLI 继续接受显式 `--storage-dir`。
2. Web API 默认使用服务器配置的 storage root。
3. 若保留 Web profile，客户端只能提交 profile ID 或允许根目录下的安全相对路径。
4. 绝对路径、`..`、符号链接逃逸和未配置根目录必须 fail closed。
5. 错误和 OpenAPI 示例不能包含真实绝对路径。

### 8.2 Draft

1. 候选选择成功后，服务端签发 opaque `draft_id` 并保存权威 Request 草案。
2. preview modify 只接收 `draft_id` 与允许 patch；返回更新后的公开草案。
3. preview save 只消费有效 `draft_id`，过期、逐出、错配和重放返回稳定冲突错误。
4. draft store 必须有 TTL、容量上限和明确清理行为。
5. 不把 draft、外部配置或完整 RSS/magnet 写入 URL 或浏览器 storage。

### 8.3 部署

1. 默认文档和启动命令保持 loopback/local-only。
2. 健康检查不能暗示外部依赖已就绪；readiness 至少区分应用可启动与 storage 可用。
3. 显式远程模式必须检查可信代理、允许来源、storage root 和敏感连接入口策略。
4. 未提供完整认证时，文档必须明确禁止直接暴露到公网。

## 9. 用户故事

### US-189：冻结现有 API 行为与端点清单

- 枚举所有 `/api/v1` 端点、方法、请求字段、响应字段、状态和敏感值边界。
- 为成功、校验失败、业务失败建立 golden contract 测试。
- 记录现有旧前端依赖的 URL、localStorage key、`request_id`/`batch_id` URL 参数。

### US-190：建立请求/响应 DTO 与 OpenAPI 生成

- 为公开响应建立 Pydantic 模型，禁止任意未知字段进入响应。
- 生成 `docs/api/openapi.json` 和简洁使用说明。
- 提供 CI 可执行的契约漂移检查。

### US-191：拆分 Web schema、serializer 与 application service（已完成）

- 从 `views.py` 迁移请求模型（`schemas.py`）、序列化（`serializers.py`）、业务编排（`services.py`）、短期 context（`contexts.py`）和 Blueprint 定义（`blueprints.py`）。
- 按 requests、mikan、batches、settings、connections 拆分路由（`routes_*.py`）。
- 保持 Blueprint、URL、endpoint 名称和旧页面行为兼容（golden contract + 浏览器套件全绿）。

### US-192：建立正确 HTTP 状态与兼容错误处理

- 按稳定错误分类映射 400/404/409/502/504/500。
- 旧前端能够解析非 2xx JSON envelope 并保持中文脱敏反馈。
- API 与浏览器测试覆盖网络失败、非 JSON 和未知错误。

### US-193：收紧 Web storage 根目录

- Web API 拒绝允许根目录外的绝对路径、穿越和符号链接逃逸。
- CLI 显式 storage 路径行为不变。
- Settings 从任意路径语义迁移为服务端允许的安全 profile/相对目录语义。
- 已实现（2026-08-30）：`services._storage_dir` 改为相对 profile 解析器（默认根
  `.migu_orca/storage`，可用 `MIGU_ORCA_WEB_STORAGE_ROOT` 服务端覆盖）；新增
  `invalid_storage_dir`（400）；旧前端 `app.js` 对 localStorage 中的绝对路径旧值自动
  回退默认根目录；OpenAPI、契约测试、浏览器测试与文档同步更新。

### US-194：建立服务端权威 draft 生命周期

- 候选与直连生成返回 opaque `draft_id`。
- preview modify/save 使用服务端草案和允许 patch，不再信任客户端完整 Request。
- TTL、容量、消费、过期、重放和失败恢复有单元/API/浏览器回归。
- 已实现（2026-08-30）：新增 `apps/migu_orca_web/drafts.py`（`DraftStore`，TTL 30 分钟、
  容量 128、自动清理、一次性保存 + 重放保护）；`POST /api/v1/requests`
  （`save_request=false`）签发 `draft_id`；`preview-modify` 只收 `draft_id` + 允许 patch
  并回写同一 draft_id；`preview-save` 一次性消费 draft_id 落盘；失效/重放统一 409
  `draft_expired`/`draft_evicted`/`draft_replayed`（错误不回显 draft_id/草案内容）；
  旧前端 `app.js` 在内存持有 `currentDraftId`/`row.draft_id`，完整 Request 不再作为
  权威快照提交；OpenAPI、DTO、契约测试、浏览器测试与文档同步更新。

### US-195：增加 P0 CI、静态检查与部署基线

- CI 执行 compileall、非浏览器测试、JS 语法检查、OpenAPI 漂移和差异检查。
- 可用 runner 执行真实 Chromium 套件；不可用不能静默视为通过。
- 文档明确 local-only 默认、readiness 语义和远程暴露限制。
- 已实现（2026-08-30）：新增 `.github/workflows/ci.yml`（checks job：compileall → ruff
  静态检查 → 非浏览器 pytest → `node --check` → OpenAPI 漂移 → `git diff --check`；
  browser job：`playwright install --with-deps chromium` + 真实 Chromium 套件，
  `MIGU_ORCA_CI=1` 下浏览器不可用直接失败，不静默 skip）。引入 `ruff` 作为 Python 静态
  检查（`pyproject.toml` `[tool.ruff.lint]`：F/E4/E7/E9/W/I/UP/B/SIM，排除 E402/E501/
  B009/UP046/UP047/UP031 并记录理由），并修复全部存量违规；compileall 降级为纯语法
  检查，不再冒充静态检查。`/readiness` 拆分为就绪探针（服务端 storage 根目录可创建/可写
  才 200，否则 503 `{ok: false, result: "storage_unavailable"}`），`/healthz` 保持纯存活
  探针；两者都不访问真实外部系统。README 新增「本地部署基线」：默认 local-only、
  未认证禁止直接暴露公网、storage 根目录、健康/就绪语义与 CI 门禁。

### US-196：Stage 26 兼容回归与文档收尾（已完成）

- 完整单元、API、CLI 和真实 Chromium 用户旅程通过（1019 非浏览器 + 269 真实 Chromium）。
- README、架构、主 PRD、M13/M14、backlog、future stages 与 API 文档同步。
- 输出 Stage 27 前端迁移 handoff，不提前实施新前端。
- 已实现（2026-08-30）：修复 US-193 回归——`_storage_dir(None|""|"  ")` 原来返回
  `None`，导致 `load_storage_config(None)` 回退 CLI 默认 `DEFAULT_STORAGE_DIR`
  （仓库根 `.migu_orca/storage`），绕过服务端 Web storage root 覆盖（含生产
  `MIGU_ORCA_WEB_STORAGE_ROOT`）；现改为返回 `_WEB_STORAGE_ROOT` 本身，并新增 golden
  contract 回归（不传 `storage_dir` 的 `save_request=true` 写入服务端根而非仓库根）。
  Stage 26 prd/progress 已归档到 `scripts/ralph/archive/`，全部 story passes 为 true。
- Stage 27 明确只通过 OpenAPI/DTO 使用后端，不导入旧 `app.js` 内部状态；详细 handoff
  见 `docs/MiGuOrca_stage27_frontend_engineering_migration_PRD.md`。

## 10. 验收命令

```bash
uv run python -m compileall -q src tests
uv run pytest -q -m "not browser"
uv run pytest tests/browser/ -q
uv run pytest -q
node --check src/apps/migu_orca_web/static/app.js
git diff --check
```

Stage 实现后还必须运行 OpenAPI 生成/漂移命令和新增静态检查命令；具体命令由 US-190/US-195 写入 `pyproject.toml`、README 与 CI。

## 11. 完成标准

1. `/api/v1` 有完整、可生成客户端的版本化契约。
2. `views.py` 不再同时承担全部 schema、序列化、context 和业务编排职责。
3. 旧 Web UI 在不改变主要视觉和用户流程的情况下继续工作。
4. Web 客户端不能选择服务器允许根目录之外的 storage。
5. 未保存草案由服务端权威 draft 管理，不能通过客户端完整对象伪造后直接持久化。
6. HTTP 状态、JSON envelope、错误脱敏和敏感值不落盘均有自动化证明。
7. Stage 27 可以只依赖 OpenAPI/DTO 开始新前端开发，无需导入旧 `app.js` 内部实现；详细 handoff 见 `docs/MiGuOrca_stage27_frontend_engineering_migration_PRD.md`。
