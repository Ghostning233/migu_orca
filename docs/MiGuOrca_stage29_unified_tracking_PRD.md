# MiGuOrca Stage 29 PRD：统一追番记录与可靠提交恢复

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 项目名称 | MiGuOrca |
| 文档名称 | Stage 29 PRD：统一追番记录与可靠提交恢复 |
| 文档类型 | 执行 PRD / 前端体验重构 B-B |
| 当前状态 | B-B 已完成（US-219～US-227 全部 passes，2026-09-08 归档；B-C handoff 见 §20 与 future_stages「Stage 29 handoff」） |
| 创建日期 | 2026-09-08 |
| Backlog | BL-025（B-B） |
| 优先级 | P0 |
| 前置条件 | Stage 26～28 已完成并合入 `main`；B-B 四轮产品与技术决策已确认 |
| 候选分支 | `ralph/stage29-unified-tracking` |
| 候选 Ralph stories | US-219～US-227 |

## 2. 背景

Stage 28 已提供带 revision 的服务端草案、可靠保存、持久化 save-confirm 幂等记录、单番/批量
save-confirm、1～36 部边界和 Request safe-info。保存确认成功后只返回
`request_id + status=ACCEPTED + next_action=OPEN_TRACKING`，尚未创建 tracking record。

当前外部提交仍存在两套入口和状态源：单番 Request 直接提交，以及按 `batch_id` 持久化的批量
queue。它们不能形成统一的“追番管理”列表，也不能让新前端只依赖一个状态模型处理待提交、提交中、
失败、结果未知和人工恢复。现有 queue 已具备“外部调用前先持久化 SUBMITTING”和本地结果恢复
经验，但它仍是批量专用结构，不能成为长期统一模型。

Stage 29 交付 B-B：建立本地 TrackingRecord 和 TrackingOperation，以 Request 为方案内容权威、
TrackingRecord 为新提交流程权威、旧 queue 为一个发布周期内的兼容投影；把新旧提交入口收敛到
同一个可靠提交服务。Stage 29 不实现 Auto Bangumi 全量管理和外部同步，它们属于 B-C。

## 3. 用户结果

1. 单番和批量确认后的方案进入同一个追番记录列表，不再依赖用户理解 batch 或 request ID。
2. 每个方案最多只有一条追番记录，重放、重启、迁移和兼容入口不会重复创建。
3. 用户能区分待提交、处理中、正在追番和需要处理，不需要理解内部英文状态。
4. 提交前发现方案变化时要求确认最新方案，不会静默提交旧内容。
5. 明确失败可以安全重试；结果未知必须先恢复，不能盲目重复创建外部订阅。
6. 历史单番、批量 queue 和已保存 AB result 能纯本地、幂等地回填到统一记录。

## 4. 目标

1. 建立严格、版本化、原子写入的 TrackingRecord repository。
2. 建立独立 TrackingOperation repository，提供跨重启提交幂等和结果恢复证据。
3. 使用确定性 opaque `tracking_id`，保证同一 Request 只能产生一条记录。
4. 从 ACCEPTED Request、旧 batch queue 和已保存 AB result 幂等迁移历史状态。
5. save-confirm、accept、旧单番提交和旧批量提交全部接入统一 tracking service。
6. 提供 tracking 列表、安全详情、纯本地复核、提交、重试和恢复 API。
7. 对 TrackingRecord 使用 revision compare-and-swap，阻止多页面乱序动作。
8. 对外部调用严格执行“先持久化处理中，再调用，再持久化结果”。
9. 同步严格 DTO、OpenAPI、endpoint inventory、生成 TypeScript client、测试和文档。

## 5. 非目标

1. 不实现 Auto Bangumi 订阅/RSS 的全量列表、详情、修改、启停、删除或刷新。
2. 不实现 Auto Bangumi 多版本 capability adapter 或外部全量同步；它们属于 B-C。
3. 不创建 `EXTERNAL_ONLY` 记录；仅冻结兼容状态，留给 B-C 使用。
4. 不开发新的正式前端页面、导航或视觉组件；只允许生成客户端和保持旧页面兼容所需的最小改动。
5. 不删除旧 Request submit、batch queue/submit/retry/recover API，至少保留一个完整发布周期。
6. 不引入数据库、后台 worker、消息队列、多用户账号或公网远程管理。
7. 不绕过 Auto Bangumi 操作 qBittorrent，不创建下载任务，不删除任何媒体文件。
8. 不实现当前已更新集数；继续使用 `updated_episode=null` 与 `NOT_IMPLEMENTED`。
9. 自动化不得访问真实 MiKan、Auto Bangumi 或 qBittorrent。

## 6. 核心决策

