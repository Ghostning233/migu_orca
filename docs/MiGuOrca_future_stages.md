# MiGuOrca Future Stages

## 1. 总体方向

MiGuOrca 后续方向是 Auto Bangumi 前置的批量新番订阅编排工作台，而不是 Auto Bangumi 或 qBittorrent 的替代执行系统。

核心用户流程：

```text
用户从季度新番推荐视频或清单中整理出一批想看的番剧
  ↓
输入简称、口语名或不完整标题
  ↓
MiGuOrca 使用 AI 名称解析和 MiKan 搜索生成可审核订阅草案
  ↓
用户逐项审核、修改、删除、接受
  ↓
接受后显式提交 Auto Bangumi
  ↓
下载执行由 Auto Bangumi / qBittorrent 负责
```

后续阶段必须遵守：

1. 不直接创建 qBittorrent 下载任务。
2. 不绕过 Auto Bangumi 建立长期订阅状态机。
3. 不复制 Auto Bangumi 已有的 MiKan 到下载链路。
4. 不让 AI 静默自动接受最终合集。
5. 所有外部配置和敏感值保持 request-scoped，不进入 storage JSON、浏览器 storage、URL、日志、截图或测试 trace。

## 2. Stage 19: 批量输入与订阅草案卡片工作台（已完成）

完成目标：

已建立新方向的最小可用形态。用户可以一次输入多行番剧简称，系统解析为候选标题和搜索词，逐项生成可审核订阅草案卡片。

已完成功能：

1. 批量输入入口：支持多行输入，每个非空行作为一个条目。
2. AI 名称解析 seam：先提供 fake provider 和稳定接口，后续再接真实 LLM provider。
3. 批量条目 API：返回每个条目的原始输入、解析结果、候选标题、搜索词、置信度和审核状态。
4. 逐项 MiKan 候选搜索：每个条目独立执行，单项失败不影响其他条目。
5. 订阅草案卡片：展示封面、番剧全名、源名称、有效种子数、展开控件和删除按钮。
6. 卡片展开摘要：展示当前字幕组、过滤器、有效种子和排除种子摘要。
7. 单卡修改回流：进入现有订阅方案详情与修改流程，保存后只更新当前卡片。
8. 单卡接受：复用现有 Request 接受能力，将当前卡片标记为已接受。

完成标志（已达成）：

用户可以完成“输入多行简称 -> 生成卡片 -> 删除错误项 -> 展开检查 -> 修改单卡 -> 接受单卡”的闭环。

Stage 19 当时未包含的事项及当前状态：

1. 批量接受和 Auto Bangumi 提交前队列已在 Stage 20 完成；最终采用前台顺序提交，不采用并发队列或后台 worker。
2. 真实 LLM provider 的完整生产配置登记为 BL-021，尚未排期，不是名称解析或 MiKan 搜索的必需依赖。
3. 不自动部署 Auto Bangumi 或 qBittorrent；BL-014 仅评估配置检查、连接诊断、教程和用户自行使用的模板。

## 3. Stage 20: 批量接受与 Auto Bangumi 提交前队列（已完成）

目标：

把 Stage 19 的单卡接受扩展为批量接受和 Auto Bangumi 提交前队列。

已完成功能：

1. 支持单个接受、批量接受和全接受；工具栏显示选中数量，不可接受项目逐项返回中文原因，单项失败不阻塞其他项。
2. 接受后的卡片进入独立追踪的提交前队列（`READY_TO_SUBMIT`/`SUBMITTING`/`SUCCEEDED`/`FAILED`/`RETRYABLE`），队列只保存非敏感元数据，endpoint/token/cookie/Authorization header/原始响应体/完整 RSS URL/magnet/本地绝对路径从不写入队列。
3. 队列面板展示待提交、提交中、提交成功、提交失败、可重试状态、尝试次数和脱敏结果摘要；刷新页面后通过 URL `batch_id` 恢复队列状态。
4. 继续要求用户显式配置或确认 Auto Bangumi endpoint/token/fallback；提交成功后清空敏感输入。
5. 单个提交失败不影响其他卡片；失败项可独立重试，成功项不会被重复提交。
6. 提交结果以脱敏形式写入现有 Request/AB result 存储。
7. 端到端安全回归覆盖 API 响应、页面、URL、浏览器 storage、队列 JSON、Request JSON、日志和 trace 的敏感值过滤。

