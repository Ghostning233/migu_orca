# 真实 Auto Bangumi 测试支持环境

本文件只描述**流程约定**；端点、账号、密码等环境细节一律保存在本地 gitignored 位置，**不得进入仓库**。

## 配置来源（按顺序）

1. 环境变量：`MIGU_ORCA_TEST_AB_URL`、`MIGU_ORCA_TEST_AB_USERNAME`、`MIGU_ORCA_TEST_AB_PASSWORD`。
2. 本地 gitignored 文件：`.migu_orca/ab-test-instance.md`（人读）或同等本地配置。

两者都不入库。`.migu_orca/` 已在 `.gitignore` 中；`ab-test-instance.md` 是测试支持配置，**不是运行数据**，
清理 `.migu_orca/storage` 时不要连带移走它。

## 使用规则

- 默认测试仍使用 fake transport，**不隐式连真实服务**；真实 AB 只用于已授权工作包内的定向验证。
- 需要真实测试但**服务未启用**（探测 `GET /api/v1/status` 失败，例如连接被拒绝）时，
  **向用户请求启动 Auto Bangumi 服务**，不要自行降级为假证据、也不要用伪造响应替代真机记录。
- 写入类验证（创建订阅、`POST /api/v1/rss/collect`、管理写）必须属于**已授权**的工作包，
  并在收尾时**清理自己产生的订阅/规则/任务**，把清理步骤写进验收记录。
- 用户明确要求：可以正常测试，但**不要对这个服务瞎搞**（不做破坏性批量操作、不清空既有规则与下载）。
- 不得把端点、账号、密码、Cookie、原始响应、完整 RSS URL、magnet 或本地绝对路径写进任何入库文件、
  业务 JSON、日志、截图或 trace。

## 本仓库已知的真实契约要点（供测试断言使用）

真实 3.1.18（本环境实测版本 `3.1.18`）：

- `GET /api/v1/status` → `{"status": true, "version": "3.1.18", "first_run": false}`（**只有这个读端点带 `status`**）。
- 写端点响应体恒为 `{"msg_en": …, "msg_zh": …}`，结果在 HTTP 状态码上；成功判定为精确 `200`。
- `POST /api/v1/rss/collect` 的 requestBody 是**裸 `Bangumi`**（不套 `data`）。
- 详细证据见相关 Issue（写入判据票与 collect 接入票）。
