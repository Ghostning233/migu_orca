# 开发、审核与验证流程

现行全仓库规范见 [AGENTS.md](../../AGENTS.md)。本文提供按需查阅的操作细节；
不代表用户已经授权开发、团队调度或 GitHub 操作，也不取代当前 GitHub Issue。

Ralph 已于 Stage 47 收尾时冻结归档；后续流程以本文件和根 `AGENTS.md` 为准，
不从历史阶段、Issue 或会话自动继承工作包、模型或发布授权。

## 1. 三类文档各司其职

| 文档 | 面向谁 / 放什么 | 不放什么 |
| --- | --- | --- |
| 根 README | 使用者与贡献者：产品能力、启动、安全、开发流程总览 | 完整 API、Agent 操作细节 |
| 根/模块 AGENTS | Agent：稳定决策规则、目录落点、验证/权限边界 | 逐 story 记录、巨型示例、阶段计数 |
| 本文、架构、API、模块规格 | 开发者：按主题查操作细节和正式契约 | 含糊的自动发布授权 |
| 当前 GitHub Issue / spec / ticket | 本次范围、依赖、验收、进度与可复用调查结论 | 自动证明审核通过 |
| `docs/history/`、Ralph archive、历史 Stage PRD | 历史证据/兼容语义的按需追溯 | 现行指令、默认必读材料 |

整理前的 README 应称为“历史综合开发手册”：它同时承担使用指南、阶段报告、API 示例、
运行手册和 Agent 提示词，而且新旧表述冲突。旧内容已保留，不整体迁成另一份常驻大文件。

## 2. 启动与角色

1. 确认目标仓库、分支、工作区与 diff 基线；必要时只读核对远端/PR，不能仅信交接信息。
2. 读根规范、目标模块规范与当前 GitHub Issue；按需读取关联 spec、ADR 和领域文档。
3. 明确本批 ticket、不可改范围、最小验证和停止条件。
4. 一个共享工作区同一时刻只保留一个代码写入者；不在未提交改动上强行切分支。

用户明确启用团队时，主 Agent 规划并独立审核，A 做开发，B 按审核问题修复，C 处理授权的发布。
按 Issue 的纵向 ticket 设置审核检查点。
只生成提示词的请求不等于允许创建/调度子 Agent；模型和团队选择也不能从历史任务自动继承。
紧急修复可以是窄 Issue/分支任务；不能顺带完成延后的设置或下一项工作。

## 3. Matt 工作流

1. 新方向先用 `grilling` 讨论可逆/不可逆决定；涉及术语或架构边界时追加 `domain-modeling`，将稳定结论写入
   `CONTEXT.md` 或 ADR。
2. 必须查证的外部事实用 `research`；需要运行才能回答的设计问题用 `prototype`。两者的产出服务于决策，
   不替代规格。
3. 在 GitHub 创建 spec 和纵向 ticket，记录验收、阻塞关系、范围外事项与风险；满足执行条件后标为
   `ready-for-agent`。标签的实际映射见 [triage labels](../agents/triage-labels.md)。
4. 每个可执行 ticket 在干净上下文实现；适用时以 `tdd` 先建立可失败的行为证明。UI 变更必须使用
   `dev-browser` 作真实 Chromium 定向验证；疑难故障先用 `diagnosing-bugs`。
5. 完成实现后用 `code-review` 从 Standards 与 Spec 两个轴独立审核。修复、复审和证据闭环后，才关闭 Issue；
   评论记录实际命令、结果与剩余风险。

一个 ticket 完成就进入独立审核；修复/复审通过前不开始依赖它的 ticket。同一共享工作区仍只保留一个代码写入者。
Ralph 的 `passes`、progress 和脚本仅为 `scripts/ralph/archive/` 下的历史证据。

## 4. 按风险选择验证，不无界重跑

普通 ticket/修复选择与 diff 对应的检查；纯文档本地只检查链接、路径、冲突和 diff。
UI 至少有相关真实 Chromium 证据，Vitest/mock 不替代浏览器；后端契约至少验证真实 serializer/DTO。
失败先跑最小失败用例。无实质代码/环境变化不重复全量；同根因连续修复无进展应停下报告，
不是不断让新 Agent 全仓重查。用户禁止某类测试时严格遵守，并报告验证缺口。

Host 校验属于部署兼容性和安全边界：不得把局域网访问回归为仅 localhost，或通过关闭
Host 校验来“修复”公网请求。变更 Host/Origin 中间件时，必须保留并执行
`tests/api_contract/test_autobangumi_settings_security.py` 中的局域网 IPv4（含端口）放行、
公网 Host 拒绝、显式可信 Host 放行和 IPv6 ULA 拒绝/显式放行回归；若测试被移动，需同步
更新引用和等价覆盖，不得仅删除测试使门禁通过。

定向示例（替换为实际目标，不原样执行占位路径）：

