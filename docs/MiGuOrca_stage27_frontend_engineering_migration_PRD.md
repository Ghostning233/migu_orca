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

**US-199 完成**：统一 transport 落在 `frontend/src/api/client.ts`（`apiRequest`/`api.*`/
`api.poster`），统一处理 envelope（`{ok:true,result}`/`{ok:false,error_type,error_message,
error_data}`）、非 2xx JSON、非 JSON 错误体（代理 HTML 归一为安全中文回退）、网络失败
（`network_error`）、AbortSignal 取消（`request_cancelled`）与超时（默认 15s，
`request_timeout`），失败统一抛 `ApiError`；路径参数用 `{param}` 模板、查询参数只放非敏感值，
海报端点返回 `Blob` 不经 envelope。`useTrackedRequest.ts` 的 `trackedApi` 驱动全局 loading
store；`app/stores/notification.ts` + `GlobalNotification.vue` 提供 aria-live 通知
（error 用 role=alert），`ErrorBoundary.vue` 包住 RouterView。SPA 路由扩为 4 条：
`/app/workbench`、`/app/requests`、`/app/queue`、`/app/settings`（导航含工作台/订阅方案/
提交队列/Settings），Requests/Queue 为带空状态的占位视图（US-202/US-206 迁移）。Flask 侧
无需新增服务端路由，fallback 边界与探针/旧页面不被截获由既有测试守护。Vitest 新增
`client.test.ts`（16 例）、`useTrackedRequest.test.ts`（2 例）、`loading.test.ts`（2 例）、
App 外壳测试扩至 4 路由+通知；浏览器 `test_app_shell.py` 更新为 4 导航与各 route 挂载
（6 例全过）。全部门禁通过（typecheck/lint/unit 29 例/build/compileall/ruff/Python
1038 非浏览器 + 275 浏览器/OpenAPI drift/node --check）。

### US-200：建立设计基础与安全表单组件

- 建立 layout、按钮、输入、确认、credential form、status/alert、loading 和 focus primitives。
- 敏感表单不进入持久化 store，模式切换、成功、取消、卸载时清空。
- 组件默认支持 label、键盘、ARIA 状态、reduced motion 和 360px 布局。

**US-200 完成**：建立共享组件原语——布局（`components/layout/PanelSection.vue`、
`FormField.vue`）、表单控件（`components/forms/BaseButton/BaseInput/BaseTextarea/
BaseSelect/CheckboxRow.vue`，全部支持 v-model/attrs 透传/aria-invalid）、确认对话框
（`components/feedback/ConfirmDialog.vue`，`confirm()` 返回 Promise<boolean>，
`role="alertdialog"` + focus trap + inert 背景 + Escape/backdrop 取消 + 焦点恢复）、
焦点陷阱（`app/composables/useFocusTrap.ts`）、敏感凭据（`app/composables/
useSensitiveFields.ts`，字段只存组件局部内存，模式切换/成功/取消/卸载主动清空，
`snapshot()` 只返回非空值）、状态反馈（`components/feedback/StatusAlert.vue`，
error 用 role=alert，状态不只靠颜色）。新增 `/app/components-demo` 原语演示路由
（迁移脚手架，US-209 删除）。Vitest 新增 26 例（useSensitiveFields 10、
useFocusTrap 8、ConfirmDialog 8、BaseInput/BaseTextarea 6 例共 61 例全过）；
浏览器新增 `tests/browser/test_components_primitives.py` 8 例真实 Chromium
（渲染/360px 无横向溢出/确认/取消/Escape+inert/敏感字段清空/必填错误），全部门禁通过。

### US-201：迁移 Settings

- 迁移 storage profile、非敏感偏好、qB/AB 连接测试和 AB Request 提交上下文。
- 补齐 preferences/connections/submit-ab 的公开 DTO 和生成类型。
- 保持确认、HTTP 分类、错误脱敏、URL Request 上下文与敏感字段清理。

