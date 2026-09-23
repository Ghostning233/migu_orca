# MiGuOrca Agent 开发规范

本文件是全仓库的常驻开发入口，只保留稳定边界和必要背景。全程使用中文交流。
更深目录的 `AGENTS.md` 补充该目录约束；用户本次指令决定任务范围与权限。

## Agent skills

### Issue tracker

本仓库使用 GitHub Issues 跟踪需求、规格与开发任务。详见 `docs/agents/issue-tracker.md`。

### Triage labels

使用 Matt Pocock Skills 的五种默认 triage 标签。详见 `docs/agents/triage-labels.md`。

### Domain docs

本仓库采用 single-context 领域文档布局。详见 `docs/agents/domain.md`。

## 开始前与按需阅读

- 先检查 `git status --short --branch`、最近提交及目标 diff，保留用户和其他 Agent 的修改。
- 开发工作先读当前 GitHub Issue（规格、依赖、验收）及其评论；不按交接文案猜当前分支、完成状态或是否已合并。
- 前端任务读 `frontend/AGENTS.md`；Web API 任务读 `src/apps/migu_orca_web/AGENTS.md`。
- 需要流程细节时读 [开发与审核流程](docs/development/workflow.md)；需要分层细节时读
  [架构](docs/design/architecture.md)，产品/视觉任务从 [文档索引](docs/README.md) 找目标规格。
- README 提供易读的开发流程总览；本文件和开发流程文档才是可执行规范。不要每轮读遍历史手册、归档日志或生成文件。
  代码和测试用于核实实际行为；当前 GitHub Issue 决定本次应实现什么，差异需报告，不能用现状抹掉需求。

## 项目背景与改动落点

MiGuOrca 是桌面端、本地优先的 Auto Bangumi 前置订阅编排工作台，不是下载器。
主链路：名称输入 → 人工选择真实 MiKan 合集 → 服务端草案审核 → 保存并确认 →
追番管理待提交 → 用户再次显式确认外部提交。单番为默认首页；批量支持 1～36 部，典型 12 部。
一级导航固定：添加番剧 / 我的追番 / 设置。

项目是模块化单体：Python 3.13（精确版本见 `.python-version`）+ Flask/Pydantic，
前端 Vue 3 + TypeScript strict + Vite/Pinia。依赖分别由 uv 与 npm 管理。
Flask 在 `/app/` 同源托管前端构建；目前没有数据库、常驻后台 worker 或多用户认证系统。

| 路径 | 职责与改动入口 |
| --- | --- |
| `src/apps/base.py`、`src/apps/registry.py`、`src/wsgi.py` | Flask 工厂、Blueprint 注册、服务入口 |
| `src/apps/migu_orca_entry/controllers/entry_controller.py` | CLI、生成 Request 的总编排 |
| `src/apps/migu_orca_web/` | `routes_*` 输入适配；`*_service` 编排；schema/DTO/serializer 边界 |
| `src/extensions/flask_api/` | JSON envelope、校验、HTTP 错误分类与脱敏 |
| `src/batch_engine/`、`catalog_engine/`、`mikan_engine/` | 名称/查询计划、fixture 匹配、真实 MiKan 与缓存 |
| `src/rss_engine/`、`subscription_engine/`、`request_engine/` | 资源解析筛选、字幕组/命名、方案状态与受限修改 |
| `src/tracking_engine/`、`ab_engine/`、`storage_engine/` | 追番状态/操作、AB 适配、本地 JSON repository |
| `src/qbittorrent_engine/`、`src/shared/` | qB 只读连接测试；跨模块稳定契约/错误/规则 |
| `frontend/src/{features,app/composables,components}/` | 页面、旅程/草案会话、共享组件；不复制业务规则 |
| `docs/api/`、`tests/api_contract/`、`tests/browser/` | 正式契约、契约回归、真实 Chromium 旅程 |

`apps` 可依赖 engine；engine 不反向依赖 `apps`；`shared` 不依赖具体 engine。
HTTP/认证细节留在 adapter，持久化留在 repository，纯规则不混入 IO。
运行数据主要为本地 JSON；草案与部分缓存在进程内，不能未经设计便增加多 worker。

