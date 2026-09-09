# MiGuOrca Stage 30 PRD：Auto Bangumi 只读能力与外部同步基础

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 文档名称 | Stage 30 PRD：Auto Bangumi 只读能力与外部同步基础 |
| 文档类型 | 执行 PRD / 前端体验重构 B-C1 |
| 当前状态 | 已完成并归档（US-228～US-236） |
| 创建日期 | 2026-09-09 |
| Backlog | BL-025（B-C1） |
| 优先级 | P0 |
| 前置条件 | Stage 26～29 已完成并合入 `main`；Stage 29 B-C handoff 已冻结 |
| 开发分支 | `ralph/stage30-ab-read-sync` |
| Ralph stories | US-228～US-236 |

## 2. 背景与拆分理由

Stage 29 已经让单番、批量和历史记录收敛到本地 `TrackingRecord`，并建立可靠提交、幂等操作和
纯本地恢复。下一步需要把 Auto Bangumi 中已经存在的番剧和 RSS 读入该统一视图，否则“追番管理”
仍只能管理 MiGuOrca 自己创建的记录，无法确认外部真实状态。

原 B-C 同时包含 capability、同步、映射、修改、启停、删除和刷新，风险与工作量过大。Auto
Bangumi 3.1.18 的部分历史管理接口使用 GET 或 DELETE 执行状态变更，并含 `file` 参数；在没有
独立幂等、确认和“不删除媒体”保护前，不适合与只读同步一起交付。因此 B-C 拆为：

- **B-C1 / Stage 30**：能力探测、只读番剧/RSS adapter、安全投影、映射对账、`EXTERNAL_ONLY`
  记录、只读外部核验。
- **B-C2 / 后续阶段**：修改、启停、外部删除、RSS 修改/启停/删除/刷新及可靠写操作状态机。

Stage 30 是后端与 API 阶段，不实现正式“追番管理”页面，不调用真实 Auto Bangumi 写接口。

## 3. 已核实的 3.1.18 契约

以 Auto Bangumi 官方仓库 `3.1.18` tag 为事实源：

- `POST /api/v1/auth/login`：表单用户名/密码，返回访问 token；后续使用 `token` Cookie。
- `GET /api/v1/status`：返回版本信息。
- `GET /api/v1/bangumi/get/all`：返回全部 `Bangumi`。
- `GET /api/v1/bangumi/get/{bangumi_id}`：返回单个 `Bangumi`。
- `GET /api/v1/rss`：返回全部 `RSSItem`。
- `Bangumi` 包含 `id/official_title/title_raw/season/group_name/rss_link/deleted` 等字段。
- `RSSItem` 包含 `id/name/url/aggregate/parser/enabled` 等字段。

事实源：

- <https://github.com/EstrellaXD/Auto_Bangumi/blob/3.1.18/backend/src/module/api/bangumi.py>
- <https://github.com/EstrellaXD/Auto_Bangumi/blob/3.1.18/backend/src/module/api/rss.py>
- <https://github.com/EstrellaXD/Auto_Bangumi/blob/3.1.18/backend/src/module/models/bangumi.py>
- <https://github.com/EstrellaXD/Auto_Bangumi/blob/3.1.18/backend/src/module/models/rss.py>

自动化测试只使用脱敏 fixture/fake transport。Ralph 不得访问用户真实实例。

## 4. 目标

1. 建立稳定的 capability DTO，明确 3.1.18 已验证只读能力与未知版本 fail-closed 行为。
2. 让 password adapter 在一次请求内登录一次、复用同源 Cookie 会话完成 status/bangumi/RSS 读取。
3. 把上游 Bangumi/RSS 映射为内部严格模型和浏览器安全 DTO，不暴露 URL、凭据或原始响应。
4. 为 `TrackingRecord.external_mapping` 冻结嵌套 schema v1，并支持确定性的外部孤立记录 ID。
5. 使用已保存外部 ID或严格多字段证据对账，不按标题模糊自动关联。
6. 提供 `POST /api/v1/tracking/sync`，把本地方案与外部对象收敛到统一追番列表。
7. 实现 `EXTERNAL_ONLY`、`DISABLED`、`EXTERNAL_DELETED` 的实际同步语义且永不伪造 Request。
8. 为 Stage 29 recover 新增独立 `VERIFY_EXTERNAL` 动作；原 `AUTO` 继续保持纯本地。
9. 同步 OpenAPI、endpoint inventory、生成 TypeScript client、契约/泄漏测试和 B-C2 handoff。

