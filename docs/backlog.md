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
| 5 | BL-007 | Web UI Request 可操作性与筛选可视化修复 | 完成 |
| 6 | BL-008 | Web UI ACCEPTED 管理与筛选语义优化 | 完成 |
| 7 | BL-009 | 真实 MiKan 合集详情页解析与直连入口 | 完成 |
| 8 | BL-001 | 优化真实 MiKan 番剧搜索和 RSS 源解析 | 完成 |
| 9 | BL-011 | 真实 MiKan Web 主流程收敛与预览优化 | 完成 |
| 10 | BL-012 | 批量番剧输入与订阅草案卡片工作台 | 完成 |
| 11 | BL-010 | AI 番剧名解析与搜索词增强 | 完成（provider seam + fake provider；Stage 21 已闭环为用户修正驱动的搜索词增强） |
| 12 | BL-013 | 批量接受与 Auto Bangumi 提交前队列管理 | 完成 (Stage 20, 2026-08-19) |
| 13 | BL-015 | 用户偏好与智能推荐闭环 | 完成 (Stage 21, 2026-08-20) |
| 14 | BL-016 | Web UI 搜索工作台重构与真实候选闭环 | 完成 (Stage 22, 2026-08-23) |
| 15 | BL-017 | 媒体缓存、MiKan 读取优化与批量审核体验 | 完成 (Stage 23, 2026-08-24) |
| 16 | BL-019 | AutoBangumi 真实认证与订阅兼容闭环 | 完成 (Stage 24, 2026-08-25) |
| 17 | BL-018 | 正式番名与季数解析 | 待规划 |
| 18 | BL-014 | 部署/配置向导可行性验证 | 待办，远期，仅辅助配置 |

以下事项已经落盘，但尚未进入开发优先级排序；触发条件满足或完成独立可行性评估后，再决定是否进入新的 Stage：

| Backlog ID | 事项 | 状态 / 触发条件 |
| --- | --- | --- |
| BL-020 | 当前最新播出集数 | 待评估；先证明公开、稳定且不依赖种子数猜测的数据源 |
| BL-021 | 真实 LLM 名称解析 provider | 待独立评估；供应商、密钥、成本和无 LLM fallback 明确后再排期 |
| BL-022 | 新版 AutoBangumi API Token/Bearer 写契约 | 条件触发；取得明确目标版本及官方契约或脱敏 fixture 后再排期 |

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

### BL-007: Web UI Request 可操作性与筛选可视化修复

- 状态：完成 (Stage 14, 2026-08-14)
- 来源：Stage 13 后人工验收
- 优先级：5
- 不阻塞：Stage 14 验收通过

观察结果：

- 已修复 `/index` 输入 `咒术回战` 并生成后详情可见但确认、取消、修改失败并提示 `未找到已保存的 Request` 的问题。
- 已明确默认生成流程为生成并保存；显式 `save_request=false` 只进入只读预览，且不展示依赖已保存 Request 的动作。
- 已通过默认生成流程刷新 Request 列表并同步详情 URL，支持稳定浏览器回归。
- 已为修改排除规则输入 `[v2]` 提供 literal helper，并在详情中展示 Seeds 被排除的效果。
- Seeds 区已展示完整、有效和排除三个种子列表及数量。
- Settings 中 qBittorrent 的 `测试 qBittorrent 连接` 已改为直接显示的按钮和表单，不再作为展开控件。

目标：

- 默认工作台流程已能生成已保存 Request，并支持列表、详情、确认、取消和修改的浏览器回归。
- 未保存预览已具备清晰状态标识、只读动作契约和保存入口，前端不对预览调用确认、取消、修改或 Auto Bangumi 提交 API。
- 修改筛选规则后，详情同步展示 Filter、完整 Seeds、有效 Seeds 和排除 Seeds，方便观察 `[v2]` 等规则效果。
- qBittorrent Settings 分区已去掉 dropdown/disclosure 逻辑，直接显示 endpoint、username、password、timeout、verify_tls 和测试按钮。
- 已保持安全边界：真实 endpoint、token、username、password、cookie、SID、原始 HTML、原始 RSS XML、原始响应体不得进入 storage JSON、browser storage、URL、日志、截图或 trace。