## 不可破坏的边界

- 真实 MiKan 合集必须由用户最终选择；AI/规则提示不等于真实季数证据。
  不绕过 Auto Bangumi 创建 qBittorrent 下载，不顺带实现下一 Stage 或移动端。
- Auto Bangumi 凭据的产品目标是保存在部署端专用私有配置，跨页、刷新和重启保留；
  实现与唯一持久化例外见 [Stage 39 PRD](docs/MiGuOrca_stage39_deployment_settings_PRD.md)。
  当前实现仅允许 AB 秘密进入服务端专用配置文件，不把新目标误用于其他外部系统。秘密不进入业务 JSON、公开 DTO、
  URL/history、浏览器存储、日志、其余 DOM/属性、截图或 trace；必要编辑表单不是复制许可。
  Cookie、原始响应、完整 RSS URL、magnet、本地绝对路径仍不得公开或额外持久化。
- 首期仅保存 AB 连接；MiKan 搜索配置由服务端封装，不要求用户配置。qB 独立连接测试及
  已有正式替代的旧 Web 编排按 Stage 39 核对后退役；不接管 qB 下载，不删除历史运行数据。
- 草案权威在服务端：前端只用 `draft_id + revision`，不回传完整 Request 当权威；
  保存复用预留 → 持久化 → 提交/释放。方案确认与外部提交是两次不同确认。
- 追番状态以服务端 TrackingRecord/TrackingOperation 为准；动作取服务端允许值与 capability，
  未知值 fail closed。外部管理写只允许 password + 精确 Auto Bangumi 3.1.18 已验证能力。
- 外部写保留 confirm、幂等键、expected revision、写前读取、写后回查与结果未知恢复。
  未知结果不等于确定失败；未决意图不得换键、换绑定或盲目重发。纯本地复核不要求 AB 凭据。
  部署配置更换不能改绑旧 operation 或复用另一 AB 实例的外部映射；新绑定必须经后端验证。
- 外部删除固定 `file=false`，保留本地方案、追番记录、审计、任务和已下载媒体。
  提交方式是一次操作的语义（下载现有资源 / 持续追番），不是追番方案字段；「下载现有资源」按
  至少一次语义把当前符合方案的资源交给 Auto Bangumi 加入下载，不建立受控外部订阅，失败时只说
  「提交失败，可重新提交」，不承诺安全重试（ADR-0001）。
  “已更新集数”仍是待开发占位，绝不从 RSS/种子数猜测。
- Web `storage_dir` 只允许服务端根下的相对 profile；空值落服务端根，不能回退 CLI 默认。
  CLI 显式路径是另一信任边界。未提供认证保护时不直接暴露公网。

## 开发、协作与权限

- 主 Agent 默认负责规划、审核与协调；直接开发限于文档、轻量修复或用户明确要求。
  未启用团队时不自行创建子 Agent；用户启用后再按开发 A → 独立审核 → 修复 B → 提交 C 分工。
  GPT 团队的开发 Agent 默认用 gpt-5.6-luna；用户指定且运行环境提供时可改用 Claude Fable
  （实际模型 `deepseek-v4-flash`）。无特殊依赖严禁复制主 Agent 全量上下文，必须以
  `fork_turns="none"` 创建干净子 Agent，由主 Agent 提供自包含的范围、边界、验证与停止条件。
- 同一工作包优先复用一个开发 Agent，通过 follow-up 连续推进；每批结束声明实际协作/模型模式，
  并分别用一句话概括给开发、测试、审核、修复 Agent 的提示词。详细规则见
  [开发与审核流程](docs/development/workflow.md)。工作包的开发、审核、修复与复审闭环前不得
  更换/关闭其开发或修复 Agent；仅闭环后才为下一工作包新建 Agent。
- 新需求遵循 Matt 工作流：先用 `grilling` 讨论方向，必要时用 `domain-modeling` 固化术语/不可逆决策，
  再以 GitHub Issue 承载规格、纵向 ticket、依赖和验收。实现前确认该 Issue 已具备 `ready-for-agent` 标签；
  不再创建 Ralph Stage、`passes` 或 progress。
