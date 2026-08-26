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

## 9. Stage 25 标题解析错误边界（已规划）

1. 区分输入校验、季数冲突/越界、解析失败、单条查询失败、全部查询失败和正常空候选。
2. provider/规则异常只返回稳定类别、字段、来源类别、输入长度和 recoverable，不回显异常原文或完整输入。
3. 查询数量与长度必须有界；单条查询失败可继续 fallback，但全部失败不得伪装为 EMPTY。
4. endpoint、token、Cookie、Authorization、raw HTML/RSS、原始响应、完整失败 URL和本地绝对路径不得进入解析/API/UI/log/trace。
