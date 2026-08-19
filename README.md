# MiGuOrca

MiGuOrca 是一个面向季度新番的 Auto Bangumi 前置订阅编排工作台，目标是在 MiKanProject 与 Auto Bangumi 之间提供 MiKan 订阅源发现、筛选预览、批量草案审核与提交辅助能力。

当前已完成 Stage 19。Stage 19 在 Stage 18 的单番剧真实 MiKan 主流程上新增批量新番订阅草案工作台：用户可在 `/index` 按行输入 `萌王S4`、`路哥S4`、`杖剑谭S2`、`邻家天使S2` 等简称，系统通过 AI 名称解析 provider seam 生成候选标题和搜索词，逐项复用 MiKan candidate search 能力生成可审核卡片。卡片支持删除、展开查看过滤器和有效/排除种子摘要、进入现有预览详情修改流程并只回流当前卡片，以及单卡接受。Stage 19 不实现批量接受、全接受或 Auto Bangumi 并发提交队列；这些能力交给 Stage 20。

## 项目目标

MVP 已完成单番剧订阅草案闭环，后续方向调整为“批量新番订阅前置工作台”：

1. 接收用户从季度新番推荐视频、清单或聊天中整理出的一批番剧简称。
2. 使用 AI 名称解析与搜索词增强，将 `萌王S4`、`路哥S4`、`杖剑谭S2`、`邻家天使S2` 等模糊输入转换为可搜索、可审核的候选标题。
3. 为每个条目搜索并分析 MiKanProject 数据，生成番剧订阅草案卡片。
4. 允许用户逐个审核、删除、展开查看、修改字幕组/筛选规则/文件夹名和有效种子。
5. 支持单个接受、批量接受和全接受；接受后进入 Auto Bangumi 提交流程。

MiGuOrca 不定位为 Auto Bangumi 或 qBittorrent 的替代品。下载执行、长期订阅执行和下载任务创建继续交给 Auto Bangumi / qBittorrent；MiGuOrca 的价值来自订阅前判断、批量编排和用户可审核的配置生成。

## 目前状态

- Stage 19 已把批量新番订阅前置工作台接入 `/index`：批量输入按非空行生成独立条目，AI 名称解析 fake provider 和 provider seam 输出候选标题/搜索词，批量 API 对每个条目独立搜索 MiKan 候选，卡片网格支持删除、展开、单卡修改回流和单卡接受。
- Stage 18 已把真实 MiKan 候选搜索设为普通 Web 主流程；fixture 仍保留为 CLI、API seam、离线开发和测试路径。Web UI 的 fixture 入口放在 `/index` 底部「开发 / 离线测试」面板中并默认收起，普通用户路径不会触发 fixture 生成。系统内置默认 MiKan 搜索 endpoint（`https://mikanani.me/Home/Search`）与 timeout（15 秒），普通 UI 不再要求用户填写 `search_endpoint` / `timeout_seconds` / `query`。
- 下一阶段应围绕批量接受、全接受和 Auto Bangumi 提交前队列展开，而不是扩展为 qBittorrent 下载器或 Auto Bangumi 替代执行系统。
- 已支持标题匹配、RSS 解析、字面/正则筛选、字幕组选择、目录命名和 JSON 输出。
- 已支持 Request 确认、取消和受限修改；确认后的 `ACCEPTED` Request 仍可执行相同受限字段的修改，并可显式删除；修改/删除后保持原有安全边界。
- 已建立 Auto Bangumi 提交结果契约、Request 到 AB payload 映射、fake client、真实 HTTP client adapter、失败降级 JSON 和显式配置读取。
- 已建立真实 MiKanProject 数据源 adapter、可注入 HTTP transport、搜索页解析、合集详情页结构化解析、字幕组级 RSS 优先输出、番剧级 RSS fallback、真实 RSS XML 读取和安全错误归一化。
- 当前 CLI 只有在显式传入 `--source mikan` 和 `--mikan-config` 时才会构造真实 MiKan client；可额外传入 `--mikan-bangumi <url-or-id>` 直接读取指定合集详情页并跳过搜索；只有在显式传入 `--submit-ab` 和 `--ab-config` 时才会构造真实 Auto Bangumi HTTP client；只有在显式传入 `--save-request` 时才会写入本地 JSON 存储。
- 已提供 Flask Web UI：`/` 重定向到 `/index`，`/index` 是订阅方案工作台，`/settings` 是配置与连接测试页面，`/Settings` 重定向到 `/settings`。
- `/index` 主流程通过真实 MiKan 候选搜索生成订阅方案，可以搜索/筛选/排序本地 Request、读取 URL 可恢复的分组详情，并执行确认、可见取消表单和受限修改；候选选择与直连 fallback 默认生成可编辑的 `订阅草案（未保存）` 预览，可修改字幕组/筛选规则/文件夹名并重算种子展示，点击 `保存草案` 后才进入待确认流程。fixture-backed 生成不参与普通主流程，而是放在页面底部「开发 / 离线测试」面板中，面板默认收起，需开发者手动展开才能使用。
- 已保存 `ACCEPTED` Request 详情同时展示 `修改`、`删除` 和 `去 Settings 提交 Auto Bangumi` 动作；`修改` 复用详情内修改表单并保持 `ACCEPTED` 状态，`删除` 需显式确认并刷新列表、清空详情和移除 URL `request_id`。
- Request 详情的 Filter 分区展示包含规则、排除规则、匹配模式（普通字符或正则）和大小写状态；Seeds 分区按 有效种子 -> 完整种子（按字幕组分组）-> 排除种子 的顺序展示：有效种子默认可见并标注 `当前选中字幕组`，完整种子按 MiKan 字幕组分组（每组显示字幕组名、种子数量并可展开），完整种子与排除种子默认折叠，排除原因使用 `命中排除规则` / `未命中包含规则` 可读语言。
- 筛选编辑控件使用 `包含规则` / `排除规则` 标签，并提供默认未勾选的 `使用正则` 与 `大小写敏感` 复选框；默认提交发送 `use_regex=false` / `case_sensitive=false`，字面文本 `[`、`[v2]` 不会触发正则错误。
- `/settings` 可以管理非敏感 Storage 浏览器偏好、直接显示并显式测试 qBittorrent 连接，并在 `/settings?request_id=<id>#auto-bangumi` 中对 `ACCEPTED` Request 执行显式 Auto Bangumi 提交配置。
- Stage 16 已完成真实 MiKan 合集详情页离线 fixture、结构化详情模型、字幕组级 RSS 优先、direct URL/ID 入口和真实读取错误脱敏；默认流程不连接 qBittorrent，不启动下载，不改变 AB 提交流程。
- Stage 17 已完成真实 MiKan 搜索候选合集展示与用户手动选择：`MikanClient.search_candidates` 从搜索页 `相关推荐` 解析候选卡片并规范化为绝对 HTTP(S) `/Home/Bangumi/<numeric-id>`，按页面顺序返回并按 `bangumi_id` 去重；Web API `POST /api/v1/mikan/candidates` 提供 request-scoped 候选搜索，返回只含公开候选元数据和推荐标签的 sanitized envelope。Stage 18 已把该能力从折叠的附属入口调整为 `/index` 普通 Web 主流程，并提供系统默认 MiKan 配置和可编辑预览草案。Stage 19 已在此基础上新增 `POST /api/v1/batches/parse` 和批量卡片工作区。

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
- 显式直连 MiKan 合集 URL 或 ID：`uv run migu-orca --source mikan --mikan-config config/user/mikan-config.example.json --mikan-bangumi 2353`
- 显式执行真实 AB 提交：`uv run migu-orca "咒术回战第三季" --action accept --submit-ab --ab-config config/user/ab-config.example.json`
- 显式组合真实 MiKan 和真实 AB 提交：`uv run migu-orca "咒术回战第三季" --source mikan --mikan-config config/user/mikan-config.example.json --action accept --submit-ab --ab-config config/user/ab-config.example.json`
- 显式保存真实 AB 提交结果：`uv run migu-orca "咒术回战第三季" --action accept --submit-ab --ab-config config/user/ab-config.example.json --save-request --storage-dir .migu_orca/storage`

