# M11 存储与状态管理模块 PRD

## 1. 模块目标

M11 负责 Request、状态历史、用户操作历史、AB 调用结果和降级配置的持久化。Stage 6 已实现本地 JSON 存储，默认流程仍不写入；只有 CLI 或 Web API 显式传入保存参数时才落盘。

## 2. 模块边界

本模块负责：

1. 持久化 Request。
2. 记录 Request 状态历史。
3. 记录用户修改、接受、取消等操作历史。
4. 记录 AB 调用结果。
5. 保存 AB 降级配置生成结果。
6. 提供 Request 查询和恢复能力。

本模块不负责：

1. Request 字段结构定义。
2. 用户交互。
3. AB 调用。
4. RSS 拉取和解析。
5. 日志系统。

## 3. 存储范围

后续阶段至少需要存储：

1. Request。
2. Request 状态。
3. 用户修改历史。
4. 用户偏好配置引用或快照。
5. 番剧简称配置引用或快照。
6. 字幕组简称配置引用或快照。
7. AB 调用结果。
8. AB 降级配置生成结果。
9. 用户配置文件。

日志不作为普通业务数据混入 Request 存储，应由 M12 独立记录。

## 4. 存储方案

后续持久化阶段优先使用本地 JSON 文件，暂不接入数据库系统。

可选方案：

1. 本地 JSON 文件。
2. SQLite。
3. PostgreSQL。
4. 其他轻量数据库。

数据库方案作为后续扩展，不进入第一阶段。

## 5. 运行数据目录

运行数据目录用于保存 Request、状态历史、AB 调用结果和降级配置。

具体目录结构待技术设计确认。

## 6. 已实现能力（Stage 6 / Stage 15）

Stage 6 已落地本地 JSON 存储：`requests/<request_id>.json` 保存 Request snapshot，`history/` 保存状态历史，`ab_results/` 保存 AB 提交结果。只有 CLI 或 Web API 显式传入保存参数时才写入。

Storage request repository（`src/storage_engine/controllers/request_repository.py`）自 Stage 15 起提供以下 path-safe 能力：

- `save_request_snapshot`：按 `request_id` 保存 Request snapshot。
- `load_request_snapshot`：按 `request_id` 读取完整 snapshot。
- `list_request_snapshots`：列出已保存 Request 摘要。
- `delete_request_snapshot`：按 `request_id` 删除 `requests/<request_id>.json`，返回安全摘要 `{request_id, storage, directory, filename, deleted}`，不返回被删除 snapshot 内容。

删除安全性约定：

- 所有派生路径的函数通过共享 `_request_path` 校验 `request_id`：拒绝空值、路径片段和路径穿越。
- 删除不存在的 Request 返回稳定 `request_not_found` 错误，不泄露本地绝对路径；unlink 失败映射为脱敏的 `storage_error`。
- 删除只移除 `requests/<request_id>.json`；history 与 ab_results 文件暂不随删除清理，Request 文件缺失后详情加载返回 `request_not_found`。

## 7. 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| Q-M11-01 | 本地 JSON 存储目录放在哪里？ | 是 | Stage 6 已确认：默认项目下 `.migu_orca/storage`，可由 `--storage-dir` 覆盖 |
| Q-M11-02 | Request 状态历史是否单独存储？ | 是 | Stage 6 已确认：按 `request_id` 独立存储于 `history/` |
| Q-M11-03 | 用户修改历史需要记录哪些字段？ | 是 | 已确认：`user_action`、`previous_status`、`next_status` 等 |
| Q-M11-04 | 是否需要 Request 过期和清理策略？ | 否 | 第一版可手动清理；Stage 15 已提供显式删除入口 |
| Q-M11-05 | 是否需要迁移到 SQLite？ | 否 | 后续扩展 |
