# Ralph Stage39 启动计划（已加载）

本目录保留 Stage39 原始计划快照；活动执行状态已加载到 `scripts/ralph/prd.json`，计划本身不是执行/提交/发布授权。

Stage 39：

- [开发 PRD](../../../docs/MiGuOrca_stage39_deployment_settings_PRD.md)
- [JSON 计划](stage39-deployment-settings/prd.json)
- 目标分支 `ralph/stage39-deployment-settings`；US-318～US-340 全部待实现。当前仅授权首批 US-318～US-320。
- 先独立验收 US-318～US-326 后端工作包，再接前端；建议每批最多 3 次迭代，最后一批 2 次。

## 获授权后加载

1. 重新核对实时 git status/log/diff、当前活动 prd/progress 与计划，不按本次基线硬编码切分支。
2. 确认新分支、写入者、模型、story批次、最大迭代数和本地提交权限。未获授权不运行 Ralph。
3. 活动 prd 属于不同阶段时，用唯一且不存在的 `archive/YYYY-MM-DD-stage38-pre-stage39-<unique>` 目录保留
   prd/progress 原文，并核对内容一致；已有归档不得覆盖。当前 Stage38 progress 与既有归档不完全一致。
4. 新分支和新状态准备都在授权后执行；用 apply_patch 将计划内容加载到活动 prd，初始化 progress，
   保留 Codebase Patterns 中新阶段有效的安全规则，不能把旧 COMPLETE/passes=true 带入。
5. 确认活动 branchName 与实时分支一致、所有 stories passes=false、23 条非空，显式指定最多迭代数启动。
6. 每批结束停下独立审核。US-326 未审核通过不得进入 US-327；全部真实完成后再进行最终门禁和用户交付。

计划 JSON 使用标准 Ralph 字段，不增加依赖或执行器自定义字段；依赖由 priority、逐条验收和开发 PRD约束。
模型遵循当时根规范/用户选择；本文件不授权团队调度、Git提交、push、PR或合并。