说明：

- 不要直接使用 `python` 执行测试或脚本。
- 需要新增依赖时，优先通过 `uv add` 或编辑 `pyproject.toml` 后再执行 `uv sync`。
- 所有后续自动化、验证和测试步骤都应默认通过 `uv` 完成。
- CLI 的 `--source` 默认为 `static-fixture`，会继续读取仓库内静态 catalog 和 RSS fixture；只有 `--source mikan --mikan-config <path>` 会访问真实 MiKanProject 页面和 RSS URL。Web UI 的普通主流程已切换为真实 MiKan 候选搜索（系统默认 MiKan 配置），fixture 只作为开发/离线测试路径保留。
- `--save-request` 默认为关闭；未传该参数时，CLI 只输出 JSON，不会创建或写入本地存储目录。
- `--storage-dir <path>` 用于覆盖本地 JSON 存储根目录；未传时，显式保存或查询命令使用项目下 `.migu_orca/storage`。
- 本地 JSON 存储目录结构：
  - `requests/`：按 `request_id` 保存完整 Request snapshot。
  - `history/`：按 `request_id` 保存确认、取消和修改等状态历史。
  - `ab_results/`：仅在显式 `--submit-ab` 产生 `ab_submit_result` 且同时 `--save-request` 时保存 AB 提交结果。
- `.migu_orca/storage` 是运行数据目录，不应提交到 Git；如需长期保留，请由部署方在仓库外指定 `--storage-dir`。
- CLI 和高级 API 的 MiKan config JSON 字段为 `search_endpoint`、`timeout_seconds`：
  - `search_endpoint`：MiKanProject 搜索页 endpoint，由调用方显式提供；程序会追加 URL 编码后的 `searchstr` 查询参数。
  - `timeout_seconds`：真实 MiKan 搜索页、番剧页和 RSS XML 读取的超时时间，必须为正数。
