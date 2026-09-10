# MiGuOrca Stage 34 PRD：前端共享审核核心

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| Stage | 34 |
| 工作包 | F-B：共享审核核心 |
| Backlog | BL-026 |
| 状态 | 已完成并归档 |
| 目标分支 | `ralph/stage34-shared-review-core` |
| Ralph stories | US-266～US-274 |
| 实时基线 | `origin/main` 合并提交 `9f2e06b`（Stage 33 已合入） |
| 前置 | Stage 33 壳层与设计系统、Stage 32 前端契约 handoff v1 |

## 2. 背景与阶段判断

Stage 33 已交付四项导航、语义 Token、共享 UI 原语和现有页面的兼容挂载。Stage 34 已完成
`DraftPreviewPanel` 已被单番与批量复用，但仍同时承担草案展示、表单状态、
`preview-modify`、`preview-save` 和通知；`BatchDraftPreviewPanel` 又依赖其暴露的保存方法。
这使 F-C 单番保存确认和 F-D 批量保存确认无法在不触碰旧保存语义的情况下复用审核界面。

Stage 34 只完成 F-B：把模式输入、候选选择和服务端权威草案编辑整理为可复用核心，并用薄兼容
适配层维持现有单番、批量流程。它不是单番三步旅程、批量审核工作台或追番方案页面的完成阶段。

早期总体规划曾把 `SafeInfoDialog` 放入 F-B，但 Stage 32 的正式契约把
`getRequestSafeInfo` 分配给 F-E，且该端点只接受已保存的 `request_id`。未保存草案不能真实取得
safe-info。本阶段因此不实现、不请求也不模拟“全部信息”；真实 `SafeInfoDialog` 统一延后到 F-E。

## 3. 目标

1. 提供单番/批量共享的模式切换和输入组件，两种输入分别保留在 `/app/add` 页面内存。
2. 抽取真实 MiKan 候选列表，继续要求用户明确选择，不自动选择任何候选。
3. 建立唯一的草案会话状态模型，只在组件内存持有 `draft_id`、`draft_revision` 和最后一致快照。
4. 提供单番、批量共用的 `AnimeDraftEditor`、`SubtitleGroupSelect` 和 `ResourceSummary`。
5. 编辑只调用 generated contract 对应的 `previewModifyRequest`，按 revision 更新完整一致结果。
6. 正确处理重复操作、乱序响应、409 冲突、草案失效和普通网络失败。
7. 通过薄兼容适配层保持现有 `preview-save` 和批量 accept 流程可用，核心本身绝不消费草案。
8. 为后续 F-C、F-D、F-E 提供稳定组件、事件和状态边界，不提前实现它们的页面流程。

## 4. 非目标

1. 不实现 F-C 单番三步旅程、`confirmRequestSave`、保存后 tracking 跳转或“重试确认”。
2. 不实现 F-D 的 1/12/36 双栏工作台、异常筛选、批量部分成功或离开保护。
3. 不实现 F-E 追番方案重构、`SafeInfoDialog` 或 `getRequestSafeInfo` 数据接入。
4. 不实现 F-F 正式追番管理，不修改 `/app/tracking` 的现有 `QueueView` 兼容挂载。
5. 不修改 OpenAPI、generated client、Flask API 或后端领域语义，不手写 API DTO。
6. 不删除现有 `DraftPreviewPanel`/`BatchDraftPreviewPanel` 兼容入口，除非已由等价薄适配层替代。
7. 不持久化输入、候选上下文或草案状态，不新增持久化 Pinia 插件。
8. 不访问真实 MiKan、Auto Bangumi 或 qBittorrent，不开发移动端，不猜测“已更新集数”。

## 5. 冻结决策

### D34-01：共享核心与保存边界

`AnimeDraftEditor` 负责展示、编辑、重算和一致状态，不提供“保存草案”“保存并确认”或批量接受
网络实现，也不得导入/调用 `previewSaveRequest`、`confirmRequestSave`、
`saveConfirmBatchItems`。它通过明确事件或公开的只读状态把用户意图交给宿主。

