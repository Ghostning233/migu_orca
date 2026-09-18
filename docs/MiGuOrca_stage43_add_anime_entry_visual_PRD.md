# MiGuOrca Stage 43 执行 PRD：搜索入口与候选选择视觉收口

## 1. 执行信息

| 项目 | 内容 |
| --- | --- |
| 状态 | 已准备执行材料、尚未开发；WP-43-A 可开始，WP-43-B～E 受 D-01 门控 |
| 日期/基线 | 2026-09-18；`334c8e69dbcc7c27be8ab482f8ccb142081db0b7` |
| 分支 | `ralph/stage43-add-anime-entry-visual`；开始前核对实时 HEAD/工作区，不从本文猜状态 |
| 总体依据 | [Stage 43～45 总体 PRD](MiGuOrca_stage43_45_add_anime_visual_PRD.md) |
| 决策唯一记录 | [D-01～04 与后续编写交接](development/add-anime-visual-prd-handoff-2026-09-18.md) |
| Ralph | `scripts/ralph/prd.json`，US-347～US-352，priority 1～6；初始全为 false，notes 为空 |
| 下一会话启动 | [团队主 Agent 提示词](development/stage43-team-main-agent-prompt.md) |

本次授权仅文档落盘/状态准备/本地文档提交，不自动启动开发、团队或发布。
后续用户发送启动提示词才按其明确授权执行。未运行本 Stage 功能测试。

## 2. 范围与稳定边界

目标：先落实确认全部的完整批次范围，再收口搜索入口和候选比较，不改草案审核结构。
采用现有组件/生成契约，复用原加载、搜索、保存及恢复链路。

允许代码：`frontend/src/features/workbench/WorkbenchView.vue`、`BatchWorkbenchView.vue`、
`AnimeModeSwitch.vue`、`AnimeTitleInput.vue`、`CandidateCollectionList.vue`、`CandidateCard.vue`、
`candidateSearch.ts`、`batchWorkbench.ts`；D-01 批准范围内的 styles/表单基础组件及必要壳层样式；
对应 Vitest/Chromium 测试、Ralph 状态与精简交接。
允许提取小型确认资格/意图 helper，但不造第二套 DTO 或状态机。

禁止：后端/API/OpenAPI/generated client 改动，草案编辑器重排，N 部隐藏项口径变更，
追番管理/设置业务、外部写、数据库/worker/下载/移动、未保存持久化、单项搜索重试或实时进度。
`useDraftSession`/scheduler/journey 原则上仅回归；如真实回归需改实现，先由主 Agent 限定窄修复。

所有故事共同 AC：

- 人工选择真实合集，唯一候选不自动选；CONFLICT 禁止选，NEEDS_CONFIRMATION 显式确认。
- 草案版本只用服务端返回值；patch/save body 不包含权威完整 Request。
- 本地确认不外部写，AB 未配置不阻止本地流程。
- 关键错误/恢复留原业务区域，关闭 Toast 后仍可恢复。
- 禁止值不落 DOM/属性、URL/history、浏览器存储、console、截图/trace；能力/键仅内存及合法请求体。
- 1280×720、1440×900、1920×1080、200% 桌面缩放可达，长标题不挤出动作；不把窄窗兼容当移动开发。
- 可见标签、错误关联、中文状态、键盘/焦点、reduced-motion；对比度和主要目标按 Token V1。
- 单番/批量输入和光标保留、离开警告、局部加载、CAS、幂等、未知重放均为已有回归门槛。

## 3. 原子工作包、依赖与迭代预算

| 包 | 故事/priority | 前置 | 迭代上限/停止点 |
| --- | --- | --- | --- |
| WP-43-A | US-347/1、US-348/2 | 基线核查，无产品待决策 | 2 个开发 story turn；两条完成后统一独立审核 |
| WP-43-B | US-349/3 | A 闭环、D-01 用户已决定并记录 | 1 个开发 story turn；包审核 |
| WP-43-C | US-350/4 | B 闭环 | 1 个开发 story turn；包审核 |
| WP-43-D | US-351/5 | C 闭环 | 1 个开发 story turn；包审核 |
| WP-43-E | US-352/6 | D 闭环 | 1 个开发 story turn；包审核、Stage 门禁 |