- 当前真实 MiKan adapter 会从搜索结果中解析包含 `/Home/Bangumi/` 的候选番剧链接；也可以通过 `--mikan-bangumi` 或 Web API `mikan_bangumi` 直接读取指定合集。详情页 parser 会输出安全结构化元数据（bangumi id、标题、规范化详情 URL、可选播出/海报、番剧级 RSS、字幕组条目和单集标题/详情链接摘要），并优先把字幕组级 RSS 转换为 `mikan_http` `RssSource`。存在字幕组级 RSS 时不混入番剧级 RSS；没有字幕组级 RSS 但有番剧级 RSS 时使用 `全部字幕组` fallback。
- MiKan direct entry 接受同源 HTTP(S) `/Home/Bangumi/<numeric-id>` URL 或 bare numeric ID；bare ID 的 host 从显式 MiKan config 的 `search_endpoint` 派生。空值、非 HTTP(S)、跨源 URL、非 Bangumi path、路径穿越和非数字 ID 都会返回脱敏错误。Stage 17 已在 Web UI `/index` 的候选搜索区中接入直连 URL/ID fallback，候选选择和 fallback 都复用 Stage 16 `mikan_bangumi` direct-entry 链路。
- Stage 17 候选搜索 Web API 为 `POST /api/v1/mikan/candidates`，请求体支持 `query` 和可选 `mikan_config`（`search_endpoint`、`timeout_seconds`）；未传 `mikan_config` 时系统使用默认 MiKan 配置（`https://mikanani.me/Home/Search`，timeout 15 秒），普通 Web UI 已不再要求用户填写这些字段。响应只返回 sanitized 公开候选元数据（`bangumi_id`、`title`、`mikan_url`、`poster_url`、`source_query`、`aliases`）和 display-only `recommendation` 标签。进程内候选缓存 key 使用 `mikan-candidates:<sha256[:32] of search_endpoint>:<normalized query>`，只缓存公开候选元数据并带 TTL，命中时不调用 transport；候选搜索、选择、fallback 的 MiKan config 都是 request-scoped，不写入 storage JSON、浏览器 storage、URL、history、日志或截图。
- 错误 details、日志、fixture 和示例配置不得包含原始 HTML、原始 RSS XML、完整 endpoint URL、cookie、token 或其他敏感配置值。
- `--submit-ab` 必须和 `--action accept`、`--ab-config <path>` 显式组合使用；未传 `--submit-ab` 时不会触发 Auto Bangumi 提交流程，也不会实例化真实 HTTP client。
- AB config JSON 字段为 `endpoint`、`token`、`fallback_enabled`：
  - `endpoint`：Auto Bangumi 创建订阅的 HTTP endpoint，由部署方显式提供。
  - `token`：用于 `Authorization: Bearer <token>` 请求头。不要提交真实 token，错误 details、日志和测试快照也不得包含 token 明文。
  - `fallback_enabled`：提交失败时是否在 `ab_submit_result.fallback_config` 中输出可人工处理的降级 JSON。
- 真实 AB client 当前发送的创建订阅 payload 字段为 `title`、`rss_url`、`save_path`、`filter_rule`，并要求响应中包含 `id`、`subscription_id` 或 `ab_subscription_id` 之一。真实 Auto Bangumi API 的 endpoint、请求字段和响应字段仍需要按实际部署版本验证。
- Web UI 真实 Auto Bangumi 配置只在当前提交中使用，不能写入 storage JSON、状态历史、浏览器 `localStorage` / `sessionStorage`、URL query、日志、截图或测试 trace。
- qBittorrent 配置同样必须保持 request-scoped：endpoint、username、password、cookie、SID、敏感路径和原始响应体不能写入 storage JSON、状态历史、浏览器 storage、URL、日志、截图、测试 trace 或 API 响应。
- Stage 15 允许 Settings 将非敏感 Storage 偏好写入浏览器 `localStorage`，键名为 `miguOrca.web.storageDir` 和 `miguOrca.web.saveRequest`；URL query 只能携带 `request_id` 等非敏感上下文。缺省 `saveRequest` 表示开发/离线 fixture 生成默认保存，显式 `"false"` 表示预览模式；真实 MiKan 候选选择与直连 fallback 始终生成可编辑预览草案，与 `saveRequest` 偏好无关。
- 筛选规则默认按普通字符匹配：规则文本以字面子串（substring）形式出现在种子名中才算命中，大小写不敏感；`use_regex=true` 才按正则编译，`case_sensitive=true` 才区分大小写。筛选规则是用户输入的非密文字符串，允许写入 saved Request，但错误消息不得包含本地存储路径或原始外部响应。
- 真实 MiKan 合集详情页解析和 direct URL/ID 入口已在 Stage 16 完成；搜索候选展示、手动选择、候选缓存和推荐标签已在 Stage 17 完成；真实 MiKan 搜索收敛为 Web 主流程、默认 MiKan 配置、直连兜底勾选框、可编辑预览订阅草案、中文状态和 Seeds 分组展示已在 Stage 18 完成；批量输入、AI 名称解析 seam、批量候选搜索、订阅草案卡片、单卡修改回流和单卡接受已在 Stage 19 完成。批量接受和 Auto Bangumi 提交前队列仍在 [backlog](docs/backlog.md) 跟踪。

## Stage 15 Flask Web UI

Stage 15 继续使用 Stage 7 引入的本地 Flask Web UI / 管理界面 MVP，并在 Stage 8 可用性、Stage 9 浏览器自动化、Stage 10 Request 操作入口、Stage 11 显式真实 MiKan / Auto Bangumi 配置入口、Stage 12 qBittorrent 显式连接测试、Stage 13 Settings 信息架构和 Stage 14 Request 可操作性修复基础上，补齐 `ACCEPTED` Request 的修改与删除能力，并将筛选规则默认语义从正则优化为大小写不敏感的字面字符匹配，同时提供显式 `使用正则` 与 `大小写敏感` 选项。它复用现有 CLI 编排、真实 Auto Bangumi HTTP client adapter、qBittorrent connection-test controller 与 Stage 6 本地 JSON 存储能力，不改变 `migu-orca` CLI 默认行为，也不引入 React/Vite 等前端构建链。

启动方式：

```bash
uv run flask --app wsgi:app run
```

启动后访问：

- `GET /`：重定向到 `/index`。
- `GET /index`：服务端渲染 Request 工作台。
- `GET /index?request_id=<id>`：打开 Request 工作台并恢复指定 Request 详情。
- `GET /settings`：服务端渲染 Settings 页面。
- `GET /Settings`：重定向到 `/settings`。
- `GET /healthz`、`GET /readiness`：健康检查。

