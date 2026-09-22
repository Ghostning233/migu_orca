# mattpocock/skills 一手资料研究与 MiGuOrca 采用判断

> 研究日期：2026-09-21
> 上游快照：`mattpocock/skills` `c55ee46073ed923f86ce59a5eb3b6d895095d1b7`，仓库版本 `1.2.3`。
> 范围：安装模型、工作流、工件、跨 Agent 兼容性，以及对 MiGuOrca 的采用边界。除“本机观察”和“项目判断”外，事实均链接到一手资料。

## 结论

MiGuOrca **可以采用 mattpocock/skills 作为新的开发工作流骨架**，但它不是 Ralph 的自动循环替代品。它是一组小型、可组合的提示级技能：把澄清、领域建模、spec、纵向 ticket、TDD、双轴审核和提交串成一条人工可控的路径；它不提供 Ralph 式循环执行器、`passes` 状态机、progress 日志或自动重试上限。[上游 README 明确把“可组合、可改造、保留用户控制”作为设计目标](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/README.md)，而 [`implement` 本身只要求按 spec/ticket 实现、尽量 TDD、定期验证、最终 code review 并提交](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/engineering/implement/SKILL.md)。

因此可替换的是 MiGuOrca 当前“主 Agent + 工作包 + Ralph 状态文件”的**编排层**；项目的产品边界、测试门禁、安全约束、浏览器验证和发布授权仍应保留为仓库规范。不要把安装技能理解为这些约束会自动迁移。

三个目标 Agent 都有可行路径：