完成标志（已达成）：

用户可以审核一批卡片，批量确认若干项目，查看提交前队列，显式配置并顺序提交 Auto Bangumi；成功和失败项目独立展示，失败项可独立重试，且所有外部敏感值都没有进入持久化或展示面。

不包含（仍成立）：

1. qBittorrent 下载任务创建。
2. 自动绕过 Auto Bangumi 的订阅执行。
3. 复杂调度器或后台常驻 worker；批量提交采用前台顺序编排。

## 4. Stage 21: 用户偏好与智能推荐闭环（已完成）

前置条件（Stage 20 handoff）：Stage 20 已完成批量接受、提交前队列、Auto Bangumi 顺序提交和失败项独立重试（详见 `docs/MiGuOrca_stage20_batch_ab_queue_PRD.md` 的 Stage 21 handoff）。Stage 21 执行 PRD 见 `docs/MiGuOrca_stage21_preference_recommendation_PRD.md`，在 Stage 19/20 批量草案之上把批量草案结果从“可审核”提升到“大部分可直接接受”，并保持 AI 只生成候选、不自动选择最终合集的边界。

已完成功能：

1. 字幕组偏好：`/settings` 偏好面板记录用户偏好的字幕组、排除字幕组和 fallback 规则；批量草案生成时作为可编辑默认值，真实种子校验的 M05 `select_subtitle_group` 先排除、再优先、最后 fallback。
2. 筛选偏好：默认 `filter_rule`（包含/排除规则、使用正则、大小写敏感）作为单卡可编辑默认值，复用 M06 语义。
3. 文件夹命名偏好：命名策略（official_title_season/official_title/raw_title）和命名模板生成 `expected_folder_name` 默认值，用户仍可逐卡修改。
4. 搜索词增强闭环：用户明确提交的非敏感修正（raw_title、公开 canonical title、season_hint、公开 bangumi 元数据、query_correction）有界存储（同 raw_title 最新版本 + 全局 500 条上限），后续批量输入复用增强搜索词并保留原始 query 与来源标记。
5. AI 解析质量回看：批量卡片展示低置信度、多候选、偏好冲突、搜索回退/失败等 `needs_user_review` 审核提示，允许用户修正并复用。
6. 安全存储偏好：偏好与修正只保存非敏感字段；endpoint、token、cookie、Authorization header、magnet、raw HTML、raw RSS XML、原始响应体和本地绝对路径从偏好 JSON、API 响应、页面、URL、浏览器 storage、日志和 trace 中被拒绝或剥离。

完成标志（已达成）：

用户每季度批量输入后，系统能根据偏好生成更接近最终配置的订阅草案，减少逐卡修改次数；偏好命中、低置信度和审核提示保持可审核性，无偏好或增强失败时回退 Stage 19 默认流程。

不包含（仍成立）：

1. AI 自动接受合集；偏好只生成可编辑默认值，不自动选择最终 MiKan 合集，不自动接受卡片。
2. 对用户观看行为或下载内容做隐式追踪。
3. 复杂账号体系，除非后续出现多人使用或远程部署需求。

## 5. Stage 22: Web UI 搜索工作台重构与真实候选闭环（已完成）

目标：

修复人工验收发现的搜索可信度和界面信息架构问题，使单个搜索与批量搜索真正复用同一套真实 MiKan 候选发现、候选选择和草案生成链路。

主要功能：

1. 将 `/index` 主入口改为用户可理解的“创建订阅方案”，通过“单个搜索 / 批量搜索”分段控件切换输入模式。
2. 新增与订阅方案详情同级、独占一行的搜索结果面板，单个和批量结果统一在此展示。
3. 明确区分标题解析、候选 FOUND/EMPTY/FAILED 与 DRAFT/READY 草案状态；`PARSED` 不再被当作真实候选或可接受草案。
4. 批量模式只编排多个单项候选搜索；无候选时明确显示空结果，不根据用户输入创建空壳 `preview_request`。
5. 单个和批量候选统一展示公开标题、MiKan ID、封面或占位，并要求用户显式选择真实合集后再生成草案。
6. 利用现有状态容器展示简洁、真实的搜索反馈，不伪造不可观测的页面解析步骤。
7. 使用生产 API 的真实状态形状补齐 Playwright 回归，移除用理想化 `DRAFT` mock 掩盖 `PARSED` 契约错误的测试模式。

