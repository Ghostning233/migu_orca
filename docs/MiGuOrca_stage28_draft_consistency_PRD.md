# MiGuOrca Stage 28 PRD：草案一致性与原子保存确认

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 项目名称 | MiGuOrca |
| 文档名称 | Stage 28 PRD：草案一致性与原子保存确认 |
| 文档类型 | 执行 PRD / 前端体验重构 B-A |
| 当前状态 | 已完成（US-210～US-218 全部 passes: true，2026-09-08） |
| 创建日期 | 2026-09-07 |
| 完成日期 | 2026-09-08 |
| Backlog | BL-025（B-A） |
| 优先级 | P0 |
| 前置条件 | Stage 26、Stage 27 已完成；前端体验 Gate 1～3 已通过 |
| 规划分支 | `ralph/stage28-draft-consistency` |
| Ralph stories | US-210～US-218 |

## 2. 背景

Stage 26 建立了服务端权威 `DraftStore`，Stage 27 的 Vue 前端只持有 opaque `draft_id`。当前
实现已经阻止浏览器回传完整 Request 冒充权威草案，但还存在四个直接阻塞新体验的问题：

1. `preview-modify` 没有 revision。两个重算请求乱序时，晚到的旧请求仍可能覆盖服务器中的新值。
2. `preview-save` 在持久化之前先消费 draft。写盘失败后草案已失效，用户只能重新搜索。
3. 单番和批量“保存并确认”需要客户端串联保存、接受和入队，无法提供一个稳定用户操作。
4. 批量解析没有服务端 36 部上限，Request 详情也不适合直接作为“全部信息”安全视图。

Stage 28 只解决本地草案、保存确认和安全读取，不实现统一 tracking 或 Auto Bangumi 管理。这样
每个 Ralph story 可以在单次迭代完成，也避免再次把跨存储、外部协议和前端重构塞入一个阶段。

## 3. 目标

1. 为每个服务端草案提供单调递增 revision，并以 compare-and-swap 阻止乱序旧写。
2. 将保存改为“预留 → 持久化 → 提交/释放”，写盘失败后同一草案仍可重试。
3. 建立不含敏感值的持久化幂等记录，使组合操作在响应丢失、进程重启或客户端重试后不重复创建。
4. 新增单番 `save-confirm`：一次用户请求完成校验、保存和确认，并返回明确 handoff。
5. 新增批量 `save-confirm`：按条执行相同用例，成功不因其他条目失败而回滚。
6. 在客户端和服务端一致执行单批 1～36 部，服务端在访问 MiKan 前拒绝第 37 部。
7. 新增 Request `safe-info` 严格白名单 DTO，为后续“全部信息”弹窗提供唯一安全数据源。
8. 同步 OpenAPI、endpoint inventory、生成 TypeScript client、契约测试和文档。

## 4. 非目标

1. 不实现 tracking repository、追番管理列表、提交前复核或统一外部提交状态机。
2. 不新增 Auto Bangumi 列表、详情、修改、启停、删除、刷新或 capability adapter。
3. 不重构生产前端页面结构、导航、视觉 Token 或用户可见布局；只允许完成 revision 契约兼容所需
   的最小数据流调整。
4. 不实现未保存批量现场的跨刷新恢复。
5. 不实现 BL-020 当前已更新集数；`safe-info` 只能报告 `NOT_IMPLEMENTED`。
6. 不引入数据库、后台 worker、多用户认证或远程访问能力。
7. 不删除旧 `preview-save`、Request accept 或 batch accept/queue 端点。
8. 自动化不得访问真实 MiKan、Auto Bangumi 或 qBittorrent。

## 5. 核心决策

