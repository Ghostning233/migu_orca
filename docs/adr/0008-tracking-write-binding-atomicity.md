# 追番写路径的绑定原子性与孤儿 operation 认领

一次外部写（提交、重试、主动重发、管理写）在磁盘上涉及两个文件：幂等键对应的 `TrackingOperation` 与 `TrackingRecord` 的记录指针 `current_operation_id`。两者不在同一个文件里，也不存在跨文件事务。进程如果在「operation 已落盘、记录指针未写」或「指针已写、operation 仍 `PREPARED`」之间退出，就会留下一条**没有任何活记录指向、也永远不会被执行**的 `PREPARED` operation（#247）。

复现确认了两种路径的不同表现：

- **submit 路径（提交/重试/主动重发）**已有 PREPARED resume：同一幂等键重放会在记录仍处于可提交状态时恢复该 operation，外部调用恰好一次。`tracking_idempotency_conflict` 只在客户端换了 revision/请求语义时出现，属幂等绑定的正常语义。
- **management 路径**对「已存在且非 `IN_PROGRESS`」的绑定一律 409：崩溃后同一意图（同键）永远无法继续，换新键会把孤儿文件留在磁盘上；「指针已写、operation 仍 `PREPARED`」同样卡死。前端在未决意图里会复用同一 key，因此这是用户可见的死胡同。

本决策同时做两件事：把绑定与指针写入放进同一个进程临界区（a），并为仍然会被进程崩溃打断的落盘序列提供一条可核验的认领规则（b）。单独的 a 不能消除跨文件崩溃窗口：锁只在进程存活期间有效。

## 决策

1. **写路径的顺序不变量。** 一次外部写严格按此顺序落盘：`bind`（`PREPARED` operation）→ 记录指针 + `SUBMITTING`/管理审计（同一次记录 CAS）→ operation `PREPARED → IN_PROGRESS` → 调用外部系统。外部调用只在 `IN_PROGRESS` 已持久化之后发生；状态机禁止从终态回到 `PREPARED`。因此一条 `PREPARED` operation 能证明外部调用从未发生——这是认领的安全证明，而不是时间戳。
2. **锁顺序固定为 `批量 store 锁 → per-record → per-key（operation）`，operation 锁最后。** 所有 tracking 写者（`ensure`/CAS/删除）本来就先取进程级 store 锁（ADR-0007 的 `_BATCH_LOCK`、`_serialized_tracking_write`），因此 `lock_tracking_record` 也必须先取它再取 per-record 锁，仓内只有这一个方向；反序会与正在运行的批量/普通写者形成 ABBA 死锁。单条写等待运行中的批次（ADR-0007），不会在"已持久化意图"之后被拒绝。同类多把锁按稳定 id 排序；持锁期间不调用任何外部服务（Auto Bangumi、MiKan、qBittorrent）。临界区内只有本地 JSON 读写，因此额外持有 store 锁的时间只覆盖几次本地写。
3. **绑定与指针写入在同一个记录临界区内完成。** `bind` + 记录指针 CAS（submit 的 `SUBMITTING`、管理的指针与审计）以及 `PREPARED → IN_PROGRESS` 门都在这一个临界区里，因此同一进程内两个重试者不可能同时取得执行权；真实执行权仍由 `PREPARED → IN_PROGRESS` 的 CAS 唯一裁定，输者得到既有的冲突错误且不调用外部。
4. **认领规则（claim）必须证明「这是本次失败的残留」，而不只是"没有指针 + `PREPARED`"。** 认领前的绑定核对：submit 侧由 `bind_tracking_operation` 的校验确认同一幂等键、同一 `tracking_id`、同一连接、同一动作、同一请求语义与同一记录 revision；management 侧在锁前的早期检查已用内联 `same_binding` 核对同样字段，锁内再由 `bind_tracking_operation` 复核；`claimable_prepared_operation` 再确认三种可恢复形态：
   - `POINTER_EMPTY`：指针从未写入，记录必须恰好停在绑定 revision；
   - `POINTER_MATCHES`：指针已指向本 operation（指针写入推进了 revision），记录必须在 `expected_revision + 1` 或之后；
   - `POINTER_PREVIOUS`：ADR-0002 的风险确认重发仍指向它要替换的待确认 operation（`previous_operation_id` 是绑定的一部分），记录停在绑定 revision。
   指针指向任何**无关** operation 一律拒绝。``allowed_statuses`` 由调用方按该动作允许的起始状态提供（管理路径由 `management_action_allowed` 反推集合），谓词本身不自带动作策略。`updated_at == created_at` 只作为辅助损坏检查，不构成安全证明；`external_result_id` 非空、schema 版本不符、记录状态已离开该动作允许的起始状态、`previous_tracking_status` 不匹配、operation 从未落盘的形态同样拒绝。
