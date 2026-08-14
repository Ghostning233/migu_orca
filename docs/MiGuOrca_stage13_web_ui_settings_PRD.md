# MiGuOrca Stage 13 PRD: Web UI Settings 分离与主界面整理

## 1. 背景

Stage 12 已完成 Flask Web UI、真实 MiKan / Auto Bangumi 显式配置入口、qBittorrent 显式连接测试和浏览器自动化覆盖。当前能力可用，但 Web UI 信息架构已经开始失控：

1. `/index` 同时承载 Request 生成、真实 MiKan 配置、qBittorrent 连接测试、Request 列表、详情、Auto Bangumi 提交和验收说明。
2. 配置项与主流程混在一起，用户无法区分“日常订阅工作台”和“外部系统配置/连接测试”。
3. Stage 12 的浏览器测试大量固化单页结构，导致测试通过只能说明旧结构没有回退，不能说明当前 UI 达到预期。

Stage 13 的目标是优化 Web UI 功能组织，把配置相关功能迁移到独立 Settings 页面，同时修复主页面交互中已经暴露的可用性问题。

## 2. 当前 Web UI 问题清单

基于当前代码检查，以下问题需要在 Stage 13 处理：

1. 缺少独立 Settings URL。当前 `src/apps/migu_orca_web/views.py` 只提供 `/` 和 `/index` 页面路由，没有 `/settings`。
2. 主页面导航过载。`index.html` 顶部导航包含生成表单、qBittorrent、Request 列表、Request 详情和验收说明，配置与验收内容都占据主流程空间。
3. 真实 MiKan 配置嵌在生成表单中。用户只想生成离线 Request 时仍会看到数据源配置概念，增加认知负担。
4. qBittorrent 连接测试是主页面全宽面板。它不是日常 Request 工作台的一部分，应迁移到 Settings 页面。
5. Auto Bangumi endpoint/token 表单由 `app.js` 动态插入 Request 详情区。详情页同时承担查看、确认、修改和外部提交配置，操作层级不清晰。
6. Storage 目录偏好与生成表单耦合。`storage_dir` 是环境/偏好配置，不应作为主生成表单的主要字段长期暴露。
7. 取消操作依赖 `window.prompt`，没有页面内确认/原因输入表单，不利于可访问性和一致的错误展示。
8. 修改表单允许提交空 patch，且无法清空已有规则或 folder_name；这使“修改”功能未达到受限编辑的预期。
9. Request 详情没有 URL 可恢复状态。刷新 `/index` 后当前选中的 Request 丢失，Settings 页面也无法稳定回跳到指定 Request。
10. 页面中的“验收说明”是开发说明，不应出现在面向用户的主界面。

## 3. Stage 13 目标

1. 新增 Settings 页面，页面 URL 为 `/settings`；同时支持 `/Settings` 重定向到 `/settings`。
2. `/index` 收敛为 Request 工作台，只保留 Request 生成、列表、详情和核心操作。
3. Settings 页面承载配置、连接测试和外部系统操作入口，包括 Storage 偏好、真实 MiKan 配置说明、qBittorrent 连接测试，以及从 Request 详情跳转来的 Auto Bangumi 提交配置。
4. 保持 Stage 12 的安全边界：真实 MiKan、Auto Bangumi、qBittorrent 的 endpoint、token、username、password、cookie、SID、原始 HTML、原始 RSS XML、原始响应体不得写入 storage JSON、状态历史、浏览器 storage、URL、日志、截图或测试 trace。
5. 补强浏览器测试，覆盖 `/settings` 路由、主页面精简、配置迁移、Request URL 状态和关键交互修复。

## 4. 非目标

1. 不新增真实 qBittorrent 下载、创建任务或订阅能力。
2. 不实现账号、认证、权限或多人配置系统。
3. 不把真实外部系统敏感配置持久化到 storage JSON 或浏览器 storage。
4. 不引入 React、Vite 或新的前端构建链。
5. 不处理 BL-001 真实 MiKan 搜索/RSS 解析兼容性优化。

## 5. 信息架构要求

### 5.1 主页面 `/index`

`/index` 是 Request 工作台，应包含：