**完成记录（2026-08-30）**：`/app/settings` 四个分区全部迁移到共享原语——
Storage 偏好（`frontend/src/features/settings/storagePreferences.ts`，localStorage 只存
服务端相对 profile，绝对路径/穿越值回退服务端根）、偏好默认值
（`preferences.ts` + `/api/v1/preferences`，保存失败回退到上次成功值并清空被拒绝的敏感
输入，恢复默认需确认）、qBittorrent（`useSensitiveFields` + 确认 + 成功后清空）、
Auto Bangumi（连接测试 + `request_id` 提交上下文 + 认证模式切换清空）。补齐公开 DTO：
`AbSubmitResultDTO`（`ab_submit_result` 白名单）、`SubtitleGroupPreferenceDTO`/
`FilterDefaultsDTO`/`NamingPreferenceDTO`/`SearchPreferenceDTO`（深层偏好结构）并重新生成
`docs/api/openapi.json` 与 `frontend/src/api/generated/api.ts`。连接测试/提交失败只显示
固定中文反馈，绝不渲染服务端原始错误（可能含凭据）。修复 `CheckboxRow`：支持
`v-model:checked`（checked prop + update:checked emit）、`inheritAttrs: false` 让 `id`
只落在原生 input（不再重复到包装 div）。Vitest 新增 34 例（storagePreferences 12、
preferences 5、SettingsView 17），浏览器新增 `tests/browser/test_app_settings.py` 18 例
真实 Chromium（四分区旅程、敏感值不落盘、360px、错误 role=alert），全套 301 例浏览器 +
1038 非浏览器全过。

### US-202：迁移 Request 列表

- 迁移列表加载、搜索、状态筛选、排序、计数、空状态和路由选择。
- 补齐 Request summary DTO；`request_id` 可刷新恢复，storage 只使用相对 profile。
- 旧列表与新列表使用同一 API，结果和失败反馈 parity。

**完成记录（2026-08-31）**：`/app/requests` 迁移完成——`GET /api/v1/requests` 走统一
transport（`api.get<ListResult>`），列表加载/搜索（标题、request_id、字幕组、
folder_name）/状态筛选（待确认/已确认/已取消）/排序（默认/标题升序/request_id 升序）/
计数（`显示 X / Y`）/空状态（无订阅方案/无匹配）/错误重试全部与旧 `/index` 列表 parity；
纯函数列表逻辑收敛到 `frontend/src/features/requests/requestsList.ts`（feature 与测试共用，
不复制第二套）。补齐公开 DTO `RequestListResultDTO`（`requests: list[RequestSummaryDTO]`，
替换裸 inline 数组）并重新生成 `docs/api/openapi.json` 与 `frontend/src/api/generated/api.ts`
（drift check 双守护）；DTO 测试新增 2 例。选择状态由 URL query `request_id` 驱动
（点击 push、刷新恢复、清空移除），每项提供「复制 request_id」按钮（剪贴板 + 通知）；
storage 只从 localStorage 读相对 profile（`sanitizeStorageProfile` 已挡绝对路径/穿越）。
Vitest 新增 33 例（requestsList 18、RequestsView 15，共 128 例全过）；浏览器新增
`tests/browser/test_app_requests.py` 15 例真实 Chromium（加载/计数/搜索/筛选/排序/空状态/
选择恢复/复制/脱敏错误/360px/role=alert），更新 `test_app_shell.py` 的 requests 路由断言，
全套 316 例浏览器 + 1040 非浏览器 + typecheck/lint/unit/build/api:check/compileall/ruff/
node --check/git diff --check 全过，仓库根 `.migu_orca/storage` 不存在。US-203 将迁移
详情面板与管理动作（列表项点击后详情区仍为 US-203 内容）。

### US-203：迁移 Request 详情与管理动作

- 迁移详情、history、AB result、Filter/Seeds/Source/Audit 展示。
- 迁移修改、取消、删除和 ACCEPTED 状态差异；危险操作显式确认。
- 补齐详情/action DTO，404/409/500 分支有类型化、安全反馈。

