# M13 Web UI / 管理界面模块 PRD

## 1. 模块目标

M13 负责 Web UI 或管理界面能力，用于展示订阅方案、执行确认操作、管理配置和查看历史记录。Stage 7～26 已逐步完成 Flask Web UI、Request 操作、Settings、真实 MiKan 候选、可编辑预览、批量工作台、提交前队列、偏好展示、媒体缓存、AutoBangumi 兼容、标题季数解析展示和 Web API 契约固化。单个/批量入口通过分段控件管理，标题解析、真实候选和订阅草案状态明确分离；Stage 27 已在 OpenAPI/DTO 基线上把页面迁移到独立前端工程（Vue 3 + TypeScript + Vite，Flask 在 `/app/` 同源托管），并删除旧 Flask/Jinja 页面与 `app.js`；Stage 28 已接入草案 revision、可靠保存与保存确认，`draft_id`/revision/idempotency_key 只在页面内存流转。

## 2. 模块边界

本模块负责：

1. 展示 Request 列表和详情。
2. 展示源信息、候选 RSS、有效种子和排除原因。
3. 提供接受、修改、取消操作入口。
4. 展示 AB 提交结果和降级配置。
5. 在 Settings 页面提供配置、连接测试和非敏感浏览器偏好入口。
6. 提供仅对 `ACCEPTED` Request 可见的显式 Auto Bangumi Settings 提交入口。
7. 提供 qBittorrent 显式连接测试入口。
8. 提供 Request 详情 URL 状态恢复。
9. 展示日志摘要或错误信息。
10. 提供批量订阅草案卡片工作台，支持用户审核名称解析和 MiKan 搜索结果。

本模块不负责：

1. Request 生成业务逻辑。
2. 种子筛选规则。
3. AB 调用。
4. 持久化底层实现。
5. qBittorrent 下载、任务创建或订阅动作。
6. 用户认证系统，除非后续明确纳入范围。
7. 自动部署或接管 Auto Bangumi / qBittorrent。
8. AI 自动决定最终合集或静默接受订阅方案。

## 3. 当前 Web UI 接入状态