`/index` 页面包含真实 MiKan 候选搜索主表单、可编辑预览订阅草案、本地 Request 列表、URL 可恢复的详情区域、状态历史和 AB 提交结果摘要。页面提供共享顶部导航、运行模式摘要、非空标题浏览器校验、提交中按钮状态、Settings Storage 偏好只读摘要、列表文本搜索/状态筛选/排序、详情 Overview/Source/Filter/Seeds/Audit 分组、统一成功/错误通知、可恢复操作按钮、可见取消/修改表单、窄屏单列布局和基础无障碍标记。候选选择与直连 fallback 默认生成 `订阅草案（未保存）` 预览，不展示确认、取消、删除或 Auto Bangumi 提交动作；预览提供可编辑表单（字幕组、包含/排除规则、使用正则、大小写敏感、folder_name），`应用修改` 通过 dry-run 预览修改端点重算当前选中字幕组的有效/排除种子展示，`保存草案` 持久化修改后的订阅方案并同步 `request_id` 到 URL 进入待确认流程。已保存 `ACCEPTED` Request 详情展示 `修改`、`删除` 和 `去 Settings 提交 Auto Bangumi` 动作，`删除` 前必须经浏览器确认框确认。Filter 分区展示包含规则、排除规则、匹配模式（普通字符或正则）和大小写状态；Seeds 分区按 有效种子（默认可见并标注当前选中字幕组）-> 完整种子（按字幕组分组，默认折叠）-> 排除种子（默认折叠）的顺序展示。`/settings` 页面包含 Storage 偏好、数据源、qBittorrent 和 Auto Bangumi 分区；Storage 偏好只写入浏览器 `localStorage`，qBittorrent 连接测试表单直接显示，Auto Bangumi 按 `request_id` 上下文渐进展示，提交前必须显式确认。页面和 API 都不应展示 token、完整 endpoint URL、qBittorrent username、password、Authorization header、cookie、SID、原始 HTML、原始 RSS XML、原始响应体或本地绝对路径。

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
- `POST /api/v1/requests`：生成 Request。请求 JSON 支持 `title`、`storage_dir`、`save_request`、`source`、可选 `mikan_config` 和 request-scoped `mikan_bangumi`。`source` 默认为 `static-fixture`；显式传入 `source: "mikan"` 时会构造真实 MiKan client，未传 `mikan_config` 时使用系统默认 MiKan 配置。存在 `mikan_bangumi` 时会直接解析指定 MiKan `Home/Bangumi/<id>` URL 或 ID 并跳过搜索；该字段不写入浏览器 storage、URL 或持久配置。API 层仍以显式 `save_request: true` 写入本地 storage；Web UI 候选选择与直连 fallback 默认发送 `save_request: false` 生成可编辑预览草案，`POST /api/v1/requests/preview-modify` 对未保存草案执行 dry-run 修改并重算种子，`POST /api/v1/requests/preview-save` 将修改后的 `PENDING_CONFIRM` 草案写入本地 storage 进入待确认流程。

`POST /api/v1/requests` 示例：

```json
{
  "title": "咒术回战第三季",
  "storage_dir": ".migu_orca/storage",
  "save_request": true
}
```

显式真实 MiKan 生成示例：

```json
{
  "title": "咒术回战第三季",
  "source": "mikan",
  "mikan_config": {
    "search_endpoint": "https://mikan.example/Home/Search",
    "timeout_seconds": 10
  },
  "storage_dir": ".migu_orca/storage",
  "save_request": true
}
```

显式真实 MiKan 直连合集示例：

```json
{
  "source": "mikan",
  "mikan_bangumi": "2353",
  "mikan_config": {
    "search_endpoint": "https://mikan.example/Home/Search",
    "timeout_seconds": 10
  },
  "storage_dir": ".migu_orca/storage",
  "save_request": true
}
```

Stage 10 新增 Request 操作端点（确认/取消仅 PENDING_CONFIRM 状态可操作；修改同时接受 PENDING_CONFIRM 与 ACCEPTED）：

- `POST /api/v1/requests/<request_id>/accept?storage_dir=.migu_orca/storage`：确认 Request，状态变更为 ACCEPTED。
- `POST /api/v1/requests/<request_id>/cancel?storage_dir=.migu_orca/storage`：取消 Request，请求体可含 `cancel_reason` 字段。
- `POST /api/v1/requests/<request_id>/modify?storage_dir=.migu_orca/storage`：修改 Request，请求体含 `patch` 对象（允许字段：`selected_subtitle_group`、`filter_rule`、`expected_folder_name`）。修改 `ACCEPTED` Request 后状态保持 `ACCEPTED` 不回落为 `PENDING_CONFIRM`，并记录 `MODIFY` history 事件；修改后重新计算有效/排除 Seeds。

Stage 15 新增已保存 Request 删除端点：

- `POST /api/v1/requests/<path:request_id>/delete?storage_dir=.migu_orca/storage`：删除 `requests/<request_id>.json`。request_id 必须来自 URL 路径，payload 只允许携带 `storage_dir` 等现有非敏感上下文；删除函数拒绝空值、路径片段和路径穿越，返回统一脱敏错误，且响应只返回被删除 request_id 和安全摘要，不返回已删除 snapshot 的原始 JSON。删除成功后列表不再包含该 request_id，详情加载该 request_id 返回 `request_not_found`。

Stage 11 新增真实配置入口端点：

- `POST /api/v1/requests/<request_id>/submit-ab?storage_dir=.migu_orca/storage`：对 `ACCEPTED` Request 执行显式 Auto Bangumi 提交。请求体必须包含 `ab_config` 对象，字段为 `endpoint`、`token`、`fallback_enabled`。提交结果会以脱敏形式写回 Request snapshot 和 `ab_results/`；endpoint、token、Authorization header、cookie 和完整 URL 不应出现在 API 响应、日志或本地存储中。

Stage 12 引入、Stage 13 迁移到 Settings 使用的 qBittorrent 显式连接测试端点：

