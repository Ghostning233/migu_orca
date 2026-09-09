# M10 Auto Bangumi 集成模块 PRD

## 1. 模块目标

M10 负责后续阶段的 Auto Bangumi 集成能力。用户接受 Request 后，系统通过本模块调用 AB 创建订阅；如果调用失败，则生成可人工处理的降级 JSON 配置。

Stage 3 已完成本模块的离线可测契约：AB 提交结果 envelope、Request 到 AB payload 映射、fake client、失败降级 JSON、显式 AB 配置读取和 CLI 显式提交流程。Stage 4 已在这些契约上实现真实 Auto Bangumi HTTP client adapter。

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
5. qBittorrent 直接调用或连接测试。

## 3. 输入数据

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| request | object | 是 | 已被用户接受的 Request |
| ab_config | object | 是 | AB 地址、认证和降级开关等系统配置 |
| fallback_enabled | bool | 否 | 是否允许生成降级配置 |

当前 AutoBangumi 配置是 request-scoped 的双认证契约。默认账号密码模式：

```json
{
  "auth_mode": "password",
  "base_url": "http://auto-bangumi.local",
  "username": "replace-with-username",
  "password": "replace-with-password",
  "fallback_enabled": true
}
```

兼容 API Token 模式使用 `auth_mode: "api_token"`、`base_url` 和 `token`；两组凭据互斥。`base_url` 只接受 HTTP(S) 服务根地址，adapter 自行拼接固定路径。用户名、密码、token、Cookie 和 Authorization 不得出现在日志、错误 details、测试快照或文档示例的真实值中。

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

1. 账号密码 adapter 以 form POST `/api/v1/auth/login` 登录，将返回 token 保持为单次 client Cookie；只读探测使用 `/api/v1/status`。
2. AutoBangumi 3.1.18 payload 由已接受 Request 纯函数映射为 `{data: Bangumi, rss: RSSItem}`，`status=true` 即成功，外部订阅 ID 可为空；不可无损表达的筛选规则会明确拒绝。
3. `api_token` adapter 仅用 Bearer 执行已验证的只读探测；在缺少逐版本写契约时 fail closed，绝不套用 3.1 payload。
4. AB client 暴露 `create_subscription(payload)`。
5. 所有 client 结果通过 `submit_ab_subscription(...)` 归一化为稳定 submit result envelope。
6. AB 调用失败可在 `fallback_enabled=true` 时生成 JSON 可序列化的 `fallback_config`。
7. 预期业务错误使用 `Stage1Error.as_dict()` 或兼容 ErrorResult 结构。

## 7. 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| Q-M10-01 | AB 是否提供稳定 API？ | 是 | 3.1.18 实机 OpenAPI 已确认；其他版本按 adapter 能力 fail closed |
| Q-M10-02 | AB 创建订阅需要哪些真实字段？ | 是 | Stage 24 对齐 3.1.18 `{data: Bangumi, rss: RSSItem}` |
| Q-M10-03 | AB 认证方式是否只需 token？ | 是 | 否；3.1.18 默认账号密码登录/Cookie，新版兼容 API Token/Bearer |
| Q-M10-04 | 创建订阅后如何确认成功？ | 是 | 3.1.18 使用 `status=true`，外部订阅 ID 可选；其他 adapter 独立定义 |
| Q-M10-05 | AB 降级 JSON 的 schema 如何定义？ | 否 | Stage 3 已有内部 fallback_config，后续可按真实 AB 导入能力调整 |
| Q-M10-06 | AB 调用失败是否需要重试？ | 否 | 默认不自动重试 |

## 8. qBittorrent 边界

M10 不直接调用 qBittorrent。Auto Bangumi 创建订阅后的下载行为仍由 AB 间接管理，不在本模块内实现。

Stage 12 已在独立 qBittorrent 边界中实现显式连接测试，用于验证用户临时提供的 qBittorrent Web API 配置。该能力不属于 M10，不创建下载任务，不创建订阅，也不改变 AB 提交流程。

如后续需要绕过 AB 直接调用 qBittorrent 启动下载或创建任务，应新增独立 Stage、独立验收标准和对应 Web UI 操作边界。

## 9. Stage 24 真实兼容契约（已完成）