**完成记录（2026-08-31）**：`/app/requests` 详情面板迁移完成——
`features/requests/RequestDetailPanel.vue` 挂在列表下方（选中 `request_id` 即渲染，
`:key` 重挂载），加载走统一 transport `GET /api/v1/requests/{request_id}`，渲染
Overview/Source/Filter/Seeds（有效/完整按字幕组分组/排除）/Audit（状态历史 + AB 结果）。
管理动作按状态分派：PENDING_CONFIRM → 确认/取消/修改；ACCEPTED → 修改/删除/去
Settings 提交 AB（入口带 `request_id` + `ab=1`，Settings 返回链接改指
`/requests?request_id=...`）；CANCELLED → 只读提示。所有破坏性动作走共享
ConfirmDialog；成功后面板用服务端返回的 `request` 更新内存快照并重载详情、列表
`@changed` 刷新；删除成功清空 URL 选择并卸载面板。失败只显示固定中文反馈
（确认失败/取消失败/修改失败/删除失败），详情加载失败显示「订阅方案详情加载失败」
（role=alert），原始 `error_type`/`error_message`/RSS URL/`mikan_url` 绝不进 DOM
（`displayValue` 对 URL 样式字符串脱敏为 `[redacted_url]`）。
补齐详情/历史/AB/action DTO（`RequestSnapshotDTO`/`HistorySectionDTO`/
`AbResultSectionDTO` 等，lenient `extra="allow"` 快照 + strict envelope）并重新生成
`docs/api/openapi.json` 与 `frontend/src/api/generated/api.ts`；纯展示逻辑收敛到
`features/requests/requestDetail.ts`，相对 storage profile 查询参数收敛到
`features/requests/requestStorage.ts`（列表/详情共用）。Vitest 新增 38 例
（requestDetail 16、RequestDetailPanel 22，共 166 例全过）；浏览器新增
`tests/browser/test_app_request_detail.py` 23 例真实 Chromium（分区/URL 恢复/缺失
request_id 安全错误/确认/取消/删除/修改 patch/脱敏/360px/中文状态码/AB 入口跳转），
全套 339 浏览器 + 1043 非浏览器 + typecheck/lint/unit/build/api:check/compileall/ruff/
node --check/git diff --check 全过，仓库根 `.migu_orca/storage` 不存在。US-204 将在
同一基线上迁移单个搜索与服务端草案。

### US-204：迁移单个搜索与服务端草案

- 迁移真实候选、直连 fallback、季数确认、同源海报和候选显式选择。
- 使用服务端 `draft_id` 完成修改、保存、过期/逐出/重放恢复。
- 不自动选候选，不把 parser 提示当作真实季数证据，不持久化 draft/context。

US-204 完成（2026-08-31）：`/app/workbench` 迁移单个搜索与服务端草案——
`WorkbenchView.vue`（搜索表单 + 直连 fallback + 候选结果区）+ `CandidateCard.vue`
（公开白名单卡片，NEEDS_CONFIRMATION 勾选后可选 / CONFLICT 禁用）+ `DraftPreviewPanel.vue`
（编辑订阅草案表单 + preview-modify 种子重算 + 保存草案 + draft 失效恢复）+
`candidateSearch.ts`（纯函数校验/季数证据/payload 构造）。补齐 `MikanCandidateDTO`/
`SeasonEvidenceDTO` 公开白名单（strict `extra="forbid"`，engine 字段在边界拒绝）并重生成
OpenAPI 与 TS 客户端（drift check 双守护）。`candidate_context`/`draft_id` 只在组件内存，
绝不进 URL/storage/日志；保存成功后跳转 `/requests?request_id=...`。Vitest 新增 31 例
（candidateSearch 17、WorkbenchView 14，共 197 例全过）；浏览器新增
`tests/browser/test_app_workbench.py` 18 例真实 Chromium（搜索/空态/失败重试/解析摘要/
季数确认/冲突禁用/候选选择草案/编辑重算/保存跳转/fallback 门控与校验/敏感边界/360px）。
全套 357 浏览器 + 1044 非浏览器 + typecheck/lint/unit/build/api:check/compileall/ruff/
node --check/git diff --check 全过，仓库根 `.migu_orca/storage` 不存在。US-205 将复用
候选、草案与 Request 组件迁移批量工作台。

