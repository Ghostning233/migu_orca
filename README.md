# MiGuOrca

MiGuOrca 是一个面向动画订阅场景的 RSS 编排工具，目标是在 MiKanProject 与 Auto Bangumi 之间提供一层自动化协作能力。

当前已完成 Stage 10：系统可以基于仓库内静态 MiKan/RSS fixture 生成 Request，支持 CLI 与 Web UI 中确认/修改/取消，并在用户显式确认提交时通过真实 Auto Bangumi HTTP adapter 输出 `ab_submit_result` 或降级 JSON。用户也可以通过显式参数启用真实 MiKanProject 数据源；默认生成和确认流程仍不会隐式访问外部系统，也不会隐式写入本地存储。只有显式传入持久化参数时，CLI 或 Web API 才会在本地 JSON 存储目录写入 Request、状态历史或 Auto Bangumi 提交结果。Stage 10 在 Stage 9 浏览器自动化测试基础上补强 Web UI Request 操作入口，包括确认、取消、受限修改、状态历史刷新和统一通知反馈。

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
- 已提供 Stage 8 Flask Web UI：`/` 重定向到 `/index`，页面可以生成 Request、显式保存 Request、记住浏览器端本地偏好、搜索/筛选/排序本地 Request、读取分组详情，并展示已保存的状态历史和 Auto Bangumi 提交结果摘要。

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
- 真实 MiKan 搜索策略和实站 RSS 解析兼容性优化仍在 [backlog](docs/backlog.md) 跟踪，不属于 Stage 8 Web UI 可用性范围。

## Stage 8 Flask Web UI

Stage 8 继续使用 Stage 7 引入的本地 Flask Web UI / 管理界面 MVP，并补强可用性。它复用现有 CLI 编排与 Stage 6 本地 JSON 存储能力，不改变 `migu-orca` CLI 默认行为，也不引入 React/Vite 等前端构建链。

启动方式：

```bash
uv run flask --app wsgi:app run
```

启动后访问：

- `GET /`：重定向到 `/index`。
- `GET /index`：服务端渲染 Web UI 页面。
- `GET /healthz`、`GET /readiness`：健康检查。

Web UI 页面包含 Request 生成表单、本地 Request 列表、详情区域、状态历史和 AB 提交结果摘要。Stage 8 额外提供顶部导航与运行模式提示、非空标题浏览器校验、提交中按钮状态、浏览器端 `localStorage` 偏好、列表文本搜索/状态筛选/排序、详情 Overview/Source/Filter/Seeds/Audit 分组、统一成功/错误通知、可恢复操作按钮、窄屏单列布局和基础无障碍标记。页面和 API 都不应展示 token、完整 endpoint URL、原始 HTML、原始 RSS XML 或本地绝对路径。

### Web API

Web API 的应用结构参考 `/home/ghostning/github/user_level_flask`，但只保留 MiGuOrca MVP 需要的部分：

- `src/apps/base.py` 提供 `create_app(config_name: str | None = None)`。
- `src/apps/registry.py` 通过 `ALL_BLUEPRINTS` 集中注册 Blueprint。
- `src/wsgi.py` 暴露 `app = create_app(...)`，用于 Flask CLI。
- JSON API 使用 `src/extensions/flask_api/` 的统一响应、异常处理、class-based view 和 Pydantic 校验约定。
- Web 模块位于 `src/apps/migu_orca_web/`，HTML 模板和静态资源与模块同目录管理。

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

Stage 10 新增 Request 操作端点（仅 PENDING_CONFIRM 状态可操作）：

- `POST /api/v1/requests/<request_id>/accept?storage_dir=.migu_orca/storage`：确认 Request，状态变更为 ACCEPTED。
- `POST /api/v1/requests/<request_id>/cancel?storage_dir=.migu_orca/storage`：取消 Request，请求体可含 `cancel_reason` 字段。
- `POST /api/v1/requests/<request_id>/modify?storage_dir=.migu_orca/storage`：修改 Request，请求体含 `patch` 对象（允许字段：`selected_subtitle_group`、`filter_rule`、`expected_folder_name`）。

取消示例：

```bash
curl -X POST 'http://127.0.0.1:5000/api/v1/requests/<id>/cancel?storage_dir=.migu_orca/storage' \
  -H 'Content-Type: application/json' \
  -d '{"cancel_reason": "不想追了"}'
```

修改示例：