## 5. 非目标

1. 不实现正式追番管理、添加番剧或设置页面的 UI 改造。
2. 不实现外部 modify、enable、disable、delete、RSS update/delete/refresh 等写操作。
3. 不让 capability endpoint、sync 或 VERIFY_EXTERNAL 调用任何外部写接口。
4. 不在自动化或 Ralph 中访问用户真实 Auto Bangumi 实例。
5. 不支持未知 Auto Bangumi 版本的推测性读取或任何写操作。
6. 不支持 API Token/Bearer 模式的管理读取；仅保留 Stage 24 的只读 status probe。
7. 不删除本地 Request、TrackingRecord、审计、下载任务或媒体文件。
8. 不持久化或回传 endpoint、用户名、密码、token、Cookie、Authorization、完整 RSS URL、
   poster 原始 URL、上游原始响应、magnet 或服务器绝对路径。
9. 不删除 Stage 29 旧单番/批量接口和 queue 兼容投影。
10. 不实现 BL-020“已更新集数”；继续返回 `null + NOT_IMPLEMENTED`。

## 6. 核心决策

| 编号 | 决策 | 说明 |
| --- | --- | --- |
| D30-01 | B-C 拆为只读与写管理两个阶段 | Stage 30 只做 B-C1；破坏性或可变更外部状态的动作全部后置。 |
| D30-02 | 3.1.18 精确基线 | 完整同步只对版本 `3.1.18` 标记已验证；其他版本能力为 `UNKNOWN`，不得猜测。 |
| D30-03 | capability 表示当前 adapter 可安全执行的能力 | Stage 30 的 list/detail 为 `SUPPORTED`；尚未实现的写能力为 `UNKNOWN`，并给出固定安全说明。 |
| D30-04 | 一次请求一个临时会话 | password client 登录一次并复用同源 token Cookie；请求完成即释放，不缓存凭据。 |
| D30-05 | 上游原始模型只存在内存 | 原始 URL 和完整对象仅用于当前同步匹配；持久化与 API 只写白名单投影。 |
| D30-06 | 外部 ID 优先 | 已保存 adapter + external ID 精确匹配优先于任何字段证据。 |
| D30-07 | 无 ID 时只允许严格唯一证据 | 精确标题、季度、字幕组并在可用时加 RSS URL 内存比对；0 个或多个候选均不自动绑定。 |
| D30-08 | 外部孤立对象不伪造 Request | 创建 `request_id=null`、origin=`EXTERNAL_SYNC` 的 `EXTERNAL_ONLY` TrackingRecord。 |
| D30-09 | 外部孤立 tracking ID 确定且不可逆 | ID 由版本化 namespace + adapter + object kind + upstream ID 的 SHA-256 摘要生成。 |
| D30-10 | sync 逐条收敛、部分失败可见 | 单条 CAS 冲突或损坏不回滚健康项；返回 counts + 固定 warnings，不回显原对象。 |
| D30-11 | AUTO 语义不变 | `recover(action=AUTO)` 永远纯本地；只有 `VERIFY_EXTERNAL` 接收 `ab_config` 并只读外部。 |
| D30-12 | 同步不覆盖本地进行中状态 | `SUBMITTING`、`REVALIDATING` 等操作中记录只补安全证据，不由 sync 强行改终态。 |
| D30-13 | 已映射对象在完整列表缺失时保留记录 | 可标记 `EXTERNAL_DELETED`，但绝不删除 Request、TrackingRecord、审计或媒体。 |
| D30-14 | EXTERNAL_ONLY 代表真实外部追番 | 状态组由 Stage 29 的预留 `INACTIVE` 调整为 `ACTIVE`；若上游 deleted/disabled 再进入对应非活动状态。 |

## 7. 数据契约

### 7.1 Capability

固定枚举：

```text
CapabilityState = SUPPORTED | UNSUPPORTED | UNKNOWN
probe_status = VERIFIED | PARTIAL | FAILED
```

`AutoBangumiCapabilitiesDTO` 必须 `extra="forbid"`：

