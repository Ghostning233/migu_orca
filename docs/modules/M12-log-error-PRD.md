# M12 日志与错误处理模块 PRD

## 1. 模块目标

M12 负责为第一阶段 Request 生成链路提供统一日志和错误表达，帮助开发、排错和后续验收。

## 2. 模块边界

本模块负责：

1. 定义错误结构。
2. 定义日志记录字段。
3. 为关键流程步骤提供可观测事件。
4. 输出可读错误信息。

本模块不负责：

1. 业务规则决策。
2. 自动重试。
3. 外部告警系统。
4. 日志分析平台。

## 3. 输入数据

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| event_name | string | 是 | 日志事件名 |
| level | string | 是 | 日志级别 |
| request_id | string/null | 否 | Request ID |
| module | string | 是 | 模块编号 |
| message | string | 是 | 可读消息 |
| context | object | 否 | 结构化上下文 |

## 4. 输出数据

日志记录结果和统一错误对象。

```json
{
  "error_code": "RSS_PARSE_FAILED",
  "error_message": "RSS 格式解析失败",
  "module": "M04",
  "failed_step": "parse_rss",
  "request_id": "req_20260618_0001",
  "details": {}
}
```

## 5. 核心流程

1. 接收业务模块提交的日志事件。
2. 标准化日志字段。
3. 输出到目标位置。
4. 接收异常并转换为统一错误对象。
5. 将错误对象返回给调用方。

## 6. 规则定义

1. 第一阶段错误必须包含 error_code、error_message、module、failed_step。
2. 日志名沿用主 PRD：migu_orca。
3. 失败场景记录原因，但不自动重试完整流程。
4. 控制台只显示必要信息，详细信息进入日志，具体策略待确认。
5. 日志输出位置、格式、级别体系待确认。

## 7. 异常场景

| 场景 | 处理方式 |
| --- | --- |
| 日志写入失败 | 不应导致主流程崩溃，需返回或记录降级信息 |
| 错误对象缺必要字段 | 使用 UNKNOWN_ERROR 补齐 |
| context 不可序列化 | 转为字符串或丢弃，策略待确认 |
| 未知异常 | 包装为 UNKNOWN_ERROR |

## 8. 数据结构

### 8.1 ErrorResult

```json
{
  "error_code": "UNKNOWN_ERROR",
  "error_message": "未知错误",
  "module": "M00",
  "failed_step": "generate_request",
  "request_id": null,
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
  "request_id": "req_20260618_0001",
  "event_name": "request_generation_started",
  "message": "开始生成 Request",
  "context": {}
}
```

## 9. 接口定义

```text
log_event(event) -> void
build_error(error_code, message, module, failed_step, request_id = null, details = null) -> error_result
```

## 10. 验收标准

1. 关键流程步骤能产生结构化日志事件。
2. 关键失败能返回统一错误对象。
3. 日志写入失败不应掩盖原始业务错误。
4. 错误信息可供 M00 返回给用户或终端展示。
5. 第一阶段不要求外部告警或日志平台。

## 11. 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| Q-M12-01 | 日志输出位置是项目 logs/、配置目录，还是控制台？ | 是 | 暂按文件加必要控制台信息 |
| Q-M12-02 | 日志格式是纯文本还是 JSON Lines？ | 是 | 待确认 |
| Q-M12-03 | 日志级别体系使用哪些级别？ | 是 | 暂按 DEBUG、INFO、WARNING、ERROR |
| Q-M12-04 | 错误码是否需要全局注册表？ | 是 | 建议需要，但未定稿 |
