# MiGuOrca 主 PRD

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 项目名称 | MiGuOrca |
| 文档名称 | MiGuOrca 主 PRD |
| 文档类型 | 主 PRD |
| 当前版本 | v0.38 |
| 文档状态 | Stage 26～Stage 39 均已完成；前端体验重构 F-A～F-G 已收尾 |
| 适用阶段 | 需求讨论、模块拆分、开发规划 |
| 相关系统 | MiKanProject、Auto Bangumi、qBittorrent |
| 简称约定 | Auto Bangumi 简称为 AB |

2026-09-13 用户确认新的本地部署目标，执行范围见[Stage 39 PRD](MiGuOrca_stage39_deployment_settings_PRD.md)：
仅 AB 凭据允许存入部署端专用私有配置，跨页/刷新/重启保留；qB 独立连接测试与无用旧 Web 编排退役，
MiKan 搜索由服务端封装，用户无需配置搜索服务；顶部连接入口进入设置，不使用全局凭据弹窗。
Stage 39 已完成独立 Gate 5 审核并合并至 `main`（PR #64、merge `f29e217`）；本文下方早期阶段/临时配置记录均为历史，
不是保留旧实现的要求。下一步等待用户审核已交付的前端功能并提出问题，再决定新的产品范围；实际状态见[文档索引](README.md)。

### 1.1 命名约定

| 类型 | 名称 |
| --- | --- |
| 正式项目名 | MiGuOrca |
| 仓库名 | migu_orca |
| Python 包名 | migu_orca |
| CLI 命令 | migu-orca |
| 配置目录 | ~/.config/migu_orca |
| 环境变量前缀 | MIGU_ORCA_ |
| 日志名 | migu_orca |

MiGu 来源于 Mikan + Bangumi。ORCA 表示 Orchestrated RSS Coordination for Anime，即面向动画 RSS 的自动编排与协调系统。

### 1.2 开发约定

本项目使用 `UV` 进行 Python 包管理和命令执行。

1. 安装依赖使用 `uv sync`。
2. 运行测试使用 `uv run pytest`。
3. 运行项目入口或脚本时优先使用 `uv run <command>`。
4. 不要直接使用 `python` 运行测试或脚本，避免绕过项目统一环境。

## 2. 项目背景

用户目前主要通过 MiKanProject 获取番剧 RSS，并使用 Auto Bangumi 配合 qBittorrent 实现自动下载。

现有流程通常是：

1. 用户确定想看的季度新番。
2. 用户手动在 MiKanProject 搜索番剧。
3. 用户在多个字幕组 RSS 中选择一个符合偏好的源。
4. 用户将 RSS 配置到 Auto Bangumi。
5. 用户手动填写订阅名称、目录名称、季度编号、筛选规则等信息。
6. Auto Bangumi 根据 RSS 与规则将种子添加到下载任务。

这个流程可用，但每季度会重复大量人工操作。用户往往先从 Bilibili UP 主季度新番推荐视频、社区清单或聊天中得到一批想看的番剧，而且输入通常是 `萌王S4`、`路哥S4`、`杖剑谭S2`、`邻家天使S2` 这类简称。用户原本需要先查官方译名或日文名，再逐个在 MiKan 搜索、选择合集、确认字幕组、调试筛选规则并配置 Auto Bangumi。

MiGuOrca 的目标是在 MiKanProject 与 Auto Bangumi 之间提供一层批量订阅前置编排能力，降低批量名称解析、搜索、判断字幕组、筛选种子和命名目录的成本。

## 3. 项目目标

MiGuOrca 是一个面向季度新番的 Auto Bangumi 前置订阅编排工作台。

项目长期目标是：

1. 用户批量输入想看的番剧简称、口语名或不完整标题。
2. 系统使用 AI 名称解析与搜索词增强，将模糊输入转换为可搜索、可审核的官方标题候选。
3. 系统逐项搜索并分析 MiKan RSS，生成可审核的订阅草案卡片。
4. 用户逐项审核、删除、展开查看、修改字幕组/筛选规则/文件夹名和有效种子。
5. 用户单个接受、批量接受或全接受后，系统显式提交 Auto Bangumi 或生成降级配置。

MiGuOrca 不做 Auto Bangumi 或 qBittorrent 的替代品，不建立绕过 Auto Bangumi 的长期订阅执行系统，也不直接创建 qBittorrent 下载任务。下载执行和长期订阅执行由 Auto Bangumi / qBittorrent 负责；MiGuOrca 聚焦订阅前判断、批量编排和用户可审核配置生成。

