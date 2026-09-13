# MiGuOrca Stage 38 PRD：正式追番管理

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| Stage | 38 |
| 工作包 | F-F：正式追番管理 |
| Backlog | BL-026 |
| 状态 | 已规划，待开发 |
| 目标分支 | `ralph/stage38-tracking-management` |
| Ralph stories | US-303～US-317 |
| 实时基线 | `origin/main` 合并提交 `7bb2f24`（Stage 37 已合入） |
| 前置 | Stage 29～32 tracking/Auto Bangumi 契约、Stage 33 壳层、Stage 35/36 handoff、Stage 37 方案链接 |
| 视觉基线 | `docs/design/assets/frontend-ux/tracking-management-v2.png`、`tracking-revalidation-failed-v1.png` |

## 2. 背景与阶段判断

Stage 35～37 已把单番/批量保存确认、本地追番方案和精确 tracking handoff 接入正式路由。当前
`/app/tracking` 仍是过渡实现：无 `tracking_id` 时挂载 Stage 27 的 `QueueView`，有 ID 时只显示一块
只读详情。它没有统一总览、单选列表、检查器、页面级临时凭据、同步、复核、可靠提交、恢复或
Auto Bangumi 管理动作，因此效果图中的核心管理闭环尚未成立。

后端 Stage 29～32 已交付并冻结 tracking list/detail、capability、sync、revalidate、submit、retry、
recover、MODIFY、SET_ENABLED、REFRESH_RSS 和 DELETE_EXTERNAL。但本次实时审查发现两个 F-F
消费阻断：generated `modifyTrackingItem` 的 `patch` 仍为 `Record<string, never>`；服务端
`available_actions` 只给动作 code，没有给管理动作可针对的安全 target scope。前端若绕过这两个缺口，
只能手写 DTO、读取标签猜 scope 或试错调用，均违反 Stage 32 handoff。

因此 Stage 38 在第一个 story 先做加法式契约补口，再完成整个 F-F。补口不新增 endpoint、不改变
状态机或外部写语义，只把后端已经接受的白名单 patch 和已经持久化的映射范围表达成严格 OpenAPI /
generated 类型。F-G 设置简化、全局连接状态与最终发布收尾继续独立评审。

## 3. 目标

1. 把 `/app/tracking` 建成状态总览、单选列表与右侧 sticky 检查器组成的正式桌面管理页。
2. 只以 `listTrackingItems`/`getTrackingItemDetail` 的安全投影为本地权威，支持搜索、状态筛选、刷新和公开 `tracking_id` 深链。
3. 建立仅存在于当前 tracking 页面实例内存的 Auto Bangumi 凭据会话，连接探测后显示安全 capability 摘要。
4. 用户显式触发 sync 后才访问外部系统；探测失败或未知能力时保留本地列表并只读降级。
5. 待提交项可本地复核、显式确认提交；明确失败可幂等重试，结果未知只能进入恢复流程。
6. 已生效项仅按服务端 `available_actions`、安全 target scope 与本次 capability 交集提供修改、启停、RSS 刷新和外部删除。
7. 每次写使用详情最新 revision、单次意图 idempotency key、确认弹窗、进行中互斥、写后回查与结果未知保护。
8. 删除始终逐条确认外部影响，固定说明保留 MiGuOrca 本地方案和已下载媒体；不提供批量外部删除。
9. 用真实 Chromium 覆盖效果图正常态、复核失败态、能力降级、失败/恢复、危险操作、键盘、多视口与敏感信息。

## 4. 非目标

1. 不实现 F-G 设置简化、Settings 旧业务入口删除、全局连接状态联动、最终 Gate 5 或发布安装包。
2. 不新增 tracking/Auto Bangumi endpoint、外部动作、状态、认证模式或持久化 schema；US-303 只修正现有契约表达。
3. 不支持批量外部提交、批量启停、批量刷新或批量删除；每个外部动作只针对当前单条 tracking。
4. 不把旧 batch queue 当作 tracking 权威；旧 `batch_id` 仅可用于兼容定位，状态和动作必须来自 tracking DTO。
5. 不绕过 Auto Bangumi 创建 qBittorrent 下载，不调用真实 MiKan/Auto Bangumi/qBittorrent 作为自动化测试。
6. 不把凭据、endpoint、Cookie、Authorization、完整 URL/RSS、外部 ID、原始响应、绝对路径、幂等键写入 URL、DOM、storage、日志、截图或 trace。
7. 不开发移动端，不根据种子、RSS、下载或文件名猜测“已更新集数”。
8. 不手写第二套 API DTO，不读取 Python 常量控制前端，不根据状态字符串自行发明动作。