现有流程仍需可用，因此 `DraftPreviewPanel` 可以暂时作为兼容适配层：它组合
`AnimeDraftEditor`，并在核心之外保留既有 `preview-save` 行为；
`BatchDraftPreviewPanel` 继续在适配层之外完成旧 batch accept。F-C/F-D 将分别替换这两条保存路径。

### D34-02：草案状态与并发

1. 草案会话唯一事实包含：最后一致的公开 Request 快照、opaque `draft_id`、单调
   `draft_revision`、表单草稿、dirty/applying/error 状态和本次请求序号。
2. `draft_id`、revision、candidate context 只存在 route/component-local 内存和单次 POST body；
   不进入 URL、history、Pinia 持久化、browser storage、DOM 属性、日志、通知、截图或 trace。
3. 修改请求只发送 generated request type 允许的 `draft_id`、`base_revision`、patch 和现有安全
   storage profile；绝不回传完整 Request 快照。
4. 成功时原子替换快照、字幕组、资源结果和 revision；不得先更新字幕组再等待资源结果。
5. 同一草案至多一个有效写请求。若实现允许并发，旧响应必须按本地请求序号丢弃；无论哪种实现，
   旧响应都不能覆盖新状态。
6. `draft_revision_conflict`、expired、evicted、replayed 会使当前草案失效：丢弃不可再提交的
   本地快照和 opaque 草案标识，通知宿主回到可重新生成状态，不静默重放。
7. 普通网络/服务错误保留最后一致资源结果和用户未应用的表单输入，提供“重试”和“恢复为上次结果”。

### D34-03：模式输入

1. `/app/add` 默认单番模式；`AnimeModeSwitch` 使用可访问的单选/标签语义和明确选中态。
2. 单番与批量各持有一份输入和光标/选择范围；切换不截断或清空另一份内容。
3. `AnimeTitleInput` 单番为单行，批量为可自增高的多行输入；本阶段复用现有解析动作，不重写
   F-C/F-D 页面旅程。
4. 状态只属于当前 `/app/add` 页面实例，离开或刷新不承诺恢复。

### D34-04：候选列表

`CandidateCollectionList` 组合现有候选卡片、季数确认和选择规则，只渲染公开白名单字段。即使只有
一个候选也不能自动选择；冲突候选保持阻断，候选上下文不进入 DOM 或持久化。单番和批量调用方
不得复制第二套候选选择规则。

### D34-05：组件职责

| 组件/模块 | Stage 34 职责 |
| --- | --- |
| `AnimeModeSwitch` | 单番/批量模式切换、键盘与 reduced-motion 语义 |
| `AnimeTitleInput` | 单行/多行统一输入接口和模式内状态恢复 |
| `CandidateCollectionList` | 候选集合、人工选择、季数确认和安全展示 |
| draft session composable/module | revision、最后一致快照、dirty、错误和请求次序 |
| `SubtitleGroupSelect` | 字幕组选择及 applying/disabled/error 状态，不自行请求 API |
| `ResourceSummary` | 有效/完整/排除资源的安全摘要和“已更新集数待开发” |
| `AnimeDraftEditor` | 共享详情表单、preview-modify 编排和原子结果更新 |
| `DraftPreviewPanel` | 旧单番保存流程的薄兼容适配层 |
| `BatchDraftPreviewPanel` | 旧批量接受流程的薄兼容适配层 |

不得建立 V2 前缀的平行组件，也不得在批量卡片中保存第二份字幕组或资源状态。

### D34-06：SafeInfo 延后

Stage 34 不创建 mock safe-info、不从 Request snapshot 客户端拼接“全部信息”，也不为未保存草案
调用 `getRequestSafeInfo`。F-E 在已保存 `request_id` 语境下实现真实 `SafeInfoDialog`，只消费服务端
白名单 DTO。若本阶段需要预留 UI 位置，只能使用不渲染、不取数的类型化插槽/事件，不得宣称功能完成。