当前已完成到 Stage 29：离线 Request 生成、确认/取消/受限修改和安全删除、真实 MiKan 数据源与候选选择、本地 JSON 持久化、Flask Web UI、浏览器自动化测试、qBittorrent 显式连接测试、批量草案与 AutoBangumi 提交前队列、用户偏好与修正闭环、媒体缓存、AutoBangumi 3.1.18 认证兼容、正式番名与结构化季数解析、Web API 契约固化、Vue/TypeScript 前端工程化、草案一致性与统一追番记录/可靠提交恢复。CLI 可通过 `--source mikan --mikan-config <path> --mikan-bangumi <url-or-id>` 直接解析已选中 MiKan `Home/Bangumi/<id>` 合集并绕过搜索；Web API `POST /api/v1/requests` 支持 request-scoped `mikan_bangumi` 字段。真实合集始终由用户显式选择，只有公开候选证据或用户明确确认的季数才能进入 Request、命名和 AutoBangumi 映射。

Stage 18 已完成真实 MiKan 主流程收敛：普通 Web 用户在 `/index` 只输入番剧标题，系统使用默认 MiKan 配置（endpoint 等价于 `https://mikanani.me/Home/Search`，timeout 15 秒）搜索候选合集并展示卡片；选择合集或使用直连 URL/ID fallback 后，默认先生成可编辑订阅草案预览，用户可修改字幕组、筛选规则和文件夹名，再保存为正式订阅方案。fixture 生成能力继续保留给 CLI、API seam、离线开发和回归测试，但不再作为普通 Web 主流程：Web UI 中的 fixture 入口放在 `/index` 底部「开发 / 离线测试」面板中并默认收起，普通用户路径不会触发 fixture 生成。Stage 18 已从普通 UI 移除 `search_endpoint`、`timeout_seconds`、`query` 等技术字段，改用中文业务文案（订阅方案/订阅草案/待确认/已确认/已取消），并将 Seeds 区调整为有效种子优先、完整种子按字幕组分组、排除种子最后。

Stage 19 已完成批量新番订阅草案工作台：`POST /api/v1/batches/parse` 接收多行输入，每个非空行作为独立 batch item；AI 名称解析 provider seam 和 fake provider 输出候选标题、季数提示、搜索词、置信度和人工审核标记；批量 API 对每个 item 独立复用 MiKan candidate search，单项失败不阻塞其他 item。`/index` 批量工作区以卡片网格展示草案，支持删除、展开查看过滤器与有效/排除种子摘要、进入现有预览详情修改流程并只回流当前卡片，以及单卡接受。

Stage 20 已完成批量接受与 Auto Bangumi 提交前队列：批量工作台提供单卡接受、选中批量接受和全接受入口，明确显示选中数量和不可接受原因；已接受项目进入独立追踪的提交前队列（`BatchQueueItem`/`BatchSubmissionQueue`），每个 item 独立记录状态（`READY_TO_SUBMIT`/`SUBMITTING`/`SUCCEEDED`/`FAILED`/`RETRYABLE`）、尝试次数、脱敏错误和脱敏结果摘要；队列只保存非敏感元数据，endpoint、token、cookie、Authorization header、原始响应体、完整 RSS URL、magnet 和本地绝对路径从不写入队列 JSON、Request snapshot、API 响应、浏览器 storage、URL、日志、截图或 trace。Web API 新增 `POST /api/v1/batches/<batch_id>/accept`、`GET /api/v1/batches/<batch_id>/queue`、`POST /api/v1/batches/<batch_id>/submit` 和 `POST /api/v1/batches/<batch_id>/retry`。批量提交要求 request-scoped `ab_config` 和显式确认，复用现有 payload builder、Auto Bangumi client 和脱敏结果契约，按队列顺序逐项处理，单项失败不阻塞其他项，失败项可独立重试，成功项不会被重复提交；批量提交采用前台顺序编排，不创建 qBittorrent 下载任务，不绕过 Auto Bangumi，不引入后台常驻 worker。

Stage 21 已完成用户偏好与智能推荐闭环：用户可在 `/settings` 显式保存非敏感偏好（字幕组/筛选/命名/搜索修正开关），批量草案生成时对每个 item 应用偏好生成默认配置，并返回偏好命中、偏好警告、低置信度/多候选/冲突审核提示和搜索词来源等可审核元数据；用户明确提交的非敏感修正（raw_title、公开 canonical title、season_hint、公开 bangumi 元数据和 query_correction）会形成有界安全的搜索词增强记录，后续批量输入复用增强搜索词，失败时回退原搜索词。偏好与修正存储只保存非敏感字段，endpoint、token、cookie、Authorization header、magnet、raw HTML、raw RSS XML、原始响应体和本地绝对路径从偏好 JSON、API 响应、页面、URL、浏览器 storage、日志和 trace 中被拒绝或剥离。Web API 新增 `GET/POST /api/v1/preferences` 和 `GET/POST /api/v1/corrections`。Stage 21 保持 Stage 19/20 的人工审核与提交语义：AI 只生成候选标题和搜索词，偏好只生成可编辑默认值，用户仍需逐卡审核并显式接受；无偏好或增强失败时回退 Stage 19 默认流程（fake provider、手动候选选择、直连 URL/ID fallback 仍然可用）。