每次只做一个 story；同包复用同一开发 Agent，不用 ralph.sh，不固定三故事一批。
每包集中修复最多 3 轮；任一轮实际失败不标通过，复审未通过不开始下一包。
达到上限保留问题/红测/进度并报告，不能以部分通过关闭工作包或无限循环。
passes 表示故事已完成列明验证，不替代独立审核；审核状态在 progress 单独记录。

## 4. WP-43-A：确认全部范围窄修复

### US-347：完整批次可确认集合

用户故事：筛选只影响浏览，确认全部保存完整批次中的全部当前可确认项。

现状：`selectable` 使用 visibleItems；请求 `items` 仅可见描述符；服务端省略 item_ids
处理全部请求 items，不补隐藏项。既有 all 测试只覆盖未筛选场景。

可观察 AC：

1. 先加入最小红测：A/B 两个可确认草案，筛选仅见 B，不勾选，确认全部请求包含 A/B。
2. 完整批次资格集合复用 `itemConfirmability`；按钮可用条件、M 计数、弹窗数量、描述符同源。
3. 排除待选、dirty/防抖/目录等待、重算/失败未恢复、零资源、失效、已确认、saved pending、未知。
4. 可见零项但隐藏有资格时全部仍可用；完整批次无资格时禁用，附近有可见中文原因。
5. 保留全部入口、N 部入口及全选当前可见可确认项；不修改 N 的当前语义，不清隐藏勾选。
6. 请求保留现行 all 约定（描述符覆盖全批有资格项，省略 item_ids），每条用最新服务端 draft_id/revision。
7. 混合状态不阻断其他正常项，成功项不再参与；未知重试原 body/key/revision/集合不变。
8. 同步页面全部旧文案/计数测试，不删除敏感断言或放宽资格测试。

| 状态 | 必须可见/请求规则 |
| --- | --- |
| 可见/隐藏都有资格 | 全部 M 包含二者，与勾选无关 |
| 只隐藏有资格 | 全部可用，显示完整批次范围 |
| 完整批次无资格 | 禁用，说明先选择/处理草案 |
| 有正常和阻断项 | 仅正常进入描述符，说明排除 |
| 保存中/未知 | 防重复，未知同意图恢复 |

失败/无障碍：错误仍原卡片和结果区；未知不误报未保存；失败隐藏项先可见化再焦点；
按钮描述包含全批范围，不仅悬停提示；取消弹窗返回原按钮。

文件：`BatchWorkbenchView.vue`、必要的 `batchWorkbench.ts` helper，两个对应 test；
`tests/browser/test_app_batch_workbench.py`。
定向 Vitest：上述两文件；真实 Chromium 新增筛选 all/零可见/混合资格场景并捕获 POST body。
契约回归：`test_save_confirm_service.py` 的 batch coordinator 顺序/子集及 `views_test.py`
的 batch save-confirm item_ids/部分成功；不改契约源。

### US-348：确认全部弹窗意图复核

用户故事：二次确认看到的数量和集合就是最终发送的对象，状态变化不能偷偷改写确认。

可观察 AC：

1. 打开 all 弹窗捕获内存 intent：batch、参与项标识、draft_id、base_revision；不持久化/展示能力。
2. 标题/按钮写明保存并确认全部 M 部；正文说明完整批次、隐藏参与 H 部、排除阻断项、仅本地保存。
3. 确认时重新核对完整资格集合及绑定版本；新增/移除资格、draft/revision/batch 变化时不发请求，
   关闭失效确认并在固定业务区说明需重新确认。不能仅过滤旧 rows，也不能自动补新 rows。
4. 只有可见性或勾选变化但资格/版本不变时，all 集合不变；函数入口防重不只依赖 disabled。
5. 取消不发请求，不改变勾选/详情；通过复核后用该 intent 对应描述符发送并交现有 saveOperation 冻结。
6. RESPONSE_UNKNOWN 的重试不走新 intent/复核换版本，沿用原被冻结 body。
7. N 部弹窗与请求保持原行为；扩展其意图护栏留 Stage 45，不因共用组件顺带改变口径。

| 弹窗状态 | 结果 |
| --- | --- |
| 资格/版本未变 | 发送原明确集合 |
| 仅筛选/勾选变 | 全部意图不变 |
| 集合/draft/revision/batch 变 | 不发送，业务区重新确认说明 |
| 用户取消 | 不发送，现场不变 |
| 保存中/未知 | 防重/原冻结请求恢复 |