### BL-008: Web UI ACCEPTED 管理与筛选语义优化

- 状态：完成 (Stage 15, 2026-08-14)
- 来源：Stage 14 后人工验收
- 优先级：6
- 不阻塞：Stage 15 验收通过

观察结果：

- 已修复 Request 确认进入 `ACCEPTED` 状态后 Web UI 不能删除或修改该 Request 的问题。
- 后端 `modify_request` 已接受 `PENDING_CONFIRM` 与 `ACCEPTED`，修改后保持原状态；`CANCELLED` 与未知状态仍被拒绝。
- 本地 Request storage 已支持 path-safe 的 `delete_request_snapshot`，删除后刷新列表、详情和 URL 状态。
- 筛选规则已默认按普通字符（字面文本）匹配且大小写不敏感，普通用户输入 `[v2]`、`v2` 等字符无需理解正则或 helper。
- 筛选表单已提供默认未选中的 `使用正则` 与 `大小写敏感` 复选框；未选中 `使用正则` 时输入 `[`、`[v2]` 等字符不会触发正则错误。

目标：

- 已为已保存 Request 增加显式删除能力，覆盖 `ACCEPTED` Request，并在删除后刷新列表、详情和 URL 状态。
- 已允许 `ACCEPTED` Request 执行与 `PENDING_CONFIRM` 相同范围的受限修改，修改后保持 `ACCEPTED` 状态并记录 `MODIFY` Audit。
- 筛选规则已默认改为普通字符包含/排除，大小写默认不敏感；`use_regex=true` 时才按正则编译。
- 已为筛选表单增加 `大小写敏感` 和 `使用正则` 复选框，两者默认未选中，默认提交发送 `use_regex=false` / `case_sensitive=false`。
- `使用正则` 未选中时，输入 `[`、`[v2]` 等字符不会触发正则错误；选中后才启用正则校验并返回统一校验错误。
- 已保持安全边界：真实 endpoint、token、username、password、cookie、SID、原始 HTML、原始 RSS XML、原始响应体不得进入 storage JSON、browser storage、URL、日志、截图或 trace。

## 搜索与真实 MiKan 兼容性

### BL-009: 真实 MiKan 合集详情页解析与直连入口

- 状态：完成 (Stage 16, 2026-08-15)
- 来源：真实 MiKan 搜索/详情页人工验证，2026-08-15
- 优先级：7
- 已解决：Stage 17 已在此之上完成搜索候选展示与用户手动选择

观察结果：

- MiKan 搜索页的 `相关推荐` 通常只有有限合集入口，不能保证直接搜索模糊番剧名时出现目标季度或第一季。
- 以《无职转生》为例，搜索 `无职转生` 可能被后续季度占满推荐位；搜索 `无职转生 第一季` 可能无结果；搜索完整标题 `无职转生～到了异世界就拿出真本事～` 可出现第一季合集。
- 进入 `https://mikanani.me/Home/Bangumi/2353` 后，详情页可解析到番剧标题、番剧级 RSS、字幕组级 RSS、字幕组名称、种子标题、单集详情页链接和 magnet 属性。

目标：

- 已支持 CLI `--mikan-bangumi` 和 Web API `mikan_bangumi` 直接输入 MiKan `Home/Bangumi/<id>` URL 或 bangumi ID，绕过不稳定搜索。
- 已修复并增强真实 MiKan 番剧详情页解析，优先返回字幕组级 RSS 源，番剧级 RSS 仅作 `全部字幕组` fallback。
- 已增加离线 HTML fixture，覆盖当前 MiKan 详情页结构，不让测试依赖实站。
- 已保持安全边界：原始 HTML、原始 RSS XML、完整失败 URL、cookie、token、原始响应体、敏感路径不写入 storage、history、浏览器 storage、URL、日志、截图或 trace。
- Stage 16 未新增 Web UI direct-entry 控件；Stage 17 将把搜索候选展示、手动选择和直连 fallback 接入 UI。

### BL-001: 优化真实 MiKan 番剧搜索和 RSS 源解析