## 5. 冻结决策

### D38-01：先补齐 F-F 可生成契约

1. `modifyTrackingItem` 请求必须在 OpenAPI 中表达为与 `target_scope` 对应的严格联合类型：
   `SUBSCRIPTION` 只允许 title、season、subtitle_group、filter_rule、offset、expected_folder_name；
   `ASSOCIATED_RSS` 只允许 name、aggregate、parser。patch 至少一个字段，未知/跨 scope 字段继续拒绝。
2. 生成 TypeScript 不得再把 patch 表达成 `Record<string, never>`、`any` 或宽松任意字典；前端只从
   `operations['modifyTrackingItem']` 派生请求类型。
3. `TrackingAvailableActionDTO` 为每项动作增加严格 `target_scopes`：非管理动作为空数组；管理动作只列
   当前 TrackingRecord 安全映射中实际存在且该本地状态允许的 `SUBSCRIPTION`/`ASSOCIATED_RSS`。
4. `target_scopes` 只表示本地映射目标，不声称当前凭据或远端版本支持；真正可用性仍由同次请求的
   capability 探测和服务端写端点 fail-closed 校验决定。
5. 改动同步 Python DTO/serializer、OpenAPI、generated client、示例、endpoint inventory、handoff 与
   contract tests；不得返回外部/RSS ID、URL 或原始映射。

### D38-02：页面数据与动作所有权

1. 列表和总览只消费 generated `listTrackingItems`；详情只消费 `getTrackingItemDetail`。
2. 用户可见状态优先使用服务端 `status_label`/`status_group`。总览覆盖待处理、处理中、追番中、需处理、
   已停用/已删除；客户端只可按服务端 `status_group` 做纯展示计数，不重建状态机。
3. 动作入口只来自当前详情 `available_actions`；未知 code/style/scope 一律不渲染并显示安全只读提示。
4. 外部动作还必须满足当前页面会话 capability 对应键为 `SUPPORTED`；`UNKNOWN`、`UNSUPPORTED`、探测
   失败都不得显示可执行写按钮。客户端隐藏不是安全边界，服务端仍在每次 POST 内重新探测。
5. `EXTERNAL_ONLY` 可显示“仅存在于 Auto Bangumi”，没有 `request_id` 时不提供返回本地方案。

### D38-03：正式布局、筛选与选择

1. 桌面采用效果图 V2 的状态总览 + 约 58%～64% 列表 + 36%～42% sticky 检查器；1280 px 或 200%
   缩放允许纵向重排，不隐藏主状态和动作。
2. 列表是单选行，无 checkbox。当前行同时使用背景、边界/指示条和 `aria-current`，状态不只靠颜色。
3. 搜索只覆盖公开标题/字幕组；状态总览与筛选可以组合。筛选不暗换当前详情，被隐藏时明确提示。
4. `tracking_id` 是唯一正式选择 query。合法目标加载后定位、高亮并聚焦；非法、重复、不存在或已删除
   query 被安全清理，不回显原值。
5. 列表刷新保留仍存在的选择；目标消失时选择相邻项或回到列表容器，焦点不得丢到页面顶部。

### D38-04：检查器与安全详情

1. 检查器展示标题、季度、字幕组、有效资源、总集数、更新“待开发”、本地状态、外部安全摘要、
   最近操作、复核问题和安全审计；不展开 raw Request 或外部响应。
2. 有 `request_id` 时“查看/修改本地方案”深链 `/app/plans?request_id=...`；无本地方案时隐藏。
3. 首次详情加载有骨架；快速切换使用请求代际/取消机制，旧响应不能覆盖当前条目。
4. 详情失败不清空健康列表；保留选择并提供固定中文重试。列表失败使用页面级可恢复错误。

### D38-05：页面级临时凭据会话

1. 新建 `CredentialSessionDialog` 或等价组件，复用 `useSensitiveFields`，默认 password；API Token 只按
   capability 结果提供它实际支持的只读/提交能力，绝不假定具备 3.1.18 写管理。
