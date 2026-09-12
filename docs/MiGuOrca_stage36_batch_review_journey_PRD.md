# MiGuOrca Stage 36 PRD：批量审核完整旅程

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| Stage | 36 |
| 工作包 | F-D：批量审核 |
| Backlog | BL-026 |
| 状态 | 已规划，待开发 |
| 目标分支 | `ralph/stage36-batch-review-journey` |
| Ralph stories | US-284～US-293 |
| 实时基线 | `origin/main` 合并提交 `c260a86`（Stage 35 已合入） |
| 前置 | Stage 34 共享审核核心、Stage 35 单番旅程、Stage 32 generated contract handoff v1 |

## 2. 背景与阶段判断

Stage 35 已把单番入口收敛为“输入 → 人工选择真实 MiKan 合集 → 审核并保存确认”，并验证了
`confirmRequestSave`、确认失败恢复和 tracking 只读 handoff。批量模式仍是 Stage 27/34 的兼容实现：
四列卡片加页后详情，单卡先调用 `preview-save`，再调用旧 `acceptBatchItems`；它尚未形成效果图要求的
左卡右详情、异常优先、固定操作栏和真正的批量部分成功。

后端所需能力已经冻结：`parseBatchTitles` 强制 1～36 部，`saveConfirmBatchItems` 提供逐项原子保存确认、
幂等重放、部分成功、`save_confirm_failed` 的公开 `request_id` 以及成功项的真实 tracking handoff。
因此 Stage 36 可以只改前端，不需要扩展 OpenAPI 或后端语义。

本阶段只完成 F-D。效果图中的“全部信息”依赖已保存 Request 的 `getRequestSafeInfo`，仍由 F-E 独占；
Stage 36 不在未保存批量草案上伪造该按钮或 DTO。正式 tracking 列表与外部管理动作仍由 F-F 完成。

## 3. 目标

1. 把批量模式收敛为可连续审核 1、典型 12、最多 36 部的桌面双栏工作台。
2. 初次按阻断异常、需核对、正常稳定排序；提供标题搜索、状态筛选、只看异常和下一异常。
3. 明确区分“当前查看的单选卡片”和“参加本次保存确认的多选卡片”。
4. 左侧卡片与右侧 `AnimeDraftEditor` 共用同一条目快照、revision 和失败状态。
5. 卡片快速切换字幕组时只锁当前条目；乱序响应不得产生新字幕组配旧资源。
6. 固定操作栏持续展示总数、筛选结果、已选、可确认、需处理、重算中和失败数量。
7. 一次调用 generated `saveConfirmBatchItems` 完成所选项的原子保存确认，并正确处理部分成功。
8. 成功项进入真实 tracking 待提交状态且不能再次提交；失败项原位保留并可局部恢复。
9. 删除批量 `preview-save → acceptBatchItems` 兼容链路和无调用的 `BatchDraftPreviewPanel`。
10. 覆盖离开保护、键盘/焦点、桌面多视口、200% 缩放、reduced-motion 和敏感信息回归。

## 4. 非目标

1. 不实现 F-E 追番方案重构、`SafeInfoDialog`、`getRequestSafeInfo` 或“复制再用”。
2. 不实现 F-F 正式 tracking 列表、同步、复核、外部提交、重试、恢复、修改、启停、刷新或删除。
3. 不实现 F-G 设置简化、发布收尾或跨页 Gate 5 最终验收。
4. 不修改 OpenAPI、generated client、Flask API、Python 领域模型或后端业务语义，不手写 API DTO。
5. 不把旧 batch queue 当作新 tracking 列表；批量 save-confirm 成功不调用旧 `acceptBatchItems`。
6. 不持久化批量候选/草案现场；刷新只能保留已经持久化的公开结果，不能恢复未保存编辑。
7. 不访问真实 MiKan、Auto Bangumi 或 qBittorrent，不创建外部订阅或下载任务。
8. 不开发移动端，不引入默认分页/虚拟滚动，不用种子数或 RSS 数量猜测“已更新集数”。

## 5. 冻结决策

### D36-01：批量现场与唯一状态源

