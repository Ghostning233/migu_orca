# MiGuOrca Stage 27 PRD：前端工程化迁移与页面重构

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 项目名称 | MiGuOrca |
| 文档名称 | Stage 27 PRD：前端工程化迁移与页面重构 |
| 文档类型 | 执行 PRD / Stage 26 handoff |
| 当前状态 | 已完成启动校准，进入开发准备 |
| 创建日期 | 2026-08-29 |
| 优化日期 | 2026-08-30 |
| Backlog | BL-024 |
| 优先级 | P1 |
| 前置条件 | Stage 26 API DTO、OpenAPI、HTTP 状态、storage 与 draft 边界全部完成（已满足） |
| 执行分支 | `agent/stage27-frontend-engineering-migration` |
| Ralph stories | US-197～US-209 |

## 2. 背景

当前 Web UI 已承载完整业务，但工程形态仍是两份 Jinja 页面、一份约 5,250 行原生
JavaScript 和一份全局 CSS。全局 DOM 引用、页面状态、API 调用、渲染函数和敏感表单逻辑
集中在同一个 IIFE 中；继续增量开发会放大状态耦合和浏览器回归成本。

Stage 26 已把 `/api/v1` 固化为可审查的后端边界：端点清单、golden contract、响应 DTO、
确定性 OpenAPI、稳定 HTTP 状态、服务端 Web storage 根目录和权威 DraftStore 均已落地。
Stage 27 在该基线上完成前端工程化和信息架构重构，不重写业务规则。

启动复核同时确认：当前 OpenAPI 覆盖 24 个 operation 且 operationId 唯一，但在直接交给
TypeScript 生成器前仍需校准错误响应、operationId 可读性和迁移功能使用的深层公开 DTO。
例如 Request 详情实际返回 404、海报端点实际返回 400/404/502，而当前 OpenAPI 声明不完整；
部分响应深层结构仍是 `dict[str, Any]`。这些问题纳入 US-198，在任何业务页面迁移前解决。

## 3. 技术选型与约束

| 领域 | 选择 | 说明 |
| --- | --- | --- |
| 框架 | Vue 3 Composition API | 适合表单、工作台和渐进组件化 |
| 语言 | TypeScript strict | API、路由状态、表单和组件 props 必须有静态契约 |
| 构建 | Vite | 开发代理、生产分包和 Flask 静态产物 |
| 路由 | Vue Router | 工作台、Request、队列和 Settings 使用明确路由 |
| 状态 | Pinia + feature-local composables | Pinia 只保存跨页面非敏感状态，不默认持久化 |
| API client | Stage 26 OpenAPI 生成类型/client + 薄 transport | 不手写第二套响应 interface；生成器与版本由 US-198 的 dry-run 固定 |
| 单元测试 | Vitest + Vue Test Utils | 覆盖纯状态、组件交互、错误边界和敏感字段清理 |
| 浏览器测试 | 现有 pytest-playwright | 真实 Chromium + route fake，逐步改用 role/label/data-testid |
| Node 包管理 | npm + package-lock.json | CI 使用 `npm ci`，不混用多个 lockfile |

约束：

- `frontend/src/api/generated/` 只能由 `docs/api/openapi.json` 生成，不手工维护。
- generator 版本、命令和配置必须入库；重复生成无 diff，CI 必须执行漂移检查。
- feature 不直接拼接 `/api/v1` URL，通过统一 client/transport 调用。
- 后端 DTO 在对应 feature 迁移前补齐该 feature 实际读取的公开字段；不得用长期
  `Record<string, unknown>` 绕过类型化目标。
- 敏感连接表单使用组件局部内存；切换认证模式、成功、取消和离开页面时主动清空。
- production build 不需要 Node 运行时，由 Flask 同源提供静态产物；SPA fallback 不得吞掉
  `/api/v1`、海报、`/healthz`、`/readiness` 或其他 Flask 路由。
- 旧页面只用于迁移期 parity/回退，不得继续增加业务能力。

## 4. 目标

1. 新建独立 `frontend/` 工程，建立 strict TypeScript、lint、unit test、build 和可重复 CI。
2. 让 OpenAPI 经过真实生成器 smoke test，并把运行时状态、稳定 operationId 和前端读取的
   深层公开结构准确表达为生成类型。