| 阶段 | 能力 | Web UI 状态 | 说明 |
| --- | --- | --- | --- |
| Stage 7 | 本地 Web UI MVP | 已接入 | 页面加载、Request 生成、保存、列表、详情、历史和 AB 结果只读展示 |
| Stage 8 | Web UI 可用性增强 | 已接入 | 导航、运行模式提示、浏览器校验、偏好记忆、列表搜索筛选排序、详情分组、通知、响应式和基础无障碍 |
| Stage 9 | 浏览器自动化测试 | 已接入 | `tests/browser/` 覆盖关键页面行为，默认使用本地 fixture 和 fake endpoint seam |
| Stage 10 | Request 确认、取消和受限修改 | 已接入 | PENDING_CONFIRM 详情页展示确认、取消、修改操作，成功后刷新详情、状态历史和列表 |
| Stage 11 | 显式真实 MiKan / Auto Bangumi 配置入口 | 已接入 | 引入显式真实 MiKan 生成配置和 ACCEPTED Request 的显式 Auto Bangumi 提交能力 |
| Stage 12 | qBittorrent 显式连接测试 | 已接入 | 引入确认后调用连接测试 API 并只展示脱敏摘要的 qBittorrent 测试能力 |
| Stage 13 | Web UI Settings 信息架构 | 已接入 | `/index` 是 Request 工作台；`/settings` 管理 Storage 偏好、qBittorrent 连接测试和 request-scoped Auto Bangumi 提交 |
| Stage 14 | Request 可操作性与筛选可视化 | 已接入 | `/index` 默认生成并保存可操作 Request；显式预览只读；Seeds 展示完整、有效、排除列表；qBittorrent Settings 表单直接显示 |
| Stage 15 | ACCEPTED 管理与筛选语义优化 | 已接入 | 已保存 `ACCEPTED` Request 展示修改/删除/AB 提交动作；筛选默认字面匹配且大小写不敏感，提供 `使用正则` / `大小写敏感` 控件；Filter 展示匹配模式与大小写状态 |
| Stage 16 | 真实 MiKan direct URL/ID 入口 | API-only | CLI/API 支持 `mikan_bangumi` request-scoped direct entry；Web UI 暂不展示直连输入控件 |
| Stage 17 | 真实 MiKan 候选搜索、手动选择与直连 fallback | 已接入 | `/index` 默认折叠的候选搜索区支持候选卡片、`选择此合集` 手动选择、直连 URL/ID fallback、进程内候选缓存和 display-only 推荐标签；全部复用 `mikan_bangumi` 生成链路，不自动选择、不自动生成 |
| Stage 18 | 真实 MiKan 主流程、可编辑预览与 Seeds 优化 | 已接入 | `/index` 主生成区默认搜索真实 MiKan 候选；普通 UI 移除 `search_endpoint`、`timeout_seconds`、`query`；候选选择和直连 fallback 默认生成可编辑订阅草案（`preview-modify` dry-run + `preview-save`）；Seeds 改为有效、完整、排除顺序并按字幕组分组；fixture 入口放入底部「开发 / 离线测试」面板并默认收起 |
| Stage 19 | 批量输入与订阅草案卡片工作台 | 已接入 | `/index` 批量工作区支持多行简称输入、AI 名称解析 seam、逐项 MiKan 候选搜索、订阅草案卡片网格、删除、展开、详情修改回流和单卡接受 |
| Stage 20 | 批量接受、提交前队列与失败项重试 | 已接入 | `/index` 批量工作台提供单卡接受、勾选批量接受和全接受；`#batch-queue-panel` 展示提交前队列（中文状态、尝试次数、脱敏结果摘要）并提供显式 AB 提交；失败项可独立重试，成功项不显示重试 |
| Stage 21 | 偏好管理面板与批量卡片偏好/修正展示 | 已接入 | `/settings` 的 `#preference-settings-panel` 管理非敏感偏好（字幕组、筛选、命名、搜索增强开关），支持保存与显式恢复默认；批量卡片展示偏好命中摘要、需人工核对 chip、偏好与审核面板（偏好命中/警告/审核提示/当前默认配置）和搜索词来源面板（修正增强搜索词/原始搜索词） |
| Stage 22 | 搜索工作台与真实候选闭环 | 已接入 | “创建订阅方案”提供单个/批量分段切换；两种结果迁入独立 `#search-results-panel`；统一候选卡、封面/占位、FOUND/EMPTY/FAILED、候选选择后草案动作和真实搜索反馈 |
| Stage 23 | 媒体缓存与批量审核体验 | 已接入 | 候选封面使用同源异步缓存；批量候选为锚定按钮的单实例浮层；批量草案进入统一详情；卡片显示播出进度占位；禁用按钮使用静态反馈 |
| Stage 24 | AutoBangumi 真实认证与订阅兼容 | 已接入 | Settings 和批量队列默认使用账号密码/服务根地址，可切换 API Token；只读连接测试、3.1.18 Cookie submit、凭据清理与 Chromium 安全回归均已完成 |
| Stage 25 | 正式番名与季数解析 | 已接入 | 单个/批量入口展示共享解析摘要、实际查询和季数证据；非第一季缺少公开证据时要求明确确认，冲突候选不可选择 |
| Stage 26 | Web API 契约固化与服务端边界治理 | 已接入 | `/api/v1` 端点清单与 golden contract 冻结、响应 DTO 与 OpenAPI 生成；稳定 HTTP 状态（400/404/409/401/502/503/504/500）；Web storage 限制为服务端根目录下相对 profile（空值回落服务端根）；未保存草案由服务端 DraftStore 权威持有，客户端只持 opaque `draft_id`；旧页面在不改变主要视觉与用户流程的前提下保持兼容 |
| Stage 27 | 前端工程化迁移与页面重构 | 已接入 | Vue 3 + TypeScript(strict) + Vite 独立前端工程（`frontend/`，Flask 在 `/app/` 同源托管，SPA fallback 只接管 `/app/*`）；4 条 SPA 路由（工作台/订阅方案/提交队列/Settings）与统一 API transport；全部 Web 旅程迁移完成（Settings/Request 列表与详情/单个与批量搜索/草案/提交队列）；入口路由固定重定向到 SPA；US-209 删除旧 `app.js`、旧 Jinja 主模板与无用 CSS/测试 helper |
| Stage 28 | 草案一致性与原子保存确认 | 已接入 | 草案 `draft_id`/`draft_revision`/`idempotency_key` 只在组件内存维护（父组件持有 revision，`changed`/`draft-changed` 事件回写批量卡片），`preview-modify` 发送 `base_revision`、`preview-save` 预留草案；保存失败保留草案面板可重试（仅 `draft_expired` 等确认失效才清除）；单番/批量 save-confirm 一次完成保存确认，返回 `CONFIRMED` + ACCEPTED handoff（Stage 29 起扩展 tracking 字段） |
| Stage 29 | 统一追番记录与可靠提交恢复 | API-only（无新页面） | 后端交付统一 tracking 列表/详情/revalidate/submit/retry/recover API 与旧入口收敛；前端只通过生成客户端获得新 DTO/operationId，现有保存确认返回 tracking handoff 字段但不渲染新状态；正式“追番管理”页面等待 B-C2/B-D，旧 `/app/workbench|requests|queue|settings` 保持不变 |