- 状态：完成 (Stage 16/17, 2026-08-15)
- 来源：Stage 5 验收后的真实 MiKan 试用
- 优先级：4
- 不阻塞：Stage 6 启动

观察结果：

- 使用真实 MiKan endpoint 搜索 `无职转生`、`無職転生`、`Mushoku Tensei` 可以返回候选番剧。
- 搜索 `无职转生 第四季`、`無職転生 第4期` 未返回候选；当前 MiKan 结果中最新可见相关候选为 `无职转生 第三季 ～到了异世界就拿出真本事～`。
- 对多个真实 MiKan 番剧页执行 `list_rss_sources(...)` 时返回 `mikan_parse_failed: MiKan 番剧页未找到 RSS 源`。
- 手动抽样页面片段可见类似 `/RSS/Bangumi?bangumiId=...` 的 RSS 链接，说明现有解析规则未完全覆盖实站 HTML 结构。

后续建议：

- 基于 Stage 16 详情页 parser 增加搜索候选展示：解析 MiKan 搜索页可见合集候选，展示标题、海报、MiKan ID 和来源查询。
- 将候选选择结果或 direct URL/ID fallback 传入 Stage 16 `mikan_bangumi` direct-entry 路径，避免新增第二套详情解析。
- 增强搜索关键词策略，例如中日文标题、数字季/第 N 季/第 N 期、罗马字别名的 fallback 查询。
- 为真实搜索和 RSS 源解析增加手动验收脚本，输出候选和安全脱敏后的解析摘要。
- 保持错误输出不包含原始 HTML、RSS XML、完整 URL、cookie 或 token。

Stage 拆分结论：

- Stage 16 已实现已选中合集详情页解析与直连 URL/ID 入口。
- Stage 17 已实现搜索候选合集展示、手动选择、直连 URL/ID fallback、进程内候选缓存和 display-only 推荐标记；推荐标记不自动选择、不自动生成。
- 搜索结果只能承诺“展示 MiKan 当前页面可解析到的候选合集”，不能承诺列出所有可能合集。
- Stage 18 已完成把真实 MiKan 搜索从附属入口收敛为 Web 主流程，并把 fixture 降级为开发/离线测试路径。
- 剩余搜索词增强（中日文标题、数字季/第 N 季、罗马字别名 fallback 查询）与 AI 番剧名解析已并入 BL-010 低优先级跟踪。

### BL-011: 真实 MiKan Web 主流程收敛与预览优化

- 状态：完成 (Stage 18, 2026-08-15)
- 来源：Stage 17 后人工验收，2026-08-15
- 优先级：9
- 阻塞：Web 主流程产品体验收敛

观察结果：

- 真实 MiKan 搜索应是普通用户输入番剧名后的主流程，而不是依附在 fixture 生成旁边的可选插件。
- 当前 Web UI 中 `search_endpoint`、`timeout_seconds`、`query` 等技术字段会误导用户；用户只应输入番剧标题。
- 直连 fallback 不应依赖用户填写 MiKan 搜索 endpoint；输入 MiKan 合集 URL 或 ID 应直接生成预览草案。
- 当前预览阶段不能修改字幕组、筛选规则或文件夹名，导致用户必须先保存 Request 才能调整规则。
- Seeds 展示应优先展示当前选中字幕组的有效种子，完整种子应按字幕组分组，排除种子放最后。

完成情况（Stage 18）：

- `/index` 主生成区已改为默认真实 MiKan 候选搜索，使用系统默认 MiKan endpoint（`https://mikanani.me/Home/Search`）和 timeout（15 秒）。
- 主界面只展示番剧标题输入；普通用户不可见 `search_endpoint`、`timeout_seconds` 或 `query` 字段。
- 已增加「搜索无结果时使用直连合集」勾选框，勾选后展示 MiKan 合集 URL 或 ID 输入框。
- 候选选择和直连 fallback 默认生成可编辑订阅草案预览（`save_request=false`）；用户可在预览中修改字幕组、筛选规则和文件夹名，通过 `preview-modify` dry-run 实时重算种子后再保存。
- 用户态文案已中文化，状态枚举映射为“待确认”“已确认”“已取消”等可读文本。
- Seeds 展示顺序已改为有效种子、完整种子、排除种子；完整种子按字幕组分组并默认收纳。
- fixture 生成能力保留给 CLI、API seam 和离线测试，但不再作为普通 Web 主流程：Web UI 入口放在 `/index` 底部「开发 / 离线测试」面板中并默认收起。

