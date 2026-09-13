# MiGuOrca 文档索引

本目录按“当前状态、后续规划、阶段记录、模块约束”组织项目文档。阅读时优先使用当前状态文档，历史 Stage PRD 只用于追溯当时的决策与验收范围。

## 当前状态与入口

- 项目使用、运行方式与已实现能力：[仓库 README](../README.md)
- Agent 常驻入口与全仓库规范：[AGENTS.md](../AGENTS.md)
- 按需查阅的验证、Ralph、审核与发布流程：[开发流程](development/workflow.md)
- 产品定位与总体需求：[主 PRD](MiGuOrca_main_PRD.md)
- 当前代码架构与目录边界：[架构与目录约定](design/architecture.md)
- Stage 19 以后方向与已完成阶段：[Future Stages](MiGuOrca_future_stages.md)
- 未实现事项和触发条件：[Backlog](backlog.md)
- 尚未承诺排期的可选能力：[可选功能](optional_features.md)

## 当前工作目标

- 前端体验全面重构的 Gate 1～3 已完成，产品方向、低保真骨架、交互规格、视觉方向和设计
  Token 均已冻结；后端 B-A、B-B、B-C1（Stage 30）、B-C2（Stage 31）已完成，
  B-D 已完成为 Stage 32；F-A 已作为 Stage 33 完成（US-257～US-265），F-B 已作为
  Stage 34 完成（US-266～US-274）并归档；Stage 35 完成（US-275～US-283）并归档；Stage 36
  完成 F-D（US-284～US-293）并归档；Stage 37 已完成 F-E（US-294～US-302）并归档；Stage 38
  已完成 F-F（US-303～US-317）并归档；F-G 经本次用户决策扩展为 Stage 39 的后端前置支撑与
  设置发布收尾，开发 PRD 已编写但尚未启动，范围见下方新阶段入口。
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
  B-C1 已完成并交付为[Stage 30：Auto Bangumi 只读能力与外部同步基础](MiGuOrca_stage30_ab_read_sync_PRD.md)，
  B-C2 已完成并交付为[Stage 31：Auto Bangumi 可靠写管理](MiGuOrca_stage31_ab_write_management_PRD.md)，
  B-D 已完成为[Stage 32：后端契约固化、兼容迁移与前端交接](MiGuOrca_stage32_contract_hardening_PRD.md)，
  F-B 已完成为[Stage 34：前端共享审核核心](MiGuOrca_stage34_shared_review_core_PRD.md)，
  F-A 已完成为[Stage 33：前端应用壳层与设计系统](MiGuOrca_stage33_frontend_shell_PRD.md)，
  F-C 已完成为[Stage 35：单番添加完整旅程](MiGuOrca_stage35_single_anime_journey_PRD.md)，
  F-D 已完成为[Stage 36：批量审核完整旅程](MiGuOrca_stage36_batch_review_journey_PRD.md)，
  F-E 已完成并归档为[Stage 37：追番方案与安全信息](MiGuOrca_stage37_plans_safe_info_PRD.md)，
  F-F 已完成并归档为[Stage 38：正式追番管理](MiGuOrca_stage38_tracking_management_PRD.md)，
  F-G 新决策见[Stage 39：部署连接配置与设置发布收尾](MiGuOrca_stage39_deployment_settings_PRD.md)。