2. 凭据只存在 `TrackingView` 当前实例及单次 POST body。刷新、离开 `/app/tracking`、取消连接、切换
   认证模式、明确清除和卸载都清空；成功采用连接后可在当前页面会话内复用。
3. 连接按钮先调用 generated `probeAutoBangumiCapabilities`，只展示版本、探测状态、能力支持/不支持/
   未知和安全文案；不显示 endpoint、账号或任何凭据。
4. 探测失败保持弹窗和当前输入便于修正，但错误区域只显示固定中文。用户取消时销毁全部输入。
5. 由外部动作触发连接时，成功后回到原条目/原动作上下文，但不自动执行写操作，仍需再次显式确认。

### D38-06：同步与能力降级

1. 页面初始只读本地 tracking；只有已建立页面凭据会话且用户点击“同步 Auto Bangumi”并确认后，才调用
   generated `syncTrackingItems(confirm=true)`。
2. 同步结果以返回的 tracking items/summary 安全更新页面，再重新读取当前详情；不从外部返回拼对象。
3. 同步失败、PARTIAL 或 capability UNKNOWN 不得清空本地列表或误报“无订阅”；保留旧内容、标记只读
   降级并提供重新连接/重新探测/再次同步入口。
4. 并发同步只允许一个请求；切换条目不取消全页同步，但旧的列表/详情响应不得覆盖同步后的新 revision。

### D38-07：本地复核与返回修改

1. `REVALIDATE` 只调用 generated `revalidateTrackingItem`，只发 `expected_revision` 与安全 storage profile，
   不要求/携带 AB 凭据，也不访问外部。
2. `ready=false` 是 HTTP 200 业务结果：使用服务端 issues 显示“尚未创建外部订阅”和需重新确认原因，
   用返回 tracking 原子更新列表/详情，不把它当 transport error。
3. 有公开 `request_id` 时提供“返回修改方案”深链；无 Request 的外部孤立项只显示不可返回原因。
4. 409 revision/state 冲突先重新读取详情，清除旧意图并要求用户重新确认；不得静默重复 POST。

### D38-08：显式提交、重试与幂等

1. `SUBMIT`/`RETRY` 都要求页面凭据会话、当前详情最新 revision、新生成的 opaque idempotency key 和
   `confirm=true`；确认弹窗逐条说明将创建 Auto Bangumi 外部订阅。
2. 每次用户确认的意图只生成一个 key。传输层重试复用同 key；业务明确失败后的 `RETRY` 是新意图、
   使用新 key；key 只在动作局部内存和请求体出现。
3. HTTP 200 必须按 `outcome` 分流：ACTIVE 成功；SUBMIT_FAILED 显示安全重试；NEEDS_RECONFIRM 显示
   返回修改；VERIFYING_EXTERNAL/RECOVERY_REQUIRED 进入恢复；任何结果都以返回 tracking 更新页面。
4. 请求期间锁定当前条目冲突动作，不锁死其他列表浏览。完成后刷新详情/总览，旧 revision 不再可提交。
5. 网络、timeout、非 JSON、5xx 或写后本地状态不明不得生成新 key 盲重试；先只读回查详情。

### D38-09：结果未知恢复

1. 只渲染服务端返回的 RECOVER_AUTO、MARK_SUCCEEDED、MARK_FAILED；`VERIFY_EXTERNAL` 作为恢复流程内
   的明确选择，必须有凭据且只读核验同一 operation，不能创建新外部写。
2. AUTO 不带凭据且不需要危险确认；VERIFY_EXTERNAL 带当前页面 `ab_config`；人工成功/失败必须二次
   确认且不接收外部 ID、URL、响应或备注。
3. `needs_manual=true` 时清楚要求用户先在 Auto Bangumi 独立核对，再选择人工结论；默认焦点在取消。
4. 恢复期间禁止 submit/retry/management；恢复结果用返回 tracking 收敛，无法确定时继续保持恢复态。

### D38-10：外部修改、启停与 RSS 刷新

1. 管理动作只对 `available_actions[].target_scopes` 与本次 capability 均允许的 scope 展示；scope 使用
   用户文案“外部番剧订阅/关联 RSS”，不显示外部 ID。
