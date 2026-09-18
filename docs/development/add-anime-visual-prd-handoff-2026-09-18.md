# 添加番剧视觉收口：决策与后续 PRD 编写交接

## 1. 当前入口与文件角色

日期：2026-09-18。本文是决策台账和后续规划入口，不是开发或发布授权。

| 文件 | 角色 |
| --- | --- |
| [Stage 43～45 总体 PRD](../MiGuOrca_stage43_45_add_anime_visual_PRD.md) | 三阶段边界、后续候选故事/AC/矩阵/风险，不替代各阶段执行 PRD |
| [Stage 43 执行 PRD](../MiGuOrca_stage43_add_anime_entry_visual_PRD.md) | 当前六故事、五原子包、门控、定向验证、收尾与停止条件 |
| [活动 prd.json](../../scripts/ralph/prd.json) / [progress](../../scripts/ralph/progress.txt) | 仅当前 Stage 43；初始全 false，无实施证据 |
| [团队主 Agent 提示词](stage43-team-main-agent-prompt.md) | 用户后续启动团队的完整任务文本；存档不等于本轮启动授权 |
| [六图方向](../design/frontend-ux-review-mockups-2026-09-17.md) / [Token V1](../design/frontend-ux-design-tokens-v1.md) | 信息层级与视觉基线；图不规定接口或精确文案 |
| [外部分析](../design/frontend-ux-external-analysis-2026-09-18.md) | 规划输入，旧事实以代码核查修正，不是执行依据 |
| [交互规格](../design/frontend-ux-interaction-spec.md) | 稳定交互约束；§18.1 是 2026-09-07 历史缺口，不据此重做已完成接口 |
| [旧 FE 问题记录](../design/frontend-review-issues-2026-09-17.md) / [旧交接](frontend-ux-followup-handoff-2026-09-17.md) | Stage 40～42 来源线索，不能直接作为未完成清单 |

Stage 41/42 的执行证据读取各自 archive，不再用活动 progress 追溯：
[Stage 41](../../scripts/ralph/archive/2026-09-18-stage41-add-anime-ux/progress.txt)、
[Stage 42](../../scripts/ralph/archive/2026-09-18-stage42-global-notification/progress.txt)。
切换前逐字比对 Stage 42 活动 JSON/progress 与归档，内容一致，保留原归档，不重复造快照。

## 2. 产品决策台账（唯一状态来源）

只有用户实际决定后更新状态/日期/原意，不能把建议或默认预选当成回答。
D-01 已于 2026-09-18 获用户明确批准，原意为“允许全局共享主题对齐 V1，并做四页回归”。
批准范围包含共享主题与基础控件的颜色、尺寸和焦点样式；四页为添加番剧、追番方案、
追番管理、设置，不改变其他页面业务。D-02～04留在对应后续阶段前处理。

| ID | 状态 | 问题/备选 | 建议与范围 |
| --- | --- | --- | --- |
| D-01 | 已确认（2026-09-18） | 全局共享主题与基础控件对齐 Token V1，并做四页回归 | 已解除 Stage 43 产品前置门控；只改视觉、不改其他页面业务，不再保留仅添加页方案 |
| D-02 | 待用户决定 | 隐藏手工勾选参与 N，或 N 继续只取当前可见勾选 | 建议全手工勾选资格集合；当前实现取可见项，Stage 43 禁止变更 |
| D-03 | 待用户决定 | 默认安全资源样例数量/是否继续完整展开 | 建议最多 3 条，全部按需展开；Stage 44 默认密度，不改变资格 |
| D-04 | 待用户决定 | 全部完成自动进管理，或留结果页 | 原冻结规格自动进管理，建议补齐；改留页须同步规格；失败/未处理始终留页 |

已经确定：保留确认全部且完整批次范围；保留 N 部；可见项全选仍明确可见；人工选合集；
本地/外部两次确认；不新增未保存 safe-info、单项批量重搜、逐条实时进度、刷新恢复；
更新集数不推算。这些不重复交用户决策。

## 3. 当前事实与待核实资料

基线为 `334c8e69dbcc7c27be8ab482f8ccb142081db0b7`。实施前核对实时 HEAD。
以下是静态事实，不是运行验证：