截至 2026-09-13，最近完成阶段为 Stage 38「正式追番管理」（F-F，US-303～US-317 已全部完成并归档）。
Stage 38 不实现 F-G 设置/发布收尾。2026-09-13 用户确认新目标：仅 AB 凭据保存在部署端，取消全局
凭据弹窗、删除无用 qB/旧 Web 编排，MiKan 搜索由服务端封装。Stage 39 先独立验收新增后端支撑，
再接入 F-G；US-318～US-340 全部待实现，Gate 5 未验收。活动 Ralph 状态仍是 Stage 38，
新计划位于[待启动计划目录](../scripts/ralph/plans/README.md)，不得把文档目标当作现有能力。

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
- Stage 30：Auto Bangumi 只读能力与外部同步基础（B-C1，US-228～US-236 已完成并归档；禁止外部管理写动作）
- Stage 31：[Auto Bangumi 可靠写管理](MiGuOrca_stage31_ab_write_management_PRD.md)（B-C2，US-237～US-246 已完成；不开发正式页面）
- Stage 32：[后端契约固化、兼容迁移与前端交接](MiGuOrca_stage32_contract_hardening_PRD.md)（B-D，US-247～US-256 已完成并归档；不新增动作、不删旧端点、不开发页面）
- Stage 33：[前端应用壳层与设计系统](MiGuOrca_stage33_frontend_shell_PRD.md)（F-A，US-257～US-265 已完成并归档；不实现 F-B～F-G）
- Stage 34：[前端共享审核核心](MiGuOrca_stage34_shared_review_core_PRD.md)（F-B，US-266～US-274 已完成并归档；SafeInfo 延后到 F-E）
- Stage 35：[单番添加完整旅程](MiGuOrca_stage35_single_anime_journey_PRD.md)（F-C，US-275～US-283 已完成并归档；不实现 F-D～F-G）
- Stage 36：[批量审核完整旅程](MiGuOrca_stage36_batch_review_journey_PRD.md)（F-D，US-284～US-293 已完成并归档；不实现 F-E～F-G）
- Stage 37：[追番方案与安全信息](MiGuOrca_stage37_plans_safe_info_PRD.md)（F-E，US-294～US-302 已完成并归档；不实现 F-F～F-G）
- Stage 38：[正式追番管理](MiGuOrca_stage38_tracking_management_PRD.md)（F-F，US-303～US-317 已完成并归档；不实现 F-G）
- Stage 39：[部署连接配置与设置发布收尾](MiGuOrca_stage39_deployment_settings_PRD.md)（新增后端前置支撑 + 扩展 F-G；US-318～US-340，未启动）

Stage PRD 记录单一阶段的范围、非目标、决策和验收结果。已完成阶段的 Ralph 执行快照位于 `../scripts/ralph/archive/`。

## 模块 PRD

`modules/` 中的 M00～M14 文档描述长期模块职责和安全边界。模块文档应反映当前实现；如果模块文档与已完成 Stage PRD 冲突，应先核对代码与测试，再同步模块文档，而不是沿用较早阶段的未来时表述。

## 事实来源优先级

1. 当前分支代码和自动化测试用于核对实际行为；Ralph 状态还需对照实际 diff/验证证据。
2. 当前执行 PRD 的范围与验收、`docs/backlog.md` 和最近完成 Stage 的 handoff。
3. 主 PRD、future stages 与模块 PRD。
4. 历史 Stage PRD、归档 progress 和早期设计规格。

当前执行 PRD 决定本次范围与验收；发现代码与需求冲突应报告，不用“代码已经这样”抹掉需求。
开发指令由 AGENTS 和用户本次指令决定，不由历史记录或 passes 标记授予权限。

`docs/api/` 提供正式 OpenAPI 契约（`openapi.json`，由确定性脚本生成，覆盖全部 `/api/v1` 端点）、端点清单与敏感值边界（`endpoint_inventory.md`）；历史手册中的接口示例仅供追溯，不作为完整、可生成客户端的 API 规范。

开发指令由根/模块 AGENTS 统一维护，README 仅为产品和启动入口。历史综合手册、旧模块实现细节
保存在 `history/`，只按需追溯，不是现行规范，也不应每轮完整读取：

- [原 README 综合手册](history/README_legacy_2026-09-13.md)
- [原前端模块详细记录](history/frontend_AGENTS_legacy_2026-09-13.md)
- [原 Web 模块详细记录](history/web_AGENTS_legacy_2026-09-13.md)