失败/无障碍：变化说明常驻，不能只 Toast；复用 ConfirmDialog trap/Escape/焦点恢复；
变更拒绝后焦点回全部入口或恢复说明，不自动再次打开确认。
文件同 US-347，必要时仅调整 ConfirmDialog 的安全文案支持，不更改全局焦点机制。
测试：deferred 修改响应在弹窗开启后更新版本/资格，确认后捕获零 POST；未变化则精确 body。
真实 Chromium 使用 held route 控制已在途响应，不在 handler sleep，不需让用户操作模态背景。

## 5. WP-43-B／US-349：批准作用域的 Token 对齐

用户故事：搜索、候选、表单和状态使用一致的已批准视觉基线。

前置 D-01 必须有用户实际回答。未回答时保持 false，不静默选择全局或局部方案。

可观察 AC：

1. 将用户选定作用域和共享 Token 映射记录于 progress；现行语义变量可映射 V1，不复制一套页面色值。
2. 覆盖画布/表面、文字、主按钮、状态、边界、焦点、字号/行高、尺寸、圆角、间距与动效。
3. 默认主要控件 44px、首页搜索操作 52px；12px 补充信息不承载关键错误；品牌/导航结构不重设计。
4. 全局方案：共享主题/基础控件对齐并四页定向回归，不改四页业务；仅添加方案：共享层定义批准作用域，
   其他页 computed style 保持原主题，模态/Teleport 样式按作用域明确处理，不散落 magic 值。
5. 焦点可见、不 overflow 裁剪；正文 4.5:1、控件边界 3:1；reduced-motion 保持即时状态与文字加载。
6. 不改 Toast timer/store，不扩大旧 z-index 取舍；对导航/底栏/模态/Toast 层级做真实命中回归。

| 状态 | 验收 |
| --- | --- |
| 默认/hover/focus | Token 映射、边界及焦点可辨 |
| disabled/loading/error | 原因/进行文字/错误不丢，仅颜色不足 |
| 200% 缩放 | 控件可达，不用宽度提示阻断 |
| reduced-motion | 无非必要位移，状态仍可识别 |

文件：`styles/tokens.css`、`styles/main.css`、`components/forms/` 受影响基础组件、
`components/layout/FormField.vue`、必要的 `App.vue` 纯样式/语义；不扩 App 业务。
Vitest：`styles/tokens.test.ts`、实际改动基础组件测试、`App.test.ts`（若受影响）。
Chromium：`test_app_shell.py`、`test_app_responsive_a11y.py`、`test_app_global_notification.py`
定向主题/焦点/层级、四页各一正常和错误/禁用态；不跑四页全部业务 suite。
无新契约，不新增后端测试；此包不以字符串包含 Token 替代真实 computed style/可读性验收。

## 6. WP-43-C／US-350：单番搜索入口层级

用户故事：进入页面即可输入，理解下一步仍需选合集和审核。

可观察 AC：

1. 页面任务主标题为添加番剧；去除重复容器标题，保留可定位的搜索/候选区域标题和现有公开路由。
2. 模式切换邻近输入；可见标签、输入、按钮组成操作组；宽桌面限制行长，200% 可换行。
3. 三步预告为输入名称 → 选择真实合集 → 审核并保存确认，不加入外部提交第四步。
4. FOUND 后输入收为搜索摘要，修改搜索入口恢复原文/焦点；摘要与修改入口集中。
5. 初始不渲染空结果/直连大面板；EMPTY/FAILED、搜索区域错误/重试及既有直连救援条件保持。
6. 模式切换保留原文/光标；进行态防重不丢输入，不自动选唯一候选；重算/保存宿主不因标题重排丢状态。

| 状态 | 展示/恢复 |
| --- | --- |
| 初始/空白 | 标签、三步、禁用原因，无空结果 |
| 有效输入 | 唯一搜索主操作 |
| 搜索中 | 原文与诚实整体等待，防重 |
| FOUND | 摘要/修改/人工候选 |
| EMPTY | 空态、改名称、既有救援 |
| FAILED/请求失败 | 搜索区安全原因/重试，非空态 |

无障碍：首次焦点输入；模式方向键/Enter/空格；搜索完成焦点候选标题/首候选；
返回编辑焦点输入；aria-live 不逐字段刷屏；修改入口与加载不依赖 Toast。
文件：WorkbenchView/AnimeModeSwitch/AnimeTitleInput，受影响原 test；
Chromium `test_app_workbench.py`、`test_app_mode_input.py` 定向初始/空/FAILED/键盘/光标/修改搜索。
契约回归 `views_test.py` 的候选 EMPTY/FAILED/脱敏/空查询；只选与实际 diff 对应分支。