```bash
curl -X POST 'http://127.0.0.1:5000/api/v1/requests/<id>/modify?storage_dir=.migu_orca/storage' \
  -H 'Content-Type: application/json' \
  -d '{"patch": {"expected_folder_name": "自定义目录"}}'
```

### 本地验收流程

1. 运行质量检查：

   ```bash
   uv run pytest
   uv run python -m compileall -q src
   ```

2. 生成并保存一个 Request，供 Web UI 列表和详情读取：

   ```bash
   uv run migu-orca "咒术回战第三季" --save-request --storage-dir .migu_orca/storage
   ```

3. 启动 Web UI：

   ```bash
   uv run flask --app wsgi:app run
   ```

4. 打开本地 `/index` 页面；`GET /` 应重定向到 `/index`。确认页面展示 Stage 8 Web UI Usability、顶部锚点导航、运行模式提示、生成表单、Request 列表、Request 详情和验收说明。
5. 在生成表单中提交空白标题，确认页面在浏览器端提示错误且不会发起生成；再填写标题，确认提交按钮在请求中禁用，完成后通过统一通知展示生成或保存结果。
6. 验证保存偏好：修改 Storage 目录和保存勾选状态后刷新页面，确认浏览器恢复最近偏好；点击 `清除本地偏好` 后恢复空 `storage_dir` 和未勾选保存。该偏好只应存在于浏览器 `localStorage`，不写入 storage JSON 或 API 响应。
7. 验证 Request 列表：刷新列表后使用文本搜索、status 筛选和默认/标题升序/request_id 升序排序，确认匹配计数形如 `显示 2 / 5`，无匹配时显示空状态，清空筛选后列表恢复。
8. 验证 Request 详情：打开列表项后确认详情按 Overview、Source、Filter、Seeds、Audit 分组；request_id 可复制；RSS 只显示是否已选择，不显示完整 RSS URL；Seeds 可展开查看完整有效种子标题；缺失 history 或 AB result 时保持非致命提示。
9. 验证通知和恢复：列表加载失败时刷新按钮仍可用；详情加载失败时不清空已加载列表；通知可手动关闭，并会在下一次操作时替换旧消息。
10. 验证窄屏和键盘操作：在移动宽度下表单、列表和详情为单列且不横向溢出；Tab 能聚焦主要控件和 Request 列表按钮；焦点样式可见，动态通知/列表/详情区域具备合适的语义标记。
11. 验证 Request 操作（Stage 10）：打开 PENDING_CONFIRM 状态的 Request 详情，确认出现确认/取消/修改按钮；点击确认后确认浏览器弹出确认框，确认后状态变为 ACCEPTED 且按钮消失；点击取消后弹出原因输入框，确认后状态变为 CANCELLED 且 Audit 历史更新；点击修改后展示内联表单（字幕组下拉、filter_rule 输入、folder_name 输入），提交修改后通知展示成功且状态保持 PENDING_CONFIRM。
12. 通过 API 验证本地列表和详情：

   ```bash
   curl 'http://127.0.0.1:5000/api/v1/requests?storage_dir=.migu_orca/storage'
   curl 'http://127.0.0.1:5000/api/v1/requests/<request_id>?storage_dir=.migu_orca/storage'
   ```

Stage 8 仍不实现真实 MiKan 搜索/RSS 兼容性优化、认证系统、复杂配置管理、前端构建链、批量季度订阅或 qBittorrent 直连。真实 MiKan 搜索/RSS 解析优化继续在 [backlog](docs/backlog.md) 跟踪，当前状态保持未完成。

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
- 当前活跃阶段：Stage 10（已完成），Web UI Request 操作
- 最近完成阶段：Stage 10，Web UI Request 确认、取消和修改操作入口 PRD
- 前一完成阶段：Stage 9，浏览器自动化测试 PRD
- 前一完成阶段：Stage 7，Flask Web UI / 管理界面 MVP PRD
- 后续待办：`docs/backlog.md`
- 已归档阶段记录：`scripts/ralph/archive/`
- Ralph 循环命令（Claude）：`./scripts/ralph/ralph.sh --tool claude --model Hiku 7`
- Ralph 循环命令（Codex 备用）：`./scripts/ralph/ralph.sh --tool codex 7`

### 使用 Claude 运行 Ralph