批量 route-local store/composable 以 `item_id` 管理输入顺序、冻结审核顺序、当前详情、勾选意图、
最后一致草案、进行中修改、保存确认结果和 tracking handoff。组件不得各自复制 API snapshot。
`candidate_context`、`draft_id`、revision、幂等键和未保存编辑只存在当前页面内存。

### D36-02：容量与双栏结构

1. 本地按规范化非空行计算数量：0 部阻断；超过 36 部在调用 API 前阻断并显示实际数量和上限。
2. 解析返回后进入持续双栏：左侧紧凑卡片约 34%～38%，右侧共享详情约 62%～66%。
3. 1 部自动选中且卡片不拉伸；约 12 部列表连续滚动；36 部不分页，筛选和固定操作栏始终可达。
4. 当前条目为 FOUND 时右侧复用真实候选集合；生成 DRAFT 后在同一位置切换到共享编辑器。
5. 200% 缩放或可用宽度不足时允许双栏纵向排列，但不得丢失当前详情或操作。

### D36-03：稳定异常优先与筛选

初次完成解析后按“阻断异常 → 其他需核对 → 正常”分组，同组保持输入顺序，并冻结为当前审核顺序。
修复条目只更新状态与计数，不自动跳位；只有显式重新排序才改变顺序。标题搜索、状态筛选和只看异常
可以叠加，只改变可见性，不清除当前项或勾选。当前项被隐藏时右侧保留详情并显示可清除提示。

### D36-04：选中、勾选与异常定位

1. 点击卡片主体只改变右侧当前详情；复选框只改变批量勾选，两者的视觉与读屏名称必须不同。
2. 只有当前可确认条目可新增勾选；条目重算或临时阻断时保留原勾选意图，但不计入主按钮 N。
3. “全选正常项”默认只作用于当前可见、可确认条目，文案明确范围。
4. “下一异常项”从当前项之后查找并循环；目标被筛选隐藏时先临时显示，再滚动、选中和聚焦。
5. 卡片列表支持方向键改变当前项；Enter 进入主要处理，空格只由聚焦的复选框改变勾选。

### D36-05：共享编辑与并发

右侧必须复用 `AnimeDraftEditor`/`useDraftSession`。卡片字幕组快捷选择和详情编辑写入同一条目会话；
每条单独维护 applying/dirty/error/last-consistent 状态。修改只发送 generated preview-modify capability，
服务端 revision 是权威；旧响应不得覆盖新响应。失败保留用户选择并标为“上次有效结果”，提供重试和
恢复最后一致值。某条重算不锁住其他条目。

### D36-06：批量原子保存确认与幂等

1. 主操作只调用 generated `saveConfirmBatchItems`，不得为任何条目串联 `preview-save` 或旧 batch accept。
2. 每条 descriptor 只含 `item_id`、`draft_id`、`base_revision` 和该条内存幂等键；请求另含可选
   `item_ids` 与相对 storage profile，不回传 Request snapshot。
3. 一次明确批量操作为参与条目各生成一个键；整批响应未知时重试必须复用完全相同的条目、能力与键。
4. 发送前锁定参与条目的写操作，未参与条目仍可操作；显示逐项完成/等待状态，不允许重复触发。
5. 成功项立即消费 draft capability，清除勾选并变成不可编辑的“已确认 / 待提交”摘要，保存公开
   `request_id`/`tracking_id` 供真实只读 handoff；不得调用外部系统。

### D36-07：部分成功与逐项恢复

1. reducer 按 `item_id` 应用结果：成功项不因兄弟失败回滚，失败项保持原位置、用户上下文和可用能力。
2. 汇总必须同时显示 requested/confirmed/failed；焦点移到第一个失败条目，不能用 Toast 取代就地状态。
3. `save_confirm_failed` 且返回合法公开 `request_id` 时，该条进入“已保存，待重试确认”，废止旧 draft
   与保存键；恢复只调用 generated `acceptRequest`，之后用 `listTrackingItems` 按 `request_id` 精确取得
   服务端 tracking ID，复用 Stage 35 的安全匹配逻辑而不推导 ID。
4. 其他逐项业务失败按稳定 `error_type` 映射固定中文建议；响应不提供可安全修复 revision 时要求重新
   生成该条草案，不用相同无效参数盲重试。