以上能力都不应把真实 MiKan、Auto Bangumi 或 qBittorrent 的 endpoint、token、username、password、cookie、SID、原始 HTML、原始 RSS XML、原始响应体或本地绝对路径写入 storage JSON、状态历史、浏览器 storage、URL、日志、截图或测试 trace。Stage 15 只允许将非敏感 Storage 偏好写入浏览器 `localStorage`，URL query 只允许携带 `request_id` 等非敏感上下文。Stage 16 的 `mikan_bangumi` 和 Stage 17 的候选搜索/选择/直连 fallback 的 `mikan_config` 都是 request-scoped 字段，不应写入浏览器 storage、URL、history 或持久配置；候选搜索响应只包含公开候选元数据和 display-only 推荐标签。Stage 19 的批量解析和卡片展示只应渲染 batch/item 状态、解析元数据、公开 MiKan 候选字段、白名单过滤器摘要和种子标题摘要；raw HTML、raw RSS XML、cookie、token、magnet、完整失败 URL、原始响应体和本地绝对路径必须被忽略或脱敏。Stage 20 的提交前队列只展示队列项目标题、状态、尝试次数、时间和脱敏结果摘要；endpoint、token、Authorization header、cookie、原始响应体、完整 RSS URL、magnet 和本地绝对路径必须被忽略或脱敏，AB 配置只存在于当前提交 POST body，不写入 URL、localStorage、sessionStorage、队列 JSON 或 Request snapshot。Stage 21 的偏好表单是非敏感表面，只提交已定义的非敏感偏好字段，拒绝的敏感输入回退到上次有效值；批量卡片只渲染 `preference_hits`/`preference_warnings`/`review_hints`/`applied_preferences`/`enhanced_search_queries` 中的公开规则摘要和中文提示，endpoint、token、cookie、raw HTML、raw RSS XML、magnet、完整失败 URL、原始响应体和本地绝对路径必须被忽略或脱敏。Stage 26 的 `storage_dir` 只允许服务端根目录下的相对 profile（空值回落服务端根，绝对路径/穿越/符号链接逃逸被拒绝），未保存草案只通过 opaque `draft_id` 交互，完整 Request、draft 内容与外部敏感配置绝不进入 URL 或浏览器 storage；OpenAPI 示例全部使用虚构脱敏值，凭据字段标记 `x-request-scoped`。Stage 28 的 `draft_revision`/`idempotency_key` 与 `draft_id` 一样只在请求体与组件内存中流转，绝不进入 URL/browser storage；save-confirm 错误与批量逐条结果只返回脱敏 error_type + 固定中文，`safe-info` 是“全部信息”的唯一允许数据源（`extra="forbid"` DTO + 默认拒绝 serializer）。

