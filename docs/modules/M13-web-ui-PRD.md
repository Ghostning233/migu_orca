# M13 Web UI / 管理界面模块 PRD

## 1. 模块目标

M13 负责 Web UI 或管理界面能力，用于展示订阅方案、执行确认操作、管理配置和查看历史记录。Stage 7 已实现 Flask Web UI MVP，Stage 8 补强可用性，Stage 9 增加浏览器自动化测试，Stage 10 增加确认、取消和受限修改操作入口，Stage 11 增加显式真实 MiKan / Auto Bangumi 配置入口，Stage 12 增加 qBittorrent 显式连接测试入口，Stage 13 将配置相关能力迁移到独立 Settings 页面并收敛 Request 工作台，Stage 14 修复默认生成后的 Request 可操作性、未保存预览契约、Seeds 三列表和 qBittorrent Settings 直显，Stage 15 增加 `ACCEPTED` Request 的修改与删除动作，并将筛选规则默认语义改为大小写不敏感的字面匹配，同时提供 `使用正则` 与 `大小写敏感` 选项。Stage 16 在 CLI/API 层完成真实 MiKan direct URL/ID 入口，但没有新增 Web UI 控件。Stage 17 已在 `/index` Request 生成流程中接入真实 MiKan 候选搜索、候选卡片手动选择、直连 URL/ID fallback、进程内候选缓存和 display-only 推荐标签。Stage 18 已把真实 MiKan 候选搜索调整为 `/index` 普通 Web 主流程，并将 fixture 降级为开发/离线测试路径。Stage 19 后，M13 的主方向调整为批量新番订阅前置工作台：批量输入番剧简称，生成可审核订阅草案卡片，并支持单卡展开、删除、修改和接受。Stage 20 已在此基础上接入批量接受、全接受、提交前队列面板和失败项独立重试，完成批量确认与 Auto Bangumi 提交辅助闭环。

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
10. 后续提供批量订阅草案卡片工作台，支持用户审核 AI 解析和 MiKan 搜索结果。

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

以上能力都不应把真实 MiKan、Auto Bangumi 或 qBittorrent 的 endpoint、token、username、password、cookie、SID、原始 HTML、原始 RSS XML、原始响应体或本地绝对路径写入 storage JSON、状态历史、浏览器 storage、URL、日志、截图或测试 trace。Stage 15 只允许将非敏感 Storage 偏好写入浏览器 `localStorage`，URL query 只允许携带 `request_id` 等非敏感上下文。Stage 16 的 `mikan_bangumi` 和 Stage 17 的候选搜索/选择/直连 fallback 的 `mikan_config` 都是 request-scoped 字段，不应写入浏览器 storage、URL、history 或持久配置；候选搜索响应只包含公开候选元数据和 display-only 推荐标签。Stage 19 的批量解析和卡片展示只应渲染 batch/item 状态、解析元数据、公开 MiKan 候选字段、白名单过滤器摘要和种子标题摘要；raw HTML、raw RSS XML、cookie、token、magnet、完整失败 URL、原始响应体和本地绝对路径必须被忽略或脱敏。Stage 20 的提交前队列只展示队列项目标题、状态、尝试次数、时间和脱敏结果摘要；endpoint、token、Authorization header、cookie、原始响应体、完整 RSS URL、magnet 和本地绝对路径必须被忽略或脱敏，AB 配置只存在于当前提交 POST body，不写入 URL、localStorage、sessionStorage、队列 JSON 或 Request snapshot。

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
4. 提交前表单包含 endpoint、token、fallback 选项和显式确认；提交中按钮禁用，批量响应结束后各项目状态独立刷新，成功项目不显示重试按钮；提交成功后清空 endpoint/token 输入，HTTP 级失败时保留输入以便重试。
5. 刷新页面后通过 URL `batch_id` 恢复队列状态（`syncBatchIdToUrl`/`batchIdFromLocation`），从持久化队列重新加载已记录的结果摘要。
6. 单项重试按钮只出现在 FAILED/RETRYABLE 项目上；点击重试后使用最新保存的 `ACCEPTED` Request 重新提交，成功项永远不会显示重试按钮。
7. endpoint、token 只存在于提交 POST body；不得写入 URL、localStorage、sessionStorage、队列 JSON 或 Request snapshot；页面和 API 不得展示 token、完整 endpoint、cookie、原始响应体、magnet、raw RSS XML 或本地绝对路径。

## 4. 后续能力规划

Web UI 后续可以支持：

1. 字幕组和 RSS 源候选的更细粒度人工选择。
2. 降级 JSON 下载或复制入口。
3. Stage 21 用户偏好、字幕组偏好、规则配置和智能推荐结果展示，偏好只保存非敏感字段。
4. 部署/配置向导仅作为远期辅助能力，不作为 qBittorrent 下载或 Auto Bangumi 替代执行系统。
5. 认证、权限或远程部署保护，仅在出现多人使用或公网暴露场景后实现。

## 5. 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| Q-M13-01 | Web UI 是否进入第二阶段还是更后阶段？ | 否 | 已在 Stage 7 进入，Stage 15 已完成 ACCEPTED 管理与筛选语义优化 |
| Q-M13-02 | 是否需要用户认证？ | 否 | 暂不纳入，除非出现远程部署或多人使用场景 |
| Q-M13-03 | UI 技术栈如何选择？ | 否 | 已选择 Flask 服务端渲染 + 少量原生 JS |
| Q-M13-04 | 是否需要移动端适配？ | 否 | Stage 15 已补齐 `/index` 与 `/settings` 响应式回归 |
| Q-M13-05 | qBittorrent 是否需要在 UI 中启动下载或创建订阅？ | 是，阻塞该类功能 | Stage 12 仅连接测试；下载或订阅动作必须单独规划 |
| Q-M13-06 | AI 是否可以自动接受某个 MiKan 合集？ | 是，阻塞自动接受 | 不允许静默自动接受；AI 只提供候选标题和搜索词，最终合集必须可审核 |
