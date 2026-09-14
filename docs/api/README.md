# MiGuOrca Web API 契约

本目录是 `/api/v1` 的机器可读契约（US-190 产物）：

| 文件 | 说明 |
| --- | --- |
| `openapi.json` | OpenAPI 3.1 文档，覆盖全部 `/api/v1` 端点，由确定性脚本生成。 |
| `endpoint_inventory.md` | US-189 冻结的端点清单、敏感值边界与前端依赖（人工可读基线；US-209 更新）。 |

## 生成与漂移检查

```bash
uv run migu-orca-openapi            # 等价：uv run python -m apps.migu_orca_web.openapi_gen
uv run migu-orca-openapi --check    # 漂移检查（CI 使用，非零退出表示文档过期）
```

- 生成是**确定性**的：同一代码重复生成字节一致，无时间戳/随机 id/机器路径。
- 新增/删除 `/api/v1` 端点必须同步 `docs/api/endpoint_inventory.md` §2 与
  `src/apps/migu_orca_web/openapi_gen.py` 的 `_ENDPOINTS` 注册表，否则
  `tests/api_contract/test_inventory_consistency.py` 与
  `tests/api_contract/test_openapi_generation.py` 失败。
- 每个 operation 在 `_ENDPOINTS` 里声明**显式可读的 `operationId`**（如
  `listRequests`、`submitBatchQueue`）；`tests/api_contract/test_openapi_runtime_consistency.py`
  核对 operationId 唯一、可读、跨重生成稳定，且 `_ENDPOINTS` 声明的每个
  error_type/status 与 `extensions/flask_api/api.py:_error_http_status` 的运行时分类一致。

## Stage 27 类型化客户端（US-198）

Stage 27 前端只通过 OpenAPI 生成 TypeScript 类型，不手写第二套响应 interface；Stage 28 在
同一契约基线上新增单番/批量 save-confirm、36 部边界与 Request safe-info 端点，均同步
OpenAPI/生成 client/endpoint inventory。Stage 29 在同一基线上新增统一追番族
`/api/v1/tracking/items` 列表/详情/revalidate/submit/retry/recover（US-223～US-226），
operationId 为 `listTrackingItems`/`getTrackingItemDetail`/`revalidateTrackingItem`/
`submitTrackingItem`/`retryTrackingItem`/`recoverTrackingItem`，全部严格 DTO
（`extra="forbid"`）与可读 operationId 同步 OpenAPI、endpoint inventory 和生成 client。

```bash
cd frontend
npm run api:generate    # openapi-typescript → src/api/generated/api.ts
npm run api:check       # 漂移检查：生成结果与入库文件不一致时非零退出
```

- 生成器是 `openapi-typescript@7.13.0`（锁定在 `frontend/package-lock.json`），
  输入是 `docs/api/openapi.json`，输出 `frontend/src/api/generated/api.ts`（入库）。
- `frontend/src/api/generated/` **只由契约生成**，不手工维护；迁移 feature 不得
  手写重复的 API response interface。
- `frontend/src/api/generated/contract-consumer.test.ts` 是最小编译级消费 fixture，
  覆盖草案确认、批量结果、追番详情/动作、capability、nullable 字段和错误 envelope；
  页面代码应复用这些 generated types，不复制 interface。
- CI：frontend job 先跑 `npm run api:check`；Python 套件的
  `test_openapi_runtime_consistency.py::test_frontend_generated_client_matches_openapi`
  也执行同一 drift check。

## 契约要点

- 成功信封：`{"ok": true, "result": {...}}`；失败信封：
  `{"ok": false, "error_type", "error_message", "error_data"}`。
- **HTTP 状态语义（US-192）**：envelope 形状不变，状态码按 `error_type` 分类：
  400 输入校验/客户端错误、404 资源不存在、409 状态冲突/重放/context 失效、
  401 外部认证失败、502 上游不可达、503 上游不可用/版本不支持、504 上游超时、
  500 服务端内部错误。`_ENDPOINTS` 注册表的 `errors` 声明与
  `extensions/flask_api/api.py:_error_http_status` 分类保持一致。
- 示例全部使用虚构脱敏值；`example.invalid` 是文档保留域。
- 凭据/外部配置字段（`mikan_config`、`ab_config`、
  `candidate_context`、`draft_id`）标记为 `x-request-scoped: true`：
  request-scoped，绝不进入 storage JSON、URL、浏览器 storage、日志或 trace。
  US-194/211/212：未保存草案由服务端权威持有，客户端只持有 opaque `draft_id` 与单调
  `draft_revision`，`preview-modify` 只接受 `draft_id` + `base_revision` + 允许 patch
  （CAS，冲突 → 409 `draft_revision_conflict`），`save-confirm` 以 `draft_id` +
  `base_revision` 预留草案、持久化成功后才消费（写盘失败释放预留可重试；
  正在保存 → 409 `draft_reserved`），不再接受客户端完整 Request。
- `storage_dir`（US-193 起）是服务端允许根目录下的**相对 profile**：拒绝绝对路径/
  穿越/符号链接逃逸（400 `invalid_storage_dir`），details 不回显原始路径；**未传时回落
  服务端根**（`services._storage_dir` 返回 `_WEB_STORAGE_ROOT`，默认 `.migu_orca/storage`，
  可用 `MIGU_ORCA_WEB_STORAGE_ROOT` 覆盖；绝不回退 CLI 默认路径——US-196 回归修复）。
- 海报二进制端点 `GET /api/v1/mikan/posters/{key}` 单独声明
  `image/jpeg|png|gif|webp` content type 与失败响应（函数视图，不经 JSON envelope；
  US-192 起失败返回 JSON envelope + 分类状态码）。
- `request_id`/`batch_id`/`draft_id`/`candidate_context` 生命周期见
  `endpoint_inventory.md` §5.3。

## Stage 27 使用方式

Stage 27 TypeScript 前端只通过本 OpenAPI/DTO 生成客户端类型，不手写第二套
响应 interface。旧 `app.js` 已在 US-209 随旧 Jinja 页面删除，生成客户端是
Web UI 唯一的前端类型来源。生成后按
`docs/MiGuOrca_stage27_frontend_engineering_migration_PRD.md` 使用。

Stage 27 US-198 已用锁定版本的真实生成器（openapi-typescript@7.13.0）完成
smoke test，校准了运行时错误状态声明、稳定 operationId 与各迁移 feature
实际读取的深层公开 DTO；业务组件不得手写接口来绕过生成类型。

## 健康/就绪探针（非 /api/v1 契约）

- `GET /healthz`：存活探针，只证明 Flask 进程在服务。
- `GET /readiness`（US-195）：就绪探针，服务端 Web storage 根目录可创建/可写才返回
  200 `{"ok": true, "result": "ok"}`；storage 不可用返回 503
  `{"ok": false, "result": "storage_unavailable"}`。两者都不访问真实外部系统。
- 这两个端点不属于 `/api/v1` OpenAPI 契约（见 `endpoint_inventory.md` §2 页面路由对照）。