Stage 15 UI 质量要求：

1. `/index` 首屏聚焦标题输入、生成操作、Request 列表和详情，不展示配置表单或开发验收说明。
2. `/index` 默认生成并保存 Request；只有显式 `save_request=false` 才展示只读预览，预览不得暴露确认、取消、修改、删除或 Auto Bangumi 提交动作。
3. 已保存 `ACCEPTED` Request 详情必须同时展示 `修改`、`删除` 和 `去 Settings 提交 Auto Bangumi`；`删除` 必须经确认框确认，取消确认不调用删除 API。
4. Request 详情 Filter 分区必须展示包含规则、排除规则、匹配模式（普通字符或正则）和大小写状态；Seeds 分区必须展示完整、有效和排除列表，排除原因使用 `命中排除规则` / `未命中包含规则` 可读语言；修改筛选规则后 Filter 与 Seeds 必须同步刷新。
5. 修改表单筛选字段使用 `包含规则` / `排除规则` 标签，并提供默认未选中的 `使用正则` / `大小写敏感` 复选框；默认提交发送 `use_regex=false` / `case_sensitive=false`，普通字符模式下输入 `[`、`[v2]` 不得触发正则错误。
6. `/settings` 的 Storage、数据源、qBittorrent 和 Auto Bangumi 分区边界清晰；qBittorrent 连接测试表单直接显示，Auto Bangumi 按 `request_id` 上下文渐进展示。
7. 按钮语义保持一致：生成、确认、提交使用主按钮；刷新、修改、返回 Settings 使用次按钮；取消、清空、删除或撤销类操作使用危险/警示样式。
8. 空状态、加载状态、成功状态和错误状态使用统一容器，只展示用户可操作信息，不展示调试噪音或敏感配置。
9. 中屏和窄屏下保持单列或低密度布局，Request 详情 Overview、Source、Filter、Seeds、Audit 分组必须可扫读。

Stage 18 UI 调整要求（Stage 18 已落地）：

1. `/index` 主生成区保留与列表同一行的布局，但标题输入默认触发真实 MiKan 候选搜索。
2. 普通 UI 只要求番剧标题，不展示 `search_endpoint`、`timeout_seconds` 或 `query` 等技术字段名。
3. 主生成区提供“搜索无结果时使用直连合集”复选框；勾选后显示 MiKan 合集 URL 或 ID 输入框。
4. 候选选择和直连 fallback 默认生成“订阅草案（未保存）”预览，用户显式保存后才进入正式订阅方案列表。
5. 预览草案可修改字幕组、筛选规则和文件夹名，并同步刷新有效/排除种子展示。
6. 用户态文案应优先使用“订阅方案”“订阅草案”“待确认”“已确认”“已取消”等中文业务表达；内部 Request 字段可保持不变。
7. Seeds 展示顺序必须为有效种子、完整种子、排除种子；完整种子按字幕组分组并可展开/收起。
8. fixture 入口如果仍在 Web 中保留，必须标注为开发/离线测试并默认隐藏或低优先级展示。Stage 18 实现为 `/index` 底部「开发 / 离线测试」面板中的 `Fixture 生成` 折叠区，`<details id="dev-fixture-disclosure">` 默认不带 `open`（收起），普通用户路径不会触发 fixture 生成；只有开发者手动展开后才能使用。

