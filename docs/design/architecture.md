# MiGuOrca 架构与目录约定

## 1. 当前形态

项目采用本地优先的模块化单体结构。Flask 同时提供 JSON API 与 Vue SPA 的同源托管，CLI 和 Web API 复用业务 engine 与存储适配器。前端是独立工程（`frontend/`，Vue 3 + TypeScript + Vite），生产构建由 Flask 在 `/app/` 托管；不包含数据库、后台 worker 或多用户认证系统。

```text
CLI                     Vue SPA (frontend/, Flask 同源 /app/)
 │                                  │
 └──────────── apps / Web API ──────┘
                    │
        batch / request / source 编排
                    │
   engines + shared contracts + external adapters
                    │
     本地 JSON storage / MiKan / AutoBangumi / qB
```

## 2. 分层职责

- `apps`：接收 CLI 或 HTTP 输入，编排用例并转换输出，不复制 engine 内的业务规则。
- `extensions/flask_api`：统一 JSON envelope、Pydantic 请求校验和异常脱敏。
- `*_engine`：封装业务能力、外部系统适配器和对应模型。
- `shared`：跨 engine 契约、错误、配置、日志、标题季数等基础能力。
- `tests/browser`：使用 Playwright 在真实 Chromium 验证 Web 用户旅程，默认以 fixture 和 route fake 隔离外部系统。

## 3. 当前目录与职责

| 目录 | 主要责任 |
| --- | --- |
| `apps/migu_orca_entry` | CLI 适配器、`generate_request` 兼容薄壳与显式 AutoBangumi 提交入口 |
| `apps/migu_orca_web` | Flask 页面、JSON API、Web 请求/响应适配与静态前端资源 |
| `extensions/flask_api` | API envelope、校验、异常转换和错误脱敏 |
| `batch_engine` | 批量输入、标题解析、查询计划、偏好应用、接受与提交队列 |
| `catalog_engine` | 静态 fixture catalog 与标题匹配 |
| `mikan_engine` | 真实 MiKan 搜索/详情/RSS 读取、候选缓存和安全封面缓存 |
| `rss_engine` | RSS 解析与种子筛选 |
| `subscription_engine` | 字幕组选择与文件夹命名 |
| `request_engine` | Request 契约、确认、取消、受限修改和摘要 |
| `plan_engine` | 方案生成编排（`build_plan`）、数据源适配器（真实 MiKan / 离线夹具）与方案确认/修改/保存动作 |
| `tracking_engine` | 统一追番记录/operation、外部映射、复核/提交/管理写与恢复规则 |
| `ab_engine` | AutoBangumi 配置、认证 adapter、payload 与提交结果 |
| `qbittorrent_engine` | 历史 qB 适配；Web 连接测试已退役，不进入默认运行时 |
| `storage_engine` | Request、history、AB result、queue、偏好、幂等、tracking/operation/迁移的本地 JSON 存储 |
| `shared` | 跨模块模型、错误、安全日志、标题季数与候选季数证据 |

## 4. 依赖规则

1. `apps` 可以依赖 engine、`shared` 和 Web extension。
2. `shared` 不得依赖 `apps` 或具体 engine。
3. engine 不得反向依赖 `apps`。
4. engine 之间只在已有明确用例关系时直接依赖；跨模块稳定数据优先放入 `shared` 契约。
5. 外部 HTTP、认证与存储细节留在对应 adapter/repository，不进入纯规则函数。
6. 不在多个 engine 中复制标题季数、Request 状态或提交状态模型。

当前存在的跨 engine 依赖包括 Request 使用订阅命名、RSS 使用 MiKan transport 数据、批量接受/提交使用 Request 与 AutoBangumi 能力、storage queue repository 使用批量队列模型、`plan_engine` 编排 catalog/MiKan/RSS、调用 `request_engine` 组装快照并把方案写入 storage。这些是现有用例关系，不代表可以任意增加双向依赖。

## 5. Web 边界现状

Web 业务操作统一通过 `/api/v1/*` JSON API 完成，页面是 Stage 27 迁移的独立前端工程：