### BL-012: 批量番剧输入与订阅草案卡片工作台

- 状态：完成 (Stage 19, 2026-08-19)
- 来源：2026-08-19 方向调整讨论
- 优先级：10
- 阻塞：批量新番订阅前置工作台成立

完成情况（Stage 19）：

- Web UI `/index` 已增加批量输入工作区，支持按行输入季度新番简称、口语名或不完整标题，空行会被忽略。
- 每个非空行作为独立 item，通过 AI 名称解析 seam 和 MiKan candidate search 生成可审核订阅草案卡片。
- 卡片展示封面或占位、番剧全名、源名称、有效种子数、展开控件和删除按钮；桌面网格、窄屏单列和长列表滚动已由浏览器测试覆盖。
- 展开卡片后展示过滤器、当前字幕组、有效种子和排除种子摘要，敏感外部字段不会渲染。
- 卡片内修改入口复用现有预览详情修改流程，修改后只回流当前卡片。
- 单卡接受已接入，成功后只更新当前卡片为「已接受」；批量接受和全接受留给 BL-013 / Stage 20。

约束：

- 批量卡片应复用现有单番剧 Request/订阅草案生成、预览修改和保存能力，不重写第二套业务逻辑。
- 卡片状态必须可审核，不允许 AI 或候选搜索静默自动选择最终合集。
- 单个卡片失败不能阻塞其他卡片继续审核。
- 批量输入、AI 解析、MiKan 搜索和卡片展示不得泄露 raw HTML、raw RSS XML、完整失败 URL、cookie、token、magnet 或原始响应体。

### BL-010: AI 番剧名解析与搜索词增强

- 状态：完成 (Stage 19 provider seam + fake provider, 2026-08-19)
- 来源：真实 MiKan 搜索策略讨论，2026-08-15；2026-08-19 批量新番工作台方向调整
- 优先级：11
- 阻塞：批量简称输入体验

完成情况（Stage 19）：

- 已新增 AI 名称解析 provider seam，输出 `raw_title`、`canonical_title_candidates`、`season_hint`、`search_queries`、`confidence`、`needs_user_review` 和 `source`。
- fake provider 已覆盖 `萌王S4`、`路哥S4`、`杖剑谭S2`、`邻家天使S2` 的确定性解析，供本地和测试使用，不调用真实 LLM。
- 低置信度、多候选和 provider 失败场景已由单元测试覆盖；失败错误保持可恢复且脱敏。
- 真实 LLM provider 的生产配置、供应商选择、密钥管理和成本控制未在 Stage 19 实现，应作为后续独立能力评估。

约束：

- AI 名称解析只能作为可选增强模块，不能成为真实 MiKan 搜索、候选选择或 Request 生成的必需依赖。
- 无 API key、无付费能力或 LLM 失败时，系统仍必须可以使用 Stage 17 的手动搜索候选选择和 Stage 16 的直连 URL/ID 入口。
- LLM 输出不能自动决定最终合集；最终仍必须经过用户确认或选择。

Stage 21 闭环情况（2026-08-20）：

- 搜索词增强已闭环为用户修正驱动：`correction_repository.py` 保存非敏感 `TitleCorrection`（raw_title、公开 canonical title、season_hint、公开 bangumi 元数据、query_correction），同 raw_title 最新版本 + 全局 500 条上限；`search_enhancer.py` 纯函数把修正展开为 `{query, original_query, source}` 可审核增强搜索词。
- 增强失败、修正为空或修正文件损坏时回退原 `search_queries`；真实 LLM provider 仍不是必需条件。
- 用户修正记录只包含显式保存的非敏感字段，不包含完整 MiKan 页面、RSS URL、响应体或外部配置。