- **Codex：上游明确支持。** 使用 `npx skills@latest add mattpocock/skills`；原生 Codex plugin 仍在路线图中，当前通用途径是 skills CLI。[安装说明](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/README.md#1-get-the-skills)；[暂缓原生 Codex plugin 的 ADR](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/.agents/adr/0002-ship-as-a-claude-code-plugin.md)。
- **Claude Code（模型后端为 DeepSeek）：分发层可用。** Claude Code 可从官方 marketplace 安装整套只读 plugin，也可用 skills CLI 安装可编辑文件。上游声明技能“适用于任何模型”，因此 DeepSeek 后端不是文件格式上的障碍；但模型的工具调用、长上下文遵循度和 subagent 能力仍影响实际效果，不能由安装成功推出质量等同。[README 的模型无关声明与两种安装模式](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/README.md)。
- **DSH：若此处指本机的 DeepSeek Harness，则可通过共享 `.agents/skills` 使用，但不是 skills CLI 的具名目标。** `skills` CLI 当前列出 Claude Code、Codex 等 79 个 Agent，没有 DSH；不过 DeepSeek Harness 官方的 filesystem provider 明确扫描项目 `<projectRoot>/.agents/skills` 和用户 `<agentsHome>/skills`，并理解 `disable-model-invocation` / `user-invocable`。DSH 还支持用户用 `/name` 显式注入 user-invocable skill，正好覆盖 mattpocock 工作流技能普遍采用的手动调用方式。这是由两个官方契约推出的兼容路径，不是 mattpocock 或 skills CLI 对 DSH 的直接支持承诺。[skills CLI 支持列表与安装路径](https://github.com/vercel-labs/skills/blob/7407f3893ad4dceab546ac002c3ef806e4000c73/README.md#supported-agents)；[DSH skill 根与 frontmatter 契约](https://github.com/deepseek-ai/deepseek-harness/blob/ddefc45fbc7f8e46dd73185e68295696d1297887/packages/skill/skill-filesystem/README.md#roots-and-priority)；[DSH 的显式 `/name` 调用](https://github.com/deepseek-ai/deepseek-harness/blob/ddefc45fbc7f8e46dd73185e68295696d1297887/packages/skill/tool-skill/README.md#use-this-package)。如果“DSH”指别的工具，本结论不成立。

## 安装与更新模型

上游提供两种哲学不同的分发方式，**不应同时安装到同一 Agent**，否则会出现重复技能：

| 方式 | 适用 | 所有权与更新 |
| --- | --- | --- |
| `claude plugins install mattpocock-skills` | Claude Code | 官方 marketplace 的整套、托管、只读 bundle；随上游发布更新 |
| `npx skills@latest add mattpocock/skills` | Codex、Claude Code、其他 Agent | 可选择技能和目标 Agent；安装为可拥有、可修改的技能，使用 `npx skills update` 主动更新 |

来源：[mattpocock/skills 安装说明](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/README.md#installation-30-second-setup)。skills CLI 默认项目级安装，也支持 `-g` 全局安装；交互式安装推荐一份 canonical copy 加各 Agent symlink，`--copy` 才创建独立副本。[skills CLI 的 scope、symlink/copy 与 update 契约](https://github.com/vercel-labs/skills/blob/7407f3893ad4dceab546ac002c3ef806e4000c73/README.md#installation-scope)。

本机观察：`~/.agents/.skill-lock.json` 记录了来自 `mattpocock/skills` 的 25 个 promoted skills，安装时间为 2026-09-21；`~/.agents/skills/` 中也存在对应的 25 个目录。它们与上述上游快照中的同名技能内容一致。这个位置可被本机 DSH 的默认 user-agents root 读取，也是 skills CLI 给多个 Agent 共享 canonical copy 时的合适位置；但是否在每个 Claude/Codex 会话中实际可见，仍应分别以各 harness 的技能列表或一次无副作用调用验收，不能仅凭磁盘目录推断。

安装后还必须在每个仓库显式运行一次 `/setup-matt-pocock-skills`。它不会改 skill 文件，而是确认 issue tracker、triage 标签和领域文档布局，并写入仓库配置。[setup 文档明确说明“项目做到一半也可以运行，既有工作不会作废”](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/docs/engineering/setup-matt-pocock-skills.md)。

## 工作流哲学与主路径

上游不是“一个命令接管整个 SDLC”，而是将不同认知任务拆成独立技能。其主路径为：

1. `/grill-with-docs`：通过访谈澄清想法，同时更新领域词汇与必要 ADR。
2. 遇到必须运行或观察才能回答的设计问题时，用 `/handoff` 跨目录/会话，运行 `/prototype`，再把结论带回。
3. 小工作直接 `/implement`；多会话工作先 `/to-spec`，再 `/to-tickets`。
4. 每个 ticket 在**新上下文**中运行 `/implement`；实现过程使用 `/tdd`，结束前执行 `/code-review`，然后提交。
5. 外来 bug/请求走 `/triage`；疑难 bug 走 `/diagnosing-bugs`；超过单会话可理解范围的巨大、模糊工作才使用 `/wayfinder`，并在决策清晰后回到 `/to-spec`，而不是直接实现。

完整路由与上下文策略见 [`ask-matt`](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/engineering/ask-matt/SKILL.md)。它强调：澄清到 tickets 形成前尽量保持同一上下文；每个 ticket 则从干净上下文开始。这个边界与 MiGuOrca 当前“同一开发 Agent 跨整个工作包持续复用”的规则不同，需要在迁移时明确选择，不能混成两套同时生效的规范。

`to-tickets` 的关键不是把 PRD 横向拆成“后端、前端、测试”，而是生成可独立演示或验证、能在一个新上下文完成的**纵向 tracer bullet**，并显式声明 blocking edges；宽范围机械重构则使用 expand–contract 例外。[纵向切片与宽重构规则](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/engineering/to-tickets/SKILL.md)。这比 Ralph 的纯 priority 序列更适合暴露可并行 frontier，但也意味着现有 user story 不能机械地一对一改名为 ticket。

## 会创建或依赖的工件

| 阶段 | 工件 | 位置/载体 |
| --- | --- | --- |
| 一次性 setup | issue tracker、domain layout、triage label 配置 | `docs/agents/issue-tracker.md`、`docs/agents/domain.md`、可选 `docs/agents/triage-labels.md`，并在已有 `CLAUDE.md` 或 `AGENTS.md` 增加 `## Agent skills` 指针 |
| 领域建模 | 统一语言、难以逆转的决策 | 单上下文默认根 `CONTEXT.md` 与 `docs/adr/NNNN-*.md`；仅有真实大型多包仓库信号时才考虑 `CONTEXT-MAP.md` |
| 规格 | problem、solution、完整 user stories、implementation/testing decisions、out of scope | 发布到已配置 issue tracker 的 spec；`to-spec` 不要求单独本地 PRD 文件 |
| 执行拆分 | 纵向 ticket、AC、blocking edges | GitHub 等真实 tracker 中一 ticket 一 issue；或本地 `.scratch/<feature>/issues/<NN>-<slug>.md` |
| tracker 状态 | `needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix` | tracker labels；`to-spec`/`to-tickets` 产物可直接 `ready-for-agent`，不再重复 triage |
| 巨大模糊工作 | map、decision tickets、fog、decisions-so-far | issue tracker 的 map 与 child issues；结果是决策而非实现 |
| 实现 | 测试、代码、最终提交 | 当前分支；没有 Ralph 式 `passes` 或 progress 文件 |
| 审核 | Standards 与 Spec 两条相互独立的报告 | 两个并行 subagent 的结果聚合到当前会话；skill 不强制生成持久文件 |
| 研究 | 带一手来源引用的 Markdown | 仓库既有研究文档位置 |
| 跨 harness/目录交接 | 临时 handoff | 操作系统临时目录，不写入仓库，不复制已有 spec/ADR/issue 内容 |

setup 的精确写入集合与选取 `CLAUDE.md`/`AGENTS.md` 的规则见 [`setup-matt-pocock-skills`](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/engineering/setup-matt-pocock-skills/SKILL.md)；spec 模板见 [`to-spec`](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/engineering/to-spec/SKILL.md)；ticket 模板与本地/真实 tracker 差异见 [`to-tickets`](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/engineering/to-tickets/SKILL.md)；领域文件边界见 [`domain-modeling`](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/engineering/domain-modeling/SKILL.md)。

## MiGuOrca 的采用条件与缺口

当前仓库有 GitHub remote 和根 `AGENTS.md`，但没有 `CONTEXT.md`、`CONTEXT-MAP.md`、`docs/adr/`、`docs/agents/` 或 `.scratch/`。这正是 setup 能处理的“已有项目、尚未初始化技能工件”的形态，不构成阻断。

采用前需要作出的项目选择：

1. **tracker 选 GitHub Issues 还是 local markdown。** 上游默认推荐已有 GitHub remote 时用 GitHub；local markdown 更适合不希望把工作状态放到远端的单人项目，但不会提供原生 blocking frontier。MiGuOrca 已有 GitHub remote，若目标包含多 Agent 并行与清晰依赖图，GitHub Issues 更贴合设计；若外部写入权限或离线性优先，可选 `.scratch`。这是产品/协作选择，不应由 Agent 静默决定。
2. **把稳定规则与临时工作状态分开。** `AGENTS.md` 继续保存跨 ticket 都必须遵守的产品、安全、权限和验证规则；feature 范围与 AC 进入 spec/ticket；术语进入 `CONTEXT.md`；真正难以逆转且有权衡的决定才进 ADR。`domain-modeling` 明确禁止把 `CONTEXT.md` 当 spec、草稿或实现决策仓库。[领域工件边界](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/engineering/domain-modeling/SKILL.md)。
3. **补齐 Agent 能力差异。** `code-review` 要求两个并行 subagent 分别检查 Standards 与 Spec；`research` 也要求后台 agent。Codex 当前具备这种编排能力；Claude/DSH 路径必须做一次小范围 smoke test。缺少 subagent 时可以人工分两会话执行，但那是本地适配，不是完全按原 skill 运行。[code-review 的双轴并行约束](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/engineering/code-review/SKILL.md)。
4. **明确发布权限和 commit 策略。** 上游 `implement` 默认在当前分支提交；MiGuOrca 当前规则限制 push/PR/merge，且要求精确暂存。这些仓库规则应继续覆盖通用 skill，避免把“commit”误扩成外部发布授权。

建议先用一个未来的、小而真实的纵向工作包试运行，而不是一次性把全部 backlog 转换成 tickets。setup 本身明确支持中途采用；上游没有要求导入所有历史，也没有提供 Ralph → mattpocock 的自动迁移器。

## Ralph 文档的处理原则

上游没有要求删除旧流程工件。对 MiGuOrca，最安全的处理是按“历史证据、仍有效事实、现行流程入口”三类分离：

- **已完成 Stage 的 `scripts/ralph/archive/**`、PRD 完成记录和 progress 验证证据：保留为只读历史。** 不应转换成数百个已关闭 ticket；需要追溯时从新 issue/spec 链接它们即可。
- **现行产品边界、接口决定、验收门禁：搬到其真正归属。** 稳定规则留在 `AGENTS.md`/架构文档，领域词汇进入 `CONTEXT.md`，满足 ADR 三条件的决定进入 ADR，未完成工作进入 spec/tickets。不要把整份 progress 搬进 `CONTEXT.md`。
- **已于 2026-09-22 执行：`scripts/ralph/prd.json` 与 `progress.txt` 已在切换点冻结至 Stage 47 归档。** 新的状态只写 GitHub tracker，避免长期双写 `passes`、progress、PRD 和 issue。
- **已于 2026-09-22 执行：`ralph.sh`、Ralph prompt、项目 `.agents/skills/ralph` 和现行 Ralph 流程条款均已移出活动入口。** 历史保留在 Stage 47 归档；`AGENTS.md`、`docs/development/workflow.md` 和文档索引以 GitHub tracker 为唯一现行状态源。
- **既有 Stage PRD 不必重写。** `to-tickets` 可以从任意 plan、spec 或 conversation 工作，也可以读取传入的 spec 路径或 issue；因此既有 PRD 可作为迁移输入和长期历史规格。[`to-tickets` 的输入契约](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/engineering/to-tickets/SKILL.md#gather-context)。

## 何时切换

上游只说明“项目做到一半也能 setup”，没有规定切换必须发生在哪种本地开发状态。结合其“每个 ticket 从干净上下文开始”的原则，**不要在一个已启动的工作包内部切换状态系统**。

研究时的观察是活动分支 `ralph/stage47-single-anime-pixel`，当时 `scripts/ralph/prd.json` 中 US-363～365
仍为 `passes=false`。后续确认 Stage 47 已在混合迁移期通过 Matt 工作流验收并由 PR #79 合并；2026-09-22 已将
三条 story 标记完成并冻结到 `scripts/ralph/archive/2026-09-22-stage47-single-anime-pixel/`。这是项目的迁移决定，
不是上游的强制切换时点。

若试运行范围希望风险更低，也可以让整个 Stage 47 继续按现行流程完成，再从 Stage 48 开始；代价是继续承担两个工作包的现行流程成本。反过来，在 US-363 审核尚未闭环时立刻切换，收益有限，却会丢失最明确的完成边界。

## Token 与效率：能够确认和不能确认的事

上游声称统一领域语言能减少冗长表达和模型思考 token，但没有给出可复现实验、基线或成本数字；不能据此承诺 MiGuOrca 会降低多少 token。[README 的定性说明](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/README.md#2-the-agent-is-way-too-verbose)。同时，这套流程会主动使用长澄清上下文、每 ticket 新会话、TDD、研究 subagent 和双轴 review；质量门禁越完整，调用数未必更少。

DSH 的官方文档给出了机制层面的成本信号：catalog 成本随 model-invocable skill 数量和描述长度增长；显式 `/name` 会把完整 skill body 注入该轮；catalog 只在首次或变更时追加，不会每次主动加载全部正文。[DSH tool-skill 的 token effect](https://github.com/deepseek-ai/deepseek-harness/blob/ddefc45fbc7f8e46dd73185e68295696d1297887/packages/skill/tool-skill/README.md#model-experience)。因此应通过一次小规模试运行记录实际输入/输出 token、wall time、返工轮数、验证次数和缺陷数，再决定是否扩大采用；仅比较“会话数”会低估或高估真实成本。
