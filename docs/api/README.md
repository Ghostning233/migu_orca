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
- 示例全部使用虚构脱敏值；`example.invalid` 是文档保留域。
- 凭据/外部配置字段（`mikan_config`、`ab_config`、`qbittorrent_config`、
  `candidate_context`、`storage_dir`）标记为 `x-request-scoped: true`：
  request-scoped，绝不进入 storage JSON、URL、浏览器 storage、日志或 trace。
- 海报二进制端点 `GET /api/v1/mikan/posters/{key}` 单独声明
  `image/jpeg|png|gif|webp` content type 与失败响应（函数视图，不经 JSON envelope）。
- `request_id`/`batch_id`/`draft_id`/`candidate_context` 生命周期见
  `endpoint_inventory.md` §5.4。

## Stage 27 使用方式

Stage 27 TypeScript 前端只通过本 OpenAPI/DTO 生成客户端类型，不导入旧
`app.js` 内部状态。生成后按 `docs/MiGuOrca_stage27_frontend_engineering_migration_PRD.md`
handoff 使用。