- `frontend/` 是 Vue 3 + TypeScript(strict) + Vite 工程，生产构建输出到 `frontend/dist/`
  （不入库），由 Flask 在 `/app/` 同源托管（`app_blueprint`，Vite base 固定 `/app/`，
  SPA fallback 只接管 `/app/*`）；开发用 Vite dev server 代理 `/api/v1` 到本地 Flask。
- 前端类型只通过 `docs/api/openapi.json` 生成（`openapi-typescript`，US-198），
  不导入 Python 模型、不手写第二套响应 interface。
- 入口路由（`/`、`/index`、`/Settings`、`/settings`）始终重定向到 SPA
  （US-209 起旧 Jinja 页面与 `web_entry_mode()` 回退开关已删除）。
- Web API 适配层自 Stage 26 起按职责拆分（`apps/migu_orca_web/`）：
  - `schemas.py`：请求/查询 Pydantic 模型。
  - `api_contract.py`：公开响应 DTO；严格白名单 DTO 使用 `extra="forbid"`，部分兼容嵌套 DTO 允许安全扩展。
  - `serializers.py`：响应序列化与脱敏白名单。
  - `services.py`：用例编排与存储 seam，复用 engine/repository，不复制业务规则。
  - `contexts.py`：短期候选选择上下文。
  - `routes_*.py`：按端点族（requests/mikan/batches/tracking/settings/connections）注册路由。
  - `views.py`：入口重定向路由与 Blueprint 组装。
- `docs/api/` 提供 OpenAPI 契约（`docs/api/openapi.json`，确定性生成），覆盖全部 `/api/v1`
  端点；响应 DTO 在 `api_contract.py`，serializer 先脱敏/白名单投影，不能以兼容 DTO 的宽松配置放出上游原始对象。新增/删除端点必须同步
  `docs/api/endpoint_inventory.md` §2、`openapi_gen.py` `_ENDPOINTS` 注册表、`docs/api/openapi.json`
  与 `tests/api_contract/`，否则契约测试失败。
- 未保存草案由 `drafts.py:DraftStore`（进程内单例）权威持有：TTL 30 分钟、容量 128、
  一次性保存与重放保护；客户端只持 opaque `draft_id`，不提交完整 Request 作为权威快照。
  Stage 28 起每个草案带单调 revision（签发为 1，成功 CAS 修改 +1）：`preview-modify` 用
  `base_revision` 做 compare-and-swap，`preview-save`/save-confirm 用「预留 → 持久化 →
  提交/释放」生命周期（写盘失败保留原 revision 可重试，重放返回 409 `draft_replayed`）。
- save-confirm 幂等记录（Stage 28，US-213）位于 `<storage>/idempotency/<opaque-key>.json`，
  由 `storage_engine/controllers/idempotency_repository.py` 原子读写，只含非敏感白名单字段
  `idempotency_key/operation/request_fingerprint/request_id/state/created_at/updated_at`；
  `apps/migu_orca_web/save_confirm_service.py` 的 `run_save_confirm` 协调器把
  IN_PROGRESS/SAVED_CONFIRM_FAILED/CONFIRMED 状态机接到单番/批量路由（US-214/216）。
- Stage 29（US-219～US-227）把“已确认方案的生命周期”统一到本地 `TrackingRecord`：
  `tracking_engine/models` 定义 schema v1 严格白名单内容契约与确定性 ID/状态机，
  `tracking_engine/controllers` 提供无 storage 依赖的纯分类（migration/revalidate/submit/
  recover）；`storage_engine/controllers/{tracking_repository,operation_repository,
  migration_repository}.py` 把 `<storage>/tracking/`、`<storage>/tracking_operations/`、
  `<storage>/tracking_migrations/` 原子读写为 JSON（确定性 `tracking_id` = 版本命名空间 +
  request_id 摘要、`operation_id` = 版本命名空间 + idempotency_key 摘要，revision/state CAS）。
  `apps/migu_orca_web/tracking_{handoff,migration_service,read_service,revalidate_service,
  submission_service,recovery_service,queue_compat,serializers}.py` 编排 ensure/迁移/复核/提交/
  恢复/旧 queue 兼容投影；新 `/api/v1/tracking/items*` 端点与旧单番 submit-ab、批量
  submit/retry/recover 共享同一 submission service，route 层不复制业务规则。