- `POST /api/v1/qbittorrent/test-connection`：执行一次用户显式触发的 qBittorrent Web API 连接测试。请求体必须包含 `qbittorrent_config` 对象，字段为 `endpoint`、`username`、`password`、`timeout_seconds` 和 `verify_tls`。端点只测试认证和轻量状态读取，不启动下载，不创建订阅，不改写 Request snapshot，也不将 qBittorrent 配置写入 storage JSON、状态历史、浏览器 storage 或 URL。

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

显式 Auto Bangumi 提交示例：

```bash
curl -X POST 'http://127.0.0.1:5000/api/v1/requests/<id>/submit-ab?storage_dir=.migu_orca/storage' \
  -H 'Content-Type: application/json' \
  -d '{"ab_config": {"endpoint": "http://auto-bangumi.local", "token": "replace-with-token", "fallback_enabled": true}}'
```

显式 qBittorrent 连接测试示例：

```bash
curl -X POST 'http://127.0.0.1:5000/api/v1/qbittorrent/test-connection' \
  -H 'Content-Type: application/json' \
  -d '{"qbittorrent_config": {"endpoint": "http://qbittorrent.local:8080", "username": "replace-with-username", "password": "replace-with-password", "timeout_seconds": 5, "verify_tls": true}}'
```

成功响应只返回脱敏摘要：

```json
{
  "ok": true,
  "result": {
    "status": "reachable",
    "reachable": true,
    "version": "4.6.5"
  }
}
```

失败响应继续使用统一错误 envelope；`error_data` 只允许保留人工可处理的分类字段，例如 `category`、`field` 或 `status_code`，不能包含完整 endpoint、username、password、cookie、SID、本地绝对路径或原始响应体。

Stage 17 新增真实 MiKan 候选搜索端点：

- `POST /api/v1/mikan/candidates`：执行一次用户显式触发的真实 MiKan 搜索页候选解析。请求体必须包含 `query`；`mikan_config` 可选（`search_endpoint`、`timeout_seconds`），未传时使用系统默认 MiKan 配置。缺少 query 时返回统一校验错误。端点通过现有 `MikanClient` transport seam 读取搜索页并返回 sanitized 候选元数据，进程内候选缓存命中时不会调用 transport。响应只包含公开候选字段 `bangumi_id`、`title`、`mikan_url`、`poster_url`、`source_query`、`aliases` 和 display-only `recommendation` 标签；raw HTML、raw RSS XML、cookie、token、完整失败 URL 和原始响应体不会出现在响应中。

候选搜索示例：

```json
{
  "query": "无职转生",
  "mikan_config": {
    "search_endpoint": "https://mikan.example/Home/Search",
    "timeout_seconds": 10
  }
}
```

成功响应：

```json
{
  "ok": true,
  "result": {
    "query": "无职转生",
    "candidates": [
      {
        "bangumi_id": 2353,
        "title": "无职转生 第三季",
        "mikan_url": "https://mikan.example/Home/Bangumi/2353",
        "poster_url": null,
        "source_query": "无职转生",
        "aliases": [],
        "recommendation": "可能匹配"
      }
    ]
  }
}
```

失败时继续使用统一错误 envelope，只保留 `category`、`field`、`status_code` 等可处理字段。候选搜索、候选选择和直连 fallback 的 MiKan config 都是 request-scoped，不写入 storage JSON、浏览器 storage、URL、history、日志或截图。

Stage 19 新增批量解析端点：

- `POST /api/v1/batches/parse`：接收 `raw_input` 多行文本，忽略空行并为每个非空行生成独立 item。端点先通过 AI 名称解析 provider seam 生成候选标题、季数提示、搜索词、置信度和审核标记，再对每个 search query 复用 MiKan candidate search。单个 provider 或 MiKan 搜索失败只标记当前 item 为 `FAILED`，不阻塞同批次其他 item。响应只包含 batch/item 状态、解析元数据、公开候选字段和卡片展示所需的订阅草案摘要；raw HTML、raw RSS XML、cookie、token、magnet、完整失败 URL、原始响应体和本地绝对路径不会进入响应、浏览器 storage、URL 或 Request snapshot。

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

