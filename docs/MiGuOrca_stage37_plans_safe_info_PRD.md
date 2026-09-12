# MiGuOrca Stage 37 PRD：追番方案与安全信息

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| Stage | 37 |
| 工作包 | F-E：追番方案 |
| Backlog | BL-026 |
| 状态 | 已完成（2026-09-13） |
| 目标分支 | `ralph/stage37-plans-safe-info` |
| Ralph stories | US-294～US-302 |
| 实时基线 | `origin/main` 合并提交 `ee8acb7`（Stage 36 已合入） |
| 前置 | Stage 32 generated contract handoff v1、Stage 34 共享审核核心、Stage 35/36 添加旅程 |

## 2. 背景与阶段判断

Stage 35、36 已把单番和批量添加收敛到真实 MiKan 合集选择、服务端权威草案编辑及原子保存确认；
Stage 37 应接管保存之后的本地方案体验。当前 `/app/plans` 仍挂载 Stage 27 的兼容 `RequestsView`：
列表偏技术化，详情维护另一套修改表单，缺少真正的“全部信息”、复制再用和清晰的 tracking 入口。

后端已有 `listRequests`、`getRequestDetail`、`modifyRequest`、`getRequestSafeInfo` 和
`listTrackingItems`。其中 Request 列表摘要尚缺效果规格要求的季度与修改时间，历史
`candidate_subtitle_groups` 还是可能携带完整 RSS URL 的宽松字典。为避免 N+1 详情请求并关闭浏览器
响应/trace 泄漏面，本阶段为现有摘要追加 `season`、`updated_at`，同时把候选字幕组收紧为无 URL 的
严格公开摘要并同步 OpenAPI/generated 类型；不新增端点、不改变状态机，也不引入外部写动作。

本阶段只完成 F-E。`listTrackingItems` 仅用于按公开 `request_id` 精确关联本地 tracking 投影与导航；
正式 tracking 总览、临时凭据、外部同步、复核、提交、恢复和 Auto Bangumi 管理仍由 F-F 独占。

## 3. 目标

1. 把 `/app/plans` 建成面向普通用户的宽松列表—详情页面，默认按最近修改排序。
2. 列表展示标题、季度、字幕组、方案状态、修改时间和精确关联的追番状态，不暴露技术字段。
3. 标题搜索和方案状态筛选不丢失合法选择；刷新可由公开 `request_id` 恢复当前详情。
4. 详情复用 `AnimeDraftEditor` 的展示/编辑字段，删除独立的第二套 saved Request 修改表单。
5. 只通过 generated `modifyRequest` 修改已保存方案，成功后回查服务端详情与列表。
6. 用真实 `getRequestSafeInfo` 实现“全部信息”弹窗，完整展示安全白名单和历史摘要。
7. 已精确建立 tracking 的方案提供“前往追番管理”，不推导或伪造 tracking ID。
8. “复制再用”以一次性内存 handoff 返回 `/app/add`，仍要求用户明确选择真实 MiKan 合集并生成新草案。
9. 覆盖键盘/焦点、桌面多视口、200% 缩放、失败恢复和敏感信息回归。

## 4. 非目标

1. 不实现 F-F 正式追番管理总览、列表、检查器、凭据会话或任何外部动作。
2. 不调用 `syncTrackingItems`、`revalidateTrackingItem`、`submitTrackingItem`、retry/recover 或
   MODIFY/SET_ENABLED/REFRESH_RSS/DELETE_EXTERNAL 管理端点。
3. 不实现 F-G 设置简化、连接诊断、跨页发布收尾或最终 Gate 5。
4. 除 `listRequests` 安全摘要追加 `season`/`updated_at` 并收紧候选字幕组公开字段外，不修改
   OpenAPI、generated client、Python 领域模型、持久化 schema 或既有业务语义；不手写 API DTO。
5. 不把 Request 状态等同于 tracking/外部状态，不把旧 queue 当作追番状态来源。
6. 不复制 Request snapshot、candidate context、draft capability、RSS URL 或幂等键；不自动保存、确认
   或提交复制出来的方案。
7. 不访问真实 MiKan、Auto Bangumi 或 qBittorrent，不创建外部订阅或下载任务。
8. 不开发移动端，不用种子数、RSS 数量或文件名猜测“已更新集数”。

## 5. 冻结决策

### D37-01：数据源与状态所有权

1. `listRequests` 是方案列表、方案状态和最近修改时间的唯一来源。
2. `getRequestDetail` 是当前方案可编辑快照的唯一来源；修改成功后必须重新读取详情。
3. `getRequestSafeInfo` 是“全部信息”的唯一来源；弹窗不得从详情快照拼装或补猜字段。
4. `listTrackingItems(sort=updated_at)` 只提供本地 tracking 安全投影。客户端以非空且完全相等的
   `request_id` 建立至多一个关联；重复、缺失或无效关联一律降级为无链接状态。