5. 整批网络/响应未知保留同次操作和幂等键；未核验前不得生成新键或把条目标成失败后重新提交。

### D36-08：离开、安全与兼容退出

1. 批量已有候选、草案、勾选、未应用编辑或进行中操作时触发应用内离开确认及原生 `beforeunload`。
2. 留在页面保持现场；确认离开后清理全部 route-local capability，并明确不承诺恢复未保存现场。
3. 已确认摘要本身不误触发保护，但仍有未保存条目时继续保护。
4. F-D 完成后删除 `BatchDraftPreviewPanel` 及其 `previewSaveRequest`/`acceptBatchItems` 调用；旧
   `/app/queue?batch_id=...` 路由兼容仍保留，但不再作为新批量确认 handoff。
5. 完整 URL、RSS、magnet、endpoint、凭据、candidate context、draft、幂等键、原始响应和绝对路径
   不得进入 URL、DOM、storage、日志、通知、截图、trace 或 sourcemap。

### D36-09：效果图实现边界

布局、密度、层级和部分成功状态以 `batch-review-12-v2.png`、`batch-partial-success-v1.png` 为方向，
不做逐像素复制。Stage 36 不显示效果图中的真实“全部信息”动作；该按钮随 F-E 的已保存 Request
`SafeInfoDialog` 一并接入。此项是已知分阶段差异，不是实现缺口或 mock 占位授权。

## 6. User Stories

### US-284：冻结批量旅程状态与 generated 契约边界

建立 API-free 批量工作台状态/reducer 与 generated 类型别名，覆盖稳定顺序、当前项、勾选意图、
逐条草案会话、保存中、部分成功、已保存待确认和 tracking handoff；定义安全错误与幂等键生命周期。

### US-285：实现批量容量校验与工作台进入状态

收敛批量输入的规范化计数、0/36 上限、解析进度和逐项安全结果；解析完成后冻结异常优先顺序，
1 部自动选中，12/36 部进入连续审核，不改写输入原文。

### US-286：实现左卡右详情与选中/勾选分离

把四列卡片和页后详情改为持续双栏。FOUND 条目在右侧复用候选集合，DRAFT 条目复用
`AnimeDraftEditor`；卡片主体单选、复选框多选、阻断原因和“全选正常项”语义独立。

### US-287：实现稳定排序、搜索与筛选恢复

加入标题搜索、状态筛选、只看异常和显式重新按异常排序；筛选不得清理勾选或暗换详情，当前详情被
隐藏时给出提示，清除筛选后恢复稳定顺序、选择和记录的滚动位置。

### US-288：实现下一异常与键盘焦点行为

实现异常循环定位、隐藏目标临时可见、滚动/选中/聚焦；补齐方向键、Enter、复选框 Space、Tab 顺序、
状态播报和 reduced-motion 行为。

### US-289：实现卡片/详情共享重算与逐项隔离

卡片字幕组快捷选择与右侧编辑复用同一 `useDraftSession`；只应用最新服务端 revision，原子同步字幕组、
资源和状态，并提供逐项重算失败的重试/恢复，不能锁住兄弟条目。

### US-290：接入批量原子保存确认与部分成功

固定操作栏构造 generated `saveConfirmBatchItems` capability-only 请求，为每条维护内存幂等键和响应未知
重试；按 item 应用成功/失败，成功项进入真实待提交摘要，失败项原位保留并聚焦首个失败。

### US-291：实现已保存确认失败与 tracking 定位恢复

对白名单合法的逐项 `save_confirm_failed` 保留公开 Request，废止 draft 并只重试 `acceptRequest`；
通过 tracking list 精确匹配真实 ID，提供逐项只读待提交入口，未知结果先核验且绝不重复保存确认。

### US-292：完成离开保护、安全回归与旧批量链路退出

接入批量应用内/原生离开保护，覆盖敏感信息与 1/12/36 桌面回归；删除无调用的
`BatchDraftPreviewPanel`、`previewSaveRequest` 和新流程中的 `acceptBatchItems`，保留旧 queue 路由兼容。

### US-293：完成最终门禁、文档归档与后续 handoff