4. 打开本地 `/index` 页面；`GET /` 应重定向到 `/index`，`GET /Settings` 应重定向到 `/settings`。确认 `/index` 和 `/settings` 使用一致顶部导航，并包含 `订阅方案工作台` 与 `Settings` 入口。
5. 在生成表单中提交空白标题，确认页面在浏览器端提示错误且不会发起生成；再填写标题，确认提交按钮在请求中禁用，完成后通过统一通知展示生成或保存结果。
6. 验证 Settings Storage 偏好：打开 `/settings`，修改默认 Storage 目录和默认保存 Request 开关后刷新页面，确认浏览器恢复最近偏好；点击 `清除偏好` 后恢复默认 `.migu_orca/storage` 和默认保存状态。该偏好只应存在于浏览器 `localStorage`，不写入 storage JSON 或 API 响应；缺省保存状态表示 `/index` 默认生成并保存 Request。
7. 验证 Request 列表：刷新列表后使用文本搜索、status 筛选和默认/标题升序/request_id 升序排序，确认匹配计数形如 `显示 2 / 5`，无匹配时显示空状态，清空筛选后列表恢复。
8. 验证 Request 详情：打开列表项后确认浏览器 URL 同步为 `/index?request_id=<id>`；刷新该 URL 后仍展示同一详情。详情应按 Overview、Source、Filter、Seeds、Audit 分组；request_id 可复制；RSS 只显示是否已选择，不显示完整 RSS URL；Filter 分区展示包含规则、排除规则、匹配模式（普通字符或正则）和大小写状态；Seeds 按 有效种子 -> 完整种子（按字幕组分组）-> 排除种子 顺序展示：有效种子默认可见并标注当前选中字幕组，完整种子每组显示字幕组名、种子数量并可展开列表，完整种子与排除种子默认折叠，排除原因使用 `命中排除规则` / `未命中包含规则` 可读语言；缺失 history 或 AB result 时保持非致命提示。
9. 验证通知和恢复：列表加载失败时刷新按钮仍可用；详情加载失败时不清空已加载列表；通知可手动关闭，并会在下一次操作时替换旧消息。
10. 验证 Stage 15 UI 质量门槛：`/index` 标题、运行模式摘要、主操作区、Request 列表和详情区应有清晰阅读顺序；`/settings` Storage、数据源、qBittorrent 和 Auto Bangumi 分区边界清晰；生成、确认、提交使用主按钮，刷新、修改、返回 Settings 使用次按钮，取消、清空、删除和撤销类操作使用危险/警示样式。
11. 验证响应式和键盘操作：在中屏和移动宽度下 `/index` 与 `/settings` 为单列或低密度布局，不出现横向拥挤导航、过密并排表单或不可读详情表格；Tab 能聚焦主要控件和 Request 列表按钮；焦点样式可见，动态通知/列表/详情区域具备合适的语义标记。
12. 验证 Request 操作：打开 PENDING_CONFIRM 状态的 Request 详情，确认出现确认、取消、修改按钮；点击确认后确认浏览器弹出确认框，确认后状态变为 ACCEPTED；点击取消后展示详情区内可见取消表单，提交前必须确认；点击修改后展示内联表单，空 patch 必须在浏览器端阻止，显式清空 filter_rule 或 expected_folder_name 后状态保持 PENDING_CONFIRM 且 Audit 更新。
13. 验证 ACCEPTED Request 管理与筛选控件：打开 `ACCEPTED` Request 详情，确认同时出现 `修改`、`删除` 和 `去 Settings 提交 Auto Bangumi` 动作；`修改` 提交受限 patch 后详情保持 `ACCEPTED` 且 Filter、Seeds、Audit 刷新；`删除` 必须先确认，取消确认不调用删除 API，确认删除后列表刷新、详情清空且 URL 移除 `request_id`。在修改表单中确认 `包含规则` / `排除规则` 标签与默认未勾选的 `使用正则` / `大小写敏感` 复选框；默认提交发送 `use_regex=false` / `case_sensitive=false`，勾选后发送 `true`；普通字符模式下输入 `[` 或 `[v2]` 不得触发正则错误，勾选 `使用正则` 后非法正则才返回统一校验错误。
14. 验证 Auto Bangumi Settings 入口：打开 `ACCEPTED` Request 详情，确认出现跳转 `/settings?request_id=<id>#auto-bangumi` 的入口；非 `ACCEPTED` Request 不显示该入口。Settings 中的 Auto Bangumi 表单包含 endpoint、password token 和 fallback 选项，展示当前 request_id、前置条件和返回详情链接，提交前必须确认；失败时只显示脱敏通知；成功后清理 endpoint 和 token 字段并提供返回 `/index?request_id=<id>` 的链接。
15. 验证 qBittorrent Settings 连接测试：`/index` 不渲染 qBittorrent 配置且不调用 `/api/v1/qbittorrent/test-connection`；`/settings` qBittorrent 分区不使用 `<details>` / `<summary>`，endpoint、username、password、timeout_seconds、verify_tls 和 `测试 qBittorrent 连接` 按钮直接显示，password 使用密码输入框。空 endpoint、空 username、空 password 或非正数 timeout 必须在浏览器端阻止提交；提交前必须出现确认提示，确认后才发送 request-scoped `qbittorrent_config` POST body。
16. 验证 qBittorrent 成功和失败路径：成功时页面只展示 `status`、`reachable`、`version` 等脱敏摘要，并清理 endpoint、username 和 password；失败时保留当前表单状态，只展示统一脱敏通知，不展示完整 endpoint、用户名、密码、cookie、SID、本地绝对路径或原始响应体。
17. 验证脱敏和不落盘：页面、通知、API 响应、本地 storage JSON、浏览器 `localStorage` / `sessionStorage`、URL query、测试截图和 trace 不应包含 token、完整 endpoint URL、qBittorrent username、password、Authorization header、cookie、SID、原始 HTML、原始 RSS XML 或原始响应体。`localStorage` 只允许保存 Storage 偏好键。
18. 通过 API 验证本地列表和详情：

   ```bash
   curl 'http://127.0.0.1:5000/api/v1/requests?storage_dir=.migu_orca/storage'
   curl 'http://127.0.0.1:5000/api/v1/requests/<request_id>?storage_dir=.migu_orca/storage'
   ```

