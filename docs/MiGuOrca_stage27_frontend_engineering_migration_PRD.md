# MiGuOrca Stage 27 PRD：前端工程化迁移与页面重构

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 项目名称 | MiGuOrca |
| 文档名称 | Stage 27 PRD：前端工程化迁移与页面重构 |
| 文档类型 | 后继 Stage PRD / Stage 26 handoff |
| 当前状态 | 已规划，等待 Stage 26 完成后启动 |
| 创建日期 | 2026-08-29 |
| Backlog | BL-024 |
| 优先级 | P1 |
| 前置条件 | Stage 26 API DTO、OpenAPI、HTTP 状态、storage 与 draft 边界全部完成 |
| 预定分支 | `agent/stage27-frontend-engineering-migration` |
| 预定 stories | US-197～US-204，启动时按 Stage 26 最终契约复核 |

## 2. 背景

当前 Web UI 已承载完整业务，但工程形态仍是两份 Jinja 页面、一份约 5,000 行原生 JavaScript 和一份约 1,500 行 CSS。全局 DOM 引用、页面状态、API 调用、渲染函数和敏感表单逻辑集中在同一个 IIFE 中；继续增量开发会放大状态耦合和浏览器回归成本。

Stage 26 将先把 `/api/v1` 固化为类型化、可生成客户端的后端边界，并解决浏览器任意 storage path 与客户端权威 preview Request 等 P0 问题。Stage 27 在该基线上完成前端工程化和页面信息架构重构，不同时重写业务 API。

## 3. 技术选型

| 领域 | 选择 | 说明 |
| --- | --- | --- |
| 框架 | Vue 3 Composition API | 适合表单、工作台、局部状态与渐进组件化 |
| 语言 | TypeScript strict | API、状态和表单必须有静态契约 |
| 构建 | Vite | 提供快速开发、分包和生产静态产物 |
| 路由 | Vue Router | 工作台、Request 详情、队列和 Settings 使用明确路由 |
| 状态 | Pinia + feature-local composables | 只保存非敏感业务/UI 状态；服务凭据不进入 store 持久化 |
| API client | Stage 26 OpenAPI 生成类型 + 薄封装 | 不手写第二套响应 interface |
| 单元测试 | Vitest + Vue Test Utils | 覆盖纯状态、组件交互和错误边界 |
| 浏览器测试 | 现有 pytest-playwright | 继续使用真实 Chromium 与 route fake，逐步减少脆弱 CSS selector |
| Node 包管理 | npm + lockfile | 仓库提交 lockfile，CI 使用可重复安装 |

若 Stage 26 的 OpenAPI 生成方式对客户端生成器有不同约束，可在 Stage 27 启动前调整具体生成工具，但不得退回手写无校验 API 类型。

## 4. 目标

1. 新建独立 `frontend/` 工程，建立 TypeScript、Vite、Vue、lint、unit test 和 production build。
2. 生产环境继续与 Flask API 同源，开发环境通过 Vite proxy 访问本地 Flask；不为前端迁移引入跨域凭据存储。
3. 将工作台和 Settings 从全局 DOM 脚本迁移到路由、feature、component、store/composable 分层。
4. 重构页面信息架构，使“创建方案—审核候选—编辑草案—管理 Request—提交队列”成为清晰连续流程。
5. 保持 Stage 25/26 业务语义、URL 恢复、安全边界和外部提交确认行为。
6. 新旧页面并行一段时间；新页面达到完整行为与浏览器验收后再切换默认入口并删除旧资产。
7. 建立可持续的前端质量门禁，避免再次形成单文件状态中心。

## 5. 非目标