完成标志（已达成）：

用户可以清晰切换单个/批量搜索，在独立结果区域查看真实候选；无效输入显示明确无结果且不能展开或接受；选择真实候选后才进入可编辑草案，并有真实 Chromium 回归保护。

执行 PRD：`docs/MiGuOrca_stage22_web_search_workbench_PRD.md`。

## 6. Stage 23: 媒体缓存、MiKan 读取优化与批量审核体验（已完成）

目标：

已解决 Stage 22 人工验收后的封面可达性、MiKan 大响应、候选/草案展示和禁用按钮反馈问题：同源安全封面缓存、结构感知提前停止、锚定候选浮层、统一草案详情、播出进度占位及静态禁用反馈均已完成。

主要功能：

1. 服务端安全缓存 MiKan 封面，默认 7 天滑动 TTL、10 秒下载超时、5 MiB 上限；浏览器只访问同源 opaque URL并异步加载。
2. 以脱敏大响应 fixture 证明候选完整性后，对 MiKan 搜索页实现 marker/结构感知提前停止，减少无用读取字节。
3. 批量候选改为锚定“查看候选”按钮的单实例浮层，支持点击外部/Escape 关闭和无障碍焦点恢复。
4. 批量草案统一进入“订阅方案详情”，结果卡不再内嵌完整草案或互相拉伸。
5. 卡片显示 `播出进度：待开发 / 总集数`；总集数只使用 MiKan 明确公开元数据，缺失显示未知。
6. 禁用按钮使用静态反馈与普通/default 鼠标，只有真实 busy 状态显示 loading。

执行 PRD：`docs/MiGuOrca_stage23_media_cache_search_ui_PRD.md`。

不包含：正式番名/季数解析、最新播出集数抓取、流式封面代理、后台 worker 或部署向导。

## 7. Stage 24: AutoBangumi 真实认证与订阅兼容闭环（已完成）

目标：

已修复 Stage 20 真实 adapter 与 AutoBangumi 3.1.18 的协议不兼容：默认用服务地址、用户名和密码登录，通过单次 token Cookie 调用只读状态与 `/api/v1/rss/subscribe`；保留新版 API Token/Bearer 兼容模式（无已证明写契约时 fail closed），并完成连接测试和单个/批量队列接通。

执行 PRD：`docs/MiGuOrca_stage24_autobangumi_compatibility_PRD.md`。

## 8. Stage 25: 正式番名与季数解析（已完成）

Stage 24 完成后已按 backlog 选择 BL-018，并完成独立执行 PRD：`docs/MiGuOrca_stage25_title_season_parsing_PRD.md`。

规划目标：

1. 用确定性规则解析器替换普通 Web 流程的 fake 默认，实现常见标题/季数表达第一至第九十九季的结构化解析。
2. 单个与批量入口共享 parse → 有界 query plan → M03 candidate search 编排。
3. 复用用户明确保存的公开修正和版本化别名，保留低置信度、冲突季数、手动搜索与 MiKan URL/ID fallback。
4. 收敛解析来源、识别季度和实际搜索词 UI，修复“源名称：搜索词：...”标签叠加。
5. parser 只生成搜索提示；真实合集仍由用户显式选择，候选无非第一季公开证据时必须明确确认，只有可证明季数才能进入 Request、命名与 AutoBangumi 映射。
6. AutoBangumi 3.1.18 的可选 `poster_link` 只使用服务端读取并校验的 MiKan 原始公开海报 URL；浏览器 opaque 封面地址不会下传，缺失海报不阻断订阅。

真实 LLM provider、当前播出集数和新版 AutoBangumi Bearer 写契约不进入 Stage 25。

## 9. Stage 26：Web API 契约固化与服务端边界治理（已完成）

Stage 26 已完成并合入 `main`。执行 PRD 为 `docs/MiGuOrca_stage26_web_api_contract_hardening_PRD.md`。

