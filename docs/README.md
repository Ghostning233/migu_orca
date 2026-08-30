# MiGuOrca 文档索引

本目录按“当前状态、后续规划、阶段记录、模块约束”组织项目文档。阅读时优先使用当前状态文档，历史 Stage PRD 只用于追溯当时的决策与验收范围。

## 当前状态与入口

- 项目使用、运行方式与已实现能力：[仓库 README](../README.md)
- 产品定位与总体需求：[主 PRD](MiGuOrca_main_PRD.md)
- 当前代码架构与目录边界：[架构与目录约定](design/architecture.md)
- Stage 19 以后方向与已完成阶段：[Future Stages](MiGuOrca_future_stages.md)
- 未实现事项和触发条件：[Backlog](backlog.md)
- 尚未承诺排期的可选能力：[可选功能](optional_features.md)

截至 2026-08-30，最近完成阶段为 Stage 26「Web API 契约固化与服务端边界治理」。Stage 27「前端工程化迁移与页面重构」已完成启动校准并进入开发准备，Ralph stories 为 US-197～US-209，以 Stage 26 最终 OpenAPI/DTO 为基线。

## Stage PRD

- Stage 13～15：Flask Web UI Settings、Request 可操作性与筛选语义
- Stage 16～18：真实 MiKan 详情、候选选择与 Web 主流程
- Stage 19～21：批量草案、提交前队列、偏好与修正闭环
- Stage 22～23：搜索工作台、媒体缓存与批量审核体验
- Stage 24：AutoBangumi 3.1.18 认证与订阅兼容
- Stage 25：正式番名、季数证据与共享查询计划
- Stage 26：Web API 契约、服务端安全边界与前端迁移基线（已完成）
- Stage 27：Vue/TypeScript/Vite 前端工程化与页面重构（启动校准已完成）

Stage PRD 记录单一阶段的范围、非目标、决策和验收结果。已完成阶段的 Ralph 执行快照位于 `../scripts/ralph/archive/`。

## 模块 PRD

`modules/` 中的 M00～M14 文档描述长期模块职责和安全边界。模块文档应反映当前实现；如果模块文档与已完成 Stage PRD 冲突，应先核对代码与测试，再同步模块文档，而不是沿用较早阶段的未来时表述。

## 事实来源优先级

1. 当前分支代码、自动化测试和 `scripts/ralph/prd.json` 的实际状态。
2. 根目录 `README.md`、`backlog.md` 和最近完成的 Stage PRD。
3. 主 PRD、future stages 与模块 PRD。
4. 历史 Stage PRD、归档 progress 和早期设计规格。

`docs/api/` 提供正式 OpenAPI 契约（`openapi.json`，由确定性脚本生成，覆盖全部 `/api/v1` 端点）、端点清单与敏感值边界（`endpoint_inventory.md`）；README 中的接口示例仅作用法示意，不作为完整、可生成客户端的 API 规范。