- Stage 28 的 save-confirm/accept handoff 保留 `request_id + status=ACCEPTED +
  next_action=OPEN_TRACKING`，并新增 `tracking_id/tracking_status/tracking_ready/safe_message`
  （US-222）；tracking 写失败不回滚已确认 Request，也不伪造 tracking 状态。

- Stage 30（B-C1，US-228～US-236，已完成并归档）把 Auto Bangumi 3.1.18 的只读 capability、番剧/RSS adapter、
  external mapping、对账和 `VERIFY_EXTERNAL` 放在 `ab_engine`/`tracking_engine` 与 Web sync service
  中；`POST /api/v1/autobangumi/capabilities`、`POST /api/v1/tracking/sync` 的 DTO、OpenAPI、
  inventory 与生成客户端必须保持同步。原始上游对象和 URL 只在 request-scoped adapter/service 内存中
  存在，未知版本/API Token 管理读取 fail closed。B-C2 才能增加外部写 adapter，且必须复用 tracking
  operation CAS/idempotency/recovery 边界。

- Stage 31（B-C2，US-237～US-246，已完成并归档）在同一 request-scoped 边界内增加四类可靠管理写动作：
  operation v2、严格目标/patch 解析、3.1.18 action-specific adapter、写后回查和 VERIFY_EXTERNAL 恢复。
  管理 route 只接收 tracking ID、固定 scope 与严格白名单字段；operation 仅保存 SHA-256 摘要。番剧
  destructive route 由 adapter 固定 `file=false`，RSS 只执行映射集合内的单项调用。
  Stage 32 B-D 完成兼容迁移、泄漏矩阵、回退和前端 handoff；正式我的追番页面在 Stage 38 交付。

- 当前导航/页面落点由 `frontend/src/app/router/catalog.ts` 和 `index.ts` 统一定义：
  `/app/add` → WorkbenchView，`/app/plans` → RequestsView，`/app/tracking` → TrackingView，
  `/app/settings` → SettingsView。`/app/workbench|requests|queue` 只保留安全兼容重定向；
  QueueView/queueWorkbench 与旧 batch 写端点已退役；`/app/queue` 仅安全重定向，历史 queue reader
  仅供迁移读取。
- 当前前端审核使用共享候选、AnimeDraftEditor、useDraftSession 和旅程 composable；
  tracking 页面统一拥有凭据/写意图/恢复，检查器只消费安全详情和页面会话。具体状态处理见代码/契约。
- 普通前端 API 仍有短超时；MiKan 多步骤搜索/草案/批量读取使用单独有界预算和固定错误映射，
  入口位于 `frontend/src/features/workbench/mikanFeedback.ts`，不是后端已变为异步 worker。

因此前端工程化已先固化 API 契约和服务端安全边界，再渐进替换页面；Stage 26 已完成该固化
（清单/DTO/OpenAPI/HTTP 状态/storage 根/draft/CI），Stage 27 完成迁移与旧前端删除，handoff
见 `docs/MiGuOrca_stage27_frontend_engineering_migration_PRD.md`。Stage 28 在 DraftStore 上
补齐 revision/保存生命周期与 save-confirm 幂等记录，并冻结 `/api/v1` 的 save-confirm/
safe-info 新契约，handoff 见 `docs/MiGuOrca_stage28_draft_consistency_PRD.md`。Stage 29 在
同一契约基线上补齐统一追番记录/提交恢复（tracking 目录族 + 六条 `/api/v1/tracking/*` 端点 +
旧入口收敛），handoff 与 B-C 边界见 `docs/MiGuOrca_stage29_unified_tracking_PRD.md`。

## 6. 状态与持久化

- 默认运行数据位于 `.migu_orca/storage`，不应提交 Git。
- Request、history、AB result、queue、preference、correction、save-confirm idempotency 与
  Stage 29 的 tracking/tracking_operations/tracking_migrations 分目录保存为 JSON
  （Stage 28 幂等记录与 Stage 29 tracking 记录/operation/manifest 都只写非敏感白名单字段，
  见 `idempotency_repository.py`/`tracking_repository.py`/`operation_repository.py`/
  `migration_repository.py`）。