2. MODIFY 使用 US-303 generated 联合类型：番剧与 RSS 分开表单，不混用字段；空 patch 禁止提交。
3. SET_ENABLED 的目标布尔值由用户明确选择；停用/启用文案说明只影响 Auto Bangumi，不修改本地方案。
4. REFRESH_RSS 仅允许 `ASSOCIATED_RSS`，逐条当前 tracking 作用域；不得调用全局 refresh。
5. 三类写都复用 revision/idempotency/confirm/凭据/回查/未知结果保护；结果以 management_status、
   needs_manual、safe_message 和返回 tracking 为准，不自行猜成功。

### D38-11：外部删除

1. DELETE_EXTERNAL 只针对当前单条 tracking 和用户明确选择的安全 scope，不提供列表 checkbox 或批量入口。
2. 确认弹窗逐项说明：删除 Auto Bangumi 中对应番剧或关联 RSS；保留 MiGuOrca 本地 Request、tracking、
   审计和任务；不会删除已下载媒体。不得发送 `file` 字段。
3. 默认焦点在取消，最终按钮为危险样式；取消零请求，进行中防重复。
4. 删除成功/失败/未知均以服务端返回和回查收敛。EXTERNAL_DELETED 仍留在本地列表，可查看历史并返回方案。

### D38-12：兼容、安全与视觉收敛

1. `/app/tracking` 不再以 `QueueView` 作为默认内容。旧 `/app/queue?batch_id=...` 和直接 batch_id 链接只
   用旧 queue 的公开 request_id 进行一次性兼容定位，最终状态/动作仍来自 tracking；不能定位时显示安全提示。
2. 删除 `QueueView` 运行时入口或旧提交表单前，必须用引用搜索、路由、bundle、Vitest 和 Chromium 证明
   新页面已覆盖单番/批量 handoff、提交、retry/recover；兼容后端 endpoint 本阶段不删除。
3. 效果图是空间与层级基线，不是数据契约。Stage 38 允许把全局连接 chip 留给 F-G，但 tracking 页内必须
   有等价的当前会话连接/能力状态和操作入口，并在完成记录写明这一视觉偏差。
4. 1280×720、1440×900、1920×1080 与 200% 缩放下可完成列表、检查器、连接、同步、提交、恢复和危险
   操作；键盘、焦点、aria-live、reduced-motion 和状态非纯颜色表达完整。
5. 敏感 canary 覆盖成功、校验失败、认证失败、timeout、非 JSON、冲突和恢复路径的 DOM、URL、history、
   local/sessionStorage、console、截图/trace；不提交 dist、trace、截图、真实凭据或本地 storage artifact。

## 6. User Stories

### US-303：补齐 F-F generated 管理契约

为 `modifyTrackingItem` 建立 scope 对应的严格 patch 联合 schema，并为 server-computed action 增加安全
`target_scopes`；同步 DTO/serializer/OpenAPI/generated client/handoff/contract tests，证明无外部 ID/URL 泄漏。

### US-304：建立 tracking 页面投影与动作意图核心

基于 generated list/detail/capability/action 类型建立 API-free 纯函数与动作意图模型，覆盖状态总览、
搜索筛选、稳定排序、未知值降级、scope/capability 交集和 opaque idempotency 生命周期。

### US-305：实现正式追番总览与单选列表

把 TrackingView 默认内容替换为状态总览、搜索/筛选和单选列表，接入 listTrackingItems、公开
tracking_id 选择、刷新/错误/空态及效果图 V2 的 58%～64% 列表布局。

### US-306：实现 TrackingInspector 安全详情

创建右侧 sticky 检查器，只消费 getTrackingItemDetail，展示安全方案/外部/操作/复核/审计摘要、更新
“待开发”和本地方案深链；处理快速切换、局部失败、选择消失与 EXTERNAL_ONLY。

### US-307：实现页面级 CredentialSessionDialog

建立 request-scoped 凭据会话和 capability probe，支持 password/API Token 输入、成功后页面内复用、
触发动作上下文返回、取消/切模/离页清理及固定安全错误文案。

### US-308：接入显式 Auto Bangumi 同步与只读降级

接入 syncTrackingItems 的确认、单飞、返回列表/summary/详情收敛；覆盖探测失败、部分能力、UNKNOWN、
同步失败保留旧列表与重新连接/重探测，不把失败误报为空数据。