1. 标题输入与生成按钮。
2. 保存 Request 的明确开关。
3. 当前 Settings 摘要，例如当前 storage 目录是否使用默认值、默认数据源是否为离线 fixture。
4. Request 列表、搜索、状态筛选和排序。
5. Request 详情。
6. PENDING_CONFIRM Request 的确认、取消、修改操作。
7. ACCEPTED Request 的 Auto Bangumi 提交入口应变成跳转到 Settings 的动作，而不是在详情区直接展开 endpoint/token 表单。

`/index` 不应包含：

1. qBittorrent endpoint/username/password 表单。
2. MiKan search_endpoint/timeout_seconds 表单。
3. Auto Bangumi endpoint/token 表单。
4. 验收说明面板。

### 5.2 Settings 页面 `/settings`

`/settings` 是配置与连接测试页面，应包含：

1. Storage 偏好：默认 storage_dir、默认保存 Request 开关、清除偏好按钮。
2. 数据源配置说明：默认离线 fixture；真实 MiKan 配置只允许作为当前请求临时输入，不持久化。
3. qBittorrent 连接测试表单：endpoint、username、password、timeout_seconds、verify_tls，复用 Stage 12 API。
4. Auto Bangumi 提交表单：当从 Request 详情携带 request_id 进入 Settings 时展示，要求 endpoint、token、fallback_enabled，并调用既有 submit API。
5. 返回主页面的导航。若存在 request_id 上下文，返回链接应能回到该 Request 的详情。

## 6. 关键行为要求

1. `/` 继续重定向到 `/index`。
2. `/settings` 可以直接访问并加载页面。
3. `/Settings` 重定向到 `/settings`。
4. 主页面生成 Request 后，如果保存成功，应刷新列表并自动选中新生成 Request；如果只生成预览，应展示详情但不污染本地 storage。
5. 主页面支持 `?request_id=<id>`，加载后自动读取并展示该 Request；Request 列表点击详情时同步 URL。
6. 主页面取消操作必须改为页面内表单或对话区域，不再使用 `window.prompt`。
7. 修改表单必须阻止空 patch，并支持清空 `must_contain`、`must_not_contain` 和 `expected_folder_name` 的明确操作。
8. Settings 页面 qBittorrent 连接测试成功只展示 `status`、`reachable`、`version`，失败只展示脱敏错误。
9. Settings 页面 Auto Bangumi 提交成功后展示脱敏摘要，并提供返回主页面对应 Request 的链接。
10. Settings 中的敏感字段提交成功后必须清空；失败时可以保留当前表单值以便修正，但不得写入 storage、URL 或浏览器 storage。

## 7. Ralph User Stories

Stage 13 的开发由 Ralph / 开发 agent 执行。每个 story 应独立可验收，并按优先级顺序推进。

1. US-088: 新增 Settings 路由、模板和导航骨架。
2. US-089: 从主页面移除 qBittorrent 面板与验收说明，保持主页面工作台可用。
3. US-090: 将 Storage 偏好迁移到 Settings，并让主页面读取偏好摘要。
4. US-091: 将 qBittorrent 连接测试迁移到 Settings 页面。
5. US-092: 为主页面增加 request_id URL 状态恢复。
6. US-093: 将 Auto Bangumi 提交配置迁移到 Settings 页面。
7. US-094: 修复取消和修改交互。
8. US-095: 补齐 Stage 13 浏览器回归测试与文档收尾。

## 8. 验收命令

每个 story 完成后至少运行：

```bash
uv run pytest -q
uv run python -m compileall -q src
```

涉及 UI 的 story 还必须运行：

```bash
uv run pytest tests/browser/ -v
```

如果浏览器环境不可用，先运行：

```bash
./script/setup-browser-deps.sh
```

## 9. 安全边界

Stage 13 不放宽任何 Stage 12 安全边界。尤其注意：

1. Settings 页面不能因为命名为配置页而持久化真实 MiKan、Auto Bangumi 或 qBittorrent 敏感配置。
2. URL query 只能携带 `request_id` 等非敏感上下文，不能携带 endpoint、token、username、password、cookie、SID 或完整外部 URL。
3. 浏览器 `localStorage` 只允许保存非敏感 UI 偏好，例如 storage_dir 和 save_request 默认值。
4. 测试 fixture、截图、trace 和日志不得包含真实外部系统凭据。