Stage 22 已完成。单个与批量搜索继续复用 `_search_mikan_candidates`、公开候选序列化、候选缓存以及既有 MiKan 详情到 preview 链路，建立“标题解析 → 真实候选 FOUND/EMPTY/FAILED → 用户显式选择 → DRAFT/READY 草案”的可信状态契约：无候选不再生成空壳 `preview_request`，PARSED/EMPTY/FAILED 均不能操作草案。`/index` 已重构为可切换单个/批量模式的“创建订阅方案”工作台，两种结果统一位于独立面板，并由真实浏览器回归保护。执行记录见 `docs/MiGuOrca_stage22_web_search_workbench_PRD.md`。

Stage 23 已完成。MiKan 封面现经服务端安全同源缓存异步加载，搜索 transport 以结构感知提前停止，批量候选/草案布局、剧集摘要和禁用按钮反馈均已收敛。

Stage 24 已完成。AutoBangumi 3.1.18 默认使用账号密码登录、单次 token Cookie、`/api/v1/status` 与 `/api/v1/rss/subscribe` 的 `{data, rss}` 契约，写入成功以**精确 HTTP 200 且响应体为 `{msg_en, msg_zh}` 写信封**判断（Auto Bangumi 3.1.18 的写响应不含 `status` 字段，判据见 #216），订阅 ID 由精确回查确定（可为空）；Settings 提供 request-scoped 只读连接测试，单个/批量队列复用同一 adapter/payload/result seam。API Token/Bearer 模式维持兼容但无已证明写契约时 fail closed。执行 PRD 见 `docs/MiGuOrca_stage24_autobangumi_compatibility_PRD.md`。其他未开发事项只按 backlog 优先级排序，不预绑定 Stage 编号。

Stage 25 已完成。单个与批量 MiKan 搜索共享确定性正式番名/季数解析、结构化 season、有界 query plan 和可审核来源展示；parser 只生成搜索提示，真实合集仍由用户显式选择，只有选中候选公开证据或用户确认能证明的季数才能进入 Request、M07 与 M10。执行 PRD 见 `docs/MiGuOrca_stage25_title_season_parsing_PRD.md`。

Stage 26 已完成。Web API 契约固化与服务端边界治理：冻结全部 `/api/v1` 端点清单与 golden contract（`docs/api/endpoint_inventory.md` + `tests/api_contract/`），建立公开响应 DTO（`extra="forbid"`）与确定性 OpenAPI（`docs/api/openapi.json`），把 `views.py` 按职责拆分为 schemas/serializers/services/contexts/routes_*，为失败建立稳定 HTTP 状态（400/404/409/401/502/503/504/500，envelope 保持兼容），把 Web storage 限制为服务端根目录下的相对 profile（空值回落服务端根，CLI 显式路径不变），用服务端权威 DraftStore（TTL/容量/一次性保存/重放保护）替代客户端完整 Request 持久化，并建立 CI、ruff 静态检查、OpenAPI 漂移与真实 Chromium 门禁及 local-only 部署基线。执行 PRD 见 `docs/MiGuOrca_stage26_web_api_contract_hardening_PRD.md`；Stage 27 前端迁移 handoff 见 `docs/MiGuOrca_stage27_frontend_engineering_migration_PRD.md`。

Stage 28 已完成。草案一致性与原子保存确认（BL-025 的 B-A，执行 PRD 见 `docs/MiGuOrca_stage28_draft_consistency_PRD.md`）：为每个服务端权威草案建立单调 revision（签发为 1，成功 CAS 修改 +1），`preview-modify` 必填 `base_revision` 做 compare-and-swap（过期 base → 409 `draft_revision_conflict`，只报 field/current_revision），`preview-save` 改为「预留 → 持久化 → 提交/释放」（写盘失败保留原 revision 可重试，正在保存 → 409 `draft_reserved`）；storage engine 新增持久化 save-confirm 幂等记录（`<storage>/idempotency/`，只含非敏感白名单字段，终态同键重放），新增单番 `POST /api/v1/requests/save-confirm`（一次完成校验/预留/持久化/确认/幂等提交并返回 `CONFIRMED` + `ACCEPTED` handoff）与批量 `POST /api/v1/batches/{batch_id}/save-confirm`（逐条复用单番用例、部分成功、成功项不因失败项回滚），批量 parse 按规范化非空行强制 1～36 部服务端边界（超限在任何标题解析/MiKan 调用前返回 400 `batch_limit_exceeded`），并新增 `GET /api/v1/requests/{request_id}/safe-info` 严格白名单 DTO 作为“全部信息”唯一安全数据源。Stage 28 只返回 ACCEPTED Request handoff，不创建或伪造 tracking record；B-B 阶段可从持久化 ACCEPTED Request 与 handoff 幂等建立 tracking record。

