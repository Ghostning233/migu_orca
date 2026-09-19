# MiGuOrca Stage 44：共享草案审核执行 PRD

| 项目 | 内容 |
| --- | --- |
| 状态 | 已编写，等待 D-03 后启动开发 |
| 基线 | `origin/main` 合并 `36ba5400dddc981a6dcd72fb69f1fc9ace30de73`（Stage 43） |
| 准备分支 | `ralph/stage44-shared-draft-review` |
| 范围 | 已选合集身份、资源/筛选审核层级、修改与单番本地确认层级 |

## 1. 目标与边界

保持主链路：名称输入 → 用户选择真实 MiKan 合集 → 服务端草案审核 → 本地保存并确认 → 追番管理再次显式确认外部提交。

本阶段只重组共享 `AnimeDraftEditor` 及其单番/批量宿主的审核信息层级。服务端草案仍是权威；前端只使用 `draft_id + revision` 与允许的 patch，不能回传完整 Request 当权威。

不新增 API/OpenAPI/generated 字段、数据库/worker、移动端、下载能力、未保存持久化、safe-info 调用、单项重搜、实时进度或外部写。不得重做 scheduler、CAS、防抖、flush、save-confirm、未知恢复或 Toast timer/store；它们只做回归。

## 2. 决策门

| ID | 状态 | 对 Stage 44 的含义 |
| --- | --- | --- |
| D-03 | 待用户决定 | 默认显示多少条安全资源样例、是否默认展开完整列表；WP-44-A 的资源默认密度不能开始 |
| D-02 | 留 Stage 45 | 不改隐藏手工勾选参与 N 部的语义 |
| D-04 | 留 Stage 45 | 不改全部完成后导航/留页语义 |

用户已确认 D-01，Stage 43 已完成；它不授权重新调整全局主题或四页业务。D-03 未决时可以调查/编写红测计划，但不得实现默认样例口径。

## 3. 工作包

### WP-44-A / US-353：合集身份、资源与筛选审核层级

作为审核草案的用户，我希望先看到已选真实合集及其公开证据，再理解当前字幕组、筛选和资源结果。

验收：

1. 默认顺序为已选合集 → 字幕/筛选与资源 → 确认条件，不重复标题、同口径规则或计数。
2. 批量宿主仅传递用户实际选择的公开候选摘要；直连/缺失/未知总集数/无封面均明确缺省，不从解析、别名、Request 或其他候选推断。
3. 有效数只对应当前字幕组；排除数只取现有排除列表；完整数只取现有分组标题集合，绝不相减推算。
4. D-03 决定默认安全样例后才实现其数量；完整资源按需展开，字幕组一级、标题二级缩进。
5. 正则、大小写、目录按需展开；等待、防抖、在途、queued、失败、zero、conflict、invalid 仍保留原有就地原因与恢复。
6. 默认/展开字段只用公开白名单；RSS URL、magnet、Cookie、凭据、原始响应、绝对路径、能力、完整 Request 和未知字段不进入 DOM/属性/URL/history/storage/trace。

### WP-44-B / US-354：修改状态与单番本地确认层级

作为审核草案的用户，我希望清楚区分“保存修改”与“保存并确认本地方案”。

验收：

1. 保存修改是次操作，说明只更新当前草案；没有待修改时禁用，等待/在途/失败/重试/恢复语义不变。
2. 单番最终确认位于审核内容之后，邻近同源资格阻断原因和“仅保存本地方案、追番管理再次确认外部提交”的说明。
3. 批量详情不增加最终保存按钮，批量最终操作继续仅由既有工具栏承载。
4. 已保存待确认、定位待核验、unknown、saved pending、部分成功继续使用现有恢复；不以 Toast 替代关键结果。
5. `AnimeDraftEditor` 已保存模式的人工保存及调用者 slot/event/props 均回归，不能误接草案自动请求。

## 4. 代码、测试与验证

实施前全库核对 `AnimeDraftEditor`、`ResourceSummary`、`CandidateCollectionList` 调用者及公开 DTO 来源。预期主要文件为 `frontend/src/features/workbench/AnimeDraftEditor.vue`、资源/筛选 helper、`WorkbenchView.vue`、`BatchWorkbenchView.vue` 与必要测试；无字段来源时省略/显示未知，不补后端。

普通 story 仅运行受影响 Vitest、typecheck、lint、build、api:check 和对应 views/DTO/CAS 契约分支。浏览器用真实 Chromium、route mock、真实 envelope、held route，覆盖单番/批量、1280/1440/1920、200% 缩放、长标题、键盘/焦点、reduced-motion、敏感 canary，以及 waiting/inflight/queued/failed/zero/conflict/invalid/save unknown/saved pending。

完成所有工作包独立审核后才运行一次完整后端、前端和 Chromium 门禁。每条实际 AC/验证满足才在 Ralph JSON 标记 passes；每包遵循开发 → 独立审核 → 最小红测 → 集中修复 → 复审，不使用 `ralph.sh`。

## 5. 停止条件与交接

D-03 未决定、公开字段来源不足、已保存模式兼容性不清或任一安全/状态矩阵缺口时停止并报告。Stage 44 完成后才编写 Stage 45；D-02、D-04 不得在本阶段代为决定。
