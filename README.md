# MiGuOrca

MiGuOrca 是一个面向季度新番的 Auto Bangumi 前置订阅编排工作台，目标是在 MiKanProject 与 Auto Bangumi 之间提供 MiKan 订阅源发现、筛选预览、批量草案审核与提交辅助能力。

Stage 28「草案一致性与原子保存确认」已完成：为服务端权威草案建立单调 revision 与 compare-and-swap（乱序旧写不再覆盖最新重算），把保存改为「预留 → 持久化 → 提交/释放」（写盘失败同一草案可重试），建立持久化 save-confirm 幂等记录（跨进程重试/响应丢失不重复创建 Request），新增单番 `POST /api/v1/requests/save-confirm` 与批量 `POST /api/v1/batches/{batch_id}/save-confirm` 组合端点（批量 1～36 部服务端边界 + 逐条部分成功），并新增 Request `safe-info` 严格白名单 DTO 作为“全部信息”唯一安全数据源。实现与验收见 `docs/MiGuOrca_stage28_draft_consistency_PRD.md`。

Stage 29「统一追番记录与可靠提交恢复」已完成：建立本地 `TrackingRecord`（确定性 opaque `tracking_id`、revision compare-and-swap、内嵌审计）与独立 `TrackingOperation`（跨重启提交幂等与恢复证据）；任意 tracking API 首次访问前以纯本地、可重入方式把历史 Request/旧 batch queue/已保存 AB result 幂等回填为统一追番记录；accept/save-confirm handoff 向后兼容扩展 `tracking_id/tracking_status/tracking_ready/safe_message`；新增统一追番列表/安全详情/纯本地复核/可靠提交/重试/人工恢复 API（`/api/v1/tracking/items*`），旧单番 submit-ab 与批量 submit/retry/recover 共享同一 submission service，旧 batch queue 作为兼容投影双向同步且绝不降级已落盘成功；结果未知必须先恢复，禁止盲目重复创建外部订阅。实现与验收见 `docs/MiGuOrca_stage29_unified_tracking_PRD.md`。

Stage 30「Auto Bangumi 只读能力与外部同步基础」已完成 B-C1：以 Auto Bangumi 3.1.18 官方源码契约为事实源，冻结 password request-scoped 只读 adapter、capability 探测、ExternalMapping v1、严格对账、`EXTERNAL_ONLY` 和 `VERIFY_EXTERNAL`；新增 `POST /api/v1/autobangumi/capabilities` 与 `POST /api/v1/tracking/sync`，同步进入 OpenAPI、endpoint inventory 和生成 TypeScript client。未知版本/API Token 管理读取 fail closed，Stage 30 不实现外部管理写操作或正式追番管理页面。后续 B-C2 handoff 仅允许在可靠写状态机、confirm/idempotency/revision 和“绝不删除媒体”边界冻结后实现 `MODIFY`、`SET_ENABLED`、`DELETE_EXTERNAL`、`REFRESH_RSS`。

Stage 31「Auto Bangumi 可靠写管理」已完成 B-C2：在精确 3.1.18 password capability 下交付 `MODIFY`、`SET_ENABLED`、`DELETE_EXTERNAL`、`REFRESH_RSS` 的 request-scoped adapter、tracking operation v2、confirm/idempotency/revision CAS、写后只读回查与 `VERIFY_EXTERNAL` 恢复；番剧停用/删除固定 `file=false`，RSS 只处理启动时映射的单项集合，删除始终保留本地 Request、TrackingRecord、审计、任务与媒体。四个管理 API、OpenAPI、endpoint inventory 和生成客户端已同步；本阶段仍不实现正式追番管理页面。实现与验收见 `docs/MiGuOrca_stage31_ab_write_management_PRD.md`，B-D 兼容/迁移/安全矩阵与前端 handoff 进入 Stage 32。

Stage 32「后端契约固化、兼容迁移与前端交接」已完成 B-D：冻结 B-A～B-C2 端点生命周期、严格 DTO/OpenAPI/生成类型、旧入口兼容与 tracking 权威状态、历史 schema 迁移、capability 降级、安全泄漏矩阵、发布回退和版本化前端 handoff。US-247～US-256 已全部通过并归档；不新增管理动作、不删除仍有调用方的旧端点、不开发正式追番管理页面。执行范围见 `docs/MiGuOrca_stage32_contract_hardening_PRD.md`。

Stage 33 已完成 F-A「前端应用壳层与设计系统」（US-257～US-265）：基于 Stage 32 合入后的生成契约交付“添加番剧 / 追番方案 / 追番管理 / 设置”四项导航、新旧路由安全迁移、语义设计 Token、桌面壳层、共享状态视觉及现有页面兼容挂载。`/app/tracking` 仍使用现有 `QueueView` 兼容内容，不代表正式追番管理；F-B～F-G 继续独立评审。执行记录见 `docs/MiGuOrca_stage33_frontend_shell_PRD.md`。

Stage 27「前端工程化迁移与页面重构」已完成：建立 Vue 3 + TypeScript(strict) + Vite 独立前端工程，以 Stage 26 OpenAPI/DTO 生成类型化客户端，迁移 Settings、Request 列表与详情、单个与批量工作台及提交队列，完成响应式、无障碍、缓存和安全收敛；默认入口已切换到 Flask 同源托管的 `/app/*` SPA，旧 Jinja 主页面、`app.js` 与旧 CSS 已删除。实现与验收见 `docs/MiGuOrca_stage27_frontend_engineering_migration_PRD.md`。

Stage 26「Web API 契约固化与服务端边界治理」已完成：冻结全部 `/api/v1` 端点清单与 golden contract、建立响应 DTO 与确定性 OpenAPI（`docs/api/openapi.json`）、按职责拆分 Web schema/serializer/service/context/route、为失败建立稳定 HTTP 状态（400/404/409/401/502/503/504/500）、把 Web storage 限制为服务端根目录下相对 profile（空值回落服务端根）、用服务端权威 DraftStore 替代客户端完整 Request 持久化，并建立 CI、静态检查、OpenAPI 漂移检查、真实 Chromium 门禁及 local-only 部署基线。实现与验收见 `docs/MiGuOrca_stage26_web_api_contract_hardening_PRD.md`。

Stage 25「正式番名与季数解析」已完成：单个与批量搜索共用结构化 season（`number/raw/normalized/source`）、确定性解析和有界查询计划；真实 MiKan 合集仍由用户显式选择，非第一季缺少候选公开证据时必须明确确认。AutoBangumi 3.1.18 可选使用服务端解析并校验的 MiKan 原始海报作为 `poster_link`，绝不使用浏览器 opaque 代理地址。实现与验收见 `docs/MiGuOrca_stage25_title_season_parsing_PRD.md`。

Stage 24「AutoBangumi 真实认证与订阅兼容闭环」已完成：默认以服务地址、用户名和密码登录兼容 AutoBangumi 3.1.18，同时保留新版 API Token/Bearer 兼容模式；Settings 提供只读连接测试，单个与批量已接受 Request 复用经验证的 `/api/v1/rss/subscribe` 映射和提交编排。执行范围见 `docs/MiGuOrca_stage24_autobangumi_compatibility_PRD.md`。

Stage 21 在 Stage 19/20 批量草案与提交前队列之上完成用户偏好与智能推荐闭环：用户在 `/settings` 偏好面板显式保存非敏感偏好（偏好字幕组/排除字幕组、fallback、筛选规则、文件夹命名策略与模板、搜索增强开关），批量草案生成时把这些偏好作为单卡可编辑默认值应用，减少逐卡修改次数；用户明确提交的非敏感标题修正（raw_title、公开 canonical title、季数提示、公开 bangumi 元数据、query_correction）有界存储并被展开为可审核增强搜索词，增强失败时回退原始搜索词；批量卡片展示偏好命中摘要、低置信度/多候选/冲突等 `needs_user_review` 审核提示和搜索词来源。偏好与修正只保存非敏感字段，endpoint、token、cookie、Authorization header、magnet、raw HTML、raw RSS XML、原始响应体和本地绝对路径从偏好 JSON、API 响应、页面、URL、浏览器 storage、日志和 trace 中被拒绝或剥离。Stage 20 在 Stage 19 的批量订阅草案工作台上扩展为批量接受与 Auto Bangumi 提交前队列；Stage 19 建立了批量输入和卡片工作台。Stage 22 保持这些历史能力与安全边界，并已收敛单个/批量真实候选链路。

## 项目目标

MVP 已完成单番剧订阅草案闭环，后续方向调整为“批量新番订阅前置工作台”：

1. 接收用户从季度新番推荐视频、清单或聊天中整理出的一批番剧简称。
2. 使用 AI 名称解析与搜索词增强，将 `萌王S4`、`路哥S4`、`杖剑谭S2`、`邻家天使S2` 等模糊输入转换为可搜索、可审核的候选标题。
3. 为每个条目搜索并分析 MiKanProject 数据，生成番剧订阅草案卡片。
4. 允许用户逐个审核、删除、展开查看、修改字幕组/筛选规则/文件夹名和有效种子。
5. 支持单个接受、批量接受和全接受；接受后进入 Auto Bangumi 提交流程。

MiGuOrca 不定位为 Auto Bangumi 或 qBittorrent 的替代品。下载执行、长期订阅执行和下载任务创建继续交给 Auto Bangumi / qBittorrent；MiGuOrca 的价值来自订阅前判断、批量编排和用户可审核的配置生成。

## 目前状态