5. 页面只维护一个选中 `request_id`，列表、详情、弹窗和复制入口不得各自保存平行 Request 快照。

### D37-02：最小 Request 列表契约补口

`RequestSummaryDTO` 追加可空 `season` 与 `updated_at`：它们必须由已保存 Request 的现有公开字段直接
序列化，缺失时返回 `null`，不得读取文件系统 mtime、绝对路径或 tracking/外部状态。同时把
`candidate_subtitle_groups` 从宽松字典改为严格的字幕组名称与资源计数摘要，删除 `rss_url` 等无关字段。
OpenAPI 示例、Python DTO/serializer、generated TypeScript 和 contract tests 必须同步；端点、状态码和
业务语义不变。

### D37-03：列表、排序与筛选

1. 默认按合法 `updated_at` 倒序；时间缺失/无效的项稳定置后并保留服务端相对顺序。
2. 标题搜索只覆盖公开标题、字幕组等用户可理解字段；不把 `request_id` 作为默认搜索
   或卡片主内容，但合法公开 `request_id` 仍可用于 URL 详情深链。
3. 状态筛选只使用 Request 方案状态。tracking 状态是单独标签，不参与方案状态筛选。
4. 列表不显示外部运行按钮、available actions、endpoint 或原始状态对象。
5. tracking 投影加载失败不得阻断方案列表/详情；显示固定“追番状态暂不可用”并允许局部重试。

### D37-04：详情与已保存方案修改

1. `AnimeDraftEditor` 保持受控展示组件：通过明确 mode/文案/能力参数支持 draft 与 saved Request，
   不把 saved Request transport 塞进 `useDraftSession`，也不把 draft revision 语义套到已保存方案。
2. `RequestDetailPanel` 负责 generated `modifyRequest` 调用、进行中互斥、安全错误、成功回查和列表刷新。
3. saved 模式只提交 generated body 允许的修改字段；空 patch 阻断。失败保留用户输入，并允许重试或
   恢复最新服务端值；不得显示原始响应。
4. PENDING_CONFIRM/ACCEPTED/CANCELLED 的既有本地生命周期语义不扩张。兼容 accept/cancel/delete
   若保留，必须明确标为本地方案动作、按状态显示并继续确认；不得伪装成外部订阅动作。

### D37-05：真实 SafeInfoDialog

1. 弹窗打开后按当前 `request_id` 调用 generated `getRequestSafeInfo`；快速切换/关闭后的旧响应不得
   覆盖当前弹窗。
2. 逐字段展示标题/别名、季度与证据、真实 MiKan 合集标题和公开编号、字幕组与过滤规则、相对
   storage profile/安全目录名、资源数量与脱敏文件名摘要、总集数、Request 状态、历史摘要和安全 AB 状态。
3. `updated_episode` 始终展示“待开发”，不得用资源数或 RSS 数量替代。
4. 加载、空、失败、重试均在弹窗内完成；失败只使用固定中文文案。
5. 使用共享弹窗原语，具备语义标题、焦点圈定、Escape/遮罩关闭、关闭后焦点恢复及 reduced-motion。

### D37-06：方案与外部管理职责分离

1. 追番状态只渲染 generated tracking `status_label`；客户端不根据 Request 状态猜测。
2. 只有唯一精确关联且 `tracking_id` 合法时显示“前往追番管理”，导航到
   `/app/tracking?tracking_id=...`；否则显示“未进入追番管理”或安全降级文案。
3. `/app/plans` 不读取/展示 `available_actions`，不收集 AB 凭据，不执行任何同步或写动作。
4. `EXTERNAL_ONLY` 等无本地 Request 的 tracking 项不得伪造为方案列表项。

### D37-07：复制再用的一次性内存 handoff

1. “复制再用”只能从已成功读取的 safe-info 白名单建立 handoff；内容限制为公开标题/真实 MiKan
   `bangumi_id` 和用户可编辑配置建议，不含 Request snapshot、`request_id`、URL、资源明细、历史、
   tracking、candidate/draft capability 或幂等键。
2. handoff 只存在当前 SPA 进程内存，不写 URL、history state、Pinia 持久化、local/sessionStorage。
3. `/app/add` 一次性消费并清除 handoff，显示“来自已有方案”的安全摘要；刷新后自然失效并提示重新选择。
4. 用户仍必须显式发起真实搜索、选择真实 MiKan 合集、生成新的服务端草案；配置建议只能在新草案
   生成后由用户确认应用。导航本身不得自动调用创建、保存确认或外部提交。

### D37-08：选择、加载与并发恢复