| 编号 | 决策 | 说明 |
| --- | --- | --- |
| D29-01 | Request 与 TrackingRecord 分工 | Request 是本地方案内容权威；TrackingRecord 是新提交流程和用户可见运行状态权威。 |
| D29-02 | 一个 Request 最多一条 tracking | 不按标题、季度或字幕组去重；相同 request_id 的 ensure/迁移必须收敛到同一 tracking_id。 |
| D29-03 | tracking ID 确定性且 opaque | 使用版本命名空间和 request_id 摘要生成；不得包含标题、外部凭据或路径。 |
| D29-04 | operation 独立存储 | 不扩展 Stage 28 仅服务 SAVE_CONFIRM 的幂等 repository；提交操作使用独立 repository。 |
| D29-05 | 状态变化与审计原子写入 | 状态审计内嵌 TrackingRecord，在同一次原子替换中落盘。 |
| D29-06 | revalidate 纯本地 | 不携带 AB 凭据、不访问外部系统；submit 仍在同一用例中再次复核。 |
| D29-07 | 结果未知禁止重试 | 只有能证明请求未送达或明确失败时才能 retry；未知结果必须 recover。 |
| D29-08 | 已落盘业务结果用 200 | `SUBMIT_FAILED`/`VERIFYING_EXTERNAL`/`RECOVERY_REQUIRED` 是业务结果，不伪装成传输错误。 |
| D29-09 | TrackingRecord 为新权威 | 旧 queue 是兼容投影；所有新旧外部提交入口必须调用同一 tracking submission service。 |
| D29-10 | 历史迁移纯本地且可重入 | 首次 tracking 访问触发；PARTIAL 后重试，COMPLETE 后不再全量扫描。 |
| D29-11 | Handoff 只做兼容扩展 | 保留 Stage 28 的 `status=ACCEPTED`，新增 tracking_id/tracking_status/tracking_ready。 |
| D29-12 | B-B 不做外部管理 | recover AUTO 只检查本地证据；外部核验、同步与管理留给 B-C。 |

## 7. 领域模型

### 7.1 用户概念

| 用户区域 | 后端实体 | 含义 |
| --- | --- | --- |
| 我的方案 | Request | 用户保存并确认的本地订阅方案。 |
| 追番管理 | TrackingRecord | 方案从待提交到正在追番、失败或恢复的生命周期。 |

### 7.2 TrackingRecord

存储位置：

```text
<storage>/tracking/<tracking_id>.json
```

最小白名单结构：

```json
{
  "schema_version": 1,
  "tracking_id": "trk_xxx",
  "request_id": "public-request-id",
  "batch_id": null,
  "origin": "SAVE_CONFIRM",
  "status": "PENDING_SUBMIT",
  "revision": 1,
  "request_fingerprint": "sha256",
  "plan_summary": {
    "title": "番剧标题",
    "season": 2,
    "subtitle_group": "字幕组",
    "poster_path": "/api/v1/mikan/posters/opaque-key"
  },
  "external_mapping": null,
  "current_operation_id": null,
  "last_error": null,
  "recovery": null,
  "audit_events": [],
  "created_at": "RFC3339",
  "updated_at": "RFC3339",
  "last_synced_at": null
}
```

约束：

- `schema_version` 固定为 1；未知版本 fail closed，不猜测字段。
- `request_id` 在 B-B 必填；可空只为 B-C 的 `EXTERNAL_ONLY` 冻结契约。
- `origin` 至少支持 `SAVE_CONFIRM | LEGACY_ACCEPT | MIGRATED_QUEUE | MIGRATED_AB_RESULT`。
- `plan_summary` 只保存 safe-info 允许的显示字段；海报只能是同源 opaque 代理路径。
- `request_fingerprint` 是允许业务字段规范化后的不可逆摘要，不保存完整 Request。
- 每次状态变化、确认最新方案或人工恢复都令 `revision + 1`。
- 使用临时文件和 `os.replace` 原子写；repository 使用进程内按键锁。
- 多 worker 共享 storage 仍不是 Stage 29 支持范围，文档必须保留该限制。

### 7.3 TrackingOperation

存储位置：

```text
<storage>/tracking_operations/<operation_id>.json
```

白名单结构：

```json
{
  "schema_version": 1,
  "operation_id": "op_xxx",
  "tracking_id": "trk_xxx",
  "operation": "SUBMIT",
  "idempotency_key": "opaque-client-key",
  "expected_revision": 5,
  "request_fingerprint": "sha256",
  "state": "IN_PROGRESS",
  "attempt": 1,
  "external_result_id": null,
  "error_type": null,
  "created_at": "RFC3339",
  "updated_at": "RFC3339",
  "completed_at": null
}
```

规则：

- operation 只允许 `SUBMIT`；后续 B-C 动作另行扩展。
- operation state 固定为
  `PREPARED | IN_PROGRESS | SUCCEEDED | FAILED | OUTCOME_UNKNOWN | RECOVERY_REQUIRED`。