- 候选缓存、候选选择 context 等短期状态当前位于单进程内存，不能假定天然支持多 worker。
- AutoBangumi 凭据唯一持久化例外是服务端专用配置 repository 的 `autobangumi.json`；其余业务
  JSON、URL、浏览器 storage、日志和测试产物均不得含秘密。qB Web 配置与连接测试已退役。
- Web 与 CLI 使用不同 storage 信任边界（US-193）：CLI 继续接受显式 `--storage-dir`；
  Web API 的 `storage_dir` 只能选择服务端根目录下的相对 profile（默认 `.migu_orca/storage`，
  可用 `MIGU_ORCA_WEB_STORAGE_ROOT` 服务端覆盖），绝对路径/穿越/符号链接逃逸返回 400
  `invalid_storage_dir`，错误 details 不回显原始路径。**空值回落服务端根本身**
  （`services._storage_dir(None|""|"  ")` 返回 `_WEB_STORAGE_ROOT`，绝不返回 `None`，
  否则 `load_storage_config(None)` 会回退 CLI 默认并绕过服务端 root 覆盖——US-196 回归修复）。

## 7. 测试与质量门禁

测试包括纯规则单元测试、fixture 解析、API/入口测试和 Playwright 浏览器测试。
下列为完整门禁命令，普通迭代应按 [开发流程](../development/workflow.md) 选择定向检查：

```bash
uv run python -m compileall -q src tests   # 语法检查（只证明可编译）
uv run ruff check src tests                # Python 静态检查（US-195，pyproject.toml [tool.ruff.lint]）
uv run pytest -q -m "not browser"          # 非浏览器测试
uv run pytest tests/browser/ -q            # 真实 Chromium 浏览器套件
uv run migu-orca-openapi --check           # OpenAPI 漂移检查
git diff --check
```

- `compileall` 只是语法检查，**不是**静态检查；静态检查由 `ruff` 承担（pyflakes/
  bugbear/pyupgrade 等规则，见 `pyproject.toml`）。CI（`.github/workflows/ci.yml`）
  依次执行全部上述命令；真实 Chromium 套件在单独 job 运行，`MIGU_ORCA_CI=1` 下浏览器
  不可用会**失败**而不是静默 skip。
- 浏览器不可用时允许明确记录 skip 原因，但不得把整体 skip 当作 UI Stage 的完成证据。
- 健康/就绪探针：`/healthz` 只证明进程存活；`/readiness` 额外校验服务端 Web storage
  根目录可创建/可写（不可用返回 503 `{ok: false, result: "storage_unavailable"}`）。
  两者都不访问真实 MiKan / AutoBangumi / qBittorrent。
- 部署基线：默认 local-only（`flask run` 只监听 127.0.0.1）；未认证时禁止直接暴露公网。
  当部署方明确将 Flask 绑定到局域网后，Host 校验必须继续允许回环地址、IPv4 私网地址
  （如 `192.168.0.0/16`）和链路本地地址，使同一局域网的其他设备可以通过
  `局域网 IP:端口` 访问。公网地址、IPv6 ULA 和其他域名不得因该兼容性放行而自动信任，
  仍须由服务端通过 `MIGU_ORCA_TRUSTED_HOSTS` 显式配置。
- 局域网 Host 放行是正式部署能力，不得为“收紧 Host 校验”或重构中间件而随意删除、
  改回只允许 localhost 的实现。修改 Host 解析/受信逻辑时，必须保留 API 契约回归覆盖：
  `tests/api_contract/test_autobangumi_settings_security.py` 至少验证带端口的 IPv4 私网
  Host 成功、公网 Host 失败，以及显式可信 Host 和 IPv6 ULA 的现有边界。

## 8. 拆分原则

满足以下条件之一时再拆分模块：

1. 出现独立外部系统适配边界。
2. 规则具有独立变化、替换或测试需求。
3. 当前文件已经同时承担 schema、路由、编排和序列化等多种职责。
4. 现有依赖导致循环、并发状态不安全或无法独立验证。

拆分应保持行为兼容和安全边界，不仅为了目录数量或 PRD 编号创建空层次。
