# MiGuOrca

MiGuOrca 是一个面向动画订阅场景的 RSS 编排工具，目标是在 MiKanProject 与 Auto Bangumi 之间提供一层自动化协作能力。

当前已完成 Stage 7：系统可以基于仓库内静态 MiKan/RSS fixture 生成 Request，支持确认/修改/取消，并在用户显式确认提交时通过真实 Auto Bangumi HTTP adapter 输出 `ab_submit_result` 或降级 JSON。用户也可以通过显式参数启用真实 MiKanProject 数据源；默认生成和确认流程仍不会隐式访问外部系统，也不会隐式写入本地存储。只有显式传入持久化参数时，CLI 或 Web API 才会在本地 JSON 存储目录写入 Request、状态历史或 Auto Bangumi 提交结果。

## 项目目标

MVP 聚焦单番剧的订阅闭环：

1. 接收一个番剧名称。
2. 搜索并分析 MiKanProject 数据。
3. 生成可确认的 Request。
4. 用户确认后提交到 Auto Bangumi，或在失败时导出 JSON 形式的降级配置。

## 目前状态

- 默认流程不访问真实 MiKanProject、Auto Bangumi 或 qBittorrent。
- 已支持标题匹配、RSS 解析、正则筛选、字幕组选择、目录命名和 JSON 输出。
- 已支持 Request 确认、取消和受限修改；确认后的 Request 可以进入显式 AB 提交流程。
- 已建立 Auto Bangumi 提交结果契约、Request 到 AB payload 映射、fake client、真实 HTTP client adapter、失败降级 JSON 和显式配置读取。
- 已建立真实 MiKanProject 数据源 adapter、可注入 HTTP transport、搜索页解析、番剧页 RSS 源发现、真实 RSS XML 读取和安全错误归一化。
- 当前 CLI 只有在显式传入 `--source mikan` 和 `--mikan-config` 时才会构造真实 MiKan client；只有在显式传入 `--submit-ab` 和 `--ab-config` 时才会构造真实 Auto Bangumi HTTP client；只有在显式传入 `--save-request` 时才会写入本地 JSON 存储。
- 已提供 Stage 7 Flask Web UI MVP：`/` 重定向到 `/index`，页面可以生成 Request、保存 Request、列出本地 Request、读取详情，并展示已保存的状态历史和 Auto Bangumi 提交结果摘要。

## 关键约定

- Python 包名：`migu_orca`
- CLI 命令：`migu-orca`
- 配置目录：`~/.config/migu_orca`
- 日志名：`migu_orca`

## 开发约定

本项目使用 `UV` 进行 Python 包管理和命令执行。

- 安装依赖：`uv sync`
- 运行测试：`uv run pytest`
- 类型/语法检查：`uv run python -m compileall -q src`
- 运行入口命令：`uv run migu-orca "咒术回战第三季"`
- 启动 Flask Web UI：`uv run flask --app wsgi:app run`
- 接受 Request：`uv run migu-orca "咒术回战第三季" --action accept`
- 生成并保存 Request：`uv run migu-orca "咒术回战第三季" --save-request --storage-dir .migu_orca/storage`
- 列出已保存 Request：`uv run migu-orca --list-requests --storage-dir .migu_orca/storage`
- 读取完整 Request：`uv run migu-orca --load-request <request_id> --storage-dir .migu_orca/storage`
- 显式使用真实 MiKan 数据源：`uv run migu-orca "咒术回战第三季" --source mikan --mikan-config config/user/mikan-config.example.json`
- 显式执行真实 AB 提交：`uv run migu-orca "咒术回战第三季" --action accept --submit-ab --ab-config config/user/ab-config.example.json`
- 显式组合真实 MiKan 和真实 AB 提交：`uv run migu-orca "咒术回战第三季" --source mikan --mikan-config config/user/mikan-config.example.json --action accept --submit-ab --ab-config config/user/ab-config.example.json`
- 显式保存真实 AB 提交结果：`uv run migu-orca "咒术回战第三季" --action accept --submit-ab --ab-config config/user/ab-config.example.json --save-request --storage-dir .migu_orca/storage`

说明：