### US-309：接入本地复核与返回修改方案

实现 REVALIDATE 的 revision-aware 纯本地调用、ready true/false 业务结果、结构化 issues、冲突回查和
`/app/plans?request_id=...` 深链，明确复核失败尚未创建外部订阅。

### US-310：实现显式可靠提交

实现 SUBMIT 的凭据门控、影响说明、确认、最新 revision、单意图 idempotency、进行中互斥、outcome
分流、写后回查和敏感信息保护；导航或连接成功不得自动提交。

### US-311：实现明确失败的幂等重试

只在服务端返回 RETRY 时提供重试；每个新确认意图生成新 key，传输重试复用同 key；覆盖成功、再次
明确失败、revision/idempotency/state 冲突和 transport 结果不明的只读回查。

### US-312：实现结果未知恢复闭环

接入 AUTO、VERIFY_EXTERNAL、MARK_SUCCEEDED、MARK_FAILED，区分无凭据本地恢复、带凭据只读外部核验
和人工二次确认；needs_manual 时保持锁定并禁止盲目 submit/retry/management。

### US-313：实现外部订阅与关联 RSS 修改

按 generated target scopes/capability 展示番剧或 RSS 修改表单，只发送对应严格 patch；复用确认、
revision、幂等、单飞、回查与未知结果恢复，不复制本地方案编辑器或外部原始字段。

### US-314：实现启停与关联 RSS 刷新

接入 SET_ENABLED 和 REFRESH_RSS；启停明确只影响外部订阅，刷新只对当前 tracking 的关联 RSS 生效；
覆盖 capability 降级、目标缺失、部分/明确失败、未知结果及列表/检查器同步。

### US-315：实现逐条外部删除安全闭环

接入 DELETE_EXTERNAL 的 scope 选择和危险确认，固定说明保留本地方案与媒体且请求无 file 字段；覆盖
取消、防重复、成功、失败、部分 RSS/未知恢复和 EXTERNAL_DELETED 本地历史保留。

### US-316：完成兼容、安全、可访问性与视觉收敛

退出 QueueView 默认运行时入口，安全迁移旧 batch_id 定位；覆盖多视口/200%、键盘/焦点/reduced-motion、
效果图正常/复核失败状态、敏感 canary 与无 artifact，并记录全局连接 chip 延后 F-G 的视觉偏差。

### US-317：完成最终门禁、文档归档与 F-G handoff

逐项映射 AC-16～AC-22，运行完整前端、后端非浏览器与真实 Chromium 门禁，更新长期文档和 AGENTS，
归档 Ralph 状态；明确 F-G 只负责设置简化、全局连接/跨页/旧入口最终收敛与发布验收。

## 7. Story 验收摘要

| Story | 最小定向验证 | 独立审核点 |
| --- | --- | --- |
| US-303 | Python DTO/serializer/OpenAPI/generated contract + api:check/typecheck | patch 非 never/any、scope 可判定、无语义扩张 |
| US-304 | tracking projection/action intent Vitest | generated-only、未知值 fail closed、幂等不泄漏 |
| US-305 | TrackingView list Vitest + Chromium | 正式默认页、总览/筛选/选择/错误、无 checkbox |
| US-306 | TrackingInspector Vitest + Chromium | 安全详情、请求代际、EXTERNAL_ONLY、方案深链 |
| US-307 | credential session Vitest + Chromium | 页面内存、探测、取消/切模/卸载清理、无自动动作 |
| US-308 | sync state Vitest + Chromium | 显式确认、旧内容保留、能力降级、响应收敛 |
| US-309 | revalidate Vitest + Chromium | 无凭据/无外部调用、业务失败、revision 冲突、深链 |
| US-310 | submit Vitest + Chromium | confirm、同 key、outcome 分流、未知先回查 |
| US-311 | retry Vitest + Chromium | 仅明确失败、新意图/传输重试 key 边界、冲突 |
| US-312 | recovery Vitest + Chromium | AUTO/VERIFY/人工分离、needs_manual、冲突动作锁定 |
| US-313 | generated modify Vitest + Chromium | scope/patch/capability、无手写 DTO、结果未知 |
| US-314 | enable/refresh Vitest + Chromium | file=false 后端边界不变、单 RSS scope、降级/恢复 |
| US-315 | delete Vitest + Chromium | 单条危险确认、本地与媒体保留、无 file/批量删除 |
| US-316 | 引用/安全/a11y/视口 + Chromium | QueueView 退出、旧定位、效果图偏差、敏感面 |
| US-317 | 完整门禁与人工视觉对照 | 所有 story、归档、F-G handoff、工作区一致 |