| 事项 | 当前事实 | 后续核实 |
| --- | --- | --- |
| all 范围 | visibleItems→selectable→请求 items；省略 item_ids 仅全部请求描述符 | Stage 43 红测/修复/实际请求；交接真实 helper 位置 |
| N 范围 | 可见且勾选可确认，隐藏意图保留 | D-02 后范围/计数/弹窗/请求同时改，不只按钮数字 |
| 批量身份摘要 | 未传 candidateSummary；单番已有公开投影 | Stage 44 是否仍缺、所选候选如何内存保存/清除，直连未知不补造 |
| 封面 | 候选仅同源 opaque poster；当前 SelectedCollectionSummary 不含封面 | 若扩展示投影只从真实已选公开字段，不新增 API、不从 snapshot 猜来源 |
| 资源统计 | helpers 有 effective/excluded/complete groups，口径不同 | 核对选中来源、去重、零值与失败状态；不可相减推排除/集数 |
| 未保存全部信息 | 现有快照显式字段折叠，未调用 safe-info | 默认和展开字段白名单/脱敏/DOM canary，不把宽松快照当安全 DTO |
| saved 模式 | AnimeDraftEditor 还用于已保存方案编辑 | Stage 44 全部调用者、slot/event/props、人工保存回归 |
| 导航 | 普通批量结果定位失败，其他完成路径未完整体现原规格 | Stage 45 D-04、first unprocessed、tracking_ready=false恢复、公开深链 |
| 未知恢复 | saveOperation 冻结 body；saved confirm 走 accept/tracking | 同键绑定、重放不换 revision/范围；不能套外部写恢复 API |
| 通知 | Stage 42 已完成，模态/Toast 同 overlay 的 DOM 顺序取舍仍在 | 仅层级/焦点/就地反馈回归，不重做 store/timer |

旧截图目录 [2609181532-web-ui-old](../design/assets/frontend-ux/archive/2609181532-web-ui-old/)
只保存静态对照；不能补记未经确认的 screenshot commit/构建版本。

## 4. Stage 44 编写检查单

只有 Stage 43 闭环后编写并切换，不现在造预期通过的执行状态。

1. 读 status/log/diff、Stage 43 PRD 与 progress 最近收尾，核对代码/测试，不只 passes。
2. 记录实际合并/开发 HEAD及 D-01 作用域，重新判断 Stage 44 工作包大小。
3. 冻结 D-03；以总体 PRD §5 承接身份、筛选/资源、修改/确认故事，不重做调度。
4. 全库 rg AnimeDraftEditor/ResourceSummary 调用，列全 saved 模式回归及事件/slot兼容。
5. 对已选候选、直连、无总集数、无封面分别定义来源/占位；季度不新增 patch。
6. 逐字段列默认/展开公开白名单；只用已允许字段，新增字段依赖另立后端 PRD。
7. AC 必须覆盖 waiting/inflight/queued/failed/zero/conflict/invalid/save unknown/saved pending/定位失败。
8. 指定 scheduler/session/journey 与两个宿主 Vitest、views/DTO/CAS 契约定向分支、真实 Chromium连续链。
9. 保留三视口+200%缩放、长标题/完整资源、键盘/焦点、reduced-motion、canary矩阵。
10. 故事一轮可完成、按依赖排序、分配下一可用 US 编号；JSON初始 false/notes空。
11. 旧活动状态先核对/归档到唯一目录，再更新 JSON/progress/索引；不覆盖不明归档。

预期输出：单独 Stage 44 执行 PRD、Ralph JSON/progress、真实文件/测试/状态/门禁矩阵、
更新本台账与索引。不能把“批量季度未提供”扩大成后端季度编辑。

## 5. Stage 45 编写检查单

1. 核对 Stage 44 实际 HEAD/闭环证据、右栏尺寸/焦点/字段和 pending 映射。
2. 冻结 D-02、D-04，不把建议当决定；承接总体 PRD §6 三候选包。
3. 使用真实确认资格来源，明确 total/visible/checked/eligible/blocked/inflight/failed 的口径。
4. 区分可见项全选、N部确认、完整批次 all；全部持续可见、范围独立。
5. 给两入口定义弹窗集合/版本变化拒绝及未知原意图恢复，不从当前筛选重算重放。
6. 结果按 results[]，并区分成功、确定失败、saved pending、unknown、tracking未定位。
7. 固定栏多行高度/预留、长错误与末项命中，三视口/缩放下实测而非仅 class断言。
8. 1/12/36、查看/勾选、隐藏详情、异常循环、稳定排序、部分成功首失败/首未处理焦点矩阵。
9. 给实际导航行为写新验收/旧规格修订，不声称未见代码的自动导航已经回归通过。
10. 独立执行 PRD/Ralph状态/归档/索引，下一 US编号重新查占用，Stage收尾一次完整门禁。

## 6. 文档维护与启动就绪结论

正式执行规范优先于旧报告和截图；本轮不改历史 Stage 40～42正文来抹掉当时事实。
只在旧问题/交接加现行入口和来源说明，docs索引指当前PRD，历史progress指archive。
根 README/AGENTS不追加故事日志，future stages不复制整份执行AC。

Stage 43 全部工作包的产品前置已满足，可按 A → B → C → D → E 的依赖顺序启动开发；
前包独立审核闭环后才进入下一包。当前全部故事尚未开发，D-02～04不阻断 Stage 43。
本次文档与本地提交授权不等于开发、push/PR/merge授权。用户把团队提示词作为下一请求发送后，
主 Agent 才执行其开发/本地提交许可，并在决策门前停止依赖工作。
