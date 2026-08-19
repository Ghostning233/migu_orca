---
name: ralph
description: "运行 MiGuOrca 的 Ralph 自主开发循环（scripts/ralph/ralph.sh 流程）：读取 scripts/ralph/prd.json 与 progress.txt，确认/创建 PRD 分支，挑选最高优先级未完成 user story，实现单个 story，运行项目质量检查，按约定提交，更新 prd.json 与 progress.txt，直到全部 story 完成。Use when starting or continuing a Ralph development iteration in this repository."
user-invocable: true
---

# Ralph 自主开发循环（MiGuOrca）

执行 MiGuOrca 的 Ralph 开发流程：每个迭代完成一个 user story，保持仓库可构建、测试全绿、进度可追溯。

## 前置工作区（Ralph 状态文件）

- PRD：`scripts/ralph/prd.json`（含 `project`、`branchName`、`description`、`userStories[]`）
- 进度日志：`scripts/ralph/progress.txt`（顶部 `## Codebase Patterns` 是跨迭代的权威记忆，先读）
- 本轮指令模板（同流程，供参考）：`scripts/ralph/CLAUDE.md` / `CODEX.md` / `prompt.md`
- 归档目录：`scripts/ralph/archive/`（换分支时由 `ralph.sh` 自动归档上一轮 prd/progress）

## 执行步骤（每轮一个 story）

1. **读取 PRD 与进度**：读 `scripts/ralph/prd.json` 和 `scripts/ralph/progress.txt`。先读 `## Codebase Patterns`（跨迭代模式、陷阱、约定），再读最近几轮记录了解上下文。
2. **确认分支**：PRD 的 `branchName` 指定目标分支（本项目形如 `agent/stage19-batch-draft-workbench`，前缀是 `agent/` 而非 `ralph/`）。若当前不在该分支：先提交/保存现有工作，再从 `main` 创建或切换到该分支。若 `main` 上有未提交的 Stage 规划文档（如新阶段 PRD、direction-reset、future stages），先单独提交（`docs: 新增 Stage N 规划文档` 之类），再建分支。
3. **挑选 story**：选 `userStories` 中 `passes: false` 且 `priority` 数值最小（依赖序在前）的那个。**一次只做一个 story**。
4. **实现**：按 story 的 acceptanceCriteria 和 notes 实现。严格遵循 `progress.txt` Codebase Patterns 中的项目约定：
   - Python 包 `migu_orca`，CLI `migu-orca`，依赖与执行一律走 `uv`（`uv sync` / `uv run ...`）
   - 安全边界：外部配置与敏感值（token、endpoint、cookie、qBittorrent 凭据、原始 HTML/RSS/响应体、本地绝对路径）必须保持 request-scoped，不得进入 storage JSON、浏览器 localStorage/sessionStorage、URL、history、日志、截图或测试 trace；错误 details 必须脱敏
   - Web UI 用户态文案用中文业务词（订阅方案/订阅草案/待确认/已确认/已取消），内部状态码仅作 option value 与内部比较
   - 复用现有链路（preview-modify/modify、mikan_bangumi 详情解析、/api/v1/mikan/candidates），不得为批量卡片另造第二套筛选/解析实现
   - 注释/文档避免泄露敏感值
5. **质量检查**（全部通过才算完成）：
   - `uv run python -m compileall -q src tests`
   - `uv run pytest -q`（完整套件，含浏览器测试）
   - 若改了 Web 前端：`node --check src/apps/migu_orca_web/static/app.js`
   - 若改了浏览器测试/Web UI：`uv run pytest tests/browser/ -q`
   - 浏览器测试前置条件：仓库根 `.migu_orca/storage` 必须不存在（存在陈旧 Request 会挂掉多个浏览器测试）
6. **浏览器验证**：UI story 需要浏览器验证时，加载 `dev-browser` skill（项目用 Playwright 套件做真实 Chromium 验证，无 MCP 浏览器工具）。
7. **更新文档/模式**：若发现可复用的新模式或踩坑，追加到 `progress.txt` 顶部 `## Codebase Patterns`（简洁、通用、非 story 专属）；若改动目录附近有 `CLAUDE.md`/`CODEX.md` 且有真正可复用价值，同步更新。
8. **提交**：质量检查通过后，把所有相关变更一起提交，消息格式：
   `feat: [Story ID] - [Story Title]`（例如 `feat: US-132 - 新增批量草案数据模型与分行解析`）。不要提交损坏代码，保持变更聚焦。
9. **更新 PRD**：把该 story 的 `passes` 置为 `true`（仅改这一个字段），提交消息同上一步的 feat 或紧随其后的 `chore: mark [Story ID] passes`——**优先与代码同一次提交**，保证"story 完成"与代码一致。
10. **追加进度**：在 `progress.txt` 末尾 APPEND（绝不覆盖/替换）以下格式：

```text
## [YYYY-MM-DD HH:MM:SS 时区] - [Story ID]
Thread: https://ampcode.com/threads/$AMP_CURRENT_THREAD_ID
- What was implemented
- Files changed
- **Learnings for future iterations:**
  - Patterns discovered
  - Gotchas encountered
  - Useful context
---
```

11. **完成判定**：检查是否所有 `userStories` 都是 `passes: true`：
    - 全部完成：回复 `<promise>COMPLETE</promise>`
    - 仍有未完成：正常结束本轮，下一轮继续下一个 story

## 项目命令速查

```bash
uv sync                                  # 安装依赖
uv run pytest -q                         # 完整测试
uv run pytest tests/browser/ -q          # 浏览器套件（需 Chromium）
uv run python -m compileall -q src tests # 语法检查
node --check src/apps/migu_orca_web/static/app.js  # 前端 JS 语法
uv run flask --app wsgi:app run          # 本地启动 Web UI（手动验证）
```

## 常见陷阱（详见 progress.txt Codebase Patterns）

- 浏览器测试用 `page.route("**/api/v1/...", ...)` mock 外部依赖；非 POST 请求要 `route.continue_()` 放行到真实后端
- fixture 生成表单藏在默认收起的 `<details id="dev-fixture-disclosure">`，驱动它先调 `open_dev_fixture_panel(page)`（`tests/browser/conftest.py`）
- Seeds 区有两个 `.seed-details` 元素（完整种子/排除种子），断言必须限定到 `.complete-seed-details` / `.excluded-seed-details` / `.effective-seed-group` / `.subgroup-seed-group`
- 折叠的 `<details>` `inner_text()` 只含 summary，断言内部内容先展开
- Stage closeout story（如 US-141）需同步 README、`docs/backlog.md`、主 PRD、stage PRD、受影响的 module PRD 与 backlog 状态
