# 前端契约 handoff v1

版本：`v1`（Stage 32 B-D）
来源：`docs/api/openapi.json` → `frontend/src/api/generated/api.ts`
范围：F-B～F-F 的页面边界；本文不实现正式页面。

## 使用规则

- 页面只从 `frontend/src/api/generated/api.ts` 导入 `operations`/`components` 类型，不能复制 DTO 或根据状态字符串自行推断动作。
- 请求通过统一 API transport 发送。`draft_id`、`candidate_context`、`ab_config`、`mikan_config`、`idempotency_key` 等 request-scoped 值只存在组件局部内存和对应的一次 POST body；不得进入 URL、history、store 持久化、browser storage、日志、DOM、截图或 trace。
- `tracking_id`、`request_id` 是公开 opaque 标识，可以用于路由和路径参数；endpoint、凭据、原始上游内容、绝对路径和外部 ID 不得进入 URL 或页面可见内容。
- 成功响应是 `{ok: true, result}`；失败响应是 `{ok: false, error_type, error_message, error_data}`。HTTP 400/401/404/409/502/503/504/500 的含义以 OpenAPI 和统一 transport 为准，页面展示固定中文反馈，不渲染服务端原始错误详情。

## 页面用例与 generated operation

| 页面用例 | 首要流程 | operationId | 生成请求/响应类型的来源 |
| --- | --- | --- | --- |
| F-B 共享审核核心 | 生成、修改内存草案 | `createRequest` → `previewModifyRequest` | `operations['createRequest']`、`operations['previewModifyRequest']`；不得调用会消费草案的 `previewSaveRequest` |
| F-C 单番确认 | 明确确认后保存并进入待提交 | `confirmRequestSave` | `operations['confirmRequestSave']`；结果中的 `handoff.tracking_id` 是后续入口 |
| F-D 批量确认 | 逐条确认，允许部分成功 | `saveConfirmBatchItems` | `operations['saveConfirmBatchItems']`；按输入顺序消费 `results[]` |
| F-E 追番方案 | 列表、详情、安全信息、复核 | `listTrackingItems`、`getTrackingItemDetail`、`getRequestSafeInfo`、`revalidateTrackingItem` | 对应 `operations[...]` 的 query/path/body 与 `result` |
| F-F 正式追番管理 | 同步、提交/重试/恢复、修改、启停、刷新、外部删除 | `syncTrackingItems`、`submitTrackingItem`、`retryTrackingItem`、`recoverTrackingItem`、`modifyTrackingItem`、`setTrackingItemEnabled`、`refreshTrackingRss`、`deleteExternalTrackingItem` | 对应 `operations[...]`；Stage 38 US-303 先补严格 modify patch 与安全 target scopes |

F-F 是 handoff 的消费边界，不表示本阶段已经交付管理页面。Stage 33 的 `QueueView` 兼容挂载只代表旧队列可访问，不等于正式追番管理完成。

## 状态与动作

列表/详情是本地 `TrackingRecord` 的安全投影，`available_actions` 只表达本地已知可执行性，不是外部授权。页面应使用 generated `code`、`style` 和 `requires_confirmation`，并在每次 POST 中让服务端重新探测 request-scoped capability。

| 动作 | operationId | 需要 `confirm` | revision / 幂等 | 外部能力与恢复 |
| --- | --- | --- | --- | --- |
| 复核 | `revalidateTrackingItem` | 否 | `expected_revision` | 纯本地；409 刷新详情后重试 |
| 提交 | `submitTrackingItem` | 必须为 `true` | `expected_revision` + `idempotency_key` | 重新验证后写外部；明确失败用 retry，未知结果只能 recover |
| 重试 | `retryTrackingItem` | 必须为 `true` | `expected_revision` + 新操作的 `idempotency_key` | 仅明确失败允许；不得绕过 recovery |
| 恢复 | `recoverTrackingItem` | 人工标记时为 `true` | `expected_revision` | `AUTO` 纯本地；`VERIFY_EXTERNAL` 只读核验；`MARK_SUCCEEDED`/`MARK_FAILED` 是人工结论，不盲目重建 |
| 修改 | `modifyTrackingItem` | 必须为 `true` | `target_scope` + `expected_revision` + `idempotency_key` | `SUBSCRIPTION`/`ASSOCIATED_RSS`；服务端 read-before-write + capability |
| 启停 | `setTrackingItemEnabled` | 必须为 `true` | 同上 | 同上；外部删除/停用固定 `file=false` |
| 刷新 RSS | `refreshTrackingRss` | 必须为 `true` | `target_scope=ASSOCIATED_RSS` + revision + 幂等 | 仅关联 RSS capability |
| 外部删除 | `deleteExternalTrackingItem` | 必须为 `true` | scope + revision + 幂等 | 保留本地 Request、tracking、审计和媒体；固定 `file=false` |