- 不要直接使用 `python` 执行测试或脚本。
- 需要新增依赖时，优先通过 `uv add` 或编辑 `pyproject.toml` 后再执行 `uv sync`。
- 所有后续自动化、验证和测试步骤都应默认通过 `uv` 完成。
- `--source` 默认为 `static-fixture`，会继续读取仓库内静态 catalog 和 RSS fixture；只有 `--source mikan --mikan-config <path>` 会访问真实 MiKanProject 页面和 RSS URL。
- `--save-request` 默认为关闭；未传该参数时，CLI 只输出 JSON，不会创建或写入本地存储目录。
- `--storage-dir <path>` 用于覆盖本地 JSON 存储根目录；未传时，显式保存或查询命令使用项目下 `.migu_orca/storage`。
- 本地 JSON 存储目录结构：
  - `requests/`：按 `request_id` 保存完整 Request snapshot。
  - `history/`：按 `request_id` 保存确认、取消和修改等状态历史。
  - `ab_results/`：仅在显式 `--submit-ab` 产生 `ab_submit_result` 且同时 `--save-request` 时保存 AB 提交结果。
- `.migu_orca/storage` 是运行数据目录，不应提交到 Git；如需长期保留，请由部署方在仓库外指定 `--storage-dir`。
- MiKan config JSON 字段为 `search_endpoint`、`timeout_seconds`：
  - `search_endpoint`：MiKanProject 搜索页 endpoint，由调用方显式提供；程序会追加 URL 编码后的 `searchstr` 查询参数。
  - `timeout_seconds`：真实 MiKan 搜索页、番剧页和 RSS XML 读取的超时时间，必须为正数。
- 当前真实 MiKan adapter 会从搜索结果中解析包含 `/Home/Bangumi/` 的候选番剧链接，再从番剧页的 RSS 链接或 anchor metadata 中解析字幕组名称与 RSS URL。MiKanProject 页面结构、RSS URL 形态和字段含义仍需要按实际站点版本验证。
- 错误 details、日志、fixture 和示例配置不得包含原始 HTML、原始 RSS XML、完整 endpoint URL、cookie、token 或其他敏感配置值。
- `--submit-ab` 必须和 `--action accept`、`--ab-config <path>` 显式组合使用；未传 `--submit-ab` 时不会触发 Auto Bangumi 提交流程，也不会实例化真实 HTTP client。
- AB config JSON 字段为 `endpoint`、`token`、`fallback_enabled`：
  - `endpoint`：Auto Bangumi 创建订阅的 HTTP endpoint，由部署方显式提供。
  - `token`：用于 `Authorization: Bearer <token>` 请求头。不要提交真实 token，错误 details、日志和测试快照也不得包含 token 明文。
  - `fallback_enabled`：提交失败时是否在 `ab_submit_result.fallback_config` 中输出可人工处理的降级 JSON。
- 真实 AB client 当前发送的创建订阅 payload 字段为 `title`、`rss_url`、`save_path`、`filter_rule`，并要求响应中包含 `id`、`subscription_id` 或 `ab_subscription_id` 之一。真实 Auto Bangumi API 的 endpoint、请求字段和响应字段仍需要按实际部署版本验证。
- 真实 MiKan 搜索策略和实站 RSS 解析兼容性优化仍在 [backlog](docs/backlog.md) 跟踪，不阻塞 Stage 7 Web UI MVP。

## Stage 7 Flask Web UI

Stage 7 引入一个本地可用的 Flask Web UI / 管理界面 MVP。它复用现有 CLI 编排与 Stage 6 本地 JSON 存储能力，不改变 `migu-orca` CLI 默认行为。

启动方式：

```bash
uv run flask --app wsgi:app run
```

启动后访问：

- `GET /`：重定向到 `/index`。
- `GET /index`：服务端渲染 Web UI 页面。
- `GET /healthz`、`GET /readiness`：健康检查。

Web UI 页面包含 Request 生成表单、本地 Request 列表、详情区域、状态历史和 AB 提交结果摘要。页面和 API 都不应展示 token、完整 endpoint URL、原始 HTML、原始 RSS XML 或本地绝对路径。

### Web API

Stage 7 API 的应用结构参考 `/home/ghostning/github/user_level_flask`，但只保留 MiGuOrca MVP 需要的部分：