5. **认领 = 补齐/沿用它自己的指针，不是重绑。** 认领沿用原 operation id、原幂等键、原连接与原请求语义；`POINTER_EMPTY` 补齐指针（submit 补 `SUBMITTING` + 审计，management 补指针 + 审计），`POINTER_MATCHES` 不再写第二份指针/审计。`POINTER_PREVIOUS`（风险确认重发）本来就要把指针从被替换的待确认 operation 移到新 operation 并写 `SUBMIT_STARTED` 审计——这是重发绑定本身，不是重复写；它不属于"沿用同一指针"的形态。无法认领的残留维持 fail closed（409），不新建 operation、不改绑、不清洗、不重发。
6. **孤儿 operation 保留为证据，不做 GC。** 未被复用的 `PREPARED` 文件留在磁盘上；`operation_repository.diagnose_prepared_binding` 提供只读诊断（纯函数、非公开端点、无公开路由），报告形态（`POINTER_EMPTY`/`POINTER_MATCHES`/`POINTER_PREVIOUS`/`POINTER_OTHER`/`NOT_PREPARED`）、脱敏的 operation/tracking 标识、记录与绑定 revision、稳定 reason code、**首个阻断原因**（`SCHEMA_MISMATCH`/`TIMESTAMP_MISMATCH`/`PREVIOUS_STATUS_MISMATCH` 等，避免把 `POINTER_*` 形态误读为可认领），并固定 `retry_authorized: false`。诊断只解释残留，永远不授权重发；授权只来自第 4 条的谓词。运维入口是内部脚本/REPL 直接调用该纯函数，不新增端点。
7. **不改变的范围。** 不新增公开端点；不改外部写、删除/放弃语义与 #223 的批次租约/顺序执行；submit 的 `tracking_idempotency_conflict` 语义与「不改绑旧 operation」保持不变。

## 后果

- 单进程内同一记录的绑定、指针与执行门是串行的；不同记录仍可并发（per-record 锁），只有 store 锁这一小段本地写全局排队。
- **非崩溃的异常补偿不在认领范围内**：管理路径在指针已写、operation 门 CAS 失败时用 `_compensate_prepared_start` 把 operation 置 `FAILED` 并清空指针；该 key 之后仍会得到确定性冲突，用户需要以新的意图（新 key）重试。这是既有行为，本决策不放宽。
- submit 路径对"无法证明可安全恢复"的残留返回 `tracking_state_conflict`（带 `reason=unclaimable_prepared_operation`）；并发的败者、记录被并发改写等仍按既有契约返回 `tracking_operation_in_progress`。两类错误都在 submit 端点既有错误集内，前端按同类冲突处理。
- management 路径的既有错误类型有一处同类迁移：旧实现对"同键但 revision 不同"的任何已存在绑定都报 `tracking_idempotency_conflict`；现在只有终态回放保持该语义，`IN_PROGRESS` 报 `tracking_management_state_conflict`，`PREPARED` 的 revision 差异走认领或 `tracking_revision_conflict`。三者都是 409、都在管理端点既有错误集内，前端按同类冲突处理。
- 单条写现在从 bind 之前就持有 store 锁，直到绑定、指针与执行门完成；因此一次单条写的 store 锁窗口覆盖三次本地 JSON 写。并发批次租约（10s 有界等待）在极慢磁盘下更可能超时得到 `connection_in_use`（可重试、无数据损失），这是 ADR-0007 既有的拒绝语义，不是新的失败模式。
- 进程崩溃后，同一意图用原幂等键重试即可继续；不会出现第二个外部调用，也不会产生重复的指针写或审计。
- 无法证明安全性的残留（指针被别人接管、记录已推进、operation 被 transition 过、时间戳异常）继续报冲突，由用户以新意图重新发起；系统不会替它重发。
- 诊断能力是运维/排障工具，不进入公开 API；将来若要自动化清理，必须先在本 ADR 之外重新设计可核验的清理规则。

## 参考

- [ADR-0002](0002-risk-confirmed-manual-resubmission.md)：风险确认的主动重发，`previous_operation_id` 的来源。
- `src/storage_engine/controllers/tracking_repository.py`：`lock_tracking_record` 与锁顺序说明。
- `src/storage_engine/controllers/operation_repository.py`：`claimable_prepared_operation`、`diagnose_prepared_binding`。
- `src/apps/migu_orca_web/tracking_submission_service.py`、`tracking_management_service.py`：两条写路径的临界区实现。
