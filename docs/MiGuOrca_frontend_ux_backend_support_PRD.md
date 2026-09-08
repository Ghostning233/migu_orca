# MiGuOrca 前端体验重构：后端支撑 PRD

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 文档类型 | 候选执行 PRD / Gate 4 输入 |
| 当前状态 | B-A 已完成（Stage 28）；B-B 已完成（Stage 29）；B-C～B-D 待评审 |
| 创建日期 | 2026-09-07 |
| Backlog | BL-025 |
| 优先级 | P0，阻塞依赖目标能力的前端切片 |
| 依赖 | Stage 26、Stage 27 已完成；Gate 1～3 已完成 |
| 事实基线 | 当前代码、`docs/api/openapi.json`、前端交互规格 §18.1 |

本 PRD 只定义前端体验重构必须补齐的服务端能力。它不重新设计页面，也不要求一次性放入一个
超大 Stage。正式排期时应按本文的候选实施包拆分，每个包分别生成 Ralph stories、提交和验收。

## 2. 背景

Stage 26 已建立 Flask `/api/v1`、严格响应 DTO、确定性 OpenAPI、服务端权威 draft 和默认
local-only 安全边界；Stage 27 已建立 Vue 3、TypeScript、Vite、生成客户端与真实 Chromium
基线；Stage 28 已完成 revision、可靠保存、单番/批量 save-confirm、36 部边界和 safe-info。
Stage 29 已完成统一单番/批量提交状态与恢复（tracking 投影、纯本地复核、可靠提交与人工恢复），
执行细节以 `docs/MiGuOrca_stage29_unified_tracking_PRD.md` 为准；B-C～B-D（Auto Bangumi
列表、详情、修改、启停、删除和 RSS 管理）继续由本文承载候选边界。

## 3. 目标

1. 提供单番和批量“保存并确认”组合契约，返回可由后续 tracking 能力幂等接管的确认结果。
2. 为服务端权威 draft 增加 revision 和乐观并发，保证重算结果原子且旧写不能覆盖新写。
3. 在 API 层一致执行单批最多 36 部校验，并返回可操作的结构化错误。
4. 建立统一追番记录、提交前复核、外部写入幂等、超时结果确认、重试和人工恢复语义。
5. 以 Auto Bangumi 3.1.18 为首个完整管理 adapter 验收基线；其他版本按逐项 capability
   探测结果开放或只读降级。
6. 用稳定、版本化、严格且脱敏的 MiGuOrca DTO 隔离 Auto Bangumi 上游响应差异。
7. 建立本地方案、追番记录、Auto Bangumi 番剧/RSS 对象之间的稳定映射和对账。
8. 提供专用 Request 安全信息白名单 DTO，服务“全部信息”弹窗。
9. 保持现有 `/api/v1` envelope、OpenAPI 生成、TypeScript 客户端漂移检查与旧端点兼容。

## 4. 非目标

1. 不实现前端页面、视觉组件或导航。
2. 不引入数据库、后台 worker、消息队列、多用户账号或公网远程管理。
3. 不为未保存的批量审核现场建立服务端可恢复会话；刷新/离开保护由前端负责。
4. 不实现 BL-020“当前已更新集数”；DTO 只提供 `null` 和能力状态，不从种子或下载状态猜测。
5. 不支持契约未证明的 Auto Bangumi 版本写操作；未知能力必须 fail closed。
6. 不绕过 Auto Bangumi 直接操作 qBittorrent，也不删除任何已下载媒体文件。
7. 不把 endpoint、用户名、密码、token、cookie、完整 RSS URL、magnet、上游原始响应或服务器
   绝对路径持久化到追番记录或返回给浏览器。

## 5. 核心决策