1. 不改变 MiKan、Request、筛选、命名、季数证据和 AutoBangumi 业务规则。
2. 不实施当前播出集数、真实 LLM provider、新版 Bearer 写契约或流式封面代理。
3. 不实现账号体系、远程多用户协作、数据库或后台 worker。
4. 不把 qBittorrent 连接测试扩展为下载任务创建。
5. 不把 AutoBangumi/qB endpoint、username、password、token、cookie 或完整外部响应保存到 Pinia、localStorage、sessionStorage、URL、日志、截图或 trace。
6. 不在功能未对等前删除旧 Flask/Jinja 页面和 `app.js`。

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

约束：

- `api/generated` 只能由 Stage 26 OpenAPI 生成，不手工维护。
- feature 组件不直接拼接 `/api/v1` URL，通过统一 client 调用。
- 敏感连接表单使用组件局部内存；切换认证模式、提交成功、离开页面时主动清空。
- 只有经过明确审查的非敏感偏好允许使用持久化 adapter。

## 7. 信息架构

### 7.1 应用外壳

- 统一顶部或侧边导航：工作台、订阅方案、提交队列、Settings。
- 全局只保留导航、非敏感运行模式提示和通知容器。
- 页面标题不再展示历史 Stage 编号。
- 桌面、平板、窄屏使用同一语义结构，避免仅靠 CSS 隐藏关键操作。

### 7.2 工作台

工作台按用户任务组织：

1. 创建区域：单个/批量输入与直连 fallback。
2. 搜索审核区域：解析摘要、FOUND/EMPTY/FAILED、真实候选选择与季数确认。
3. 草案区域：字幕组、筛选、命名、有效/完整/排除种子。
4. 接受区域：保存、单个/批量接受与明确不可接受原因。

批量候选和草案继续复用同一业务组件，不复制单个/批量两套详情逻辑。

### 7.3 Request 与队列

- Request 列表与详情使用路由状态，而不是依赖一个页面内的全局 selected ID。
- `request_id`、`batch_id` 保持可复制和刷新恢复，但外部配置绝不进入 URL。
- 提交队列提供独立视图，保留顺序提交、重试、人工 recover 和防重复提交语义。
- AutoBangumi 敏感表单只在当前提交操作中存在，成功后清空。

### 7.4 Settings

- Storage/profile、非敏感偏好、数据源说明、qBittorrent 和 AutoBangumi 分区清晰。
- 连接测试使用统一 credential form 组件，但 qB/AB payload 仍按独立 API 契约生成。
- 恢复默认、删除、人工 recover 等不可逆或高风险动作继续显式确认。

## 8. 渐进迁移策略

1. 新前端初期挂载在 `/app/`，旧 `/index`、`/settings` 保持可用。
2. Flask 在生产提供 Vite build 静态资源和 SPA fallback；API 与海报保持同源。
3. 每完成一个 feature，增加 API contract test、Vitest 和 Playwright parity 测试。
4. Settings 先迁移，用于验证表单、API client、通知、敏感字段清理和响应式基础。
5. 然后迁移 Request 列表/详情、单个搜索、批量工作台、提交队列。
6. 全部关键旅程通过后，将 `/index` 和 `/settings` 切换或重定向到新前端。
7. 保留一个明确回退版本窗口；稳定后删除旧 Jinja 主页面、`app.js` 和不再使用的 CSS。

不采用“大爆炸式”替换，也不允许新旧前端各自实现不同 API 或业务状态机。

## 9. 状态管理规则

### 9.1 可持久化

- 经过 Stage 26 约束后的非敏感 storage profile ID。
- 用户明确保存的非敏感 UI 偏好。
- 不含外部配置的展示偏好，例如列表排序或折叠状态。

### 9.2 只存在于内存

- candidate context、draft ID 及其过期状态。
- 当前搜索结果、批量卡片工作状态。
- AutoBangumi/qBittorrent 服务地址和所有认证字段。
- submit/retry/recover 当前请求状态。

### 9.3 由服务端权威管理

- Request snapshot 与 history。
- batch submission queue。
- preview draft 内容和生命周期。
- preference/correction 业务数据。
- 候选季数证据和一次性确认 context。

## 10. 用户故事