Stage 19 UI 调整要求（Stage 19 已落地）：

1. `/index` 提供批量获取入口，包含多行输入框、示例简称和提交按钮；空输入在前端以中文错误拦截，不调用批量 API。
2. 批量结果以 `.batch-card-grid` 卡片网格展示，桌面端通常一行 4 个，窄屏最低一行 1 个，长列表外层可滚动。
3. 每张卡片展示封面或占位、番剧标题、源名称、有效种子数、中文状态和可用动作；删除只移除当前卡片。
4. DRAFT/READY 卡片可展开查看当前字幕组、包含规则、排除规则、匹配模式、大小写、有效种子和排除种子摘要。
5. 单卡 `修改` 复用现有未保存预览详情修改流程，保存后只更新当前卡片。
6. 单卡 `接受` 复用现有 Request accept 能力，成功后当前卡片状态显示为「已接受」，同批次其他卡片不变。
7. 已接受卡片不得展示无需确认的危险删除动作；Stage 19 不提供批量接受、全接受或 Auto Bangumi 提交队列，Stage 20 已补齐该能力。

Stage 20 UI 调整要求（Stage 20 已落地）：

1. `/index` 批量工作台提供单卡接受、可勾选选择、批量接受和全接受入口；工具栏显示选中数量（`已选择 N 项`），FAILED、已删除、缺少候选等不可接受项目逐项显示中文原因。
2. 批量接受成功后的卡片显示「已接受 / 待提交」，其他卡片状态保持不变；提交过程中接受按钮、复选框和删除按钮进入 loading/disabled 状态，失败后恢复可操作。
3. `#batch-queue-panel` 展示队列项目标题、中文状态（待提交/提交中/提交成功/提交失败/可重试）、尝试次数、脱敏结果摘要和最后更新时间。
4. 提交前表单包含服务地址、认证方式、当前模式凭据、fallback 选项和显式确认；默认账号密码，可切换 API Token。提交中按钮禁用，批量响应结束后各项目状态独立刷新，成功项目不显示重试按钮；提交成功后清空服务地址和全部认证输入，HTTP 级失败时保留输入以便重试。
5. 刷新页面后通过 URL `batch_id` 恢复队列状态（`syncBatchIdToUrl`/`batchIdFromLocation`），从持久化队列重新加载已记录的结果摘要。
6. 单项重试按钮只出现在 FAILED/RETRYABLE 项目上；点击重试后使用最新保存的 `ACCEPTED` Request 重新提交，成功项永远不会显示重试按钮。
7. 服务地址、username、password、token 只存在于当前提交 POST body；不得写入 URL、localStorage、sessionStorage、队列 JSON 或 Request snapshot；页面和 API 不得展示凭据、完整服务地址、Authorization、cookie、原始响应体、magnet、raw RSS XML 或本地绝对路径。

Stage 21 UI 调整要求（Stage 21 已落地）：

1. `/settings` 提供 `#preference-settings-panel` 偏好面板：偏好字幕组/排除字幕组文本域、fallback 下拉、包含/排除规则、使用正则/大小写敏感复选框、命名策略下拉与命名模板、搜索增强开关；页面加载时展示已保存偏好，保存成功后展示中文成功反馈并刷新规范化值。
2. 偏好表单是非敏感表面：只提交已定义的非敏感字段；被拒绝的敏感输入回退到上次有效值，不会残留在表单控件中，也不回显外部 endpoint/token/cookie/raw 响应。
3. 清空或恢复默认偏好必须显式触发（`window.confirm`），且只写 `<storage>/preferences/user_preferences.json`，不会清除 Stage 20 队列、Request 或 AB result 存储。
4. 批量卡片展示偏好命中摘要行（偏好命中：字幕组、筛选、命名 / 偏好不可用，已回退默认流程 / 未配置偏好，使用默认流程）和需人工核对 chip（`needs_user_review` 且未接受时）。
5. 展开的 `.batch-card-review` 面板展示偏好与审核块（偏好命中摘要、偏好警告、审核提示、当前默认配置）和搜索词来源块（修正增强搜索词及来源、原始搜索词）。
6. 单卡修改只更新当前卡片，其他卡片的偏好命中/审核提示文本保持不变；偏好提示不覆盖现有卡片修改、候选选择、批量接受和 Stage 20 队列状态。
7. 偏好/审核展示只读公开非敏感字段；无偏好、偏好读取失败或增强失败时展示明确的默认流程状态，不阻塞手动候选选择和直连 fallback。