## 7. WP-43-D／US-351：批量输入、容量与等待

用户故事：在同一区域检查 1～36 部容量，再搜索候选。

可观察 AC：

1. 将现有宿主输入与批量子组件动作归为一个操作区域，仍只有一个 v-model 输入权威来源。
2. 有效行数复用 batchItemCount/splitter 语义，0/36 与实际数量可见，不改写原文/截断输入。
3. 0/37+ 禁用搜索并关联就地说明；1/36 可搜索；函数校验继续存在，不只靠按钮。
4. 动作文案改为搜索候选合集；首次不展示完整空工作台，完成后才出现双栏结果。
5. 搜索中保留原文及提交规模、整体不定进行态，不承诺逐条实时完成或虚构百分比。
6. 部分 EMPTY/FAILED 保留其他条目；单项失败只能整批重新搜索或既有候选生成恢复。
7. 有候选/草案/勾选未保存现场重搜，复用 ConfirmDialog 明确舍弃范围；取消保持现场，确认后才清除。
8. 沿用输入自动增高/内部滚动，不重建调度/跨刷新恢复；36 行时说明、错误和操作可达。

| 状态 | 展示/恢复 |
| --- | --- |
| 0/1～36/37+ | 不可用/可用/超限，准确计数 |
| 搜索中 | 原文、整体等待、防重 |
| 混合逐项结果 | 工作台和实际状态汇总 |
| 整体失败 | 原文、就地错误/整批重试 |
| 未保存现场重搜 | 明确影响；取消不清，确认才重搜 |

无障碍：计数/错误关联 textarea；搜索完成聚焦工作台标题；不每击键播报长说明；
重搜取消恢复触发入口；200% 缩放和1280×720 输入/动作可达。
文件：WorkbenchView、BatchWorkbenchView、AnimeTitleInput、batchWorkbench helper；
Vitest 四者现有对应 test；Chromium batch/mode/workbench 定向 0/1/36/37、held 搜索、混合结果和重搜取消。
契约回归 `views_test.py` 的边界 batch sizes、over limit before seam、single provider failure。

## 8. WP-43-E／US-352：共享候选比较布局

用户故事：标题、证据和选择操作靠近，单番能比较、批量右栏不空旷。

可观察 AC：

1. CandidateCollectionList/Card 继续共享；以宿主布局输入或容器响应调整单番与批量，不复制两套选择逻辑。
2. 默认展示标题、安全代理封面/占位、季度证据、独立总集数、选择动作；高级匹配信息按需展开。
3. 候选阶段不展示有效/排除资源、不推算已更新集数；移除混合的播出进度表达，未知总集数明确未知。
4. 多候选单番自适应比较，不强制三列；批量窄右栏紧凑，长标题/证据可换行，按钮不挤出。
5. 无封面/图片加载失败回落占位，src 仅当前允许同源 opaque poster 路径，不虚构或跨候选猜配。
6. 保持 CONFLICT 禁选、NEEDS_CONFIRMATION 明确人工确认；缺证据不由前端猜季度。
7. clicked 卡就地进行文字，单番同会话其他选择暂禁、批量仅本 item 锁；其他 item 可查看/操作。
8. 失败候选旁安全错误/重试，成功进入共享审核，不自动勾选其他项；safe-info 不新增调用。

| 状态 | 展示/操作 |
| --- | --- |
| 可选 | 比较字段，等待人工 |
| NEEDS_CONFIRMATION | 可见确认框，确认后允许 |
| CONFLICT | 就地说明，禁止选 |
| 生成中 | 当前按钮旁文字，同条目防重 |
| 失败/失效 | 就地重试或既有重搜/生成 |
| 无封面/长标题 | 占位/换行，动作可达 |

无障碍：每个选择按钮 accessible name 包含候选名；加载可读，成功聚焦审核标题，
失败保持上下文；reduced-motion 不留无文字残弧；主要目标和焦点按 Token。
文件：CandidateCollectionList/Card、candidateSearch、两个宿主必要布局；
Vitest CandidateCollectionList/candidateSearch/WorkbenchView/BatchWorkbenchView。
Chromium两个 workbench 文件：2～3 候选、长标题、坏图、证据分支、held 生成、批量另一项操作。
候选 DTO/敏感投影以 `test_dto_contracts.py` 和 `views_test.py` 相关分支回归。