Stage 29 已完成 B-B「统一追番记录与可靠提交恢复」（执行 PRD 见 `docs/MiGuOrca_stage29_unified_tracking_PRD.md`）：建立严格白名单的 `TrackingRecord`/`TrackingOperation` 与确定性 opaque ID，历史 Request、旧 batch queue 和 AB result 通过纯本地幂等迁移统一收敛；accept/save-confirm handoff、tracking 列表/详情、revalidate、submit、retry、recover 共享统一服务，提交过程具备持久化幂等、结果待确认恢复和旧队列兼容投影。Stage 30 已完成 B-C1 的 Auto Bangumi 只读能力、外部同步和映射对账；Stage 31 已完成 B-C2 可靠写管理；B-D 已作为 Stage 32 完成契约固化、兼容迁移与前端交接。

## 4. 第一阶段范围

第一阶段目标是：**输入单个番剧名后，基于静态 MiKan/RSS 数据生成一条结构完整、状态为待确认的 Request。**

### 4.1 第一阶段必须支持

1. 接收单个番剧名称。
2. 从静态 MiKan 模拟数据中获取候选番剧。
3. 自动选择最相似的番剧匹配结果。
4. 从静态数据中获取候选字幕组 RSS。
5. 解析静态 RSS 内容或等价 fixture。
6. 根据当前用户筛选规则计算有效种子。
7. 推荐一个字幕组。
8. 生成预期文件夹名。
9. 生成结构完整、状态为 `PENDING_CONFIRM` 的 Request。
10. 将 Request 以 JSON 或终端可读形式输出。
11. 失败时返回明确错误信息。

### 4.2 第一阶段明确不做

1. 不访问真实 MiKanProject 页面。
2. 不实现真实 MiKan 爬虫。
3. 不提供候选番剧手动选择。
4. 不提供完整 Request 接受、修改、取消交互。
5. 不调用 Auto Bangumi。
6. 不生成 AB 降级配置。
7. 不直接调用 qBittorrent。
8. 不持久化 Request、状态历史或 AB 调用结果。
9. 不做 Web UI。
10. 不做批量季度清单输入。
11. 不做本地媒体库管理。
12. 不做复杂历史学习。

## 5. 第一阶段验收标准

第一阶段以“能否离线稳定生成 Request”为验收核心。

1. 输入一个番剧名称后，系统可以生成一条 Request。
2. Request 中包含匹配到的番剧信息。
3. Request 中包含候选字幕组列表。
4. Request 中包含每个字幕组 RSS 下的种子总数。
5. Request 中包含当前筛选规则下的有效种子数。
6. Request 中包含当前选择字幕组。
7. Request 中包含当前筛选规则。
8. Request 中包含当前有效种子名列表。
9. Request 中包含预期文件夹名。
10. Request 状态为 `PENDING_CONFIRM` 或等价待确认状态。
11. Request 中 `ab_submit_result` 为 `null`。
12. 系统不依赖 Auto Bangumi 或 qBittorrent 在线可用。
13. 系统不依赖真实 MiKanProject 在线可用。
14. 关键失败场景可以返回明确错误原因。
15. 项目测试通过 `uv run pytest`。

## 6. 核心概念

| 概念 | 含义 | 详细定义 |
| --- | --- | --- |
| Request | 系统根据用户输入、规则和数据源生成的番剧订阅确认对象 | M01 |
| source_info | 系统搜索、解析、分析后得到的客观源信息 | M01、M03、M04、M06 |
| confirmable_config | 用户后续可以确认或修改的配置集合 | M01 |
| 有效种子 | 按筛选规则去除重复、无效和不符合规则的种子后保留的种子 | M06 |
| 字幕组推荐 | 从候选 RSS 中选出默认字幕组 | M05 |
| 预期文件夹名 | 第一阶段根据匹配番剧全名生成的目录名 | M07 |

主 PRD 只定义概念边界，不维护完整字段结构。字段、状态、错误和接口定义由对应模块 PRD 维护。

第一阶段输出的 Request 是一次计算得到的“待确认快照”，只承诺成功结果状态为
`PENDING_CONFIRM`。它不是完整的 Request 生命周期或持久化状态机。确认、修改、
取消、过期、提交及失败历史等状态，在后续实现 M09、M10、M11 时再定义。

## 7. 模块划分