1. URL 只保存公开 `request_id`；非法、重复或不存在的 query 进入安全未选择/未找到状态，不回显原值。
2. 列表刷新保留仍存在的选择；所选项删除/消失后清除 query 并把焦点移回列表标题或下一合法项。
3. 详情、safe-info 与 tracking 三类请求独立加载和失败；使用请求序号或取消机制丢弃旧响应。
4. 修改、删除等本地写动作进行中时锁定冲突动作，结果未知时不得凭客户端猜测成功，先回查详情/列表。

### D37-09：安全、视觉与兼容

1. 采用交互规格的宽松列表—详情布局：桌面列表约 34%～40%，详情约 60%～66%；窄桌面/200% 可
   纵向排列，列表筛选、详情动作和弹窗均可达。
2. 当前行使用背景、边界/指示条和 `aria-current` 等价语义，不只依赖颜色；键盘可完成筛选、选择、
   修改、全部信息、复制再用和管理跳转。
3. 完整 URL、RSS、magnet、endpoint、凭据、Cookie、Authorization、原始响应、candidate context、
   draft/幂等键和本地绝对路径不得进入 DOM、URL、storage、日志、通知、截图、trace 或 sourcemap。
4. `/app/requests?request_id=...` 等旧入口继续安全重定向；移除旧 Requests 兼容 UI 前必须有引用搜索、
   bundle、路由及真实 Chromium 证据。

## 6. User Stories

### US-294：补齐并收紧 Request 列表安全展示契约

为现有 `RequestSummaryDTO` 追加可空 `season`、`updated_at`，并把候选字幕组改为无 RSS URL 的严格
公开摘要；同步 serializer、schema、OpenAPI、generated TypeScript、示例和 contract tests。

### US-295：建立追番方案列表投影与状态核心

建立 API-free 类型/纯函数层，从 generated `listRequests` 和 `listTrackingItems` 生成方案行、稳定最近修改
排序、标题/状态筛选及精确 tracking 关联；覆盖重复/缺失关联、无效时间、未知状态和安全降级。

### US-296：实现宽松列表—详情页面骨架

把 `/app/plans` 重构为桌面列表—详情布局，接入列表/追番投影的独立加载、错误和重试，使用公开
`request_id` 维持页内选择；展示规定字段并移除复制 request_id 等技术化主界面行为。

### US-297：实现真实 SafeInfoDialog

创建只消费 generated `getRequestSafeInfo` 的全部信息弹窗，逐字段呈现安全白名单、历史与明确的
“已更新集数待开发”，处理快速切换、弹窗内失败重试、焦点圈定与关闭恢复。

### US-298：扩展共享编辑器的 saved Request 模式

以受控 props/slots/文案扩展 `AnimeDraftEditor`，让 draft 与 saved Request 共用展示和编辑字段；保持
draft 现有 revision/重试行为，saved 模式不依赖 `useDraftSession` 或 preview-modify transport。

### US-299：接入方案详情、修改与本地生命周期

重构 `RequestDetailPanel` 使用共享编辑器和 generated `modifyRequest`，展示修改时间、历史摘要、全部信息
与精确 tracking 入口；保留必要的本地 accept/cancel/delete 兼容并明确边界，失败后安全回查/恢复。

### US-300：实现复制再用内存 handoff

从 safe-info 创建最小一次性内存 handoff，导航 `/app/add` 后预填安全起点和配置建议；要求用户重新
执行真实搜索/合集选择并在新草案上显式应用，覆盖消费清理、刷新失效和无自动保存/提交。

### US-301：完成安全、可访问性与兼容收敛

覆盖列表—详情和弹窗在桌面多视口、200% 缩放、键盘、焦点、reduced-motion 下的行为；验证敏感值
注入不进入 DOM/URL/storage/console/trace，删除无调用的旧方案 UI/表单并保留旧路由重定向。

### US-302：完成最终门禁、文档归档与 F-F handoff

运行完整前端、后端非浏览器和真实 Chromium 门禁，映射 F-E 验收与视觉偏差，归档 Ralph 状态并明确
F-F 正式 tracking 管理和 F-G 设置/发布收尾的剩余职责。

## 7. Story 验收摘要

| Story | 最小定向验证 | 独立审核点 |
| --- | --- | --- |
| US-294 | Request DTO/serializer/OpenAPI contract + api:check/typecheck | 仅新增两个公开字段、确定性与无泄漏 |
| US-295 | 方案投影/排序/关联 Vitest + typecheck | generated 类型、精确关联、稳定降级 |
| US-296 | PlansView 组件测试 + 定向 Chromium | 宽松双栏、选择/筛选、独立失败 |
| US-297 | SafeInfoDialog 组件测试 + 定向 Chromium | 白名单完整性、旧响应、焦点与错误安全 |
| US-298 | AnimeDraftEditor 两种模式 Vitest + 定向 Chromium | 共享展示、transport 隔离、draft 无回归 |
| US-299 | 详情/修改/本地动作 Vitest + 定向 Chromium | generated modify、回查、无外部动作 |
| US-300 | handoff/add 旅程 Vitest + 定向 Chromium | 一次性内存、显式合集选择、无自动提交 |
| US-301 | 引用搜索、安全/a11y/视口测试 + 定向 Chromium | 敏感面、200%、旧路由与旧实现退出 |
| US-302 | 完整门禁与人工视觉对照 | 归档、偏差、F-F/F-G handoff |