- `PREPARED` 表示幂等绑定已落盘但尚未调用外部；只有切换为 `IN_PROGRESS` 后才允许执行外部调用。
- 同一幂等键绑定 tracking_id、operation、expected_revision 和 request fingerprint。
- 同键同绑定重放相同公开结果；任一绑定不同返回 409 `tracking_idempotency_conflict`。
- 用户对明确失败点击“重试”创建新 operation；同一次网络重放复用原 operation。
- TrackingRecord/兼容 queue 的调用前写入失败时，operation 终止为 `FAILED`，证明外部未调用；
  外部调用已经开始但最终状态未能可靠落盘时必须保持 `IN_PROGRESS` 或转为 `OUTCOME_UNKNOWN`，
  不能写成可直接重试的 `FAILED`。
- operation 永不保存请求体、AB 配置、上游响应、标题、URL、magnet 或路径。

### 7.4 Tracking ID

- 有 Request 的记录使用版本化命名空间与 `request_id` 生成确定性摘要，例如 `trk_<digest>`。
- 摘要算法与命名空间必须被测试固定；升级算法不能静默改变已有 ID。
- 相同 Request 在重启、并发 ensure、终态重放和迁移时必须得到同一 ID。
- B-C 将来为外部孤立对象使用 adapter + opaque external ID 的独立命名空间。
- 外部记录以后关联本地 Request 时保留原 tracking ID，避免页面地址变化。

## 8. 状态与用户展示

### 8.1 后端状态

```text
PENDING_SUBMIT
REVALIDATING
NEEDS_RECONFIRM
SUBMITTING
VERIFYING_EXTERNAL
ACTIVE
SUBMIT_FAILED
RECOVERY_REQUIRED
UNKNOWN
DISABLED          # B-C 预留
EXTERNAL_DELETED  # B-C 预留
EXTERNAL_ONLY     # B-C 预留
```

B-B 只主动产生前九种状态。

### 8.2 用户状态组

| status_group | 用户文案 | 后端状态 |
| --- | --- | --- |
| `PENDING` | 待处理 | PENDING_SUBMIT、NEEDS_RECONFIRM |
| `PROCESSING` | 处理中 | REVALIDATING、SUBMITTING、VERIFYING_EXTERNAL |
| `ACTIVE` | 正在追番 | ACTIVE |
| `ATTENTION` | 需要处理 | SUBMIT_FAILED、RECOVERY_REQUIRED、UNKNOWN |
| `INACTIVE` | 已停用/已删除 | DISABLED、EXTERNAL_DELETED（B-C） |

DTO 必须返回稳定 `status`、中文 `status_label`、`status_group` 和服务端计算的
`available_actions`，前端不得自行推断动作权限。

### 8.3 状态迁移

```text
创建/回填 -> PENDING_SUBMIT

PENDING_SUBMIT -> REVALIDATING
REVALIDATING -> SUBMITTING | NEEDS_RECONFIRM
NEEDS_RECONFIRM -> REVALIDATING

SUBMITTING -> ACTIVE
SUBMITTING -> SUBMIT_FAILED
SUBMITTING -> VERIFYING_EXTERNAL
SUBMITTING -> RECOVERY_REQUIRED

SUBMIT_FAILED -> REVALIDATING
VERIFYING_EXTERNAL -> ACTIVE | SUBMIT_FAILED | RECOVERY_REQUIRED
RECOVERY_REQUIRED -> ACTIVE | SUBMIT_FAILED
```

安全规则：

- 外部调用前持久化失败时不得访问 Auto Bangumi。
- 能证明请求未送达或明确失败时才进入 `SUBMIT_FAILED`。
- 请求可能已送达但结果未知时进入 `VERIFYING_EXTERNAL`。
- 外部结果成功但本地关键结果落盘失败时进入 `RECOVERY_REQUIRED`。
- `VERIFYING_EXTERNAL`、`RECOVERY_REQUIRED` 不能直接 retry。
- Request 缺失、不是 ACCEPTED 或 fingerprint 改变时进入 `NEEDS_RECONFIRM`。

## 9. 审计事件

审计事件内嵌 TrackingRecord，与状态变化原子写入。只记录状态变化、迁移和人工动作，不记录列表、
详情读取、无变化复核或轮询。Stage 29 不截断事件；详情默认只序列化最近 20 条。

```json
{
  "event_id": "evt_xxx",
  "action": "SUBMIT_SUCCEEDED",
  "actor": "SYSTEM",
  "from_status": "SUBMITTING",
  "to_status": "ACTIVE",
  "tracking_revision": 6,
  "operation_id": "op_xxx",
  "reason_code": null,
  "safe_message": "已成功提交到 AutoBangumi",
  "created_at": "RFC3339"
}
```

`actor` 只允许 `SYSTEM | USER | MIGRATION`。事件 action 至少支持：

```text
TRACKING_CREATED
TRACKING_BACKFILLED
PLAN_CHANGE_DETECTED
REVALIDATION_PASSED
REVALIDATION_FAILED
SUBMIT_STARTED
SUBMIT_SUCCEEDED
SUBMIT_FAILED
SUBMIT_OUTCOME_UNKNOWN
RESULT_PERSIST_FAILED
RECOVERY_AUTO_SUCCEEDED
RECOVERY_AUTO_FAILED
RECOVERY_NEEDS_MANUAL
RECOVERY_MANUAL_SUCCEEDED
RECOVERY_MANUAL_FAILED
COMPAT_QUEUE_UPDATED
COMPAT_QUEUE_UPDATE_FAILED
```