```text
probe_status
version: string | null
adapter: legacy_3_1 | api_token | null
subscription_list/detail/modify/enable/disable/delete: CapabilityState
rss_list/modify/enable/disable/delete/refresh: CapabilityState
external_verify: CapabilityState
checked_at
safe_message: string | null
```

规则：

- password + `3.1.18`：subscription list/detail、rss list、external verify 为 `SUPPORTED`。
- Stage 30 未交付的管理写动作统一为 `UNKNOWN`，不能因为上游存在路由就向用户承诺可用。
- 探测失败：`probe_status=FAILED`，全部能力 `UNKNOWN`。
- API Token：保留已验证 status 能力，B-C1 管理读取均 `UNKNOWN`。
- `safe_message` 只用固定中文文案，不含地址、账号、版本原始响应或异常文本。

### 7.2 内部外部对象

adapter 内部模型区分“当前请求内原始对象”和“可持久化安全投影”。

`ExternalSubscription` 内部对象可临时包含用于精确匹配的 RSS URL，但不能离开 adapter/service
边界。安全投影只允许：

```text
external_id: string
title: string
season: int | null
subtitle_group: string | null
deleted: bool
rss_count: int
```

`ExternalRss` 安全投影只允许：

```text
external_id: string
name: string | null
aggregate: bool
parser: string | null
enabled: bool
```

浏览器 DTO 默认不返回 external ID；管理动作始终以本地 `tracking_id` 定位。若调试/契约测试需要
关联，只返回服务端生成的 opaque reference，不返回原始 URL。

### 7.3 ExternalMapping schema v1

`TrackingRecord.external_mapping` 从 Stage 29 的安全预留对象冻结为：

```text
schema_version: 1
adapter: legacy_3_1
subscription_id: string | null
rss_ids: list[string]
match_reason: EXTERNAL_ID | EXACT_FIELDS | EXTERNAL_ONLY
external_deleted: bool
enabled: bool | null
missing_sync_count: int
last_verified_at: RFC3339 string | null
```

约束：

- 字段严格白名单，未知字段拒绝；敏感 key/value 继续由深层清洗兜底。
- `rss_ids` 有序去重并设置合理数量上限；只允许短 opaque token。
- 不保存标题、URL、凭据、原始响应、错误原文或绝对路径。
- 已有 Stage 29 `external_mapping` 若不符合 v1，只能安全读取为 legacy/unknown，不能猜测改写。

### 7.4 外部孤立记录

新增 origin `EXTERNAL_SYNC` 与纯函数：

```text
tracking_id_for_external(adapter, object_kind, external_id)
create_external_tracking_record(...)
```

算法冻结：

```text
trk_ + sha256("migu-orca/tracking/external/v1\0" + adapter + "\0" + kind + "\0" + id)[:32]
```

外部孤立记录：

- `request_id=null`，不创建 Request snapshot。
- `status=EXTERNAL_ONLY`；上游 `deleted=true` 时为 `EXTERNAL_DELETED`。
- `plan_summary` 只保存经安全 label 清洗的 title/season/subtitle_group/poster_path(null)。
- 同一 adapter + kind + ID 重复 sync 必须收敛同一记录，不 bump revision、不重复审计。

## 8. 对账规则

### 8.1 匹配顺序

1. 现有 `external_mapping.adapter + subscription_id` 精确命中，直接关联。
2. 无 ID 时构造本地和外部标准化证据：正式标题、季度、字幕组；双方都有 RSS URL 时在内存中
   追加 exact URL 等值证据。
3. 只有唯一候选且全部要求字段一致时才自动关联，写 `match_reason=EXACT_FIELDS`。
4. 0 个候选：外部对象创建/更新确定性的 `EXTERNAL_ONLY` 记录。
5. 多个候选或证据冲突：不绑定任何本地 Request；创建/保留外部记录并返回固定
   `AMBIGUOUS_EXTERNAL_MATCH` warning，禁止按标题相似度选第一个。

### 8.2 状态映射

