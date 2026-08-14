# M13 Web UI / 管理界面模块 PRD

## 1. 模块目标

M13 负责 Web UI 或管理界面能力，用于展示 Request、执行确认操作、管理配置和查看历史记录。Stage 7 已实现 Flask Web UI MVP，Stage 8 补强可用性，Stage 9 增加浏览器自动化测试，Stage 10 增加确认、取消和受限修改操作入口，Stage 11 增加显式真实 MiKan / Auto Bangumi 配置入口，Stage 12 增加 qBittorrent 显式连接测试入口，Stage 13 将配置相关能力迁移到独立 Settings 页面并收敛 Request 工作台，Stage 14 修复默认生成后的 Request 可操作性、未保存预览契约、Seeds 三列表和 qBittorrent Settings 直显，Stage 15 增加 `ACCEPTED` Request 的修改与删除动作，并将筛选规则默认语义改为大小写不敏感的字面匹配，同时提供 `使用正则` 与 `大小写敏感` 选项。

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

本模块不负责：

1. Request 生成业务逻辑。
2. 种子筛选规则。
3. AB 调用。
4. 持久化底层实现。
5. qBittorrent 下载、任务创建或订阅动作。
6. 用户认证系统，除非后续明确纳入范围。

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

以上能力都不应把真实 MiKan、Auto Bangumi 或 qBittorrent 的 endpoint、token、username、password、cookie、SID、原始 HTML、原始 RSS XML、原始响应体或本地绝对路径写入 storage JSON、状态历史、浏览器 storage、URL、日志、截图或测试 trace。Stage 15 只允许将非敏感 Storage 偏好写入浏览器 `localStorage`，URL query 只允许携带 `request_id` 等非敏感上下文。

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

## 4. 后续能力规划

Web UI 后续可以支持：

1. 真实 MiKan 搜索/RSS 解析兼容性优化后的候选选择与解析诊断展示。
2. 字幕组和 RSS 源候选的更细粒度人工选择。
3. 降级 JSON 下载或复制入口。
4. 更多用户偏好和规则配置管理。
5. qBittorrent 下载或订阅动作入口，仅在后续 Stage 明确纳入范围后实现。
6. 认证、权限或远程部署保护，仅在出现多人使用或公网暴露场景后实现。

## 5. 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| Q-M13-01 | Web UI 是否进入第二阶段还是更后阶段？ | 否 | 已在 Stage 7 进入，Stage 15 已完成 ACCEPTED 管理与筛选语义优化 |
| Q-M13-02 | 是否需要用户认证？ | 否 | 暂不纳入，除非出现远程部署或多人使用场景 |
| Q-M13-03 | UI 技术栈如何选择？ | 否 | 已选择 Flask 服务端渲染 + 少量原生 JS |
| Q-M13-04 | 是否需要移动端适配？ | 否 | Stage 15 已补齐 `/index` 与 `/settings` 响应式回归 |
| Q-M13-05 | qBittorrent 是否需要在 UI 中启动下载或创建订阅？ | 是，阻塞该类功能 | Stage 12 仅连接测试；下载或订阅动作必须单独规划 |
