# MiGuOrca Backlog

本文件记录已发现但不阻塞当前阶段推进的后续优化事项。进入新 Stage 或编写 Ralph PRD 时，应先检查本文件，决定是否纳入当前阶段范围。

## 开发优先级

当前排序来自 Stage 8 Web UI 人工验收后的用户反馈。

| 优先级 | Backlog ID | 事项 | 状态 |
| --- | --- | --- | --- |
| 0 | BL-002 | Playwright / 浏览器自动化测试 | 完成 |
| 1 | BL-003 | Web UI 确认 / 取消 / 修改 Request 的操作入口 | 完成 |
| 2 | BL-004 | Web UI 真实 MiKan / Auto Bangumi 配置入口 | 完成 |
| 3 | BL-005 | qBittorrent 直连 | 完成 |
| 4 | BL-006 | Web UI Settings 信息架构优化 | 完成 |
| 5 | BL-001 | 优化真实 MiKan 番剧搜索和 RSS 源解析 | 待办 |

认证、权限模块当前优先级最低，现阶段无明确需求，默认不纳入后续开发计划。除非之后出现部署暴露、多人使用或远程访问场景，否则不为其单独规划 Stage。

## Web UI 质量与操作能力

### BL-002: Playwright / 浏览器自动化测试

- 状态：完成 (Stage 9, 2026-08-08)
- 来源：Stage 8 Web UI 人工验收
- 优先级：0
- 不阻塞：Stage 8 验收通过

目标：

- 引入浏览器级自动化验收，覆盖 `/` 重定向、`/index` 页面加载、表单校验、生成/保存、列表搜索筛选排序、详情分组、通知、响应式和键盘可访问性关键路径。
- 优先使用 Playwright 或等价浏览器自动化方案；如需新增依赖，应通过 `uv` 管理并记录运行命令。
- 测试应默认使用本地 fixture 和临时 storage，不访问真实 MiKan、Auto Bangumi 或 qBittorrent。
- 自动化输出应避免保存 token、完整 endpoint URL、原始 HTML、RSS XML 或本地绝对路径。

### BL-003: Web UI 确认 / 取消 / 修改 Request 的操作入口

- 状态：完成 (Stage 10, 2026-08-08)
- 来源：Stage 8 Web UI 人工验收
- 优先级：1
- 不阻塞：Stage 8 验收通过

目标：

- 在 Web UI 详情页提供 Request 确认、取消和受限修改入口。
- 行为应复用现有 CLI/controller 的确认、取消、修改能力，不复制业务规则。
- 操作成功后应更新本地 Request snapshot、状态历史，并刷新详情 Audit 区块。
- 失败时使用统一 Web UI 通知和后端 API error envelope，错误内容继续脱敏。
- 修改范围应保持受限，避免直接编辑完整原始 Request JSON。

### BL-004: Web UI 真实 MiKan / Auto Bangumi 配置入口

- 状态：完成 (Stage 11, 2026-08-12)
- 来源：Stage 8 Web UI 人工验收
- 优先级：2
- 不阻塞：Stage 8 验收通过

目标：

- 为 Web UI 增加显式真实 MiKan 和 Auto Bangumi 配置入口。
- 真实 MiKan 入口应要求用户明确选择，不改变默认 `static-fixture` 行为。
- Auto Bangumi 提交入口应继续要求显式确认，不能隐式提交。
- 配置输入和错误展示不得泄露 token、完整 endpoint URL、cookie、原始 HTML 或 RSS XML。
- 配置保存策略已在 Stage 11 明确为 request-scoped：真实 MiKan 与 Auto Bangumi 配置只用于当前生成或提交，不写入 storage JSON、状态历史、浏览器 storage、URL、日志、截图或测试 trace。

### BL-005: qBittorrent 直连

- 状态：完成 (Stage 12, 2026-08-12)
- 来源：Stage 8 Web UI 人工验收
- 优先级：3
- 不阻塞：Stage 8 验收通过

目标：

- 已评估并实现 qBittorrent 直连的显式连接测试能力，用于后续订阅或下载链路打通。
- Stage 12 已建立配置、认证、HTTP client seam、失败降级、Web API、Web UI 入口和浏览器自动化脱敏覆盖；不在本阶段启动下载或批量订阅。
- 已先设计配置、认证、连接测试和失败降级策略，再接入 Web UI 操作。
- 默认流程不得隐式连接 qBittorrent；必须由用户显式配置和触发。
- qBittorrent 配置只用于当前连接测试请求，不写入 storage JSON、状态历史、浏览器 storage、URL、日志、截图或测试 trace。
- 错误、日志和页面展示不得泄露认证信息、完整服务地址、cookie、SID、原始响应体或敏感路径。

### BL-006: Web UI Settings 信息架构优化

- 状态：完成 (Stage 13, 2026-08-14)
- 来源：Stage 12 单页 Web UI 配置过载
- 优先级：4
- 不阻塞：Stage 13 验收通过

目标：

- 已将 `/index` 收敛为 Request 工作台，保留生成、列表、URL 可恢复详情、确认、可见取消表单和受限修改。
- 已新增 `/settings` 页面，将非敏感 Storage 偏好、qBittorrent 连接测试和 request-scoped Auto Bangumi 提交配置迁移到 Settings。
- 已统一 Stage 13 UI 质量要求：清晰视觉层级、按钮语义、空/加载/成功/错误状态、Settings 分区边界、响应式布局和 Request 详情可扫读性。
- 已通过 Playwright 浏览器回归覆盖 Settings 保存/清除偏好、qBittorrent 成功/失败/确认、Auto Bangumi accepted-only 入口、URL 状态恢复、取消/修改交互和敏感信息脱敏。
- 信息架构拆分不改变安全边界：真实外部系统 endpoint、token、username、password、cookie、SID、原始响应体和敏感路径仍不得持久化或泄露。

## 搜索与真实 MiKan 兼容性

### BL-001: 优化真实 MiKan 番剧搜索和 RSS 源解析

- 状态：待办
- 来源：Stage 5 验收后的真实 MiKan 试用
- 优先级：4
- 不阻塞：Stage 6 启动

观察结果：

- 使用真实 MiKan endpoint 搜索 `无职转生`、`無職転生`、`Mushoku Tensei` 可以返回候选番剧。
- 搜索 `无职转生 第四季`、`無職転生 第4期` 未返回候选；当前 MiKan 结果中最新可见相关候选为 `无职转生 第三季 ～到了异世界就拿出真本事～`。
- 对多个真实 MiKan 番剧页执行 `list_rss_sources(...)` 时返回 `mikan_parse_failed: MiKan 番剧页未找到 RSS 源`。
- 手动抽样页面片段可见类似 `/RSS/Bangumi?bangumiId=...` 的 RSS 链接，说明现有解析规则未完全覆盖实站 HTML 结构。

后续建议：

- 增加针对 MiKan 实站当前 HTML 结构的离线 fixture，覆盖番剧页顶部 `.mikan-rss` 链接。
- 区分番剧级 RSS 和字幕组级 RSS：若页面只有番剧级 RSS，应明确产出可用 `RssSource` 或给出更准确的错误。
- 增强搜索关键词策略，例如中日文标题、数字季/第 N 季/第 N 期、罗马字别名的 fallback 查询。
- 为真实搜索和 RSS 源解析增加手动验收脚本，输出候选和安全脱敏后的解析摘要。
- 保持错误输出不包含原始 HTML、RSS XML、完整 URL、cookie 或 token。