Stage 22 UI 调整要求（已完成）：

1. `#generate-panel` 标题使用用户目标“创建订阅方案”，不再使用“真实 MiKan 候选搜索”作为一级标题。
2. 使用具备键盘操作、焦点样式和 ARIA 选中态的“单个搜索 / 批量搜索”分段控件；一次只展示当前模式输入。
3. 新增 `#search-results-panel`，与订阅方案详情等 panel 同级并独占一行；单个候选列表、批量分组结果及批量选择工具栏统一迁入该面板。
4. 模式切换不能把另一模式的旧结果冒充当前结果；结果面板必须显示当前模式和安全搜索上下文。
5. 单个和批量结果复用候选卡渲染原语；FOUND 显示标题、MiKan ID、匹配提示、封面或占位和“选择此合集”，批量按原始输入分组且不默认选择第一个候选。
6. EMPTY 显示“未找到匹配的 MiKan 合集”，FAILED 显示可重试的脱敏错误；两者均不显示展开、修改、保存、接受动作。
7. `PARSED` 只表示标题解析成功，不能渲染为已找到或可接受草案；只有真实候选选择并完成详情解析后，DRAFT/READY 才可展开、修改和接受。
8. 复用现有状态框显示简洁真实的搜索中、完成、空结果和失败反馈；单一长请求不得用定时器伪造服务端页面解析或逐项进度。
9. loading 时禁用相关输入、模式切换和提交控件，结束后恢复；状态框使用 `aria-live`，不得强制移动用户焦点。
10. Playwright 必须使用生产 API 的真实状态形状覆盖 FOUND/EMPTY/FAILED、PARSED→选择候选→DRAFT、封面/占位、模式切换、独立结果面板、窄屏和基础无障碍；不得用理想化 `DRAFT` mock 掩盖后端 `PARSED` 契约。
11. 新面板只渲染公开候选与脱敏状态，不得显示或持久化 endpoint、token、cookie、Authorization header、raw HTML、raw RSS XML、magnet、原始响应体、完整失败 URL或本地绝对路径。

Stage 23 UI 调整要求（已完成）：

1. 候选图片只使用 MiGuOrca 同源 opaque cache URL，默认显示占位，并设置 `loading="lazy"`、`decoding="async"`；图片慢或失败不阻塞正文、选择和其他操作。
2. 批量 FOUND 的“查看候选”打开单实例锚定浮层，箭头指向触发按钮；点击其他按钮切换，点击外部/Escape/模式切换/重新搜索/删除 active 卡片关闭。
3. 浮层维护 `aria-expanded`/`aria-controls`、焦点进入和返回；桌面/窄屏保持 viewport 内，不在 `#search-results-panel` 制造额外内部滚动条。
4. DRAFT/READY 的“查看草案”把 preview/request 送入现有“订阅方案详情”，不在结果卡内渲染完整 `.batch-card-review`；详情保留修改、保存、接受、筛选和种子动作。
5. 各结果卡片布局相互独立，不因同一 grid row 另一张卡片的草案内容被拉长。
6. 卡片单行显示 `播出进度：待开发 / N 集` 或 `播出进度：待开发 / 未知`；不以有效种子数推断播出进度。
7. disabled/`aria-disabled=true` 控件使用静态视觉和普通/default 鼠标，hover 不显示 spinner/无限动画；只有真实 `aria-busy=true` 才显示 loading。
8. 新浮层、详情和封面端点继续遵守敏感值过滤与真实 Chromium 回归要求。