| 编号 | 决策 | 说明 |
| --- | --- | --- |
| D28-01 | revision 从 1 开始 | 创建草案返回 1；每次成功修改加 1；读取和保存不自增。 |
| D28-02 | 服务端执行 CAS | `preview-modify` 和保存确认都带 `base_revision`；不匹配返回 409。 |
| D28-03 | 重算结果原子写入 | 字幕组、资源集合、计数、审核状态与 revision 同一次替换，不做字段级并发合并。 |
| D28-04 | 保存失败不消费草案 | 只有持久化成功后才把 draft 标为已保存；失败释放预留并保留原 revision。 |
| D28-05 | 组合操作带幂等键 | 客户端为一次明确操作生成 opaque `idempotency_key`，传输重试必须复用。 |
| D28-06 | 幂等结果可跨进程恢复 | 服务端在 storage profile 内持久化非敏感操作记录，不只依赖进程内 tombstone。 |
| D28-07 | 确认失败不回滚已保存 Request | 返回 `SAVED_CONFIRM_FAILED`、公开 `request_id` 与重试动作，不要求重新搜索。 |
| D28-08 | 批量按条提交 | 每条有独立幂等键和结果；单条失败不回滚成功项，也不重新处理已成功项。 |
| D28-09 | Stage 28 不创建 tracking | 成功 handoff 使用 `request_id` 和 `ACCEPTED`；后续 B-B 幂等迁移为 tracking record。 |
| D28-10 | safe-info 默认拒绝 | serializer 显式构造白名单，不能先返回完整 snapshot 再由前端隐藏。 |

## 6. 目标契约

### 6.1 DraftStore

`issue` 的公开结果在内部表示为：

```text
DraftHandle(draft_id, revision=1)
```

读取返回草案和 revision。修改使用 `compare_and_swap(draft_id, base_revision, new_request)`：

- revision 匹配：原子替换 Request，revision 加 1，返回新 revision；
- revision 不匹配：不修改草案，返回 `draft_revision_conflict`；
- 草案过期、逐出、重放：继续使用现有稳定 409 分类。

保存使用 reservation，不允许直接先 `pop`：

```text
reserve_for_save(draft_id, base_revision, idempotency_key)
commit_save(reservation, public_result)
release_save(reservation)
```

同一草案处于预留状态时，其他 revision 修改或不同幂等键保存返回稳定冲突。持久化异常必须调用
`release_save`；成功后 `commit_save` 保存最小公开结果并建立重放 tombstone。

### 6.2 Revision API

扩展现有端点：

- `POST /api/v1/requests` 在 `save_request=false` 时返回 `draft_id` 和 `draft_revision`。
- `POST /api/v1/requests/preview-modify` 请求增加必填 `base_revision`；成功返回相同 `draft_id`、
  新 `draft_revision` 和完整公开预览结果。
- 409 `draft_revision_conflict` 的 `error_data` 只允许
  `{"field":"base_revision","current_revision":N}`，不得包含 draft ID 或草案内容。

旧前端在 Stage 28 期间仍存在，因此需要同一 PR 内升级当前 Vue 调用以发送/保存 revision；这属于
必要契约兼容，不授权实施新页面设计。不得让 revision 变成 URL 或持久化 Pinia 状态。

### 6.3 单番保存确认

新增：

```text
POST /api/v1/requests/save-confirm
```

请求：

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

持久化成功、确认失败返回对应 HTTP 失败 envelope，`error_data` 只包含：

```json
{
  "outcome": "SAVED_CONFIRM_FAILED",
  "request_id": "public-saved-id",
  "retry_action": "ACCEPT_SAVED_REQUEST"
}
```

同一 `idempotency_key` 重试返回同一最终结果；不同键重放已提交 draft 返回 409
`draft_replayed`。幂等记录不得包含 draft 内容、标题、URL、凭据或绝对路径。

### 6.4 批量保存确认

扩展 `POST /api/v1/batches/parse`：规范化非空行后，0 部沿用 `validation_error`，超过 36 部返回
400 `batch_limit_exceeded`，`error_data` 只含 `field=raw_input`、`limit=36`、`actual`。
校验必须发生在标题解析或 MiKan 调用之前。

新增：

```text
POST /api/v1/batches/{batch_id}/save-confirm
```