### D34-07：安全、无障碍与视觉

复用 Stage 33 Token、Base*、PanelSection、FormField 和反馈原语。状态不能只靠颜色；模式切换、
候选选择、编辑、失败恢复均支持键盘和明确焦点。真实 Chromium 检查不得把敏感 canary 写入
截图/trace；测试只断言其未出现在 URL、DOM、history 和 browser storage。

## 6. User Stories

### US-266：建立草案会话状态与 generated contract 边界

建立可独立测试的 draft session/composable：用 generated `createRequest` 和
`previewModifyRequest` 类型表达输入输出，管理最后一致快照、opaque ID、revision、dirty、请求次序
和错误转换。覆盖原子成功、旧响应拒绝、冲突失效、普通失败保留与 reset/retry 状态；核心中不得出现
preview-save、save-confirm 或手写 Request DTO。

### US-267：实现模式切换与统一输入

实现 `AnimeModeSwitch`、`AnimeTitleInput` 及 `/app/add` route-local 状态。单番/批量分别保留输入和
光标，支持鼠标、键盘、reduced motion；继续调用现有单番搜索与批量解析入口，不在本 story 改造
候选或草案详情。

### US-268：抽取共享候选集合

从现有 Workbench/批量候选 UI 抽取 `CandidateCollectionList`，复用 `CandidateCard` 和既有纯函数。
覆盖零/一/多候选、季数确认、冲突禁用与明确人工选择；单番和批量接入时不改变现有 API payload、
candidate context 生命周期或结果文案。

> 第一开发批次到此停止。开发 Agent 运行 Ralph 最多 3 次，只完成 US-266～US-268，然后交由独立
> 审核；不得继续 US-269。

### US-269：抽取字幕组与资源摘要组件

从现有草案详情抽取 `SubtitleGroupSelect` 和 `ResourceSummary`。组件只接收公开状态和事件，不自行
持有第二份 draft 或调用 API；资源摘要复用现有 helper，完整 URL/magnet 不进入 DOM，“已更新集数”
固定显示待开发/不可用语义。

### US-270：实现共享 AnimeDraftEditor 结构

让 `AnimeDraftEditor` 组合共享表单、字幕组和资源摘要，覆盖普通字段与渐进披露的高级设置，消费
Stage 33 Token 和原语。单番、批量使用相同 props/events；本 story 只建立编辑结构和状态绑定，
不调用任何保存确认端点。

### US-271：接入 revision 重算与失败恢复

把 `previewModifyRequest` 接入共享编辑器：发送当前 base revision 和最小 patch，成功时原子更新，
重复提交/旧响应不能覆盖新状态。409 草案冲突/失效清除不可用会话并要求重新生成；普通失败保留
最后一致结果和未应用输入，支持重试或恢复。

> 第二开发批次到此停止并独立审核；审核通过前不得继续兼容集成。

### US-272：接入单番兼容适配层

把现有 `DraftPreviewPanel` 收敛为组合共享编辑器的薄适配层。`preview-save` 只能保留在该适配层，
现有单番“保存草案后进入方案详情”行为、错误文案和草案一次性消费保持对等；共享核心本身的依赖
检查必须证明没有保存端点。

### US-273：接入批量兼容适配层

让 `BatchDraftPreviewPanel` 和当前批量卡片复用同一 `AnimeDraftEditor`/draft session，修改后同步唯一
快照与 revision。既有 preview-save → batch accept 只作为 F-D 前的兼容路径保留在适配层；不得复制
表单、字幕组、资源 helper 或提前实现批量 save-confirm/新双栏工作台。

### US-274：完成门禁、文档归档与后续 handoff

执行一次完整前端门禁、必要后端非浏览器回归和完整真实 Chromium；检查 OpenAPI/generated 无漂移、
敏感值无泄漏、兼容流程对等。同步文档与 Ralph 归档，分别记录 F-C/F-D 如何移除兼容保存层，以及
F-E 独占 `SafeInfoDialog`/`getRequestSafeInfo` 的冻结边界。