事件不得保存 AB 配置、endpoint、凭据、请求/响应体、traceback、完整 URL、magnet、绝对路径或
上游原始错误文案。

## 10. 历史迁移

### 10.1 Manifest

```text
<storage>/tracking_migrations/schema-v1.json
```

只保存版本、`COMPLETE | PARTIAL`、开始/完成时间和 created/existing/recovery_required/unreadable
计数。任意 tracking API 首次执行前运行 migration coordinator：

- 只扫描本地 Request、batch queue 和 AB result，绝不访问外部系统。
- 每个 Request 独立迁移；单条损坏不回滚健康记录。
- 有未处理损坏项时写 `PARTIAL`，后续访问继续重试。
- `COMPLETE` 后不再全量扫描；新数据靠所有 accept/save-confirm 入口实时 ensure。
- 重复运行不得新增记录、改变 tracking ID/revision 或重复审计事件。
- API 只返回安全计数和固定 warning，不返回文件名、路径、原始 JSON 或解析错误内容。

### 10.2 证据优先级与映射

```text
已有 TrackingRecord > 明确成功的 AB result > batch queue > ACCEPTED Request > 其他 Request 状态
```

| 历史证据 | 迁移状态 |
| --- | --- |
| ACCEPTED Request，无 queue/AB result | PENDING_SUBMIT |
| queue READY_TO_SUBMIT | PENDING_SUBMIT |
| queue SUBMITTING | VERIFYING_EXTERNAL |
| queue FAILED/RETRYABLE | SUBMIT_FAILED |
| queue RESULT_PERSIST_FAILED | RECOVERY_REQUIRED |
| queue SUCCEEDED 且 AB result 明确成功 | ACTIVE |
| AB result success=true 且 Request 为 ACCEPTED | ACTIVE |
| AB result success=false 且无矛盾证据 | SUBMIT_FAILED |
| queue 成功但 AB result 缺失、损坏或失败 | RECOVERY_REQUIRED |
| AB result 成功但 Request 缺失、取消或状态异常 | RECOVERY_REQUIRED |
| 多个 queue 对同一 Request 状态冲突 | RECOVERY_REQUIRED |
| PENDING_CONFIRM/CANCELLED 且无提交证据 | 不创建 |
| 非 ACCEPTED 但存在提交证据 | RECOVERY_REQUIRED |

明确 AB 成功证据优先阻止重复提交。迁移只读取 `success`、安全 external ID 和固定 error type，
不复制旧结果对象。标题、季度和 queue 文案不能作为关联或去重证据。同一 Request 出现在多个 queue
时只创建一条记录；一致来源保留最早 batch_id，其余来源写安全审计，冲突进入恢复。

## 11. API 契约

### 11.1 端点

```text
GET  /api/v1/tracking/items
GET  /api/v1/tracking/items/{tracking_id}
POST /api/v1/tracking/items/{tracking_id}/revalidate
POST /api/v1/tracking/items/{tracking_id}/submit
POST /api/v1/tracking/items/{tracking_id}/retry
POST /api/v1/tracking/items/{tracking_id}/recover
```

`/tracking/sync`、外部 modify/set-enabled/refresh/delete 属于 B-C，不在 Stage 29 注册。

### 11.2 列表

查询参数：安全 `storage_dir`、可选 `q`、`status_group`、`sort`。`sort` 只允许更新时间、标题和状态
的固定枚举。B-B 不分页，目标规模为本地几十到数百条。

结果：

```json
{
  "items": [
    {
      "tracking_id": "trk_xxx",
      "request_id": "request-id",
      "title": "番剧",
      "season": 2,
      "subtitle_group": "字幕组",
      "poster_path": "/api/v1/mikan/posters/opaque-key",
      "status": "PENDING_SUBMIT",
      "status_label": "待提交",
      "status_group": "PENDING",
      "available_actions": [],
      "valid_resource_count": 12,
      "updated_episode": null,
      "updated_episode_status": "NOT_IMPLEMENTED",
      "total_episodes": null,
      "revision": 3,
      "updated_at": "RFC3339"
    }
  ],
  "summary": {
    "total": 12,
    "pending": 5,
    "processing": 1,
    "active": 5,
    "needs_attention": 1,
    "unreadable": 0
  },
  "warnings": []
}
```

单条 tracking JSON 损坏不阻塞健康列表，也不得自动删除。响应只增加固定 warning 和 unreadable
计数，不暴露文件信息。

### 11.3 详情

详情在 summary 之外只返回：Request safe-info、当前 operation 安全摘要、revalidation issues、
外部安全映射摘要和最近 20 条审计事件。不得返回完整 Request、外部原始 JSON、完整 URL、凭据、
magnet 或绝对路径。