当前项目的 `scripts/ralph/ralph.sh` 支持 `--tool amp|claude|codex` 选择执行工具。使用 Claude 时，脚本会读取 `scripts/ralph/CLAUDE.md`，并通过 `claude --dangerously-skip-permissions --print` 启动一次无交互开发迭代。

Claude 模型可以通过命令行参数显式指定：

```bash
./scripts/ralph/ralph.sh --tool claude --model Hiku 7
```

也可以通过环境变量指定：

```bash
RALPH_MODEL=Hiku ./scripts/ralph/ralph.sh --tool claude 7
```

`--claude-model Hiku` 是 `--model Hiku` 的等价写法：

```bash
./scripts/ralph/ralph.sh --tool claude --claude-model Hiku 7
```

本地已通过 CCSwitch 将 Claude 的 `Hiku` 模型映射到实际提供方模型 `deepseek-v4-flash`。因此在本机运行上述命令时，Ralph 会向 Claude CLI 传入 `--model Hiku`，实际模型路由由 CCSwitch 配置决定。

`--model` 目前只会传递给 Claude 分支；当 `--tool` 为 `amp` 或 `codex` 时，脚本会忽略该参数并输出提示。

Stage 7 已在 Stage 6 本地 JSON Request 持久化基础上，增加 Flask app factory、Blueprint registry、统一 JSON API 响应层、Pydantic 校验、Request 查询/生成 API、服务端渲染 Web UI、状态历史展示和 AB 提交结果展示，同时保持默认 CLI 流程不隐式写入磁盘。

Stage 8 已围绕 Web UI 可用性补强：顶部导航与运行模式提示、生成表单说明和本地校验、Storage 偏好记忆、Request 列表搜索/筛选/排序、详情区块重组、统一通知与错误恢复、响应式布局和基础无障碍验收。Stage 8 仍不包含真实 MiKan 搜索/RSS 兼容性优化、认证系统、复杂配置管理、前端构建链、批量季度订阅或 qBittorrent 直连。

Stage 9 引入 Playwright 浏览器自动化测试基础设施，覆盖了 `/` 到 `/index` 路由验证、页面基础加载、Request 生成表单校验和显式保存流程、列表搜索/筛选/排序、详情分组和通知恢复、响应式布局和键盘可访问性等关键路径。Stage 10 将浏览器测试扩展到 Web UI 确认、取消和修改流程，目前共有 88 个浏览器测试。测试默认使用本地 fixture 和临时 storage，不访问真实 MiKan、Auto Bangumi 或 qBittorrent。

## Stage 9 浏览器自动化测试

Stage 9 使用 Playwright + Chromium 为 Stage 8 Web UI 提供浏览器级回归保障。测试代码位于 `tests/browser/`，与现有单元测试分层清晰。

### 依赖安装

Playwright Python 包已纳入 `dev` 依赖组，通过 `uv sync` 即可安装。浏览器二进制和系统库需要额外设置：

```bash
# 方式 1：自动设置脚本（推荐，不需要 root）
./script/setup-browser-deps.sh

# 方式 2：手动安装系统依赖（需要 sudo）
sudo apt-get install libnspr4 libnss3 libatk1.0-0 libatk-bridge2.0-0 \
  libcups2 libdrm2 libdbus-1-3 libxkbcommon0 libxcomposite1 libxdamage1 \
  libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
  libatspi2.0-0

# 方式 3：使用 Playwright 内置依赖安装（需要 sudo）
uv run playwright install-deps chromium

# 安装 Chromium 浏览器二进制
uv run playwright install chromium
```

### 运行浏览器测试

```bash
# 运行所有测试（包括浏览器测试）
uv run pytest

# 只运行浏览器测试
uv run pytest tests/browser/ -v

# 只运行非浏览器测试（跳过浏览器测试）
uv run pytest -m "not browser"
```

### 浏览器不可用时的回退

当浏览器二进制或系统库不可用时，conftest 会自动跳过标记了 `@pytest.mark.browser` 的测试，
并打印跳过原因。所有非浏览器测试正常执行不受影响。

### 测试输出脱敏

浏览器测试的输出、截图、trace 和失败日志不会包含 token、完整 endpoint URL、
原始 HTML、原始 RSS XML 或本地绝对路径。

## 参考文档

- [主 PRD](docs/MiGuOrca_main_PRD.md)
- [Stage 1 实现规格](docs/design/stage1-spec.md)
- [架构与目录约定](docs/design/architecture.md)