- Stage 21 已把用户偏好与智能推荐闭环接入 `/index` 与 `/settings`：`/settings` 的 `#preference-settings-panel` 管理非敏感偏好（偏好字幕组/排除字幕组、fallback、筛选规则、正则/大小写选项、命名策略与模板、搜索增强开关），保存成功刷新规范化值，清空/恢复默认需显式确认；批量草案生成时偏好作为单卡可编辑默认值——批量解析响应为每个 PARSED 条目附加可编辑的 `preview_request` 草案骨架（PENDING_CONFIRM，`request_id` 由 batch/item 派生，携带偏好驱动的字幕组/筛选/文件夹默认值，种子区在选中 MiKan 合集前为空），卡片因此可直接进入预览修改/保存草案/接受流程；字幕组偏好经 M05 `select_subtitle_group` 先排除、再优先、最后 fallback；批量卡片展示偏好命中摘要、低置信度/多候选/冲突审核提示和搜索词来源。搜索词增强闭环基于用户明确提交的非敏感 `TitleCorrection`（`<storage>/corrections/` 有界存储，同 raw_title 最新版本 + 全局 500 条上限），**接受卡片时前端自动记录用户确认的 raw_title → canonical title / season hint / bangumi 元数据 / query 修正**，`search_enhancer` 纯函数展开为可审核增强搜索词，增强失败/修正为空/文件损坏时回退原始 `search_queries`；修正保存失败不阻断接受流程。无偏好或偏好读取失败时当前 item 单独回退 Stage 19 默认流程，不阻塞同批次其他 item；AI 只生成候选，不自动选择最终 MiKan 合集，不自动接受卡片。
- Stage 20/24 已把批量接受、全接受、提交前队列和 Auto Bangumi 顺序提交接入 `/index`：批量工作台提供单卡接受、可勾选选择、批量接受和全接受入口，明确显示选中数量和不可接受原因；已接受卡片进入独立追踪的提交前队列，`#batch-queue-panel` 展示队列项目标题、中文状态（待提交/提交中/提交成功/提交失败/可重试）、尝试次数和脱敏结果摘要；提交前表单使用服务地址与默认账号密码（可切换 API Token）、fallback 和显式确认，提交成功后清空敏感输入；失败项可独立重试，成功项不会被重复提交。批量提交采用前台顺序编排，不引入后台 worker，刷新后通过 URL `batch_id` 恢复队列状态。
- Stage 19 已把批量新番订阅前置工作台接入 `/index`：批量输入按非空行生成独立条目，AI 名称解析 fake provider 和 provider seam 输出候选标题/搜索词，批量 API 对每个条目独立搜索 MiKan 候选，卡片网格支持删除、展开、单卡修改回流和单卡接受。
- Stage 18 已把真实 MiKan 候选搜索设为普通 Web 主流程；fixture 仍保留为 CLI、API seam、离线开发和测试路径。Web UI 的 fixture 入口放在 `/index` 底部「开发 / 离线测试」面板中并默认收起，普通用户路径不会触发 fixture 生成。系统内置默认 MiKan 搜索 endpoint（`https://mikanani.me/Home/Search`）与 timeout（15 秒），普通 UI 不再要求用户填写 `search_endpoint` / `timeout_seconds` / `query`。
- Stage 24 AutoBangumi 真实认证与订阅兼容闭环与 Stage 25 BL-018 均已完成。部署/配置向导及其他条件触发事项继续记录在 `docs/backlog.md`，流式封面代理记录在 `docs/optional_features.md`；后续阶段按 backlog 动态规划。
- Stage 27「前端工程化迁移与页面重构」已完成：Vue 3 + TypeScript(strict) + Vite 工程、OpenAPI 类型化客户端、统一 API transport、4 条 SPA 路由以及全部 Web 用户旅程均已迁移；US-209 已删除旧 Jinja 主页面、`app.js`、旧 CSS 与迁移期测试脚手架，默认入口固定重定向到 `/app/*`。
- Stage 28「草案一致性与原子保存确认」已完成：服务端草案带单调 revision（签发为 1、成功 CAS 修改 +1），`preview-modify` 必填 `base_revision` 做 compare-and-swap（过期 base → 409 `draft_revision_conflict`，只报 field/current_revision），`preview-save` 改为「预留 → 持久化 → 提交/释放」（写盘失败保留原 revision 可重试，正在保存 → 409 `draft_reserved`）；storage engine 新增持久化 save-confirm 幂等记录（`<storage>/idempotency/`，只含非敏感白名单字段），单番/批量 save-confirm 组合端点一次完成校验、保存、确认与幂等提交并返回 ACCEPTED handoff，批量逐条部分成功且强制 1～36 部服务端边界；`safe-info` 以 `extra="forbid"` DTO + 默认拒绝 serializer 提供“全部信息”唯一安全数据源。
- Stage 29「统一追番记录与可靠提交恢复」已完成：TrackingRecord/TrackingOperation 以严格 schema v1 白名单 + 原子写落地到 `<storage>/tracking|tracking_operations|tracking_migrations`，同一 Request 的 ensure/重放/迁移始终收敛到同一确定性 `tracking_id`；单番/批量 save-confirm 与 accept handoff 返回 tracking 状态，tracking 写失败不回滚已确认 Request；`/api/v1/tracking/items` 列表/详情提供稳定状态、状态组、服务端 `available_actions` 与安全审计摘要；revalidate 纯本地复核（不接收 AB 凭据）、submit/retry 严格幂等且外部调用前先持久化 SUBMITTING/IN_PROGRESS，结果未知必须先 recover（AUTO 只看本地证据）；旧单番 submit-ab 与批量 submit/retry/recover 复用统一 submission service，旧 queue 为兼容投影，双写失败不覆盖已落盘成功。
- Stage 26「Web API 契约固化与服务端边界治理」已完成：`/api/v1` 端点清单与 golden contract 冻结、响应 DTO（`extra="forbid"`）与确定性 OpenAPI、Web 适配层按职责拆分（schemas/serializers/services/contexts/routes_*）、稳定 HTTP 状态语义、Web storage 根目录限制（空值回落服务端根）与服务端权威 draft 生命周期、CI 与 local-only 部署基线；本阶段未更换页面框架，页面主要视觉与用户流程保持不变。
- 已支持标题匹配、RSS 解析、字面/正则筛选、字幕组选择、目录命名和 JSON 输出。
- 已支持 Request 确认、取消和受限修改；确认后的 `ACCEPTED` Request 仍可执行相同受限字段的修改，并可显式删除；修改/删除后保持原有安全边界。
- 已建立 Auto Bangumi 提交结果契约、Request 到 AB payload 映射、fake client、真实 HTTP client adapter、失败降级 JSON 和显式配置读取。
- 已建立真实 MiKanProject 数据源 adapter、可注入 HTTP transport、搜索页解析、合集详情页结构化解析、字幕组级 RSS 优先输出、番剧级 RSS fallback、真实 RSS XML 读取和安全错误归一化。
- 当前 CLI 只有在显式传入 `--source mikan` 和 `--mikan-config` 时才会构造真实 MiKan client；可额外传入 `--mikan-bangumi <url-or-id>` 直接读取指定合集详情页并跳过搜索；只有在显式传入 `--submit-ab` 和 `--ab-config` 时才会构造真实 Auto Bangumi HTTP client；只有在显式传入 `--save-request` 时才会写入本地 JSON 存储。
- 已提供 Web UI（Stage 27 迁移为 Vue SPA，US-209 已删除旧 Flask/Jinja 页面与 `app.js`）：`/` 重定向到 `/app/workbench`，`/index` 是订阅方案工作台入口（重定向到 `/app/workbench`），`/settings` 是配置与连接测试页面（重定向到 `/app/settings`），`/Settings` 重定向到 `/app/settings`。
- `/index` 主流程通过真实 MiKan 候选搜索生成订阅方案，可以搜索/筛选/排序本地 Request、读取 URL 可恢复的分组详情，并执行确认、可见取消表单和受限修改；候选选择与直连 fallback 默认生成可编辑的 `订阅草案（未保存）` 预览，可修改字幕组/筛选规则/文件夹名并重算种子展示，点击 `保存草案` 后才进入待确认流程。fixture-backed 生成不参与普通主流程，而是放在页面底部「开发 / 离线测试」面板中，面板默认收起，需开发者手动展开才能使用。
- 已保存 `ACCEPTED` Request 详情同时展示 `修改`、`删除` 和 `去 Settings 提交 Auto Bangumi` 动作；`修改` 复用详情内修改表单并保持 `ACCEPTED` 状态，`删除` 需显式确认并刷新列表、清空详情和移除 URL `request_id`。
- Request 详情的 Filter 分区展示包含规则、排除规则、匹配模式（普通字符或正则）和大小写状态；Seeds 分区按 有效种子 -> 完整种子（按字幕组分组）-> 排除种子 的顺序展示：有效种子默认可见并标注 `当前选中字幕组`，完整种子按 MiKan 字幕组分组（每组显示字幕组名、种子数量并可展开），完整种子与排除种子默认折叠，排除原因使用 `命中排除规则` / `未命中包含规则` 可读语言。
- 筛选编辑控件使用 `包含规则` / `排除规则` 标签，并提供默认未勾选的 `使用正则` 与 `大小写敏感` 复选框；默认提交发送 `use_regex=false` / `case_sensitive=false`，字面文本 `[`、`[v2]` 不会触发正则错误。
- `/settings` 可以管理非敏感 Storage 浏览器偏好、直接显示并显式测试 qBittorrent 连接，并在 `/settings?request_id=<id>#auto-bangumi` 中对 `ACCEPTED` Request 执行显式 Auto Bangumi 提交配置。
- Stage 16 已完成真实 MiKan 合集详情页离线 fixture、结构化详情模型、字幕组级 RSS 优先、direct URL/ID 入口和真实读取错误脱敏；默认流程不连接 qBittorrent，不启动下载，不改变 AB 提交流程。
- Stage 17 已完成真实 MiKan 搜索候选合集展示与用户手动选择：`MikanClient.search_candidates` 从搜索页 `相关推荐` 解析候选卡片并规范化为绝对 HTTP(S) `/Home/Bangumi/<numeric-id>`，按页面顺序返回并按 `bangumi_id` 去重；Web API `POST /api/v1/mikan/candidates` 提供 request-scoped 候选搜索，返回只含公开候选元数据和推荐标签的 sanitized envelope。Stage 18 已把该能力从折叠的附属入口调整为 `/index` 普通 Web 主流程，并提供系统默认 MiKan 配置和可编辑预览草案。Stage 19 已在此基础上新增 `POST /api/v1/batches/parse` 和批量卡片工作区。Stage 20 已在此基础上新增 `POST /api/v1/batches/<batch_id>/accept`、`GET /api/v1/batches/<batch_id>/queue`、`POST /api/v1/batches/<batch_id>/submit`、`POST /api/v1/batches/<batch_id>/retry` 和 `POST /api/v1/batches/<batch_id>/recover`，完成批量接受、提交前队列、顺序提交、失败项独立重试和卡住项目恢复闭环。Stage 21 已在此基础上新增 `GET/POST /api/v1/preferences` 与 `GET/POST /api/v1/corrections`，完成非敏感偏好与用户修正的显式保存、读取和恢复默认闭环。

## 关键约定

- Python 包名：`migu_orca`
- CLI 命令：`migu-orca`
- 配置目录：`~/.config/migu_orca`
- 日志名：`migu_orca`

## 开发约定

本项目使用 `UV` 进行 Python 包管理和命令执行。

- 安装依赖：`uv sync`
- 运行测试：`uv run pytest`
- 语法检查：`uv run python -m compileall -q src tests`（只证明可编译，不是静态检查）
- 静态检查：`uv run ruff check src tests`（US-195 引入；pyflakes/bugbear/pyupgrade 规则，
  配置见 `pyproject.toml` 的 `[tool.ruff.lint]`。编译通过≠静态通过，CI 两者都跑）
- 运行入口命令：`uv run migu-orca "咒术回战第三季"`
- 生成/检查 OpenAPI 契约：`uv run migu-orca-openapi` / `uv run migu-orca-openapi --check`（漂移检查，CI 使用）
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
  - `preferences/`：保存非敏感 `user_preferences.json`（Stage 21 偏好管理）。
  - `corrections/`：保存用户明确提交的非敏感 `TitleCorrection` 记录（Stage 21 搜索词增强，同 raw_title 最新版本 + 全局 500 条上限）。