### 11.4 Available action

服务端返回严格对象，不返回不可执行的 disabled 假动作：

```json
{
  "code": "SUBMIT",
  "label": "提交追番",
  "style": "PRIMARY",
  "requires_confirmation": true
}
```

`style` 只允许 `PRIMARY | SECONDARY | DANGER`；code 候选为：

```text
OPEN
VIEW_PLAN
REVALIDATE
SUBMIT
RETRY
RECOVER_AUTO
MARK_SUCCEEDED
MARK_FAILED
```

### 11.5 Revalidate

请求只含 `expected_revision` 和可选 storage profile。它是纯本地操作，不接收 `ab_config`、不探测
连接或 capability。复核至少检查 Request 存在且 ACCEPTED、fingerprint、标题/季度确认、MiKan
合集、字幕组、有效资源、外部映射、未完成 operation 和当前 tracking 状态。

业务复核失败仍返回 HTTP 200：

```json
{
  "tracking_id": "trk_xxx",
  "ready": false,
  "checked_revision": 5,
  "next_revision": 6,
  "checked_at": "RFC3339",
  "next_status": "NEEDS_RECONFIRM",
  "issues": [
    {
      "code": "REQUEST_CHANGED",
      "field": null,
      "message": "订阅方案已发生修改，请确认最新方案",
      "recovery_action": "SUBMIT"
    }
  ],
  "tracking": {}
}
```

issue code 固定为：

```text
REQUEST_MISSING
REQUEST_NOT_ACCEPTED
REQUEST_CHANGED
TITLE_MISSING
SEASON_REVIEW_REQUIRED
MIKAN_SELECTION_MISSING
SUBTITLE_GROUP_MISSING
NO_VALID_RESOURCES
EXTERNAL_ALREADY_LINKED
OPERATION_IN_PROGRESS
TRACKING_STATE_INVALID
```

### 11.6 Submit

```json
{
  "expected_revision": 5,
  "idempotency_key": "opaque-client-operation-id",
  "confirm": true,
  "ab_config": {}
}
```

- `confirm` 必须严格为 true，AB 配置只在本次请求内存中存在。
- submit 必须重新读取当前 Request 并执行完整本地复核。
- Request fingerprint 已变化但仍为 ACCEPTED 时，`confirm=true` 表示用户确认提交当前最新方案；
  服务端更新 fingerprint、revision 和审计后继续同一次提交，不接收浏览器计算的 fingerprint。
- 本地复核不通过时不访问 Auto Bangumi。
- 外部调用前先持久化 TrackingRecord `SUBMITTING` 和 operation `IN_PROGRESS`。
- 已持久化的业务结果返回 HTTP 200，outcome 为
  `ACTIVE | SUBMIT_FAILED | VERIFYING_EXTERNAL | RECOVERY_REQUIRED | NEEDS_RECONFIRM`。

### 11.7 Retry

请求 shape 与 submit 相同，但只允许 `SUBMIT_FAILED`。用户明确点击一次重试创建新 operation；同一
网络请求重放复用原 key。retry 重新读取 Request 和复核，不使用旧 payload 快照。
`VERIFYING_EXTERNAL`/`RECOVERY_REQUIRED` 必须先 recover，不能 retry。

### 11.8 Recover

```json
{
  "expected_revision": 9,
  "action": "AUTO",
  "confirm": false
}
```

action 只允许 `AUTO | MARK_SUCCEEDED | MARK_FAILED`：

- AUTO 只读取本地 operation、Request 脱敏 AB result 和旧 queue 证据，不访问外部系统。
- 无明确证据时保持 RECOVERY_REQUIRED。
- 两个人工动作必须 `confirm=true` 并写 USER 审计。
- MARK_SUCCEEDED 不允许浏览器提交 external ID、URL 或原始结果。
- MARK_FAILED 后再次提交时必须重新显式确认重复创建风险。
- B-C 将来新增独立 `VERIFY_EXTERNAL`，不改变 AUTO 的纯本地语义。

## 12. Handoff 兼容扩展

保留 Stage 28 的 Request `status=ACCEPTED`：

```json
{
  "request_id": "request-id",
  "status": "ACCEPTED",
  "tracking_id": "trk_xxx",
  "tracking_status": "PENDING_SUBMIT",
  "tracking_ready": true,
  "next_action": "OPEN_TRACKING",
  "safe_message": null
}
```

Request 已确认但 tracking 写入失败时不回滚 Request，也不伪造 tracking 状态：

```json
{
  "request_id": "request-id",
  "status": "ACCEPTED",
  "tracking_id": "trk_xxx",
  "tracking_status": null,
  "tracking_ready": false,
  "next_action": "OPEN_TRACKING",
  "safe_message": "方案已保存，追番列表将在打开时自动恢复"
}
```