### US-205：迁移批量工作台

- 迁移批量输入、独立 FOUND/EMPTY/FAILED、候选浮层、草案详情和删除。
- 迁移选择、单个接受、批量接受和全接受，并显示明确不可接受原因。
- 补齐 batch parse/accept DTO；复用候选、草案和 Request 组件。

US-205 完成（2026-08-31）：`/app/workbench` 底部挂载 `BatchWorkbenchView.vue`（批量
工作台区）——批量输入（textarea，每行一个番剧名）→ `POST /api/v1/batches/parse` 返回
独立 FOUND/EMPTY/FAILED 卡片与 `batch_id`（进 URL query 供提交队列刷新恢复）。FOUND
卡片经 `BatchCandidatePopover.vue`（复用 `CandidateCard`，`role="dialog"`，季数确认/
冲突禁用）选候选 → `POST /api/v1/requests`（`save_request=false`）生成服务端权威草案；
DRAFT 卡片经 `BatchDraftPreviewPanel.vue`（复用 `DraftPreviewPanel` + 批量专属
「接受当前批量草案/删除当前批量卡片」）查看/编辑/保存草案。选择/单个接受/批量接受/
全接受统一走 `POST /api/v1/batches/{batch_id}/accept`（「批量接受」带 `item_ids` 只发
选中项；「全接受」按 legacy parity 发送全部卡片不带 `item_ids`，不可接受卡片显示中文
reason）。补齐批量公开 DTO（`BatchParseItemDTO`/`BatchQueueItemDTO`/`BatchQueueDTO`/
`BatchResultItemDTO`，lenient `_SnapshotBase` 内嵌 strict `MikanCandidateDTO`）并重生成
OpenAPI 与 TS 客户端（drift check 双守护）。Vitest 新增 28 例（batchWorkbench 18 +
BatchWorkbenchView 10，共 225 例全过）；浏览器新增 `tests/browser/test_app_batch_workbench.py`
13 例真实 Chromium（解析状态/loading/空输入校验/候选浮层/季数确认/草案详情与删除/
脱敏/选择接受/全接受/全选计数/失败保留/360px/敏感边界）。全套 370 浏览器 + 1044 非
浏览器 + typecheck/lint/unit/build/api:check/compileall/ruff/node --check/git diff --check
全过，仓库根 `.migu_orca/storage` 不存在。US-206 将迁移提交队列（queue/submit/retry/
recover）。

### US-206：迁移提交队列

- 迁移队列读取、刷新恢复、顺序提交、失败重试、recover 和防重复提交。
- 补齐 queue/submit/retry/recover DTO；成功项不重复提交，失败项独立恢复。
- AB 凭据仅存在于当前组件内存和单次 POST body，成功/离开时清空。