3. 生产环境继续与 Flask API 同源，开发环境通过 Vite proxy 访问本地 Flask。
4. 将工作台和 Settings 从全局 DOM 脚本迁移到 route、feature、component、store/composable。
5. 重构信息架构，使“创建方案—审核候选—编辑草案—管理 Request—提交队列”连续可理解。
6. 保持 Stage 25/26 业务语义、URL 恢复、安全边界和外部提交确认行为。
7. 每个 feature 独立完成 DTO、Vitest、Playwright parity 和敏感值回归后再迁移下一项。
8. 完成全量 parity 与回退演练后切换入口并删除旧前端资产。

## 5. 非目标

1. 不改变 MiKan、Request、筛选、命名、季数证据和 AutoBangumi 业务规则。
2. 不实施当前播出集数、真实 LLM provider、新版 Bearer 写契约或流式封面代理。
3. 不实现账号体系、远程多用户协作、数据库或后台 worker。
4. 不把 qBittorrent 连接测试扩展为下载任务创建。
5. 不把 endpoint、username、password、token、cookie、Authorization、原始响应或本地绝对路径
   保存到 Pinia 持久化、localStorage、sessionStorage、URL、日志、截图、trace 或 sourcemap。
6. 不在功能未对等、全量回归未通过、回退未演练前删除旧 Jinja 页面和 `app.js`。
7. 不用前端迁移顺带实现 BL-020、BL-021、BL-022 或 OF-001。

## 6. 目标目录

```text
frontend/
  src/
    app/
      router/
      shell/
    api/
      generated/
      client.ts
    features/
      search/
      drafts/
      requests/
      batches/
      queue/
      preferences/
      connections/
    components/
      feedback/
      forms/
      layout/
    styles/
    test/
  package.json
  package-lock.json
  tsconfig.json
  vite.config.ts
```

Flask 生产静态目录、Vite `base` 和 build 输出位置由 US-197 固定；生成文件和 build 产物的
提交/忽略策略必须明确，不能依赖开发机残留目录。

## 7. 信息架构与状态边界

### 7.1 应用外壳

- 导航包含：工作台、订阅方案、提交队列、Settings。
- 全局只保留导航、非敏感运行模式提示、错误边界和通知容器。
- 页面标题不展示历史 Stage 编号。
- 桌面、平板、360px 窄屏使用同一语义结构，不靠隐藏关键操作适配窄屏。

### 7.2 工作台

1. 创建：单个/批量输入与直连 fallback。
2. 搜索审核：解析摘要、FOUND/EMPTY/FAILED、真实候选和季数确认。
3. 草案：字幕组、筛选、命名、有效/完整/排除种子。
4. 接受：保存、单个/批量接受和明确不可接受原因。

单个与批量复用候选、草案和 Request 组件，不复制业务状态机。

### 7.3 Request、队列与 Settings

- Request 列表、详情和提交队列使用路由状态；`request_id`、`batch_id` 可复制并刷新恢复。
- candidate context、draft ID、服务地址和认证字段只存在于内存，不进入 URL 或持久化 store。
- 队列保留顺序提交、独立重试、人工 recover 和防重复提交语义。
- Storage/profile、非敏感偏好、qBittorrent 和 AutoBangumi 分区清晰。
- 恢复默认、删除、recover 和真实提交继续显式确认。

### 7.4 状态所有权

| 范围 | 状态 |
| --- | --- |
| 可持久化 | 相对 storage profile、用户明确保存的非敏感偏好、展示偏好 |
| 仅组件/会话内存 | candidate context、draft ID、搜索结果、敏感连接表单、当前提交状态 |
| 服务端权威 | Request/history、提交队列、draft 内容、偏好/修正业务数据、季数证据 context |

## 8. 渐进迁移与切换策略

1. 新前端先挂载在 `/app/`，旧 `/index`、`/settings` 保持可用。
2. 先完成工程基线、OpenAPI 生成验证、统一 transport、路由和应用外壳。
3. 再按共享安全表单 → Settings → Request 列表 → Request 详情 → 单个搜索/草案 →
   批量工作台 → 提交队列的顺序迁移。
