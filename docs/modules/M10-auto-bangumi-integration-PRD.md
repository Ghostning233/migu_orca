# M10 Auto Bangumi 集成模块 PRD

## 1. 模块目标

M10 负责后续阶段的 Auto Bangumi 集成能力。用户接受 Request 后，系统通过本模块调用 AB 创建订阅；如果调用失败，则生成可人工处理的降级 JSON 配置。

Stage 3 已完成本模块的离线可测契约：AB 提交结果 envelope、Request 到 AB payload 映射、fake client、失败降级 JSON、显式 AB 配置读取和 CLI 显式提交流程。Stage 4 将在这些契约上实现真实 Auto Bangumi HTTP client adapter。

## 2. 模块边界

本模块负责：

1. 管理 AB 调用所需字段映射。
2. 通过统一 client 协议调用 AB 创建订阅。
3. 处理 AB 调用成功、失败和异常响应。
4. 创建失败时生成降级 JSON 配置。
5. 返回 AB 调用结果给 M01/M11。

本模块不负责：

1. Request 生成。
2. RSS 解析。
3. 种子筛选。
4. 用户确认交互。
5. qBittorrent 直接调用。

## 3. 输入数据

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| request | object | 是 | 已被用户接受的 Request |
| ab_config | object | 是 | AB 地址、认证和降级开关等系统配置 |
| fallback_enabled | bool | 否 | 是否允许生成降级配置 |

当前 AB config JSON 最小字段：

```json
{
  "endpoint": "http://auto-bangumi.local",
  "token": "replace-with-token",
  "fallback_enabled": true
}
```

`token` 不得出现在日志、错误 details、测试快照或文档示例的真实值中。

## 4. 输出数据

```json
{
  "success": true,
  "ab_subscription_id": "ab_sub_001",
  "ab_response": {},
  "fallback_config": null,
  "error": null
}
```

失败并生成降级配置时：

```json
{
  "success": false,
  "ab_subscription_id": null,
  "ab_response": null,
  "fallback_config": {},
  "error": {
    "error_type": "ab_submit_failed",
    "error_message": "Auto Bangumi 提交失败",
    "failed_step": "create_ab_subscription",
    "details": {}
  }
}
```

## 5. 核心流程

1. 接收已接受的 Request。
2. 从 confirmable_config 中读取选中 RSS、文件夹名和筛选规则。
3. 读取 AB 系统配置。
4. 将 Request 映射为 AB 创建订阅所需字段。
5. 通过 AutoBangumiClient 协议调用 AB。
6. 成功时返回订阅结果。
7. 失败时记录错误。
8. 如果允许降级，则生成 AB 降级 JSON。

当前 Stage 3 的 CLI 行为：

```bash
uv run migu-orca "番剧名" --action accept --submit-ab --ab-config config/user/ab-config.example.json
```

未显式传入 `--submit-ab` 时，生成和确认流程不得访问 Auto Bangumi。Stage 3 的 CLI 提交路径使用 `FakeAutoBangumiClient`，Stage 4 需要替换为真实 HTTP adapter，同时保留测试注入 fake client 的能力。

## 6. 已实现契约

1. AB payload 内部字段为 `title`、`rss_url`、`save_path`、`filter_rule`。
2. AB client 暴露 `create_subscription(payload)`。
3. 所有 client 结果通过 `submit_ab_subscription(...)` 归一化为稳定 submit result envelope。
4. AB 调用失败可在 `fallback_enabled=true` 时生成 JSON 可序列化的 `fallback_config`。
5. 预期业务错误使用 `Stage1Error.as_dict()` 或兼容 ErrorResult 结构。

## 7. 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| Q-M10-01 | AB 是否提供稳定 API？ | 是 | Stage 4 通过真实 HTTP adapter 验证 |
| Q-M10-02 | AB 创建订阅需要哪些真实字段？ | 是 | Stage 3 已有内部 payload，Stage 4 映射到真实 API |
| Q-M10-03 | AB 认证方式是否只需 token？ | 是 | Stage 4 验证 |
| Q-M10-04 | 创建订阅后如何确认成功？ | 是 | Stage 3 支持从 `id`、`subscription_id`、`ab_subscription_id` 读取，Stage 4 需对齐真实响应 |
| Q-M10-05 | AB 降级 JSON 的 schema 如何定义？ | 否 | Stage 3 已有内部 fallback_config，后续可按真实 AB 导入能力调整 |
| Q-M10-06 | AB 调用失败是否需要重试？ | 否 | 默认不自动重试 |

## 8. qBittorrent 边界

本项目后续阶段原则上不直接调用 qBittorrent。qBittorrent 由 AB 间接管理。

如后续需要绕过 AB 直接调用 qBittorrent，应新增独立集成模块或扩展本模块边界。