19. 验证 Stage 18 真实 MiKan 主流程：打开 `/index` 主生成区（标题为「真实 MiKan 候选搜索」），确认只要求输入番剧标题，普通可见 UI 不出现 `search_endpoint`、`timeout_seconds` 或 `query` 字样。输入标题后搜索，确认候选卡片展示标题、MiKan ID、封面（如有）和推荐标签；即使只有一个候选也必须点击「选择此合集」才能生成草案，不会自动生成。搜索无结果时勾选「搜索无结果时使用直连合集」，输入 MiKan `Home/Bangumi/<id>` URL 或 bare ID 可直接生成预览草案。候选选择和直连 fallback 都先生成「订阅草案（未保存）」预览，不展示确认、取消、删除或 Auto Bangumi 提交动作；预览提供可编辑表单（字幕组、包含/排除规则、使用正则、大小写敏感、folder_name），点击「应用修改」后 Filter 与 Seeds 同步重算，点击「保存草案」后进入待确认流程并同步 URL `request_id`。页面底部「开发 / 离线测试」面板中的 `Fixture 生成` 默认收起，普通路径不会触发 fixture 生成。页面使用中文业务文案（订阅方案/订阅草案/待确认/已确认/已取消），Seeds 区按 有效种子（当前选中字幕组，默认可见）-> 完整种子（按字幕组分组，默认折叠）-> 排除种子（默认折叠）顺序展示。
20. 验证 Stage 19 批量工作台：在 `/index` 批量获取区域输入多行简称，确认空输入不会调用 `/api/v1/batches/parse`，有效输入会展示每行 raw_title、解析状态和卡片网格。卡片应展示封面或占位、番剧标题、源名称、有效种子数和中文状态；删除只移除当前卡片，窄屏为单列，长列表区域可滚动。展开 DRAFT/READY 卡片后确认展示当前字幕组、包含/排除规则、匹配模式、大小写、有效种子和排除种子摘要；点击单卡「修改」应进入现有订阅草案详情修改流程并只回流当前卡片；点击单卡「接受」应只把当前卡片显示为「已接受」，其他卡片状态不变。页面、URL、browser storage、storage JSON、截图和 trace 不得包含 raw HTML、raw RSS XML、cookie、token、magnet、完整失败 URL、原始响应体或本地绝对路径。

Stage 16 不实现 Web UI 搜索候选展示、AI 番剧名解析、认证系统、复杂配置管理、前端构建链、批量季度订阅或 qBittorrent 下载/订阅动作。本阶段已完成真实 MiKan 合集详情页离线 fixture、结构化详情解析、字幕组级 RSS 优先输出、番剧级 RSS fallback、CLI/API direct URL/ID 入口和真实读取错误脱敏；Stage 17 已在该基础上完成 Web UI direct-entry fallback 与搜索候选选择。Stage 18 已把真实 MiKan 候选搜索收敛为 `/index` 普通 Web 主流程，并提供系统默认 MiKan 配置、直连兜底勾选框、可编辑预览订阅草案、中文状态与 Seeds 分组展示。Stage 19 已完成批量输入、AI 名称解析 seam、批量候选搜索、卡片网格、单卡修改和单卡接受。Stage 19 仍不实现真实 LLM provider 生产配置、批量接受、全接受、Auto Bangumi 提交队列、认证系统、复杂配置管理、前端构建链或 qBittorrent 下载/订阅动作。

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

示例 qBittorrent 配置：

```json
{
  "endpoint": "http://qbittorrent.local:8080",
  "username": "replace-with-username",
  "password": "replace-with-password",
  "timeout_seconds": 5,
  "verify_tls": true
}
```

## Ralph 开发流

- 当前活跃 Ralph PRD：Stage 19，批量新番订阅草案工作台 PRD（已完成）
- 最近完成阶段：Stage 18，真实 MiKan 主流程与预览优化 PRD
- 前一完成阶段：Stage 17，真实 MiKan 搜索候选合集展示与用户选择 PRD
- 前一完成阶段：Stage 16，真实 MiKan 合集详情页解析与直连 URL/ID 入口 PRD
- 前一完成阶段：Stage 15，Web UI ACCEPTED 管理与筛选语义优化 PRD
- 前一完成阶段：Stage 14，Web UI Request 可操作性修复 PRD
- 前一完成阶段：Stage 13，Web UI Settings 信息架构优化 PRD
- 前一完成阶段：Stage 12，qBittorrent 直连显式连接测试 PRD
- 前一完成阶段：Stage 11，Web UI 显式真实 MiKan / Auto Bangumi 配置入口 PRD
- 前一完成阶段：Stage 10，Web UI Request 确认、取消和修改操作入口 PRD
- 前一完成阶段：Stage 9，浏览器自动化测试 PRD
- 前一完成阶段：Stage 7，Flask Web UI / 管理界面 MVP PRD
- 后续待办：`docs/backlog.md`，当前优先项为 BL-013 / 批量接受与 Auto Bangumi 提交前队列管理
- 已归档阶段记录：`scripts/ralph/archive/`
- Ralph 循环命令（Claude）：`./scripts/ralph/ralph.sh --tool claude --model Hiku 7`
- Ralph 循环命令（Codex 备用）：`./scripts/ralph/ralph.sh --tool codex 7`

### Ralph 阶段开发规范

Stage 开发必须通过 Ralph 循环完成，不应绕过 `scripts/ralph/prd.json` 手工挑 story 开发。每次启动一个 Stage 前，应先确认 `scripts/ralph/prd.json` 是当前 Stage 的 PRD，`scripts/ralph/progress.txt` 已记录本 Stage 的约束和进度。

Stage 开发期间，Ralph 每轮应以完成当前 Stage 的全部 user story 为目标运行。`scripts/ralph/prd.json` 中的 user story 拆分用于明确验收粒度、依赖顺序和进度记录，不表示开发 Agent 只能处理一个 story。每轮完成后应更新全部已完成 story 的 `passes` 状态和 `scripts/ralph/progress.txt`，并运行当前 Stage 要求的验证命令；涉及 Web UI 的 Stage 必须运行浏览器测试或记录无法运行的明确原因。

一个 Stage 全部 story 完成后，必须执行收尾流程：

1. 将已完成 Stage 的 `scripts/ralph/prd.json` 和 `scripts/ralph/progress.txt` 归档到 `scripts/ralph/archive/<date>-<stage-name>/`。
2. 更新 README、`docs/backlog.md` 和必要模块文档，使当前状态、已完成事项和后续待办保持一致。
3. 运行 `uv run pytest`、`uv run pytest tests/browser -v` 和 `uv run python -m compileall -q src`；如果某项无法运行，必须在提交说明或 PR 描述中写明原因。
4. 整理本 Stage 的最终提交和 PR 描述。
5. 推送到 GitHub，创建 PR，确认可合并后合并进 `main`。
6. 合并后确认本地 `main` 与 `origin/main` 对齐，且工作区干净。