| 外部证据 | 可安全修改的本地状态 | 目标状态 |
| --- | --- | --- |
| 精确对象存在且 `deleted=false` | ACTIVE/DISABLED/EXTERNAL_ONLY/UNKNOWN/RECOVERY_REQUIRED/VERIFYING_EXTERNAL | ACTIVE 或 EXTERNAL_ONLY |
| 精确对象存在且 `deleted=true` | ACTIVE/DISABLED/EXTERNAL_ONLY/UNKNOWN/RECOVERY_REQUIRED/VERIFYING_EXTERNAL | DISABLED |
| 已映射 ID 在一次完整、验证通过的 subscription list 中缺失 | ACTIVE/DISABLED/EXTERNAL_ONLY/UNKNOWN | EXTERNAL_DELETED |
| 本地记录处于 SUBMITTING/REVALIDATING | 任意外部证据 | 保持状态，仅更新 mapping/last_synced_at |
| 证据歧义或响应不完整 | 任意 | 不改终态，写固定 warning/count |

状态变化通过一次 TrackingRecord CAS 同时写 revision、审计和安全 mapping。`last_synced_at` 与
mapping 的 `last_verified_at` 只记录最近一次**外部投影发生实质变化**的同步时间；每次调用的实际
检查时间只放在 sync 响应 `checked_at`。因此同一外部快照重复同步不写盘、不 bump revision、
不重复审计；只要持久化字段发生变化，就必须按一次 CAS + 审计处理。

### 8.3 同步幂等

- 同一完整 fixture 连续同步两次，第二次不得新增记录、重复审计或改变业务 revision。
- 外部对象从 enabled/active 变为 deleted，保留原 tracking_id、Request 和全部历史。
- 外部孤立对象后来与本地 Request 获得唯一映射时，必须避免列表长期保留两个权威条目：以
  Request-backed tracking 为权威绑定，外部孤立记录标记为合并别名/不再出现在默认列表；具体采用
  `recovery.merged_into_tracking_id` 安全指针，不删除旧审计文件。
- 单条损坏或 CAS 冲突只计入 `failed`，不影响其他条目落盘。

## 9. API 契约

### 9.1 能力探测

```text
POST /api/v1/autobangumi/capabilities
```

请求：

```json
{
  "ab_config": {
    "base_url": "request-scoped",
    "auth_mode": "password",
    "username": "request-scoped",
    "password": "request-scoped",
    "fallback_enabled": false
  }
}
```

响应只返回 §7.1 DTO。凭据、完整地址和上游响应在所有成功/失败路径都不得回显。

### 9.2 外部同步

```text
POST /api/v1/tracking/sync
```

请求：

```text
ab_config: request-scoped
storage_dir?: relative profile
confirm: true
```

虽然 sync 只读外部，但会更新本地 tracking 投影，因此必须 `confirm=true`。响应：

```text
sync_status: COMPLETE | PARTIAL | FAILED
checked_at
capabilities
summary:
  external_subscriptions
  external_rss
  linked
  external_only_created
  updated
  unchanged
  ambiguous
  failed
warnings[]: code, message
items[]: TrackingSummaryDTO
```

`items` 使用现有 tracking summary 唯一 serializer；响应中不得嵌入上游 Bangumi/RSS dict。
探测、番剧列表或 RSS 列表任一失败时，不得把未知当作空列表进而标记外部删除。

### 9.3 单条外部核验

扩展现有：

```text
POST /api/v1/tracking/items/{tracking_id}/recover
```

- `AUTO | MARK_SUCCEEDED | MARK_FAILED` 请求 shape 与 Stage 29 语义不变，不接受 `ab_config`。
- 新动作 `VERIFY_EXTERNAL` 必须接收 request-scoped `ab_config`，只调用 capability + read API。
- 精确 ID 存在或唯一严格证据命中：记录转 `ACTIVE`/`DISABLED`，operation 可终态化为 SUCCEEDED。
- 无匹配或多匹配不证明“外部未创建”：保持/进入 `RECOVERY_REQUIRED`，`needs_manual=true`。
- 只有上游明确以映射 ID 返回不存在，且完整列表也确认缺失，才允许给出“外部对象不存在”的安全
  结果；Stage 30 默认仍不自动转为可重试失败，避免重复创建。
- 该动作不改变 `AUTO` 的纯本地实现或测试。

## 10. HTTP 与安全错误

新增稳定错误类型建议：

| error_type | HTTP | 场景 |
| --- | --- | --- |
| `ab_management_unsupported` | 409 | adapter/version 未证明管理读取能力 |
| `ab_capability_unknown` | 409 | 能力探测失败或未知，操作 fail closed |
| `tracking_sync_confirmation_required` | 400 | sync 未显式 confirm |
| `tracking_sync_failed` | 502/503/504 | 上游协议/连接/超时；按现有 AB 分类细分优先 |
| `external_mapping_conflict` | 409 | 映射与 tracking 当前 revision/绑定冲突 |

