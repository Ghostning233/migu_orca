# 子 Agent 编排与长期中文 PR Agent

## 1. 目的与不可变边界

本文是根 `AGENTS.md` 的调用细节，适用于 GitHub Issue 中定义的纵向 ticket。Ralph 已归档，仅作历史追溯。
一个工作包的真实闭环是：主 Agent
给开发 Agent 自包含任务 → 同一开发 Agent 连续完成该包 → 主 Agent 独立审核 → 有问题先固化最小红测
再交修复 Agent 集中修复 → 主 Agent 复审。未闭环不得开始下一工作包。

同一共享工作区任何时刻只能有一个写入者。开发、修复与 C 发布 Agent 之间必须先停止当前写入者；
审核 Agent 只读。子 Agent 不得收到主 Agent 的完整对话、历史推理或未筛选工具输出。

## 2. Luna：Codex 内建开发/修复子 Agent（默认）

主 Agent 用协作接口创建 Luna，严格以 `fork_turns="none"` 取得干净上下文。首次提示词必须自包含：

```text
仓库与分支：<绝对仓库路径；实际分支；基线 SHA>。
工作包：<Issue/ticket 列表>；只完成此包，不进入下一包。
目标/非目标：<产品目标、不能改动的 API/模块/资产>。
必读：<AGENTS、模块规范、当前 GitHub Issue、关联规格、精确代码/测试文件>。
实现与安全边界：<草案/revision/敏感值/外部写等适用规则>。
最小验证：<精确命令；浏览器场景或明确禁止项>。
停止条件：<缺口、失败、权限或范围变化时停止并报告>。
完成时：报告实际 diff、命令/结果、遗留风险；未经授权不提交、push、建 PR 或合并。
```

调用形状（由主 Agent 填真实字段，不复制本会话）：

```text
spawn_agent(
  task_name="issue_123_development",
  model="gpt-5.6-luna",
  fork_turns="none",
  message="上述自包含提示词"
)
```

开发 Agent 在一个工作包中保持存活；主 Agent 使用 follow-up 传递同一包的补充、测试问题或集中修复任务，
不为同一 ticket 的修复新建会话。主 Agent 审核发现问题后，先按根规范固定最小红测，再将完整清单交给一个修复
Agent；复审仍有问题时继续复用该修复 Agent。只有该工作包复审通过才关闭旧会话，并为下一包创建新会话。

## 3. Fable：Claude Code 子 Agent（仅用户指定且环境可用）

当前环境实测 `claude --version` 为 2.1.270。CLI 识别的模型入口是 `--model fable`；直接传
`--model deepseek-v4-flash` 会得到 `unrecognized_model`，不能作为稳定调用方式。用户指定的 Fable
后端映射为 `deepseek-v4-flash`，但 CLI 本地输出的 canonical model 为 `claude-fable-5`，代理后端不能
仅凭本机独立验证。因此主 Agent 在报告中必须记录“请求别名 `fable`”与实际 CLI 输出，不能伪称已验证
底层 provider。

Fable 不在当前 Codex 内建 `spawn_agent` 模型列表时，按 Claude CLI 的独立会话调用；同样传入上述
自包含提示词，且不使用 `--continue` 继承不明旧上下文。常规开发应以交互 TTY 和最小工具白名单运行，
不使用 `--dangerously-skip-permissions`：

```bash
claude --model fable --permission-mode acceptEdits \
  --allowedTools 'Read,Edit,Bash(git status *),Bash(git diff *),Bash(npm run *)' \
  --session-id '<新 UUID>' \
  '<自包含的工作包提示词>'
```

同一工作包后续使用 CLI 返回的 session id 续接；主 Agent 只发送该包新增的精确任务和固定问题清单。
若模型、认证、权限、工具白名单或共享工作区写入权不满足，停止并报告；不得静默降级为复制主上下文或
使用高权限绕过。

## 4. 长期 C：中文 PR 推送/合并 Agent

C 只处理主 Agent 已独立审核的 HEAD：中文提交/PR 文案、授权后的精确暂存、push、建 PR、读取 CI 摘要、
获授权后的合并及 merge SHA/远端 main 核对。C 不开发功能、不改验收结果、不修 CI、不重跑失败 CI，也不
在无用户明确发布授权时执行任何远端写。

- 在同一 Codex 主会话中，保留一个命名稳定的 C Agent（例如 `release_c_cn`），跨工作包复用；每次发布前
  主 Agent 给它当前分支、已审核 HEAD、允许的文件、中文 PR 要点与精确发布授权。
- 累计约 20 次 PR 提交（创建或更新 PR 的提交）后，记录轮换原因，结束旧 C Agent，并以
  `fork_turns="none"` 新建 C；新 C 只接收发布职责、当前仓库/分支、授权边界与简短已合并摘要。
- Codex 子 Agent 的存活范围不跨新的主会话。需要跨主会话保留 Claude 会话时，使用下一节的 Cloud session
  id；它是会话连续性手段，不是自动获得 GitHub 权限或发布授权。

## 5. Claude Cloud：跨主会话复用的前提与已验证调用

Claude CLI 帮助提供：`--cloud [description|session_id|url]` 可创建或附着 Cloud session；它要求**交互式
TTY**。2026-09-17 本机探针结论：非交互调用会直接拒绝；TTY 调用进一步报错“Cloud 会话要求 Claude.ai
账户认证，API key 不足”。本次没有创建 Cloud session、没有读取/修改仓库，也没有远端 Git 操作。

完成 Claude.ai `/login` 后，创建长期 C 会话的最小步骤如下（创建本身不等于发布授权）：

```bash
# 交互 TTY；首次按 CLI 指引执行 /login。
claude --cloud 'MiGuOrca 中文 PR 发布 Agent：仅处理已审核 HEAD；无明确授权绝不 push、建 PR 或合并。'

# 保存 CLI 返回的 session id 或 claude.ai/code URL 到受控交接记录；下次附着同一会话。
claude --cloud '<session_id 或 claude.ai/code URL>'
```

Cloud 会话提示词仍须包含当前仓库/分支、已审核 SHA、授权动作、禁止范围、CI 停止条件与中文输出要求；绝不
将凭据、token、Cookie、完整主 Agent 上下文或未脱敏日志写入 Cloud 描述、提示词或交接记录。若没有 OAuth、
会话已失效或 Cloud 权限无法证明，使用同一主会话内的 Luna C Agent；不要尝试 API key 绕过或假定 Cloud
拥有 GitHub 写权限。