| 模块编号 | 模块名称 | 当前状态 | 优先级 | 模块 PRD |
| --- | --- | --- | --- | --- |
| M00 | 入口与流程编排模块 | Stage 18～25 已实现真实候选、批量草案/队列、偏好/搜索增强、候选选择、结构化季数与统一草案详情链路 | P0 | docs/modules/M00-entry-orchestration-PRD.md |
| M01 | 用户输入与 Request 管理模块 | Stage 15 已实现 CLI/Web 确认、取消、受限修改；`ACCEPTED` Request 支持受限修改；Stage 28 已为未保存草案加入 revision 与可靠保存生命周期；Stage 29 已接入统一追番 handoff 与迁移 | P0 | docs/modules/M01-request-management-PRD.md |
| M02 | 番剧搜索与匹配模块 | Stage 25 已实现确定性标题/季数解析与有界查询计划；解析成功不等于真实 MiKan 候选搜索成功 | P0 | docs/modules/M02-bangumi-search-match-PRD.md |
| M03 | MiKan 数据源模块 | Stage 17～25 已实现详情、候选、缓存、共享查询计划、同源安全封面、提前停止和可选总集数契约 | P0 | docs/modules/M03-mikan-source-PRD.md |
| M04 | RSS 解析模块 | Stage 1 已确认 | P0 | docs/modules/M04-rss-parser-PRD.md |
| M05 | 字幕组评估模块 | Stage 1 已确认；Stage 21 已为 `select_subtitle_group` 增加排除列表过滤（先排除、再优先、最后 fallback） | P1 | docs/modules/M05-subtitle-group-evaluation-PRD.md |
| M06 | 种子筛选规则模块 | Stage 15 已实现默认字面匹配、大小写不敏感与可选 `use_regex` / `case_sensitive` | P0 | docs/modules/M06-torrent-filter-rule-PRD.md |
| M07 | 文件夹命名模块 | Stage 1 已确认 | P1 | docs/modules/M07-folder-naming-PRD.md |
| M08 | 用户偏好与规则配置模块 | Stage 21 已实现非敏感偏好契约与存储（字幕组/筛选/命名/搜索修正）、偏好 Web API、偏好 Web UI 和批量草案偏好应用；偏好与修正存储只保存非敏感字段 | P1 | docs/modules/M08-user-preference-rule-PRD.md |
| M09 | Request 确认交互模块 | Stage 2 已实现；Stage 28 已实现单番/批量 save-confirm 组合确认与幂等记录；Stage 29 handoff 幂等建立统一 TrackingRecord | P2 | docs/modules/M09-request-confirmation-PRD.md |
| M10 | Auto Bangumi 集成模块 | Stage 24 已按 3.1.18 契约实现账号密码/Cookie、真实 subscribe payload/response，并保留 fail-closed Bearer 兼容模式；Stage 29 统一 submit/retry/recover 复用该提交边界 | P2 | docs/modules/M10-auto-bangumi-integration-PRD.md |
| M11 | 存储与状态管理模块 | Stage 15/20 已实现 Request、历史、AB 结果和队列存储；Stage 23 已实现 path-safe 封面缓存；Stage 28 已新增 save-confirm 幂等记录 repository；Stage 29 新增 TrackingRecord/TrackingOperation/迁移 manifest 原子存储 | P2 | docs/modules/M11-storage-state-PRD.md |
| M12 | 日志与错误处理模块 | Stage 24 已覆盖 AB 认证、连接、协议兼容与规则转换的脱敏分类；Stage 29 为追番提交、提交结果待确认与恢复提供固定错误与安全审计摘要 | P1 | docs/modules/M12-log-error-PRD.md |
| M13 | Web UI / 管理界面模块 | Stage 25 已完成 AB 界面、解析来源、结构化季数和实际搜索词展示；Stage 26 已冻结 `/api/v1` 契约并建立 OpenAPI/DTO；Stage 27 已完成 Vue 3 + TS + Vite 前端迁移；Stage 28 已接入草案 revision/save-confirm/safe-info；Stage 29 已提供 tracking 列表、详情、复核、提交、重试、恢复 API，正式管理页面留待 B-C | P2 | docs/modules/M13-web-ui-PRD.md |
| M14 | 系统配置模块 | Stage 24 已定义 request-scoped AB 双认证配置；Stage 26 已约束 Web storage 为服务端根目录下的相对 profile | P1 | docs/modules/M14-system-config-PRD.md |

## 8. 第一阶段开发顺序

第一阶段按可运行的纵向链路推进，避免先建设尚未验证的基础设施。

```text
共享数据契约与 fixture
  ↓
M02 + M03 候选读取与匹配
  ↓
M04 + M06 RSS 解析与筛选
  ↓
M05 + M07 订阅默认值
  ↓
M01 Request 快照
  ↓
M00 CLI 与流程编排
  ↓
最小配置与日志收尾
```

说明：

1. 每一步先补行为测试，再实现最小功能。
2. M02 与 M03 合入 catalog_engine，M04 与 M06 合入 rss_engine。
3. M05 与 M07 合入 subscription_engine。
4. M08、M12、M14 在 Stage 1 只提供普通基础模块，不建立独立 engine。
5. 确认交互、持久化和 AB 对接全部后置。