请求：

```text
items[]: item_id, draft_id, base_revision, idempotency_key
item_ids?: 只处理选中项；省略时按 items 顺序处理全部
storage_dir?: 安全相对 profile
```

响应：

```text
batch_id
results[]: item_id, outcome, request_id?, status, error_type?, error_message?
summary: requested, confirmed, failed
```

批内错误使用逐条脱敏结果，不把可预期单条业务失败升级为整个 HTTP 失败。请求级 shape、batch ID、
storage profile 等错误仍使用普通失败 envelope。成功项幂等重试不能创建第二个 Request。

### 6.5 Request safe-info

新增：

```text
GET /api/v1/requests/{request_id}/safe-info?storage_dir=profile-name
```

`RequestSafeInfoDTO` 使用 `extra="forbid"`，只允许：

- `request_id`、标题、别名、季度和公开季数证据摘要；
- 选定 MiKan 合集标题和公开编号，不含完整合集/RSS URL；
- 字幕组、过滤规则用户可读摘要、相对 storage profile 和安全文件夹名；
- 有效/完整/排除资源数量与脱敏文件名摘要，不含 magnet、下载 URL 或原始 RSS；
- 总集数、`updated_episode=null`、`updated_episode_status=NOT_IMPLEMENTED`；
- Request 状态、脱敏历史和 Auto Bangumi 状态摘要。

未知嵌套字段、endpoint、URL、token、cookie、password、Authorization、magnet、原始响应和绝对
路径必须在 DTO/serializer 边界被拒绝或完全省略，不能出现在隐藏 DOM 所依赖的数据中。

## 7. 幂等记录与恢复

新增 storage repository 保存最小记录：

```text
idempotency_key
operation: SAVE_CONFIRM
request_fingerprint（不可逆、非敏感）
request_id?
state: IN_PROGRESS | SAVED_CONFIRM_FAILED | CONFIRMED
created_at, updated_at
```

约束：

1. storage profile 仍由 `_storage_dir` 安全解析；空值回落服务端根。
2. 同一个键只能绑定一个操作和 request fingerprint；不同 payload 复用同一键返回 409
   `idempotency_conflict`。fingerprint 只能由允许字段的规范化形式计算，不能保存原始 payload。
3. `IN_PROGRESS` 重试先核对 Request 是否已经落盘：存在则继续/确认，不存在则在持有有效
   reservation 时重试保存；不能无条件创建新 Request。
4. 最终状态重试直接返回持久化的公开标识与 outcome，不重新修改 Request。
5. 记录不保存完整请求、草案、输入标题、外部配置、URL 或错误堆栈。
6. repository 写入使用现有 storage 的原子文件模式，并有损坏/缺失 fixture 测试。

## 8. 用户故事

### US-210：建立带 revision 的 DraftStore 原语

- `DraftStore.issue` 建立 revision=1 的 handle，读取返回当前 revision。
- 新增 compare-and-swap 更新；匹配时原子替换并加 1，不匹配时不改变 payload/revision。
- 保持 TTL、LRU、evicted/expired/replayed tombstone 和容量语义。
- 单元测试覆盖初始 revision、连续更新、乱序冲突、过期、逐出和 clear。

### US-211：把 revision 接入 preview API 与生成契约

- 扩展 create/preview-modify schema、response DTO、serializer 和 route。
- `preview-modify` 必须提交 `base_revision`，冲突返回 409 `draft_revision_conflict` 和最小安全数据。
- 升级现有 Vue 草案调用，只在组件内存维护 revision；不进行视觉或页面结构改造。
- 同步 OpenAPI、生成 TypeScript client、golden/DTO/API/现有浏览器测试 fixture。

### US-212：修复草案先消费后持久化的问题

- 为 DraftStore 增加 reserve/commit/release 保存生命周期；预留期间拒绝修改和不同保存操作。
- `preview-save` 改为持久化成功后 commit，持久化异常后 release，同一 draft/revision 可重试。
- 成功保存继续保持 replay 防护；失败和冲突不泄漏 draft 内容或 storage 绝对路径。
- 单元与 API 测试注入持久化失败，证明草案未丢失且第二次保存成功。