### BL-013: 批量接受与 Auto Bangumi 提交前队列管理

- 状态：完成 (Stage 20, 2026-08-19)
- 来源：2026-08-19 方向调整讨论
- 优先级：12
- 不阻塞：Stage 19 单卡审核闭环

完成情况（Stage 20）：

- 批量工作台支持单卡接受、选中批量接受和全接受；工具栏显示选中数量，不可接受项目逐项返回中文原因，单项失败不阻塞其他项。
- 已接受项目进入独立追踪的提交前队列（`READY_TO_SUBMIT`），队列只保存非敏感元数据，endpoint/token/cookie/Authorization header/原始响应体/完整 RSS URL/magnet/本地绝对路径从不进入队列。
- `#batch-queue-panel` 展示队列项目标题、中文状态（待提交/提交中/提交成功/提交失败/可重试）、尝试次数和脱敏结果摘要；刷新页面后通过 URL `batch_id` 恢复队列状态。
- 批量提交要求 request-scoped `ab_config` 和显式确认；按队列顺序复用现有 Auto Bangumi 提交流程，单项成功/失败独立记录，失败项可独立重试，成功项不会被重复提交。
- 提交结果以脱敏形式写入现有 Request/AB result storage；端到端安全回归覆盖 API 响应、页面、URL、浏览器 storage、队列 JSON、Request JSON、日志和 trace 的敏感值过滤。

约束（仍成立）：

- 不直接创建 qBittorrent 下载任务。
- 不绕过 Auto Bangumi 建立长期订阅状态机。
- 不引入后台常驻 worker 或复杂调度器；批量提交采用前台顺序编排。
- 不把“确认后自动提交并下载”作为核心卖点；核心卖点是批量订阅前审核与提交辅助。

Stage 21 handoff：在 Stage 19/20 批量草案基础上记录用户偏好（字幕组、筛选、文件夹命名）并闭环搜索词增强，减少逐卡修改次数。具体执行拆分见 `docs/MiGuOrca_stage21_preference_recommendation_PRD.md`。

### BL-015: 用户偏好与智能推荐闭环

- 状态：完成 (Stage 21, 2026-08-20)
- 来源：BL-013 Stage 21 handoff、BL-010 搜索词增强闭环需求
- 优先级：13
- 阻塞：减少批量草案逐卡修改次数

完成情况（Stage 21）：

- `/settings` 偏好面板管理非敏感偏好：偏好字幕组/排除字幕组、fallback 规则、筛选包含/排除规则、正则/大小写敏感选项、文件夹命名策略与命名模板、搜索增强开关；保存成功刷新规范化值，清空/恢复默认需显式确认。
- 批量草案生成时把偏好作为单卡可编辑默认值：字幕组偏好经 M05 `select_subtitle_group` 先排除、再优先、最后 fallback；筛选偏好复用 M06 语义；命名偏好生成 `expected_folder_name` 默认值。
- 搜索词增强闭环：`correction_repository.py` 保存非敏感 `TitleCorrection`（同 raw_title 最新版本 + 全局 500 条上限），`search_enhancer.py` 纯函数展开为 `{query, original_query, source}` 可审核增强搜索词；增强失败或修正为空时回退原 `search_queries`。
- 批量卡片展示偏好命中摘要、低置信度/多候选/冲突等 `needs_user_review` 审核提示和搜索词来源，帮助用户快速核对；单卡修改只更新当前卡片。
- 安全边界：偏好与修正只保存非敏感字段；endpoint、token、cookie、Authorization header、magnet、raw HTML、raw RSS XML、原始响应体和本地绝对路径从偏好 JSON、API 响应、页面、URL、浏览器 storage、日志和 trace 中被拒绝或剥离；端到端安全回归已覆盖。

约束（仍成立）：

- AI 只生成候选，不自动选择最终 MiKan 合集，不自动接受卡片。
- 无偏好、偏好读取失败或增强失败时回退 Stage 19 默认流程。
- 偏好不隐式追踪用户观看行为或下载内容。
- 不引入复杂账号体系，除非出现多人使用或远程部署需求。