US-206 完成（2026-08-31）：`/app/queue` 迁移提交队列——`QueueView.vue` 从 URL
`batch_id`（公开标识符）读取 `GET /api/v1/batches/{batch_id}/queue` 恢复队列（批量工作台
解析后已把 `batch_id` 推入 URL），无 `batch_id` 显示空状态并禁用刷新；队列项按状态分派
动作：FAILED/RETRYABLE → 单项「重试」（`retry` 带 `request_id`），SUBMITTING/
RESULT_PERSIST_FAILED → 「恢复」（`recover`：先 `action=auto`，服务端返回 `needs_manual`
时经共享 ConfirmDialog 人工核验——确认=已创建订阅→`succeeded`、取消=未创建→`failed`，
均带 `confirm: true`），已成功项绝不重复提交。提交/重试/恢复共用同一个 Auto Bangumi
凭据表单（`useSensitiveFields` 组件内存 + 单次 POST body `ab_config`，成功清空/切换认证
模式清空/卸载清空；HTTP 级失败保留输入与确认便于重试，只显示固定中文反馈）。纯函数逻辑
收敛到 `features/queue/queueWorkbench.ts`（`queueStatusLabel`/`queueStatusClass`/
`queueItemSummary`/`queueItemCanRetry`/`queueItemCanRecover`/`buildAbConfig`/
`validateAbConfig`/`batchSubmitSummaryMessage`/`batchSubmitNotification` +
transport wrappers）。Vitest 新增 29 例（queueWorkbench 13 + QueueView 16，共 254 例全过）；
浏览器新增 `tests/browser/test_app_queue.py` 16 例真实 Chromium（空状态/读取与状态渲染/
读取失败脱敏/360px/提交校验与确认/提交成功清空与防重复/提交失败保留输入/in-flight 禁用/
重试按钮分派/重试成功/重试失败/恢复按钮分派/自动恢复/人工核验确认/人工核验取消/敏感边界），
并同步 `test_app_shell.py` queue 路由断言（`#queue-heading` → `#batch-queue-count`/
`#batch-queue-list`）。全套 386 浏览器 + 1044 非浏览器 + typecheck/lint/unit/build/
api:check/compileall/ruff/node --check/git diff --check 全过，仓库根 `.migu_orca/storage`
不存在。US-207 将做跨功能响应式、无障碍与运行质量收敛。

### US-207：完成跨功能响应式、无障碍与运行质量收敛

- 覆盖 360px、平板和桌面，无关键操作横向溢出或只靠颜色表达状态。
- 完成键盘导航、焦点恢复、ARIA live/error、reduced motion 和错误边界审计。
- 检查路由懒加载、production chunk、静态缓存和公开 sourcemap 策略。

**US-207 完成（2026-08-31）**：跨功能收敛落地——

- 键盘可达性：App.vue 增加 `#skip-link`（Tab 首个聚焦目标，聚焦时可见，
  href=`#app-main`），`main#app-main` 加 `tabindex="-1"` 作为焦点落点。
- 批量候选浮层（`BatchCandidatePopover.vue`）打开时焦点移入 dialog（close 按钮），
  Escape 关闭且父组件在关闭时**同步**把焦点恢复到触发按钮（不再用
  `requestAnimationFrame`，避免 popover 卸载先把焦点丢到 body）。
- 响应式：`top-nav` 改 `flex-wrap`（360px 下 4 个导航链接换行不溢出）；四路由 ×
  360/768/1280 三视口无横向溢出由新浏览器收敛套件守护。
- reduced-motion：LoadingState/BaseButton spinner 在 `prefers-reduced-motion` 下停
  动画但文本 + `aria-busy`/disabled 保留；conftest 新增 `test-slow-queue` 服务端延迟
  路由供浏览器观察 loading（`time.sleep` 写在 `page.route` handler 会阻塞 Playwright
  分发线程——加载态永远不可见）。
- production 运行质量：vite.config.ts 用 functional `manualChunks` 把 `node_modules`
  打进 `vendor-*.js`（保持路由懒加载）；`sourcemap: false` 且 build 永不提交 `.map`；
  Flask `/app/assets/*` 返回 `public, max-age=31536000, immutable`，SPA shell 与
  fallback 返回 `no-cache`（部署换哈希不 pin 旧资源），`routes_app.py` 的
  `app_shell`/`app_fallback` 改为返回带 Cache-Control 的 `Response`。
- 测试：Vitest 新增 App skip-link 1 例 + BatchCandidatePopover 3 例（共 258 例全过）；
  浏览器新增 `tests/browser/test_app_responsive_a11y.py` 22 例真实 Chromium（四路由 ×
  三视口无横向溢出/导航换行/状态文本不只靠颜色/skip link 跳转/main landmark/
  popover Escape 焦点恢复/reduced-motion 加载与按钮/ vendor chunk/无 sourcemap/
  缓存头）；`app_routes_test.py` 新增 3 例（asset immutable 缓存/shell no-cache/
  build 无 sourcemap）。全套 408 浏览器 + 1051 非浏览器 + typecheck/lint/unit/build/
  api:check/compileall/ruff/node --check/git diff --check 全过，仓库根
  `.migu_orca/storage` 不存在。US-208 将基于此收敛基线建立 parity 矩阵并切换默认入口。