### US-213：建立保存确认幂等记录

- 在 storage engine 增加最小 save-confirm idempotency repository 和原子读写，保存不可逆的
  request fingerprint 而不是原始 payload。
- 支持 `IN_PROGRESS`、`SAVED_CONFIRM_FAILED`、`CONFIRMED` 与同键相同结果重放。
- 同键不同操作/payload 返回 409 `idempotency_conflict`，错误不回显原始 payload。
- 测试覆盖进程级 store 清空后的重试、损坏记录、重复成功和并发冲突。

### US-214：实现单番 save-confirm 组合端点

- 新增严格请求/响应 DTO、application service 和 `POST /api/v1/requests/save-confirm`。
- 一次请求执行 revision 校验、预留、持久化、确认和幂等结果提交。
- 成功返回 `CONFIRMED` handoff；确认失败返回公开 request_id 和 `ACCEPT_SAVED_REQUEST`。
- 测试覆盖全成功、保存失败可重试、确认失败、同键重试、异键重放和错误脱敏。

### US-215：建立批量 1～36 部服务端边界

- `BatchParsePayload`/服务端用例按规范化非空行计数，允许 1、12、36，拒绝 0 和 37。
- 37 部返回 400 `batch_limit_exceeded`，只报告 limit/actual/field。
- 测试证明超限时标题解析器、MiKan 搜索和持久化 seam 均未被调用。
- 同步 OpenAPI、endpoint inventory 和生成 TypeScript client。

### US-216：实现批量 save-confirm 部分成功端点

- 新增严格请求 DTO、逐条结果 DTO 和 `POST /api/v1/batches/{batch_id}/save-confirm`。
- 每条复用 US-214 的保存确认 service；支持 `item_ids` 选择并保持输入顺序。
- 成功项不因失败项回滚；失败项返回稳定脱敏原因；幂等重试不重复创建 Request。
- 测试覆盖 1/12/36、部分成功、revision 冲突、重复 item/key、请求级错误和逐条计数。

### US-217：提供 Request safe-info 严格白名单

- 新增 `RequestSafeInfoDTO`、显式 serializer 和 `GET /api/v1/requests/{request_id}/safe-info`。
- 返回规定业务摘要和更新集数 `NOT_IMPLEMENTED`，不返回完整 URL、magnet、凭据、原始响应或绝对路径。
- DTO 使用 `extra="forbid"`；递归泄漏测试覆盖顶层、嵌套、列表、错误和 OpenAPI 示例。
- 404、非法 request ID、storage profile 错误保持现有 HTTP/envelope 分类。

### US-218：完成 Stage 28 契约回归与文档 handoff

- endpoint inventory、OpenAPI、生成 TypeScript client、README、架构/M01/M09/M13 与 backlog 同步。
- 新旧 preview/save/accept/batch 端点兼容测试、全部非浏览器测试和真实 Chromium 回归通过。
- 输出 B-B tracking 阶段 handoff，明确 Stage 28 只返回 ACCEPTED request handoff，不伪造 tracking。
- 归档 Stage 28 Ralph prd/progress，记录实际测试数量、偏差和剩余风险。

## 9. Ralph story 大小与顺序

故事按 `US-210 → 211 → 212 → 213 → 214 → 215 → 216 → 217 → 218` 执行。每个故事只承担
一个可测试的纵向变化；不得提前实现 tracking 或 AB 管理。若某一 story 在单次 Ralph 迭代内无法
同时完成实现与验证，应在开始编码前继续拆分，不允许靠跳过测试把 `passes` 改为 true。

## 10. 验收命令

每个 story 运行受影响的最小测试；Stage 合并前完整运行：