Stage 24 UI 调整要求（已完成）：

1. Settings AutoBangumi 分区始终提供只读“测试连接”，不再要求先有 request_id；提交仍只对已接受 Request 展示并要求显式确认。
2. 表单字段为服务地址和认证方式；默认账号密码模式显示用户名/密码，API Token 模式只显示 token，隐藏模式的敏感字段必须清空且不提交。
3. 单个提交和批量队列使用同一认证组件/配置契约，不再把 endpoint 当作完整写 URL。
4. 成功摘要只显示版本、认证模式、adapter 和是否支持提交；连接或提交成功后清空全部敏感字段。
5. 真实 Chromium 覆盖切换、校验、连接测试、提交确认、成功清理、失败脱敏、键盘可访问性和窄屏布局。

Stage 25 UI 调整（已完成）：

1. 单个与批量结果统一展示识别标题、识别季度、中文解析来源、实际搜索词和审核提示。
2. 候选来源只显示一次，修复“源名称：搜索词：...”标签叠加；内部 source code 通过白名单映射，不直接渲染。
3. 低置信度、多别名、季数冲突、原始输入 fallback、查询截断和候选冲突显示“需人工核对”。
4. EMPTY/FAILED 保留手动重试和 MiKan URL/ID fallback；任何结果都不自动选择、保存、接受或提交。
5. 复用 Stage 22/23 的候选卡、单实例浮层和统一详情，并用真实 Chromium覆盖单个/批量、窄屏、键盘和安全边界。

Stage 26 UI 调整（已完成，维持最小旧前端兼容）：

1. `fetchJson` 兼容非 2xx JSON envelope、非 JSON body 与网络失败，错误统一走中文脱敏通知。
2. `storage_dir` 只接受服务端根目录下的相对 profile；旧 localStorage 绝对路径值自动清除（平滑迁移），Settings 输入改标“storage profile（相对服务器根目录）”。
3. 未保存草案只持内存 `currentDraftId`/`row.draft_id`，`preview-modify`/`preview-save` 只发送 `draft_id`；draft 过期/重放错误追加“请重新生成订阅草案后再试”指引。
4. 不改变页面主要视觉与用户流程；全部既有 URL、状态恢复与中文业务文案保持兼容。

Stage 27 UI 调整（已完成，US-209 删除旧前端）：

1. 页面迁移到 Vue 3 + TypeScript + Vite 独立工程（`frontend/`），4 条 SPA 路由
   （`/app/workbench`、`/app/requests`、`/app/queue`、`/app/settings`）；统一 API transport
   处理 envelope/非 2xx/非 JSON/网络失败/取消/超时，feature 不自行拼接 `/api/v1` URL。
2. 入口路由（`/`、`/index`、`/Settings`、`/settings`）固定重定向到 SPA，保留公开
   `request_id`/`batch_id` query；旧书签可用。旧 Jinja 页面、`app.js`、`style.css` 与
   `MIGU_ORCA_WEB_ENTRY_LEGACY` 回退开关已在 US-209 删除。
3. 敏感值（endpoint/token/cookie/password/原始响应等）只存在于组件局部内存与单次 POST
   body；不进入 URL、browser storage、日志、截图或 trace。前端类型只来自生成的 OpenAPI
   客户端，不手写第二套响应 interface。

Stage 28 UI 调整（已完成）：

1. 未保存草案的 `draft_id` 与单调 `draft_revision` 只在组件内存维护：生成时从 create/
   parse 结果取 revision，每次 `preview-modify` 发送当前 `base_revision` 并用返回的新
   `draft_revision` 更新本地 ref；批量卡片在 `items` 内保存 `draft_revision`，修改后经
   `changed`/`draft-changed` 事件回写父组件。revision/draft_id 绝不写入 URL 或 browser
   storage，`draft_revision_conflict` 并入 409 重生成提示。