优先复用 Stage 24/26 已有 `ab_auth_failed`、`ab_connection_failed`、`ab_timeout`、
`invalid_ab_response`、`tracking_revision_conflict`。错误 details 只允许 field、reason、
current_revision、capability_state、safe counts 等固定值。

## 11. 模块边界

建议布局：

```text
src/ab_engine/
  models/management.py                 # capability / raw internal / safe projection
  controllers/ab_management_client.py  # 3.1.18 request-scoped read adapter
  controllers/reconcile.py             # 纯映射决策（不得 import storage/web）

src/tracking_engine/
  controllers/external_sync.py         # 纯状态/对账决策
  models/tracking.py                    # external origin/id/mapping v1 扩展

src/apps/migu_orca_web/
  tracking_sync_service.py             # storage + adapter + CAS 编排
  tracking_external_recovery_service.py
  routes_tracking.py / routes_connections.py
  schemas.py / api_contract.py / tracking_serializers.py / openapi_gen.py
```

路由只做 schema 解析和 service 调用；上游 shape 解析只在 adapter；对账规则只在纯 controller；
storage 写入只由 service/repository 编排。不得把 3.1.18 dict 直接传到 API DTO。

## 12. Ralph User Stories

### US-228：冻结 3.1.18 只读管理模型与会话 adapter

建立 capability、内部 Bangumi/RSS、安全投影模型和 management client 协议；实现 password 模式
登录一次、同源 Cookie 复用以及 status/list/detail/RSS 读取。用 recording fake transport 固定
method/path/header/response shape，禁止真实网络和写方法。

### US-229：提供 capability 探测服务与 API

实现版本精确判断、逐项 `CapabilityState`、失败 fail-closed 与
`POST /api/v1/autobangumi/capabilities`。同步严格请求/响应 DTO、HTTP 分类和泄漏测试；API Token
管理能力必须保持 UNKNOWN。

### US-230：冻结 ExternalMapping v1 与外部孤立 TrackingRecord

扩展 TrackingRecord origin、确定性 external tracking ID、严格 external mapping nested schema 和
外部孤立记录构造；兼容读取 Stage 29 记录。测试 ID 稳定、重复 ensure、未知字段拒绝、敏感值清洗
以及 `request_id=null` 不伪造 Request。

### US-231：实现纯对账决策与状态映射

在无 storage/web import 的纯 controller 中实现“ID 优先、严格唯一字段、歧义拒绝、外部孤立、
deleted/disabled 状态”决策。覆盖已有映射、唯一匹配、0 匹配、多匹配、RSS URL 仅内存比较、进行中
状态保护和重复输入确定性。

### US-232：实现 tracking 外部同步协调器

实现 capability → subscription/RSS read → reconcile → 逐条 CAS/ensure 的同步服务；完整、部分失败、
重复同步、映射消失、损坏记录和 CAS 冲突均返回安全计数。任何读取失败都不得把未知列表当空列表，
任何异常都不得删除本地数据。

### US-233：提供 tracking sync API 与安全列表投影

新增 `POST /api/v1/tracking/sync`、strict payload/result DTO、`confirm=true`、安全 warning 和现有
TrackingSummaryDTO 复用；让 `EXTERNAL_ONLY` 在默认列表中按活跃外部追番展示，并更新 detail 的
安全 external summary。补 API contract、排序/筛选和递归敏感字段测试。

### US-234：实现 VERIFY_EXTERNAL 只读恢复

扩展 recover schema/service，保持 AUTO/人工动作完全兼容；`VERIFY_EXTERNAL` 仅通过 management
read adapter 按 ID/唯一证据核验。命中则安全收敛，缺失/歧义保持人工恢复，绝不自动盲目重试、
绝不调用外部写接口。

### US-235：同步 OpenAPI、生成客户端与后端 handoff

已同步 endpoint inventory、OpenAPI registry/JSON、TypeScript generated client、api drift tests、
README/架构/模块 PRD/backlog/future stages，并输出 B-C2 管理写动作 handoff。不得实现正式页面或
任何写管理 endpoint。`uv run migu-orca-openapi --check` 是本阶段契约漂移门禁。

