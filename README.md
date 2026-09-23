# MiGuOrca

MiGuOrca 是面向桌面端的 Auto Bangumi 前置订阅编排工作台：从 MiKan 发现真实合集，
审核单番或批量订阅草案，保存方案，并在用户再次确认后交给 Auto Bangumi 执行。
它不是 Auto Bangumi 或 qBittorrent 的替代品，也不会绕过 Auto Bangumi 创建下载。

## 能做什么

- 添加番剧：默认单番搜索，支持直连合集；批量每行一部，最多 36 部。
- 追番方案：查看、修改本地方案和安全信息，复制方案作为重新搜索起点。
- 我的追番：同步外部状态、本地复核、显式提交、结果未知恢复及单条外部管理。
- 设置：本地存储偏好、筛选偏好与 Auto Bangumi 保存/测试/清除连接。

候选合集必须人工选择；保存并确认后进入待提交状态，不会自动外部提交。
Auto Bangumi 管理能力目前仅向已验证的 password + 精确 3.1.18 开放；
外部删除不删除本地媒体。“已更新集数”仍为待开发占位。

## 本地启动

需要 uv、Python（版本见 `.python-version`）和 Node.js/npm（CI 使用 Node 22）。

```bash
uv sync --all-groups
cd frontend
npm ci
npm run build
cd ..
uv run flask --app wsgi:app run
```

访问 `http://127.0.0.1:5000/app/add`。导航为：添加番剧 / 我的追番 / 设置。
旧入口会安全重定向；前端构建由 Flask 同源托管，运行时不需要 Node。
开发时可另开终端，在 `frontend/` 执行 `npm run dev`，API 代理到本地 Flask。

## 数据与安全

默认运行数据保存在 `.migu_orca/storage/`，不入 Git；长期使用应备份并配置独立数据目录。
Web 服务端根目录可通过 `MIGU_ORCA_WEB_STORAGE_ROOT` 指定，浏览器只能选择其下相对 profile。
Auto Bangumi 连接是唯一允许持久化秘密的配置：仅写入服务端 `MIGU_ORCA_WEB_CONFIG_ROOT` 下的
`autobangumi.json`（默认 `.migu_orca/config`），不写入浏览器存储、方案/追番文件或日志。
配置目录与业务 storage/profile 隔离；文件权限为部署敏感信息，备份时必须同样保护。配置无加密保证，
进程仍为单进程、本地监听且无内置认证，未提供认证保护时不得暴露公网。清除连接只清除该专用配置，
不会删除本地方案、追番记录、审计、任务或媒体。

本项目目前没有内置多用户认证：默认只监听本机；不要直接暴露公网或不可信网络。
远程访问需要部署方提供认证保护。`/healthz` 检查存活，`/readiness` 检查本地存储可用性，
两者不探测外部服务。MiKan 多步骤读取可能需要数分钟，批量仍逐项处理。

## CLI（离线示例）

```bash
uv run migu-orca "咒术回战第三季"
```

默认使用仓库 fixture，输出 JSON，不访问外部服务或保存方案。
真实源、保存和外部提交需要显式参数，运行 `uv run migu-orca --help` 查看。

## 开发与文档

- 开发规则与目录边界：[AGENTS.md](AGENTS.md)。不必先读历史综合手册。
- 验证、审核与发布：[开发流程](docs/development/workflow.md)。
- 产品、视觉、阶段和待办：[文档索引](docs/README.md)。
- 技术分层：[架构](docs/design/architecture.md)；接口规范：[API 文档](docs/api/README.md)。
- 旧 README 已保留为[历史综合开发手册](docs/history/README_legacy_2026-09-13.md)，
  仅供追溯，不代表当前页面、契约或开发权限。

## 参与开发

需求和进度统一记录在 GitHub Issues。开发从讨论开始，而不是从预设的 Stage 或脚本循环开始：

| 阶段 | 使用的 skill | 为什么使用 |
| --- | --- | --- |
| 明确方向 | `grilling` | 逐轮澄清目标、边界和不可逆决定，避免在含糊需求上直接改代码。 |
| 固化共同语言 | `domain-modeling`（需要时） | 将稳定术语和架构决定沉淀到领域文档或 ADR，避免不同任务各自解释同一个概念。 |
| 查证或试验 | `research` / `prototype`（需要时） | 用一手资料回答外部事实；把必须运行才能回答的问题限制为可丢弃的小实验。 |
| 规划与领取 | GitHub Issues | 一个 spec 或纵向 ticket 写清验收、依赖和范围外事项；可实施时标记 `ready-for-agent`。 |
| 实现与验证 | `tdd`、`dev-browser`（按变更适用） | 先证明预期行为；Web UI 在真实 Chromium 中验证，而不只依赖 mock。 |
| 审核与修复 | `code-review`、`diagnosing-bugs`（需要时） | 分开核对规范与需求；疑难失败先定位原因，再决定修复。 |

完整操作细节、权限与验证矩阵在[开发流程](docs/development/workflow.md)。历史 Ralph 记录保留在
`scripts/ralph/archive/`，仅用于追溯，后续开发不再使用 Ralph 状态文件或执行器。