每个 Ralph 迭代只完成一个 story。每次恰好运行最多 3 个 stories；完成 US-305、US-308、US-311、
US-314、US-317 后必须停止并由主 Agent 独立审核。普通 story 只跑定向检查；完整前端、后端非浏览器
和 Chromium 套件只在 US-317 运行一次。预计 15 个开发迭代；任一批最多 2 个聚焦修复提交，超过后
停止并报告，不做无界循环。

## 8. 完整验收标准

1. `/app/tracking` 默认显示正式 tracking 总览、单选列表和检查器，不再默认挂载旧 QueueView。
2. 保存确认/方案深链的真实 tracking_id 可定位、高亮、聚焦待提交项，且不会自动创建外部订阅。
3. 本地列表无需凭据可读；外部 probe/sync/submit/retry/verify/management 只有用户显式操作才访问外部。
4. 凭据只在当前 tracking 页面会话内存及单次 POST body，离页/刷新/取消/切模/清除后消失。
5. 动作只来自服务端 available_actions + target_scopes + 本次 capability；未知/不支持/失败时只读降级。
6. revalidate 不带凭据；失败明确尚未创建外部订阅，并可深链返回真实本地方案。
7. submit/retry/recover/management 的 revision、confirm、idempotency、并发与结果未知语义符合 Stage 32 handoff。
8. 3.1.18 password 下支持单项提交、重试、恢复、修改、启停、关联 RSS 刷新和外部删除；其他模式按能力降级。
9. 删除无 file 字段、无批量入口，且明确并实际保留本地 Request、tracking、审计和已下载媒体。
10. 1280×720、1440×900、1920×1080 与 200% 缩放可完成关键旅程；键盘/焦点/读屏/reduced-motion 合格。
11. 敏感信息在 DOM、URL、history、storage、console、通知、截图/trace/sourcemap 均不可见；无相关 artifact 入库。
12. 自动化全离线，既不访问真实外部服务，也不以 mock-only 静态页面冒充正式功能。

## 9. 最终质量门禁

```bash
uv run python -m compileall -q src tests
uv run ruff check src tests
uv run migu-orca-openapi --check
uv run pytest -q -m "not browser"
cd frontend
npm run api:check
npm run typecheck
npm run lint
npm run test:unit -- --run
npm run build
cd ..
uv run pytest tests/browser/ -q
git diff --check
```

所有 UI story 必须按 `dev-browser` skill 使用真实 Chromium；浏览器测试只用项目 fake/route mock，不连接
真实 Auto Bangumi。失败后先跑最小失败用例，无代码变化不得重复完整门禁。

## 10. 回退与完成定义

1. US-303 契约补口保持加法兼容；旧客户端可忽略 target_scopes，后端 endpoint/状态/写语义不变。
2. 正式 TrackingView 可按提交回退；旧 QueueView/后端 queue endpoint 在本阶段只退出默认运行时，不删除
   后端兼容契约，确保 F-G 最终收敛前仍可回滚。
3. 每个写动作使用服务端回传 tracking 收敛；回退不能清除 operation、tracking、mapping、Request 或媒体。
4. US-303～US-317 全部 `passes=true`、五轮独立审核无阻断、完整门禁通过后才标记完成并归档。
5. Ralph 开发/修复 Agent 不 push、不创建 PR、不合并、不清理分支；最终推送合并只由用户授权的 Agent C 执行。

## 11. F-G handoff

- F-G 只负责 Settings 简化、移除旧 Settings/Queue 业务提交入口、全局非敏感连接状态、跨页导航徽标、
  旧路由最终收敛、完整用户文档与候选发布 Gate 5。
- “已更新集数”继续属于 BL-020，不进入 F-G；移动端、服务端批量现场恢复与真实 LLM provider 继续独立评审。
- 若 Stage 38 实现暴露新的后端语义缺口，必须停下评审，不允许前端猜测或手写临时 DTO。