## 7. 验收矩阵

| 风险 | 必须证明 |
| --- | --- |
| 状态分叉 | 单番与批量详情消费同一编辑器和会话模型，无第二份字幕组/资源状态 |
| 契约越界 | 核心只依赖 create/preview-modify generated types，不调用任何保存端点 |
| 乱序覆盖 | 单请求串行或请求序号测试证明旧响应无法覆盖新 revision/快照 |
| 失败丢数据 | 普通失败保留最后一致资源和表单输入；冲突则清除失效会话并要求重新生成 |
| 兼容回归 | 旧单番保存和批量接受仍可用，且保存逻辑只在薄适配层 |
| 候选真实性 | 永不自动选择，季数确认与冲突阻断保持现有服务端语义 |
| SafeInfo 伪造 | 未保存草案不请求、不拼接、不展示伪造的“全部信息” |
| 安全 | ID/revision/context/敏感值不进入 URL、DOM、storage、日志、截图或 trace |

## 8. 迭代与成本控制

1. 每个 Ralph 迭代只完成一个最高优先级 story。
2. 每次只运行 3 个迭代：第一批 US-266～US-268，审核修复后第二批 US-269～US-271，再审核后
   执行 US-272～US-274。开发 Agent 到达批次边界必须停止并报告。
3. US-266～US-273 只运行受影响 Vitest、typecheck 和少量相关 Chromium；UI story 必须使用
   `dev-browser` skill 在真实 Chromium 验证。
4. 只有 US-274 运行一次完整前端与完整 Chromium 门禁；无代码变化不得重复全量检查。
5. 测试失败先运行最小失败用例；预计 9 个实现迭代，额外修复最多 2 轮，超过 11 轮停止报告。
6. 不重复安装依赖，不连接外部服务，不读取无关大日志，不顺带开发 F-C～F-G。

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

1. US-266～US-274 全部 `passes=true`，每个 story 有独立提交和真实验证记录。
2. 单番/批量模式输入、候选选择和草案详情分别只有一个共享实现与明确状态所有者。
3. 草案修改满足 revision、原子结果、乱序保护、失效清理与普通失败恢复要求。
4. `AnimeDraftEditor` 不消费草案；旧保存/接受仅存在于可移除兼容适配层。
5. 未修改 OpenAPI/generated client/后端业务，未实现或伪造 SafeInfo、F-C～F-G 页面。
6. Stage 34 合入并稳定后，再分别评审 F-C 单番添加、F-D 批量审核和 F-E 追番方案；不预先锁定
   它们的 Stage 编号或并行方式。

### 10.1 归档证据与后续消费边界

- US-266～US-274 均已通过并保留独立提交；Ralph 状态归档于
  `scripts/ralph/archive/2026-09-11-stage34-shared-review-core/`。
- 最终门禁通过：compileall、Ruff、1,636 个非浏览器后端测试、OpenAPI drift、前端 typecheck/lint、
  325 个 Vitest 单元测试、生产构建、完整真实 Chromium 套件和 `git diff --check`。
- Stage 34 未修改 OpenAPI、generated client 或后端业务语义；安全边界检查确认 draft capability、
  revision、candidate context、敏感配置和原始响应体不进入 URL、DOM、browser storage、日志、截图
  或 trace。
- F-C 应以 `AnimeDraftEditor`/`useDraftSession` 的公开事件和服务端权威 snapshot/revision 为基础，
  接管单番保存确认后删除 `DraftPreviewPanel` 的 `preview-save` 兼容路径。
- F-D 应复用同一编辑器/会话边界，接管批量保存确认和部分成功流程后删除
  `BatchDraftPreviewPanel` 的 `preview-save`/accept 兼容路径。
- F-E 独占已保存 Request 语境下的 `SafeInfoDialog`/`getRequestSafeInfo`；不得从未保存草案拼接或
  模拟“全部信息”。Stage 34 不实现 F-C～F-G 页面。