4. 每项迁移都先补齐对应 DTO，随后通过 Vitest、API contract 和真实 Chromium parity；
   不把安全、响应式和无障碍全部推迟到收尾 story。
5. US-207 只处理跨 feature 的 360px、键盘、焦点、ARIA、reduced motion、分包与错误边界收敛。
6. US-208 生成可审查 parity 矩阵，完成入口切换和自动化回退演练；旧资产仍保留一个提交窗口。
7. US-209 在回退演练和全量门禁通过后删除旧主模板、`app.js` 和无用 CSS，并完成归档。

禁止“大爆炸式”替换，也禁止新旧前端各自实现不同 API 或业务规则。

## 9. 用户故事

### US-197：建立 Vue/TypeScript/Vite 工程与 CI 基线

- 创建 `frontend/`、npm lockfile、strict TypeScript、ESLint、Vitest 和 production build。
- 固定 Flask 静态托管、Vite dev proxy、`base`、SPA fallback 与 build 产物策略。
- CI 使用 `npm ci` 并运行 typecheck、lint、unit test、build，保留全部 Python/Chromium 门禁。

### US-198：校准 OpenAPI 并生成类型化客户端

- 用真实生成器对 `docs/api/openapi.json` 做 smoke test，选定并锁定工具、版本和命令。
- 修正 Request 详情 404、海报 400/404/502 等运行时/文档差异，新增自动一致性测试。
- 固化可读且稳定的 operationId；生成结果不依赖路径顺序或临时机器信息。
- 建立生成目录和 drift check；迁移 feature 不手写重复 API interface。

**US-198 完成**：选定 `openapi-typescript@7.13.0`（`frontend/package-lock.json` 锁定），
`npm run api:generate` 生成 `frontend/src/api/generated/api.ts`（入库），`npm run api:check`
漂移检查；修复 OpenAPI 的 schema 合法性（内联数组属性 → `type: array`+items）、Request
详情 404/`invalid_request_id`、海报 400/404/502/500、各端点可达的 mikan/AB/qB 错误状态；
24 个 operation 均固化显式可读 operationId；新增
`tests/api_contract/test_openapi_runtime_consistency.py`（7 例：声明 vs 运行时分类一致、
分类 error_type 全部有声明或显式豁免、operationId 唯一/可读/稳定、前端生成客户端 drift）。

### US-199：建立统一 API transport、路由和应用外壳

- 统一处理成功/失败 envelope、非 2xx JSON、非 JSON、网络失败、取消和超时。
- 建立 `/app/` 路由、导航、加载/空/错误状态、通知和全局错误边界。
- API、海报、health/readiness 和旧 Flask 页面不被 SPA fallback 截获。

### US-200：建立设计基础与安全表单组件

- 建立 layout、按钮、输入、确认、credential form、status/alert、loading 和 focus primitives。
- 敏感表单不进入持久化 store，模式切换、成功、取消、卸载时清空。
- 组件默认支持 label、键盘、ARIA 状态、reduced motion 和 360px 布局。

### US-201：迁移 Settings

- 迁移 storage profile、非敏感偏好、qB/AB 连接测试和 AB Request 提交上下文。
- 补齐 preferences/connections/submit-ab 的公开 DTO 和生成类型。
- 保持确认、HTTP 分类、错误脱敏、URL Request 上下文与敏感字段清理。

### US-202：迁移 Request 列表

- 迁移列表加载、搜索、状态筛选、排序、计数、空状态和路由选择。
- 补齐 Request summary DTO；`request_id` 可刷新恢复，storage 只使用相对 profile。
- 旧列表与新列表使用同一 API，结果和失败反馈 parity。

### US-203：迁移 Request 详情与管理动作

- 迁移详情、history、AB result、Filter/Seeds/Source/Audit 展示。
- 迁移修改、取消、删除和 ACCEPTED 状态差异；危险操作显式确认。
- 补齐详情/action DTO，404/409/500 分支有类型化、安全反馈。

### US-204：迁移单个搜索与服务端草案

- 迁移真实候选、直连 fallback、季数确认、同源海报和候选显式选择。
- 使用服务端 `draft_id` 完成修改、保存、过期/逐出/重放恢复。
- 不自动选候选，不把 parser 提示当作真实季数证据，不持久化 draft/context。