运行完整前端、后端非浏览器及真实 Chromium 门禁，对照 AC-06～14、AC-23～25 和两张效果图记录偏差，
归档 Ralph 状态并明确 F-E/F-F/F-G 的剩余边界。

## 7. Story 验收摘要

| Story | 最小定向验证 | 独立审核点 |
| --- | --- | --- |
| US-284 | 批量状态/reducer Vitest + typecheck | 状态所有权、generated 类型、幂等与安全错误 |
| US-285 | 输入/容量组件测试 + 定向 Chromium | 0/1/12/36、异常初排、无真实外部访问 |
| US-286 | 双栏/选择组件测试 + 定向 Chromium | 共享详情、单选与多选、响应式 |
| US-287 | 排序筛选纯函数/组件测试 + 定向 Chromium | 稳定顺序、隐藏当前项、滚动恢复 |
| US-288 | 键盘/焦点组件测试 + 定向 Chromium | 下一异常循环、读屏、reduced-motion |
| US-289 | revision/乱序/恢复 Vitest + 定向 Chromium | 同一状态源、旧响应丢弃、逐项锁 |
| US-290 | save-confirm reducer/transport + 定向 Chromium | capability-only、幂等重试、部分成功 |
| US-291 | 恢复状态测试 + 定向 Chromium | 只重试确认、tracking 真 ID、未知结果核验 |
| US-292 | 引用搜索、安全/离开测试 + 定向 Chromium | 旧链路归零、敏感面、兼容路由 |
| US-293 | 完整门禁与人工视觉对照 | 归档、偏差、F-E/F-F/F-G handoff |

每个 Ralph 迭代只完成一个 story。每次最多运行 3 个 stories；完成 US-286、US-289、US-292 后必须
停止并进行独立审核。普通 story 只运行定向检查；完整前端、非浏览器和 Chromium 套件只在 US-293
最终收尾运行一次，除非代码变化后需要复验具体失败。

## 8. 完整验收标准

1. AC-06～AC-14、AC-23～AC-25 均有 Vitest/真实 Chromium 责任映射并通过。
2. 1280×720、1440×900、1920×1080 与 200% 缩放可完成 1/12/36 部审核，无分页和不可达操作。
3. 效果图的双栏比例、异常层级、固定操作栏及部分成功恢复方向成立；已知仅缺 F-E 的全部信息。
4. 批量新流程只调用 `saveConfirmBatchItems`；成功不调用 Auto Bangumi/qBittorrent，也不建立旧 queue。
5. 部分成功、保存后确认失败、revision 失败和响应未知均不重复创建 Request/tracking。
6. 卡片/详情共享一个服务端权威草案状态，旧响应不能覆盖最新 revision。
7. 未保存批量现场不落盘且离开前有明确保护；敏感值检查覆盖 DOM/URL/storage/console/trace/screenshot。
8. OpenAPI、generated client 和后端业务语义保持不变；无 dist、trace、截图或敏感产物入库。

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

真实 Chromium 验证必须按 `dev-browser` skill 执行；route fake/本地 fake transport 不得访问真实外部
服务。测试失败后先运行最小失败用例，无代码变化不得重复跑同一完整门禁。

## 10. 回退与完成定义

1. Stage 36 只改批量前端 slice、相关共享 helper/test 与状态文档，可独立回退到 Stage 35 批量兼容页。
2. 删除旧组件前必须有引用搜索、bundle、定向 Chromium 和旧 queue 路由兼容证据。
3. US-284～US-293 全部 `passes=true`、代码独立审核无阻断、完整门禁通过后，才可标记完成并归档。
4. 合并、push、PR 和分支清理仍需用户单独授权；Ralph Agent 不得自行执行。

## 11. 后续 handoff

- F-E：追番方案列表—详情、已保存 Request 修改/复制再用/历史、真实 `SafeInfoDialog`。
- F-F：正式追番管理总览、列表、检查器、凭据会话、复核/提交/恢复与 AB 完整管理动作。
- F-G：设置简化、连接诊断、跨页收敛和 Gate 5 候选发布包。
- 独立发布验收可并入 F-G；若跨流程风险或设计偏差仍高，再单列一个最终 Stage，不在本阶段预占编号。
