# MiGuOrca

MiGuOrca 是面向桌面端的 Auto Bangumi 前置订阅编排工作台：从 MiKan 发现真实合集，
审核单番或批量订阅草案，保存方案，并在用户再次确认后交给 Auto Bangumi 执行。
它不是 Auto Bangumi 或 qBittorrent 的替代品，也不会绕过 Auto Bangumi 创建下载。

## 能做什么

- 添加番剧：默认单番搜索，支持直连合集；批量每行一部，最多 36 部。
- 追番方案：查看、修改本地方案和安全信息，复制方案作为重新搜索起点。
- 追番管理：同步外部状态、本地复核、显式提交、结果未知恢复及单条外部管理。
- 设置：本地存储偏好、筛选偏好与外部服务连接测试。

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

访问 `http://127.0.0.1:5000/app/add`。导航为：添加番剧 / 追番方案 / 追番管理 / 设置。
旧入口会安全重定向；前端构建由 Flask 同源托管，运行时不需要 Node。
开发时可另开终端，在 `frontend/` 执行 `npm run dev`，API 代理到本地 Flask。

## 数据与安全

默认运行数据保存在 `.migu_orca/storage/`，不入 Git；长期使用应备份并配置独立数据目录。
Web 服务端根目录可通过 `MIGU_ORCA_WEB_STORAGE_ROOT` 指定，浏览器只能选择其下相对 profile。
凭据只用于临时会话和单次请求，不写入浏览器存储、方案文件或日志。

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

- Agent 开始开发：[AGENTS.md](AGENTS.md)。不必先读历史综合手册。
- 验证、Ralph 和审核：[开发流程](docs/development/workflow.md)。
- 产品、视觉、阶段和待办：[文档索引](docs/README.md)。
- 技术分层：[架构](docs/design/architecture.md)；接口规范：[API 文档](docs/api/README.md)。
- 旧 README 已保留为[历史综合开发手册](docs/history/README_legacy_2026-09-13.md)，
  仅供追溯，不代表当前页面、契约或开发权限。