打开 tracking 列表/详情、save-confirm 终态重放和所有 accept 入口都再次 ensure。批量逐条返回
tracking_id/status/ready；一个 tracking 写入失败不回滚其他已确认条目。

## 13. 统一提交与旧 Queue 兼容

### 13.1 权威关系

```text
Request：方案内容权威
TrackingRecord：新流程提交状态权威
TrackingOperation：外部写入幂等与恢复证据
AB result：外部结果的本地安全证据
旧 batch queue：一个发布周期内的兼容投影
```

旧单番 submit-ab 与 batch submit/retry/recover 必须调用新的统一 tracking submission service，
共享 ensure、revalidate、operation、SUBMITTING 预写、结果分类和恢复，不得在 route 层复制逻辑。

### 13.2 外部调用前

1. 加载最新 Request/TrackingRecord，校验 expected revision 和 operation。
2. 建立 operation=PREPARED，绑定本次幂等键和 fingerprint。
3. 写 TrackingRecord=SUBMITTING；如果存在旧 queue 条目，同步 queue=SUBMITTING。
4. 把 operation 切换为 IN_PROGRESS，作为“外部调用可能发生”的持久化边界。
5. 只有以上安全持久化完成后才访问 Auto Bangumi。

调用前 queue 同步失败时不得访问外部；TrackingRecord 进入 SUBMIT_FAILED，记录
COMPAT_QUEUE_UPDATE_FAILED，可安全重试。

### 13.3 外部调用后

优先持久化 AB 安全结果，再写 TrackingRecord 最终状态，最后更新 queue 兼容投影。

- 外部成功但 queue 最终写失败：TrackingRecord 保持 ACTIVE；queue 通常停在 SUBMITTING，记录
  非阻断兼容 warning，后续访问尝试修复。
- 外部调用后 TrackingRecord 最终写失败：绝不恢复 PENDING_SUBMIT；operation 保持 IN_PROGRESS
  或未知，下次根据 AB result/queue 恢复，无证据则 RECOVERY_REQUIRED。
- 任一结果未知状态都不能自动再次访问外部。

## 14. 错误与 HTTP 语义

| error_type | HTTP | 安全 details |
| --- | ---: | --- |
| `tracking_not_found` | 404 | `field=tracking_id` |
| `tracking_revision_conflict` | 409 | `field=expected_revision`、`current_revision` |
| `tracking_state_conflict` | 409 | `current_status`、`available_actions` |
| `tracking_operation_in_progress` | 409 | `current_status` |
| `tracking_idempotency_conflict` | 409 | `field=idempotency_key`、固定 reason |
| `tracking_confirmation_required` | 400 | `field=confirm` |
| `tracking_storage_error` | 500 | 固定中文文案，不含路径 |
| `tracking_migration_error` | 500 | 固定中文文案，不含文件名/原文 |

继续复用 `data_validation_errors`、`invalid_storage_dir`、合法 AB config 校验和现有安全 storage
错误。NEEDS_RECONFIRM、SUBMIT_FAILED、VERIFYING_EXTERNAL、RECOVERY_REQUIRED 是已落盘业务结果，
使用 HTTP 200 result。路由或 serializer 不得返回上游原始错误。

## 15. 安全与隐私

1. TrackingRecord、operation、migration manifest 和 API DTO 全部默认拒绝、严格白名单。
2. `ab_config` 只存在于单次 submit/retry 请求内存；成功、失败、取消和异常后立即释放。
3. 不记录请求 body，不把凭据放入错误、history、日志、URL、浏览器 storage、截图或 trace。
4. 公开海报仅允许同源 `/api/v1/mikan/posters/<opaque-key>`，不返回原始图片 URL。
5. 所有 title/subtitle/error/message 进入 tracking 前复用严格 safe serializer。
6. migration 和 recover 不能复制旧 AB response 或 queue 原始文本。
7. 人工恢复不接收 external ID、URL、凭据或原始响应。
8. 损坏文件不自动删除、覆盖或回显；API 只返回安全计数和固定文案。

## 16. Ralph User Stories

### US-219：建立 TrackingRecord 模型、确定性 ID 与 repository

- 新增 schema v1、严格白名单、状态/状态组/审计模型。
- 新增确定性 tracking ID 和原子 repository；支持 load/list/CAS/ensure。
- storage layout 增加 tracking/tracking_operations/tracking_migrations。
- 测试确定性、并发 ensure、revision、损坏 JSON、路径逃逸和敏感字段缺失。

### US-220：建立 TrackingOperation 与提交幂等状态机

- 新增 operation repository、绑定规则、状态和按键并发锁。
- 同键同绑定重放；异 tracking/operation/revision/fingerprint 冲突。
- 进程重启后可读取 IN_PROGRESS 和终态结果，不保存业务 payload 或凭据。

### US-221：实现历史数据幂等迁移

- 实现 manifest、PARTIAL/COMPLETE 和逐 Request 迁移。
- 覆盖所有 Request/queue/AB result 映射、冲突和重复来源。
- 证明不访问外部、不重复记录、不改变 tracking ID，并安全报告损坏项。