### US-197：建立 Vue/TypeScript/Vite 前端工程

- 创建 `frontend/`、npm lockfile、strict TypeScript、ESLint、Vitest 和生产 build。
- Flask 同源提供生产静态资源，Vite dev proxy 连接本地 API。
- CI 检查 install、typecheck、lint、unit test 和 build。

### US-198：建立生成 API client 与应用外壳

- 从 Stage 26 OpenAPI 生成 TypeScript 类型/client。
- 建立统一 envelope、HTTP 错误、通知和安全字段处理。
- 完成导航、路由、布局、空/加载/错误状态和基础设计 token。

### US-199：迁移 Settings 与敏感连接表单

- 迁移 storage profile、用户偏好、qB 与 AB 连接测试/提交上下文。
- 敏感输入不进入 store 持久化，切换模式和成功后清空。
- 保持确认、错误脱敏和窄屏可用性。

### US-200：迁移 Request 列表与详情

- 迁移搜索、状态筛选、排序、详情、history、AB result、修改、取消和删除。
- Request 详情使用路由恢复，保留 preview/saved/accepted 状态差异。
- Seeds、Filter、Source、Audit 使用可复用类型化组件。

### US-201：迁移单个搜索与服务端草案

- 迁移解析摘要、真实候选、直连 fallback、季数确认和同源封面。
- 使用 Stage 26 draft ID 完成修改、保存和过期恢复。
- 不自动选择候选，不把 parser 提示当作真实季数证据。

### US-202：迁移批量工作台与提交队列

- 迁移批量输入、候选浮层、草案详情、删除、批量接受和全接受。
- 迁移队列读取、顺序提交、重试、recover 和防重复提交。
- 单个与批量复用候选、草案、Request 和 credential 组件。

### US-203：完成响应式、无障碍与测试迁移

- 桌面、平板和窄屏关键旅程无横向溢出，键盘和焦点行为可用。
- Vitest 覆盖 feature 状态和安全清理，Playwright 覆盖关键端到端旅程。
- 浏览器测试优先使用 role、label 和稳定 `data-testid`，减少对视觉 class 的耦合。

### US-204：切换默认入口并清理旧前端

- parity 清单全部通过后切换 `/index`、`/settings` 到新前端。
- 完成回退演练后删除旧 `app.js`、旧主模板和无用 CSS。
- 更新 README、架构、M13、部署说明、测试命令和 Stage 归档。

## 11. 验收矩阵

至少覆盖：

- 单个 FOUND/EMPTY/FAILED 与候选选择。
- 非第一季明确确认、冲突候选禁用和 draft 过期恢复。
- 批量多项独立失败、修改、删除、单个/批量/全接受。
- 队列刷新恢复、顺序提交、失败重试、SUBMITTING/RESULT_PERSIST_FAILED recover。
- Request 修改、取消、删除与 AutoBangumi Settings 上下文。
- qB/AB 连接成功、认证失败、超时、非 JSON 响应和敏感字段清理。
- localStorage、sessionStorage、URL、页面、日志、截图和 trace 的敏感值检查。
- 360px 窄屏、键盘导航、焦点恢复、ARIA 状态和 reduced motion。

## 12. 完成标准

1. 用户所有主要 Web 旅程在新前端达到或超过旧页面行为。
2. 前端只依赖 Stage 26 OpenAPI/DTO，不导入或复制 Python 内部模型。
3. 旧原生 JavaScript 全局状态中心被删除，不存在新旧双实现长期并存。
4. 敏感外部配置仅存在于当前组件内存和单次 POST body。
5. TypeScript、lint、Vitest、production build、Python API 测试和真实 Chromium 全部通过。
6. `/index`、`/settings`、`request_id`、`batch_id` 的用户可恢复行为保持兼容。
7. Stage 27 不夹带新的业务 backlog 功能，前端迁移完成后再重新评估 BL-020/BL-021 等事项。