```bash
uv run ruff check src/path/to/changed.py tests/path/to/changed_test.py
uv run pytest src/path/to/changed_test.py::test_target -q
# 以下在 frontend/ 内
npm run test:unit -- --run src/features/area/changed.test.ts
npm run typecheck
# UI 的浏览器验证从仓库根执行；先构建最新 frontend/dist
uv run pytest tests/browser/test_app_area.py::TestJourney::test_target -q
```

功能收尾通常完整运行一次下列门禁，具体受 Issue/用户限制；CI 对新提交独立运行：

| 执行位置 | 完整门禁 |
| --- | --- |
| 仓库根 | `uv run python -m compileall -q src tests`；`uv run ruff check src tests` |
| 仓库根 | `uv run pytest -q -m "not browser"`；`uv run migu-orca-openapi --check` |
| `frontend/` | `npm run api:check`；`npm run typecheck`；`npm run lint` |
| `frontend/` | `npm run test:unit -- --run`；`npm run build` |
| 仓库根，构建后 | `uv run pytest tests/browser/ -q`；`git diff --check` |

不要再组合“完整 pytest（含 browser）+ 完整 browser”重复跑同一浏览器套件。
`compileall` 不替代静态检查；本地 skip/环境受限写明原因，CI `MIGU_ORCA_CI=1` 缺浏览器会失败。

浏览器按 `dev-browser` skill：route mock/fake transport 隔离外部系统；held route 观察 loading，
不用在同步 handler 内 sleep。运行数据只用临时根；陈旧 `.migu_orca/storage` 会污染空列表和黄金路径。
核对内容后移动到唯一备份目录，不删除用户方案/未知缓存，不覆盖旧备份，并报告位置。
临时服务记录启动者、端口与生命周期；“Empty reply”先核实服务是否仍活着，不能直接断言业务崩溃。
环境权限导致启动失败时走产品许可机制，不通过改测试为 skip 来伪装成功。

## 5. 审核与修复

审核先确定目标分支、提交/diff 范围、Issue 状态，然后按验收逐条检查：
业务语义 → 安全/敏感值 → revision/幂等/恢复 → 契约/兼容 → 测试真实性 → 视觉/可访问性。
报告提供严重程度、文件行号、触发条件与影响；没有阻断时仍说明验证边界及剩余风险。

修复提示词最少包含：

```text
仓库与分支：具体目标；基线提交：具体 SHA。
必须修复：每项给触发条件、文件/位置、预期行为和回归场景。
不能修改：业务/契约/下一阶段/其他文件的明确边界。
最小验证：指定测试文件/用例；无变更不得重复全量。
完成条件：一轮修复、相关验证、报告 diff/结果后停；是否可提交/推送另行指定。
```

B 每轮完成后主 Agent 独立检查，不能只信 passes/progress 或“已修好”。
Agent 无响应时先检查实际进度，停止写入者再交接给接替者；不并发重复开发。
本次 CI 漏掉两个批量旧文案断言的教训：修改 UI 时搜索该页面所有测试，而非只跑新增用例。
可定向跑受影响页面，不因此让每条普通 story 都跑完整 Chromium。

## 6. 真实故障排查经验

- 能 ping、能打开浏览器首页不证明应用的 HTTP/认证/API 契约成功；区分输入规范化、
  部署主机网络、应用→上游、浏览器→应用以及上游版本/认证能力。
- 浏览器整个业务请求的等待预算与上游单次 timeout 不同。MiKan 可能多次回退、读取详情/多个 RSS；
  空结果很快而真实标题失败，不一定是网站不可达。先输出安全耗时/分类/计数，再决定修复范围。
- 用固定可操作原因区分浏览器等待超时、上游超时、连接/HTTP、标题/页面/RSS、应用内部错误；
  不在日志或 UI 放地址、凭据、RSS URL、响应原文，也不把 HTTP 200 当作业务成功。
- 长任务端点级预算应有依据与上限，配合函数入口防重、状态一致性和诚实等待提示；
  不提高全局短 API 时限，不用伪进度。顺序批量/所有 RSS 的性能改造另行规划。
- 外部写结果未知时只读核验，不能为了排错重新创建订阅；真实诊断优先只读，
  任何有副作用的真实操作都需要明确授权，自动化默认 mock。

## 7. 收尾与发布

关闭 Issue 前检查验收、代码、提交、关联文档与工作区；只有影响用户能力、启动方式或流程总览时才改 README。
后续方向从新的讨论与 Issue 开始，不预先锁定编号。
本地提交、push、PR、merge 与删分支按本次权限处理；“开发完成”本身不是发布授权。

发布已获授权时：冻结已审核 HEAD → C 推送并创建中文 PR → 等该 HEAD 全部 CI 成功 → 合并。
失败停止合并，读失败摘要交回审核/修复；不能盲 rerun、忽略失败或自动改产品行为迎合旧测试。
修复产生新提交后重新审核，再更新原 PR，让新 HEAD 正常触发 CI；这是新版本验证，不是旧失败任务重跑。
合并后核对 GitHub 实际 MERGED/SHA、远端 main 和本地状态；本地切换/同步/删分支单独按授权，
不 reset 工作区、不删除仍有未合并工作的分支。已合并不等于部署环境已重建/重启。