- `.migu_orca/storage` 是运行数据目录，不应提交到 Git；如需长期保留，请由部署方在仓库外指定 `--storage-dir`。
- CLI 和高级 API 的 MiKan config JSON 字段为 `search_endpoint`、`timeout_seconds`：
  - `search_endpoint`：MiKanProject 搜索页 endpoint，由调用方显式提供；程序会追加 URL 编码后的 `searchstr` 查询参数。
  - `timeout_seconds`：真实 MiKan 搜索页、番剧页和 RSS XML 读取的超时时间，必须为正数。
- 当前真实 MiKan adapter 会从搜索结果中解析包含 `/Home/Bangumi/` 的候选番剧链接；也可以通过 `--mikan-bangumi` 或 Web API `mikan_bangumi` 直接读取指定合集。详情页 parser 会输出安全结构化元数据（bangumi id、标题、规范化详情 URL、可选播出/海报、番剧级 RSS、字幕组条目和单集标题/详情链接摘要），并优先把字幕组级 RSS 转换为 `mikan_http` `RssSource`。存在字幕组级 RSS 时不混入番剧级 RSS；没有字幕组级 RSS 但有番剧级 RSS 时使用 `全部字幕组` fallback。
- MiKan direct entry 接受同源 HTTP(S) `/Home/Bangumi/<numeric-id>` URL 或 bare numeric ID；bare ID 的 host 从显式 MiKan config 的 `search_endpoint` 派生。空值、非 HTTP(S)、跨源 URL、非 Bangumi path、路径穿越和非数字 ID 都会返回脱敏错误。Stage 17 已在 Web UI `/index` 的候选搜索区中接入直连 URL/ID fallback，候选选择和 fallback 都复用 Stage 16 `mikan_bangumi` direct-entry 链路。
- Stage 17 候选搜索 Web API 为 `POST /api/v1/mikan/candidates`，请求体支持 `query` 和可选 `mikan_config`（`search_endpoint`、`timeout_seconds`）；未传 `mikan_config` 时系统使用默认 MiKan 配置（`https://mikanani.me/Home/Search`，timeout 15 秒），普通 Web UI 已不再要求用户填写这些字段。响应只返回 sanitized 公开候选元数据（`bangumi_id`、`title`、`mikan_url`、`poster_url`、`source_query`、`aliases`）和 display-only `recommendation` 标签。进程内候选缓存 key 使用 `mikan-candidates:<sha256[:32] of search_endpoint>:<normalized query>`，只缓存公开候选元数据并带 TTL，命中时不调用 transport；候选搜索、选择、fallback 的 MiKan config 都是 request-scoped，不写入 storage JSON、浏览器 storage、URL、history、日志或截图。
- 错误 details、日志、fixture 和示例配置不得包含原始 HTML、原始 RSS XML、完整 endpoint URL、cookie、token 或其他敏感配置值。
- `--submit-ab` 必须和 `--action accept`、`--ab-config <path>` 显式组合使用；未传 `--submit-ab` 时不会触发 Auto Bangumi 提交流程，也不会实例化真实 HTTP client。
- AB config 使用服务根地址和显式认证模式：默认 `password` 使用 `base_url`、用户名和密码登录并保持单次 Cookie 会话；兼容 `api_token` 使用 `base_url` 和 Bearer token。两种凭据互斥，固定 API 路径由 adapter 拼接，所有凭据只用于当前请求。
  - `fallback_enabled`：提交失败时是否在 `ab_submit_result.fallback_config` 中输出可人工处理的降级 JSON。
- AutoBangumi 3.1.18 client 通过 form 登录 `/api/v1/auth/login`，以单次 Cookie 会话调用 `/api/v1/status` 和 `/api/v1/rss/subscribe`；订阅 body 为 `{data: Bangumi, rss: RSSItem}`，`status=true` 即成功且外部订阅 ID 可为空。`data.poster_link` 仅可来自服务端从 MiKan 页面解析、规范化并校验的公开 HTTP(S) 原始海报 URL；缺失海报不阻断订阅，opaque 同源代理 URL 与客户端字段均不会传播。API Token adapter 仅在已证明的写契约下提交，当前未知版本一律 fail closed。
- Web UI 真实 Auto Bangumi 配置只在当前提交中使用，不能写入 storage JSON、状态历史、浏览器 `localStorage` / `sessionStorage`、URL query、日志、截图或测试 trace。
- qBittorrent 配置同样必须保持 request-scoped：endpoint、username、password、cookie、SID、敏感路径和原始响应体不能写入 storage JSON、状态历史、浏览器 storage、URL、日志、截图、测试 trace 或 API 响应。
- Stage 15 允许 Settings 将非敏感 Storage 偏好写入浏览器 `localStorage`，键名为 `miguOrca.web.storageDir` 和 `miguOrca.web.saveRequest`；URL query 只能携带 `request_id` 等非敏感上下文。缺省 `saveRequest` 表示开发/离线 fixture 生成默认保存，显式 `"false"` 表示预览模式；真实 MiKan 候选选择与直连 fallback 始终生成可编辑预览草案，与 `saveRequest` 偏好无关。
- 筛选规则默认按普通字符匹配：规则文本以字面子串（substring）形式出现在种子名中才算命中，大小写不敏感；`use_regex=true` 才按正则编译，`case_sensitive=true` 才区分大小写。筛选规则是用户输入的非密文字符串，允许写入 saved Request，但错误消息不得包含本地存储路径或原始外部响应。
- 真实 MiKan 合集详情页解析和 direct URL/ID 入口已在 Stage 16 完成；搜索候选展示、手动选择、候选缓存和推荐标签已在 Stage 17 完成；真实 MiKan 搜索收敛为 Web 主流程、默认 MiKan 配置、直连兜底勾选框、可编辑预览订阅草案、中文状态和 Seeds 分组展示已在 Stage 18 完成；批量输入、AI 名称解析 seam、批量候选搜索、订阅草案卡片、单卡修改回流和单卡接受已在 Stage 19 完成；批量接受、全接受、提交前队列、Auto Bangumi 顺序提交和失败项独立重试已在 Stage 20 完成；非敏感偏好保存/应用、审核元数据展示、用户修正驱动的搜索词增强和偏好管理 Web UI 已在 Stage 21 完成。Stage 20 的队列只保存非敏感元数据，endpoint/token/cookie/Authorization header/原始响应体/完整 RSS URL/magnet/本地绝对路径从不进入队列 JSON、Request snapshot、API 响应、浏览器 storage、URL、日志、截图或 trace；批量提交采用前台顺序编排，不创建 qBittorrent 下载任务，不绕过 Auto Bangumi，不引入后台常驻 worker。Stage 21 的偏好与修正存储只保存非敏感字段，endpoint/token/cookie/Authorization header/magnet/raw HTML/raw RSS XML/原始响应体/完整失败 URL/本地绝对路径从不进入偏好 JSON、修正 JSON、API 响应、页面、URL、浏览器 storage、日志或 trace；`load_user_preferences` 对未知键在加载时剥离，偏好表单只提交已定义的非敏感字段，被拒绝的敏感输入回退到上次有效值。

## Web UI 与 API

当前 Web UI 是 Stage 27 迁移的独立前端工程（Vue 3 + TypeScript + Vite），已累积接入 Settings、真实 MiKan 候选、可编辑预览、批量草案、提交前队列、偏好、媒体缓存、AutoBangumi 3.1.18 兼容、Stage 25 标题季数解析与 Stage 28 草案一致性和保存确认。业务操作统一通过 `/api/v1/*` JSON API 编排，CLI 默认行为保持不变。

Stage 27 已把 Web UI 迁移到独立前端工程并完成入口切换：`frontend/` 是 Vue 3 + TypeScript(strict) + Vite 工程（npm 管理，`package-lock.json` 已入库）。生产构建输出到 `frontend/dist/`（不入库），由 Flask 在 `/app/` 同源托管（`routes_app.py` 的 `app_blueprint`）；Vite `base` 固定为 `/app/`，SPA fallback 只接管 `/app/*` 路径，绝不截获 `/api/v1/*`、海报、`/healthz`、`/readiness` 或入口路由。开发时可 `cd frontend && npm run dev`（Vite dev server 代理 `/api/v1` 到本地 Flask）。US-197 建立了工程基线（typecheck/lint/unit/build 全绿 + CI 门禁）；US-199 建立了统一 API transport（`frontend/src/api/client.ts`，处理 envelope/非 2xx/非 JSON/网络失败/取消/超时，feature 不得自行拼接 `/api/v1` URL）、4 条 SPA 路由（工作台/订阅方案/提交队列/Settings）与全局 loading/空状态/错误边界/aria-live 通知。US-201 已迁移 Settings（storage 偏好/非敏感偏好/qB/AB 连接测试与提交上下文）；US-202 已迁移 Request 列表（`/app/requests`：加载、搜索、状态筛选、排序、计数、空状态、`request_id` 刷新恢复与复制）；US-203 已迁移 Request 详情与管理动作（`/app/requests` 详情面板：Overview/Source/Filter/Seeds/Audit、确认/取消/修改/删除、AB 提交入口）；US-204 已迁移单个搜索与服务端草案（`/app/workbench`：真实 MiKan 候选搜索、直连 fallback、季数确认/冲突禁用、可编辑订阅草案 preview-modify/preview-save，`candidate_context`/`draft_id` 只在内存）；US-205 已迁移批量工作台（`/app/workbench` 批量工作台区：批量输入、独立 FOUND/EMPTY/FAILED 卡片、候选浮层、共享草案详情与删除、选择/单个接受/批量接受/全接受，统一走 `POST /api/v1/batches/{batch_id}/accept`，`batch_id` 进 URL 供提交队列刷新恢复）；US-206 已迁移提交队列（`/app/queue`：从 URL `batch_id` 恢复队列、逐项提交/失败重试/恢复（自动 + 人工核验）、防重复提交，AB 凭据只在内存与单次 POST body）。US-207 完成跨功能收敛：键盘 skip link、批量候选浮层焦点管理（打开聚焦/Escape 关闭/焦点恢复）、360/768/1280 无横向溢出、状态不只靠颜色、reduced-motion 反馈、vendor chunk 分包、`/app/assets/*` immutable 缓存 + shell no-cache、build 无 sourcemap（详见 `tests/browser/test_app_responsive_a11y.py`）。US-208 完成 parity 与默认入口切换（旧 269 个 Chromium 旅程到新路由的 parity 矩阵，`/index`、`/settings` 及 `request_id`/`batch_id` 兼容入口默认重定向到新前端，并演练了不修改业务数据的入口回退）。US-209 完成收尾：删除旧 `app.js`、旧 Jinja 主模板与无用 CSS/测试 helper，入口路由固定重定向到 SPA，parity 矩阵与回退演练归档为 Stage 27 完成证据，README/架构/模块/backlog 全部同步。