已完成目标：

1. 冻结 `/api/v1` 请求、响应、错误和敏感值契约，增加 Pydantic 响应 DTO 与 OpenAPI。
2. 拆分当前集中的 Web schema、serializer、service、context 和 route 职责。
3. 建立正确 HTTP 状态，同时兼容现有 JSON envelope 和旧页面。
4. 限制 Web storage 根目录（空值回落服务端根），用服务端权威 draft 替代客户端完整 Request 持久化。
5. 明确 local-only 默认部署，建立 CI、契约漂移与真实 Chromium 门禁。

Stage 26 不引入新前端框架、不改变主要页面设计；前端工程化迁移作为 Stage 26 完成后的独立 Stage。

### Stage 26 handoff：Stage 27 前端工程化迁移与页面重构

Stage 27 已作为 BL-024 完成（`docs/MiGuOrca_stage27_frontend_engineering_migration_PRD.md`）。它使用 Vue 3、TypeScript 和 Vite，先通过真实生成器校准 Stage 26 OpenAPI，再按应用外壳/安全组件、Settings、Request 列表/详情、单个搜索、批量工作台与提交队列顺序渐进迁移，在完整 parity 和回退演练后切换默认入口；US-209 已删除旧 `app.js`、旧 Jinja 主模板与无用 CSS/测试 helper，入口路由固定重定向到 SPA。

### Stage 28 handoff：B-B 统一追番记录

Stage 28 已作为 BL-025 的 B-A 完成（`docs/MiGuOrca_stage28_draft_consistency_PRD.md`，Ralph stories US-210～US-218，归档于 `scripts/ralph/archive/2026-09-08-stage28-draft-consistency/`）。它为 DraftStore 增加单调 revision 与 compare-and-swap、把保存改为预留生命周期、建立持久化 save-confirm 幂等记录、新增单番/批量 save-confirm 与 36 部服务端边界，并以 `safe-info` 严格白名单 DTO 提供“全部信息”安全数据源。**Stage 28 只返回 ACCEPTED Request handoff（`request_id` + `status=ACCEPTED` + `next_action=OPEN_TRACKING`），不创建或伪造 tracking record**；B-B 阶段应从持久化 ACCEPTED Request 与 handoff 幂等建立统一 tracking record，旧单番/批量提交写入成功后也必须更新同一 tracking record，避免两套状态源分叉。

### Stage 29 已完成：B-B 统一追番记录与可靠提交恢复

B-B 已作为 BL-025 的第二个工作包完成（`docs/MiGuOrca_stage29_unified_tracking_PRD.md`，Ralph
stories US-219～US-227，归档于 `scripts/ralph/archive/2026-09-08-stage29-unified-tracking/`）。
Stage 29 建立确定性 TrackingRecord（版本化命名空间 + request_id 摘要的 opaque `tracking_id`，
严格 schema v1 + revision compare-and-swap + 内嵌审计）、独立 TrackingOperation（跨重启提交
幂等与恢复证据）与纯本地历史迁移 manifest（首次 tracking API 访问前运行，COMPLETE 后不再全量
扫描，PARTIAL 安全重试）；accept/save-confirm/批量 handoff 兼容扩展 tracking 状态；新增统一追番
列表/安全详情/revalidate/submit/retry/recover API。旧 batch queue 仅保留一个发布周期作为兼容
投影，新提交流程以 TrackingRecord 为权威；任何可能已送达外部但结果未知的操作必须先恢复，禁止
盲目重试。旧单番 submit-ab 与批量 submit/retry/recover 已收敛到统一 submission/recovery
service，调用前/调用后双写失败都不覆盖已落盘成功。Stage 29 **不实现** Auto Bangumi 全量同步、
修改、启停、删除、RSS 刷新或正式前端页面。

### Stage 29 handoff：B-C Auto Bangumi 管理、外部同步与追番管理页面

Stage 29 交付后，B-C 只能基于已冻结的 TrackingRecord 与 external mapping 扩展，不能改变 B-B 的
纯本地语义：

- Auto Bangumi 3.1.18 capability 探测；未知版本写操作 fail closed。
- 外部 subscription/RSS 的列表、详情、修改、启停、删除与刷新（独立 adapter + opaque external ID
  命名空间，`EXTERNAL_ONLY` 记录）；`POST /api/v1/tracking/sync`。