| 编号 | 决策 | 说明 |
| --- | --- | --- |
| DB-01 | 保持 Stage 26 envelope | 新端点继续使用 `{ok,result}` / `{ok,error_type,error_message,error_data}` 和统一 HTTP 分类。 |
| DB-02 | 草案标识只放请求体 | `draft_id` 和 revision 不进入 URL、浏览器持久化存储或日志。 |
| DB-03 | 外部凭据保持 request-scoped | 需要访问 Auto Bangumi 的 API 使用 POST body 携带 `ab_config`；服务端不得持久化或回显。 |
| DB-04 | 追番记录使用本地 opaque ID | `tracking_id` 是页面路由和管理动作的稳定标识，不把版本相关的外部 ID 暴露为主键。 |
| DB-05 | 同步产生安全投影 | 外部同步只持久化白名单状态、映射、revision 和时间，不持久化原始响应与敏感 URL。 |
| DB-06 | 提交始终内含复核 | 独立复核用于预览；即使刚复核成功，真正提交仍必须在同一服务端用例中再次检查。 |
| DB-07 | 幂等覆盖单番和批量 | 用户一次显式提交生成一个 `idempotency_key`；传输重试复用同一键，服务端保存操作状态。 |
| DB-08 | 外部删除只删除外部对象 | 本地方案、追番记录和审计历史保留；任何响应和实现都不得提供删除媒体选项。 |
| DB-09 | 3.1.18 是完整基线 | 未证明版本只能开放探测为 `SUPPORTED` 的动作；探测失败是 `UNKNOWN`，不是 `UNSUPPORTED`。 |
| DB-10 | 旧端点先兼容后收敛 | 现有 preview save/accept、单番 submit 和 batch queue 端点暂不删除；新前端只消费新组合/追番契约。 |

## 6. 目标状态与持久化边界

### 6.1 Draft

- 创建未保存草案时签发 `draft_id` 和从 1 开始的 `draft_revision`。
- 修改请求必须携带 `base_revision`；成功后原子返回新 revision、字幕组、资源集合、计数和审核
  状态。
- revision 不匹配返回 409 `draft_revision_conflict`，并只返回当前公开 revision；不得回显草案。
- “保存并确认”成功后消费草案；持久化失败时不得消费，持久化成功但确认失败时保留已保存
  `request_id` 并返回可重试确认状态。

### 6.2 Tracking record

每个追番记录至少保存：

```text
tracking_id
request_id（可空，外部孤立对象没有本地方案）
batch_id（可空，仅用于回溯来源）
external_mapping（adapter、外部番剧/RSS opaque ID，可空）
status、revision、operation_id、idempotency_key
安全的外部状态投影与最近同步时间
最近一次脱敏错误、审计时间与恢复状态
```

不得保存 `ab_config`、Authorization、cookie、完整 endpoint、原始响应、完整 RSS URL、magnet、
下载目录绝对路径。`idempotency_key` 是随机非敏感操作标识，只用于去重，不能包含业务或凭据。

### 6.3 用户可见追番状态

```text
PENDING_SUBMIT
REVALIDATING
NEEDS_RECONFIRM
SUBMITTING
VERIFYING_EXTERNAL
ACTIVE
DISABLED
SUBMIT_FAILED
RECOVERY_REQUIRED
EXTERNAL_DELETED
EXTERNAL_ONLY
UNKNOWN
```

内部状态可更细，但 DTO 必须稳定映射为以上枚举和中文 `status_label`。超时且结果未知必须进入
`VERIFYING_EXTERNAL` 或 `RECOVERY_REQUIRED`，不能直接回到可重复创建的待提交状态。

## 7. API 契约

### 7.1 草案、保存确认与安全详情

| 方法 | 路由 | 类型 | 目的 |
| --- | --- | --- | --- |
| POST | `/api/v1/requests` | 扩展 | 未保存预览响应增加 `draft_revision`。 |
| POST | `/api/v1/requests/preview-modify` | 扩展 | 请求增加 `base_revision`，响应原子返回新 revision 与重算结果。 |
| POST | `/api/v1/requests/save-confirm` | 新增 | 一次执行校验、保存、确认并建立待提交追番记录。 |
| POST | `/api/v1/batches/parse` | 扩展 | 规范化非空行后强制 1～36 部；条目响应携带 draft revision。 |
| POST | `/api/v1/batches/{batch_id}/save-confirm` | 新增 | 按条执行草案保存、确认与入追番记录，返回部分成功结果。 |
| GET | `/api/v1/requests/{request_id}/safe-info` | 新增 | 返回“全部信息”弹窗专用的严格安全白名单。 |

`POST /api/v1/requests/save-confirm` 请求：

```json
{
  "draft_id": "opaque",
  "base_revision": 3,
  "idempotency_key": "opaque-client-operation-id",
  "storage_dir": "profile-name"
}
```

成功 `result`：

```json
{
  "outcome": "CONFIRMED",
  "request": {},
  "summary": {},
  "handoff": {
    "request_id": "public-saved-id",
    "status": "ACCEPTED",
    "next_action": "OPEN_TRACKING"
  }
}
```