Stage 23 closeout：同源安全封面缓存、搜索结构感知提前停止、锚定候选浮层、统一草案详情、播出进度占位与禁用控件静态反馈均已完成并有安全/Chromium 回归。随后 BL-019 在 Stage 24 完成 AutoBangumi 3.1.18 账号密码/Cookie 与 RSS subscribe 兼容闭环，并保留 API Token fail-closed 边界。其他未开发事项只保留优先级，不再预绑定 Stage 编号。

### BL-016: Web UI 搜索工作台重构与真实候选闭环

- 状态：完成 (Stage 22, 2026-08-23)
- 来源：2026-08-23 Web UI 人工验收
- 优先级：14
- 阻塞：搜索结果可信度、批量草案人工审核与操作闭环
- 执行 PRD：`docs/MiGuOrca_stage22_web_search_workbench_PRD.md`

已确认问题：

- `/index` 的 `#generate-panel` 同时混排单番剧输入、批量输入、直连 fallback 和两套结果，标题“真实 MiKan 候选搜索”也偏实现术语。
- 批量 API 确实逐项复用真实 `_search_mikan_candidates`，但无候选时仍基于 fake provider 的解析标题创建空壳 `preview_request` 并显示“已解析”，容易把无效输入误认为真实番剧。
- 后端成功路径返回 `PARSED`，前端卡片展开逻辑只允许 `DRAFT/READY`；部分浏览器测试使用理想化 `DRAFT` mock，掩盖了真实契约错误。
- 单个/批量候选卡和搜索状态反馈尚未统一；封面缺失、无候选和搜索失败的用户态表达不清晰。

目标：

- 将主入口改为“创建订阅方案”，以“单个搜索 / 批量搜索”分段控件一次展示一个输入模式。
- 新增与订阅方案详情同级、独占一行的搜索结果面板，两种模式统一向此输出。
- 明确标题解析、候选 FOUND/EMPTY/FAILED 与 DRAFT/READY 草案状态；无候选不生成空壳草案。
- 批量模式只编排多个单项候选搜索；用户显式选择真实 MiKan 合集后才复用详情解析与 preview 链路生成草案。
- 统一候选标题、MiKan ID、封面/占位和选择动作，增加简洁真实的 loading/完成/空结果/失败反馈。
- 使用生产 API 状态形状和真实 Chromium 补齐浏览器回归，外部 MiKan 继续通过测试 seam/mock 隔离。

约束：

- AI 只生成候选标题和搜索词，不自动选择最终合集、接受卡片或提交 Auto Bangumi。
- 不新增第二套 MiKan parser、筛选器、命名器或 Request 生命周期实现。
- 不创建 qBittorrent 下载任务，不绕过 Auto Bangumi，不引入后台 worker。
- 新结果面板和测试不得泄露 endpoint、token、cookie、Authorization header、raw HTML、raw RSS XML、magnet、原始响应体、完整失败 URL或本地绝对路径。

### BL-017: 媒体缓存、MiKan 读取优化与批量审核体验

- 状态：完成 (Stage 23, 2026-08-24)
- 来源：2026-08-23 Stage 22 后人工验收
- 优先级：15
- 执行 PRD：`docs/MiGuOrca_stage23_media_cache_search_ui_PRD.md`

范围：

- MiKan 封面改为服务端安全同源缓存，默认 7 天滑动 TTL、10 秒下载超时、5 MiB 上限，页面异步加载且不阻塞正文。
- 通过结构证据和脱敏 fixture 实现 MiKan 搜索页有界提前停止，避免下载候选区域之后的大量无关内容。
- 批量候选改为锚定按钮的单实例浮层；批量草案统一进入订阅方案详情，卡片布局相互独立。
- 卡片显示 `播出进度：待开发 / 总集数`，总集数缺失显示未知，不推断当前最新播出集数。
- 禁用按钮不再显示等待鼠标或旋转动画；真实 busy 状态保持 loading。

约束：

- 不提供任意 URL图片代理，不引入后台 worker，不泄露原始封面 URL或缓存路径。
- 不实现正式番名解析、最新播出集数或流式封面转发。

### BL-019: AutoBangumi 真实认证与订阅兼容闭环

