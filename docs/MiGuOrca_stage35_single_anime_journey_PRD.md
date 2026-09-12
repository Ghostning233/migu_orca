# MiGuOrca Stage 35 PRD：单番添加完整旅程

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| Stage | 35 |
| 工作包 | F-C：单番添加 |
| Backlog | BL-026 |
| 状态 | 已完成并归档 |
| 目标分支 | `ralph/stage35-single-anime-journey` |
| Ralph stories | US-275～US-283 |
| 实时基线 | `origin/main` 合并提交 `cee2452`（Stage 34 已合入） |
| 前置 | Stage 34 共享审核核心、Stage 32 前端契约 handoff v1 |

## 2. 背景与阶段判断

Stage 34 已交付单番/批量共享的模式输入、真实 MiKan 候选集合、`AnimeDraftEditor`、
`useDraftSession`、revision 重算和失败恢复；现有单番仍由 `DraftPreviewPanel` 薄适配层执行旧
`preview-save`，成功后进入追番方案，而不是产品冻结的三步“保存并确认 → 追番管理待提交”。

Stage 35 只完成 F-C：把 `/app/add` 的默认单番模式收敛为名称输入、人工选择真实合集、审核并
保存确认三个用户可见步骤，正式消费 `confirmRequestSave`，并把成功 handoff 定位到真实 tracking
记录。它不扩展批量流程、追番方案或正式追番管理动作。

契约存在一个必须显式处理的恢复分支：save-confirm 正常成功直接返回 `handoff.tracking_id`；若
Request 已保存但确认失败，409 `save_confirm_failed` 只返回公开 `request_id` 和
`ACCEPT_SAVED_REQUEST`。前端重试旧 `acceptRequest` 后不得推导 tracking ID，而应通过一次只读
`listTrackingItems` 精确匹配同一 `request_id`，取得服务端公开的真实 `tracking_id`。解析失败只影响
定位，不得重复保存或重复确认。

## 3. 目标

1. `/app/add` 默认单番模式提供清晰、可返回的三步旅程，并保持批量模式现有能力不变。
2. 搜索词、候选、草案和步骤状态仅存在当前页面实例内存；用户必须选择真实 MiKan 合集。
3. 第三步复用 Stage 34 唯一 `AnimeDraftEditor`/`useDraftSession`，不复制表单或业务规则。
4. 唯一主操作为“保存并确认”，一次调用 generated `confirmRequestSave` 完成持久化与确认。
5. 一次用户操作生成一个内存幂等键；传输重试复用该键，不创建第二个 Request/tracking。
6. 保存成功、确认失败时保留公开 `request_id`，提供只重试确认的恢复流程，不要求重新搜索。
7. 成功后进入 `/app/tracking?tracking_id=...`，读取真实 tracking 详情并定位、聚焦待提交条目。
8. F-C 接管完成后移除单番 `DraftPreviewPanel` 的 `preview-save` 兼容保存路径。
9. 覆盖键盘、焦点、离开保护、桌面多视口和敏感信息不泄漏的真实 Chromium 验收。

## 4. 非目标

1. 不实现 F-D 批量 1/12/36 双栏审核、批量 save-confirm、部分成功或批量离开保护。
2. 不实现 F-E 追番方案重构、`SafeInfoDialog` 或 `getRequestSafeInfo`；未保存草案不得拼接“全部信息”。
3. 不实现 F-F tracking 列表、筛选、同步、复核、提交、重试、恢复、修改、启停、刷新或外部删除。
4. `/app/tracking` 只增加 F-C handoff 的真实只读落点；`batch_id` 仍挂载现有 `QueueView` 兼容流程。
5. 不修改 OpenAPI、generated client、Flask API 或后端领域语义，不手写 API DTO。
6. 不访问真实 MiKan、Auto Bangumi 或 qBittorrent，不创建外部订阅或下载任务。
7. 不持久化未保存现场，不新增跨刷新恢复，不开发移动端，不猜测“已更新集数”。
8. 不顺带清理批量 `BatchDraftPreviewPanel` 的兼容保存/接受路径，该路径归 F-D。

## 5. 冻结决策

### D35-01：三个用户可见步骤

单番旅程固定为：

1. 输入名称并搜索；
2. 人工选择真实 MiKan 合集；
3. 审核方案并执行“保存并确认”。

外部提交不是第四步。本阶段成功只建立本地 `PENDING_SUBMIT` tracking，绝不自动调用 Auto
Bangumi。步骤状态由 `/app/add` route-local 状态机持有，URL 不携带搜索词、候选、draft 或步骤号。