公开状态重点包括 `PENDING_SUBMIT`、`SUBMITTING`、`ACTIVE`、`DISABLED`、`EXTERNAL_DELETED`、`VERIFYING_EXTERNAL`、`RECOVERY_REQUIRED` 等服务端返回值。页面不得把 `VERIFYING_EXTERNAL` 或 `RECOVERY_REQUIRED` 当作成功，也不得由旧 queue/AB 投影自行清除它们。

## 确认、revision、幂等和错误恢复顺序

1. F-B 生成草案后只保存服务端签发的 `draft_id` 与 `draft_revision`；修改/保存携带 `base_revision`，409 `draft_revision_conflict` 时丢弃本地快照并重新加载/生成。
2. F-C/F-D 保存确认只在用户明确确认后发送；传输重试复用同一个 `idempotency_key`，不得生成第二个 Request 或 tracking record。单番确认完成后只进入 `PENDING_SUBMIT`，不会自动调用 Auto Bangumi。
3. F-E/F-F 读取详情取得当前 `revision`；每次写动作原样带 `expected_revision`。409 revision/idempotency/state conflict 时先刷新列表/详情，再由用户重新确认，不能静默重放。
4. HTTP 200 也要检查业务 `outcome`：明确失败显示安全失败并按契约允许 retry；`OUTCOME_UNKNOWN`、`VERIFYING_EXTERNAL`、`RECOVERY_REQUIRED` 只进入 recover/核验流程；恢复完成后再刷新详情。
5. 列表刷新失败、非 JSON、网络失败或上游错误只显示固定安全文案。不要把 `error_data`、endpoint、响应体或 traceback 放进 DOM、通知、日志或 URL。

## F-B～F-E 交付边界

- F-B 只消费 draft create/modify 的 generated request/result，绝不调用会消费 draft 的 `previewSaveRequest`；保存确认由 F-C/F-D 的 `save-confirm` 流程负责，且不得把完整 Request 快照当作客户端 DTO 回传。
- F-C 使用 `confirmRequestSave` 的 `handoff`；`tracking_ready=false` 时保留已确认 Request，提示用户打开追番列表恢复，不重复保存。
- F-D 只按 `results[]` 逐条显示 `confirmed`/`failed`/`skipped`，一条失败不回滚其他已确认项；失败条目沿用服务端给出的公开 `error_type` 分类，不显示原始详情。
- F-E 使用 tracking list/detail 和 safe-info；`safe_info` 是白名单展示数据，不能推断外部原始响应或本地路径。
- 所有 tracking 投影以 `TrackingRecord` 为唯一外部提交权威；旧 queue/AB 结果仅为兼容投影或迁移证据。

## F-F 启动条件与 Stage 38 补口

Stage 32 已合入，F-A～F-E 也已完成，因此 F-F 已规划为 Stage 38。实时复核发现 generated
`modifyTrackingItem.patch` 仍为 `Record<string, never>`，且 `available_actions` 尚无可安全判定的目标 scope；
US-303 只补齐严格 patch 联合与 server-computed `target_scopes`，不新增管理动作、状态、endpoint 或外部语义。
补口通过 API drift check 与 typecheck 后再实现正式页面；Stage 33 的 QueueView 兼容挂载仍不等于管理页面完成。

## 集数占位

所有相关结果的 `updated_episode` 固定为 `null`，`updated_episode_status` 固定为 `NOT_IMPLEMENTED`。前端不得从种子、RSS、下载进度或标题猜测已更新集数，也不得把该字段渲染成已更新集数。