每个 Ralph 迭代只完成一个 story。每次最多运行 3 个 stories；完成 US-296、US-299、US-302 后必须
停止并进行独立审核。普通 story 只运行定向检查；完整前端、后端非浏览器和 Chromium 套件只在
US-302 最终收尾运行一次，除非代码变化后需要复验具体失败。

## 8. 完整验收标准

1. `/app/plans` 默认按 Request `updated_at` 最近优先，缺失时间稳定置后；支持标题搜索和方案状态筛选。
2. 每行只展示标题、季度、字幕组、方案状态、修改时间与安全 tracking 状态/入口，不混入外部动作。
3. 详情只有一个共享编辑表面；saved 修改只调用 generated `modifyRequest`，成功后服务端回查。
4. `SafeInfoDialog` 只调用 `getRequestSafeInfo`，完整展示安全白名单，已更新集数明确为待开发。
5. tracking 入口只来自按 `request_id` 的唯一精确关联；缺失、重复、失败均不推导 ID。
6. 复制再用只使用一次性内存白名单，用户仍选择真实 MiKan 合集；刷新失效且不自动保存/提交。
7. `/app/plans` 不调用任何外部同步、复核、提交、恢复或管理端点，不收集 AB 凭据。
8. 1280×720、1440×900、1920×1080 与 200% 缩放可完成列表、详情、修改、弹窗和复制旅程。
9. 键盘/焦点/reduced-motion 与加载、空、局部失败、结果未知恢复均有 Vitest/Chromium 证据。
10. 敏感信息检查覆盖 DOM、URL、storage、console、trace/screenshot；无 dist、trace 或截图产物入库。

## 9. 最终质量门禁

```bash
cd frontend
npm run api:check
npm run typecheck
npm run lint
npm run test:unit -- --run
npm run build
cd ..
uv run python -m compileall -q src tests
uv run ruff check src tests
uv run pytest -q -m "not browser"
uv run pytest tests/browser/ -q
git diff --check
```

真实 Chromium 验证必须按 `dev-browser` skill 执行；fake transport 不得访问真实外部服务。失败后先跑
最小失败用例，无代码变化不得重复运行同一完整门禁。

## 10. 回退与完成定义

1. Stage 37 的列表摘要新增字段可空；候选字幕组只删除无消费者的 URL 并保留公开名称/计数，前端可
   独立回退到 Stage 36 兼容页。
2. 删除旧组件/表单前必须有引用搜索、bundle、路由与真实 Chromium 证据。
3. US-294～US-302 全部 `passes=true`、代码独立审核无阻断、完整门禁通过后，才可标记完成并归档。
4. 合并、push、PR 和远端/旧分支清理仍需用户单独授权；Ralph Agent 不得自行执行。

## 11. Stage 37 完成记录

- US-294～US-302 全部通过；实现列表—详情、SafeInfo 白名单、saved Request 修改、一次性内存复制再用、响应式/键盘/敏感信息收敛。
- 最终门禁：`api:check`、前端 typecheck/lint/Vitest/build、Python compileall/Ruff/非浏览器 pytest 与完整真实 Chromium 均通过；具体命令和计数记录在 `scripts/ralph/progress.txt`。
- 视觉对照：宽松列表—详情层级、弹窗安全摘要、复制再用显式搜索/合集选择/草案生成路径与交互规格一致；未发现阻断性偏差。
- 本阶段未实现正式 tracking 管理、外部同步/复核/提交/恢复或 Auto Bangumi 管理动作，也未扩展设置发布流程。
- Ralph 归档：`scripts/ralph/archive/2026-09-13-stage37-plans-safe-info/`。

## 12. 后续 handoff

- F-F：正式追番管理总览、单选列表、检查器、页面级临时凭据、同步、复核、外部提交、结果未知恢复
  及 MODIFY/SET_ENABLED/REFRESH_RSS/DELETE_EXTERNAL 管理动作。
- F-G：设置简化、连接诊断、旧兼容入口最终收敛、跨页 Gate 5 和候选发布包。
- 若 F-F 实现后仍存在较大跨流程或视觉风险，再单列最终发布 Stage；本阶段不预占其编号。