### US-208：完成 parity、切换默认入口并演练回退

- 建立旧 269 个 Chromium 旅程到新路由的 parity 矩阵（`docs/Stage27_parity_matrix.md`，
  数据在 `tests/api_contract/parity_matrix.py`，`tests/api_contract/test_parity_matrix_guard.py`
  自动重数旧套件测试数并守护映射，重命名/删减旧套件即失败），关键旅程全部指向新前端。
- `/index`、`/settings` 及 request_id/batch_id 兼容入口切换到新前端（`views.py`
  `web_entry_mode()`：默认 `spa`，`GET /`、`GET /index` → `/app/workbench` 保留
  `request_id`/`batch_id` query，`GET /Settings`、`GET /settings` → `/app/settings`
  保留 `request_id` query；只转发公开已保存标识符，敏感值绝不进入重定向 URL）。
- 演练一次无需修改业务数据的入口回退（`tests/browser/test_app_entry_switch.py` 真实
  Chromium：`MIGU_ORCA_WEB_ENTRY_LEGACY=1` 恢复旧 `/index`、`/settings` Jinja 页面，
  同一 `/api/v1/requests` 与 storage 前后不变；旧旅程浏览器套件用
  `pytestmark = [pytest.mark.browser, pytest.mark.legacy_entry]` 在 legacy 入口下回归）。
- 旧资产（旧主模板、`app.js`、无用 CSS）保留一个提交窗口；US-209 在全部门禁通过后删除。

完成记录（2026-08-31）：parity 矩阵 + guard、默认入口切换与回退演练全部门禁通过——
全套 416 浏览器（269 旧旅程 legacy 入口 + 147 SPA）+ 1076 非浏览器 +
typecheck/lint/unit/build/api:check/compileall/ruff/node --check/git diff --check 全绿，
仓库根 `.migu_orca/storage` 不存在。US-209 将删除旧前端资产并归档 Stage 27。

### US-209：删除旧前端并完成 Stage 27 收尾

- 在 parity、回退演练和全量门禁通过后删除旧 `app.js`、旧主模板和无用 CSS/测试 helper。
- 更新 README、架构、M13、部署说明、测试命令和文档索引。
- 归档 Stage 27 prd/progress，确认 build 产物、`.migu_orca/storage` 和敏感数据未污染仓库。

完成记录（2026-08-31）：旧 `app.js`、`style.css`、`index.html`/`settings.html`/`_top_nav.html`
Jinja 主模板与 14 个旧旅程浏览器套件、`test_components_primitives` 脚手架、
`test_app_entry_switch` 回退演练、parity 矩阵（`docs/Stage27_parity_matrix.md` +
`tests/api_contract/parity_matrix.py` + `test_parity_matrix_guard.py`）与
`test_frontend_dependencies.py` 全部删除；`views.py` 去掉 `web_entry_mode()` legacy 分支，
入口路由固定重定向 SPA，`blueprints.py` 移除 static/template 文件夹；conftest 移除
`open_dev_fixture_panel`/`_legacy_entry_mode`，pyproject 移除 legacy_entry marker，
CI 移除 `node --check`。README、架构、M13、backlog、future stages、主 PRD、docs/README、
endpoint_inventory、docs/api/README、skills 与 AGENTS.md 全部同步为 Stage 27 已完成。
全套 Python（非浏览器 + 真实 Chromium SPA 套件）+ 前端 typecheck/lint/unit/build/api:check +
compileall/ruff/OpenAPI drift/git diff 全绿，仓库根 `.migu_orca/storage` 不存在；
Stage 27 prd/progress 已归档到 `scripts/ralph/archive/`。

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