- 优先按已保存 external ID 对账；无 ID 时由 adapter 明确定义多字段证据，歧义进入恢复。
- recover 新增独立外部核验动作，不改变 Stage 29 `AUTO` 的纯本地语义；`VERIFY_EXTERNAL` 作为 B-C
  独立动作。
- 外部删除只删除外部对象；本地 Request、TrackingRecord、审计与媒体全部保留。
- B-C PRD 与 OpenAPI 冻结前，不启动依赖外部管理能力的“追番管理”正式前端页面。
- B-B 已交付的 tracking 列表/详情/revalidate/submit/retry/recover 端点可作为 B-C 管理动作的前端
  数据源；旧 queue 兼容投影保留一个发布周期，删除旧接口须由独立 PRD 决定。

### Stage 30 已完成 B-C1：Auto Bangumi 只读能力与外部同步

Stage 30 执行 PRD 为 `docs/MiGuOrca_stage30_ab_read_sync_PRD.md`，US-228～US-236 已完成并归档。
它交付 Auto Bangumi 3.1.18 capability、番剧/RSS 只读 adapter、安全投影、
external mapping、严格对账、`EXTERNAL_ONLY` 记录、`POST /api/v1/tracking/sync` 与
`VERIFY_EXTERNAL` 只读恢复；OpenAPI、endpoint inventory 和生成客户端已无漂移。未知版本与 API
Token 管理读取 fail closed。Stage 30 不实现 modify、启停、删除、RSS 刷新或正式追番管理页面；
这些写操作属于后续 B-C2。

### Stage 31 已完成：B-C2 外部可靠写管理

B-C2 的 operation kind 固定为 `MODIFY`、`SET_ENABLED`、`DELETE_EXTERNAL`、`REFRESH_RSS`。写操作
必须显式 `confirm=true`，携带幂等键与 `expected_revision`，经 `PREPARED → IN_PROGRESS → 终态`
和结果未知恢复；写后必须只读回查并 CAS 更新安全投影。`DELETE_EXTERNAL` 强制 `file=false`，
API 不接受 `file`，不得删除本地 Request、TrackingRecord、审计、下载任务或媒体。完成 B-C2/B-D
契约收尾后才允许启动正式追番管理页面。

正式执行 PRD 为 `docs/MiGuOrca_stage31_ab_write_management_PRD.md`，分支为
`ralph/stage31-ab-write-management`，US-237～US-246 已完成并归档。四类写动作、operation v2、
回查恢复、四个管理 API 与生成契约均已交付；Stage 31 不开发前端页面。

### Stage 32 已完成：B-D 后端契约固化、兼容迁移与前端交接

Stage 32 执行 PRD 为 `docs/MiGuOrca_stage32_contract_hardening_PRD.md`，分支为
`ralph/stage32-contract-hardening`，使用为后端预留的 US-247～US-256。它只完成端点生命周期、
严格 DTO/OpenAPI/生成类型、旧入口兼容与 tracking 权威状态、历史 schema 迁移、capability 降级、
敏感信息泄漏矩阵、发布回退和版本化前端 handoff。现有旧端点仍有真实前端调用且没有经过完整
发布周期，因此本阶段不删除旧端点；同时不新增外部管理动作或开发正式追番管理页面。US-247～US-256
已全部通过，最终门禁和文档已归档；后续 F-F 可在该生成契约 handoff 上单独规划。

## 10. Gate 1～3 之后的前端体验重构方向

2026-09-07 已完成桌面端前端体验重构的产品方向、混合低保真、组件级交互和视觉方案评审。
2026-09-08 B-A 已作为 Stage 28 完成并交付，B-B 已作为 Stage 29 完成并交付；2026-09-09 B-C1
已作为 Stage 30 完成，B-C2 已作为 Stage 31 完成；B-D 已作为 Stage 32 完成，F-A 已作为
Stage 33 完成，F-B 已完成为 Stage 34，F-C 已完成为 Stage 35，F-D 已完成为 Stage 36，F-E 已规划为 Stage 37，其余工作包暂不分配正式 Stage 编号：

