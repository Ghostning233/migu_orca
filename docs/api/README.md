# MiGuOrca Web API 契约

本目录是 `/api/v1` 的机器可读契约（US-190 产物）：

| 文件 | 说明 |
| --- | --- |
| `openapi.json` | OpenAPI 3.1 文档，覆盖全部 `/api/v1` 端点，由确定性脚本生成。 |
| `endpoint_inventory.md` | US-189 冻结的端点清单、敏感值边界与旧前端依赖（人工可读基线）。 |

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

## 契约要点

- 成功信封：`{"ok": true, "result": {...}}`；失败信封：
  `{"ok": false, "error_type", "error_message", "error_data"}`。
- **HTTP 状态语义（US-192）**：envelope 形状不变，状态码按 `error_type` 分类：
  400 输入校验/客户端错误、404 资源不存在、409 状态冲突/重放/context 失效、
  401 外部认证失败、502 上游不可达、503 上游不可用/版本不支持、504 上游超时、
  500 服务端内部错误。`_ENDPOINTS` 注册表的 `errors` 声明与
  `extensions/flask_api/api.py:_error_http_status` 分类保持一致。
- 示例全部使用虚构脱敏值；`example.invalid` 是文档保留域。
- 凭据/外部配置字段（`mikan_config`、`ab_config`、`qbittorrent_config`、
  `candidate_context`、`draft_id`）标记为 `x-request-scoped: true`：
  request-scoped，绝不进入 storage JSON、URL、浏览器 storage、日志或 trace。
  US-194：未保存草案由服务端权威持有，客户端只持有 opaque `draft_id`，
  `preview-modify`/`preview-save` 不再接受客户端完整 Request。
- `storage_dir`（US-193 起）是服务端允许根目录下的**相对 profile**：拒绝绝对路径/
  穿越/符号链接逃逸（400 `invalid_storage_dir`），details 不回显原始路径。
- 海报二进制端点 `GET /api/v1/mikan/posters/{key}` 单独声明
  `image/jpeg|png|gif|webp` content type 与失败响应（函数视图，不经 JSON envelope；
  US-192 起失败返回 JSON envelope + 分类状态码）。
- `request_id`/`batch_id`/`draft_id`/`candidate_context` 生命周期见
  `endpoint_inventory.md` §5.4。

## Stage 27 使用方式

Stage 27 TypeScript 前端只通过本 OpenAPI/DTO 生成客户端类型，不导入旧
`app.js` 内部状态。生成后按 `docs/MiGuOrca_stage27_frontend_engineering_migration_PRD.md`
handoff 使用。

## 健康/就绪探针（非 /api/v1 契约）

- `GET /healthz`：存活探针，只证明 Flask 进程在服务。
- `GET /readiness`（US-195）：就绪探针，服务端 Web storage 根目录可创建/可写才返回
  200 `{"ok": true, "result": "ok"}`；storage 不可用返回 503
  `{"ok": false, "result": "storage_unavailable"}`。两者都不访问真实外部系统。
- 这两个端点不属于 `/api/v1` OpenAPI 契约（见 `endpoint_inventory.md` §2 页面路由对照）。