如果 Request 已保存但确认失败，HTTP 仍按实际错误分类返回失败 envelope；`error_data` 仅允许：

```json
{
  "outcome": "SAVED_CONFIRM_FAILED",
  "request_id": "public-saved-id",
  "retry_action": "ACCEPT_SAVED_REQUEST"
}
```

不得返回已消费的 `draft_id` 或草案内容。前端使用现有 Request accept 契约重试确认；成功后服务端
同样必须幂等建立唯一 tracking record。

批量组合请求的 `items` 每项仅含 `item_id`、`draft_id`、`base_revision` 和
`idempotency_key`；不得由浏览器回传完整 Request。响应沿用现有逐条模型并扩展：

```text
batch_id
results[]: item_id, outcome, request_id?, status, error_type?, error_message?
summary: requested, confirmed, failed
```

每条失败不回滚成功条目；重放已经成功的 `item_id + draft_id` 必须返回同一公开结果或稳定
`already_confirmed`，不能创建第二个 Request 或 tracking record。

### 7.2 Auto Bangumi 能力与同步

| 方法 | 路由 | 目的 |
| --- | --- | --- |
| POST | `/api/v1/autobangumi/capabilities` | 使用 request-scoped `ab_config` 探测版本和逐项能力。 |
| GET | `/api/v1/tracking/items` | 读取本地安全投影；支持状态、标题筛选和排序，不访问外部系统。 |
| POST | `/api/v1/tracking/sync` | 使用 request-scoped `ab_config` 拉取外部对象、对账并返回最新安全列表。 |
| GET | `/api/v1/tracking/items/{tracking_id}` | 读取本地方案、外部映射和审计的安全详情。 |

`CapabilityState` 固定为 `SUPPORTED | UNSUPPORTED | UNKNOWN`。能力 DTO 至少包含：

```text
probe_status: VERIFIED | PARTIAL | FAILED
version: string | null
adapter: string | null
subscription_list/detail/modify/enable/disable/delete: CapabilityState
rss_list/modify/enable/disable/delete/refresh: CapabilityState
checked_at: RFC3339 string
safe_message: string | null
```

`FAILED` 时全部未证明能力为 `UNKNOWN`。`safe_message` 只能使用服务端固定脱敏文案。

### 7.3 追番动作

| 方法 | 路由 | 目的 |
| --- | --- | --- |
| POST | `/api/v1/tracking/items/{tracking_id}/revalidate` | 返回提交前结构化复核结果，不执行外部写入。 |
| POST | `/api/v1/tracking/items/{tracking_id}/submit` | 再次复核后执行幂等外部创建。 |
| POST | `/api/v1/tracking/items/{tracking_id}/retry` | 使用同一逻辑和持久化操作状态重试失败写入。 |
| POST | `/api/v1/tracking/items/{tracking_id}/recover` | 查询外部结果或记录用户人工核验，不直接盲目重建。 |
| POST | `/api/v1/tracking/items/{tracking_id}/modify` | capability 允许时修改外部订阅/RSS 的白名单字段。 |
| POST | `/api/v1/tracking/items/{tracking_id}/set-enabled` | capability 允许时启用或停用外部订阅。 |
| POST | `/api/v1/tracking/items/{tracking_id}/refresh` | capability 允许时手动刷新关联 RSS。 |
| POST | `/api/v1/tracking/items/{tracking_id}/delete-external` | 删除外部对象，强制保留本地方案、记录和媒体。 |

所有会访问外部系统的请求都在 body 中携带 `ab_config`，完成响应后立即丢弃。写动作同时携带：

```json
{
  "confirm": true,
  "idempotency_key": "opaque-client-operation-id",
  "expected_revision": 7,
  "ab_config": {}
}
```

`modify` 额外包含严格白名单 `patch`；`set-enabled` 额外包含 `enabled`。B-B 的 `recover` 使用
`action: "AUTO" | "MARK_SUCCEEDED" | "MARK_FAILED"`，其中 AUTO 只检查本地证据；B-C 另增外部
核验动作。人工成功/失败必须二次确认并写审计记录。

### 7.4 提交前复核

`TrackingRevalidationDTO`：