## 9. 后续阶段路线图

| 阶段 | 目标 | 主要模块 |
| --- | --- | --- |
| 第一阶段 | 离线生成 `PENDING_CONFIRM` Request | M00、M01、M02、M03、M04、M05、M06、M07、M08、M12、M14 |
| 第二阶段 | 支持 Request 确认、修改、取消 | M09、M01、M06、M07 |
| 第三阶段 | 建立 Auto Bangumi 离线提交契约、fake client、失败降级 JSON 和显式 CLI 提交路径 | M10、M14、M12 |
| 第四阶段 | 实现真实 Auto Bangumi HTTP client adapter、网络错误标准化和 CLI 真实 client 注入 | M10、M14、M12 |
| 第五阶段 | 扩展真实 MiKan 访问和 RSS 读取 | M03、M04、M12、M14 |
| 第六阶段 | 持久化 Request、状态历史和结果 | M11、M01、M12 |
| 第七阶段 | Flask Web UI / 管理界面 MVP | M13、M11 |
| 第八阶段 | Web UI 可用性增强 | M13 |
| 第九阶段 | 浏览器自动化测试 | M13、测试基础设施 |
| 第十阶段 | Web UI Request 确认、取消和修改操作入口 | M13、M01、M11 |
| 第十一阶段 | Web UI 显式真实 MiKan / Auto Bangumi 配置入口 | M13、M03、M10、M14 |
| 第十二阶段 | qBittorrent 显式连接测试与安全边界 | qBittorrent 集成边界、M13、M14、M12 |
| 第十三阶段 | Web UI Settings 信息架构拆分与界面质量收敛 | M13、M11、M10、qBittorrent 集成边界 |
| 第十四阶段 | Web UI Request 可操作性与筛选可视化修复 | M13、M01、M11、qBittorrent 集成边界 |
| 第十五阶段 | Web UI ACCEPTED 管理与筛选语义优化 | M13、M01、M06、M11 |
| 第十六阶段 | 真实 MiKan 合集详情页解析与直连 URL/ID 入口（已完成） | M03、M00、M13 |
| 第十七阶段 | 真实 MiKan 搜索候选合集展示与用户选择（已完成） | M03、M13、M00 |
| 第十八阶段 | 真实 MiKan 主流程收敛、可编辑预览和 Seeds 展示优化（已完成） | M13、M03、M00、M01、M06 |
| 第十九阶段 | 批量番剧输入、AI 名称解析和订阅草案卡片工作台（已完成） | M13、M00、M01、M03、M06 |
| 第二十阶段 | 批量接受与 Auto Bangumi 提交前队列管理（已完成） | M13、M10、M11、M01 |
| 第二十一阶段 | 用户偏好、字幕组偏好和搜索词增强闭环（已完成） | M08、M03、M05、M13 |
| 第二十二阶段 | Web UI 搜索工作台重构与真实候选闭环（已完成） | M13、M00、M02、M03、测试基础设施 |
| 第二十三阶段 | 媒体缓存、MiKan 读取优化与批量审核体验（已完成） | M03、M11、M12、M13、测试基础设施 |
| 第二十四阶段 | AutoBangumi 真实认证与订阅兼容闭环（已完成） | M10、M12、M13、M14、测试基础设施 |
| 第二十五阶段 | 正式番名与季数解析（已完成） | M00、M02、M03、M07、M10、M12、M13、测试基础设施 |
| 第二十六阶段 | Web API 契约固化与服务端边界治理（已完成） | M00、M01、M11、M12、M13、M14、测试与 CI 基础设施 |
| 第二十七阶段 | 前端工程化迁移与页面重构（已完成） | M13、API 契约、前端与测试基础设施 |
| 第二十八阶段 | 草案一致性与原子保存确认（已完成） | M01、M09、M11、M13、API 契约与测试基础设施 |
| 第二十九阶段 | 统一追番记录与可靠提交恢复（已完成） | M01、M09、M10、M11、M12、M13、API 契约与测试基础设施 |
| 第三十阶段 | Auto Bangumi 只读能力与外部同步基础（已完成，US-228～US-236） | M10、M11、M12、M13、API 契约与测试基础设施 |
| 第三十一阶段 | Auto Bangumi 可靠写管理（已完成，US-237～US-246；B-C2，不实现正式页面） | M10、M11、M12、M13、API 契约与测试基础设施 |
| 第三十二阶段 | 后端契约固化、兼容迁移与前端交接（已完成，US-247～US-256；B-D） | M01、M09、M10、M11、M12、M13、API 契约与测试基础设施 |
| 第三十三阶段 | 前端应用壳层与设计系统（已完成，US-257～US-265；F-A，不实现 F-B～F-G） | M13、前端与测试基础设施 |
| 第三十四阶段 | 前端共享审核核心（已完成，US-266～US-274；F-B，SafeInfo 延后到 F-E） | M13、前端与测试基础设施 |
| 第三十五阶段 | 单番添加完整旅程（已完成，US-275～US-283；F-C，不实现 F-D～F-G） | M13、API 契约、前端与测试基础设施 |
| 第三十六阶段 | 批量审核完整旅程（已完成，US-284～US-293；F-D，不实现 F-E～F-G） | M13、API 契约、前端与测试基础设施 |
| 第三十七阶段 | 追番方案与安全信息（已完成并归档，US-294～US-302；F-E，不实现 F-F～F-G） | M01、M09、M11、M13、API 契约、前端与测试基础设施 |
| 第三十八阶段 | 正式追番管理（已完成并归档，US-303～US-317；F-F，不实现 F-G） | M09、M11、M13、API 契约、前端与测试基础设施 |
| 第三十九阶段 | 部署连接配置与设置发布收尾（已完成并归档，US-318～US-340；F-G） | M09、M10、M11、M13、M14、API 契约与测试基础设施 |

