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