```text
tracking_id
ready: boolean
checked_revision
checked_at
issues[]: code, field?, message, recovery_action
next_status: PENDING_SUBMIT | NEEDS_RECONFIRM
```

复核至少检查：

1. 本地 Request 存在且处于允许提交的已确认状态。
2. 标题、季度、真实 MiKan 合集和用户确认依据仍完整。
3. 字幕组、过滤结果和有效资源仍满足提交要求。
4. tracking revision 与 Request/映射一致，没有被另一个页面修改。
5. 已存在映射或本地证据表明可能已创建时不得再次创建；应转入恢复。

独立 `revalidate` 是纯本地操作，不携带 `ab_config`、不探测连接或 capability。提交动作仍须在
同一服务端用例中重新执行本地复核并校验 request-scoped AB 配置；外部 capability 探测属于 B-C。

`issues[].code` 采用稳定枚举，例如 `REQUEST_MISSING`、`REQUEST_NOT_ACCEPTED`、
`REQUEST_CHANGED`、`SEASON_REVIEW_REQUIRED`、`MIKAN_SELECTION_MISSING`、
`SUBTITLE_GROUP_MISSING`、`NO_VALID_RESOURCES`、`EXTERNAL_ALREADY_LINKED`、
`OPERATION_IN_PROGRESS`、`TRACKING_STATE_INVALID`。文案为脱敏中文，不能包含上游响应。

## 8. DTO 白名单

### 8.1 Tracking summary

`TrackingSummaryDTO` 必须 `extra="forbid"`，至少包含：

```text
tracking_id, request_id?, title, season?, poster_url?
status, status_label, subtitle_group?, valid_resource_count
updated_episode: null, updated_episode_status: "NOT_IMPLEMENTED"
total_episodes?, external_linked, enabled?, last_synced_at?
available_actions[], revision, safe_error?
```

`available_actions` 只由服务端根据本地状态和已证明 capability 生成，前端不得自行推断动作权限。

### 8.2 Tracking detail

`TrackingDetailDTO` 在 summary 之外只允许：本地方案摘要、关联外部对象的安全摘要、最近操作状态、
安全审计事件和复核问题。禁止外部原始 JSON、完整 URL、认证头、cookie、绝对路径和 magnet。

### 8.3 Request safe info

`RequestSafeInfoDTO` 只允许：

- `request_id`、标题、别名、季度与季数证据摘要；
- 选定 MiKan 合集的标题和公开编号，不含完整合集/RSS URL；
- 字幕组、过滤规则的用户可读摘要、相对 storage profile 和安全文件夹名；
- 有效/完整/排除资源数量与经过脱敏的文件名摘要，不含 magnet、下载 URL 或原始 RSS；
- 总集数、已更新集数能力状态、Request 状态和脱敏历史摘要；
- 安全的 Auto Bangumi 状态摘要，不含 endpoint、外部原始响应或凭据。

serializer 必须按默认拒绝原则显式构造字段。不能先输出 Request snapshot 再让前端删字段。

## 9. Auto Bangumi adapter 与映射

1. adapter 接口按 capability 拆分：probe、list/detail、create、modify、set enabled、delete、
   list/modify/set enabled/delete/refresh RSS。
2. 3.1.18 adapter 使用已验证的登录和 Cookie 会话；同一请求内复用会话，请求结束即销毁。
3. 上游响应先映射为内部对象，再由 Web serializer 生成严格 DTO；路由不直接返回上游 dict。
4. 对账优先使用已保存外部 ID；缺失 ID 时只能使用 adapter 明确定义的多字段证据，并将歧义
   返回为 `RECOVERY_REQUIRED`，不得只按标题自动关联。
5. 外部对象没有本地方案时可以创建 `EXTERNAL_ONLY` 安全映射；不伪造 Request。
6. 删除后 tracking record 进入 `EXTERNAL_DELETED`，保留删除范围、时间和本地方案链接。
7. 自动化只使用脱敏 fixture/fake transport，不向真实 Auto Bangumi 执行写操作。

## 10. 兼容与迁移

1. 现有 `/requests/preview-save`、`/{request_id}/accept`、`/{request_id}/submit-ab` 和
   `/batches/{batch_id}/accept|queue|submit|retry|recover` 继续工作，至少保留一个完整发布周期。
2. 新 tracking repository 首次读取时可从已接受 Request、现有 batch queue 和已保存 AB result
   幂等回填；迁移不得访问真实外部系统。
