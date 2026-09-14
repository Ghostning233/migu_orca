# Stage 39 当前交接（2026-09-14）

本文件供新的 Terra Medium 主会话一次性接手使用；它是当前快照，不取代 PRD、代码或测试事实。
接手后先核对 `git status --short --branch`、HEAD、`scripts/ralph/prd.json` 和 progress 最近记录。

## 当前状态

- 仓库：`/home/ghostning/github/migu_orca`
- 分支：`ralph/stage39-deployment-settings`
- 基线 HEAD：`bcd616a`（工作包 E 开始；以当前 git HEAD 为准）
- US-318～US-337 已完成；US-338～US-340 已完成候选验收记录，等待独立审核。
- 未 push、未建 PR、未合并；Stage 39 中间分支不能作为完成品部署。
- 当前前端与后端均使用保存连接 generation；业务请求仅携带 `connection_ref` 与
  `configuration_revision`。旧提交/队列 Web 写端点已退役，历史 reader 仍保留只读迁移能力。

## 新主会话启动方式

- 主 Agent 使用 gpt-5.6-terra medium，只读本文件、根/目标模块 AGENTS、当前 PRD 与 progress 最近记录。
- 不导入旧聊天记录，不重新读取所有历史 Stage 文档；遇到具体语义再按关键词查代码和 Stage 39 PRD。
- 先向用户确认工作包 A 的范围/验收矩阵，再创建一个 `fork_turns="none"` 的 gpt-5.6-luna
  持久开发子 Agent；提示词必须自包含，严禁复制主 Agent 全量上下文。
- 同一 Luna 身份连续完成工作包，包内逐 story 验收、提交和记录；不调用 `ralph.sh` 创建逐 story 进程。

## 下一工作包 A

范围为 US-327～US-330，作为一次设置与追番保存连接的原子迁移：

1. US-327：设置页保存、测试、更换和清除 AB 连接。
2. US-328：追番提交与重试切换到保存连接引用。
3. US-329：修改、启停、刷新、删除切换到保存连接引用。
4. US-330：同步、探测、未知结果恢复切换，并移除追番页凭据弹窗。

开发前先建立 AC—文件—测试矩阵，确认 generated/OpenAPI 与调用者在各 story 边界保持可编译；
共享门禁在工作包原子切换完成后集中运行。不得提前实现 US-331、删除 US-333 以后端点或执行发布。

工作包结束后按[过渡流程](stage39-transition-workflow.md)统一独立审核，并报告模型/协作模式、
各子 Agent 一句话提示词摘要、提交、实际验证和剩余风险，然后停下等待用户讨论下一工作包。