Stage 26 已完成 BL-023：冻结 `/api/v1` 端点与 golden contract、建立响应 DTO 与确定性 OpenAPI、拆分 Web schema/serializer/service/context/route 职责、建立稳定 HTTP 状态语义、收紧 Web storage 根目录、建立服务端权威 draft 生命周期、增加 CI 与 local-only 部署基线，并完成兼容回归与文档收尾。Stage 27 已完成 BL-024：建立 Vue 3 + TypeScript + Vite 独立前端工程（Flask 在 `/app/` 同源托管），渐进迁移全部 Web 旅程并删除旧前端。Stage 28 已完成 BL-025 的 B-A：交付 draft revision、可靠保存、单番/批量原子保存确认、36 部上限与安全信息 DTO；成功 handoff 只返回 `request_id` + `ACCEPTED`。Stage 29 已完成 BL-025 的 B-B：从持久化 ACCEPTED Request 与 handoff 幂等建立统一 TrackingRecord，交付 tracking 列表/详情、纯本地 revalidate、统一 submit、retry/recover、结果待确认恢复和旧入口/队列兼容。Stage 30 已完成 B-C1 只读同步（US-228～US-236）；Stage 31 已完成 B-C2 可靠写管理（US-237～US-246）；Stage 32 已完成 B-D 契约收尾（US-247～US-256）。Stage 33 已完成 BL-026 的 F-A：交付 `/app/add`、`/app/plans`、`/app/tracking`、`/app/settings` 壳层与安全 query 路由迁移、语义 Token、共享 UI 原语、现有业务页兼容挂载及真实 Chromium 可访问性回归；`/app/tracking` 仍是 QueueView 兼容内容。Stage 34 已完成 BL-026 的 F-B：交付共享模式输入、候选集合、草案编辑器、revision 失败恢复和薄兼容适配层。Stage 35 已完成 BL-026 的 F-C：交付单番三步旅程、原子保存确认、确认失败恢复和 tracking 只读 handoff。Stage 36 已完成 F-D：交付 1/12/36 部双栏批量审核、异常优先、原子批量保存确认、部分成功与逐项恢复。Stage 37 已完成 F-E：在已保存 Request 语境下交付方案列表—详情、真实 `SafeInfoDialog`、共享修改、复制再用与精确 tracking 链接。Stage 38 已完成 F-F：以加法补口补齐 generated 严格 modify patch 与安全 target scopes，把 `/app/tracking` 建成正式追番管理页，交付页面级临时凭据会话、显式同步、本地复核、可靠提交/幂等重试、结果待确认恢复与单条外部管理动作；`QueueView` 退出默认运行时但组件与后端兼容端点保留，F-G 负责旧入口最终收敛、全局连接状态与发布收尾。

## 10. 主 PRD 已确认事项

主 PRD 只记录影响阶段范围、用户入口、模块优先级的项目级决策。模块内部规则由模块 PRD 维护。