### D35-02：搜索、候选与返回语义

1. 初始焦点在单番名称输入；空白输入不可提交，搜索期间防重复请求并保留原输入。
2. 成功后折叠输入摘要并把焦点移动到候选标题/首项；零结果和失败原位展示，提供修改与重试。
3. 即使只有一个候选也不能自动选择；季数冲突和证据不足继续使用既有明确确认规则。
4. 从第三步“重新选择合集”返回候选；从候选“修改搜索”返回输入。会丢弃已编辑草案时必须先说明
   影响并由用户确认，不能静默消费或替换 draft capability。

### D35-03：审核状态与确认阻断

第三步只组合 Stage 34 的共享编辑器/会话。服务端成功重算的快照和 revision 是唯一事实；字幕组
重算中、会话 dirty、季数未确认、无有效资源、字段校验失败或草案已失效时，“保存并确认”必须
禁用并显示可操作原因。普通修改失败保留上次一致快照和未应用输入；失效错误要求重新选择/生成。

### D35-04：原子保存确认与幂等

1. 用户点击主操作后先完成共享编辑器待应用修改，再锁定当前草案写操作。
2. 请求只发送 generated `confirmRequestSave` 允许的 `draft_id`、`base_revision`、
   `idempotency_key` 和现有相对 storage profile；不得回传完整 Request。
3. 幂等键用 Web Crypto 或等价浏览器安全随机源生成，只存在组件内存和单次 POST body；同一次传输
   重试必须复用，用户修改方案或开始新草案后才生成新键。
4. 响应未知/网络失败不得自动生成新键重发。页面保留本次操作并提供明确“重试本次保存确认”。
5. `draft_revision_conflict`/expired/evicted/replayed、`draft_reserved`、idempotency conflict 和普通
   网络失败分别使用固定中文状态，不渲染原始 `error_data`。

### D35-05：已保存但确认失败

仅当统一 transport 返回 `error_type=save_confirm_failed`，且白名单解析得到
`outcome=SAVED_CONFIRM_FAILED`、合法公开 `request_id`、
`retry_action=ACCEPT_SAVED_REQUEST` 时，页面进入“已保存，待重试确认”状态：

1. 立即使旧 draft capability 和旧保存幂等键不可再次用于保存；不得回到搜索或重做 save-confirm。
2. “重试确认”只调用 generated `acceptRequest`，使用公开 `request_id` 和相对 storage profile。
3. accept 成功后调用一次 `listTrackingItems`，只在返回的安全投影中精确匹配同一 `request_id`，取得
   服务端返回的 `tracking_id`；不得在浏览器推导/哈希 tracking ID。
4. accept 响应未知或返回可能表示已接受的状态冲突时，必须先用同一只读匹配核验；找到 tracking
   即视为确认已完成，未找到且核验成功才允许用户重试 accept。核验本身失败时不得盲目重复确认。
5. 定位解析失败时保留“方案已确认”的终态，只允许重试定位或进入不带定位参数的追番管理；不得
   再调用 accept/save-confirm。未经白名单验证的错误详情一律按普通安全失败处理。

### D35-06：tracking handoff 与兼容路由

1. 正常成功使用 `router.replace` 和 `handoff.tracking_id`，避免浏览器返回已消费草案；
   `tracking_ready=false` 仍保留已确认事实，并展示服务端固定 safe message 的本地等价文案，打开
   详情触发后端既有补偿，绝不重复保存。
2. tracking 路由白名单扩展为公开 `tracking_id` 与既有 `batch_id`。两者同时出现时拒绝歧义输入，
   不允许未知 query、数组、路径片段或敏感值通过。
3. `tracking_id` 模式只调用 generated `getTrackingItemDetail`，展示顶层安全摘要、状态、有效资源数、
   总集数和“已更新集数待开发”，并把标题/容器聚焦和高亮；不得渲染响应内 `safe_info`、外部映射、
   审计详情或任何 `available_actions` 按钮。
4. `batch_id` 模式继续使用现有 QueueView；旧 `/app/queue` 重定向和批量提交兼容不回归。
5. 刷新带合法 `tracking_id` 的页面能恢复同一只读落点；加载失败保留标识和重试入口。

### D35-07：单番旧路径退出

