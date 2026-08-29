# AGENTS.md — apps/migu_orca_web

Stage 26 US-191 将原先 2,000+ 行的 `views.py` 按职责拆分。新增/修改 Web API 代码时遵循以下约定。

## 模块职责（拆分后的布局）

- `blueprints.py`：定义 `api_blueprint` / `web_blueprint`（唯一 Blueprint 归属地，避免循环导入）。
- `schemas.py`：请求/查询 Pydantic 模型（`RequestCreatePayload` 等）。响应 DTO 在 `api_contract.py`。
- `serializers.py`：响应序列化与脱敏白名单（`_serialize_*`、`_sanitize_*`、`_strip_sensitive_result_fields`）。
- `services.py`：用例编排与存储 seam（`_storage_dir`、`_resolve_mikan_config`、`_search_*`、`_build_batch_*`），复用 engine/repository，不复制业务规则。
- `contexts.py`：短期候选选择上下文（`candidate_selection_contexts` / `CandidateSelectionContextStore`）。
- `routes_requests.py` / `routes_mikan.py` / `routes_batches.py` / `routes_settings.py` / `routes_connections.py`：按端点族注册 `/api/v1` 路由。
- `views.py`：仅保留 Jinja 页面路由 + 导入 route 模块（导入副作用即注册端点）+ 再导出 blueprints；同时为测试兼容再导出 `CandidateSelectionContextStore` / `candidate_selection_contexts`。
- `__init__.py` 的 `blueprints = [web_blueprint, api_blueprint]` 由 `apps/registry.py` 消费。

## 路由注册与测试 seam 的坑

- route 模块**导入即注册**：`views.py` 必须 import 所有 `routes_*` 模块，否则端点不注册（`tests/api_contract/test_inventory_consistency.py` 会失败）。
- monkeypatch 目标必须指向**符号实际被调用处的模块命名空间**，不是定义处：
  - 路由类里调用的 `generate_request`/`apply_request_save_action`/`delete_request_snapshot` → patch `apps.migu_orca_web.routes_requests.<sym>`。
  - `_search_batch_item_candidates`/`_batch_title_parsing_provider` 在 `routes_batches` 命名空间调用 → patch `apps.migu_orca_web.routes_batches.<sym>`；`_search_candidates_from_parse_result` 在 `routes_mikan` 调用。
  - `test_ab_connection`/`test_qbittorrent_connection` → patch `routes_connections.<sym>`；`save_user_preferences` → patch `routes_settings.<sym>`。
  - `mikan_client_module.create_mikan_client`/`candidate_search_cache` 在 `services` 命名空间使用 → patch `apps.migu_orca_web.services.<sym>`。
  - 上下文单例从 `apps.migu_orca_web.contexts` 导入（`views` 也再导出，两者指向同一对象）。
- 新增/删除 `/api/v1` 端点必须同步 4 处，否则 CI 失败：
  1. `docs/api/endpoint_inventory.md` §2 总表 + §5.1 前端依赖（若 app.js 使用）；
  2. `src/apps/migu_orca_web/openapi_gen.py` 的 `_ENDPOINTS` 注册表；
  3. 重新生成 `docs/api/openapi.json`（`uv run python -m apps.migu_orca_web.openapi_gen`）；
  4. `tests/api_contract/` 相关 golden/DTO 测试。
- 响应 DTO 全部 `extra="forbid"`；深层的 engine dict（request 快照、parse_result、queue item 等）在 DTO 内仍为 `dict[str, Any]`，脱敏由 serializer 白名单负责。

## HTTP 状态语义（US-192）

- **envelope 形状不变，状态码表达失败分类**：`extensions/flask_api/api.py:_error_http_status`
  是唯一分类来源（400/404/409/401/502/503/504/500），路由**不得**硬编码状态码。
- `openapi_gen.py` 的 `_ENDPOINTS` 注册表 `errors` 声明必须与 `_error_http_status` 分类一致；
  改分类或改注册表都要跑 `uv run python -m apps.migu_orca_web.openapi_gen` 重生成
  `docs/api/openapi.json`。
- 新增 `Stage1Error` error_type 时：若它属于已分类语义（not_found/conflict/timeout/
  auth/upstream），直接加入 `_error_http_status` 对应集合；未知 error_type 默认 400。
- 海报二进制端点 `GET /api/v1/mikan/posters/<key>`（函数视图）在 `routes_mikan.py` 里
  用 `try/except Stage1Error` + `failed_response(..., status=_error_http_status(...))`
  统一错误处理，成功仍返回图片字节。

## 安全边界

- 外部 endpoint、token、cookie、password、raw HTML/RSS、完整失败 URL、magnet、本地绝对路径不得进入 API 展示、storage、URL、browser storage、日志或 trace。
- 新增响应字段时走 `serializers.py` 的白名单/脱敏路径，不要直接回传 engine dict。