### US-222：接入 accept/save-confirm handoff

- 单番 accept、单番 save-confirm、批量 save-confirm 和终态重放调用 ensure。
- handoff 向后兼容增加 tracking_id/status/ready/safe_message。
- tracking 写失败不回滚已确认 Request；后续访问可补偿。

### US-223：提供 tracking 列表、详情与严格安全 DTO

- 新增两个 GET API、筛选/排序/summary/warnings、available action 对象。
- 详情复用 Request safe-info，只返回 operation/映射/最近 20 条审计的安全摘要。
- 单条损坏不阻塞健康列表，DTO/OpenAPI/TS client 同步。

### US-224：实现纯本地 revalidate 与方案变化确认

- 新增 revision-aware revalidate；不接收凭据、不访问外部。
- 覆盖 Request 状态、fingerprint、季度、合集、字幕组、资源、映射和 operation。
- submit confirm 只确认服务端重新读取的最新 Request，不信任浏览器 fingerprint。

### US-225：实现统一 submit 与结果分类

- 新增 tracking submit；外部调用前持久化 SUBMITTING/IN_PROGRESS。
- 接入现有 Auto Bangumi create seam，分类成功、明确失败、未知和结果落盘失败。
- 并发/重放只允许一次外部调用，AB 配置 request-scoped。

### US-226：实现 retry/recover 与旧入口兼容

- retry 只允许 SUBMIT_FAILED；未知结果必须 recover。
- AUTO 本地恢复、人工成功/失败、确认和审计完整。
- 旧单番/批量 submit/retry/recover 复用统一 service；queue 双写失败遵守 §13。

### US-227：完成契约回归、迁移演练与 B-C handoff

- 同步 OpenAPI、endpoint inventory、生成客户端、主文档和模块文档。
- 使用脱敏 fixture 演练全量/部分迁移、崩溃窗口、旧入口兼容和回退。
- 运行完整非浏览器、前端和真实 Chromium 回归。
- 输出 B-C capability/外部同步/管理 adapter handoff；Stage 29 不提前实现 B-C。

## 17. 测试矩阵与成本控制

### 17.1 必测矩阵

- Repository：白名单、原子写、确定性 ID、CAS、并发 ensure、损坏 JSON、路径逃逸、敏感字段。
- Migration：全部 queue 状态、AB 成败/缺失/损坏、Request 异常、冲突、多 queue、PARTIAL 重试、
  COMPLETE 不重跑、纯本地。
- Revalidate：Request 缺失/状态/fingerprint、季度、合集、字幕组、资源、外部映射、operation、revision。
- Submit：成功、调用前失败、明确外部失败、结果未知、结果/record 落盘失败、幂等重放、并发单调用。
- Retry/Recover：允许状态、禁止盲重试、本地自动证据、人工确认、审计和无原始输入。
- Compatibility：所有旧入口更新 tracking；调用前 queue 失败不访问外部；调用后 queue 失败不覆盖成功。
- Contract/Security：严格 DTO、OpenAPI/TS 无漂移，API/JSON/日志/测试产物无敏感值。

### 17.2 分层门禁

为避免每个 Story 重复执行整仓门禁造成异常成本：

- US-219～US-226 每次只运行受影响的定向测试、ruff、compileall 和 `git diff --check`。
- 只有修改 API contract 的 Story 执行 OpenAPI 生成/检查和相关前端生成客户端测试。
- 纯后端 Story 不重复执行完整前端测试或浏览器套件。
- US-227 只执行一次完整非浏览器、前端 typecheck/lint/unit/build、OpenAPI drift 和 Chromium。
- 测试不得访问真实外部服务；失败时先定位失败集合，不无界重复全量运行。
- 每个 Story 在 progress 中记录实际命令、数量和耗时，禁止复制上一 Story 的测试数字。

## 18. 依赖与实施顺序

```text
US-219 -> US-220
US-219/220 -> US-221
US-219/220 -> US-222 -> US-223 -> US-224 -> US-225 -> US-226 -> US-227
```

US-221 与 US-222 在基础 repository/operation 冻结后可由不同 Agent 独立实现，但 Ralph 默认一次
只处理一个 Story。任何实现 Agent 不得把 B-C 外部管理或新页面视觉顺带加入 Stage 29。

## 19. 完成标准

1. US-219～US-227 全部有独立提交、定向验收证据和 `passes=true`。
2. 同一 Request 在新建、迁移、终态重放和旧入口中始终对应同一 tracking ID。
3. 单番和批量保存确认正常返回 tracking handoff，写入失败不丢已确认 Request。
4. 新旧提交入口共享一个 submission service，任何崩溃窗口都不会回到可盲目重复创建的状态。
5. 结果未知必须 recover；retry 只处理明确失败。
6. 列表/详情/revalidate/submit/retry/recover 的 DTO、OpenAPI、TS client 和错误语义一致。
7. 迁移重复执行无副作用，损坏单条不阻塞健康记录且不泄漏原始内容。
8. 完整质量门禁通过，自动化未访问真实外部系统。
9. 旧接口仍可用；其删除只能由后续独立 PRD 决定。
10. 文档明确 B-C 接手 capability、外部同步、EXTERNAL_ONLY 和 Auto Bangumi 管理动作。

