# MiGuOrca Ralph 单轮指令

此文件供脚本加载；全仓库规范以根 [AGENTS.md](../../AGENTS.md) 为入口，
流程细节见 [开发与审核流程](../../docs/development/workflow.md)。全程中文。

1. 先读根规范与改动目录的 AGENTS；检查分支、工作区、最近提交。
2. 读本目录 `prd.json`、`progress.txt` 的 Codebase Patterns/最近记录及对应执行 PRD。
   当前分支应匹配 branchName；不匹配或存在他人未提交改动时先确认，不自动提交它们或强行切换。
3. 选 priority 最小、依赖满足的未完成 story；本轮只实现该条，不顺带下一 Stage。
4. 按验收条件实现，保留安全/契约/可靠写边界；只查相关代码，不每轮读遍仓库和历史。
5. 按根规范/本条 PRD 做定向检查；UI 加载项目 dev-browser skill，用真实 Chromium。
   Stage 收尾才通常完整运行一次门禁；失败先跑最小失败用例，无变化不重复全量。
6. 验收及实际验证满足后，只将本条 passes 改为 true；追加真实 progress：
   时间/story、范围、文件、验证命令与结果、遗留风险和可复用结论。不要伪造线程链接。
   新稳定规则归 AGENTS，细节归开发文档；不向各模型模板重复追加规则。
7. 在本任务已授权的 Ralph 本地提交流程内，精确暂存本条代码、状态及 progress，
   同次提交 `feat: [Story ID] - [Story Title]`；不 git add . 或吞入其他 Agent 修改。
8. 本轮结束即交回脚本，不自行再启动循环或调度 Agent；批次上限由启动者明确。
   未明确授权，不 push、建 PR、merge 或清理分支。阻塞/验证缺口如实报告，不标完成。

所有 stories 真正完成且验证满足时，最终输出的最后一行单独写：
<promise>COMPLETE</promise>
否则正常结束，不在普通叙述或示例中输出该标记。完成标记不替代独立审核。