### US-236：完成 Stage 30 回归、同步演练与归档

用脱敏 fixture 演练首次全量同步、重复同步、外部孤立、唯一关联、歧义、外部缺失、部分读取失败、
VERIFY_EXTERNAL 和回退；执行一次最终完整质量门禁，记录准确测试数，归档 prd/progress。确认
Stage 30 没有真实网络、外部写操作、敏感数据或范围外 UI。

## 13. Story 验收重点

所有 story 必须：

1. 只运行与本 story 直接相关的定向测试和必要静态检查。
2. 不在每个 story 重跑完整 pytest、Chromium、前端全套或重复生成无变化的大文件。
3. 新增业务代码必须有定向测试；新增路由必须有 DTO/golden/OpenAPI contract 测试。
4. 任何 fake transport 必须记录 method/path，断言 Stage 30 只出现 login/status/GET read 路径。
5. 每个 story 独立提交并更新 `scripts/ralph/prd.json` 和 `progress.txt`。
6. Python 变更至少通过对应测试文件、`ruff check` 的相关路径和 compileall 的相关包。
7. 最终 story 才执行一次完整门禁并归档。

## 14. 最终质量门禁

```bash
uv run python -m compileall -q src tests
uv run ruff check src tests
uv run pytest -q -m "not browser"
uv run python -m apps.migu_orca_web.openapi_gen
git diff --exit-code -- docs/api/openapi.json
cd frontend && npm ci && npm run api:generate && npm run api:check && npm run typecheck && npm run lint && npm run test:run && npm run build
uv run pytest tests/browser/ -q
git diff --check
```

浏览器套件只在最终 story 运行一次；Stage 30 无 UI 变更，不新增浏览器 story。若完整门禁失败，先运行
最小失败子集定位，禁止无修改重复重跑全套。

## 15. 完成标准

1. US-228～US-236 全部 `passes: true`，每个 story 有独立提交和验证记录。
2. 3.1.18 password adapter 能通过 fake transport 完成一次登录后的 capability、番剧列表/详情和
   RSS 列表读取，且没有任何管理写请求。
3. `POST /api/v1/autobangumi/capabilities` 与 `POST /api/v1/tracking/sync` 契约冻结并进入
   OpenAPI/TS client。
4. 本地记录、外部孤立对象、重复同步、唯一匹配、歧义和外部删除都按确定性规则收敛。
5. `VERIFY_EXTERNAL` 可只读核验未知结果，原 `AUTO` 行为不变。
6. 所有 API、持久化文件、错误、日志与测试产物通过递归敏感字段检查。
7. 文档明确 Stage 31/B-C2 接手 modify、enable/disable、delete-external、RSS 管理与可靠写操作。
8. prd/progress 归档，工作区 `git diff --check` 通过。

## 16. B-C2 Handoff

Stage 30 完成后，后续 B-C2 才能在已证明 capability、external mapping 和只读核验上增加：

- TrackingOperation kinds：MODIFY、SET_ENABLED、DELETE_EXTERNAL、REFRESH_RSS 等。
- 每个写动作的 PREPARED → IN_PROGRESS → 终态、幂等键、expected revision 和结果未知恢复。
- 3.1.18 修改/启停/删除/RSS 动作 adapter；危险历史 GET/DELETE 路由只能封装在固定方法中。
- `delete-external` 永远强制 `file=false`，API schema 不接收 `file`，不提供删除媒体能力。
- 外部写后立即只读回查并更新安全投影；无法确认时进入 RECOVERY_REQUIRED。
- B-C2 完成并经 B-D 契约收尾后，才启动依赖这些动作的正式追番管理页面。

B-C2 的 operation kind 白名单为 `MODIFY`、`SET_ENABLED`、`DELETE_EXTERNAL`、`REFRESH_RSS`；每个动作
必须使用 `confirm=true`、客户端幂等键和 `expected_revision`，先写入 `PREPARED → IN_PROGRESS`，
再调用固定 adapter，随后只读回查并以 CAS 写入结果。结果未知进入 `RECOVERY_REQUIRED`，不得盲目
重试；`DELETE_EXTERNAL` 强制 `file=false`，API schema 不接受 `file`，任何写动作都不得删除本地
Request、TrackingRecord、审计、下载任务或媒体。