## 9. 验证矩阵与命令

前端目录每 story 跑对应受影响文件，例如 A：

```bash
npm run test:unit -- --run src/features/workbench/BatchWorkbenchView.test.ts src/features/workbench/batchWorkbench.test.ts
npm run typecheck
npm run lint
npm run build
```

根目录包 A 的既有服务语义核验（只选择必要用例，不每条重复）：

```bash
uv run pytest tests/api_contract/test_save_confirm_service.py -q -k 'batch_save_confirm_coordinator_preserves_order or batch_save_confirm_coordinator_item_ids'
uv run pytest src/apps/migu_orca_web/views_test.py -q -k 'batch_save_confirm_api_item_ids_selects or batch_save_confirm_api_returns_partial_success'
```

新增浏览器函数节点名由实现者确定并在 progress 记录真实命令；先 build 后按 dev-browser
定向运行相应文件/类/函数，不用未经核实的假节点名。held route 控制请求，真实 envelope，
外部系统全 mock，运行数据隔离、不删除未知数据、不生成敏感 screenshot/trace。
敏感 canary 必须真实进入 API 客户端内存/展示边界再检查，不以未被消费的额外字段制造空转证据。

| 场景 | Vitest/契约 | Chromium |
| --- | --- | --- |
| all 隐藏项/零可见/排除资格 | 最小红测、精确 body、服务 items/item_ids | 捕获请求集合与可见禁用原因 |
| 弹窗晚响应/意图变化 | deferred revision/集合变化，零 POST | held 响应在模态期间到达，重新确认 |
| Token/作用域 | 映射/基础控件状态 | computed style、对比/命中、四页回归 |
| 单番入口 | 输入/光标、防重、FOUND/EMPTY/FAILED | 初始/摘要/修改/救援/键盘 |
| 批量入口 | 0/1/36/37、原文、重搜取消 | 输入/等待/混合结果 |
| 候选 | 季数阻断、局部锁、错误 | 长标题/坏图/held/另一 item |
| 既有高风险回归 | revision/防抖/保存/未知原 body | 修改新 revision 后本地确认；部分成功/未知恢复 |
| 桌面/无障碍/安全 | 标签/状态与投影 | 三视口+缩放、键盘、reduced-motion、canary |

每包提交证据矩阵，未覆盖单元不闭包；文案/选择器同步全库搜索旧断言。
最后 story 验证并包 E 复审后，Stage 收尾执行一次总体 PRD §7 完整门禁。
源码/契约无变更不生成产物；仍执行收尾 OpenAPI/api:check 漂移检查。

## 10. 审核、提交与停止条件

团队开启后：主 Agent 规划/协调/独立审核，A 默认 Luna 开发；有问题测试者先最小红测，
B 同一修复者集中收口并复审；C 只处理已审核 HEAD 的授权发布。同一共享区一个写入者。
开发子 Agent 以 fork_turns=none 自包含范围创建，同包 follow-up 复用，不复制主全上下文。
本地逐 story 提交只有后续启动授权明确允许时执行，格式 `feat: [Story ID] - [Story Title]`，
精确暂存实现/测试/prd/progress；不 git add .。本轮只提交文档准备。

停止条件：D-01 未决不开始 B；新增 API/字段/季度编辑需求退出当前包；任何敏感泄漏、
旧版本保存、暗中 flush、all 可见化范围、未知换键、外部写、不可达主操作均阻断。
复审/迭代上限与权限受限不得标 true 或跳下一包；报告精确剩余问题，不盲重跑全量。
COMPLETE 仅所有故事实际通过且整 Stage 审核/门禁完成才成立，不从 JSON 或 Agent 自述推断。

## 11. Stage 44 交接产物

收尾在本 PRD/progress 记录真实 HEAD、代码文件、定向/完整命令结果、D-01 作用域、
新布局尺寸/焦点行为、all 集合 helper 的真实位置、N 当前语义及残余风险。
随后按[编写交接](development/add-anime-visual-prd-handoff-2026-09-18.md)核对 D-03 和共享编辑器调用者，
只编写 Stage 44 执行 PRD；不顺带开发 Stage 44/45或占用活动 Ralph 状态。