1. BL-025 后端支撑：B-A 已作为 Stage 28 完成，覆盖 draft revision、可靠保存、单番/批量保存
   确认、36 部上限和 safe-info（见 `docs/MiGuOrca_stage28_draft_consistency_PRD.md`）；B-B 已作为
   Stage 29 完成，覆盖统一追番记录/提交恢复契约（见
   `docs/MiGuOrca_stage29_unified_tracking_PRD.md`）；B-C1 已作为 Stage 30 完成，只处理 Auto Bangumi
   3.1.18 只读同步与映射；B-C2 已作为 Stage 31 完成；B-D 已作为 Stage 32 完成（见
   `docs/MiGuOrca_stage32_contract_hardening_PRD.md`）。总体候选 PRD 为
   `docs/MiGuOrca_frontend_ux_backend_support_PRD.md`。
2. BL-026 前端分片：F-A 已完成为 Stage 33（US-257～US-265），只实现四项导航、壳层、Token、
   共享状态与现有页面兼容挂载，执行 PRD 为 `docs/MiGuOrca_stage33_frontend_shell_PRD.md`；
   F-B 共享审核核心已完成为 Stage 34；F-C 单番三步、原子保存确认和 tracking 只读 handoff 已完成
   为 Stage 35；F-D 的 1/12/36 部批量审核已完成为 Stage 36；F-E 追番方案与安全信息已规划为
   Stage 37；正式追番管理和设置收尾继续作为 F-F～F-G 评审。

后端按 B-A～B-D、前端按 F-A～F-G 表达依赖。B-A 已按 9 个单次迭代 story（US-210～US-218）作为
Stage 28 完成并归档到 `scripts/ralph/archive/2026-09-08-stage28-draft-consistency/`；B-B 已按 9 个
story（US-219～US-227）作为 Stage 29 完成并归档到
`scripts/ralph/archive/2026-09-08-stage29-unified-tracking/`。Stage 34 已按 9 个单次迭代 story
（US-266～US-274）完成并归档；Stage 35 已按 9 个单次迭代 story（US-275～US-283）完成并归档；
Stage 36 已按 10 个单次迭代 story（US-284～US-293）完成并归档；Stage 37 已按 9 个单次迭代
story（US-294～US-302）规划。其余正式 Stage 仍应在 PRD 评审后按可独立验收的工作量生成，不要求一个 backlog 对应一个 Stage，
也不要求连续编号一次全部锁定。
Stage 28～32 的现有功能、OpenAPI 生成客户端和浏览器测试作为 Stage 33 迁移基线保留，
不能用一次性大重写替换。

## 11. 未开发事项优先级池

除已完成的 Stage 26～36 和已规划的 Stage 37 外，其他事项继续按 `docs/backlog.md` 的触发条件动态
排序，允许插入更高优先级修复。

### 未排期与条件触发事项

1. BL-020 当前最新播出集数：先证明公开稳定的数据源，不使用种子/RSS/下载状态猜测。
2. BL-021 真实 LLM 名称解析 provider：独立评估供应商、密钥、成本和 fallback。
3. BL-022 新版 AutoBangumi API Token/Bearer 写契约：仅在目标版本和写契约可证明时排期，未知契约继续 fail closed。
4. OF-001 流式封面代理：保留在 `docs/optional_features.md`，仅当真实慢网测试证明现有缓存体验不足时考虑。

### 部署/配置向导可行性验证

目标：

验证是否需要帮助用户降低 Auto Bangumi、qBittorrent 和 MiGuOrca 的初始配置成本。该阶段是远期可选能力，不阻塞批量订阅工作台。

主要功能候选：

1. 配置检查清单：检测 AB/qB/MiGuOrca 的连接配置是否完整。
2. 连接诊断：复用现有 qBittorrent test connection 和 Auto Bangumi submit seam，输出脱敏诊断。
3. 教程式向导：按步骤引导用户填写 endpoint、token、qB 地址和认证信息。
4. Docker Compose 模板：提供可读模板和安全说明，用户自行部署。
5. 配置导入/导出：只处理非敏感配置或明确脱敏后的示例。

完成标志：

