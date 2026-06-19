# M12 日志与错误处理模块 PRD

## 1. 模块目标

M12 负责为第一阶段 Request 生成链路提供统一日志能力和基础错误表达，帮助开发、排错和后续验收。

日志系统是第一阶段最高优先级的开发模块。所有模块都应基于 M12 进行日志管理，避免各模块自行实现日志写入、日志格式和控制台输出。

M12 必须提供易用的库接口，便于 M00-M14 各模块直接调用日志系统记录运行过程、关键状态和异常信息。

第一阶段业务模块记录日志时，只需要提供 `event_name`、`level`、`message` 三个字段。模块名、调用位置、时间戳、日志文件路径等运行时信息由 M12 自动补齐。

## 2. 模块边界

本模块负责：

1. 提供统一日志库接口。
2. 定义日志记录字段。
3. 统一管理日志文件创建、写入和控制台输出。
4. 为关键流程步骤提供可观测事件。
5. 输出基础可读错误信息。
6. 自动补齐日志运行时元信息。

本模块不负责：

1. 业务规则决策。
2. 自动重试。
3. 外部告警系统。
4. 日志分析平台。
5. 自动判断业务上应该在哪里记录日志。

## 3. 输入数据

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| event_name | string | 是 | 日志事件名 |
| level | string | 是 | 日志级别 |
| message | string | 是 | 可读消息 |

M12 自动补齐字段：

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| timestamp | M12 运行时 | 日志记录时间 |
| logger | M12 运行时 | 固定为 migu_orca |
| module | 调用方模块或 logger 绑定信息 | 例如 M00、M04 |
| caller | M12 运行时 | 调用位置，包含文件、函数或行号，具体精度由技术实现决定 |
| log_file | M12 运行时 | 本次运行对应的日志文件 |

## 4. 输出数据

日志记录结果和基础错误对象。

```json
{
  "error_message": "RSS 格式解析失败",
  "error_type": "rss_parse_failed",
  "failed_step": "parse_rss",
  "details": {}
}
```

## 5. 核心流程

1. 接收业务模块提交的日志事件。
2. 标准化日志字段。
3. 将日志写入本次运行对应的日志文件。
4. 默认同时将日志输出到控制台。
5. 接收异常并转换为基础错误对象。
6. 将错误对象返回给调用方。

## 6. 规则定义

1. 日志系统是最高优先级开发模块，其他模块必须通过 M12 提供的库接口记录日志。
2. 日志名沿用主 PRD：migu_orca。
3. 日志必须落盘到项目 `logs/` 目录。
4. 默认同时输出到控制台。
5. 日志格式为纯文本。
6. 项目每次运行都按启动时间新生成一个日志文件。
7. 单次运行的所有模块日志都写入同一个日志文件。
8. 日志级别使用 DEBUG、INFO、WARNING、ERROR。
9. 失败场景记录原因，但不自动重试完整流程。
10. 第一阶段不建立错误码系统，不维护全局错误码注册表。
11. M12 可以自动补齐调用位置，但不能自动理解业务流程中哪些节点需要记录日志。
12. 关键业务记录点仍由各模块在对应流程处显式调用 M12。

## 7. 异常场景

| 场景 | 处理方式 |
| --- | --- |
| 日志写入失败 | 不应导致主流程崩溃，需返回或记录降级信息 |
| 错误对象缺必要字段 | 使用可读默认消息补齐 |
| 自动调用位置获取失败 | 使用 unknown caller，不影响日志写入 |
| 未知异常 | 包装为基础错误对象并记录异常摘要 |

## 8. 数据结构

### 8.1 ErrorResult

```json
{
  "error_message": "未知错误",
  "error_type": "unknown_error",
  "failed_step": "generate_request",
  "details": {}
}
```

### 8.2 LogEvent

```json
{
  "timestamp": "2026-06-18T00:00:00+08:00",
  "level": "INFO",
  "logger": "migu_orca",
  "module": "M00",
  "caller": "m00_entry.generate_request",
  "event_name": "request_generation_started",
  "message": "开始生成 Request"
}
```

### 8.3 LogRuntime

```json
{
  "logger": "migu_orca",
  "log_dir": "logs/",
  "log_file": "logs/migu_orca_20260619_153000.log",
  "console_enabled": true,
  "format": "plain_text"
}
```

## 9. 接口定义

```text
init_logger(log_dir = "logs/", console_enabled = true, level = "INFO") -> logger
log_event(event_name, level, message) -> void
debug(event_name, message) -> void
info(event_name, message) -> void
warning(event_name, message) -> void
error(event_name, message) -> void
build_error(message, failed_step = null, details = null, error_type = null) -> error_result
```

## 10. 验收标准

1. 所有第一阶段模块都能通过 M12 库接口记录日志。
2. 每次运行都会在 `logs/` 下生成一个新的纯文本日志文件。
3. 单次运行内所有模块日志都写入同一个日志文件。
4. 默认同时输出日志到控制台。
5. 关键流程步骤能产生日志事件。
6. 关键失败能返回基础错误对象。
7. 日志写入失败不应掩盖原始业务错误。
8. 错误信息可供 M00 返回给用户或终端展示。
9. 第一阶段不要求外部告警或日志平台。
10. 业务模块调用日志接口时，最小输入只包含 `event_name`、`level`、`message`。
11. 日志输出中能自动包含时间、日志名、模块或调用位置等运行时元信息。

## 11. 已确认事项与待确认问题

### 11.1 已确认事项

| 编号 | 事项 | 当前结论 |
| --- | --- | --- |
| D-M12-01 | 日志输出位置 | 必须落盘到项目 `logs/`，默认同时输出到控制台 |
| D-M12-02 | 日志格式与文件策略 | 纯文本；每次运行按时间新建一个文件；单次运行所有日志写入同一文件 |
| D-M12-03 | 日志级别体系 | DEBUG、INFO、WARNING、ERROR |
| D-M12-04 | 错误码系统 | 第一阶段不加错误码系统，不维护全局错误码注册表 |
| D-M12-05 | 日志接口最小输入 | 业务模块只需传入 event_name、level、message |
| D-M12-06 | 日志记录点识别 | M12 可自动补齐调用位置，但业务记录点仍由各模块显式调用 |

### 11.2 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| 无 | 暂无 | 否 | - |