- 中文 PR 推送/合并由长期 C Agent 负责，跨工作包/Stage 尽量复用；累计约 20 次 PR 提交后才轮换。
  C 仅处理已审核 HEAD，且每次仍须用户明确发布授权；跨主会话复用与 Luna/Fable 调用细节见
  [子 Agent 编排](docs/development/subagent-orchestration.md)。
- 已启动的工作包必须跑完其约定的开发、定向验证、独立审核、红测、集中修复与复审闭环；
  任一 AC、固定问题清单或验证矩阵单元未覆盖/未通过时，不得以部分结果、后续风险或
  Agent 自述在中途交回，继续复用同一修复 Agent 收口至工作包边界。
- 修复指令指定仓库/分支、文件或问题、不能改的范围、最小验证与停止条件。
  同一共享工作区只允许一个写入 Agent；审核/提交前确认写入者已结束。
- 用户只要求诊断/静态审核时不擅自实现；禁止的 pytest/浏览器检查严格不运行。
- 只暂存本任务相关文件，不 `git add .` 吞入其他修改；不 reset --hard、checkout -- 或强推。
  未明确授权，不 push、建 PR、合并或清理分支。任务完成不自动继承上一任务的发布授权。

## 验证、审核与成本控制

- 普通 ticket/修复只跑受影响用例；UI 用项目 `dev-browser` skill，在真实 Chromium 做定向验证。
  完整后端/前端/Chromium 门禁通常在功能收尾执行一轮，CI 对新提交独立验证。
- 失败先跑最小失败用例；无代码/配置变化不重复同一全量检查；文档整理只做文档检查。
  `compileall` 只证明语法，不替代 Ruff 或测试；skip/Agent 自述不算验证通过。
- 测试前隔离运行数据，确认 `.migu_orca/storage` 不污染浏览器/黄金路径；先核对内容并
  移到唯一备份目录，不删除未知数据，不覆盖已有备份。临时服务由启动者管理和收尾。
- 按 Issue acceptance criteria 独立审核：优先业务、安全、状态一致性、并发/幂等、契约漂移、
  敏感泄漏与测试真实性。报告按严重度给文件/行号；无阻断也说明剩余风险。
- 审核应一次性形成完整问题清单；先由测试 Agent 固化最小红测，再交同一个修复 Agent 集中收口。
  复审仍有阻断时继续复用该 Agent 和剩余清单，不重启整套流程、不因预算阈值遗留半成品。
- API/契约迁移同时核对源 schema/route/OpenAPI 生成源、生成产物与全部调用者；不得以生成后
  字符串过滤、字段改名、兼容别名或仅类型通过来掩盖旧秘密/旧请求语义。源—产物—调用三层
  都清零后，才可认定契约迁移完成。
- Issue 标签、评论或关闭状态都需核对代码和证据；不能当作审核结论。
  修复重复无进展时报告，不无界循环或靠全量重跑碰运气。
- 可复用结论、实际验证命令/结果和遗留风险记录在 Issue；历史 Ralph 阶段只在归档中追溯，
  不往 README/AGENTS 累加逐 ticket 日志，不伪造线程链接或测试结果。
- 本会话经验：先区分浏览器总超时与上游单次超时、网络/HTTP/解析/内部故障；
  HTTP 200 仍可能带 FAILED/部分成功业务结果。长任务使用端点级有界预算与防重锁，
  不提高全局等待时间。页面文案/行为变更同步检查对应 Vitest 和浏览器断言。
- 发布授权生效后，C 只处理已审核 HEAD；任何 CI 失败停止合并，读摘要交回修复，
  不盲重跑或绕过。合并后核对实际 merge SHA、远端 main 和本地状态，不删未合并工作。

## 文档维护

根 AGENTS 尽量保持约 100～150 行，模块 AGENTS 更短；长度是维护目标，不是装满指标。
只保留会改变开发决策的稳定规则，细节按需放开发文档/模块规格；事实变化时更新或删旧规则。
历史快照不能变成现行指令。命令、门禁和分层事实同时以项目配置、CI、当前代码核对。