2. `preview-save`/save-confirm 发送 `draft_id` + `base_revision`。保存写盘失败（如
   `storage_error`）保留草案面板让用户重试同一草案；只有服务端确认草案失效
   （`draft_expired`/`draft_evicted`/`draft_replayed`/`draft_revision_conflict`）才清除并
   提示重新生成。`draft_reserved` 是瞬态并发冲突，也保留草案并提示稍后重试。
3. 保存确认使用 opaque `idempotency_key`（客户端为一次明确操作生成，传输重试必须复用），
   只在单次请求体与内存中出现；成功返回 `ACCEPTED` handoff，Stage 28 前端不展示或伪造
   tracking 状态。

Stage 29 UI 调整（已完成，无新页面）：

1. Stage 29 不开发新的正式追番管理页面（B-B 只交付后端契约与生成客户端）。前端生成客户端
   新增 `/api/v1/tracking/items*` 的 operationId/类型，`api.test.ts` 同步断言；旧页面不直接
   调用这些端点。
2. save-confirm/批量确认响应新增 `tracking_id`/`tracking_status`/`tracking_ready`/`safe_message`
   字段；现有页面继续使用 `request_id` + `status=ACCEPTED` 流程，不渲染 tracking 状态。
3. 旧单番/批量提交与队列页面的后端行为收敛到统一 submission service，页面操作与安全边界不变；
   Stage 30 B-C1 只提供只读同步；等待 B-C2/B-D 冻结后再接入依赖外部写管理能力的“追番管理”页面（见 `MiGuOrca_future_stages.md`
   Stage 29 handoff）。

## 4. 后续能力规划

Web UI 后续可以支持：

1. 字幕组和 RSS 源候选的更细粒度人工选择。
2. 降级 JSON 下载或复制入口。
3. 部署/配置向导仅作为 backlog 中的远期辅助能力，不预绑定 Stage，也不作为 qBittorrent 下载或 Auto Bangumi 替代执行系统。
4. 认证、权限或远程部署保护，仅在出现多人使用或公网暴露场景后实现。
5. 当前最新播出集数登记为 BL-020；在公开稳定数据源未证明前继续显示安全占位，不根据种子、RSS 或下载状态猜测。

## 5. 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| Q-M13-01 | Web UI 是否进入第二阶段还是更后阶段？ | 否 | 已在 Stage 7 进入，Stage 15 已完成 ACCEPTED 管理与筛选语义优化 |
| Q-M13-02 | 是否需要用户认证？ | 否 | 暂不纳入，除非出现远程部署或多人使用场景 |
| Q-M13-03 | UI 技术栈如何选择？ | 否 | Stage 27 已选择 Vue 3 + TypeScript + Vite 独立前端工程（US-197 建立基线，US-209 删除旧 Flask/Jinja 页面） |
| Q-M13-04 | 是否需要移动端适配？ | 否 | Stage 15 已补齐 `/index` 与 `/settings` 响应式回归 |
| Q-M13-05 | qBittorrent 是否需要在 UI 中启动下载或创建订阅？ | 是，阻塞该类功能 | Stage 12 仅连接测试；下载或订阅动作必须单独规划 |
| Q-M13-06 | AI 是否可以自动接受某个 MiKan 合集？ | 是，阻塞自动接受 | 不允许静默自动接受；AI 只提供候选标题和搜索词，最终合集必须可审核 |

## Stage 25 实际边界

单个与批量候选共用结构化 season 摘要和实际查询列表。候选缺少非第一季公开证据时，确认框默认未勾选且选择按钮禁用；用户勾选才可选择，取消即恢复禁用，并由服务端再次 fail closed。页面仅显示 opaque 封面地址，不能把它作为 AutoBangumi 海报来源。
