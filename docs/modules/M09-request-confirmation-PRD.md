# M09 Request 确认交互模块 PRD

## 1. 模块目标

M09 负责 Request 确认交互能力，包括向用户展示 Request，并支持接受、修改、取消。Stage 2 已实现 CLI/controller 层确认、取消和受限修改；Stage 10 已通过 Web UI 暴露操作入口。

## 2. 模块边界

本模块负责：

1. 展示 Request 的关键信息。
2. 接收用户接受、修改、取消操作。
3. 在用户修改可修改字段后触发重新计算。
4. 在用户接受前触发必要的 RSS 变化校验。
5. 将交互结果反馈给 M01、M06、M07、M10 等模块。

本模块不负责：

1. Request 字段结构定义。
2. 种子筛选规则本身。
3. 文件夹命名规则本身。
4. Auto Bangumi 调用。
5. Request 持久化。
6. 完整 Web UI 实现。

## 3. 用户操作

### 3.1 接受

用户接受当前 Request。

系统行为：

1. 将 Request 状态更新为 ACCEPTED。
2. 执行接受前校验。
3. 校验通过后进入 M10 Auto Bangumi 集成流程。
4. 校验失败时返回需要重新确认的 Request 或错误信息。

### 3.2 修改

用户修改当前 Request 的可修改字段。

可修改字段包括：

1. 选择的字幕组。
2. 种子筛选规则。
3. 预期文件夹名。
4. 后续 AB 所需配置项。

不可直接修改字段包括：

1. 有效种子名列表。
2. RSS 中原始种子信息。
3. MiKan 原始搜索结果。

系统行为：

1. 接收用户提交的修改补丁。
2. 校验修改字段是否合法。
3. 对筛选规则或字幕组变化触发 M06 重新计算有效种子。
4. 对命名相关变化触发 M07 重新生成或校验文件夹名。
5. 返回状态保持原样（Stage 15 起）的新 Request：`PENDING_CONFIRM` 修改后仍为 `PENDING_CONFIRM`，`ACCEPTED` 修改后仍为 `ACCEPTED`，不回落为 `PENDING_CONFIRM`。
6. 记录 `MODIFY` history 事件。

修改范围约束（Stage 15 起）：

- 可修改字段仍限定为 `selected_subtitle_group`、`filter_rule`、`expected_folder_name`，不开放完整 Request JSON 编辑。
- `modify_request` 同时接受 `PENDING_CONFIRM` 与 `ACCEPTED`；`CANCELLED` 与未知状态拒绝修改并返回统一脱敏错误。
- 修改 `ACCEPTED` Request 不会隐式触发 Auto Bangumi 提交，提交仍需用户显式执行。

### 3.3 取消

用户取消当前 Request。

常见原因：

1. 用户输入的番剧名未正确匹配。
2. 系统匹配到了错误番剧。
3. 匹配到了番剧，但没有合适字幕组。
4. RSS 中没有有效种子。
5. 用户暂时不想订阅该番剧。

系统行为：

1. 将 Request 状态更新为 CANCELLED。
2. 记录取消原因。
3. 不调用 AB。

## 4. 接受前校验

用户接受 Request 时，系统需要重新校验当前选择的 RSS。

原因：

1. RSS 内容可能发生变化。
2. 有效种子列表可能增加或减少。
3. 字幕组可能更新了修正版。
4. 用户看到的 Request 可能已经不是最新状态。

后续需要定义：

1. 是否重新拉取 RSS。
2. 如何判断有效种子列表发生关键变化。
3. 如何提示用户确认变化。
4. 如何决定继续提交 AB 或重新生成 Request。

## 5. 输入输出

输入：

1. request_id。
2. 用户操作类型。
3. 修改补丁，如果操作类型为修改。
4. 取消原因，如果操作类型为取消。

输出：

1. 更新后的 Request。
2. 交互错误对象。
3. 是否进入 AB 提交流程的决策结果。

## 6. 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| Q-M09-01 | 接受前是否必须重新读取 RSS？ | 是 | 待确认 |
| Q-M09-02 | RSS 变化达到什么程度需要用户二次确认？ | 是 | 待确认 |
| Q-M09-03 | 修改补丁格式如何定义？ | 是 | 已确认：`patch` 对象只允许 `selected_subtitle_group`、`filter_rule`、`expected_folder_name`；`filter_rule` 内含 `must_contain` / `must_not_contain` / `use_regex` / `case_sensitive` |
| Q-M09-04 | 第一版确认交互是 CLI、API，还是 Web UI？ | 是 | 待确认 |