启动方式：

```bash
uv run flask --app wsgi:app run
```

启动后访问：

- `GET /`：重定向到 `/app/workbench`（US-208/209 起默认入口为新前端）。
- `GET /index`：重定向到 `/app/workbench`（保留 `request_id`/`batch_id` query；
  旧 Jinja 页面已在 US-209 删除）。
- `GET /settings`：重定向到 `/app/settings`（保留 `request_id` query）。
- `GET /Settings`：重定向到 `/app/settings`。
- `GET /app/`：新 Vue SPA 外壳（US-197 起）；`/app/workbench`、`/app/requests`、
  `/app/queue`、`/app/settings` 是 SPA 路由（US-199 起 4 条导航），由 Vue Router 处理，
  刷新时由 Flask fallback 返回外壳。
- `GET /healthz`：存活探针。只证明 Flask 进程在服务，不做任何存储或外部系统工作。
- `GET /readiness`：就绪探针（US-195）。进程在服务**且**服务端 Web storage 根目录可用
  （可创建/可写）时返回 200 `{"ok": true, "result": "ok"}`；storage 不可用时返回 503
  `{"ok": false, "result": "storage_unavailable"}`。只触碰本地存储布局，绝不探测或写入
  真实 MiKan / AutoBangumi / qBittorrent。

> US-209 入口固化：`views.py` 的入口路由始终重定向到 SPA（旧 Jinja 页面与
> `MIGU_ORCA_WEB_ENTRY_LEGACY` 回退开关已随旧前端删除），只转发公开
> `request_id`/`batch_id` 标识符，API 与 storage 行为不变。

新前端 `/app/workbench` 包含真实 MiKan 候选搜索主表单、可编辑预览订阅草案、批量工作台；`/app/requests` 提供本地 Request 列表、URL 可恢复的详情区域、状态历史和 AB 提交结果摘要；`/app/settings` 提供 Storage 偏好、偏好默认值、qBittorrent 和 Auto Bangumi 分区。页面提供共享顶部导航、运行模式摘要、非空标题浏览器校验、提交中按钮状态、Settings Storage 偏好只读摘要、列表文本搜索/状态筛选/排序、详情 Overview/Source/Filter/Seeds/Audit 分组、统一成功/错误通知、可恢复操作按钮、可见取消/修改表单、窄屏单列布局和基础无障碍标记。候选选择与直连 fallback 默认生成 `订阅草案（未保存）` 预览，不展示确认、取消、删除或 Auto Bangumi 提交动作；预览提供可编辑表单（字幕组、包含/排除规则、使用正则、大小写敏感、folder_name），`应用修改` 通过 dry-run 预览修改端点重算当前选中字幕组的有效/排除种子展示，`保存草案` 持久化修改后的订阅方案并同步 `request_id` 到 URL 进入待确认流程。已保存 `ACCEPTED` Request 详情展示 `修改`、`删除` 和 `去 Settings 提交 Auto Bangumi` 动作，`删除` 前必须经浏览器确认框确认。Filter 分区展示包含规则、排除规则、匹配模式（普通字符或正则）和大小写状态；Seeds 分区按 有效种子（默认可见并标注当前选中字幕组）-> 完整种子（按字幕组分组，默认折叠）-> 排除种子（默认折叠）的顺序展示。`/app/settings` 页面包含 Storage 偏好、偏好默认值、qBittorrent 和 Auto Bangumi 分区；Storage 偏好只写入浏览器 `localStorage`，qBittorrent 连接测试表单直接显示，Auto Bangumi 按 `request_id` 上下文渐进展示，提交前必须显式确认。页面和 API 都不应展示 token、完整 endpoint URL、qBittorrent username、password、Authorization header、cookie、SID、原始 HTML、原始 RSS XML、原始响应体或本地绝对路径。

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

当前 API（US-193 起 `storage_dir` 是服务端允许根目录下的**相对 profile**，未传时回落服务端根目录本身；CLI 的显式 `--storage-dir` 路径行为不变）：

- `GET /api/v1/requests`：列出已保存 Request 摘要。未传 `storage_dir` 时使用服务端 storage 根目录（默认 `.migu_orca/storage`，可用 `MIGU_ORCA_WEB_STORAGE_ROOT` 覆盖）。
- `GET /api/v1/requests/<request_id>`：读取完整 Request snapshot，并附带可用的 `history` 与 `ab_result` 只读数据。
- `GET /api/v1/requests/<request_id>/safe-info`（US-217）：返回“全部信息”弹窗专用的严格安全白名单 `{safe_info: <RequestSafeInfoDTO>}`。serializer 默认拒绝，只显式构造标题/别名/季度/公开季数证据摘要、选定 MiKan 合集标题与公开编号（不含完整合集/RSS URL）、字幕组/过滤规则用户可读摘要/相对 storage profile/安全文件夹名、有效/完整/排除资源数量与脱敏文件名摘要、`total_episodes`（暂无公开数据恒为 `null`）、`updated_episode=null`/`updated_episode_status=NOT_IMPLEMENTED`（不猜测当前集数）、Request 状态、脱敏历史与安全 Auto Bangumi 状态摘要。完整 URL、RSS、magnet、endpoint、token/cookie/password/Authorization、原始响应与本地绝对路径不出现在成功/错误/OpenAPI 示例。
- `POST /api/v1/requests`：生成 Request。请求 JSON 支持 `title`、`storage_dir`、`save_request`、`source`、可选 `mikan_config` 和 request-scoped `mikan_bangumi`。`source` 默认为 `static-fixture`；显式传入 `source: "mikan"` 时会构造真实 MiKan client，未传 `mikan_config` 时使用系统默认 MiKan 配置。存在 `mikan_bangumi` 时会直接解析指定 MiKan `Home/Bangumi/<id>` URL 或 ID 并跳过搜索；该字段不写入浏览器 storage、URL 或持久配置。API 层仍以显式 `save_request: true` 写入本地 storage；Web UI 候选选择与直连 fallback 默认发送 `save_request: false` 生成可编辑预览草案——服务端在 `DraftStore` 持有权威 `PENDING_CONFIRM` 草案并签发 opaque `draft_id` 与单调 `draft_revision`（US-194/211），`POST /api/v1/requests/preview-modify` 只接受 `draft_id` + `base_revision` + 允许 patch 做 CAS dry-run 修改并重算种子（成功返回新 `draft_revision`；base 过期返回 409 `draft_revision_conflict`），`POST /api/v1/requests/preview-save` 以 `draft_id` + `base_revision` 预留草案，**持久化成功后才消费**（US-212：写盘失败会释放预留，同一草案可重试，不再因先 pop 后落盘丢失用户编辑），进入待确认流程；draft 失效/重放返回 409 `draft_expired`/`draft_replayed`/`draft_reserved`，客户端只持有 id 与 revision，完整 Request 与草案内容绝不进入 URL 或浏览器 storage。

`POST /api/v1/requests` 示例：

```json
{
  "title": "咒术回战第三季",
  "storage_dir": "backups",
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
  "storage_dir": "backups",
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
  "storage_dir": "backups",
  "save_request": true
}
```

Stage 28 新增单番「保存并确认」端点（US-214）：

- `POST /api/v1/requests/save-confirm`：一次完成草案校验（`draft_id` + `base_revision`）、预留、持久化、确认和幂等提交。请求只接受 `draft_id`、`base_revision`、`idempotency_key` 与可选 `storage_dir`，绝不接受完整 Request。成功返回 `CONFIRMED`、已保存的 `ACCEPTED` Request 与 `handoff`（`request_id`/`status=ACCEPTED`/`next_action=OPEN_TRACKING`；Stage 29 起同时返回 `tracking_id`/`tracking_status`/`tracking_ready`/`safe_message`，同一 Request 的终态重放与后续访问都 ensure 到同一确定性 tracking_id）。同一 `idempotency_key` 重试返回同一最终结果（终态重放，不触碰草案）；不同键重放已保存草案返回 409 `draft_replayed`；持久化成功但确认失败返回 409 `save_confirm_failed`，`error_data.details` 只含 `outcome=SAVED_CONFIRM_FAILED`、公开 `request_id` 与 `retry_action=ACCEPT_SAVED_REQUEST`，客户端用既有 Request accept 契约重试确认。tracking 写入失败不回滚已确认 Request，也不伪造 tracking 状态（返回 `tracking_ready=false` 与固定安全文案，后续访问可补偿）。

Stage 28 新增批量 36 部服务端边界（US-215）：

- `POST /api/v1/batches/parse` 现在按规范化非空行计数并强制单批 1～36 部：0 部沿用 `validation_error`「请至少输入一个番剧名称」；超过 36 部在任何标题解析、MiKan 搜索或持久化 seam 之前返回 HTTP 400 `batch_limit_exceeded`，`error_data.details` 只含 `field=raw_input`、`limit=36` 与 `actual`，绝不回显原始批量输入行。`MAX_BATCH_ITEMS = 36` 定义在 `batch_engine/models`，与前端 UX PRD 的批量上限一致。

Stage 28 新增批量 save-confirm 逐条部分成功端点（US-216）：

- `POST /api/v1/batches/<batch_id>/save-confirm`：一次确认所选批量卡片，每条复用单番 save-confirm 用例（revision 校验、预留、持久化、确认与幂等结果提交）。请求每条只接受公开 `item_id`、服务端签发 `draft_id`/`base_revision` 与 opaque `idempotency_key`——绝不接受完整 Request；`item_ids` 可选，只处理选中项并保持输入顺序，省略时按 `items` 顺序处理全部。成功响应是 HTTP 200 逐条部分成功：`{batch_id, results: [{item_id, outcome, request_id?, status?, error_type?, error_message?}], summary: {requested, confirmed, failed}}`。可预期的单条业务失败（`draft_expired`/`draft_revision_conflict`/`draft_reserved`/`idempotency_conflict`/`save_confirm_failed` 等）返回逐条脱敏 `failed` 结果（固定中文 `error_message`，绝不回显 draft_id/标题/URL/路径），成功项不因失败项回滚；同一请求内重复 `item_id` 返回 `skipped`。同一 item + `idempotency_key` 幂等重试重放同一 CONFIRMED 结果，绝不创建第二个 Request。请求级 shape/batch_id/storage profile 错误仍走普通失败 envelope。

Stage 29 新增统一追番记录端点（US-223～US-226）：

