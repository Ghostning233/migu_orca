# MiGuOrca 文档索引

本目录按“当前状态、后续规划、阶段记录、模块约束”组织项目文档。阅读时优先使用当前状态文档，历史 Stage PRD 只用于追溯当时的决策与验收范围。

## 当前状态与入口

- 项目使用、运行方式与已实现能力：[仓库 README](../README.md)
- 产品定位与总体需求：[主 PRD](MiGuOrca_main_PRD.md)
- 当前代码架构与目录边界：[架构与目录约定](design/architecture.md)
- Stage 19 以后方向与已完成阶段：[Future Stages](MiGuOrca_future_stages.md)
- 未实现事项和触发条件：[Backlog](backlog.md)
- 尚未承诺排期的可选能力：[可选功能](optional_features.md)

## 当前工作目标

- 前端体验全面重构的 Gate 1～3 已完成，产品方向、低保真骨架、交互规格、视觉方向和设计
  Token 均已冻结；后端 B-A、B-B 已完成，B-C1 已规划为 Stage 30，B-C2～B-D 与前端分片
  仍待后续 Gate 4，不授权大规模页面编码。
  工作目标、候选 Stage、设计决策门和 Agent 协作顺序见
  [前端体验重构：工作目标与协作流程](frontend-ux-refactor-work-goals.md)。
- 页面体验设计与视觉评审已经作为独立工作完成。后续必须先完成后端支撑和前端分片 PRD、
  OpenAPI 边界及验收计划，再交由对应实现 Agent 分片开发。
- 第一轮产品方向和混合低保真结构已经确认，详见
  [桌面端低保真页面方案](design/frontend-ux-low-fidelity-options.md)；组件行为、状态矩阵和后端
  依赖见[桌面端前端交互规格](design/frontend-ux-interaction-spec.md)。已经通过 Gate 3 的关键页面、
  修正版和异常状态参考见[视觉方向 V1](design/frontend-ux-visual-direction-v1.md)，可编码的颜色、
  字体、间距、组件状态和桌面布局基线见[前端设计 Token V1](design/frontend-ux-design-tokens-v1.md)。
- 候选开发边界见[前端体验重构：后端支撑 PRD](MiGuOrca_frontend_ux_backend_support_PRD.md)与
  [前端体验重构：前端分片实施 PRD](MiGuOrca_frontend_ux_implementation_PRD.md)。两份文档仍按
  工作包继续分包评审；其中 B-A 已完成并交付为[Stage 28：草案一致性与原子保存确认](MiGuOrca_stage28_draft_consistency_PRD.md)，
  B-B 已完成并交付为[Stage 29：统一追番记录与可靠提交恢复](MiGuOrca_stage29_unified_tracking_PRD.md)，
  B-C1 已规划为[Stage 30：Auto Bangumi 只读能力与外部同步基础](MiGuOrca_stage30_ab_read_sync_PRD.md)，
  其余工作包仍未分配 Stage。

截至 2026-09-09，最近完成阶段为 Stage 30「Auto Bangumi 只读能力与外部同步基础」（US-228～US-235 已完成：3.1.18 password 只读 adapter、capability、external mapping、严格对账、tracking sync、`VERIFY_EXTERNAL`、OpenAPI/生成客户端与 B-C2 handoff；US-236 保留最终回归与归档）。B-C1 不实现 Auto Bangumi 外部管理写操作或正式追番管理页面。

## Stage PRD

- Stage 13～15：Flask Web UI Settings、Request 可操作性与筛选语义
- Stage 16～18：真实 MiKan 详情、候选选择与 Web 主流程
- Stage 19～21：批量草案、提交前队列、偏好与修正闭环
- Stage 22～23：搜索工作台、媒体缓存与批量审核体验
- Stage 24：AutoBangumi 3.1.18 认证与订阅兼容
- Stage 25：正式番名、季数证据与共享查询计划
- Stage 26：Web API 契约、服务端安全边界与前端迁移基线（已完成）
- Stage 27：Vue/TypeScript/Vite 前端工程化与页面重构（US-197～US-209 全部完成，旧前端已删除）
- Stage 28：草案一致性与原子保存确认（US-210～US-218 全部完成，已归档；只返回 ACCEPTED handoff，不创建 tracking record）
- Stage 29：统一追番记录与可靠提交恢复（B-B，US-219～US-227 全部完成，已归档；不实现 Auto Bangumi 管理/外部同步，B-C handoff 见 future_stages）
- Stage 30：Auto Bangumi 只读能力与外部同步基础（B-C1，US-228～US-235 已完成；US-236 为最终回归与归档；禁止外部管理写动作）

Stage PRD 记录单一阶段的范围、非目标、决策和验收结果。已完成阶段的 Ralph 执行快照位于 `../scripts/ralph/archive/`。

## 模块 PRD

`modules/` 中的 M00～M14 文档描述长期模块职责和安全边界。模块文档应反映当前实现；如果模块文档与已完成 Stage PRD 冲突，应先核对代码与测试，再同步模块文档，而不是沿用较早阶段的未来时表述。

## 事实来源优先级

1. 当前分支代码、自动化测试和 `scripts/ralph/prd.json` 的实际状态。
2. 根目录 `README.md`、`backlog.md` 和最近完成的 Stage PRD。
3. 主 PRD、future stages 与模块 PRD。
4. 历史 Stage PRD、归档 progress 和早期设计规格。

`docs/api/` 提供正式 OpenAPI 契约（`openapi.json`，由确定性脚本生成，覆盖全部 `/api/v1` 端点）、端点清单与敏感值边界（`endpoint_inventory.md`）；README 中的接口示例仅作用法示意，不作为完整、可生成客户端的 API 规范。