| 编号 | 事项 | 影响范围 | 当前结论 |
| --- | --- | --- | --- |
| D-MAIN-01 | 第一阶段入口形态 | M00 | 同时支持内部 `generate_request` 能力和最小 CLI 包装 |
| D-MAIN-02 | 第一阶段 Request 输出形式 | M00 | 以 JSON 对象为主，终端展示作为包装能力 |
| D-MAIN-03 | 第一阶段静态数据组织方式 | M03、M04 | 静态 MiKan/RSS 数据纳入仓库并作为测试 fixture，保证离线验收可重复 |
| D-MAIN-04 | 第一阶段实现定位 | 全部 | 最小离线技术探针，不提前建设完整长期架构 |
| D-MAIN-05 | Stage 1 代码结构 | 全部 | 保留 apps/engine/controllers/models，总量收敛为 4 个 engine |
| D-MAIN-06 | Stage 1 Request 状态 | M00、M01 | Request 是 PENDING_CONFIRM 快照，不是完整状态机；失败使用独立 ErrorResult |
| D-MAIN-07 | Stage 19 后产品定位 | 全部 | MiGuOrca 是 Auto Bangumi 前置订阅编排工作台，不是 Auto Bangumi 或 qBittorrent 替代品 |
| D-MAIN-08 | 批量输入方向 | M00、M13、M03 | 下一阶段以批量番剧简称解析、订阅草案卡片和用户审核为主，不再把单番剧自动提交作为核心卖点 |
| D-MAIN-09 | AI 能力边界 | M03、M08、M13 | AI 只生成候选标题和搜索词，不自动决定最终合集；低置信度结果必须可审核 |
| D-MAIN-10 | 前端体验重构边界 | M01、M09、M10、M13 | Gate 1～3 已冻结四项导航与混合布局；Stage 28～32 已完成 B-A～B-D，前端切片独立推进 |

## 11. 文档职责边界

| 文档 | 职责 |
| --- | --- |
| docs/MiGuOrca_main_PRD.md | 项目级目标、第一阶段范围、模块划分、验收标准、路线图 |
| docs/modules/*.md | 模块目标、边界、输入输出、流程、规则、异常、接口、验收 |
| docs/design/architecture.md | 技术架构、目录结构、分层原则、测试组织规范 |
| docs/design/stage1-spec.md | Stage 1 唯一技术行为基线、数据契约、规则与验收用例 |
| docs/api/ | 后续接口、数据结构和对外 API 说明 |
| docs/test_manual/ | 后续真实环境验证、手动测试记录 |

维护原则：

1. 主 PRD 不维护模块字段级细节。
2. 主 PRD 不维护具体算法规则。
3. 主 PRD 不维护完整技术目录和代码结构。
4. 模块 PRD 与主 PRD 冲突时，以主 PRD 的阶段范围和模块边界为准。
5. 模块内部细节以对应模块 PRD 为准。

## 12. 合规说明

本系统定位为 RSS 订阅前置编排和 Auto Bangumi 提交辅助工具。

用户需要自行确保订阅源、下载内容、收藏行为符合当地法律法规及内容授权要求。

系统本身不内置受版权保护内容，不提供资源分发能力，只对用户配置的数据源进行流程编排。

## 13. 下一步工作

1. BL-023 已完成为 Stage 26 Web API 契约固化与服务端边界治理；执行范围见 `docs/MiGuOrca_stage26_web_api_contract_hardening_PRD.md`。Stage 26 不重构页面视觉，不引入新前端框架。
2. BL-024 已完成 Stage 27 前端工程化迁移与页面重构；执行范围见 `docs/MiGuOrca_stage27_frontend_engineering_migration_PRD.md`。前端只通过生成类型/client 使用后端，不导入 Python 模型或复制旧 `app.js` 内部状态（旧 `app.js` 已随 US-209 删除）。
3. BL-025 的 B-A～B-D 已分别完成 Stage 28～32（US-210～US-256）并归档，覆盖契约、兼容、迁移、安全、回退与前端 handoff；正式追番管理页面仍待后续前端阶段。
4. BL-026 的 F-A～F-G 已完成为 Stage 33～39（US-257～US-340）并归档。后续不预设 Stage 40：先由用户审核已交付前端功能、形成问题清单，再按问题的产品边界决定是否立项。
5. BL-020 当前最新播出集数、BL-021 真实 LLM provider 和 BL-022 新版 AutoBangumi Bearer 写契约尚未排期，必须先满足各自的数据源、供应商/密钥或逐版本契约前提。
6. fixture 生成能力继续保留给 CLI、API seam、离线开发和回归测试，但不再作为普通 Web 主流程。
7. 后续不应实现自己的 qBittorrent 下载任务创建，不应绕过 Auto Bangumi 建立长期订阅状态机，不应复制 Auto Bangumi 已有的 MiKan 到下载链路，不应引入后台常驻 worker 或复杂调度器；批量提交继续采用前台顺序编排。
8. 当前 `/app/workbench|requests|queue|settings` 作为兼容入口保留；目标信息架构已交付为 `/app/add|plans|tracking|settings`。所有流程继续禁止把 MiKan config、ab_config、raw HTML、raw RSS XML、magnet、cookie、token 和原始响应体写入 storage JSON、浏览器 storage、URL、history、日志、截图或 trace。
9. 每次阶段推进继续使用 `uv run pytest`、`uv run python -m compileall -q src tests` 和前端工程的 `cd frontend && npm run typecheck && npm run lint && npm run test:unit -- --run && npm run build` 验证；UI story 必须执行真实 Chromium 检查。