- `GET /api/v1/tracking/items`：统一追番列表，任意 tracking API 首次访问前自动运行纯本地历史迁移。查询只接受安全 `storage_dir`、可选 `q`/`status_group`/`sort`（固定枚举）；返回 `items`（稳定 `status`、中文 `status_label`、`status_group`、服务端计算的 `available_actions`、`valid_resource_count` 等）、按全部健康记录计算的 `summary` 计数与固定 `warnings`。单条损坏只增加 `unreadable` 计数与固定 warning，不阻塞健康列表，也不自动删除或回显损坏文件。
- `GET /api/v1/tracking/items/{tracking_id}`：安全方案详情。summary 之外只返回 Request safe-info（唯一 producer）、当前 operation 安全摘要、revalidation issues、外部安全映射摘要和最近 20 条审计事件；完整 Request、外部原始 JSON、完整 URL、凭据、magnet 与绝对路径一律不回显。
- `POST /api/v1/tracking/items/{tracking_id}/revalidate`：纯本地复核。请求只含 `expected_revision` 与可选 `storage_dir`（不接收 `ab_config`、不探测外部）；业务复核失败仍返回 HTTP 200，`ready=false` + 固定 issue code（REQUEST_CHANGED/NO_VALID_RESOURCES 等）；只有 revision/状态冲突才 409。
- `POST /api/v1/tracking/items/{tracking_id}/submit`：可靠提交。`confirm` 必须严格 true，`ab_config` 只在单次请求内存；服务端重新读取 Request 并完整本地复核，不通过时不访问 Auto Bangumi；外部调用前先持久化 TrackingRecord `SUBMITTING` 与 operation `IN_PROGRESS`。已落盘业务结果（`ACTIVE`/`SUBMIT_FAILED`/`VERIFYING_EXTERNAL`/`RECOVERY_REQUIRED`/`NEEDS_RECONFIRM`）返回 HTTP 200；同一 `idempotency_key` 终态重放复用原 operation 结果，绝不二次调用外部。
- `POST /api/v1/tracking/items/{tracking_id}/retry`：只允许 `SUBMIT_FAILED`；新幂等键创建新 operation 并重新读取 Request/复核。
- `POST /api/v1/tracking/items/{tracking_id}/recover`：`action=AUTO|MARK_SUCCEEDED|MARK_FAILED`。AUTO 只读本地 operation/AB result/queue 证据，绝不访问外部；无证据保持/进入 `RECOVERY_REQUIRED` 并 `needs_manual=true`，人工动作必须 `confirm=true` 且写 USER 审计，MARK_SUCCEEDED 不接收外部 ID/URL/原始结果。
- 旧单番 `submit-ab` 与批量 `submit`/`retry`/`recover` 路由已收敛到同一 tracking submission/recovery service；旧 batch queue 作为兼容投影双向 best-effort 同步（queue→tracking 反映 §10.2 结果，tracking→queue 写回 SUBMITTING/终态），已 `SUCCEEDED` queue 项与已 `ACTIVE` tracking 记录绝不降级。

Stage 10 新增 Request 操作端点（确认/取消仅 PENDING_CONFIRM 状态可操作；修改同时接受 PENDING_CONFIRM 与 ACCEPTED）：

- `POST /api/v1/requests/<request_id>/accept`：确认 Request，状态变更为 ACCEPTED。
- `POST /api/v1/requests/<request_id>/cancel`：取消 Request，请求体可含 `cancel_reason` 字段。
- `POST /api/v1/requests/<request_id>/modify`：修改 Request，请求体含 `patch` 对象（允许字段：`selected_subtitle_group`、`filter_rule`、`expected_folder_name`）。修改 `ACCEPTED` Request 后状态保持 `ACCEPTED` 不回落为 `PENDING_CONFIRM`，并记录 `MODIFY` history 事件；修改后重新计算有效/排除 Seeds。

Stage 15 新增已保存 Request 删除端点：

- `POST /api/v1/requests/<path:request_id>/delete`：删除 `requests/<request_id>.json`。request_id 必须来自 URL 路径，payload 只允许携带 `storage_dir` 等现有非敏感上下文；删除函数拒绝空值、路径片段和路径穿越，返回统一脱敏错误，且响应只返回被删除 request_id 和安全摘要，不返回已删除 snapshot 的原始 JSON。删除成功后列表不再包含该 request_id，详情加载该 request_id 返回 `request_not_found`。

Stage 11 新增真实配置入口端点：

- `POST /api/v1/requests/<request_id>/submit-ab`：对 `ACCEPTED` Request 执行显式 Auto Bangumi 提交。请求体必须包含 request-scoped `ab_config`：默认账号密码模式为 `auth_mode`、`base_url`、`username`、`password`、`fallback_enabled`，API Token 模式为 `auth_mode`、`base_url`、`token`、`fallback_enabled`。提交结果会以脱敏形式写回 Request snapshot 和 `ab_results/`；服务地址、用户名、密码、token、Authorization header、cookie 和完整 URL 不应出现在 API 响应、日志或本地存储中。

Stage 12 引入、Stage 13 迁移到 Settings 使用的 qBittorrent 显式连接测试端点：

- `POST /api/v1/qbittorrent/test-connection`：执行一次用户显式触发的 qBittorrent Web API 连接测试。请求体必须包含 `qbittorrent_config` 对象，字段为 `endpoint`、`username`、`password`、`timeout_seconds` 和 `verify_tls`。端点只测试认证和轻量状态读取，不启动下载，不创建订阅，不改写 Request snapshot，也不将 qBittorrent 配置写入 storage JSON、状态历史、浏览器 storage 或 URL。

取消示例：

```bash
curl -X POST 'http://127.0.0.1:5000/api/v1/requests/<id>/cancel' \
  -H 'Content-Type: application/json' \
  -d '{"cancel_reason": "不想追了"}'
```

修改示例：

```bash
curl -X POST 'http://127.0.0.1:5000/api/v1/requests/<id>/modify' \
  -H 'Content-Type: application/json' \
  -d '{"patch": {"expected_folder_name": "自定义目录"}}'
```

显式 Auto Bangumi 提交示例：

