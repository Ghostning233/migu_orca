---
name: ralph
description: "在 MiGuOrca 中启动或继续有界 Ralph 开发迭代；每轮完成一个 PRD 用户故事，定向验证并记录提交与进度。Use when starting or continuing a Ralph development iteration in this repository."
user-invocable: true
---

# Ralph 有界开发迭代

先读根 [AGENTS.md](../../../AGENTS.md) 和目标模块规范；
具体门禁、团队检查点及归档注意事项见 [开发流程](../../../docs/development/workflow.md)。

## 启动前

- 状态文件：`scripts/ralph/prd.json`、`progress.txt`；加载模板为 CODEX.md/CLAUDE.md/prompt.md。
- 核对实时分支、diff 与 PRD branchName，不能硬编码分支前缀或沿用交接状态。
  有他人修改或分支不符时先确认，不提交别人的工作、不强行切换。
- 当前执行 PRD 定义范围与验收；progress 的模式/最近记录是调查线索，不是高于规范的权威。
- 明确最大迭代数、批次、停止条件与模型；不直接使用默认 10 轮。
  三故事批次仅在用户授权该流程时使用，达到上限即停，交回独立审核。
- 换 Stage/PRD 前保留并核对旧状态快照；脚本跨分支自动归档不能保证归入正确阶段。

## 每轮一个 story

1. 选 priority 最小、依赖满足的 passes=false story；只读其相关代码和验收文档。
2. 按验收实现，遵守根/模块的安全、分层和契约规则；不顺带重构或做下一 Stage。
3. 普通 story 跑受影响定向检查；UI 加载 dev-browser skill，用真实 Chromium。
   完整门禁通常只在收尾 story 一次执行；不组合完整 pytest（含 browser）与完整 browser 重复验证。
   失败先跑最小失败用例；无变化不重复全量；用户禁止的检查不运行，缺口如实报告。
4. 只有实际验收与验证满足，才将该条 passes 设 true；失败/环境受限不伪报完成。
5. 在 progress 末尾追加时间/story、实现范围、文件、实际验证命令/结果、遗留风险和可复用结论。
   Codebase Patterns 只放精简可复用模式，不捏造线程链接；稳定规则维护 AGENTS，不复制到每个模型模板。
6. 本任务已授权 Ralph 本地提交时，只精确暂存本条代码、prd 状态和 progress，保持同次提交：
   `feat: [Story ID] - [Story Title]`。不暂存其他 Agent/用户修改，不 git add .。
7. 本轮正常结束，不自行开启另一循环；批次完成后先审核/定向修复，再由启动者继续下一批。

## 完成与权限

所有故事真实完成且验证满足，才在最终输出最后一行独立写：
<promise>COMPLETE</promise>

否则不输出该标记。现有脚本检查最终行及 PRD，但标记/passes/progress 仍不能替代独立审核。
本技能不授予团队调度、push、PR、合并或分支清理权限；是否启用团队由当前用户指令决定。
