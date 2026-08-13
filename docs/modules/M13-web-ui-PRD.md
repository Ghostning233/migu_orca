# M13 Web UI / 管理界面模块 PRD

## 1. 模块目标

M13 负责 Web UI 或管理界面能力，用于展示 Request、执行确认操作、管理配置和查看历史记录。Stage 7 已实现 Flask Web UI MVP，Stage 8 补强可用性，Stage 9 增加浏览器自动化测试，Stage 10 增加确认、取消和受限修改操作入口，Stage 11 增加显式真实 MiKan / Auto Bangumi 配置入口，Stage 12 增加 qBittorrent 显式连接测试入口。

## 2. 模块边界

本模块负责：

1. 展示 Request 列表和详情。
2. 展示源信息、候选 RSS、有效种子和排除原因。
3. 提供接受、修改、取消操作入口。
4. 展示 AB 提交结果和降级配置。
5. 提供显式真实 MiKan 生成配置入口。
6. 提供仅对 `ACCEPTED` Request 可见的显式 Auto Bangumi 提交入口。
7. 提供 qBittorrent 显式连接测试入口。
8. 提供用户偏好和规则配置入口。
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
| Stage 11 | 显式真实 MiKan / Auto Bangumi 配置入口 | 已接入 | 生成表单可显式选择真实 MiKan；ACCEPTED 详情页可显式提交 Auto Bangumi |
| Stage 12 | qBittorrent 显式连接测试 | 已接入 | 页面提供默认折叠的连接测试面板，确认后调用连接测试 API，只展示脱敏摘要 |

以上能力都不应把真实 MiKan、Auto Bangumi 或 qBittorrent 的 endpoint、token、username、password、cookie、SID、原始 HTML、原始 RSS XML、原始响应体或本地绝对路径写入 storage JSON、状态历史、浏览器 storage、URL、日志、截图或测试 trace。

## 4. 后续能力规划

Web UI 后续可以支持：

1. 真实 MiKan 搜索/RSS 解析兼容性优化后的候选选择与解析诊断展示。
2. 字幕组和 RSS 源候选的更细粒度人工选择。
3. 降级 JSON 下载或复制入口。
4. 用户偏好配置管理。
5. qBittorrent 下载或订阅动作入口，仅在后续 Stage 明确纳入范围后实现。
6. 认证、权限或远程部署保护，仅在出现多人使用或公网暴露场景后实现。

## 5. 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| Q-M13-01 | Web UI 是否进入第二阶段还是更后阶段？ | 否 | 已在 Stage 7 进入，Stage 12 已补强真实配置和 qBittorrent 连接测试入口 |
| Q-M13-02 | 是否需要用户认证？ | 否 | 暂不纳入，除非出现远程部署或多人使用场景 |
| Q-M13-03 | UI 技术栈如何选择？ | 否 | 已选择 Flask 服务端渲染 + 少量原生 JS |
| Q-M13-04 | 是否需要移动端适配？ | 否 | Stage 8 已提供基础响应式布局 |
| Q-M13-05 | qBittorrent 是否需要在 UI 中启动下载或创建订阅？ | 是，阻塞该类功能 | Stage 12 仅连接测试；下载或订阅动作必须单独规划 |