F-C 完成后，`WorkbenchView` 不再通过 `DraftPreviewPanel` 执行 `previewSaveRequest` 或跳转
`/app/plans?request_id=...`。可删除 `DraftPreviewPanel`，或仅在仍有非单番真实调用方时保留无保存
能力的薄展示包装；代码搜索与依赖测试必须证明单番新旅程只存在一个保存实现。批量兼容路径不动。

### D35-08：离开、安全与可访问性

1. 搜索结果本身不触发离开保护；已经生成且尚未确认的草案、未应用编辑或进行中的保存操作触发。
2. 应用内导航使用共享确认弹窗，默认焦点为“留在此页”；刷新/关闭使用原生 `beforeunload`。
3. 用户确认离开后清除 draft、revision、idempotency key、候选上下文和临时状态；保存确认成功或
   已保存待重试确认状态不得被误报为“未保存草案”。
4. 搜索、候选、审核、错误恢复和 handoff 均有明确标题、状态文本、键盘顺序与焦点目标。
5. `draft_id`、revision、idempotency key、candidate context、RSS URL、magnet、endpoint、凭据、
   原始响应和绝对路径不得进入 URL、DOM、storage、日志、通知、截图或 trace。

## 6. User Stories

### US-275：冻结单番旅程状态与 generated 契约边界

建立可独立测试的单番 journey/save-confirm 状态模型和 generated 类型别名，覆盖三个步骤、草案能力、
确认中、已保存待确认、已确认待定位与完成状态；定义合法状态迁移、主操作阻断、幂等键生命周期和
安全错误分类。不得调用 API、手写 DTO 或修改共享编辑器。

### US-276：实现输入与候选两步旅程

把现有单番搜索接入明确的第一/第二步：默认聚焦、加载防重、输入摘要、零结果/失败重试、人工候选
选择和返回修改搜索。复用 `AnimeModeSwitch`、`AnimeTitleInput`、`CandidateCollectionList`，保持批量
模式现状和候选季数规则，不生成自动选择。

### US-277：接入第三步共享审核与返回保护

选择候选后进入第三步并复用 `AnimeDraftEditor`/`useDraftSession`；显示步骤标题、审核摘要、阻断原因、
重新选择合集和修改搜索入口。返回会丢弃草案/编辑时显式确认并正确释放本地状态；本 story 不调用
任何保存端点。

> 第一开发批次到此停止。开发 Agent 运行 Ralph 最多 3 次，只完成 US-275～US-277，然后交由独立
> 审核；不得继续 US-278。

### US-278：接入原子保存并确认

实现单番保存宿主，应用最新编辑后只调用 `confirmRequestSave`；建立一次用户操作一个幂等键、同次
传输重试复用、操作锁和成功 handoff。成功清除 draft capability，不调用 preview-save/accept，不
创建外部订阅；普通失败与草案失效按冻结状态恢复。

### US-279：实现已保存确认失败恢复

严格白名单解析 `save_confirm_failed`，保留公开 request ID 并提供“重试确认”；只调用
`acceptRequest`，成功后通过 `listTrackingItems` 精确匹配 request ID 解析真实 tracking ID。accept
响应未知/状态冲突时先只读核验再决定是否允许重试；确认成功后即使定位失败也禁止再次确认或保存，
只允许重试定位/打开追番管理。

### US-280：实现 tracking 只读 handoff 落点

扩展 route catalog/sanitizer 支持互斥的 `tracking_id`/`batch_id`；为 tracking ID 提供真实详情读取、
待提交摘要、聚焦、高亮、刷新恢复和安全失败重试。保留 batch QueueView 兼容；不渲染 safe-info、
available actions 或任何正式管理功能。

> 第二开发批次到此停止并独立审核；审核通过前不得继续兼容清理与全局离开保护。

### US-281：完成单番离开保护与无障碍状态

对未确认草案、未应用修改和进行中操作接入应用内确认与 `beforeunload`；确认离开清理内存状态，
完成/已保存待确认状态不误触发。补齐三步焦点移动、错误聚焦、键盘返回、reduced-motion 和桌面
多视口行为。

### US-282：移除单番旧保存兼容路径并完成安全回归

让 `WorkbenchView` 完全退出 `DraftPreviewPanel` 的 preview-save/跳转 plans 路径，删除无调用代码或
收敛为不含保存能力的包装；批量适配层保持不变。补充依赖守卫、路由 query 清洗、敏感 canary、
刷新恢复和旧单番/批量兼容回归。

### US-283：完成最终门禁、文档归档与后续 handoff