```bash
uv run python -m compileall -q src tests
uv run ruff check src tests
uv run pytest -q -m "not browser"
uv run python -m apps.migu_orca_web.openapi_gen
cd frontend
npm ci
npm run api:generate
npm run api:check
npm run typecheck
npm run lint
npm run test:run
npm run build
cd ..
uv run pytest tests/browser/ -q
git diff --check
```

OpenAPI 和 TypeScript 生成文件必须无漂移；浏览器整体 skip 不能作为通过证据。测试使用临时
storage 和 fake transport，不访问真实外部服务。完整门禁后确认仓库根 `.migu_orca/storage`
不存在，且没有未提交的 build、trace、截图或包含敏感值的临时产物。

## 11. 完成标准

1. US-210～US-218 全部 `passes: true`，每个 story 有提交和验证记录。
2. 乱序 preview modify 无法覆盖最新草案；卡片/详情可以依赖同一 revision 事实源。
3. 保存写盘失败不丢草案；组合请求重试和进程重启不重复创建 Request。
4. 单番与批量都只需一次 save-confirm 调用，批量部分成功语义稳定。
5. 1/12/36 部通过，37 部在任何外部调用前被拒绝。
6. `safe-info` 是“全部信息”的唯一允许数据源，并通过递归敏感值泄漏测试。
7. 现有端点与 Stage 27 页面回归通过；生产视觉和导航未被提前修改。
8. B-B 可以只基于持久化 ACCEPTED Request 和 handoff 幂等建立 tracking record。

## 12. 完成记录（2026-09-08）

Stage 28 已完成并合入 `ralph/stage28-draft-consistency`，US-210～US-218 全部 `passes: true`，
每个 story 有独立提交与验证记录：

- US-210 DraftStore revision 原语（issue→revision=1、get 返回当前 revision、
  `compare_and_swap` + `REASON_REVISION_CONFLICT`，RLock 临界区 + 深拷贝隔离；16 例单测）。
- US-211 revision 接入 preview API 与生成契约（create 未保存返回 draft_id+draft_revision；
  `preview-modify` 必填 `base_revision`，stale → 409 `draft_revision_conflict`，只报
  field/current_revision；Vue 只在组件内存维护 revision，不写 URL/browser storage）。
- US-212 修复先消费后持久化（`reserve_for_save`/`commit_save`/`release_save` 生命周期，
  预留期间拒绝 get/CAS/consume/逐出/过期；写盘失败 release 保留原 revision 可重试；
  注入持久化失败证明同 draft 只产生一个 Request）。
- US-213 建立 save-confirm 幂等记录（`<storage>/idempotency/<opaque-key>.json` 原子读写，
  白名单字段 + 不可逆 `request_fingerprint`；IN_PROGRESS/SAVED_CONFIRM_FAILED/CONFIRMED
  状态机 + `resolve_in_progress_retry` 磁盘核对；同键异 payload → 409 `idempotency_conflict`）。
- US-214 单番 save-confirm 组合端点（`POST /api/v1/requests/save-confirm`：校验/预留/持久化/
  确认/幂等提交一次完成，成功返回 CONFIRMED + ACCEPTED handoff；确认失败 → 409
  `save_confirm_failed`，只报 outcome/request_id/retry_action=ACCEPT_SAVED_REQUEST）。
- US-215 批量 1～36 部服务端边界（`MAX_BATCH_ITEMS=36` + `split_batch_raw_input` 共用计数，
  37 部在任何解析/MiKan seam 前返回 400 `batch_limit_exceeded`，只报 field/limit/actual）。
- US-216 批量 save-confirm 部分成功端点（`POST /api/v1/batches/{batch_id}/save-confirm`
  逐条复用单番用例；重复 item→skipped、同键复用→逐条 idempotency_conflict、summary
  {requested,confirmed,failed}；成功项不因失败项回滚）。
- US-217 Request safe-info 严格白名单（`GET /api/v1/requests/{request_id}/safe-info`，
  `extra="forbid"` DTO + 默认拒绝 serializer；updated_episode 恒 null/
  NOT_IMPLEMENTED；递归泄漏测试覆盖顶层/嵌套/列表/404/非法 id/storage 错误）。
