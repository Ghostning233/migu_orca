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

Stage 18 补充：

- Web API `POST /api/v1/requests/preview-save` 通过 `apply_request_save_action` 复用 `save_request_snapshot` 持久化 `PENDING_CONFIRM` 预览草案；保存后的对象进入现有待确认流程，可继续确认/取消/修改/删除。
- Request、history 与 AB result repository 的用户可见 `error_message` 已中文化（例如「未找到已保存的订阅方案」「保存/读取/删除/列出订阅方案 JSON 失败」），内部字段名、错误 type 和 API 字段保持不变。

## 7. Stage 23 封面缓存（已完成）

1. 已新增与业务 Request storage 分离的 poster cache 目录；目录由应用配置解析，客户端和外部响应不能控制本地路径。
2. cache key 使用规范化受信图片 URL 的不可逆摘要，文件名只含白名单字符/扩展名；公共 API 不暴露原始 URL 或绝对路径。
3. 缓存默认 TTL 7 天并按成功访问续期；下载采用 10 秒总超时和 5 MiB 上限，临时文件校验成功后原子替换。
4. 清理采用有节流的机会式扫描，不引入后台 worker；只删除明确 cache root 内过期的普通缓存文件，拒绝符号链接和路径逃逸。
5. Request、history、队列、偏好和修正 JSON 不保存图片二进制、原始封面 URL或缓存绝对路径。

## 9. Stage 26 Web storage 根目录（已完成）

1. Web API 的 `storage_dir` 只能选择服务端根目录下的相对 profile（默认 `.migu_orca/storage`，可用 `MIGU_ORCA_WEB_STORAGE_ROOT` 覆盖）；绝对路径/穿越/符号链接逃逸返回 400 `invalid_storage_dir`。
2. `storage_dir` 未传/空值时回落服务端根本身（`services._storage_dir` 返回 `_WEB_STORAGE_ROOT`，绝不返回 `None`——返回 `None` 会让 `load_storage_config(None)` 回退 CLI 默认路径，绕过服务端 root 覆盖；US-196 回归修复）。
3. CLI `--storage-dir` 是独立信任边界，接受显式本地路径；Web 与 CLI 使用不同 storage 信任边界。

## 9.1 Stage 28 save-confirm 幂等记录（已完成）

1. `StorageConfig` 新增 `idempotency_dir`（`<storage>/idempotency`），由
   `ensure_storage_layout` 统一创建。新增存储族必须同步 `storage_config.py` +
   `storage_config_test.py`。
2. `storage_engine/controllers/idempotency_repository.py` 提供原子读写的 save-confirm 幂等
   repository：每条 = `<storage>/idempotency/<opaque-key>.json`，写用 temp 文件 + `os.replace`
   原子替换，读缺失返回 None、损坏/非对象返回稳定 `storage_json_error`；key 校验拒绝路径片段
   与穿越，文件名永不取自用户输入。
3. 记录只含白名单字段 `idempotency_key/operation/request_fingerprint/request_id/state/
   created_at/updated_at`；调用方即使误传 draft/标题/URL/凭据/路径也绝不落盘。
   `request_fingerprint` 是 `save_confirm_service.compute_request_fingerprint` 对业务字段
   规范化排序的 sha256，不可逆且排除 request_id 与敏感字段。
4. 状态机 `IN_PROGRESS → CONFIRMED | SAVED_CONFIRM_FAILED`：终态同键重放直接返回持久化公开
   结果；`IN_PROGRESS` 重试先核对已落盘 Request 再决定继续确认或安全重试保存；同一进程内按 key
   RLock 串行并发同键尝试。

## 8. 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| Q-M11-01 | 本地 JSON 存储目录放在哪里？ | 是 | Stage 6 已确认：默认项目下 `.migu_orca/storage`，可由 `--storage-dir` 覆盖 |
| Q-M11-02 | Request 状态历史是否单独存储？ | 是 | Stage 6 已确认：按 `request_id` 独立存储于 `history/` |
| Q-M11-03 | 用户修改历史需要记录哪些字段？ | 是 | 已确认：`user_action`、`previous_status`、`next_status` 等 |
| Q-M11-04 | 是否需要 Request 过期和清理策略？ | 否 | 第一版可手动清理；Stage 15 已提供显式删除入口 |
| Q-M11-05 | 是否需要迁移到 SQLite？ | 否 | 后续扩展 |