执行一次完整前端门禁、必要后端非浏览器回归和完整真实 Chromium；核对三步旅程、原子确认、恢复、
tracking 落点、旧路径退出、契约漂移和泄漏矩阵。同步文档与 Ralph 归档，明确 F-D 继续复用共享核心、
F-E 独占 SafeInfo，且 F-F 才能实现正式 tracking 管理动作。

## 7. 验收矩阵

| 风险 | 必须证明 |
| --- | --- |
| 伪三步/自动选择 | 用户只见三个步骤，必须人工选择真实合集，外部提交不是第四步 |
| 状态丢失 | 返回修改搜索/重选合集按规则保留或确认丢弃；失败不会无故要求重新搜索 |
| 双重保存 | 新单番只调用 confirmRequestSave；无 preview-save → accept 串联 |
| 幂等失效 | 同次重试复用键；未知结果不换键盲重试；新草案才产生新键 |
| 保存后确认失败 | 只重试 accept；成功后即使定位失败也不再次保存/确认 |
| tracking 身份猜测 | 正常用 handoff ID，恢复用 list 精确解析；浏览器不推导 tracking ID |
| F-F 越界 | tracking 落点只读且无同步、提交、恢复和管理动作 |
| 兼容回归 | batch_id QueueView、批量适配层和旧路由继续可用 |
| SafeInfo 越界 | 未调用 getRequestSafeInfo，不渲染 tracking detail.safe_info |
| 安全 | 敏感值和 opaque capability 不进入 URL、DOM、storage、日志、截图或 trace |

## 8. 迭代与成本控制

1. 每个 Ralph 迭代只完成一个最高优先级 story。
2. 每次严格只运行 3 个迭代：US-275～US-277、US-278～US-280、US-281～US-283；到批次边界
   必须停止并交由独立审核，审核通过后才进入下一批。
3. US-275～US-282 只运行受影响 Vitest、typecheck、lint 和少量相关 Chromium；UI story 必须使用
   项目 `dev-browser` skill 在真实 Chromium 验证。
4. 只有 US-283 运行一次完整前端与完整 Chromium 门禁及必要后端非浏览器回归；无代码变化不得
   重复全套。
5. 测试失败先运行最小失败用例；预计 9 个实现迭代，额外修复最多 2 轮，超过 11 轮停止报告。
6. 不重复安装依赖，不连接外部服务，不读取无关大日志，不顺带开发 F-D～F-G。

## 9. 最终门禁

```bash
uv run python -m compileall -q src tests
uv run ruff check src tests
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

普通 story 不得重复运行上述全套；只执行与改动直接相关的最小命令。

## 10. 完成定义与后续 handoff

1. US-275～US-283 全部 `passes=true`，每个 story 有独立提交和真实验证记录。
2. 单番只经过输入、真实合集选择、审核并保存确认三个用户可见步骤。
3. 单番保存只消费 `confirmRequestSave`；幂等、响应未知和 saved-confirm-failed 恢复均有测试。
4. 成功后定位真实 tracking，页面明确为待提交，且没有任何隐式外部写入。
5. `WorkbenchView` 不再依赖单番 preview-save；批量兼容适配层与 QueueView batch 模式无回归。
6. 未修改 OpenAPI/generated/后端语义，未实现 SafeInfo、F-D、F-E 或 F-F 管理动作。
7. 完整门禁、真实 Chromium、安全检查、文档和 Ralph 归档全部完成，工作区干净。
8. Stage 35 已完成并归档。后续优先评审 F-D 批量审核；F-D 继续复用共享审核核心并独占批量保存确认，
   F-E 独占已保存 Request 语境下的 SafeInfo，F-F 才实现正式 tracking 管理动作；F-G 继续后置。

## 11. 最终门禁与交付记录

- US-275～US-283 均已通过并分别提交；Ralph 状态归档于
  `scripts/ralph/archive/2026-09-12-stage35-single-anime-journey/`。
- 前端 API drift check、typecheck、lint、341 个 unit tests、production build 和真实 Chromium 160 tests
  通过；后端 compileall、Ruff、非浏览器 pytest 1,636 tests 与 `git diff --check` 通过。
- 复核确认未修改 OpenAPI、generated client 或后端业务语义；未产生应提交的 dist、trace、截图或敏感测试产物。
- 设计边界：F-D 复用 `AnimeDraftEditor`/`useDraftSession` 并接管批量保存确认；F-E 独占
  `SafeInfoDialog`/`getRequestSafeInfo`；F-F 才能实现正式 tracking 列表、筛选、同步、提交与管理动作。
