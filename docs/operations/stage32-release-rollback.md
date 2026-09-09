# Stage 32 发布、升级与回退 runbook

本 runbook 只回退应用版本，不回滚业务数据。所有操作使用离线、临时的本地
storage 验证；不得连接真实 Auto Bangumi、MiKan 或 qBittorrent。

## 发布与升级

1. 停止新的外部写入入口，并等待正在处理的请求进入已落盘状态；不要删除或重置
   `tracking`、`tracking_operations`、`tracking_migrations`、`queue`、Request、审计、
   下载任务、目录或媒体。
2. 停止应用后，将整个 `.migu_orca/storage` 复制到只读备份位置。复制必须是新目录，
   备份完成后校验文件数量和内容，再启动目标版本。
3. 以前向版本启动时只执行现有的本地 schema migration。`PARTIAL` 可在输入修复后
   重试，`COMPLETE` 不需要重复扫描；未知版本和损坏文件必须保留并 fail closed。
4. 观察本地 tracking、operation、manifest 和 queue 的安全摘要。不要把凭据、URL、
   原始响应或本地绝对路径写入日志、审计或 API 响应。

## 回退

1. 停止新写并再次复制 storage；保留新版产生的所有文件，即使上一版本无法解析。
2. 切换应用代码到上一版本并启动只读检查。不要用删除 operation 或清空状态的方式
   让旧版本“恢复正常”。
3. `IN_PROGRESS`、`OUTCOME_UNKNOWN` 和 `RECOVERY_REQUIRED` 一律不自动重放外部写。
   `OUTCOME_UNKNOWN` 只能通过现有 `VERIFY_EXTERNAL` 收敛；`RECOVERY_REQUIRED` 只能
   通过现有 `RECOVER` 收敛。迁移中断只允许继续本地迁移。
4. 只有在人工核对 evidence、revision 和 capability 后，才恢复新写入口。外部结果
   不确定时保留原 operation 和 tracking 权威状态。

## 故障窗口演练矩阵

| 故障窗口 | 保留的状态 | 回退后的动作 | 自动外部重放 |
| --- | --- | --- | --- |
| 外部调用前落盘失败 | `FAILED` | 记录为未调用，可重新建立新意图 | 否 |
| 外部可能已执行 | `OUTCOME_UNKNOWN` | `VERIFY_EXTERNAL` | 否 |
| operation 已终态、record 未更新 | `RECOVERY_REQUIRED` | `RECOVER`，不降级 tracking | 否 |
| queue 投影失败 | `RECOVERY_REQUIRED` | 仅修复兼容投影 | 否 |
| migration 中断 | `RECOVERY_REQUIRED` | 继续本地 migration | 否 |

`src/storage_engine/controllers/rollback.py` 和对应测试提供了上述策略的离线
故障注入基线；测试只复制临时 storage 并比较原始 bytes，证明回退准备不会改写或
删除业务证据。