- US-218 契约回归与文档 handoff（本文档 + README/架构/M01/M09/M11/M13/backlog/future stages/
  api 文档同步；新旧 preview/save/accept/batch 兼容 + 全部非浏览器 + 真实 Chromium 回归通过；
  输出 B-B tracking handoff；归档 prd/progress）。

实际测试数量（初版交付）：非浏览器 1127 passed、真实 Chromium 133 passed、前端 Vitest 261 passed，
外加 typecheck/lint/api:check/build/compileall/ruff/OpenAPI drift/git diff --check 全绿。

2026-09-08 追加一轮「Stage 28 静态审查修复」（不改变产品范围）：
- 终态幂等键重放前经无副作用 `DraftStore.peek` 核对仍存在草案的 fingerprint，同键异草案 →
  409 `idempotency_conflict`（草案保持可用，不被预留/消费）；draft 缺失/预留时仍安全重放。
- `run_save_confirm` 用显式 `persisted` 阶段标志，保证 reserve 后到持久化成功前的任一异常
  都 `release_draft`，落盘后不再释放。
- save-confirm 请求模型改 `extra="forbid"`，OpenAPI 三个 requestBody 同步
  `additionalProperties: false`。
- `_safe_label` 对非字符串返回 None、对任意位置的 URL/magnet/绝对路径/key=value 敏感文本
  稳定脱敏；bool/整数类型显式归一化。
- `_KEY_LOCKS` 改引用计数按键锁；批量 summary 的 skipped 计入 failed 保持
  `requested == confirmed + failed` 闭合。

修复后门禁：非浏览器 1137 passed、真实 Chromium 133 passed、前端 Vitest 261 passed，
typecheck/lint/api:check/build/compileall/ruff/OpenAPI drift/git diff --check 全绿。

2026-09-08 追加一轮「Stage 28 边界修复」（不改变产品范围）：
- 终态幂等重放区分 `reserved` 与真正不存在：`peek_draft` 对 `REASON_RESERVED` 直接抛 409
  `draft_reserved`（绝不重放旧终态），仅 `replayed`/`expired`/`evicted`/`unknown`（真正缺失，
  含进程重启）折叠为 None 允许安全重放；单番与批量共用同一 `_run_draft_save_confirm` 语义。
- `_SAFE_UNIX_ABS_RE` 改为通用 POSIX 绝对路径（任意根目录，`/` 前为字符串开头或空白），
  不再依赖固定根目录白名单，同时不误杀 `Fate/stay night`、`A/B 测试` 等词内斜杠。

2026-09-08 追加「Stage 28 边界修复补充」（通用 POSIX 路径任意边界）：
- `_SAFE_UNIX_ABS_RE` 边界从 `(?:^|\s)` 改为负向后行 `(?<![A-Za-z0-9_])`，使
  `path=/mnt/secret`、`路径为/data/secret`、`（/Users/name/secret）`、`"/opt"`、
  `dest:/var/lib/data` 等任意位置嵌入的绝对路径均被脱敏，同时 `Fate/stay night`、
  `A/B 测试`、`v1/1080p` 等词内斜杠不误杀。本轮实际验证：非浏览器 1140 passed、
  真实 Chromium 133 passed、前端 Vitest 261 passed，typecheck/lint/api:check/build/
  compileall/ruff/OpenAPI drift/git diff --check 全绿。

实现偏差：均为契约内最小扩展，无范围外 feature（未实现 tracking/AB 管理/新页面视觉）。
剩余风险：draft 仍为单进程内存权威（多 worker 部署需外部化）；批量上限只约束 parse 入口，
不限制后续 accept/save-confirm 条数；`safe-info` 的 `total_episodes` 暂无数据源恒为 null。
Stage 28 prd/progress 已归档到 `scripts/ralph/archive/2026-09-08-stage28-draft-consistency/`。