3. 旧单番/批量提交写入成功后也必须更新同一 tracking record，避免两套状态源分叉。
4. 只有新前端、浏览器套件和迁移检查全部不再使用旧端点，才可另立 PRD 讨论删除；本 PRD 不删。
5. 每个新增/修改端点同步 `schemas.py`、`api_contract.py`、serializer/service/route、OpenAPI
   注册表、endpoint inventory、生成 JSON、TypeScript client 和契约测试。

## 11. 候选实施包

这些实施包表达依赖关系，不等于正式 Stage 编号：

| 实施包 | 内容 | 可独立验收结果 | 依赖 |
| --- | --- | --- | --- |
| B-A 草案一致性（Stage 28） | revision、可靠保存、单番/批量保存确认、36 部上限、安全信息 DTO | 新添加与批量审核不再串联保存/接受；确认结果可由 B-B 幂等迁移 | 已完成 (Stage 28, 2026-09-08)，执行 PRD 见 `docs/MiGuOrca_stage28_draft_consistency_PRD.md` |
| B-B 统一追番记录 | Stage 29：tracking repository、回填、状态映射、纯本地复核、幂等提交/恢复 | 单番与批量进入同一待提交列表 | 已完成 (Stage 29, 2026-09-08)，执行 PRD 见 `docs/MiGuOrca_stage29_unified_tracking_PRD.md`；B-C 由此扩展 |
| B-C AB 管理 adapter | 3.1.18 capability、列表/详情/修改/启停/删除/RSS 刷新、映射对账 | 3.1.18 完整管理闭环可由 API 验收 | B-B |
| B-D 契约收尾 | OpenAPI、TS client、泄漏回归、兼容与迁移演练 | 后端 handoff 冻结，可启动全部依赖前端切片 | B-A～B-C |

B-A 已完成（Stage 28），B-B 已完成（Stage 29）；B-B 与 B-C 不应塞进前端实现 PR。B-C 风险最高，建议使用独立分支和独立 PR，
避免一次提交同时改草案事务、存储迁移和多个外部写动作。

## 12. 验收

### 12.1 契约与业务

1. 单番保存确认只产生一个 Request；传输重试不重复创建，B-B 回填后也只能产生一个 tracking record。
2. 批量 1、12、36 部均可处理；37 部在访问 MiKan 前返回结构化 400。
3. 批量部分失败保留成功结果，失败条目可定位并重试，成功条目不会重放。
4. 两个乱序 draft 修改只有匹配最新 revision 的请求可写入；响应不出现新字幕组配旧资源。
5. 提交前复核失败不调用外部创建，并把记录置为 `NEEDS_RECONFIRM`。
6. 提交超时通过同一幂等操作进入结果确认；无法确认时进入人工恢复，不重复创建。
7. 3.1.18 的列表、详情、修改、启停、删除与 RSS 刷新使用 fake transport 全部通过。
8. 未知版本和探测失败只读降级，写动作服务端同样拒绝，不能只靠按钮隐藏。
9. 外部删除后本地 Request、tracking 审计和 fixture 媒体目录完全保留。
10. `safe-info`、tracking、capability 和所有错误响应均通过敏感字段递归泄漏检查。

### 12.2 质量门禁

```bash
uv run python -m compileall -q src tests
uv run ruff check src tests
uv run pytest -q -m "not browser"
uv run python -m apps.migu_orca_web.openapi_gen
cd frontend && npm ci && npm run api:generate && npm run api:check && npm run typecheck && npm run lint && npm run test:run && npm run build
uv run pytest tests/browser/ -q
git diff --check
```

实现 PRD 可以把耗时门禁分层，但合并前必须执行完整集合。外部 adapter 测试不得访问真实服务。

## 13. 完成标准

1. B-A～B-D 均有正式 story、独立验收证据和明确 PR 边界。
2. 新路由、DTO、错误类型、状态机、迁移和敏感值边界全部进入 OpenAPI/清单/测试。
3. 新前端不需要串联旧保存与接受端点来伪装“保存并确认”。
4. B-B 完成后，单番、批量和外部已有订阅由同一 tracking 投影管理，外部状态不再只存在页面内。
5. Auto Bangumi 3.1.18 完整能力通过 fake contract，未知版本可靠降级。
6. Gate 4 评审确认后，依赖这些能力的前端切片才可进入生产实现。