- `src/apps/base.py` 提供 `create_app(config_name: str | None = None)`。
- `src/apps/registry.py` 通过 `ALL_BLUEPRINTS` 集中注册 Blueprint。
- `src/wsgi.py` 暴露 `app = create_app(...)`，用于 Flask CLI。
- JSON API 使用 `src/extensions/flask_api/` 的统一响应、异常处理、class-based view 和 Pydantic 校验约定。
- Stage 7 Web 模块位于 `src/apps/migu_orca_web/`，HTML 模板和静态资源与模块同目录管理。

成功响应形态：

```json
{
  "ok": true,
  "result": {}
}
```

失败响应形态：

```json
{
  "ok": false,
  "error_type": "validation_error",
  "error_message": "请求参数校验失败"
}
```

当前 API：

- `GET /api/v1/requests?storage_dir=.migu_orca/storage`：列出已保存 Request 摘要。未传 `storage_dir` 时使用默认 `.migu_orca/storage`。
- `GET /api/v1/requests/<request_id>?storage_dir=.migu_orca/storage`：读取完整 Request snapshot，并附带可用的 `history` 与 `ab_result` 只读数据。
- `POST /api/v1/requests`：生成 Request。请求 JSON 支持 `title`、`storage_dir`、`save_request`。`save_request` 未传或为 `false` 时不写入本地 storage；为 `true` 时复用 Stage 6 storage repository 保存 Request。

`POST /api/v1/requests` 示例：

```json
{
  "title": "咒术回战第三季",
  "storage_dir": ".migu_orca/storage",
  "save_request": true
}
```

### 本地验收流程

1. 生成并保存一个 Request：

   ```bash
   uv run migu-orca "咒术回战第三季" --save-request --storage-dir .migu_orca/storage
   ```

2. 启动 Web UI：

   ```bash
   uv run flask --app wsgi:app run
   ```

3. 打开 `http://127.0.0.1:5000/index`，确认页面展示 Stage 7 Web UI MVP、生成表单、Request 列表和详情区域。
4. 在页面中填写标题并选择是否保存，确认默认生成仍使用 `static-fixture`，不会访问真实 MiKan、Auto Bangumi 或 qBittorrent。
5. 通过 API 验证本地列表和详情：

   ```bash
   curl 'http://127.0.0.1:5000/api/v1/requests?storage_dir=.migu_orca/storage'
   curl 'http://127.0.0.1:5000/api/v1/requests/<request_id>?storage_dir=.migu_orca/storage'
   ```

Stage 7 暂不实现认证系统、复杂配置管理、真实 MiKan 搜索优化、批量季度订阅或 qBittorrent 直连。真实 MiKan 搜索/RSS 解析优化继续在 [backlog](docs/backlog.md) 跟踪。

示例 AB 配置：

```json
{
  "endpoint": "http://auto-bangumi.local",
  "token": "replace-with-token",
  "fallback_enabled": true
}
```

示例 MiKan 配置：

```json
{
  "search_endpoint": "https://mikan.example/Home/Search",
  "timeout_seconds": 10
}
```

## Ralph 开发流

- 当前活跃 Ralph PRD：`scripts/ralph/prd.json`
- 当前活跃阶段：Stage 7，Flask Web UI / 管理界面 MVP PRD
- 最近完成阶段：Stage 7，Flask Web UI / 管理界面 MVP PRD
- 后续待办：`docs/backlog.md`
- 已归档阶段记录：`scripts/ralph/archive/`
- Ralph 循环命令：`./scripts/ralph/ralph.sh --tool codex 8`

Stage 7 已在 Stage 6 本地 JSON Request 持久化基础上，增加 Flask app factory、Blueprint registry、统一 JSON API 响应层、Pydantic 校验、Request 查询/生成 API、服务端渲染 Web UI、状态历史展示和 AB 提交结果展示，同时保持默认 CLI 流程不隐式写入磁盘。

## 参考文档

- [主 PRD](docs/MiGuOrca_main_PRD.md)
- [Stage 1 实现规格](docs/design/stage1-spec.md)
- [架构与目录约定](docs/design/architecture.md)