```bash
curl -X POST 'http://127.0.0.1:5000/api/v1/requests/<id>/submit-ab' \
  -H 'Content-Type: application/json' \
  -d '{"ab_config": {"auth_mode": "password", "base_url": "http://auto-bangumi.local", "username": "replace-with-username", "password": "replace-with-password", "fallback_enabled": true}}'
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

- `POST /api/v1/batches/parse`：接收 `raw_input` 多行文本，忽略空行并为每个非空行生成独立 item（服务端强制单批 1～36 部，US-215：0 部返回 `validation_error`，超过 36 部在任何标题解析/MiKan/持久化调用前返回 400 `batch_limit_exceeded`，只报告 `field=raw_input`/`limit=36`/`actual`，不回显原始输入）。端点先通过 AI 名称解析 provider seam 生成候选标题、季数提示、搜索词、置信度和审核标记，再对每个 search query 复用 MiKan candidate search。单个 provider 或 MiKan 搜索失败只标记当前 item 为 `FAILED`，不阻塞同批次其他 item。响应只包含 batch/item 状态、解析元数据、公开候选字段和卡片展示所需的订阅草案摘要；raw HTML、raw RSS XML、cookie、token、magnet、完整失败 URL、原始响应体和本地绝对路径不会进入响应、浏览器 storage、URL 或 Request snapshot。

Stage 20 新增批量接受、队列、提交与重试端点（`batch_id` 来自 URL 路径，payload 模型仍声明 `batch_id`）：

- `POST /api/v1/batches/<batch_id>/accept`：批量接受或全接受。payload 为 `{items: [{item_id, request_id, title}], storage_dir, item_ids?}`；`item_ids` 存在时只接受选中的 item（按 batch 顺序），省略时全接受当前批次中所有可接受项目。每个成功接受的项目进入队列 `READY_TO_SUBMIT`；已 `ACCEPTED` 的项目幂等返回，不重复写入确认历史或队列——若该 `request_id` 已存在于当前批次队列则保持幂等，若队列中缺失（队列保存失败、被删除或损坏）则补建 `READY_TO_SUBMIT` 队列项目以便恢复提交；**若该 Request 已保存成功的 AB 提交结果（`ab_submit_result.success == true`）则绝不补建队列**（避免恢复出的项目被再次提交造成 Auto Bangumi 重复订阅），提交端同样检测到成功结果时直接标记 `SUCCEEDED` 而不调用 Auto Bangumi；不可接受项目（缺少 request_id/snapshot、CANCELLED、其他状态）逐项返回中文原因；单项失败不阻塞其他项。响应包含 `batch_id`、逐项状态、队列项目和不可接受原因。
- `GET /api/v1/batches/<batch_id>/queue`：读取脱敏队列。返回队列项目（标题、状态、尝试次数、时间、脱敏结果摘要）；队列不存在时返回 `{batch_id, queue: None}`。响应只包含非敏感字段，不包含 endpoint、token、cookie、Authorization header、原始响应体、完整 RSS URL、magnet 或本地绝对路径。
- `POST /api/v1/batches/<batch_id>/submit`：批量顺序提交 Auto Bangumi。payload 为 `{storage_dir, ab_config, confirm}`；`ab_config` 使用与单项完全一致的服务根地址/认证模式契约，缺少 `ab_config` 或 `confirm` 时返回中文 `validation_error` envelope。端点按队列顺序处理 `READY_TO_SUBMIT` 项目，复用现有 payload builder、Auto Bangumi client 和脱敏结果契约；提交前校验对应 Request 仍为 `ACCEPTED`。**可靠性边界**：每个项目在实际调用 Auto Bangumi 前先把 `SUBMITTING` 状态持久化到队列 JSON，调用后立即持久化最终 `SUCCEEDED`/`FAILED`/`RETRYABLE`/`RESULT_PERSIST_FAILED` 状态，因此进程在外部提交后、最终保存前中断时，磁盘队列保持 `SUBMITTING`（后续 submit/retry 会跳过该项目），不会把已到达 Auto Bangumi 的项目错误恢复成可重复提交的 `READY_TO_SUBMIT`；每个项目的脱敏提交结果（成功或失败）会按单项 submit-ab 契约写入对应 Request snapshot 的 `ab_submit_result` 字段和 `ab_results/<request_id>.json`，Request 详情 API 可直接读取展示。**单项结果持久化失败**时（Auto Bangumi 调用已发生、结果无法落盘），该项目进入独立的 `RESULT_PERSIST_FAILED`（结果保存失败）状态并继续处理其他项目——该状态**不可直接重试**（重试可能重复创建订阅），只能通过 `recover` 端点人工核验后恢复。响应逐项返回成功或失败结果，不因一项失败而中断其余项目；已成功项目不会被重复提交。
- `POST /api/v1/batches/<batch_id>/retry`：失败项独立重试。payload 为 `BatchSubmitPayload` + `request_id`；只有 `FAILED`/`RETRYABLE` 项目可重试，`SUCCEEDED`/`SUBMITTING`/`RESULT_PERSIST_FAILED` 项目返回 `skipped` 且不会再次提交。重试重新加载最新保存的 `ACCEPTED` Request 快照，从不用队列中复制的完整 RSS、token、cookie、magnet 或原始响应；提交前同样先持久化 `SUBMITTING` 再调用 Auto Bangumi，并写入脱敏提交结果；成功后更新为 `SUCCEEDED`，失败后保留可重试状态并递增 `attempts`。
- `POST /api/v1/batches/<batch_id>/recover`：恢复「卡住」的队列项目（`SUBMITTING` / `RESULT_PERSIST_FAILED`）。payload 为 `{storage_dir, request_id, action, confirm}`：
  - `action=auto`：自动恢复——仅对 `SUBMITTING` 生效；已保存且 `success=true` 的 `ab_submit_result` 自动恢复为 `SUCCEEDED`，已保存且 `success=false` 的结果按错误类型恢复为 `FAILED`/`RETRYABLE`，缺少明确 `success` 结果时返回 `needs_manual`（需人工核验）。
  - `action=succeeded`（需 `confirm=true`）：人工核验确认 Auto Bangumi 已创建订阅，恢复为 `SUCCEEDED`。
  - `action=failed`（需 `confirm=true`）：人工核验确认 Auto Bangumi 未创建订阅，恢复为普通 `FAILED`（之后可安全重试）。
  - 非卡住状态（`READY_TO_SUBMIT`/`SUCCEEDED`/`FAILED`/`RETRYABLE`）返回 `skipped` 且不改变状态。

Stage 20 批量 API 遵循与单请求 AB 提交一致的安全边界：endpoint、token、Authorization header、cookie、原始响应体、完整失败 URL、magnet 和本地绝对路径不会出现在 API 响应、错误 details、日志、队列 JSON、Request snapshot 或浏览器 storage 中；提交配置只存在于当前 POST body，不写入 URL、localStorage、sessionStorage 或持久化配置。

Stage 21 新增偏好与修正端点（非敏感表面，只提交已定义的非敏感字段）：

- `GET /api/v1/preferences`：读取已保存偏好（`<storage>/preferences/user_preferences.json`）。返回 `preference_hits`（字幕组/筛选/命名）、`preference_warnings` 和规范化偏好值；无偏好文件或文件损坏时返回 `None`/空，不回显外部 endpoint/token/cookie/raw 响应。
- `POST /api/v1/preferences`：保存或清空非敏感偏好。payload 为偏好字段或 `{"reset": true}`；未知/敏感字段在服务端剥离，被拒绝的敏感输入回退到上次有效值；`reset: true` 需要显式调用（对应 UI `window.confirm` 确认），恢复默认后只影响偏好 JSON。
- `GET /api/v1/corrections`：读取非敏感修正记录（`<storage>/corrections/` 有界存储，同 raw_title 最新版本 + 全局 500 条上限），供前端展示搜索词来源。
- `POST /api/v1/corrections`：记录一条用户明确提交的非敏感修正（raw_title、公开 canonical title、season_hint、公开 bangumi 元数据、query_correction）；不接收或持久化任何外部敏感值。

Stage 21 偏好/修正 API 的安全边界：endpoint、token、Authorization header、cookie、magnet、raw HTML、raw RSS XML、原始响应体、完整失败 URL 和本地绝对路径不会出现在偏好 JSON、修正 JSON、API 响应、页面、URL、浏览器 storage、日志或 trace 中；偏好与修正只作为批量草案的可编辑默认值和可审核搜索词来源，AI 不自动选择最终 MiKan 合集，不自动接受卡片。

**外部 Auto Bangumi 幂等性限制（剩余风险）**：MiGuOrca 的批量提交通过「提交前持久化 `SUBMITTING` + 成功后标记 `SUCCEEDED`」避免已到达 Auto Bangumi 的项目被自动重试，并通过 `recover` 端点提供人工核验恢复；但 Auto Bangumi 自身不提供幂等创建订阅语义，以下场景仍可能产生重复订阅，需人工核对：1) 进程在 Auto Bangumi 已成功创建订阅、但 MiGuOrca 尚未把结果写入 Request/ab_results 前中断——磁盘队列停留在 `SUBMITTING`，不会被自动重试；若没有明确结果，用户需在 `recover` 核验弹窗中选择「已创建订阅」或「未创建订阅」；若 Request 中已保存 `success=true`，则可自动恢复为成功，若已保存 `success=false`，则按错误类型恢复为失败或可重试；2) 单项结果持久化失败进入 `RESULT_PERSIST_FAILED`，用户在 `recover` 中核验 Auto Bangumi 侧状态后选择「已创建/未创建」恢复，**不可**直接点重试。除此之外，`SUCCEEDED` 项目在任何路径下都不会再次调用 Auto Bangumi，`RESULT_PERSIST_FAILED` 与无明确结果的 `SUBMITTING` 项目永远不会被自动重试。

### 本地部署基线（US-195）

- **默认 local-only**：`uv run flask --app wsgi:app run` 只监听 `127.0.0.1:5000`。Web UI
  没有内置认证/授权，且页面与 API 只面向本机单用户工作流。
- **未认证时禁止直接暴露公网**：不要在不加任何反向代理认证的情况下把本应用直接暴露到
  公网或不可信网络。如需远程访问，必须在前面放置强制认证的代理（如带 Basic Auth /
  OIDC 的反向代理），并保持 storage 与敏感配置只在服务端。否则任何能访问页面的人都能
  读取/修改本地订阅方案并触发对 Auto Bangumi / qBittorrent 的写操作。
- **服务端 storage 根目录**：Web API 只能使用服务端允许的 storage 根目录
  （默认 `.migu_orca/storage`，可用 `MIGU_ORCA_WEB_STORAGE_ROOT` 覆盖），浏览器只能选择
  根目录下的相对 profile（US-193）；`storage_dir` 未传/空值时回落服务端根本身
  （US-196 回归修复：绝不回退 CLI 默认路径）。CLI `--storage-dir` 是独立信任边界。
- **健康/就绪探针**：`/healthz` 只报告进程存活；`/readiness` 额外确认服务端 storage 根
  目录可创建/可写（503 表示 storage 不可用）。两者都不访问真实外部系统。
- **CI 门禁**：`.github/workflows/ci.yml` 在每次 push/PR 执行
  compileall → ruff 静态检查 → 非浏览器 pytest → OpenAPI 漂移检查 →
  `git diff --check`；真实 Chromium 套件在单独 job 运行，`MIGU_ORCA_CI=1` 下浏览器不可用
  会**失败**而不是静默 skip。CI 不保存凭据、真实 endpoint、trace 或含敏感数据的失败产物。

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

4. 打开新前端默认入口：`GET /` 与 `GET /index` 应重定向到 `/app/workbench`，
   `GET /Settings` 与 `GET /settings` 应重定向到 `/app/settings`；确认新前端
   4 条导航（工作台/订阅方案/提交队列/Settings）与一致顶部导航。
5. 在生成表单中提交空白标题，确认页面在浏览器端提示错误且不会发起生成；再填写标题，确认提交按钮在请求中禁用，完成后通过统一通知展示生成或保存结果。
6. 验证 Settings Storage 偏好：打开 `/app/settings`，修改默认 Storage 目录和默认保存 Request 开关后刷新页面，确认浏览器恢复最近偏好；点击 `清除偏好` 后恢复默认 `.migu_orca/storage` 和默认保存状态。该偏好只应存在于浏览器 `localStorage`，不写入 storage JSON 或 API 响应；缺省保存状态表示默认生成并保存 Request。
7. 验证 Request 列表：刷新列表后使用文本搜索、status 筛选和默认/标题升序/request_id 升序排序，确认匹配计数形如 `显示 2 / 5`，无匹配时显示空状态，清空筛选后列表恢复。
8. 验证 Request 详情：打开列表项后确认浏览器 URL 同步为 `/app/requests?request_id=<id>`；刷新该 URL 后仍展示同一详情。详情应按 Overview、Source、Filter、Seeds、Audit 分组；request_id 可复制；RSS 只显示是否已选择，不显示完整 RSS URL；Filter 分区展示包含规则、排除规则、匹配模式（普通字符或正则）和大小写状态；Seeds 按 有效种子 -> 完整种子（按字幕组分组）-> 排除种子 顺序展示：有效种子默认可见并标注当前选中字幕组，完整种子每组显示字幕组名、种子数量并可展开列表，完整种子与排除种子默认折叠，排除原因使用 `命中排除规则` / `未命中包含规则` 可读语言；缺失 history 或 AB result 时保持非致命提示。
9. 验证通知和恢复：列表加载失败时刷新按钮仍可用；详情加载失败时不清空已加载列表；通知可手动关闭，并会在下一次操作时替换旧消息。
10. 验证 Stage 15 UI 质量门槛：新前端各页标题、运行模式摘要、主操作区、Request 列表和详情区应有清晰阅读顺序；Settings Storage、偏好默认值、qBittorrent 和 Auto Bangumi 分区边界清晰；生成、确认、提交使用主按钮，刷新、修改、返回 Settings 使用次按钮，取消、清空、删除和撤销类操作使用危险/警示样式。
11. 验证响应式和键盘操作：在中屏和移动宽度下新前端各页为单列或低密度布局，不出现横向拥挤导航、过密并排表单或不可读详情表格；Tab 能聚焦主要控件和 Request 列表按钮；焦点样式可见，动态通知/列表/详情区域具备合适的语义标记。
12. 验证 Request 操作：打开 PENDING_CONFIRM 状态的 Request 详情，确认出现确认、取消、修改按钮；点击确认后确认浏览器弹出确认框，确认后状态变为 ACCEPTED；点击取消后展示详情区内可见取消表单，提交前必须确认；点击修改后展示内联表单，空 patch 必须在浏览器端阻止，显式清空 filter_rule 或 expected_folder_name 后状态保持 PENDING_CONFIRM 且 Audit 更新。
13. 验证 ACCEPTED Request 管理与筛选控件：打开 `ACCEPTED` Request 详情，确认同时出现 `修改`、`删除` 和 `去 Settings 提交 Auto Bangumi` 动作；`修改` 提交受限 patch 后详情保持 `ACCEPTED` 且 Filter、Seeds、Audit 刷新；`删除` 必须先确认，取消确认不调用删除 API，确认删除后列表刷新、详情清空且 URL 移除 `request_id`。在修改表单中确认 `包含规则` / `排除规则` 标签与默认未勾选的 `使用正则` / `大小写敏感` 复选框；默认提交发送 `use_regex=false` / `case_sensitive=false`，勾选后发送 `true`；普通字符模式下输入 `[` 或 `[v2]` 不得触发正则错误，勾选 `使用正则` 后非法正则才返回统一校验错误。
14. 验证 Auto Bangumi Settings 入口：打开 `/settings#auto-bangumi`，确认无 request_id 也可选择默认账号密码或 API Token 并执行只读“测试连接”；成功摘要只显示连通性、公开版本、认证方式、adapter 和提交能力。打开 `ACCEPTED` Request 详情，确认出现跳转 `/settings?request_id=<id>#auto-bangumi` 的入口；提交前必须确认。成功后清理服务地址和全部认证字段，失败时只显示脱敏通知且不复制凭据。真实实例验收仅允许登录/状态等只读操作；Ralph 和自动化不调用真实订阅写接口。
15. 验证 qBittorrent Settings 连接测试：新前端工作台（`/app/workbench`）不渲染 qBittorrent 配置且不调用 `/api/v1/qbittorrent/test-connection`；`/app/settings` qBittorrent 分区不使用 `<details>` / `<summary>`，endpoint、username、password、timeout_seconds、verify_tls 和 `测试 qBittorrent 连接` 按钮直接显示，password 使用密码输入框。空 endpoint、空 username、空 password 或非正数 timeout 必须在浏览器端阻止提交；提交前必须出现确认提示，确认后才发送 request-scoped `qbittorrent_config` POST body。
16. 验证 qBittorrent 成功和失败路径：成功时页面只展示 `status`、`reachable`、`version` 等脱敏摘要，并清理 endpoint、username 和 password；失败时保留当前表单状态，只展示统一脱敏通知，不展示完整 endpoint、用户名、密码、cookie、SID、本地绝对路径或原始响应体。
17. 验证脱敏和不落盘：页面、通知、API 响应、本地 storage JSON、浏览器 `localStorage` / `sessionStorage`、URL query、测试截图和 trace 不应包含 token、完整 endpoint URL、qBittorrent username、password、Authorization header、cookie、SID、原始 HTML、原始 RSS XML 或原始响应体。`localStorage` 只允许保存 Storage 偏好键。
18. 通过 API 验证本地列表和详情：

   ```bash
   curl 'http://127.0.0.1:5000/api/v1/requests'
   curl 'http://127.0.0.1:5000/api/v1/requests/<request_id>'
   ```

19. 验证 Stage 22 创建订阅方案工作台：主区标题为「创建订阅方案」，可用键盘或鼠标在「单个搜索 / 批量搜索」之间切换；一次只显示当前输入，结果始终位于独占一行的 `#search-results-panel`。切换后另一模式旧结果不应冒充当前结果。单个及批量 FOUND 候选均展示公开标题、MiKan ID、匹配提示和封面或明确占位；即使仅有一个候选，也必须点击「选择此合集」后才生成订阅草案。批量按原始输入分组，绝不默认选择第一个候选。EMPTY 显示「未找到匹配的 MiKan 合集」，FAILED 显示可重试的脱敏错误，两者及仅 PARSED 条目均不可展开、修改、保存或接受；选择真实候选并完成详情解析后才进入可编辑的 DRAFT/READY 草案。搜索开始、完成、无结果和失败反馈使用 aria-live 状态区；搜索中相关输入、模式切换和提交操作禁用，结束后恢复。页面底部「开发 / 离线测试」中的 `Fixture 生成` 默认收起，普通路径不会触发 fixture 生成。
20. 验证 Stage 19/20 批量草案、接受和提交前队列：在批量搜索中输入多行简称，确认空输入不会调用 `/api/v1/batches/parse`。选择真实候选生成草案后，卡片展示封面或占位、番剧标题、源名称、有效种子数和中文状态；删除只移除当前卡片，窄屏为单列，长列表可滚动。仅 DRAFT/READY 卡片可展开、修改或接受；批量接受、全接受和队列提交语义保持不变。确认页面、API 响应、URL、browser storage、Request/队列 JSON、日志、截图和 trace 不包含 endpoint、token、Authorization header、cookie、raw HTML、raw RSS XML、magnet、完整失败 URL、原始响应体或本地绝对路径。
21. 验证 Stage 20/24 批量接受与提交前队列：在批量工作台生成卡片后，勾选若干卡片点击「批量接受」或直接点击「全接受」，确认工具栏显示选中数量，成功卡片显示「已接受 / 待提交」chip 且其他卡片状态不变，不可接受卡片显示中文原因；刷新页面后通过 URL `batch_id` 恢复队列。打开「提交前队列」面板确认展示项目标题、中文状态（待提交/提交中/提交成功/提交失败/可重试）、尝试次数和脱敏结果摘要；提交前填写服务地址、默认账号密码（或显式切换 API Token）和 fallback 并显式确认，提交中按钮禁用，提交成功后服务地址和认证字段被清空；单项失败不阻塞其他项目，失败项显示「重试」按钮，成功项不显示重试按钮；点击「重试」后失败项按最新已接受的 Request 重新提交并刷新状态。刷新页面后队列状态从持久化队列恢复。确认页面、URL、browser storage、队列 JSON、Request JSON、截图和 trace 不包含服务地址、username、password、token、Authorization header、cookie、raw HTML、raw RSS XML、原始响应体、完整失败 URL、magnet 或本地绝对路径，且 MiGuOrca 不创建任何 qBittorrent 下载任务。
22. 验证 Stage 21 偏好管理与搜索增强：打开 `/settings`，确认 `#preference-settings-panel` 展示偏好字幕组/排除字幕组、fallback、筛选规则、使用正则/大小写敏感、命名策略与模板、搜索增强开关；修改后保存，确认展示中文成功反馈并刷新规范化值；再次加载页面确认偏好被恢复。尝试提交被拒绝的敏感输入（如外部 endpoint/token），确认回退到上次有效值且不回显。清空/恢复默认偏好必须触发 `window.confirm` 确认，确认后 `user_preferences.json` 恢复默认，但队列、Request 和 AB result 存储不受影响。回到 `/index` 批量输入 `萌王S4` 等简称并解析，确认批量卡片展示偏好命中摘要行（偏好命中/偏好不可用回退/未配置默认流程）、需人工核对 chip（低置信度/多候选/冲突）和展开后的偏好与审核面板（偏好命中、警告、审核提示、当前默认配置）与搜索词来源面板（修正增强搜索词及来源、原始搜索词）。无偏好、偏好读取失败或增强失败时卡片明确展示默认流程状态，不阻塞手动候选选择和直连 fallback。确认页面、URL、browser storage、偏好 JSON、修正 JSON、截图和 trace 不包含 endpoint、token、Authorization header、cookie、raw HTML、raw RSS XML、原始响应体、完整失败 URL、magnet 或本地绝对路径。
23. 验证 Stage 23 媒体与审核体验：搜索候选确认封面只使用 `/api/v1/mikan/posters/<opaque-key>` 同源地址，图片初始为占位并以 `loading="lazy"`、`decoding="async"` 独立加载；缓存未命中后再次访问应命中，超过 7 天 TTL 的缓存安全清理。确认慢图或失败图不阻塞候选选择，原始图片 URL、缓存路径和响应体不会出现在页面、URL、browser storage、storage JSON、日志、截图或 trace。用脱敏大响应 fixture 验证搜索读取在候选区完整后提前停止且候选与完整读取一致。批量 FOUND 的“查看候选”应在按钮旁打开单一浮层，支持切换、点击外部/Escape 关闭且窄屏无横向溢出；DRAFT/READY 的“查看草案”应跳转到统一订阅方案详情而不拉伸卡片。卡片显示 `播出进度：待开发 / N 集` 或 `未知`；禁用控件是静态且不可触发，真实请求状态仍在状态区反馈。

Stage 16 不实现 Web UI 搜索候选展示、AI 番剧名解析、认证系统、复杂配置管理、前端构建链、批量季度订阅或 qBittorrent 下载/订阅动作。本阶段已完成真实 MiKan 合集详情页离线 fixture、结构化详情解析、字幕组级 RSS 优先输出、番剧级 RSS fallback、CLI/API direct URL/ID 入口和真实读取错误脱敏；Stage 17 已在该基础上完成 Web UI direct-entry fallback 与搜索候选选择。Stage 18 已把真实 MiKan 候选搜索收敛为 `/index` 普通 Web 主流程。Stage 19 已完成批量输入、AI 名称解析 seam、批量候选搜索、卡片网格、单卡修改和单卡接受；Stage 20 已完成批量接受、全接受、提交前队列、Auto Bangumi 顺序提交和失败项独立重试；Stage 21 已完成非敏感偏好保存与应用、审核元数据展示、用户修正驱动的搜索词增强和偏好管理 Web UI。Stage 22 已完成单个/批量分段搜索、独立结果面板、FOUND/EMPTY/FAILED 真实候选状态、统一候选卡、显式候选选择到草案生成和真实搜索状态反馈；Stage 23 已完成同源安全封面缓存、候选读取提前停止、锚定候选浮层、统一草案详情、播出进度占位和禁用控件静态反馈。`PARSED` 或无候选条目不会被解释为已找到真实番剧或可接受草案。

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

> 当前 `ralph.sh` 只支持 `amp`、`claude`、`codex` 三种执行工具，不包含 DSH 或 provider 配置。项目保留的轻量定制是可通过 `--model`、`--claude-model` 或 `RALPH_MODEL` 指定模型；模型参数会传给 Claude 和 Codex，Amp 分支不使用该参数。

- 当前 Ralph 状态快照：Stage 33 已完成并归档；US-257～US-265 全部通过
- 最近完成阶段：Stage 33，前端应用壳层与设计系统（F-A）
- 最近完成阶段：Stage 31，Auto Bangumi 可靠写管理
- 前一完成阶段：Stage 30，Auto Bangumi 只读能力与外部同步基础
- 前一完成阶段：Stage 29，统一追番记录与可靠提交恢复
- 前一完成阶段：Stage 28，草案一致性与原子保存确认
- 前一完成阶段：Stage 27，前端工程化迁移与页面重构
- 前一完成阶段：Stage 26，Web API 契约固化与服务端边界治理
- 前一完成阶段：Stage 25，正式番名与季数解析
- 前一完成阶段：Stage 24，AutoBangumi 真实认证与订阅兼容闭环
- 前一完成阶段：Stage 23，媒体缓存、MiKan 读取优化与批量审核体验
- 前一完成阶段：Stage 22，Web UI 搜索工作台重构与真实候选闭环
- 前一完成阶段：Stage 21，用户偏好与智能推荐闭环 PRD
- 前一完成阶段：Stage 20，批量接受与 Auto Bangumi 提交前队列 PRD
- 前一完成阶段：Stage 19，批量新番订阅草案工作台 PRD
- 前一完成阶段：Stage 18，真实 MiKan 主流程与预览优化 PRD
- 前一完成阶段：Stage 16，真实 MiKan 合集详情页解析与直连 URL/ID 入口 PRD
- 前一完成阶段：Stage 15，Web UI ACCEPTED 管理与筛选语义优化 PRD
- 前一完成阶段：Stage 14，Web UI Request 可操作性修复 PRD
- 前一完成阶段：Stage 13，Web UI Settings 信息架构优化 PRD
- 前一完成阶段：Stage 12，qBittorrent 直连显式连接测试 PRD
- 前一完成阶段：Stage 11，Web UI 显式真实 MiKan / Auto Bangumi 配置入口 PRD
- 前一完成阶段：Stage 10，Web UI Request 确认、取消和修改操作入口 PRD
- 前一完成阶段：Stage 9，浏览器自动化测试 PRD
- 前一完成阶段：Stage 7，Flask Web UI / 管理界面 MVP PRD
- Stage 26 执行：`docs/MiGuOrca_stage26_web_api_contract_hardening_PRD.md`；执行分支 `agent/stage26-web-api-contract-hardening`，Ralph stories 为 US-189～US-196（已全部完成）
- Stage 27 执行：`docs/MiGuOrca_stage27_frontend_engineering_migration_PRD.md`；执行分支 `agent/stage27-frontend-engineering-migration`，Ralph stories 为 US-197～US-209（已全部完成并归档）
- Stage 28 执行：`docs/MiGuOrca_stage28_draft_consistency_PRD.md`；执行分支 `ralph/stage28-draft-consistency`，Ralph stories 为 US-210～US-218（已全部完成并归档）
- Stage 29 执行：`docs/MiGuOrca_stage29_unified_tracking_PRD.md`；执行分支 `ralph/stage29-unified-tracking`，Ralph stories 为 US-219～US-227（已全部完成并归档；B-C handoff 见 future_stages「Stage 29 handoff」）
- Stage 30 执行：`docs/MiGuOrca_stage30_ab_read_sync_PRD.md`；执行分支 `ralph/stage30-ab-read-sync`，Ralph stories 为 US-228～US-236（已全部完成并归档）
- Stage 31 执行：`docs/MiGuOrca_stage31_ab_write_management_PRD.md`；执行分支 `ralph/stage31-ab-write-management`，Ralph stories 为 US-237～US-246（已全部完成并归档）
- Stage 32 执行：`docs/MiGuOrca_stage32_contract_hardening_PRD.md`；执行分支 `ralph/stage32-contract-hardening`，Ralph stories 为 US-247～US-256（已全部完成并归档）
- Stage 33 执行：`docs/MiGuOrca_stage33_frontend_shell_PRD.md`；执行分支 `ralph/stage33-frontend-shell`，Ralph stories 为 US-257～US-265（已全部完成并归档）
- 后续待办：`docs/backlog.md`；不为未开发事项预留 Stage 编号
- 已归档阶段记录：`scripts/ralph/archive/`
- Ralph 循环命令（Claude，可指定模型）：`./scripts/ralph/ralph.sh --tool claude --model claude-model-id 7`
- Ralph 循环命令（Codex，可指定模型）：`./scripts/ralph/ralph.sh --tool codex --model codex-model-id 7`
- Ralph 循环命令（Amp）：`./scripts/ralph/ralph.sh --tool amp 7`

### Ralph 阶段开发规范

Stage 开发必须通过 Ralph 循环完成，不应绕过 `scripts/ralph/prd.json` 手工挑 story 开发。每次启动一个 Stage 前，应先确认 `scripts/ralph/prd.json` 是当前 Stage 的 PRD，`scripts/ralph/progress.txt` 已记录本 Stage 的约束和进度。

Stage 开发期间，Ralph 每轮只选择并完成一个最高优先级、`passes: false` 的 user story；完成实现和该 story 所需的质量检查后，更新对应 `passes` 状态与 `scripts/ralph/progress.txt`。脚本通过多轮迭代依次推进，直到全部 story 完成并输出 `<promise>COMPLETE</promise>`。涉及 Web UI 的 story 必须运行真实浏览器测试或记录无法运行的明确原因。

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
./scripts/ralph/ralph.sh --tool claude --model claude-model-id 7
```

也可以通过环境变量指定：

```bash
RALPH_MODEL=claude-model-id ./scripts/ralph/ralph.sh --tool claude 7
```

`--claude-model` 是 `--model` 的等价写法：

```bash
./scripts/ralph/ralph.sh --tool claude --claude-model claude-model-id 7
```

`claude-model-id` 是占位符，应替换为当前 Claude CLI 可识别的模型名或本地别名。`--model` 同样可传给 Codex；Amp 分支忽略模型参数。

Stage 7 已在 Stage 6 本地 JSON Request 持久化基础上，增加 Flask app factory、Blueprint registry、统一 JSON API 响应层、Pydantic 校验、Request 查询/生成 API、服务端渲染 Web UI、状态历史展示和 AB 提交结果展示，同时保持默认 CLI 流程不隐式写入磁盘。

Stage 8 已围绕 Web UI 可用性补强：顶部导航与运行模式提示、生成表单说明和本地校验、Storage 偏好记忆、Request 列表搜索/筛选/排序、详情区块重组、统一通知与错误恢复、响应式布局和基础无障碍验收。Stage 8 仍不包含真实 MiKan 搜索/RSS 兼容性优化、认证系统、复杂配置管理、前端构建链、批量季度订阅或 qBittorrent 直连。

Stage 9 引入 Playwright 浏览器自动化测试基础设施，覆盖了 `/` 到 `/index` 路由验证、页面基础加载、Request 生成表单校验和显式保存流程、列表搜索/筛选/排序、详情分组和通知恢复、响应式布局和键盘可访问性等关键路径。Stage 10 将 Web UI 扩展到确认、取消和修改流程。Stage 11 将 Web UI 扩展到显式真实 MiKan 配置入口和显式 Auto Bangumi 提交入口。Stage 12 将 Web UI 扩展到 qBittorrent 显式连接测试入口，并通过 Playwright route fake 验证连接测试，不访问真实 qBittorrent。Stage 13 将配置和连接测试迁移到 `/settings`，将 `/index` 收敛为 Request 工作台，补齐 URL 可恢复详情、可见取消/修改表单、按钮语义、状态反馈、Settings 分区和响应式 UI 回归。Stage 14 补齐默认生成保存、只读预览、默认生成后的确认/取消/修改、Seeds 完整/有效/排除列表、qBittorrent Settings 直显和敏感信息不落盘回归。Stage 15 补齐 `ACCEPTED` Request 的删除与受限修改、筛选字面默认语义、`使用正则` / `大小写敏感` 选项、Filter 与 Seeds 排除说明和 Stage 15 安全回归。Stage 16 补齐真实 MiKan 合集详情页解析、字幕组级 RSS 优先、番剧级 RSS fallback、CLI/API direct URL/ID 入口和真实读取错误脱敏。Stage 17 补齐真实 MiKan 搜索候选合集展示、request-scoped 候选搜索 API、Web UI 手动选择与直连 fallback、进程内候选缓存和 display-only 推荐标签，并把全部真实 MiKan 能力接入 `/index` Request 生成流程。Stage 18 补齐真实 MiKan 主流程收敛：系统默认 MiKan 配置、主生成区候选搜索、直连兜底勾选框、可编辑预览订阅草案（dry-run 修改 + 保存）、中文用户态文案与状态、Seeds 有效/完整/排除顺序与字幕组分组，以及 fixture 模式降级为开发/离线测试路径。Stage 19 补齐批量输入、AI 名称解析 seam、批量候选搜索、订阅草案卡片、单卡修改回流和单卡接受。Stage 20 补齐批量接受、全接受、提交前队列、Auto Bangumi 顺序提交和失败项独立重试，并建立端到端安全回归（endpoint、token、Authorization header、cookie、raw HTML、raw RSS XML、原始响应体、完整失败 URL、magnet 和本地绝对路径不出现在 API 响应、页面、URL、浏览器 storage、队列 JSON、Request JSON、日志或 trace 中）。Stage 21 补齐偏好管理面板（`/settings` `#preference-settings-panel`）、偏好保存/恢复默认的显式确认、批量卡片偏好命中与审核提示、搜索词来源展示，以及偏好/修正端到端安全回归（上述敏感值不出现在偏好 JSON、修正 JSON、API 响应、页面、URL、浏览器 storage、日志或 trace 中）。测试默认使用本地 fixture、临时 storage 和 fake endpoint seam，不访问真实 MiKan、Auto Bangumi 或 qBittorrent。

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

## 前端工程（Stage 27）

`frontend/` 是独立的前端工程（Vue 3 + TypeScript strict + Vite），US-197 建立了工程与 CI 基线。

```bash
cd frontend
npm ci                    # 安装依赖（lockfile 已入库，CI 使用 npm ci）
npm run typecheck         # vue-tsc --noEmit（strict）
npm run lint              # ESLint flat config（--max-warnings 0）
npm run test:unit -- --run  # Vitest + Vue Test Utils（jsdom）
npm run build             # 先 typecheck，再 vite build 输出到 dist/
npm run dev               # Vite dev server（代理 /api/v1 到 http://127.0.0.1:5000）
```

约定：

- `frontend/dist/`（生产构建）与 `node_modules/` 不入库；CI 通过 `npm ci` 重建。
- Vite `base` 固定为 `/app/`，生产构建由 Flask 同源托管在 `/app/`，不依赖 Node 运行时。
- SPA fallback 只接管 `/app/*` 路径，绝不截获 `/api/v1/*`、海报、`/healthz`、`/readiness`
  或旧 Flask 页面（`src/apps/migu_orca_web/routes_app.py` 的 `app_blueprint` 保证）。
- 路由 base 是 `/app/`：Vue Router 的 `to` 使用相对路径（如 `/workbench`），完整 URL 是
  `/app/workbench`。
- 新前端只通过 Stage 26 OpenAPI（`docs/api/openapi.json`）生成 TypeScript 类型/client
  （US-198），不导入 Python 模型、不手写第二套响应 interface。
- 安全边界与旧前端一致：endpoint、token、cookie、password、原始响应等敏感值只存在于
  组件局部内存与单次 POST body，不进入 store 持久化、URL、browser storage、日志或 trace。
- US-207 运行质量：`npm run build` 会把 `node_modules` 打进 `vendor-*.js`（保持路由
  懒加载），`sourcemap: false` 且 `dist` 永不提交 `.map`；Flask 对 `/app/assets/*`
  返回 `public, max-age=31536000, immutable`，对 SPA shell 与其它 `/app/*` 返回
  `no-cache`（部署换哈希后不会 pin 旧资源）。
- US-201 已迁移 Settings 到 `/app/settings`：Storage 偏好（localStorage 只存服务端相对
  profile）、偏好默认值（`/api/v1/preferences`，保存失败回退到上次成功值并清空被拒绝的
  敏感输入）、qBittorrent 与 Auto Bangumi 连接测试和 AB 提交上下文（`request_id` 来自
  URL query）；连接测试/提交失败只显示固定中文反馈，绝不渲染服务端原始错误（可能含凭据）。

## 参考文档

- [文档索引](docs/README.md)
- [主 PRD](docs/MiGuOrca_main_PRD.md)
- [Stage 1 实现规格](docs/design/stage1-spec.md)
- [架构与目录约定](docs/design/architecture.md)
