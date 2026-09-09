# M12 日志与错误处理模块 PRD

## 1. 模块目标

为流程提供足够的运行诊断和稳定的错误输出，不让日志基础设施主导 Stage 1。

## 2. Stage 1 边界

负责：

- 使用 Python 标准库 `logging` 初始化日志；
- CLI 默认输出控制台日志；
- 在用户显式指定时写入日志文件；
- 将可预期业务失败表达为 ErrorResult。

不负责：

- 独立 logging engine；
- 每次运行强制创建日志文件；
- 错误码注册表、日志平台、告警和自动重试；
- 业务规则和记录点的自动判断。

## 3. ErrorResult

```json
{
  "error_type": "rss_parse_failed",
  "error_message": "RSS 中没有有效条目",
  "failed_step": "parse_rss",
  "details": {}
}
```

ErrorResult 独立于 Request。Stage 1 不通过 `FAILED` Request 表达流程失败。

## 4. 规则

1. 默认日志级别为 INFO。
2. CLI 默认使用控制台 handler。
3. `--log-file` 提供路径时增加文件 handler。
4. engine 不自行初始化全局日志。
5. 日志写入失败不得掩盖原始业务错误。
6. 意外异常在入口边界转换为 ErrorResult，并保留可诊断日志。

## 5. 验收

1. CLI 正常运行时可以输出必要日志。
2. 未指定日志文件时不产生运行文件。
3. 指定日志文件时能够写入。
4. 业务失败返回稳定的 ErrorResult 结构。

## 6. 后续阶段

集中式日志、结构化日志、运行 ID、错误码和外部告警只有在出现明确运维需求后再设计。

## 7. Stage 23 媒体与提前停止错误边界（已完成）

1. 封面下载超时、超限、非图片、来源拒绝、重定向拒绝、缓存读写和清理失败均使用稳定类别；用户态只显示占位，不回显原始图片 URL、目标 IP、响应体或缓存路径。
2. 图片失败不得把候选搜索或页面请求整体标记失败；日志只记录 opaque key、稳定 category 和必要状态码。
3. MiKan 搜索提前停止需要可诊断的“标记命中/安全 fallback”测试指标，但生产日志不得记录原始 HTML 或完整搜索 URL。
4. 缓存清理失败不掩盖业务响应，也不得扩大删除范围重试。

## 8. Stage 24 AutoBangumi 错误边界（已完成）

1. 区分配置校验、认证失败、连接失败、超时、协议不兼容、筛选规则不可表达和写入失败；只返回稳定类别与必要安全状态码。
2. base_url、username、password、token、Cookie、Authorization header、原始响应体和完整失败 URL不得进入错误 details、日志或 trace。
3. 登录/状态探测失败不得继续写入；未知版本或未证明的写契约必须 fail closed。
4. 外部写结果不确定时继续使用 `SUBMITTING` / `RESULT_PERSIST_FAILED` 人工恢复，不自动重试。

## 9. Stage 25 标题解析错误边界（已完成）

1. 区分输入校验、季数冲突/越界、解析失败、单条查询失败、全部查询失败和正常空候选。
2. provider/规则异常只返回稳定类别、字段、来源类别、输入长度和 recoverable，不回显异常原文或完整输入。
3. 查询数量与长度必须有界；单条查询失败可继续 fallback，但全部失败不得伪装为 EMPTY。
4. endpoint、token、Cookie、Authorization、raw HTML/RSS、原始响应、完整失败 URL和本地绝对路径不得进入解析/API/UI/log/trace。
5. 非第一季确认失败、冲突和非法海报 URL只返回稳定类别；不得回显客户端 aliases、海报 URL、凭据或外部响应。

## 10. Stage 29 tracking 错误边界（已完成）

Stage 29（US-223～US-226）为统一追番 API 增加稳定的 tracking 错误分类并继续执行安全细节边界：

1. HTTP 分类固定（§14）：`tracking_not_found` → 404；`tracking_revision_conflict` /
   `tracking_state_conflict` / `tracking_operation_in_progress` /
   `tracking_idempotency_conflict` → 409（details 只含 field/current_revision/current_status/
   固定 reason）；`tracking_confirmation_required` → 400；`tracking_storage_error` /
   `tracking_migration_error` → 500。NEEDS_RECONFIRM/SUBMIT_FAILED/VERIFYING_EXTERNAL/
   RECOVERY_REQUIRED 是已落盘业务结果，用 HTTP 200 result，不伪装成传输错误。
2. migration manifest 只暴露时间窗与安全计数（created/existing/recovery_required/unreadable）；
   PARTIAL 只返回固定中文 warning，绝不回显文件名、路径、request id 或原始 JSON/解析错误。
3. TrackingRecord/operation/manifest 与 DTO 全部默认拒绝、严格白名单；损坏文件不自动删除、
   覆盖或回显。
4. `ab_config`、endpoint、凭据、上游响应、完整 URL、magnet、绝对路径、raw RSS/HTML 与
   traceback 不得进入 tracking 错误、审计事件、日志、截图或 trace。

## 11. Stage 30 外部同步错误边界（已完成）

capability 未知、版本不支持、管理读取失败和 sync 部分失败只返回固定 error type、safe counts
与 capability state；不得把读取失败当空列表，也不得回显上游 URL、Cookie、token、账号、密码、
header、原始响应或 RSS URL。`VERIFY_EXTERNAL` 的无匹配/歧义保持 `RECOVERY_REQUIRED`，不伪装成
可重试失败；未知外部写结果的 `RECOVERY_REQUIRED` 规则留给 B-C2。

## 12. Stage 31 外部管理写错误边界（已完成）

Stage 31 将 capability/校验/认证/明确 4xx 分类为确定失败；timeout、连接中断、5xx、未知响应与写后
回查失败保持 `VERIFYING_EXTERNAL` 或 `RECOVERY_REQUIRED`，使用固定中文安全消息，不回显 URL、凭据、
外部 ID、方法、路径、body 或原始响应。恢复只核验原 operation，不创建新幂等 key 或重复写入。