1. 旧 `endpoint + Bearer token + {title,rss_url,save_path,filter_rule}` 不再是有效提交契约。
2. 默认 `password` adapter 接收服务根地址、用户名和密码：form 登录 `/api/v1/auth/login`，将返回 token 作为单次会话 Cookie，3.1.18 只读探测使用 `/api/v1/status`。
3. 3.1.18 写入使用 `/api/v1/rss/subscribe` 与 `{data: Bangumi, rss: RSSItem}`；`status=true` 表示成功，外部订阅 ID 可为空。
4. `api_token` adapter 使用 Bearer Header，但只有明确版本/契约证明后才允许写入；未知版本只能报告连接能力，不能猜测 payload。后续写兼容工作登记为 backlog BL-022，未满足触发条件前继续 fail closed。
5. 单个、批量、retry/recover 复用同一 adapter/payload/result seam，并保持 Stage 20 不重复提交边界。
6. 自动化只使用 fake transport；真实实例只允许只读烟雾，写入必须由用户在 Web UI 显式确认。

Stage 25 实际边界：标题 parser 的 season hint 不得直接进入 AutoBangumi payload。M10 只消费 accepted Request 中由真实候选公开标题/元数据或用户显式确认支持的 `season` / `season_raw`；冲突或无法证明的显式非第一季继续 fail closed。3.1.18 的可选 `data.poster_link` 只使用服务端校验过的 MiKan 原始公开 HTTP(S) 海报 URL；缺失时为空且不阻断订阅，opaque 代理地址或客户端字段绝不传播。

## 10. Stage 29 统一提交/恢复边界（已完成）

Stage 29（US-225/226）把“外部调用”收敛到一个可靠提交服务，M10 的 AB create seam 只作为默认
`submit_one` 被统一 submission service 复用，route 层不复制 payload/client/结果分类逻辑：

1. `apps/migu_orca_web/tracking_submission_service.py::run_tracking_submit/run_tracking_retry`
   是唯一入口：先纯本地 revalidate（不通过则不访问 AB），再持久化 TrackingRecord `SUBMITTING`
   与 operation `IN_PROGRESS`，之后才调用 AB create seam；结果经
   `tracking_engine/controllers/submit.py::classify_external_submit_result` 分类为
   SUCCEEDED/FAILED/OUTCOME_UNKNOWN（timeout/connection/5xx/未知 code 保守 UNKNOWN，4xx/auth/
   config 明确 FAILED），再写本地 AB result 与 tracking/operation 终态。
2. recover（US-226）只做纯本地证据核验：读 operation 状态与 Request 内脱敏 AB result，绝不访问
   Auto Bangumi；AUTO 无证据 → `RECOVERY_REQUIRED`，人工 `MARK_SUCCEEDED`/`MARK_FAILED` 必须
   `confirm=true` 且不接收外部 ID/URL/原始结果。
3. operation 永不保存 AB 配置、endpoint、凭据、上游响应、标题、URL、magnet 或路径；AB 结果只
   以安全白名单（success/公开 external id/固定 error_type）落盘。
4. Stage 29 **不实现** AB 订阅/RSS 的列表、详情、修改、启停、删除、刷新或 capability 探测
   （B-C）；旧 `submit-ab`/批量 submit/retry/recover 继续保留一个发布周期，删除由独立 PRD 决定。

## 11. Stage 30 B-C1 只读同步边界（已完成）

Stage 30 新增独立的 request-scoped management read adapter：password 模式一次登录并复用同源
Cookie，只读访问 status、bangumi list/detail 和 RSS list；3.1.18 以外版本与 API Token 管理读取
均 fail closed。capability 与 sync API 只返回严格安全投影，原始对象、URL、Cookie、凭据和响应体
不得落盘或进入错误/日志。`EXTERNAL_ONLY`、ExternalMapping v1、唯一对账和 `VERIFY_EXTERNAL`
不改变 Stage 29 的提交/恢复语义。B-C2 才能新增 `MODIFY`、`SET_ENABLED`、`DELETE_EXTERNAL`、
`REFRESH_RSS`，并必须具备 confirm、幂等键、revision CAS、结果未知恢复和 `file=false` 媒体保护。

## 12. Stage 31 B-C2 可靠写管理（已完成）

Stage 31 执行 PRD 为 `docs/MiGuOrca_stage31_ab_write_management_PRD.md`（US-237～US-246）。它只对
password + 精确 3.1.18 开放 `MODIFY`、`SET_ENABLED`、`DELETE_EXTERNAL`、`REFRESH_RSS`，统一经过
tracking ID、confirm、幂等 operation、revision CAS、写后只读回查和未知结果恢复。番剧停用与
删除由 adapter 固定 `file=false`；禁止真实实例测试、全局 RSS 刷新、批量外部删除、媒体删除和
正式前端页面。US-237～US-246 已完成，最终兼容与前端 handoff 由 Stage 32 B-D 独立收尾。