用户能更快完成 AB/qB/MiGuOrca 的连接配置诊断，但 MiGuOrca 不接管用户机器或容器环境。

不包含：

1. 通用运维 Agent。
2. 默认接管 NAS、服务器或 Docker daemon。
3. 未经确认写入外部系统配置。
4. 自动创建下载任务或替代 Auto Bangumi 执行链路。

## 12. 阶段数量判断

已明确完成或进入开发的核心产品阶段为：

1. Stage 19：批量输入与订阅草案卡片工作台（已完成）。
2. Stage 20：批量接受与 Auto Bangumi 提交前队列（已完成）。
3. Stage 21：用户偏好与智能推荐闭环（已完成）。
4. Stage 22：Web UI 搜索工作台重构与真实候选闭环（已完成）。
5. Stage 23：媒体缓存、MiKan 读取优化与批量审核体验（已完成）。
6. Stage 24：AutoBangumi 真实认证与订阅兼容闭环（已完成）。
7. Stage 25：正式番名与季数解析（已完成）。
8. Stage 26：Web API 契约固化与服务端边界治理（已完成）。
9. Stage 27：前端工程化迁移与页面重构（已完成，US-209 删除旧前端）。
10. Stage 28：草案一致性与原子保存确认（已完成，US-210～US-218；只返回 ACCEPTED handoff，不创建 tracking record）。
11. Stage 29：统一追番记录与可靠提交恢复（已完成，US-219～US-227；不实现 Auto Bangumi 管理/外部同步，B-C handoff 见上）。
12. Stage 30：Auto Bangumi 只读能力与外部同步基础（已完成，US-228～US-236；B-C1，只读，不实现外部管理写动作）。
13. Stage 31：Auto Bangumi 可靠写管理（已完成，US-237～US-246；B-C2，不实现正式页面）。
14. Stage 32：后端契约固化、兼容迁移与前端交接（已完成，US-247～US-256；B-D，不新增动作或删除旧端点）。
15. Stage 33：前端应用壳层与设计系统（已完成，US-257～US-265；F-A，不实现新业务页面）。
16. Stage 34：前端共享审核核心（已完成，US-266～US-274；F-B，SafeInfo 延后到 F-E）。
17. Stage 35：单番添加完整旅程（已完成，US-275～US-283；F-C，不实现 F-D～F-G）。
18. Stage 36：批量审核完整旅程（已完成，US-284～US-293；F-D，不实现 F-E～F-G）。
19. Stage 37：追番方案与安全信息（已规划，US-294～US-302；F-E，不实现 F-F～F-G）。

因此，Stage 19 到 Stage 29 的原产品闭环与前后端工程基线已经完成，Stage 26 作为 P0 后端基础
阶段已交付，Stage 27 作为 P1 前端迁移阶段已交付，Stage 28 作为 BL-025 的 B-A 草案一致性
阶段已交付，Stage 29 作为 BL-025 的 B-B 统一追番阶段已交付；Stage 30 已完成 B-C1 只读同步，
Stage 31 已完成 B-C2 可靠写管理；Stage 32 已完成 B-D 契约收尾，BL-026 的 F-A 已在最新
`main` 基线上完成为 Stage 33；F-B 已从该合并基线完成为 Stage 34，目标分支为
`ralph/stage34-shared-review-core`，并已归档到
`scripts/ralph/archive/2026-09-11-stage34-shared-review-core/`。
其余前端工作包仍按依赖和真实工作量拆分。F-B 共享审核核心已完成（US-266～US-274）；F-C 已
完成为 Stage 35（US-275～US-283），接管单番保存确认后移除 `DraftPreviewPanel` 兼容保存，并
提供不含正式管理动作的 tracking 只读 handoff。F-D 已完成为 Stage 36（US-284～US-293），接管
批量保存确认后移除 `BatchDraftPreviewPanel` 兼容接受；F-E 已规划为 Stage 37（US-294～US-302），
在已保存 Request 语境下独占真实 `SafeInfoDialog`/`getRequestSafeInfo`，并交付列表—详情、共享修改、
复制再用与精确 tracking 链接。F-F 正式追番管理仍须单独规划，并复用 Stage 32 最终 generated contract。
流式封面代理等未排期方向继续记录在 `docs/optional_features.md`。