## 7. Stage 28 save-confirm 组合确认（已完成）

Stage 28 为单番与批量新增“保存并确认”组合端点，把 revision 校验、草案预留、Request
持久化、确认与幂等结果提交合并为一次用户操作：

- `POST /api/v1/requests/save-confirm`（单番）：请求只接受 `draft_id`、`base_revision`、
  opaque `idempotency_key` 与可选安全 `storage_dir`，绝不接受完整 Request。成功一次完成
  `DraftStore.reserve_for_save` → 持久化 Request → `commit_save` → 幂等记录 `CONFIRMED`，
  返回 `{outcome: CONFIRMED, request, summary, handoff: {request_id, status: ACCEPTED,
  next_action: OPEN_TRACKING}}`。
- `POST /api/v1/batches/{batch_id}/save-confirm`（批量）：每条只接受 `item_id`/`draft_id`/
  `base_revision`/`idempotency_key`，逐条复用单番用例；`item_ids` 可选并按输入顺序处理。
  响应是 HTTP 200 逐条部分成功 `{batch_id, results[], summary:{requested, confirmed, failed}}`，
  可预期单条失败映射为脱敏 `failed` 结果，成功项不因失败项回滚；同一请求内重复 `item_id`
  返回 `skipped`。
- 幂等语义（US-213）：storage engine 在 `<storage>/idempotency/<opaque-key>.json` 持久化
  只含非敏感白名单字段的原子记录。同一 `idempotency_key` 重试返回同一最终结果（终态重放）；
  同键不同 operation/payload → 409 `idempotency_conflict`（不回显原始 payload）；
  `IN_PROGRESS` 重试先核对已落盘 Request，存在则继续确认、不存在才在持有有效预留时安全重试保存，
  不无条件创建新 Request。持久化成功但确认失败 → 409 `save_confirm_failed`，details 只含
  `outcome=SAVED_CONFIRM_FAILED`/公开 `request_id`/`retry_action=ACCEPT_SAVED_REQUEST`。
- Stage 28 **不创建或伪造 tracking record**：成功 handoff 只返回 `request_id` + `ACCEPTED`；
  后续 B-B tracking 阶段从持久化 ACCEPTED Request 与 handoff 幂等建立统一 tracking record。

## 8. Stage 29 tracking handoff 扩展（已完成）

Stage 29（US-222）在不改变 Stage 28 语义的前提下扩展确认 handoff：

- 单番 accept、单番 save-confirm、批量 save-confirm 与终态重放成功后都会调用
  `ensure_confirmed_request_tracking`，把同一 Request 收敛到同一条确定性 `tracking_id`。
- handoff 保留 `status=ACCEPTED` 与 `next_action=OPEN_TRACKING`，并新增
  `tracking_id`/`tracking_status`/`tracking_ready`/`safe_message`：
  - 正常：`tracking_id=trk_…`、`tracking_status=PENDING_SUBMIT…`、`tracking_ready=true`、
    `safe_message=null`；
  - tracking 写失败：**不回滚已确认 Request**，也不伪造 tracking 状态——
    `tracking_ready=false`、`tracking_status=null`、固定中文 `safe_message`
    「方案已保存，追番列表将在打开时自动恢复」，后续打开列表/详情、终态重放或任何 accept
    入口都会再次 ensure 补偿。
- 批量 save-confirm 逐条返回 `tracking_id`/`tracking_status`/`tracking_ready`；单条 tracking
  写失败不失败 HTTP、也不回滚同批其他已确认条目。
- 确认后的“下一步”统一为 OPEN_TRACKING；统一的追番列表/详情/revalidate/submit/retry/recover
  入口见 M13 与 `docs/MiGuOrca_stage29_unified_tracking_PRD.md`。

## 9. Stage 32 B-D 契约收尾（已完成）

Stage 32 已完成保存确认与旧 accept/preview 入口的兼容演练、严格 OpenAPI/生成客户端同步及安全泄漏门禁。
确认只进入已保存的 `ACCEPTED`/待提交状态；外部提交仍需独立显式确认，结果未知必须走既有恢复流程。