- 状态：完成 (Stage 24, 2026-08-25)
- 来源：2026-08-24 AutoBangumi 3.1.18 实机只读验证
- 优先级：16
- 执行 PRD：`docs/MiGuOrca_stage24_autobangumi_compatibility_PRD.md`

目标：

- 已默认使用服务地址、用户名和密码登录 AutoBangumi 3.1.18，以单次 token Cookie 调用只读与订阅接口。
- 已保留新版 API Token/Bearer 兼容模式，未知写契约 fail closed。
- 已增加只读连接测试，按真实 `/api/v1/rss/subscribe` 契约提交单个/批量已接受 Request。
- 凭据保持 request-scoped；自动化与 Ralph 不对真实实例执行写操作。

### BL-018: 正式番名与季数解析

- 状态：待规划
- 来源：2026-08-23 批量搜索人工验收
- 优先级：17

待解决：

- `萌王S4` 依赖 fake provider 开发示例，而 `无职转生s4` 等真实输入不能可靠转换为官方第四季搜索词。
- 收敛“源名称：搜索词：...”标签叠加，定义正式的解析来源和搜索词展示契约。
- 定义简称、别名、中日文标题、数字季/`S4`、多个搜索词、低置信度和无结果 fallback。
- AI/规则只生成候选搜索词，最终 MiKan 合集仍由用户显式选择。

### BL-014: 部署/配置向导可行性验证

- 状态：待办，远期，仅辅助配置
- 来源：2026-08-19 方向调整讨论
- 优先级：18
- 不阻塞：批量新番订阅工作台

目标：

- 评估是否需要独立能力帮助用户从 0 配置 qBittorrent、Auto Bangumi 和 MiGuOrca 的连接信息。
- 优先考虑配置检查、连接诊断、教程式向导和 Docker Compose 模板，而不是全自动运维 Agent。
- 如后续纳入开发，必须作为独立 Stage 规划，明确平台范围、权限边界、回滚策略和安全责任。

约束：

- 不把 MiGuOrca 扩展为通用部署器。
- 不默认接管用户机器、NAS 或容器环境。
- 不因部署向导改变 MiGuOrca 的核心定位：Auto Bangumi 前置订阅编排工作台。

### BL-020: 当前最新播出集数

- 状态：待评估，未排期
- 来源：Stage 23 剧集摘要占位
- 优先级：未排序，不阻塞 BL-018

待确认：

- 先确定公开、稳定、可测试且允许使用的数据源，再决定是否实现抓取或聚合。
- 不使用有效种子数、RSS 最大集数、下载状态或文件名猜测当前播出集数。
- 数据源缺失、失败或冲突时继续显示“待开发”或“未知”，不得伪造进度。

### BL-021: 真实 LLM 名称解析 provider

- 状态：待独立评估，未排期
- 来源：Stage 19/21 名称解析 provider seam
- 优先级：未排序，不阻塞 BL-018

待确认：

- 评估供应商选择、模型能力、密钥管理、费用、限流、超时和脱敏边界。
- 真实 LLM 只能生成候选标题和搜索词，不能自动选择 MiKan 合集、接受草案或提交 AutoBangumi。
- 无 API key、无付费能力、超时或 provider 失败时，规则解析、手动候选选择和 MiKan URL/ID fallback 必须继续可用。
- BL-018 应先定义与 provider 无关的稳定解析契约；本项不与 BL-018 强绑定。

### BL-022: 新版 AutoBangumi API Token/Bearer 写契约

- 状态：条件触发，未排期
- 来源：Stage 24 AutoBangumi 兼容闭环
- 优先级：未排序；只有出现明确目标版本和写入需求时重新评估

待确认：

- 取得目标 AutoBangumi 版本的官方契约、OpenAPI 或不含凭据的脱敏 fixture，证明认证、提交路径、payload 和成功响应。
- 每个版本/adapter 独立声明 `submit_supported`，不得把 3.1.18 Cookie 或 `{data, rss}` 契约套用于未知 Bearer 版本。
- 未证明写契约时继续只读探测并 fail closed；自动化不得向真实实例创建订阅。
