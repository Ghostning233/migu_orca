# M10 Auto Bangumi 集成模块 PRD

## 1. 模块目标

M10 负责后续阶段的 Auto Bangumi 集成能力。用户接受 Request 后，系统通过本模块调用 AB 创建订阅；如果调用失败，则生成可人工处理的降级 JSON 配置。

第一阶段不实现本模块。本模块用于承接 AB 提交和降级配置需求。

## 2. 模块边界

本模块负责：

1. 管理 AB 调用所需字段映射。
2. 调用 AB 创建订阅。
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
| ab_config | object | 是 | AB 地址、认证等系统配置 |
| fallback_enabled | bool | 否 | 是否允许生成降级配置 |

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
    "error_code": "AB_SUBMIT_FAILED",
    "error_message": "Auto Bangumi 提交失败"
  }
}
```

## 5. 核心流程

1. 接收已接受的 Request。
2. 从 confirmable_config 中读取选中 RSS、文件夹名和筛选规则。
3. 读取 AB 系统配置。
4. 将 Request 映射为 AB 创建订阅所需字段。
5. 调用 AB。
6. 成功时返回订阅结果。
7. 失败时记录错误。
8. 如果允许降级，则生成 AB 降级 JSON。

## 6. 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| Q-M10-01 | AB 是否提供稳定 API？ | 是 | 待验证 |
| Q-M10-02 | AB 创建订阅需要哪些字段？ | 是 | 待验证 |
| Q-M10-03 | AB 是否需要认证？ | 是 | 待验证 |
| Q-M10-04 | 创建订阅后如何确认成功？ | 是 | 待验证 |
| Q-M10-05 | AB 降级 JSON 的 schema 如何定义？ | 是 | 待定义 |
| Q-M10-06 | AB 调用失败是否需要重试？ | 否 | 默认不自动重试 |

## 7. qBittorrent 边界

本项目后续阶段原则上不直接调用 qBittorrent。qBittorrent 由 AB 间接管理。

如后续需要绕过 AB 直接调用 qBittorrent，应新增独立集成模块或扩展本模块边界。