Ralph 运行过程中由下属 Agent 产生的本地中间提交不强制使用中文，不应仅因中间提交信息为英文而消耗 token 重写提交历史。最终对外可见的 PR 标题、PR 描述、合并提交信息、Stage 收尾提交信息和归档/验收说明必须使用中文描述。

### 使用 Claude 运行 Ralph

当前项目的 `scripts/ralph/ralph.sh` 支持 `--tool amp|claude|codex` 选择执行工具。使用 Claude 时，脚本会读取 `scripts/ralph/CLAUDE.md`，并通过 `claude --dangerously-skip-permissions --print` 启动一次无交互开发迭代。

Claude 模型可以通过命令行参数显式指定。当前仓库里可直接运行的示例是：

```bash
./scripts/ralph/ralph.sh --tool claude --model deepseek-v4-flash 7
```

也可以通过环境变量指定：

```bash
RALPH_MODEL=deepseek-v4-flash ./scripts/ralph/ralph.sh --tool claude 7
```

`--claude-model` 是 `--model` 的等价写法：

```bash
./scripts/ralph/ralph.sh --tool claude --claude-model deepseek-v4-flash 7
```

如果你的 Claude 环境已经为别名做了额外映射，也可以换成对应别名；但在本仓库当前环境中，`deepseek-v4-flash` 是可直接运行的模型名。

`--model` 目前只会传递给 Claude 分支；当 `--tool` 为 `amp` 或 `codex` 时，脚本会忽略该参数并输出提示。

Stage 7 已在 Stage 6 本地 JSON Request 持久化基础上，增加 Flask app factory、Blueprint registry、统一 JSON API 响应层、Pydantic 校验、Request 查询/生成 API、服务端渲染 Web UI、状态历史展示和 AB 提交结果展示，同时保持默认 CLI 流程不隐式写入磁盘。

Stage 8 已围绕 Web UI 可用性补强：顶部导航与运行模式提示、生成表单说明和本地校验、Storage 偏好记忆、Request 列表搜索/筛选/排序、详情区块重组、统一通知与错误恢复、响应式布局和基础无障碍验收。Stage 8 仍不包含真实 MiKan 搜索/RSS 兼容性优化、认证系统、复杂配置管理、前端构建链、批量季度订阅或 qBittorrent 直连。

Stage 9 引入 Playwright 浏览器自动化测试基础设施，覆盖了 `/` 到 `/index` 路由验证、页面基础加载、Request 生成表单校验和显式保存流程、列表搜索/筛选/排序、详情分组和通知恢复、响应式布局和键盘可访问性等关键路径。Stage 10 将 Web UI 扩展到确认、取消和修改流程。Stage 11 将 Web UI 扩展到显式真实 MiKan 配置入口和显式 Auto Bangumi 提交入口。Stage 12 将 Web UI 扩展到 qBittorrent 显式连接测试入口，并通过 Playwright route fake 验证连接测试，不访问真实 qBittorrent。Stage 13 将配置和连接测试迁移到 `/settings`，将 `/index` 收敛为 Request 工作台，补齐 URL 可恢复详情、可见取消/修改表单、按钮语义、状态反馈、Settings 分区和响应式 UI 回归。Stage 14 补齐默认生成保存、只读预览、默认生成后的确认/取消/修改、Seeds 完整/有效/排除列表、qBittorrent Settings 直显和敏感信息不落盘回归。Stage 15 补齐 `ACCEPTED` Request 的删除与受限修改、筛选字面默认语义、`使用正则` / `大小写敏感` 选项、Filter 与 Seeds 排除说明和 Stage 15 安全回归。Stage 16 补齐真实 MiKan 合集详情页解析、字幕组级 RSS 优先、番剧级 RSS fallback、CLI/API direct URL/ID 入口和真实读取错误脱敏。Stage 17 补齐真实 MiKan 搜索候选合集展示、request-scoped 候选搜索 API、Web UI 手动选择与直连 fallback、进程内候选缓存和 display-only 推荐标签，并把全部真实 MiKan 能力接入 `/index` Request 生成流程。Stage 18 补齐真实 MiKan 主流程收敛：系统默认 MiKan 配置、主生成区候选搜索、直连兜底勾选框、可编辑预览订阅草案（dry-run 修改 + 保存）、中文用户态文案与状态、Seeds 有效/完整/排除顺序与字幕组分组，以及 fixture 模式降级为开发/离线测试路径。测试默认使用本地 fixture、临时 storage 和 fake endpoint seam，不访问真实 MiKan、Auto Bangumi 或 qBittorrent。

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

当前项目浏览器测试优先使用 Chromium / Google Chrome for Testing。`./script/setup-browser-deps.sh` 会执行两类配置：

1. 通过 `uv run playwright install chromium` 安装 Playwright 管理的 Chromium 二进制。
2. 在无 sudo 环境下，从 Ubuntu 包源下载 Chromium 所需系统库 `.deb`，并解包到 `/tmp/chromium-libs`。

本地无 root 回退依赖路径：

```text
/tmp/chromium-libs/usr/lib/x86_64-linux-gnu
/tmp/chromium-libs/lib/x86_64-linux-gnu
```

浏览器测试的 `tests/browser/conftest.py` 会自动把上述路径加入 `LD_LIBRARY_PATH`，并从 `~/.cache/ms-playwright/` 查找可用的 Chromium 或 headless shell。若 `/tmp` 被系统清理，重新执行 `./script/setup-browser-deps.sh` 即可恢复浏览器测试环境。

快速验证：

```bash
uv run pytest tests/browser/ -v
uv run pytest
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