### US-205：迁移批量工作台

- 迁移批量输入、独立 FOUND/EMPTY/FAILED、候选浮层、草案详情和删除。
- 迁移选择、单个接受、批量接受和全接受，并显示明确不可接受原因。
- 补齐 batch parse/accept DTO；复用候选、草案和 Request 组件。

### US-206：迁移提交队列

- 迁移队列读取、刷新恢复、顺序提交、失败重试、recover 和防重复提交。
- 补齐 queue/submit/retry/recover DTO；成功项不重复提交，失败项独立恢复。
- AB 凭据仅存在于当前组件内存和单次 POST body，成功/离开时清空。

### US-207：完成跨功能响应式、无障碍与运行质量收敛

- 覆盖 360px、平板和桌面，无关键操作横向溢出或只靠颜色表达状态。
- 完成键盘导航、焦点恢复、ARIA live/error、reduced motion 和错误边界审计。
- 检查路由懒加载、production chunk、静态缓存和公开 sourcemap 策略。

### US-208：完成 parity、切换默认入口并演练回退

- 建立旧 269 个 Chromium 旅程到新路由的 parity 矩阵，关键旅程全部指向新前端。
- `/index`、`/settings` 及 request_id/batch_id 兼容入口切换到新前端。
- 演练一次无需修改业务数据的入口回退；失败时可恢复旧入口，API/storage 不回滚。

### US-209：删除旧前端并完成 Stage 27 收尾

- 在 parity、回退演练和全量门禁通过后删除旧 `app.js`、旧主模板和无用 CSS/测试 helper。
- 更新 README、架构、M13、部署说明、测试命令和文档索引。
- 归档 Stage 27 prd/progress，确认 build 产物、`.migu_orca/storage` 和敏感数据未污染仓库。

## 10. 每个 story 的共同门禁

- `npm run typecheck`、`npm run lint`、`npm run test:unit -- --run`、`npm run build`。
- `uv run python -m compileall -q src tests`、`uv run ruff check src tests`。
- 与当前改动相关的 Python/API contract 测试；OpenAPI 变化运行 `uv run migu-orca-openapi --check`。
- UI story 使用 `.agents/skills/dev-browser/SKILL.md` 在真实 Chromium 验证，不接受整体 skip。
- `git diff --check`；不得生成仓库根 `.migu_orca/storage`。
- 不访问真实 MiKan、AutoBangumi 或 qBittorrent，不在 trace/screenshot/build 输出敏感值。

## 11. 验收矩阵

至少覆盖：

- 单个 FOUND/EMPTY/FAILED、候选选择、非第一季确认、冲突候选禁用和 draft 失效恢复。
- 批量多项独立失败、修改、删除、单个/批量/全接受。
- 队列刷新恢复、顺序提交、失败重试、SUBMITTING/RESULT_PERSIST_FAILED recover。
- Request 修改、取消、删除与 AutoBangumi Settings 上下文。
- qB/AB 成功、认证失败、超时、非 JSON 和敏感字段清理。
- localStorage、sessionStorage、URL、页面、日志、构建产物、截图和 trace 的敏感值检查。
- 360px、键盘、焦点恢复、ARIA 状态、reduced motion 和 SPA fallback 边界。
- 新旧 parity、入口切换和不回滚业务数据的回退演练。

## 12. 完成标准

1. 所有主要 Web 旅程在新前端达到或超过旧页面行为。
2. 前端只依赖生成的 OpenAPI 类型/client，不导入 Python 模型或复制响应 interface。
3. UI 实际读取的公开 API 字段有明确 DTO，不以长期 `Any`/`unknown` 逃避类型。
4. 旧原生 JavaScript 全局状态中心和不再使用的主模板已删除。
5. 敏感外部配置仅存在于当前组件内存和单次 POST body。
6. TypeScript、lint、Vitest、production build、Python/API 测试和真实 Chromium 全部通过。
7. `/index`、`/settings`、`request_id`、`batch_id` 的兼容入口和刷新恢复保持有效。
8. SPA fallback 不截获 API、海报和健康检查，生产运行不依赖 Node。
9. Stage 27 不夹带业务 backlog，Ralph 记录正确归档，工作区无运行数据或敏感产物。