## 20. B-C Handoff

Stage 29 交付后，B-C 只能基于 TrackingRecord 和已冻结 mapping 扩展：

- Auto Bangumi 3.1.18 capability 探测；未知版本写操作 fail closed。
- 外部 subscription/RSS 的列表、详情、修改、启停、删除和刷新。
- `POST /api/v1/tracking/sync` 与 `EXTERNAL_ONLY`。
- 优先按已保存外部 ID 对账；无 ID 时使用 adapter 明确定义的多字段证据，歧义进入恢复。
- recover 新增独立外部核验动作，不改变 Stage 29 AUTO 的纯本地语义。
- 外部删除只删除外部对象，本地 Request、TrackingRecord、审计和媒体全部保留。

在 B-C PRD 与 OpenAPI 冻结前，不启动依赖外部管理能力的“追番管理”正式页面实现。

## 21. 完成记录（2026-09-08）

Stage 29 已完成并合入 `ralph/stage29-unified-tracking`，US-219～US-227 全部 `passes: true`，
每个 story 有独立提交与验证记录：

- US-219 建立 TrackingRecord 模型、确定性 ID 与 repository（`tracking_engine/models/tracking.py`
  schema v1 严格白名单 + `trk_` 确定性 opaque ID + 内嵌审计；`tracking_repository` 原子
  ensure/load/CAS/list；storage layout 增加 tracking/tracking_operations/tracking_migrations）。
- US-220 建立 TrackingOperation 与提交幂等状态机（独立 operation repository；同键同绑定重放、
  异绑定 409 `tracking_idempotency_conflict`；PREPARED/IN_PROGRESS 终态；永不保存业务 payload）。
- US-221 实现历史数据幂等迁移（manifest COMPLETE/PARTIAL + 逐 Request 分类；纯本地、重复运行
  无副作用、单条损坏不阻塞健康记录且不回显原文）。
- US-222 接入 accept/save-confirm handoff（ensure 收敛同一 tracking_id；handoff 兼容扩展
  tracking_id/status/ready/safe_message；tracking 写失败不回滚已确认 Request）。
- US-223 提供 tracking 列表、详情与严格安全 DTO（两条 GET；summary 计数 + 服务端
  available_actions；详情复用 Request safe-info 唯一 producer + 最近 20 条审计）。
- US-224 实现纯本地 revalidate 与方案变化确认（固定 §11.5 issue code；业务失败 HTTP 200 +
  ready=false；仅 fingerprint 变化且 confirm=true 时采纳新方案继续同一次提交）。
- US-225 实现统一 submit 与结果分类（外部调用前持久化 SUBMITTING/IN_PROGRESS；结果分类
  ACTIVE/SUBMIT_FAILED/VERIFYING_EXTERNAL/RECOVERY_REQUIRED/NEEDS_RECONFIRM；同键终态重放）。
- US-226 实现 retry/recover 与旧入口兼容（retry 只允许 SUBMIT_FAILED；AUTO 纯本地恢复；
  人工动作 confirm=true + USER 审计；旧单番/批量入口共享统一 submission/recovery service；
  queue 双写 best-effort 且不覆盖已落盘成功）。
- US-227 完成契约回归、迁移演练与 B-C handoff（同步 README/主 PRD/架构/backlog/future stages/
  M01/M09/M10/M11/M12/M13/api 文档；脱敏 fixture 演练全量/部分迁移、崩溃窗口、旧入口兼容与
  回退；完整非浏览器 + 前端 + OpenAPI drift + 真实 Chromium 回归；输出 B-C handoff；
  归档 prd/progress）。

实际测试数量（最终交付）：非浏览器 1496 passed（含新增 7 例 US-227 迁移演练）、真实 Chromium
133 passed、前端 Vitest 261 passed，外加 typecheck/lint/api:check/build/compileall/ruff/OpenAPI
drift/git diff --check 全绿。

实现偏差：均为契约内最小扩展，无范围外 feature（未实现 Auto Bangumi 管理、外部同步、
EXTERNAL_ONLY、正式追番管理前端页面；B-C 全部留给后续）。
剩余风险：多 worker 共享同一 storage 仍不支持（进程内按键锁）；operation 的 PREPARED 恢复依赖
同键 submit 或 recover 人工介入；历史迁移对“损坏文件”只报告 unreadable 计数，后续访问会持续
重试直到修复；旧 batch queue 兼容投影保留一个发布周期，删除旧接口需独立 PRD。
Stage 29 prd/progress 已归档到
`scripts/ralph/archive/2026-09-08-stage29-unified-tracking/`。
